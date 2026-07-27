#!/usr/bin/env python3
"""
E2E integration tests: prediction-hint thumbs votes STEER later predictions (Stage 3).

The thumbs-vote training-signal loop, end to end against the live server + DB:
a 👍 recorded via POST /api/notify/prediction-vote writes an APPROVED organic case
into the engine's CBR store, and a later similar question is steered TOWARD that
answer (approved weight beats a raw majority). A 👎 writes a REJECTED case whose
NEGATIVE vote steers the engine AWAY from that answer.

Design doc: src/rnd/v0.1.8/2026.06.03-prediction-hint-thumbs-vote-training-signal.md
(Stage 1 = ratification-aware weighting; Stage 2 = vote capture; Stage 3 = this loop
verified DB-backed, plus multi-select/open-ended weighting coverage).

Venue: :8000 ONLY (mutates LanceDB + Postgres; needs the Testing config block whose
`prediction engine lancedb table = prediction_decisions_test`). Schedule via
POST /api/test-suite/submit — never run ad-hoc against :7999.

Requires:
    - FastAPI server on port 8000 (Testing config block)
    - PostgreSQL (lupin_db_test) + EmbeddingProvider reachable
    - Vote weights at defaults: approved=2.0, rejected=2.0

Run:
    ./src/tests/run-integration-tests.sh -v
    OR: pytest src/tests/integration/test_prediction_vote_steering_e2e.py -v
"""

import os

import json
import time
import uuid
import threading

import requests
import pytest

import cosa.utils.util as cu

BASE_URL           = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:8000" )
TEST_LANCEDB_TABLE = "prediction_decisions_test"


def _send_notification_sse( headers, params, result_holder ):
    """Send a response-required notification in a background thread (SSE blocks)."""
    try:
        r = requests.post( f"{BASE_URL}/api/notify", headers=headers, params=params,
                           stream=True, timeout=30 )
        result_holder[ "status_code" ] = r.status_code
        for line in r.iter_lines():
            pass  # drain the SSE stream until the response/timeout closes it
    except Exception as e:
        result_holder[ "error" ] = str( e )


def _find_notification_id( session_factory ):
    """Most recent notification ID from the DB, or None."""
    from cosa.rest.postgres_models import Notification

    with session_factory() as session:
        notif = session.query( Notification ).order_by(
            Notification.created_at.desc()
        ).first()
        if notif:
            return str( notif.id )
    return None


def _get_prediction_log( session_factory, notification_id ):
    """prediction_log row for a notification (detached), or None."""
    from sqlalchemy.orm import make_transient
    from cosa.rest.db.repositories.prediction_log_repository import PredictionLogRepository

    with session_factory() as session:
        repo = PredictionLogRepository( session )
        log  = repo.get_by_notification_id( notification_id )
        if log is not None:
            session.refresh( log )
            make_transient( log )
        return log


class TestPredictionVoteSteeringE2E:
    """
    DB-backed steering: seed ordinary cases + record real votes via the endpoint,
    then verify a later similar prediction lands on the human-confirmed side.
    """

    @pytest.fixture( autouse=True )
    def setup_auth( self, ws_connection ):
        self.user_data    = ws_connection
        self.auth_headers = { "Authorization": f"Bearer {ws_connection[ 'access_token' ]}" }
        self.target_email = ws_connection[ "email" ]

    @pytest.fixture( autouse=True )
    def setup_db( self ):
        from cosa.rest.db.database import get_db
        self._get_db = get_db

    @pytest.fixture( autouse=True )
    def clean_prediction_state( self ):
        """Server-side: drop the test LanceDB table + reset the engine singleton
        before AND after each test (server owns the table files — root in Docker)."""
        requests.get( f"{BASE_URL}/api/prediction-engine/reset", params={ "drop_table": "true" } )
        yield
        requests.get( f"{BASE_URL}/api/prediction-engine/reset", params={ "drop_table": "true" } )

    # -- helpers ------------------------------------------------------------

    def _generate_embedding_http( self, text ):
        response = requests.post(
            f"{BASE_URL}/api/embeddings/generate",
            json    = { "text": text, "content_type": "prose" },
            headers = self.auth_headers,
            timeout = 10
        )
        assert response.status_code == 200, f"Embedding generation failed: {response.text}"
        embedding = response.json()[ "embedding" ]
        assert len( embedding ) == 768
        return embedding

    def _seed_decision( self, question, category, decision_value, response_type="yes_no" ):
        """Seed an ORDINARY (not_required) case — the raw-majority side of the contest."""
        from cosa.agents.decision_proxy.proxy_decision_embeddings import ProxyDecisionEmbeddings
        from datetime import datetime, timezone

        embedding    = self._generate_embedding_http( question )
        # NO db_path (decision 2b20a6d6). These are E2E tests: they seed here and then ask
        # the SERVER to predict, so the seed MUST land where the server reads. Under the
        # live `postgres` backend that is the PredictionDecisionRepository, and the
        # LanceDB path this used to pass was never honored — it only made the call look
        # isolated. `resolve_lancedb_path` now raises on it.
        #
        # Venue note: pytest runs inside the test container (LUPIN_ENV=testing), so both
        # this process and the server resolve to `lupin_db_test` — the dedicated test
        # database, NOT the live `lupin_db_dev` store Rick's ruling protects.
        #
        # TEST_LANCEDB_TABLE is retained for the LanceDB path only; _pg_add_decision does
        # not forward table_name to the repository, so it buys no isolation under postgres.
        store        = ProxyDecisionEmbeddings(
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
            data_origin        = "synthetic_seed",
            response_type      = response_type
        )

    def _vote( self, vote, question, predicted_value, category, response_type="yes_no" ):
        """
        Record a real thumbs vote through the capture endpoint (Stage 2 write path).
        Uses a fresh non-UUID notification id so the endpoint falls back to the
        client-supplied question (no persisted notification needed) and each vote
        creates its own hintvote-* case.
        """
        notification_id = f"steer-{uuid.uuid4().hex[ :12 ]}"
        response = requests.post(
            f"{BASE_URL}/api/notify/prediction-vote/{notification_id}",
            headers = self.auth_headers,
            json    = {
                "vote"            : vote,
                "question"        : question,
                "predicted_value" : predicted_value,
                "category"        : category,
                "response_type"   : response_type,
            },
            timeout = 30
        )
        assert response.status_code == 200, f"vote POST failed: {response.text}"
        body = response.json()
        expected_state = "approved" if vote == "up" else "rejected"
        assert body[ "ratification_state" ] == expected_state
        return body

    def _send_and_respond( self, message, response_type, response_value, response_default="yes" ):
        """Send a response-required notification, answer it, return its id."""
        params = {
            "message"            : message,
            "type"               : "custom",
            "priority"           : "medium",
            "target_user"        : self.target_email,
            "response_requested" : True,
            "response_type"      : response_type,
            "timeout_seconds"    : 10,
            "response_default"   : response_default,
        }

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
            json = { "notification_id": notification_id, "response_value": response_value }
        )
        assert response.status_code == 200, f"Response submission failed: {response.text}"

        sse_thread.join( timeout=15 )
        time.sleep( 0.5 )
        return notification_id

    # -- the steering contests ----------------------------------------------

    def test_thumbs_up_steers_prediction_toward_approved_answer( self ):
        """
        Contest: 3 ordinary 'no' cases vs 2 👍-approved 'yes' cases.
        Raw majority says 'no' (3 vs 2); approved weight (2.0 each → 4.0) says 'yes'.
        The prediction landing on 'yes' is the up-vote steering, DB-backed.

        Phrasing note: every message keys ONLY the 'should i' permission keyword
        (no branch/push/merge/etc.) so the keyword classifier deterministically
        categorizes all cases AND the incoming question as 'permission'.
        """
        self._seed_decision( "Should I archive the stale draft documents?", "permission", "no" )
        self._seed_decision( "Should I archive the old draft documents?", "permission", "no" )
        self._seed_decision( "Should I archive stale draft documents now?", "permission", "no" )

        self._vote( "up", "Should I archive stale draft documents today?", "yes", "permission" )
        self._vote( "up", "Should I archive the stale drafts?", "yes", "permission" )

        notification_id = self._send_and_respond(
            message        = "Should I archive the stale draft documents this week?",
            response_type  = "yes_no",
            response_value = "yes",
        )

        log = _get_prediction_log( self._get_db, notification_id )
        assert log is not None, "No prediction_log entry found"
        assert log.prediction_strategy == "cbr_majority_vote", \
            f"expected warm CBR prediction, got {log.prediction_strategy} (similarity retrieval failed?)"
        assert log.predicted_value[ "value" ] == "yes", \
            f"👍-approved 'yes' (weight 4.0) should beat raw 'no' majority (3.0); got {log.predicted_value}"

    def test_thumbs_down_steers_prediction_away_from_rejected_answer( self ):
        """
        Contest: 2 ordinary 'yes' cases + 1 ordinary 'no' case + 1 👎-rejected 'yes' case.
        Raw majority says 'yes' (3 vs 1); the rejected case votes -2.0 against 'yes'
        (2 - 2 = 0 vs 1) so the engine steers to 'no'.
        """
        # 'push' + 'branch' double-key the workflow category in every message —
        # beats the single 'should i' permission hit, deterministically 'workflow'.
        self._seed_decision( "Should I force-push the rebased branch?", "workflow", "yes" )
        self._seed_decision( "Should I force push the rebased branch?", "workflow", "yes" )
        self._seed_decision( "Force-push the rebased branch to origin?", "workflow", "no" )

        self._vote( "down", "Should we force-push rebased branches?", "yes", "workflow" )

        notification_id = self._send_and_respond(
            message        = "Should I force-push the rebased feature branch?",
            response_type  = "yes_no",
            response_value = "no",
            response_default = "no",
        )

        log = _get_prediction_log( self._get_db, notification_id )
        assert log is not None, "No prediction_log entry found"
        assert log.prediction_strategy == "cbr_majority_vote", \
            f"expected warm CBR prediction, got {log.prediction_strategy} (similarity retrieval failed?)"
        assert log.predicted_value[ "value" ] == "no", \
            f"👎 on 'yes' (-2.0) should flip the raw 'yes' majority to 'no'; got {log.predicted_value}"

    def test_revote_flips_case_in_place_and_changes_steering( self ):
        """
        Idempotent re-vote: 👍 then 👎 on the SAME notification id flips the one
        hintvote case approved → rejected (updated=True, no duplicate), and the
        later prediction follows the FINAL state.
        """
        # 'commit' + 'merge' double-key workflow in every message (see test 2 note).
        self._seed_decision( "Should I squash the migration commits before merge?", "workflow", "no" )
        self._seed_decision( "Squash the migration commits before the merge?", "workflow", "no" )

        notification_id_voted = f"steer-revote-{uuid.uuid4().hex[ :8 ]}"
        question              = "Should we squash migration commits before merge?"
        for vote, expected_updated in ( ( "up", False ), ( "down", True ) ):
            response = requests.post(
                f"{BASE_URL}/api/notify/prediction-vote/{notification_id_voted}",
                headers = self.auth_headers,
                json    = { "vote": vote, "question": question, "predicted_value": "yes",
                            "category": "workflow", "response_type": "yes_no" },
                timeout = 30
            )
            assert response.status_code == 200, f"vote POST failed: {response.text}"
            assert response.json()[ "updated" ] is expected_updated

        notification_id = self._send_and_respond(
            message        = "Should I squash migration commits before the merge?",
            response_type  = "yes_no",
            response_value = "no",
            response_default = "no",
        )

        log = _get_prediction_log( self._get_db, notification_id )
        assert log is not None, "No prediction_log entry found"
        assert log.prediction_strategy == "cbr_majority_vote", \
            f"expected warm CBR prediction, got {log.prediction_strategy}"
        # Final state is rejected: 'yes' tallies -2.0, ordinary 'no' tallies 2.0 → 'no'
        assert log.predicted_value[ "value" ] == "no", \
            f"re-voted-to-👎 'yes' must not win; got {log.predicted_value}"
