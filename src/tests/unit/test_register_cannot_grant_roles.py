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
