#!/usr/bin/env python3
"""
Unit tests for SWE Team Agent — Phase 3 Verification.

Tests VerificationResult model, TestRunner subprocess wrapper,
_verify_result(), _redelegate_with_feedback(), coder-tester loop,
and _build_agent_options() for tester role.

Coverage:
    - TestVerificationResult: model defaults and states (4 tests)
    - TestTestRunner: subprocess parsing and error handling (5 tests)
    - TestVerifyResult: tester delegation outcomes (6 tests)
    - TestRedelegateWithFeedback: augmented prompt and result (4 tests)
    - TestCoderTesterLoop: full iteration cycle (6 tests)
    - TestBuildAgentOptionsTester: tester options config (3 tests)
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cosa.agents.swe_team.config import SweTeamConfig
from cosa.agents.swe_team.safety_limits import SafetyGuard, SafetyLimitError
from cosa.agents.swe_team.state import (
    OrchestratorState,
    TaskSpec,
    DelegationResult,
    VerificationResult,
)
from cosa.agents.swe_team.orchestrator import (
    SweTeamOrchestrator,
    MAX_VERIFICATION_ITERATIONS,
)
from cosa.agents.swe_team.test_runner import (
    TestRunResult,
    run_pytest,
    _parse_pytest_summary,
)


# =============================================================================
# TestVerificationResult
# =============================================================================

class TestVerificationResult:
    """Tests for VerificationResult Pydantic model."""

    def test_default_fields( self ):
        """Default VerificationResult is failed with empty fields."""
        vr = VerificationResult(
            task_index = 0,
            task_title = "Test task",
        )
        assert vr.passed is False
        assert vr.status == "failed"
        assert vr.tester_output == ""
        assert vr.test_run_result is None
        assert vr.test_files_created == []
        assert vr.iterations == 1

    def test_passed_state( self ):
        """VerificationResult with passed=True and status='passed'."""
        vr = VerificationResult(
            task_index    = 1,
            task_title    = "Add endpoint",
            passed        = True,
            status        = "passed",
            tester_output = "All tests pass",
            iterations    = 2,
        )
        assert vr.passed is True
        assert vr.status == "passed"
        assert vr.iterations == 2

    def test_test_run_result_dict( self ):
        """VerificationResult stores test_run_result as dict."""
        vr = VerificationResult(
            task_index      = 0,
            task_title      = "Task",
            test_run_result = {
                "passed"       : True,
                "total_tests"  : 5,
                "passed_count" : 5,
                "failed_count" : 0,
            },
        )
        assert vr.test_run_result[ "passed" ] is True
        assert vr.test_run_result[ "total_tests" ] == 5

    def test_test_files_created_list( self ):
        """VerificationResult tracks test files created."""
        vr = VerificationResult(
            task_index         = 0,
            task_title         = "Task",
            test_files_created = [ "tests/test_auth.py", "tests/test_utils.py" ],
        )
        assert len( vr.test_files_created ) == 2
        assert "tests/test_auth.py" in vr.test_files_created


# =============================================================================
# TestTestRunner
# =============================================================================

class TestTestRunner:
    """Tests for test_runner.py subprocess wrapper."""

    @patch( "cosa.agents.swe_team.test_runner.asyncio.create_subprocess_exec" )
    def test_subprocess_success_parsing( self, mock_exec ):
        """run_pytest parses successful pytest output."""
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (
            b"test_auth.py::test_login PASSED\ntest_auth.py::test_logout PASSED\n\n====== 2 passed in 0.5s ======\n",
            None,
        )
        mock_exec.return_value = mock_proc

        result = asyncio.run( run_pytest( "src/tests/unit/test_auth.py" ) )

        assert result.passed is True
        assert result.passed_count == 2
        assert result.failed_count == 0
        assert result.error_count == 0
        assert result.total_tests == 2
        assert result.timed_out is False

    @patch( "cosa.agents.swe_team.test_runner.asyncio.create_subprocess_exec" )
    def test_subprocess_failure_parsing( self, mock_exec ):
        """run_pytest parses failed pytest output."""
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (
            b"test_auth.py::test_login PASSED\ntest_auth.py::test_logout FAILED\n\n====== 1 passed, 1 failed in 0.5s ======\n",
            None,
        )
        mock_exec.return_value = mock_proc

        result = asyncio.run( run_pytest( "src/tests/unit/test_auth.py" ) )

        assert result.passed is False
        assert result.passed_count == 1
        assert result.failed_count == 1
        assert result.total_tests == 2

    @patch( "cosa.agents.swe_team.test_runner.asyncio.create_subprocess_exec" )
    def test_subprocess_timeout_handling( self, mock_exec ):
        """run_pytest handles timeout gracefully."""
        mock_proc = AsyncMock()
        mock_proc.communicate.side_effect = asyncio.TimeoutError()
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()
        mock_exec.return_value = mock_proc

        result = asyncio.run( run_pytest( "src/tests/", timeout_secs=1 ) )

        assert result.passed is False
        assert result.timed_out is True
        assert "timed out" in result.output

    @patch( "cosa.agents.swe_team.test_runner.asyncio.create_subprocess_exec" )
    def test_output_truncation( self, mock_exec ):
        """run_pytest truncates output to max_output chars."""
        long_output = b"x" * 10000
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = ( long_output, None )
        mock_exec.return_value = mock_proc

        result = asyncio.run( run_pytest( "test.py", max_output=100 ) )

        assert len( result.output ) <= 200  # 100 + truncation message

    @patch( "cosa.agents.swe_team.test_runner.asyncio.create_subprocess_exec" )
    def test_bad_path_graceful_failure( self, mock_exec ):
        """run_pytest returns failure result on subprocess error."""
        mock_exec.side_effect = FileNotFoundError( "No such file" )

        result = asyncio.run( run_pytest( "/nonexistent/path.py" ) )

        assert result.passed is False
        assert result.error_count == 1
        assert "error" in result.output.lower()


# =============================================================================
# TestParseOutput
# =============================================================================

class TestParseOutput:
    """Tests for _parse_pytest_summary helper."""

    def test_parse_all_passed( self ):
        counts = _parse_pytest_summary( "====== 5 passed in 0.3s ======" )
        assert counts[ "passed_count" ] == 5
        assert counts[ "failed_count" ] == 0

    def test_parse_mixed_results( self ):
        counts = _parse_pytest_summary( "3 passed, 2 failed, 1 error in 1.5s" )
        assert counts[ "passed_count" ] == 3
        assert counts[ "failed_count" ] == 2
        assert counts[ "error_count" ] == 1

    def test_parse_no_tests( self ):
        counts = _parse_pytest_summary( "no tests ran" )
        assert counts[ "passed_count" ] == 0
        assert counts[ "failed_count" ] == 0


# =============================================================================
# TestVerifyResult
# =============================================================================

class TestVerifyResult:
    """Tests for orchestrator._verify_result() method."""

    def _make_orchestrator( self ):
        config = SweTeamConfig( dry_run=False )
        return SweTeamOrchestrator(
            task_description = "Add feature X",
            config           = config,
            debug            = False,
        )

    def _make_task_spec( self, title="Test task" ):
        return TaskSpec(
            title         = title,
            objective     = f"Implement {title}",
            output_format = "Modified files",
        )

    def _make_coder_result( self, task_index=0, title="Test task" ):
        return DelegationResult(
            task_index    = task_index,
            task_title    = title,
            status        = "success",
            output        = "Implementation completed successfully",
            files_changed = [ "src/auth.py" ],
            confidence    = 0.8,
        )

    @patch( "cosa.agents.swe_team.orchestrator.sdk_query" )
    def test_passes_on_green_tests( self, mock_query ):
        """_verify_result returns passed=True when tester reports pass."""
        async def mock_messages( **kwargs ):
            from claude_agent_sdk import TextBlock
            yield TextBlock( text="All tests pass. The implementation is correct." )

        mock_query.return_value = mock_messages()

        orch     = self._make_orchestrator()
        spec     = self._make_task_spec()
        result   = self._make_coder_result()
        team_io  = MagicMock()
        team_io.notify_progress = AsyncMock()

        vr = asyncio.run( orch._verify_result( spec, result, 0, team_io ) )

        assert vr.passed is True
        assert vr.status == "passed"

    @patch( "cosa.agents.swe_team.orchestrator.sdk_query" )
    def test_fails_on_red_tests( self, mock_query ):
        """_verify_result returns passed=False when tester reports failure."""
        async def mock_messages( **kwargs ):
            from claude_agent_sdk import TextBlock
            yield TextBlock( text="Tests failed: test_login assertion error" )

        mock_query.return_value = mock_messages()

        orch     = self._make_orchestrator()
        spec     = self._make_task_spec()
        result   = self._make_coder_result()
        team_io  = MagicMock()
        team_io.notify_progress = AsyncMock()

        vr = asyncio.run( orch._verify_result( spec, result, 0, team_io ) )

        assert vr.passed is False
        assert vr.status == "failed"

    @patch( "cosa.agents.swe_team.orchestrator.sdk_query" )
    def test_sets_testing_state( self, mock_query ):
        """_verify_result sets orchestrator to TESTING state."""
        async def mock_messages( **kwargs ):
            from claude_agent_sdk import TextBlock
            yield TextBlock( text="All tests pass." )

        mock_query.return_value = mock_messages()

        orch     = self._make_orchestrator()
        spec     = self._make_task_spec()
        result   = self._make_coder_result()
        team_io  = MagicMock()
        team_io.notify_progress = AsyncMock()

        asyncio.run( orch._verify_result( spec, result, 0, team_io ) )

        # During verification, state should have been TESTING
        # (it may change after, but we check notification was sent)
        team_io.notify_progress.assert_called()

    @patch( "cosa.agents.swe_team.orchestrator.sdk_query" )
    def test_sends_notifications( self, mock_query ):
        """_verify_result sends progress notification."""
        async def mock_messages( **kwargs ):
            from claude_agent_sdk import TextBlock
            yield TextBlock( text="All tests pass." )

        mock_query.return_value = mock_messages()

        orch     = self._make_orchestrator()
        spec     = self._make_task_spec( title="Auth endpoint" )
        result   = self._make_coder_result( title="Auth endpoint" )
        team_io  = MagicMock()
        team_io.notify_progress = AsyncMock()

        asyncio.run( orch._verify_result( spec, result, 0, team_io ) )

        team_io.notify_progress.assert_called_once()
        call_kwargs = team_io.notify_progress.call_args.kwargs
        assert "Auth endpoint" in call_kwargs[ "message" ]
        assert call_kwargs[ "role" ] == "tester"

    @patch( "cosa.agents.swe_team.orchestrator.sdk_query" )
    def test_tracks_test_files( self, mock_query ):
        """_verify_result records test files created by tester."""
        async def mock_messages( **kwargs ):
            from claude_agent_sdk import AssistantMessage, ToolUseBlock, TextBlock

            tool_block = ToolUseBlock(
                id    = "toolu_456",
                name  = "Write",
                input = { "file_path": "src/tests/unit/test_new.py", "content": "# test" },
            )
            text_block = TextBlock( text="All tests pass." )
            msg = AssistantMessage(
                content = [ tool_block, text_block ],
                model   = "claude-sonnet-4-6",
            )
            yield msg

        mock_query.return_value = mock_messages()

        orch     = self._make_orchestrator()
        spec     = self._make_task_spec()
        result   = self._make_coder_result()
        team_io  = MagicMock()
        team_io.notify_progress = AsyncMock()

        vr = asyncio.run( orch._verify_result( spec, result, 0, team_io ) )

        assert "src/tests/unit/test_new.py" in vr.test_files_created

    @patch( "cosa.agents.swe_team.orchestrator.sdk_query" )
    def test_handles_tester_exception( self, mock_query ):
        """_verify_result returns failed result on exception."""
        async def mock_messages( **kwargs ):
            raise RuntimeError( "SDK connection lost" )
            yield  # Make it a generator

        mock_query.return_value = mock_messages()

        orch     = self._make_orchestrator()
        spec     = self._make_task_spec()
        result   = self._make_coder_result()
        team_io  = MagicMock()
        team_io.notify_progress = AsyncMock()

        vr = asyncio.run( orch._verify_result( spec, result, 0, team_io ) )

        assert vr.passed is False
        assert vr.status == "failed"
        assert "error" in vr.tester_output.lower()


# =============================================================================
# TestRedelegateWithFeedback
# =============================================================================

class TestRedelegateWithFeedback:
    """Tests for orchestrator._redelegate_with_feedback() method."""

    def _make_orchestrator( self ):
        config = SweTeamConfig( dry_run=False )
        return SweTeamOrchestrator(
            task_description = "Add feature X",
            config           = config,
            debug            = False,
        )

    def _make_task_spec( self ):
        return TaskSpec(
            title         = "Fix endpoint",
            objective     = "Fix the broken endpoint",
            output_format = "Modified files",
        )

    def _make_coder_result( self ):
        return DelegationResult(
            task_index    = 0,
            task_title    = "Fix endpoint",
            status        = "success",
            output        = "Initial implementation done",
            files_changed = [ "src/routes.py" ],
        )

    @patch( "cosa.agents.swe_team.orchestrator.sdk_query" )
    def test_returns_delegation_result( self, mock_query ):
        """_redelegate_with_feedback returns DelegationResult."""
        async def mock_messages( **kwargs ):
            from claude_agent_sdk import TextBlock
            yield TextBlock( text="Fixed the issue per tester feedback" )

        mock_query.return_value = mock_messages()

        orch        = self._make_orchestrator()
        spec        = self._make_task_spec()
        result      = self._make_coder_result()
        team_io     = MagicMock()
        team_io.notify_progress = AsyncMock()

        new_result = asyncio.run(
            orch._redelegate_with_feedback( spec, 0, result, "test_login failed", 2, team_io )
        )

        assert isinstance( new_result, DelegationResult )
        assert new_result.status == "success"

    @patch( "cosa.agents.swe_team.orchestrator.sdk_query" )
    def test_prompt_contains_feedback( self, mock_query ):
        """Re-delegation prompt includes tester feedback."""
        captured_prompt = None

        async def mock_messages( **kwargs ):
            nonlocal captured_prompt
            prompt_arg = kwargs.get( "prompt", "" )
            # Bug 15 workaround (2026-04-17): prompt is now an async generator
            # yielding SDK message dicts, not a raw string. Extract content.
            if hasattr( prompt_arg, "__aiter__" ):
                collected = []
                async for chunk in prompt_arg:
                    content = chunk.get( "message", {} ).get( "content", "" )
                    if content:
                        collected.append( content )
                captured_prompt = "".join( collected )
            else:
                captured_prompt = prompt_arg
            from claude_agent_sdk import TextBlock
            yield TextBlock( text="Fixed" )

        mock_query.side_effect = lambda **kwargs: mock_messages( **kwargs )

        orch    = self._make_orchestrator()
        spec    = self._make_task_spec()
        result  = self._make_coder_result()
        team_io = MagicMock()
        team_io.notify_progress = AsyncMock()

        asyncio.run(
            orch._redelegate_with_feedback( spec, 0, result, "assertion failed in test_login", 2, team_io )
        )

        assert captured_prompt is not None
        assert "assertion failed in test_login" in captured_prompt

    @patch( "cosa.agents.swe_team.orchestrator.sdk_query" )
    def test_prompt_contains_iteration_number( self, mock_query ):
        """Re-delegation prompt includes iteration number."""
        captured_prompt = None

        async def mock_messages( **kwargs ):
            nonlocal captured_prompt
            prompt_arg = kwargs.get( "prompt", "" )
            # Bug 15 workaround (2026-04-17): prompt is now an async generator
            # yielding SDK message dicts, not a raw string. Extract content.
            if hasattr( prompt_arg, "__aiter__" ):
                collected = []
                async for chunk in prompt_arg:
                    content = chunk.get( "message", {} ).get( "content", "" )
                    if content:
                        collected.append( content )
                captured_prompt = "".join( collected )
            else:
                captured_prompt = prompt_arg
            from claude_agent_sdk import TextBlock
            yield TextBlock( text="Fixed" )

        mock_query.side_effect = lambda **kwargs: mock_messages( **kwargs )

        orch    = self._make_orchestrator()
        spec    = self._make_task_spec()
        result  = self._make_coder_result()
        team_io = MagicMock()
        team_io.notify_progress = AsyncMock()

        asyncio.run(
            orch._redelegate_with_feedback( spec, 0, result, "test failed", 3, team_io )
        )

        assert captured_prompt is not None
        assert "Iteration 3" in captured_prompt

    @patch( "cosa.agents.swe_team.orchestrator.sdk_query" )
    def test_handles_sdk_error( self, mock_query ):
        """_redelegate_with_feedback returns failure on error."""
        async def mock_messages( **kwargs ):
            raise RuntimeError( "SDK error" )
            yield

        mock_query.return_value = mock_messages()

        orch    = self._make_orchestrator()
        spec    = self._make_task_spec()
        result  = self._make_coder_result()
        team_io = MagicMock()
        team_io.notify_progress = AsyncMock()

        new_result = asyncio.run(
            orch._redelegate_with_feedback( spec, 0, result, "test failed", 2, team_io )
        )

        assert new_result.status == "failure"
        assert "SDK error" in new_result.errors[ 0 ]


# =============================================================================
# TestCoderTesterLoop
# =============================================================================

class TestCoderTesterLoop:
    """Tests for the full coder-tester iteration loop in _execute_live."""

    def _make_orchestrator( self, require_test_pass=True ):
        config = SweTeamConfig( dry_run=False, require_test_pass=require_test_pass )
        return SweTeamOrchestrator(
            task_description = "Add feature",
            config           = config,
            debug            = False,
        )

    @patch( "cosa.agents.swe_team.orchestrator.sdk_query" )
    def test_passes_first_try( self, mock_query ):
        """Task passes verification on first try (1 iteration)."""
        call_count = 0

        async def mock_messages( **kwargs ):
            nonlocal call_count
            from claude_agent_sdk import TextBlock
            call_count += 1

            if call_count == 1:
                # Lead decomposition
                task_json = json.dumps( [ {
                    "title"         : "Task 1",
                    "objective"     : "Do 1",
                    "output_format" : "File 1",
                } ] )
                yield TextBlock( text=task_json )
            elif call_count == 2:
                # Coder implementation
                yield TextBlock( text="Implementation done" )
            elif call_count == 3:
                # Tester verification — passes
                yield TextBlock( text="All tests pass. Implementation is correct." )

        mock_query.side_effect = lambda **kwargs: mock_messages( **kwargs )

        orch = self._make_orchestrator()

        with patch( "cosa.agents.swe_team.orchestrator.ProgressLog" ) as MockPL, \
             patch( "cosa.agents.swe_team.orchestrator.FeatureList" ) as MockFL:
            MockPL.return_value = MagicMock()
            MockFL.return_value = MagicMock()
            MockFL.return_value.tasks = []

            team_io = MagicMock()
            team_io.notify_progress  = AsyncMock()
            team_io.ask_confirmation = AsyncMock( return_value=True )
            team_io.get_feedback     = AsyncMock( return_value=None )

            result = asyncio.run( orch._execute_live( team_io ) )

        assert result is not None
        assert len( orch.state[ "verification_results" ] ) == 1
        assert orch.state[ "verification_results" ][ 0 ].passed is True
        assert orch.state[ "total_verification_iterations" ] == 1

    @patch( "cosa.agents.swe_team.orchestrator.sdk_query" )
    def test_retries_on_failure( self, mock_query ):
        """Task fails verification, coder retries, passes on second try."""
        call_count = 0

        async def mock_messages( **kwargs ):
            nonlocal call_count
            from claude_agent_sdk import TextBlock
            call_count += 1

            if call_count == 1:
                # Lead decomposition
                task_json = json.dumps( [ {
                    "title"         : "Task 1",
                    "objective"     : "Do 1",
                    "output_format" : "File 1",
                } ] )
                yield TextBlock( text=task_json )
            elif call_count == 2:
                # Coder first attempt
                yield TextBlock( text="First implementation" )
            elif call_count == 3:
                # Tester — fails
                yield TextBlock( text="Tests failed: assertion error in test_login" )
            elif call_count == 4:
                # Coder re-implementation with feedback
                yield TextBlock( text="Fixed implementation" )
            elif call_count == 5:
                # Tester — passes
                yield TextBlock( text="All tests pass now." )

        mock_query.side_effect = lambda **kwargs: mock_messages( **kwargs )

        orch = self._make_orchestrator()

        with patch( "cosa.agents.swe_team.orchestrator.ProgressLog" ) as MockPL, \
             patch( "cosa.agents.swe_team.orchestrator.FeatureList" ) as MockFL:
            MockPL.return_value = MagicMock()
            MockFL.return_value = MagicMock()
            MockFL.return_value.tasks = []

            team_io = MagicMock()
            team_io.notify_progress  = AsyncMock()
            team_io.ask_confirmation = AsyncMock( return_value=True )
            team_io.get_feedback     = AsyncMock( return_value=None )

            result = asyncio.run( orch._execute_live( team_io ) )

        assert result is not None
        assert len( orch.state[ "verification_results" ] ) == 2
        assert orch.state[ "verification_results" ][ 0 ].passed is False
        assert orch.state[ "verification_results" ][ 1 ].passed is True
        assert orch.state[ "total_verification_iterations" ] == 2

    @patch( "cosa.agents.swe_team.orchestrator.sdk_query" )
    def test_caps_at_max_iterations( self, mock_query ):
        """Verification loop caps at MAX_VERIFICATION_ITERATIONS."""
        call_count = 0

        async def mock_messages( **kwargs ):
            nonlocal call_count
            from claude_agent_sdk import TextBlock
            call_count += 1

            if call_count == 1:
                # Lead decomposition
                task_json = json.dumps( [ {
                    "title"         : "Task 1",
                    "objective"     : "Do 1",
                    "output_format" : "File 1",
                } ] )
                yield TextBlock( text=task_json )
            else:
                # Every subsequent call: either coder or tester, all fail
                if call_count % 2 == 0:
                    yield TextBlock( text="Implementation attempt" )
                else:
                    yield TextBlock( text="Tests failed again" )

        mock_query.side_effect = lambda **kwargs: mock_messages( **kwargs )

        # Use max_failures high enough so guard doesn't stop us prematurely
        orch = self._make_orchestrator()
        orch.guard.max_failures = 10

        with patch( "cosa.agents.swe_team.orchestrator.ProgressLog" ) as MockPL, \
             patch( "cosa.agents.swe_team.orchestrator.FeatureList" ) as MockFL:
            MockPL.return_value = MagicMock()
            MockFL.return_value = MagicMock()
            MockFL.return_value.tasks = []

            team_io = MagicMock()
            team_io.notify_progress  = AsyncMock()
            team_io.ask_confirmation = AsyncMock( return_value=True )
            team_io.get_feedback     = AsyncMock( return_value=None )

            result = asyncio.run( orch._execute_live( team_io ) )

        assert result is not None
        assert len( orch.state[ "verification_results" ] ) == MAX_VERIFICATION_ITERATIONS
        # All verifications should have failed
        assert all( not v.passed for v in orch.state[ "verification_results" ] )

    @patch( "cosa.agents.swe_team.orchestrator.sdk_query" )
    def test_skipped_when_require_test_pass_false( self, mock_query ):
        """Verification skipped when require_test_pass=False."""
        call_count = 0

        async def mock_messages( **kwargs ):
            nonlocal call_count
            from claude_agent_sdk import TextBlock
            call_count += 1

            if call_count == 1:
                task_json = json.dumps( [ {
                    "title"         : "Task 1",
                    "objective"     : "Do 1",
                    "output_format" : "File 1",
                } ] )
                yield TextBlock( text=task_json )
            else:
                yield TextBlock( text="Done" )

        mock_query.side_effect = lambda **kwargs: mock_messages( **kwargs )

        orch = self._make_orchestrator( require_test_pass=False )

        with patch( "cosa.agents.swe_team.orchestrator.ProgressLog" ) as MockPL, \
             patch( "cosa.agents.swe_team.orchestrator.FeatureList" ) as MockFL:
            MockPL.return_value = MagicMock()
            MockFL.return_value = MagicMock()
            MockFL.return_value.tasks = []

            team_io = MagicMock()
            team_io.notify_progress  = AsyncMock()
            team_io.ask_confirmation = AsyncMock( return_value=True )
            team_io.get_feedback     = AsyncMock( return_value=None )

            result = asyncio.run( orch._execute_live( team_io ) )

        assert result is not None
        assert len( orch.state[ "verification_results" ] ) == 0
        assert orch.state[ "total_verification_iterations" ] == 0
        # Only 2 sdk_query calls: decompose + coder (no tester)
        assert call_count == 2

    @patch( "cosa.agents.swe_team.orchestrator.sdk_query" )
    def test_populates_test_results_on_success( self, mock_query ):
        """Successful verification populates result.test_results."""
        call_count = 0

        async def mock_messages( **kwargs ):
            nonlocal call_count
            from claude_agent_sdk import TextBlock
            call_count += 1

            if call_count == 1:
                task_json = json.dumps( [ {
                    "title"         : "Task 1",
                    "objective"     : "Do 1",
                    "output_format" : "File 1",
                } ] )
                yield TextBlock( text=task_json )
            elif call_count == 2:
                yield TextBlock( text="Implementation done" )
            elif call_count == 3:
                yield TextBlock( text="All tests pass. 3 tests verified." )

        mock_query.side_effect = lambda **kwargs: mock_messages( **kwargs )

        orch = self._make_orchestrator()

        with patch( "cosa.agents.swe_team.orchestrator.ProgressLog" ) as MockPL, \
             patch( "cosa.agents.swe_team.orchestrator.FeatureList" ) as MockFL:
            MockPL.return_value = MagicMock()
            MockFL.return_value = MagicMock()
            MockFL.return_value.tasks = []

            team_io = MagicMock()
            team_io.notify_progress  = AsyncMock()
            team_io.ask_confirmation = AsyncMock( return_value=True )
            team_io.get_feedback     = AsyncMock( return_value=None )

            asyncio.run( orch._execute_live( team_io ) )

        final_result = orch.state[ "delegation_results" ][ 0 ]
        assert final_result.test_results is not None
        assert "tests pass" in final_result.test_results.lower()

    @patch( "cosa.agents.swe_team.orchestrator.sdk_query" )
    def test_guard_record_failure_at_max( self, mock_query ):
        """Guard records failure when max verification iterations reached."""
        call_count = 0

        async def mock_messages( **kwargs ):
            nonlocal call_count
            from claude_agent_sdk import TextBlock
            call_count += 1

            if call_count == 1:
                task_json = json.dumps( [ {
                    "title"         : "Task 1",
                    "objective"     : "Do 1",
                    "output_format" : "File 1",
                } ] )
                yield TextBlock( text=task_json )
            else:
                if call_count % 2 == 0:
                    yield TextBlock( text="Implementation" )
                else:
                    yield TextBlock( text="Tests failed" )

        mock_query.side_effect = lambda **kwargs: mock_messages( **kwargs )

        orch = self._make_orchestrator()
        orch.guard.max_failures = 10  # Don't let guard stop us
        initial_failures = orch.guard.failure_count

        with patch( "cosa.agents.swe_team.orchestrator.ProgressLog" ) as MockPL, \
             patch( "cosa.agents.swe_team.orchestrator.FeatureList" ) as MockFL:
            MockPL.return_value = MagicMock()
            MockFL.return_value = MagicMock()
            MockFL.return_value.tasks = []

            team_io = MagicMock()
            team_io.notify_progress  = AsyncMock()
            team_io.ask_confirmation = AsyncMock( return_value=True )
            team_io.get_feedback     = AsyncMock( return_value=None )

            asyncio.run( orch._execute_live( team_io ) )

        # Guard should have recorded at least one failure
        assert orch.guard.failure_count > initial_failures


# =============================================================================
# TestBuildAgentOptionsTester
# =============================================================================

class TestBuildAgentOptionsTester:
    """Tests for _build_agent_options with tester role."""

    def _make_orchestrator( self ):
        config = SweTeamConfig( dry_run=False )
        return SweTeamOrchestrator(
            task_description = "Test feature",
            config           = config,
            debug            = False,
        )

    def test_tester_uses_worker_model( self ):
        """Tester role uses worker_model, not lead_model."""
        orch    = self._make_orchestrator()
        team_io = MagicMock()

        options = orch._build_agent_options( "tester", team_io )

        assert options.model == orch.config.worker_model

    def test_tester_has_accept_edits_permission( self ):
        """Tester role gets acceptEdits permission mode."""
        orch    = self._make_orchestrator()
        team_io = MagicMock()

        options = orch._build_agent_options( "tester", team_io )

        assert options.permission_mode == "acceptEdits"

    def test_tester_uses_tester_system_prompt( self ):
        """Tester role uses TESTER_SYSTEM_PROMPT."""
        from cosa.agents.swe_team.agent_definitions import TESTER_SYSTEM_PROMPT

        orch    = self._make_orchestrator()
        team_io = MagicMock()

        options = orch._build_agent_options( "tester", team_io )

        assert options.system_prompt == TESTER_SYSTEM_PROMPT
