"""
A reaped seat takes its own worktree and merged branch with it (row 129cc96b, P3).

Measured by María 2026-09-18: dismiss_sessions left a reaped seat's tree AND its
`lupin-seat:` lock behind, so every seat's tree waited hours for the janitor. Teardown
now runs at the two doors a seat leaves by — the manager's reap and the seat's own
SessionEnd — and removes the tree only when:

  · it is a linked worktree locked `lupin-seat:<this seat>`
  · the seat is provably gone (tmux absent, nobody standing in the tree)
  · nothing is uncommitted, no ignored file is data
  · HEAD is already on the repo's current WIP branch

Anything else is KEPT and reported. It never auto-commits, never forces, never uses -D.
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from cosa.agents.shared import seat_teardown as st


SEAT   = "cc-author-rio-1"
GONE   = lambda name, path: False
ALIVE  = lambda name, path: True


# ---------------------------------------------------------------------------
# Real git
# ---------------------------------------------------------------------------
def _git( cwd, *args ):
    return subprocess.run( [ "git", *args ], cwd=cwd, capture_output=True, text=True, timeout=60 )


def _commit( cwd, name ):
    ( cwd / name ).write_text( f"{name}\n" )
    assert _git( cwd, "add", "-A" ).returncode == 0
    assert _git( cwd, "commit", "-q", "-m", f"add {name}" ).returncode == 0


@pytest.fixture
def repo( tmp_path ):
    root = tmp_path / "repo"
    root.mkdir()
    _git( root, "init", "-q", "-b", "wip-v9" )
    _git( root, "config", "user.email", "t@example.com" )
    _git( root, "config", "user.name", "T" )
    ( root / ".gitignore" ).write_text( "*.local\n" )
    _commit( root, "README.md" )
    return root


def _seat_tree( repo, seat=SEAT, lock=True ):
    """Provisioned the way provision-seat-worktree.sh does it: detached, then locked."""
    tree = repo / ".claude" / "worktrees" / f"seat-{seat}"
    assert _git( repo, "worktree", "add", "-q", "--detach", str( tree ), "HEAD" ).returncode == 0
    if lock:
        assert _git( repo, "worktree", "lock", "--reason", f"lupin-seat:{seat}", str( tree ) ).returncode == 0
    return tree


def _registered( repo, tree ):
    return str( tree ) in _git( repo, "worktree", "list", "--porcelain" ).stdout


def _has_branch( repo, branch ):
    return _git( repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}" ).returncode == 0


def test_a_clean_seat_that_never_branched_loses_its_tree_and_its_lock( repo ):
    tree = _seat_tree( repo )
    out  = st.retire_seat_worktree( str( tree ), SEAT, alive_fn=GONE, wait_seconds=0 )
    assert out[ "removed" ] is True and out[ "kept_reason" ] is None
    assert not tree.exists() and not _registered( repo, tree )
    assert out[ "branch_outcome" ] is None


def test_a_merged_seat_branch_is_deleted_with_dash_d( repo ):
    tree = _seat_tree( repo )
    _git( tree, "switch", "-q", "-c", "rio/fix" )
    _commit( tree, "fix.txt" )
    assert _git( repo, "merge", "-q", "--ff-only", "rio/fix" ).returncode == 0

    out = st.retire_seat_worktree( str( tree ), SEAT, alive_fn=GONE, wait_seconds=0 )

    assert out[ "removed" ] is True
    assert out[ "branch_outcome" ][ "deleted" ] is True
    assert not _has_branch( repo, "rio/fix" )


def test_the_cwd_may_be_anywhere_inside_the_tree( repo ):
    tree = _seat_tree( repo )
    ( tree / "deep" / "er" ).mkdir( parents=True )
    out = st.retire_seat_worktree( str( tree / "deep" / "er" ), SEAT, alive_fn=GONE, wait_seconds=0 )
    assert out[ "removed" ] is True and out[ "path" ] == str( tree )


def test_an_unmerged_seat_keeps_its_tree_its_branch_and_its_lock( repo ):
    tree = _seat_tree( repo )
    _git( tree, "switch", "-q", "-c", "rio/open" )
    _commit( tree, "open.txt" )

    out = st.retire_seat_worktree( str( tree ), SEAT, alive_fn=GONE, wait_seconds=0 )

    assert ( out[ "removed" ], out[ "kept_reason" ] ) == ( False, "unmerged" )
    assert out[ "branch_outcome" ][ "commits_ahead" ] == 1
    assert tree.exists() and _has_branch( repo, "rio/open" )
    assert f"locked lupin-seat:{SEAT}" in _git( repo, "worktree", "list", "--porcelain" ).stdout


def test_commits_on_a_detached_head_are_unmerged_too( repo ):
    tree = _seat_tree( repo )
    _commit( tree, "detached.txt" )
    out = st.retire_seat_worktree( str( tree ), SEAT, alive_fn=GONE, wait_seconds=0 )
    assert out[ "kept_reason" ] == "unmerged" and tree.exists()


def test_uncommitted_work_keeps_the_tree_and_is_never_auto_committed( repo ):
    tree = _seat_tree( repo )
    ( tree / "draft.txt" ).write_text( "not saved\n" )
    head = _git( tree, "rev-parse", "HEAD" ).stdout

    out = st.retire_seat_worktree( str( tree ), SEAT, alive_fn=GONE, wait_seconds=0 )

    assert out[ "kept_reason" ] == "uncommitted_work"
    assert ( tree / "draft.txt" ).read_text() == "not saved\n"
    assert _git( tree, "rev-parse", "HEAD" ).stdout == head, "teardown must not commit anything"


def test_an_ignored_data_file_keeps_the_tree( repo ):
    tree = _seat_tree( repo )
    ( tree / "notes.local" ).write_text( "mine\n" )
    out = st.retire_seat_worktree( str( tree ), SEAT, alive_fn=GONE, wait_seconds=0 )
    assert ( out[ "kept_reason" ], out[ "ignored_blockers" ] ) == ( "ignored_files_present", [ "notes.local" ] )
    assert ( tree / "notes.local" ).exists()


def test_a_live_seat_keeps_its_tree( repo ):
    tree = _seat_tree( repo )
    out  = st.retire_seat_worktree( str( tree ), SEAT, alive_fn=ALIVE, wait_seconds=0 )
    assert out[ "kept_reason" ] == "seat_alive" and tree.exists()


def test_another_seats_tree_is_never_touched( repo ):
    tree = _seat_tree( repo, seat="cc-author-maria-1" )
    out  = st.retire_seat_worktree( str( tree ), SEAT, alive_fn=GONE, wait_seconds=0 )
    assert out[ "kept_reason" ] == "not_this_seats_tree" and tree.exists()


def test_an_unlocked_tree_is_not_a_seat_tree( repo ):
    tree = _seat_tree( repo, lock=False )
    out  = st.retire_seat_worktree( str( tree ), SEAT, alive_fn=GONE, wait_seconds=0 )
    assert out[ "kept_reason" ] == "not_a_seat_tree" and tree.exists()


def test_the_main_checkout_is_never_a_seat_tree( repo ):
    assert st.retire_seat_worktree( str( repo ), SEAT, alive_fn=GONE, wait_seconds=0 )[ "kept_reason" ] == "main_worktree"


def test_the_seat_name_can_come_from_the_lock( repo ):
    tree = _seat_tree( repo )
    out  = st.retire_seat_worktree( str( tree ), None, alive_fn=GONE, wait_seconds=0 )
    assert out[ "removed" ] is True and out[ "seat" ] == SEAT


def test_a_detached_main_tree_keeps_everything( repo ):
    tree = _seat_tree( repo )
    _git( repo, "checkout", "-q", "--detach" )
    assert st.retire_seat_worktree( str( tree ), SEAT, alive_fn=GONE, wait_seconds=0 )[ "kept_reason" ] == "no_target_branch"


@pytest.mark.parametrize( "path, reason", [ ( None, "no_tree" ), ( "/no/such/dir", "no_tree" ) ] )
def test_no_tree_at_all( path, reason ):
    assert st.retire_seat_worktree( path, SEAT, alive_fn=GONE, wait_seconds=0 )[ "kept_reason" ] == reason


def test_a_plain_directory_is_not_a_worktree( tmp_path ):
    assert st.retire_seat_worktree( str( tmp_path ), SEAT, alive_fn=GONE, wait_seconds=0 )[ "kept_reason" ] == "not_a_worktree"


def test_the_default_liveness_check_is_the_janitors( repo ):
    """No tmux session by that name exists here, and no process stands in the tree."""
    tree = _seat_tree( repo, seat="cc-no-such-tmux-session-zz9" )
    out  = st.retire_seat_worktree( str( tree ), "cc-no-such-tmux-session-zz9", wait_seconds=0 )
    assert out[ "kept_reason" ] in ( None, "seat_alive" )      # tmux absent on this host ⇒ seat_alive


# ---------------------------------------------------------------------------
# The wait
# ---------------------------------------------------------------------------
def test_the_wait_polls_until_the_seat_is_gone():
    answers, sleeps, now = iter( [ True, True, False ] ), [], [ 0.0 ]
    def clock(): return now[ 0 ]
    def sleep( s ): sleeps.append( s ); now[ 0 ] += s
    assert st._wait_until_gone( SEAT, "/t", lambda n, p: next( answers ), 10, sleep, clock ) is True
    assert sleeps == [ st.POLL_SECONDS, st.POLL_SECONDS ]


def test_the_wait_gives_up_at_the_deadline():
    now = [ 0.0 ]
    def sleep( s ): now[ 0 ] += s
    assert st._wait_until_gone( SEAT, "/t", ALIVE, 1.0, sleep, lambda: now[ 0 ] ) is False
    assert now[ 0 ] == 1.0


# ---------------------------------------------------------------------------
# Scripted git — every failure keeps the tree
# ---------------------------------------------------------------------------
class _Git:
    def __init__( self, tree, main, fail=(), listing=None, branch=None, lock=f"lupin-seat:{SEAT}" ):
        self.tree, self.main, self.fail, self.calls = tree, main, set( fail ), []
        seat_branch  = f"branch refs/heads/{branch}" if branch else "detached"
        self.listing = listing if listing is not None else (
            f"worktree {main}\nHEAD a\nbranch refs/heads/wip-v9\n\n"
            f"worktree {tree}\nHEAD b\n{seat_branch}\nlocked {lock}\n" )
    def __call__( self, argv, cwd=None, timeout=60 ):
        self.calls.append( argv )
        key = " ".join( argv[ 1:3 ] )
        if key in self.fail:
            return SimpleNamespace( returncode=1 if key != "merge-base --is-ancestor" else 128, stdout="", stderr="boom" )
        if key == "worktree remove":      # the tree is gone from the registry from here on
            self.listing = self.listing.split( "\n\n" )[ 0 ] + "\n"
        out = { "rev-parse --show-toplevel"   : self.tree,
                "rev-parse --path-format=absolute": f"{self.main}/.git",
                "worktree list"               : self.listing,
                "rev-parse HEAD"              : "b" * 40 }.get( key, "" )
        return SimpleNamespace( returncode=0, stdout=out, stderr="" )


@pytest.fixture
def dirs( tmp_path ):
    main = tmp_path / "main"
    tree = main / ".claude" / "worktrees" / "seat"
    tree.mkdir( parents=True )
    return str( tree ), str( main )


@pytest.mark.parametrize( "fail, reason", [
    ( [ "rev-parse --show-toplevel" ],        "not_a_worktree" ),
    ( [ "rev-parse --path-format=absolute" ], "not_a_worktree" ),
    ( [ "status --porcelain" ],               "status_failed" ),
    ( [ "-c core.quotepath=off" ],            "ignored_check_failed" ),
    ( [ "merge-base --is-ancestor" ],         "merge_check_failed" ),
    ( [ "rev-parse HEAD" ],                   "merge_check_failed" ),
    ( [ "worktree unlock" ],                  "unlock_failed" ),
    ( [ "worktree remove" ],                  "remove_failed" ),
] )
def test_every_git_failure_keeps_the_tree( dirs, fail, reason ):
    tree, main = dirs
    git = _Git( tree, main, fail=fail )
    out = st.retire_seat_worktree( tree, SEAT, run=git, alive_fn=GONE, wait_seconds=0 )
    assert ( out[ "removed" ], out[ "kept_reason" ] ) == ( False, reason )


def test_a_failed_removal_puts_the_lock_back( dirs ):
    tree, main = dirs
    git = _Git( tree, main, fail=[ "worktree remove" ] )
    st.retire_seat_worktree( tree, SEAT, run=git, alive_fn=GONE, wait_seconds=0 )
    assert git.calls[ -1 ] == [ "git", "worktree", "lock", "--reason", f"lupin-seat:{SEAT}", tree ]


def test_a_failed_relock_is_named( dirs ):
    tree, main = dirs
    out = st.retire_seat_worktree( tree, SEAT, run=_Git( tree, main, fail=[ "worktree remove", "worktree lock" ] ),
                                   alive_fn=GONE, wait_seconds=0 )
    assert any( "unprotected" in e for e in out[ "errors" ] )


def test_an_unregistered_tree_is_kept( dirs ):
    tree, main = dirs
    git = _Git( tree, main, listing=f"worktree {main}\nHEAD a\nbranch refs/heads/wip-v9\n" )
    assert st.retire_seat_worktree( tree, SEAT, run=git, alive_fn=GONE, wait_seconds=0 )[ "kept_reason" ] == "not_registered"


def test_the_removal_never_forces_and_the_delete_is_dash_d( dirs ):
    tree, main = dirs
    git = _Git( tree, main, branch="rio/done" )
    out = st.retire_seat_worktree( tree, SEAT, run=git, alive_fn=GONE, wait_seconds=0 )
    assert out[ "removed" ] is True
    assert [ "git", "worktree", "remove", tree ] in git.calls
    assert [ "git", "branch", "-d", "rio/done" ] in git.calls
    assert not any( "--force" in a or "-D" in a for a in git.calls )


def test_the_default_runner_is_real_git( tmp_path ):
    assert st.retire_seat_worktree( str( tmp_path ), SEAT, alive_fn=GONE, wait_seconds=0, debug=True )[ "kept_reason" ] == "not_a_worktree"


def test_debug_prints_the_removal( dirs, capsys ):
    tree, main = dirs
    st.retire_seat_worktree( tree, SEAT, run=_Git( tree, main ), alive_fn=GONE, wait_seconds=0, debug=True )
    assert "[seat_teardown] removed" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The notice
# ---------------------------------------------------------------------------
def test_the_notice_is_quiet_when_nothing_was_kept_for_work():
    assert st.teardown_notice( {} ) is None
    assert st.teardown_notice( { "a": { "removed": True }, "b": { "removed": False, "kept_reason": "not_a_seat_tree" } } ) is None


def test_the_notice_names_every_tree_kept_for_work_and_every_raise():
    notice = st.teardown_notice( {
        "b": { "removed": False, "kept_reason": "unmerged", "path": "/t/b" },
        "a": "RuntimeError: git gone" } )
    assert notice.startswith( "SEAT TREE KEPT for 2 seat(s): a: teardown raised" )
    assert "b: unmerged at /t/b" in notice


# ---------------------------------------------------------------------------
# The CLI the SessionEnd waiter runs
# ---------------------------------------------------------------------------
def test_the_cli_prints_one_json_line( capsys ):
    seen = {}
    def retire( path, **kw ):
        seen.update( path=path, **kw )
        return { "removed": False, "kept_reason": "seat_alive" }
    assert st.main( [ "--path", "/t", "--wait-seconds", "3" ], retire_fn=retire ) == 0
    line = json.loads( capsys.readouterr().out )
    assert line[ "kept_reason" ] == "seat_alive" and "ts" in line
    assert seen == { "path": "/t", "seat_name": None, "wait_seconds": 3.0 }


def test_the_cli_defaults_to_the_real_teardown( capsys ):
    assert st.main( [ "--path", "/no/such/dir" ] ) == 0
    assert json.loads( capsys.readouterr().out )[ "kept_reason" ] == "no_tree"


# ---------------------------------------------------------------------------
# Door 1 — dismiss_sessions
# ---------------------------------------------------------------------------
import lupin_mcp.session_spawner as ss

_OK_RUNNER = lambda argv, env=None: SimpleNamespace( returncode=0 )
_NOOP      = { "emit_reap_fn": lambda i, reason="": None, "emit_reaped_fn": lambda i: None }


def _setup( tmp, cwd ):
    sd, mgr = Path( tmp ), "mgr-abc12345"
    ss._write_manifest( ss._manifest_path( mgr, sd ), [ { "session_name": SEAT, "session_id": "sid-1" } ] )
    ( sd / "cc-99999.json" ).write_text( json.dumps( {
        "tmux_session": SEAT, "stable_session_id": "abcd1234-aaaa", "cwd": cwd,
        "voice_persona": { "name": "Rio", "icon": "⚡" } } ) )
    return sd, mgr


def test_the_reap_tears_down_the_seat_it_killed_with_its_own_cwd():
    with tempfile.TemporaryDirectory() as tmp:
        sd, mgr = _setup( tmp, "/seats/rio" )
        seen = []
        res  = ss.dismiss_sessions( mgr, session_names=[ SEAT ], runner=_OK_RUNNER, session_dir=sd,
                                    seat_teardown_fn=lambda name, cwd: seen.append( ( name, cwd ) )
                                                                       or { "removed": True }, **_NOOP )
        assert seen == [ ( SEAT, "/seats/rio" ) ]
        assert res[ "seat_trees" ] == { SEAT: { "removed": True } }
        assert res[ "seat_tree_notice" ] is None


def test_a_kept_tree_is_named_at_the_top_of_the_reap():
    with tempfile.TemporaryDirectory() as tmp:
        sd, mgr = _setup( tmp, "/seats/rio" )
        res = ss.dismiss_sessions( mgr, session_names=[ SEAT ], runner=_OK_RUNNER, session_dir=sd,
                                   seat_teardown_fn=lambda n, c: { "removed": False, "kept_reason": "unmerged",
                                                                   "path": c }, **_NOOP )
        assert "unmerged at /seats/rio" in res[ "seat_tree_notice" ]


def test_a_raising_teardown_never_breaks_the_reap():
    with tempfile.TemporaryDirectory() as tmp:
        sd, mgr = _setup( tmp, "/seats/rio" )
        def boom( n, c ): raise RuntimeError( "git gone" )
        res = ss.dismiss_sessions( mgr, session_names=[ SEAT ], runner=_OK_RUNNER, session_dir=sd,
                                   seat_teardown_fn=boom, **_NOOP )
        assert res[ "dismissed" ][ 0 ][ "status" ] == "killed"
        assert res[ "seat_trees" ][ SEAT ] == "RuntimeError: git gone"


def test_a_withheld_seat_is_never_torn_down():
    with tempfile.TemporaryDirectory() as tmp:
        sd, mgr = _setup( tmp, "/seats/rio" )
        seen = []
        res  = ss.dismiss_sessions( mgr, session_names=[ SEAT ], runner=_OK_RUNNER, session_dir=sd,
                                    memento_coord_fn=lambda ids: { n: { "status": "timeout_no_memento" } for n in ids },
                                    seat_teardown_fn=lambda n, c: seen.append( n ), **_NOOP )
        assert res[ "dismissed" ][ 0 ][ "status" ] == "withheld_no_memento"
        assert seen == []


def test_no_teardown_seam_means_no_teardown():
    with tempfile.TemporaryDirectory() as tmp:
        sd, mgr = _setup( tmp, "/seats/rio" )
        res = ss.dismiss_sessions( mgr, session_names=[ SEAT ], runner=_OK_RUNNER, session_dir=sd, **_NOOP )
        assert res[ "seat_trees" ] == {} and res[ "seat_tree_notice" ] is None


def test_a_real_reap_removes_a_real_seat_tree( repo ):
    """End to end: the real teardown, driven through the real dismiss_sessions."""
    tree = _seat_tree( repo )
    with tempfile.TemporaryDirectory() as tmp:
        sd, mgr = _setup( tmp, str( tree ) )
        res = ss.dismiss_sessions( mgr, session_names=[ SEAT ], runner=_OK_RUNNER, session_dir=sd,
                                   seat_teardown_fn=lambda n, c: st.retire_seat_worktree( c, n, alive_fn=GONE,
                                                                                          wait_seconds=0 ),
                                   **_NOOP )
    assert res[ "seat_trees" ][ SEAT ][ "removed" ] is True
    assert not tree.exists() and not _registered( repo, tree )


# ---------------------------------------------------------------------------
# Door 2 — the SessionEnd hook
# ---------------------------------------------------------------------------
import lupin_cli.claude_code.hooks.session_end as session_end


LANE = os.path.join( os.sep, "r", ".claude", "worktrees", "seat-x" )


@pytest.mark.parametrize( "payload, has_root", [
    ( { "reason": "clear",   "cwd": LANE }, True ),
    ( { "reason": "compact", "cwd": LANE }, True ),
    ( { "reason": "logout",  "cwd": "/r/src" }, True ),
    ( { "reason": "logout",  "cwd": LANE }, False ),
] )
def test_the_hook_starts_nothing_unless_a_seat_is_really_leaving( tmp_path, payload, has_root ):
    """
    The root is a WRITABLE tmp dir on purpose. With an unwritable one the launch fails on
    makedirs and returns None anyway, so a removed guard survived (mutation arms
    P3-hook-skips-clear and P3-hook-lane-filter, 2026-09-18).
    """
    popen = MagicMock()
    root  = str( tmp_path ) if has_root else ""
    assert session_end._schedule_seat_teardown( payload, popen_fn=popen, lupin_root=root ) is None
    popen.assert_not_called()


def test_the_hook_starts_a_detached_waiter_outside_the_tree( tmp_path ):
    popen = MagicMock( return_value="handle" )
    out   = session_end._schedule_seat_teardown( { "reason": "logout", "cwd": LANE }, popen_fn=popen,
                                                 lupin_root=str( tmp_path ) )
    argv, kw = popen.call_args
    assert out == "handle"
    assert argv[ 0 ][ 1: ] == [ "-m", "cosa.agents.shared.seat_teardown", "--path", LANE, "--wait-seconds", "120" ]
    assert kw[ "cwd" ] == "/" and kw[ "start_new_session" ] is True
    assert kw[ "env" ][ "PYTHONPATH" ] == str( tmp_path / "src" )
    assert ( tmp_path / "io" / "worktree-janitor" / "seat-teardown.jsonl" ).exists()


def test_the_hook_falls_back_to_its_own_cwd( tmp_path, monkeypatch ):
    lane = tmp_path / ".claude" / "worktrees" / "seat-y"
    lane.mkdir( parents=True )
    monkeypatch.chdir( lane )
    popen = MagicMock()
    session_end._schedule_seat_teardown( { "reason": "logout" }, popen_fn=popen, lupin_root=str( tmp_path ) )
    assert popen.call_args[ 0 ][ 0 ][ 4 ] == os.path.realpath( lane )


def test_a_failed_launch_is_reported_never_raised( tmp_path, capsys ):
    def boom( *a, **k ): raise OSError( "no fork" )
    assert session_end._schedule_seat_teardown( { "reason": "logout", "cwd": LANE }, popen_fn=boom,
                                                lupin_root=str( tmp_path ) ) is None
    assert "seat teardown launch failed" in capsys.readouterr().err


def test_the_hook_defaults_to_the_environment( monkeypatch ):
    monkeypatch.delenv( "LUPIN_ROOT", raising=False )
    assert session_end._schedule_seat_teardown( { "reason": "logout", "cwd": LANE } ) is None


def test_main_runs_the_seat_teardown_phase( monkeypatch ):
    payload = { "session_id": "", "reason": "logout", "cwd": LANE }
    monkeypatch.setattr( session_end, "read_hook_input", lambda: payload )
    monkeypatch.setattr( session_end, "log_payload", MagicMock() )
    monkeypatch.setattr( session_end, "emit_json", MagicMock() )
    schedule = MagicMock()
    monkeypatch.setattr( session_end, "_schedule_seat_teardown", schedule )
    session_end.main()
    schedule.assert_called_once_with( payload )
