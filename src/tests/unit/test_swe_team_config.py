#!/usr/bin/env python3
"""
Unit tests for SWE Team Agent — Phase 1 Foundation.

Tests config defaults, safety limits, state schemas, agent definitions,
sender ID format, and orchestrator dry-run execution.
"""

import asyncio
import re
import pytest

from cosa.agents.swe_team.config import SweTeamConfig
from cosa.agents.swe_team.safety_limits import (
    SAFETY_LIMITS,
    DANGEROUS_COMMANDS,
    SafetyGuard,
    SafetyLimitError,
    is_dangerous_command,
)
from cosa.agents.swe_team.state import (
    OrchestratorState,
    JobSubState,
    TaskSpec,
    DelegationResult,
    ReviewFinding,
    SweTeamState,
    create_initial_state,
)
from cosa.agents.swe_team.agent_definitions import (
    AgentRole,
    get_agent_roles,
    get_active_roles,
    get_model_for_role,
    get_sender_id,
    SWE_TEAM_SENDERS,
)
from cosa.agents.swe_team.mock_clients import (
    MockAgentSDKSession,
    MockAgentMessage,
)
from cosa.agents.swe_team.orchestrator import SweTeamOrchestrator
from cosa.agents.swe_team.cosa_interface import (
    is_approval,
    is_rejection,
)


# =============================================================================
# SweTeamConfig Tests
# =============================================================================

class TestSweTeamConfig:
    """Tests for SweTeamConfig dataclass."""

    def test_default_models( self ):
        config = SweTeamConfig()
        assert config.lead_model == "claude-opus-4-20250514"
        assert config.worker_model == "claude-sonnet-4-20250514"

    def test_default_safety_limits( self ):
        config = SweTeamConfig()
        assert config.max_iterations_per_task == 10
        assert config.max_tokens_per_session == 500_000
        assert config.wall_clock_timeout_secs == 1800
        assert config.max_consecutive_failures == 3
        assert config.max_file_changes_per_task == 20
        assert config.require_test_pass is True

    def test_default_budget( self ):
        config = SweTeamConfig()
        assert config.budget_usd == 5.00

    def test_default_disabled( self ):
        config = SweTeamConfig()
        assert config.enabled is False
        assert config.dry_run is False

    def test_custom_values( self ):
        config = SweTeamConfig(
            lead_model="custom-opus",
            worker_model="custom-sonnet",
            budget_usd=10.00,
            max_iterations_per_task=5,
            dry_run=True,
        )
        assert config.lead_model == "custom-opus"
        assert config.worker_model == "custom-sonnet"
        assert config.budget_usd == 10.00
        assert config.max_iterations_per_task == 5
        assert config.dry_run is True

    def test_cosa_integration_defaults( self ):
        config = SweTeamConfig()
        assert config.feedback_timeout_seconds == 300
        assert config.narrate_progress is True


# =============================================================================
# Safety Limits Tests
# =============================================================================

class TestSafetyLimits:
    """Tests for SAFETY_LIMITS dict and guard functions."""

    def test_safety_limits_dict_values( self ):
        assert SAFETY_LIMITS[ "max_iterations_per_task" ] == 10
        assert SAFETY_LIMITS[ "max_tokens_per_session" ] == 500_000
        assert SAFETY_LIMITS[ "wall_clock_timeout_secs" ] == 1800
        assert SAFETY_LIMITS[ "max_consecutive_failures" ] == 3
        assert SAFETY_LIMITS[ "max_file_changes_per_task" ] == 20
        assert SAFETY_LIMITS[ "require_test_pass" ] is True

    def test_dangerous_commands_immutable( self ):
        assert isinstance( DANGEROUS_COMMANDS, frozenset )

    @pytest.mark.parametrize( "cmd,expected", [
        ( "rm -rf /tmp/foo", True ),
        ( "git push --force origin main", True ),
        ( "DROP TABLE users", True ),
        ( "DELETE FROM sessions", True ),
        ( "kill -9 1234", True ),
        ( "chmod 777 /etc/passwd", True ),
        ( "ls -la", False ),
        ( "git status", False ),
        ( "pytest src/tests/", False ),
        ( "cat README.md", False ),
        ( "", False ),
    ] )
    def test_is_dangerous_command( self, cmd, expected ):
        assert is_dangerous_command( cmd ) == expected


class TestSafetyGuard:
    """Tests for SafetyGuard runtime enforcement."""

    def test_iteration_limit_enforced( self ):
        guard = SafetyGuard( max_iterations=3 )
        guard.check_iteration()
        guard.check_iteration()
        guard.check_iteration()
        with pytest.raises( SafetyLimitError, match="Max iterations exceeded" ):
            guard.check_iteration()

    def test_failure_limit_enforced( self ):
        guard = SafetyGuard( max_failures=2 )
        guard.record_failure( "error 1" )
        with pytest.raises( SafetyLimitError, match="Max consecutive failures" ):
            guard.record_failure( "error 2" )

    def test_success_resets_failures( self ):
        guard = SafetyGuard( max_failures=3 )
        guard.record_failure( "fail 1" )
        guard.record_failure( "fail 2" )
        guard.record_success()
        assert guard.failure_count == 0

    def test_file_change_limit( self ):
        guard = SafetyGuard()
        for _ in range( 20 ):
            guard.record_file_change()
        with pytest.raises( SafetyLimitError, match="Max file changes exceeded" ):
            guard.record_file_change()

    def test_get_status_within_limits( self ):
        guard = SafetyGuard( max_iterations=10, max_failures=3, timeout_secs=1800 )
        guard.check_iteration()
        status = guard.get_status()
        assert status[ "within_limits" ] is True
        assert "iterations" in status
        assert "failures" in status
        assert "elapsed_secs" in status


# =============================================================================
# State Schema Tests
# =============================================================================

class TestStateSchemas:
    """Tests for state enums and Pydantic models."""

    def test_orchestrator_state_count( self ):
        assert len( OrchestratorState ) == 14

    def test_job_sub_state_count( self ):
        assert len( JobSubState ) == 5

    def test_task_spec_defaults( self ):
        spec = TaskSpec(
            title="Test task",
            objective="Do something",
            output_format="Modified file",
        )
        assert spec.assigned_role == "coder"
        assert spec.priority == 1
        assert spec.tool_guidance == ""
        assert spec.scope_boundary == ""
        assert spec.depends_on is None

    def test_delegation_result_defaults( self ):
        result = DelegationResult(
            task_index=0,
            task_title="Test",
        )
        assert result.status == "success"
        assert result.output == ""
        assert result.files_changed == []
        assert result.errors == []
        assert result.confidence == 0.0

    def test_review_finding_validation( self ):
        finding = ReviewFinding(
            severity="critical",
            file_path="src/auth.py",
            description="SQL injection vulnerability",
        )
        assert finding.severity == "critical"
        assert finding.line_number is None
        assert finding.suggestion == ""

    def test_create_initial_state( self ):
        state = create_initial_state( "Build auth system" )
        assert state[ "original_task" ] == "Build auth system"
        assert state[ "iteration_count" ] == 0
        assert state[ "review_passed" ] is False
        assert state[ "task_specs" ] == []
        assert state[ "delegation_results" ] == []
        assert state[ "files_changed" ] == []


# =============================================================================
# Agent Definitions Tests
# =============================================================================

class TestAgentDefinitions:
    """Tests for agent role definitions and sender IDs."""

    def test_all_six_roles_defined( self ):
        roles = get_agent_roles()
        assert len( roles ) == 6
        expected = { "lead", "architect", "coder", "reviewer", "tester", "debugger" }
        assert set( roles.keys() ) == expected

    def test_phase_1_only_lead_active( self ):
        active = get_active_roles()
        assert len( active ) == 1
        assert "lead" in active

    def test_model_tier_lead_roles( self ):
        roles = get_agent_roles()
        assert roles[ "lead" ].model_tier == "lead"
        assert roles[ "architect" ].model_tier == "lead"

    def test_model_tier_worker_roles( self ):
        roles = get_agent_roles()
        for name in [ "coder", "reviewer", "tester", "debugger" ]:
            assert roles[ name ].model_tier == "worker", f"{name} should be worker tier"

    def test_reviewer_has_no_write_tools( self ):
        roles = get_agent_roles()
        reviewer_tools = roles[ "reviewer" ].tools
        assert "Edit" not in reviewer_tools
        assert "Write" not in reviewer_tools
        assert "Bash" not in reviewer_tools

    def test_get_model_for_role( self ):
        config = SweTeamConfig()
        roles = get_agent_roles( config )
        assert get_model_for_role( roles[ "lead" ], config ) == config.lead_model
        assert get_model_for_role( roles[ "coder" ], config ) == config.worker_model

    def test_swe_team_senders_set( self ):
        assert len( SWE_TEAM_SENDERS ) == 6
        assert isinstance( SWE_TEAM_SENDERS, frozenset )
        assert "swe.lead" in SWE_TEAM_SENDERS
        assert "swe.coder" in SWE_TEAM_SENDERS


class TestSenderIds:
    """Tests for sender ID format and regex compliance."""

    # Lupin sender_id regex from architecture design doc
    SENDER_REGEX = r"^[a-z]+(\.[a-z]+)+@[a-z]+\.deepily\.ai(#[a-z0-9\-]+)?$"

    def test_sender_id_format_no_session( self ):
        sid = get_sender_id( "lead" )
        assert sid == "swe.lead@lupin.deepily.ai"
        assert re.match( self.SENDER_REGEX, sid )

    def test_sender_id_format_with_session( self ):
        sid = get_sender_id( "coder", "a1b2c3d4" )
        assert sid == "swe.coder@lupin.deepily.ai#a1b2c3d4"
        assert re.match( self.SENDER_REGEX, sid )

    def test_all_roles_produce_valid_sender_ids( self ):
        for role_name in [ "lead", "architect", "coder", "reviewer", "tester", "debugger" ]:
            sid = get_sender_id( role_name )
            assert re.match( self.SENDER_REGEX, sid ), f"Invalid sender_id for {role_name}: {sid}"

    def test_sender_id_with_team_prefix_session( self ):
        sid = get_sender_id( "lead", "team-abc123" )
        assert sid == "swe.lead@lupin.deepily.ai#team-abc123"
        assert re.match( self.SENDER_REGEX, sid )


# =============================================================================
# Mock Client Tests
# =============================================================================

class TestMockClients:
    """Tests for MockAgentSDKSession."""

    def test_session_id_format( self ):
        session = MockAgentSDKSession( "Test task" )
        assert session.session_id.startswith( "st-" )
        assert len( session.session_id ) == 11

    def test_dry_run_phases_count( self ):
        assert len( MockAgentSDKSession.DRY_RUN_PHASES ) == 6

    def test_async_query_yields_messages( self ):
        async def run():
            session = MockAgentSDKSession( "Test", debug=False )
            messages = []
            async for msg in session.query():
                messages.append( msg )
            return session, messages

        session, messages = asyncio.run( run() )
        assert len( messages ) == 6
        assert session.messages_sent == 6

    def test_session_summary( self ):
        session = MockAgentSDKSession( "Test task" )
        summary = session.get_session_summary()
        assert summary[ "dry_run" ] is True
        assert summary[ "cost_usd" ] == 0.0


# =============================================================================
# Orchestrator Tests
# =============================================================================

class TestOrchestrator:
    """Tests for SweTeamOrchestrator."""

    def test_creation( self ):
        config = SweTeamConfig( dry_run=True )
        orch = SweTeamOrchestrator( "Test task", config=config )
        assert orch.task_description == "Test task"
        assert orch.current_state == OrchestratorState.INITIALIZING
        assert orch.session_id.startswith( "st-" )

    def test_get_state( self ):
        config = SweTeamConfig( dry_run=True )
        orch = SweTeamOrchestrator( "Test task", config=config )
        state = orch.get_state()
        assert state[ "orchestrator_state" ] == "initializing"
        assert state[ "dry_run" ] is True
        assert "guard_status" in state

    def test_dry_run_completes( self ):
        config = SweTeamConfig( dry_run=True )
        orch = SweTeamOrchestrator( "Test task", config=config )
        result = asyncio.run( orch.run() )
        assert result is not None
        assert "Dry-run complete" in result
        assert orch.current_state == OrchestratorState.COMPLETED

    def test_stop_request( self ):
        config = SweTeamConfig( dry_run=True )
        orch = SweTeamOrchestrator( "Test task", config=config )
        stop_state = asyncio.run( orch.stop() )
        assert orch._stop_requested is True
        assert stop_state[ "orchestrator_state" ] == "stopped"

    def test_progress_calculation( self ):
        config = SweTeamConfig( dry_run=True )
        orch = SweTeamOrchestrator( "Test task", config=config )
        assert orch._calculate_progress() == 5  # INITIALIZING
        orch.current_state = OrchestratorState.COMPLETED
        assert orch._calculate_progress() == 100


# =============================================================================
# COSA Interface Tests (pure functions only)
# =============================================================================

class TestCosaInterface:
    """Tests for feedback analysis utilities."""

    @pytest.mark.parametrize( "feedback,expected", [
        ( "yes", True ),
        ( "Yes, proceed", True ),
        ( "sounds good", True ),
        ( "go for it", True ),
        ( "no", False ),
        ( "", False ),
        ( "maybe later", False ),
    ] )
    def test_is_approval( self, feedback, expected ):
        assert is_approval( feedback ) == expected

    @pytest.mark.parametrize( "feedback,expected", [
        ( "no", True ),
        ( "wait, stop", True ),
        ( "change it", True ),
        ( "actually, different approach", True ),
        ( "yes", False ),
        ( "", False ),
        ( "sounds good", False ),
    ] )
    def test_is_rejection( self, feedback, expected ):
        assert is_rejection( feedback ) == expected
