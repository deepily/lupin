"""
Unit tests for the CJ Flow background consumer
(cosa.rest.queue_consumer.start_todo_producer_run_consumer_thread).

The producer thread's inner consumer_worker is exercised synchronously: we patch
threading.Thread to CAPTURE the worker target and call it directly, drive the
mock queues to walk every branch, and flip consumer_running to exit each loop.
condition is a MagicMock so .wait() is a no-op (no real blocking); time.sleep is
patched. ZERO real threads, ZERO sleeps.

Covers: stall-threshold parse (numeric / non-numeric except), idle-wake derive,
_tick_heartbeat (success / AttributeError), outer-loop-not-entered, job path
(websocket_mgr present / _process_job present), job path (no websocket_mgr /
no _process_job warn / monopolize-false / debug-false), empty-queue wait,
items-scheduled-future wait, items-all-paused wait, the top-level except (with
debug traceback), and option-(a) true-monopoly (bug 30398595): Gate B intake
hold, Gate A drain-clean dispatch, Gate A drain-timeout dead-letter, kill-switch
disabled skip — to genuine 100% line + branch + function.

Every `running` mock sets `_monopolize_active = None` so Gate B (the honest
`_monopolize_active is not None` predicate) reads inactive; the dedicated
monopoly tests set it explicitly. `_is_monopolize_enabled` is a fresh gate-time
read on the real queue — mocked per-test here.
"""

import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, Mock, patch

from cosa.rest import queue_consumer as qc


def _todo( **over ):
    """Build a mock todo_queue with a no-op MagicMock condition."""
    t = MagicMock( name="todo" )
    t.consumer_running = over.get( "consumer_running", True )
    t.debug            = over.get( "debug", True )
    t.condition        = MagicMock( name="condition" )
    return t


def _job():
    return Mock( monopolize=True, id_hash="h1", last_question_asked="q?",
                 user_id="u1", job_type="agent", created_date="2026-01-01",
                 user_email="u@e.com" )


class _ConsumerTestBase( unittest.TestCase ):
    def _drive( self, todo, running ):
        """Capture consumer_worker via patched Thread, run it synchronously."""
        with patch.object( qc.threading, "Thread" ) as MkThread, \
             patch.object( qc.time, "sleep" ), \
             patch.object( qc, "emit_job_state_transition" ) as emit, \
             patch( "builtins.print" ):
            qc.start_todo_producer_run_consumer_thread( todo, running )
            worker = MkThread.call_args.kwargs[ "target" ]
            worker()
        return emit


class TestJobFullPath( _ConsumerTestBase ):
    def test_job_processed_with_ws_and_process_job( self ):
        todo = _todo()
        todo.pop_next_eligible.return_value = _job()
        running = Mock()
        running._consumer_stall_threshold_seconds = 120     # numeric → int() success arc
        running._monopolize_active = None                   # Gate B inactive
        running.await_monopolize_pool_drain.return_value = [ ]   # Gate A drains clean
        running._process_job.side_effect = lambda job: setattr( todo, "consumer_running", False )
        emit = self._drive( todo, running )
        running.push.assert_called_once()
        running._process_job.assert_called_once()
        emit.assert_called_once()


class TestJobDegradedPath( _ConsumerTestBase ):
    def test_no_ws_no_process_job_monopolize_false_debug_false( self ):
        todo = _todo( debug=False )
        job  = _job()
        job.monopolize = False
        todo.pop_next_eligible.return_value = job
        running = Mock( spec=[ "push", "last_consumer_heartbeat_at",
                               "_consumer_stall_threshold_seconds", "_monopolize_active" ] )
        running._consumer_stall_threshold_seconds = 120
        running._monopolize_active = None                   # Gate B inactive (monopolize=False → Gate A skipped)
        running.push.side_effect = lambda job: setattr( todo, "consumer_running", False )
        emit = self._drive( todo, running )
        running.push.assert_called_once()
        emit.assert_not_called()              # no websocket_mgr → no emit


class TestEmptyQueueWait( _ConsumerTestBase ):
    def test_empty_waits_then_stops_with_nonnumeric_stall_threshold( self ):
        todo = _todo()
        todo.pop_next_eligible.return_value = None
        todo.is_empty.return_value = True
        todo.condition.wait.side_effect = lambda *a, **k: setattr( todo, "consumer_running", False )
        running = Mock()      # _consumer_stall_threshold_seconds is a Mock → int() raises → except → 120
        running._monopolize_active = None                   # Gate B inactive
        self._drive( todo, running )
        todo.condition.wait.assert_called()


class TestHeartbeatAttributeError( _ConsumerTestBase ):
    def test_tick_heartbeat_swallows_attribute_error( self ):
        class _NoHeartbeat:
            __slots__ = ()                                  # assigning any attr → AttributeError
            _consumer_stall_threshold_seconds = 120
            _monopolize_active                = None        # Gate B inactive (class attr — no slot needed)
            def push( self, job ): pass
            def _process_job( self, job ): pass
        todo = _todo()
        todo.pop_next_eligible.return_value = None
        todo.is_empty.return_value = True
        todo.condition.wait.side_effect = lambda *a, **k: setattr( todo, "consumer_running", False )
        self._drive( todo, _NoHeartbeat() )                 # heartbeat setattr raises → except pass


class TestScheduledFutureWait( _ConsumerTestBase ):
    def test_items_scheduled_future( self ):
        todo = _todo()
        todo.pop_next_eligible.return_value = None
        todo.is_empty.return_value = False
        todo.earliest_scheduled_at.return_value = datetime.now() + timedelta( seconds=120 )
        todo.condition.wait.side_effect = lambda *a, **k: setattr( todo, "consumer_running", False )
        running = Mock()
        running._consumer_stall_threshold_seconds = 120
        running._monopolize_active = None                   # Gate B inactive
        self._drive( todo, running )
        todo.condition.wait.assert_called()


class TestAllPausedWait( _ConsumerTestBase ):
    def test_items_all_paused( self ):
        todo = _todo()
        todo.pop_next_eligible.return_value = None
        todo.is_empty.return_value = False
        todo.earliest_scheduled_at.return_value = None       # all paused
        todo.condition.wait.side_effect = lambda *a, **k: setattr( todo, "consumer_running", False )
        running = Mock()
        running._consumer_stall_threshold_seconds = 120
        running._monopolize_active = None                   # Gate B inactive
        self._drive( todo, running )
        todo.condition.wait.assert_called()


class TestBodyExceptionHandled( _ConsumerTestBase ):
    def test_exception_in_body_is_caught_with_debug_traceback( self ):
        todo = _todo()                                       # debug=True → traceback arc
        todo.pop_next_eligible.return_value = _job()
        running = Mock()
        running._consumer_stall_threshold_seconds = 120
        running._monopolize_active = None                   # Gate B inactive

        def _push_then_die( job ):
            todo.consumer_running = False                    # ensure outer loop exits after
            raise RuntimeError( "push exploded" )
        running.push.side_effect = _push_then_die
        with patch( "traceback.print_exc" ):
            self._drive( todo, running )
        running.push.assert_called_once()

    def test_exception_in_body_debug_false_skips_traceback( self ):
        todo = _todo( debug=False )                          # debug False → skip traceback arc
        todo.pop_next_eligible.return_value = _job()
        running = Mock()
        running._consumer_stall_threshold_seconds = 120
        running._monopolize_active = None                   # Gate B inactive

        def _push_then_die( job ):
            todo.consumer_running = False
            raise RuntimeError( "push exploded" )
        running.push.side_effect = _push_then_die
        self._drive( todo, running )
        running.push.assert_called_once()


# ── Option (a) true-monopoly (bug 30398595) — Gate B intake hold ────────────
class TestGateBIntakeHold( _ConsumerTestBase ):
    """While a monopolize job holds the pool, the consumer defers ALL intake —
    without popping, so the todo queue stays FIFO-intact."""

    def test_hold_defers_all_intake_without_popping( self ):
        todo = _todo()                                      # debug=True → Gate B print arc
        todo.condition.wait.side_effect = lambda *a, **k: setattr( todo, "consumer_running", False )
        running = Mock()
        running._consumer_stall_threshold_seconds = 120
        running._monopolize_active = "held-hash"            # a real hold
        running._is_monopolize_enabled.return_value = True
        self._drive( todo, running )
        todo.pop_next_eligible.assert_not_called()          # nothing popped → FIFO preserved
        running.push.assert_not_called()
        running._process_job.assert_not_called()
        todo.condition.wait.assert_called()

    def test_hold_defers_debug_false( self ):
        todo = _todo( debug=False )                         # Gate B print skipped arc
        todo.condition.wait.side_effect = lambda *a, **k: setattr( todo, "consumer_running", False )
        running = Mock()
        running._consumer_stall_threshold_seconds = 120
        running._monopolize_active = "held-hash"
        running._is_monopolize_enabled.return_value = True
        self._drive( todo, running )
        todo.pop_next_eligible.assert_not_called()

    def test_kill_switch_off_lifts_the_hold( self ):
        """Flag flipped off mid-hold → Gate B stops deferring live (gate-time read)."""
        todo = _todo()
        todo.pop_next_eligible.return_value = None           # fall through to empty-wait
        todo.is_empty.return_value = True
        todo.condition.wait.side_effect = lambda *a, **k: setattr( todo, "consumer_running", False )
        running = Mock()
        running._consumer_stall_threshold_seconds = 120
        running._monopolize_active = "held-hash"             # hold set...
        running._is_monopolize_enabled.return_value = False  # ...but kill-switch OFF
        self._drive( todo, running )
        todo.pop_next_eligible.assert_called()               # Gate B did NOT defer

    def test_second_monopolize_job_serializes_after_hold_clears( self ):
        """FIFO + back-to-back (D4): a second monopolize job waits at Gate B while
        the first holds, then dispatches first (in order) once the hold clears."""
        todo = _todo()
        job2 = _job()                                        # monopolize=True (the 2nd sweep)
        todo.pop_next_eligible.return_value = job2
        running = Mock()
        running._consumer_stall_threshold_seconds = 120
        running._monopolize_active = "first-sweep"           # first monopolize job holds
        running._is_monopolize_enabled.return_value = True
        running._monopolize_drain_timeout_seconds = 300
        running.await_monopolize_pool_drain.return_value = [ ]   # pool clean when it finally dispatches
        def _clear_hold( *a, **k ):
            running._monopolize_active = None                # first sweep completes → hold clears
        todo.condition.wait.side_effect = _clear_hold
        running._process_job.side_effect = lambda j: setattr( todo, "consumer_running", False )
        self._drive( todo, running )
        todo.condition.wait.assert_called()                  # deferred at least once (serialized)
        running._process_job.assert_called_once_with( job2 ) # then dispatched, in order


# ── Option (a) true-monopoly (bug 30398595) — Gate A pool drain ─────────────
class TestGateAPoolDrain( _ConsumerTestBase ):
    """Before a monopolize job takes the pool, Gate A drains foreign writers;
    on timeout it dead-letters (fail loud) rather than run onto a dirty DB."""

    def _mono_running( self, enabled=True ):
        r = Mock()
        r._consumer_stall_threshold_seconds = 120
        r._monopolize_active = None                          # Gate B inactive
        r._monopolize_drain_timeout_seconds = 300
        r._is_monopolize_enabled.return_value = enabled
        return r

    def test_drain_clean_then_dispatches( self ):
        todo = _todo()
        todo.pop_next_eligible.return_value = _job()         # monopolize=True
        running = self._mono_running()
        running.await_monopolize_pool_drain.return_value = [ ]   # drained clean
        running._process_job.side_effect = lambda job: setattr( todo, "consumer_running", False )
        self._drive( todo, running )
        running.await_monopolize_pool_drain.assert_called_once()
        running._process_job.assert_called_once()
        running._transition_to_dead.assert_not_called()

    def test_drain_timeout_dead_letters_naming_offenders( self ):
        todo = _todo()
        todo.pop_next_eligible.return_value = _job()
        running = self._mono_running()
        running.await_monopolize_pool_drain.return_value = [
            { "id_hash": "dr-abc", "job_type": "deep_research" }
        ]
        running._transition_to_dead.side_effect = lambda job, cause: setattr( todo, "consumer_running", False )
        self._drive( todo, running )
        running._transition_to_dead.assert_called_once()
        cause = running._transition_to_dead.call_args[ 0 ][ 1 ]
        self.assertIn( "dr-abc", cause )
        self.assertIn( "deep_research", cause )
        self.assertIn( "30398595", cause )
        running._process_job.assert_not_called()             # never ran onto a dirty DB

    def test_kill_switch_disabled_skips_drain( self ):
        todo = _todo()
        todo.pop_next_eligible.return_value = _job()         # monopolize=True
        running = self._mono_running( enabled=False )        # kill-switch OFF
        running._process_job.side_effect = lambda job: setattr( todo, "consumer_running", False )
        self._drive( todo, running )
        running.await_monopolize_pool_drain.assert_not_called()   # Gate A skipped
        running._process_job.assert_called_once()


def isolated_unit_test():
    """
    Run the queue_consumer unit tests in isolation.

    Ensures:
        - Returns (success, duration, message) for the smoke-runner harness
    """
    import time
    start_time = time.time()
    suite = unittest.TestLoader().loadTestsFromModule( __import__( __name__ ) )
    result = unittest.TextTestRunner( verbosity=2 ).run( suite )
    duration = time.time() - start_time
    success = result.wasSuccessful()
    message = f"{result.testsRun} run, {len( result.failures )} failed, {len( result.errors )} errors"
    return success, duration, message


if __name__ == "__main__":
    ok, secs, msg = isolated_unit_test()
    print( f"\n{'✅ PASS' if ok else '❌ FAIL'} queue_consumer tests in {secs:.3f}s — {msg}" )
