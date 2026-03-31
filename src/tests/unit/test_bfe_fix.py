"""
Unit tests for Bug Fix Expediter Phase 4: Fix Phase (Coder + Tester).

Tests fix prompt construction, coder/tester options, verification loop,
plan writer updates, and integration flow.
"""

import json
import os
import asyncio
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cosa.agents.bug_fix_expediter.state import (
    BFEPhase,
    DeadJobContext,
    DiagnosisResult,
    ProposedFix,
    FixResult,
)
from cosa.agents.bug_fix_expediter.config import BugFixExpediterConfig
from cosa.agents.bug_fix_expediter.prompts.fix import (
    CODER_SYSTEM_PROMPT,
    TESTER_SYSTEM_PROMPT,
    build_fix_prompt,
    build_verification_prompt,
    build_redelegation_prompt,
)
from cosa.agents.bug_fix_expediter.plan_writer import PlanWriter
from cosa.agents.bug_fix_expediter.orchestrator import (
    BFEOrchestrator,
    SDK_AVAILABLE,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def dead_job_context():
    return DeadJobContext(
        id_hash="dr-abc12345::user1", job_type="deep_research",
        user_id="user1", user_email="test@example.com", session_id="wise-penguin",
        status="failed", question_text="What is quantum computing?",
        error="KeyError: 'missing_config_key'",
        stack_trace="Traceback:\n  File \"cli.py\", line 42",
    )


@pytest.fixture
def diagnosis():
    return DiagnosisResult(
        root_cause="Missing config key in INI", error_category="config",
        confidence=0.85, evidence=[ "KeyError at cli.py:42" ],
        affected_components=[ "src/conf/lupin-app.ini" ],
    )


@pytest.fixture
def selected_fix():
    return ProposedFix(
        title="Add missing key to INI", description="Add 'missing_config_key = default_value' to INI",
        fix_type="config_change", confidence=0.9, risk_level="low",
        estimated_effort="minimal",
        changes=[ { "file": "src/conf/lupin-app.ini", "action": "modify", "description": "Add missing key" } ],
    )


@pytest.fixture
def config():
    return BugFixExpediterConfig()


@pytest.fixture
def orchestrator( dead_job_context, config ):
    return BFEOrchestrator(
        dead_job_context=dead_job_context, extra_context="",
        config=config, session_id="wise-penguin", job_id="bfe-test123",
        debug=True,
    )


# =============================================================================
# 1. Fix Prompt Construction (4 tests)
# =============================================================================

class TestFixPrompts:

    def test_fix_prompt_includes_changes_table( self, selected_fix, diagnosis, dead_job_context ):
        prompt = build_fix_prompt( selected_fix, diagnosis, dead_job_context )
        assert "lupin-app.ini" in prompt
        assert "modify" in prompt
        assert "Add missing key" in prompt

    def test_fix_prompt_includes_diagnosis( self, selected_fix, diagnosis, dead_job_context ):
        prompt = build_fix_prompt( selected_fix, diagnosis, dead_job_context )
        assert "Missing config key" in prompt
        assert "config" in prompt

    def test_verification_prompt_includes_coder_output( self, selected_fix ):
        prompt = build_verification_prompt( selected_fix, "Added key to INI file", [ "lupin-app.ini" ] )
        assert "Added key to INI file" in prompt
        assert "lupin-app.ini" in prompt
        assert "PASS or FAIL" in prompt

    def test_redelegation_prompt_includes_feedback( self, selected_fix ):
        prompt = build_redelegation_prompt( selected_fix, "Prior changes", "AssertionError: key not found", 2 )
        assert "iteration 2" in prompt
        assert "AssertionError" in prompt
        assert "Do NOT modify test files" in prompt


# =============================================================================
# 2. Coder/Tester Options (2 tests)
# =============================================================================

class TestAgentOptions:

    @pytest.mark.skipif( not SDK_AVAILABLE, reason="Claude Agent SDK not installed" )
    def test_coder_options_accept_edits( self, orchestrator ):
        from cosa.agents.swe_team.safety_limits import SafetyGuard
        guard = SafetyGuard()
        mock_cosa = MagicMock()
        mock_cosa.ask_confirmation = AsyncMock( return_value=True )

        opts = orchestrator._build_coder_options( guard, mock_cosa )
        assert opts.permission_mode == "acceptEdits"
        assert opts.model == "claude-sonnet-4-6"
        assert "Edit" in opts.tools

    @pytest.mark.skipif( not SDK_AVAILABLE, reason="Claude Agent SDK not installed" )
    def test_tester_options_accept_edits( self, orchestrator ):
        from cosa.agents.swe_team.safety_limits import SafetyGuard
        guard = SafetyGuard()
        mock_cosa = MagicMock()
        mock_cosa.ask_confirmation = AsyncMock( return_value=True )

        opts = orchestrator._build_tester_options( guard, mock_cosa )
        assert opts.permission_mode == "acceptEdits"
        assert opts.model == "claude-sonnet-4-6"


# =============================================================================
# 3. FixResult Construction (3 tests)
# =============================================================================

class TestFixResult:

    def test_fix_result_success( self ):
        result = FixResult( applied=True, success=True, details="Fixed on iteration 1", retry_eligible=True )
        assert result.applied
        assert result.success
        assert result.retry_eligible

    def test_fix_result_failure( self ):
        result = FixResult( applied=False, success=False, details="Coder failed" )
        assert not result.applied
        assert not result.retry_eligible

    def test_fix_result_safety_limit( self ):
        result = FixResult( applied=False, success=False, details="Safety limit: timeout exceeded" )
        assert "Safety limit" in result.details


# =============================================================================
# 4. Tester Verification (4 tests, mock sdk_query + run_pytest)
# =============================================================================

class TestVerification:

    @pytest.mark.skipif( not SDK_AVAILABLE, reason="Claude Agent SDK not installed" )
    def test_tester_pass_confirmed_by_pytest( self, orchestrator, selected_fix ):
        from claude_agent_sdk import AssistantMessage, TextBlock
        from cosa.agents.swe_team.safety_limits import SafetyGuard

        async def mock_gen( prompt, options ):
            yield AssistantMessage( content=[ TextBlock( text="All tests pass. PASS." ) ], model="sonnet" )

        guard = SafetyGuard()
        mock_cosa = MagicMock()

        with patch( "cosa.agents.bug_fix_expediter.orchestrator.sdk_query", side_effect=mock_gen ):
            # No test files created → relies on tester self-report
            passed, output = asyncio.get_event_loop().run_until_complete(
                orchestrator._verify_fix( MagicMock(), selected_fix, "Coder output", [ "file.py" ], guard, mock_cosa )
            )

        assert passed
        assert "pass" in output.lower()

    @pytest.mark.skipif( not SDK_AVAILABLE, reason="Claude Agent SDK not installed" )
    def test_tester_fail( self, orchestrator, selected_fix ):
        from claude_agent_sdk import AssistantMessage, TextBlock
        from cosa.agents.swe_team.safety_limits import SafetyGuard

        async def mock_gen( prompt, options ):
            yield AssistantMessage( content=[ TextBlock( text="Tests FAIL. AssertionError." ) ], model="sonnet" )

        guard = SafetyGuard()
        mock_cosa = MagicMock()

        with patch( "cosa.agents.bug_fix_expediter.orchestrator.sdk_query", side_effect=mock_gen ):
            passed, output = asyncio.get_event_loop().run_until_complete(
                orchestrator._verify_fix( MagicMock(), selected_fix, "Coder output", [ "file.py" ], guard, mock_cosa )
            )

        assert not passed

    @pytest.mark.skipif( not SDK_AVAILABLE, reason="Claude Agent SDK not installed" )
    def test_pytest_override_tester_claim( self, orchestrator, selected_fix ):
        """Independent pytest OVERRIDES tester's self-report."""
        from claude_agent_sdk import AssistantMessage, TextBlock, ToolUseBlock
        from cosa.agents.swe_team.safety_limits import SafetyGuard
        from cosa.agents.swe_team.test_runner import TestRunResult

        async def mock_gen( prompt, options ):
            # Tester claims pass
            yield AssistantMessage( content=[
                ToolUseBlock( id="t1", name="Write", input={ "file_path": "/tmp/test_fix.py", "content": "pass" } ),
                TextBlock( text="All tests pass. PASS." ),
            ], model="sonnet" )

        mock_pytest_result = MagicMock( spec=TestRunResult )
        mock_pytest_result.passed       = False  # pytest says FAIL
        mock_pytest_result.passed_count = 0
        mock_pytest_result.total_tests  = 1

        guard = SafetyGuard()
        mock_cosa = MagicMock()

        with patch( "cosa.agents.bug_fix_expediter.orchestrator.sdk_query", side_effect=mock_gen ):
            with patch( "cosa.agents.bug_fix_expediter.orchestrator.run_pytest", new_callable=AsyncMock, return_value=mock_pytest_result ):
                with patch( "cosa.agents.bug_fix_expediter.orchestrator.post_tool_hook", new_callable=AsyncMock ):
                    passed, output = asyncio.get_event_loop().run_until_complete(
                        orchestrator._verify_fix( MagicMock(), selected_fix, "Coder output", [ "file.py" ], guard, mock_cosa )
                    )

        assert not passed  # pytest override

    def test_verification_error_returns_false( self, orchestrator, selected_fix ):
        from cosa.agents.swe_team.safety_limits import SafetyGuard
        guard = SafetyGuard()
        mock_cosa = MagicMock()

        with patch( "cosa.agents.bug_fix_expediter.orchestrator.sdk_query", side_effect=RuntimeError( "SDK error" ) ):
            passed, output = asyncio.get_event_loop().run_until_complete(
                orchestrator._verify_fix( MagicMock(), selected_fix, "output", [], guard, mock_cosa )
            )

        assert not passed
        assert "error" in output.lower()


# =============================================================================
# 5. Retry Loop (5 tests)
# =============================================================================

class TestRetryLoop:

    @pytest.mark.skipif( not SDK_AVAILABLE, reason="Claude Agent SDK not installed" )
    def test_pass_on_first_try( self, orchestrator, diagnosis, selected_fix ):
        """Coder succeeds, tester passes → FixResult(applied=True, success=True)."""
        with patch.object( orchestrator, "_delegate_to_coder", new_callable=AsyncMock, return_value=( "Fixed it", [ "file.py" ] ) ):
            with patch.object( orchestrator, "_verify_fix", new_callable=AsyncMock, return_value=( True, "All tests pass" ) ):
                with patch.object( PlanWriter, "update_implementation_log" ):
                    result = asyncio.get_event_loop().run_until_complete(
                        orchestrator.run_fix( diagnosis, selected_fix, "/tmp/plan.md" )
                    )

        assert result.applied
        assert result.success

    @pytest.mark.skipif( not SDK_AVAILABLE, reason="Claude Agent SDK not installed" )
    def test_fail_then_pass( self, orchestrator, diagnosis, selected_fix ):
        """First verification fails, redelegation succeeds on second try."""
        orchestrator.config.max_fix_attempts = 2

        verify_calls = [ 0 ]

        async def mock_verify( *args, **kwargs ):
            verify_calls[ 0 ] += 1
            if verify_calls[ 0 ] == 1:
                return ( False, "Tests failed" )
            return ( True, "All tests pass" )

        with patch.object( orchestrator, "_delegate_to_coder", new_callable=AsyncMock, return_value=( "Fixed it", [ "file.py" ] ) ):
            with patch.object( orchestrator, "_verify_fix", side_effect=mock_verify ):
                with patch.object( PlanWriter, "update_implementation_log" ):
                    result = asyncio.get_event_loop().run_until_complete(
                        orchestrator.run_fix( diagnosis, selected_fix, "/tmp/plan.md" )
                    )

        assert result.applied
        assert result.success
        assert verify_calls[ 0 ] == 2

    @pytest.mark.skipif( not SDK_AVAILABLE, reason="Claude Agent SDK not installed" )
    def test_max_iterations_escalation( self, orchestrator, diagnosis, selected_fix ):
        """All iterations fail → escalation presented."""
        orchestrator.config.max_fix_attempts = 1

        mock_cosa = MagicMock()
        mock_cosa.present_choices = AsyncMock( return_value={
            "answers": { "Fix Escalation": "Reject fix" }
        } )

        with patch.object( orchestrator, "_delegate_to_coder", new_callable=AsyncMock, return_value=( "Tried", [ "file.py" ] ) ):
            with patch.object( orchestrator, "_verify_fix", new_callable=AsyncMock, return_value=( False, "Tests failed" ) ):
                with patch( "cosa.agents.bug_fix_expediter.orchestrator.BFEOrchestrator.run_fix.__module__" ):
                    with patch.object( PlanWriter, "update_implementation_log" ):
                        # Patch cosa_interface in the orchestrator's run_fix context
                        with patch( "cosa.agents.bug_fix_expediter.cosa_interface", mock_cosa ):
                            result = asyncio.get_event_loop().run_until_complete(
                                orchestrator.run_fix( diagnosis, selected_fix, "/tmp/plan.md" )
                            )

        assert not result.success

    @pytest.mark.skipif( not SDK_AVAILABLE, reason="Claude Agent SDK not installed" )
    def test_cancellation_during_loop( self, orchestrator, diagnosis, selected_fix ):
        """Cancellation mid-loop → returns partial result."""
        async def mock_coder( *args, **kwargs ):
            orchestrator._stop_requested = True
            return ( "Partial output", [ "file.py" ] )

        with patch.object( orchestrator, "_delegate_to_coder", side_effect=mock_coder ):
            with patch.object( PlanWriter, "update_implementation_log" ):
                result = asyncio.get_event_loop().run_until_complete(
                    orchestrator.run_fix( diagnosis, selected_fix, "/tmp/plan.md" )
                )

        assert result.applied  # Coder ran
        assert not result.success  # But cancelled before verification

    def test_sdk_unavailable( self, orchestrator, diagnosis, selected_fix ):
        """SDK not available → graceful failure."""
        with patch( "cosa.agents.bug_fix_expediter.orchestrator.SDK_AVAILABLE", False ):
            result = asyncio.get_event_loop().run_until_complete(
                orchestrator.run_fix( diagnosis, selected_fix, "/tmp/plan.md" )
            )

        assert not result.applied
        assert "SDK not installed" in result.details


# =============================================================================
# 6. Plan Writer Update (4 tests)
# =============================================================================

class TestPlanWriterUpdate:

    def _create_plan( self, tmpdir, dead_job_context, diagnosis ):
        """Helper: write a plan file and return its path."""
        with patch( "cosa.utils.util.get_project_root", return_value=tmpdir ):
            writer = PlanWriter( user_email="test@test.com" )
            fix = ProposedFix(
                title="Test fix", description="Fix it",
                fix_type="config_change", confidence=0.9,
            )
            return writer.write_plan( dead_job_context, diagnosis, [ fix ] )

    def test_implementation_log_replaced( self, dead_job_context, diagnosis ):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch( "cosa.utils.util.get_project_root", return_value=tmpdir ):
                plan_path = self._create_plan( tmpdir, dead_job_context, diagnosis )
                writer = PlanWriter( user_email="test@test.com" )
                fr = FixResult( applied=True, success=True, details="All good" )
                writer.update_implementation_log( plan_path, fr, [ "file.py" ], "Fixed the thing" )

                content = open( plan_path ).read()
                assert "Applied — Success" in content
                assert "(Phase 4 — populated after fix is applied)" not in content

    def test_files_changed_listed( self, dead_job_context, diagnosis ):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch( "cosa.utils.util.get_project_root", return_value=tmpdir ):
                plan_path = self._create_plan( tmpdir, dead_job_context, diagnosis )
                writer = PlanWriter( user_email="test@test.com" )
                fr = FixResult( applied=True, success=True, details="Done" )
                writer.update_implementation_log( plan_path, fr, [ "a.py", "b.py" ], "output" )

                content = open( plan_path ).read()
                assert "a.py" in content
                assert "b.py" in content

    def test_coder_output_included( self, dead_job_context, diagnosis ):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch( "cosa.utils.util.get_project_root", return_value=tmpdir ):
                plan_path = self._create_plan( tmpdir, dead_job_context, diagnosis )
                writer = PlanWriter( user_email="test@test.com" )
                fr = FixResult( applied=True, success=True, details="OK" )
                writer.update_implementation_log( plan_path, fr, [], "Added key to config" )

                content = open( plan_path ).read()
                assert "Added key to config" in content

    def test_failure_status( self, dead_job_context, diagnosis ):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch( "cosa.utils.util.get_project_root", return_value=tmpdir ):
                plan_path = self._create_plan( tmpdir, dead_job_context, diagnosis )
                writer = PlanWriter( user_email="test@test.com" )
                fr = FixResult( applied=False, success=False, details="Coder crashed" )
                writer.update_implementation_log( plan_path, fr, [], "" )

                content = open( plan_path ).read()
                assert "Failed — Failure" in content


# =============================================================================
# 7. Integration Flow (3 tests)
# =============================================================================

class TestIntegrationFlow:

    def test_no_fix_selected( self ):
        """When no fix is selected, FixResult should indicate not applied."""
        result = FixResult( applied=False, success=False, details="No fix selected" )
        assert not result.applied
        assert "No fix selected" in result.details

    @pytest.mark.skipif( not SDK_AVAILABLE, reason="Claude Agent SDK not installed" )
    def test_run_fix_happy_path( self, orchestrator, diagnosis, selected_fix ):
        """Full happy path with mocked SDK."""
        with patch.object( orchestrator, "_delegate_to_coder", new_callable=AsyncMock, return_value=( "Done", [ "f.py" ] ) ):
            with patch.object( orchestrator, "_verify_fix", new_callable=AsyncMock, return_value=( True, "PASS" ) ):
                with patch.object( PlanWriter, "update_implementation_log" ):
                    result = asyncio.get_event_loop().run_until_complete(
                        orchestrator.run_fix( diagnosis, selected_fix, "/tmp/plan.md" )
                    )

        assert result.applied
        assert result.success
        assert result.retry_eligible

    def test_run_fix_sdk_unavailable_graceful( self, orchestrator, diagnosis, selected_fix ):
        with patch( "cosa.agents.bug_fix_expediter.orchestrator.SDK_AVAILABLE", False ):
            result = asyncio.get_event_loop().run_until_complete(
                orchestrator.run_fix( diagnosis, selected_fix, "/tmp/plan.md" )
            )
        assert not result.applied
