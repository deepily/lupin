"""
Guard tests for bug `574fd1dc` Defect 2 — dropped rows are now COUNTED.

THE DEFECT
    `InputAndOutputTable.insert_io_row`'s async worker caught every
    exception, printed a banner + stack trace, and returned. The row was
    gone. The caller had ALREADY returned "success" the moment the work was
    queued, so nothing upstream ever learned the write was lost — and there
    was no counter, so "how many rows have we lost?" was unanswerable BY
    CONSTRUCTION. The only evidence was a console line in a container log,
    which is exactly how this surfaced: a human read it by eye.

WHAT THIS DOES *NOT* CLAIM
    The row is still dropped. There is no retry and no dead-letter store
    here. The single property under test is that the loss is now COUNTABLE.
    Do not read a green run of this file as "no rows are lost."

⚠️ WHY THE CONCURRENCY TEST IS NOT DECORATION
    The counter is incremented from the shared embedding-pool's worker
    threads. A bare `self.async_failure_count += 1` is a read-modify-write:
    under concurrency it silently LOSES increments, which would make the
    instrument understate exactly the quantity it exists to measure — a
    failure invisible in every single-threaded test.
"""
import threading
import unittest
from unittest.mock import MagicMock

from cosa.memory.input_and_output_table import InputAndOutputTable


def _make_table() -> InputAndOutputTable:
    """
    Build an InputAndOutputTable with __init__ bypassed, wired with only the
    async-accounting state. __init__ opens LanceDB / Postgres and constructs
    embedding engines — none of which this seam touches.
    """
    table                         = InputAndOutputTable.__new__( InputAndOutputTable )
    table.debug                   = False
    table.verbose                 = False
    table.async_failure_count     = 0
    table.last_async_failure      = None
    table._async_failure_lock     = threading.Lock()
    return table


class TestAsyncFailureAccounting( unittest.TestCase ):

    def test_counter_starts_at_zero( self ):
        self.assertEqual( 0, _make_table().async_failure_count )
        self.assertIsNone( _make_table().last_async_failure )

    def test_one_failure_increments_by_exactly_one( self ):
        t = _make_table()
        t._record_async_failure( "what is 2 + 2?", RuntimeError( "cold start" ) )
        self.assertEqual( 1, t.async_failure_count )

    def test_last_failure_records_input_type_and_message( self ):
        t = _make_table()
        t._record_async_failure( "what is 2 + 2?", ValueError( "boom" ) )
        text, exc_type, msg = t.last_async_failure
        self.assertEqual( "what is 2 + 2?", text )
        self.assertEqual( "ValueError",     exc_type )
        self.assertEqual( "boom",           msg )

    def test_last_failure_is_the_MOST_RECENT_not_the_first( self ):
        """A recorder that kept the first failure would go stale immediately."""
        t = _make_table()
        t._record_async_failure( "first",  RuntimeError( "one" ) )
        t._record_async_failure( "second", RuntimeError( "two" ) )
        self.assertEqual( 2, t.async_failure_count )
        self.assertEqual( "second", t.last_async_failure[ 0 ] )

    def test_long_input_is_truncated_to_100_chars( self ):
        t = _make_table()
        t._record_async_failure( "x" * 500, RuntimeError( "e" ) )
        self.assertEqual( 100, len( t.last_async_failure[ 0 ] ) )

    def test_empty_input_is_recorded_as_empty_not_crashed( self ):
        t = _make_table()
        t._record_async_failure( "", RuntimeError( "e" ) )
        self.assertEqual( "", t.last_async_failure[ 0 ] )
        self.assertEqual( 1, t.async_failure_count )

    def test_none_input_is_recorded_as_empty_not_crashed( self ):
        t = _make_table()
        t._record_async_failure( None, RuntimeError( "e" ) )
        self.assertEqual( "", t.last_async_failure[ 0 ] )

    def test_concurrent_increments_lose_nothing( self ):
        """
        The load-bearing one. 20 threads x 50 failures = exactly 1000. An
        unlocked `+= 1` passes every other test in this file and fails here.
        """
        t       = _make_table()
        THREADS = 20
        PER     = 50
        barrier = threading.Barrier( THREADS )

        def hammer():
            barrier.wait()                       # maximize interleaving
            for _ in range( PER ):
                t._record_async_failure( "x", RuntimeError( "e" ) )

        workers = [ threading.Thread( target=hammer ) for _ in range( THREADS ) ]
        for w in workers: w.start()
        for w in workers: w.join()

        self.assertEqual( THREADS * PER, t.async_failure_count )


if __name__ == "__main__":
    unittest.main()
