"""
The janitor deletes a reaped tree's branch only when every commit on it is already on
the repo's current WIP branch (row 129cc96b, P1 — Rick, 2026-09-18).

Before this, the janitor kept every branch by design, and 80 of them piled up in lupin.
The rule now:

  · measured against the branch the MAIN tree has checked out, in that repo
  · `git merge-base --is-ancestor <branch> <WIP>` must say yes, and only then
  · `git branch -d` — never -D
  · main, master, the WIP branch, any "*wip*" branch, and any branch still checked out
    in a worktree are never touched
  · everything else is kept and reported in branches_kept

The real-git tests build a throwaway repo in tmp_path. The upstream test is the one that
proves the ancestry check is load-bearing: `git branch -d` on its own deletes a branch
that is merged into its UPSTREAM but not into the WIP branch.
"""

import os
import subprocess
import time
from types import SimpleNamespace

import pytest

import cosa.agents.shared.worktree_reaper as wr


# ---------------------------------------------------------------------------
# Real git
# ---------------------------------------------------------------------------
def _git( cwd, *args ):
    return subprocess.run( [ "git", *args ], cwd=cwd, capture_output=True, text=True, timeout=60 )


def _commit( cwd, name, text="x\n" ):
    ( cwd / name ).write_text( text )
    assert _git( cwd, "add", "-A" ).returncode == 0
    assert _git( cwd, "commit", "-q", "-m", f"add {name}" ).returncode == 0


def _has_branch( repo, branch ):
    return _git( repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}" ).returncode == 0


@pytest.fixture
def repo( tmp_path ):
    """A real repo whose main tree sits on a WIP branch, with a janitor lane."""
    root = tmp_path / "repo"
    root.mkdir()
    _git( root, "init", "-q", "-b", "wip-v9" )
    _git( root, "config", "user.email", "t@example.com" )
    _git( root, "config", "user.name", "T" )
    _commit( root, "README.md", "seed\n" )
    ( root / ".claude" / "worktrees" ).mkdir( parents=True )
    return root


def _idle_tree( repo, name, branch ):
    path = repo / ".claude" / "worktrees" / name
    assert _git( repo, "worktree", "add", "-q", "-b", branch, str( path ), "HEAD" ).returncode == 0
    return path


def _age( path, hours=7 ):
    old = time.time() - hours * 3600
    for p in path.rglob( "*" ):
        if p.is_file() and p.name != ".git":
            os.utime( p, ( old, old ) )


def _reconcile( repo ):
    return wr.reconcile_worktrees( project_root=str( repo ), age_threshold_hours=6.0 )


def test_a_merged_branch_is_deleted_after_its_tree_is_reaped( repo ):
    tree = _idle_tree( repo, "wt-done", "wt-done" )
    _commit( tree, "feature.txt" )
    assert _git( repo, "merge", "-q", "--ff-only", "wt-done" ).returncode == 0     # now on the WIP line
    _age( tree )

    out = _reconcile( repo )

    assert not tree.exists()
    assert not _has_branch( repo, "wt-done" )
    assert [ o[ "branch" ] for o in out[ "branches_deleted" ] ] == [ "wt-done" ]
    assert out[ "swept" ][ 0 ][ "result" ][ "branch_outcome" ][ "deleted" ] is True


def test_an_unmerged_branch_is_kept_and_reported_with_its_count( repo ):
    tree = _idle_tree( repo, "wt-open", "wt-open" )
    _commit( tree, "a.txt" )
    _commit( tree, "b.txt" )
    _age( tree )

    out = _reconcile( repo )

    assert not tree.exists(), "the tree still goes — the janitor keeps its old contract"
    assert _has_branch( repo, "wt-open" ), "an unmerged branch is never deleted"
    kept = out[ "branches_kept" ]
    assert [ ( k[ "branch" ], k[ "kept_reason" ], k[ "commits_ahead" ] ) for k in kept ] == [ ( "wt-open", "unmerged", 2 ) ]
    assert out[ "branches_deleted" ] == []


def test_uncommitted_work_the_janitor_saves_keeps_its_branch( repo ):
    tree = _idle_tree( repo, "wt-dirty", "wt-dirty" )
    ( tree / "unsaved.txt" ).write_text( "only here\n" )
    _age( tree )

    out = _reconcile( repo )

    assert _has_branch( repo, "wt-dirty" ), "the WIP auto-commit makes the branch unmerged, so it stays"
    assert out[ "branches_kept" ][ 0 ][ "kept_reason" ] == "unmerged"
    shown = _git( repo, "show", "wt-dirty:unsaved.txt" )
    assert shown.stdout == "only here\n"


def test_merged_into_its_upstream_but_not_the_wip_branch_is_kept( repo ):
    """
    The trap `-d` alone falls into. `side` carries a commit the WIP branch lacks; `feat`
    points at the same commit and tracks `side`. `git branch -d feat` would delete it
    (merged to upstream), with only a warning. The ancestry check keeps it.
    """
    _git( repo, "branch", "side" )
    tree = _idle_tree( repo, "wt-feat", "feat" )
    _commit( tree, "c.txt" )
    assert _git( repo, "branch", "-f", "side", "feat" ).returncode == 0
    assert _git( repo, "branch", "--set-upstream-to=side", "feat" ).returncode == 0
    _age( tree )

    out = _reconcile( repo )

    assert _has_branch( repo, "feat" ), "merged into its upstream is NOT merged into the WIP branch"
    assert out[ "branches_kept" ][ 0 ][ "kept_reason" ] == "unmerged"


def test_the_upstream_trap_is_real_git_deletes_it_without_the_check( repo ):
    """Control for the test above: prove `git branch -d` really does delete that branch."""
    _git( repo, "branch", "side" )
    tree = _idle_tree( repo, "wt-feat", "feat" )
    _commit( tree, "c.txt" )
    _git( repo, "branch", "-f", "side", "feat" )
    _git( repo, "branch", "--set-upstream-to=side", "feat" )
    assert _git( repo, "worktree", "remove", str( tree ) ).returncode == 0

    assert _git( repo, "branch", "-d", "feat" ).returncode == 0
    assert not _has_branch( repo, "feat" )


def test_each_repo_is_measured_against_its_own_current_branch( repo ):
    """The target is whatever the main tree has checked out — here a non-WIP name."""
    _git( repo, "checkout", "-q", "-b", "trunk" )
    tree = _idle_tree( repo, "wt-x", "wt-x" )
    _age( tree )

    out = _reconcile( repo )

    assert out[ "branches_deleted" ][ 0 ][ "target" ] == "trunk"
    assert not _has_branch( repo, "wt-x" )


def test_a_branch_checked_out_elsewhere_is_never_deleted( repo ):
    """Two trees, one branch: git forbids it, so check the rule on the real list."""
    _idle_tree( repo, "wt-live", "wt-live" )
    outcome = wr.delete_merged_branch( str( repo ), "wt-live", "wip-v9" )
    assert outcome[ "kept_reason" ] == "checked_out"
    assert _has_branch( repo, "wt-live" )


def test_a_wip_named_branch_is_never_deleted_even_when_merged( repo ):
    _git( repo, "branch", "wip-v8-old-line" )
    outcome = wr.delete_merged_branch( str( repo ), "wip-v8-old-line", "wip-v9" )
    assert outcome[ "kept_reason" ] == "protected"
    assert _has_branch( repo, "wip-v8-old-line" )


def test_a_detached_main_tree_means_nothing_is_deleted( repo ):
    _git( repo, "checkout", "-q", "--detach" )
    tree = _idle_tree( repo, "wt-y", "wt-y" )
    _age( tree )

    out = _reconcile( repo )

    assert _has_branch( repo, "wt-y" )
    assert out[ "branches_kept" ][ 0 ][ "kept_reason" ] == "no_target_branch"


# ---------------------------------------------------------------------------
# Injected runner — the verbs, exactly
# ---------------------------------------------------------------------------
class _Git:
    """Scripted git: returncodes per verb, every argv recorded."""
    def __init__( self, ancestor_rc=0, count="3", count_rc=0, delete_rc=0, list_rc=0, listing="" ):
        self.calls = []
        self.rc    = { "merge-base": ancestor_rc, "rev-list": count_rc, "branch": delete_rc, "worktree": list_rc }
        self.out   = { "rev-list": count, "worktree": listing }
    def __call__( self, argv, cwd=None, timeout=60 ):
        self.calls.append( argv )
        rc = self.rc.get( argv[ 1 ], 0 )
        return SimpleNamespace( returncode=rc, stdout=self.out.get( argv[ 1 ], "" ), stderr="" if rc == 0 else "nope" )


def test_the_delete_is_branch_dash_d_never_capital_d():
    git = _Git()
    outcome = wr.delete_merged_branch( "/repo", "wt-a", "wip-v9", run=git )
    assert outcome[ "deleted" ] is True
    assert git.calls[ -1 ] == [ "git", "branch", "-d", "wt-a" ]
    assert not any( "-D" in argv for argv in git.calls )


def test_the_delete_runs_only_after_a_yes_from_the_ancestry_check():
    git = _Git( ancestor_rc=1 )
    outcome = wr.delete_merged_branch( "/repo", "wt-a", "wip-v9", run=git )
    assert outcome[ "kept_reason" ] == "unmerged"
    assert outcome[ "commits_ahead" ] == 3
    assert [ "git", "branch", "-d", "wt-a" ] not in git.calls


@pytest.mark.parametrize( "branch, target", [
    ( "main", "wip-v9" ), ( "master", "wip-v9" ), ( "wip-v9", "wip-v9" ), ( "WIP-scratch", "trunk" ),
    ( "trunk", "trunk" ),     # the current branch, with no "wip" in its name to hide behind
] )
def test_protected_branches_never_reach_git( branch, target ):
    git = _Git()
    outcome = wr.delete_merged_branch( "/repo", branch, target, run=git )
    assert outcome[ "kept_reason" ] == "protected"
    assert git.calls == []


@pytest.mark.parametrize( "kwargs, reason", [
    ( dict( ancestor_rc=128 ),               "merge_check_failed" ),
    ( dict( delete_rc=1 ),                   "branch_d_refused" ),
    ( dict( list_rc=1 ),                     "worktree_list_failed" ),
    ( dict( listing="worktree /r\nbranch refs/heads/wt-a\n" ), "checked_out" ),
] )
def test_every_other_outcome_keeps_the_branch( kwargs, reason ):
    outcome = wr.delete_merged_branch( "/repo", "wt-a", "wip-v9", run=_Git( **kwargs ) )
    assert ( outcome[ "deleted" ], outcome[ "kept_reason" ] ) == ( False, reason )


def test_an_unreadable_count_is_none_not_zero():
    outcome = wr.delete_merged_branch( "/repo", "wt-a", "wip-v9", run=_Git( ancestor_rc=1, count_rc=1 ) )
    assert ( outcome[ "kept_reason" ], outcome[ "commits_ahead" ] ) == ( "unmerged", None )


@pytest.mark.parametrize( "branch, target, reason", [
    ( None, "wip-v9", "no_branch" ), ( "wt-a", None, "no_target_branch" ),
] )
def test_a_missing_branch_or_target_keeps( branch, target, reason ):
    git = _Git()
    assert wr.delete_merged_branch( "/repo", branch, target, run=git )[ "kept_reason" ] == reason
    assert git.calls == []


def test_the_default_runner_is_real_git( repo ):
    assert wr.delete_merged_branch( str( repo ), "no-such-branch", "wip-v9" )[ "kept_reason" ] == "merge_check_failed"


def test_a_tree_the_drain_did_not_remove_keeps_its_branch_untouched():
    calls = []
    out = wr.reconcile_worktrees(
        project_root="/repo", run=lambda *a, **k: None,
        list_fn=lambda: [ { "path": "/repo", "is_main": True, "branch": "wip-v9" },
                          { "path": "/repo/.claude/worktrees/a", "is_main": False, "branch": "a" } ],
        age_fn=lambda p: 99.0, drain_fn=lambda p, **kw: { "removed": False, "branch": "a" },
        branch_fn=lambda *a, **kw: calls.append( a ) )
    assert calls == []
    assert out[ "branches_deleted" ] == [] and out[ "branches_kept" ] == []


def test_main_worktree_branch_without_a_main_record_is_none():
    assert wr.main_worktree_branch( [ { "is_main": False, "branch": "x" } ] ) is None


# ---------------------------------------------------------------------------
# A tag named like a branch (Rachel's break test, 2026-09-18)
# ---------------------------------------------------------------------------
def _give_upstream( repo, tree, branch, tmp_path ):
    """Push `branch` to a bare remote and track it, so `git branch -d` measures the upstream."""
    bare = tmp_path / "origin.git"
    _git( tmp_path, "init", "-q", "--bare", str( bare ) )
    _git( repo, "remote", "add", "origin", str( bare ) )
    assert _git( tree, "push", "-q", "origin", f"refs/heads/{branch}:refs/heads/{branch}" ).returncode == 0
    _git( repo, "fetch", "-q", "origin" )
    _git( repo, "config", f"branch.{branch}.remote", "origin" )
    _git( repo, "config", f"branch.{branch}.merge", f"refs/heads/{branch}" )


def test_a_tag_named_like_the_branch_cannot_pass_it_off_as_merged( repo, tmp_path ):
    """
    git resolves a bare name to a TAG first. A tag `feat` sitting on the WIP line made the
    ancestry check answer "merged"; the upstream then satisfied `-d`, and the branch went.
    """
    tree = _idle_tree( repo, "wt-shadow", "feat" )
    _git( repo, "tag", "feat", "wip-v9" )
    _commit( tree, "not-on-wip.txt" )
    _give_upstream( repo, tree, "feat", tmp_path )
    assert _git( repo, "worktree", "remove", str( tree ) ).returncode == 0

    outcome = wr.delete_merged_branch( str( repo ), "feat", "wip-v9" )

    assert ( outcome[ "deleted" ], outcome[ "kept_reason" ] ) == ( False, "unmerged" )
    assert _has_branch( repo, "feat" )


def test_a_tag_named_like_the_wip_branch_cannot_move_the_target( repo, tmp_path ):
    """The other side of the same trap: a tag `wip-v9` on the branch tip, not on the line."""
    tree = _idle_tree( repo, "wt-shadow", "feat" )
    _commit( tree, "not-on-wip.txt" )
    _git( repo, "tag", "wip-v9", "feat" )
    _give_upstream( repo, tree, "feat", tmp_path )
    assert _git( repo, "worktree", "remove", str( tree ) ).returncode == 0

    outcome = wr.delete_merged_branch( str( repo ), "feat", "wip-v9" )

    assert ( outcome[ "deleted" ], outcome[ "kept_reason" ] ) == ( False, "unmerged" )
    assert _has_branch( repo, "feat" )


def test_a_merged_branch_sharing_a_tags_name_is_still_deleted( repo ):
    """
    The janitor used to take the branch from the drain's `rev-parse --abbrev-ref HEAD`,
    which reads `heads/feat` when a tag `feat` exists. `refs/heads/heads/feat` names
    nothing, so a merged branch was kept as "merge_check_failed". The name now comes from
    the full ref in `worktree list --porcelain` (Rachel via María, 2026-09-18).
    """
    tree = _idle_tree( repo, "wt-tagged", "feat" )
    _git( repo, "tag", "feat", "wip-v9" )
    _age( tree )

    out = _reconcile( repo )

    assert [ ( o[ "branch" ], o[ "deleted" ] ) for o in out[ "branches_deleted" ] ] == [ ( "feat", True ) ]
    assert not _has_branch( repo, "feat" )


def test_a_detached_tree_measures_the_rescue_branch_the_drain_named( repo ):
    tree = repo / ".claude" / "worktrees" / "wt-detached"
    assert _git( repo, "worktree", "add", "-q", "--detach", str( tree ), "HEAD" ).returncode == 0
    _age( tree )

    out = _reconcile( repo )

    rescue = out[ "swept" ][ 0 ][ "result" ][ "rescue_branch" ]
    assert rescue and out[ "branches_deleted" ][ 0 ][ "branch" ] == rescue, "a clean rescue branch is merged"
    assert not _has_branch( repo, rescue )
