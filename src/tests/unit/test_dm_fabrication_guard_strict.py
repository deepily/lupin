"""
V3-STRICT on the DM tutor's fabrication guard — row ddf7581e.

WHAT SHIPPED AND WHY
--------------------
The fabrication guard refuses a rewrite that asserts a fact the sender never wrote.
Its name check flagged any novel CAPITALISED token, which caught invented people —
its founding purpose, the "there was no reviewer" incident — but also caught every
ordinary sentence-initial verb: Update, Implement, Include, Ensure, Verify, Use.

Rick ruled "V3-strict behind a flag" live on 2026-08-18. Measured on 400 paired
bodies (run 2026.08.18-mrradio-host-400): flash_lite 130 blocks -> 54, phi_4 67 -> 30.

WHY "STRICT" AND NOT PLAIN "IS IT A DICTIONARY WORD"
----------------------------------------------------
/usr/share/dict/american-english holds 20,494 CAPITALISED entries, so `rachel`,
`clayton`, `krishna` and `tiffany` are all "dictionary words". Exempting any
dictionary entry would blind the guard to invented PERSON names — the one thing it
was built for. So a capitalised token is exempt ONLY when the word list holds it as
a LOWERCASE entry. Proper nouns live there capitalised and stay flaggable.

`test_plain_v3_would_have_blinded_the_guard_to_person_names` is the standing proof
that the distinction is load-bearing rather than a detail of phrasing.

THE COST, ACCEPTED KNOWINGLY BY RICK
------------------------------------
The guard loses its one demonstrated true positive: a rewrite that turned
"Force-recreated" into "Deployed". `deployed` is a lowercase entry, so that rewrite
now ships. It is pinned below as a test so the trade stays visible instead of
becoming folklore — NOT so it can be quietly special-cased back.

THE TWO STRUCTURAL TESTS MR RADIO ASKED FOR
-------------------------------------------
· `test_the_word_list_is_read_once_at_import_not_per_call` fails if the 789 KB read
  moves back inside the function and onto the send path.
· `test_an_unreadable_word_list_degrades_to_no_exemptions_and_never_raises` pins the
  failure direction: a missing file means MORE blocking, never less, and never an
  exception at import.

RED-IF-REMOVED
--------------
`test_removing_the_strict_rule_turns_this_suite_red` documents the mutation that was
run by hand; the exemption tests are themselves the red-if-removed proof, since
deleting the rule blocks all eight verbs again.

Venue: :7999-eligible. Pure function calls, no server, no model, no network.
"""

import builtins
import unittest
from unittest.mock import patch

from cosa.rest.routers import dm


# The exact token sets from the row's 2026-08-18 amendment. These are not invented
# examples — they are the measured before/after populations from the 400-body run,
# which is what makes this suite a check on the ruling rather than on my own reading.
_STILL_BLOCKED = [
    "JSON", "DMs", "DOM", "ImportError", "Mistral", "SessionStart",
    "Rachel", "Clayton", "Krishna's", "Thursday",
]
_NO_LONGER_BLOCKED = [
    "Update", "Implement", "Include", "Ensure", "Verify", "Use", "Option", "Stop",
]

_ORIGINAL = "the queue drained and the container came back"


def _names( rewritten, strict=True, original=_ORIGINAL ):
    """Name-class findings only — the class V3-strict changes."""
    return dm._fabricated_facts( original, rewritten, strict=strict ).get( "name", [] )


# ══════════════════════════════════════════════════════════════════════════
# The ruling, token by token
# ══════════════════════════════════════════════════════════════════════════

class TestTheRuledTokenSets( unittest.TestCase ):

    def test_every_token_the_ruling_keeps_blocked_is_still_blocked( self ):
        """
        The guard's founding purpose. If any of these stops being flagged, an invented
        person or an invented identifier ships as signal — which is the incident, not
        a regression in a nice-to-have.
        """
        for token in _STILL_BLOCKED:
            with self.subTest( token=token ):
                self.assertIn( token, _names( f"{token} reviewed it" ) )

    def test_every_token_the_ruling_releases_is_no_longer_blocked( self ):
        """The false positives Rick asked to be rid of. 130 -> 54 lives here."""
        for token in _NO_LONGER_BLOCKED:
            with self.subTest( token=token ):
                self.assertEqual( [], _names( f"{token} the row" ) )

    def test_plain_v3_would_have_blinded_the_guard_to_person_names( self ):
        """
        THE REASON THE RULE IS "STRICT" — pinned so nobody relaxes it back to a plain
        dictionary lookup thinking the word "strict" was decoration.

        Every one of these names IS in the system dictionary, capitalised. A plain
        "is it a dictionary word" exemption would therefore release all four, and the
        guard would stop catching invented reviewers. Under the strict rule none of
        them is a LOWERCASE entry, so all four stay flaggable.
        """
        for name in [ "Rachel", "Clayton", "Tiffany", "Krishna's" ]:
            with self.subTest( name=name ):
                self.assertNotIn( name.lower(), dm._FAB_LOWERCASE_WORDS )
                self.assertIn( name, _names( f"{name} approved it" ) )

    def test_the_word_list_holds_the_released_verbs_as_lowercase_entries( self ):
        """
        The other half of the pair above: the release is not an accident of some
        unrelated rule, it is the word list doing the work it was vendored to do.
        """
        for token in _NO_LONGER_BLOCKED:
            with self.subTest( token=token ):
                self.assertIn( token.lower(), dm._FAB_LOWERCASE_WORDS )


# ══════════════════════════════════════════════════════════════════════════
# The flag is a real dial, not two divergent code paths
# ══════════════════════════════════════════════════════════════════════════

class TestTheFlag( unittest.TestCase ):

    def test_strict_off_reproduces_the_pre_v3_behaviour_exactly( self ):
        """
        With the flag off, every released verb blocks again. That equivalence is the
        whole point of implementing the dial as an empty exemption set rather than as
        a second branch: there is no "off" path that can drift from the "on" path.
        """
        for token in _NO_LONGER_BLOCKED:
            with self.subTest( token=token ):
                self.assertIn( token, _names( f"{token} the row", strict=False ) )

    def test_strict_off_still_blocks_everything_strict_on_blocks( self ):
        """Turning the flag off must only ever ADD blocking, never remove it."""
        for token in _STILL_BLOCKED:
            with self.subTest( token=token ):
                self.assertIn( token, _names( f"{token} reviewed it", strict=False ) )

    def test_strict_defaults_to_on_for_a_direct_caller( self ):
        """
        A caller that does not pass the flag gets the SHIPPED behaviour. A default of
        False here would mean the tests exercise one thing and production another.
        """
        self.assertEqual( [], dm._fabricated_facts( _ORIGINAL, "Verify the row" ).get( "name", [] ) )

    def test_the_config_reader_exposes_the_new_key_defaulting_true( self ):
        self.assertTrue( dm._DM_TUTOR_DEFAULTS[ "fab_guard_strict" ] )

    def test_the_config_read_asks_for_the_ruled_ini_key_name( self ):
        """
        Pins the key STRING. A typo here is invisible at runtime — ConfigurationManager
        would return the default and the dial would silently never move, which is
        exactly the failure the flag exists to prevent.
        """
        seen = {}

        class _FakeCM:
            def __init__( self, **kwargs ): pass
            def get( self, key, default=None, return_type=None ):
                seen[ key ] = default
                return default

        with patch( "cosa.config.configuration_manager.ConfigurationManager", _FakeCM ):
            cfg = dm.get_dm_tutor_config()

        self.assertIn( "dm tutor fabrication guard strict", seen )
        self.assertTrue( seen[ "dm tutor fabrication guard strict" ] )
        self.assertTrue( cfg[ "fab_guard_strict" ] )

    def test_an_unreadable_config_still_yields_a_usable_strict_value( self ):
        """
        The tutor's config read is fail-closed by design. This proves the NEW key
        participates in that contract rather than raising a KeyError at the call site
        when the fallback dict is returned.
        """
        with patch( "cosa.config.configuration_manager.ConfigurationManager",
                    side_effect=RuntimeError( "no config" ) ):
            cfg = dm.get_dm_tutor_config()
        self.assertIn( "fab_guard_strict", cfg )


# ══════════════════════════════════════════════════════════════════════════
# The cost Rick accepted, pinned so it stays visible
# ══════════════════════════════════════════════════════════════════════════

class TestTheAcceptedCost( unittest.TestCase ):

    def test_force_recreated_rewritten_as_deployed_now_ships( self ):
        """
        THE GUARD'S ONE DEMONSTRATED TRUE POSITIVE, now released. `deployed` is a
        lowercase dictionary entry, so V3-strict exempts it.

        This test asserts the LOSS on purpose. Rick was shown this exact trade and took
        it; a suite that quietly special-cased "Deployed" back would be overturning a
        ruling in a place he would never look. If this ever needs to change, it changes
        with him, not here.
        """
        self.assertEqual(
            [], _names( "Deployed the container", original="Force-recreated the container" )
        )

    def test_and_the_flag_still_catches_it_when_turned_off( self ):
        """The escape hatch is real: the old catch comes back with the dial."""
        self.assertIn(
            "Deployed",
            _names( "Deployed the container", strict=False, original="Force-recreated the container" ),
        )


# ══════════════════════════════════════════════════════════════════════════
# The curly apostrophe — same word, invisible character, opposite verdict
# ══════════════════════════════════════════════════════════════════════════

class TestApostropheNormalisation( unittest.TestCase ):

    def test_straight_and_curly_apostrophes_reach_the_same_verdict( self ):
        """
        The rewriter is a language model and emits U+2019 constantly. The vendored list
        holds ASCII apostrophes only, so without normalisation "Update's" is exempt and
        "Update’s" is blocked — identical text on screen, opposite outcomes, decided
        by a character invisible in a diff.
        """
        self.assertEqual( [], _names( "Update's plan landed" ) )
        self.assertEqual( [], _names( "Update’s plan landed" ) )

    def test_normalisation_does_not_release_a_possessive_person_name( self ):
        """
        The negative control. Normalising apostrophes must not turn "Krishna’s" into
        something exempt — it is a proper noun in either spelling.
        """
        self.assertIn( "Krishna’s", _names( "Krishna’s row moved" ) )
        self.assertIn( "Krishna's",      _names( "Krishna's row moved" ) )

    def test_strict_exempt_is_true_only_for_a_lowercase_entry( self ):
        self.assertTrue(  dm._strict_exempt( "Update", dm._FAB_LOWERCASE_WORDS ) )
        self.assertFalse( dm._strict_exempt( "Rachel", dm._FAB_LOWERCASE_WORDS ) )

    def test_strict_exempt_against_an_empty_list_exempts_nothing( self ):
        self.assertFalse( dm._strict_exempt( "Update", frozenset() ) )


# ══════════════════════════════════════════════════════════════════════════
# Loading — once, at import, and never fatally
# ══════════════════════════════════════════════════════════════════════════

class TestTheVendoredList( unittest.TestCase ):

    def test_the_vendored_list_loaded_and_is_not_empty( self ):
        self.assertGreater( len( dm._FAB_LOWERCASE_WORDS ), 50_000 )

    def test_every_vendored_entry_is_lowercase( self ):
        """
        STRICTNESS IS A PROPERTY OF THE FILE, not only of the lookup. One capitalised
        line in the vendored list would silently release a proper noun, and the lookup
        code would still look correct. Checked here so the data is guarded too.
        """
        offenders = [ w for w in dm._FAB_LOWERCASE_WORDS if w != w.lower() ]
        self.assertEqual( [], offenders[ :10 ] )

    def test_the_word_list_is_read_once_at_import_not_per_call( self ):
        """
        THE STRUCTURAL TEST MR RADIO ASKED FOR. The list is ~789 KB; re-reading it per
        DM would put a file read on the send path. This fails if the read moves back
        inside `_fabricated_facts`, because `open` would then be called during these
        comparisons.
        """
        with patch.object( builtins, "open", side_effect=AssertionError(
                "the word list must not be re-read per call — load it once at import" ) ):
            for token in _NO_LONGER_BLOCKED:
                self.assertEqual( [], _names( f"{token} the row" ) )
            for token in _STILL_BLOCKED:
                self.assertIn( token, _names( f"{token} reviewed it" ) )

    def test_an_unreadable_word_list_degrades_to_no_exemptions_and_never_raises( self ):
        """
        THE FAILURE DIRECTION, pinned. A missing list must mean MORE blocking, never
        less: an empty exemption set reproduces the pre-V3 guard. Failing toward the
        permissive side would silently disarm the guard exactly when something is
        already wrong with the deployment.
        """
        words = dm._load_lowercase_words( "/nonexistent/there-is-no-such-word-list.txt" )
        self.assertEqual( frozenset(), words )
        self.assertFalse( dm._strict_exempt( "Update", words ) )

    def test_loading_a_real_file_strips_blanks_and_whitespace( self ):
        import tempfile, os
        fd, path = tempfile.mkstemp( suffix=".txt" )
        try:
            with os.fdopen( fd, "w", encoding="utf-8" ) as fh:
                fh.write( "update\n\n  verify  \n\n" )
            self.assertEqual( frozenset( { "update", "verify" } ),
                              dm._load_lowercase_words( path ) )
        finally:
            os.unlink( path )

    def test_the_path_helper_points_inside_the_repo( self ):
        path = dm._strict_wordlist_path()
        self.assertTrue( path.endswith( "/src/conf/dm-tutor-lowercase-words.txt" ) )

    def test_the_vendored_file_actually_exists_where_the_helper_points( self ):
        """
        The instrument is checked against the file it exists to read. A path helper
        proven only against a fixture can pass while pointing at nothing — which is the
        whole class of defect the "do not read /usr/share/dict" instruction is about.
        """
        import os
        self.assertTrue( os.path.isfile( dm._strict_wordlist_path() ) )


# ══════════════════════════════════════════════════════════════════════════
# The other fact classes are untouched
# ══════════════════════════════════════════════════════════════════════════

class TestTheOtherClassesAreUnaffected( unittest.TestCase ):

    def test_strict_does_not_release_a_fabricated_sha( self ):
        self.assertEqual( [ "7848d17e" ],
                          dm._fabricated_facts( _ORIGINAL, "see 7848d17e", strict=True )[ "hex_id" ] )

    def test_strict_does_not_release_a_fabricated_number( self ):
        self.assertEqual( [ "400" ],
                          dm._fabricated_facts( _ORIGINAL, "there were 400", strict=True )[ "number" ] )

    def test_strict_does_not_release_a_fabricated_path( self ):
        self.assertIn( "src/conf/x.ini",
                       dm._fabricated_facts( _ORIGINAL, "see src/conf/x.ini", strict=True )[ "path" ] )

    def test_a_faithful_rewrite_is_still_clean( self ):
        self.assertEqual( {}, dm._fabricated_facts(
            "the queue drained and the container came back",
            "the container came back after the queue drained", strict=True ) )

    def test_a_name_the_sender_already_used_is_never_flagged( self ):
        """Novelty, not capitalisation, is what the check is about."""
        self.assertEqual( [], _names( "Rachel signed off", original="Rachel reviewed the row" ) )

    def test_the_guard_returns_empty_rather_than_raising_on_bad_input( self ):
        """
        A guard that raises would take the send path with it. Pinned because the
        try/except around the comparison is easy to remove while refactoring.
        """
        self.assertEqual( {}, dm._fabricated_facts( None, "Verify the row", strict=True ) )


class TestRedIfRemoved( unittest.TestCase ):
    """
    RED-IF-REMOVED, build item 4 of the row.

    Acceptance item 1 originally asked for "a test that goes red if the casefold is
    removed" and could not be met, because the check had been case-insensitive since
    13 Aug — there was no casefold to remove. The strict rule is a real rule, so the
    criterion is now meetable, and this is where it is met.

    Mutations run BY HAND on 2026-08-18, each confirmed to turn this file red:
      1. drop `and not _strict_exempt( c, exempt )` from the comparison
      2. `exempt = _FAB_LOWERCASE_WORDS` unconditionally (flag stops working)
      3. `exempt = frozenset()` unconditionally (strict stops working)
      4. plain V3 — exempt on any case-insensitive dictionary hit
      5. drop the curly-apostrophe normalisation
    """

    def test_the_exemption_is_what_releases_the_verbs( self ):
        """
        Mutation 1, expressed as an assertion: with the exemption set emptied, every
        released verb blocks again. If someone deletes the rule, this is the sentence
        that fails.
        """
        for token in _NO_LONGER_BLOCKED:
            with self.subTest( token=token ):
                self.assertEqual( [], _names( f"{token} the row", strict=True ) )
                self.assertIn( token, _names( f"{token} the row", strict=False ) )

