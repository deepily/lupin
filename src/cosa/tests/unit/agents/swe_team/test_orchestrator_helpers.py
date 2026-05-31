"""
Unit tests for swe_team/orchestrator.py — SweTeamOrchestrator HELPERS tier:
  __init__ (incl. proxy setup arcs), _notify, _emit_state, _gated_confirmation,
  _persist_trust_feedback, _on_circuit_breaker_trip, _emit_proxy_summary_notification,
  _check_in_with_user, _drain_user_messages, _parse_task_specs, _fallback_single_task,
  _build_agent_options, get_state, stop, _calculate_progress.

The async SDK-delegation PHASE methods live in test_orchestrator_phases.py.

ALL boundaries mocked: team_io (cosa_interface), the decision proxy + its TrustTracker/
CircuitBreaker, ConfigurationManager, requests (HTTP), get_db. NO LLM/SDK/network/DB.

Created 2026-05-31 by Extra 1 🪨 (CoSA coverage campaign, swe_team lane, orchestrator).
"""

import asyncio
import io
import sys
import types
import unittest
from contextlib import redirect_stdout
from unittest.mock import AsyncMock, MagicMock, patch

import cosa.agents.swe_team.orchestrator as orch_mod
from cosa.agents.swe_team.orchestrator import SweTeamOrchestrator
from cosa.agents.swe_team.config import SweTeamConfig
from cosa.agents.swe_team.state import OrchestratorState, TaskSpec
from cosa.agents.swe_team.safety_limits import SafetyLimitError


def _run( coro ):
    return asyncio.run( coro )


def _mk_orch( trust_mode="disabled", debug=False, **cfg_over ):
    """Construct an orchestrator with proxy disabled by default (no proxy setup)."""
    cfg = SweTeamConfig( dry_run=True, trust_mode=trust_mode, **cfg_over )
    return SweTeamOrchestrator( task_description="Build X", config=cfg, job_id="swe-1", debug=debug )


# ============================================================================
# __init__ — proxy setup arcs
# ============================================================================

class TestInit( unittest.TestCase ):

    def test_proxy_disabled_leaves_proxy_none( self ):
        o = _mk_orch( trust_mode="disabled" )
        self.assertIsNone( o.proxy )
        self.assertEqual( o.current_state, OrchestratorState.INITIALIZING )
        self.assertTrue( o.session_id )   # default st- id when none passed? job passes none here

    def test_default_session_id_when_none( self ):
        o = SweTeamOrchestrator( task_description="t", config=SweTeamConfig( trust_mode="disabled" ) )
        self.assertTrue( o.session_id.startswith( "st-" ) )

    def test_proxy_enabled_success_path( self ):
        # trust_mode != disabled → build TrustTracker + CircuitBreaker + EngineeringStrategy.
        with patch.object( orch_mod, "ConfigurationManager", create=True ) as CM:
            fake_proxy_mod = types.ModuleType( "cosa.agents.swe_team.proxy" )
            fake_proxy_mod.EngineeringStrategy = MagicMock( return_value="PROXY" )
            tt_mod  = types.ModuleType( "cosa.agents.decision_proxy.trust_tracker" )
            tt_mod.TrustTracker = MagicMock()
            cb_mod  = types.ModuleType( "cosa.agents.decision_proxy.circuit_breaker" )
            cb_mod.CircuitBreaker = MagicMock()
            cfg_mod = types.ModuleType( "cosa.agents.decision_proxy.config" )
            cfg_mod.trust_proxy_config_from_config_mgr = MagicMock( return_value={ "l2_threshold": 5 } )
            sweproxy_cfg_mod = types.ModuleType( "cosa.agents.swe_team.proxy.config" )
            sweproxy_cfg_mod.swe_proxy_config_from_config_mgr = MagicMock( return_value={ "accepted_senders": [ "a" ] } )
            cm_mod = types.ModuleType( "cosa.config.configuration_manager" )
            cm_mod.ConfigurationManager = MagicMock()
            mods = {
                "cosa.agents.swe_team.proxy"                : fake_proxy_mod,
                "cosa.agents.decision_proxy.trust_tracker"  : tt_mod,
                "cosa.agents.decision_proxy.circuit_breaker": cb_mod,
                "cosa.agents.decision_proxy.config"         : cfg_mod,
                "cosa.agents.swe_team.proxy.config"         : sweproxy_cfg_mod,
                "cosa.config.configuration_manager"         : cm_mod,
            }
            with patch.dict( sys.modules, mods ):
                o = SweTeamOrchestrator( task_description="t",
                                         config=SweTeamConfig( trust_mode="shadow" ) )
        self.assertEqual( o.proxy, "PROXY" )

    def test_proxy_enabled_inner_config_failure_uses_defaults( self ):
        fake_proxy_mod = types.ModuleType( "cosa.agents.swe_team.proxy" )
        fake_proxy_mod.EngineeringStrategy = MagicMock( return_value="PROXY" )
        tt_mod  = types.ModuleType( "cosa.agents.decision_proxy.trust_tracker" )
        tt_mod.TrustTracker = MagicMock()
        cb_mod  = types.ModuleType( "cosa.agents.decision_proxy.circuit_breaker" )
        cb_mod.CircuitBreaker = MagicMock()
        cm_mod = types.ModuleType( "cosa.config.configuration_manager" )
        cm_mod.ConfigurationManager = MagicMock( side_effect=RuntimeError( "ini boom" ) )
        mods = {
            "cosa.agents.swe_team.proxy"                : fake_proxy_mod,
            "cosa.agents.decision_proxy.trust_tracker"  : tt_mod,
            "cosa.agents.decision_proxy.circuit_breaker": cb_mod,
            "cosa.config.configuration_manager"         : cm_mod,
        }
        with patch.dict( sys.modules, mods ):
            o = SweTeamOrchestrator( task_description="t",
                                     config=SweTeamConfig( trust_mode="shadow" ) )
        self.assertEqual( o.proxy, "PROXY" )   # defaults used after inner failure

    def test_proxy_import_error_leaves_proxy_none( self ):
        # `from .proxy import EngineeringStrategy` raises ImportError → except arc.
        empty_proxy = types.ModuleType( "cosa.agents.swe_team.proxy" )  # no EngineeringStrategy attr
        with patch.dict( sys.modules, { "cosa.agents.swe_team.proxy": empty_proxy } ):
            o = SweTeamOrchestrator( task_description="t",
                                     config=SweTeamConfig( trust_mode="shadow" ) )
        self.assertIsNone( o.proxy )


# ============================================================================
# _notify / _emit_state
# ============================================================================

class TestNotifyAndEmit( unittest.TestCase ):

    def test_notify_with_job_id_passes_queue_run( self ):
        o = _mk_orch()
        team_io = MagicMock(); team_io.notify_progress = AsyncMock()
        _run( o._notify( team_io, "hi", role="coder", priority="low", abstract="a", progress_group_id="pg" ) )
        kwargs = team_io.notify_progress.await_args.kwargs
        self.assertEqual( kwargs[ "queue_name" ], "run" )
        self.assertEqual( kwargs[ "job_id" ], "swe-1" )

    def test_notify_without_job_id_passes_queue_none( self ):
        o = SweTeamOrchestrator( task_description="t", config=SweTeamConfig( trust_mode="disabled" ) )
        o.job_id = None
        team_io = MagicMock(); team_io.notify_progress = AsyncMock()
        _run( o._notify( team_io, "hi" ) )
        self.assertIsNone( team_io.notify_progress.await_args.kwargs[ "queue_name" ] )

    def test_emit_state_no_callback( self ):
        o = _mk_orch()
        _run( o._emit_state( OrchestratorState.INITIALIZING, OrchestratorState.CODING ) )  # no raise

    def test_emit_state_callback_invoked( self ):
        cb = AsyncMock()
        o = SweTeamOrchestrator( task_description="t", config=SweTeamConfig( trust_mode="disabled" ),
                                 on_state_change=cb )
        _run( o._emit_state( OrchestratorState.INITIALIZING, OrchestratorState.CODING, { "x": 1 } ) )
        cb.assert_awaited_once()

    def test_emit_state_callback_exception_swallowed( self ):
        cb = AsyncMock( side_effect=RuntimeError( "cb boom" ) )
        o = SweTeamOrchestrator( task_description="t", config=SweTeamConfig( trust_mode="disabled" ),
                                 on_state_change=cb )
        _run( o._emit_state( OrchestratorState.INITIALIZING, OrchestratorState.CODING ) )  # no raise


# ============================================================================
# _gated_confirmation
# ============================================================================

class TestGatedConfirmation( unittest.TestCase ):

    def _team_io( self, confirm=True ):
        t = MagicMock()
        t.ask_confirmation = AsyncMock( return_value=confirm )
        return t

    def test_no_proxy_falls_through_to_user( self ):
        o = _mk_orch( trust_mode="disabled" )   # proxy None
        t = self._team_io( confirm=True )
        out = _run( o._gated_confirmation( "ok?", "lead", "no", 60, None, t ) )
        self.assertTrue( out )
        t.ask_confirmation.assert_awaited_once()

    def _proxy( self, action, value="approved", trust_mode="active" ):
        p = MagicMock()
        p.trust_mode = trust_mode
        result = MagicMock( action=action, value=value, category="testing",
                            confidence=0.9, trust_level=3 )
        p.evaluate.return_value = result
        return p, result

    def test_active_act_auto_approves( self ):
        o = _mk_orch()
        o.proxy, _ = self._proxy( "act", value="approved" )
        t = MagicMock(); t.notify_progress = AsyncMock(); t.ask_confirmation = AsyncMock()
        with patch.object( o, "_notify", AsyncMock() ):
            out = _run( o._gated_confirmation( "deploy?", "lead", "no", 60, None, t ) )
        self.assertTrue( out )
        t.ask_confirmation.assert_not_awaited()   # auto-approved, never asked user

    def test_active_suggest_appends_note_then_asks( self ):
        o = _mk_orch( debug=True )
        o.proxy, _ = self._proxy( "suggest", value="approved" )
        t = self._team_io( confirm=True )
        with patch.object( o, "_persist_trust_feedback" ), \
             patch.object( o, "_emit_proxy_summary_notification" ):
            buf = io.StringIO()
            with redirect_stdout( buf ):
                out = _run( o._gated_confirmation( "q?", "lead", "no", 60, "base", t ) )
        self.assertTrue( out )
        # suggestion appended to abstract passed to ask_confirmation
        self.assertIn( "Proxy suggestion", t.ask_confirmation.await_args.args[ 4 ] )
        self.assertIn( "Proxy Feedback", buf.getvalue() )

    def test_active_defer_falls_through_and_summarizes( self ):
        # 282->287: active mode, action="defer" (not act, not suggest) → skip suggest-note,
        # ask user; step-4 emits proxy summary (defer ∈ {suggest,defer}).
        o = _mk_orch()
        o.proxy, _ = self._proxy( "defer", value="requires_review" )
        t = self._team_io( confirm=False )
        with patch.object( o, "_persist_trust_feedback" ), \
             patch.object( o, "_emit_proxy_summary_notification" ) as summary:
            out = _run( o._gated_confirmation( "q?", "lead", "no", 60, None, t ) )
        self.assertFalse( out )
        t.ask_confirmation.assert_awaited_once()
        summary.assert_called_once()   # defer → pending ratification

    def test_shadow_records_feedback_no_summary( self ):
        o = _mk_orch()
        o.proxy, _ = self._proxy( "shadow", value="requires_review", trust_mode="shadow" )
        t = self._team_io( confirm=False )
        with patch.object( o, "_persist_trust_feedback" ) as persist, \
             patch.object( o, "_emit_proxy_summary_notification" ) as summary:
            out = _run( o._gated_confirmation( "q?", "lead", "no", 60, None, t ) )
        self.assertFalse( out )
        persist.assert_called_once()
        summary.assert_not_called()   # shadow action → no pending ratification

    def test_evaluate_exception_swallowed( self ):
        o = _mk_orch()
        o.proxy = MagicMock( trust_mode="active" )
        o.proxy.evaluate.side_effect = RuntimeError( "eval boom" )
        t = self._team_io( confirm=True )
        out = _run( o._gated_confirmation( "q?", "lead", "no", 60, None, t ) )
        self.assertTrue( out )   # falls through; proxy_result None

    def test_feedback_recording_exception_swallowed( self ):
        o = _mk_orch()
        o.proxy, _ = self._proxy( "suggest", value="approved" )
        o.proxy.trust_tracker.record_decision.side_effect = RuntimeError( "rec boom" )
        t = self._team_io( confirm=True )
        out = _run( o._gated_confirmation( "q?", "lead", "no", 60, None, t ) )
        self.assertTrue( out )   # exception in step-4 swallowed


# ============================================================================
# _persist_trust_feedback / _on_circuit_breaker_trip / _emit_proxy_summary
# ============================================================================

class TestPersistAndAlerts( unittest.TestCase ):

    def test_persist_success( self ):
        o = _mk_orch()
        db_mod = types.ModuleType( "cosa.rest.db.database" )
        ctx = MagicMock(); ctx.__enter__ = MagicMock( return_value=MagicMock() ); ctx.__exit__ = MagicMock( return_value=False )
        db_mod.get_db = MagicMock( return_value=ctx )
        repo_mod = types.ModuleType( "cosa.rest.db.repositories.proxy_decision_repository" )
        repo_mod.TrustStateRepository = MagicMock()
        with patch.dict( sys.modules, { "cosa.rest.db.database": db_mod,
                                        "cosa.rest.db.repositories.proxy_decision_repository": repo_mod } ):
            o._persist_trust_feedback( "testing", True )
        repo_mod.TrustStateRepository.return_value.update_after_ratification.assert_called_once()

    def test_persist_exception_swallowed( self ):
        o = _mk_orch()
        db_mod = types.ModuleType( "cosa.rest.db.database" )
        db_mod.get_db = MagicMock( side_effect=RuntimeError( "db boom" ) )
        with patch.dict( sys.modules, { "cosa.rest.db.database": db_mod } ):
            o._persist_trust_feedback( "testing", False )   # no raise

    def test_circuit_breaker_trip_posts_alert( self ):
        o = _mk_orch()
        req_mod = types.ModuleType( "requests" )
        req_mod.post = MagicMock()
        with patch.dict( sys.modules, { "requests": req_mod } ):
            o._on_circuit_breaker_trip( "deploy", "too many errors" )
        req_mod.post.assert_called_once()

    def test_circuit_breaker_trip_exception_swallowed( self ):
        o = _mk_orch()
        req_mod = types.ModuleType( "requests" )
        req_mod.post = MagicMock( side_effect=RuntimeError( "net boom" ) )
        with patch.dict( sys.modules, { "requests": req_mod } ):
            o._on_circuit_breaker_trip( "deploy", "reason" )   # no raise

    def test_emit_proxy_summary_success_and_ws( self ):
        o = _mk_orch()
        o._proxy_pending_count = 2
        req_mod = types.ModuleType( "requests" )
        req_mod.get  = MagicMock( return_value=MagicMock( json=MagicMock( return_value={ "batch_id": "pr-1" } ) ) )
        req_mod.post = MagicMock()
        async def _go():
            with patch.dict( sys.modules, { "requests": req_mod } ), \
                 patch.object( o, "_notify", AsyncMock() ), \
                 patch.object( orch_mod.asyncio, "ensure_future", MagicMock() ):
                o._emit_proxy_summary_notification( "deploy", "suggest", 3, 0.9, "q?", MagicMock() )
        _run( _go() )
        req_mod.get.assert_called_once()
        req_mod.post.assert_called_once()

    def test_emit_proxy_summary_ws_failure_is_best_effort( self ):
        o = _mk_orch()
        o._proxy_pending_count = 1
        req_mod = types.ModuleType( "requests" )
        req_mod.get  = MagicMock( return_value=MagicMock( json=MagicMock( return_value={ "batch_id": "pr-1" } ) ) )
        req_mod.post = MagicMock( side_effect=RuntimeError( "ws boom" ) )
        async def _go():
            with patch.dict( sys.modules, { "requests": req_mod } ), \
                 patch.object( o, "_notify", AsyncMock() ), \
                 patch.object( orch_mod.asyncio, "ensure_future", MagicMock() ):
                o._emit_proxy_summary_notification( "deploy", "suggest", 3, 0.9, "q?", MagicMock() )
        _run( _go() )   # WS post failure swallowed

    def test_emit_proxy_summary_outer_exception_swallowed( self ):
        o = _mk_orch()
        req_mod = types.ModuleType( "requests" )
        req_mod.get = MagicMock( side_effect=RuntimeError( "batch boom" ) )
        with patch.dict( sys.modules, { "requests": req_mod } ):
            o._emit_proxy_summary_notification( "deploy", "suggest", 3, 0.9, "q?", MagicMock() )  # no raise


# ============================================================================
# _check_in_with_user / _drain_user_messages
# ============================================================================

class TestCheckInAndDrain( unittest.TestCase ):

    def test_checkin_disabled_returns_none( self ):
        o = _mk_orch( enable_checkins=False )
        self.assertIsNone( _run( o._check_in_with_user( MagicMock(), "prompt" ) ) )

    def test_checkin_substantive_feedback( self ):
        o = _mk_orch( enable_checkins=True )
        t = MagicMock()
        t.get_feedback = AsyncMock( return_value="please use module Y" )
        t.is_approval = MagicMock( return_value=False )
        with patch.object( o, "_drain_user_messages", return_value=[] ):
            out = _run( o._check_in_with_user( t, "prompt" ) )
        self.assertEqual( out, "please use module Y" )

    def test_checkin_approval_returns_none( self ):
        o = _mk_orch( enable_checkins=True )
        t = MagicMock()
        t.get_feedback = AsyncMock( return_value="yes go ahead" )
        t.is_approval = MagicMock( return_value=True )
        with patch.object( o, "_drain_user_messages", return_value=[] ):
            self.assertIsNone( _run( o._check_in_with_user( t, "prompt" ) ) )

    def test_checkin_with_queued_messages_approved( self ):
        o = _mk_orch( enable_checkins=True )
        t = MagicMock()
        t.get_feedback = AsyncMock( return_value=None )
        t.is_approval = MagicMock( return_value=True )
        with patch.object( o, "_drain_user_messages", return_value=[ { "message": "m", "priority": "normal" } ] ), \
             patch.object( o, "_analyze_user_messages", AsyncMock( return_value="ANALYSIS" ) ), \
             patch.object( o, "_notify", AsyncMock() ), \
             patch.object( o, "_gated_confirmation", AsyncMock( return_value=True ) ):
            out = _run( o._check_in_with_user( t, "prompt" ) )
        self.assertEqual( out, "ANALYSIS" )   # approved → analysis returned as feedback

    def test_checkin_queued_messages_not_approved_falls_to_feedback( self ):
        # 516->522: gated_confirmation False → skip the approved-return, fall to get_feedback.
        o = _mk_orch( enable_checkins=True )
        t = MagicMock()
        t.get_feedback = AsyncMock( return_value="more guidance" )
        t.is_approval = MagicMock( return_value=False )
        with patch.object( o, "_drain_user_messages", return_value=[ { "message": "m", "priority": "urgent" } ] ), \
             patch.object( o, "_analyze_user_messages", AsyncMock( return_value="ANALYSIS" ) ), \
             patch.object( o, "_notify", AsyncMock() ), \
             patch.object( o, "_gated_confirmation", AsyncMock( return_value=False ) ):
            out = _run( o._check_in_with_user( t, "prompt" ) )
        self.assertEqual( out, "more guidance" )

    def test_drain_empty_and_nonempty( self ):
        o = _mk_orch()
        self.assertEqual( o._drain_user_messages(), [] )
        o._user_messages.put( { "message": "a" } )
        o._user_messages.put( { "message": "b" } )
        drained = o._drain_user_messages()
        self.assertEqual( len( drained ), 2 )
        self.assertTrue( o._user_messages.empty() )


# ============================================================================
# _parse_task_specs / _fallback_single_task
# ============================================================================

class TestParseTaskSpecs( unittest.TestCase ):

    def setUp( self ):
        self.o = _mk_orch()

    def test_plain_json_array( self ):
        raw = '[{"title":"a","objective":"o","output_format":"f"}]'
        specs = self.o._parse_task_specs( raw )
        self.assertEqual( len( specs ), 1 )
        self.assertEqual( specs[ 0 ].title, "a" )

    def test_fenced_json( self ):
        raw = '```json\n[{"title":"a","objective":"o","output_format":"f"}]\n```'
        specs = self.o._parse_task_specs( raw )
        self.assertEqual( specs[ 0 ].title, "a" )

    def test_json_object_wrapped_to_list( self ):
        # `if not isinstance(data, list)` TRUE arc — single object → wrapped.
        raw = '{"title":"solo","objective":"o","output_format":"f"}'
        specs = self.o._parse_task_specs( raw )
        self.assertEqual( len( specs ), 1 )
        self.assertEqual( specs[ 0 ].title, "solo" )

    def test_empty_list_falls_back( self ):
        specs = self.o._parse_task_specs( "[]" )
        self.assertEqual( len( specs ), 1 )                    # fallback single task
        self.assertEqual( specs[ 0 ].objective, "Build X" )

    def test_invalid_json_falls_back( self ):
        specs = self.o._parse_task_specs( "{ not json" )
        self.assertEqual( len( specs ), 1 )
        self.assertEqual( specs[ 0 ].objective, "Build X" )

    def test_fallback_single_task_shape( self ):
        specs = self.o._fallback_single_task()
        self.assertEqual( len( specs ), 1 )
        self.assertEqual( specs[ 0 ].assigned_role, "coder" )


# ============================================================================
# _build_agent_options / get_state / stop / _calculate_progress
# ============================================================================

class TestBuildOptionsStateStop( unittest.TestCase ):

    def test_build_options_lead_plan_mode( self ):
        o = _mk_orch()
        opts = o._build_agent_options( "lead" )
        self.assertEqual( opts.permission_mode, "plan" )

    def test_build_options_coder_with_team_io_accept_edits( self ):
        o = _mk_orch()
        opts = o._build_agent_options( "coder", team_io=MagicMock() )
        self.assertEqual( opts.permission_mode, "acceptEdits" )
        self.assertIsNotNone( opts.can_use_tool )

    def test_build_options_tester_with_team_io( self ):
        o = _mk_orch()
        opts = o._build_agent_options( "tester", team_io=MagicMock() )
        self.assertEqual( opts.permission_mode, "acceptEdits" )

    def test_build_options_coder_without_team_io_plan( self ):
        o = _mk_orch()
        opts = o._build_agent_options( "coder", team_io=None )
        self.assertEqual( opts.permission_mode, "plan" )

    def test_get_state_proxy_disabled( self ):
        o = _mk_orch( trust_mode="disabled" )
        st = o.get_state()
        self.assertEqual( st[ "proxy_trust_mode" ], "disabled" )
        self.assertEqual( st[ "proxy_trust_levels" ], {} )

    def test_get_state_proxy_present( self ):
        o = _mk_orch()
        o.proxy = MagicMock( trust_mode="active" )
        o.proxy.trust_tracker.get_all_levels.return_value = { "testing": 3 }
        o.proxy.trust_tracker.get_stats.return_value = { "n": 1 }
        o.proxy.circuit_breaker.get_status.return_value = { "closed": True }
        st = o.get_state()
        self.assertEqual( st[ "proxy_trust_mode" ], "active" )
        self.assertEqual( st[ "proxy_trust_levels" ], { "testing": 3 } )

    def test_stop_sets_flag_and_state( self ):
        o = _mk_orch()
        out = _run( o.stop() )
        self.assertTrue( o._stop_requested )
        self.assertEqual( out[ "orchestrator_state" ], "stopped" )

    def test_calculate_progress_maps_states( self ):
        o = _mk_orch()
        o.current_state = OrchestratorState.INITIALIZING
        self.assertEqual( o._calculate_progress(), 5 )
        o.current_state = OrchestratorState.COMPLETED
        self.assertEqual( o._calculate_progress(), 100 )
        o.current_state = OrchestratorState.CODING
        self.assertEqual( o._calculate_progress(), 50 )


if __name__ == "__main__":
    unittest.main()
