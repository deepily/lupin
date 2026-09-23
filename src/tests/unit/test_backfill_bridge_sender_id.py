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

def test_git_ancestor_finds_a_real_repo( backfill, tmp_path ):
    repo = tmp_path / "lupin"
    ( repo / ".git" ).mkdir( parents=True )
    assert backfill.git_ancestor( repo ) == repo.resolve()


def test_git_ancestor_finds_the_repo_from_a_worktree_below_it( backfill, tmp_path ):
    """A seat's cwd is deep under the repo; the walk must reach the repo itself."""
    repo     = tmp_path / "lupin"
    worktree = repo / ".claude" / "worktrees" / "seat-cc-author-rio-1"
    ( repo / ".git" ).mkdir( parents=True )
    worktree.mkdir( parents=True )
    assert backfill.git_ancestor( worktree ) == repo.resolve()


def test_git_ancestor_accepts_a_gitlink_FILE_not_only_a_directory( backfill, tmp_path ):
    """A real worktree's `.git` is a FILE. Testing only for a directory would refuse it."""
    wt = tmp_path / "some-worktree"
    wt.mkdir()
    ( wt / ".git" ).write_text( "gitdir: /elsewhere/.git/worktrees/x\n" )
    assert backfill.git_ancestor( wt ) == wt.resolve()


def test_git_ancestor_returns_none_when_there_is_no_repo( backfill, tmp_path ):
    """
    The refusal signal. `tmp_path` has no `.git` anywhere above it inside the tmp root,
    and this is what separates "a repo was found" from "a name was returned".
    """
    bare = tmp_path / "not-a-repo"
    bare.mkdir()
    assert backfill.git_ancestor( bare ) is None


# ── classify(): what happens to one bridge, and why ──────────────────────────

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
