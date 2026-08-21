"""
Unit tests for the retired Bug Fix Expediter router (`cosa.rest.routers.bug_fix_expediter`).

WHAT THIS FILE USED TO TEST, AND WHY IT DOES NOT ANY MORE. It covered `submit_bug_fix` —
the missing-uid 400, the missing-email 400, the session-id fallback, the success arms for
every optional field, the factory-None 500, the push-failure 500. That handler is gone:
`/api/bug-fix-expediter/submit` is a tombstone answering 410 and naming `/api/v2/submit`,
so every one of those tests exercised code that no longer exists. They are not rewritten
into equivalents here, because there is nothing to rewrite them INTO — the behaviour did
not move to a new home in this module, it moved to a door with its own suite.

WHAT REPLACES THEM. The generic tombstone checks live in
`src/tests/unit/test_retired_queue_doors_410.py`, which is parametrised over the whole
`RETIRED_DOORS` table and asserts the table's exact contents, so this door cannot fall out
of coverage quietly. What that file cannot see is anything specific to THIS module, and
that is what is left here: the route is mounted at the path the table names, the module no
longer carries the machinery of a live door, and its refusal names the submit door rather
than the ask door.

Venue: :7999-eligible. Pure in-process; no queue, no LLM, no network, no auth.
"""

import unittest

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import cosa.rest.routers.bug_fix_expediter as bfe
from cosa.rest.routers._retired_doors import RETIRED_DOORS, V2_SUBMIT

PATH = "/api/bug-fix-expediter/submit"


def _client():
    app = FastAPI()
    app.include_router( bfe.router )
    return TestClient( app, raise_server_exceptions=False )


class TestTheDoorIsRetired( unittest.TestCase ):
    """
    The tombstone, checked where it lives rather than only in the table.
    """

    def test_the_route_is_still_mounted_at_its_old_path( self ):
        """
        A DELETED route would be invisible, and invisible is exactly what a tombstone is
        for avoiding: nothing would stop someone re-adding this path next year because
        the product needs it. It stays mounted so it can say it was retired on purpose.
        """
        paths = { route.path for route in _client().app.routes
                  if "POST" in getattr( route, "methods", set() ) }
        self.assertIn( PATH, paths )

    def test_it_answers_410_and_names_the_submit_door( self ):
        response = _client().post( PATH, json={ "dead_job_id": "d-1" } )
        self.assertEqual( response.status_code, 410 )
        self.assertIn( V2_SUBMIT, response.json()[ "detail" ] )

    def test_it_refuses_an_unauthenticated_caller_the_same_way( self ):
        """
        No auth dependency on a tombstone, on purpose. With `Depends( get_current_user )`
        still on it, a stale client would get a 401 — which teaches nobody anything and
        reads like a credentials problem rather than a retired door.
        """
        response = _client().post( PATH, json={ } )   # no token, no valid body
        self.assertEqual( response.status_code, 410 )

    def test_a_body_that_would_once_have_been_rejected_still_gets_the_410( self ):
        """`dead_job_id` was a required, min-length-1 field. A tombstone must not answer
        422 to a caller sending the old body wrong — the body is not read at all now, and
        the caller's real problem is that the door is gone."""
        response = _client().post( PATH, json={ "dead_job_id": "" } )
        self.assertEqual( response.status_code, 410 )

    def test_the_table_says_this_door_retires_into_submit_not_ask( self ):
        """The two doors are not interchangeable: `ask` takes a bare question and works
        out what it means, `submit` takes work whose command is already decided. This one
        named its own command, so it is submit-shaped."""
        self.assertEqual( RETIRED_DOORS[ PATH ], V2_SUBMIT )


class TestTheModuleNoLongerCarriesALiveDoor( unittest.TestCase ):
    """
    The half the generic table-driven suite cannot see: a tombstone that still imports the
    job factory and the queue looks, to the next reader, like a door that was disabled
    rather than retired — and unreachable machinery is code nobody can test and everybody
    must still read.
    """

    def test_the_handler_only_refuses( self ):
        """RED ON REVERT: give the handler a body again and it stops raising."""
        with self.assertRaises( HTTPException ) as caught:
            import asyncio
            asyncio.run( bfe.submit_bug_fix() )
        self.assertEqual( caught.exception.status_code, 410 )

    def test_the_job_building_machinery_is_gone_from_this_module( self ):
        for name in ( "create_agentic_job", "user_job_tracker", "get_todo_queue" ):
            self.assertFalse( hasattr( bfe, name ),
                              f"{name} survives in a module whose only route is a tombstone" )

    def test_the_request_and_response_models_are_gone( self ):
        """A Pydantic model no route reads is a shape a caller can still find and
        reasonably believe in."""
        for name in ( "BugFixExpediterSubmitRequest", "BugFixExpediterSubmitResponse" ):
            self.assertFalse( hasattr( bfe, name ), f"{name} describes a body nothing accepts" )


if __name__ == "__main__":
    unittest.main()
