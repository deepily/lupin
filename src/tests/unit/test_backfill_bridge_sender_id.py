#!/usr/bin/env python3
"""
Clause 3 of the sender_id backfill, exercised — row 2184bebb.

🔴 WHY THESE TESTS AND NOT A LIVE RUN. The script's own dry run on this box reported
8 eligible, 1 skipped_dead, and ZERO for both refusal outcomes. That run therefore
demonstrates nothing about the clause that matters: every bridge on this host happens
to have a live cwd under a real repo. A guard that has never been watched refusing is
indistinguishable from a guard that cannot refuse, and the script's own docstring says
so — "a run that writes many and skips none on a box with deleted worktrees would mean
clause 3 is not firing." These tests construct the conditions the box does not supply.

THE DEFECT CLAUSE 3 EXISTS TO PREVENT, measured 2026-09-22 against the real function:

    detect_project_for_path( "/no/such/place/at/all/seat-x" )  ->  "seat-x"

`detect_project_for_path` FALLS BACK TO THE BASENAME for a path it cannot resolve, and
never raises. That fallback is the original defect's mechanism — it is how the
container produced `@seat-cc-author-<name>`. A backfill that trusted the return value
would write that manufactured identity INTO the bridge, where the server is now
contractually forbidden from questioning it: the bug, laundered from a recomputed
(and therefore fixable) error into a durable, authoritative one.

So the tests below are not about tidy input validation. `test_the_trap_*` is the file's
reason for existing.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

MODULE = "scripts.backfill_bridge_sender_id"
SCRIPTS_DIR = Path( __file__ ).resolve().parents[ 2 ] / "scripts"


@pytest.fixture( scope="module" )
def backfill():
    """Import the script by path — `src/scripts/` is not a package on sys.path."""
    if str( SCRIPTS_DIR ) not in sys.path:
        sys.path.insert( 0, str( SCRIPTS_DIR ) )
    return importlib.import_module( "backfill_bridge_sender_id" )


# ── clause 3(ii): the .git-ancestor corroboration ────────────────────────────

# ⚠️ FOUR `git_ancestor` TESTS WERE DELETED HERE, WITH THE FUNCTION THEY TESTED
# (row 1ca233ae, 2026-09-26). `git_ancestor` was a LOCAL copy of the sender_id walk,
# kept only because `detect_project_for_path` could not refuse and so needed a second
# opinion. `resolve_project_for_path` refuses, so clause 3(ii) is now that one call and
# the copy is gone. This is not a coverage loss: the walk itself is tested at its real
# home in test_sender_id.py, and deleting a duplicate implementation removes the
# divergence those four tests could never have caught — they asserted that the COPY
# behaved, never that it still matched the original.

def test_an_existing_sender_id_is_never_overwritten( backfill ):
    """It came from that session's own SessionStart, on the host. It is authoritative."""
    outcome, sid = backfill.classify( {
        "sender_id": "claude.code@lupin.deepily.ai#abcd1234",
        "cwd"      : "/anything",
    } )
    assert outcome == "already_has_one"
    assert sid is None


def test_a_bridge_with_no_cwd_is_skipped( backfill ):
    for bridge in ( { }, { "cwd": "" }, { "cwd": 5 }, { "cwd": None } ):
        outcome, sid = backfill.classify( bridge )
        assert outcome == "skipped_no_cwd", bridge
        assert sid is None


def test_clause_3i_a_vanished_cwd_is_skipped( backfill, tmp_path ):
    """
    CLAUSE 3(i). The recorded directory is gone — a reaped worktree, the ordinary case.
    """
    gone = tmp_path / "lupin" / ".claude" / "worktrees" / "seat-REAPED"
    outcome, sid = backfill.classify( {
        "cwd": str( gone ), "stable_session_id": "abcd1234-x",
    } )
    assert outcome == "skipped_cwd_missing"
    assert sid is None


def test_clause_3ii_an_existing_dir_with_no_repo_above_it_is_skipped( backfill, tmp_path ):
    """
    CLAUSE 3(ii), and it is NOT a restatement of 3(i): this directory EXISTS. It simply
    has no `.git` ancestor, so there is no honest project name to be had — and
    `detect_project_for_path` would cheerfully return its basename anyway.
    """
    real_but_repoless = tmp_path / "scratch-dir"
    real_but_repoless.mkdir()
    outcome, sid = backfill.classify( {
        "cwd": str( real_but_repoless ), "stable_session_id": "abcd1234-x",
    } )
    assert outcome == "skipped_no_git_ancestor"
    assert sid is None


def test_the_trap_a_refused_bridge_never_yields_a_basename_identity( backfill, tmp_path ):
    """
    🔴 THE REASON THIS FILE EXISTS.

    Both refusal paths are checked for the one outcome that would matter: that neither
    hands back an id built from the directory's own name. The directory here is called
    `seat-x` precisely because `detect_project_for_path( ".../seat-x" )` returns
    `"seat-x"` — measured. If clause 3 were dropped, this test would find
    `claude.code@seat-x.deepily.ai#abcd1234` in the second slot and fail on it.
    """
    vanished = tmp_path / "gone" / "seat-x"
    present  = tmp_path / "seat-x"
    present.mkdir()

    for cwd in ( vanished, present ):
        outcome, sid = backfill.classify( {
            "cwd": str( cwd ), "stable_session_id": "abcd1234-x",
        } )
        assert sid is None, f"{ cwd } produced an id: { sid }"
        assert outcome.startswith( "skipped_" ), f"{ cwd } -> { outcome }"
        assert "seat-x" not in str( sid )


def test_an_eligible_bridge_resolves_to_the_repo_not_the_worktree( backfill, tmp_path ):
    """
    The positive case, and the row-6597cea9 requirement: a worktree seat takes the MAIN
    repo's project. Without a passing case here the refusals above would be satisfied by
    a classify() that refuses everything.
    """
    repo     = tmp_path / "lupin"
    worktree = repo / ".claude" / "worktrees" / "seat-cc-author-rio-1"
    ( repo / ".git" ).mkdir( parents=True )
    worktree.mkdir( parents=True )

    outcome, sid = backfill.classify( {
        "cwd": str( worktree ), "stable_session_id": "abcd1234-wt",
    } )
    assert outcome == "eligible"
    assert sid == "claude.code@lupin.deepily.ai#abcd1234"
    assert "seat-cc-author-rio-1" not in sid


def test_an_eligible_bridge_prefers_the_stable_session_id( backfill, tmp_path ):
    """
    The id must survive a /clear, as the hook's own does — otherwise a cleared session
    is backfilled under a suffix its own notifications no longer use.
    """
    repo = tmp_path / "lupin"
    ( repo / ".git" ).mkdir( parents=True )

    outcome, sid = backfill.classify( {
        "cwd"               : str( repo ),
        "session_id"        : "99999999-transient",
        "stable_session_id" : "abcd1234-stable",
    } )
    assert outcome == "eligible"
    assert sid == "claude.code@lupin.deepily.ai#abcd1234"


def test_an_eligible_bridge_with_no_session_id_writes_nothing( backfill, tmp_path ):
    """No id to suffix with means nothing honest to write."""
    repo = tmp_path / "lupin"
    ( repo / ".git" ).mkdir( parents=True )
    outcome, sid = backfill.classify( { "cwd": str( repo ) } )
    assert sid is None
    assert outcome.startswith( "skipped_" )


# ── classify: the last two guards, and main() (row e1a36bb4, coverage to 100%) ──

def test_a_sender_id_the_builder_rejects_is_refused_not_raised( backfill, tmp_path, monkeypatch ):
    repo = tmp_path / "lupin"
    ( repo / ".git" ).mkdir( parents=True )

    def _boom( *a, **k ): raise ValueError( "bad suffix" )
    monkeypatch.setattr( backfill, "build_sender_id", _boom )

    assert backfill.classify( { "cwd": str( repo ), "session_id": "abcd1234" } ) == ( "skipped_no_git_ancestor", None )


def test_an_import_failure_exits_3_naming_the_remedy( capsys ):
    """A missing dependency at import time exits 3 rather than half-importing."""
    import builtins
    real_import = builtins.__import__

    def _no_cosa( name, *a, **k ):
        if name.startswith( "cosa.agents.utils" ): raise ImportError( "simulated absence" )
        return real_import( name, *a, **k )

    spec = importlib.util.spec_from_file_location( "backfill_import_probe", SCRIPTS_DIR / "backfill_bridge_sender_id.py" )
    mod  = importlib.util.module_from_spec( spec )
    builtins.__import__ = _no_cosa
    try:
        with pytest.raises( SystemExit ) as caught:
            spec.loader.exec_module( mod )
    finally:
        builtins.__import__ = real_import
    assert caught.value.code == 3
    assert "FATAL: import failed" in capsys.readouterr().err


@pytest.fixture
def sessions( backfill, tmp_path, monkeypatch ):
    """A real sessions dir read through the script's seam, with a helper to add bridges."""
    sdir = tmp_path / "sessions"
    sdir.mkdir()
    monkeypatch.setattr( backfill, "sessions_dir", lambda: str( sdir ) )

    def put( name, data ):
        p = sdir / f"cc-{name}.json"
        p.write_text( data if isinstance( data, str ) else json.dumps( data ) )
        return p
    put.dir = sdir
    return put


def _run( backfill, monkeypatch, capsys, *argv ):
    monkeypatch.setattr( sys, "argv", [ "backfill_bridge_sender_id.py", *argv ] )
    rc = backfill.main()
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _live_repo( tmp_path ):
    repo = tmp_path / "lupin"
    ( repo / ".git" ).mkdir( parents=True )
    return repo


def test_dry_run_and_write_together_are_refused_with_exit_2( backfill, monkeypatch, capsys, sessions ):
    rc, _out, err = _run( backfill, monkeypatch, capsys, "--dry-run", "--write" )
    assert rc == 2
    assert "contradict each other" in err


def test_an_unreadable_sessions_directory_is_exit_2( backfill, monkeypatch, capsys ):
    def _boom(): raise OSError( "no such dir" )
    monkeypatch.setattr( backfill, "sessions_dir", _boom )
    rc, _out, err = _run( backfill, monkeypatch, capsys )
    assert rc == 2
    assert "could not read the sessions directory" in err


def test_report_only_names_the_eligible_bridge_and_writes_nothing( backfill, monkeypatch, capsys, sessions, tmp_path ):
    repo = _live_repo( tmp_path )
    path = sessions( "a", { "cwd": str( repo ), "stable_session_id": "abcd1234-z" } )
    before = path.read_text()

    rc, out, _err = _run( backfill, monkeypatch, capsys )

    assert rc == 0
    assert "bridges found: 1" in out and "REPORT ONLY" in out
    assert "WOULD WRITE             cc-a.json -> claude.code@lupin.deepily.ai#abcd1234" in out
    assert "eligible_not_written     1" in out
    assert path.read_text() == before, "report-only mode modified a bridge"


def test_write_mode_adds_the_sender_id_to_the_bridge_on_disk( backfill, monkeypatch, capsys, sessions, tmp_path ):
    repo = _live_repo( tmp_path )
    path = sessions( "a", { "cwd": str( repo ), "stable_session_id": "abcd1234-z", "keep": "me" } )

    rc, out, _err = _run( backfill, monkeypatch, capsys, "--write" )

    assert rc == 0 and "mode         : WRITE" in out
    assert "written                 cc-a.json" in out
    on_disk = json.loads( path.read_text() )
    assert on_disk[ "sender_id" ] == "claude.code@lupin.deepily.ai#abcd1234"
    assert on_disk[ "keep" ] == "me", "the backfill dropped the bridge's other fields"
    assert "written                  1" in out


def test_a_failed_atomic_write_is_counted_unreadable_and_named( backfill, monkeypatch, capsys, sessions, tmp_path ):
    repo = _live_repo( tmp_path )
    path = sessions( "a", { "cwd": str( repo ), "stable_session_id": "abcd1234-z" } )
    before = path.read_text()
    monkeypatch.setattr( backfill, "atomic_write_json", lambda p, d: False )

    rc, out, _err = _run( backfill, monkeypatch, capsys, "--write" )

    assert rc == 0
    assert "WRITE FAILED            cc-a.json" in out
    assert "unreadable               1" in out and "written                  0" in out
    assert path.read_text() == before


def test_unreadable_bridges_are_counted_and_named_only_under_verbose( backfill, monkeypatch, capsys, sessions ):
    sessions( "garbled", "{ not json" )
    sessions( "list", "[1, 2]" )                           # valid JSON, not an object

    _rc, quiet, _ = _run( backfill, monkeypatch, capsys )
    _rc, loud,  _ = _run( backfill, monkeypatch, capsys, "-v" )

    assert "unreadable               2" in quiet and "unreadable              cc-" not in quiet
    assert "unreadable              cc-garbled.json" in loud
    assert "unreadable              cc-list.json: ValueError" in loud


def test_a_dead_pid_is_skipped_unless_include_dead_is_passed( backfill, monkeypatch, capsys, sessions, tmp_path ):
    repo = _live_repo( tmp_path )
    sessions( "dead", { "cwd": str( repo ), "stable_session_id": "abcd1234-z", "cc_pid": 123 } )
    monkeypatch.setattr( backfill, "_is_pid_alive", lambda pid: False )

    _rc, skipped, _ = _run( backfill, monkeypatch, capsys, "-v" )
    _rc, included, _ = _run( backfill, monkeypatch, capsys, "--include-dead" )

    assert "skipped_dead            cc-dead.json (pid 123)" in skipped
    assert "skipped_dead             1" in skipped and "WOULD WRITE" not in skipped
    assert "WOULD WRITE             cc-dead.json" in included


def test_each_refusal_outcome_is_counted_and_verbose_names_the_bridge( backfill, monkeypatch, capsys, sessions, tmp_path ):
    sessions( "has", { "sender_id": "claude.code@x#1" } )
    sessions( "nocwd", { } )
    sessions( "gone", { "cwd": str( tmp_path / "vanished" ) } )
    bare = tmp_path / "bare"; bare.mkdir()
    sessions( "nogit", { "cwd": str( bare ) } )

    _rc, out, _ = _run( backfill, monkeypatch, capsys, "-v" )

    for outcome, name in ( ( "already_has_one", "has" ), ( "skipped_no_cwd", "nocwd" ),
                           ( "skipped_cwd_missing", "gone" ), ( "skipped_no_git_ancestor", "nogit" ) ):
        assert f"{outcome.ljust( 23 )} cc-{name}.json" in out
        assert f"{outcome.ljust( 24 )} 1" in out
