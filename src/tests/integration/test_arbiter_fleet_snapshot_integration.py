"""
Integration tests for GET/POST /api/arbiter/fleet-snapshot — the v2.1
direct-state-visibility endpoints (arbiter design `03` §10.4, redline C2).

Authored by Mr. Radio 🦉 (Tester, SWE-Team Thread B). The unit suite
(`src/tests/unit/test_arbiter_router.py`) overrides `require_api_key_or_jwt`
with a lambda to test ROUTING in isolation. THIS suite exercises the REAL
credential against a live server + auth DB — both the X-API-Key path and the
Bearer-JWT path — the full C2 contract end to end.

VENUE: :8000 monopolize-mode, SCHEDULED ONLY. The POST mutates the live
server-singleton `arbiter_snapshot_store`, and the auth path needs a real DB
credential → this is NOT :7999-eligible and must NEVER be side-door-injected.
Submit via POST /api/test-suite/submit with a Rick-confirmed `scheduled_at`
(Tiberius coordinates the slot). Base URL via `LUPIN_TEST_BASE_URL`
(default http://localhost:8000), per the integration convention.

Auth-matrix covered (the third leg of the gate):
    GET  no-auth                 → 401 "Missing auth..."
    GET  malformed X-API-Key     → 401 "Invalid API key format"
    GET  valid X-API-Key         → 200 (cached snapshot shape)
    GET  valid Bearer JWT        → 200
    POST no-auth                 → 401
    POST valid X-API-Key (R/T)   → 200 {status:ok}; GET reflects the push
    POST valid Bearer JWT        → 200
    POST negative session_count  → 422 (Pydantic ge=0, server-side, authed)
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
ENDPOINT = f"{BASE_URL}/api/arbiter/fleet-snapshot"


# ── test_api_key fixture (replicated from the proven test_notification_auth.py,
#    so this suite is self-contained; it seeds a real service-account + API key
#    in the test DB and yields the plaintext key for X-API-Key requests). ───────
@pytest.fixture
def test_api_key( clean_test_db ):
    """Create a test API key and store its bcrypt hash in the test database."""
    api_key  = "ck_live_" + secrets.token_urlsafe( 48 )
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
            description = "Arbiter fleet-snapshot integration test key",
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


class TestArbiterFleetSnapshotAuth:
    """Full C2 credential matrix against the live server + auth DB."""

    # ── GET ──────────────────────────────────────────────────────────────────

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
        """A real seeded X-API-Key is accepted → 200 with snapshot shape."""
        r = requests.get( ENDPOINT, headers={ "X-API-Key": test_api_key[ "api_key" ] }, timeout=10 )
        assert r.status_code == 200, f"{r.status_code}: {r.text}"
        body = r.json()
        # Either an 'awaiting' placeholder or a pushed snapshot — both carry these keys.
        assert "session_count" in body and "sessions" in body

    def test_get_valid_jwt_returns_200( self, auth_headers ):
        """A real Bearer JWT (conftest auth_headers) is accepted → 200."""
        r = requests.get( ENDPOINT, headers=auth_headers, timeout=10 )
        assert r.status_code == 200, f"{r.status_code}: {r.text}"
        assert "session_count" in r.json()

    # ── POST ─────────────────────────────────────────────────────────────────

    def test_post_missing_auth_returns_401( self ):
        """POST without a credential is rejected before any mutation → 401."""
        r = requests.post( ENDPOINT, json={ "session_count": 0 }, timeout=10 )
        assert r.status_code == 401, f"{r.status_code}: {r.text}"

    def test_post_then_get_roundtrip_with_api_key( self, test_api_key ):
        """POST a known snapshot (X-API-Key), then GET reflects it (live singleton)."""
        headers = { "X-API-Key": test_api_key[ "api_key" ] }
        snap = {
            "generated_at"  : "2026-06-06T22:41:00+00:00",
            "session_count" : 2,
            "sessions"      : [
                { "session_id": "s1", "state": "working",
                  "liveness": { "bridge_age_s": 3, "verdict": "LIVE" } },
                { "session_id": "s2", "state": "idle",
                  "liveness": { "bridge_age_s": 90, "verdict": "STALE" } },
            ],
        }
        post = requests.post( ENDPOINT, json=snap, headers=headers, timeout=10 )
        assert post.status_code == 200, f"{post.status_code}: {post.text}"
        assert post.json() == { "status": "ok", "session_count": 2 }

        got = requests.get( ENDPOINT, headers=headers, timeout=10 )
        assert got.status_code == 200, f"{got.status_code}: {got.text}"
        body = got.json()
        assert body[ "session_count" ] == 2
        # state/liveness preserved orthogonally through the round-trip (C4).
        verdicts = { s[ "session_id" ]: s[ "liveness" ][ "verdict" ] for s in body[ "sessions" ] }
        assert verdicts == { "s1": "LIVE", "s2": "STALE" }

    def test_post_valid_jwt_returns_200( self, auth_headers ):
        """The Bearer-JWT path also authorizes a push → 200."""
        snap = { "generated_at": "2026-06-06T22:42:00+00:00", "session_count": 0, "sessions": [ ] }
        r = requests.post( ENDPOINT, json=snap, headers=auth_headers, timeout=10 )
        assert r.status_code == 200, f"{r.status_code}: {r.text}"
        assert r.json() == { "status": "ok", "session_count": 0 }

    def test_post_negative_session_count_returns_422( self, test_api_key ):
        """Pydantic ge=0 rejects a negative count server-side (authed) → 422."""
        r = requests.post(
            ENDPOINT,
            json    = { "session_count": -1 },
            headers = { "X-API-Key": test_api_key[ "api_key" ] },
            timeout = 10,
        )
        assert r.status_code == 422, f"{r.status_code}: {r.text}"


if __name__ == "__main__":
    import sys
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
