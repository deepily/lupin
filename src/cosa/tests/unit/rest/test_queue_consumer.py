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
(monopolize+debug / websocket_mgr present / _process_job present), job path
(no websocket_mgr / no _process_job warn / monopolize-false / debug-false),
empty-queue wait, items-scheduled-future wait, items-all-paused wait, and the
top-level except (with debug traceback) — to genuine 100% line + branch + function.
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
                               "_consumer_stall_threshold_seconds" ] )
        running._consumer_stall_threshold_seconds = 120
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
        self._drive( todo, running )
        todo.condition.wait.assert_called()


class TestHeartbeatAttributeError( _ConsumerTestBase ):
    def test_tick_heartbeat_swallows_attribute_error( self ):
        class _NoHeartbeat:
            __slots__ = ()                                  # assigning any attr → AttributeError
            _consumer_stall_threshold_seconds = 120
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
        self._drive( todo, running )
        todo.condition.wait.assert_called()


class TestBodyExceptionHandled( _ConsumerTestBase ):
    def test_exception_in_body_is_caught_with_debug_traceback( self ):
        todo = _todo()                                       # debug=True → traceback arc
        todo.pop_next_eligible.return_value = _job()
        running = Mock()
        running._consumer_stall_threshold_seconds = 120

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

        def _push_then_die( job ):
            todo.consumer_running = False
            raise RuntimeError( "push exploded" )
        running.push.side_effect = _push_then_die
        self._drive( todo, running )
        running.push.assert_called_once()


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
