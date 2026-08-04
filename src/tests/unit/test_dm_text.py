"""
Unit tests for the shared DM word-count module (plan item 1).

dm_word_count centralizes the `len( text.split() )` that was duplicated verbatim at
four sites (dm.py x2, judge.py, judge_v2.py). These tests pin its contract and the
version constant that only means something once the count lives in one place.

Design: src/rnd/v0.2.0/2026.08.04-dm-verbosity-reduction/2026.08.04-dm-verbosity-pilot-plan.md §1
"""

import unittest

from cosa.utils.dm_text import dm_word_count, WORD_COUNT_VERSION


class TestDmWordCount( unittest.TestCase ):

    def test_empty_string_is_zero( self ):
        self.assertEqual( dm_word_count( "" ), 0 )

    def test_whitespace_only_is_zero( self ):
        """A blank body is zero words, not one — `"   ".split()` is []."""
        self.assertEqual( dm_word_count( "   \t \n " ), 0 )

    def test_simple_sentence( self ):
        self.assertEqual( dm_word_count( "one two three" ), 3 )

    def test_collapses_runs_of_whitespace( self ):
        """Whitespace splitting collapses multiple separators — 'a   b' is 2, not 4."""
        self.assertEqual( dm_word_count( "a   b\tc\nd" ), 4 )

    def test_matches_the_inline_form_it_replaced( self ):
        """CONTROL — the centralized count must equal the four inline copies it replaced,
        or the migration silently changed a measured value."""
        for body in ( "", "hello", "a  b   c", "line one\nline two here" ):
            self.assertEqual( dm_word_count( body ), len( body.split() ) )

    def test_version_constant_is_one( self ):
        """word_count_version 1 = whitespace split. Bumping the algorithm bumps this."""
        self.assertEqual( WORD_COUNT_VERSION, 1 )

    def test_non_string_fails_loud( self ):
        """A None body is a caller bug — fail loud (AttributeError), never coerce."""
        with self.assertRaises( AttributeError ):
            dm_word_count( None )


if __name__ == "__main__":
    unittest.main()
