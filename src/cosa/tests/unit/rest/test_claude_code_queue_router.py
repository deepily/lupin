"""
Unit tests for the retired Claude Code queue router (`cosa.rest.routers.claude_code_queue`).

WHAT USED TO BE HERE. The dependency reads, the identity 400s, the task_type validation,
the session-id fallback, every optional-field arm, the scheduling pass-through, and the
push-failure 500 — all tests of a handler that submitted Claude Code jobs to CJ Flow. That
handler is gone: both `/api/claude-code/submit` and its `/api/claude-code/queue/submit`
alias are tombstones naming `/api/v2/submit`. There is nothing to rewrite those tests
INTO; the behaviour did not move within this module, it moved to a door with its own suite
(`src/tests/unit/test_v2_submit_claude_code_through_path.py`).

ONE OF THEM DID NOT SIMPLY MOVE, and that is worth stating rather than leaving as a gap in
a diff. The old handler validated `task_type` and answered 400 for anything but
BOUNDED/INTERACTIVE. `/api/v2/submit` is generic: it checks that a command's required
ARGUMENTS are present, not which values they may take. That guard now lives in
`ClaudeCodeJob.__init__` and is tested at
`src/cosa/tests/unit/agents/claude_code/test_job.py::test_an_unknown_task_type_is_refused_at_construction`.

Rick's ruling, 2026-08-21: the Claude Code job is *upgraded* to the v2 front door rather
than left to die on the vine. The tombstone is the second half of that upgrade — the door
that used to build the job now says where it is built instead.
"""

import asyncio
import unittest

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import cosa.rest.routers.claude_code_queue as mod
from cosa.rest.routers.claude_code_queue import (
    submit_claude_code_to_queue,
    submit_claude_code_to_queue_alias,
)
from cosa.rest.routers._retired_doors import REMOVE_BY, RETIRED_DOORS, V2_SUBMIT

CANONICAL = "/api/claude-code/submit"
ALIAS     = "/api/claude-code/queue/submit"


class TestBothClaudeCodeDoorsAreRetired( unittest.TestCase ):
    """
    Both paths, one assertion set each — not a loop. The inventory that listed only the
    alias is exactly how the canonical path nearly survived this change, and a loop that
    covers whatever the table happens to hold would not have said which one was missing.
    """

    def _client( self ):
        app = FastAPI()
        app.include_router( mod.router )
        return TestClient( app, raise_server_exceptions=False )

    # ── the canonical door ──

    def test_the_canonical_door_answers_410_and_names_the_submit_door( self ):
        response = self._client().post( CANONICAL, json={ "prompt": "run the tests" } )
        self.assertEqual( response.status_code, 410 )
        self.assertIn( V2_SUBMIT, response.json()[ "detail" ] )

    def test_the_canonical_refusal_says_the_removal_date_out_loud( self ):
        detail = self._client().post( CANONICAL, json={ } ).json()[ "detail" ]
        self.assertIn( "2026-12-31", detail )
        self.assertIn( "REMOVE BY", detail )

    # ── the alias ──

    def test_the_alias_answers_410_and_names_the_submit_door( self ):
        response = self._client().post( ALIAS, json={ "prompt": "run the tests" } )
        self.assertEqual( response.status_code, 410 )
        self.assertIn( V2_SUBMIT, response.json()[ "detail" ] )

    def test_the_alias_refusal_names_ITS_OWN_path_not_the_canonical_one( self ):
        """
        The live handler carried both routes on ONE function and told them apart by reading
        `request.url.path`. Two stubs replace it so each refusal names the path the caller
        actually called — a refusal that names a different door than the one you knocked on
        sends the reader looking for a caller they do not have.
        """
        detail = self._client().post( ALIAS, json={ } ).json()[ "detail" ]
        self.assertIn( ALIAS, detail )
        self.assertNotIn( f"{CANONICAL} is GONE", detail )

    # ── both ──

    def test_neither_door_asks_for_credentials( self ):
        """
        No auth on a tombstone: an unauthenticated caller must learn the same thing an
        authenticated one does. A 401 reads like a credentials problem, not a retired door.
        """
        client = self._client()
        for path in ( CANONICAL, ALIAS ):
            with self.subTest( path=path ):
                self.assertEqual( client.post( path, json={ } ).status_code, 410 )

    def test_the_table_says_both_doors_retire_into_submit_not_ask( self ):
        """
        `submit` and not `ask`, because a Claude Code caller has already decided what it
        wants run. Sending it to `ask` would teach it the wrong one of two doors that both
        exist and both answer.
        """
        for path in ( CANONICAL, ALIAS ):
            with self.subTest( path=path ):
                self.assertEqual( RETIRED_DOORS[ path ], V2_SUBMIT )

    def test_both_handlers_only_refuse( self ):
        """RED ON REVERT: give either handler a body again and it stops raising."""
        for handler in ( submit_claude_code_to_queue, submit_claude_code_to_queue_alias ):
            with self.subTest( handler=handler.__name__ ):
                with self.assertRaises( HTTPException ) as caught:
                    asyncio.run( handler() )
                self.assertEqual( caught.exception.status_code, 410 )
                self.assertIn( REMOVE_BY, caught.exception.detail )

    def test_the_job_building_machinery_is_gone_from_this_module( self ):
        """
        A Pydantic model no route reads is a shape a caller can still find and reasonably
        believe in, and a dependency nothing calls is a live wire in a dead module.
        """
        for name in ( "create_agentic_job", "get_todo_queue", "get_user_job_tracker",
                      "ClaudeCodeQueueRequest", "ClaudeCodeQueueResponse", "get_current_user" ):
            with self.subTest( name=name ):
                self.assertFalse( hasattr( mod, name ),
                                  f"{name} survives in a module whose only POSTs are tombstones" )

    def test_the_router_still_mounts_both_paths( self ):
        """
        A tombstone nobody mounts is a 404, which teaches a stale caller nothing. This is
        the check that would go red if someone "cleaned up" by deleting the routes instead
        of retiring them.
        """
        paths = { route.path for route in mod.router.routes }
        self.assertIn( CANONICAL, paths )
        self.assertIn( ALIAS,     paths )


if __name__ == "__main__":
    unittest.main()
