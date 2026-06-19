"""
Unit tests for the decision-proxy router (`cosa.rest.routers.decision_proxy`).

Covers:
- Batch state helpers + endpoints (get_current_batch_id, acknowledge_batch,
  /acknowledge, /batch-id).
- DB-backed endpoints (get_pending_decisions, ratify_decision, delete_decision,
  get_trust_state, get_decisions_by_domain_category) across success + every
  HTTP-error arm (404 / 400 / 422 / 500) and the created_at/ratified_at
  isoformat-vs-None ternaries.
- Trust-mode hot-reload: get_run_queue/get_config_mgr deps, _find_running_swe_job,
  get_trust_mode (ini-only + running + config-read failure), update_trust_mode
  (invalid mode via model_construct, config put failure, running update, queued).

Zero external dependencies — get_db, the two repositories, lupin_app.main, and
SweTeamJob are boundary-mocked. No real DB, no real queue. Auth bypassed by
passing current_user explicitly.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch
from types import SimpleNamespace
from datetime import datetime
import asyncio
import sys
import time

from fastapi import HTTPException

import cosa.rest.routers.decision_proxy as dp
from cosa.rest.routers.decision_proxy import (
    get_current_batch_id, acknowledge_batch, acknowledge_proxy_batch, get_proxy_batch_id,
    get_pending_decisions, ratify_decision, delete_decision,
    get_trust_state, get_decisions_by_domain_category,
    get_run_queue, get_config_mgr, _find_running_swe_job,
    get_trust_mode, update_trust_mode, TrustModeUpdateRequest,
)

DP   = "cosa.rest.routers.decision_proxy"
UUID = "12345678-1234-5678-1234-567812345678"


def _patch_fastapi_main( mock_main ):
    pkg = Mock(); pkg.main = mock_main
    return patch.dict( sys.modules, { "lupin_app": pkg, "lupin_app.main": mock_main } )


def _db_cm( session ):
    cm = MagicMock()
    cm.__enter__.return_value = session
    cm.__exit__.return_value  = False
    return cm


def _decision( created=datetime( 2026, 1, 1 ), **over ):
    base = dict(
        id="d1", notification_id="n1", domain="swe", category="testing", question="q",
        sender_id="s", action="a", decision_value="v", confidence=0.9, trust_level="L",
        reason="r", ratification_state="pending", data_origin="o", metadata_json={},
        created_at=created,
    )
    base.update( over )
    return SimpleNamespace( **base )


def _trust_state( created=datetime( 2026, 1, 1 ), updated=datetime( 2026, 1, 2 ) ):
    return SimpleNamespace(
        id="t1", domain="swe", category="testing", trust_level="L", total_decisions=5,
        successful_decisions=4, rejected_decisions=1, circuit_breaker_state="closed",
        created_at=created, updated_at=updated,
    )


class TestBatchState( unittest.IsolatedAsyncioTestCase ):
    """Batch id formatting + acknowledge increment + endpoints."""

    def setUp( self ):
        self._saved = dict( dp._proxy_batch_state )
        self.addCleanup( lambda: dp._proxy_batch_state.update( self._saved ) )

    def test_current_batch_id_format( self ):
        """Ensures: batch id is pr-{hex}-{generation}."""
        dp._proxy_batch_state[ "hex" ] = "abcd1234"
        dp._proxy_batch_state[ "generation" ] = 3
        self.assertEqual( get_current_batch_id(), "pr-abcd1234-3" )

    def test_acknowledge_increments( self ):
        """Ensures: acknowledge retires the old batch and bumps the generation."""
        dp._proxy_batch_state[ "hex" ] = "abcd1234"
        dp._proxy_batch_state[ "generation" ] = 1
        result = acknowledge_batch()
        self.assertEqual( result[ "retired_batch" ], "pr-abcd1234-1" )
        self.assertEqual( result[ "new_batch" ], "pr-abcd1234-2" )

    async def test_acknowledge_endpoint( self ):
        """Ensures: /acknowledge wraps acknowledge_batch with status success."""
        resp = await acknowledge_proxy_batch()
        self.assertEqual( resp[ "status" ], "success" )
        self.assertIn( "retired_batch", resp )

    async def test_batch_id_endpoint( self ):
        """Ensures: /batch-id returns the current batch id."""
        resp = await get_proxy_batch_id()
        self.assertEqual( resp[ "status" ], "success" )
        self.assertTrue( resp[ "batch_id" ].startswith( "pr-" ) )


class TestGetPending( unittest.IsolatedAsyncioTestCase ):
    """get_pending_decisions success (created_at both arms) + 500."""

    async def test_success( self ):
        """Ensures: pending decisions are serialized (created_at present + None)."""
        repo = MagicMock()
        repo.get_pending.return_value = [ _decision( created=datetime( 2026, 1, 1 ) ),
                                          _decision( created=None ) ]
        repo.get_pending_summary.return_value = { "total": 2 }
        with patch( f"{DP}.get_db", return_value=_db_cm( MagicMock() ) ), \
             patch( f"{DP}.ProxyDecisionRepository", return_value=repo ):
            resp = await get_pending_decisions( user_email="u@e.com" )
        self.assertEqual( resp[ "status" ], "success" )
        self.assertEqual( len( resp[ "decisions" ] ), 2 )
        self.assertIsNotNone( resp[ "decisions" ][ 0 ][ "created_at" ] )
        self.assertIsNone( resp[ "decisions" ][ 1 ][ "created_at" ] )

    async def test_query_failure_500( self ):
        """Ensures: a repo failure → 500."""
        repo = MagicMock(); repo.get_pending.side_effect = RuntimeError( "db" )
        with patch( f"{DP}.get_db", return_value=_db_cm( MagicMock() ) ), \
             patch( f"{DP}.ProxyDecisionRepository", return_value=repo ):
            with self.assertRaises( HTTPException ) as ctx:
                await get_pending_decisions( user_email="u@e.com" )
        self.assertEqual( ctx.exception.status_code, 500 )


class TestRatify( unittest.IsolatedAsyncioTestCase ):
    """ratify_decision: 404, 400-already, success (ratified_at arms), bad-uuid 500."""

    def _patches( self, decision_repo, trust_repo ):
        return (
            patch( f"{DP}.get_db", return_value=_db_cm( MagicMock() ) ),
            patch( f"{DP}.ProxyDecisionRepository", return_value=decision_repo ),
            patch( f"{DP}.TrustStateRepository", return_value=trust_repo ),
        )

    async def test_not_found_404( self ):
        """Ensures: an unknown decision id → 404."""
        repo = MagicMock(); repo.get_by_id.return_value = None
        p1, p2, p3 = self._patches( repo, MagicMock() )
        with p1, p2, p3:
            with self.assertRaises( HTTPException ) as ctx:
                await ratify_decision( decision_id=UUID, approved=True, user_email="u@e.com" )
        self.assertEqual( ctx.exception.status_code, 404 )

    async def test_already_ratified_400( self ):
        """Ensures: an already-approved decision → 400."""
        repo = MagicMock(); repo.get_by_id.return_value = _decision( ratification_state="approved" )
        p1, p2, p3 = self._patches( repo, MagicMock() )
        with p1, p2, p3:
            with self.assertRaises( HTTPException ) as ctx:
                await ratify_decision( decision_id=UUID, approved=True, user_email="u@e.com" )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_success_approved( self ):
        """Ensures: a pending decision is ratified + trust updated (ratified_at present)."""
        repo = MagicMock()
        repo.get_by_id.return_value = _decision( ratification_state="pending" )
        repo.ratify.return_value = SimpleNamespace(
            ratification_state="approved", ratified_at=datetime( 2026, 1, 3 ), domain="swe", category="testing"
        )
        trust = MagicMock()
        p1, p2, p3 = self._patches( repo, trust )
        with p1, p2, p3:
            resp = await ratify_decision( decision_id=UUID, approved=True, feedback="ok", user_email="u@e.com" )
        self.assertEqual( resp[ "ratification_state" ], "approved" )
        self.assertIsNotNone( resp[ "ratified_at" ] )
        trust.update_after_ratification.assert_called_once()

    async def test_success_rejected_ratified_at_none( self ):
        """Ensures: rejection path + a None ratified_at serializes to None."""
        repo = MagicMock()
        repo.get_by_id.return_value = _decision( ratification_state="pending" )
        repo.ratify.return_value = SimpleNamespace(
            ratification_state="rejected", ratified_at=None, domain="swe", category="testing"
        )
        p1, p2, p3 = self._patches( repo, MagicMock() )
        with p1, p2, p3:
            resp = await ratify_decision( decision_id=UUID, approved=False, user_email="u@e.com" )
        self.assertIsNone( resp[ "ratified_at" ] )

    async def test_bad_uuid_500( self ):
        """Ensures: a malformed decision id raises 500 (uuid parse failure)."""
        repo = MagicMock()
        p1, p2, p3 = self._patches( repo, MagicMock() )
        with p1, p2, p3:
            with self.assertRaises( HTTPException ) as ctx:
                await ratify_decision( decision_id="not-a-uuid", approved=True, user_email="u@e.com" )
        self.assertEqual( ctx.exception.status_code, 500 )


class TestDelete( unittest.IsolatedAsyncioTestCase ):
    """delete_decision: success, 404, ValueError 400, generic 500."""

    def _patch_repo( self, repo ):
        return ( patch( f"{DP}.get_db", return_value=_db_cm( MagicMock() ) ),
                 patch( f"{DP}.ProxyDecisionRepository", return_value=repo ) )

    async def test_success( self ):
        """Ensures: a successful delete returns success + audit user."""
        repo = MagicMock(); repo.delete_pending.return_value = True
        p1, p2 = self._patch_repo( repo )
        with p1, p2:
            resp = await delete_decision( decision_id=UUID, user_email="u@e.com" )
        self.assertEqual( resp[ "status" ], "success" )
        self.assertEqual( resp[ "deleted_by" ], "u@e.com" )

    async def test_not_found_404( self ):
        """Ensures: a missing decision → 404."""
        repo = MagicMock(); repo.delete_pending.return_value = False
        p1, p2 = self._patch_repo( repo )
        with p1, p2:
            with self.assertRaises( HTTPException ) as ctx:
                await delete_decision( decision_id=UUID, user_email="u@e.com" )
        self.assertEqual( ctx.exception.status_code, 404 )

    async def test_not_pending_value_error_400( self ):
        """Ensures: a ValueError (e.g. not pending) → 400."""
        repo = MagicMock(); repo.delete_pending.side_effect = ValueError( "not pending" )
        p1, p2 = self._patch_repo( repo )
        with p1, p2:
            with self.assertRaises( HTTPException ) as ctx:
                await delete_decision( decision_id=UUID, user_email="u@e.com" )
        self.assertEqual( ctx.exception.status_code, 400 )

    async def test_generic_500( self ):
        """Ensures: an unexpected error → 500."""
        repo = MagicMock(); repo.delete_pending.side_effect = RuntimeError( "boom" )
        p1, p2 = self._patch_repo( repo )
        with p1, p2:
            with self.assertRaises( HTTPException ) as ctx:
                await delete_decision( decision_id=UUID, user_email="u@e.com" )
        self.assertEqual( ctx.exception.status_code, 500 )


class TestGetTrustState( unittest.IsolatedAsyncioTestCase ):
    """get_trust_state success (timestamp arms) + 500."""

    async def test_success( self ):
        """Ensures: trust states serialize (created/updated present + None arms)."""
        repo = MagicMock()
        repo.get_all_for_user.return_value = [ _trust_state(),
                                               _trust_state( created=None, updated=None ) ]
        with patch( f"{DP}.get_db", return_value=_db_cm( MagicMock() ) ), \
             patch( f"{DP}.TrustStateRepository", return_value=repo ):
            resp = await get_trust_state( user_email="u@e.com" )
        self.assertEqual( len( resp[ "trust_states" ] ), 2 )
        self.assertIsNotNone( resp[ "trust_states" ][ 0 ][ "created_at" ] )
        self.assertIsNone( resp[ "trust_states" ][ 1 ][ "updated_at" ] )

    async def test_failure_500( self ):
        """Ensures: a repo failure → 500."""
        repo = MagicMock(); repo.get_all_for_user.side_effect = RuntimeError( "db" )
        with patch( f"{DP}.get_db", return_value=_db_cm( MagicMock() ) ), \
             patch( f"{DP}.TrustStateRepository", return_value=repo ):
            with self.assertRaises( HTTPException ) as ctx:
                await get_trust_state( user_email="u@e.com" )
        self.assertEqual( ctx.exception.status_code, 500 )


class TestGetDecisionsByDomain( unittest.IsolatedAsyncioTestCase ):
    """get_decisions_by_domain_category success (created_at arms) + 500."""

    async def test_success( self ):
        """Ensures: domain/category decisions serialize with both created_at arms."""
        repo = MagicMock()
        repo.get_by_domain_category.return_value = [ _decision(), _decision( created=None ) ]
        with patch( f"{DP}.get_db", return_value=_db_cm( MagicMock() ) ), \
             patch( f"{DP}.ProxyDecisionRepository", return_value=repo ):
            resp = await get_decisions_by_domain_category( domain="swe", category="testing" )
        self.assertEqual( resp[ "domain" ], "swe" )
        self.assertEqual( len( resp[ "decisions" ] ), 2 )

    async def test_failure_500( self ):
        """Ensures: a repo failure → 500."""
        repo = MagicMock(); repo.get_by_domain_category.side_effect = RuntimeError( "db" )
        with patch( f"{DP}.get_db", return_value=_db_cm( MagicMock() ) ), \
             patch( f"{DP}.ProxyDecisionRepository", return_value=repo ):
            with self.assertRaises( HTTPException ) as ctx:
                await get_decisions_by_domain_category( domain="swe", category="testing" )
        self.assertEqual( ctx.exception.status_code, 500 )


class TestTrustModeDeps( unittest.TestCase ):
    """get_run_queue / get_config_mgr dependencies + _find_running_swe_job."""

    def test_get_run_queue( self ):
        """Ensures: run queue read off lupin_app.main."""
        m = MagicMock(); m.jobs_run_queue = "RQ"
        with _patch_fastapi_main( m ):
            self.assertEqual( get_run_queue(), "RQ" )

    def test_get_config_mgr( self ):
        """Ensures: config manager read off lupin_app.main."""
        m = MagicMock(); m.config_mgr = "CM"
        with _patch_fastapi_main( m ):
            self.assertEqual( get_config_mgr(), "CM" )

    def test_find_swe_job_none_queue( self ):
        """Ensures: a None run queue yields no job."""
        self.assertIsNone( _find_running_swe_job( None ) )

    def test_find_swe_job_matches_with_orchestrator( self ):
        """Ensures: the first SweTeamJob with a live orchestrator is returned."""
        class FakeSweJob:
            def __init__( self, orch ): self._orchestrator = orch
        rq = MagicMock()
        rq.get_all_jobs.return_value = [ object(), FakeSweJob( None ), FakeSweJob( "ORCH" ) ]
        with patch( "cosa.agents.swe_team.job.SweTeamJob", FakeSweJob ):
            job = _find_running_swe_job( rq )
        self.assertEqual( job._orchestrator, "ORCH" )

    def test_find_swe_job_no_match_returns_none( self ):
        """Ensures: no matching SweTeamJob → None."""
        class FakeSweJob:
            def __init__( self, orch ): self._orchestrator = orch
        rq = MagicMock()
        rq.get_all_jobs.return_value = [ object(), FakeSweJob( None ) ]
        with patch( "cosa.agents.swe_team.job.SweTeamJob", FakeSweJob ):
            self.assertIsNone( _find_running_swe_job( rq ) )


class TestGetTrustMode( unittest.IsolatedAsyncioTestCase ):
    """get_trust_mode: ini-only, running orchestrator, config read failure."""

    async def test_ini_only_no_running_job( self ):
        """Ensures: with no running job, effective = ini mode."""
        cfg = MagicMock(); cfg.get.return_value = "active"
        with patch( f"{DP}._find_running_swe_job", return_value=None ):
            resp = await get_trust_mode( current_user={ "uid": "u" }, run_queue=MagicMock(), config_mgr=cfg )
        self.assertEqual( resp[ "ini_mode" ], "active" )
        self.assertEqual( resp[ "effective" ], "active" )
        self.assertFalse( resp[ "has_running_job" ] )

    async def test_running_job_overrides( self ):
        """Ensures: a running orchestrator's trust_mode becomes the effective mode."""
        cfg = MagicMock(); cfg.get.return_value = "shadow"
        job = MagicMock()
        job._orchestrator.proxy.trust_mode = "suggest"
        with patch( f"{DP}._find_running_swe_job", return_value=job ):
            resp = await get_trust_mode( current_user={ "uid": "u" }, run_queue=MagicMock(), config_mgr=cfg )
        self.assertEqual( resp[ "running_mode" ], "suggest" )
        self.assertEqual( resp[ "effective" ], "suggest" )
        self.assertTrue( resp[ "has_running_job" ] )

    async def test_config_read_failure_defaults_shadow( self ):
        """Ensures: a config-read failure leaves ini_mode at the 'shadow' default."""
        cfg = MagicMock(); cfg.get.side_effect = RuntimeError( "ini gone" )
        with patch( f"{DP}._find_running_swe_job", return_value=None ):
            resp = await get_trust_mode( current_user={ "uid": "u" }, run_queue=MagicMock(), config_mgr=cfg )
        self.assertEqual( resp[ "ini_mode" ], "shadow" )


class TestUpdateTrustMode( unittest.IsolatedAsyncioTestCase ):
    """update_trust_mode: invalid mode 422, config-put failure, running update, queued."""

    async def test_invalid_mode_422( self ):
        """Ensures: a mode that bypasses the model pattern still hits the endpoint guard → 422."""
        body = TrustModeUpdateRequest.model_construct( mode="bogus", domain="swe" )
        with self.assertRaises( HTTPException ) as ctx:
            await update_trust_mode( request_body=body, current_user={ "uid": "u" },
                                     run_queue=MagicMock(), config_mgr=MagicMock() )
        self.assertEqual( ctx.exception.status_code, 422 )

    async def test_queued_when_no_running_job( self ):
        """Ensures: with no running job, the new mode is persisted + queued for next."""
        cfg = MagicMock(); cfg.get.return_value = "shadow"
        body = TrustModeUpdateRequest( mode="active", domain="swe" )
        with patch( f"{DP}._find_running_swe_job", return_value=None ):
            resp = await update_trust_mode( request_body=body, current_user={ "uid": "u" },
                                            run_queue=MagicMock(), config_mgr=cfg )
        self.assertEqual( resp[ "status" ], "queued" )
        self.assertEqual( resp[ "new_mode" ], "active" )
        cfg.put.assert_called_once_with( "swe team trust mode", "active" )

    async def test_running_update_with_config_failure( self ):
        """Ensures: a config-put failure is swallowed; a running orchestrator is hot-reloaded."""
        cfg = MagicMock(); cfg.get.side_effect = RuntimeError( "ini gone" )
        job = MagicMock(); job.id_hash = "job123"
        job._orchestrator.proxy.trust_mode = "shadow"
        body = TrustModeUpdateRequest( mode="active", domain="swe" )
        with patch( f"{DP}._find_running_swe_job", return_value=job ):
            resp = await update_trust_mode( request_body=body, current_user={ "uid": "u" },
                                            run_queue=MagicMock(), config_mgr=cfg )
        self.assertEqual( resp[ "status" ], "updated" )
        self.assertEqual( resp[ "old_mode" ], "shadow" )
        self.assertEqual( resp[ "new_mode" ], "active" )
        self.assertEqual( job._orchestrator.proxy.trust_mode, "active" )


def isolated_unit_test():
    """Run the decision-proxy router unit tests in isolation."""
    import cosa.utils.util as du
    start_time = time.time()
    try:
        loader = unittest.TestLoader()
        suite  = unittest.TestSuite()
        for tc in (
            TestBatchState, TestGetPending, TestRatify, TestDelete, TestGetTrustState,
            TestGetDecisionsByDomain, TestTrustModeDeps, TestGetTrustMode, TestUpdateTrustMode,
        ):
            suite.addTests( loader.loadTestsFromTestCase( tc ) )
        result = unittest.TextTestRunner( verbosity=2 ).run( suite )
        duration  = time.time() - start_time
        tests_run = result.testsRun
        failures  = len( result.failures )
        errors    = len( result.errors )
        success = failures == 0 and errors == 0
        if success:
            du.print_banner( "✅ ALL DECISION-PROXY ROUTER TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME DECISION-PROXY ROUTER TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"
        return success, duration, message
    except Exception as e:
        duration  = time.time() - start_time
        error_msg = f"Unit test execution failed: {str(e)}"
        du.print_banner( f"💥 DECISION-PROXY ROUTER TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} Decision-proxy router unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )
