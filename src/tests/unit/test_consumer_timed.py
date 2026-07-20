"""
Unit tests for CJ Flow consumer thread with timed execution support.

Tests the consumer loop's interaction with pop_next_eligible(), dynamic
timeout calculation, and wake-up behavior for scheduled/paused jobs.

Session 381: Initial implementation.
Bug 84db12a0 (2026-07-19): sleep-as-thread-sync replaced with real
synchronization edges — see wait_for()/still_before() below.
"""

import pytest
import threading
import time
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock
from cosa.rest.fifo_queue import FifoQueue
from cosa.rest.job_state import JobState
from cosa.rest.queue_consumer import start_todo_producer_run_consumer_thread


# Far-future offset for jobs that must NOT become eligible during a test.
# Generous by design: the margin is what keeps a starved box from turning a
# "still waiting" assertion into a false RED.
FAR_FUTURE_SECONDS = 30.0

# Offset for jobs that SHOULD become eligible mid-test.
SCHEDULED_SECONDS  = 0.3


def wait_for( predicate, timeout=5.0, interval=0.005 ):
    """
    Poll until predicate() is truthy or the timeout elapses.

    Replaces bare time.sleep() as a thread-synchronization primitive. A sleep
    is a wall-clock bet, not a happens-before edge: under full-suite CPU
    contention the consumer thread may simply not have run yet, which made
    this class a false-RED generator (bug 84db12a0). Waiting on STATE is
    load-insensitive; waiting on the clock is not.

    Requires:
        - predicate is a zero-argument callable
        - timeout and interval are positive floats with interval < timeout

    Ensures:
        - returns True as soon as predicate() is truthy
        - returns False only after the full timeout has elapsed
        - re-checks predicate() once after the deadline before returning False,
          so a predicate satisfied during the final interval is not missed
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate(): return True
        time.sleep( interval )
    return bool( predicate() )


def still_before( t0, offset_seconds ):
    """
    Report whether the wall clock is provably still before t0 + offset_seconds.

    Guards "not yet processed" assertions. Such a claim is only CHECKABLE
    while the job's scheduled time has not arrived. If the box starved and the
    deadline slipped past while we were descheduled, the assertion is
    unverifiable rather than false — skipping it is honest; failing it is a
    false RED, and asserting it anyway is what bug 84db12a0 was filed for.

    Requires:
        - t0 is a time.monotonic() reading taken before the job was pushed
        - offset_seconds is a positive float

    Ensures:
        - returns True only while ( monotonic() - t0 ) < offset_seconds
    """
    return ( time.monotonic() - t0 ) < offset_seconds


class MockSchedulableJob:
    """Mock job with scheduling fields for consumer tests."""

    def __init__( self, id_hash, scheduled_at=None, monopolize=False ):
        self.id_hash               = id_hash
        self.push_counter          = 0
        self.user_id               = "test_user"
        self.user_email            = "test@test.com"
        self.session_id            = "test_session"
        self.routing_command       = "test"
        self.run_date              = datetime.now().isoformat()
        self.created_date          = datetime.now().isoformat()
        self.started_at            = None
        self.completed_at          = None
        self.question              = f"Job {id_hash}"
        self.last_question_asked   = f"Job {id_hash}"
        self.answer                = ""
        self.answer_conversational = ""
        self.job_type              = "MockSchedulableJob"
        self.is_cache_hit          = False
        self.state                 = JobState.PENDING
        self.error                 = None
        self.scheduled_at          = scheduled_at
        self.monopolize            = monopolize

    def do_all( self ):
        return "done"

    def code_ran_to_completion( self ):
        return True

    def formatter_ran_to_completion( self ):
        return True


class MockTodoQueue( FifoQueue ):
    """TodoFifoQueue-like mock with condition variable for consumer tests."""

    def __init__( self ):
        super().__init__()
        self.condition        = threading.Condition()
        self.consumer_running = True
        self.debug            = False

    def push_with_notify( self, job ):
        """Push a job and notify the consumer (mimics TodoFifoQueue.push)."""
        with self.condition:
            super().push( job )
            self.condition.notify()

    def delete_by_id_hash( self, id_hash ):
        """Override with notify (mimics TodoFifoQueue override)."""
        with self.condition:
            result = super().delete_by_id_hash( id_hash )
            if result:
                self.condition.notify()
            return result

    def shutdown( self ):
        """Signal consumer to stop."""
        with self.condition:
            self.consumer_running = False
            self.condition.notify()


class TestConsumerTimed:
    """Tests for consumer thread with timed execution."""

    def _start_consumer( self, todo_queue, processed_jobs ):
        """Start consumer with a mock running queue that tracks processed jobs."""
        running_queue = Mock()
        running_queue.websocket_mgr = None
        # Option (a) true-monopoly (bug 30398595): no hold active, and a clean
        # pool-drain so monopolize jobs (test_monopolize_*) still dispatch here.
        running_queue._monopolize_active = None
        running_queue._is_monopolize_enabled.return_value = True
        running_queue._monopolize_drain_timeout_seconds = 300
        running_queue.await_monopolize_pool_drain.return_value = [ ]

        def mock_process( job ):
            processed_jobs.append( job.id_hash )

        running_queue._process_job = mock_process

        thread = start_todo_producer_run_consumer_thread( todo_queue, running_queue )
        assert wait_for( thread.is_alive ), "Consumer thread failed to start"
        return thread

    def test_consumer_processes_immediate_job( self ):
        """Basic: push immediate job, consumer processes it."""
        todo_queue = MockTodoQueue()
        processed = []
        thread = self._start_consumer( todo_queue, processed )

        job = MockSchedulableJob( "imm-1" )
        todo_queue.push_with_notify( job )

        assert wait_for( lambda: "imm-1" in processed ), "Immediate job was never processed"

        todo_queue.shutdown()
        thread.join( timeout=1.0 )

    def test_consumer_sleeps_until_scheduled( self ):
        """Push job at now+0.3s, verify it waits then processes."""
        todo_queue = MockTodoQueue()
        processed = []
        thread = self._start_consumer( todo_queue, processed )

        t0        = time.monotonic()
        scheduled = ( datetime.now() + timedelta( seconds=SCHEDULED_SECONDS ) ).isoformat()
        job       = MockSchedulableJob( "timed-1", scheduled_at=scheduled )
        todo_queue.push_with_notify( job )

        # Should NOT be processed before its scheduled time. Only assertable
        # while we are provably still before that time.
        if still_before( t0, SCHEDULED_SECONDS * 0.5 ):
            assert "timed-1" not in processed, "Timed job ran before its scheduled time"

        assert wait_for( lambda: "timed-1" in processed ), "Timed job never ran after its scheduled time"

        todo_queue.shutdown()
        thread.join( timeout=1.0 )

    def test_earlier_job_wakes_consumer( self ):
        """Sleeping for a far-future job, push immediate job, wakes and processes."""
        todo_queue = MockTodoQueue()
        processed = []
        thread = self._start_consumer( todo_queue, processed )

        # Push far-future job — consumer sleeps until it is eligible
        future = ( datetime.now() + timedelta( seconds=FAR_FUTURE_SECONDS ) ).isoformat()
        todo_queue.push_with_notify( MockSchedulableJob( "future-1", scheduled_at=future ) )

        # Push immediate job — should wake consumer
        todo_queue.push_with_notify( MockSchedulableJob( "immediate-1" ) )

        assert wait_for( lambda: "immediate-1" in processed ), "Immediate job did not wake the consumer"
        # Positive assertion above is the control: the consumer demonstrably ran,
        # so this negative cannot pass vacuously.
        assert "future-1" not in processed, "Far-future job ran early"

        todo_queue.shutdown()
        thread.join( timeout=1.0 )

    def test_timed_job_deleted_while_waiting( self ):
        """Delete the job consumer is sleeping for — consumer recalculates."""
        todo_queue = MockTodoQueue()
        processed = []
        thread = self._start_consumer( todo_queue, processed )

        future = ( datetime.now() + timedelta( seconds=FAR_FUTURE_SECONDS ) ).isoformat()
        todo_queue.push_with_notify( MockSchedulableJob( "future-del", scheduled_at=future ) )

        # Delete the job — delete_by_id_hash calls condition.notify()
        assert wait_for( lambda: todo_queue.delete_by_id_hash( "future-del" ) ), "Job never became deletable"

        # Queue is now empty, consumer should be waiting (not stuck)
        assert wait_for( todo_queue.is_empty ), "Queue did not drain after delete"
        assert "future-del" not in processed, "Deleted job was processed anyway"

        todo_queue.shutdown()
        thread.join( timeout=1.0 )

    def test_empty_then_timed_push( self ):
        """Empty queue -> push timed job -> consumer sleeps until scheduled."""
        todo_queue = MockTodoQueue()
        processed = []
        thread = self._start_consumer( todo_queue, processed )

        t0        = time.monotonic()
        scheduled = ( datetime.now() + timedelta( seconds=SCHEDULED_SECONDS ) ).isoformat()
        todo_queue.push_with_notify( MockSchedulableJob( "timed-2", scheduled_at=scheduled ) )

        if still_before( t0, SCHEDULED_SECONDS * 0.5 ):
            assert "timed-2" not in processed, "Timed job ran before its scheduled time"

        assert wait_for( lambda: "timed-2" in processed ), "Timed job never became eligible"

        todo_queue.shutdown()
        thread.join( timeout=1.0 )

    def test_immediate_bypasses_future( self ):
        """[future, immediate] -> immediate processed first."""
        todo_queue = MockTodoQueue()
        processed = []
        thread = self._start_consumer( todo_queue, processed )

        future = ( datetime.now() + timedelta( seconds=FAR_FUTURE_SECONDS ) ).isoformat()
        todo_queue.push_with_notify( MockSchedulableJob( "future-2", scheduled_at=future ) )
        todo_queue.push_with_notify( MockSchedulableJob( "immediate-2" ) )

        # Wait for SOMETHING to be processed before indexing — the original
        # bare sleep(0.3) indexed processed[0] on a list the consumer had not
        # yet appended to under load. That is bug 84db12a0's exact failure.
        assert wait_for( lambda: len( processed ) >= 1 ), "Nothing was processed"
        assert processed[ 0 ] == "immediate-2", f"Expected immediate job first, got {processed[ 0 ]}"

        todo_queue.shutdown()
        thread.join( timeout=1.0 )

    def test_monopolize_flag_preserved( self ):
        """Job with monopolize=True processes normally in serial mode."""
        todo_queue = MockTodoQueue()
        processed = []
        thread = self._start_consumer( todo_queue, processed )

        job = MockSchedulableJob( "mono-1", monopolize=True )
        todo_queue.push_with_notify( job )

        assert wait_for( lambda: "mono-1" in processed ), "Monopolize job was never processed"

        todo_queue.shutdown()
        thread.join( timeout=1.0 )

    def test_monopolize_plus_timed( self ):
        """Timed + monopolize job respects both: waits then processes."""
        todo_queue = MockTodoQueue()
        processed = []
        thread = self._start_consumer( todo_queue, processed )

        t0        = time.monotonic()
        scheduled = ( datetime.now() + timedelta( seconds=SCHEDULED_SECONDS ) ).isoformat()
        job       = MockSchedulableJob( "mono-timed", scheduled_at=scheduled, monopolize=True )
        todo_queue.push_with_notify( job )

        if still_before( t0, SCHEDULED_SECONDS * 0.5 ):
            assert "mono-timed" not in processed, "Timed monopolize job ran before its scheduled time"

        assert wait_for( lambda: "mono-timed" in processed ), "Timed monopolize job never ran"

        todo_queue.shutdown()
        thread.join( timeout=1.0 )

    def test_pause_while_consumer_sleeping( self ):
        """Pause a timed job that consumer is sleeping for — recalculates."""
        todo_queue = MockTodoQueue()
        processed  = []
        thread     = self._start_consumer( todo_queue, processed )

        scheduled = ( datetime.now() + timedelta( seconds=SCHEDULED_SECONDS ) ).isoformat()
        job = MockSchedulableJob( "pause-sleep", scheduled_at=scheduled )
        todo_queue.push_with_notify( job )

        # Pause the job — consumer should NOT process it even after scheduled time
        job.state = JobState.PAUSED
        with todo_queue.condition:
            todo_queue.condition.notify()  # Wake consumer to see paused state

        # Wait well PAST the scheduled time, then assert it still has not run.
        # wait_for returning False here is the success signal: the predicate we
        # are hoping stays false is "was processed". Under load this only gets
        # MORE conclusive (more wall clock elapses past the deadline).
        ran = wait_for( lambda: "pause-sleep" in processed, timeout=SCHEDULED_SECONDS * 3 )
        assert not ran, "Paused job was processed despite being paused"

        todo_queue.shutdown()
        thread.join( timeout=1.0 )

    def test_resume_wakes_consumer( self ):
        """Resume a paused job — consumer wakes and processes it."""
        todo_queue = MockTodoQueue()
        processed  = []
        thread     = self._start_consumer( todo_queue, processed )

        job       = MockSchedulableJob( "resume-1" )
        job.state = JobState.PAUSED
        todo_queue.push_with_notify( job )

        ran = wait_for( lambda: "resume-1" in processed, timeout=0.3 )
        assert not ran, "Paused job was processed before resume"

        # Resume
        job.state = JobState.QUEUED
        with todo_queue.condition:
            todo_queue.condition.notify()

        assert wait_for( lambda: "resume-1" in processed ), "Resumed job was never processed"

        todo_queue.shutdown()
        thread.join( timeout=1.0 )
