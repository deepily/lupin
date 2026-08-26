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

from cosa.agents.dm_tutor.sentences import pointer_tokens, count_sentences, is_bare_identifier, restorable_pointers


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


class TestSlashEnumerationsAreNotPointers( unittest.TestCase ):
    """
    🔴 REGRESSION, row 206dd6ea (María, 2026-08-15). The slashed-path shape matched a
    slash-separated ENUMERATION and a bare RATIO as if it were a file path. The token
    was then lifted out and re-appended as its own line, so a clean rewrite arrived with
    a garbage final line that read as a message truncated mid-word — three live DMs
    delivered "training/", "SCHEDULED/PAUSED", and "pending/running/terminal" that way.

    The predicate now keeps a token only when it carries a positive path signal.
    """

    def test_a_bare_word_with_a_trailing_slash_is_not_a_pointer( self ):
        """The exact fragment that shipped: "§5.3: training/ has five files"."""
        self.assertEqual( pointer_tokens( "§5.3: training/ has five files in two namespaces" ), [] )

    def test_a_numeric_ratio_is_not_a_pointer( self ):
        self.assertEqual( pointer_tokens( "Tiberius reads 10/10 where you cite 6/10 today" ), [] )

    def test_an_uppercase_two_way_enumeration_is_not_a_pointer( self ):
        self.assertEqual( pointer_tokens( "answer the SCHEDULED/PAUSED question in the doc" ), [] )

    def test_a_lowercase_three_way_enumeration_is_not_a_pointer( self ):
        """Two slashes is not enough on its own — the enum has no path signal."""
        self.assertEqual( pointer_tokens( "the states pending/running/terminal are covered" ), [] )

    def test_a_real_trailing_slash_directory_still_survives( self ):
        """A genuine multi-segment directory keeps its trailing-slash form."""
        self.assertEqual( pointer_tokens( "src/conf/training/ holds two namespaces" ),
                          [ "src/conf/training/" ] )

    def test_an_absolute_path_survives( self ):
        self.assertEqual( pointer_tokens( "written to /mnt/DATA01/x.md just now" ),
                          [ "/mnt/DATA01/x.md" ] )

    def test_a_home_path_survives( self ):
        self.assertEqual( pointer_tokens( "the key is in ~/.claude/settings.json today" ),
                          [ "~/.claude/settings.json" ] )

    def test_a_real_path_and_a_ratio_in_one_body_keeps_only_the_path( self ):
        """The mixed shape from the live DM: a real filename:line beside a ratio and an enum."""
        body = "leak at test_suite.py:181, answer SCHEDULED/PAUSED, Tiberius reads 10/10"
        self.assertEqual( pointer_tokens( body ), [ "test_suite.py:181" ] )


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

    def test_the_four_word_variant_of_the_notice_is_also_structure( self ):
        """
        Row `20026f56` added a second notice — the same opening sentence plus "Check who
        did what." — for the messages the attribution check fires on.

        The exemption is prefix-anchored (`^\\s*This DM was condensed in transit\\..*$`), so
        the extra words land inside the `.*` and it still matches. That is a property of
        the pattern rather than of anyone's care, and this is what proves it: re-anchor
        the pattern to the end of the old wording and this line starts counting as a
        claim, which is the tutor rewriting its own footer forever.
        """
        body = (
            "The one real claim is here.\n"
            "This DM was condensed in transit. Check who did what. Need more detail? "
            "Ask the sender one question"
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


class TestRestorablePointersIsNarrowerThanPointerTokens( unittest.TestCase ):
    """
    Two selectors, and keeping them SEPARATE is the whole design (row a0151611).

    `pointer_tokens` is the body of the whole-line structure rule, so narrowing it
    would silently change the sentence counter — a delivered pointer line would start
    counting as a claim and a repaired message could re-trigger the tutor. Only the
    RESTORE path is narrowed, and this class pins both halves: what the counter sees is
    unchanged, and what comes back after a rewrite is paths only.
    """

    _BODY = ( "The leak is in running_fifo_queue.py:422 and the probe is at "
              "/tmp/claude-1001/scratchpad/repro.py, recording to row e0bb5a94.\n"
              "See https://example.com/x for the write-up." )

    def test_a_bare_row_id_is_a_bare_identifier( self ):
        self.assertTrue( is_bare_identifier( "e0bb5a94" ) )

    def test_paths_urls_and_filenames_are_not( self ):
        for token in ( "/tmp/claude-1001/scratchpad/repro.py", "running_fifo_queue.py:422",
                       "job.py", "https://example.com/x", "src/rnd/note.md" ):
            with self.subTest( token=token ):
                self.assertFalse( is_bare_identifier( token ),
                                  f"{token} says where to look — it must stay restorable" )

    def test_restorable_pointers_drops_the_id_and_keeps_the_rest( self ):
        self.assertEqual( restorable_pointers( self._BODY ),
                          [ "running_fifo_queue.py:422", "/tmp/claude-1001/scratchpad/repro.py",
                            "https://example.com/x" ] )

    def test_pointer_tokens_still_sees_the_id( self ):
        """
        THE CONTROL FOR THE TRAP. If this ever goes red, someone narrowed
        `pointer_tokens` in place and the sentence counter moved with it.
        """
        self.assertIn( "e0bb5a94", pointer_tokens( self._BODY ) )

    def test_a_body_of_only_ids_is_restorable_by_nothing( self ):
        self.assertEqual( restorable_pointers( "Rows a0151611 and adf5c1a1 are open." ), [] )

    def test_a_body_with_no_pointer_at_all( self ):
        self.assertEqual( restorable_pointers( "Plain prose with no pointer." ), [] )

    def test_a_RUN_of_pointers_on_one_line_is_structure( self ):
        """
        The shape the restore now emits when a rewrite drops two paths. A line of
        nothing but pointers asserts nothing however many it carries — and if the
        counter disagreed, the repair would push the message one claim over the
        trigger and the tutor could re-fire on the line it had just appended.
        """
        three = ( "Verdict.\nSupport one.\nSupport two.\n"
                  "src/a.py src/b.py https://example.com/x" )
        self.assertEqual( count_sentences( three ), 3 )

    def test_the_run_rule_does_not_stall_on_a_long_near_miss( self ):
        """
        The widened rule repeats a group, which is the shape that goes exponential when
        a long line ALMOST matches and the engine backtracks through every split. The
        near-miss is the case to fear: 120 real paths followed by one token that is not
        a pointer, so the whole line must be rejected. Measured at ~0.0002s; the ceiling
        below is three orders of magnitude of headroom, so it fails on a stall, not on a
        slow machine.
        """
        import time
        near_miss = " ".join( f"src/a{i}.py" for i in range( 120 ) ) + " not-a-pointer!"
        started   = time.time()
        self.assertEqual( count_sentences( near_miss ), 1 )   # prose, not structure
        self.assertLess( time.time() - started, 2.0,
                         "the pointer-run rule backtracked instead of failing fast" )

    def test_a_long_run_of_real_paths_is_still_structure( self ):
        """The other end of the same shape: it must match, and match fast."""
        run = " ".join( f"src/a{i}.py" for i in range( 200 ) )
        self.assertEqual( count_sentences( f"Verdict.\n{run}" ), 1 )

    def test_a_line_of_PROSE_is_not_rescued_by_the_run_rule( self ):
        """CONTROL. Widening the rule must not turn a claim into structure."""
        self.assertEqual( count_sentences( "Verdict.\nSupport one.\n"
                                           "The fix landed in src/a.py and src/b.py." ), 3 )


if __name__ == "__main__":
    unittest.main()
