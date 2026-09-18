"""
Rachel's adversarial break tests for row 129cc96b P1-P3 — real git in tmp_path, no fakes.

Each test builds a destroy-work scenario and asserts the work survives.
"""

import os
import subprocess

import pytest

from cosa.agents.shared import worktree_reaper as wr
from cosa.agents.shared import seat_teardown as st
from lupin_arbiter_app.fleet_arbiter_loop import make_worktree_janitor_fn


def g( cwd, *args, check=True ):
    p = subprocess.run( [ "git", *args ], cwd=cwd, capture_output=True, text=True )
    if check and p.returncode != 0:
        raise AssertionError( f"git {args} failed: {p.stderr}" )
    return p.stdout.strip()


def commit( cwd, name, text="x" ):
    with open( os.path.join( cwd, name ), "w" ) as fh: fh.write( text )
    g( cwd, "add", name )
    g( cwd, "commit", "-q", "-m", f"add {name}" )
    return g( cwd, "rev-parse", "HEAD" )


def branch_exists( repo, b ):
    return subprocess.run( [ "git", "rev-parse", "-q", "--verify", f"refs/heads/{b}" ], cwd=repo,
                           capture_output=True ).returncode == 0


def reachable( repo, sha ):
    """Is sha reachable from any ref (branches, tags, remotes)?"""
    out = g( repo, "for-each-ref", "--contains", sha, "--format=%(refname)" )
    return bool( out )


@pytest.fixture
def repo( tmp_path, monkeypatch ):
    monkeypatch.setenv( "GIT_AUTHOR_NAME", "t" ); monkeypatch.setenv( "GIT_AUTHOR_EMAIL", "t@t" )
    monkeypatch.setenv( "GIT_COMMITTER_NAME", "t" ); monkeypatch.setenv( "GIT_COMMITTER_EMAIL", "t@t" )
    monkeypatch.setenv( "LUPIN_MEMENTO_MIRROR_HOME", str( tmp_path / "mirror" ) )
    r = tmp_path / "repo"
    r.mkdir()
    g( r, "init", "-q", "-b", "main" )
    with open( r / ".gitignore", "w" ) as fh: fh.write( ".claude/\n" )
    g( r, "add", ".gitignore" ); g( r, "commit", "-q", "-m", "root" )
    g( r, "switch", "-q", "-c", "wip-v9" )
    commit( r, "base.txt" )
    return str( r )


def add_tree( repo, name, branch=None, detach=False ):
    path = os.path.join( repo, ".claude", "worktrees", name )
    if detach:
        g( repo, "worktree", "add", "-q", "--detach", path )
    else:
        g( repo, "worktree", "add", "-q", "-b", branch, path )
    return path


def sweep( repo ):
    return wr.reconcile_worktrees( project_root=repo, age_threshold_hours=0.0,
                                   seat_alive_fn=lambda s, p: False )


# ── T5: an upstream that has the commits must not license deletion ──────────
def test_upstream_merged_but_wip_lacks_it_is_kept( repo, tmp_path ):
    bare = str( tmp_path / "origin.git" )
    g( tmp_path, "init", "-q", "--bare", bare )
    g( repo, "remote", "add", "origin", bare )
    t   = add_tree( repo, "seat-a", branch="feat-up" )
    sha = commit( t, "only-on-feat.txt" )
    g( t, "push", "-q", "-u", "origin", "feat-up" )
    out = sweep( repo )
    assert branch_exists( repo, "feat-up" ), out
    assert out[ "branches_kept" ][ 0 ][ "kept_reason" ] == "unmerged"


# ── T6: rescue branch carrying a WIP auto-commit must survive ───────────────
def test_detached_dirty_tree_rescue_branch_survives( repo ):
    t = add_tree( repo, "seat-b", detach=True )
    with open( os.path.join( t, "base.txt" ), "w" ) as fh: fh.write( "edited, uncommitted" )
    out    = sweep( repo )
    result = out[ "swept" ][ 0 ][ "result" ]
    assert result[ "wip_committed" ] and result[ "rescue_branch" ]
    assert branch_exists( repo, result[ "rescue_branch" ] ), out
    assert reachable( repo, result[ "wip_sha" ] )


# ── T6b: a named branch with WIP auto-commit survives ───────────────────────
def test_named_branch_with_wip_autocommit_survives( repo ):
    t = add_tree( repo, "seat-c", branch="feat-dirty" )
    with open( os.path.join( t, "new.txt" ), "w" ) as fh: fh.write( "untracked work" )
    out = sweep( repo )
    assert branch_exists( repo, "feat-dirty" ), out
    assert out[ "swept" ][ 0 ][ "result" ][ "wip_committed" ]


# ── positive control: a clean merged branch IS deleted (the instrument can see) ─
def test_positive_control_merged_branch_deleted( repo ):
    t = add_tree( repo, "seat-d", branch="feat-merged" )
    commit( t, "m.txt" )
    g( repo, "merge", "-q", "--ff-only", "feat-merged" )
    out = sweep( repo )
    assert not branch_exists( repo, "feat-merged" ), out
    assert out[ "branches_deleted" ][ 0 ][ "branch" ] == "feat-merged"


# ── T7: branch checked out in a live (locked) worktree is never deleted ─────
def test_branch_checked_out_in_locked_seat_is_kept( repo ):
    live = add_tree( repo, "seat-live", branch="shared-name" )
    g( repo, "worktree", "lock", "--reason", "lupin-seat:someone", live )
    oc = wr.delete_merged_branch( repo, "shared-name", "wip-v9" )
    assert oc[ "kept_reason" ] == "checked_out" and branch_exists( repo, "shared-name" )


# ── T8: main checkout detached → nothing to measure → keep everything ──────
def test_main_detached_keeps_merged_branch( repo ):
    t = add_tree( repo, "seat-e", branch="feat-e" )     # merged (at wip tip)
    g( repo, "switch", "-q", "--detach" )
    out = sweep( repo )
    assert branch_exists( repo, "feat-e" ), out
    assert out[ "branches_kept" ][ 0 ][ "kept_reason" ] == "no_target_branch"


# ── T9: protected names ─────────────────────────────────────────────────────
@pytest.mark.parametrize( "name", [ "main", "master", "wip-v9", "feature-WIP-x", "Wip/rescue" ] )
def test_protected_names( repo, name ):
    assert wr.delete_merged_branch( repo, name, "wip-v9" )[ "kept_reason" ] == "protected"


# ── T4: cross-repo — each repo measured against ITS OWN WIP line ────────────
def test_cross_repo_same_branch_name_measured_per_repo( tmp_path, monkeypatch, repo ):
    # repo B: current line is wip-b; branch 'twin' is merged there
    b = str( tmp_path / "repoB" ); os.makedirs( b )
    g( b, "init", "-q", "-b", "main" )
    with open( os.path.join( b, ".gitignore" ), "w" ) as fh: fh.write( ".claude/\n" )
    g( b, "add", ".gitignore" ); g( b, "commit", "-q", "-m", "root" ); g( b, "switch", "-q", "-c", "wip-b" )
    tb = add_tree( b, "seat-x", branch="twin" )
    # repo A (lupin stand-in): 'twin' exists with an unmerged commit, and a tree on it
    ta     = add_tree( repo, "seat-y", branch="twin" )
    a_sha  = commit( ta, "a-only.txt" )
    janitor = make_worktree_janitor_fn( sandbox_root=".claude/worktrees", age_hours=0.0,
                                        ledger_path=str( tmp_path / "ledger.json" ),
                                        notify_fn=lambda *a, **k: [], log_fn=lambda *a, **k: None,
                                        report_fn=lambda *a, **k: None,
                                        reconcile_fn=lambda **kw: wr.reconcile_worktrees(
                                            seat_alive_fn=lambda s, p: False, **kw ),
                                        repo_roots=[ repo, b ] )
    out = janitor()
    assert branch_exists( repo, "twin" ) and reachable( repo, a_sha ), out   # A keeps its unmerged twin
    assert not branch_exists( b, "twin" ), out                                # B deletes its merged twin


# ── tag shadowing: a tag with the branch's name fools the ancestry probe ────
def test_tag_named_like_branch_does_not_delete_unmerged( repo ):
    t = add_tree( repo, "seat-f", branch="shadow" )
    g( repo, "tag", "shadow", "wip-v9" )               # tag at a merged commit, same name as the branch
    sha = commit( t, "unmerged.txt" )
    verdict = wr.merge_verdict( repo, "shadow", "wip-v9", wr._default_run )
    print( "merge_verdict with tag shadow ->", verdict )
    out = sweep( repo )
    print( out[ "branches_kept" ], out[ "branches_deleted" ] )
    assert branch_exists( repo, "shadow" ) and reachable( repo, sha )


# ── seat teardown (P3) ──────────────────────────────────────────────────────
def seat_tree( repo, name, owner, branch=None ):
    t = add_tree( repo, name, branch=branch, detach=branch is None )
    g( repo, "worktree", "lock", "--reason", f"lupin-seat:{owner}", t )
    return t


def retire( t, seat ):
    return st.retire_seat_worktree( t, seat_name=seat, alive_fn=lambda s, p: False, wait_seconds=0 )


def test_teardown_keeps_unmerged_named_branch_and_tree( repo ):
    t   = seat_tree( repo, "seat-g", "g", branch="feat-g" )
    sha = commit( t, "g.txt" )
    out = retire( t, "g" )
    assert out[ "kept_reason" ] == "unmerged" and os.path.isdir( t ) and branch_exists( repo, "feat-g" )
    assert "lupin-seat:g" in g( repo, "worktree", "list", "--porcelain" )    # lock intact


def test_teardown_keeps_detached_commit( repo ):
    t   = seat_tree( repo, "seat-h", "h" )
    sha = commit( t, "h.txt" )                          # commit on detached HEAD: only the tree anchors it
    out = retire( t, "h" )
    assert out[ "kept_reason" ] == "unmerged" and os.path.isdir( t )


def test_teardown_keeps_dirty( repo ):
    t = seat_tree( repo, "seat-i", "i", branch="feat-i" )
    with open( os.path.join( t, "base.txt" ), "w" ) as fh: fh.write( "dirty" )
    assert retire( t, "i" )[ "kept_reason" ] == "uncommitted_work" and os.path.isdir( t )


def test_teardown_refuses_another_seats_tree( repo ):
    t = seat_tree( repo, "seat-j", "j", branch="feat-j" )
    assert retire( t, "not-j" )[ "kept_reason" ] == "not_this_seats_tree" and os.path.isdir( t )


def test_teardown_positive_control_removes_and_unlocks( repo ):
    t   = seat_tree( repo, "seat-k", "k", branch="feat-k" )
    out = retire( t, "k" )
    assert out[ "removed" ] and not os.path.isdir( t ) and not branch_exists( repo, "feat-k" ), out
    assert "seat-k" not in g( repo, "worktree", "list", "--porcelain" )


def test_teardown_from_cwd_inside_main_is_noop( repo ):
    assert retire( repo, None )[ "kept_reason" ] == "main_worktree"


# ── tag shadow + upstream: both locks fooled → a branch NOT on the WIP line is deleted ─
def test_tag_shadow_plus_upstream_deletes_branch_not_on_wip( repo, tmp_path ):
    bare = str( tmp_path / "origin.git" )
    g( tmp_path, "init", "-q", "--bare", bare )
    g( repo, "remote", "add", "origin", bare )
    t   = add_tree( repo, "seat-z", branch="shadow2" )
    g( repo, "tag", "shadow2", "wip-v9" )
    sha = commit( t, "not-on-wip.txt" )
    g( t, "push", "-q", "origin", "refs/heads/shadow2:refs/heads/shadow2" )
    g( repo, "fetch", "-q", "origin" )
    g( repo, "config", "branch.shadow2.remote", "origin" ); g( repo, "config", "branch.shadow2.merge", "refs/heads/shadow2" )
    print( "UPSTREAM:", g( repo, "for-each-ref", "--format=%(upstream)", "refs/heads/shadow2" ) )
    out = sweep( repo )
    print( "KEPT:", out[ "branches_kept" ], "REMOTE:", g( repo, "show-ref" ) )
    print( "DELETED:", [ o[ "branch" ] for o in out[ "branches_deleted" ] ],
           "| on WIP:", subprocess.run( [ "git", "merge-base", "--is-ancestor", sha, "wip-v9" ], cwd=repo ).returncode == 0,
           "| reachable only via:", g( repo, "for-each-ref", "--contains", sha, "--format=%(refname)" ) )
    assert branch_exists( repo, "shadow2" ), "deleted a branch whose commits are NOT on the WIP line"


# ── BLOCKER candidate: seat teardown + a tag named like the seat's branch ────
@pytest.mark.parametrize( "with_upstream", [ False, True ] )
def test_teardown_tag_shadow_never_loses_unmerged_commit( repo, tmp_path, with_upstream ):
    t   = seat_tree( repo, "seat-s", "s", branch="feat-s" )
    g( repo, "tag", "feat-s", "wip-v9" )               # e.g. a salvage/marker tag reusing the name
    sha = commit( t, "not-on-wip.txt" )
    if with_upstream:
        bare = str( tmp_path / "o.git" ); g( tmp_path, "init", "-q", "--bare", bare )
        g( repo, "remote", "add", "origin", bare )
        g( t, "push", "-q", "origin", "refs/heads/feat-s:refs/heads/feat-s" )
        g( repo, "fetch", "-q", "origin" )
        g( repo, "config", "branch.feat-s.remote", "origin" ); g( repo, "config", "branch.feat-s.merge", "refs/heads/feat-s" )
    out = retire( t, "s" )
    print( f"\nUPSTREAM={with_upstream} removed={out[ 'removed' ]} kept={out[ 'kept_reason' ]} "
           f"branch_outcome={out[ 'branch_outcome' ]} tree_exists={os.path.isdir( t )} "
           f"local_branch={branch_exists( repo, 'feat-s' )} refs_containing={g( repo, 'for-each-ref', '--contains', sha, '--format=%(refname)' ).split()}" )
    assert branch_exists( repo, "feat-s" ), "local branch holding a commit NOT on the WIP line was deleted"
