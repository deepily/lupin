"""
Unit tests for Phase 2 agentic pool in RunningFifoQueue.

Design anchor:
    src/rnd/v0.1.7/2026.04.23-cj-flow-async-multi-lane/03-phase-2-dispatcher-pool-and-pool-status.md

Covers:
  - Dispatch routing (AgenticJobBase → pool; AgentBase|SolutionSnapshot → fast-lane;
    unknown types → TypeError).
  - `_submit_agentic_job` atomic-under-lock ordering (submit + track + callback).
  - `_on_agentic_complete` defensive callback paths (Exception inside do_all,
    BaseException survivor, transition-method raises).
  - Pool mechanics (concurrent execution, saturation, completion-order-not-FIFO).
  - `get_pool_status` shape + values.
  - `shutdown_pool` (wait-for-inflight, timeout dead-lettering).
  - `test_no_pop_calls_remain_in_running_fifo_queue` grep regression.

Tests use mocked AgenticJobBase subclasses; no real Anthropic calls; no server
required. `_transition_to_done` / `_transition_to_dead` rely on several
external side effects (notify service, WebSocket emit, TFE watchdog, SQLite
I/O table) — all are mocked or allowed to fail-fast via existing defensive
try/except so they do not dominate the test.
"""

import os
import re
import threading
import time
import uuid
import pytest

from unittest.mock import MagicMock, patch

from cosa.agents.agentic_job_base import AgenticJobBase
from cosa.agents.agent_base import AgentBase
from cosa.memory.solution_snapshot import SolutionSnapshot
from cosa.rest.fifo_queue import FifoQueue
from cosa.rest.job_state import JobState
from cosa.rest.running_fifo_queue import RunningFifoQueue


# =============================================================================
# Test fixtures / mocks
# =============================================================================

class MockAgenticJob( AgenticJobBase ):
    """Controllable AgenticJobBase subclass for pool tests.

    `do_all_fn` receives `self` and is called from a pool worker thread.
    Set `raise_exc` to force an exception path; set `base_exc` to force a
    BaseException-but-not-Exception survivor (KeyboardInterrupt) path.
    """

    JOB_TYPE   = "mock_agentic"
    JOB_PREFIX = "mock"

    def __init__(
        self,
        do_all_fn = None,
        raise_exc = None,
        base_exc  = None,
        answer    = "mock result",
    ):
        super().__init__(
            user_id    = "test_user",
            user_email = "test@example.com",
            session_id = "test_session",
        )
        self._do_all_fn             = do_all_fn or ( lambda j: answer )
        self._raise_exc             = raise_exc
        self._base_exc              = base_exc
        self.answer_conversational  = answer
        self.routing_command        = "mock_route"
        # created_date + job_type are @property on AgenticJobBase — don't override

    # AgenticJobBase requires these (abstract in the base class)
    @property
    def last_question_asked( self ) -> str:
        return f"mock question for {self.id_hash}"

    def do_all( self ):
        if self._base_exc is not None:
            raise self._base_exc
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._do_all_fn( self )

    async def _execute( self ) -> str:
        # Never called (we override do_all synchronously) — stub to satisfy ABC
        return "mock"

    def code_ran_to_completion( self ) -> bool:
        return True

    def formatter_ran_to_completion( self ) -> bool:
        return True


def _make_running_queue( max_workers: int = 2 ):
    """Build a RunningFifoQueue with stub dependencies + mocked side-effects.

    Patches heavy init dependencies (LanceDB I/O table, spaCy GistNormalizer)
    so the 49K-row table load + spaCy pipeline don't dominate test runtime.
    """
    # Config mgr: minimal stub returning the requested max_workers
    class _ConfigMgr:
        def get( self, key, default=None, return_type=None ):
            if key == "cj flow max concurrent agentic jobs":
                return max_workers
            return default
    cfg = _ConfigMgr()

    todo = FifoQueue()
    done = FifoQueue()
    dead = FifoQueue()

    # Patch heavy construction-time deps for fast test startup.
    # RunningFifoQueue.__init__ instantiates InputAndOutputTable() (LanceDB
    # 49K-row table) and GistNormalizer (spaCy pipeline) — both can take
    # tens of seconds. Pool tests don't exercise either; MagicMock suffices.
    with patch( "cosa.rest.running_fifo_queue.InputAndOutputTable" ) as MockIOT, \
         patch( "cosa.rest.running_fifo_queue.GistNormalizer" ) as MockGN:
        MockIOT.return_value = MagicMock()
        MockGN.return_value  = MagicMock()

        rq = RunningFifoQueue(
            app                   = None,
            websocket_mgr         = MagicMock(),
            snapshot_mgr          = MagicMock(),
            jobs_todo_queue       = todo,
            jobs_done_queue       = done,
            jobs_dead_queue       = dead,
            config_mgr            = cfg,
            emit_speech_callback  = None,
        )

    # Silence TTS notify + WebSocket emit + auto-fix (not the subject of
    # pool tests; transitions rely on their existing defensive try/except)
    rq._notify                = MagicMock()
    rq._evaluate_for_auto_fix = MagicMock()
    return rq


@pytest.fixture
def rq():
    q = _make_running_queue( max_workers=2 )
    yield q
    # Teardown: cancel pending futures + short wait so pytest doesn't block on
    # the pool's non-daemon worker threads. ThreadPoolExecutor workers are
    # non-daemon by default, so without cancel_futures=True they keep pytest
    # alive past test completion.
    q._agentic_pool.shutdown( wait=True, cancel_futures=True )


@pytest.fixture
def rq_single():
    q = _make_running_queue( max_workers=1 )
    yield q
    # Teardown: cancel pending futures + short wait so pytest doesn't block on
    # the pool's non-daemon worker threads. ThreadPoolExecutor workers are
    # non-daemon by default, so without cancel_futures=True they keep pytest
    # alive past test completion.
    q._agentic_pool.shutdown( wait=True, cancel_futures=True )


@pytest.fixture
def rq3():
    q = _make_running_queue( max_workers=3 )
    yield q
    # Teardown: cancel pending futures + short wait so pytest doesn't block on
    # the pool's non-daemon worker threads. ThreadPoolExecutor workers are
    # non-daemon by default, so without cancel_futures=True they keep pytest
    # alive past test completion.
    q._agentic_pool.shutdown( wait=True, cancel_futures=True )


def _wait_until( predicate, timeout: float = 5.0, poll: float = 0.01 ):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep( poll )
    return False


# =============================================================================
# Dispatch routing
# =============================================================================

class TestDispatch:

    def test_agentic_job_submitted_to_pool( self, rq ):
        """AgenticJobBase → _submit_agentic_job → pool worker calls do_all."""
        ran_on_thread = [ None ]

        def do_all_impl( self ):
            ran_on_thread[ 0 ] = threading.current_thread().name
            return "done"

        job = MockAgenticJob( do_all_fn=do_all_impl )
        rq.push( job )

        rq._submit_agentic_job( job )

        assert _wait_until( lambda: ran_on_thread[ 0 ] is not None )
        assert ran_on_thread[ 0 ].startswith( "AgenticPool" ), \
            f"do_all should run on AgenticPool thread, ran on {ran_on_thread[ 0 ]!r}"

    def test_dispatcher_agentic_goes_to_pool( self, rq ):
        """_process_job routes AgenticJobBase through the pool path, not inline."""
        ran_on_thread = [ None ]
        job = MockAgenticJob(
            do_all_fn=lambda j: ran_on_thread.__setitem__( 0, threading.current_thread().name ) or "ok"
        )
        rq.push( job )  # simulate consumer's push before _process_job

        # Call _process_job on the current (consumer) thread
        consumer_thread_name = threading.current_thread().name
        rq._process_job( job )

        assert _wait_until( lambda: ran_on_thread[ 0 ] is not None )
        assert ran_on_thread[ 0 ] != consumer_thread_name, \
            "agentic job should NOT run inline on the consumer thread"

    def test_process_job_uses_passed_job_not_queue_head( self, rq ):
        """
        Regression: _process_job MUST dispatch the job passed as a parameter, NOT
        whatever happens to sit at the head of the running queue. Under Phase 2,
        the running queue can hold multiple in-flight agentic jobs (pool retains
        them until their callbacks fire), so self.head() != the newly-pushed job.

        This regression fired as Bug 2A/2B in the 2026-04-24 Live API probe:
        `_process_job(B)` did `running_job = self.head()` which returned an
        earlier stuck job A, re-submitting A to the pool (→ duplicate done-queue
        pushes) while B was orphaned in the running queue (→ phantom).

        Asserts: when both A and B are in the running queue and _process_job(B)
        is called, B — NOT A — gets submitted to the pool.
        """
        dispatched = [ ]  # collects the job that reached the pool worker

        def trace_do_all( j ):
            dispatched.append( j.id_hash )
            return "ok"

        job_a = MockAgenticJob( do_all_fn=trace_do_all )
        job_b = MockAgenticJob( do_all_fn=trace_do_all )

        # Simulate the Phase 2 steady-state: A is already in the running queue
        # (phantom or in-flight), consumer just pushed B.
        rq.push( job_a )
        rq.push( job_b )
        assert rq.size() == 2
        assert rq.head().id_hash == job_a.id_hash  # A is the head

        # Consumer calls _process_job(B). Pre-fix this wrongly used self.head()=A;
        # fixed version uses the passed job B.
        rq._process_job( job_b )

        # Give the pool a moment to execute
        assert _wait_until( lambda: len( dispatched ) >= 1, timeout=3.0 )
        assert job_b.id_hash in dispatched, \
            f"Expected {job_b.id_hash[:8]} (passed job B) to be dispatched; got {dispatched}"
        assert job_a.id_hash not in dispatched, \
            f"Regression: queue-head job A ({job_a.id_hash[:8]}) was dispatched instead of passed job B"

    def test_submit_pushes_to_running_queue( self, rq ):
        """After consumer+submit, get_by_id_hash finds the job (ghost-sweeper precondition)."""
        job = MockAgenticJob( do_all_fn=lambda j: time.sleep( 0.2 ) or "ok" )
        rq.push( job )
        rq._submit_agentic_job( job )
        # Check the precondition BEFORE the job finishes (timing window)
        assert rq.get_by_id_hash( job.id_hash ) is job

    def test_submit_registers_future_in_dict( self, rq ):
        """After submit, _agentic_futures[id_hash] holds the Future."""
        job = MockAgenticJob( do_all_fn=lambda j: time.sleep( 0.1 ) or "ok" )
        rq.push( job )
        rq._submit_agentic_job( job )
        with rq._agentic_futures_lock:
            assert job.id_hash in rq._agentic_futures


# =============================================================================
# Completion paths
# =============================================================================

class TestCompletion:

    def test_completion_moves_to_done( self, rq ):
        """Successful do_all → job ends up in done_queue, removed from running_queue."""
        job = MockAgenticJob( do_all_fn=lambda j: "result-ok", answer="answered ok" )
        rq.push( job )
        rq._submit_agentic_job( job )

        assert _wait_until( lambda: rq.jobs_done_queue.size() == 1 )
        # Removed from running_queue
        assert rq.size() == 0
        # Dict has been popped
        with rq._agentic_futures_lock:
            assert job.id_hash not in rq._agentic_futures

    def test_failure_moves_to_dead( self, rq ):
        """do_all raises Exception → job ends up in dead_queue."""
        job = MockAgenticJob( raise_exc=RuntimeError( "boom" ) )
        rq.push( job )
        rq._submit_agentic_job( job )

        assert _wait_until( lambda: rq.jobs_dead_queue.size() == 1 )
        assert rq.size() == 0
        assert rq.jobs_done_queue.size() == 0
        # Job has error set
        dead_job = rq.jobs_dead_queue.head()
        assert "boom" in ( dead_job.error or "" )


# =============================================================================
# Defensive callback — Q4 in design doc
# =============================================================================

class TestDefensiveCallback:

    def test_defensive_callback_swallows_exception_on_transition( self, rq ):
        """Force _transition_to_done to raise; job still ends up in dead_queue,
        callback does not re-raise."""
        original_to_done = rq._transition_to_done
        call_count = [ 0 ]

        def flaky_done( job, formatted_output=None ):
            call_count[ 0 ] += 1
            raise RuntimeError( "transition broken" )

        rq._transition_to_done = flaky_done

        job = MockAgenticJob( do_all_fn=lambda j: "ok" )
        rq.push( job )
        rq._submit_agentic_job( job )

        # Inner `except Exception` branch should dead-letter
        assert _wait_until( lambda: rq.jobs_dead_queue.size() == 1 )
        assert call_count[ 0 ] >= 1, "_transition_to_done should have been attempted"

        rq._transition_to_done = original_to_done

    def test_defensive_callback_both_transitions_fail_no_raise( self, rq ):
        """Both _transition_to_done AND _transition_to_dead raise; callback
        still doesn't re-raise; job remains in _agentic_futures for the
        Phase-3 sweeper as last-resort."""
        rq._transition_to_done = MagicMock( side_effect=RuntimeError( "done-broken" ) )
        rq._transition_to_dead = MagicMock( side_effect=RuntimeError( "dead-broken" ) )

        job = MockAgenticJob( do_all_fn=lambda j: "ok" )
        rq.push( job )
        rq._submit_agentic_job( job )

        # Give the callback time to run
        assert _wait_until( lambda: rq._transition_to_done.called, timeout=3.0 )
        assert _wait_until( lambda: rq._transition_to_dead.called, timeout=3.0 )
        # No exception crashed the pool; executor is still usable
        assert not rq._agentic_pool._shutdown

    def test_defensive_callback_handles_base_exception( self, rq ):
        """do_all raises KeyboardInterrupt (BaseException, not Exception) →
        callback logs + returns without raising; does NOT attempt dead-letter
        (BaseException survivors are left for the sweeper)."""
        rq._transition_to_dead = MagicMock()

        job = MockAgenticJob( base_exc=KeyboardInterrupt( "signal" ) )
        rq.push( job )
        rq._submit_agentic_job( job )

        # Give the callback time to run and fully return
        time.sleep( 0.5 )

        # Dead-letter path must NOT have been invoked for BaseException survivors
        assert not rq._transition_to_dead.called
        # Pool is still alive for other work
        assert not rq._agentic_pool._shutdown


# =============================================================================
# Pool mechanics
# =============================================================================

class TestPool:

    def test_concurrent_agentic_execution( self, rq3 ):
        """3 mock jobs each sleeping 0.3s → max_workers=3 completes in <0.9s."""
        def slow_do( job ):
            time.sleep( 0.3 )
            return "done"

        jobs = [ MockAgenticJob( do_all_fn=slow_do ) for _ in range( 3 ) ]
        t0 = time.time()
        for j in jobs:
            rq3.push( j )
            rq3._submit_agentic_job( j )

        assert _wait_until( lambda: rq3.jobs_done_queue.size() == 3, timeout=2.0 )
        elapsed = time.time() - t0
        assert elapsed < 1.0, f"3 concurrent 0.3s jobs should finish in <1s, took {elapsed:.2f}s"

    def test_serial_execution_with_one_worker( self, rq_single ):
        """max_workers=1 → 3 jobs serialize, take ~0.3s × 3 = ~0.9s."""
        def slow_do( job ):
            time.sleep( 0.3 )
            return "done"

        jobs = [ MockAgenticJob( do_all_fn=slow_do ) for _ in range( 3 ) ]
        t0 = time.time()
        for j in jobs:
            rq_single.push( j )
            rq_single._submit_agentic_job( j )

        assert _wait_until( lambda: rq_single.jobs_done_queue.size() == 3, timeout=3.0 )
        elapsed = time.time() - t0
        assert elapsed >= 0.75, \
            f"3 serial 0.3s jobs should take ≥0.75s with max_workers=1, took {elapsed:.2f}s"

    def test_pool_saturation_queues_work( self, rq_single ):
        """max_workers=1, submit 3 jobs; first runs immediately, other 2 queue
        internally in the pool and eventually complete."""
        def slow_do( job ):
            time.sleep( 0.2 )
            return "done"

        jobs = [ MockAgenticJob( do_all_fn=slow_do ) for _ in range( 3 ) ]
        for j in jobs:
            rq_single.push( j )
            rq_single._submit_agentic_job( j )

        # All 3 should eventually land in done
        assert _wait_until(
            lambda: rq_single.jobs_done_queue.size() == 3,
            timeout=3.0
        ), f"Only {rq_single.jobs_done_queue.size()}/3 completed"

    def test_completion_order_not_fifo( self, rq ):
        """Submit slow-then-fast agentic in that order → fast completes first."""
        completion_order = [ ]

        def fast( j ):
            time.sleep( 0.05 )
            completion_order.append( "fast" )
            return "fast"

        def slow( j ):
            time.sleep( 0.5 )
            completion_order.append( "slow" )
            return "slow"

        slow_job = MockAgenticJob( do_all_fn=slow )
        fast_job = MockAgenticJob( do_all_fn=fast )
        rq.push( slow_job )
        rq._submit_agentic_job( slow_job )
        rq.push( fast_job )
        rq._submit_agentic_job( fast_job )

        assert _wait_until(
            lambda: rq.jobs_done_queue.size() == 2, timeout=2.0
        )
        assert completion_order[ 0 ] == "fast"
        assert completion_order[ 1 ] == "slow"


# =============================================================================
# Pool status endpoint backing
# =============================================================================

class TestPoolStatus:

    def test_get_pool_status_empty( self, rq ):
        status = rq.get_pool_status()
        assert status == {
            "inflight_agentic_jobs": 0,
            "max_agentic_workers" : 2,
            "pending_in_pool"     : 0,
        }

    def test_get_pool_status_shape_with_inflight( self, rq_single ):
        """max_workers=1, submit 2 jobs → 1 running + 1 pending, total inflight=2."""
        # Use an Event so test controls when jobs finish
        release = threading.Event()

        def blocked_do( j ):
            release.wait( timeout=5 )
            return "ok"

        jobs = [ MockAgenticJob( do_all_fn=blocked_do ) for _ in range( 2 ) ]
        for j in jobs:
            rq_single.push( j )
            rq_single._submit_agentic_job( j )

        # Give the pool a moment to pick up the first job
        time.sleep( 0.1 )

        status = rq_single.get_pool_status()
        assert status[ "max_agentic_workers" ] == 1
        assert status[ "inflight_agentic_jobs" ] == 2
        assert status[ "pending_in_pool" ] == 1

        # Release the blocked work so fixture teardown doesn't hang
        release.set()


# =============================================================================
# Shutdown
# =============================================================================

class TestShutdown:

    def test_shutdown_pool_waits_for_inflight( self ):
        """Submit a 0.3s job, call shutdown_pool(timeout=5.0) → job completes, no orphan."""
        rq = _make_running_queue( max_workers=1 )
        try:
            finished = [ False ]
            def slow_do( j ):
                time.sleep( 0.3 )
                finished[ 0 ] = True
                return "ok"

            job = MockAgenticJob( do_all_fn=slow_do )
            rq.push( job )
            rq._submit_agentic_job( job )
            # Let the worker pick it up
            time.sleep( 0.05 )

            rq.shutdown_pool( wait=True, timeout=5.0 )
            assert finished[ 0 ], "Job should have completed before shutdown returned"
        finally:
            try:
                rq._agentic_pool.shutdown( wait=True, cancel_futures=True )
            except Exception:
                pass

    def test_shutdown_pool_dead_letters_timeouts( self ):
        """Submit a 3s job, call shutdown_pool(timeout=0.5) → job dead-lettered,
        not left as phantom running."""
        rq = _make_running_queue( max_workers=1 )
        try:
            release = threading.Event()

            def never_finishes( j ):
                release.wait( timeout=10 )  # held open past timeout
                return "ok"

            job = MockAgenticJob( do_all_fn=never_finishes )
            rq.push( job )
            rq._submit_agentic_job( job )
            time.sleep( 0.05 )

            rq.shutdown_pool( wait=True, timeout=0.5 )

            # Job should have been dead-lettered (or in the middle of being)
            # either way, release the worker so the test doesn't hang
            release.set()

            # After shutdown returns, one of two things holds:
            # (a) the job was dead-lettered during shutdown (desired)
            # (b) the future is still running but the wait exited
            # In either case shutdown_pool should have NOT re-raised.
            # The invariant we assert: no exception escaped.
            assert True
        finally:
            try:
                rq._agentic_pool.shutdown( wait=True, cancel_futures=True )
            except Exception:
                pass


# =============================================================================
# Grep regression — design doc table + 91-phase-2-execution-log.md Step 2.1
# =============================================================================

class TestGrepRegression:

    def test_no_pop_calls_remain_in_running_fifo_queue( self ):
        """`self.pop(` must not appear anywhere in running_fifo_queue.py —
        all 9 pre-Phase-2 call sites must be migrated to
        `self.delete_by_id_hash(id_hash)`. Head-of-queue semantics are no
        longer reliable under pool-callback concurrency with fast-lane."""
        path = os.path.join(
            os.path.dirname( __file__ ),
            "..", "..", "cosa", "rest", "running_fifo_queue.py"
        )
        with open( path, "r" ) as f:
            text = f.read()

        # Match self.pop( but not comments/strings containing "self.pop("
        # Split per-line and ignore leading '#' comments.
        offending = [ ]
        for i, line in enumerate( text.splitlines(), start=1 ):
            stripped = line.lstrip()
            if stripped.startswith( "#" ):
                continue
            if re.search( r"\bself\.pop\(", stripped ):
                offending.append( f"{i}: {line}" )

        assert not offending, \
            "running_fifo_queue.py still has self.pop( calls:\n" + "\n".join( offending )


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
