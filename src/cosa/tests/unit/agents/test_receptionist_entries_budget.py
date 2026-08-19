#!/usr/bin/env python3
"""
Control for the receptionist's memory token budget — row a203d91d.

The defect: the memory block was bounded by a ROW COUNT (50). A row cap cannot bound
a token budget, because rows vary in size — 50 rows measured 3,345 tokens on the night
this was filed, and the prompt came to 4,136 against a 4,096 ceiling.

Hermetic: fit_fragments_to_budget takes its token counter as an argument, so these run
with no model server. The counter here is words, which keeps the arithmetic readable.
"""

import unittest

from cosa.agents.receptionist_agent import fit_fragments_to_budget


def words( text ): return len( text.split() )


# Newest first, matching the repository's ORDER BY id DESC.
FRAGMENTS = [ "n5 e", "n4 d", "n3 c", "n2 b", "n1 a" ]


class TestFitFragmentsToBudget( unittest.TestCase ):

    def test_a_generous_budget_keeps_everything_oldest_first( self ):
        """
        Ensures:
            - nothing is dropped when it all fits
            - the block reads chronologically, oldest first, though input is newest first
        """
        block = fit_fragments_to_budget( FRAGMENTS, budget=100, count_tokens=words )
        self.assertEqual( block.split( "\n" ), [ "n1 a", "n2 b", "n3 c", "n4 d", "n5 e" ] )

    def test_a_tight_budget_keeps_the_NEWEST_that_fit( self ):
        """
        The whole point: what survives is the recent conversation, not an arbitrary
        subset and not the oldest rows.

        Ensures:
            - a 4-token budget keeps exactly the two newest fragments
            - they are still oldest-first within the block
        """
        block = fit_fragments_to_budget( FRAGMENTS, budget=4, count_tokens=words )
        self.assertEqual( block.split( "\n" ), [ "n4 d", "n5 e" ] )

    def test_the_result_never_exceeds_the_budget( self ):
        """Ensures: the returned block is measured, not estimated, against the budget."""
        for budget in range( 0, 12 ):
            block = fit_fragments_to_budget( FRAGMENTS, budget=budget, count_tokens=words )
            if block: self.assertLessEqual( words( block ), budget )

    def test_a_budget_too_small_for_even_one_fragment_yields_nothing( self ):
        """Ensures: an impossible budget returns "" rather than overshooting by one."""
        self.assertEqual( fit_fragments_to_budget( FRAGMENTS, budget=1, count_tokens=words ), "" )

    def test_no_fragments_or_no_budget_is_empty( self ):
        """Ensures: the degenerate inputs do not call the counter at all."""
        def explode( _ ): raise AssertionError( "counter must not be called" )
        self.assertEqual( fit_fragments_to_budget( [ ], budget=99, count_tokens=explode ), "" )
        self.assertEqual( fit_fragments_to_budget( FRAGMENTS, budget=0, count_tokens=explode ), "" )

    def test_sizing_is_logarithmic_not_one_call_per_fragment( self ):
        """
        Ensures:
            - 50 fragments are sized in far fewer than 50 counter calls, so bounding
              the block does not cost one round trip per row
        """
        calls = [ ]
        def counting( text ):
            calls.append( text )
            return words( text )

        many = [ f"row{n} x" for n in range( 50 ) ]
        fit_fragments_to_budget( many, budget=20, count_tokens=counting )

        self.assertLess( len( calls ), 12 )


class TestTheReportedDefect( unittest.TestCase ):

    def test_the_night_this_was_filed( self ):
        """
        Reproduces the measured numbers: 50 rows at ~67 tokens each against a budget of
        window//2 minus the 791-token template.

        Ensures:
            - the block is trimmed to fit rather than sent whole
            - the surviving block plus the template stays inside half the window
        """
        window, template = 8192, 791
        budget = window // 2 - template                      # 3305
        rows   = [ "t " * 67 for _ in range( 50 ) ]          # ~67 tokens each, 3350 total

        block = fit_fragments_to_budget( rows, budget=budget, count_tokens=words )

        self.assertLessEqual( words( block ), budget )
        self.assertLessEqual( words( block ) + template, window // 2 )
        self.assertGreater( words( block ), 0 )


if __name__ == "__main__":
    unittest.main()


class TestTheAgentActuallyAppliesTheBudget( unittest.TestCase ):
    """
    The wiring control: _get_df_metadata must route the fragments through the budget.

    Driven with a stand-in `self` carrying only what that method touches, so no config,
    no database and no model server are involved.
    """

    class _Rows:
        def __init__( self, rows ): self._rows = rows
        def get_all_qnr( self ): return self._rows

    def _stand_in( self, rows, budget ):
        from cosa.agents.receptionist_agent import ReceptionistAgent

        class StandIn:
            io_tbl          = TestTheAgentActuallyAppliesTheBudget._Rows( rows )
            prompt_template = "template"
            def _entries_token_budget( self ):     return budget
            def _count_tokens( self, text ):       return words( text )

        return ReceptionistAgent._get_df_metadata( StandIn() )

    def test_entries_are_trimmed_to_the_budget( self ):
        """
        Ensures:
            - with three rows and room for two, only the two NEWEST reach the prompt
            - dropping the budget from the call site fails this test
        """
        rows = [
            { "date": "d3", "input": "newest", "output_final": "c" },
            { "date": "d2", "input": "middle", "output_final": "b" },
            { "date": "d1", "input": "oldest", "output_final": "a" },
        ]
        one_fragment = words(
            "<memory-fragment> <date>d3</date/> <human-queried>newest</human-queried>"
            " <ai-answered>c</ai-answered> </memory-fragment>"
        )

        _, entries = self._stand_in( rows, budget=one_fragment * 2 )

        self.assertIn( "newest", entries )
        self.assertIn( "middle", entries )
        self.assertNotIn( "oldest", entries )

    def test_a_generous_budget_keeps_every_row( self ):
        """Ensures: the budget is a ceiling, not a fixed-size window."""
        rows = [ { "date": "d2", "input": "b", "output_final": "B" },
                 { "date": "d1", "input": "a", "output_final": "A" } ]

        _, entries = self._stand_in( rows, budget=10_000 )

        self.assertIn( "a", entries )
        self.assertIn( "b", entries )
