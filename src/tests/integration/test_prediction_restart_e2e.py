#!/usr/bin/env python3
"""
Restart-between-ask-and-answer integration test for the forecast ledger.

A forecast must survive a restart: ask, lose the pending map, then answer.
No server is bounced. The reset route with clear_pending=true empties the map.

Requires:
    - FastAPI test server on :8000 with the clear_pending flag (commit 374f18717 or later)
    - PostgreSQL (lupin_db_test)

Run (scheduled integration tier, :8000 only):
    pytest src/tests/integration/test_prediction_restart_e2e.py -v
"""

import json
import threading
import time

import pytest
import requests

from tests.integration.test_prediction_engine_e2e import (
    BASE_URL,
    _assert_reset_ok,
    _find_notification_id,
    _get_prediction_log,
    _send_notification_sse,
)


class TestPredictionSurvivesRestart:
    """Ask, clear the pending map, answer: one outcome row and one case."""

    @pytest.fixture( autouse=True )
    def setup_auth( self, ws_connection ):
        """Authenticated user for the notify and response calls."""
        self.auth_headers = { "Authorization": f"Bearer {ws_connection[ 'access_token' ]}" }
        self.target_email = ws_connection[ "email" ]

    @pytest.fixture( autouse=True )
    def setup_db( self ):
        """DB session factory for verification queries."""
        from cosa.rest.db.database import get_db
        self._get_db = get_db

    @pytest.fixture( autouse=True )
    def clean_engine( self, reset_auth_headers ):
        """Drop test decision rows and reset the engine before and after each test."""
        self.reset_headers = reset_auth_headers
        _assert_reset_ok( requests.post( f"{BASE_URL}/api/prediction-engine/reset",
                          params={ "drop_table": "true" }, headers=reset_auth_headers ) )
        yield
        _assert_reset_ok( requests.post( f"{BASE_URL}/api/prediction-engine/reset",
                          params={ "drop_table": "true" }, headers=reset_auth_headers ) )

    def _count_rows( self, notification_id ):
        """
        Count forecast-ledger rows and answer cases for one notification.

        Requires:
            - notification_id is the string id of an existing notification

        Ensures:
            - returns ( prediction_log_rows, prediction_decision_cases )
        """
        from sqlalchemy import text
        with self._get_db() as session:
            logs  = session.execute( text( "select count(*) from prediction_log where notification_id = :n" ),
                                     { "n": notification_id } ).scalar()
            cases = session.execute( text( "select count(*) from prediction_decisions where id = :n" ),
                                     { "n": notification_id } ).scalar()
        return logs, cases

    def test_restart_between_ask_and_answer_writes_one_outcome_and_one_case( self ):
        """
        Ask, clear pending, answer.

        Expects:
            - the forecast row exists before the clear (written at ask time)
            - the clear reports at least one pending entry dropped (the restart was real)
            - after the answer: exactly one prediction_log row, with actual_value and
              responded_at set, and exactly one answer case
        """
        params = {
            "message"            : "Restart test: do you want to proceed with the schema migration?",
            "type"               : "custom",
            "priority"           : "medium",
            "target_user"        : self.target_email,
            "response_requested" : True,
            "response_type"      : "yes_no",
            "timeout_seconds"    : 10,
            "response_default"   : "yes",
        }
        sse_result = {}
        sse_thread = threading.Thread( target=_send_notification_sse,
                                       args=( self.auth_headers, params, sse_result ) )
        sse_thread.start()

        notification_id = None
        for _ in range( 20 ):
            time.sleep( 0.5 )
            notification_id = _find_notification_id( self._get_db )
            if notification_id: break
        assert notification_id is not None, "Notification was not created in DB within timeout"

        # The forecast row must already exist: it is written at ask time, not with the answer
        log_before = _get_prediction_log( self._get_db, notification_id )
        assert log_before is not None, "No forecast row at ask time"
        assert log_before.actual_value is None, "Outcome must not exist before the answer"

        # Simulated restart: empty the router's in-memory pending map (no bounce)
        cleared = requests.post( f"{BASE_URL}/api/prediction-engine/reset",
                                 params={ "clear_pending": "true" }, headers=self.reset_headers )
        assert cleared.status_code == 200, f"clear_pending failed: {cleared.status_code} {cleared.text[ :200 ]}"
        body = cleared.json()
        assert body.get( "status" ) == "success", f"clear_pending refused (the server must run a Lupin: Testing block): {body}"
        assert body.get( "pending_cleared", 0 ) >= 1, f"Nothing was pending to clear, so no restart was simulated: {body}"

        # Answer after the "restart"
        response = requests.post(
            f"{BASE_URL}/api/notify/response",
            json    = { "notification_id": notification_id, "response_value": "no" },
            headers = self.auth_headers,
        )
        assert response.status_code == 200, f"Response submission failed: {response.text}"
        sse_thread.join( timeout=30 )
        time.sleep( 1.0 )

        logs, cases = self._count_rows( notification_id )
        assert logs == 1,  f"Expected exactly one prediction_log row, found {logs}"
        assert cases == 1, f"Expected exactly one answer case after the restart, found {cases}"

        log_after = _get_prediction_log( self._get_db, notification_id )
        assert log_after.actual_value is not None, "Outcome was not attached after the restart"
        assert log_after.responded_at is not None, "responded_at was not set after the restart"
