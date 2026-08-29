#!/usr/bin/env python3
"""
Regression tests for the pool-exhaustion hang in cosa.agents.two_word_id_generator.

Field incident 2026-08-19: the pinned v1 baseline server on :7997 stopped answering
after ~1340 routed jobs. It was not deadlocked and it was not waiting on I/O — 32
threads were all runnable, splitting exactly 1.03 cores through the GIL, and the
busiest of them had 246 CPU-seconds against 20 read syscalls for its whole life.
They were all inside TwoWordIdGenerator.get_id(), drawing random adjective/noun
pairs from a 32 x 32 = 1024-name pool that had been completely used up. Every draw
collided, so the loop could never return. AgentBase.__init__ calls get_id() once per
routed job, so from the 1025th job onward every job hung on construction.

This file carries a CONTROL that proves the old loop cannot terminate on a full
pool, and the tests that prove the fixed generator does.

Guard-free by design (no legacy test-infra import), so it always collects.
"""

import random
import re
import threading
import time
import unittest

from cosa.agents.two_word_id_generator import TwoWordIdGenerator

# The shape a browser session id must have to be allowed onto a WebSocket. Kept in
# step with is_valid_session_id() in cosa/rest/routers/websocket.py, which is the
# gate at websocket.py:228 and :380. Copied rather than imported so this file stays
# free of the router's import chain.
BROWSER_SESSION_ID_PATTERN = r"^[a-z]+ [a-z]+$"


def legacy_get_id( adjectives, nouns, generated_ids, max_draws ):
    """
    The pre-fix loop body, verbatim, but with a draw budget so the test cannot hang.

    Requires:
        - adjectives and nouns are non-empty lists
        - generated_ids is a set
        - max_draws is a positive integer

    Ensures:
        - Returns the first unused "adjective noun" pair it draws
        - Returns None once max_draws draws have all collided — the real loop had no
          budget and would keep drawing forever at that point

    Raises:
        - None
    """
    for _ in range( max_draws ):
        combination = f"{random.choice( adjectives )} {random.choice( nouns )}"
        if combination not in generated_ids:
            generated_ids.add( combination )
            return combination
    return None


class TestTwoWordIdGeneratorExhaustion( unittest.TestCase ):
    """Proves the exhaustion hang existed and that the fixed generator does not hang."""

    def setUp( self ):
        """Snapshot the process-wide singleton so these tests leak no state."""
        self.gen          = TwoWordIdGenerator()
        self._saved_ids   = set( self.gen.generated_ids )
        self._saved_cycle = self.gen._cycle
        self.gen.generated_ids.clear()
        self.gen._cycle = 1

    def tearDown( self ):
        """Restore the singleton exactly as it was found."""
        self.gen.generated_ids.clear()
        self.gen.generated_ids.update( self._saved_ids )
        self.gen._cycle = self._saved_cycle

    # ---- CONTROL: the defect is real -------------------------------------------------

    def test_control_legacy_loop_cannot_terminate_on_a_full_pool( self ):
        """
        CONTROL for the field hang: with every name taken, the old loop never returns.

        Requires:
            - The word lists produce a finite pool

        Ensures:
            - Filling the pool with all len(adjectives) * len(nouns) names leaves the
              legacy loop with no free name to land on
            - 50,000 consecutive draws all collide, so the unbudgeted original could
              only have spun on CPU forever — which is what the server was doing

        Raises:
            - None
        """
        adjectives = self.gen.adjectives
        nouns      = self.gen.nouns
        full_pool  = { f"{a} {n}" for a in adjectives for n in nouns }
        self.assertEqual( len( full_pool ), len( adjectives ) * len( nouns ) )
        self.assertEqual( len( full_pool ), 1024 )                       # the pool the server ran out of

        self.assertIsNone( legacy_get_id( adjectives, nouns, full_pool, max_draws=50_000 ) )

    def test_control_legacy_loop_still_returns_while_the_pool_has_room( self ):
        """
        Negative half of the control: the old loop was fine until the pool ran dry.

        Requires:
            - A pool with at least one free name

        Ensures:
            - The legacy loop returns a name well inside its draw budget
            - The failure was exhaustion, not the draw-and-retry idea itself

        Raises:
            - None
        """
        adjectives = self.gen.adjectives
        nouns      = self.gen.nouns
        nearly_full = { f"{a} {n}" for a in adjectives for n in nouns }
        nearly_full.discard( "wise owl" )

        self.assertEqual( legacy_get_id( adjectives, nouns, nearly_full, max_draws=50_000 ), "wise owl" )

    # ---- THE FIX ---------------------------------------------------------------------

    def test_get_id_returns_when_the_pool_is_exhausted( self ):
        """
        The fixed generator hands out a name instead of spinning once cycle 1 is full.

        Requires:
            - The singleton has been reset by setUp

        Ensures:
            - get_id() returns within one second on a completely full first cycle
            - The name carries the cycle-2 suffix and is not a repeat

        Raises:
            - None
        """
        self.gen.generated_ids.update( f"{a} {n}" for a in self.gen.adjectives for n in self.gen.nouns )

        started = time.monotonic()
        result  = self.gen.get_id()
        elapsed = time.monotonic() - started

        self.assertLess( elapsed, 1.0 )
        self.assertTrue( result.endswith( "a" ), f"expected a cycle-2 name, got [{result}]" )
        self.assertEqual( len( result.split() ), 2 )

    def test_field_incident_volume_completes( self ):
        """
        Reproduces the incident volume: 1340 ids, the count that wedged the server.

        Requires:
            - The singleton has been reset by setUp

        Ensures:
            - All 1340 calls return
            - Every id is unique
            - The generator has rolled past the 1024-name first cycle

        Raises:
            - None
        """
        ids = [ self.gen.get_id() for _ in range( 1340 ) ]

        self.assertEqual( len( ids ), 1340 )
        self.assertEqual( len( set( ids ) ), 1340 )
        self.assertGreater( self.gen._cycle, 1 )

    def test_third_cycle_opens_after_two_full_ones( self ):
        """
        Two full cycles roll to a third, so the fix is not a one-shot escape hatch.

        Requires:
            - The singleton has been reset by setUp

        Ensures:
            - Drawing 2 * 1024 + 1 ids reaches cycle 3
            - The last id carries the cycle-3 suffix

        Raises:
            - None
        """
        names_per_cycle = len( self.gen.adjectives ) * len( self.gen.nouns )

        for _ in range( 2 * names_per_cycle ):
            self.gen.get_id()
        result = self.gen.get_id()

        self.assertEqual( self.gen._cycle, 3 )
        self.assertTrue( result.endswith( "b" ), f"expected a cycle-3 name, got [{result}]" )

    def test_cycle_skips_forward_when_the_set_is_pre_loaded( self ):
        """
        The cycle counter catches up in one call when several cycles are already spent.

        Requires:
            - The singleton has been reset by setUp

        Ensures:
            - Seeding three cycles' worth of names moves the counter straight to cycle 4
            - Drives the multi-step arm of the cycle-advance loop

        Raises:
            - None
        """
        names_per_cycle = len( self.gen.adjectives ) * len( self.gen.nouns )
        self.gen.generated_ids.update( f"seeded-{i}" for i in range( 3 * names_per_cycle ) )

        result = self.gen.get_id()

        self.assertEqual( self.gen._cycle, 4 )
        self.assertTrue( result.endswith( "c" ), f"expected a cycle-4 name, got [{result}]" )

    def test_concurrent_callers_never_receive_a_duplicate( self ):
        """
        Sixteen threads calling at once get 1024 distinct ids, not a torn check-then-add.

        Requires:
            - The singleton has been reset by setUp

        Ensures:
            - 16 threads x 64 calls all return
            - No two callers receive the same id

        Raises:
            - None
        """
        collected = []
        guard     = threading.Lock()

        def worker():
            mine = [ self.gen.get_id() for _ in range( 64 ) ]
            with guard:
                collected.extend( mine )

        threads = [ threading.Thread( target=worker ) for _ in range( 16 ) ]
        for t in threads: t.start()
        for t in threads: t.join( timeout=30 )

        self.assertFalse( any( t.is_alive() for t in threads ), "a caller never returned" )
        self.assertEqual( len( collected ), 16 * 64 )
        self.assertEqual( len( set( collected ) ), 16 * 64 )

    def test_every_id_still_passes_the_websocket_session_id_check( self ):
        """
        Overflow names stay two lowercase words, so browsers can still connect.

        get_session_id() in cosa/rest/routers/system.py hands this generator's output
        to the browser as its WebSocket session id, and websocket.py refuses any id
        that does not match ^[a-z]+ [a-z]+$. A digit suffix or a third word would lock
        every browser out once the first 1024 names were spent.

        Requires:
            - The singleton has been reset by setUp

        Ensures:
            - 2100 ids, spanning three cycles, every one matching the browser pattern

        Raises:
            - None
        """
        for _ in range( 2100 ):
            candidate = self.gen.get_id()
            self.assertRegex( candidate, BROWSER_SESSION_ID_PATTERN, f"[{candidate}] would be refused a WebSocket" )

        self.assertGreater( self.gen._cycle, 2 )

    def test_cycle_suffix_rolls_past_a_single_letter( self ):
        """
        The suffix keeps going after z, so there is no second ceiling hiding behind the first.

        Requires:
            - The singleton has been reset by setUp

        Ensures:
            - Cycle 1 is unsuffixed, 2 is "a", 27 is "z", 28 is "aa", 29 is "ab"
            - Drives the multi-letter arm of the suffix loop

        Raises:
            - None
        """
        self.assertEqual( self.gen._cycle_suffix( 1 ),  "" )
        self.assertEqual( self.gen._cycle_suffix( 2 ),  "a" )
        self.assertEqual( self.gen._cycle_suffix( 27 ), "z" )
        self.assertEqual( self.gen._cycle_suffix( 28 ), "aa" )
        self.assertEqual( self.gen._cycle_suffix( 29 ), "ab" )
        self.assertRegex( f"bright lion{self.gen._cycle_suffix( 28 )}", BROWSER_SESSION_ID_PATTERN )


if __name__ == "__main__":
    unittest.main()
