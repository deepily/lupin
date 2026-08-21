#!/usr/bin/env python3
"""
Positional sentinels resolve to real option labels (row 9046ef58).

WHY THIS EXISTS. The document choice card's option labels are filenames discovered
while a run is in flight, so a Q&A script cannot name one. The first attempt wrote a
DIRECTIVE in the entry — "Pick the first document option in the list" — trusting the
matcher prompt to turn it into a label. On a live presentation job the matcher returned
the directive verbatim, the expeditor saw a label the card had never offered, refused
to guess which document was meant, and the run cancelled. These tests pin the resolver
that replaced it.
"""

import unittest

from cosa.agents.notification_proxy import option_sentinels as sentinels


DESCRIBE = "Let me describe it instead"
CANCEL   = "Cancel"
ESCAPES  = ( DESCRIBE, CANCEL )


def _card( *labels ):
    """A notification shaped like the multiple-choice card the expeditor sends."""
    return { "response_options": { "questions": [
        { "options": [ { "label": l, "description": "" } for l in labels ] }
    ] } }


class TestIsSentinel( unittest.TestCase ):

    def test_the_two_tokens_are_sentinels( self ):
        self.assertTrue( sentinels.is_sentinel( "__first_option__" ) )
        self.assertTrue( sentinels.is_sentinel( "__last_option__" ) )

    def test_surrounding_whitespace_is_tolerated( self ):
        self.assertTrue( sentinels.is_sentinel( "  __first_option__\n" ) )

    def test_prose_containing_a_sentinel_is_not_one( self ):
        # A sentinel is a token, not a phrase. If a partial match counted, the exact
        # prose answer that caused this row would start "working" by accident and the
        # entry would never be corrected.
        self.assertFalse( sentinels.is_sentinel( "pick __first_option__ please" ) )
        self.assertFalse( sentinels.is_sentinel( "Pick the first document option in the list" ) )

    def test_the_match_is_case_sensitive( self ):
        # MARÍA'S POINT. A sentinel's entire job is to be unambiguous; case-folding
        # would make it a fuzzy match on a token. The near-miss is not merely "not a
        # sentinel" — resolve() raises on it, asserted below.
        # RED ON REVERT (case-folding restored): AssertionError: True is not false
        for variant in ( "__FIRST_OPTION__", "__First_Option__", "__LAST_OPTION__" ):
            with self.subTest( variant=variant ):
                self.assertFalse( sentinels.is_sentinel( variant ) )

    def test_ordinary_answers_are_not_sentinels( self ):
        for answer in ( "general", "default", "yes", "", None, 7, [ "__first_option__" ] ):
            with self.subTest( answer=answer ):
                self.assertFalse( sentinels.is_sentinel( answer ) )


class TestOptionLabels( unittest.TestCase ):

    def test_labels_come_back_in_card_order( self ):
        self.assertEqual(
            sentinels.option_labels( _card( "a.md", "b.md", DESCRIBE, CANCEL ) ),
            [ "a.md", "b.md", DESCRIBE, CANCEL ],
        )

    def test_blank_and_missing_labels_are_dropped_not_yielded_empty( self ):
        card = { "response_options": { "questions": [ { "options": [
            { "label": "  " }, { "description": "no label at all" }, { "label": " a.md " },
        ] } ] } }
        self.assertEqual( sentinels.option_labels( card ), [ "a.md" ] )

    def test_a_notification_without_options_yields_nothing( self ):
        for card in ( {}, { "response_options": None }, { "response_options": {} },
                      { "response_options": { "questions": None } },
                      { "response_options": { "questions": [ { } ] } },
                      { "response_options": { "questions": [ { "options": None } ] } } ):
            with self.subTest( card=card ):
                self.assertEqual( sentinels.option_labels( card ), [] )

    def test_labels_across_several_questions_are_concatenated( self ):
        card = { "response_options": { "questions": [
            { "options": [ { "label": "a.md" } ] },
            { "options": [ { "label": "b.md" } ] },
        ] } }
        self.assertEqual( sentinels.option_labels( card ), [ "a.md", "b.md" ] )


class TestLooksLikeASentinel( unittest.TestCase ):

    def test_typos_and_case_variants_still_look_like_sentinels( self ):
        # This is what lets a typo be CAUGHT rather than forwarded: the shape is
        # recognised even when the token is not.
        for value in ( "__frist_option__", "__FIRST_OPTION__", "__second_option__" ):
            with self.subTest( value=value ):
                self.assertTrue( sentinels.looks_like_a_sentinel( value ) )

    def test_real_sentinels_look_like_sentinels( self ):
        for value in sentinels.SENTINELS:
            with self.subTest( value=value ):
                self.assertTrue( sentinels.looks_like_a_sentinel( value ) )

    def test_ordinary_answers_do_not( self ):
        for value in ( "general", "", None, 7, "__not closed", "pick __first_option__" ):
            with self.subTest( value=value ):
                self.assertFalse( sentinels.looks_like_a_sentinel( value ) )


class TestResolve( unittest.TestCase ):

    def test_an_ordinary_answer_passes_straight_through( self ):
        # The pass-through is what lets this sit in the responder's hot path without
        # touching any other entry in any other script.
        self.assertEqual( sentinels.resolve( "general", _card( "a.md" ) ), "general" )
        self.assertIsNone( sentinels.resolve( None, _card( "a.md" ) ) )

    def test_first_option_picks_the_first_real_candidate( self ):
        card = _card( "kiss.md", "quantum.md", DESCRIBE, CANCEL )
        self.assertEqual(
            sentinels.resolve( "__first_option__", card, excluded_labels=ESCAPES ), "kiss.md" )

    def test_last_option_picks_the_last_real_candidate( self ):
        # Without the exclusions this would select Cancel, which reads to the
        # expeditor as the user declining — a green-looking run that did nothing.
        card = _card( "kiss.md", "quantum.md", DESCRIBE, CANCEL )
        self.assertEqual(
            sentinels.resolve( "__last_option__", card, excluded_labels=ESCAPES ), "quantum.md" )

    def test_the_escapes_are_never_selectable( self ):
        card = _card( DESCRIBE, CANCEL )
        self.assertIsNone( sentinels.resolve( "__first_option__", card, excluded_labels=ESCAPES ) )
        self.assertIsNone( sentinels.resolve( "__last_option__",  card, excluded_labels=ESCAPES ) )

    def test_exclusion_ignores_case_and_padding( self ):
        card = _card( "  cancel  ", "kiss.md" )
        self.assertEqual(
            sentinels.resolve( "__first_option__", card, excluded_labels=( "CANCEL", ) ), "kiss.md" )

    def test_with_no_exclusions_every_label_is_fair_game( self ):
        self.assertEqual( sentinels.resolve( "__first_option__", _card( "a.md", "b.md" ) ), "a.md" )

    def test_a_typod_sentinel_raises_rather_than_forwarding_a_literal( self ):
        # MARÍA'S SECOND POINT, and it is defect #2 under a new name: an unrecognised
        # __…__ value falling through as a literal is exactly the prose-submitted-as-a-
        # label failure the sentinels were introduced to kill.
        # RED ON REVERT (raise removed): the call returns '__frist_option__' and
        # assertRaises fails with "ValueError not raised".
        for bad in ( "__frist_option__", "__FIRST_OPTION__", "__second_option__" ):
            with self.subTest( bad=bad ):
                with self.assertRaises( ValueError ) as caught:
                    sentinels.resolve( bad, _card( "a.md" ) )
                # The message must name the offending value AND the valid set, so the
                # fix is obvious from the log line alone.
                self.assertIn( bad, str( caught.exception ) )
                self.assertIn( "__first_option__", str( caught.exception ) )

    def test_an_unresolvable_sentinel_returns_none_not_the_sentinel( self ):
        # THE IMPORTANT ONE. Returning the sentinel string would submit
        # "__first_option__" as if it were a label — the expeditor rejects it and the
        # run cancels for a reason invisible from the outside. None makes the caller
        # report a skip out loud.
        self.assertIsNone( sentinels.resolve( "__first_option__", {} ) )
        self.assertNotEqual( sentinels.resolve( "__first_option__", {} ), "__first_option__" )


if __name__ == "__main__":
    unittest.main()
