"""
Unit tests for combine_overall's note wording ( row 700a6330 ).

The Overall `note` is the only prose in the DM-quality payload — the whole teaching
surface. It is picked by comparing length against qualitative, which is a RELATIVE
ordering, so it must never be worded as ABSOLUTE harm: a top-scoring DM ( every
sub-score positive, Overall at the top of the scale ) must not be told something
"dragged it down". These tests pin the neutral wording so the harm phrasing cannot
return unnoticed.

Zero external dependencies — combine_overall is pure Python arithmetic + templating.
"""

import unittest

from cosa.agents.dm_quality_judge.judge import combine_overall


# Phrases that assert harm. The defect this file guards against is any of these
# appearing on a message whose sub-scores are all positive.
_HARM_PHRASES = [ "dragged it down", "pulled this down", "dragged the score" ]


class TestCombineOverallNote( unittest.TestCase ):

    def test_top_score_note_asserts_no_harm( self ):
        """
        length +2, directness +1, tone +1 → qualitative +1 < length +2 → Overall +2.

        This is the exact shape from row 700a6330 instance 1 ( Cheech's DM #3 ): a
        top-of-scale message. The note must state the ordering without claiming harm.
        """
        result = combine_overall( 2, 1, 1, "53 words, target ~60" )

        self.assertEqual( result[ "weight" ], 2, "should be top of scale" )
        for phrase in _HARM_PHRASES:
            self.assertNotIn(
                phrase, result[ "note" ],
                f"harm phrase '{phrase}' fired on an all-positive, top-scoring DM: {result[ 'note' ]!r}"
            )
        # And it should still name which side scored lower ( qualitative < length here ).
        self.assertIn( "scored below", result[ "note" ] )

    def test_length_lower_note_asserts_no_harm( self ):
        """
        length -2, directness +2, tone +2 → length below qualitative.

        The symmetric branch must also be neutral — no "pulled this down".
        """
        result = combine_overall( -2, 2, 2, "300 words, target ~60" )

        for phrase in _HARM_PHRASES:
            self.assertNotIn(
                phrase, result[ "note" ],
                f"harm phrase '{phrase}' fired: {result[ 'note' ]!r}"
            )
        self.assertIn( "scored below", result[ "note" ] )

    def test_balanced_branch_unchanged( self ):
        """When length and qualitative agree, the note says so — not a comparison."""
        result = combine_overall( 1, 1, 1, "60 words, target ~60" )
        self.assertIn( "Balanced", result[ "note" ] )


if __name__ == "__main__":
    unittest.main()
