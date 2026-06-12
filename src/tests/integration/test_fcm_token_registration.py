"""
Integration — FCM token registration round-trip + durable rehydration (AC-S6.1).

Runs against the live test server (:8000, scheduled via POST /api/test-suite/submit).

AC-S6.1 (F-S6-S2-1a, mechanism per F-S6-S3-1): register a token through the
ENDPOINT (the server process writes it), then RE-INSTANTIATE the registry
component — a brand-new FcmTokenRepository on a brand-new session in THIS test
process (zero in-memory carryover from the writer; stronger than the AC's
fresh-instance minimum, this is cross-process) — and prove the token still
resolves for the wake trigger. A write-through-cache-never-read-back
implementation fails this: the reader here shares no memory with the writer.

Venue: :8000 (mutates fcm_tokens rows in lupin_db_test; cleaned up per test).
"""

import os

import pytest
import requests

from tests.integration.conftest import BASE_URL


def _fresh_repository_session():
    """Open a brand-new DB session + repository — the AC-S6.1 rehydration reader."""
    from cosa.rest.db.database import get_db
    from cosa.rest.db.repositories.fcm_token_repository import FcmTokenRepository
    return get_db, FcmTokenRepository


TEST_TOKEN = "itest-fcm-token-ac-s6-1"


@pytest.fixture
def registered_token( auth_headers ):
    """Register the test token via the endpoint; always unregister afterwards."""
    response = requests.post(
        f"{BASE_URL}/api/fcm/register-token",
        json    = { "token": TEST_TOKEN, "platform": "android", "user_email": "itest@example.com" },
        headers = auth_headers
    )
    assert response.status_code == 200
    yield TEST_TOKEN
    requests.post(
        f"{BASE_URL}/api/fcm/unregister-token",
        json    = { "token": TEST_TOKEN },
        headers = auth_headers
    )


class TestRegisterRoundTrip:

    def test_register_returns_contract_shape( self, auth_headers, registered_token ):
        # Re-register (idempotent upsert) — still the contract response
        response = requests.post(
            f"{BASE_URL}/api/fcm/register-token",
            json    = { "token": registered_token, "platform": "android", "user_email": "itest@example.com" },
            headers = auth_headers
        )
        assert response.status_code == 200
        assert response.json() == { "status": "ok" }

    def test_rehydration_from_durable_store( self, create_test_user, registered_token ):
        """
        AC-S6.1 core: the SERVER process wrote the row; a FRESH repository on a
        FRESH session in THIS process resolves it. Zero in-memory carryover.
        """
        get_db, FcmTokenRepository = _fresh_repository_session()
        with get_db() as session:
            repo   = FcmTokenRepository( session )
            tokens = repo.get_tokens_for_user( create_test_user[ "user_id" ] )
        assert registered_token in tokens

    def test_upsert_never_duplicates( self, auth_headers, create_test_user, registered_token ):
        for _ in range( 3 ):
            requests.post(
                f"{BASE_URL}/api/fcm/register-token",
                json    = { "token": registered_token, "platform": "android", "user_email": "itest@example.com" },
                headers = auth_headers
            )
        get_db, FcmTokenRepository = _fresh_repository_session()
        with get_db() as session:
            tokens = FcmTokenRepository( session ).get_tokens_for_user( create_test_user[ "user_id" ] )
        assert tokens.count( registered_token ) == 1

    def test_unregister_removes_and_is_idempotent( self, auth_headers, create_test_user, registered_token ):
        for _ in range( 2 ):   # second call exercises the unknown-token 200 arm
            response = requests.post(
                f"{BASE_URL}/api/fcm/unregister-token",
                json    = { "token": registered_token },
                headers = auth_headers
            )
            assert response.status_code == 200
            assert response.json() == { "status": "ok" }

        get_db, FcmTokenRepository = _fresh_repository_session()
        with get_db() as session:
            tokens = FcmTokenRepository( session ).get_tokens_for_user( create_test_user[ "user_id" ] )
        assert registered_token not in tokens


class TestAuthGate:

    def test_register_requires_auth( self ):
        response = requests.post(
            f"{BASE_URL}/api/fcm/register-token",
            json={ "token": "no-auth-token", "platform": "android", "user_email": "x@example.com" }
        )
        assert response.status_code in ( 401, 403 )

    def test_unregister_requires_auth( self ):
        response = requests.post(
            f"{BASE_URL}/api/fcm/unregister-token",
            json={ "token": "no-auth-token" }
        )
        assert response.status_code in ( 401, 403 )
