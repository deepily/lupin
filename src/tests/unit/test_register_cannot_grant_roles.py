"""
POST /auth/register cannot grant a role (row e0fa0598, security).

THE HOLE: /auth/register takes no credential, and it used to pass the request's
`roles` straight to create_user. Both admin gates read roles from the database, so an
anonymous `{"roles": ["admin"]}` produced a full admin on REST and on the WebSocket.

These tests enter the way the attack would: an HTTP POST, no credential, through the
real auth router mounted on a FastAPI app. Only the database layer (create_user and the
lookups after it) is replaced, so the route, the request model and the refusal are the
real ones.
"""
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cosa.rest.routers import auth as auth_router


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router( auth_router.router )
    return TestClient( app )


def _post( client, **body ):
    body.setdefault( "email", "anyone@example.com" )
    body.setdefault( "password", "Str0ng!Passw0rd" )
    return client.post( "/auth/register", json=body )


@pytest.mark.parametrize( "roles", [ [ "admin" ], [ "user", "admin" ], [ "ADMIN" ], [ "service_account" ] ] )
def test_an_anonymous_caller_cannot_ask_for_a_role( client, roles ):
    with patch( "cosa.rest.routers.auth.create_user" ) as create:
        r = _post( client, roles=roles )
    assert r.status_code == 403, r.text
    create.assert_not_called()


@pytest.mark.parametrize( "extra", [ {}, { "roles": [ "user" ] }, { "roles": None } ] )
def test_a_plain_registration_still_reaches_create_user_as_a_user( client, extra ):
    """
    THE CONTROL. A route that refused everything would pass the test above. Here the
    create is stubbed to fail, so the request stops at a 400 right after it — which
    proves the refusal did not fire and shows exactly what create_user was handed.
    """
    with patch( "cosa.rest.routers.auth.create_user", return_value=( False, "stop here", None ) ) as create:
        r = _post( client, **extra )
    assert r.status_code == 400, r.text
    assert create.call_args.kwargs[ "roles" ] == [ "user" ]


# ---- Audit trail (row f0017421) -------------------------------------------------------

UID = "6f1b2c3d-1111-4222-8333-444455556666"
USER_ROW = {
    "id": UID, "email": "anyone@example.com", "roles": [ "user" ], "email_verified": False,
    "is_active": True, "created_at": "2026-09-29T00:00:00", "last_login_at": None
}

TOKENS = { "access_token": "a", "refresh_token": "r", "token_type": "bearer", "expires_in": 900 }


def test_a_refused_register_writes_the_refusal_event_and_creates_no_user( client ):
    with patch( "cosa.rest.routers.auth.create_user" ) as create, \
         patch( "cosa.rest.routers.auth.log_auth_event" ) as audit:
        r = _post( client, roles=[ "user", "admin" ] )
    assert r.status_code == 403, r.text
    create.assert_not_called()
    audit.assert_called_once()
    kw = audit.call_args.kwargs
    assert kw[ "event_type" ] == "user_self_register_refused"
    assert kw[ "email" ]      == "anyone@example.com"
    assert kw[ "ip_address" ] == "testclient"
    assert kw[ "success" ] is False
    assert "['admin']" in kw[ "details" ]


def test_a_successful_register_writes_user_self_register_with_email_roles_and_ip( client ):
    with patch( "cosa.rest.routers.auth.create_user", return_value=( True, "ok", UID ) ), \
         patch( "cosa.rest.routers.auth.get_user_by_id", return_value=USER_ROW ), \
         patch( "cosa.rest.routers.auth._create_token_response", return_value=TOKENS ), \
         patch( "cosa.rest.routers.auth.log_auth_event" ) as audit:
        r = _post( client )
    assert r.status_code == 201, r.text
    audit.assert_called_once()
    kw = audit.call_args.kwargs
    assert kw[ "event_type" ] == "user_self_register"
    assert kw[ "user_id" ]    == UID
    assert kw[ "email" ]      == "anyone@example.com"
    assert kw[ "ip_address" ] == "testclient"
    assert kw[ "success" ] is True
    assert "['user']" in kw[ "details" ]


def test_a_failed_create_writes_no_event( client ):
    with patch( "cosa.rest.routers.auth.create_user", return_value=( False, "dup", None ) ), \
         patch( "cosa.rest.routers.auth.log_auth_event" ) as audit:
        r = _post( client )
    assert r.status_code == 400
    audit.assert_not_called()


def test_a_missing_client_is_recorded_as_unknown():
    from types import SimpleNamespace
    import asyncio
    from cosa.rest.auth_models import RegisterRequest
    req = RegisterRequest( email="anyone@example.com", password="Str0ng!Passw0rd" )
    with patch( "cosa.rest.routers.auth.create_user", return_value=( True, "ok", UID ) ), \
         patch( "cosa.rest.routers.auth.get_user_by_id", return_value=USER_ROW ), \
         patch( "cosa.rest.routers.auth._create_token_response", return_value=TOKENS ), \
         patch( "cosa.rest.routers.auth.log_auth_event" ) as audit:
        asyncio.run( auth_router.register( req, SimpleNamespace( client=None ) ) )
    assert audit.call_args.kwargs[ "ip_address" ] == "unknown"


def test_a_created_user_that_cannot_be_read_back_is_a_500_but_still_audited( client ):
    with patch( "cosa.rest.routers.auth.create_user", return_value=( True, "ok", UID ) ), \
         patch( "cosa.rest.routers.auth.get_user_by_id", return_value=None ), \
         patch( "cosa.rest.routers.auth.log_auth_event" ) as audit:
        r = _post( client )
    assert r.status_code == 500
    audit.assert_called_once()
    assert audit.call_args.kwargs[ "event_type" ] == "user_self_register"
    assert audit.call_args.kwargs[ "user_id" ]    == UID


def test_a_created_user_whose_token_creation_fails_is_still_audited( client ):
    with patch( "cosa.rest.routers.auth.create_user", return_value=( True, "ok", UID ) ), \
         patch( "cosa.rest.routers.auth.get_user_by_id", return_value=USER_ROW ), \
         patch( "cosa.rest.routers.auth._create_token_response", side_effect=RuntimeError( "tokens down" ) ), \
         patch( "cosa.rest.routers.auth.log_auth_event" ) as audit:
        with pytest.raises( RuntimeError ):
            _post( client )
    audit.assert_called_once()
    assert audit.call_args.kwargs[ "event_type" ] == "user_self_register"
