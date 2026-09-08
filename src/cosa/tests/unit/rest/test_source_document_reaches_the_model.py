#!/usr/bin/env python3
"""
The seed document reaches the MODEL, for `research to podcast` and `research to presentation`.

🔴 THIS FILE EXISTS BECAUSE THE SAME SEAM KILLED THIS FEATURE ONCE ALREADY.

Slice 1 (row 14c54c10) shipped `source_document` on deep research and it was a NO-OP in
production: the v2 door validated and resolved the paths, `DeepResearchJob` knew how to
read them, and `agentic_job_factory` between the two dropped them. Three test files were
green over it — one drove the door with a FAKE factory, one built the job DIRECTLY, one
tested the validator alone. Each stopped exactly at the seam. Both ends of a join were
proven and the join was proven by nobody. Krishna 🦚 found it in review.

Row 5726e3c5 extends the argument to two more commands, and those two are FURTHER from
the model than deep research is, not closer:

    factory._build_research_to_podcast  ->  DeepResearchToPodcastJob   (its own class)
    job._make_agent                     ->  DeepResearchToPodcastAgent (its own class)
    agent._run_deep_research            ->  run_research( query=... )  (the model call)

Measured 2026-09-08: neither chain constructs a `DeepResearchJob`, so neither inherits
anything from slice 1. Four seams, and a mock at any one of them hides a dead feature.

WHAT IS REAL HERE AND WHAT IS NOT, stated so the next reader can judge the claim:

    REAL   create_agentic_job, the job class, _make_agent, the agent class, and
           query_with_seed_context -- every link between the door and the model
    FAKED  run_research itself (it IS the model), and the three heavy collaborators
           around it that would otherwise call an LLM, notify a live server, or write
           to storage -- Gister, voice_io, generate_abstract_for_cli / save_report

Faking the model is the point: the assertion is about what the model was HANDED.

⚠️ Run scoped -- an unscoped run collects `src/tmp/`, which exits at import time.
"""

import asyncio
import os
import sys
import tempfile
import unittest

_SRC = os.path.abspath( os.path.join( os.path.dirname( __file__ ), "..", "..", "..", ".." ) )
if _SRC not in sys.path: sys.path.insert( 0, _SRC )

from cosa.rest.agentic_job_factory import create_agentic_job
from cosa.rest.v2.source_document import SOURCE_DOCUMENT_ARG


_SEED_TEXT = "ACIDIFICATION-BASELINE-1987 is the figure this document exists to carry."

_CHAINS = (
    ( "agent router go to research to podcast",      "cosa.agents.deep_research_to_podcast.agent" ),
    ( "agent router go to research to presentation", "cosa.agents.deep_research_to_presentation.agent" ),
)


class _Captured( Exception ):
    """Raised by the fake `run_research` to stop the pipeline the instant we have the query.

    STOPPING HERE IS DELIBERATE. Everything after `run_research` -- the abstract, the
    report file, the podcast or the deck -- is a different feature's business, and letting
    it run would make this test depend on all of it. The exception carries the one thing
    this file is about.
    """
    def __init__( self, query ):
        self.query = query
        super().__init__( "run_research reached" )


def _seed_file( tmpdir ):
    path = os.path.join( tmpdir, "notes.md" )
    with open( path, "w", encoding="utf-8" ) as handle: handle.write( _SEED_TEXT + "\n" )
    return path


def _job_for( command, args ):
    """Drive the REAL factory. No fake, no patch -- that is the whole point of the file."""
    return create_agentic_job(
        command    = command,
        args_dict  = args,
        user_id    = "u1",
        user_email = "u@x.com",
        session_id = "s1",
        debug      = False,
        verbose    = False,
    )


def _query_handed_to_the_model( testcase, command, agent_module, args ):
    """Run the REAL chain factory -> job -> agent -> run_research, returning the query.

    Ensures:
        - returns the `query` keyword `run_research` was actually called with
        - fails the test if `run_research` is never reached
    """
    import importlib

    from cosa.agents.deep_research import cli as dr_cli
    from cosa.memory import gister as gister_mod

    agent_mod = importlib.import_module( agent_module )

    async def _fake_run_research( **kwargs ):
        raise _Captured( kwargs[ "query" ] )

    class _FakeGister:
        def __init__( self, *a, **k ): pass
        def get_gist( self, *a, **k ): return "a session name"

    async def _quiet( *a, **k ): return None

    saved = {
        "run_research" : dr_cli.run_research,
        "Gister"       : gister_mod.Gister,
        "notify"       : agent_mod.__dict__.get( "_notify_saved" ),
    }
    dr_cli.run_research  = _fake_run_research
    gister_mod.Gister    = _FakeGister

    job   = _job_for( command, args )
    agent = job._make_agent()

    # The agent's own notifier, silenced. Everything else about the agent is real.
    agent._notify = _quiet

    try:
        try:
            asyncio.run( agent._run_deep_research() )
        except _Captured as captured:
            return captured.query
        testcase.fail( f"{command}: run_research was never reached" )
    finally:
        dr_cli.run_research = saved[ "run_research" ]
        gister_mod.Gister   = saved[ "Gister" ]


class TestSourceDocumentReachesTheModel( unittest.TestCase ):

    def test_the_document_TEXT_is_in_the_query_the_model_receives( self ):
        """THE JOIN. A path validated at the door arrives at the model as CONTENT.

        This is the assertion the three green files of slice 1 could not make, and the
        one that would have caught the dead factory line on the first run.
        """
        for command, agent_module in _CHAINS:
            with self.subTest( command=command ), tempfile.TemporaryDirectory() as tmpdir:
                path  = _seed_file( tmpdir )
                query = _query_handed_to_the_model(
                    self, command, agent_module,
                    { "query": "how bad is it", SOURCE_DOCUMENT_ARG: [ path ] } )

                self.assertIn(
                    _SEED_TEXT, query,
                    f"{command}: the document was validated at the door and the model never saw it" )
                self.assertIn(
                    path, query,
                    f"{command}: the model was given the text without the path that names it" )

    def test_the_QUESTION_survives_alongside_the_document( self ):
        """Rick's Q2 ruling was SEED CONTEXT, not replacement.

        Without this, an implementation that handed the model the document INSTEAD of the
        question would pass the test above.
        """
        for command, agent_module in _CHAINS:
            with self.subTest( command=command ), tempfile.TemporaryDirectory() as tmpdir:
                query = _query_handed_to_the_model(
                    self, command, agent_module,
                    { "query": "how bad is it", SOURCE_DOCUMENT_ARG: [ _seed_file( tmpdir ) ] } )
                self.assertIn( "how bad is it", query, f"{command}: the user's question was dropped" )

    def test_TWO_documents_reach_the_model_IN_ORDER( self ):
        """Rick ruled a list. Order is what tells the model which document is which.

        ⚠️ THE FIXTURE IS DELIBERATELY UNSORTED. With `apple` before `zebra` a chain that
        SORTED the list would pass the one test whose whole subject is order.
        """
        for command, agent_module in _CHAINS:
            with self.subTest( command=command ), tempfile.TemporaryDirectory() as tmpdir:
                zebra = os.path.join( tmpdir, "zebra.md" )
                apple = os.path.join( tmpdir, "apple.md" )
                with open( zebra, "w" ) as h: h.write( "ZEBRA-MARKER\n" )
                with open( apple, "w" ) as h: h.write( "APPLE-MARKER\n" )

                query = _query_handed_to_the_model(
                    self, command, agent_module,
                    { "query": "q", SOURCE_DOCUMENT_ARG: [ zebra, apple ] } )

                self.assertLess(
                    query.index( "ZEBRA-MARKER" ), query.index( "APPLE-MARKER" ),
                    f"{command}: the documents reached the model in the wrong order" )

    def test_NO_document_hands_the_model_the_BARE_QUERY( self ):
        """🔴 THE POSITIVE CONTROL — Rick's "works as it did before".

        Without this, every test above would pass against a chain that had been made to
        REQUIRE a document, and every research request without one would break while the
        suite stayed green. It is also what keeps a mutation arm honest: an arm that
        reddens this too has broken the file, not the guard.
        """
        for command, agent_module in _CHAINS:
            with self.subTest( command=command ):
                query = _query_handed_to_the_model(
                    self, command, agent_module, { "query": "how bad is it" } )
                self.assertEqual(
                    query, "how bad is it",
                    f"{command}: a run with no document no longer sends the plain question" )


if __name__ == "__main__":
    unittest.main()
