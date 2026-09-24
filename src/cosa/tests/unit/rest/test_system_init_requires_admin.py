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
from fastapi.testclient import TestClient

# ⚠️ TWO functions in this tree are named get_current_user: `cosa.rest.auth`'s, which
# system.py's other routes use, and `cosa.rest.auth_middleware`'s, which is the one
# `require_roles` — and therefore `require_admin` — actually depends on. Overriding the
# wrong one changes nothing and every case answers 401, which reads exactly like a
# working gate. The import below is the load-bearing half of this file.
from cosa.rest.auth_middleware import get_current_user
from cosa.rest.routers.system import router


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


def isolated_unit_test():
    """
    Ensures:
        - returns True when every case in this module passes
    """
    suite  = unittest.TestLoader().loadTestsFromTestCase( TestInitRequiresAdmin )
    result = unittest.TextTestRunner( verbosity=2 ).run( suite )
    return result.wasSuccessful()


if __name__ == "__main__":
    unittest.main()
