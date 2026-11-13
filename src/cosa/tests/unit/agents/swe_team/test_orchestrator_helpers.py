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

from datetime import datetime, timezone
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

    def test_ask_switch_defaults_off_and_reads_ini_value( self ):
        # The switch comes from swe_cfg["ask_before_act"]; absent / failed INI read => False.
        def build( swe_cfg ):
            fake_proxy_mod = types.ModuleType( "cosa.agents.swe_team.proxy" )
            fake_proxy_mod.EngineeringStrategy = MagicMock( return_value="PROXY" )
            tt_mod  = types.ModuleType( "cosa.agents.decision_proxy.trust_tracker" )
            tt_mod.TrustTracker = MagicMock()
            cb_mod  = types.ModuleType( "cosa.agents.decision_proxy.circuit_breaker" )
            cb_mod.CircuitBreaker = MagicMock()
            cfg_mod = types.ModuleType( "cosa.agents.decision_proxy.config" )
            cfg_mod.trust_proxy_config_from_config_mgr = MagicMock( return_value={} )
            sweproxy_cfg_mod = types.ModuleType( "cosa.agents.swe_team.proxy.config" )
            sweproxy_cfg_mod.swe_proxy_config_from_config_mgr = MagicMock( return_value=swe_cfg )
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
                return SweTeamOrchestrator( task_description="t", config=SweTeamConfig( trust_mode="shadow" ) )

        self.assertTrue(  build( { "accepted_senders": [ "a" ], "ask_before_act": True } )._ask_before_act )
        self.assertFalse( build( { "accepted_senders": [ "a" ], "ask_before_act": False } )._ask_before_act )
        self.assertFalse( _mk_orch( trust_mode="disabled" )._ask_before_act )   # no proxy built => off

    def test_ini_l4_audit_sample_rate_reaches_the_strategy_and_absent_key_keeps_its_default( self ):
        # Row 6d7f809b: the INI key was read into config but never passed on, so the rate stayed 0.10.
        def build( proxy_cfg ):
            strategy_cls = MagicMock( return_value="PROXY" )
            fake_proxy_mod = types.ModuleType( "cosa.agents.swe_team.proxy" )
            fake_proxy_mod.EngineeringStrategy = strategy_cls
            tt_mod  = types.ModuleType( "cosa.agents.decision_proxy.trust_tracker" )
            tt_mod.TrustTracker = MagicMock()
            cb_mod  = types.ModuleType( "cosa.agents.decision_proxy.circuit_breaker" )
            cb_mod.CircuitBreaker = MagicMock()
            cfg_mod = types.ModuleType( "cosa.agents.decision_proxy.config" )
            cfg_mod.trust_proxy_config_from_config_mgr = MagicMock( return_value=proxy_cfg )
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
                SweTeamOrchestrator( task_description="t", config=SweTeamConfig( trust_mode="shadow" ) )
            return strategy_cls.call_args.kwargs

        self.assertEqual( build( { "l4_audit_sample_rate": 0.37 } )[ "l4_audit_rate" ], 0.37 )
        self.assertNotIn( "l4_audit_rate", build( {} ) )   # key absent => strategy default (0.10) applies

    def test_ini_trust_model_and_beta_thresholds_reach_the_tracker_and_absent_keys_keep_count( self ):
        # Row cfc7dd01: the trust model was never passed on, so beta and BLR could not be selected.
        def build( proxy_cfg ):
            tracker_cls = MagicMock()
            fake_proxy_mod = types.ModuleType( "cosa.agents.swe_team.proxy" )
            fake_proxy_mod.EngineeringStrategy = MagicMock( return_value="PROXY" )
            tt_mod  = types.ModuleType( "cosa.agents.decision_proxy.trust_tracker" )
            tt_mod.TrustTracker = tracker_cls
            cb_mod  = types.ModuleType( "cosa.agents.decision_proxy.circuit_breaker" )
            cb_mod.CircuitBreaker = MagicMock()
            cfg_mod = types.ModuleType( "cosa.agents.decision_proxy.config" )
            cfg_mod.trust_proxy_config_from_config_mgr = MagicMock( return_value=proxy_cfg )
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
                SweTeamOrchestrator( task_description="t", config=SweTeamConfig( trust_mode="shadow" ) )
            return tracker_cls.call_args.kwargs

        beta_cfg = { "trust_model": "blr" }
        for lvl, ( rate, n ) in zip( ( 2, 3, 4, 5 ), ( ( 0.1, 11 ), ( 0.2, 12 ), ( 0.3, 13 ), ( 0.4, 14 ) ) ):
            beta_cfg[ f"beta_l{lvl}_rate_threshold" ] = rate
            beta_cfg[ f"beta_l{lvl}_min_samples" ]    = n
        kw = build( beta_cfg )
        self.assertEqual( kw[ "trust_model" ], "blr" )
        self.assertEqual( kw[ "rate_thresholds" ], { 2: 0.1, 3: 0.2, 4: 0.3, 5: 0.4 } )
        self.assertEqual( kw[ "min_samples" ],     { 2: 11, 3: 12, 4: 13, 5: 14 } )
        kw = build( {} )
        self.assertEqual( kw[ "trust_model" ], "count" )                      # key absent => behaviour unchanged
        self.assertNotIn( "rate_thresholds", kw ); self.assertNotIn( "min_samples", kw )

    def _build_with_config_error( self, error ):
        # Same stubs as the sibling tests: the decision_proxy config, trust_tracker and circuit_breaker are all faked,
        # so the only thing that can raise out of the constructor is the error under test.
        from cosa.agents.decision_proxy.errors import InvalidTrustModelError   # noqa: F401  (real module, never faked)
        fake_proxy_mod = types.ModuleType( "cosa.agents.swe_team.proxy" )
        fake_proxy_mod.EngineeringStrategy = MagicMock( return_value="PROXY" )
        tt_mod  = types.ModuleType( "cosa.agents.decision_proxy.trust_tracker" )
        tt_mod.TrustTracker = MagicMock()
        cb_mod  = types.ModuleType( "cosa.agents.decision_proxy.circuit_breaker" )
        cb_mod.CircuitBreaker = MagicMock()
        cfg_mod = types.ModuleType( "cosa.agents.decision_proxy.config" )
        cfg_mod.trust_proxy_config_from_config_mgr = MagicMock( side_effect=error )
        sweproxy_cfg_mod = types.ModuleType( "cosa.agents.swe_team.proxy.config" )
        sweproxy_cfg_mod.swe_proxy_config_from_config_mgr = MagicMock( return_value={} )
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
            o = SweTeamOrchestrator( task_description="t", config=SweTeamConfig( trust_mode="shadow" ) )
        return o, fake_proxy_mod

    def test_an_unknown_trust_model_is_refused_at_startup_and_does_not_fall_back_to_defaults( self ):
        # Sam's review of row cfc7dd01: the factory's error for an unknown trust model was swallowed.
        from cosa.agents.decision_proxy.errors import InvalidTrustModelError
        with self.assertRaisesRegex( InvalidTrustModelError, "trust model must be one of" ):
            self._build_with_config_error( InvalidTrustModelError( "trust model must be one of" ) )

    def test_any_other_ini_read_failure_stays_non_fatal_and_builds_the_proxy_on_defaults( self ):
        # A non-numeric INI value (a plain ValueError) must not crash the constructor.
        o, proxy_mod = self._build_with_config_error( ValueError( "invalid literal for int()" ) )
        self.assertEqual( o.proxy, "PROXY" )
        proxy_mod.EngineeringStrategy.assert_called_once()

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
        config = SweTeamConfig( trust_mode="shadow" )   # built before the patch: its model ids are read from the real INI
        with patch.dict( sys.modules, mods ):
            o = SweTeamOrchestrator( task_description="t", config=config )
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

    def setUp( self ):
        # _persist_proxy_decision opens a real DB session; these tests are about the gate, not the row
        patcher = patch.object( SweTeamOrchestrator, "_persist_proxy_decision" )
        patcher.start()
        self.addCleanup( patcher.stop )

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

    def test_a_human_yes_at_l1_shadow_is_recorded_as_agreement_not_a_proxy_failure( self ):
        # Row c73bcfa0 (D1): the REAL strategy and tracker, nothing mocked but the human and the DB.
        # At L1 gate() returns "shadow"; evaluate() used to leave value None, so a human "yes"
        # scored as disagreement and every L1 yes counted as a proxy failure.
        from cosa.agents.swe_team.proxy import EngineeringStrategy
        from cosa.agents.decision_proxy.trust_tracker import TrustTracker
        o       = _mk_orch()
        tracker = TrustTracker()
        o.proxy = EngineeringStrategy( trust_tracker=tracker, trust_mode="shadow" )
        t       = self._team_io( confirm=True )
        with patch.object( o, "_persist_trust_feedback" ) as persist:
            out = _run( o._gated_confirmation( "should we run the unit tests?", "lead", "no", 60, None, t ) )
        self.assertTrue( out )
        stats = tracker.get_stats()
        recorded = { name: c for name, c in stats.items() if c[ "total_decisions" ] }
        self.assertEqual( len( recorded ), 1, recorded )
        cat = next( iter( recorded.values() ) )
        self.assertEqual( ( cat[ "total_successes" ], cat[ "total_rejections" ] ), ( 1, 0 ), cat )
        persist.assert_called_once()
        self.assertTrue( persist.call_args.args[ 1 ], "the DB write must carry agreement=True too" )

    def test_a_real_blr_tracker_learns_from_the_humans_answer_through_the_gate( self ):
        # Row cfc7dd01, end to end: real strategy, real tracker; only the human and the DB are faked.
        from cosa.agents.swe_team.proxy import EngineeringStrategy
        from cosa.agents.decision_proxy.trust_tracker import TrustTracker
        o       = _mk_orch()
        tracker = TrustTracker( trust_model="blr" )
        o.proxy = EngineeringStrategy( trust_tracker=tracker, trust_mode="shadow" )
        t       = self._team_io( confirm=True )
        with patch.object( o, "_persist_trust_feedback" ):
            _run( o._gated_confirmation( "should we run the unit tests?", "lead", "no", 60, None, t ) )
        fed = [ c for c in tracker.categories.values() if c._blr_model is not None ]
        self.assertEqual( len( fed ), 1 )
        self.assertEqual( fed[ 0 ]._blr_model._feature_count, 1 )

    def test_a_human_no_where_the_proxy_would_approve_is_still_a_disagreement( self ):
        from cosa.agents.swe_team.proxy import EngineeringStrategy
        from cosa.agents.decision_proxy.trust_tracker import TrustTracker
        o       = _mk_orch()
        tracker = TrustTracker()
        o.proxy = EngineeringStrategy( trust_tracker=tracker, trust_mode="shadow" )
        t       = self._team_io( confirm=False )
        with patch.object( o, "_persist_trust_feedback" ):
            _run( o._gated_confirmation( "should we run the unit tests?", "lead", "no", 60, None, t ) )
        cat = next( c for c in tracker.get_stats().values() if c[ "total_decisions" ] )
        self.assertEqual( ( cat[ "total_successes" ], cat[ "total_rejections" ] ), ( 0, 1 ), cat )

    # ── D2 (row 251f26fb): trust persists across jobs, keyed by the user's email ──

    @staticmethod
    def _fake_trust_db():
        """
        An in-memory trust store with real transactions.

        Rows are keyed by (user, domain, category).
        A session works on copies; a clean exit commits them and an exception rolls them back.
        """
        import copy
        rows = {}
        class Row:
            def __init__( self, category ):
                self.category = category; self.successful_decisions = 0; self.rejected_decisions = 0; self.trust_level = 1; self.circuit_breaker_state = None; self.decision_history = None; self.blr_state = None
                from datetime import datetime, timezone
                self.updated_at = datetime.now( timezone.utc )
        class Session:
            def __init__( self ): self.work = { k: copy.copy( v ) for k, v in rows.items() }
        class Repo:
            def __init__( self, session ): self.work = session.work
            def update_after_ratification( self, user_email, domain, category, approved, **extra ):
                row = self.work.setdefault( ( user_email, domain, category ), Row( category ) )
                if "blr_state" in extra: row.blr_state = extra[ "blr_state" ]
                if approved: row.successful_decisions += 1
                else:        row.rejected_decisions   += 1
                return row
            def update_trust_level( self, user_email, domain, category, new_level ):
                row = self.work.setdefault( ( user_email, domain, category ), Row( category ) )
                row.trust_level = new_level
                return row
            def update_circuit_breaker_state( self, user_email, domain, category, cb_state ):
                row = self.work.setdefault( ( user_email, domain, category ), Row( category ) )
                row.circuit_breaker_state = cb_state
                return row
            def get_all_for_user( self, user_email, domain=None ):
                return [ r for ( u, d, _ ), r in self.work.items() if u == user_email and d == domain ]
        class Db:
            def __enter__( self ):
                self.session = Session()
                return self.session
            def __exit__( self, exc_type, exc, tb ):
                if exc_type is None:                              # commit: keep object identity for rows that already exist
                    for key, row in self.session.work.items():
                        if key in rows: rows[ key ].__dict__.update( row.__dict__ )
                        else:           rows[ key ] = row
                return False                                      # on an exception nothing is committed
        return rows, Repo, Db

    def _job( self, user_email, session_id, Repo, Db, confirm=True, trust_mode="shadow" ):
        cfg = SweTeamConfig( dry_run=True, trust_mode=trust_mode )
        with patch( "cosa.rest.db.database.get_db", lambda: Db() ), \
             patch( "cosa.rest.db.repositories.proxy_decision_repository.TrustStateRepository", Repo ):
            o = SweTeamOrchestrator( task_description="t", config=cfg, session_id=session_id, user_email=user_email )
            t = self._team_io( confirm=confirm )
            _run( o._gated_confirmation( "should we run the unit tests?", "lead", "no", 60, None, t ) )
        return o

    def test_two_jobs_for_one_user_accumulate_trust_under_one_key_and_the_second_job_loads_it( self ):
        rows, Repo, Db = self._fake_trust_db()
        first  = self._job( "rick@example.com", "st-job-one", Repo, Db )
        second = self._job( "rick@example.com", "st-job-two", Repo, Db )
        self.assertEqual( { k[ 0 ] for k in rows }, { "rick@example.com" }, "rows must not be keyed by the per-job session id" )
        self.assertEqual( sum( r.successful_decisions for r in rows.values() ), 2 )
        cat = next( c for c in second.proxy.trust_tracker.get_stats().values() if c[ "total_decisions" ] )
        self.assertEqual( cat[ "total_decisions" ], 2, "job two started from job one's stored decision, then added its own" )
        self.assertEqual( cat[ "total_successes" ], 2 )

    def test_the_stored_level_follows_the_trackers_level_instead_of_staying_at_one( self ):
        # Row 139cddd6 (D11): nothing wrote trust_level, so every stored row read L1.
        rows, Repo, Db = self._fake_trust_db()
        from cosa.agents.decision_proxy.trust_tracker import TrustTracker
        from cosa.agents.swe_team.proxy import EngineeringStrategy
        o = SweTeamOrchestrator( task_description="t", config=SweTeamConfig( dry_run=True, trust_mode="shadow" ),
                                 session_id="st-x", user_email="rick@example.com" )
        o.proxy = EngineeringStrategy( trust_tracker=TrustTracker( l2_threshold=1, l3_threshold=2, l4_threshold=3, l5_threshold=4 ),
                                       trust_mode="shadow" )
        t = self._team_io( confirm=True )
        with patch( "cosa.rest.db.database.get_db", lambda: Db() ), \
             patch( "cosa.rest.db.repositories.proxy_decision_repository.TrustStateRepository", Repo ):
            for _ in range( 3 ):
                _run( o._gated_confirmation( "should we run the unit tests?", "lead", "no", 60, None, t ) )
        row   = next( iter( rows.values() ) )
        level = o.proxy.trust_tracker.get_level( row.category )
        self.assertGreater( level, 1, "three agreeing answers against thresholds 1/2/3/4 must lift the level" )
        self.assertEqual( row.trust_level, level )
        self.assertEqual( row.successful_decisions, 3 )

    def _level_job( self, Repo, Db ):
        """A shadow job whose tracker graduates quickly: thresholds 1/2/3/4."""
        from cosa.agents.decision_proxy.trust_tracker import TrustTracker
        from cosa.agents.swe_team.proxy import EngineeringStrategy
        o = SweTeamOrchestrator( task_description="t", config=SweTeamConfig( dry_run=True, trust_mode="shadow" ),
                                 session_id="st-x", user_email="rick@example.com" )
        o.proxy = EngineeringStrategy( trust_tracker=TrustTracker( l2_threshold=1, l3_threshold=2, l4_threshold=3, l5_threshold=4 ),
                                       trust_mode="shadow" )
        return o

    def _answer( self, o, Repo, Db, times=1, confirm=True ):
        t = self._team_io( confirm=confirm )
        with patch( "cosa.rest.db.database.get_db", lambda: Db() ), \
             patch( "cosa.rest.db.repositories.proxy_decision_repository.TrustStateRepository", Repo ):
            for _ in range( times ):
                _run( o._gated_confirmation( "should we run the unit tests?", "lead", "no", 60, None, t ) )

    def test_a_demoted_tracker_level_is_what_gets_stored_on_the_next_answer( self ):
        # John's D11 review: promotion alone is not enough; a LOWER level must be stored too.
        rows, Repo, Db = self._fake_trust_db()
        o = self._level_job( Repo, Db )
        self._answer( o, Repo, Db, times=3 )
        row    = next( iter( rows.values() ) )
        before = row.trust_level
        self.assertGreater( before, 1 )
        o.proxy.trust_tracker.demote_category( row.category, 2 )                  # what a breaker trip does
        lowered = o.proxy.trust_tracker.get_level( row.category )
        self.assertLess( lowered, before )
        self._answer( o, Repo, Db, times=1, confirm=False )                     # a rejection adds no graduation credit
        self.assertEqual( row.trust_level, o.proxy.trust_tracker.get_level( row.category ) )
        self.assertLess( row.trust_level, before, "the lower level must replace the old one in the store" )

    def test_a_circuit_breaker_trip_stores_the_demoted_level_without_waiting_for_feedback( self ):
        # Row d2d6a192: the breaker demotes in memory only; the trip callback must carry it to the store.
        rows, Repo, Db = self._fake_trust_db()
        o = self._level_job( Repo, Db )
        self._answer( o, Repo, Db, times=3 )
        row    = next( iter( rows.values() ) )
        before = row.trust_level
        o.proxy.trust_tracker.demote_category( row.category, 2 )
        with patch( "cosa.rest.db.database.get_db", lambda: Db() ), \
             patch( "cosa.rest.db.repositories.proxy_decision_repository.TrustStateRepository", Repo ), \
             patch( "requests.post" ):
            o._on_circuit_breaker_trip( row.category, "error rate" )
        self.assertLess( row.trust_level, before )
        self.assertEqual( row.trust_level, o.proxy.trust_tracker.get_level( row.category ) )

    def test_a_breaker_demotion_survives_the_next_job_through_the_recorded_trip( self ):
        # A trip is recorded in circuit_breaker_state and caps the restored level until it is earned back.
        rows, Repo, Db = self._fake_trust_db()
        o = self._level_job( Repo, Db )
        self._answer( o, Repo, Db, times=3 )
        row     = next( iter( rows.values() ) )
        earned  = o.proxy.trust_tracker.get_level( row.category )
        self.assertGreater( earned, 2 )
        o.proxy.circuit_breaker.on_trip_callback = o._on_circuit_breaker_trip
        with patch( "cosa.rest.db.database.get_db", lambda: Db() ), \
             patch( "cosa.rest.db.repositories.proxy_decision_repository.TrustStateRepository", Repo ), \
             patch( "requests.post" ):
            o.proxy.circuit_breaker.trip( row.category, "error rate" )              # the real breaker demotes, then calls back
        demoted = o.proxy.trust_tracker.get_level( row.category )
        self.assertLess( demoted, earned )
        self.assertEqual( row.trust_level, demoted, "the trip stored the demoted level" )
        self.assertEqual( row.circuit_breaker_state, { "status": "tripped", "tripped_level": demoted, "successes_at_trip": 3 } )
        self.assertEqual( row.successful_decisions, 3, "the counters are unchanged by a demotion" )

        with patch( "cosa.rest.db.database.get_db", lambda: Db() ), \
             patch( "cosa.rest.db.repositories.proxy_decision_repository.TrustStateRepository", Repo ):
            fresh = SweTeamOrchestrator( task_description="t", config=SweTeamConfig( dry_run=True, trust_mode="shadow" ),
                                         session_id="st-next", user_email="rick@example.com" )
        # Same low thresholds as the first job, so the counters alone would earn the higher level again.
        from cosa.agents.decision_proxy.trust_tracker import TrustTracker
        from cosa.agents.swe_team.proxy import EngineeringStrategy
        fresh.proxy = EngineeringStrategy( trust_tracker=TrustTracker( l2_threshold=1, l3_threshold=2, l4_threshold=3, l5_threshold=4 ),
                                           trust_mode="shadow" )
        with patch( "cosa.rest.db.database.get_db", lambda: Db() ), \
             patch( "cosa.rest.db.repositories.proxy_decision_repository.TrustStateRepository", Repo ):
            self.assertEqual( fresh._load_trust_state(), 1 )
        self.assertEqual( fresh.proxy.trust_tracker.get_level( row.category ), demoted )

    def _fresh_load( self, Repo, Db ):
        """A new job for the same user: fresh orchestrator and tracker, rows loaded."""
        from cosa.agents.decision_proxy.trust_tracker import TrustTracker
        from cosa.agents.swe_team.proxy import EngineeringStrategy
        with patch( "cosa.rest.db.database.get_db", lambda: Db() ), \
             patch( "cosa.rest.db.repositories.proxy_decision_repository.TrustStateRepository", Repo ):
            o = SweTeamOrchestrator( task_description="t", config=SweTeamConfig( dry_run=True, trust_mode="shadow" ),
                                     session_id="st-next", user_email="rick@example.com" )
            o.proxy = EngineeringStrategy( trust_tracker=TrustTracker( l2_threshold=1, l3_threshold=2, l4_threshold=3, l5_threshold=4 ),
                                           trust_mode="shadow" )
            o._load_trust_state()
        return o

    def test_a_category_with_stored_level_one_and_no_trip_climbs_across_fresh_trackers( self ):
        # Mr. Radio's follow-up: a stored level must not ratchet the next job down.
        rows, Repo, Db = self._fake_trust_db()
        o = self._level_job( Repo, Db )
        self._answer( o, Repo, Db, times=2 )
        row = next( iter( rows.values() ) )
        row.trust_level = 1                                                       # e.g. a row only a human ratification wrote
        self.assertIsNone( row.circuit_breaker_state )
        second = self._fresh_load( Repo, Db )
        self.assertGreater( second.proxy.trust_tracker.get_level( row.category ), 1, "counters alone must lift it past the stored 1" )
        self._answer( second, Repo, Db, times=2 )
        third = self._fresh_load( Repo, Db )
        self.assertGreater( third.proxy.trust_tracker.get_level( row.category ), 2, "a later job starts from the climbed level" )
        self.assertGreater( row.trust_level, 2, "two jobs later the category has climbed further" )

    def test_a_tripped_category_stays_capped_across_fresh_trackers_until_it_earns_the_level_back( self ):
        rows, Repo, Db = self._fake_trust_db()
        o = self._level_job( Repo, Db )
        self._answer( o, Repo, Db, times=4 )
        row = next( iter( rows.values() ) )
        o.proxy.circuit_breaker.on_trip_callback = o._on_circuit_breaker_trip
        with patch( "cosa.rest.db.database.get_db", lambda: Db() ), \
             patch( "cosa.rest.db.repositories.proxy_decision_repository.TrustStateRepository", Repo ), \
             patch( "requests.post" ):
            o.proxy.circuit_breaker.trip( row.category, "error rate" )
        capped = row.trust_level
        self.assertIsNotNone( row.circuit_breaker_state )

        second = self._fresh_load( Repo, Db )
        self.assertEqual( second.proxy.trust_tracker.get_level( row.category ), capped, "the cap survives a new job" )
        self.assertEqual( self._fresh_load( Repo, Db ).proxy.trust_tracker.get_level( row.category ), capped )

        self._answer( second, Repo, Db, times=2 )                                 # earns back the gap above the cap
        self.assertIsNone( row.circuit_breaker_state, "the trip is cleared once the level is earned back" )
        self.assertGreater( second.proxy.trust_tracker.get_level( row.category ), capped )
        self.assertGreater( self._fresh_load( Repo, Db ).proxy.trust_tracker.get_level( row.category ), capped )

    def test_a_failing_level_write_keeps_the_counters_and_the_job_going( self ):
        # John's D11 review: with transactional rows, a level write that raises must not take the committed
        # counter update with it. Both writes in ONE transaction would roll the counters back and fail this test.
        rows, Repo, Db = self._fake_trust_db()
        def boom( self, *a, **k ): raise RuntimeError( "level write failed" )
        Repo.update_trust_level = boom
        o = self._level_job( Repo, Db )
        t = self._team_io( confirm=True )
        with patch( "cosa.rest.db.database.get_db", lambda: Db() ), \
             patch( "cosa.rest.db.repositories.proxy_decision_repository.TrustStateRepository", Repo ):
            outs = [ _run( o._gated_confirmation( "should we run the unit tests?", "lead", "no", 60, None, t ) ) for _ in range( 2 ) ]
        self.assertEqual( outs, [ True, True ], "the job carries on with the human's answer" )
        row = next( iter( rows.values() ) )
        self.assertEqual( row.successful_decisions, 2, "both counter updates were committed" )
        self.assertEqual( row.trust_level, 1, "the level write failed and committed nothing" )

    def test_the_fake_store_really_rolls_back_a_transaction_that_raises( self ):
        # The control for the test above: prove the fake can lose a write, or its pass means nothing.
        rows, Repo, Db = self._fake_trust_db()
        with self.assertRaises( RuntimeError ):
            with Db() as session:
                Repo( session ).update_after_ratification( "u", "swe", "testing", True )
                raise RuntimeError( "boom" )
        self.assertEqual( rows, {} )

    def test_persisting_a_level_with_no_proxy_does_nothing( self ):
        o = _mk_orch( trust_mode="disabled" )
        with patch( "cosa.rest.db.database.get_db", side_effect=AssertionError( "must not touch the DB" ) ):
            o._persist_trust_level( "testing" )

    def test_a_different_user_does_not_inherit_another_users_trust( self ):
        rows, Repo, Db = self._fake_trust_db()
        self._job( "rick@example.com", "st-a", Repo, Db )
        with patch( "cosa.rest.db.database.get_db", lambda: Db() ), \
             patch( "cosa.rest.db.repositories.proxy_decision_repository.TrustStateRepository", Repo ):
            other = SweTeamOrchestrator( task_description="t", config=SweTeamConfig( dry_run=True, trust_mode="shadow" ),
                                         session_id="st-b", user_email="someone@example.com" )
        self.assertEqual( sum( c[ "total_decisions" ] for c in other.proxy.trust_tracker.get_stats().values() ), 0 )

    def test_no_user_email_means_no_db_read( self ):
        o = _mk_orch( trust_mode="shadow" )
        with patch( "cosa.rest.db.database.get_db", side_effect=AssertionError( "must not read the DB" ) ):
            self.assertEqual( o._load_trust_state(), 0 )

    def test_no_proxy_means_nothing_to_load( self ):
        o = _mk_orch( trust_mode="disabled" )
        o._user_email = "rick@example.com"
        self.assertEqual( o._load_trust_state(), 0 )

    def test_a_stored_decision_history_reaches_the_tracker_so_old_days_age_out( self ):
        # Row da64aaab: without the history every restored decision was stamped with updated_at.
        from datetime import datetime, timedelta, timezone
        from cosa.agents.decision_proxy.trust_tracker import TrustTracker
        from cosa.agents.swe_team.proxy import EngineeringStrategy
        now = datetime.now( timezone.utc )
        old, fresh = ( now - timedelta( days=60 ) ).strftime( "%Y-%m-%d" ), now.strftime( "%Y-%m-%d" )
        row = MagicMock( category="testing", successful_decisions=5, rejected_decisions=2, circuit_breaker_state=None,
                         decision_history={ old: [ 5, 0 ], fresh: [ 0, 2 ] } )
        row.updated_at = now
        Repo = MagicMock(); Repo.return_value.get_all_for_user.return_value = [ row ]
        o = _mk_orch( trust_mode="shadow" )
        o._user_email = "rick@example.com"
        o.proxy = EngineeringStrategy( trust_tracker=TrustTracker( rolling_window_days=30 ), trust_mode="shadow" )
        with patch( "cosa.rest.db.database.get_db", MagicMock() ), \
             patch( "cosa.rest.db.repositories.proxy_decision_repository.TrustStateRepository", Repo ):
            self.assertEqual( o._load_trust_state(), 1 )
        cat = o.proxy.trust_tracker.categories[ "testing" ]
        self.assertEqual( ( cat.total_successes, cat.total_rejections ), ( 5, 2 ) )
        self.assertEqual( [ ok for _, ok in cat.decisions ], [ False, False ], "the 60-day-old successes left the window" )

    def test_a_row_the_tracker_refuses_is_skipped_not_counted( self ):
        o = _mk_orch( trust_mode="shadow" )
        o._user_email = "rick@example.com"
        row = MagicMock( category="nope", successful_decisions=1, rejected_decisions=0, circuit_breaker_state=None )
        row.updated_at.timestamp.return_value = 1.0
        Repo = MagicMock(); Repo.return_value.get_all_for_user.return_value = [ row ]
        with patch( "cosa.rest.db.database.get_db", MagicMock() ), \
             patch( "cosa.rest.db.repositories.proxy_decision_repository.TrustStateRepository", Repo ), \
             patch.object( o.proxy.trust_tracker, "restore_category", return_value=False ):
            self.assertEqual( o._load_trust_state(), 0 )

    def test_persisting_a_level_for_a_category_the_tracker_lacks_skips_the_trip_write( self ):
        o = _mk_orch( trust_mode="shadow" )
        o._user_email = "rick@example.com"
        Repo = MagicMock()
        with patch( "cosa.rest.db.database.get_db", MagicMock() ), \
             patch( "cosa.rest.db.repositories.proxy_decision_repository.TrustStateRepository", Repo ):
            o._persist_trust_level( "never-seen" )
        Repo.return_value.update_trust_level.assert_called_once()
        Repo.return_value.update_circuit_breaker_state.assert_not_called()

    def test_a_failing_db_read_is_logged_and_returns_zero( self ):
        o = _mk_orch( trust_mode="shadow" )
        o._user_email = "rick@example.com"
        with patch( "cosa.rest.db.database.get_db", side_effect=RuntimeError( "db down" ) ):
            self.assertEqual( o._load_trust_state(), 0 )

    def test_active_act_auto_approves( self ):
        o = _mk_orch()
        o.proxy, _ = self._proxy( "act", value="approved" )
        t = MagicMock(); t.notify_progress = AsyncMock(); t.ask_confirmation = AsyncMock()
        with patch.object( o, "_notify", AsyncMock() ):
            out = _run( o._gated_confirmation( "deploy?", "lead", "no", 60, None, t ) )
        self.assertTrue( out )
        t.ask_confirmation.assert_not_awaited()   # auto-approved, never asked user
        o.proxy.trust_tracker.record_decision.assert_not_called()   # no human verdict, so no trust credit

    def test_an_auto_approval_leaves_the_real_tracker_and_the_db_untouched( self ):
        # Row 0bba595e (D3), real strategy and tracker: act at L5 in active mode with the ask switch off.
        from cosa.agents.swe_team.proxy import EngineeringStrategy
        from cosa.agents.decision_proxy.trust_tracker import TrustTracker
        o       = _mk_orch()
        tracker = TrustTracker()
        o.proxy = EngineeringStrategy( trust_tracker=tracker, trust_mode="active" )
        t       = MagicMock(); t.ask_confirmation = AsyncMock()
        o.proxy.gate = MagicMock( return_value="act" )
        with patch.object( o, "_notify", AsyncMock() ), patch.object( o, "_persist_trust_feedback" ) as persist:
            out = _run( o._gated_confirmation( "should we run the unit tests?", "lead", "no", 60, None, t ) )
        self.assertTrue( out )
        t.ask_confirmation.assert_not_awaited()
        self.assertEqual( sum( c[ "total_decisions" ] for c in tracker.get_stats().values() ), 0 )
        persist.assert_not_called()

    def test_active_act_with_ask_switch_on_asks_and_does_not_auto_approve( self ):
        # Switch ON + action "act": the "[Auto-approved by proxy]" return must NOT happen;
        # the gate falls through to ask_confirmation exactly once.
        o = _mk_orch()
        o._ask_before_act = True
        o.proxy, _ = self._proxy( "act", value="approved" )
        t = self._team_io( confirm=False )
        with patch.object( o, "_notify", AsyncMock() ) as notify, \
             patch.object( o, "_persist_trust_feedback" ) as persist, \
             patch.object( o, "_emit_proxy_summary_notification" ):
            out = _run( o._gated_confirmation( "deploy?", "lead", "no", 60, None, t ) )
        self.assertFalse( out )   # the user's answer, not the proxy's "approved"
        t.ask_confirmation.assert_awaited_once()
        notify.assert_not_awaited()   # no "[Auto-approved by proxy]" message sent
        persist.assert_called_once()  # trust feedback recorded after the asked answer

    def test_active_act_with_ask_switch_off_still_auto_approves( self ):
        # Switch OFF (explicit): path = step-2 auto-approve, user never asked.
        o = _mk_orch()
        o._ask_before_act = False
        o.proxy, _ = self._proxy( "act", value="approved" )
        t = self._team_io( confirm=False )
        with patch.object( o, "_notify", AsyncMock() ) as notify:
            out = _run( o._gated_confirmation( "deploy?", "lead", "no", 60, None, t ) )
        self.assertTrue( out )
        t.ask_confirmation.assert_not_awaited()
        self.assertIn( "[Auto-approved by proxy]", notify.await_args.kwargs[ "message" ] )

    def test_ask_switch_on_with_suggest_behaves_as_today( self ):
        # Switch ON + action "suggest": path = step-2 suggest note, then step-3 ask (unchanged).
        o = _mk_orch()
        o._ask_before_act = True
        o.proxy, _ = self._proxy( "suggest", value="approved" )
        t = self._team_io( confirm=True )
        with patch.object( o, "_persist_trust_feedback" ), \
             patch.object( o, "_emit_proxy_summary_notification" ):
            out = _run( o._gated_confirmation( "q?", "lead", "no", 60, "base", t ) )
        self.assertTrue( out )
        t.ask_confirmation.assert_awaited_once()
        self.assertIn( "Proxy suggestion", t.ask_confirmation.await_args.args[ 4 ] )

    def test_ask_switch_on_with_defer_behaves_as_today( self ):
        # Switch ON + action "defer": path = step-3 ask, step-4 summary (unchanged).
        o = _mk_orch()
        o._ask_before_act = True
        o.proxy, _ = self._proxy( "defer", value="requires_review" )
        t = self._team_io( confirm=False )
        with patch.object( o, "_persist_trust_feedback" ), \
             patch.object( o, "_emit_proxy_summary_notification" ) as summary:
            out = _run( o._gated_confirmation( "q?", "lead", "no", 60, None, t ) )
        self.assertFalse( out )
        t.ask_confirmation.assert_awaited_once()
        summary.assert_called_once()

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

    def test_blr_model_records_the_ratified_decision_with_features_and_others_do_not( self ):
        # Row cfc7dd01: BLR is fed from the path that records the human's answer.
        for model, fed in ( ( "blr", True ), ( "beta", False ), ( "count", False ) ):
            o = _mk_orch()
            o.proxy, _ = self._proxy( "shadow", value="approved", trust_mode="shadow" )
            o.proxy.trust_tracker.trust_model = model
            t = self._team_io( confirm=True )
            with patch.object( o, "_persist_trust_feedback" ):
                _run( o._gated_confirmation( "q words?", "lead", "no", 60, None, t ) )
            tracker = o.proxy.trust_tracker
            if fed:
                tracker.record_decision_with_features.assert_called_once()
                self.assertEqual( tracker.record_decision_with_features.call_args.args[ 1: ], ( True, "q words?" ) )
                tracker.record_decision.assert_not_called()
            else:
                tracker.record_decision.assert_called_once()
                tracker.record_decision_with_features.assert_not_called()

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

    def _persist_kwargs( self, o, tracker_model=None ):
        """Run _persist_trust_feedback on a mocked repo; return the repo write's kwargs."""
        db_mod = types.ModuleType( "cosa.rest.db.database" )
        ctx = MagicMock(); ctx.__enter__ = MagicMock( return_value=MagicMock() ); ctx.__exit__ = MagicMock( return_value=False )
        db_mod.get_db = MagicMock( return_value=ctx )
        repo_mod = types.ModuleType( "cosa.rest.db.repositories.proxy_decision_repository" )
        repo_mod.TrustStateRepository = MagicMock()
        with patch.dict( sys.modules, { "cosa.rest.db.database": db_mod,
                                        "cosa.rest.db.repositories.proxy_decision_repository": repo_mod } ):
            o._persist_trust_feedback( "testing", True )
        return repo_mod.TrustStateRepository.return_value.update_after_ratification.call_args.kwargs

    def test_persist_stores_the_blr_state_with_the_blr_model( self ):
        # Row 5bb93a7b, round trip: what persist writes is what load restores into a fresh tracker.
        import numpy as np
        from cosa.agents.decision_proxy.trust_tracker import TrustTracker
        from cosa.agents.swe_team.proxy import EngineeringStrategy
        tracker = TrustTracker( trust_model="blr" )
        tracker.register_category( "testing" )
        for i in range( 10 ): tracker.record_decision_with_features( "testing", i % 3 != 0, f"question number {i}?" )
        o = _mk_orch(); o.proxy = EngineeringStrategy( trust_tracker=tracker, trust_mode="shadow" )
        with patch.object( o, "_persist_trust_level" ):
            kwargs = self._persist_kwargs( o )
        self.assertEqual( kwargs[ "blr_state" ], tracker.blr_state_for( "testing" ) )

        fresh = TrustTracker( trust_model="blr" ); fresh.register_category( "testing" )
        o2 = _mk_orch(); o2._user_email = "rick@example.com"
        o2.proxy = EngineeringStrategy( trust_tracker=fresh, trust_mode="shadow" )
        row = MagicMock( category="testing", successful_decisions=6, rejected_decisions=4, circuit_breaker_state=None,
                         decision_history=None, blr_state=kwargs[ "blr_state" ] )
        row.updated_at = datetime.now( timezone.utc )
        Repo = MagicMock(); Repo.return_value.get_all_for_user.return_value = [ row ]
        with patch( "cosa.rest.db.database.get_db", MagicMock() ), \
             patch( "cosa.rest.db.repositories.proxy_decision_repository.TrustStateRepository", Repo ):
            self.assertEqual( o2._load_trust_state(), 1 )
        probe = np.array( [ 1.0, 0.5, 0.25, 0.1 ] )
        self.assertEqual( fresh.categories[ "testing" ]._blr_model.predict( probe ),
                          tracker.categories[ "testing" ]._blr_model.predict( probe ) )

    def test_persist_leaves_the_blr_state_alone_for_count_and_without_a_proxy( self ):
        from cosa.agents.decision_proxy.trust_tracker import TrustTracker
        from cosa.agents.swe_team.proxy import EngineeringStrategy
        o = _mk_orch()
        self.assertIsNone( o.proxy )
        self.assertNotIn( "blr_state", self._persist_kwargs( o ) )
        o.proxy = EngineeringStrategy( trust_tracker=TrustTracker( trust_model="count" ), trust_mode="shadow" )
        self.assertNotIn( "blr_state", self._persist_kwargs( o ) )

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
