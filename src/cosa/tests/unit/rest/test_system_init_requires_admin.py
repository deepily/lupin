"""
`GET /api/init` is admin-only — asserted through the ROUTE, not the function.

Rows 977eaaf2 / f9e71d8e. The endpoint hot-swaps the active config block and the
database connection of a running server, and until 2026-09-23 it carried no auth
dependency at all.

🔴 WHY THIS FILE EXISTS SEPARATELY FROM test_system_router.py: every existing test
of this endpoint calls `await init( ... )` DIRECTLY. A direct call bypasses FastAPI's
dependency resolution entirely, so it cannot see whether the route is gated — the
whole suite stayed green through the ungated years and would stay green if the gate
were deleted tomorrow. These cases drive the mounted app with a TestClient, which is
the only layer at which the defect was ever visible.

Venue: :7999 (in-process TestClient, no server, no state mutation).
"""

import unittest

from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

# ⚠️ TWO functions in this tree are named get_current_user: `cosa.rest.auth`'s, which
# system.py's other routes use, and `cosa.rest.auth_middleware`'s, which is the one
# `require_roles` — and therefore `require_admin` — actually depends on. Overriding the
# wrong one changes nothing and every case answers 401, which reads exactly like a
# working gate. The import below is the load-bearing half of this file.
from cosa.rest.auth_middleware import get_current_user
from cosa.rest.routers.system import router
import cosa.utils.util as cu


def _client( user=None ):
    """
    Mount the system router and return a client speaking as `user`.

    Requires:
        - user is a dict shaped like get_current_user's return, or None

    Ensures:
        - None leaves the real dependency in place (an unauthenticated caller)
        - a dict overrides it, standing in for a decoded JWT with those roles
    """
    app = FastAPI()
    app.include_router( router )
    if user is not None:
        app.dependency_overrides[ get_current_user ] = lambda: user
    return TestClient( app, raise_server_exceptions=False )


class TestInitRequiresAdmin( unittest.TestCase ):
    """
    Ensures:
        - an anonymous caller is refused
        - an authenticated non-admin is refused with 403
        - an admin is let through the gate
    """

    def test_anonymous_caller_is_refused( self ):
        """Ensures: no credentials means the config swap never runs."""
        response = _client().get( "/api/init" )
        self.assertIn( response.status_code, ( 401, 403 ) )

    def test_authenticated_non_admin_is_forbidden( self ):
        """Ensures: a valid token without the admin role gets 403, not 200."""
        response = _client( { "uid": "u-1", "email": "user@example.com", "roles": [ "user" ] } ).get( "/api/init" )
        self.assertEqual( response.status_code, 403 )
        self.assertIn( "admin", response.json()[ "detail" ] )

    def test_non_admin_is_refused_even_with_a_config_block_id( self ):
        """
        Ensures: the query parameter that swaps the DB connection is refused too.

        The parameter is the dangerous half of this endpoint — it is what changes
        which database a running server talks to.
        """
        response = _client( { "uid": "u-1", "roles": [ "user" ] } ).get(
            "/api/init", params={ "config_block_id": "Lupin: Testing" }
        )
        self.assertEqual( response.status_code, 403 )

    def test_admin_passes_the_gate( self ):
        """
        Ensures: an admin is NOT refused.

        The assertion is deliberately about the gate and not the body: `init()`
        catches everything and reports its own failure in a 200 payload, so the
        status code is what distinguishes "refused at the door" from "ran".
        """
        response = _client( { "uid": "admin-1", "roles": [ "admin" ] } ).get( "/api/init" )
        self.assertNotIn( response.status_code, ( 401, 403 ) )


def _init_route():
    """
    Return the mounted APIRoute for `/api/init`.

    Ensures:
        - fails loudly if the path is absent or registered more than once, so a
          rename cannot turn these guards into a silent no-op
    """
    matches = [ r for r in router.routes if isinstance( r, APIRoute ) and r.path == "/api/init" ]
    assert len( matches ) == 1, f"expected exactly one /api/init route, found {len( matches )}"
    return matches[ 0 ]


def _route_is_auth_gated( route ):
    """
    Walk the route's dependency tree and report whether auth is reached.

    Requires:
        - route is a mounted FastAPI APIRoute

    Ensures:
        - returns True iff some dependency, at any depth, resolves to
          `cosa.rest.auth_middleware.get_current_user`

    🔴 THE PREDICATE IS THE MECHANISM, NOT A NAME. `require_admin` is not its own
    function — it is `require_roles( [ "admin" ] )`, whose returned closure is called
    `check_roles`. Asserting on that spelling would pass a rename that removed the
    gate, and fail a rename that kept it. What actually gates the route is that
    auth_middleware's `get_current_user` is reached, so that is what this asks.
    """
    stack = list( route.dependant.dependencies )
    while stack:
        dep = stack.pop()
        if dep.call is get_current_user: return True
        stack.extend( dep.dependencies )
    return False


class TestInitGateIsVisibleAndDocumented( unittest.TestCase ):
    """
    The gate exists in three places a reader consults, and they must agree.

    Ensures:
        - the mounted route reaches auth (the gate itself)
        - the OpenAPI schema declares 401/403, so `/docs` shows the gate
        - the hand-written reference table does not still call the route Public

    Rows 977eaaf2 / f9e71d8e. These are a SEPARATE axis from the class above: those
    cases drive the endpoint and read status codes; these ask what the route and its
    published description claim about themselves. A gate that works while every
    document describing it says "Public" is how the next reader concludes there is
    no gate and stops looking.
    """

    def test_the_route_reaches_auth( self ):
        """Ensures: /api/init is gated — the fact every assertion below is derived from."""
        self.assertTrue(
            _route_is_auth_gated( _init_route() ),
            "/api/init no longer reaches get_current_user — the admin gate is gone"
        )

    def test_openapi_declares_the_refusals( self ):
        """
        Ensures: `/docs` shows 401 and 403 for this route.

        🔴 WHY THIS IS NOT REDUNDANT WITH THE GATE ITSELF. `require_admin` takes the
        Authorization header as an ordinary dependency, so it contributes NO security
        scheme and NO 401/403 to the generated schema. Before these `responses` were
        declared the spec showed only 200 and 422 — a gated route that published
        itself as being exactly as open as it was before the fix, to the surface
        CLAUDE.md names as the authoritative API reference.
        """
        app = FastAPI()
        app.include_router( router )
        declared = app.openapi()[ "paths" ][ "/api/init" ][ "get" ][ "responses" ]
        self.assertIn( "401", declared )
        self.assertIn( "403", declared )

    def test_the_reference_table_agrees_with_the_route( self ):
        """
        Ensures: rest-api-reference.md's Auth column for /api/init is not `Public`.

        The expectation is DERIVED from the route rather than restated: this case asks
        `_route_is_auth_gated` first and only then requires the doc to agree. Two
        pieces of code deciding one rule independently agree until they do not.
        """
        gated = _route_is_auth_gated( _init_route() )

        path = cu.get_project_root() + "/src/docs/rest-api-reference.md"
        with open( path, encoding="utf-8" ) as handle:
            rows = [ line for line in handle if "`/api/init`" in line and line.lstrip().startswith( "|" ) ]

        self.assertEqual( len( rows ), 1, f"expected one /api/init row in {path}, found {len( rows )}" )
        auth_column = rows[ 0 ].split( "|" )[ 3 ].strip()

        if gated:
            self.assertNotEqual(
                auth_column, "Public",
                "the route is auth-gated but rest-api-reference.md still advertises it as Public"
            )
        else:
            self.assertEqual(
                auth_column, "Public",
                "the route is NOT gated but the reference table claims it is — the doc is the stale half"
            )


def isolated_unit_test():
    """
    Ensures:
        - returns True when every case in this module passes
    """
    loader = unittest.TestLoader()
    suite  = unittest.TestSuite( [
        loader.loadTestsFromTestCase( TestInitRequiresAdmin ),
        loader.loadTestsFromTestCase( TestInitGateIsVisibleAndDocumented )
    ] )
    result = unittest.TextTestRunner( verbosity=2 ).run( suite )
    return result.wasSuccessful()


if __name__ == "__main__":
    unittest.main()
