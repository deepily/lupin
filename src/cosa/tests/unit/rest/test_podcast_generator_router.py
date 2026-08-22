"""
Unit tests for the retired Podcast Generator router (`cosa.rest.routers.podcast_generator`).

WHAT USED TO BE HERE, and it was the largest router suite of the eight: the queue and
websocket dual-key reads, `is_research_path`, `validate_source_path`,
`match_research_docs`, `get_user_document_selection`, and `submit_podcast_job` across both
flows — direct path and description, the expeditor branch and the legacy resolver branch,
the cancelled path, the no-matches path, and the speculative job card.

That handler is gone: `/api/podcast-generator/submit` is a tombstone naming `/api/v2/ask`.
There is nothing to rewrite those tests INTO — the behaviour did not move within this
module, it moved to a door with its own suite, where the Runtime Argument Expeditor does
the document resolution and the question-asking this handler used to do itself.

WHY `ask` AND NOT `submit`, said here too because a reader landing on this file will ask
it: the description flow held a CONVERSATION and could end "cancelled". That is what `ask`
does and what `submit` refuses to do by design.

Zero external dependencies — the tombstone reads no body, touches no queue and builds no
job, so there is nothing left to mock.
"""

import unittest
import asyncio
import time

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import cosa.rest.routers.podcast_generator as mod
from cosa.rest.routers.podcast_generator import submit_podcast_job
from cosa.rest.routers._retired_doors import RETIRED_DOORS, V2_ASK, V2_SUBMIT

PATH = "/api/podcast-generator/submit"


class TestTheSubmitDoorIsRetired( unittest.TestCase ):
    """The door answers 410, at the right path, naming the right replacement."""

    def _client( self ):
        app = FastAPI()
        app.include_router( mod.router )
        return TestClient( app, raise_server_exceptions=False )

    def test_it_answers_410_and_names_the_ask_door( self ):
        response = self._client().post( PATH, json={ "research_source": "/io/paper.md" } )
        self.assertEqual( response.status_code, 410 )
        self.assertIn( V2_ASK, response.json()[ "detail" ] )

    def test_it_refuses_an_unauthenticated_caller_the_same_way( self ):
        """No auth on a tombstone: a 401 reads like a credentials problem, not a retired door."""
        self.assertEqual( self._client().post( PATH, json={ } ).status_code, 410 )

    def test_it_is_mounted_once_at_the_path_the_table_names( self ):
        """
        RED ON REVERT. The router carries a prefix, so a decorator handed the FULL path
        would mount the door at /api/podcast-generator/api/podcast-generator/submit and the
        real path would answer 404 — the one answer a tombstone must never give, since 404
        is exactly what "this route was deleted" looks like. Every handler-level test still
        passes when that happens; only a mounted-path check catches it.
        """
        paths = { route.path for route in mod.router.routes }
        self.assertEqual( paths, { PATH }, f"mounted at {paths}" )

    def test_this_is_the_one_door_that_retires_into_ask_not_submit( self ):
        """
        THE ASSERTION THIS FILE EXISTS FOR. Every other door that queued a job points at
        `submit`. This one points at `ask`, because its description flow asked the user
        questions and could answer "cancelled" — behaviour `submit` refuses by design.
        Flip this row to V2_SUBMIT and the door starts telling callers to use the one door
        that cannot do what it did.
        """
        self.assertEqual( RETIRED_DOORS[ PATH ], V2_ASK )
        self.assertNotEqual( RETIRED_DOORS[ PATH ], V2_SUBMIT )

    def test_the_refusal_sentence_matches_the_door_it_names( self ):
        detail = self._client().post( PATH, json={ } ).json()[ "detail" ]
        self.assertIn( "Every question now enters through", detail )
        self.assertNotIn( "Work whose command is already decided", detail )

    def test_the_handler_only_refuses( self ):
        """RED ON REVERT: give the handler a body again and it stops raising."""
        with self.assertRaises( HTTPException ) as caught:
            asyncio.run( submit_podcast_job() )
        self.assertEqual( caught.exception.status_code, 410 )

    def test_the_job_building_and_matching_machinery_is_gone_from_this_module( self ):
        """
        A queue handle, a request model or a half-used fuzzy matcher left behind in a
        module whose only POST is a tombstone reads as a door that was disabled rather than
        retired — and a Pydantic model no route reads is a shape a caller can still find and
        reasonably believe in.
        """
        for name in ( "create_agentic_job", "user_job_tracker", "get_todo_queue",
                      "get_websocket_mgr", "is_research_path", "validate_source_path",
                      "match_research_docs", "get_user_document_selection",
                      "PodcastSubmitRequest", "PodcastSubmitResponse",
                      "PodcastMatchingResponse" ):
            self.assertFalse( hasattr( mod, name ),
                              f"{name} survives in a module whose only POST is a tombstone" )

    def test_the_dead_ini_flag_is_gone_too( self ):
        """
        `podcast card uses runtime argument expeditor` chose which resolver this handler
        used. This module was its only reader, so with the handler gone the key reads
        nothing. A configuration key that no longer changes any behaviour is worse than no
        key at all: someone will flip it and conclude the system ignored them.
        """
        import cosa.utils.util as cu
        for name in ( "lupin-app.ini", "lupin-app-splainer.ini" ):
            text = open( f"{cu.get_project_root()}/src/conf/{name}" ).read()
            self.assertNotIn( "podcast card uses runtime argument expeditor", text, name )


def isolated_unit_test():
    """
    Run the podcast-generator router unit tests in isolation.

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
            du.print_banner( "✅ ALL PODCAST ROUTER TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME PODCAST ROUTER TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"

        return success, duration, message

    except Exception as e:
        duration  = time.time() - start_time
        error_msg = f"Unit test execution failed: {str( e )}"
        du.print_banner( f"💥 PODCAST ROUTER TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} Podcast router unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )
