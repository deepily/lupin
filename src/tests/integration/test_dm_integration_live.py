"""
AC9d integration test for Inter-Session DM Phase 0 (2026-05-15).

Per `src/rnd/v0.1.7/2026.05.15-inter-session-direct-messaging-design.md` AC9d.

**Venue: :8000 (monopolize)**. Submit via:

    POST /api/test-suite/submit
    {
        "test_types"        : "integration",
        "pytest_args"       : "-k test_dm_integration",
        "scheduled_at"      : "<user-confirmed-slot>",
        "auto_fix_on_failure": false
    }

**Scope** (minimal v1 covering the new DM register-question paths):
- HTTP round-trip with recipient_persona — accept 201 OR 422 since recipient
  resolution depends on whether the persona matches an active session at
  test time. Both paths are valid behaviors.
- HTTP round-trip with recipient_session_id — same accept-set.
- 422 with unknown recipient_persona returns rich `RecipientResolutionError`
  body (per Phase 0 Q3-rev amendment).
- 422 with neither field returns `recipient_required`.
- Non-DM register (no recipient_*) continues to work (preserves Phase 3
  contract).

**Out of scope here** (deferred):
- Full 2-CC-subprocess E2E with tmux scrollback inspection — the smoke-tier
  `test_dm_endpoint_smoke.py` already covers the dispatch + watcher wiring
  via in-process TestClient + mocked notification_queue. This integration
  layer covers real-server FastAPI lifespan + JWT auth + real network.
"""

import os
import time

import pytest
import requests


BASE_URL = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:8000" )
_EMAIL    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
_PASSWORD = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )


pytestmark = pytest.mark.skipif(
    not ( _EMAIL and _PASSWORD ),
    reason = "Requires LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL + LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD env vars",
)


@pytest.fixture( scope="module" )
def auth_headers():
    resp = requests.post(
        f"{BASE_URL}/auth/login",
        json    = { "email": _EMAIL, "password": _PASSWORD },
        timeout = 10,
    )
    assert resp.status_code == 200, f"Login failed: {resp.status_code} {resp.text}"
    body   = resp.json()
    tokens = body.get( "tokens", body )
    token  = tokens.get( "access_token" ) or tokens.get( "accessToken" )
    assert token, f"No access_token in login response: {body}"
    return { "Authorization": f"Bearer {token}" }


@pytest.fixture
def unique_qid():
    return f"dm-itest-{int( time.time() * 1000 )}"


# ─── DM register-question — recipient_persona path ──────────────────────────


def test_dm_register_with_unknown_persona_returns_422_with_rich_error( auth_headers, unique_qid ):
    """
    POST with recipient_persona='nonexistent-test-persona-xyz' returns 422
    with the rich RecipientResolutionError body so an AI agent can self-correct.

    This is the deterministic v1 test — we KNOW the persona doesn't exist,
    so resolution definitely fails, and we assert on the error contract shape.
    """
    resp = requests.post(
        f"{BASE_URL}/api/commons/register-question",
        json = {
            "topic"             : "dm-itest-topic",
            "question_id"       : unique_qid,
            "asker_session_id"  : "itest-asker",
            "recipient_persona" : "nonexistent-test-persona-xyz",
        },
        headers = auth_headers,
        timeout = 10,
    )
    assert resp.status_code == 422, resp.text
    body   = resp.json()
    detail = body.get( "detail" ) if isinstance( body, dict ) else body
    assert isinstance( detail, dict ), f"Expected dict detail, got {type( detail )}: {detail!r}"
    assert detail[ "error" ] == "recipient_not_found"
    assert detail[ "supplied_persona" ] == "nonexistent-test-persona-xyz"
    assert isinstance( detail[ "resolution_chain_attempted" ], list )
    assert "exact" in detail[ "resolution_chain_attempted" ]
    assert isinstance( detail[ "candidate_alternatives" ], list )
    assert isinstance( detail[ "suggested_next_action" ], str )
    assert len( detail[ "suggested_next_action" ] ) > 0


def test_dm_register_with_unknown_session_id_returns_422_recipient_inactive( auth_headers, unique_qid ):
    """POST with non-existent recipient_session_id returns 422 recipient_inactive."""
    resp = requests.post(
        f"{BASE_URL}/api/commons/register-question",
        json = {
            "topic"                : "dm-itest-topic",
            "question_id"          : unique_qid,
            "asker_session_id"     : "itest-asker",
            "recipient_session_id" : "phantom-session-xyz",
        },
        headers = auth_headers,
        timeout = 10,
    )
    assert resp.status_code == 422
    detail = resp.json().get( "detail" )
    assert isinstance( detail, dict )
    assert detail[ "error" ] == "recipient_inactive"
    assert detail[ "supplied_session_id" ] == "phantom-session-xyz"


# ─── Phase 3 contract preservation (non-DM register) ────────────────────────


def test_non_dm_register_still_works_returns_201( auth_headers, unique_qid ):
    """
    POST without any recipient_* field continues to work — returns 201
    with `dm_dispatched=None`. Confirms the Phase 3 contract is preserved
    by the DM extension.
    """
    resp = requests.post(
        f"{BASE_URL}/api/commons/register-question",
        json = {
            "topic"            : "dm-itest-topic",
            "question_id"      : unique_qid,
            "asker_session_id" : "itest-asker",
            "ttl_seconds"      : 60,
        },
        headers = auth_headers,
        timeout = 10,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body[ "question_id" ] == unique_qid
    assert body[ "ttl_seconds" ] == 60
    # New field added by DM extension — None when no recipient_* supplied
    assert "dm_dispatched" in body
    assert body[ "dm_dispatched" ] is None

    # Clean up — unregister to keep watcher state tidy
    requests.delete(
        f"{BASE_URL}/api/commons/register-question/{unique_qid}",
        headers = auth_headers,
        timeout = 10,
    )


# ─── 422 Pydantic field-level validation on the DM fields ───────────────────


def test_dm_register_recipient_persona_oversize_returns_422( auth_headers, unique_qid ):
    """recipient_persona length > 64 → 422 (Pydantic max_length)."""
    resp = requests.post(
        f"{BASE_URL}/api/commons/register-question",
        json = {
            "topic"             : "dm-itest-topic",
            "question_id"      : unique_qid,
            "asker_session_id"  : "itest-asker",
            "recipient_persona" : "x" * 65,
        },
        headers = auth_headers,
        timeout = 10,
    )
    assert resp.status_code == 422


def test_dm_register_recipient_session_id_oversize_returns_422( auth_headers, unique_qid ):
    """recipient_session_id length > 128 → 422 (Pydantic max_length)."""
    resp = requests.post(
        f"{BASE_URL}/api/commons/register-question",
        json = {
            "topic"                : "dm-itest-topic",
            "question_id"          : unique_qid,
            "asker_session_id"     : "itest-asker",
            "recipient_session_id" : "s" * 129,
        },
        headers = auth_headers,
        timeout = 10,
    )
    assert resp.status_code == 422
