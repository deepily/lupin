"""
Each janitor poll deletes local branches that are fully merged and that no worktree has
checked out (Rick, 2026-09-29, broadcast 766066df: 107 had piled up, because the janitor
only ever deleted a branch when it removed that branch's tree).
"""

import os
import subprocess
from types import SimpleNamespace

import pytest

from cosa.agents.shared.worktree_reaper import sweep_merged_branches, branch_created_ts, _default_run
from lupin_arbiter_app import fleet_arbiter_loop as fal


def _git( cwd, *args, env=None ):
    return subprocess.run( [ "git", *args ], cwd=cwd, capture_output=True, text=True, timeout=60,
                           env={ **os.environ, **( env or {} ) } )


OLD = { "GIT_COMMITTER_DATE": "2026-09-01T00:00:00Z" }       # the reflog entry is stamped with this


def _old_branch( root, name ):
    assert _git( root, "branch", name, env=OLD ).returncode == 0


@pytest.fixture
def repo( tmp_path ):
    root = tmp_path / "repo"
    root.mkdir()
    _git( root, "init", "-q", "-b", "wip-v9" )
    _git( root, "config", "user.email", "t@example.com" )
    _git( root, "config", "user.name", "T" )
    ( root / "a" ).write_text( "a\n" )
    _git( root, "add", "-A" )
    _git( root, "commit", "-q", "-m", "seed" )
    return root


def _branches( root ):
    return set( _git( root, "for-each-ref", "--format=%(refname:short)", "refs/heads" ).stdout.split() )


def test_merged_unused_branches_go_and_everything_else_stays( repo, tmp_path ):
    _old_branch( repo, "merged-old" )                          # at HEAD: fully merged, old
    _git( repo, "branch", "merged-new" )                       # fully merged, but made just now
    _old_branch( repo, "main" )                                # protected by name
    _old_branch( repo, "wip-v8" )                              # protected: holds "wip"
    _git( repo, "worktree", "add", "-q", "-b", "in-use", str( tmp_path / "wt" ), "HEAD" )
    _git( repo, "switch", "-q", "-c", "unmerged" )
    ( repo / "b" ).write_text( "b\n" )
    _git( repo, "add", "b" )
    _git( repo, "commit", "-q", "-m", "only on unmerged" )
    _git( repo, "switch", "-q", "wip-v9" )

    out = sweep_merged_branches( project_root=str( repo ) )

    assert out[ "error" ] is None and out[ "target" ] == "wip-v9"
    assert [ o[ "branch" ] for o in out[ "deleted" ] ] == [ "merged-old" ]
    assert out[ "kept" ] == []                                 # skipped candidates are not noise
    assert _branches( repo ) == { "wip-v9", "merged-new", "main", "wip-v8", "in-use", "unmerged" }


def test_a_detached_main_tree_deletes_nothing( repo ):
    _old_branch( repo, "merged-old" )
    _git( repo, "checkout", "-q", "--detach" )
    out = sweep_merged_branches( project_root=str( repo ) )
    assert out[ "deleted" ] == [] and "nothing to measure against" in out[ "error" ]
    assert "merged-old" in _branches( repo )


def test_an_unreadable_listing_deletes_nothing( repo ):
    real = lambda argv, cwd=None, timeout=60: subprocess.run( argv, cwd=cwd, capture_output=True, text=True )
    def run( argv, cwd=None, timeout=60 ):
        if "for-each-ref" in argv:
            return SimpleNamespace( returncode=1, stdout="", stderr="boom" )
        return real( argv, cwd )
    out = sweep_merged_branches( project_root=str( repo ), run=run )
    assert out[ "deleted" ] == [] and out[ "error" ] == "could not list branches: boom"


def test_a_worktree_listing_failure_deletes_nothing( repo ):
    real = lambda argv, cwd=None, timeout=60: subprocess.run( argv, cwd=cwd, capture_output=True, text=True )
    calls = { "n": 0 }
    def run( argv, cwd=None, timeout=60 ):
        if argv[ 1:3 ] == [ "worktree", "list" ]:
            calls[ "n" ] += 1
            if calls[ "n" ] == 2:                              # list_worktrees ok, checked_out fails
                return SimpleNamespace( returncode=1, stdout="", stderr="" )
        return real( argv, cwd )
    out = sweep_merged_branches( project_root=str( repo ), run=run )
    assert out[ "deleted" ] == [] and out[ "error" ] == "could not list branches: worktree list failed"


def test_a_refused_delete_is_reported_as_kept( repo ):
    _old_branch( repo, "merged-old" )
    out = sweep_merged_branches( project_root=str( repo ),
                                 delete_fn=lambda root, b, t, run=None: { "branch": b, "deleted": False,
                                                                          "kept_reason": "branch_d_refused" } )
    assert out[ "kept" ] == [ { "branch": "merged-old", "deleted": False, "kept_reason": "branch_d_refused" } ]


def test_a_git_runner_that_raises_reads_as_could_not_look():
    def run( argv, cwd=None, timeout=60 ): raise OSError( "no git" )
    out = sweep_merged_branches( project_root="/nonexistent", run=run )
    assert out[ "deleted" ] == [] and "nothing to measure against" in out[ "error" ]


def test_a_raising_delete_is_captured_not_raised( repo ):
    _old_branch( repo, "merged-old" )
    def boom( *a, **k ): raise RuntimeError( "db" )
    out = sweep_merged_branches( project_root=str( repo ), delete_fn=boom )
    assert out[ "deleted" ] == [] and out[ "error" ] == "branch sweep raised: db"


def test_the_default_root_is_the_project_root( monkeypatch, repo ):
    import cosa.utils.util as cu
    monkeypatch.setattr( cu, "get_project_root", lambda: str( repo ) )
    _old_branch( repo, "merged-old" )
    assert [ o[ "branch" ] for o in sweep_merged_branches()[ "deleted" ] ] == [ "merged-old" ]


# ── the grace period (María, 2026-09-29) ──────────────────────────────────────────────

def test_a_fresh_branch_survives_until_its_grace_period_ends( repo ):
    _git( repo, "branch", "fresh" )
    made = branch_created_ts( str( repo ), "fresh", _default_run )
    assert sweep_merged_branches( project_root=str( repo ), now_ts=made + 23.9 * 3600 )[ "deleted" ] == []
    out = sweep_merged_branches( project_root=str( repo ), now_ts=made + 24 * 3600 )
    assert [ o[ "branch" ] for o in out[ "deleted" ] ] == [ "fresh" ]


def test_the_age_is_the_reflog_entry_not_the_commit( repo ):
    # A branch made TODAY at an OLD commit is young; reading the commit time would call it old.
    _git( repo, "commit", "-q", "--allow-empty", "-m", "old commit", env=OLD )
    _git( repo, "branch", "today-at-old-commit" )
    assert sweep_merged_branches( project_root=str( repo ) )[ "deleted" ] == []


def test_an_unreadable_reflog_means_too_young( repo ):
    _old_branch( repo, "merged-old" )
    real = lambda argv, cwd=None: subprocess.run( argv, cwd=cwd, capture_output=True, text=True )
    def run( argv, cwd=None, timeout=60 ):
        if "reflog" in argv:
            return SimpleNamespace( returncode=128, stdout="", stderr="bad revision" )
        return real( argv, cwd )
    assert branch_created_ts( str( repo ), "merged-old", run ) is None
    assert sweep_merged_branches( project_root=str( repo ), run=run )[ "deleted" ] == []


def test_an_expired_reflog_reads_as_old( repo ):
    _git( repo, "branch", "merged-old" )
    ( repo / ".git" / "logs" / "refs" / "heads" / "merged-old" ).unlink()
    assert branch_created_ts( str( repo ), "merged-old", _default_run ) == 0.0
    assert [ o[ "branch" ] for o in sweep_merged_branches( project_root=str( repo ) )[ "deleted" ] ] == [ "merged-old" ]

# ── the janitor calls it once per repo ────────────────────────────────────────────────

def _janitor( roots, sweep, events ):
    return fal.make_worktree_janitor_fn(
        sandbox_root=".claude/worktrees", age_hours=6, ledger_path="/nowhere",
        notify_fn=lambda m, a: [], log_fn=lambda e, **f: events.append( ( e, f ) ),
        reconcile_fn=lambda **kw: { "swept": [] }, report_fn=lambda *a, **k: { "changed": False },
        repo_roots=roots, branch_sweep_fn=sweep )


def test_each_repo_is_branch_swept_and_deletions_are_logged():
    seen, events = [], []
    def sweep( project_root ):
        seen.append( project_root )
        return { "deleted": [ { "branch": f"b-{project_root}" } ],
                 "kept": [ { "branch": "k", "kept_reason": "branch_d_refused" } ] if project_root == "/b" else [],
                 "error": "x" if project_root == "/b" else None }
    out = _janitor( [ "/a", "/b" ], sweep, events )()
    assert seen == [ "/a", "/b" ]
    assert [ o[ "branch" ] for o in out[ "branches_deleted" ] ] == [ "b-/a", "b-/b" ]
    assert out[ "branches_kept" ][ 0 ][ "branch" ] == "k" and out[ "errors" ] == [ "/b: x" ]
    assert events[ 0 ][ 0 ] == "worktree_janitor_branches"


def test_a_raising_branch_sweep_does_not_stop_the_poll():
    def sweep( project_root ): raise RuntimeError( "boom" )
    out = _janitor( [ "/a" ], sweep, [] )()
    assert out[ "errors" ] == [ "/a: branch sweep raised: boom" ]


def test_the_default_sweep_is_the_reaper_function( monkeypatch ):
    import cosa.agents.shared.worktree_reaper as wr
    monkeypatch.setattr( wr, "sweep_merged_branches", lambda project_root=None: { "root": project_root } )
    assert fal._default_branch_sweep_fn( project_root="/r" ) == { "root": "/r" }


def test_the_factory_wires_the_branch_sweep( monkeypatch, tmp_path ):
    captured = {}
    real = fal.make_worktree_janitor_fn
    def spy( **kw ):
        captured.update( kw )
        return real( **kw )
    monkeypatch.setattr( fal, "make_worktree_janitor_fn", spy )
    from tests.unit.test_the_janitor_sweeps_every_fleet_repo import _Gateway, _Store
    fal.build_fleet_arbiter_job_factory(
        _Gateway(), _Store(), log_fn=lambda e, **f: None,
        worktree_janitor_enabled=True, worktree_refusal_ledger_path=str( tmp_path / "l.json" ) )
    assert captured[ "branch_sweep_fn" ] is fal._default_branch_sweep_fn
