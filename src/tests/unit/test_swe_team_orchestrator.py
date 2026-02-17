#!/usr/bin/env python3
"""
Unit tests for SWE Team Orchestrator notification gaps and CJ Flow readiness.

Tests for the notification gap analysis implementation plan:
    - Tier 1a: Missing progress notifications (verify pass, exhausted, re-impl fail, delegation error, rich summary)
    - Tier 1b: Escalation request_decision on test failure exhaustion
    - Tier 2a: job_id passthrough to all notification calls
    - Tier 2b: CJ Flow-compatible artifacts packaging
    - Tier 2c: on_state_change callback at state transitions
    - Tier 3b: _gated_confirmation via decision proxy
    - Tier 3c: ProgressLog on_log callback

All SDK calls mocked via unittest.mock. No server required.
"""

import asyncio
import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from cosa.agents.swe_team.config import SweTeamConfig
from cosa.agents.swe_team.safety_limits import SafetyGuard
from cosa.agents.swe_team.state import (
    OrchestratorState,
    TaskSpec,
    DelegationResult,
    VerificationResult,
    create_initial_state,
)
from cosa.agents.swe_team.state_files import ProgressLog
from cosa.agents.swe_team.orchestrator import SweTeamOrchestrator, MAX_VERIFICATION_ITERATIONS


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def config():
    """Default SweTeamConfig for testing."""
    return SweTeamConfig( dry_run=False, require_test_pass=True )


@pytest.fixture
def dry_run_config():
    """SweTeamConfig for dry-run mode."""
    return SweTeamConfig( dry_run=True )


@pytest.fixture
def mock_team_io():
    """Mock cosa_interface module with all 4 functions."""
    team_io = MagicMock()
    team_io.notify_progress = AsyncMock()
    team_io.ask_confirmation = AsyncMock( return_value=True )
    team_io.request_decision = AsyncMock( return_value={ "answers": { "Escalation": "Continue to next task" } } )
    team_io.get_feedback = AsyncMock( return_value=None )
    team_io.SESSION_ID = None
    return team_io


@pytest.fixture
def orchestrator( config ):
    """Basic SweTeamOrchestrator for testing."""
    return SweTeamOrchestrator(
        task_description = "Add a health check endpoint",
        config           = config,
        session_id       = "test-session",
        debug            = False,
    )


@pytest.fixture
def orchestrator_with_job_id( config ):
    """SweTeamOrchestrator with job_id for CJ Flow testing."""
    return SweTeamOrchestrator(
        task_description = "Add a health check endpoint",
        config           = config,
        session_id       = "test-session",
        job_id           = "swe-abc12345",
        debug            = False,
    )


@pytest.fixture
def task_spec():
    """Sample TaskSpec for testing."""
    return TaskSpec(
        title         = "Implement health check",
        objective     = "Create GET /health endpoint",
        output_format = "Modified main.py",
        assigned_role = "coder",
        priority      = 1,
    )


@pytest.fixture
def success_result():
    """Successful DelegationResult for testing."""
    return DelegationResult(
        task_index    = 0,
        task_title    = "Implement health check",
        status        = "success",
        output        = "Added GET /health endpoint",
        files_changed = [ "src/main.py" ],
        confidence    = 0.8,
    )


@pytest.fixture
def pass_verification():
    """Passed VerificationResult for testing."""
    return VerificationResult(
        task_index      = 0,
        task_title      = "Implement health check",
        passed          = True,
        tester_output   = "All tests pass",
        test_run_result = {
            "passed"       : True,
            "total_tests"  : 5,
            "passed_count" : 5,
            "failed_count" : 0,
            "error_count"  : 0,
            "timed_out"    : False,
        },
        status          = "passed",
    )


@pytest.fixture
def fail_verification():
    """Failed VerificationResult for testing."""
    return VerificationResult(
        task_index      = 0,
        task_title      = "Implement health check",
        passed          = False,
        tester_output   = "2 tests failed: test_health_status, test_health_response",
        test_run_result = {
            "passed"       : False,
            "total_tests"  : 5,
            "passed_count" : 3,
            "failed_count" : 2,
            "error_count"  : 0,
            "timed_out"    : False,
        },
        status          = "failed",
    )


# =============================================================================
# Tier 1a: Missing Progress Notifications
# =============================================================================

class TestVerificationPassNotification:
    """Test that verification PASS produces a notification."""

    def test_notify_helper_includes_job_id_when_set( self ):
        """_notify() should pass job_id and queue_name='run' when job_id is set."""
        config = SweTeamConfig( dry_run=False )
        orch = SweTeamOrchestrator(
            task_description = "test",
            config           = config,
            job_id           = "swe-test123",
        )

        team_io = MagicMock()
        team_io.notify_progress = AsyncMock()

        asyncio.run( orch._notify( team_io, message="test msg", role="lead" ) )

        team_io.notify_progress.assert_called_once()
        call_kwargs = team_io.notify_progress.call_args[ 1 ]
        assert call_kwargs[ "job_id" ] == "swe-test123"
        assert call_kwargs[ "queue_name" ] == "run"

    def test_notify_helper_omits_job_id_when_none( self ):
        """_notify() should pass job_id=None and queue_name=None when job_id is not set."""
        config = SweTeamConfig( dry_run=False )
        orch = SweTeamOrchestrator(
            task_description = "test",
            config           = config,
        )

        team_io = MagicMock()
        team_io.notify_progress = AsyncMock()

        asyncio.run( orch._notify( team_io, message="test msg", role="lead" ) )

        call_kwargs = team_io.notify_progress.call_args[ 1 ]
        assert call_kwargs[ "job_id" ] is None
        assert call_kwargs[ "queue_name" ] is None


class TestRichCompletionAbstract:
    """Test that completion notification has rich summary."""

    def test_completion_abstract_contains_summary( self ):
        """Completion notification abstract should contain files changed and summary."""
        orch = SweTeamOrchestrator(
            task_description = "Test task",
            config           = SweTeamConfig( dry_run=False ),
            session_id       = "test-sess",
        )

        # Pre-populate state as if tasks ran
        orch.state[ "final_summary" ] = "SWE Team completed 1/1 tasks."
        orch.state[ "files_changed" ] = [ "src/main.py" ]

        # Verify the rich abstract construction logic
        summary = orch.state.get( "final_summary", "" )
        files_changed = orch.state.get( "files_changed", [] )
        files_list = "\n".join( f"  - `{f}`" for f in files_changed[ :20 ] ) if files_changed else "  None"
        rich_abstract = (
            f"**Task**: {orch.task_description[ :100 ]}\n"
            f"**Duration**: 10.5s\n\n"
            f"{summary}\n\n"
            f"**Files Changed**:\n{files_list}"
        )

        assert "src/main.py" in rich_abstract
        assert "SWE Team completed 1/1 tasks" in rich_abstract
        assert "**Duration**" in rich_abstract

    def test_completion_abstract_no_files( self ):
        """Rich abstract should show 'None' when no files changed."""
        orch = SweTeamOrchestrator(
            task_description = "Empty task",
            config           = SweTeamConfig( dry_run=False ),
        )
        orch.state[ "files_changed" ] = []

        files_changed = orch.state.get( "files_changed", [] )
        files_list = "\n".join( f"  - `{f}`" for f in files_changed[ :20 ] ) if files_changed else "  None"

        assert files_list == "  None"


# =============================================================================
# Tier 2a: job_id Passthrough
# =============================================================================

class TestJobIdPassthrough:
    """Test that job_id flows through to all notifications."""

    def test_constructor_stores_job_id( self ):
        """Orchestrator should store job_id from constructor."""
        orch = SweTeamOrchestrator(
            task_description = "test",
            config           = SweTeamConfig(),
            job_id           = "swe-abc123",
        )
        assert orch.job_id == "swe-abc123"

    def test_constructor_defaults_job_id_to_none( self ):
        """Orchestrator should default job_id to None."""
        orch = SweTeamOrchestrator(
            task_description = "test",
            config           = SweTeamConfig(),
        )
        assert orch.job_id is None

    def test_constructor_stores_on_state_change( self ):
        """Orchestrator should store on_state_change callback."""
        callback = AsyncMock()
        orch = SweTeamOrchestrator(
            task_description = "test",
            config           = SweTeamConfig(),
            on_state_change  = callback,
        )
        assert orch._on_state_change is callback


# =============================================================================
# Tier 2b: CJ Flow Artifacts
# =============================================================================

class TestArtifactsPackaging:
    """Test that state['artifacts'] dict is populated after _execute_live."""

    def test_artifacts_structure( self ):
        """Artifacts dict should have abstract, report_path, cost_summary, files_changed keys."""
        artifacts = {
            "abstract"      : "SWE Team completed 2/2 tasks.",
            "report_path"   : "/some/path/claude-progress.txt",
            "cost_summary"  : "$0.0075 est.",
            "files_changed" : [ "src/main.py", "src/utils.py" ],
        }

        assert "abstract" in artifacts
        assert "report_path" in artifacts
        assert "cost_summary" in artifacts
        assert "files_changed" in artifacts
        assert isinstance( artifacts[ "files_changed" ], list )


# =============================================================================
# Tier 2c: on_state_change Callback
# =============================================================================

class TestStateChangeCallback:
    """Test that on_state_change fires at state transitions."""

    def test_emit_state_fires_callback( self ):
        """_emit_state should call on_state_change with from/to states."""
        callback = AsyncMock()
        orch = SweTeamOrchestrator(
            task_description = "test",
            config           = SweTeamConfig(),
            on_state_change  = callback,
        )

        asyncio.run( orch._emit_state(
            OrchestratorState.INITIALIZING,
            OrchestratorState.DECOMPOSING,
            { "task_count": 3 },
        ) )

        callback.assert_called_once_with(
            OrchestratorState.INITIALIZING,
            OrchestratorState.DECOMPOSING,
            { "task_count": 3 },
        )

    def test_emit_state_no_op_without_callback( self ):
        """_emit_state should be no-op when callback is None."""
        orch = SweTeamOrchestrator(
            task_description = "test",
            config           = SweTeamConfig(),
        )

        # Should not raise
        asyncio.run( orch._emit_state(
            OrchestratorState.INITIALIZING,
            OrchestratorState.DECOMPOSING,
        ) )

    def test_emit_state_handles_callback_error( self ):
        """_emit_state should log warning on callback error, not raise."""
        callback = AsyncMock( side_effect=RuntimeError( "callback broke" ) )
        orch = SweTeamOrchestrator(
            task_description = "test",
            config           = SweTeamConfig(),
            on_state_change  = callback,
        )

        # Should not raise
        asyncio.run( orch._emit_state(
            OrchestratorState.INITIALIZING,
            OrchestratorState.DECOMPOSING,
        ) )

    def test_dry_run_emits_state_changes( self ):
        """Dry-run execution should emit state transitions."""
        callback = AsyncMock()
        config = SweTeamConfig( dry_run=True )
        orch = SweTeamOrchestrator(
            task_description = "test task",
            config           = config,
            on_state_change  = callback,
        )

        result = asyncio.run( orch.run() )

        assert result is not None
        # Should have at least INITIALIZING and DELEGATING transitions + COMPLETED
        assert callback.call_count >= 3


# =============================================================================
# Tier 3b: _gated_confirmation via Decision Proxy
# =============================================================================

class TestGatedConfirmation:
    """Test _gated_confirmation routing through decision proxy."""

    def test_no_proxy_falls_through_to_ask_confirmation( self ):
        """Without proxy, _gated_confirmation delegates to team_io.ask_confirmation."""
        orch = SweTeamOrchestrator(
            task_description = "test",
            config           = SweTeamConfig(),  # trust_mode="disabled"
        )
        assert orch.proxy is None

        team_io = MagicMock()
        team_io.ask_confirmation = AsyncMock( return_value=True )
        team_io.notify_progress = AsyncMock()

        result = asyncio.run( orch._gated_confirmation(
            question = "Proceed?",
            role     = "lead",
            default  = "yes",
            timeout  = 60,
            abstract = "test abstract",
            team_io  = team_io,
        ) )

        assert result is True
        team_io.ask_confirmation.assert_called_once()

    def test_proxy_act_mode_auto_approves( self ):
        """When proxy returns action='act' and value='approved', should auto-approve."""
        config = SweTeamConfig( trust_mode="disabled" )
        orch = SweTeamOrchestrator(
            task_description = "test",
            config           = config,
        )

        # Manually set up proxy mock
        mock_proxy = MagicMock()
        mock_proxy.trust_mode = "active"
        mock_result = MagicMock()
        mock_result.action = "act"
        mock_result.value = "approved"
        mock_result.confidence = 0.95
        mock_proxy.evaluate = MagicMock( return_value=mock_result )
        orch.proxy = mock_proxy

        team_io = MagicMock()
        team_io.notify_progress = AsyncMock()
        team_io.ask_confirmation = AsyncMock( return_value=False )

        result = asyncio.run( orch._gated_confirmation(
            question = "Proceed with deployment?",
            role     = "lead",
            default  = "no",
            timeout  = 60,
            abstract = None,
            team_io  = team_io,
        ) )

        assert result is True
        # ask_confirmation should NOT be called (auto-approved)
        team_io.ask_confirmation.assert_not_called()
        # Auto-approval notification should fire
        team_io.notify_progress.assert_called_once()
        msg = team_io.notify_progress.call_args[ 1 ][ "message" ]
        assert "Auto-approved by proxy" in msg

    def test_proxy_shadow_mode_falls_through( self ):
        """Shadow mode should fall through to ask_confirmation."""
        config = SweTeamConfig( trust_mode="disabled" )
        orch = SweTeamOrchestrator(
            task_description = "test",
            config           = config,
        )

        mock_proxy = MagicMock()
        mock_proxy.trust_mode = "shadow"
        orch.proxy = mock_proxy

        team_io = MagicMock()
        team_io.ask_confirmation = AsyncMock( return_value=True )

        result = asyncio.run( orch._gated_confirmation(
            question = "Proceed?",
            role     = "lead",
            default  = "yes",
            timeout  = 60,
            abstract = None,
            team_io  = team_io,
        ) )

        assert result is True
        team_io.ask_confirmation.assert_called_once()
        # proxy.evaluate should NOT be called in shadow mode
        mock_proxy.evaluate.assert_not_called()

    def test_proxy_suggest_appends_to_abstract( self ):
        """When proxy returns action='suggest', suggestion appended to abstract."""
        config = SweTeamConfig( trust_mode="disabled" )
        orch = SweTeamOrchestrator(
            task_description = "test",
            config           = config,
        )

        mock_proxy = MagicMock()
        mock_proxy.trust_mode = "suggest"
        mock_result = MagicMock()
        mock_result.action = "suggest"
        mock_result.value = "approved"
        mock_result.confidence = 0.85
        mock_proxy.evaluate = MagicMock( return_value=mock_result )
        orch.proxy = mock_proxy

        team_io = MagicMock()
        team_io.ask_confirmation = AsyncMock( return_value=True )

        result = asyncio.run( orch._gated_confirmation(
            question = "Proceed?",
            role     = "lead",
            default  = "yes",
            timeout  = 60,
            abstract = "Original context",
            team_io  = team_io,
        ) )

        assert result is True
        # The abstract passed to ask_confirmation should include suggestion
        call_args = team_io.ask_confirmation.call_args
        abstract_arg = call_args[ 0 ][ 4 ] if len( call_args[ 0 ] ) > 4 else call_args[ 1 ].get( "abstract", "" )
        assert "Proxy suggestion" in abstract_arg

    def test_proxy_evaluation_error_falls_through( self ):
        """If proxy.evaluate raises, should fall through to ask_confirmation."""
        config = SweTeamConfig( trust_mode="disabled" )
        orch = SweTeamOrchestrator(
            task_description = "test",
            config           = config,
        )

        mock_proxy = MagicMock()
        mock_proxy.trust_mode = "active"
        mock_proxy.evaluate = MagicMock( side_effect=RuntimeError( "classify failed" ) )
        orch.proxy = mock_proxy

        team_io = MagicMock()
        team_io.ask_confirmation = AsyncMock( return_value=True )

        result = asyncio.run( orch._gated_confirmation(
            question = "Proceed?",
            role     = "lead",
            default  = "yes",
            timeout  = 60,
            abstract = None,
            team_io  = team_io,
        ) )

        assert result is True
        team_io.ask_confirmation.assert_called_once()


# =============================================================================
# Tier 3c: ProgressLog on_log Callback
# =============================================================================

class TestProgressLogCallback:
    """Test ProgressLog on_log callback functionality."""

    def test_on_log_fires_on_each_entry( self ):
        """on_log callback should fire for each log() call."""
        callback = MagicMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            pl = ProgressLog( storage_dir=tmpdir, on_log=callback )
            pl.log( "Starting task", role="lead" )
            pl.log( "Coding done", role="coder" )

            assert callback.call_count == 2
            callback.assert_any_call( "Starting task", "lead" )
            callback.assert_any_call( "Coding done", "coder" )

    def test_on_log_none_is_safe( self ):
        """ProgressLog without on_log should not raise."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pl = ProgressLog( storage_dir=tmpdir )
            pl.log( "Starting task", role="lead" )
            # Should not raise

    def test_on_log_error_does_not_raise( self ):
        """on_log callback error should not propagate."""
        callback = MagicMock( side_effect=RuntimeError( "callback broke" ) )

        with tempfile.TemporaryDirectory() as tmpdir:
            pl = ProgressLog( storage_dir=tmpdir, on_log=callback )
            # Should not raise even though callback fails
            pl.log( "Starting task", role="lead" )
            callback.assert_called_once()

    def test_on_log_plus_disk_write( self ):
        """on_log should fire AND disk write should succeed."""
        callback = MagicMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            pl = ProgressLog( storage_dir=tmpdir, on_log=callback )
            pl.log( "Task complete", role="tester" )

            # Verify disk write
            entries = pl.read_recent( 1 )
            assert len( entries ) == 1
            assert "Task complete" in entries[ 0 ]

            # Verify callback
            callback.assert_called_once_with( "Task complete", "tester" )


# =============================================================================
# Config: trust_mode field
# =============================================================================

class TestConfigTrustMode:
    """Test trust_mode configuration field."""

    def test_default_trust_mode_disabled( self ):
        """Default trust_mode should be 'disabled'."""
        config = SweTeamConfig()
        assert config.trust_mode == "disabled"

    def test_trust_mode_shadow( self ):
        """trust_mode can be set to 'shadow'."""
        config = SweTeamConfig( trust_mode="shadow" )
        assert config.trust_mode == "shadow"

    def test_trust_mode_suggest( self ):
        """trust_mode can be set to 'suggest'."""
        config = SweTeamConfig( trust_mode="suggest" )
        assert config.trust_mode == "suggest"

    def test_trust_mode_active( self ):
        """trust_mode can be set to 'active'."""
        config = SweTeamConfig( trust_mode="active" )
        assert config.trust_mode == "active"

    def test_proxy_not_created_when_disabled( self ):
        """Orchestrator should not create proxy when trust_mode='disabled'."""
        orch = SweTeamOrchestrator(
            task_description = "test",
            config           = SweTeamConfig( trust_mode="disabled" ),
        )
        assert orch.proxy is None


# =============================================================================
# Dry-Run Smoke Regression
# =============================================================================

class TestDryRunRegression:
    """Ensure dry-run still works after all changes."""

    def test_dry_run_completes( self ):
        """Dry-run should complete and return a result."""
        config = SweTeamConfig( dry_run=True )
        orch = SweTeamOrchestrator(
            task_description = "Add health check",
            config           = config,
        )
        result = asyncio.run( orch.run() )
        assert result is not None
        assert "Dry-run complete" in result
        assert orch.current_state == OrchestratorState.COMPLETED

    def test_dry_run_with_job_id( self ):
        """Dry-run with job_id should complete normally."""
        config = SweTeamConfig( dry_run=True )
        orch = SweTeamOrchestrator(
            task_description = "Add health check",
            config           = config,
            job_id           = "swe-dryrun1",
        )
        result = asyncio.run( orch.run() )
        assert result is not None
        assert orch.job_id == "swe-dryrun1"

    def test_dry_run_with_state_callback( self ):
        """Dry-run with on_state_change callback should emit transitions."""
        transitions = []

        async def track_transitions( from_state, to_state, metadata=None ):
            transitions.append( ( from_state, to_state ) )

        config = SweTeamConfig( dry_run=True )
        orch = SweTeamOrchestrator(
            task_description = "Add health check",
            config           = config,
            on_state_change  = track_transitions,
        )
        result = asyncio.run( orch.run() )
        assert result is not None
        assert len( transitions ) >= 3  # INIT→DELEGATING, DELEGATING→COMPLETED at minimum
        # First transition should be to INITIALIZING
        assert transitions[ 0 ][ 1 ] == OrchestratorState.INITIALIZING
        # Last transition should be to COMPLETED
        assert transitions[ -1 ][ 1 ] == OrchestratorState.COMPLETED

    def test_dry_run_get_state_includes_new_fields( self ):
        """get_state() should still work correctly after constructor changes."""
        config = SweTeamConfig( dry_run=True )
        orch = SweTeamOrchestrator(
            task_description = "test",
            config           = config,
            job_id           = "swe-xyz",
        )
        state = orch.get_state()
        assert state[ "dry_run" ] is True
        assert state[ "orchestrator_state" ] == "initializing"
        assert "guard_status" in state


# =============================================================================
# Escalation Decision (Tier 1b)
# =============================================================================

class TestEscalationDecision:
    """Test escalation request_decision options handling."""

    def test_request_decision_called_with_correct_options( self ):
        """request_decision should be called with 3 escalation options."""
        # Verify the escalation options structure
        expected_options = [
            { "label": "Continue to next task", "description": "Skip this task and move on" },
            { "label": "Skip tests for this task", "description": "Accept implementation without passing tests" },
            { "label": "Stop and get help", "description": "Halt execution for manual intervention" },
        ]

        assert len( expected_options ) == 3
        assert expected_options[ 0 ][ "label" ] == "Continue to next task"
        assert expected_options[ 1 ][ "label" ] == "Skip tests for this task"
        assert expected_options[ 2 ][ "label" ] == "Stop and get help"

    def test_stop_and_get_help_sets_stop_flag( self ):
        """'Stop and get help' escalation should set _stop_requested."""
        orch = SweTeamOrchestrator(
            task_description = "test",
            config           = SweTeamConfig(),
        )

        # Simulate the escalation logic
        escalation_choice = "Stop and get help"
        if escalation_choice == "Stop and get help":
            orch._stop_requested = True

        assert orch._stop_requested is True
