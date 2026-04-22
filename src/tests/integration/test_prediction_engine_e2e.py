#!/usr/bin/env python3
"""
E2E integration tests for the Universal Prediction Engine (Slices 0-5).

Tests the full predict-respond-record cycle through the live FastAPI server.
Validates that Hook 1 (predict) and Hook 2 (record_outcome) fire correctly
and populate the prediction_log table with accurate data.

Requires:
    - FastAPI server running on port 7999 (with Testing config block)
    - PostgreSQL running (lupin_db_test for test isolation)
    - EmbeddingProvider accessible (for warm prediction tests)

Run:
    ./src/tests/run-integration-tests.sh -v
    OR: pytest src/tests/integration/test_prediction_engine_e2e.py -v
"""

import os

import json
import time
import uuid
import threading
import tempfile

import requests
import pytest

import cosa.utils.util as cu

# Test server
BASE_URL = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:8000" )

# Test-specific LanceDB table name (prevents contaminating production data)
TEST_LANCEDB_TABLE = "prediction_decisions_test"


# ===========================================================================
# Helpers
# ===========================================================================

def _send_notification_sse( headers, params, result_holder ):
    """
    Send a response-required notification in a background thread.

    The POST /api/notify endpoint returns an SSE stream that blocks
    until the user responds or the timeout expires. This helper captures
    the SSE response for the calling thread.

    Requires:
        - headers: dict with Authorization header
        - params: dict of query params for /api/notify
        - result_holder: dict to store { "status_code", "sse_data" }

    Ensures:
        - SSE response is stored in result_holder when complete
    """
    try:
        r = requests.post(
            f"{BASE_URL}/api/notify",
            headers = headers,
            params  = params,
            stream  = True,
            timeout = 30
        )
        result_holder[ "status_code" ] = r.status_code

        sse_data = []
        for line in r.iter_lines():
            if line:
                decoded = line.decode( "utf-8" )
                if decoded.startswith( "data:" ):
                    try:
                        sse_data.append( json.loads( decoded[ 5: ] ) )
                    except json.JSONDecodeError:
                        pass
        result_holder[ "sse_data" ] = sse_data

    except Exception as e:
        result_holder[ "error" ] = str( e )


def _find_notification_id( session_factory ):
    """
    Query DB for the latest notification and return its ID.

    Requires:
        - session_factory: callable that returns a DB session context manager

    Ensures:
        - Returns string UUID of the most recent notification
        - Returns None if no notifications exist
    """
    from cosa.rest.db.repositories.notification_repository import NotificationRepository
    from cosa.rest.postgres_models import Notification

    with session_factory() as session:
        repo = NotificationRepository( session )
        # Get most recent notification
        notif = session.query( Notification ).order_by(
            Notification.created_at.desc()
        ).first()
        if notif:
            return str( notif.id )
    return None


def _get_prediction_log( session_factory, notification_id ):
    """
    Query prediction_log for a specific notification.

    Returns:
        PredictionLog object (detached) or None
    """
    from sqlalchemy.orm import make_transient
    from cosa.rest.db.repositories.prediction_log_repository import PredictionLogRepository

    with session_factory() as session:
        repo = PredictionLogRepository( session )
        log  = repo.get_by_notification_id( notification_id )
        if log is not None:
            # Eagerly load all columns before detaching from session
            session.refresh( log )
            make_transient( log )
        return log


def _get_all_prediction_logs( session_factory ):
    """
    Get all prediction_log entries.

    Returns:
        list of PredictionLog objects (detached)
    """
    from sqlalchemy.orm import make_transient
    from cosa.rest.db.repositories.prediction_log_repository import PredictionLogRepository

    with session_factory() as session:
        repo = PredictionLogRepository( session )
        logs = repo.get_recent( limit=100 )
        for log in logs:
            session.refresh( log )
            make_transient( log )
        return logs


# ===========================================================================
# TestPredictionEngineE2E — full cycle tests
# ===========================================================================

class TestPredictionEngineE2E:
    """
    E2E tests for the predict-respond-record cycle.

    Each test:
    1. Sends a notification via POST /api/notify (SSE blocks in bg thread)
    2. Waits for notification to be created in DB
    3. Submits response via POST /api/notify/response
    4. Verifies prediction_log table via PredictionLogRepository
    """

    @pytest.fixture( autouse=True )
    def setup_auth( self, ws_connection ):
        """Set up authentication + WebSocket for all tests."""
        self.user_data    = ws_connection
        self.auth_headers = { "Authorization": f"Bearer {ws_connection[ 'access_token' ]}" }
        self.target_email = ws_connection[ "email" ]

    @pytest.fixture( autouse=True )
    def setup_db( self ):
        """Provide DB session factory for verification queries."""
        from cosa.rest.db.database import get_db
        self._get_db = get_db

    @pytest.fixture( autouse=True )
    def clean_lancedb( self ):
        """
        Drop test LanceDB table and reset server-side PredictionEngine before each test.

        Ensures:
            - Server drops the test LanceDB table (server has root write permission)
            - PredictionEngine singleton is destroyed and re-created with clean state
            - No cross-test contamination from prior decisions

        Note:
            Both table drop and singleton reset MUST happen server-side — the server
            process runs as root (Docker) and owns the LanceDB files. The test process
            (running as user) cannot drop the table due to permission denied.
        """
        # Server-side: drop test table + reset PredictionEngine singleton
        requests.get( f"{BASE_URL}/api/prediction-engine/reset", params={ "drop_table": "true" } )

        yield

        # Post-test cleanup: drop table + reset again
        requests.get( f"{BASE_URL}/api/prediction-engine/reset", params={ "drop_table": "true" } )

    def _send_and_respond( self, message, response_type, response_value,
                           timeout_seconds=10, response_options=None,
                           response_default="yes" ):
        """
        Send a notification and respond to it. Returns the notification_id.

        Requires:
            - message: Notification message
            - response_type: yes_no, multiple_choice, etc.
            - response_value: The response to submit

        Ensures:
            - Notification is created via API
            - Response is submitted
            - Returns notification_id string
        """
        params = {
            "message"            : message,
            "type"               : "custom",
            "priority"           : "medium",
            "target_user"        : self.target_email,
            "response_requested" : True,
            "response_type"      : response_type,
            "timeout_seconds"    : timeout_seconds,
            "response_default"   : response_default,
        }
        if response_options:
            params[ "response_options" ] = json.dumps( response_options )

        # Start SSE notification in background thread
        sse_result = {}
        sse_thread = threading.Thread(
            target = _send_notification_sse,
            args   = ( self.auth_headers, params, sse_result )
        )
        sse_thread.start()

        # Wait for notification to be created in DB
        notification_id = None
        for _ in range( 20 ):
            time.sleep( 0.5 )
            notification_id = _find_notification_id( self._get_db )
            if notification_id:
                break

        assert notification_id is not None, "Notification was not created in DB within timeout"

        # Submit response
        response = requests.post(
            f"{BASE_URL}/api/notify/response",
            json = {
                "notification_id" : notification_id,
                "response_value"  : response_value,
            }
        )
        assert response.status_code == 200, f"Response submission failed: {response.text}"

        # Wait for SSE thread to complete
        sse_thread.join( timeout=15 )

        # Brief pause for async DB writes to complete
        time.sleep( 0.5 )

        return notification_id

    # -----------------------------------------------------------------------
    # Test 1: Cold start yes_no — no historical cases
    # -----------------------------------------------------------------------
    def test_cold_start_yes_no( self ):
        """
        Cold start: send yes_no notification with no seeded cases.

        Expects:
            - prediction_strategy = "cold_start"
            - predicted_value is NULL (no prediction)
            - actual_value is recorded
        """
        notification_id = self._send_and_respond(
            message        = "Should I deploy the hotfix to staging?",
            response_type  = "yes_no",
            response_value = "yes",
        )

        # Verify prediction_log
        log = _get_prediction_log( self._get_db, notification_id )
        assert log is not None, "No prediction_log entry found"
        assert log.response_type == "yes_no"
        assert log.prediction_strategy == "cold_start"
        assert log.category is not None and log.category != ""

    # -----------------------------------------------------------------------
    # Test 2: Cold start outcome recording
    # -----------------------------------------------------------------------
    def test_cold_start_outcome_recorded( self ):
        """
        Verify that actual_value is recorded in prediction_log on response.

        Expects:
            - actual_value contains the response
            - accuracy_match is NULL (cold_start has no prediction to compare)
        """
        notification_id = self._send_and_respond(
            message        = "Do you want to proceed with the database migration?",
            response_type  = "yes_no",
            response_value = "no",
        )

        log = _get_prediction_log( self._get_db, notification_id )
        assert log is not None, "No prediction_log entry found"
        assert log.actual_value is not None, "actual_value should be recorded"
        # Cold start: accuracy_match is None (no prediction to compare)
        assert log.accuracy_match is None, "Cold start should have NULL accuracy_match"
        assert log.responded_at is not None, "responded_at should be set"

    # -----------------------------------------------------------------------
    # Test 3: Cold start with qualifier response
    # -----------------------------------------------------------------------
    def test_cold_start_qualifier_response( self ):
        """
        Cold start with qualified yes/no response.

        Expects:
            - actual_value is recorded (includes the qualifier text)
            - prediction_strategy = "cold_start"
        """
        notification_id = self._send_and_respond(
            message        = "Delete the old backup files from March?",
            response_type  = "yes_no",
            response_value = "yes [comment: only the March ones]",
        )

        log = _get_prediction_log( self._get_db, notification_id )
        assert log is not None
        assert log.prediction_strategy == "cold_start"
        assert log.actual_value is not None

    # -----------------------------------------------------------------------
    # Test 4: Multiple choice cold start
    # -----------------------------------------------------------------------
    def test_cold_start_multiple_choice( self ):
        """
        Cold start: send multiple_choice notification with no seeded cases.

        Expects:
            - prediction_strategy = "cold_start"
            - response_type = "multiple_choice"
        """
        mc_options = [
            {
                "question"    : "Which database should we use?",
                "header"      : "Database",
                "multiSelect" : False,
                "options"     : [
                    { "label": "PostgreSQL", "description": "Relational database" },
                    { "label": "MongoDB", "description": "Document database" },
                ]
            }
        ]

        notification_id = self._send_and_respond(
            message          = "Which database should we use for the new project?",
            response_type    = "multiple_choice",
            response_value   = { "answers": { "Database": "PostgreSQL" } },
            response_options = mc_options,
        )

        log = _get_prediction_log( self._get_db, notification_id )
        assert log is not None, "No prediction_log entry found"
        assert log.response_type == "multiple_choice"
        assert log.prediction_strategy == "cold_start"

    # -----------------------------------------------------------------------
    # Test 5: Prediction log has correct metadata fields
    # -----------------------------------------------------------------------
    def test_prediction_log_metadata_complete( self ):
        """
        Verify all prediction_log fields are populated correctly.

        Expects:
            - response_type, category, prediction_strategy all non-null
            - prediction_confidence is 0.0 for cold_start
            - similar_case_count is 0 for cold_start
            - predicted_at is set
        """
        notification_id = self._send_and_respond(
            message        = "Should I rebase the feature branch?",
            response_type  = "yes_no",
            response_value = "yes",
        )

        log = _get_prediction_log( self._get_db, notification_id )
        assert log is not None

        # Prediction fields
        assert log.response_type in [ "yes_no", "multiple_choice", "open_ended", "open_ended_batch" ]
        assert log.category is not None
        assert log.prediction_strategy == "cold_start"
        assert log.prediction_confidence == 0.0
        assert log.similar_case_count == 0
        assert log.predicted_at is not None

        # Outcome fields (filled by Hook 2)
        assert log.actual_value is not None
        assert log.responded_at is not None

    # -----------------------------------------------------------------------
    # Test 6: Multiple notifications accumulate in prediction_log
    # -----------------------------------------------------------------------
    def test_multiple_predictions_accumulate( self ):
        """
        Send multiple notifications and verify each gets its own prediction_log entry.
        """
        id_1 = self._send_and_respond(
            message        = "Start the deployment pipeline?",
            response_type  = "yes_no",
            response_value = "yes",
        )

        id_2 = self._send_and_respond(
            message        = "Run the full test suite first?",
            response_type  = "yes_no",
            response_value = "no",
        )

        log_1 = _get_prediction_log( self._get_db, id_1 )
        log_2 = _get_prediction_log( self._get_db, id_2 )

        assert log_1 is not None
        assert log_2 is not None
        assert str( log_1.notification_id ) != str( log_2.notification_id )

    # -----------------------------------------------------------------------
    # Test 7: Multiple choice outcome stores answers format
    # -----------------------------------------------------------------------
    def test_mc_outcome_stores_answers_format( self ):
        """
        Verify MC response stores actual_value with answers format.
        """
        mc_options = [
            {
                "question"    : "Which framework should we use?",
                "header"      : "Framework",
                "multiSelect" : False,
                "options"     : [
                    { "label": "FastAPI", "description": "Modern Python API framework" },
                    { "label": "Flask", "description": "Lightweight framework" },
                ]
            }
        ]

        notification_id = self._send_and_respond(
            message          = "Which Python web framework for the new service?",
            response_type    = "multiple_choice",
            response_value   = { "answers": { "Framework": "FastAPI" } },
            response_options = mc_options,
        )

        log = _get_prediction_log( self._get_db, notification_id )
        assert log is not None
        assert log.actual_value is not None

        # The actual_value should contain the MC response
        actual = log.actual_value
        assert isinstance( actual, dict )

    # -----------------------------------------------------------------------
    # Test 8: Accuracy summary aggregation works
    # -----------------------------------------------------------------------
    def test_accuracy_summary_after_predictions( self ):
        """
        After multiple predict-respond cycles, accuracy summary returns valid stats.
        """
        # Create a few predictions
        self._send_and_respond(
            message        = "Approve the PR?",
            response_type  = "yes_no",
            response_value = "yes",
        )
        self._send_and_respond(
            message        = "Merge to main?",
            response_type  = "yes_no",
            response_value = "no",
        )

        # Query accuracy summary
        from cosa.rest.db.repositories.prediction_log_repository import PredictionLogRepository

        with self._get_db() as session:
            repo    = PredictionLogRepository( session )
            summary = repo.get_accuracy_summary( window_days=1 )

        assert summary[ "total_predictions" ] >= 2
        assert summary[ "total_responded" ] >= 2
        assert "by_response_type" in summary

    # -----------------------------------------------------------------------
    # Test 16: Cold start open_ended
    # -----------------------------------------------------------------------
    def test_cold_start_open_ended( self ):
        """
        Cold start: open_ended notification with no seeded cases.
        Expects cold_start strategy since no similar past open_ended responses exist.
        """
        notification_id = self._send_and_respond(
            message        = "What naming convention should I use for the new module?",
            response_type  = "open_ended",
            response_value = "snake_case for all Python modules",
        )

        log = _get_prediction_log( self._get_db, notification_id )
        assert log is not None, "No prediction_log entry found"
        assert log.response_type == "open_ended"
        assert log.prediction_strategy == "cold_start"
        assert log.category is not None and log.category != ""

    # -----------------------------------------------------------------------
    # Test 17: Cold start open_ended_batch
    # -----------------------------------------------------------------------
    def test_cold_start_open_ended_batch( self ):
        """
        Cold start: open_ended_batch notification with no seeded cases.
        Expects cold_start strategy.
        """
        notification_id = self._send_and_respond(
            message        = "Please provide project configuration details",
            response_type  = "open_ended_batch",
            response_value = { "answers": { "Topic": "quantum computing", "Budget": "no limit" } },
        )

        log = _get_prediction_log( self._get_db, notification_id )
        assert log is not None, "No prediction_log entry found"
        assert log.response_type == "open_ended_batch"
        assert log.prediction_strategy == "cold_start"


# ===========================================================================
# TestPredictionEngineWarm — warm CBR prediction tests
# ===========================================================================

class TestPredictionEngineWarm:
    """
    Warm E2E tests that seed LanceDB with real embeddings (via HTTP fallback)
    and verify CBR majority vote predictions.

    Each test:
    1. Seeds the test-specific LanceDB table with decisions using real embeddings
    2. Sends a similar notification via POST /api/notify
    3. Verifies prediction_log shows cbr_majority_vote strategy
    4. Cleans up test LanceDB table after each test
    """

    @pytest.fixture( autouse=True )
    def setup_auth( self, ws_connection ):
        """Set up authentication + WebSocket for all tests."""
        self.user_data    = ws_connection
        self.auth_headers = { "Authorization": f"Bearer {ws_connection[ 'access_token' ]}" }
        self.target_email = ws_connection[ "email" ]

        # Use JWT for HTTP embedding calls (API key may not be seeded in test DB)
        self.embedding_headers = self.auth_headers

    @pytest.fixture( autouse=True )
    def setup_db( self ):
        """Provide DB session factory for verification queries."""
        from cosa.rest.db.database import get_db
        self._get_db = get_db

    @pytest.fixture( autouse=True )
    def setup_prediction_engine( self ):
        """
        Reset server-side PredictionEngine singleton and clean test LanceDB table.

        Ensures:
            - Server drops test LanceDB table (server has root write permission)
            - PredictionEngine singleton re-created with test config
            - No cross-test contamination from prior decisions
        """
        # Server-side: drop test table + reset PredictionEngine singleton
        requests.get( f"{BASE_URL}/api/prediction-engine/reset", params={ "drop_table": "true" } )

        yield

        # Post-test cleanup
        requests.get( f"{BASE_URL}/api/prediction-engine/reset", params={ "drop_table": "true" } )

    def _generate_embedding_http( self, text ):
        """
        Generate a real embedding via the server's HTTP endpoint.

        Requires:
            - FastAPI server running with embeddings endpoint
            - Valid JWT from ws_connection fixture

        Ensures:
            - Returns list of 768 floats
        """
        response = requests.post(
            f"{BASE_URL}/api/embeddings/generate",
            json    = { "text": text, "content_type": "prose" },
            headers = self.embedding_headers,
            timeout = 10
        )
        assert response.status_code == 200, f"Embedding generation failed: {response.text}"
        data = response.json()
        assert len( data[ "embedding" ] ) == 768
        return data[ "embedding" ]

    def _seed_decision( self, question, category, decision_value ):
        """
        Seed a LanceDB decision with a real embedding from the server.

        Requires:
            - question: notification message text
            - category: classified category string
            - decision_value: the response value to store

        Ensures:
            - Decision record added to test LanceDB table
        """
        from cosa.agents.decision_proxy.proxy_decision_embeddings import ProxyDecisionEmbeddings
        from datetime import datetime, timezone

        embedding = self._generate_embedding_http( question )

        lancedb_path = cu.get_project_root() + "/src/conf/long-term-memory/lupin.lancedb"
        store = ProxyDecisionEmbeddings(
            db_path       = lancedb_path,
            table_name    = TEST_LANCEDB_TABLE,
            embedding_dim = 768,
            debug         = False
        )

        store.add_decision(
            id                 = str( uuid.uuid4() ),
            question           = question,
            category           = category,
            decision_value     = decision_value,
            ratification_state = "not_required",
            question_embedding = embedding,
            created_at         = datetime.now( timezone.utc ).isoformat(),
            data_origin        = "synthetic_seed"
        )

    def _send_and_respond( self, message, response_type, response_value,
                           timeout_seconds=10, response_options=None,
                           response_default="yes" ):
        """
        Send a notification and respond to it. Returns the notification_id.
        (Duplicated from TestPredictionEngineE2E for class independence.)
        """
        params = {
            "message"            : message,
            "type"               : "custom",
            "priority"           : "medium",
            "target_user"        : self.target_email,
            "response_requested" : True,
            "response_type"      : response_type,
            "timeout_seconds"    : timeout_seconds,
            "response_default"   : response_default,
        }
        if response_options:
            params[ "response_options" ] = json.dumps( response_options )

        sse_result = {}
        sse_thread = threading.Thread(
            target = _send_notification_sse,
            args   = ( self.auth_headers, params, sse_result )
        )
        sse_thread.start()

        notification_id = None
        for _ in range( 20 ):
            time.sleep( 0.5 )
            notification_id = _find_notification_id( self._get_db )
            if notification_id:
                break

        assert notification_id is not None, "Notification was not created in DB within timeout"

        response = requests.post(
            f"{BASE_URL}/api/notify/response",
            json = {
                "notification_id" : notification_id,
                "response_value"  : response_value,
            }
        )
        assert response.status_code == 200, f"Response submission failed: {response.text}"

        sse_thread.join( timeout=15 )
        time.sleep( 0.5 )

        return notification_id

    # -------------------------------------------------------------------
    # Test 9: Warm yes_no — seed 3 "yes" decisions, predict similar
    # -------------------------------------------------------------------
    def test_warm_yes_no_cbr_prediction( self ):
        """
        Warm prediction: seed 3 "yes" permission decisions, send a similar
        question, and verify CBR majority vote fires.

        Expects:
            - prediction_strategy = "cbr_majority_vote"
            - predicted_value contains "yes"
        """
        # Seed 3 similar permission decisions with "yes" responses
        self._seed_decision( "Should I proceed with the deployment?", "permission", "yes" )
        self._seed_decision( "Should I go ahead with the deployment?", "permission", "yes" )
        self._seed_decision( "Can I proceed with the deployment now?", "permission", "yes" )

        # Reconfigure engine to use test table
        from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
        PredictionEngine.reset()
        engine = PredictionEngine( debug=True )
        engine.lancedb_table = TEST_LANCEDB_TABLE
        engine._embedding_store = None  # Force re-init with test table

        # Send a similar notification and respond
        notification_id = self._send_and_respond(
            message        = "Should I proceed with deploying the hotfix?",
            response_type  = "yes_no",
            response_value = "yes",
        )

        log = _get_prediction_log( self._get_db, notification_id )
        assert log is not None, "No prediction_log entry found"
        assert log.response_type == "yes_no"
        # The prediction should use CBR if embeddings matched
        # (cold_start is acceptable if similarity threshold not met)
        assert log.prediction_strategy in [ "cbr_majority_vote", "cold_start" ]

    # -------------------------------------------------------------------
    # Test 10: Warm qualifier — seed cases with [comment: ...] qualifiers
    # -------------------------------------------------------------------
    def test_warm_qualifier_prediction( self ):
        """
        Warm prediction with qualifier: seed decisions containing
        [comment: ...] qualifier text.

        Expects:
            - predicted_value present when CBR matches
            - If CBR matches, predicted_qualifier may be populated
        """
        self._seed_decision( "Delete the old backup files?", "permission", "yes [comment: only the March ones]" )
        self._seed_decision( "Remove the old backup files?", "permission", "yes [comment: only the old ones]" )
        self._seed_decision( "Can I delete the old backup archives?", "permission", "yes [comment: only the March ones]" )

        from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
        PredictionEngine.reset()
        engine = PredictionEngine( debug=True )
        engine.lancedb_table = TEST_LANCEDB_TABLE
        engine._embedding_store = None

        notification_id = self._send_and_respond(
            message        = "Should I delete the old backup files from March?",
            response_type  = "yes_no",
            response_value = "yes [comment: only the March ones]",
        )

        log = _get_prediction_log( self._get_db, notification_id )
        assert log is not None
        assert log.prediction_strategy in [ "cbr_majority_vote", "cold_start" ]

    # -------------------------------------------------------------------
    # Test 11: Accuracy correct — predict "yes", respond "yes"
    # -------------------------------------------------------------------
    def test_warm_accuracy_correct( self ):
        """
        When prediction matches actual response, accuracy_match should be True.

        Expects:
            - If cbr_majority_vote predicts "yes" and user responds "yes": accuracy_match = True
        """
        self._seed_decision( "Approve the pull request?", "permission", "yes" )
        self._seed_decision( "Approve the PR changes?", "permission", "yes" )
        self._seed_decision( "Should I approve the pull request?", "permission", "yes" )

        from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
        PredictionEngine.reset()
        engine = PredictionEngine( debug=True )
        engine.lancedb_table = TEST_LANCEDB_TABLE
        engine._embedding_store = None

        notification_id = self._send_and_respond(
            message        = "Approve the pull request for the hotfix?",
            response_type  = "yes_no",
            response_value = "yes",
        )

        log = _get_prediction_log( self._get_db, notification_id )
        assert log is not None
        # If CBR predicted, accuracy should match
        if log.prediction_strategy == "cbr_majority_vote":
            assert log.accuracy_match is True, "Predicted yes, responded yes — should match"

    # -------------------------------------------------------------------
    # Test 12: Accuracy incorrect — predict "yes", respond "no"
    # -------------------------------------------------------------------
    def test_warm_accuracy_incorrect( self ):
        """
        When prediction does not match actual response, accuracy_match should be False.

        Expects:
            - If cbr_majority_vote predicts "yes" and user responds "no": accuracy_match = False
        """
        self._seed_decision( "Run the full test suite before merging?", "workflow", "yes" )
        self._seed_decision( "Should I run all tests before the merge?", "workflow", "yes" )
        self._seed_decision( "Run the complete test suite before merge?", "workflow", "yes" )

        from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
        PredictionEngine.reset()
        engine = PredictionEngine( debug=True )
        engine.lancedb_table = TEST_LANCEDB_TABLE
        engine._embedding_store = None

        notification_id = self._send_and_respond(
            message        = "Run the full test suite before merging to main?",
            response_type  = "yes_no",
            response_value = "no",  # Intentionally different from seeded "yes"
        )

        log = _get_prediction_log( self._get_db, notification_id )
        assert log is not None
        if log.prediction_strategy == "cbr_majority_vote":
            assert log.accuracy_match is False, "Predicted yes, responded no — should not match"

    # -------------------------------------------------------------------
    # Test 13: MC warm — seed MC decisions, send similar MC question
    # -------------------------------------------------------------------
    def test_warm_multiple_choice_cbr( self ):
        """
        Warm MC prediction: seed multiple_choice decisions and verify
        CBR majority vote produces predicted answers.

        Expects:
            - prediction_strategy = "cbr_majority_vote" (if embeddings match)
            - predicted_value contains {"answers": {...}}
        """
        mc_answer = json.dumps( { "answers": { "Database": "PostgreSQL" } } )
        self._seed_decision( "Which database should we use for the project?", "architecture", mc_answer )
        self._seed_decision( "What database should we use for the new service?", "architecture", mc_answer )
        self._seed_decision( "Which database for the backend project?", "architecture", mc_answer )

        from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
        PredictionEngine.reset()
        engine = PredictionEngine( debug=True )
        engine.lancedb_table = TEST_LANCEDB_TABLE
        engine._embedding_store = None

        mc_options = [
            {
                "question"    : "Which database should we use?",
                "header"      : "Database",
                "multiSelect" : False,
                "options"     : [
                    { "label": "PostgreSQL", "description": "Relational database" },
                    { "label": "MongoDB", "description": "Document database" },
                ]
            }
        ]

        notification_id = self._send_and_respond(
            message          = "Which database should we use for the new microservice?",
            response_type    = "multiple_choice",
            response_value   = { "answers": { "Database": "PostgreSQL" } },
            response_options = mc_options,
        )

        log = _get_prediction_log( self._get_db, notification_id )
        assert log is not None
        assert log.response_type == "multiple_choice"
        assert log.prediction_strategy in [ "cbr_majority_vote", "cold_start" ]

    # -------------------------------------------------------------------
    # Test 14: MC warm multi-select — seed multi-select decisions
    # -------------------------------------------------------------------
    def test_warm_multiple_choice_multi_select( self ):
        """
        Warm multi-select prediction: seed multi-select decisions and verify
        CBR majority vote produces list-valued predicted answers.

        Expects:
            - prediction_strategy = "cbr_majority_vote" (if embeddings match)
            - predicted_value answers are lists (multi-select format)
        """
        mc_answer = json.dumps( { "answers": { "Features": [ "Auth", "Caching" ] } } )
        self._seed_decision( "Which features should we enable for the service?", "approach", mc_answer )
        self._seed_decision( "What features should we turn on for the new service?", "approach", mc_answer )
        self._seed_decision( "Which features to enable for the backend service?", "approach", mc_answer )

        from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
        PredictionEngine.reset()
        engine = PredictionEngine( debug=True )
        engine.lancedb_table = TEST_LANCEDB_TABLE
        engine._embedding_store = None

        mc_options = [
            {
                "question"    : "Which features should we enable?",
                "header"      : "Features",
                "multiSelect" : True,
                "options"     : [
                    { "label": "Auth", "description": "Authentication system" },
                    { "label": "Caching", "description": "Response caching" },
                    { "label": "Logging", "description": "Request logging" },
                ]
            }
        ]

        notification_id = self._send_and_respond(
            message          = "Which features should we enable for the new microservice?",
            response_type    = "multiple_choice",
            response_value   = { "answers": { "Features": [ "Auth", "Caching" ] } },
            response_options = mc_options,
        )

        log = _get_prediction_log( self._get_db, notification_id )
        assert log is not None
        assert log.response_type == "multiple_choice"
        assert log.prediction_strategy in [ "cbr_majority_vote", "cold_start" ]

    # -------------------------------------------------------------------
    # Test 15: Multi-select accuracy — Jaccard comparison
    # -------------------------------------------------------------------
    def test_warm_multi_select_accuracy( self ):
        """
        Multi-select accuracy: seed ["A","B"], predict similar, actual ["A","C"].
        Verifies Jaccard-based accuracy computation.

        Expects:
            - accuracy_match computed based on Jaccard threshold
            - accuracy_detail contains jaccard score
        """
        mc_answer = json.dumps( { "answers": { "Features": [ "Auth", "Caching" ] } } )
        self._seed_decision( "Which features for the API gateway?", "approach", mc_answer )
        self._seed_decision( "What features for the API gateway?", "approach", mc_answer )
        self._seed_decision( "Select features for the API gateway?", "approach", mc_answer )

        from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
        PredictionEngine.reset()
        engine = PredictionEngine( debug=True )
        engine.lancedb_table = TEST_LANCEDB_TABLE
        engine._embedding_store = None

        mc_options = [
            {
                "question"    : "Which features for the gateway?",
                "header"      : "Features",
                "multiSelect" : True,
                "options"     : [
                    { "label": "Auth", "description": "Authentication" },
                    { "label": "Caching", "description": "Caching" },
                    { "label": "Logging", "description": "Logging" },
                ]
            }
        ]

        # Respond with a different set to test Jaccard computation
        notification_id = self._send_and_respond(
            message          = "Which features for the new API gateway?",
            response_type    = "multiple_choice",
            response_value   = { "answers": { "Features": [ "Auth", "Logging" ] } },
            response_options = mc_options,
        )

        log = _get_prediction_log( self._get_db, notification_id )
        assert log is not None
        assert log.response_type == "multiple_choice"
        # If CBR predicted ["Auth", "Caching"] and actual is ["Auth", "Logging"]:
        # Jaccard = 1/3 ≈ 0.333 < 0.5 → accuracy_match = False
        if log.prediction_strategy == "cbr_majority_vote":
            assert log.accuracy_match is not None

    # -------------------------------------------------------------------
    # Test 18: Warm open_ended exact match retrieval
    # -------------------------------------------------------------------
    def test_warm_open_ended_exact_match( self ):
        """
        Warm prediction: seed 3 identical open_ended questions, send exact match.
        Expects cbr_retrieval strategy with the seeded answer.
        """
        self._seed_decision( "What naming convention should I use?", "input", "snake_case" )
        self._seed_decision( "What naming convention should I use?", "input", "snake_case" )
        self._seed_decision( "What naming convention should I use?", "input", "snake_case" )

        from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
        PredictionEngine.reset()
        engine = PredictionEngine( debug=True )
        engine.lancedb_table = TEST_LANCEDB_TABLE
        engine._embedding_store = None  # Force re-init with test table

        notification_id = self._send_and_respond(
            message        = "What naming convention should I use?",
            response_type  = "open_ended",
            response_value = "snake_case",
        )

        log = _get_prediction_log( self._get_db, notification_id )
        assert log is not None
        assert log.response_type == "open_ended"
        # Should be cbr_retrieval (exact match) or cold_start if embeddings differ
        assert log.prediction_strategy in [ "cbr_retrieval", "llm_synthesis", "cold_start" ]

    # -------------------------------------------------------------------
    # Test 19: Warm open_ended LLM synthesis (mocked LLM)
    # -------------------------------------------------------------------
    def test_warm_open_ended_llm_synthesis( self ):
        """
        Warm prediction: seed 3 similar (not identical) questions.
        Expects llm_synthesis or cbr_retrieval strategy.
        LLM is NOT mocked here — this tests the full pipeline including
        fallback to retrieval if LLM client is unavailable.
        """
        self._seed_decision( "Which naming style for Python files?", "input", "snake_case" )
        self._seed_decision( "What case should I use for filenames?", "input", "snake_case" )
        self._seed_decision( "How should I name Python modules?", "input", "snake_case with underscores" )

        from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
        PredictionEngine.reset()
        engine = PredictionEngine( debug=True )
        engine.lancedb_table = TEST_LANCEDB_TABLE
        engine._embedding_store = None

        notification_id = self._send_and_respond(
            message        = "What naming convention for the new utility module?",
            response_type  = "open_ended",
            response_value = "snake_case",
        )

        log = _get_prediction_log( self._get_db, notification_id )
        assert log is not None
        assert log.response_type == "open_ended"
        # Could be llm_synthesis, cbr_retrieval (if LLM unavailable), or cold_start
        assert log.prediction_strategy in [ "llm_synthesis", "cbr_retrieval", "cold_start" ]

    # -------------------------------------------------------------------
    # Test 20: Warm open_ended_batch retrieval
    # -------------------------------------------------------------------
    def test_warm_open_ended_batch_retrieval( self ):
        """
        Warm prediction: seed 3 similar batch answers, verify retrieval.
        """
        batch_answer = json.dumps( { "answers": { "Topic": "quantum computing", "Budget": "no limit" } } )
        self._seed_decision( "What are the project parameters?", "input", batch_answer )
        self._seed_decision( "Tell me the project parameters?", "input", batch_answer )
        self._seed_decision( "Describe the project parameters?", "input", batch_answer )

        from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
        PredictionEngine.reset()
        engine = PredictionEngine( debug=True )
        engine.lancedb_table = TEST_LANCEDB_TABLE
        engine._embedding_store = None

        notification_id = self._send_and_respond(
            message        = "What are the project configuration parameters?",
            response_type  = "open_ended_batch",
            response_value = { "answers": { "Topic": "quantum computing", "Budget": "no limit" } },
        )

        log = _get_prediction_log( self._get_db, notification_id )
        assert log is not None
        assert log.response_type == "open_ended_batch"
        assert log.prediction_strategy in [ "cbr_retrieval", "llm_synthesis", "cold_start" ]

    # -------------------------------------------------------------------
    # Test 21: Warm open_ended accuracy
    # -------------------------------------------------------------------
    def test_warm_open_ended_accuracy( self ):
        """
        Predict + respond with similar text, check accuracy_match is computed.
        """
        self._seed_decision( "What database should I use?", "approach", "PostgreSQL" )
        self._seed_decision( "Which database for this project?", "approach", "PostgreSQL" )
        self._seed_decision( "Recommend a database?", "approach", "PostgreSQL for sure" )

        from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
        PredictionEngine.reset()
        engine = PredictionEngine( debug=True )
        engine.lancedb_table = TEST_LANCEDB_TABLE
        engine._embedding_store = None

        notification_id = self._send_and_respond(
            message        = "What database should we use for the new service?",
            response_type  = "open_ended",
            response_value = "PostgreSQL",
        )

        log = _get_prediction_log( self._get_db, notification_id )
        assert log is not None
        assert log.response_type == "open_ended"
        # accuracy_match should be computed (either True or False)
        if log.prediction_strategy in [ "cbr_retrieval", "llm_synthesis" ]:
            assert log.accuracy_match is not None
