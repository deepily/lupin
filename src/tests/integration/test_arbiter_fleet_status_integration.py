"""
Integration tests for GET /api/arbiter/fleet-state — the Fleet-Status P1
backend enrichment contract (role/manager per session row + the top-level
app_timezone proxy field; built commit 2a8cfb6, Fleet-Status table design P0).

Authored by Krishna 🦚 (for Tiberius 👑; black-box — no P1 internals consumed).
The unit suite (`src/tests/unit/test_arbiter_router.py`) covers the proxy
routing with the :8001 pull monkeypatched; THIS suite exercises the REAL
credential against a live server + auth DB AND the real :8001 upstream, so the
enrichment is asserted on genuinely-published fleet rows.

VENUE: :8000 monopolize-mode, SCHEDULED ONLY. The auth path needs a real DB
credential (the seeded test_api_key mutates the test DB) → NOT :7999-eligible
and must NEVER be side-door-injected. Submit via POST /api/test-suite/submit.
Base URL via `LUPIN_TEST_BASE_URL` (default http://localhost:8000), per the
integration convention.

LIVE-FLEET CAVEAT: session rows reflect whatever CC fleet is alive at run time
(possibly zero rows at an off-peak slot). The row-shape assertions therefore
quantify over EVERY published row rather than expecting specific personas; an
unreachable/awaiting upstream is asserted away loudly as a failed deploy
precondition (this suite verifies the LIVE surface).
"""

import os

import pytest
import requests
import bcrypt
import secrets
import uuid

from cosa.rest.db.database import get_db
from cosa.rest.db.repositories import UserRepository, ApiKeyRepository


BASE_URL = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:8000" )
ENDPOINT = f"{BASE_URL}/api/arbiter/fleet-state"


# ── test_api_key fixture (replicated from the proven test_notification_auth.py /
#    test_arbiter_fleet_snapshot_integration.py pattern, so this suite is
#    self-contained; seeds a real service-account + API key in the test DB). ────
@pytest.fixture
def test_api_key( clean_test_db ):
    """Create a test API key and store its bcrypt hash in the test database."""
    api_key   = "ck_live_" + secrets.token_urlsafe( 48 )
    key_bytes = api_key.encode( "utf-8" )
    salt      = bcrypt.gensalt( rounds=12 )
    key_hash  = bcrypt.hashpw( key_bytes, salt ).decode( "utf-8" )

    email = f"test-{uuid.uuid4()}@test.com"

    with get_db() as session:
        user_repo = UserRepository( session )
        user = user_repo.create_user(
            email         = email,
            password_hash = "dummy_hash",
            roles         = [ "service_account" ],
        )
        user.email_verified = True
        user.is_active      = True

        api_key_repo = ApiKeyRepository( session )
        api_key_obj  = api_key_repo.create_key(
            user_id     = user.id,
            key_hash    = key_hash,
            description = "Arbiter fleet-status integration test key",
        )
        key_id  = str( api_key_obj.id )
        user_id = str( user.id )

    yield {
        "api_key" : api_key,
        "user_id" : user_id,
        "key_id"  : key_id,
        "email"   : email,
    }

    # Explicit teardown (clean_test_db also drops tables; kept for clarity).
    with get_db() as session:
        ApiKeyRepository( session ).delete( uuid.UUID( key_id ) )
        UserRepository( session ).delete( uuid.UUID( user_id ) )


def _get_live_composite( headers ):
    """
    GET the composite and FAIL LOUDLY when the upstream watcher is not live.

    The {status:"unreachable"} envelope is correct API behavior for a downed
    :8001, but a FAILED deploy precondition here — this suite verifies the live
    Fleet-Status surface, so we assert it away with a diagnostic.
    """
    r = requests.get( ENDPOINT, headers=headers, timeout=10 )
    assert r.status_code == 200, f"{r.status_code}: {r.text}"
    body = r.json()
    assert body.get( "status" ) != "unreachable", \
        f"lupin-arbiter-app :8001 unreachable — deploy precondition failed: {body}"
    return body


class TestFleetStateAuth:
    """The credential matrix against the live server + auth DB (C2 contract)."""

    def test_get_missing_auth_returns_401( self ):
        """No credential → 401 with the canonical 'Missing auth' message."""
        r = requests.get( ENDPOINT, timeout=10 )
        assert r.status_code == 401, f"{r.status_code}: {r.text}"
        assert "Missing auth" in r.json()[ "detail" ]

    def test_get_malformed_api_key_returns_401( self ):
        """A non-ck_live_ key fails the format regex → 401."""
        r = requests.get( ENDPOINT, headers={ "X-API-Key": "not-a-valid-key" }, timeout=10 )
        assert r.status_code == 401, f"{r.status_code}: {r.text}"
        assert "Invalid API key format" in r.json()[ "detail" ]

    def test_get_valid_api_key_returns_200( self, test_api_key ):
        """A real seeded X-API-Key is accepted → 200."""
        r = requests.get( ENDPOINT, headers={ "X-API-Key": test_api_key[ "api_key" ] }, timeout=10 )
        assert r.status_code == 200, f"{r.status_code}: {r.text}"

    def test_get_valid_jwt_returns_200( self, auth_headers ):
        """A real Bearer JWT (conftest auth_headers) is accepted → 200."""
        r = requests.get( ENDPOINT, headers=auth_headers, timeout=10 )
        assert r.status_code == 200, f"{r.status_code}: {r.text}"


class TestFleetStatusEnrichment:
    """The Fleet-Status P1 contract on the live composite (table design §4)."""

    def test_top_level_app_timezone_present( self, test_api_key ):
        """The ONE :7999-local injection: a non-empty IANA zone string (§4.1)."""
        body = _get_live_composite( { "X-API-Key": test_api_key[ "api_key" ] } )
        assert isinstance( body.get( "app_timezone" ), str ) and body[ "app_timezone" ], body.get( "app_timezone" )
        # IANA zones are Region/City-shaped (e.g. America/New_York)
        assert "/" in body[ "app_timezone" ], body[ "app_timezone" ]

    def test_every_session_row_carries_role_and_manager_keys( self, test_api_key ):
        """
        Fleet-Status P1 enrichment: EVERY published session row carries the
        `role` and `manager` keys (key PRESENCE is the contract — values are
        fleet-dependent and may be null for an unmanaged/unclassified session).
        """
        body          = _get_live_composite( { "X-API-Key": test_api_key[ "api_key" ] } )
        fleet_arbiter = body[ "fleet_arbiter" ]
        sessions      = fleet_arbiter.get( "sessions", [ ] )
        for row in sessions:
            assert "role" in row, f"session row lacks 'role': {row}"
            assert "manager" in row, f"session row lacks 'manager': {row}"

    def test_session_rows_consistent_with_session_count( self, test_api_key ):
        """The published session_count matches the rows actually shipped (when live)."""
        body          = _get_live_composite( { "X-API-Key": test_api_key[ "api_key" ] } )
        fleet_arbiter = body[ "fleet_arbiter" ]
        if fleet_arbiter.get( "status" ) == "awaiting":
            # cold arbiter (just restarted, first tick pending) — placeholder is self-consistent too
            assert fleet_arbiter[ "session_count" ] == 0 and fleet_arbiter[ "sessions" ] == [ ]
        else:
            assert fleet_arbiter[ "session_count" ] == len( fleet_arbiter[ "sessions" ] )


if __name__ == "__main__":
    import sys
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
