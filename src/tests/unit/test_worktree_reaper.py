"""
Tests for cosa.agents.shared.worktree_reaper.drain_then_remove.

Two tiers:
  * INJECTED-RUNNER tests — fast, prove control flow + the no-push / no-branch-
    delete invariants by spying on the argv stream.
  * REAL-GIT tests — create an actual temp repo + worktree and run real git, so
    the git invocations themselves are proven correct (a mock can't catch a wrong
    `git worktree remove` arg; a real repo can).

Run: pytest src/tests/unit/test_worktree_reaper.py -v
"""

import os
import subprocess
import time
from types import SimpleNamespace

import pytest

from cosa.agents.shared.worktree_reaper import (
    drain_then_remove,
    list_worktrees,
    reconcile_worktrees,
    WIP_COMMIT_PREFIX,
    RESCUE_BRANCH_PREFIX,
)


# ----------------------------------------------------------------------------
# Injected-runner tests (fast; invariant-focused)
# ----------------------------------------------------------------------------

def test_path_absent_is_a_noop_skip():
    r = drain_then_remove( "/tmp/nope-not-here-zzz", project_root="/tmp" )
    assert r[ "removed" ] is False
    assert r[ "skipped_reason" ] == "path_absent"
    assert r[ "errors" ] == []


def test_clean_worktree_removes_without_wip_commit():
    calls = []
    def run( argv, cwd=None, timeout=60 ):
        calls.append( argv )
        sub = argv[ 1 ] if len( argv ) > 1 else ""
        if sub == "rev-parse" and "--abbrev-ref" in argv:
            return SimpleNamespace( returncode=0, stdout="wt-feature\n", stderr="" )
        if sub == "status":
            return SimpleNamespace( returncode=0, stdout="", stderr="" )
        return SimpleNamespace( returncode=0, stdout="", stderr="" )

    r = drain_then_remove( "/tmp", project_root="/tmp", run=run )
    assert r[ "removed" ] is True
    assert r[ "wip_committed" ] is False
    assert r[ "branch" ] == "wt-feature"


def test_never_pushes_and_never_deletes_a_branch():
    calls = []
    def run( argv, cwd=None, timeout=60 ):
        calls.append( argv )
        sub = argv[ 1 ] if len( argv ) > 1 else ""
        if sub == "rev-parse" and "--abbrev-ref" in argv:
            return SimpleNamespace( returncode=0, stdout="wt-feature\n", stderr="" )
        if sub == "status":
            return SimpleNamespace( returncode=0, stdout=" M a.py\n", stderr="" )
        if sub == "rev-parse":
            return SimpleNamespace( returncode=0, stdout="deadbeef\n", stderr="" )
        return SimpleNamespace( returncode=0, stdout="", stderr="" )

    drain_then_remove( "/tmp", project_root="/tmp", run=run )
    assert not any( "push" in a for a in calls ), "drain_then_remove must NEVER push"
    assert not any(
        ( "branch" in a and ( "-d" in a or "-D" in a ) ) for a in calls
    ), "drain_then_remove must NEVER delete a branch"


def test_commits_wip_before_removing_dir():
    calls = []
    def run( argv, cwd=None, timeout=60 ):
        calls.append( argv )
        sub = argv[ 1 ] if len( argv ) > 1 else ""
        if sub == "rev-parse" and "--abbrev-ref" in argv:
            return SimpleNamespace( returncode=0, stdout="wt-feature\n", stderr="" )
        if sub == "status":
            return SimpleNamespace( returncode=0, stdout=" M a.py\n", stderr="" )
        if sub == "rev-parse":
            return SimpleNamespace( returncode=0, stdout="abc1234\n", stderr="" )
        return SimpleNamespace( returncode=0, stdout="", stderr="" )

    r = drain_then_remove( "/tmp", project_root="/tmp", run=run )
    subs = [ a[ 1 ] for a in calls ]
    assert subs.index( "commit" ) < subs.index( "worktree" ), "WIP commit must precede removal"
    assert r[ "wip_committed" ] is True
    assert r[ "wip_sha" ] == "abc1234"


def test_wip_commit_failure_refuses_removal():
    def run( argv, cwd=None, timeout=60 ):
        sub = argv[ 1 ] if len( argv ) > 1 else ""
        if sub == "rev-parse" and "--abbrev-ref" in argv:
            return SimpleNamespace( returncode=0, stdout="wt-feature\n", stderr="" )
        if sub == "status":
            return SimpleNamespace( returncode=0, stdout=" M a.py\n", stderr="" )
        if sub == "commit":
            return SimpleNamespace( returncode=1, stdout="", stderr="commit failed" )
        return SimpleNamespace( returncode=0, stdout="", stderr="" )

    r = drain_then_remove( "/tmp", project_root="/tmp", run=run )
    assert r[ "removed" ] is False
    assert r[ "skipped_reason" ] == "wip_commit_failed"


def test_broken_orphan_is_refused_not_rm():
    def run( argv, cwd=None, timeout=60 ):
        # rev-parse HEAD fails => not a working worktree (admin gitdir gone)
        return SimpleNamespace( returncode=128, stdout="", stderr="not a git repository" )

    r = drain_then_remove( "/tmp", project_root="/tmp", run=run )
    assert r[ "removed" ] is False
    assert r[ "skipped_reason" ] == "broken_or_not_a_worktree"


# ----------------------------------------------------------------------------
# Real-git tests (prove the actual git invocations)
# ----------------------------------------------------------------------------

def _git( cwd, *args ):
    return subprocess.run(
        [ "git", *args ], cwd=cwd, capture_output=True, text=True, timeout=60,
    )


@pytest.fixture
def repo( tmp_path ):
    """A real git repo with one commit on `main`, configured for commits."""
    root = tmp_path / "repo"
    root.mkdir()
    _git( root, "init", "-q", "-b", "main" )
    _git( root, "config", "user.email", "test@example.com" )
    _git( root, "config", "user.name", "Test" )
    ( root / "README.md" ).write_text( "seed\n" )
    _git( root, "add", "-A" )
    _git( root, "commit", "-q", "-m", "seed" )
    return root


def _add_worktree( root, name, branch ):
    wt = root.parent / name
    res = _git( root, "worktree", "add", "-b", branch, str( wt ), "HEAD" )
    assert res.returncode == 0, res.stderr
    _git( wt, "config", "user.email", "test@example.com" )
    _git( wt, "config", "user.name", "Test" )
    return wt


def _branch_exists( root, branch ):
    return _git( root, "rev-parse", "--verify", branch ).returncode == 0


def test_real_clean_worktree_dir_removed_branch_kept( repo ):
    wt = _add_worktree( repo, "wt-clean", "wt-clean-branch" )
    assert wt.exists()

    r = drain_then_remove( str( wt ), project_root=str( repo ) )

    assert r[ "removed" ] is True
    assert r[ "wip_committed" ] is False
    assert not wt.exists(), "worktree DIR must be gone"
    assert _branch_exists( repo, "wt-clean-branch" ), "branch must be KEPT"


def test_real_dirty_worktree_wip_preserved_on_branch( repo ):
    wt = _add_worktree( repo, "wt-dirty", "wt-dirty-branch" )
    ( wt / "scratch.py" ).write_text( "x = 1  # uncommitted work\n" )

    r = drain_then_remove( str( wt ), project_root=str( repo ) )

    assert r[ "removed" ] is True
    assert r[ "wip_committed" ] is True
    assert not wt.exists(), "worktree DIR must be gone"
    assert _branch_exists( repo, "wt-dirty-branch" ), "branch must be KEPT"

    tip_msg = _git( repo, "log", "-1", "--format=%s", "wt-dirty-branch" ).stdout.strip()
    assert tip_msg.startswith( WIP_COMMIT_PREFIX ), f"branch tip should be the WIP commit: {tip_msg}"
    files = _git( repo, "show", "--name-only", "--format=", "wt-dirty-branch" ).stdout
    assert "scratch.py" in files, "uncommitted work must be preserved in the WIP commit"


def test_real_detached_head_dirty_gets_rescue_branch( repo ):
    wt = _add_worktree( repo, "wt-det", "wt-det-branch" )
    head_sha = _git( wt, "rev-parse", "HEAD" ).stdout.strip()
    _git( wt, "checkout", "-q", "--detach", head_sha )
    ( wt / "lost.py" ).write_text( "rescue me\n" )

    r = drain_then_remove( str( wt ), project_root=str( repo ) )

    assert r[ "removed" ] is True
    assert r[ "wip_committed" ] is True
    assert r[ "rescue_branch" ] is not None
    assert r[ "rescue_branch" ].startswith( RESCUE_BRANCH_PREFIX )
    assert _branch_exists( repo, r[ "rescue_branch" ] ), "rescue branch must preserve the WIP"
    files = _git( repo, "show", "--name-only", "--format=", r[ "rescue_branch" ] ).stdout
    assert "lost.py" in files


def test_real_run_makes_no_remote_calls( repo ):
    """A repo with NO remote: if drain_then_remove tried to push, git would error
    — removal still succeeds because push is never attempted."""
    wt = _add_worktree( repo, "wt-noremote", "wt-noremote-branch" )
    ( wt / "f.py" ).write_text( "data\n" )
    assert _git( repo, "remote" ).stdout.strip() == "", "fixture should have no remote"

    r = drain_then_remove( str( wt ), project_root=str( repo ) )

    assert r[ "removed" ] is True and r[ "wip_committed" ] is True
    assert r[ "errors" ] == [], "no push attempt => no errors from a missing remote"


# ----------------------------------------------------------------------------
# Janitor: list_worktrees parsing + reconcile_worktrees (the backstop)
# ----------------------------------------------------------------------------

_PORCELAIN = (
    "worktree /repo\n"
    "HEAD 1111111\n"
    "branch refs/heads/main\n"
    "\n"
    "worktree /repo/.claude/worktrees/wt-a\n"
    "HEAD 2222222\n"
    "branch refs/heads/wt-a\n"
    "\n"
    "worktree /repo/.claude/worktrees/wt-locked\n"
    "HEAD 3333333\n"
    "branch refs/heads/wt-locked\n"
    "locked under review\n"
    "\n"
    "worktree /repo/.claude/worktrees/wt-detached\n"
    "HEAD 4444444\n"
    "detached\n"
)


def test_list_worktrees_parses_porcelain():
    def run( argv, cwd=None, timeout=60 ):
        return SimpleNamespace( returncode=0, stdout=_PORCELAIN, stderr="" )
    recs = list_worktrees( project_root="/repo", run=run )
    assert len( recs ) == 4
    main = [ r for r in recs if r[ "is_main" ] ][ 0 ]
    assert main[ "path" ] == "/repo" and main[ "branch" ] == "main"
    locked = [ r for r in recs if r[ "path" ].endswith( "wt-locked" ) ][ 0 ]
    assert locked[ "locked" ] is True
    detached = [ r for r in recs if r[ "path" ].endswith( "wt-detached" ) ][ 0 ]
    assert detached[ "branch" ] is None and detached[ "is_main" ] is False


def test_reconcile_skips_main_locked_active_sweeps_only_idle():
    records = [
        { "path": "/repo",                              "branch": "main",        "locked": False, "is_main": True },
        { "path": "/repo/.claude/worktrees/idle",       "branch": "wt-idle",     "locked": False, "is_main": False },
        { "path": "/repo/.claude/worktrees/active",     "branch": "wt-active",   "locked": False, "is_main": False },
        { "path": "/repo/.claude/worktrees/locked",     "branch": "wt-locked",   "locked": True,  "is_main": False },
        { "path": "/elsewhere/outside",                 "branch": "wt-out",      "locked": False, "is_main": False },
    ]
    ages = { "/repo/.claude/worktrees/idle": 9.0, "/repo/.claude/worktrees/active": 0.5 }
    swept_calls = []
    def drain_fn( path, project_root=None, run=None, now=None, debug=False ):
        swept_calls.append( path )
        return { "removed": True, "branch": "wt-idle", "wip_committed": False }

    out = reconcile_worktrees(
        sandbox_root="/repo/.claude/worktrees", project_root="/repo",
        age_threshold_hours=6.0,
        list_fn=lambda: records,
        age_fn=lambda p: ages.get( p, 0.0 ),
        drain_fn=drain_fn,
    )
    assert swept_calls == [ "/repo/.claude/worktrees/idle" ], "only the idle, non-locked, in-sandbox worktree is swept"
    reasons = { s[ "path" ]: s[ "reason" ] for s in out[ "skipped" ] }
    assert reasons[ "/repo" ] == "main_worktree"
    assert reasons[ "/repo/.claude/worktrees/locked" ] == "locked"
    assert reasons[ "/elsewhere/outside" ] == "outside_sandbox"
    assert reasons[ "/repo/.claude/worktrees/active" ].startswith( "active_" )


def test_reconcile_one_bad_worktree_does_not_derail_others():
    records = [
        { "path": "/repo/.claude/worktrees/boom", "branch": "b", "locked": False, "is_main": False },
        { "path": "/repo/.claude/worktrees/ok",   "branch": "o", "locked": False, "is_main": False },
    ]
    def drain_fn( path, project_root=None, run=None, now=None, debug=False ):
        if path.endswith( "boom" ): raise RuntimeError( "kaboom" )
        return { "removed": True }
    out = reconcile_worktrees(
        sandbox_root="/repo/.claude/worktrees", project_root="/repo",
        list_fn=lambda: records, age_fn=lambda p: 99.0, drain_fn=drain_fn,
    )
    assert any( "boom" in e for e in out[ "errors" ] )
    assert any( s[ "path" ].endswith( "ok" ) for s in out[ "swept" ] ), "the good worktree still got swept"


def test_real_reconcile_sweeps_idle_keeps_fresh_and_branch( repo ):
    sandbox = repo.parent / "wts"
    sandbox.mkdir()
    idle  = sandbox / "idle-wt"
    fresh = sandbox / "fresh-wt"
    assert _git( repo, "worktree", "add", "-b", "wt-idle",  str( idle ),  "HEAD" ).returncode == 0
    assert _git( repo, "worktree", "add", "-b", "wt-fresh", str( fresh ), "HEAD" ).returncode == 0

    # Age the idle worktree's files to 7h ago (the .git FILE is excluded by the scanner).
    old = time.time() - 7 * 3600
    for p in idle.rglob( "*" ):
        if p.is_file() and p.name != ".git":
            os.utime( p, ( old, old ) )

    out = reconcile_worktrees( sandbox_root=str( sandbox ), project_root=str( repo ), age_threshold_hours=6.0 )

    swept = [ s[ "path" ] for s in out[ "swept" ] ]
    assert any( "idle-wt"  in p for p in swept ), f"idle worktree should be swept; got {out}"
    assert not any( "fresh-wt" in p for p in swept ), "fresh worktree must NOT be swept"
    assert not idle.exists(),  "idle worktree DIR removed"
    assert fresh.exists(),     "fresh worktree DIR kept"
    assert _branch_exists( repo, "wt-idle" ),  "idle branch must be KEPT (preservation)"
    assert _branch_exists( repo, "wt-fresh" ), "fresh branch intact"


if __name__ == "__main__":
    raise SystemExit( pytest.main( [ __file__, "-v" ] ) )
