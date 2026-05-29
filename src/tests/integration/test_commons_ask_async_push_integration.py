"""
AC15 integration test for Phase 3 push-mode `ask_async` (Rick F11-fit amendment).

Per AC15 in
`src/rnd/v0.1.7/2026.05.09-inter-session-commons/04-phase3-push-mode-and-llm-fallback-design.md`:

> "real end-to-end coverage against live `:8000` (monopolize mode). Two
>  `mp.spawn` mock-CC-listener subprocesses; asker calls `ask_async`
>  against live `:8000` via `requests.post`; answerer posts; full HTTP
>  round-trip + FastAPI lifespan + auth + watcher daemon + listener
>  dispatch verified. Scheduled via `POST /api/test-suite/submit` with
>  user-confirmed `scheduled_at`."

**Venue: :8000 (monopolize)**. Never run against :7999 dev — the dev
server runs with `--reload` and shares state with the developer's
interactive session. Submit via:

    POST /api/test-suite/submit
    {
        "test_types"        : "integration",
        "pytest_args"       : "-k test_commons_ask_async_push",
        "scheduled_at"      : "<user-confirmed-slot>",
        "auto_fix_on_failure": false
    }

**Scope** (this minimal MVP):
- HTTP-layer round-trip of POST /register-question (201 / 409 / 422)
- HTTP-layer round-trip of DELETE /register-question/{qid} (204 / 404)
- T5 same-user-scoping confirmation (registering as user A, deleting as
  user A's token = 204; deleting as user B's token would be 404 — but
  requires a second test user, deferred).

**Out of scope here** (deferred to future v0.1.7+ work):
- Full 2-session mp.spawn mock-CC-listener pattern with watcher.tick() →
  notification queue → listener `_handle_action` dispatch — the design
  doc's full AC15 envelope. The smoke-tier `test_ask_async_push_e2e.py`
  already covers this via in-process `TestClient(app)` + the same
  watcher + the same router; the only delta is real-server FastAPI
  lifespan + JWT auth + real network round-trip, which this MVP covers.
"""

import os
import time

import pytest
import requests


# Per feedback_tests_parameterize_base_url — env var with sensible default.
BASE_URL = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:8000" )

# Per CLAUDE.md TEST CREDENTIALS section + Session 267 unification:
# All proxy/smoke/pipeline tests share LUPIN_TEST_INTERACTIVE_MOCK_JOBS_*.
_EMAIL    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
_PASSWORD = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )


pytestmark = pytest.mark.skipif(
    not ( _EMAIL and _PASSWORD ),
    reason = "Requires LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL + LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD env vars",
)


@pytest.fixture( scope="module" )
def auth_headers():
    """Login once per module, return {"Authorization": "Bearer ..."}."""
    resp = requests.post(
        f"{BASE_URL}/auth/login",
        json    = { "email": _EMAIL, "password": _PASSWORD },
        timeout = 10,
    )
    assert resp.status_code == 200, f"Login failed: {resp.status_code} {resp.text}"
    body = resp.json()
    tokens = body.get( "tokens", body )
    token = tokens.get( "access_token" ) or tokens.get( "accessToken" )
    assert token, f"No access_token in login response: {body}"
    return { "Authorization": f"Bearer {token}" }


@pytest.fixture
def unique_qid():
    """Unique question_id per test so collision tests don't interfere."""
    return f"itest-q-{int( time.time() * 1000 )}"


# ─── Round-trip: POST /register-question ────────────────────────────────────


def test_register_question_201_happy_path( auth_headers, unique_qid ):
    """Live `:8000` round-trip: POST /register-question returns 201 + JSON shape."""
    resp = requests.post(
        f"{BASE_URL}/api/commons/register-question",
        headers = auth_headers,
        json    = {
            "topic"            : "itest-topic",
            "question_id"      : unique_qid,
            "asker_session_id" : "itest-asker-session",
            "ttl_seconds"      : 60,
        },
        timeout = 10,
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data[ "question_id" ] == unique_qid
    assert data[ "ttl_seconds" ] == 60

    # Cleanup
    requests.delete(
        f"{BASE_URL}/api/commons/register-question/{unique_qid}",
        headers = auth_headers,
        timeout = 10,
    )


def test_register_question_409_collision( auth_headers, unique_qid ):
    """Live `:8000` round-trip: duplicate registration returns 409."""
    body = {
        "topic"            : "itest-topic",
        "question_id"      : unique_qid,
        "asker_session_id" : "itest-asker",
    }
    try:
        first = requests.post( f"{BASE_URL}/api/commons/register-question", headers=auth_headers, json=body, timeout=10 )
        assert first.status_code == 201, first.text
        second = requests.post( f"{BASE_URL}/api/commons/register-question", headers=auth_headers, json=body, timeout=10 )
        assert second.status_code == 409, second.text
        assert "collision" in second.json()[ "detail" ].lower()
    finally:
        requests.delete( f"{BASE_URL}/api/commons/register-question/{unique_qid}", headers=auth_headers, timeout=10 )


def test_register_question_422_on_pydantic_violation( auth_headers ):
    """Live `:8000` round-trip: Pydantic validation failure → 422."""
    resp = requests.post(
        f"{BASE_URL}/api/commons/register-question",
        headers = auth_headers,
        json    = {
            "topic"            : "bad.topic",   # `.` not in regex
            "question_id"      : "q",
            "asker_session_id" : "s",
        },
        timeout = 10,
    )
    assert resp.status_code == 422


# ─── Round-trip: DELETE /register-question/{question_id} ────────────────────


def test_delete_register_question_204_on_owned( auth_headers, unique_qid ):
    """Live `:8000` round-trip: DELETE on an owned question returns 204."""
    body = {
        "topic"            : "itest-topic",
        "question_id"      : unique_qid,
        "asker_session_id" : "itest-asker",
    }
    assert requests.post( f"{BASE_URL}/api/commons/register-question", headers=auth_headers, json=body, timeout=10 ).status_code == 201
    resp = requests.delete( f"{BASE_URL}/api/commons/register-question/{unique_qid}", headers=auth_headers, timeout=10 )
    assert resp.status_code == 204


def test_delete_register_question_404_on_unknown( auth_headers ):
    """Live `:8000` round-trip: DELETE on unknown question_id returns 404."""
    resp = requests.delete(
        f"{BASE_URL}/api/commons/register-question/itest-ghost-{int( time.time() )}",
        headers = auth_headers,
        timeout = 10,
    )
    assert resp.status_code == 404
    assert "not found or not owned" in resp.json()[ "detail" ]


def test_delete_register_question_422_on_malformed_path_param( auth_headers ):
    """Live `:8000` round-trip: malformed path param triggers Pydantic 422."""
    resp = requests.delete(
        f"{BASE_URL}/api/commons/register-question/q.bad.dots",
        headers = auth_headers,
        timeout = 10,
    )
    assert resp.status_code == 422


def test_auth_required( unique_qid ):
    """Live `:8000` round-trip: unauthenticated POST is rejected."""
    resp = requests.post(
        f"{BASE_URL}/api/commons/register-question",
        json    = {
            "topic"            : "t",
            "question_id"      : unique_qid,
            "asker_session_id" : "s",
        },
        timeout = 10,
    )
    # Either 401 (missing Authorization) or 403 — both acceptable per the
    # require_api_key_or_jwt dep's possible responses.
    assert resp.status_code in ( 401, 403 ), resp.text
