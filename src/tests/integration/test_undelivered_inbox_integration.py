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


def test_age_cap_excludes_stale_undelivered():
    """
    Storm-guard regression (2026-06-03 incident): the undelivered drain MUST
    exclude rows older than `notification undelivered max age hours` so a server
    bounce / WS reconnect can never replay months-old notifications as a TTS storm.

    DB-backed (mirrors the live probe that confirmed the fix): insert one FRESH
    and one STALE (48h-old) undelivered row for the test user, then assert the
    repo's get/count with a 24h cap returns ONLY the fresh row while the uncapped
    query returns both. Self-cleaning in a finally block.

    Venue: :8000 (mutates DB state; runs in-container where get_db reaches the DB).
    """
    import uuid
    from sqlalchemy import text
    from cosa.rest.db.database import get_db
    from cosa.rest.db.repositories.notification_repository import NotificationRepository

    fresh_id = "0000aaaa-0000-0000-0000-0000000000f1"
    stale_id = "0000aaaa-0000-0000-0000-0000000000f2"

    with get_db() as session:
        row = session.execute( text( "SELECT id FROM users WHERE email = :e" ), { "e": _EMAIL } ).first()
        assert row is not None, f"test user {_EMAIL} not found"
        rid      = str( row[ 0 ] )
        rid_uuid = uuid.UUID( rid )
        repo     = NotificationRepository( session )

        # The shared test user carries a real undelivered backlog (100s of rows), and the
        # getter is limit=100 oldest-first — so a freshly-inserted row sorts PAST the window
        # and absolute get()-membership is unreliable. Assert on the UNBOUNDED count() deltas
        # instead (immune to the limit window), plus stale-exclusion in the capped pull.
        base_no_cap = repo.count_undelivered_for_recipient( rid_uuid )
        base_capped = repo.count_undelivered_for_recipient( rid_uuid, max_age_hours=24 )

        try:
            session.execute( text(
                "INSERT INTO notifications "
                "(id, sender_id, recipient_id, message, type, priority, created_at, response_requested, state, is_hidden) VALUES "
                "(:fid,'probe',:rid,'PROBE fresh','task','high', now(),                    false, 'created', false), "
                "(:sid,'probe',:rid,'PROBE stale','task','high', now() - interval '48 hours', false, 'created', false)"
            ), { "fid": fresh_id, "sid": stale_id, "rid": rid } )
            session.commit()

            no_cap_after = repo.count_undelivered_for_recipient( rid_uuid )
            capped_after = repo.count_undelivered_for_recipient( rid_uuid, max_age_hours=24 )
            capped_msgs  = [ n.message for n in repo.get_undelivered_for_recipient( rid_uuid, max_age_hours=24 ) ]

            # Uncapped count rises by BOTH probes; capped count rises by ONLY the fresh one
            # (the 48h-old stale probe is excluded by the 24h cap) — the structural guard.
            assert no_cap_after - base_no_cap == 2, ( base_no_cap, no_cap_after )
            assert capped_after - base_capped == 1, ( base_capped, capped_after )
            # The 48h-old probe is filtered by the cap BEFORE the limit, so it can never
            # appear in the capped pull regardless of backlog size.
            assert "PROBE stale" not in capped_msgs, capped_msgs
        finally:
            session.execute( text( "DELETE FROM notifications WHERE id IN (:fid, :sid)" ), { "fid": fresh_id, "sid": stale_id } )
            session.commit()
