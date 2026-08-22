"""
Unit tests for the retired SWE Team router (`cosa.rest.routers.swe_team`).

WHAT USED TO BE HERE. `TestGetTodoQueue` and `TestSubmitSweTeamTask` — the dual-key
`lupin_app.main` read, the identity 400s, every optional-field arm (lead/worker model,
budget, timeout, trust mode), the scheduling and lineage stamps, and the factory-None and
push-failure 500s.

That handler is gone: `/api/swe-team/submit` is a tombstone naming `/api/v2/submit`. There
is nothing to rewrite those tests INTO — the behaviour did not move within this module, it
moved to a door with its own suite.

Zero external dependencies — the tombstone reads no body, touches no queue and builds no
job, so there is nothing left to mock.
"""

import unittest
import asyncio
import time

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import cosa.rest.routers.swe_team as mod
from cosa.rest.routers.swe_team import submit_swe_team_task
from cosa.rest.routers._retired_doors import RETIRED_DOORS, V2_SUBMIT

PATH = "/api/swe-team/submit"


class TestTheSubmitDoorIsRetired( unittest.TestCase ):
    """The door answers 410, at the right path, naming the right replacement."""

    def _client( self ):
        app = FastAPI()
        app.include_router( mod.router )
        return TestClient( app, raise_server_exceptions=False )

    def test_it_answers_410_and_names_the_submit_door( self ):
        response = self._client().post( PATH, json={ "task": "add retries" } )
        self.assertEqual( response.status_code, 410 )
        self.assertIn( V2_SUBMIT, response.json()[ "detail" ] )

    def test_it_refuses_an_unauthenticated_caller_the_same_way( self ):
        """No auth on a tombstone: a 401 reads like a credentials problem, not a retired door."""
        self.assertEqual( self._client().post( PATH, json={ } ).status_code, 410 )

    def test_it_is_mounted_once_at_the_path_the_table_names( self ):
        """
        RED ON REVERT, and the trap here is the MIRROR of the one the prefixed routers hit.
        This router carries NO prefix, so the decorator must take the FULL path. Copy the
        tail form its prefixed neighbours use and the door mounts at `/submit` while the
        real path answers 404 — the one answer a tombstone must never give, since 404 is
        exactly what "this route was deleted" looks like. Every handler-level test still
        passes when that happens; only a mounted-path check catches it.
        """
        paths = { route.path for route in mod.router.routes }
        self.assertEqual( paths, { PATH }, f"mounted at {paths}" )

    def test_the_router_still_carries_no_prefix( self ):
        """The premise the assertion above rests on, stated rather than assumed. If someone
        adds a prefix here, the full path in the decorator becomes the twice-mounted bug."""
        self.assertEqual( mod.router.prefix, "" )

    def test_the_table_says_this_door_retires_into_submit_not_ask( self ):
        self.assertEqual( RETIRED_DOORS[ PATH ], V2_SUBMIT )

    def test_the_refusal_sentence_matches_the_door_it_names( self ):
        detail = self._client().post( PATH, json={ } ).json()[ "detail" ]
        self.assertIn( "Work whose command is already decided", detail )
        self.assertNotIn( "Every question now enters through", detail )

    def test_the_handler_only_refuses( self ):
        """RED ON REVERT: give the handler a body again and it stops raising."""
        with self.assertRaises( HTTPException ) as caught:
            asyncio.run( submit_swe_team_task() )
        self.assertEqual( caught.exception.status_code, 410 )

    def test_the_job_building_machinery_is_gone_from_this_module( self ):
        for name in ( "create_agentic_job", "user_job_tracker", "get_todo_queue",
                      "SweTeamSubmitRequest", "SweTeamSubmitResponse" ):
            self.assertFalse( hasattr( mod, name ),
                              f"{name} survives in a module whose only POST is a tombstone" )

    def test_the_lineage_field_still_has_a_door_that_accepts_it( self ):
        """
        The one thing worth checking OUTSIDE this module, because this door's retirement is
        the one that could break a live rig. A monopolizing sweep's child pytest echoes the
        sweep's id_hash back as `parent_id_hash` so Gate B admits it through the monopoly
        hold; this was the last v1 door that accepted that field. If /api/v2/submit did not,
        the sweep would starve its own children for 900s and nothing here would say so.
        """
        from cosa.rest.routers.v2_ask import SubmitRequest
        self.assertIn( "parent_id_hash", SubmitRequest.model_fields )


def isolated_unit_test():
    """
    Run the swe-team router unit tests in isolation.

    Ensures:
        - Executes all TestCases and reports (success, duration, message)
    """
    import cosa.utils.util as du

    start_time = time.time()
    try:
        loader = unittest.TestLoader()
        suite  = unittest.TestSuite()
        for tc in ( TestTheSubmitDoorIsRetired, ):
            suite.addTests( loader.loadTestsFromTestCase( tc ) )
        result = unittest.TextTestRunner( verbosity=2 ).run( suite )

        duration  = time.time() - start_time
        tests_run = result.testsRun
        failures  = len( result.failures )
        errors    = len( result.errors )

        success = failures == 0 and errors == 0
        if success:
            du.print_banner( "✅ ALL SWE-TEAM ROUTER TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME SWE-TEAM ROUTER TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"

        return success, duration, message

    except Exception as e:
        duration  = time.time() - start_time
        error_msg = f"Unit test execution failed: {str( e )}"
        du.print_banner( f"💥 SWE-TEAM ROUTER TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} SWE-team router unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )
