"""
Unit tests for the Worktree Artifacts block in TFE/BFE completion abstracts.

Both orchestrators expose `render_worktree_artifacts_abstract` — pure
function from state to list-of-markdown-lines. These tests lock down the
content so the completion notification code path (which only runs on a
real Phase 5 completion, ~25 minutes into a TFE run) can't silently break.

Filed 2026-04-18 Session be57a252.
"""

import os
from types import SimpleNamespace

import pytest

from cosa.agents.test_fix_expediter.orchestrator import TFEOrchestrator
from cosa.agents.bug_fix_expediter.orchestrator import BFEOrchestrator


# ==================================================================
# TFE: multi-cluster, uses orchestrator instance state
# ==================================================================

def _fake_tfe_orch( selected_fixes=None, fix_results=None, files_map=None,
                    branch_name=None, commit_hashes=None, pr_url=None ) -> SimpleNamespace:
    """
    Shape a minimal TFEOrchestrator-lookalike. The method we're testing is
    an instance method bound to `self`; we call it unbound via the class
    so we don't need to construct a full orchestrator.
    """
    return SimpleNamespace(
        selected_fixes            = selected_fixes or [],
        fix_results               = fix_results or [],
        files_changed_by_cluster  = files_map or {},
        branch_name               = branch_name,
        commit_hashes             = commit_hashes or [],
        pr_url                    = pr_url,
    )


def _fake_proposed( cluster_id: str, title: str ) -> SimpleNamespace:
    return SimpleNamespace( cluster_id=cluster_id, title=title )


def _fake_fix_result( success: bool ) -> SimpleNamespace:
    return SimpleNamespace( success=success )


def _call_tfe( orch, job_id: str = "tfe-deadbeef" ) -> list:
    """Invoke the unbound method against a fake self."""
    return TFEOrchestrator.render_worktree_artifacts_abstract( orch, job_id )


class TestTFERenderWorktreeArtifacts:

    def test_empty_selected_fixes_returns_empty_list( self ):
        orch = _fake_tfe_orch( selected_fixes=[] )
        assert _call_tfe( orch ) == []

    def test_single_successful_fix_renders_header_and_bullet( self ):
        orch = _fake_tfe_orch(
            selected_fixes = [ _fake_proposed( "C2", "Add PRODUCT_NAMES entry" ) ],
            fix_results    = [ _fake_fix_result( success=True ) ],
            files_map      = { "C2": [ "src/x.py" ] },
        )
        lines = _call_tfe( orch, "tfe-abc" )
        out   = "\n".join( lines )
        assert "**Worktree Artifacts**" in out
        assert "tfe-abc" in out
        assert "C2" in out
        assert "✓" in out
        assert "files=1" in out

    def test_failed_fix_uses_x_mark( self ):
        orch = _fake_tfe_orch(
            selected_fixes = [ _fake_proposed( "C3", "stale count" ) ],
            fix_results    = [ _fake_fix_result( success=False ) ],
        )
        out = "\n".join( _call_tfe( orch ) )
        assert "✗" in out
        assert "✓" not in out

    def test_mixed_outcomes( self ):
        orch = _fake_tfe_orch(
            selected_fixes = [
                _fake_proposed( "C1", "first" ),
                _fake_proposed( "C2", "second" ),
                _fake_proposed( "C3", "third" ),
            ],
            fix_results = [
                _fake_fix_result( success=True ),
                _fake_fix_result( success=False ),
                _fake_fix_result( success=True ),
            ],
            files_map = { "C1": [ "a.py", "b.py" ], "C3": [ "c.py" ] },
        )
        out = "\n".join( _call_tfe( orch ) )
        assert out.count( "✓" ) == 2
        assert out.count( "✗" ) == 1
        assert "files=2" in out  # C1
        assert "files=1" in out  # C3
        # C2 has no files — suffix should be absent for that line
        c2_line = [ l for l in _call_tfe( orch ) if l.startswith( "- **C2**" ) ][ 0 ]
        assert "files=" not in c2_line

    def test_git_outcome_l1_commits_only( self ):
        orch = _fake_tfe_orch(
            selected_fixes = [ _fake_proposed( "C1", "x" ) ],
            fix_results    = [ _fake_fix_result( success=True ) ],
            commit_hashes  = [ "3f2a19c9deadbeefcafe", "8b47cd2bad00f00d" ],
        )
        out = "\n".join( _call_tfe( orch ) )
        assert "**Commits**: 2" in out
        assert "`3f2a19c9`" in out
        assert "`8b47cd2b`" in out
        assert "**Branch**" not in out  # L1 commit_only: no branch
        assert "**PR**" not in out

    def test_git_outcome_l3_branch_and_pr( self ):
        orch = _fake_tfe_orch(
            selected_fixes = [ _fake_proposed( "C1", "x" ) ],
            fix_results    = [ _fake_fix_result( success=True ) ],
            branch_name    = "fix/2026-04-18-stuff",
            commit_hashes  = [ "abc12345def" ],
            pr_url         = "https://github.com/deepily/lupin/pull/42",
        )
        out = "\n".join( _call_tfe( orch ) )
        assert "**Branch**: `fix/2026-04-18-stuff`" in out
        assert "**PR**: https://github.com/deepily/lupin/pull/42" in out
        assert "**Commits**: 1" in out

    def test_inspect_section_always_included( self ):
        orch = _fake_tfe_orch(
            selected_fixes = [ _fake_proposed( "C1", "x" ) ],
            fix_results    = [ _fake_fix_result( success=False ) ],
        )
        out = "\n".join( _call_tfe( orch ) )
        assert "**Inspect**:" in out
        assert "git -C" in out
        assert "log --oneline" in out
        assert "diff --stat origin/main" in out

    def test_commit_list_truncates_at_ten( self ):
        orch = _fake_tfe_orch(
            selected_fixes = [ _fake_proposed( "C1", "x" ) ],
            fix_results    = [ _fake_fix_result( success=True ) ],
            commit_hashes  = [ f"commit_{i:02d}_abcdef" for i in range( 20 ) ],
        )
        lines = _call_tfe( orch )
        # Only first 10 hash bullets
        hash_lines = [ l for l in lines if l.startswith( "- `commit_" ) ]
        assert len( hash_lines ) == 10
        # Header still reports total count
        assert "**Commits**: 20" in "\n".join( lines )

    def test_partial_fix_results_zips_safely( self ):
        # selected_fixes=3, but fix_results only has 2 — zip stops at shorter.
        # This is a defensive check for mid-crash state snapshots.
        orch = _fake_tfe_orch(
            selected_fixes = [
                _fake_proposed( "C1", "a" ),
                _fake_proposed( "C2", "b" ),
                _fake_proposed( "C3", "c" ),
            ],
            fix_results = [
                _fake_fix_result( success=True ),
                _fake_fix_result( success=False ),
            ],
        )
        out = "\n".join( _call_tfe( orch ) )
        # Expect C1, C2 rendered; C3 skipped because no matching fix_result
        assert "- **C1**" in out
        assert "- **C2**" in out
        assert "- **C3**" not in out

    def test_long_title_truncated_at_80( self ):
        orch = _fake_tfe_orch(
            selected_fixes = [ _fake_proposed( "C1", "x" * 200 ) ],
            fix_results    = [ _fake_fix_result( success=True ) ],
        )
        out = "\n".join( _call_tfe( orch ) )
        c1_line = [ l for l in _call_tfe( orch ) if "C1" in l ][ 0 ]
        # "x" count in the line must be ≤ 80
        assert c1_line.count( "x" ) <= 80


# ==================================================================
# BFE: single-fix, static method
# ==================================================================

def _fake_bfe_fix_result( commit_hash=None, branch_name=None, git_strategy=None, pr_url=None ) -> SimpleNamespace:
    return SimpleNamespace(
        commit_hash  = commit_hash,
        branch_name  = branch_name,
        git_strategy = git_strategy,
        pr_url       = pr_url,
    )


class TestBFERenderWorktreeArtifacts:

    def test_no_fix_applied_no_commit_returns_empty( self ):
        fr = _fake_bfe_fix_result()
        assert BFEOrchestrator.render_worktree_artifacts_abstract(
            "bfe-xxx", fr, fix_applied=False
        ) == []

    def test_fix_applied_but_no_commit_still_renders( self ):
        # Some paths mark applied without a commit (e.g. dry-run ish)
        fr = _fake_bfe_fix_result()
        lines = BFEOrchestrator.render_worktree_artifacts_abstract(
            "bfe-abc", fr, fix_applied=True
        )
        assert lines
        assert "**Worktree Artifacts**" in "\n".join( lines )

    def test_commit_without_fix_applied_still_renders( self ):
        fr = _fake_bfe_fix_result( commit_hash="abc12345def" )
        lines = BFEOrchestrator.render_worktree_artifacts_abstract(
            "bfe-xyz", fr, fix_applied=False
        )
        assert lines
        out = "\n".join( lines )
        assert "**Commit**: `abc12345`" in out

    def test_l1_commit_only_shows_strategy_and_hash( self ):
        fr = _fake_bfe_fix_result(
            commit_hash  = "deadbeefcafe00",
            git_strategy = "commit_only",
        )
        out = "\n".join(
            BFEOrchestrator.render_worktree_artifacts_abstract( "bfe-1", fr, fix_applied=True )
        )
        assert "**Strategy**: commit_only" in out
        assert "**Commit**: `deadbeef`" in out
        assert "**Branch**" not in out
        assert "**PR**" not in out

    def test_l3_branch_and_pr_shows_all_fields( self ):
        fr = _fake_bfe_fix_result(
            commit_hash  = "abc12345ff",
            branch_name  = "fix/2026-04-18-bfe",
            git_strategy = "branch_and_pr",
            pr_url       = "https://github.com/deepily/lupin/pull/99",
        )
        out = "\n".join(
            BFEOrchestrator.render_worktree_artifacts_abstract( "bfe-2", fr, fix_applied=True )
        )
        assert "**Strategy**: branch_and_pr" in out
        assert "**Branch**: `fix/2026-04-18-bfe`" in out
        assert "**Commit**: `abc12345`" in out
        # BFE helper currently doesn't print pr_url (the outer BFE abstract
        # already prints it earlier via the main "lines" block); verify we
        # don't duplicate here.
        assert "pull/99" not in out

    def test_inspect_section_always_included( self ):
        fr = _fake_bfe_fix_result( commit_hash="x" )
        out = "\n".join(
            BFEOrchestrator.render_worktree_artifacts_abstract( "bfe-k", fr, fix_applied=True )
        )
        assert "**Inspect**:" in out
        assert "git -C" in out


if __name__ == "__main__":
    import sys
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
