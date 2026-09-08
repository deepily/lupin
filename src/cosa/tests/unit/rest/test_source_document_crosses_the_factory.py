#!/usr/bin/env python3
"""
The validated `source_document` survives the job factory and reaches the real job.

🔴 THIS FILE EXISTS BECAUSE A REVIEWER FOUND A BUG THREE GREEN TEST FILES COULD NOT SEE.

`_build_deep_research` in `agentic_job_factory.py` constructed `DeepResearchJob` without
passing `source_document`. Every layer was individually correct and the feature was dead:
the door validated the paths and wrote them back into args, the job class knew how to read
them — and the factory between the two dropped them on the floor. A research run would
have reported on a document it never opened, with nothing anywhere saying so.

WHY 45 PASSING TESTS MISSED IT, WHICH IS THE LESSON WORTH MORE THAN THE FIX:

    test_v2_submit_source_document.py     drives the door with a FAKE factory
    test_deep_research_seed_context.py    constructs DeepResearchJob DIRECTLY
    test_source_document_validation.py    tests the validator alone

Each one stops exactly at the seam the bug lived in. Both sides of a join were proven and
the join itself was proven by nobody — and mocking the collaborator is precisely what
hides that. So this file mocks NOTHING about the path under test: it calls the real
`create_agentic_job` and reads the real job object it returns.

⚠️ Run scoped — an unscoped run collects `src/tmp/`, which exits at import time.
"""

import os
import sys
import unittest

_SRC = os.path.abspath( os.path.join( os.path.dirname( __file__ ), "..", "..", "..", ".." ) )
if _SRC not in sys.path: sys.path.insert( 0, _SRC )

from cosa.rest.agentic_job_factory import create_agentic_job
from cosa.rest.v2.source_document import SOURCE_DOCUMENT_ARG


_COMMAND = "agent router go to deep research"


def _build( args ):
    """Drive the REAL factory. No fake, no patch — that is the whole point of the file."""
    return create_agentic_job(
        command    = _COMMAND,
        args_dict  = args,
        user_id    = "u1",
        user_email = "u@x.com",
        session_id = "s1",
        debug      = False,
        verbose    = False,
    )


class TestSourceDocumentCrossesTheFactory( unittest.TestCase ):

    def test_the_factory_CARRIES_source_document_through_to_the_job( self ):
        """THE REGRESSION TEST. This is the exact assertion that was missing.

        `_build_deep_research` listed nine arguments and not this one, so the validated
        paths stopped here. Nothing downstream could tell that from a run with no
        document at all.
        """
        paths = [ "/tmp/does-not-need-to-exist-here.md" ]
        job   = _build( { "query": "a topic", SOURCE_DOCUMENT_ARG: paths } )

        self.assertEqual(
            job.source_document, paths,
            "the factory dropped source_document — the door validated documents the job never sees" )

    def test_a_LIST_of_documents_survives_the_factory_IN_ORDER( self ):
        """Rick ruled a list. Order is what tells the model which document is which.

        ⚠️ THE FIXTURE IS DELIBERATELY UNSORTED, AND IT USED TO BE SORTED. The pair was
        [ "/tmp/first.md", "/tmp/second.txt" ] — already in lexical order, so a factory
        that SORTED the list passed the one test whose whole subject is order. The
        assertion could not fail in the one direction it exists to watch.

        `zebra` before `apple` differs from its own sorted order, so a sort now reddens
        this test by name. Found reviewing María's 🌸 branch, 2026-09-08.
        """
        paths = [ "/tmp/zebra.md", "/tmp/apple.txt" ]
        job   = _build( { "query": "a topic", SOURCE_DOCUMENT_ARG: paths } )
        self.assertEqual( job.source_document, paths )

    def test_NO_source_document_still_builds_a_working_job( self ):
        """🔴 THE POSITIVE CONTROL — Rick's "works as it did before".

        Without this, the two tests above would pass against a factory that had been
        made to REQUIRE the argument, and every research request without a document
        would break while the suite stayed green.
        """
        job = _build( { "query": "a topic" } )
        self.assertEqual( job.source_document, [ ] )
        self.assertEqual( job.query, "a topic" )

    def test_the_QUERY_still_arrives_when_a_document_does_too( self ):
        """The document is seed context, not a replacement — Q2's ruling was (a).

        A factory that forwarded the document by overwriting the query would satisfy
        the first test in this file and destroy the feature.
        """
        job = _build( { "query": "a topic", SOURCE_DOCUMENT_ARG: [ "/tmp/a.md" ] } )
        self.assertEqual( job.query, "a topic" )


if __name__ == "__main__":
    unittest.main()
