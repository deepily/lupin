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

import cosa.agents.shared.worktree_reaper as _reaper_mod   # module handle: this file defines a LOCAL `_git` helper that would shadow the import
from cosa.agents.shared.worktree_reaper import (
    drain_then_remove,
    list_worktrees,
    reconcile_worktrees,
    _newest_mtime_age_hours,
    _is_in_container,
    CONTAINER_PROJECT_ROOT,
    WIP_COMMIT_PREFIX,
    RESCUE_BRANCH_PREFIX,
)


def _run_remove_fails( prune_returncode=0 ):
    """
    Injected runner where `git worktree remove` FAILS (returncode=1) so the
    drain reaches the remove-failure branch that (host-side) runs prune.
    prune_returncode controls the prune result for the failure sub-branch.
    """
    def run( argv, cwd=None, timeout=60 ):
        sub = argv[ 1 ] if len( argv ) > 1 else ""
        if sub == "rev-parse" and "--abbrev-ref" in argv:
            return SimpleNamespace( returncode=0, stdout="wt-feature\n", stderr="" )
        if sub == "status":
            return SimpleNamespace( returncode=0, stdout="", stderr="" )
        if sub == "worktree" and len( argv ) > 2 and argv[ 2 ] == "remove":
            return SimpleNamespace( returncode=1, stdout="", stderr="remove failed (submodule)" )
        if sub == "worktree" and len( argv ) > 2 and argv[ 2 ] == "prune":
            return SimpleNamespace( returncode=prune_returncode, stdout="",
                                    stderr="" if prune_returncode == 0 else "prune failed" )
        return SimpleNamespace( returncode=0, stdout="", stderr="" )
    return run


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
# In-container prune guard (bug 47ac0e50) — remove-failure branch
# ----------------------------------------------------------------------------

def test_remove_failure_prunes_on_host( monkeypatch ):
    # Host-side (project_root != /var/lupin, no env sentinel): the remove-failure
    # branch runs `git worktree prune` as before — safe, full worktree visibility.
    monkeypatch.delenv( "LUPIN_IN_CONTAINER", raising=False )
    calls = []
    base  = _run_remove_fails()
    def spy( argv, cwd=None, timeout=60 ):
        calls.append( argv )
        return base( argv, cwd=cwd, timeout=timeout )
    r = drain_then_remove( "/tmp", project_root="/tmp", run=spy )
    assert r[ "removed" ] is False
    assert any( a[ :3 ] == [ "git", "worktree", "prune" ] for a in calls ), "host must still prune"
    assert any( "git worktree remove failed" in e for e in r[ "errors" ] )


def test_remove_failure_prune_failure_is_recorded( monkeypatch ):
    # The prune sub-branch failure (host) is surfaced in errors[].
    monkeypatch.delenv( "LUPIN_IN_CONTAINER", raising=False )
    r = drain_then_remove( "/tmp", project_root="/tmp", run=_run_remove_fails( prune_returncode=1 ) )
    assert any( "git worktree prune failed" in e for e in r[ "errors" ] )


def test_remove_failure_skips_prune_in_container():
    # In-container (project_root == /var/lupin): NEVER prune — it would wipe the
    # shared host worktree registry (bug 47ac0e50). Skip with a recorded note.
    # debug=True exercises the in-container skip + remove-failed debug prints.
    calls = []
    base  = _run_remove_fails()
    def spy( argv, cwd=None, timeout=60 ):
        calls.append( argv )
        return base( argv, cwd=cwd, timeout=timeout )
    r = drain_then_remove( "/tmp", project_root=CONTAINER_PROJECT_ROOT, run=spy, debug=True )
    assert not any( a[ :3 ] == [ "git", "worktree", "prune" ] for a in calls ), "in-container must NOT prune"
    assert any( "skipped `git worktree prune`" in e and "47ac0e50" in e for e in r[ "errors" ] )


def test_is_in_container_true_on_container_project_root( monkeypatch ):
    monkeypatch.delenv( "LUPIN_IN_CONTAINER", raising=False )
    assert _is_in_container( CONTAINER_PROJECT_ROOT ) is True


def test_is_in_container_false_on_host_path( monkeypatch ):
    monkeypatch.delenv( "LUPIN_IN_CONTAINER", raising=False )
    assert _is_in_container( "/mnt/DATA01/whatever/lupin" ) is False


def test_is_in_container_true_on_env_sentinel( monkeypatch ):
    # An explicit sentinel forces in-container even on a host-shaped path.
    monkeypatch.setenv( "LUPIN_IN_CONTAINER", "true" )
    assert _is_in_container( "/mnt/DATA01/whatever/lupin" ) is True


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


# ----------------------------------------------------------------------------
# Grandfathered coverage-gap closure (a20fca35) — pre-existing defensive/edge
# branches enumerated by the 47ac0e50 fix. TEST-ONLY: no product behavior change.
# ----------------------------------------------------------------------------

def test_git_runner_exception_becomes_failure_dict():
    # _reaper_mod._git (module fn, NOT this file's local real-git `_git` helper):
    # an injected runner that RAISES normalizes to a success=False dict.
    def boom( argv, cwd=None, timeout=60 ):
        raise RuntimeError( "git exploded" )
    out = _reaper_mod._git( boom, "/tmp", "status" )
    assert out[ "success" ] is False
    assert out[ "returncode" ] == -1
    assert "git exploded" in out[ "stderr" ]


def test_detached_head_rescue_branch_failure_is_recorded():
    # drain_then_remove: detached HEAD + `switch -c` failure appends a rescue error.
    def run( argv, cwd=None, timeout=60 ):
        sub = argv[ 1 ] if len( argv ) > 1 else ""
        if sub == "rev-parse" and "--abbrev-ref" in argv:
            return SimpleNamespace( returncode=0, stdout="HEAD\n", stderr="" )   # detached
        if sub == "switch":
            return SimpleNamespace( returncode=1, stdout="", stderr="cannot create branch" )
        return SimpleNamespace( returncode=0, stdout="", stderr="" )
    r = drain_then_remove( "/tmp", project_root="/tmp", run=run )
    assert any( "rescue-branch create failed" in e for e in r[ "errors" ] )
    assert r[ "rescue_branch" ] is None                                          # never set on failure


def test_git_add_failure_is_recorded():
    # drain_then_remove: dirty tree + `git add -A` failure appends an add error.
    def run( argv, cwd=None, timeout=60 ):
        sub = argv[ 1 ] if len( argv ) > 1 else ""
        if sub == "rev-parse" and "--abbrev-ref" in argv:
            return SimpleNamespace( returncode=0, stdout="wt-x\n", stderr="" )
        if sub == "status":
            return SimpleNamespace( returncode=0, stdout=" M a.py\n", stderr="" )
        if sub == "add":
            return SimpleNamespace( returncode=1, stdout="", stderr="add failed" )
        return SimpleNamespace( returncode=0, stdout="", stderr="" )
    r = drain_then_remove( "/tmp", project_root="/tmp", run=run )
    assert any( "git add -A failed" in e for e in r[ "errors" ] )


def test_list_worktrees_returns_empty_on_git_failure():
    # list_worktrees: a failed `worktree list --porcelain` yields [].
    def run( argv, cwd=None, timeout=60 ):
        return SimpleNamespace( returncode=1, stdout="", stderr="not a repo" )
    assert list_worktrees( project_root="/tmp", run=run ) == []


def test_list_worktrees_skips_block_without_path():
    # list_worktrees: a porcelain block with no `worktree ` line is skipped.
    porcelain = "worktree /a\nbranch refs/heads/main\n\nbranch refs/heads/orphan\n"
    def run( argv, cwd=None, timeout=60 ):
        return SimpleNamespace( returncode=0, stdout=porcelain, stderr="" )
    recs = list_worktrees( project_root="/a", run=run )
    assert len( recs ) == 1 and recs[ 0 ][ "path" ] == "/a"                      # orphan block dropped


def test_newest_mtime_empty_tree_is_infinite( tmp_path ):
    # _newest_mtime_age_hours: an empty tree (no non-vendored files) -> inf.
    assert _newest_mtime_age_hours( str( tmp_path ), now_ts=1_000_000.0 ) == float( "inf" )


def test_newest_mtime_skips_unstatable_file( tmp_path, monkeypatch ):
    # _newest_mtime_age_hours: getmtime raising OSError is swallowed (file skipped).
    # With the only file unstatable, newest stays 0.0 -> inf.
    ( tmp_path / "a.py" ).write_text( "x" )
    real_getmtime = os.path.getmtime
    def boom( p ):
        if str( p ).endswith( "a.py" ): raise OSError( "stat failed" )
        return real_getmtime( p )
    monkeypatch.setattr( os.path, "getmtime", boom )
    assert _newest_mtime_age_hours( str( tmp_path ), now_ts=1_000_000.0 ) == float( "inf" )


def test_newest_mtime_returns_finite_age_for_real_file( tmp_path ):
    # _newest_mtime_age_hours: a real file yields a finite age (the m>newest + normal return).
    f = tmp_path / "a.py"; f.write_text( "x" )
    mt  = os.path.getmtime( str( f ) )
    age = _newest_mtime_age_hours( str( tmp_path ), now_ts=mt + 3600.0 )
    assert age == pytest.approx( 1.0, abs=0.05 )


def test_reconcile_defaults_sandbox_root_to_claude_worktrees():
    # reconcile_worktrees: sandbox_root=None -> <project_root>/.claude/worktrees default.
    out = reconcile_worktrees( sandbox_root=None, project_root="/repo",
                               list_fn=lambda: [], run=lambda *a, **k: None )
    assert out == { "swept": [], "skipped": [], "errors": [] }


def test_reconcile_joins_relative_sandbox_root():
    # reconcile_worktrees: a relative sandbox_root is joined onto project_root, so
    # "/repo/wt/x" falls INSIDE the resolved sandbox and is swept.
    seen = {}
    def list_fn():
        return [ { "path": "/repo/wt/x", "is_main": False, "locked": False } ]
    def drain_fn( path, project_root=None, run=None, now=None, debug=False ):
        seen[ "swept" ] = path; return { "removed": True }
    reconcile_worktrees( sandbox_root="wt", project_root="/repo",
                         list_fn=list_fn, age_fn=lambda p: 999.0, drain_fn=drain_fn,
                         run=lambda *a, **k: None )
    assert seen.get( "swept" ) == "/repo/wt/x"


def test_reconcile_skips_record_with_empty_path():
    # reconcile_worktrees: a record whose path is falsy is silently skipped (continue).
    def list_fn():
        return [ { "path": "" }, { "path": None } ]
    out = reconcile_worktrees( sandbox_root="/s", project_root="/repo",
                               list_fn=list_fn, run=lambda *a, **k: None )
    assert out == { "swept": [], "skipped": [], "errors": [] }


if __name__ == "__main__":
    raise SystemExit( pytest.main( [ __file__, "-v" ] ) )
