"""
Auth guard for POST /api/system/bounce (row 1b4211ac R2 / commit 5f40de15).

The endpoint drops a trigger file the host watcher turns into a real :7999 restart, so
an UNAUTHENTICATED caller must never reach it — otherwise anyone could bounce the fleet's
dev server at will. The commit names a 401 branch; the existing test_system_bounce.py
proves the 409/503/202 arms but calls the endpoint with a FAKE current_user
(`bounce_dev_server( current_user={...} )`), so the auth dependency is bypassed and the
401 is never exercised. This closes that gap by driving the REAL dependency chain
(HTTPBearerWith401 → get_current_user) through a TestClient.

The code is 401, NOT FastAPI's default 403 for a missing Bearer: get_current_user is
guarded by the custom `HTTPBearerWith401` scheme (auth.py), which the commit message
explicitly claims. This test proves that claim.

Red-proof (documented — production not editable here, Clayton/Rick own the file): remove
`Depends(get_current_user)` from the endpoint and an unauthenticated POST reaches the
body → 503 (no watcher) or 202, never 401 → both asserts below redden.

Test file only. Unauth is rejected BEFORE any trigger-drop side effect (the security
dependency runs first), so no state is mutated — :7999-eligible.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cosa.rest.routers import system


@pytest.fixture( scope="module" )
def client():
    app = FastAPI()
    app.include_router( system.router )
    return TestClient( app )


def test_bounce_without_auth_is_401_not_404( client ):
    """
    No Authorization header → 401 from HTTPBearerWith401, BEFORE any trigger is written.

    401 (not 404) is the load-bearing distinction: it proves the route EXISTS and is
    auth-guarded. A 404 would also "not be 200" but would prove nothing about auth — so
    the assertion names both the code and, via WWW-Authenticate, that it came from the
    Bearer scheme.
    """
    resp = client.post( "/api/system/bounce" )
    assert resp.status_code == 401, (
        f"unauthenticated bounce must be 401 (route exists AND is auth-guarded), "
        f"got {resp.status_code}: {resp.text}"
    )
    assert resp.headers.get( "WWW-Authenticate" ) == "Bearer", resp.headers


def test_bounce_with_malformed_auth_is_401( client ):
    """A non-Bearer Authorization header is rejected 401 too (credentials resolve to None)."""
    resp = client.post( "/api/system/bounce", headers={ "Authorization": "NotBearer nope" } )
    assert resp.status_code == 401, resp.text
