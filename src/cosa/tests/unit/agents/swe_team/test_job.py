"""
Unit tests for swe_team/job.py — SweTeamJob (AgenticJobBase subclass):
  - __init__ / last_question_asked
  - do_all            : sync→async bridge (success + failure re-raise)
  - _execute          : dry-run dispatch + live orchestrator delegation + finally cleanup
  - _start_notification_client : success + failure-returns-None
  - _execute_dry_run  : breadcrumb notify loop + proxy-decision generation

ALL collaborators (orchestrator, ConfigurationManager, voice_io, notification client,
DB get_db/repo) are boundary-mocked; asyncio.sleep is mocked (no real delays);
EngineeringClassifier is real (pure keyword logic, zero cost). NO LLM/SDK/network/DB.

Created 2026-05-31 by Extra 1 🪨 (CoSA coverage campaign, swe_team lane, complex tier).
"""

import asyncio
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import cosa.agents.swe_team.job as job_mod
from cosa.agents.swe_team.job import SweTeamJob
from cosa.rest.job_state import JobState


def _run( coro ):
    return asyncio.run( coro )


def _mk_job( **overrides ):
    kwargs = dict(
        task="Add a health check endpoint",
        user_id="user-1", user_email="u@x.ai", session_id="sess-1",
        debug=False,
    )
    kwargs.update( overrides )
    return SweTeamJob( **kwargs )


class TestInitAndDisplay( unittest.TestCase ):

    def test_init_stores_attrs_and_id_prefix( self ):
        j = _mk_job( dry_run=True, lead_model="opus", budget=3.0, trust_mode="active" )
        self.assertEqual( j.task, "Add a health check endpoint" )
        self.assertTrue( j.dry_run )
        self.assertEqual( j.lead_model, "opus" )
        self.assertEqual( j._trust_mode_override, "active" )
        self.assertIsNone( j._orchestrator )
        self.assertIsNone( j.cost_summary )
        self.assertTrue( j.id_hash.startswith( "swe-" ) )
        self.assertEqual( j.state, JobState.PENDING )

    def test_last_question_asked_truncates_long_task( self ):
        j = _mk_job( task="x" * 80 )
        lqa = j.last_question_asked
        self.assertIn( "[SWE Team]", lqa )
        self.assertIn( "...", lqa )

    def test_last_question_asked_short_task( self ):
        j = _mk_job( task="short" )
        self.assertEqual( j.last_question_asked, "[SWE Team] short" )

    def test_class_constants( self ):
        self.assertEqual( SweTeamJob.JOB_TYPE, "swe_team" )
        self.assertEqual( SweTeamJob.JOB_PREFIX, "swe" )


class TestDoAll( unittest.TestCase ):

    def test_success_sets_completed_state( self ):
        j = _mk_job( debug=True )
        with patch.object( j, "_execute", AsyncMock( return_value="ALL DONE" ) ):
            out = j.do_all()
        self.assertEqual( out, "ALL DONE" )
        self.assertEqual( j.state, JobState.COMPLETED )
        self.assertEqual( j.result, "ALL DONE" )
        self.assertEqual( j.answer_conversational, "ALL DONE" )
        self.assertIsNotNone( j.completed_at )

    def test_failure_sets_failed_state_and_reraises( self ):
        j = _mk_job( debug=True )
        with patch.object( j, "_execute", AsyncMock( side_effect=RuntimeError( "kaboom" ) ) ):
            with self.assertRaises( RuntimeError ):
                j.do_all()
        self.assertEqual( j.state, JobState.FAILED )
        self.assertEqual( j.error, "kaboom" )
        self.assertIn( "SWE Team task failed", j.answer_conversational )

    def test_success_debug_off_skips_prints( self ):
        # 199->202 + 213->217 debug-skip arcs.
        j = _mk_job( debug=False )
        with patch.object( j, "_execute", AsyncMock( return_value="OK" ) ):
            self.assertEqual( j.do_all(), "OK" )
        self.assertEqual( j.state, JobState.COMPLETED )

    def test_failure_debug_off_skips_prints( self ):
        # 225->232 debug-skip arc in the except block.
        j = _mk_job( debug=False )
        with patch.object( j, "_execute", AsyncMock( side_effect=ValueError( "x" ) ) ):
            with self.assertRaises( ValueError ):
                j.do_all()
        self.assertEqual( j.state, JobState.FAILED )


class TestExecuteDispatch( unittest.TestCase ):

    def test_dry_run_dispatches_to_dry_run_path( self ):
        j = _mk_job( dry_run=True )
        with patch.dict( sys.modules, { "cosa.agents.swe_team": MagicMock() } ):
            # voice_io accessed via `from cosa.agents.swe_team import voice_io`
            vio = sys.modules[ "cosa.agents.swe_team" ].voice_io
            with patch.object( j, "_execute_dry_run", AsyncMock( return_value="DRY" ) ) as m:
                out = _run( j._execute() )
        self.assertEqual( out, "DRY" )
        m.assert_awaited_once()


class TestExecuteLive( unittest.TestCase ):

    def _live_patches( self, run_return="LIVE RESULT", enable_user_messages=True ):
        """Patch every late-imported collaborator in the live _execute path."""
        vio = MagicMock()
        vio.reconfigure = MagicMock()
        vio.set_job_id = MagicMock()
        vio.clear_job_id = MagicMock()

        ci = MagicMock()

        cfg = job_mod  # placeholder
        config = MagicMock()
        config.enable_user_messages = enable_user_messages
        config_cls = MagicMock()
        config_cls.from_config.return_value = config

        orch = MagicMock()
        orch.run = AsyncMock( return_value=run_return )
        orch_cls = MagicMock( return_value=orch )

        cm_mod = MagicMock()

        swe_pkg = MagicMock()
        swe_pkg.voice_io = vio
        swe_pkg.cosa_interface = ci

        mods = {
            "cosa.agents.swe_team"                     : swe_pkg,
            "cosa.agents.swe_team.config"              : MagicMock( SweTeamConfig=config_cls ),
            "cosa.agents.swe_team.orchestrator"        : MagicMock( SweTeamOrchestrator=orch_cls ),
            "cosa.config.configuration_manager"        : MagicMock( ConfigurationManager=MagicMock() ),
        }
        return mods, vio, config, orch, orch_cls

    def test_live_with_overrides_and_user_messages( self ):
        j = _mk_job( debug=True, dry_run=False, trust_mode="active",
                     lead_model="opus", worker_model="sonnet", budget=9.0, timeout=600 )
        mods, vio, config, orch, orch_cls = self._live_patches()
        client = MagicMock()
        with patch.dict( sys.modules, mods ), \
             patch.object( j, "_start_notification_client", return_value=client ) as snc:
            out = _run( j._execute() )
        self.assertEqual( out, "LIVE RESULT" )
        # Per-job overrides applied to config.
        self.assertEqual( config.trust_mode, "active" )
        self.assertEqual( config.lead_model, "opus" )
        self.assertEqual( config.worker_model, "sonnet" )
        self.assertEqual( config.budget_usd, 9.0 )
        self.assertEqual( config.wall_clock_timeout_secs, 600 )
        snc.assert_called_once()
        client.stop_sync.assert_called_once()   # finally cleanup
        vio.clear_job_id.assert_called_once()
        self.assertIsNone( j._orchestrator )

    def test_live_no_overrides_no_user_messages( self ):
        j = _mk_job( dry_run=False )   # no overrides → skip all the `if` arcs
        mods, vio, config, orch, orch_cls = self._live_patches( enable_user_messages=False )
        with patch.dict( sys.modules, mods ), \
             patch.object( j, "_start_notification_client" ) as snc:
            out = _run( j._execute() )
        self.assertEqual( out, "LIVE RESULT" )
        snc.assert_not_called()        # enable_user_messages False → no client

    def test_live_orchestrator_returns_none( self ):
        j = _mk_job( dry_run=False )
        mods, vio, config, orch, orch_cls = self._live_patches( run_return=None,
                                                                enable_user_messages=False )
        with patch.dict( sys.modules, mods ):
            out = _run( j._execute() )
        self.assertIn( "failed or was cancelled", out )


class TestStartNotificationClient( unittest.TestCase ):

    def test_success_returns_started_client( self ):
        j = _mk_job( debug=True )
        orch = MagicMock()
        fake_client = MagicMock()
        fake_mod = MagicMock( OrchestratorNotificationClient=MagicMock( return_value=fake_client ) )
        with patch.dict( sys.modules, { "cosa.agents.swe_team.notification_client": fake_mod } ):
            out = j._start_notification_client( orch )
        self.assertIs( out, fake_client )
        fake_client.start.assert_called_once()

    def test_success_debug_off( self ):
        # 355->358 debug-skip arc.
        j = _mk_job( debug=False )
        orch = MagicMock()
        fake_client = MagicMock()
        fake_mod = MagicMock( OrchestratorNotificationClient=MagicMock( return_value=fake_client ) )
        with patch.dict( sys.modules, { "cosa.agents.swe_team.notification_client": fake_mod } ):
            self.assertIs( j._start_notification_client( orch ), fake_client )

    def test_failure_returns_none( self ):
        j = _mk_job()
        orch = MagicMock()
        fake_mod = MagicMock(
            OrchestratorNotificationClient=MagicMock( side_effect=RuntimeError( "no ws" ) ) )
        with patch.dict( sys.modules, { "cosa.agents.swe_team.notification_client": fake_mod } ):
            self.assertIsNone( j._start_notification_client( orch ) )


class TestExecuteDryRun( unittest.TestCase ):

    def _patch_db( self, raise_on_get_db=False ):
        db_ctx = MagicMock()
        db_session = MagicMock()
        db_ctx.__enter__ = MagicMock( return_value=db_session )
        db_ctx.__exit__  = MagicMock( return_value=False )
        db_mod = MagicMock()
        if raise_on_get_db:
            db_mod.get_db = MagicMock( side_effect=RuntimeError( "db down" ) )
        else:
            db_mod.get_db = MagicMock( return_value=db_ctx )
        repo_instance = MagicMock()
        repo_mod = MagicMock( ProxyDecisionRepository=MagicMock( return_value=repo_instance ) )
        return {
            "cosa.rest.db.database"                                  : db_mod,
            "cosa.rest.db.repositories.proxy_decision_repository"    : repo_mod,
        }, db_session, repo_instance

    def test_dry_run_full_path_logs_decisions( self ):
        j = _mk_job( dry_run=True, debug=True )
        vio = MagicMock()
        vio.notify = AsyncMock()
        mods, db_session, repo = self._patch_db()
        with patch.dict( sys.modules, mods ), \
             patch.object( job_mod.asyncio, "sleep", AsyncMock() ):
            out = _run( j._execute_dry_run( vio ) )
        self.assertIn( "Dry run complete", out )
        self.assertEqual( j.cost_summary[ "total_cost_usd" ], 0.0 )
        self.assertIn( "abstract", j.artifacts )
        # 10 phases, 3 None-question phases (0,1,8) → 7 logged decisions.
        self.assertEqual( repo.log_decision.call_count, 7 )
        db_session.commit.assert_called_once()
        # Two notify calls: per-phase loop (10) + completion (1).
        self.assertEqual( vio.notify.await_count, 11 )

    def test_dry_run_fewer_phases( self ):
        # dry_run_phases=2 → only phases 0,1 (both None-question) → 0 decisions.
        j = _mk_job( dry_run=True, dry_run_phases=2 )
        vio = MagicMock()
        vio.notify = AsyncMock()
        mods, db_session, repo = self._patch_db()
        with patch.dict( sys.modules, mods ), \
             patch.object( job_mod.asyncio, "sleep", AsyncMock() ):
            _run( j._execute_dry_run( vio ) )
        self.assertEqual( repo.log_decision.call_count, 0 )
        self.assertEqual( vio.notify.await_count, 3 )   # 2 phases + completion

    def test_dry_run_db_exception_swallowed( self ):
        j = _mk_job( dry_run=True, debug=True )
        vio = MagicMock()
        vio.notify = AsyncMock()
        mods, _, _ = self._patch_db( raise_on_get_db=True )
        with patch.dict( sys.modules, mods ), \
             patch.object( job_mod.asyncio, "sleep", AsyncMock() ):
            out = _run( j._execute_dry_run( vio ) )   # must not raise
        self.assertIn( "Dry run complete", out )


if __name__ == "__main__":
    unittest.main()
