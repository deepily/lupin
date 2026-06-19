"""
Unit tests for proxy decision persistence
(cosa.rest.db.repositories.proxy_decision_repository).

Covers ProxyDecisionRepository (log_shadow reason-default arc, log_decision
requires-ratification arc, get_pending filter arcs, ratify approve/reject/
not-found, delete_pending found/not-found/wrong-state, get_by_domain_category,
find_similar empty-keywords/with-keywords, get_pending_summary populated/empty)
and TrustStateRepository (get_by_user_domain_category, get_or_create
existing/new, update_after_ratification approve/reject, get_all_for_user
domain/no-domain, update_trust_level, update_circuit_breaker_state) — to
genuine 100% line + branch + function.

All DB access is boundary-mocked via a self-returning fluent query mock; create
and lookup helpers are patched where the create/get path is under test. ZERO DB.
"""

import unittest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

from cosa.rest.db.repositories.proxy_decision_repository import (
    ProxyDecisionRepository, TrustStateRepository
)
from cosa.rest.postgres_models import ProxyDecision, TrustState


def _fluent_query( rows=None, first=None ):
    """A self-returning query mock: filter/order_by/limit chain → all()/first()."""
    q = MagicMock( name="query" )
    q.filter.return_value   = q
    q.order_by.return_value = q
    q.limit.return_value    = q
    q.all.return_value      = rows if rows is not None else []
    q.first.return_value    = first
    return q


# ---------------------------------------------------------------------------
# ProxyDecisionRepository
# ---------------------------------------------------------------------------
class _PDRBase( unittest.TestCase ):
    def setUp( self ):
        self.session = MagicMock( name="session" )
        self.repo    = ProxyDecisionRepository( self.session )


class TestPDRInit( _PDRBase ):
    def test_binds_model( self ):
        self.assertIs( self.repo.model, ProxyDecision )


class TestLogShadow( _PDRBase ):
    def test_default_reason_when_blank( self ):
        self.repo.create = Mock( return_value="created" )
        self.assertEqual(
            self.repo.log_shadow( "nid", "swe", "cat", "q?" ), "created"
        )
        kwargs = self.repo.create.call_args.kwargs
        self.assertEqual( kwargs[ "action" ], "shadow" )
        self.assertEqual( kwargs[ "ratification_state" ], "not_required" )
        self.assertEqual( kwargs[ "reason" ], "L1 shadow mode — log only" )

    def test_explicit_reason_preserved( self ):
        self.repo.create = Mock( return_value="created" )
        self.repo.log_shadow( "nid", "swe", "cat", "q?", reason="because" )
        self.assertEqual( self.repo.create.call_args.kwargs[ "reason" ], "because" )


class TestLogDecision( _PDRBase ):
    def test_requires_ratification_true( self ):
        self.repo.create = Mock( return_value="created" )
        self.repo.log_decision( "nid", "swe", "cat", "q?", "act",
                                requires_ratification=True )
        self.assertEqual(
            self.repo.create.call_args.kwargs[ "ratification_state" ], "pending"
        )

    def test_requires_ratification_false( self ):
        self.repo.create = Mock( return_value="created" )
        self.repo.log_decision( "nid", "swe", "cat", "q?", "suggest" )
        self.assertEqual(
            self.repo.create.call_args.kwargs[ "ratification_state" ], "not_required"
        )


class TestGetPending( _PDRBase ):
    def test_no_optional_filters( self ):
        q = _fluent_query( rows=[ "d1" ] )
        self.session.query.return_value = q
        self.assertEqual( self.repo.get_pending(), [ "d1" ] )
        self.assertEqual( q.filter.call_count, 1 )   # only the pending filter

    def test_domain_and_category_filters( self ):
        q = _fluent_query( rows=[] )
        self.session.query.return_value = q
        self.repo.get_pending( domain="swe", category="cat", limit=10 )
        self.assertEqual( q.filter.call_count, 3 )   # pending + domain + category
        q.limit.assert_called_once_with( 10 )


class TestRatify( _PDRBase ):
    def test_approve( self ):
        decision = SimpleNamespace()
        self.repo.get_by_id = Mock( return_value=decision )
        out = self.repo.ratify( "did", approved=True, ratified_by="a@b.com", feedback="ok" )
        self.assertIs( out, decision )
        self.assertEqual( decision.ratification_state, "approved" )
        self.assertEqual( decision.ratified_by, "a@b.com" )
        self.assertEqual( decision.ratification_feedback, "ok" )
        self.session.flush.assert_called_once_with()

    def test_reject( self ):
        decision = SimpleNamespace()
        self.repo.get_by_id = Mock( return_value=decision )
        self.repo.ratify( "did", approved=False, ratified_by="a@b.com" )
        self.assertEqual( decision.ratification_state, "rejected" )

    def test_not_found_returns_none( self ):
        self.repo.get_by_id = Mock( return_value=None )
        self.assertIsNone( self.repo.ratify( "did", True, "a@b.com" ) )
        self.session.flush.assert_not_called()


class TestDeletePending( _PDRBase ):
    def test_not_found_returns_false( self ):
        self.repo.get_by_id = Mock( return_value=None )
        self.assertFalse( self.repo.delete_pending( "did" ) )

    def test_wrong_state_raises( self ):
        self.repo.get_by_id = Mock( return_value=SimpleNamespace( ratification_state="approved" ) )
        with self.assertRaises( ValueError ):
            self.repo.delete_pending( "did" )

    def test_pending_deletes( self ):
        decision = SimpleNamespace( ratification_state="pending" )
        self.repo.get_by_id = Mock( return_value=decision )
        self.assertTrue( self.repo.delete_pending( "did" ) )
        self.session.delete.assert_called_once_with( decision )
        self.session.flush.assert_called_once_with()


class TestGetByDomainCategory( _PDRBase ):
    def test_returns_rows( self ):
        q = _fluent_query( rows=[ "d1", "d2" ] )
        self.session.query.return_value = q
        self.assertEqual( self.repo.get_by_domain_category( "swe", "cat" ), [ "d1", "d2" ] )
        q.limit.assert_called_once_with( 50 )


class TestFindSimilar( _PDRBase ):
    def test_no_long_keywords_returns_empty( self ):
        # all tokens <= 3 chars → words == [] → early return, no query
        self.assertEqual( self.repo.find_similar( "a b cd", "swe", "cat" ), [] )
        self.session.query.assert_not_called()

    def test_with_keywords_filters_first_three( self ):
        q = _fluent_query( rows=[ "d1" ] )
        self.session.query.return_value = q
        out = self.repo.find_similar( "alpha beta gamma delta epsilon", "swe", "cat" )
        self.assertEqual( out, [ "d1" ] )
        # 1 base domain/category filter + 3 keyword filters (first 3 only)
        self.assertEqual( q.filter.call_count, 4 )


class TestGetPendingSummary( _PDRBase ):
    def test_populated_with_domain_filter( self ):
        base = datetime( 2026, 1, 1, tzinfo=timezone.utc )
        decisions = [
            SimpleNamespace( category="a", trust_level=1, created_at=base ),
            SimpleNamespace( category="a", trust_level=2, created_at=base - timedelta( days=1 ) ),  # older → `<` true
            SimpleNamespace( category="b", trust_level=1, created_at=base + timedelta( days=1 ) ),  # newer → `<` false
        ]
        q = _fluent_query( rows=decisions )
        self.session.query.return_value = q
        summary = self.repo.get_pending_summary( domain="swe" )
        self.assertEqual( summary[ "total_pending" ], 3 )
        self.assertEqual( summary[ "by_category" ], { "a": 2, "b": 1 } )
        self.assertEqual( summary[ "by_trust_level" ], { "L1": 2, "L2": 1 } )
        self.assertEqual( summary[ "oldest_pending" ], ( base - timedelta( days=1 ) ).isoformat() )
        self.assertEqual( q.filter.call_count, 2 )   # pending + domain

    def test_empty_no_domain( self ):
        q = _fluent_query( rows=[] )
        self.session.query.return_value = q
        summary = self.repo.get_pending_summary()
        self.assertEqual( summary[ "total_pending" ], 0 )
        self.assertIsNone( summary[ "oldest_pending" ] )
        self.assertEqual( q.filter.call_count, 1 )   # pending only


# ---------------------------------------------------------------------------
# TrustStateRepository
# ---------------------------------------------------------------------------
class _TSRBase( unittest.TestCase ):
    def setUp( self ):
        self.session = MagicMock( name="session" )
        self.repo    = TrustStateRepository( self.session )


class TestTSRInit( _TSRBase ):
    def test_binds_model( self ):
        self.assertIs( self.repo.model, TrustState )


class TestGetByUserDomainCategory( _TSRBase ):
    def test_returns_first( self ):
        q = _fluent_query( first="state" )
        self.session.query.return_value = q
        self.assertEqual(
            self.repo.get_by_user_domain_category( "a@b.com", "swe", "cat" ), "state"
        )


class TestGetOrCreate( _TSRBase ):
    def test_returns_existing( self ):
        self.repo.get_by_user_domain_category = Mock( return_value="existing" )
        self.repo.create = Mock()
        self.assertEqual( self.repo.get_or_create( "a@b.com", "swe", "cat" ), "existing" )
        self.repo.create.assert_not_called()

    def test_creates_new_with_defaults( self ):
        self.repo.get_by_user_domain_category = Mock( return_value=None )
        self.repo.create = Mock( return_value="new" )
        self.assertEqual( self.repo.get_or_create( "a@b.com", "swe", "cat" ), "new" )
        kwargs = self.repo.create.call_args.kwargs
        self.assertEqual( kwargs[ "trust_level" ], 1 )
        self.assertEqual( kwargs[ "total_decisions" ], 0 )


class TestUpdateAfterRatification( _TSRBase ):
    def test_approved_increments_successful( self ):
        state = SimpleNamespace( total_decisions=0, successful_decisions=0, rejected_decisions=0 )
        self.repo.get_or_create = Mock( return_value=state )
        out = self.repo.update_after_ratification( "a@b.com", "swe", "cat", approved=True )
        self.assertIs( out, state )
        self.assertEqual( state.total_decisions, 1 )
        self.assertEqual( state.successful_decisions, 1 )
        self.assertEqual( state.rejected_decisions, 0 )
        self.session.flush.assert_called_once_with()

    def test_rejected_increments_rejected( self ):
        state = SimpleNamespace( total_decisions=0, successful_decisions=0, rejected_decisions=0 )
        self.repo.get_or_create = Mock( return_value=state )
        self.repo.update_after_ratification( "a@b.com", "swe", "cat", approved=False )
        self.assertEqual( state.rejected_decisions, 1 )
        self.assertEqual( state.successful_decisions, 0 )


class TestGetAllForUser( _TSRBase ):
    def test_no_domain_filter( self ):
        q = _fluent_query( rows=[ "s1" ] )
        self.session.query.return_value = q
        self.assertEqual( self.repo.get_all_for_user( "a@b.com" ), [ "s1" ] )
        self.assertEqual( q.filter.call_count, 1 )

    def test_with_domain_filter( self ):
        q = _fluent_query( rows=[] )
        self.session.query.return_value = q
        self.repo.get_all_for_user( "a@b.com", domain="swe" )
        self.assertEqual( q.filter.call_count, 2 )


class TestUpdateTrustLevel( _TSRBase ):
    def test_sets_level_and_flushes( self ):
        state = SimpleNamespace()
        self.repo.get_or_create = Mock( return_value=state )
        out = self.repo.update_trust_level( "a@b.com", "swe", "cat", 4 )
        self.assertIs( out, state )
        self.assertEqual( state.trust_level, 4 )
        self.assertIsNotNone( state.updated_at )
        self.session.flush.assert_called_once_with()


class TestUpdateCircuitBreakerState( _TSRBase ):
    def test_sets_cb_state_and_flushes( self ):
        state = SimpleNamespace()
        self.repo.get_or_create = Mock( return_value=state )
        cb = { "open": True }
        out = self.repo.update_circuit_breaker_state( "a@b.com", "swe", "cat", cb )
        self.assertIs( out, state )
        self.assertEqual( state.circuit_breaker_state, cb )
        self.session.flush.assert_called_once_with()


def isolated_unit_test():
    """
    Run the proxy-decision repository unit tests in isolation.

    Ensures:
        - Returns (success, duration, message) for the smoke-runner harness
    """
    import time
    start_time = time.time()
    suite = unittest.TestLoader().loadTestsFromModule( __import__( __name__ ) )
    result = unittest.TextTestRunner( verbosity=2 ).run( suite )
    duration = time.time() - start_time
    success = result.wasSuccessful()
    message = f"{result.testsRun} run, {len( result.failures )} failed, {len( result.errors )} errors"
    return success, duration, message


if __name__ == "__main__":
    ok, secs, msg = isolated_unit_test()
    print( f"\n{'✅ PASS' if ok else '❌ FAIL'} proxy_decision_repository tests in {secs:.3f}s — {msg}" )
