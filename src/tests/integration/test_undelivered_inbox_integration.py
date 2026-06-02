"""
Integration test — lever D (pull-able AFK inbox), messaging-coordination plane.

Live round-trip against a real server + DB ( :8000 scheduled venue ):
  1. send a fire-and-forget notify to the test user while they are OFFLINE
     (no WS connection in this requests-only test) → it persists undelivered
     (state 'created'/'queued'), per the "DB row remains for forensic recovery" path;
  2. pull GET /api/notifications/undelivered as that user → the just-sent
     notification is present, undelivered_count >= 1.

Design: src/rnd/v0.1.8/2026.06.02-messaging-coordination-plane-design.md (lever D1).
Venue: :8000 (mutates DB state). Submit via the test-suite channel.
"""

import os
import time

import pytest
import requests


# Per feedback_tests_parameterize_base_url — env var with sensible default.
BASE_URL = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:8000" )

_EMAIL    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
_PASSWORD = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )


pytestmark = pytest.mark.skipif(
    not ( _EMAIL and _PASSWORD ),
    reason = "Requires LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL + LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD env vars",
)


@pytest.fixture( scope="module" )
def auth_headers():
    """Login once per module → {"Authorization": "Bearer ..."}."""
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


def test_undelivered_inbox_round_trip( auth_headers ):
    """A notify sent while the user is offline shows up in the pull-able undelivered inbox."""
    marker = f"lever-d-itest-{int( time.time() * 1000 )}"

    # 1. Fire-and-forget notify to self while offline (no WS) → persists undelivered.
    send = requests.post(
        f"{BASE_URL}/api/notify",
        headers = auth_headers,
        params  = {
            "message"            : marker,
            "target_user"        : _EMAIL,
            "type"               : "task",
            "priority"           : "low",
            "response_requested" : "false",
        },
        timeout = 15,
    )
    assert send.status_code in ( 200, 201 ), f"notify send failed: {send.status_code} {send.text}"

    # 2. Pull the undelivered inbox as that user. High limit: the inbox is oldest-first
    #    and the shared test user accrues a backlog of stale undelivered rows, so a
    #    freshly-sent (newest) marker sorts last — fetch wide enough to include it.
    resp = requests.get(
        f"{BASE_URL}/api/notifications/undelivered",
        headers = auth_headers,
        params  = { "limit": 1000 },
        timeout = 10,
    )
    assert resp.status_code == 200, f"undelivered GET failed: {resp.status_code} {resp.text}"
    data = resp.json()
    assert data[ "status" ] == "success", data
    assert "undelivered_count" in data and "notifications" in data, data

    messages = [ n.get( "message" ) for n in data[ "notifications" ] ]
    assert marker in messages, f"sent marker {marker!r} not found in undelivered inbox: {messages}"
    assert data[ "undelivered_count" ] >= 1
    # Every returned item must be in a non-delivered state (created/queued).
    for n in data[ "notifications" ]:
        assert n.get( "state" ) in ( "created", "queued" ), f"unexpected state: {n}"


def test_undelivered_requires_auth():
    """The pull endpoint rejects an unauthenticated request."""
    resp = requests.get( f"{BASE_URL}/api/notifications/undelivered", timeout=10 )
    assert resp.status_code in ( 401, 403 ), resp.text
