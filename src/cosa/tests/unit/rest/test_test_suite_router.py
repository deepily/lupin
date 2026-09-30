"""
The test-suite router is a tombstone (row a3c59f2d): POST /api/test-suite/submit answers 410
naming /api/v2/submit. The handler's behaviour moved to the factory's test-suite builder and
is tested through the v2 door (tests/unit/test_v2_submit_test_suite_through_path.py and the
guards for suite names, pytest_args and the timeout budget).
"""

import asyncio
import unittest

from fastapi import HTTPException

from cosa.rest.routers.test_suite import router, submit_test_suite


class TestTestSuiteTombstone( unittest.TestCase ):

    def test_submit_is_gone_and_names_v2_submit( self ):
        with self.assertRaises( HTTPException ) as ctx:
            asyncio.run( submit_test_suite() )
        self.assertEqual( ctx.exception.status_code, 410 )
        self.assertIn( "/api/v2/submit", ctx.exception.detail )

    def test_the_route_is_registered_as_deprecated_post( self ):
        route = [ r for r in router.routes if r.path == "/api/test-suite/submit" ][ 0 ]
        self.assertEqual( route.methods, { "POST" } )
        self.assertTrue( route.deprecated )


if __name__ == "__main__":
    unittest.main()
