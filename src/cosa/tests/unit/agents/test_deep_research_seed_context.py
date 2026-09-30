#!/usr/bin/env python3
"""
The deep research job reads its source documents and puts them in front of the model.

THE HALF THE DOOR CANNOT PROVE. The door tests beside this one prove a bad path never
becomes a job and a good path arrives as a resolved absolute path. Neither of them can
show that the agent OPENS the file — a door that validated a path perfectly and then
handed it to a job that ignored it would pass every one of those tests, and the research
would come back having read nothing. That gap is the whole reason this file exists.

🔴 THE CONTROL THAT MATTERS MOST IS THE UNCHANGED ONE. Rick's requirement was that
"the process would work as it did before, simply that it takes the optional argument."
`test_with_NO_source_document_the_query_is_returned_UNCHANGED` is that sentence as an
assertion: it fails the moment an empty-document run starts getting decorated, which is
how an optional feature quietly becomes mandatory.
"""

import os
import sys
import unittest

_SRC = os.path.abspath( os.path.join( os.path.dirname( __file__ ), "..", "..", "..", ".." ) )
if _SRC not in sys.path: sys.path.insert( 0, _SRC )

from cosa.agents.deep_research.job import DeepResearchJob


def _job( tmpdir, source_document=None, query="Compare React and Vue" ):
    """A job built without touching the network, the queue or a config manager."""
    return DeepResearchJob(
        query           = query,
        user_id         = "u1",
        user_email      = "u@x.com",
        session_id      = "s1",
        source_document = source_document,
    )


class TestSeedContextNormalization( unittest.TestCase ):
    """One spelling of the argument at the boundary, so nothing downstream has to ask."""

    def setUp( self ):
        import tempfile
        self.tmp = tempfile.mkdtemp()

    def tearDown( self ):
        import shutil
        shutil.rmtree( self.tmp, ignore_errors=True )

    def test_None_becomes_an_EMPTY_LIST( self ):
        self.assertEqual( _job( self.tmp ).source_document, [ ] )

    def test_a_BARE_STRING_becomes_a_one_element_list( self ):
        """A direct in-process caller may not know the argument is plural."""
        job = _job( self.tmp, source_document="/some/path.md" )
        self.assertEqual( job.source_document, [ "/some/path.md" ] )

    def test_a_LIST_is_kept_in_order( self ):
        job = _job( self.tmp, source_document=[ "/b.md", "/a.md" ] )
        self.assertEqual( job.source_document, [ "/b.md", "/a.md" ] )


class TestQueryWithSeedContext( unittest.TestCase ):
    """Real files, because the claim is that the agent READS them."""

    def setUp( self ):
        import tempfile
        self.tmp   = tempfile.mkdtemp()
        self.first = os.path.join( self.tmp, "notes.md" )
        with open( self.first, "w" ) as handle:
            handle.write( "# Notes\nVue has a smaller runtime.\n" )
        self.second = os.path.join( self.tmp, "second.txt" )
        with open( self.second, "w" ) as handle:
            handle.write( "React ships hooks.\n" )

    def tearDown( self ):
        import shutil
        shutil.rmtree( self.tmp, ignore_errors=True )

    def test_with_NO_source_document_the_query_is_returned_UNCHANGED( self ):
        """🔴 THE CONTROL. Rick's "works as it did before" as an executable assertion.

        Every other test here would still pass if an empty run were being decorated with
        an empty preamble; only this one catches it.
        """
        job = _job( self.tmp )
        self.assertEqual( job._query_with_seed_context(), "Compare React and Vue" )

    def test_the_DOCUMENT_TEXT_actually_reaches_the_research_query( self ):
        """The claim the door cannot make: the file was opened and its content is in."""
        job      = _job( self.tmp, source_document=[ self.first ] )
        enriched = job._query_with_seed_context()
        self.assertIn( "Vue has a smaller runtime.", enriched )

    def test_the_USERS_QUESTION_SURVIVES_the_enrichment( self ):
        """Seed context is context, not a replacement — Q2's ruling was (a), not (b)."""
        job      = _job( self.tmp, source_document=[ self.first ] )
        enriched = job._query_with_seed_context()
        self.assertIn( "Compare React and Vue", enriched )
        self.assertIn( "RESEARCH QUESTION:", enriched )

    def test_the_DOCUMENT_COMES_FIRST_and_the_QUESTION_LAST( self ):
        """"Read them first" is an ordering claim, so it gets an ordering assertion."""
        job      = _job( self.tmp, source_document=[ self.first ] )
        enriched = job._query_with_seed_context()
        self.assertLess( enriched.index( "Vue has a smaller runtime." ),
                         enriched.index( "RESEARCH QUESTION:" ) )

    def test_SEVERAL_documents_all_arrive_LABELLED_with_their_paths( self ):
        """Rick ruled a list. Unlabelled concatenation would leave the model unable to say
        which document a claim came from, which is most of the value of supplying two."""
        job      = _job( self.tmp, source_document=[ self.first, self.second ] )
        enriched = job._query_with_seed_context()
        self.assertIn( "Vue has a smaller runtime.", enriched )
        self.assertIn( "React ships hooks.", enriched )
        self.assertIn( self.first, enriched )
        self.assertIn( self.second, enriched )

    def test_SELF_QUERY_IS_NEVER_MUTATED_by_the_enrichment( self ):
        """🔴 THE FOUR OTHER READERS.

        `self.query` also feeds the session-name gist, the starting notification, the
        report frontmatter and the job title. Folding a document into it would put a whole
        file into all four — a session named after eighty characters of somebody's notes.
        """
        job = _job( self.tmp, source_document=[ self.first ] )
        job._query_with_seed_context()
        self.assertEqual( job.query, "Compare React and Vue" )

    def test_a_VANISHED_document_RAISES_rather_than_researching_without_it( self ):
        """By this point the door already validated the path, so a read failure means the
        world moved. Continuing would produce a report silently resting on less than was
        asked for — indistinguishable from a run that had the document all along."""
        job = _job( self.tmp, source_document=[ os.path.join( self.tmp, "gone.md" ) ] )
        with self.assertRaises( OSError ):
            job._query_with_seed_context()


if __name__ == "__main__":
    unittest.main()
