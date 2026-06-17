"""
AC13 E2E smoke for Phase 3 push-mode `ask_async`.

Per AC13 in
`src/rnd/v0.1.7/2026.05.09-inter-session-commons/04-phase3-push-mode-and-llm-fallback-design.md`:

> "uses `TestClient(app)` to hit `POST /api/commons/register-question`
>  (asserts 201/409/400 response codes + JSON body shape at HTTP layer
>  per F11-fit); then A posts `ask_async`, B reads + answers, watcher
>  dispatches via A's mock `inject_fn`, the recorded `<system-reminder>`
>  body is asserted to contain `'COMMONS PEER REPLY'` + the answer text
>  + the stamped persona."

Venue: :7999 AI-discretionary — non-destructive (tempdir for storage),
fast (<5s), no shared external state.

**Build approach**: instantiates a stripped-down `FastAPI()` app with the
commons router mounted and `init_commons_state(...)` wired manually. Skips
the heavyweight GPU + embedding lifespan in `src/lupin_app/main.py`.

**Auth bypass**: the test overrides `require_api_key_or_jwt` to return a
fixed user_id, avoiding JWT issuance for in-process unit-level coverage.
Real-server auth is covered by AC15 (`test_commons_ask_async_push_integration.py`).
"""

import tempfile
import time
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ── DEPRECATED (revisit-later): superseded by dm_send / notification-native path ──
# This whole E2E file exercises the legacy POST/DELETE /api/commons/register-question
# routes (+ the CommonsQuestionWatcher tick→dispatch push-back), which were RETIRED
# FROM REGISTRATION in the cosa-voice token-reduction Phase 4 (2026-06-15): the path
# is replaced by the notification-native dm_send / POST /api/dm/send flow. The
# routes are commented out in commons.py, so every test below would now 404. The
# file is SKIPPED (not deleted) so it is restorable if the routes are re-enabled;
# the pure-logic cores remain unit-tested in test_commons_router.py and the watcher
# in test_commons_question_watcher.py.
# Plan: src/rnd/v0.1.8/2026.06.13-cosa-voice-token-reduction/03-phase4-legacy-commons-dm-retirement-proposal.md
pytestmark = pytest.mark.skip(
    reason="register-question routes retired (cosa-voice token-reduction Phase 4) — "
           "superseded by dm_send / /api/dm/send; revisit at full-removal"
)

from cosa.rest.commons_ack_watcher import CommonsAckWatcher
from cosa.rest.commons_question_watcher import CommonsQuestionWatcher
from cosa.rest.commons_rate_limiter import CommonsBroadcastRateLimiter
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt
from cosa.rest.routers import commons as commons_router_module
from cosa.rest.routers.commons import init_commons_state, router as commons_router
from lupin_mcp.commons_store import CommonsStore


_TEST_USER_ID = "ac13-test-user"


@pytest.fixture
def captured_pushes():
    """Mutable list to collect inject_fn-pushed notifications."""
    return [ ]


@pytest.fixture
def mock_notification_queue( captured_pushes ):
    """Mock NotificationFifoQueue that captures pushed notifications."""
    class _Q:
        def push_notification( self, **kwargs ):
            captured_pushes.append( kwargs )
    return _Q()


@pytest.fixture
def app_and_state( mock_notification_queue ):
    """
    Build a stripped FastAPI app with the commons router + watchers wired.

    Yields (app, store, question_watcher, ack_watcher) so each test can
    assert on the wired state directly.
    """
    with tempfile.TemporaryDirectory() as tmp:
        store           = CommonsStore( tmp )
        rate_limiter    = CommonsBroadcastRateLimiter( window_seconds=30 )
        ack_watcher     = CommonsAckWatcher( store=store, push_notification_fn=mock_notification_queue.push_notification )
        question_watcher = CommonsQuestionWatcher(
            store        = store,
            per_user_max = 50,
            global_max   = 1000,
        )

        init_commons_state(
            store                            = store,
            rate_limiter                     = rate_limiter,
            ack_watcher                      = ack_watcher,
            active_session_threshold_seconds = 600.0,
            question_watcher                 = question_watcher,
        )

        app = FastAPI()
        app.include_router( commons_router )

        # Auth bypass
        async def _fake_auth():
            return _TEST_USER_ID
        app.dependency_overrides[ require_api_key_or_jwt ] = _fake_auth

        # Notification-queue DI override — point at our mock
        from cosa.rest.routers.commons import get_notification_queue
        app.dependency_overrides[ get_notification_queue ] = lambda: mock_notification_queue

        try:
            yield app, store, question_watcher, ack_watcher
        finally:
            # Idempotent cleanup — reset module-level state for the next test
            init_commons_state(
                store                            = store,
                rate_limiter                     = rate_limiter,
                ack_watcher                      = ack_watcher,
                active_session_threshold_seconds = 600.0,
                question_watcher                 = None,
            )


@pytest.fixture
def client( app_and_state ):
    app, _, _, _ = app_and_state
    return TestClient( app )


# ─── AC13 HTTP-layer assertions (201/409/400/422) ───────────────────────────


def test_register_question_returns_201_on_happy_path( client ):
    """POST /register-question with valid body returns 201 + JSON body shape."""
    resp = client.post(
        "/api/commons/register-question",
        json = {
            "topic"            : "q-topic",
            "question_id"      : "qid-happy-1",
            "asker_session_id" : "asker-sess-1",
            "ttl_seconds"      : 600,
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data[ "question_id" ] == "qid-happy-1"
    assert data[ "ttl_seconds" ] == 600


def test_register_question_returns_409_on_collision( client ):
    """Second POST with same question_id returns 409."""
    body = {
        "topic"            : "q-topic",
        "question_id"      : "qid-dup",
        "asker_session_id" : "asker-sess",
    }
    assert client.post( "/api/commons/register-question", json=body ).status_code == 201
    resp = client.post( "/api/commons/register-question", json=body )
    assert resp.status_code == 409


def test_register_question_returns_422_on_invalid_topic( client ):
    """Topic with disallowed chars (FastAPI auto-422 via Pydantic Field pattern)."""
    resp = client.post(
        "/api/commons/register-question",
        json = {
            "topic"            : "q.topic",   # `.` not in pattern
            "question_id"      : "qid-1",
            "asker_session_id" : "asker",
        },
    )
    assert resp.status_code == 422


def test_register_question_returns_422_on_oversize_question_id( client ):
    """question_id > 64 chars → 422 (Pydantic max_length)."""
    resp = client.post(
        "/api/commons/register-question",
        json = {
            "topic"            : "t",
            "question_id"      : "a" * 65,
            "asker_session_id" : "asker",
        },
    )
    assert resp.status_code == 422


def test_register_question_returns_422_on_missing_field( client ):
    """Missing required field → 422 (Pydantic Field(...))."""
    resp = client.post(
        "/api/commons/register-question",
        json = { "topic": "t", "question_id": "q1" },   # missing asker_session_id
    )
    assert resp.status_code == 422


def test_delete_register_question_204_on_success( client ):
    """DELETE on an in-flight question returns 204."""
    body = {
        "topic"            : "q-topic",
        "question_id"      : "qid-del-1",
        "asker_session_id" : "asker",
    }
    assert client.post( "/api/commons/register-question", json=body ).status_code == 201
    resp = client.delete( "/api/commons/register-question/qid-del-1" )
    assert resp.status_code == 204


def test_delete_register_question_404_on_unknown( client ):
    """DELETE on unknown question_id returns uniform 404 (T5)."""
    resp = client.delete( "/api/commons/register-question/ghost-qid" )
    assert resp.status_code == 404
    assert "not found or not owned" in resp.json()[ "detail" ]


def test_delete_register_question_422_on_malformed_path_param( client ):
    """Path param violating regex/length triggers Pydantic 422."""
    resp = client.delete( "/api/commons/register-question/q.bad" )
    assert resp.status_code == 422


# ─── AC13 end-to-end: register → answer arrives → reminder built ────────────


def test_full_e2e_register_post_answer_tick_dispatches_peer_reply(
    app_and_state, client, captured_pushes
):
    """
    Full happy path: register question via HTTP; answer posted to store; tick()
    fires inject_fn; the resulting notification carries the Q3-framed payload.
    """
    _, store, question_watcher, _ = app_and_state

    # 1. A registers via HTTP
    resp = client.post(
        "/api/commons/register-question",
        json = {
            "topic"            : "qa-topic",
            "question_id"      : "qid-e2e",
            "asker_session_id" : "asker-session-1",
        },
    )
    assert resp.status_code == 201

    # 2. B posts an answer to the same topic with in_reply_to correlation
    store.post(
        topic             = "qa-topic",
        body              = "the answer is 42",
        sender_session_id = "answerer-session",
        persona_name      = "Tiberius",
        persona_icon      = "🌑",
        persona_color     = "#000",
        metadata          = { "kind": "answer", "in_reply_to": "qid-e2e" },
    )

    # 3. Run tick() — watcher detects the matching entry and dispatches
    dispatched = question_watcher.tick()
    assert dispatched == 1

    # 4. Inject_fn → notification queue: assert payload + framing
    assert len( captured_pushes ) == 1
    notif = captured_pushes[ 0 ]
    assert notif[ "type" ]   == "user_initiated_message"
    assert notif[ "title" ]  == "action:commons_answer_received"
    payload = notif[ "payload" ]
    assert payload[ "question_id" ]  == "qid-e2e"
    assert payload[ "body" ]         == "the answer is 42"
    assert payload[ "persona_name" ] == "Tiberius"
    assert payload[ "persona_icon" ] == "🌑"


def test_full_e2e_unregister_prevents_dispatch( app_and_state, client, captured_pushes ):
    """After unregister, an answer posted to the topic is NOT dispatched."""
    _, store, question_watcher, _ = app_and_state

    body = {
        "topic"            : "qa-topic-2",
        "question_id"      : "qid-cancelled",
        "asker_session_id" : "asker-2",
    }
    assert client.post( "/api/commons/register-question", json=body ).status_code == 201
    assert client.delete( "/api/commons/register-question/qid-cancelled" ).status_code == 204

    # Post answer AFTER unregister — should be ignored by tick()
    store.post(
        topic             = "qa-topic-2",
        body              = "should not be delivered",
        sender_session_id = "answerer",
        persona_name      = "Maria",
        persona_icon      = "🌸",
        persona_color     = "#A040A0",
        metadata          = { "kind": "answer", "in_reply_to": "qid-cancelled" },
    )

    assert question_watcher.tick() == 0
    assert captured_pushes == [ ]


# ─── AC17 follow-up — cap-hit returns 429 over HTTP ─────────────────────────


def test_ac17_register_returns_429_on_per_user_cap( mock_notification_queue ):
    """
    AC17 — registering past `per_user_max` returns 429. Uses a fresh
    question_watcher with cap=2 so we don't have to register 51 questions.
    """
    with tempfile.TemporaryDirectory() as tmp:
        store        = CommonsStore( tmp )
        rate_limiter = CommonsBroadcastRateLimiter( window_seconds=30 )
        ack_watcher  = CommonsAckWatcher( store=store, push_notification_fn=mock_notification_queue.push_notification )
        question_watcher = CommonsQuestionWatcher(
            store        = store,
            per_user_max = 2,
            global_max   = 100,
        )
        init_commons_state(
            store                            = store,
            rate_limiter                     = rate_limiter,
            ack_watcher                      = ack_watcher,
            active_session_threshold_seconds = 600.0,
            question_watcher                 = question_watcher,
        )

        app = FastAPI()
        app.include_router( commons_router )

        async def _fake_auth(): return _TEST_USER_ID
        app.dependency_overrides[ require_api_key_or_jwt ] = _fake_auth
        from cosa.rest.routers.commons import get_notification_queue
        app.dependency_overrides[ get_notification_queue ] = lambda: mock_notification_queue

        c = TestClient( app )
        for i in range( 2 ):
            assert c.post(
                "/api/commons/register-question",
                json={ "topic": "t", "question_id": f"q{i}", "asker_session_id": "s" },
            ).status_code == 201

        resp = c.post(
            "/api/commons/register-question",
            json={ "topic": "t", "question_id": "q-overflow", "asker_session_id": "s" },
        )
        assert resp.status_code == 429
        assert "cap" in resp.json()[ "detail" ].lower()
