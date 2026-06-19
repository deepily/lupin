"""
Unit tests for swe_team pure-logic / thin-delegation mid-tier modules:
  - safety_limits.py    : DANGEROUS_COMMANDS + is_dangerous_command + SafetyGuard
  - state.py            : enums + Pydantic models + create_initial_state
  - agent_definitions.py: AgentRole registry + model/sender helpers
  - cosa_interface.py    : role-aware async wrappers delegating to AgentNotificationDispatcher

time.time is patched where needed to drive timeout arcs deterministically;
the dispatcher is mocked at the boundary — no real notification/network.

Created 2026-05-31 by Extra 1 🪨 (CoSA coverage campaign, swe_team lane, mid tier).
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import cosa.agents.swe_team.safety_limits as sl
import cosa.agents.swe_team.state as state
import cosa.agents.swe_team.agent_definitions as adefs
import cosa.agents.swe_team.cosa_interface as ci


def _run( coro ):
    return asyncio.run( coro )


# ============================================================================
# safety_limits.py
# ============================================================================

class TestIsDangerousCommand( unittest.TestCase ):

    def test_empty_command_is_safe( self ):
        self.assertFalse( sl.is_dangerous_command( "" ) )

    def test_matches_shell_pattern( self ):
        self.assertTrue( sl.is_dangerous_command( "rm -rf /tmp/x" ) )

    def test_matches_sql_pattern_case_insensitive( self ):
        self.assertTrue( sl.is_dangerous_command( "drop table users" ) )

    def test_safe_command_returns_false( self ):
        self.assertFalse( sl.is_dangerous_command( "ls -la" ) )


class TestSafetyGuard( unittest.TestCase ):

    def test_init_defaults_from_safety_limits( self ):
        g = sl.SafetyGuard()
        self.assertEqual( g.max_iterations, sl.SAFETY_LIMITS[ "max_iterations_per_task" ] )
        self.assertEqual( g.max_failures, sl.SAFETY_LIMITS[ "max_consecutive_failures" ] )
        self.assertEqual( g.iteration_count, 0 )

    def test_check_iteration_passes_then_raises( self ):
        g = sl.SafetyGuard( max_iterations=2 )
        g.check_iteration()
        g.check_iteration()
        with self.assertRaises( sl.SafetyLimitError ):
            g.check_iteration()

    def test_check_timeout_within_limit( self ):
        g = sl.SafetyGuard( timeout_secs=1000 )
        # Force a small elapsed → no raise.
        with patch.object( sl.time, "time", side_effect=[ g.start_time + 1 ] ):
            g.check_timeout()  # no exception

    def test_check_timeout_exceeded_raises( self ):
        g = sl.SafetyGuard( timeout_secs=10 )
        with patch.object( sl.time, "time", side_effect=[ g.start_time + 99 ] ):
            with self.assertRaises( sl.SafetyLimitError ):
                g.check_timeout()

    def test_record_failure_below_then_at_threshold( self ):
        g = sl.SafetyGuard( max_failures=2 )
        g.record_failure( "first" )            # count 1 — no raise
        self.assertEqual( g.failure_count, 1 )
        with self.assertRaises( sl.SafetyLimitError ):
            g.record_failure( "second" )       # count 2 — raises

    def test_record_success_resets_failures( self ):
        g = sl.SafetyGuard( max_failures=3 )
        g.record_failure( "x" )
        g.record_success()
        self.assertEqual( g.failure_count, 0 )

    def test_record_file_change_passes_then_raises( self ):
        g = sl.SafetyGuard()
        g.record_file_change( max_changes=1 )  # 1 — no raise
        with self.assertRaises( sl.SafetyLimitError ):
            g.record_file_change( max_changes=1 )  # 2 — raises

    def test_get_status_within_limits_true( self ):
        g = sl.SafetyGuard( max_iterations=10, max_failures=3, timeout_secs=1800 )
        g.check_iteration()
        with patch.object( sl.time, "time", side_effect=[ g.start_time + 5 ] ):
            status = g.get_status()
        self.assertTrue( status[ "within_limits" ] )
        self.assertIn( "iterations", status )

    def test_get_status_within_limits_false_when_failures_maxed( self ):
        g = sl.SafetyGuard( max_failures=3 )
        g.failure_count = 3                     # make `failure_count < max_failures` False
        with patch.object( sl.time, "time", side_effect=[ g.start_time + 5 ] ):
            status = g.get_status()
        self.assertFalse( status[ "within_limits" ] )


# ============================================================================
# state.py
# ============================================================================

class TestState( unittest.TestCase ):

    def test_orchestrator_state_has_14_members( self ):
        self.assertEqual( len( state.OrchestratorState ), 14 )
        self.assertEqual( state.OrchestratorState.INITIALIZING.value, "initializing" )

    def test_job_sub_state_has_5_members( self ):
        self.assertEqual( len( state.JobSubState ), 5 )

    def test_models_validate_with_defaults( self ):
        spec = state.TaskSpec( title="t", objective="o", output_format="f" )
        self.assertEqual( spec.assigned_role, "coder" )
        self.assertEqual( spec.priority, 1 )
        dr = state.DelegationResult( task_index=0, task_title="t" )
        self.assertEqual( dr.status, "success" )
        rf = state.ReviewFinding( severity="minor", file_path="a.py", description="d" )
        self.assertEqual( rf.suggestion, "" )
        vr = state.VerificationResult( task_index=0, task_title="t" )
        self.assertFalse( vr.passed )
        self.assertEqual( vr.status, "failed" )

    def test_create_initial_state( self ):
        s = state.create_initial_state( "Build X" )
        self.assertEqual( s[ "original_task" ], "Build X" )
        self.assertEqual( s[ "iteration_count" ], 0 )
        self.assertFalse( s[ "review_passed" ] )
        self.assertEqual( s[ "task_specs" ], [] )
        self.assertEqual( s[ "execution_metadata" ], {} )


# ============================================================================
# agent_definitions.py
# ============================================================================

class TestAgentDefinitions( unittest.TestCase ):

    def test_get_agent_roles_default_config( self ):
        roles = adefs.get_agent_roles()
        self.assertEqual( set( roles.keys() ),
                          { "lead", "architect", "coder", "reviewer", "tester", "debugger" } )
        self.assertTrue( roles[ "lead" ].active )
        self.assertFalse( roles[ "architect" ].active )
        # max_failures interpolated into the lead prompt.
        self.assertIn( "3 times", roles[ "lead" ].system_prompt )

    def test_get_agent_roles_custom_config( self ):
        cfg = adefs.SweTeamConfig( max_consecutive_failures=7 )
        roles = adefs.get_agent_roles( cfg )
        self.assertIn( "7 times", roles[ "lead" ].system_prompt )

    def test_get_active_roles( self ):
        active = adefs.get_active_roles()
        self.assertEqual( set( active.keys() ), { "lead", "coder", "tester" } )

    def test_get_model_for_role_lead_and_worker( self ):
        roles = adefs.get_agent_roles()
        cfg = adefs.SweTeamConfig()
        self.assertEqual( adefs.get_model_for_role( roles[ "lead" ], cfg ),  cfg.lead_model )
        self.assertEqual( adefs.get_model_for_role( roles[ "coder" ], cfg ), cfg.worker_model )

    def test_get_model_for_role_default_config( self ):
        roles = adefs.get_agent_roles()
        # config=None branch builds a default SweTeamConfig.
        self.assertEqual( adefs.get_model_for_role( roles[ "lead" ] ),
                          adefs.SweTeamConfig().lead_model )

    def test_get_sender_id_with_and_without_session( self ):
        self.assertEqual( adefs.get_sender_id( "lead" ), "swe.lead@lupin.deepily.ai" )
        self.assertEqual( adefs.get_sender_id( "coder", "abc" ),
                          "swe.coder@lupin.deepily.ai#abc" )

    def test_swe_team_senders_frozenset( self ):
        self.assertEqual( len( adefs.SWE_TEAM_SENDERS ), 6 )
        self.assertIn( "swe.lead", adefs.SWE_TEAM_SENDERS )


# ============================================================================
# cosa_interface.py — thin async delegation
# ============================================================================

class TestCosaInterfaceGetSenderId( unittest.TestCase ):

    def test_get_sender_id_no_session( self ):
        with patch.object( ci, "build_sender_id", return_value="SID" ) as bsi:
            out = ci.get_sender_id( "lead" )
        self.assertEqual( out, "SID" )
        # suffix None when no session_id supplied.
        _, kwargs = bsi.call_args
        self.assertIsNone( kwargs[ "suffix" ] )

    def test_get_sender_id_plain_session( self ):
        with patch.object( ci, "build_sender_id", return_value="SID" ) as bsi:
            ci.get_sender_id( "coder", "abc123" )
        _, kwargs = bsi.call_args
        self.assertEqual( kwargs[ "suffix" ], "abc123" )

    def test_get_sender_id_strips_compound_hash( self ):
        with patch.object( ci, "build_sender_id", return_value="SID" ) as bsi:
            ci.get_sender_id( "lead", "swe-46::user-99" )
        _, kwargs = bsi.call_args
        self.assertEqual( kwargs[ "suffix" ], "swe-46" )   # "::"-split keeps base


class TestCosaInterfaceDelegation( unittest.TestCase ):

    def test_notify_progress_delegates( self ):
        with patch.object( ci._dispatcher, "notify_progress", AsyncMock( return_value=None ) ) as m:
            _run( ci.notify_progress( "hi", role="coder", priority="low" ) )
        m.assert_awaited_once()
        self.assertEqual( m.await_args.kwargs[ "role" ], "coder" )

    def test_ask_confirmation_delegates( self ):
        with patch.object( ci._dispatcher, "ask_confirmation", AsyncMock( return_value=True ) ) as m:
            out = _run( ci.ask_confirmation( "ok?", role="lead", default="yes" ) )
        self.assertTrue( out )
        m.assert_awaited_once()

    def test_request_decision_delegates_to_present_choices( self ):
        with patch.object( ci._dispatcher, "present_choices", AsyncMock( return_value={ "answers": {} } ) ) as m:
            out = _run( ci.request_decision( "q", [ { "x": 1 } ], role="lead" ) )
        self.assertEqual( out, { "answers": {} } )
        m.assert_awaited_once()

    def test_get_feedback_delegates( self ):
        with patch.object( ci._dispatcher, "get_feedback", AsyncMock( return_value="fb" ) ) as m:
            out = _run( ci.get_feedback( "prompt", role="tester", timeout=9 ) )
        self.assertEqual( out, "fb" )
        m.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
