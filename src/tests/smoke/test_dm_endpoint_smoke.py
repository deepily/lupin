"""
AC9b smoke for Inter-Session DM endpoint (Phase 0 implementation 2026-05-15).

Per AC9b in
`src/rnd/v0.1.7/2026.05.15-inter-session-direct-messaging-design.md`:

> "test_dm_endpoint_smoke.py — TestClient: POST /api/commons/register-question
>  with recipient_persona='radio' → 201 + watcher registered + notification
>  dispatched on the in-process notification_queue mock"

Venue: :7999 AI-discretionary — non-destructive (tempdir), fast (<5s),
no shared external state. Mirrors the fixture pattern of
`test_ask_async_push_e2e.py` with the extra wrinkle that DM resolution
requires the session-enumeration callables to be monkey-patched with
fixture data (no real bridges on disk in unit-test context).

Build approach: stripped FastAPI app with commons router; auth bypass to
fixed user_id; mock notification_queue captures dispatches; monkeypatched
`find_active_voice_persona_sessions` + `_load_bridge_fields` to return a
controlled set of "active sessions" the resolver can match against.
"""

import tempfile
import time
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cosa.rest.commons_ack_watcher import CommonsAckWatcher
from cosa.rest.commons_question_watcher import CommonsQuestionWatcher
from cosa.rest.commons_rate_limiter import CommonsBroadcastRateLimiter
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt
from cosa.rest.routers.commons import init_commons_state, router as commons_router
from lupin_mcp.commons_store import CommonsStore


_TEST_USER_ID = "ac9b-dm-test-user"


# ─── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def captured_pushes():
    return [ ]


@pytest.fixture
def mock_notification_queue( captured_pushes ):
    class _Q:
        def push_notification( self, **kwargs ):
            captured_pushes.append( kwargs )
    return _Q()


def _build_raw_session( session_id: str, persona_name: str ):
    persona_dict = { "name": persona_name, "icon": "🌸", "color": "#F06292" }
    return ( f"/fake/bridge/{session_id}.json", session_id, persona_dict )


def _build_fixture_bridge( session_id: str, user_id: str = _TEST_USER_ID ):
    return {
        "stable_session_id"   : session_id,
        "session_id"          : session_id,
        "user_id"             : user_id,
        "owner_user_id"       : user_id,
        "last_activity_iso"   : "2026-05-15T12:00:00+00:00",
        "idle_detection"      : { "last_interaction_at" : time.time() },
    }


@pytest.fixture
def fixture_sessions():
    """Two same-user sessions for the resolver to enumerate."""
    return [
        _build_raw_session( "sid_radio",  "radio"  ),
        _build_raw_session( "sid_rachel", "rachel" ),
    ]


@pytest.fixture
def fixture_bridges( fixture_sessions ):
    bridges : Dict[ str, Dict[ str, Any ] ] = { }
    for path, sid, _persona in fixture_sessions:
        bridges[ path ] = _build_fixture_bridge( sid )
    return bridges


@pytest.fixture
def app_and_state( mock_notification_queue, fixture_sessions, fixture_bridges, monkeypatch ):
    """Bootstrapped app + monkeypatched session enumeration."""
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

        # Monkeypatch the module-level imports the route handler passes through
        monkeypatch.setattr(
            "cosa.rest.routers.commons.find_active_voice_persona_sessions",
            lambda: fixture_sessions,
        )
        monkeypatch.setattr(
            "cosa.rest.routers.commons._load_bridge_fields",
            lambda path: fixture_bridges.get( path ),
        )

        app = FastAPI()
        app.include_router( commons_router )

        async def _fake_auth():
            return _TEST_USER_ID
        app.dependency_overrides[ require_api_key_or_jwt ] = _fake_auth

        from cosa.rest.routers.commons import get_notification_queue
        app.dependency_overrides[ get_notification_queue ] = lambda: mock_notification_queue

        try:
            yield app, store, question_watcher
        finally:
            init_commons_state(
                store                            = store,
                rate_limiter                     = rate_limiter,
                ack_watcher                      = ack_watcher,
                active_session_threshold_seconds = 600.0,
                question_watcher                 = None,
            )


@pytest.fixture
def client( app_and_state ):
    app, _, _ = app_and_state
    return TestClient( app )


# ─── AC9b smoke assertions ───────────────────────────────────────────────────


def test_dm_register_with_recipient_persona_returns_201( client, captured_pushes ):
    """POST with recipient_persona='radio' → 201 + dm_dispatched=True + dispatch fired."""
    resp = client.post(
        "/api/commons/register-question",
        json = {
            "topic"             : "dm-radio",
            "question_id"       : "qid-dm-1",
            "asker_session_id"  : "sid_asker",
            "recipient_persona" : "radio",
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data[ "question_id" ]    == "qid-dm-1"
    assert data[ "dm_dispatched" ]  is True
    # Verify dispatch fired with the right shape
    assert len( captured_pushes ) == 1
    push = captured_pushes[ 0 ]
    assert push[ "type" ]    == "user_initiated_message"
    assert push[ "title" ]   == "action:commons_question_received"
    assert push[ "payload" ][ "question_id" ]       == "qid-dm-1"
    assert push[ "payload" ][ "topic" ]             == "dm-radio"
    assert push[ "payload" ][ "recipient_persona" ] == "radio"


def test_dm_register_with_recipient_session_id_returns_201( client, captured_pushes ):
    """POST with recipient_session_id='sid_rachel' → 201 + dispatch fired."""
    resp = client.post(
        "/api/commons/register-question",
        json = {
            "topic"                : "dm-rachel",
            "question_id"          : "qid-dm-2",
            "asker_session_id"     : "sid_asker",
            "recipient_session_id" : "sid_rachel",
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data[ "dm_dispatched" ] is True
    assert len( captured_pushes ) == 1
    assert captured_pushes[ 0 ][ "payload" ][ "recipient_persona" ] == "rachel"


def test_dm_register_with_unknown_persona_returns_422_resolution_error( client, captured_pushes ):
    """POST with unknown recipient_persona → 422 with RecipientResolutionError body."""
    resp = client.post(
        "/api/commons/register-question",
        json = {
            "topic"             : "dm-tiberius",
            "question_id"       : "qid-dm-3",
            "asker_session_id"  : "sid_asker",
            "recipient_persona" : "tiberius",
        },
    )
    assert resp.status_code == 422, resp.text
    body = resp.json()
    # FastAPI wraps HTTPException(detail=...) under "detail"; the RecipientResolutionError dict is nested
    detail = body.get( "detail" ) if isinstance( body, dict ) else body
    # detail may be the model_dump or a list (FastAPI validation list); our path is the model_dump
    assert isinstance( detail, dict )
    assert detail[ "error" ] == "recipient_not_found"
    assert detail[ "supplied_persona" ] == "tiberius"
    assert "exact" in detail[ "resolution_chain_attempted" ]
    assert any( c[ "persona" ] == "radio"  for c in detail[ "candidate_alternatives" ] )
    assert any( c[ "persona" ] == "rachel" for c in detail[ "candidate_alternatives" ] )
    # On resolution failure, no dispatch should have fired
    assert captured_pushes == [ ]


def test_dm_register_with_unknown_session_id_returns_422_inactive( client, captured_pushes ):
    """POST with non-existent recipient_session_id → 422 recipient_inactive."""
    resp = client.post(
        "/api/commons/register-question",
        json = {
            "topic"                : "dm-phantom",
            "question_id"          : "qid-dm-4",
            "asker_session_id"     : "sid_asker",
            "recipient_session_id" : "sid_phantom",
        },
    )
    assert resp.status_code == 422
    detail = resp.json().get( "detail" )
    assert isinstance( detail, dict )
    assert detail[ "error" ] == "recipient_inactive"
    assert detail[ "supplied_session_id" ] == "sid_phantom"
    assert captured_pushes == [ ]


def test_dm_register_case_insensitive_persona_match( client, captured_pushes ):
    """POST with recipient_persona='Radio' (capitalized) → 201 + matched 'radio'."""
    resp = client.post(
        "/api/commons/register-question",
        json = {
            "topic"             : "dm-radio",
            "question_id"       : "qid-dm-5",
            "asker_session_id"  : "sid_asker",
            "recipient_persona" : "Radio",
        },
    )
    assert resp.status_code == 201
    assert captured_pushes[ 0 ][ "payload" ][ "recipient_persona" ] == "radio"


def test_dm_register_resolution_failure_unwinds_watcher( client, app_and_state, captured_pushes ):
    """422 resolution failure must unregister the question so the asker can retry."""
    _, _, question_watcher = app_and_state
    resp = client.post(
        "/api/commons/register-question",
        json = {
            "topic"             : "dm-ghost",
            "question_id"       : "qid-dm-6",
            "asker_session_id"  : "sid_asker",
            "recipient_persona" : "ghost",
        },
    )
    assert resp.status_code == 422
    # The watcher should NOT have the question registered anymore
    # (asker can retry with the same question_id)
    resp_retry = client.post(
        "/api/commons/register-question",
        json = {
            "topic"             : "dm-radio",
            "question_id"       : "qid-dm-6",
            "asker_session_id"  : "sid_asker",
            "recipient_persona" : "radio",
        },
    )
    assert resp_retry.status_code == 201, "watcher unwind should let same question_id retry"


def test_non_dm_register_still_works_returns_201( client, captured_pushes ):
    """POST without any recipient_* fields → 201 with dm_dispatched=None (preserves Phase 3 contract)."""
    resp = client.post(
        "/api/commons/register-question",
        json = {
            "topic"            : "free-topic",
            "question_id"      : "qid-no-dm",
            "asker_session_id" : "sid_asker",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data[ "dm_dispatched" ] is None
    # No dispatch should have fired for the non-DM register
    assert captured_pushes == [ ]
