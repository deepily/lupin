"""
The guard for row 88f4dfdb: the same population exclusion was made TWICE, by the same author, and
the correction in between lived only in a task-store row body.

🔴 THIS GUARDS THE CORPUS, NOT THE COUNT. It never asserts how many dead citations exist — a guard
written against the live total would ship RED on 133 sites today, and a guard that ships red is one
somebody deletes. It asserts that the search can SEE what it claims to search, which is the thing
that was actually wrong both times.

Every test carries a POSITIVE CONTROL, because an empty result and an empty search print the same.
"""

import os
import subprocess
import unittest

import cosa.utils.util as cu

import importlib.util


def _load_scanner():
    """
    Ensures: returns the dead_rnd_citations module loaded from THIS tree, resolved through
             cu.get_project_root() so it follows LUPIN_ROOT rather than the import graph.
    """
    path = os.path.join( cu.get_project_root(), "src", "scripts", "dead_rnd_citations.py" )
    spec = importlib.util.spec_from_file_location( "dead_rnd_citations", path )
    mod  = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( mod )
    return mod


class TheCorpusIncludesTheIndex( unittest.TestCase ):

    @classmethod
    def setUpClass( cls ):
        cls.mod  = _load_scanner()
        cls.root = cu.get_project_root()

    # ---------------------------------------------------------------- the exclusion that bit twice

    def test_the_rnd_index_is_in_the_corpus_even_though_the_rnd_tree_is_not( self ):
        """
        The whole finding, in one assertion. `src/rnd/` is excluded because a research doc citing a
        sibling is a record; the INDEX is carved back in because an index instructs.
        """
        # POSITIVE CONTROL: the exclusion is real, so this test is not vacuously true
        self.assertFalse( self.mod.in_corpus( "src/rnd/v0.2.0/some-research-doc.md" ),
                          "the rnd tree must still be excluded — otherwise this guard proves nothing" )
        # THE GUARD
        self.assertTrue( self.mod.in_corpus( "src/rnd/README.md" ),
                         "the rnd INDEX was excluded along with the documents — the defect that hid "
                         "52 dead links, twice" )

    def test_every_declared_index_file_exists_on_disk( self ):
        """
        A carve-out naming a file that is not there is a carve-out that guards nothing.
        """
        self.assertTrue( self.mod.INDEX_FILES, "INDEX_FILES must not be empty" )
        for rel in self.mod.INDEX_FILES:
            self.assertTrue( os.path.exists( os.path.join( self.root, rel ) ),
                             f"INDEX_FILES names {rel}, which does not exist" )

    # ---------------------------------------------------------------- the scan reports its own corpus

    def test_the_scan_reports_which_index_files_it_actually_reached( self ):
        """
        Naming the problem in the source is not the same as delivering it. The scan's OUTPUT has to
        say which index files it reached, or the next reader has no way to notice the regression.
        """
        result = self.mod.scan( self.root )
        # POSITIVE CONTROL: the scan read a real corpus and found real citations
        self.assertGreater( len( result[ "scanned" ] ), 1000,
                            "the scan read almost nothing — an empty corpus passes every per-item "
                            "assertion below it" )
        self.assertGreater( len( result[ "live" ] ), 100,
                            "no LIVE src/rnd paths found, so a DEAD answer would mean nothing" )
        # THE GUARD
        self.assertIn( "src/rnd/README.md", result[ "index_scanned" ] )

    def test_an_already_annotated_citation_is_not_re_flagged( self ):
        """
        The fix form embeds the dead path inside its own recovery command, so a naive re-scan
        reports the cleanup as the disease.
        """
        line = "recover with `git show c752ab9e^:src/rnd/v0.2.0/gone.md`"
        col  = line.index( "src/rnd/" )
        self.assertTrue( self.mod.is_annotated( line, col ) )
        # POSITIVE CONTROL: an un-annotated citation on the same shape is still flagged
        plain = "see `src/rnd/v0.2.0/gone.md` for the analysis"
        self.assertFalse( self.mod.is_annotated( plain, plain.index( "src/rnd/" ) ) )

    def test_an_annotation_is_recognised_for_EVERY_deletion_sha_not_just_the_first_one( self ):
        """
        🔴 THE DEFECT THIS PINS. The markers were hardcoded to `c752ab9e`, which is one of FIVE
        deletion shas in this repo. A scanner that recognises one sha's cleanup re-flags the other
        four's, and reports the fix as the disease.

        Measured before the fix: 40 sites annotated, only 15 stopped being reported.

        This is a DISCRIMINATING test, not a restatement: every sha below is one the hardcoded
        form got WRONG, so the case fails on the old implementation and passes on the new. The
        positive control at the end is what stops it passing vacuously — an un-annotated citation
        on the same shape must still be flagged, or "recognises everything" would satisfy it.
        """
        for sha in ( "172cb57f", "8bf71a64", "a4a27b0c", "942fe0b8", "c752ab9e" ):
            with self.subTest( sha=sha ):
                # the recovery-command form, which embeds the dead path after `<sha>^:`
                line = "recover with `git show %s^:src/rnd/v0.2.0/gone.md`" % sha
                self.assertTrue( self.mod.is_annotated( line, line.index( "src/rnd/" ) ),
                                 "a recovery command for %s must not be re-flagged" % sha )
                # the line-marker form, which is what a plain-text (non-markdown) comment carries
                plain_note = "See src/rnd/v0.2.0/gone.md - REMOVED by %s (2026-08-29)" % sha
                self.assertTrue( self.mod.is_annotated( plain_note, plain_note.index( "src/rnd/" ) ),
                                 "a REMOVED-by marker naming %s must not be re-flagged" % sha )

        # POSITIVE CONTROL: the matcher must still say NO to something, or it proves nothing
        plain = "see `src/rnd/v0.2.0/gone.md` for the analysis"
        self.assertFalse( self.mod.is_annotated( plain, plain.index( "src/rnd/" ) ) )
        # and a bare hex word that is NOT a recovery command must not count as an annotation
        decoy = "deadbeef is not a marker: src/rnd/v0.2.0/gone.md"
        self.assertFalse( self.mod.is_annotated( decoy, decoy.index( "src/rnd/" ) ) )

    def test_archive_files_are_classified_as_archive_and_ordinary_docs_are_not( self ):
        """
        A frozen record is not a defect. Both directions, so the classifier is not a constant.
        """
        self.assertTrue(  self.mod.is_archive( "todo-history/2026-04-10-to-2026-05-01-todo.md" ) )
        self.assertTrue(  self.mod.is_archive( "src/cosa/history.md.backup-20251030" ) )
        self.assertFalse( self.mod.is_archive( "README.md" ) )
        self.assertFalse( self.mod.is_archive( "src/docs/notification-api.md" ) )

    # ---------------------------------------------------------------- the index is its own population

    def test_the_index_link_resolver_works_before_any_dead_count_is_believed( self ):
        """
        The 52 dead links are reported as a finding ONLY because the resolver demonstrably resolves.
        This asserts the control, never the count — the count is a census and moves.
        """
        live, dead = self.mod.scan_index_links( self.root )
        self.assertGreater( live, 100,
                            "the index resolver found almost nothing live, so its dead list is not "
                            "evidence of anything" )
        self.assertIsInstance( dead, list )

    def test_tracked_files_answers_from_git_rather_than_the_filesystem( self ):
        """
        POSITIVE CONTROL on the corpus source: git must answer, and must name a file we know it
        tracks. A silent empty here would make every count above meaningless.
        """
        files = self.mod.tracked_files( self.root )
        self.assertGreater( len( files ), 1000 )
        self.assertIn( "CLAUDE.md", files )

    def test_a_git_failure_raises_rather_than_returning_an_empty_corpus( self ):
        """
        An empty corpus and a failed call must not print the same. This is the refuse-rather-than-
        no-op contract: the tool declines instead of handing back a clean-looking nothing.
        """
        with self.assertRaises( subprocess.CalledProcessError ):
            self.mod.tracked_files( "/dev/null/not-a-repo" )


if __name__ == "__main__":
    unittest.main()
