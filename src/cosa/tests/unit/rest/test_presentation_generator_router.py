"""
Unit tests for the retired Presentation Generator router
(`cosa.rest.routers.presentation_generator`).

WHAT USED TO BE HERE. `TestDependencies`, `TestValidateSourcePath` and
`TestSubmitPresentationJob` — the queue and websocket dual-key reads, the path guard's
within-root / escape / exact-root arms, and the handler's empty-source 400, escape 403,
not-found 404, render-only-on-non-YAML 400, both success arms and the factory-None 500.

That handler is gone: `/api/presentation-generator/submit` is a tombstone naming
`/api/v2/submit`. Most of those tests have nothing to be rewritten INTO — the behaviour
did not move within this module, it moved to a door with its own suite.

THE ONE EXCEPTION IS THE PATH GUARD, and it is worth being precise about where its
coverage went rather than letting it look dropped. `validate_source_path` moved onto the
job as `presentation_generator/job.py::source_path_is_inside_the_project`, one commit
ahead of this one, and its tests moved with it to
`src/tests/unit/test_presentation_generator_job.py`. It is the only thing this door did
that nothing downstream repeated, which is why it travelled first and the tombstone waited.

Zero external dependencies — the tombstone reads no body, touches no queue and builds no
job, so there is nothing left to mock.
"""

import unittest
import asyncio
import time

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import cosa.rest.routers.presentation_generator as mod
from cosa.rest.routers.presentation_generator import submit_presentation_job
from cosa.rest.routers._retired_doors import RETIRED_DOORS, V2_SUBMIT

PATH = "/api/presentation-generator/submit"


class TestTheSubmitDoorIsRetired( unittest.TestCase ):
    """The door answers 410, at the right path, naming the right replacement."""

    def _client( self ):
        app = FastAPI()
        app.include_router( mod.router )
        return TestClient( app, raise_server_exceptions=False )

    def test_it_answers_410_and_names_the_submit_door( self ):
        response = self._client().post( PATH, json={ "source_path": "/io/deck.md" } )
        self.assertEqual( response.status_code, 410 )
        self.assertIn( V2_SUBMIT, response.json()[ "detail" ] )

    def test_it_refuses_an_unauthenticated_caller_the_same_way( self ):
        """No auth on a tombstone: a 401 reads like a credentials problem, not a retired door."""
        self.assertEqual( self._client().post( PATH, json={ } ).status_code, 410 )

    def test_it_is_mounted_once_at_the_path_the_table_names( self ):
        """
        RED ON REVERT, and this is the assertion that earns its keep. The router carries a
        prefix, so a decorator handed the FULL path would mount the door at
        /api/presentation-generator/api/presentation-generator/submit and the real path
        would answer 404 — the one answer a tombstone must never give, since 404 is exactly
        what "this route was deleted" looks like. Every handler-level test still passes when
        that happens; only a mounted-path check catches it.
        """
        paths = { route.path for route in mod.router.routes }
        self.assertEqual( paths, { PATH }, f"mounted at {paths}" )

    def test_the_table_says_this_door_retires_into_submit_not_ask( self ):
        """A presentation is work whose command is already decided, not a question."""
        self.assertEqual( RETIRED_DOORS[ PATH ], V2_SUBMIT )

    def test_the_refusal_sentence_matches_the_door_it_names( self ):
        detail = self._client().post( PATH, json={ } ).json()[ "detail" ]
        self.assertIn( "Work whose command is already decided", detail )
        self.assertNotIn( "Every question now enters through", detail )

    def test_the_handler_only_refuses( self ):
        """RED ON REVERT: give the handler a body again and it stops raising."""
        with self.assertRaises( HTTPException ) as caught:
            asyncio.run( submit_presentation_job() )
        self.assertEqual( caught.exception.status_code, 410 )

    def test_the_job_building_machinery_is_gone_from_this_module( self ):
        """
        A queue handle or a request model left behind in a module whose only POST is a
        tombstone reads as a door that was disabled rather than retired — and a Pydantic
        model no route reads is a shape a caller can still find and reasonably believe in.
        """
        for name in ( "create_agentic_job", "user_job_tracker", "get_todo_queue",
                      "get_websocket_mgr", "validate_source_path",
                      "PresentationSubmitRequest", "PresentationSubmitResponse" ):
            self.assertFalse( hasattr( mod, name ),
                              f"{name} survives in a module whose only POST is a tombstone" )

    def test_the_path_guard_still_exists_where_it_moved_to( self ):
        """
        The guard was the one thing this door did that nothing downstream repeated, so
        "it is gone from the router" must not be the whole story. It is on the job now,
        and this asserts that rather than trusting the comment above.
        """
        from cosa.agents.presentation_generator.job import source_path_is_inside_the_project
        self.assertFalse( source_path_is_inside_the_project( "../../etc/passwd" ) )
        self.assertTrue( source_path_is_inside_the_project( "/io/deck.md" ) )


def isolated_unit_test():
    """
    Run the presentation-generator router unit tests in isolation.

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
            du.print_banner( "✅ ALL PRESENTATION ROUTER TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME PRESENTATION ROUTER TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"

        return success, duration, message

    except Exception as e:
        duration  = time.time() - start_time
        error_msg = f"Unit test execution failed: {str( e )}"
        du.print_banner( f"💥 PRESENTATION ROUTER TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} Presentation router unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )
