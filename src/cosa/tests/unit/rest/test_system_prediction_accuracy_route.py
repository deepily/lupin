#!/usr/bin/env python3
"""
Route tests for GET /api/prediction-engine/accuracy.

Drives the mounted system router with a TestClient. The database session is a stand-in, so
no server, no state, :7999-eligible. The counts against real rows are in the integration test.
"""

import contextlib
import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

# The get_current_user that require_admin depends on is the auth_middleware one, not cosa.rest.auth's.
from cosa.rest.auth_middleware import get_current_user
from cosa.rest.db.repositories.prediction_log_repository import PredictionLogRepository
from cosa.rest.routers.system import router

ADMIN = { "uid": "admin-1", "email": "admin@example.com", "roles": [ "admin" ] }
USER  = { "uid": "u-1",     "email": "user@example.com",  "roles": [ "user" ] }
URL   = "/api/prediction-engine/accuracy"


def _client( user=None ):
    """Mount the system router and return a client speaking as `user`, or the real auth if None."""
    app = FastAPI()
    app.include_router( router )
    if user is not None:
        app.dependency_overrides[ get_current_user ] = lambda: user
    return TestClient( app, raise_server_exceptions=False )


@contextlib.contextmanager
def _session( scalar=0, fail=False ):
    """Patch get_db: the session answers `scalar` for every count, or the open raises."""
    session = MagicMock( name="session" )
    session.query.return_value.filter.return_value.scalar.return_value = scalar

    @contextlib.contextmanager
    def fake_get_db():
        if fail: raise RuntimeError( "db down" )
        yield session

    with patch( "cosa.rest.db.database.get_db", fake_get_db ), \
         patch.object( PredictionLogRepository, "_get_breakdown", return_value={} ):
        yield session


class TestAccuracyRoute( unittest.TestCase ):

    def test_anonymous_caller_is_refused( self ):
        self.assertIn( _client().get( URL ).status_code, ( 401, 403 ) )

    def test_non_admin_is_forbidden_and_the_database_is_never_opened( self ):
        with _session( fail=True ):
            response = _client( USER ).get( URL )
        self.assertEqual( response.status_code, 403 )

    def test_admin_gets_the_summary_for_the_window_and_filters( self ):
        with patch.object( PredictionLogRepository, "get_accuracy_summary", return_value={ "accuracy_rate": 0.5, "status": "ok" } ) as summary, \
             _session():
            response = _client( ADMIN ).get( URL, params={ "window_days": 7, "category": "input", "response_type": "yes_no", "sender_id": "s-1" } )
        self.assertEqual( response.status_code, 200 )
        self.assertEqual( response.json(), { "accuracy_rate": 0.5, "status": "ok" } )
        self.assertEqual( summary.call_args.kwargs, { "window_days": 7, "category": "input", "response_type": "yes_no", "sender_id": "s-1" } )

    def test_default_window_is_thirty_days( self ):
        with patch.object( PredictionLogRepository, "get_accuracy_summary", return_value={} ) as summary, _session():
            _client( ADMIN ).get( URL )
        self.assertEqual( summary.call_args.kwargs[ "window_days" ], 30 )

    def test_zero_scorable_rows_answer_insufficient_data( self ):
        with _session( scalar=0 ):
            response = _client( ADMIN ).get( URL )
        body = response.json()
        self.assertEqual( response.status_code, 200 )
        self.assertEqual( ( body[ "status" ], body[ "accuracy_rate" ], body[ "total_scored" ] ), ( "insufficient data", None, 0 ) )

    def test_rows_present_answer_a_rate_over_scored_rows( self ):
        with _session( scalar=4 ):          # every count reads 4, so 4 correct over 4 scored
            body = _client( ADMIN ).get( URL ).json()
        self.assertEqual( ( body[ "status" ], body[ "accuracy_rate" ], body[ "total_scored" ] ), ( "ok", 1.0, 4 ) )

    def test_a_bad_window_is_a_422( self ):
        with _session():
            self.assertEqual( _client( ADMIN ).get( URL, params={ "window_days": 0 } ).status_code, 422 )

    def test_a_database_failure_is_a_500_not_a_zero( self ):
        with _session( fail=True ):
            response = _client( ADMIN ).get( URL )
        self.assertEqual( response.status_code, 500 )


class TestBusyRoute( unittest.TestCase ):
    """/api/busy reads the queues of lupin_app.main, so a stand-in module replaces it."""

    def test_reports_every_count_from_the_queues( self ):
        import sys, types
        fake = types.ModuleType( "lupin_app.main" )
        fake.jobs_run_queue  = MagicMock( size=lambda: 2, get_pool_status=lambda: { "inflight_agentic_jobs": 1, "monopolize_inflight": True, "monopolize_id": "job-9" } )
        fake.jobs_todo_queue = MagicMock( size=lambda: 3 )
        with patch.dict( sys.modules, { "lupin_app.main": fake } ):
            body = _client().get( "/api/busy" ).json()
        self.assertEqual( body, { "inflight_agentic_jobs": 1, "run_queue_size": 2, "todo_queue_size": 3,
                                  "monopolize_inflight": True, "monopolize_id": "job-9" } )


if __name__ == "__main__":
    unittest.main()
