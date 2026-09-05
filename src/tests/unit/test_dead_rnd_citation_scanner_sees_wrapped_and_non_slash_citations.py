"""
The guard for row c6101ab0: `dead_rnd_citations.py` failed in BOTH directions at once, and neither
failure appeared in its own output.

· It HID real dead links, because it is line-oriented and a citation split across a wrap matches
  neither half. Measured: 49 wrapped lines carry a src/rnd citation, 6 have dead targets, 3 of
  those are split by the wrap and had never once been reported.
· It MANUFACTURED dead links, because the sibling-repo prefix list was four names hand-typed
  against fourteen registered repos, and because it only recognised the SLASH form of a cross-repo
  citation. Measured: 22 non-slash citations against 121 slash ones, in four distinct shapes.

🔴 THE THREE FIXES ARE ONE CHANGE AND THIS FILE PINS THEM AS ONE. Dewrapping is not purely
additive: it makes non-slash forms VISIBLE to a guard that has never had to classify them, so
shipping the dewrap without the separator fix trades three false negatives for a fresh batch of
false POSITIVES on correct citations — re-creating, in a new place, the exact defect its
predecessor row was about.

⚠️ EVERY TEST HERE ASSERTS BOTH DIRECTIONS. A rule that excused everything would satisfy the
cross-repo half, and a joiner that glued every line to its neighbour would satisfy the wrap half.
The negative controls are what make these tests rather than rubber stamps.
"""

import os
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


class TheScannerSeesWrappedCitations( unittest.TestCase ):

    @classmethod
    def setUpClass( cls ):
        cls.mod = _load_scanner()

    # ------------------------------------------------------------------------ the wrap, both ways

    def test_the_three_wrap_shapes_in_this_tree_are_joined( self ):
        """
        The shapes are not a taxonomy for its own sake — each one is a live site the scanner was
        blind to, and each needs a different piece of furniture removed.
        """
        cases = [
            ( "prose ending in a hyphen",
              "  the only one a user could see. See src/rnd/v0.2.0/2026.08.22-qa-card-\n",
              "  registry-driven-submit-panel-retirement.md §5.2\n",
              "src/rnd/v0.2.0/2026.08.22-qa-card-registry-driven-submit-panel-retirement.md" ),
            ( "a path continued after a slash",
              "    src/rnd/2026.02.25-full-voice-io/\n",
              "    creating-unique-session-id/session_bridge.py\n",
              "src/rnd/2026.02.25-full-voice-io/creating-unique-session-id/session_bridge.py" ),
            ( "python implicit string concatenation, quotes on both sides",
              '    "src/rnd/v0.2.0/2026.08.04-dm-verbosity/live-runs/"\n',
              '    "sentence-band-outputs.txt" )\n',
              "src/rnd/v0.2.0/2026.08.04-dm-verbosity/live-runs/sentence-band-outputs.txt" ),
            ( "an INI comment marker opening the continuation line",
              "# see src/rnd/v0.2.0/2026.08.04-dm-verbosity-reduction/\n",
              "# sentence_band_summary.py for the derivation\n",
              "src/rnd/v0.2.0/2026.08.04-dm-verbosity-reduction/sentence_band_summary.py" ),
        ]
        for name, head_line, tail_line, want in cases:
            with self.subTest( shape=name ):
                head = self.mod.wrap_head( head_line )
                self.assertIsNotNone( head, "%s: the head must be recognised as continuing" % name )
                joined = head + self.mod.wrap_tail( tail_line )
                found  = [ m.group( 0 ) for m in self.mod.CITATION_PAT.finditer( joined ) ]
                self.assertIn( want, found, "%s: the joined line must yield the whole path" % name )

        # POSITIVE CONTROL ON THE INSTRUMENT ITSELF: the same pattern must find the path in NEITHER
        # half alone, or these cases would pass without the join doing any work at all.
        for name, head_line, tail_line, want in cases:
            with self.subTest( shape=name, half="unjoined" ):
                self.assertNotIn( want, [ m.group( 0 ) for m in self.mod.CITATION_PAT.finditer( head_line ) ] )
                self.assertNotIn( want, [ m.group( 0 ) for m in self.mod.CITATION_PAT.finditer( tail_line ) ] )

    def test_an_ordinary_line_is_not_joined_to_its_neighbour( self ):
        """
        🔴 THE NEGATIVE CONTROL THAT MATTERS MOST. A joiner that glued every line to the next would
        pass every assertion above and would invent paths that appear nowhere in the file. The head
        must be REFUSED unless it actually ends mid-path.
        """
        for line in ( "see src/rnd/v0.2.0/one.md for the design\n",
                      "ROWS = pathlib.Path(\n",
                      "    the sentence simply ends here.\n",
                      "\n" ):
            with self.subTest( line=line.strip() or "<empty>" ):
                self.assertIsNone( self.mod.wrap_head( line ),
                                   "a line that does not end mid-path must not be joined" )

        # and the positive control, so the refusals above are not a function that only returns None
        self.assertIsNotNone( self.mod.wrap_head( "see src/rnd/v0.2.0/some-doc-\n" ) )
        self.assertIsNotNone( self.mod.wrap_head( "see src/rnd/v0.2.0/some-dir/\n" ) )


class TheCrossRepoGuardIsDerivedAndSeparatorTolerant( unittest.TestCase ):

    @classmethod
    def setUpClass( cls ):
        cls.mod = _load_scanner()

    # --------------------------------------------------------------- the tuple, derived not typed

    def test_the_sibling_set_is_derived_from_the_ini_rather_than_hand_typed( self ):
        """
        🔴 THE DEFECT. The old tuple held FOUR names — planning-is-prompting, lupin-mobile,
        cosa-voice, lupin-plugin-firefox — against FOURTEEN repos registered in lupin-app.ini. A
        citation into any of the other ten was resolved against THIS repo and reported dead.

        The three names below are the discriminating ones: each is registered in the ini and none
        was in the hand-typed tuple, so this test fails on the old code by construction.
        """
        names = self.mod.CROSS_REPO_NAMES
        for repo in ( "lookml", "par-pacific", "claude-plans" ):
            with self.subTest( repo=repo ):
                self.assertIn( repo, names, "%s is registered in the ini and must be derived" % repo )

        # the two corrections derivation cannot make on its own, asserted in both directions
        self.assertNotIn( "lupin", names,
                          "this repo must NOT be cross-repo, or the scanner stops resolving its own docs" )
        self.assertIn( "lupin-plugin-firefox", names,
                       "an unregistered sibling must survive the switch to derivation" )

        # POSITIVE CONTROL: the set is not empty and is longest-first, so the alternation cannot
        # settle for a short name that is a prefix of a longer one
        self.assertGreater( len( names ), 4, "derivation must widen the old four-name tuple" )
        self.assertEqual( list( names ), sorted( names, key=lambda n: ( -len( n ), n ) ) )

    # ------------------------------------------------------------ the separator, not only a slash

    def test_a_cross_repo_citation_is_recognised_whatever_short_separator_follows_the_name( self ):
        """
        Counted across the tree, the text between a repo name and `src/rnd/`:
            /  121     →  8     → `  7     `  5     >/  2     (empty) 1
        Four distinct shapes. Special-casing the arrow fixes 8 of the 22 non-slash sites and LOOKS
        finished, which is how the four-name tuple came to exist in the first place.

        RULED BY MARÍA 2026-09-05: match a short RUN of separator characters, not an explicit list.
        """
        for sep in ( "/", " → ", " → `", "`", ">/", "" ):
            with self.subTest( separator=repr( sep ) ):
                line = "see planning-is-prompting%ssrc/rnd/2026.06.04-doc.md" % sep
                col  = line.index( "src/rnd/" )
                self.assertTrue( self.mod.is_cross_repo( line, col ),
                                 "a correct cross-repo citation must not be resolved against lupin" )

    def test_a_lupin_citation_is_still_ours_however_it_is_written( self ):
        """
        🔴 THE NEGATIVE CONTROL, AND THE ONE THAT KEEPS THE WIDENING HONEST. A separator run that
        excused too much would silence real dead links — and unlike a false positive, nothing
        downstream catches that. Every case here must stay OURS to resolve.
        """
        mine = "see `src/rnd/v0.2.0/gone.md` for the design"
        self.assertFalse( self.mod.is_cross_repo( mine, mine.index( "src/rnd/" ) ) )

        # this repo's own name is in the ini and must never excuse a citation — 61 sites
        ours = "see lupin/src/rnd/v0.2.0/gone.md"
        self.assertFalse( self.mod.is_cross_repo( ours, ours.index( "src/rnd/" ) ) )

        # a directory that merely looks like a repo boundary is not one
        decoy = "see `some-other-dir/src/rnd/v0.2.0/gone.md`"
        self.assertFalse( self.mod.is_cross_repo( decoy, decoy.index( "src/rnd/" ) ) )

        # 🔴 and a repo name that is the TAIL OF A LONGER WORD is not a repo boundary either — this
        # is what the word-boundary lookbehind replaced the trailing slash to catch
        glued = "see xlupin-mobile/src/rnd/v0.2.0/gone.md"
        self.assertFalse( self.mod.is_cross_repo( glued, glued.index( "src/rnd/" ) ) )

    def test_the_wrap_and_the_separator_fixes_meet_on_one_line( self ):
        """
        🔴 WHY THESE SHIP AS ONE COMMIT, stated as an assertion rather than as a paragraph. A
        cross-repo citation that is ALSO wrapped is invisible to the old scanner twice over. Once
        the join makes it visible, only the separator fix stops it being reported as a lupin dead
        link — so the dewrap alone would convert a hidden non-defect into a manufactured one.
        """
        head = self.mod.wrap_head( "see planning-is-prompting/src/rnd/v0.2.0/2026.08.22-qa-card-\n" )
        self.assertIsNotNone( head )
        joined  = head + self.mod.wrap_tail( "registry-driven-submit-panel-retirement.md\n" )
        matches = list( self.mod.CITATION_PAT.finditer( joined ) )
        self.assertEqual( 1, len( matches ), "the join must yield exactly one whole path" )
        self.assertTrue( self.mod.is_cross_repo( joined, matches[ 0 ].start() ),
                         "a wrapped cross-repo citation must be excused, not manufactured as dead" )


if __name__ == "__main__":
    unittest.main()
