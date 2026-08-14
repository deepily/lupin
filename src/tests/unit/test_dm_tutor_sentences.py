#!/usr/bin/env python3
"""
Unit tests for the DM tutor's pointer predicate — the token-level restore (row a74f2176).

The send-path suite (test_dm_tutor_send_path.py) exercises the restore THROUGH the
tutor. This file pins the predicate DIRECTLY: what `pointer_tokens` extracts, and the
fact that a whole-line pointer of every shape counts as structure while the same token
mid-sentence still counts as a claim. The two must never disagree — a line that is
nothing but a pointer is preserved; a pointer buried in prose is a claim that also gets
its token lifted out and restored.
"""

import unittest

from cosa.agents.dm_tutor.sentences import pointer_tokens, count_sentences


class TestPointerTokens( unittest.TestCase ):
    """Every shape the predicate must see, wherever it sits in the body."""

    def test_a_url_is_a_token( self ):
        self.assertEqual( pointer_tokens( "grab it from https://x.io/a/b now" ),
                          [ "https://x.io/a/b" ] )

    def test_a_slashed_path_with_line_is_a_token( self ):
        self.assertEqual( pointer_tokens( "the leak is at src/foo.py:42 today" ),
                          [ "src/foo.py:42" ] )

    def test_a_bare_filename_mid_sentence_is_a_token( self ):
        """The shape the line-anchored restore could not see — no slash."""
        self.assertEqual( pointer_tokens( "look in running_fifo_queue.py:422 for it" ),
                          [ "running_fifo_queue.py:422" ] )

    def test_a_bare_8_hex_row_id_mid_sentence_is_a_token( self ):
        self.assertEqual( pointer_tokens( "recording to row e0bb5a94 for continuity" ),
                          [ "e0bb5a94" ] )

    def test_a_plain_8_digit_number_is_not_a_row_id( self ):
        """A year or a count carries no hex letter, so it must never be mistaken for a row."""
        self.assertEqual( pointer_tokens( "there were 12345678 rows on 20260813" ), [] )

    def test_a_40_char_sha_does_not_yield_a_spurious_8_hex_token( self ):
        """Word boundaries keep the predicate from slicing 8 hex out of a longer run."""
        long_sha = "abc12345def67890abc12345def67890abc12345"
        self.assertEqual( pointer_tokens( f"full sha {long_sha} here" ), [] )

    def test_all_four_shapes_in_one_body( self ):
        body = ( "url https://x.io/a and path src/foo.py:9 and "
                 "file job.py:1163 and row 0c4e8cfa done" )
        self.assertEqual(
            pointer_tokens( body ),
            [ "https://x.io/a", "src/foo.py:9", "job.py:1163", "0c4e8cfa" ],
        )

    def test_a_repeated_token_is_de_duplicated_first_seen_order( self ):
        """The dedup branch — a token seen twice is returned once, in first-seen order."""
        body = "job.py:1 then e0bb5a94 then job.py:1 again"
        self.assertEqual( pointer_tokens( body ), [ "job.py:1", "e0bb5a94" ] )

    def test_a_body_with_no_pointer_returns_empty( self ):
        self.assertEqual( pointer_tokens( "just plain prose with no pointer at all" ), [] )

    def test_a_pointer_inside_a_code_fence_is_ignored( self ):
        """Fenced material is quoted, not a pointer the sender is asserting."""
        self.assertEqual( pointer_tokens( "```\nsrc/foo.py:42\n```" ), [] )


class TestWholeLinePointerIsStructure( unittest.TestCase ):
    """
    Each pointer shape, ALONE on its line, asserts nothing → structure → 0 claims. The
    same token mid-sentence still carries the claim around it → counts. This is the
    property that lets the restore append a bare token as its own line without ever
    pushing the message back over the trigger.
    """

    def test_a_bare_filename_line_is_structure( self ):
        self.assertEqual( count_sentences( "running_fifo_queue.py:422" ), 0 )

    def test_a_bare_row_id_line_is_structure( self ):
        self.assertEqual( count_sentences( "e0bb5a94" ), 0 )

    def test_a_url_line_is_structure( self ):
        self.assertEqual( count_sentences( "https://x.io/a/b" ), 0 )

    def test_the_same_filename_mid_sentence_still_counts( self ):
        self.assertEqual( count_sentences( "Fix the leak in running_fifo_queue.py:422 today." ), 1 )

    def test_the_same_row_id_mid_sentence_still_counts( self ):
        self.assertEqual( count_sentences( "I am recording to row e0bb5a94 now." ), 1 )

    def test_every_structure_line_shape_contributes_no_claim( self ):
        """
        One body carrying every structure shape the counter must discard — a blank
        line, a table rule, a table row, a heading, a horizontal rule, and the canned
        P.S. — plus a single claim. The count is 1: only the claim survives.
        """
        body = (
            "The one real claim is here.\n"
            "\n"
            "| col | col |\n"
            "|-----|-----|\n"
            "| a   | b   |\n"
            "## A heading\n"
            "***\n"
            "P.S. Need more detail? Ask me one question only!\n"
            "This DM was condensed in transit. Need more detail? Ask the sender one question"
        )
        self.assertEqual( count_sentences( body ), 1 )

    def test_a_clean_rewrite_plus_appended_pointer_lines_stays_at_three( self ):
        """The delivered shape after a repair: three claims, then pointer-only lines."""
        delivered = ( "Krishna has the row.\n"
                      "The theory is refuted.\n"
                      "Tell me if you agree.\n"
                      "running_fifo_queue.py:422\n"
                      "e0bb5a94" )
        self.assertEqual( count_sentences( delivered ), 3 )


if __name__ == "__main__":
    unittest.main()
