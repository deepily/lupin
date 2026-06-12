#!/usr/bin/env python3
"""
Unit — FCM token-registration endpoints (S6 §3.1, amended 2026-06-12).

Pins the wire contract mobile codes against:
    POST /api/fcm/register-token   { token, platform, user_email } → 200 { "status": "ok" }
    POST /api/fcm/unregister-token { token }                       → 200 { "status": "ok" }

and the binding rule: the stored user_id is the AUTHENTICATED uid, not anything
the body claims.

Venue: :7999 (pure unit — TestClient, mocked repository + DB session).
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.routers.fcm import router
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt


AUTH_UID = "uid-550e8400"


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router( router )
    app.dependency_overrides[ require_api_key_or_jwt ] = lambda: AUTH_UID
    yield TestClient( app )
    app.dependency_overrides.clear()


@pytest.fixture
def mock_repo():
    """Patch get_db + FcmTokenRepository at the router module seam."""
    repo = MagicMock()

    class _Ctx:
        def __enter__( self ):
            return MagicMock()
        def __exit__( self, *args ):
            pass

    with patch( "cosa.rest.routers.fcm.get_db", return_value=_Ctx() ), \
         patch( "cosa.rest.routers.fcm.FcmTokenRepository", return_value=repo ):
        yield repo


class TestRegisterToken:

    def test_contract_response_shape( self, client, mock_repo ):
        response = client.post( "/api/fcm/register-token", json={
            "token"      : "fcm-tok-123",
            "platform"   : "android",
            "user_email" : "rick@example.com"
        } )
        assert response.status_code == 200
        assert response.json() == { "status": "ok" }

    def test_upsert_binds_authenticated_uid( self, client, mock_repo ):
        client.post( "/api/fcm/register-token", json={
            "token"      : "fcm-tok-123",
            "platform"   : "android",
            "user_email" : "rick@example.com"
        } )
        mock_repo.upsert_token.assert_called_once_with(
            token      = "fcm-tok-123",
            user_id    = AUTH_UID,
            user_email = "rick@example.com",
            platform   = "android"
        )

    def test_platform_defaults_to_android( self, client, mock_repo ):
        response = client.post( "/api/fcm/register-token", json={
            "token"      : "fcm-tok-123",
            "user_email" : "rick@example.com"
        } )
        assert response.status_code == 200
        assert mock_repo.upsert_token.call_args.kwargs[ "platform" ] == "android"

    def test_non_android_platform_is_422( self, client, mock_repo ):
        # R5: platform is the spec-pinned enum {"android"} — iOS/APNs is out of
        # milestone scope by design, so anything else is a contract violation.
        response = client.post( "/api/fcm/register-token", json={
            "token"      : "fcm-tok-123",
            "platform"   : "ios",
            "user_email" : "rick@example.com"
        } )
        assert response.status_code == 422
        mock_repo.upsert_token.assert_not_called()

    def test_missing_token_is_422( self, client, mock_repo ):
        response = client.post( "/api/fcm/register-token", json={ "user_email": "rick@example.com" } )
        assert response.status_code == 422
        mock_repo.upsert_token.assert_not_called()

    def test_empty_token_is_422( self, client, mock_repo ):
        response = client.post( "/api/fcm/register-token", json={
            "token"      : "",
            "user_email" : "rick@example.com"
        } )
        assert response.status_code == 422

    def test_missing_user_email_is_422( self, client, mock_repo ):
        response = client.post( "/api/fcm/register-token", json={ "token": "fcm-tok-123" } )
        assert response.status_code == 422


class TestUnregisterToken:

    def test_contract_response_shape_known_token( self, client, mock_repo ):
        mock_repo.delete_token.return_value = True
        response = client.post( "/api/fcm/unregister-token", json={ "token": "fcm-tok-123" } )
        assert response.status_code == 200
        assert response.json() == { "status": "ok" }
        mock_repo.delete_token.assert_called_once_with( "fcm-tok-123" )

    def test_unknown_token_still_200( self, client, mock_repo ):
        # Best-effort logout path: idempotent by contract
        mock_repo.delete_token.return_value = False
        response = client.post( "/api/fcm/unregister-token", json={ "token": "never-seen" } )
        assert response.status_code == 200
        assert response.json() == { "status": "ok" }

    def test_missing_token_is_422( self, client, mock_repo ):
        response = client.post( "/api/fcm/unregister-token", json={} )
        assert response.status_code == 422
        mock_repo.delete_token.assert_not_called()

    def test_legacy_delete_shape_is_gone( self, client, mock_repo ):
        # The pre-amendment DELETE /api/fcm/register-token must NOT exist —
        # 405 (path exists, method doesn't) pins the switch.
        response = client.request( "DELETE", "/api/fcm/register-token", json={ "token": "x" } )
        assert response.status_code == 405


class TestAuthRequired:

    def test_register_unauthenticated_is_rejected( self ):
        app = FastAPI()
        app.include_router( router )   # NO auth override
        client = TestClient( app )
        response = client.post( "/api/fcm/register-token", json={
            "token"      : "fcm-tok-123",
            "user_email" : "rick@example.com"
        } )
        assert response.status_code in ( 401, 403 )

    def test_unregister_unauthenticated_is_rejected( self ):
        app = FastAPI()
        app.include_router( router )
        client = TestClient( app )
        response = client.post( "/api/fcm/unregister-token", json={ "token": "fcm-tok-123" } )
        assert response.status_code in ( 401, 403 )


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
