"""
Unit tests for Bug Fix Expediter Phase 5: Trust Proxy + Git Strategy.

Tests orchestrator proxy initialization, run_git_strategy branching,
slug generation, plan writer git references update, and FixResult git fields.
"""

import asyncio
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cosa.agents.bug_fix_expediter.state import (
    BFEPhase,
    DeadJobContext,
    FixResult,
)
from cosa.agents.bug_fix_expediter.config import BugFixExpediterConfig
from cosa.agents.bug_fix_expediter.orchestrator import BFEOrchestrator
from cosa.agents.bug_fix_expediter.plan_writer import PlanWriter


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def dead_job_context():
    return DeadJobContext(
        id_hash       = "dr-abc12345::u1",
        job_type      = "deep_research",
        user_id       = "u1",
        user_email    = "test@example.com",
        session_id    = "wise-penguin",
        status        = "failed",
        question_text = "test",
    )


@pytest.fixture
def orchestrator( dead_job_context ):
    return BFEOrchestrator(
        dead_job_context = dead_job_context,
        extra_context    = "",
        config           = BugFixExpediterConfig(),   # trust_mode defaults to "shadow"
        session_id       = "wise-penguin",
        job_id           = "bfe-test123",
        debug            = False,
    )


@pytest.fixture
def successful_fix_result():
    return FixResult( applied=True, success=True, details="Fixed null pointer in auth module" )


@pytest.fixture
def failed_fix_result():
    return FixResult( applied=True, success=False, details="Tests still failing after 3 attempts" )


# =============================================================================
# Proxy initialization
# =============================================================================

def test_proxy_init_shadow_mode_default( orchestrator ):
    """Default trust_mode=shadow should either init proxy or fall back to None."""
    # Either import succeeds and proxy is set, or it fails gracefully
    # In either case: last_files_changed must be an empty list
    assert orchestrator.last_files_changed == []
    # If proxy was initialized, it should be in shadow mode
    if orchestrator.proxy is not None:
        assert orchestrator.proxy.trust_mode == "shadow"


def test_proxy_init_exception_falls_back_to_none( dead_job_context ):
    """If EngineeringStrategy constructor raises, proxy should be None (safe default)."""
    import cosa.agents.swe_team.proxy.engineering_strategy as es_module
    with patch.object( es_module, "EngineeringStrategy", side_effect=Exception( "boom" ) ):
        orch = BFEOrchestrator(
            dead_job_context = dead_job_context,
            extra_context    = "",
            config           = BugFixExpediterConfig(),
            session_id       = "s1",
            job_id           = "j1",
            debug            = False,
        )
    assert orch.proxy is None
    assert orch.last_files_changed == []
    # Trust level resolution still works (returns L1)
    assert orch._resolve_trust_level() == 1


# =============================================================================
# run_git_strategy guards
# =============================================================================

def test_run_git_strategy_skips_when_fix_not_success( orchestrator, failed_fix_result ):
    """Guard: if fix.success is False, skip git entirely and return unchanged."""
    with patch( "cosa.agents.bug_fix_expediter.git_ops.GitOps" ) as MockGitOps:
        result = asyncio.get_event_loop().run_until_complete( orchestrator.run_git_strategy(
            failed_fix_result, [ "file.py" ], "/tmp/plan.md"
        ) )
    assert result is failed_fix_result
    assert result.git_strategy is None
    MockGitOps.assert_not_called()


def test_run_git_strategy_skips_when_no_files( orchestrator, successful_fix_result ):
    """Guard: if files_changed is empty, skip git entirely."""
    with patch( "cosa.agents.bug_fix_expediter.git_ops.GitOps" ) as MockGitOps:
        result = asyncio.get_event_loop().run_until_complete( orchestrator.run_git_strategy(
            successful_fix_result, [], "/tmp/plan.md"
        ) )
    assert result.git_strategy is None
    MockGitOps.assert_not_called()


# =============================================================================
# Trust level resolution
# =============================================================================

def test_resolve_trust_level_no_proxy_returns_l1( orchestrator ):
    """Without a proxy, trust level defaults to L1 (conservative)."""
    orchestrator.proxy = None
    assert orchestrator._resolve_trust_level() == 1


def test_resolve_trust_level_proxy_without_tracker_returns_l1( orchestrator ):
    """Proxy missing trust_tracker attr → L1 fallback."""
    mock_proxy = MagicMock( spec=[] )   # no trust_tracker attr
    orchestrator.proxy = mock_proxy
    assert orchestrator._resolve_trust_level() == 1


def test_resolve_trust_level_reads_get_level_method( orchestrator ):
    """If tracker exposes get_level(category), use its return value."""
    mock_tracker = MagicMock()
    mock_tracker.get_level.return_value = 3
    mock_proxy = MagicMock( trust_tracker=mock_tracker )
    orchestrator.proxy = mock_proxy
    assert orchestrator._resolve_trust_level() == 3
    mock_tracker.get_level.assert_called_with( "engineering" )


# =============================================================================
# Slug generation
# =============================================================================

def test_generate_slug_format():
    """Slug has fix/YYYY-MM-DD-{word1-word2-word3} format."""
    slug = BFEOrchestrator._generate_slug( "Fix null pointer in auth module" )
    assert slug.startswith( "fix/" )
    # Date should be in YYYY-MM-DD form
    parts = slug.split( "/" )[ 1 ].split( "-" )
    assert len( parts ) >= 4   # year-month-day-word1[-word2-word3]
    # Last 3 words from cleaned text
    assert "fix" in slug
    assert "null" in slug
    assert "pointer" in slug


def test_generate_slug_strips_punctuation():
    """Slug strips punctuation from input text."""
    slug = BFEOrchestrator._generate_slug( "Fix: auth!!! module (broken)" )
    # No punctuation in the word-portion of the slug
    word_portion = "-".join( slug.split( "/" )[ 1 ].split( "-" )[ 3: ] )
    assert "!" not in word_portion
    assert ":" not in word_portion
    assert "(" not in word_portion


def test_generate_slug_empty_text_yields_fix():
    """Empty text should fall back to 'fix'."""
    slug = BFEOrchestrator._generate_slug( "" )
    assert slug.endswith( "-fix" )


# =============================================================================
# plan_writer.update_git_references
# =============================================================================

def test_update_git_references_replaces_placeholder():
    """update_git_references rewrites the Phase 5 placeholder with git details."""
    with tempfile.NamedTemporaryFile( mode="w", suffix=".md", delete=False ) as f:
        f.write( "# Plan\n\n## Git References\n(Phase 5 — populated after git operations)\n\n---\n" )
        plan_path = f.name

    try:
        result = FixResult(
            applied       = True,
            success       = True,
            git_strategy  = "branch_and_pr",
            commit_hash   = "abc1234",
            branch_name   = "fix/2026-04-05-test",
            pr_url        = "https://github.com/foo/bar/pull/42",
        )
        writer = PlanWriter( user_email="test@test.com", debug=False )
        writer.update_git_references( plan_path, result )

        content = open( plan_path ).read()
        assert "(Phase 5 — populated after git operations)" not in content
        assert "**Strategy**: branch_and_pr" in content
        assert "**Commit**: abc1234" in content
        assert "**Branch**: fix/2026-04-05-test" in content
        assert "**PR**: https://github.com/foo/bar/pull/42" in content
    finally:
        os.unlink( plan_path )


def test_update_git_references_no_op_on_missing_file():
    """update_git_references silently no-ops if plan file doesn't exist."""
    result = FixResult( applied=True, success=True, git_strategy="commit_only", commit_hash="abc" )
    writer = PlanWriter( user_email="test@test.com", debug=False )
    # Should not raise
    writer.update_git_references( "/nonexistent/plan/path.md", result )


def test_update_git_references_no_op_if_placeholder_missing():
    """update_git_references no-ops if the placeholder is already replaced / absent."""
    with tempfile.NamedTemporaryFile( mode="w", suffix=".md", delete=False ) as f:
        f.write( "# Plan\n\n## Git References\n**Strategy**: commit_only\n" )   # already populated
        plan_path = f.name

    try:
        original_content = open( plan_path ).read()
        result = FixResult( applied=True, success=True, git_strategy="branch_and_pr", commit_hash="xyz" )
        writer = PlanWriter( user_email="test@test.com", debug=False )
        writer.update_git_references( plan_path, result )
        # Content unchanged
        assert open( plan_path ).read() == original_content
    finally:
        os.unlink( plan_path )


def test_footer_includes_git_references_placeholder():
    """_render_footer now includes the Phase 5 Git References section."""
    footer = PlanWriter._render_footer()
    assert "## Git References" in footer
    assert "(Phase 5 — populated after git operations)" in footer
    # Previous sections preserved
    assert "## Implementation Log" in footer
    assert "## Retry Result" in footer


# =============================================================================
# FixResult git fields
# =============================================================================

def test_fix_result_git_fields_default_none():
    """FixResult git_* fields default to None."""
    result = FixResult( applied=True, success=True )
    assert result.git_strategy is None
    assert result.commit_hash is None
    assert result.branch_name is None
    assert result.pr_url is None


def test_fix_result_git_fields_accept_values():
    """FixResult git_* fields accept string values."""
    result = FixResult(
        applied=True, success=True,
        git_strategy="branch_and_pr",
        commit_hash="abc123",
        branch_name="fix/2026-04-05-bug",
        pr_url="https://github.com/foo/bar/pull/1",
    )
    assert result.git_strategy == "branch_and_pr"
    assert result.commit_hash == "abc123"
    assert result.branch_name == "fix/2026-04-05-bug"
    assert result.pr_url == "https://github.com/foo/bar/pull/1"


# =============================================================================
# BFEPhase enum
# =============================================================================

def test_bfe_phase_has_committing():
    """COMMITTING phase was added for Phase 5."""
    assert BFEPhase.COMMITTING.value == "committing"
    assert len( BFEPhase ) == 10
