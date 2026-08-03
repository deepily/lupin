"""
In-process ASSEMBLY test for the monopolize lineage-pass-through fix (bug 3a14292b).

Where the per-gate unit tests (test_queue_consumer / test_fifo_queue_coverage /
test_running_fifo_queue) prove each gate in ISOLATION with mocks, this test drives
the REAL assembly end-to-end: a real FifoQueue (todo) + a real RunningFifoQueue
with a REAL ThreadPoolExecutor pool + the real background consumer thread. A
monopolize PARENT job, once running in the pool, pushes a LINEAGE CHILD
(spawned_by_id_hash == parent.id_hash) and a FOREIGN job (no lineage). It proves:

  1. the child is DISPATCHED while the parent's monopoly hold is ACTIVE
     (the ts-ad4670ec deadlock — children starved for the whole run — is gone);
  2. the foreign job stays DEFERRED during the hold (Gate B predicate rejects it);
  3. on parent completion the hold releases and the foreign job THEN dispatches
     (the FIFO-intact release path — PROVEN, not just asserted).

Worktree-honest: imports the modules under test via PYTHONPATH (NOT a live :7999
HTTP call, which would exercise the MAIN tree). No server, no DB — the heavy
RunningFifoQueue collaborators (InputAndOutputTable / GistNormalizer /
notify_user_sync) and the websocket emit are boundary-patched; the pool and the
consumer loop are REAL. Thread sync via threading.Event with hard timeouts.

IMPORTANT (why observations are recorded, not asserted, inside do_all): a parent
job's do_all() runs on a POOL thread; an AssertionError there is swallowed by
_on_agentic_complete's exception handling (routed to the dead-letter path). So the
parent RECORDS what it observed into a shared dict and the TEST thread asserts.
"""

import threading
import unittest
from unittest.mock import MagicMock, patch

import cosa.rest.running_fifo_queue as rfq
import cosa.rest.queue_consumer as qc
from cosa.rest.running_fifo_queue import RunningFifoQueue
from cosa.rest.fifo_queue import FifoQueue
from cosa.agents.agentic_job_base import AgenticJobBase


class _ProbeTodoQueue( FifoQueue ):
    """A real FifoQueue (so the REAL pop_next_eligible(predicate) under test runs)
    plus the minimal consumer-facing surface TodoFifoQueue adds."""

    def __init__( self ):
        super().__init__( websocket_mgr=MagicMock(), queue_name="todo", emit_enabled=False )
        self.condition        = threading.Condition()
        self.consumer_running = False
        self.debug            = False


class _ProbeJob( AgenticJobBase ):
    """Minimal real AgenticJobBase whose do_all() delegates to an injected fn."""

    JOB_TYPE   = "mock"     # NOT "test_suite" — a normal agentic job
    JOB_PREFIX = "probe"

    def __init__( self, label, do_all_fn, monopolize=False, spawned_by_id_hash=None ):
        super().__init__(
            user_id="u1", user_email="u@e.com", session_id="s1",
            monopolize=monopolize, spawned_by_id_hash=spawned_by_id_hash,
        )
        self._label     = label
        self._do_all_fn = do_all_fn

    @property
    def last_question_asked( self ):
        return self._label

    async def _execute( self ):          # abstractmethod — unused (do_all overridden)
        return self._label               # pragma: no cover

    def do_all( self ):
        return self._do_all_fn( self )


class TestMonopolizeLineageInProcess( unittest.TestCase ):
    """End-to-end assembly proof of the lineage pass-through fix (bug 3a14292b)."""

    POOL_WIDTH = 3   # shared-pool width; the Shape-B subclass overrides to 1

    def setUp( self ):
        # Boundary-patch ONLY the heavy DB/notification collaborators + emit.
        # ThreadPoolExecutor is deliberately NOT patched → a REAL pool.
        self._patchers = [
            patch.object( rfq, "InputAndOutputTable", MagicMock() ),
            patch.object( rfq, "GistNormalizer",      MagicMock() ),
            patch.object( rfq, "notify_user_sync",    MagicMock() ),
            patch.object( qc,  "emit_job_state_transition", MagicMock() ),
        ]
        for p in self._patchers:
            p.start()

        vals = {
            "debug auto": False, "debug inject bugs": False, "app debug": False,
            "app verbose": False, "similarity threshold confirmation": 90.0,
            "cj flow max concurrent agentic jobs": self.POOL_WIDTH,   # Shape-B subclass drops to 1
            "cj flow monopolize enabled": True,
            "cj flow consumer stall threshold seconds": 20,    # idle-wake = max(5, 5) = 5s
            "cj flow ghost job sweep interval seconds": 3600,  # sweeper never fires in-test
            "cj flow monopolize drain timeout seconds": 30,
        }
        cfg = MagicMock( name="config_mgr" )
        cfg.get.side_effect = lambda key, default=None, return_type=None: vals.get( key, default )

        self.todo    = _ProbeTodoQueue()
        self.running = RunningFifoQueue(
            app=MagicMock(), websocket_mgr=MagicMock(), snapshot_mgr=MagicMock(),
            jobs_todo_queue=self.todo, jobs_done_queue=MagicMock(),
            jobs_dead_queue=MagicMock(), config_mgr=cfg,
        )
        # Stub the heavy terminal-transition tails; the hold-release (in
        # _on_agentic_complete, BEFORE the transition) stays REAL.
        self.running._transition_to_done    = lambda job, output: None
        self.running._transition_to_dead    = lambda job, cause: None
        self.running._transition_to_stalled = lambda job, output: None

        self._consumer_thread = None

    def tearDown( self ):
        # Stop the consumer, the sweeper, and the pool, then unpatch.
        try:
            with self.todo.condition:
                self.todo.consumer_running = False
                self.todo.condition.notify_all()
            if self._consumer_thread is not None:
                self._consumer_thread.join( timeout=5 )
            self.running._ghost_job_sweeper_stop_event.set()
            self.running._agentic_pool.shutdown( wait=False )
        finally:
            for p in reversed( self._patchers ):
                p.stop()

    def test_lineage_child_dispatches_during_hold_foreign_deferred_then_released( self ):
        order      = []
        order_lock = threading.Lock()
        child_dispatched   = threading.Event()
        foreign_dispatched = threading.Event()
        observations       = {}

        def _note( label ):
            with order_lock:
                order.append( label )

        def _child_do_all( job ):
            _note( "child" )
            child_dispatched.set()
            return "child done"

        def _foreign_do_all( job ):
            _note( "foreign" )
            foreign_dispatched.set()
            return "foreign done"

        # Built inside the parent so the parent stamps the child's lineage with
        # its OWN id_hash — exactly the runtime lineage seam (test_suite sweep →
        # LUPIN_TEST_MONOPOLIZE_PARENT_ID → swe_team child's parent_id_hash).
        child   = None
        foreign = None

        def _parent_do_all( job ):
            _note( "parent" )
            nonlocal child, foreign
            child   = _ProbeJob( "child",   _child_do_all,   spawned_by_id_hash=job.id_hash )
            foreign = _ProbeJob( "foreign", _foreign_do_all, spawned_by_id_hash=None )
            # Push both while the monopoly hold is ACTIVE (this parent holds it).
            with self.todo.condition:
                self.todo.push( child )
                self.todo.push( foreign )
                self.todo.condition.notify_all()
            # The child MUST reach dispatch while we (the parent) still hold the pool.
            observations[ "child_dispatched_during_hold" ] = child_dispatched.wait( timeout=8 )
            # The foreign job MUST still be deferred — Gate B's predicate structurally
            # rejects it while _monopolize_active is set, so this is race-free.
            observations[ "foreign_deferred_during_hold" ] = not foreign_dispatched.is_set()
            observations[ "hold_active_during_parent" ]    = ( self.running._monopolize_active == job.id_hash )
            return "parent done"

        parent = _ProbeJob( "parent", _parent_do_all, monopolize=True )

        with self.todo.condition:
            self.todo.push( parent )
            self.todo.condition.notify_all()

        self._consumer_thread = qc.start_todo_producer_run_consumer_thread( self.todo, self.running )

        # Release path: once the parent completes, the hold clears and the deferred
        # foreign job dispatches (within one Gate-B poll ~1s). Generous timeout.
        dispatched = foreign_dispatched.wait( timeout=15 )

        # ── Assertions (on the TEST thread — do_all AssertionErrors are swallowed) ──
        self.assertTrue( observations.get( "hold_active_during_parent" ),
                         "the parent's monopolize hold should be active while it runs" )
        self.assertTrue( observations.get( "child_dispatched_during_hold" ),
                         "lineage child must dispatch DURING the monopoly hold (deadlock gone)" )
        self.assertTrue( observations.get( "foreign_deferred_during_hold" ),
                         "foreign job must stay DEFERRED while the hold is active" )
        self.assertTrue( dispatched,
                         "foreign job must dispatch after the parent releases the hold" )
        # FIFO-intact release path: parent → child (during hold) → foreign (after release).
        self.assertEqual( order, [ "parent", "child", "foreign" ],
                          f"dispatch order should be parent→child→foreign, got {order}" )
        # The hold was truly released (not merely un-observed).
        self.assertIsNone( self.running._monopolize_active,
                           "monopoly hold must be cleared after the parent completes" )


class TestMonopolizeOutsidePoolWidthOne( TestMonopolizeLineageInProcess ):
    """Shape-B (bug fe375cf6): the SAME end-to-end assembly proof re-run on a
    pool_max==1 SHARED pool — the width Shape-A's belt refuses because it DEADLOCKS
    pre-Shape-B (the in-pool monopolizer holds the only worker, so its lineage child
    can never acquire a slot; Gate B admits the child through intake but cannot conjure
    a pool slot).

    Under Shape-B the monopolizer runs on the DEDICATED single-worker executor, so the
    sole shared-pool worker stays free for the child: the child dispatches DURING the
    hold, the foreign job defers, and the release path is intact — dispatch order still
    parent→child→foreign. If the child dispatches during the hold at width 1, the
    monopolizer provably occupied ZERO shared-pool slots. This is the deterministic
    regression guard standing in for the (retained-for-now) pool_max==1 belt.

    RED-first: on the pre-Shape-B source (monopolizer in the shared pool) this same
    test hangs the child until the parent exits → child_dispatched_during_hold=False →
    the inherited assertions fail. Confirmed RED before the fix, GREEN after."""

    POOL_WIDTH = 1


def isolated_unit_test():
    """Run this assembly test in isolation; returns (success, duration, message)."""
    import time
    start = time.time()
    loader = unittest.TestLoader()
    suite  = unittest.TestSuite()
    for tc in ( TestMonopolizeLineageInProcess, TestMonopolizeOutsidePoolWidthOne ):
        suite.addTests( loader.loadTestsFromTestCase( tc ) )
    result = unittest.TextTestRunner( verbosity=2 ).run( suite )
    duration = time.time() - start
    success  = result.wasSuccessful()
    message  = f"{result.testsRun} run, {len( result.failures )} failed, {len( result.errors )} errors"
    return success, duration, message


if __name__ == "__main__":
    ok, secs, msg = isolated_unit_test()
    print( f"\n{'✅ PASS' if ok else '❌ FAIL'} monopolize-lineage in-process test in {secs:.3f}s — {msg}" )
