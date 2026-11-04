"""
The janitor refuses any tree a live process is standing in, locked or not.

Store id 0b1388ce-6aa2-41d6-8b1a-3e2169b12815. A hand-made, unlocked tree was removed while
two claim checks ran with it as their working directory. The janitor's only test for an
unlocked tree was the age of its newest file. A tree nobody writes to looks idle, however
busy the processes standing in it are. The process check existed, but only
`seat_is_alive` used it, and only for a tree locked with a seat name.

A process is identified by where it stands (its /proc/<pid>/cwd), never by a saved pid.

Seams driven for real: `reconcile_worktrees` and the /proc scan, against a real child
process whose working directory is inside a real directory. Faked: the worktree list, the
tree's age, and the drain.
"""

import os
import subprocess
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from cosa.agents.shared import worktree_reaper as wr

NOW = datetime( 2026, 10, 7, 18, 0, tzinfo=timezone.utc )


def _git_stub( argv, cwd=None, timeout=60 ):
    """Ensures: answers every git call with success and no output."""
    return SimpleNamespace( returncode=0, stdout="", stderr="" )


def _tree( tmp_path, name="cheech-sweep-check" ):
    """Ensures: returns a real directory under the project's worktree lane, with a subdirectory."""
    tree = tmp_path / ".claude" / "worktrees" / name
    ( tree / "src" ).mkdir( parents=True )
    return tree


def _reconcile( tmp_path, tree, **kw ):
    """
    Run the janitor over one unlocked tree that is old enough to sweep.

    Ensures:
        - returns ( result, drained_paths )
        - the drain is a spy that removes nothing
    """
    drained = []
    def drain( path, **k ):
        drained.append( path )
        return { "removed": False }
    rec = { "path": str( tree ), "is_main": False, "locked": False, "branch": "refs/heads/x" }
    out = wr.reconcile_worktrees(
        project_root=str( tmp_path ), run=_git_stub, now=NOW, list_fn=lambda: [ rec ],
        drain_fn=drain, age_fn=lambda p: 100.0, **kw )
    return out, drained


@pytest.fixture
def stand_in():
    """Ensures: yields a function that starts a child in a given directory; all are ended after."""
    started = []

    def start( cwd ):
        proc = subprocess.Popen( [ sys.executable, "-c", "import time; time.sleep(120)" ], cwd=str( cwd ) )
        started.append( proc )
        return proc

    yield start
    for proc in started:
        proc.kill(); proc.wait()


def _skipped_reasons( out ):
    return [ s[ "reason" ] for s in out[ "skipped" ] ]


def test_POSITIVE_CONTROL_an_idle_tree_with_nobody_inside_is_drained( tmp_path ):
    tree = _tree( tmp_path )
    out, drained = _reconcile( tmp_path, tree )
    assert drained == [ str( tree ) ]


def test_a_live_process_inside_a_subdirectory_blocks_the_sweep( tmp_path, stand_in ):
    tree = _tree( tmp_path )
    stand_in( tree / "src" )
    out, drained = _reconcile( tmp_path, tree )
    assert drained == [], "the janitor removed a tree with a live process standing in it"
    assert _skipped_reasons( out ) == [ "process_cwd_inside" ]


def test_a_live_process_at_the_tree_root_blocks_the_sweep( tmp_path, stand_in ):
    tree = _tree( tmp_path )
    stand_in( tree )
    out, drained = _reconcile( tmp_path, tree )
    assert drained == []
    assert _skipped_reasons( out ) == [ "process_cwd_inside" ]


def test_the_tree_is_swept_again_once_the_process_has_gone( tmp_path, stand_in ):
    tree = _tree( tmp_path )
    proc = stand_in( tree / "src" )
    proc.kill(); proc.wait()
    out, drained = _reconcile( tmp_path, tree )
    assert drained == [ str( tree ) ], "a process identified by cwd stops counting the moment it exits"


def test_a_process_in_a_sibling_whose_name_starts_the_same_does_not_block( tmp_path, stand_in ):
    tree    = _tree( tmp_path )
    sibling = _tree( tmp_path, name="cheech-sweep-check-two" )
    stand_in( sibling )
    out, drained = _reconcile( tmp_path, tree )
    assert drained == [ str( tree ) ], "a path-prefix match would have refused this tree for its neighbour's process"


def test_an_unreadable_proc_listing_refuses_the_sweep( tmp_path, monkeypatch ):
    tree      = _tree( tmp_path )
    real_list = os.listdir

    def listing( path="." ):
        if str( path ) == "/proc": raise OSError( "proc is not readable" )
        return real_list( path )

    monkeypatch.setattr( wr.os, "listdir", listing )
    out, drained = _reconcile( tmp_path, tree )
    assert drained == [], "when nobody can be proven absent, the tree stays"
    assert _skipped_reasons( out ) == [ "process_cwd_unknown" ]


def test_the_proc_scan_runs_once_per_poll_however_many_trees_there_are( tmp_path ):
    trees, drained, scans = [ _tree( tmp_path, name=f"tree-{n}" ) for n in range( 3 ) ], [], []

    def drain( path, **k ):
        drained.append( path )
        return { "removed": False }

    def cwds():
        scans.append( 1 )
        return { str( trees[ 1 ] / "src" ) }

    records = [ { "path": str( t ), "is_main": False, "locked": False, "branch": "refs/heads/x" } for t in trees ]
    out = wr.reconcile_worktrees( project_root=str( tmp_path ), run=_git_stub, now=NOW, list_fn=lambda: records,
                                  drain_fn=drain, age_fn=lambda p: 100.0, cwds_fn=cwds )

    assert len( scans ) == 1, "one /proc scan per poll, shared by every tree"
    assert drained == [ str( trees[ 0 ] ), str( trees[ 2 ] ) ]
    assert _skipped_reasons( out ) == [ "process_cwd_inside" ]
