"""
Unit tests for the mock-job router (`cosa.rest.routers.mock_job`).

The router now holds only the door-14 tombstone (`POST /submit` -> 410 naming
`/api/v2/submit`) and the untouched `GET /health` that three suites probe. The handler and
its models were deleted (row 432511fd); their behaviour lives in
`cosa.agents.test_harness.mock_submit` and is tested by
`cosa/tests/unit/agents/test_harness/test_mock_submit.py` and
`tests/unit/test_v2_submit_mock_job_through_path.py`.
"""

import asyncio
import unittest

from fastapi import HTTPException

from cosa.rest.routers.mock_job import mock_job_health, submit_mock_job


class TestMockJobTombstone( unittest.TestCase ):
    """Ensures: the retired door refuses with 410 and names its successor."""

    def test_submit_is_gone_and_names_v2_submit( self ):
        with self.assertRaises( HTTPException ) as ctx:
            asyncio.run( submit_mock_job() )
        self.assertEqual( ctx.exception.status_code, 410 )
        self.assertIn( "/api/v2/submit", ctx.exception.detail )


class TestMockJobHealth( unittest.TestCase ):
    """Ensures: health endpoint reports availability."""

    def test_health_ok( self ):
        result = asyncio.run( mock_job_health() )
        self.assertEqual( result[ "status" ], "ok" )
        self.assertTrue( result[ "available" ] )


if __name__ == "__main__":
    unittest.main()
