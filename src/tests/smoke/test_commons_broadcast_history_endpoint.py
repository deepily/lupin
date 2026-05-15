"""
Smoke test for the broadcast-history aggregator endpoint.

Tests `GET /api/commons/broadcast-history` — the live :7999 dev-server surface
behind the Commons Traffic Visibility broadcast-card Recent Activity stream.

Per src/rnd/v0.1.7/2026.05.14-commons-traffic-visibility-design.md (AC1,
AC4, AC5, AC11). Step 3 of the 11-step implementation plan.

NON-DESTRUCTIVE: hits a read-only GET endpoint on the dev server. No fixtures
posted; tests assert response SHAPE + filtering invariants against whatever
the live commons store happens to contain. Eligible to run on :7999 per the
TESTING VENUES rubric in CLAUDE.md (no state mutation, ≤2 min, no monopoly
requirement).

Requires environment variables:
    LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL    - Email for /auth/login
    LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD - Password for /auth/login

Run via pytest:
    pytest src/tests/smoke/test_commons_broadcast_history_endpoint.py -v

Or standalone (per the project's quick_smoke_test convention):
    python -m tests.smoke.test_commons_broadcast_history_endpoint
"""

import os
import sys

import pytest
import requests


BASE_URL          = "http://localhost:7999"
ENDPOINT          = f"{BASE_URL}/api/commons/broadcast-history"
LOGIN_ENDPOINT    = f"{BASE_URL}/auth/login"
RESERVED_EXCLUDED = { "presence", "system-events" }


def _require_creds_or_skip():
    """Read creds from env; pytest.skip if absent so the test pass on bare-bones CI."""
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not password:
        pytest.skip( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL/PASSWORD not set — required for live :7999 auth handshake" )
    return email, password


@pytest.fixture( scope="module" )
def jwt_token():
    """Login once per test module; reuse the access token."""
    email, password = _require_creds_or_skip()
    try:
        resp = requests.post(
            LOGIN_ENDPOINT,
            json={ "email": email, "password": password },
            timeout=10,
        )
    except requests.exceptions.ConnectionError:
        pytest.skip( f"Cannot reach {BASE_URL} — is the :7999 dev server running?" )
    assert resp.status_code == 200, f"Login failed: {resp.status_code} — {resp.text[ :200 ]}"
    return resp.json()[ "tokens" ][ "access_token" ]


@pytest.mark.timeout( 15 )
def test_unauthenticated_request_rejected():
    """No Authorization header → 401 (per the require_api_key_or_jwt dep)."""
    resp = requests.get( ENDPOINT, params={ "hours": 24 }, timeout=10 )
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"


@pytest.mark.timeout( 15 )
def test_authenticated_request_returns_expected_top_level_shape( jwt_token ):
    """Authenticated GET → 200 with `entries` + `since_used` + `next_cursor` keys."""
    resp = requests.get(
        ENDPOINT,
        headers={ "Authorization": f"Bearer {jwt_token}" },
        params={ "hours": 24, "limit": 50 },
        timeout=10,
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[ :300 ]}"

    body = resp.json()
    assert isinstance( body, dict )
    assert "entries"     in body, f"Missing `entries` key: {body}"
    assert "since_used"  in body, f"Missing `since_used` key: {body}"
    assert "next_cursor" in body, f"Missing `next_cursor` key: {body}"
    assert isinstance( body[ "entries" ], list )
    # next_cursor is None in v1 per design "Open follow-ups"
    assert body[ "next_cursor" ] is None


@pytest.mark.timeout( 15 )
def test_entry_shape_when_entries_present( jwt_token ):
    """If the live commons store has entries, each one carries the projected shape (AC1)."""
    resp = requests.get(
        ENDPOINT,
        headers={ "Authorization": f"Bearer {jwt_token}" },
        params={ "hours": 168, "limit": 100 },   # week — likely to find some entries
        timeout=10,
    )
    assert resp.status_code == 200

    entries = resp.json()[ "entries" ]
    for entry in entries:
        # Required fields per `_project_history_entry`
        for k in ( "ts", "topic", "topic_kind", "sender_session_id",
                   "persona_name", "persona_icon", "persona_color", "body", "metadata" ):
            assert k in entry, f"Entry missing key `{k}`: {entry}"
        assert entry[ "topic_kind" ] in { "reserved", "free-form" }, \
            f"Unexpected topic_kind: {entry[ 'topic_kind' ]}"
        assert isinstance( entry[ "metadata" ], dict )


@pytest.mark.timeout( 15 )
def test_excluded_topics_never_appear( jwt_token ):
    """Reserved topics `presence` + `system-events` are excluded per Q5 INI default."""
    resp = requests.get(
        ENDPOINT,
        headers={ "Authorization": f"Bearer {jwt_token}" },
        params={ "hours": 168, "limit": 1000 },
        timeout=10,
    )
    assert resp.status_code == 200

    bad_topics = [
        entry[ "topic" ] for entry in resp.json()[ "entries" ]
        if entry[ "topic" ] in RESERVED_EXCLUDED
    ]
    assert bad_topics == [ ], f"Excluded topics leaked into response: {bad_topics}"


@pytest.mark.timeout( 15 )
def test_entries_are_sorted_newest_first( jwt_token ):
    """Per Q7 ratification — flat reverse-chronological by `ts`."""
    resp = requests.get(
        ENDPOINT,
        headers={ "Authorization": f"Bearer {jwt_token}" },
        params={ "hours": 168, "limit": 100 },
        timeout=10,
    )
    assert resp.status_code == 200

    timestamps = [ e[ "ts" ] for e in resp.json()[ "entries" ] if e.get( "ts" ) ]
    assert timestamps == sorted( timestamps, reverse=True ), \
        "Entries are not in newest-first order"


@pytest.mark.timeout( 15 )
def test_hours_window_resolves_to_since_used( jwt_token ):
    """When `hours` is supplied, `since_used` reflects the computed cutoff (AC4)."""
    resp = requests.get(
        ENDPOINT,
        headers={ "Authorization": f"Bearer {jwt_token}" },
        params={ "hours": 1 },
        timeout=10,
    )
    assert resp.status_code == 200
    assert resp.json()[ "since_used" ] is not None, \
        "`hours` parameter must compute a `since_used` cutoff"


@pytest.mark.timeout( 15 )
def test_limit_caps_response_size( jwt_token ):
    """Caller `limit` parameter is honored (AC1 — capped at min(limit, ceiling))."""
    resp = requests.get(
        ENDPOINT,
        headers={ "Authorization": f"Bearer {jwt_token}" },
        params={ "hours": 168, "limit": 3 },
        timeout=10,
    )
    assert resp.status_code == 200
    assert len( resp.json()[ "entries" ] ) <= 3


@pytest.mark.timeout( 15 )
def test_broadcasts_topic_entries_are_deduped_by_broadcast_id( jwt_token ):
    """
    Each `broadcast_id` appears at most once in the response.

    Phase 2's `perform_fanout` writes one `broadcasts` row per recipient
    (intentional for `target_session_id` scoping). The Recent Activity
    aggregator collapses them to one admin-overview row via
    `_dedupe_broadcasts_by_id`. Asserts the wire-level invariant.
    """
    resp = requests.get(
        ENDPOINT,
        headers={ "Authorization": f"Bearer {jwt_token}" },
        params={ "hours": 168, "limit": 1000 },
        timeout=10,
    )
    assert resp.status_code == 200

    seen_ids = [ ]
    for entry in resp.json()[ "entries" ]:
        if entry[ "topic" ] != "broadcasts":
            continue
        bid = ( entry.get( "metadata" ) or { } ).get( "broadcast_id" )
        if bid:
            seen_ids.append( bid )
    assert len( seen_ids ) == len( set( seen_ids ) ), \
        f"Duplicate broadcast_id in response — dedupe regression. Got: {seen_ids}"


@pytest.mark.timeout( 15 )
def test_deduped_broadcasts_row_omits_target_session_id( jwt_token ):
    """
    The dedup'd admin-overview row strips `target_session_id` from metadata
    (the row represents the broadcast as a whole, not a single recipient slice).
    """
    resp = requests.get(
        ENDPOINT,
        headers={ "Authorization": f"Bearer {jwt_token}" },
        params={ "hours": 168, "limit": 1000 },
        timeout=10,
    )
    assert resp.status_code == 200

    for entry in resp.json()[ "entries" ]:
        if entry[ "topic" ] != "broadcasts":
            continue
        md = entry.get( "metadata" ) or { }
        if "broadcast_id" not in md:
            continue
        assert "target_session_id" not in md, \
            f"Deduped broadcasts row leaked target_session_id: {md}"


# ── Standalone runner (per project quick_smoke_test convention) ────────────


def quick_smoke_test():
    """Run all tests in this file as a standalone script."""
    import subprocess
    cmd = [
        sys.executable, "-m", "pytest", "-v", "--tb=short",
        os.path.abspath( __file__ ),
    ]
    sys.exit( subprocess.call( cmd ) )


if __name__ == "__main__":
    quick_smoke_test()
