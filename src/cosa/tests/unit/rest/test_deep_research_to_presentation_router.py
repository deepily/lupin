"""
Unit tests for the retired Deep Research to Presentation router (`cosa.rest.routers.deep_research_to_presentation`).

WHAT THIS FILE USED TO TEST, AND WHY IT DOES NOT ANY MORE. It covered `submit_research_to_presentation` —
the identity 400s, the session-id fallback, the success arms for every optional field,
the lineage stamp, the factory-None and push-failure 500s. That handler is gone:
`/api/deep-research-to-presentation/submit` is a tombstone answering 410 and naming `/api/v2/submit`, so every one of those
tests exercised code that no longer exists. They are not rewritten into equivalents here,
because there is nothing to rewrite them INTO — the behaviour did not move to a new home
in this module, it moved to a door with its own suite.

WHAT REPLACES THEM. The generic tombstone checks live in
`src/tests/unit/test_retired_queue_doors_410.py`, parametrised over the whole
`RETIRED_DOORS` table and asserting its exact contents, and in
`test_retired_doors_through_the_real_app.py`, which drives the app `main.py` actually
builds. What neither can see is anything specific to THIS module, and that is what is
left here.

⚠️ THE PREFIX CHECK BELOW IS NOT COSMETIC. This router carries a `prefix=`, so a
decorator handed the FULL path mounts the route TWICE-prefixed — the door then answers
404, which is the one answer a tombstone must never give, and every unit test on the
handler would still pass. It happened here while this commit was being written.

Venue: :7999-eligible. Pure in-process; no queue, no LLM, no network, no auth.
"""

import unittest

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import cosa.rest.routers.deep_research_to_presentation as mod
from cosa.rest.routers._retired_doors import RETIRED_DOORS, V2_SUBMIT

PATH = "/api/deep-research-to-presentation/submit"


def _client():
    app = FastAPI()
    app.include_router( mod.router )
    return TestClient( app, raise_server_exceptions=False )


class TestTheDoorIsRetired( unittest.TestCase ):
    """The tombstone, checked where it lives rather than only in the shared table."""

    def test_the_route_is_mounted_at_exactly_the_path_the_table_names( self ):
        """
        RED ON REVERT: put the full path back in the decorator and the route mounts as
        `/api/deep-research-to-presentation/api/deep-research-to-presentation/submit` — a 404 wearing a tombstone's clothes.
        """
        paths = [ route.path for route in _client().app.routes
                  if "POST" in getattr( route, "methods", set() ) ]
        self.assertEqual( paths, [ PATH ], paths )

    def test_it_answers_410_and_names_the_submit_door( self ):
        response = _client().post( PATH, json={ "query": "anything" } )
        self.assertEqual( response.status_code, 410 )
        self.assertIn( V2_SUBMIT, response.json()[ "detail" ] )

    def test_it_refuses_an_unauthenticated_caller_the_same_way( self ):
        """No auth dependency on a tombstone, on purpose: with one still attached a stale
        client would get a 401, which reads like a credentials problem rather than a
        retired door."""
        self.assertEqual( _client().post( PATH, json={ } ).status_code, 410 )

    def test_a_body_that_would_once_have_been_rejected_still_gets_the_410( self ):
        """`query` was required and min-length-1. The body is not read at all now, and the
        caller's real problem is that the door is gone — not that they sent it wrong."""
        self.assertEqual( _client().post( PATH, json={ "query": "" } ).status_code, 410 )

    def test_the_table_says_this_door_retires_into_submit_not_ask( self ):
        """The two v2 doors are not interchangeable: `ask` takes a bare question, `submit`
        takes work whose command is already decided. This one named its own command."""
        self.assertEqual( RETIRED_DOORS[ PATH ], V2_SUBMIT )


class TestTheModuleNoLongerCarriesALiveDoor( unittest.TestCase ):
    """
    The half the shared suites cannot see: a tombstone that still imports the job factory
    and the queue looks, to the next reader, like a door that was disabled rather than
    retired — and unreachable machinery is code nobody can test and everybody must read.
    """

    def test_the_handler_only_refuses( self ):
        """RED ON REVERT: give the handler a body again and it stops raising."""
        import asyncio
        with self.assertRaises( HTTPException ) as caught:
            asyncio.run( mod.submit_research_to_presentation() )
        self.assertEqual( caught.exception.status_code, 410 )

    def test_the_job_building_machinery_is_gone_from_this_module( self ):
        for name in ( "create_agentic_job", "user_job_tracker", "get_todo_queue", "DeepResearchToPresentationJob" ):
            self.assertFalse( hasattr( mod, name ),
                              f"{name} survives in a module whose only route is a tombstone" )

    def test_the_request_and_response_models_are_gone( self ):
        """A Pydantic model no route reads is a shape a caller can still find and
        reasonably believe in."""
        for name in ( "ResearchToPresentationSubmitRequest", "ResearchToPresentationSubmitResponse" ):
            self.assertFalse( hasattr( mod, name ), f"{name} describes a body nothing accepts" )

    def test_the_smoke_block_still_runs( self ):
        """`quick_smoke_test` referenced the deleted models; it now checks the tombstone
        instead. A smoke block that raises on import is one nobody runs twice."""
        mod.quick_smoke_test()


if __name__ == "__main__":
    unittest.main()
