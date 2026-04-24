"""
Unit tests for FifoQueue thread safety (v0.1.7 Phase 1 CJ Flow async multi-lane).

Design anchor:
    src/rnd/v0.1.7/2026.04.23-cj-flow-async-multi-lane/02-phase-1-rlock-config-and-resource-manager.md

These tests prove that FifoQueue's RLock (added in Phase 1) correctly serializes
concurrent access to queue_list and queue_dict across multiple threads, which is
a hard prerequisite for Phase 2 (ThreadPoolExecutor-driven agentic dispatch).
"""

import threading
import time
import random
import pytest

from cosa.rest.fifo_queue import FifoQueue


class MockJob:
    """Minimal QueueableJob-protocol implementation for thread-safety tests."""

    def __init__( self, id_hash: str ):
        self.id_hash              = id_hash
        self.push_counter         = 0
        self.user_id              = "test_user"
        self.session_id           = "test_session"
        self.routing_command      = "test"
        self.run_date             = "2026-04-24"
        self.created_date         = "2026-04-24"
        self.question             = id_hash
        self.last_question_asked  = id_hash
        self.answer               = "test answer"
        self.answer_conversational = "Test answer"
        self.job_type             = "MockJob"
        self.user_email           = "test@test.com"
        self.is_cache_hit         = False
        self.started_at           = None
        self.completed_at         = None
        self.state                = "pending"
        self.error                = None
        self.scheduled_at         = None
        self.monopolize           = False

    def do_all( self ):
        return "done"

    def code_ran_to_completion( self ):
        return True

    def formatter_ran_to_completion( self ):
        return True


class TestFifoQueueThreadSafety:
    """Concurrency tests for FifoQueue's RLock protection."""

    def test_concurrent_push_no_corruption( self ):
        """10 threads × 100 pushes → queue.size() == 1000, no duplicate id_hash, no exception."""
        queue    = FifoQueue()
        threads  = [ ]
        n_writers      = 10
        pushes_per_thr = 100

        def push_many( writer_id: int ):
            for i in range( pushes_per_thr ):
                queue.push( MockJob( f"w{writer_id}_i{i}" ) )

        for wid in range( n_writers ):
            t = threading.Thread( target=push_many, args=( wid, ) )
            threads.append( t )
            t.start()

        for t in threads:
            t.join( timeout=10.0 )
            assert not t.is_alive(), "Thread did not complete — possible deadlock"

        assert queue.size() == n_writers * pushes_per_thr
        assert len( queue.queue_dict ) == n_writers * pushes_per_thr
        # No duplicates: dict keys are unique by construction; list entries must match
        assert len( set( j.id_hash for j in queue.queue_list ) ) == n_writers * pushes_per_thr

    def test_concurrent_push_pop_consistency( self ):
        """5 pushers + 5 poppers for 2s → no exceptions, final size = pushes − pops."""
        queue   = FifoQueue()
        stop_at = time.time() + 2.0
        pushed  = [ 0 ] * 5
        popped  = [ 0 ] * 5
        errors  = [ ]

        def pusher( pid: int ):
            i = 0
            try:
                while time.time() < stop_at:
                    queue.push( MockJob( f"p{pid}_{i}" ) )
                    pushed[ pid ] += 1
                    i += 1
            except Exception as e:
                errors.append( ( "push", pid, repr( e ) ) )

        def popper( pid: int ):
            try:
                while time.time() < stop_at:
                    r = queue.pop()
                    if r is not None:
                        popped[ pid ] += 1
            except Exception as e:
                errors.append( ( "pop", pid, repr( e ) ) )

        ts = [ threading.Thread( target=pusher, args=( i, ) ) for i in range( 5 ) ] + \
             [ threading.Thread( target=popper, args=( i, ) ) for i in range( 5 ) ]
        for t in ts: t.start()
        for t in ts: t.join( timeout=5.0 )

        assert not errors, f"Exceptions during concurrent push/pop: {errors}"
        assert queue.size() == sum( pushed ) - sum( popped )

    def test_concurrent_read_during_write( self ):
        """Readers calling size() + get_all_jobs() while writers mutate → no dict-mutated errors."""
        queue   = FifoQueue()
        stop_at = time.time() + 1.5
        errors  = [ ]

        def writer( wid: int ):
            i = 0
            try:
                while time.time() < stop_at:
                    # Disjoint namespace per-writer so id_hash stays unique
                    queue.push( MockJob( f"w{wid}_{i}" ) )
                    i += 1
                    if i % 3 == 0 and not queue.is_empty():
                        queue.pop()
            except Exception as e:
                errors.append( ( "writer", repr( e ) ) )

        def reader():
            try:
                while time.time() < stop_at:
                    _ = queue.size()
                    _ = queue.get_all_jobs()
                    _ = queue.is_empty()
            except Exception as e:
                errors.append( ( "reader", repr( e ) ) )

        ts = [ threading.Thread( target=writer, args=( i, ) ) for i in range( 3 ) ] + \
             [ threading.Thread( target=reader ) for _ in range( 3 ) ]
        for t in ts: t.start()
        for t in ts: t.join( timeout=5.0 )

        assert not errors, f"Exceptions during concurrent read/write: {errors}"

    def test_delete_by_id_hash_under_concurrency( self ):
        """Delete specific keys while other threads push → deletion succeeds or returns False, never raises."""
        queue   = FifoQueue()
        # Pre-seed
        for i in range( 100 ):
            queue.push( MockJob( f"seed_{i}" ) )

        stop_at = time.time() + 1.5
        errors  = [ ]

        def pusher( pid: int ):
            i = 0
            try:
                while time.time() < stop_at:
                    # Disjoint namespace per-pusher so id_hash stays unique
                    queue.push( MockJob( f"late{pid}_{i}" ) )
                    i += 1
            except Exception as e:
                errors.append( ( "pusher", repr( e ) ) )

        def deleter( offset: int ):
            try:
                while time.time() < stop_at:
                    i = random.randint( 0, 99 )
                    _ = queue.delete_by_id_hash( f"seed_{i}" )
            except Exception as e:
                errors.append( ( "deleter", repr( e ) ) )

        ts = [ threading.Thread( target=pusher, args=( i, ) ) for i in range( 2 ) ] + \
             [ threading.Thread( target=deleter, args=( i, ) ) for i in range( 3 ) ]
        for t in ts: t.start()
        for t in ts: t.join( timeout=5.0 )

        assert not errors, f"Exceptions during concurrent delete: {errors}"
        # List and dict must agree
        assert len( queue.queue_list ) == len( queue.queue_dict )
        assert set( j.id_hash for j in queue.queue_list ) == set( queue.queue_dict.keys() )

    def test_rlock_reentrant_pop( self ):
        """pop() → is_empty() internal self-call must not deadlock (RLock regression)."""
        queue = FifoQueue()
        queue.push( MockJob( "only" ) )

        # Direct timing: if a non-reentrant Lock were used, this would deadlock
        # and the timeout below would catch it.
        result_holder = [ None ]
        def do_pop():
            result_holder[ 0 ] = queue.pop()

        t = threading.Thread( target=do_pop )
        t.start()
        t.join( timeout=2.0 )

        assert not t.is_alive(), "pop() deadlocked — RLock re-entry is broken"
        assert result_holder[ 0 ] is not None
        assert result_holder[ 0 ].id_hash == "only"
        assert queue.is_empty()

    def test_phase2_shaped_stress( self ):
        """
        Phase-2-shaped access pattern: 1 dispatcher + 4 callback-shaped threads doing a
        random mix of delete_by_id_hash / size / get_all_jobs / push for 5 seconds, with
        a 10-second watchdog that aborts the test on deadlock.

        Asserts:
          (1) no deadlock (watchdog does not fire)
          (2) len(queue._queue_list) == len(queue._queue_dict) at end
          (3) set(item.id_hash for item in queue._queue_list) == set(queue._queue_dict.keys())

        Catches RLock-placement bugs that only surface at Phase 2 concurrency.
        """
        queue    = FifoQueue()
        stop_at  = time.time() + 5.0
        errors   = [ ]
        deadlock = threading.Event()

        def dispatcher():
            i = 0
            try:
                while time.time() < stop_at and not deadlock.is_set():
                    queue.push( MockJob( f"dispatch_{i}" ) )
                    i += 1
                    time.sleep( 0.001 )
            except Exception as e:
                errors.append( ( "dispatcher", repr( e ) ) )

        def callback( cid: int ):
            i = 0
            try:
                while time.time() < stop_at and not deadlock.is_set():
                    op = random.choice( [ "delete", "size", "getall", "push" ] )
                    if op == "delete":
                        queue.delete_by_id_hash( f"dispatch_{random.randint( 0, 100 )}" )
                    elif op == "size":
                        _ = queue.size()
                    elif op == "getall":
                        _ = queue.get_all_jobs()
                    else:
                        queue.push( MockJob( f"cb{cid}_{i}" ) )
                        i += 1
                    time.sleep( 0.0005 )
            except Exception as e:
                errors.append( ( f"callback_{cid}", repr( e ) ) )

        threads = [ threading.Thread( target=dispatcher ) ]
        threads += [ threading.Thread( target=callback, args=( i, ) ) for i in range( 4 ) ]
        for t in threads: t.start()

        # Watchdog: if any thread is still alive 10s after nominal stop, flag deadlock
        watchdog_deadline = stop_at + 10.0
        for t in threads:
            remaining = max( 0.1, watchdog_deadline - time.time() )
            t.join( timeout=remaining )
            if t.is_alive():
                deadlock.set()

        assert not deadlock.is_set(), "Watchdog fired — some thread did not finish within 10s of nominal stop (deadlock suspected)"
        assert not errors, f"Exceptions during phase-2-shaped stress: {errors}"

        # Final consistency: list and dict must agree on which jobs are present
        assert len( queue.queue_list ) == len( queue.queue_dict ), \
            f"list/dict size mismatch: {len( queue.queue_list )} vs {len( queue.queue_dict )}"
        assert set( j.id_hash for j in queue.queue_list ) == set( queue.queue_dict.keys() ), \
            "queue_list and queue_dict disagree on which id_hashes are present"


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
