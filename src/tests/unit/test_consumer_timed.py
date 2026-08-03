"""
Unit tests for CJ Flow consumer thread with timed execution support.

Tests the consumer loop's interaction with pop_next_eligible(), dynamic
timeout calculation, and wake-up behavior for scheduled/paused jobs.

Session 381: Initial implementation.
Bug 84db12a0 (2026-07-19): sleep-as-thread-sync replaced with real
synchronization edges — see wait_for() below.
Row 02bdbb4b (2026-07-21): the wall-clock guard that replaced it could skip an
absence claim SILENTLY under load. Absence is now made deterministic by
MockTodoQueue's eligibility gate — see the block above MockSchedulableJob.
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


# ── ABSENCE CLAIMS: WHY THERE IS NO CLOCK GUARD HERE ANYMORE (row 02bdbb4b) ──
#
# Three tests below assert a NEGATIVE — "this job must NOT have run yet". You
# cannot Event.wait() for something that must never fire, so the first fix
# (97fe3ec6, row 84db12a0) guarded those assertions with a wall-clock window:
#
#     if still_before( t0, SCHEDULED_SECONDS * 0.5 ):
#         assert "timed-1" not in processed
#
# That traded a LOUD wrong answer for a QUIET one. When the box starved and the
# window slipped, the `if` was simply false, the assertion never ran, and the
# test reported PASSED — byte-identically to a run that checked and verified.
# Rachel 🕊️ (row d2788869) measured it standalone and then made the skip
# ANNOUNCE itself (8777d4e9); she also measured the real margin at ~1500x, which
# is why this landed as hygiene rather than under time pressure.
#
# THE REMEDY IS TO REMOVE THE CLOCK FROM THE CLAIM, not to describe the slip
# better. `MockTodoQueue` now owns an explicit eligibility gate, so while the
# gate is closed the job CANNOT become eligible no matter how long the test
# takes. The absence is PERMANENT rather than time-boxed, which is exactly the
# precondition the load-safe pattern already used further down this file needs:
#
#     ran = wait_for( lambda: "timed-1" in processed, timeout=... )
#     assert not ran, "..."
#
# ⚠️ THE PRECEDENT DOES NOT TRANSPLANT ON ITS OWN — this is the trap worth
# naming. That pattern is load-safe at the two paused-job sites because a PAUSED
# job's absence is permanent: extra wall clock under contention only makes the
# verdict MORE conclusive. A SCHEDULED job's absence expires on its own at
# t0+0.3s, so copying the shape without the gate would have re-introduced the
# false-RED of 84db12a0 — a starved box overruns the timeout, the job becomes
# legitimately eligible, and `assert not ran` fails on a correct system. The gate
# is what converts the temporary absence into a permanent one; the pattern is
# what is safe to copy ONCE it is.
#
# WHAT MOVED, stated plainly rather than papered over: these three tests now
# assert the CONSUMER's property ("it never dispatches a job the queue reports
# ineligible, and dispatches it once it does"). The scheduled_at-vs-now
# arithmetic itself belongs to FifoQueue.pop_next_eligible and is covered by that
# unit's own tests. Each job below still carries a real future scheduled_at, so
# the consumer's earliest_scheduled_at() sleep path is still exercised.
#
# `still_before` is GONE, not deprecated: with these three sites converted it had
# zero call sites repo-wide (verified 2026-07-21), and a helper nothing calls is
# dead code, not a safety net. Rachel's warning form did its job — it made the
# invisible gap visible long enough to close it.


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
        # Eligibility gate (row 02bdbb4b) — OPEN by default so every test that
        # does not care about absence behaves exactly as before.
        self._eligible        = threading.Event()
        self._eligible.set()

    def pop_next_eligible( self, now=None, predicate=None ):
        """
        Deterministic eligibility: nothing is eligible while the gate is closed.

        This is the injected clock in its useful form. The test, not the box,
        decides when the job becomes eligible, so an absence claim made while
        the gate is closed cannot expire under load.

        Requires:
            - now is a datetime or None; predicate is None or callable

        Ensures:
            - returns None while the gate is closed, whatever the wall clock says
            - delegates unchanged to FifoQueue.pop_next_eligible when open
        """
        if not self._eligible.is_set(): return None
        return super().pop_next_eligible( now, predicate )

    def withhold_eligibility( self ):
        """Close the gate. Call BEFORE pushing the job the consumer must not run."""
        self._eligible.clear()

    def release_eligibility( self ):
        """Open the gate and wake the consumer — the edge an absence claim lacks."""
        with self.condition:
            self._eligible.set()
            self.condition.notify()

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

        scheduled = ( datetime.now() + timedelta( seconds=SCHEDULED_SECONDS ) ).isoformat()
        job       = MockSchedulableJob( "timed-1", scheduled_at=scheduled )
        todo_queue.withhold_eligibility()
        todo_queue.push_with_notify( job )

        # ABSENCE CLAIM — always evaluated, never skipped. The gate keeps the job
        # ineligible for as long as this takes, so contention only buys the
        # consumer MORE chances to wrongly dispatch it: load makes this MORE
        # conclusive, never less.
        ran = wait_for( lambda: "timed-1" in processed, timeout=SCHEDULED_SECONDS * 2 )
        assert not ran, "Timed job was dispatched while the queue reported it ineligible"

        todo_queue.release_eligibility()
        assert wait_for( lambda: "timed-1" in processed ), "Timed job never ran once eligible"

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

        scheduled = ( datetime.now() + timedelta( seconds=SCHEDULED_SECONDS ) ).isoformat()
        todo_queue.withhold_eligibility()
        todo_queue.push_with_notify( MockSchedulableJob( "timed-2", scheduled_at=scheduled ) )

        ran = wait_for( lambda: "timed-2" in processed, timeout=SCHEDULED_SECONDS * 2 )
        assert not ran, "Timed job was dispatched while the queue reported it ineligible"

        todo_queue.release_eligibility()
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

        scheduled = ( datetime.now() + timedelta( seconds=SCHEDULED_SECONDS ) ).isoformat()
        job       = MockSchedulableJob( "mono-timed", scheduled_at=scheduled, monopolize=True )
        todo_queue.withhold_eligibility()
        todo_queue.push_with_notify( job )

        ran = wait_for( lambda: "mono-timed" in processed, timeout=SCHEDULED_SECONDS * 2 )
        assert not ran, "Timed monopolize job was dispatched while the queue reported it ineligible"

        todo_queue.release_eligibility()
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
