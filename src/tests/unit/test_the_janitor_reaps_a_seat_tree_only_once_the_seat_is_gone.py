"""
The janitor reaps a seat's tree only once that seat is provably gone.

Rick, 2026-09-14 (row 033538f6): seat trees used to be built NEXT TO the repo, where the
janitor never looks, and 227 of them piled up. They now live in the janitor's own lane,
`<main>/.claude/worktrees/seat-<name>`. That lane is swept once a tree is idle past the
threshold, and a LIVE seat can easily sit idle that long. So the provisioner locks the
tree with reason `lupin-seat:<tmux session>`, and the janitor sweeps a seat-locked tree
only when:

  · tmux positively reports the session absent, AND
  · no live process has its cwd inside the tree (Mr. Radio's second signal), AND
  · the tree is idle past the threshold.

Every uncertainty counts as ALIVE. If the drain does not remove the tree, the lock goes
back on with its original reason (Mr. Radio), because an unlocked survivor loses the
protection the next poll relies on.
"""

import os
from datetime import datetime, timezone
from types import SimpleNamespace

from cosa.agents.shared import worktree_reaper as wr


ROOT    = "/repo"
LANE    = "/repo/.claude/worktrees"
SEAT    = f"{LANE}/seat-cc-author-maria-1"
REASON  = "lupin-seat:cc-author-maria-1"
NOW     = datetime( 2026, 9, 14, 17, 0, tzinfo=timezone.utc )


class _Git:
    """Records every git argv; unlock/lock succeed unless told otherwise."""
    def __init__( self, unlock_rc=0, lock_rc=0 ):
        self.calls, self.unlock_rc, self.lock_rc = [], unlock_rc, lock_rc
    def __call__( self, argv, cwd=None, timeout=60 ):
        self.calls.append( argv )
        rc = 0
        if argv[ 1:3 ] == [ "worktree", "unlock" ]: rc = self.unlock_rc
        if argv[ 1:3 ] == [ "worktree", "lock" ]:   rc = self.lock_rc
        return SimpleNamespace( returncode=rc, stdout="", stderr="" if rc == 0 else "boom" )
    def verbs( self ):
        return [ " ".join( a[ 1:3 ] ) for a in self.calls ]


def _reconcile( rec, alive=False, age=10.0, removed=True, git=None ):
    git     = git or _Git()
    drained = []
    def drain( path, **kw ):
        drained.append( path )
        return { "removed": removed }
    out = wr.reconcile_worktrees(
        project_root=ROOT, run=git, now=NOW, list_fn=lambda: [ rec ],
        drain_fn=drain, age_fn=lambda p: age, seat_alive_fn=lambda name, path: alive )
    return out, drained, git


def _seat( reason=REASON ):
    return { "path": SEAT, "branch": None, "locked": True, "lock_reason": reason, "is_main": False }


# ---------------------------------------------------------------------------
# The verdict table
# ---------------------------------------------------------------------------
def test_a_live_seat_is_never_swept_however_idle():
    out, drained, _ = _reconcile( _seat(), alive=True, age=999.0 )
    assert drained == []
    assert out[ "skipped" ] == [ { "path": SEAT, "reason": "seat_alive" } ]


def test_a_gone_seat_still_waits_out_the_idle_threshold():
    out, drained, _ = _reconcile( _seat(), alive=False, age=0.5 )
    assert drained == []
    assert out[ "skipped" ][ 0 ][ "reason" ].startswith( "active_" )


def test_a_gone_and_idle_seat_is_unlocked_then_drained():
    out, drained, git = _reconcile( _seat(), alive=False, age=10.0 )
    assert drained == [ SEAT ]
    assert git.verbs() == [ "worktree unlock" ], "unlock must come before the drain, and nothing re-locks a removed tree"
    assert out[ "swept" ][ 0 ][ "path" ] == SEAT


def test_the_liveness_check_is_asked_about_the_seat_named_in_the_lock():
    asked = []
    wr.reconcile_worktrees( project_root=ROOT, run=_Git(), now=NOW, list_fn=lambda: [ _seat() ],
                            drain_fn=lambda p, **kw: { "removed": True }, age_fn=lambda p: 10.0,
                            seat_alive_fn=lambda name, path: asked.append( ( name, path ) ) or True )
    assert asked == [ ( "cc-author-maria-1", SEAT ) ]


def test_any_other_lock_is_still_a_hands_off_signal():
    out, drained, _ = _reconcile( _seat( reason="manual: maria building" ), alive=False, age=999.0 )
    assert drained == []
    assert out[ "skipped" ] == [ { "path": SEAT, "reason": "locked" } ]


def test_a_lock_with_no_reason_is_still_hands_off():
    out, drained, _ = _reconcile( _seat( reason=None ), alive=False, age=999.0 )
    assert drained == [] and out[ "skipped" ][ 0 ][ "reason" ] == "locked"


# ---------------------------------------------------------------------------
# Mr. Radio's two failure arms
# ---------------------------------------------------------------------------
def test_a_drain_that_does_not_remove_puts_the_lock_back_with_its_reason():
    out, drained, git = _reconcile( _seat(), alive=False, age=10.0, removed=False )
    assert drained == [ SEAT ]
    relock = [ a for a in git.calls if a[ 1:3 ] == [ "worktree", "lock" ] ]
    assert relock == [ [ "git", "worktree", "lock", "--reason", REASON, SEAT ] ]


def test_a_failed_relock_is_named_as_an_unprotected_tree():
    out, _, _ = _reconcile( _seat(), alive=False, age=10.0, removed=False, git=_Git( lock_rc=1 ) )
    assert any( "unprotected" in e for e in out[ "errors" ] )


def test_a_failed_unlock_drains_nothing():
    out, drained, _ = _reconcile( _seat(), alive=False, age=10.0, git=_Git( unlock_rc=1 ) )
    assert drained == []
    assert any( "unlock failed" in e for e in out[ "errors" ] )


# ---------------------------------------------------------------------------
# seat_is_alive fails closed
# ---------------------------------------------------------------------------
def test_alive_while_tmux_does_not_positively_say_absent( monkeypatch ):
    monkeypatch.setattr( wr, "_tmux_session_absent", lambda name: False )
    monkeypatch.setattr( wr, "_process_cwd_inside", lambda path: False )
    assert wr.seat_is_alive( "s", SEAT ) is True


def test_alive_while_a_process_stands_in_the_tree_even_with_tmux_gone( monkeypatch ):
    monkeypatch.setattr( wr, "_tmux_session_absent", lambda name: True )
    monkeypatch.setattr( wr, "_process_cwd_inside", lambda path: True )
    assert wr.seat_is_alive( "s", SEAT ) is True


def test_alive_when_proc_cannot_be_read( monkeypatch ):
    monkeypatch.setattr( wr, "_tmux_session_absent", lambda name: True )
    monkeypatch.setattr( wr, "_process_cwd_inside", lambda path: None )
    assert wr.seat_is_alive( "s", SEAT ) is True


def test_gone_only_when_both_signals_agree( monkeypatch ):
    monkeypatch.setattr( wr, "_tmux_session_absent", lambda name: True )
    monkeypatch.setattr( wr, "_process_cwd_inside", lambda path: False )
    assert wr.seat_is_alive( "s", SEAT ) is False


def test_tmux_missing_is_not_proof_of_absence( monkeypatch ):
    def no_tmux( *a, **kw ): raise FileNotFoundError( "tmux" )
    monkeypatch.setattr( wr.subprocess, "run", no_tmux )
    assert wr._tmux_session_absent( "s" ) is False


def test_tmux_absence_needs_the_absent_message_not_just_a_nonzero_exit( monkeypatch ):
    monkeypatch.setattr( wr.subprocess, "run",
                         lambda *a, **kw: SimpleNamespace( returncode=1, stderr="some other failure" ) )
    assert wr._tmux_session_absent( "s" ) is False
    monkeypatch.setattr( wr.subprocess, "run",
                         lambda *a, **kw: SimpleNamespace( returncode=1, stderr="can't find session: =s" ) )
    assert wr._tmux_session_absent( "s" ) is True


def test_a_process_cwd_inside_the_tree_is_found_through_a_real_proc_layout( tmp_path ):
    tree  = tmp_path / "seat"
    ( tree / "src" ).mkdir( parents=True )
    other = tmp_path / "elsewhere"
    other.mkdir()
    proc  = tmp_path / "proc"
    for pid, cwd in ( ( "100", other ), ( "200", tree / "src" ) ):
        ( proc / pid ).mkdir( parents=True )
        os.symlink( cwd, proc / pid / "cwd" )
    ( proc / "self" ).mkdir()                                  # non-numeric entries are ignored
    assert wr._process_cwd_inside( str( tree ), proc_root=str( proc ) ) is True
    os.unlink( proc / "200" / "cwd" )
    assert wr._process_cwd_inside( str( tree ), proc_root=str( proc ) ) is False
    assert wr._process_cwd_inside( str( tree ), proc_root=str( tmp_path / "no-proc" ) ) is None


def test_a_sibling_whose_name_starts_with_the_tree_is_not_inside( tmp_path ):
    """Path components, not string prefixes — util.py's detector learned this the hard way."""
    tree    = tmp_path / "seat-a"
    sibling = tmp_path / "seat-ab"
    tree.mkdir(); sibling.mkdir()
    ( tmp_path / "proc" / "1" ).mkdir( parents=True )
    os.symlink( sibling, tmp_path / "proc" / "1" / "cwd" )
    assert wr._process_cwd_inside( str( tree ), proc_root=str( tmp_path / "proc" ) ) is False


# ---------------------------------------------------------------------------
# list_worktrees reads the lock reason
# ---------------------------------------------------------------------------
def test_list_worktrees_carries_the_lock_reason():
    porcelain = ( f"worktree {ROOT}\nHEAD abc\nbranch refs/heads/main\n\n"
                  f"worktree {SEAT}\nHEAD abc\ndetached\nlocked {REASON}\n\n"
                  f"worktree {LANE}/bare-lock\nHEAD abc\ndetached\nlocked\n" )
    run  = lambda argv, cwd=None, timeout=60: SimpleNamespace( returncode=0, stdout=porcelain, stderr="" )
    recs = { r[ "path" ]: r for r in wr.list_worktrees( ROOT, run=run ) }
    assert recs[ ROOT ][ "lock_reason" ] is None and recs[ ROOT ][ "is_main" ]
    assert recs[ SEAT ][ "locked" ] and recs[ SEAT ][ "lock_reason" ] == REASON
    assert recs[ f"{LANE}/bare-lock" ][ "locked" ] and recs[ f"{LANE}/bare-lock" ][ "lock_reason" ] is None
