"""
Unit tests for the CJ Flow execution engine (cosa.rest.running_fifo_queue).

Drives RunningFifoQueue to genuine 100% line + branch + function coverage with
ZERO real concurrency, GPU, DB, network, or LLM:

  - threading.Thread is replaced by a capture-only fake so __init__ NEVER starts
    the real ghost-job-sweeper daemon; the sweep loop is driven synchronously
    with a controlled stop-event (memento Thread-capture pattern).
  - ThreadPoolExecutor is a MagicMock — no real pool, no real workers. Futures
    are MagicMock stand-ins whose .done()/.exception()/.result() are scripted.
  - The 6 isinstance dispatch classes (AgentBase, AgenticJobBase, SolutionSnapshot,
    CrudForDataFramesAgent, ReceptionistAgent, WeatherAgent) are patched with
    lightweight fakes so dispatch is exercised without importing heavy agents.
  - InputAndOutputTable, GistNormalizer, emit_job_state_transition, notify_user_sync
    are boundary-mocked. self._notify is stubbed per instance.
  - The real FifoQueue base is used for the running queue so delete_by_id_hash /
    get_by_id_hash / queue_dict behave realistically; jobs are inserted directly
    into queue_dict/queue_list (bypassing the QueueableJob protocol gate). The
    done/dead/todo queues are MagicMocks.

quick_smoke_test() + __main__ are coverage-excluded (pyproject exclude_also).
"""

import unittest
from unittest.mock import MagicMock, patch

from cosa.rest import running_fifo_queue as rfq
from cosa.rest.running_fifo_queue import RunningFifoQueue
from cosa.rest.job_state import JobState


# ── Lightweight fake job hierarchy (real instances, so isinstance works) ─────
class _Job:
    """Flexible fake job exposing every attribute/method the SUT reads."""

    def __init__( self, **kw ):
        d = dict(
            id_hash="h1", user_id="u1", user_email="e@x.com", session_id="s1",
            last_question_asked="what time is it?", routing_command="agent router go to x",
            job_type="jt", created_date="2026-01-01", started_at="2026-01-01T00:00:00",
            answer_conversational="the answer", answer="raw answer", is_cache_hit=False,
            state=None, error=None, artifacts={}, solution_summary_gist="gist",
            solution_summary="summary", thoughts="thoughts", runtime_stats={},
            answer_is_correct=None, question="what time is it?",
            _do_all_return="output", _do_all_exc=None, _code_ok=True, _fmt_ok=True,
            _code_response={ "return_code": 0, "output": "ok" }, _formatted="fmt",
        )
        d.update( kw )
        self.__dict__.update( d )

    def do_all( self ):
        if self._do_all_exc is not None: raise self._do_all_exc
        return self._do_all_return

    def code_ran_to_completion( self ): return self._code_ok
    def formatter_ran_to_completion( self ): return self._fmt_ok

    def run_code( self, **kw ):
        if isinstance( self._code_response, Exception ): raise self._code_response
        return self._code_response

    def run_formatter( self ): return self._formatted
    def set_solution_summary_gist( self, v ): self.solution_summary_gist = v
    def update_runtime_stats( self, t ): pass
    def record_replay( self, **kw ): pass

    def for_current_user( self, **kw ):
        c = type( self )(); c.__dict__.update( self.__dict__ ); return c


class _AgentBaseFake( _Job ): pass
class _AgenticFake( _Job ):
    def __init__( self, **kw ):
        kw.setdefault( "JOB_TYPE", "AgenticType" )
        kw.setdefault( "spawned_by_id_hash", None )   # mirror AgenticJobBase (bug 3a14292b)
        super().__init__( **kw )
class _SnapFake( _Job ):
    @classmethod
    def create( cls, job ):
        c = cls(); c.__dict__.update( job.__dict__ ); return c
class _CrudFake( _AgentBaseFake ): pass
class _ReceptionistFake( _AgentBaseFake ): pass
class _WeatherFake( _AgentBaseFake ): pass


class _FakeThread:
    """Capture-only Thread: never starts a real thread."""
    last = None
    def __init__( self, target=None, daemon=None, name=None, **kw ):
        self.target = target; self.daemon = daemon; self.name = name; self._alive = False
        _FakeThread.last = self
    def start( self ): pass
    def join( self, timeout=None ): pass
    def is_alive( self ): return self._alive


class _RFQBase( unittest.TestCase ):
    """
    Boundary-mock harness for RunningFifoQueue.

    Requires:
        - cosa.rest.running_fifo_queue imports cleanly

    Ensures:
        - setUp patches all heavy collaborators + concurrency primitives
        - build() returns a fully boundary-mocked RunningFifoQueue with a
          stubbed _notify and a real FifoQueue base
        - tearDown stops all patches

    Raises:
        - None
    """

    def setUp( self ):
        self._patchers = []

        def _p( target, **kw ):
            pt = patch.object( rfq, target, **kw ); m = pt.start(); self._patchers.append( pt ); return m

        _p( "AgentBase",              new=_AgentBaseFake )
        _p( "AgenticJobBase",         new=_AgenticFake )
        _p( "SolutionSnapshot",       new=_SnapFake )
        _p( "CrudForDataFramesAgent", new=_CrudFake )
        _p( "ReceptionistAgent",      new=_ReceptionistFake )
        _p( "WeatherAgent",           new=_WeatherFake )

        self.io_cls    = _p( "InputAndOutputTable" )
        self.gist_cls  = _p( "GistNormalizer" )
        self.emit      = _p( "emit_job_state_transition" )
        self.notify_fn = _p( "notify_user_sync" )
        self.pool_cls  = _p( "ThreadPoolExecutor" )
        # Shape-B (bug fe375cf6): RunningFifoQueue now builds TWO executors — the
        # shared _agentic_pool and the dedicated _monopolize_pool. Return a DISTINCT
        # mock per construction so the two are separable (e.g. shutdown asserts each
        # once; routing asserts submit lands on the right one).
        self.pool_cls.side_effect = lambda *a, **k: MagicMock( name="ThreadPoolExecutor()" )

        self._thread_patch = patch.object( rfq.threading, "Thread", _FakeThread )
        self._thread_patch.start(); self._patchers.append( self._thread_patch )

    def tearDown( self ):
        for pt in reversed( self._patchers ): pt.stop()

    def _cfg( self, **over ):
        c = MagicMock( name="config_mgr" )
        vals = {
            "debug auto": False, "debug inject bugs": False, "app debug": False,
            "app verbose": False, "similarity threshold confirmation": 90.0,
            "cj flow max concurrent agentic jobs": 1,
            "cj flow consumer stall threshold seconds": 120,
            "cj flow ghost job sweep interval seconds": 30,
        }
        vals.update( over )
        c.get.side_effect = lambda key, default=None, return_type=None: vals.get( key, default )
        return c

    def build( self, config_mgr="default", **cfg_over ):
        if config_mgr == "default": config_mgr = self._cfg( **cfg_over )
        rq = RunningFifoQueue(
            app=MagicMock(), websocket_mgr=MagicMock(), snapshot_mgr=MagicMock(),
            jobs_todo_queue=MagicMock(), jobs_done_queue=MagicMock(),
            jobs_dead_queue=MagicMock(), config_mgr=config_mgr,
        )
        rq._notify = MagicMock( name="_notify" )
        self.pool = rq._agentic_pool   # the MagicMock pool instance
        return rq

    def _enqueue( self, rq, job ):
        """Insert a job directly into the running queue (bypass protocol gate)."""
        rq.queue_dict[ job.id_hash ] = job
        rq.queue_list = list( rq.queue_dict.values() )


# ── Construction ─────────────────────────────────────────────────────────────
class TestConstruction( _RFQBase ):

    def test_build_with_config( self ):
        rq = self.build()
        self.assertEqual( rq._pool_max_workers, 1 )
        self.assertEqual( rq._consumer_stall_threshold_seconds, 120 )
        self.assertIsNone( rq.last_consumer_heartbeat_at )
        self.assertEqual( rq._agentic_futures, {} )
        # ghost sweeper thread is the capture-fake, not started
        self.assertIs( rq._ghost_job_sweeper_thread, _FakeThread.last )

    def test_build_with_none_config( self ):
        rq = self.build( config_mgr=None )
        self.assertFalse( rq.auto_debug )
        self.assertFalse( rq.inject_bugs )
        self.assertEqual( rq.threshold_confirmation, 90.0 )
        self.assertEqual( rq._pool_max_workers, 1 )
        self.assertEqual( rq._consumer_stall_threshold_seconds, 120 )


# ── _submit_agentic_job / _execute_agentic_in_pool ──────────────────────────
class TestSubmitAgentic( _RFQBase ):

    def test_submit_tracks_future_and_callback( self ):
        rq = self.build()
        fut = MagicMock( name="future" )
        rq._agentic_pool.submit.return_value = fut
        job = _AgenticFake( id_hash="aj1" )
        rq._submit_agentic_job( job )
        self.assertIs( rq._agentic_futures[ "aj1" ], fut )
        rq._agentic_pool.submit.assert_called_once()
        fut.add_done_callback.assert_called_once()

    def test_monopolize_routes_to_dedicated_executor_plain_to_shared( self ):
        """Shape-B (bug fe375cf6): a monopolize job submits to the DEDICATED
        _monopolize_pool (and sets the hold); a plain job submits to the shared
        _agentic_pool (no hold). Both are tracked in the SAME _agentic_futures dict."""
        rq = self.build()
        plain = _AgenticFake( id_hash="plain", monopolize=False )
        rq._submit_agentic_job( plain )
        rq._agentic_pool.submit.assert_called_once()
        rq._monopolize_pool.submit.assert_not_called()
        self.assertIn( "plain", rq._agentic_futures )
        self.assertIsNone( rq._monopolize_active )
        mono = _AgenticFake( id_hash="mono", monopolize=True )
        rq._submit_agentic_job( mono )
        rq._monopolize_pool.submit.assert_called_once()          # dedicated executor
        rq._agentic_pool.submit.assert_called_once()             # shared pool NOT re-used
        self.assertIn( "mono", rq._agentic_futures )             # SAME dict → ghost-sweep/callback cover it
        self.assertEqual( rq._monopolize_active, "mono" )        # hold set

    def test_monopolize_disabled_kill_switch_routes_to_shared_no_hold( self ):
        """When the master kill-switch is OFF, a monopolize job routes to the SHARED
        pool and sets no hold (is_mono is False) — the old no-op behavior."""
        rq = self.build( **{ "cj flow monopolize enabled": False } )
        mono = _AgenticFake( id_hash="mono2", monopolize=True )
        rq._submit_agentic_job( mono )
        rq._agentic_pool.submit.assert_called_once()
        rq._monopolize_pool.submit.assert_not_called()
        self.assertIsNone( rq._monopolize_active )

    def test_execute_in_pool_calls_do_all( self ):
        rq = self.build()
        job = _AgenticFake( _do_all_return="RESULT" )
        self.assertEqual( rq._execute_agentic_in_pool( job ), "RESULT" )


# ── _on_agentic_complete ────────────────────────────────────────────────────
class TestOnAgenticComplete( _RFQBase ):

    def _future( self, exc=None, result=None ):
        f = MagicMock( name="future" )
        f.exception.return_value = exc
        f.result.return_value = result
        return f

    def test_regular_exception_dead_letters( self ):
        rq = self.build(); rq._transition_to_dead = MagicMock()
        job = _AgenticFake( id_hash="x" ); rq._agentic_futures[ "x" ] = "f"
        rq._on_agentic_complete( job, self._future( exc=ValueError( "boom" ) ) )
        rq._transition_to_dead.assert_called_once()
        self.assertNotIn( "x", rq._agentic_futures )

    def test_base_exception_survivor_logged_only( self ):
        rq = self.build(); rq._transition_to_dead = MagicMock()
        job = _AgenticFake()
        rq._on_agentic_complete( job, self._future( exc=KeyboardInterrupt() ) )
        rq._transition_to_dead.assert_not_called()

    def test_stalled_routes_to_stalled( self ):
        rq = self.build(); rq._transition_to_stalled = MagicMock(); rq._transition_to_done = MagicMock()
        job = _AgenticFake( state=JobState.STALLED )
        rq._on_agentic_complete( job, self._future( result="out" ) )
        rq._transition_to_stalled.assert_called_once()
        rq._transition_to_done.assert_not_called()

    def test_failed_state_routes_to_dead( self ):
        rq = self.build(); rq._transition_to_dead = MagicMock()
        job = _AgenticFake( state=JobState.FAILED, error="explicit err" )
        rq._on_agentic_complete( job, self._future( result="out" ) )
        rq._transition_to_dead.assert_called_once_with( job, "explicit err" )

    def test_failed_state_no_error_uses_output_then_default( self ):
        rq = self.build(); rq._transition_to_dead = MagicMock()
        job = _AgenticFake( state=JobState.FAILED, error="" )
        rq._on_agentic_complete( job, self._future( result="" ) )
        cause = rq._transition_to_dead.call_args[ 0 ][ 1 ]
        self.assertEqual( cause, "Job reported FAILED with no error message" )

    def test_success_routes_to_done( self ):
        rq = self.build(); rq._transition_to_done = MagicMock()
        job = _AgenticFake( state=None )
        rq._on_agentic_complete( job, self._future( result="out" ) )
        rq._transition_to_done.assert_called_once_with( job, "out" )

    def test_outer_baseexception_caught_and_dead_lettered( self ):
        # transition_to_done raises a regular Exception -> outer catch dead-letters
        rq = self.build()
        rq._transition_to_done = MagicMock( side_effect=RuntimeError( "inner" ) )
        rq._transition_to_dead = MagicMock()
        job = _AgenticFake( state=None )
        rq._on_agentic_complete( job, self._future( result="out" ) )
        rq._transition_to_dead.assert_called_once()

    def test_outer_dead_letter_also_fails( self ):
        rq = self.build()
        rq._transition_to_done = MagicMock( side_effect=RuntimeError( "inner" ) )
        rq._transition_to_dead = MagicMock( side_effect=RuntimeError( "dead fail" ) )
        job = _AgenticFake( state=None )
        rq._on_agentic_complete( job, self._future( result="out" ) )  # must not raise

    def test_outer_baseexception_not_exception_no_dead_letter( self ):
        rq = self.build()
        rq._transition_to_done = MagicMock( side_effect=KeyboardInterrupt() )
        rq._transition_to_dead = MagicMock()
        job = _AgenticFake( state=None )
        rq._on_agentic_complete( job, self._future( result="out" ) )
        rq._transition_to_dead.assert_not_called()


# ── _transition_to_done ─────────────────────────────────────────────────────
class TestTransitionToDone( _RFQBase ):

    def test_done_happy_path_with_duration( self ):
        rq = self.build(); job = _AgenticFake( id_hash="d1" ); self._enqueue( rq, job )
        with patch( "cosa.rest.test_suite_completion_watchdog.get_watchdog" ) as gw:
            wd = MagicMock(); gw.return_value = wd
            rq._transition_to_done( job, "formatted" )
        self.emit.assert_called_once()
        rq.jobs_done_queue.push.assert_called_once_with( job )
        wd.evaluate.assert_called_once_with( job )
        self.assertNotIn( "d1", rq.queue_dict )

    def test_done_started_at_none_skips_duration( self ):
        rq = self.build(); job = _AgenticFake( id_hash="d2", started_at=None ); self._enqueue( rq, job )
        with patch( "cosa.rest.test_suite_completion_watchdog.get_watchdog", return_value=None ):
            rq._transition_to_done( job, "f" )
        self.emit.assert_called_once()

    def test_done_bad_timestamp_swallows( self ):
        rq = self.build(); job = _AgenticFake( id_hash="d3", started_at="not-a-date" ); self._enqueue( rq, job )
        with patch( "cosa.rest.test_suite_completion_watchdog.get_watchdog", return_value=None ):
            rq._transition_to_done( job, "f" )
        self.emit.assert_called_once()

    def test_done_watchdog_raises_and_io_raises( self ):
        rq = self.build( **{ "app debug": True } ); job = _AgenticFake( id_hash="d4" ); self._enqueue( rq, job )
        rq.io_tbl.insert_io_row.side_effect = RuntimeError( "io down" )
        with patch( "cosa.rest.test_suite_completion_watchdog.get_watchdog", side_effect=RuntimeError( "wd boom" ) ):
            rq._transition_to_done( job, None )   # formatted_output None -> str(artifacts) path uses {} falsy -> str(None)
        self.emit.assert_called_once()

    def test_done_with_artifacts_output_raw( self ):
        rq = self.build(); job = _AgenticFake( id_hash="d5", artifacts={ "abstract": "a" } ); self._enqueue( rq, job )
        with patch( "cosa.rest.test_suite_completion_watchdog.get_watchdog", return_value=None ):
            rq._transition_to_done( job, "f" )
        rq.io_tbl.insert_io_row.assert_called_once()


# ── _transition_to_stalled ──────────────────────────────────────────────────
class TestTransitionToStalled( _RFQBase ):

    def test_stalled_happy( self ):
        rq = self.build(); job = _AgenticFake( id_hash="s1" ); self._enqueue( rq, job )
        rq._transition_to_stalled( job, "out" )
        self.emit.assert_called_once()
        rq.jobs_done_queue.push.assert_called_once_with( job )

    def test_stalled_started_none_and_io_raises( self ):
        rq = self.build( **{ "app debug": True } ); job = _AgenticFake( id_hash="s2", started_at=None ); self._enqueue( rq, job )
        rq.io_tbl.insert_io_row.side_effect = RuntimeError( "io" )
        rq._transition_to_stalled( job, None )
        self.emit.assert_called_once()

    def test_stalled_bad_timestamp( self ):
        rq = self.build(); job = _AgenticFake( id_hash="s3", started_at="bad" ); self._enqueue( rq, job )
        rq._transition_to_stalled( job, "x" )
        self.emit.assert_called_once()


# ── _transition_to_dead ─────────────────────────────────────────────────────
class TestTransitionToDead( _RFQBase ):

    def test_dead_string_cause( self ):
        rq = self.build(); job = _AgenticFake( id_hash="x1", error=None ); self._enqueue( rq, job )
        with patch.object( rq, "_evaluate_for_auto_fix" ) as ev:
            rq._transition_to_dead( job, "string failure" )
        self.assertEqual( job.error, "string failure" )
        self.assertEqual( job.state, JobState.FAILED )
        rq.jobs_dead_queue.push.assert_called_once_with( job )
        ev.assert_called_once_with( job )

    def test_dead_exception_cause_with_traceback( self ):
        rq = self.build(); job = _AgenticFake( id_hash="x2", error=None ); self._enqueue( rq, job )
        try:
            raise ValueError( "kaboom" )
        except ValueError as e:
            exc = e
        with patch.object( rq, "_evaluate_for_auto_fix" ):
            rq._transition_to_dead( job, exc )
        self.assertEqual( job.error, "kaboom" )

    def test_dead_exception_traceback_format_fails( self ):
        # cause is an Exception whose traceback formatting raises -> except -> stack_trace=error_msg
        rq = self.build(); job = _AgenticFake( id_hash="x3", error="pre" ); self._enqueue( rq, job )
        exc = ValueError( "msg" )
        with patch.object( rfq.traceback, "format_exception", side_effect=RuntimeError( "fmt" ) ), \
             patch.object( rq, "_evaluate_for_auto_fix" ):
            rq._transition_to_dead( job, exc )
        # job.error already set ("pre") -> not overwritten
        self.assertEqual( job.error, "pre" )

    def test_dead_job_attr_set_raises_swallowed( self ):
        # job.error assignment raises -> except pass (boundary tolerance)
        rq = self.build()
        class _Brittle( _AgenticFake ):
            @property
            def error( self ): return self._err
            @error.setter
            def error( self, v ): raise AttributeError( "read only" )
        job = _Brittle( id_hash="x4", _err=None ); self._enqueue( rq, job )
        with patch.object( rq, "_evaluate_for_auto_fix" ):
            rq._transition_to_dead( job, "cause" )   # must not raise
        rq.jobs_dead_queue.push.assert_called_once()

    def test_dead_started_at_none( self ):
        rq = self.build(); job = _AgenticFake( id_hash="x5", started_at=None, error=None ); self._enqueue( rq, job )
        with patch.object( rq, "_evaluate_for_auto_fix" ):
            rq._transition_to_dead( job, "c" )
        self.emit.assert_called_once()

    def test_dead_bad_timestamp( self ):
        rq = self.build(); job = _AgenticFake( id_hash="x6", started_at="bad", error=None ); self._enqueue( rq, job )
        with patch.object( rq, "_evaluate_for_auto_fix" ):
            rq._transition_to_dead( job, "c" )
        self.emit.assert_called_once()

    def test_dead_auto_fix_raises_swallowed( self ):
        rq = self.build( **{ "app debug": True } ); job = _AgenticFake( id_hash="x7", error=None ); self._enqueue( rq, job )
        with patch.object( rq, "_evaluate_for_auto_fix", side_effect=RuntimeError( "ev" ) ):
            rq._transition_to_dead( job, "c" )   # must not raise
        rq.jobs_dead_queue.push.assert_called_once()

    def test_dead_uses_JOB_TYPE_when_present( self ):
        rq = self.build(); job = _AgenticFake( id_hash="x8", error=None, JOB_TYPE="MyType" ); self._enqueue( rq, job )
        with patch.object( rq, "_evaluate_for_auto_fix" ):
            rq._transition_to_dead( job, "c" )
        # _notify is stubbed; assert it was called (urgent path)
        rq._notify.assert_called_once()


# ── get_pool_status ─────────────────────────────────────────────────────────
class TestGetPoolStatus( _RFQBase ):

    def test_status_counts_and_heartbeat_none( self ):
        rq = self.build()
        f_run  = MagicMock(); f_run.done.return_value=False;  f_run.running.return_value=True
        f_pend = MagicMock(); f_pend.done.return_value=False; f_pend.running.return_value=False
        f_done = MagicMock(); f_done.done.return_value=True;  f_done.running.return_value=False
        rq._agentic_futures = { "a": f_run, "b": f_pend, "c": f_done }
        with patch( "cosa.utils.api_resource_manager.get_arm" ) as ga:
            ga.return_value.get_status.return_value = { "x": 1 }
            out = rq.get_pool_status()
        self.assertEqual( out[ "inflight_agentic_jobs" ], 2 )   # run + pend not done
        self.assertEqual( out[ "pending_in_pool" ], 1 )
        self.assertIsNone( out[ "last_consumer_heartbeat_at" ] )
        self.assertIsNone( out[ "seconds_since_heartbeat" ] )
        self.assertFalse( out[ "consumer_stalled" ] )
        self.assertEqual( out[ "api_resource_manager" ], { "x": 1 } )

    def test_status_excludes_monopolizer_and_reports_fields( self ):
        """Shape-B (bug fe375cf6): the active monopolizer's Future is in
        _agentic_futures but EXCLUDED from the shared-pool inflight/pending counts
        (it runs on the dedicated executor, not a shared-pool worker); surfaced via
        the additive monopolize_inflight/monopolize_id fields."""
        rq = self.build()
        f_mono  = MagicMock(); f_mono.done.return_value=False;  f_mono.running.return_value=True
        f_child = MagicMock(); f_child.done.return_value=False; f_child.running.return_value=False
        rq._agentic_futures = { "mono": f_mono, "child": f_child }
        rq._monopolize_active = "mono"
        with patch( "cosa.utils.api_resource_manager.get_arm" ) as ga:
            ga.return_value.get_status.return_value = {}
            out = rq.get_pool_status()
        self.assertEqual( out[ "inflight_agentic_jobs" ], 1 )   # child only; monopolizer excluded
        self.assertEqual( out[ "pending_in_pool" ], 1 )         # child pending (not running); mono excluded
        self.assertTrue( out[ "monopolize_inflight" ] )
        self.assertEqual( out[ "monopolize_id" ], "mono" )

    def test_status_no_monopolizer_reports_false_none( self ):
        """No monopolizer → monopolize_inflight False, monopolize_id None, and the
        shared-pool counts include everything (nothing excluded)."""
        rq = self.build()
        f = MagicMock(); f.done.return_value=False; f.running.return_value=True
        rq._agentic_futures = { "a": f }
        rq._monopolize_active = None
        with patch( "cosa.utils.api_resource_manager.get_arm" ) as ga:
            ga.return_value.get_status.return_value = {}
            out = rq.get_pool_status()
        self.assertEqual( out[ "inflight_agentic_jobs" ], 1 )
        self.assertFalse( out[ "monopolize_inflight" ] )
        self.assertIsNone( out[ "monopolize_id" ] )

    def test_status_heartbeat_present_and_stalled( self ):
        from datetime import datetime, timedelta
        rq = self.build()
        rq.last_consumer_heartbeat_at = datetime.now() - timedelta( seconds=999 )
        with patch( "cosa.utils.api_resource_manager.get_arm" ) as ga:
            ga.return_value.get_status.return_value = {}
            out = rq.get_pool_status()
        self.assertTrue( out[ "consumer_stalled" ] )
        self.assertIsNotNone( out[ "seconds_since_heartbeat" ] )

    def test_status_arm_uninitialised( self ):
        rq = self.build()
        with patch( "cosa.utils.api_resource_manager.get_arm", side_effect=RuntimeError ):
            out = rq.get_pool_status()
        self.assertEqual( out[ "api_resource_manager" ], { "state": "uninitialised" } )

    def test_status_arm_error( self ):
        rq = self.build()
        with patch( "cosa.utils.api_resource_manager.get_arm", side_effect=ValueError( "weird" ) ):
            out = rq.get_pool_status()
        self.assertEqual( out[ "api_resource_manager" ][ "state" ], "error" )


# ── get_non_test_inflight_agentic_jobs (bug caf58f71 — concurrent-writer classifier)
class TestNonTestInflightClassifier( _RFQBase ):
    """The merge-gate sweep exclusivity classifier: which inflight agentic jobs
    are NON-test writers on the shared lupin_db_test, so the sweep can fail loud."""

    @staticmethod
    def _future( done ):
        f = MagicMock( name="future" ); f.done.return_value = done; return f

    def test_done_futures_are_not_offenders( self ):
        """A completed (done) future is not inflight — never an offender, even
        for a non-test job."""
        rq  = self.build()
        job = _AgenticFake( id_hash="d1", job_type="deep_research" )
        self._enqueue( rq, job )
        rq._agentic_futures = { "d1": self._future( done=True ) }
        self.assertEqual( rq.get_non_test_inflight_agentic_jobs(), [ ] )

    def test_self_is_excluded_by_id_hash( self ):
        """The sweep's OWN inflight future must be skipped via exclude_id_hash."""
        rq  = self.build()
        job = _AgenticFake( id_hash="sweep", job_type="test_suite" )
        self._enqueue( rq, job )
        rq._agentic_futures = { "sweep": self._future( done=False ) }
        self.assertEqual(
            rq.get_non_test_inflight_agentic_jobs( exclude_id_hash="sweep" ), [ ]
        )

    def test_other_test_suite_job_is_not_an_offender( self ):
        """Another test_suite job (job_type == 'test_suite') is not a foreign
        writer — skipped even without exclude_id_hash."""
        rq  = self.build()
        job = _AgenticFake( id_hash="ts2", job_type="test_suite" )
        self._enqueue( rq, job )
        rq._agentic_futures = { "ts2": self._future( done=False ) }
        self.assertEqual( rq.get_non_test_inflight_agentic_jobs(), [ ] )

    def test_inflight_non_test_job_is_an_offender( self ):
        """An inflight non-test agentic job IS a concurrent writer → offender,
        reported with its id_hash and job_type."""
        rq  = self.build()
        job = _AgenticFake( id_hash="dr1", job_type="deep_research" )
        self._enqueue( rq, job )
        rq._agentic_futures = { "dr1": self._future( done=False ) }
        out = rq.get_non_test_inflight_agentic_jobs( exclude_id_hash="sweep" )
        self.assertEqual( out, [ { "id_hash": "dr1", "job_type": "deep_research" } ] )

    def test_inflight_future_without_backing_job_is_unknown_offender( self ):
        """A future present + inflight but whose job is gone from queue_dict is
        fail-loud 'unknown' — an unclassifiable writer we cannot vouch for."""
        rq = self.build()
        rq._agentic_futures = { "ghost": self._future( done=False ) }  # not enqueued
        out = rq.get_non_test_inflight_agentic_jobs()
        self.assertEqual( out, [ { "id_hash": "ghost", "job_type": "unknown" } ] )

    def test_mixed_pool_reports_only_foreign_inflight_writers( self ):
        """Full mix: self (excluded), a done non-test (not inflight), another
        test_suite (skipped), and one live foreign writer → only the last."""
        rq = self.build()
        for h, jt in [ ( "sweep", "test_suite" ), ( "ts2", "test_suite" ),
                       ( "dr_done", "deep_research" ), ( "pod_live", "podcast" ) ]:
            self._enqueue( rq, _AgenticFake( id_hash=h, job_type=jt ) )
        rq._agentic_futures = {
            "sweep"   : self._future( done=False ),
            "ts2"     : self._future( done=False ),
            "dr_done" : self._future( done=True ),
            "pod_live": self._future( done=False ),
        }
        out = rq.get_non_test_inflight_agentic_jobs( exclude_id_hash="sweep" )
        self.assertEqual( out, [ { "id_hash": "pod_live", "job_type": "podcast" } ] )

    def test_lineage_child_of_sweep_is_exempted( self ):
        """bug 3a14292b: an inflight job SPAWNED BY the sweep (spawned_by_id_hash ==
        exclude_id_hash) is not foreign TO the sweep — exempted even though its
        job_type is not test_suite."""
        rq    = self.build()
        child = _AgenticFake( id_hash="swe1", job_type="swe_team", spawned_by_id_hash="sweep" )
        self._enqueue( rq, child )
        rq._agentic_futures = { "swe1": self._future( done=False ) }
        self.assertEqual(
            rq.get_non_test_inflight_agentic_jobs( exclude_id_hash="sweep" ), [ ]
        )

    def test_lineage_of_other_parent_is_still_foreign( self ):
        """A child of a DIFFERENT parent (spawned_by_id_hash != exclude_id_hash) is
        still a foreign writer — the exemption is lineage-scoped, not blanket."""
        rq    = self.build()
        other = _AgenticFake( id_hash="swe2", job_type="swe_team", spawned_by_id_hash="other-sweep" )
        self._enqueue( rq, other )
        rq._agentic_futures = { "swe2": self._future( done=False ) }
        out = rq.get_non_test_inflight_agentic_jobs( exclude_id_hash="sweep" )
        self.assertEqual( out, [ { "id_hash": "swe2", "job_type": "swe_team" } ] )

    def test_no_exclude_id_hash_does_not_exempt_lineage( self ):
        """With exclude_id_hash None, a job's default-None lineage must NOT match
        (None == None) and wrongly exempt it — the guard keys on a real sweep id."""
        rq  = self.build()
        job = _AgenticFake( id_hash="dr9", job_type="deep_research" )   # spawned_by_id_hash defaults None
        self._enqueue( rq, job )
        rq._agentic_futures = { "dr9": self._future( done=False ) }
        out = rq.get_non_test_inflight_agentic_jobs()                    # exclude_id_hash=None
        self.assertEqual( out, [ { "id_hash": "dr9", "job_type": "deep_research" } ] )


# ── assert_monopolize_pool_capacity (bug 3a14292b — Shape-B pool_max==1 belt) ─
class TestMonopolizePoolCapacityGuard( _RFQBase ):
    """A monopolize sweep that spawns pool children hard-deadlocks on a width-1
    pool; the guard refuses it LOUD (raises) so the router can 422."""

    def test_width_one_raises_naming_deadlock( self ):
        rq = self.build( **{ "cj flow max concurrent agentic jobs": 1 } )
        with self.assertRaises( RuntimeError ) as ctx:
            rq.assert_monopolize_pool_capacity()
        msg = str( ctx.exception )
        self.assertIn( "3a14292b", msg )
        self.assertIn( "1", msg )                          # names the offending width
        self.assertIn( "cj flow max concurrent agentic jobs", msg )

    def test_width_two_or_more_passes( self ):
        rq = self.build( **{ "cj flow max concurrent agentic jobs": 3 } )
        self.assertIsNone( rq.assert_monopolize_pool_capacity() )   # no raise → room for children


# ── _ghost_job_sweep + loop ─────────────────────────────────────────────────
class TestGhostSweep( _RFQBase ):

    def test_sweep_skips_not_done( self ):
        rq = self.build(); rq._transition_to_dead = MagicMock()
        f = MagicMock(); f.done.return_value=False
        rq._agentic_futures = { "g": f }
        rq._ghost_job_sweep()
        rq._transition_to_dead.assert_not_called()

    def test_sweep_job_gone_cleans_tracker( self ):
        rq = self.build(); rq._transition_to_dead = MagicMock()
        f = MagicMock(); f.done.return_value=True
        rq._agentic_futures = { "gone": f }   # not in queue_dict
        rq._ghost_job_sweep()
        rq._transition_to_dead.assert_not_called()
        self.assertNotIn( "gone", rq._agentic_futures )

    def test_sweep_ghost_dead_letters_with_future_exc( self ):
        rq = self.build(); rq._transition_to_dead = MagicMock()
        job = _AgenticFake( id_hash="ghost" ); self._enqueue( rq, job )
        f = MagicMock(); f.done.return_value=True; f.exception.return_value=ValueError( "fx" )
        rq._agentic_futures = { "ghost": f }
        rq._ghost_job_sweep()
        rq._transition_to_dead.assert_called_once()
        self.assertNotIn( "ghost", rq._agentic_futures )

    def test_sweep_ghost_no_future_exc_uses_runtimeerror( self ):
        rq = self.build(); rq._transition_to_dead = MagicMock()
        job = _AgenticFake( id_hash="ghost2" ); self._enqueue( rq, job )
        f = MagicMock(); f.done.return_value=True; f.exception.return_value=None
        rq._agentic_futures = { "ghost2": f }
        rq._ghost_job_sweep()
        cause = rq._transition_to_dead.call_args[ 0 ][ 1 ]
        self.assertIsInstance( cause, RuntimeError )

    def test_sweep_transition_raises_logged( self ):
        rq = self.build(); rq._transition_to_dead = MagicMock( side_effect=RuntimeError( "boom" ) )
        job = _AgenticFake( id_hash="ghost3" ); self._enqueue( rq, job )
        f = MagicMock(); f.done.return_value=True; f.exception.return_value=None
        rq._agentic_futures = { "ghost3": f }
        rq._ghost_job_sweep()   # must not raise
        self.assertNotIn( "ghost3", rq._agentic_futures )

    def test_sweep_loop_config_interval_and_exception( self ):
        rq = self.build()
        stop = MagicMock(); stop.is_set.side_effect = [ False, True ]
        rq._ghost_job_sweeper_stop_event = stop
        with patch.object( rq, "_ghost_job_sweep", side_effect=RuntimeError( "sweep boom" ) ):
            rq._ghost_job_sweep_loop()
        stop.wait.assert_called_once_with( timeout=30 )

    def test_sweep_loop_none_config_default_interval( self ):
        rq = self.build( config_mgr=None )
        stop = MagicMock(); stop.is_set.side_effect = [ False, True ]
        rq._ghost_job_sweeper_stop_event = stop
        with patch.object( rq, "_ghost_job_sweep" ):
            rq._ghost_job_sweep_loop()
        stop.wait.assert_called_once_with( timeout=30 )


# ── shutdown_pool ───────────────────────────────────────────────────────────
class TestShutdownPool( _RFQBase ):

    def test_shutdown_no_wait( self ):
        rq = self.build()
        rq.shutdown_pool( wait=False )
        rq._agentic_pool.shutdown.assert_called_once()
        rq._monopolize_pool.shutdown.assert_called_once()   # Shape-B: dedicated executor shuts down too

    def test_shutdown_sweeper_still_alive_warns( self ):
        rq = self.build()
        rq._ghost_job_sweeper_thread._alive = True   # is_alive True -> warn branch
        rq.shutdown_pool( wait=False )

    def test_shutdown_wait_future_ok( self ):
        rq = self.build()
        f = MagicMock(); f.result.return_value = None
        rq._agentic_futures = { "j": f }
        rq.shutdown_pool( wait=True, timeout=1.0 )
        f.result.assert_called_once()

    def test_shutdown_wait_timeout_dead_letters( self ):
        rq = self.build(); rq._transition_to_dead = MagicMock()
        job = _AgenticFake( id_hash="j2" ); self._enqueue( rq, job )
        f = MagicMock(); f.result.side_effect = TimeoutError()
        rq._agentic_futures = { "j2": f }
        rq.shutdown_pool( wait=True, timeout=0.0 )
        rq._transition_to_dead.assert_called_once()

    def test_shutdown_wait_timeout_job_gone( self ):
        rq = self.build(); rq._transition_to_dead = MagicMock()
        f = MagicMock(); f.result.side_effect = TimeoutError()
        rq._agentic_futures = { "missing": f }   # not in queue
        rq.shutdown_pool( wait=True, timeout=0.0 )
        rq._transition_to_dead.assert_not_called()

    def test_shutdown_wait_timeout_get_returns_none( self ):
        # get_by_id_hash returns None (defensive None-check) -> skip dead-letter
        rq = self.build(); rq._transition_to_dead = MagicMock()
        rq.get_by_id_hash = MagicMock( return_value=None )
        f = MagicMock(); f.result.side_effect = TimeoutError()
        rq._agentic_futures = { "nonejob": f }
        rq.shutdown_pool( wait=True, timeout=0.0 )
        rq._transition_to_dead.assert_not_called()

    def test_shutdown_wait_timeout_dead_letter_raises( self ):
        rq = self.build(); rq._transition_to_dead = MagicMock( side_effect=RuntimeError( "dl" ) )
        job = _AgenticFake( id_hash="j3" ); self._enqueue( rq, job )
        f = MagicMock(); f.result.side_effect = TimeoutError()
        rq._agentic_futures = { "j3": f }
        rq.shutdown_pool( wait=True, timeout=0.0 )   # must not raise

    def test_shutdown_wait_other_exception_passes( self ):
        rq = self.build()
        f = MagicMock(); f.result.side_effect = RuntimeError( "already handled" )
        rq._agentic_futures = { "j4": f }
        rq.shutdown_pool( wait=True, timeout=0.0 )   # must not raise


# ── _evaluate_for_auto_fix ──────────────────────────────────────────────────
class TestEvaluateForAutoFix( _RFQBase ):

    def test_watchdog_present_evaluates( self ):
        rq = self.build()
        with patch( "cosa.rest.dead_queue_watchdog.get_watchdog" ) as gw:
            wd = MagicMock(); gw.return_value = wd
            rq._evaluate_for_auto_fix( _AgenticFake() )
            wd.evaluate.assert_called_once()

    def test_watchdog_absent_noop( self ):
        rq = self.build()
        with patch( "cosa.rest.dead_queue_watchdog.get_watchdog", return_value=None ):
            rq._evaluate_for_auto_fix( _AgenticFake() )

    def test_watchdog_raises_swallowed( self ):
        rq = self.build( **{ "app debug": True } )
        with patch( "cosa.rest.dead_queue_watchdog.get_watchdog", side_effect=RuntimeError( "x" ) ):
            rq._evaluate_for_auto_fix( _AgenticFake() )   # must not raise


# ── _process_job dispatch ───────────────────────────────────────────────────
class TestProcessJob( _RFQBase ):

    def test_none_job_returns( self ):
        rq = self.build()
        rq._process_job( None )   # early return, no error

    def test_agentic_submits( self ):
        rq = self.build(); rq._submit_agentic_job = MagicMock()
        job = _AgenticFake()
        rq._process_job( job )
        rq._submit_agentic_job.assert_called_once_with( job )

    def test_crud_skips_cache( self ):
        rq = self.build( **{ "app debug": True } ); rq._handle_base_agent = MagicMock( return_value="j" )
        job = _CrudFake()
        rq._process_job( job )
        rq._handle_base_agent.assert_called_once()
        rq.snapshot_mgr.get_snapshots_by_question.assert_not_called()

    def test_agent_cache_exact_hit( self ):
        rq = self.build( **{ "app debug": True } ); rq._format_cached_result = MagicMock( return_value="c" )
        snap = _SnapFake( run_date="2026" )
        rq.snapshot_mgr.get_snapshots_by_question.return_value = [ ( 100.0, snap ) ]
        rq._process_job( _AgentBaseFake() )
        rq._format_cached_result.assert_called_once()

    def test_agent_cache_threshold_accept( self ):
        rq = self.build(); rq._format_cached_result = MagicMock( return_value="c" )
        snap = _SnapFake( run_date="2026" )
        rq.snapshot_mgr.get_snapshots_by_question.return_value = [ ( 95.0, snap ) ]
        rq._process_job( _AgentBaseFake() )
        rq._format_cached_result.assert_called_once()

    def test_agent_cache_threshold_reject_routes_to_agent( self ):
        rq = self.build(); rq._handle_base_agent = MagicMock( return_value="a" )
        snap = _SnapFake( run_date="2026" )
        rq.snapshot_mgr.get_snapshots_by_question.return_value = [ ( 50.0, snap ) ]
        rq._process_job( _AgentBaseFake() )
        rq._handle_base_agent.assert_called_once()

    def test_agent_cache_miss( self ):
        rq = self.build( **{ "app debug": True } ); rq._handle_base_agent = MagicMock( return_value="a" )
        rq.snapshot_mgr.get_snapshots_by_question.return_value = []
        rq._process_job( _AgentBaseFake() )
        rq._handle_base_agent.assert_called_once()

    def test_solution_snapshot_dispatch( self ):
        rq = self.build(); rq._handle_solution_snapshot = MagicMock( return_value="s" )
        rq._process_job( _SnapFake() )
        rq._handle_solution_snapshot.assert_called_once()

    def test_exception_dead_letters( self ):
        rq = self.build(); rq._transition_to_dead = MagicMock()
        rq._submit_agentic_job = MagicMock( side_effect=RuntimeError( "boom" ) )
        job = _AgenticFake()
        rq._process_job( job )
        rq._transition_to_dead.assert_called_once()


# ── enter_running_loop (deprecated) ─────────────────────────────────────────
class _StopLoop( Exception ): pass

class TestEnterRunningLoop( _RFQBase ):

    def test_loop_agent_then_idle_sleep( self ):
        rq = self.build(); rq._handle_base_agent = MagicMock()
        job = _AgentBaseFake()
        rq.jobs_todo_queue.is_empty.side_effect = [ False, True ]
        rq.jobs_todo_queue.pop.return_value = job
        rq.push = MagicMock()
        rq.head = MagicMock( return_value=job )
        with patch.object( rfq.time, "sleep", side_effect=_StopLoop() ):
            with self.assertRaises( _StopLoop ):
                rq.enter_running_loop()
        rq._handle_base_agent.assert_called_once()

    def test_loop_snapshot_branch( self ):
        rq = self.build(); rq._handle_solution_snapshot = MagicMock()
        snap = _SnapFake()
        rq.jobs_todo_queue.is_empty.side_effect = [ False, True ]
        rq.jobs_todo_queue.pop.return_value = snap
        rq.push = MagicMock()
        rq.head = MagicMock( return_value=snap )
        with patch.object( rfq.time, "sleep", side_effect=_StopLoop() ):
            with self.assertRaises( _StopLoop ):
                rq.enter_running_loop()
        rq._handle_solution_snapshot.assert_called_once()


# ── _handle_error_case ──────────────────────────────────────────────────────
class TestHandleErrorCase( _RFQBase ):

    def test_with_explicit_message( self ):
        rq = self.build(); rq._transition_to_dead = MagicMock()
        job = _AgenticFake()
        out = rq._handle_error_case( { "output": "line1\nline2" }, job, "q", error_message="custom" )
        rq._transition_to_dead.assert_called_once_with( job, "custom" )
        self.assertIs( out, job )

    def test_with_default_message( self ):
        rq = self.build(); rq._transition_to_dead = MagicMock()
        job = _AgenticFake()
        rq._handle_error_case( { "output": "x" }, job, "q" )
        cause = rq._transition_to_dead.call_args[ 0 ][ 1 ]
        self.assertIn( "I'm sorry Dave", cause )


# ── _fire_correctness_check_async ───────────────────────────────────────────
class TestFireCorrectness( _RFQBase ):

    def _run_inner( self, rq, snap ):
        rq._fire_correctness_check_async( snap, "q", "a" )
        return _FakeThread.last.target

    def test_responded_yes_emits( self ):
        rq = self.build()
        snap = _SnapFake()
        resp = MagicMock(); resp.status="responded"; resp.response_value="yes"
        self.notify_fn.return_value = resp
        target = self._run_inner( rq, snap )
        target()
        self.assertTrue( snap.answer_is_correct )
        rq.snapshot_mgr.save_snapshot.assert_called_once_with( snap )
        rq.websocket_mgr.emit.assert_called_once()

    def test_responded_no_websocket_none( self ):
        rq = self.build( **{ "app debug": True } ); rq.websocket_mgr = None
        snap = _SnapFake()
        resp = MagicMock(); resp.status="responded"; resp.response_value="no"
        self.notify_fn.return_value = resp
        target = self._run_inner( rq, snap )
        target()
        self.assertFalse( snap.answer_is_correct )

    def test_not_responded( self ):
        rq = self.build( **{ "app debug": True } )
        snap = _SnapFake()
        resp = MagicMock(); resp.status="timeout"
        self.notify_fn.return_value = resp
        target = self._run_inner( rq, snap )
        target()
        self.assertIsNone( snap.answer_is_correct )

    def test_inner_exception_swallowed( self ):
        rq = self.build( **{ "app debug": True } )
        snap = _SnapFake()
        self.notify_fn.side_effect = RuntimeError( "notify down" )
        target = self._run_inner( rq, snap )
        target()   # must not raise


# ── _handle_base_agent ──────────────────────────────────────────────────────
class TestHandleBaseAgent( _RFQBase ):

    def test_do_all_raises_routes_error_case( self ):
        rq = self.build(); rq._handle_error_case = MagicMock( return_value="err" )
        job = _AgentBaseFake( _do_all_exc=RuntimeError( "do_all fail" ) )
        out = rq._handle_base_agent( job, "q", rfq.sw.Stopwatch( "t" ) )
        rq._handle_error_case.assert_called_once()
        self.assertEqual( out, "err" )

    def test_serialize_snapshot_success_with_gist_present( self ):
        rq = self.build()
        job = _AgentBaseFake( id_hash="b1" ); self._enqueue( rq, job )
        rq._fire_correctness_check_async = MagicMock()
        out = rq._handle_base_agent( job, "q", rfq.sw.Stopwatch( "t" ) )
        # recast to SolutionSnapshot
        self.assertIsInstance( out, _SnapFake )
        rq.snapshot_mgr.save_snapshot.assert_called_once()
        rq._fire_correctness_check_async.assert_called_once()

    def test_serialize_snapshot_gist_missing_generates( self ):
        rq = self.build( **{ "app debug": True } )
        job = _AgentBaseFake( id_hash="b2", solution_summary_gist="", solution_summary="ss" ); self._enqueue( rq, job )
        rq._fire_correctness_check_async = MagicMock()
        rq.gist_normalizer.get_normalized_gist.return_value = "newgist"
        out = rq._handle_base_agent( job, "q", rfq.sw.Stopwatch( "t" ) )
        self.assertIsInstance( out, _SnapFake )

    def test_serialize_snapshot_gist_generation_raises( self ):
        rq = self.build( **{ "app debug": True } )
        job = _AgentBaseFake( id_hash="b3", solution_summary_gist="", solution_summary="ss" ); self._enqueue( rq, job )
        rq._fire_correctness_check_async = MagicMock()
        rq.gist_normalizer.get_normalized_gist.side_effect = RuntimeError( "gist boom" )
        rq._handle_base_agent( job, "q", rfq.sw.Stopwatch( "t" ) )

    def test_serialize_snapshot_gist_missing_no_explanation( self ):
        rq = self.build()
        job = _AgentBaseFake( id_hash="b3b", solution_summary_gist="", solution_summary="", thoughts="" ); self._enqueue( rq, job )
        rq._fire_correctness_check_async = MagicMock()
        out = rq._handle_base_agent( job, "q", rfq.sw.Stopwatch( "t" ) )
        self.assertIsInstance( out, _SnapFake )

    def test_ephemeral_receptionist_not_serialized( self ):
        rq = self.build()
        job = _ReceptionistFake( id_hash="b4" ); self._enqueue( rq, job )
        out = rq._handle_base_agent( job, "q", rfq.sw.Stopwatch( "t" ) )
        self.assertEqual( out.answer, "no code executed by non-serializing/ephemeral objects" )
        rq.snapshot_mgr.save_snapshot.assert_not_called()

    def test_ephemeral_crud_keeps_answer( self ):
        rq = self.build()
        job = _CrudFake( id_hash="b5", answer="crud answer" ); self._enqueue( rq, job )
        out = rq._handle_base_agent( job, "q", rfq.sw.Stopwatch( "t" ) )
        self.assertEqual( out.answer, "crud answer" )

    def test_code_not_complete_routes_error_case( self ):
        rq = self.build(); rq._handle_error_case = MagicMock( return_value="err" )
        job = _AgentBaseFake( _code_ok=False )
        out = rq._handle_base_agent( job, "q", rfq.sw.Stopwatch( "t" ) )
        rq._handle_error_case.assert_called_once()
        self.assertEqual( out, "err" )

    def test_success_started_at_none( self ):
        rq = self.build()
        job = _ReceptionistFake( id_hash="b6", started_at=None ); self._enqueue( rq, job )
        rq._handle_base_agent( job, "q", rfq.sw.Stopwatch( "t" ) )
        self.emit.assert_called_once()

    def test_success_bad_timestamp( self ):
        rq = self.build()
        job = _WeatherFake( id_hash="b7", started_at="nope" ); self._enqueue( rq, job )
        rq._handle_base_agent( job, "q", rfq.sw.Stopwatch( "t" ) )
        self.emit.assert_called_once()


# ── _handle_solution_snapshot ───────────────────────────────────────────────
class TestHandleSolutionSnapshot( _RFQBase ):

    def test_happy_gist_present( self ):
        rq = self.build()
        snap = _SnapFake( id_hash="ss1" ); self._enqueue( rq, snap )
        out = rq._handle_solution_snapshot( snap, "q", rfq.sw.Stopwatch( "t" ) )
        self.assertIs( out, snap )
        rq.snapshot_mgr.save_snapshot.assert_called_once_with( snap )

    def test_gist_missing_generates( self ):
        rq = self.build( **{ "app debug": True } )
        snap = _SnapFake( id_hash="ss2", solution_summary_gist="", solution_summary="ss" ); self._enqueue( rq, snap )
        rq.gist_normalizer.get_normalized_gist.return_value = "g"
        rq._handle_solution_snapshot( snap, "q", rfq.sw.Stopwatch( "t" ) )

    def test_gist_generation_raises( self ):
        rq = self.build( **{ "app debug": True } )
        snap = _SnapFake( id_hash="ss3", solution_summary_gist="", solution_summary="ss" ); self._enqueue( rq, snap )
        rq.gist_normalizer.get_normalized_gist.side_effect = RuntimeError( "g boom" )
        rq._handle_solution_snapshot( snap, "q", rfq.sw.Stopwatch( "t" ) )

    def test_gist_missing_no_explanation( self ):
        rq = self.build()
        snap = _SnapFake( id_hash="ss4", solution_summary_gist="", solution_summary="", thoughts="" ); self._enqueue( rq, snap )
        rq._handle_solution_snapshot( snap, "q", rfq.sw.Stopwatch( "t" ) )

    def test_started_at_none( self ):
        rq = self.build()
        snap = _SnapFake( id_hash="ss5", started_at=None ); self._enqueue( rq, snap )
        rq._handle_solution_snapshot( snap, "q", rfq.sw.Stopwatch( "t" ) )
        self.emit.assert_called_once()

    def test_bad_timestamp( self ):
        rq = self.build()
        snap = _SnapFake( id_hash="ss6", started_at="bad" ); self._enqueue( rq, snap )
        rq._handle_solution_snapshot( snap, "q", rfq.sw.Stopwatch( "t" ) )


# ── _format_cached_result ───────────────────────────────────────────────────
class TestFormatCachedResult( _RFQBase ):

    def test_cache_reexec_success( self ):
        rq = self.build()
        cached = _SnapFake( id_hash="c1", runtime_stats={ "first_run_ms": 1000 } )
        original = _AgentBaseFake( id_hash="orig1" )
        out = rq._format_cached_result( cached, original, "q", rfq.sw.Stopwatch( "t" ) )
        self.assertEqual( out.id_hash, "orig1" )   # done_queue_entry.id_hash set to original
        rq.jobs_done_queue.push.assert_called_once()

    def test_cache_reexec_returns_nonzero( self ):
        rq = self.build()
        cached = _SnapFake( id_hash="c2", _code_response={ "return_code": 1, "output": "" } )
        original = _AgentBaseFake( id_hash="orig2" )
        rq._format_cached_result( cached, original, "q", rfq.sw.Stopwatch( "t" ) )

    def test_cache_reexec_value_error_fallback( self ):
        rq = self.build( **{ "app debug": True } )
        cached = _SnapFake( id_hash="c3", _code_response=ValueError( "no code" ) )
        original = _AgentBaseFake( id_hash="orig3" )
        rq._format_cached_result( cached, original, "q", rfq.sw.Stopwatch( "t" ) )

    def test_cache_started_at_none( self ):
        rq = self.build()
        cached = _SnapFake( id_hash="c4" )
        original = _AgentBaseFake( id_hash="orig4", started_at=None )
        rq._format_cached_result( cached, original, "q", rfq.sw.Stopwatch( "t" ) )

    def test_cache_bad_timestamp_and_debug( self ):
        rq = self.build( **{ "app debug": True } )
        cached = _SnapFake( id_hash="c5" )
        original = _AgentBaseFake( id_hash="orig5", started_at="bad" )
        rq._format_cached_result( cached, original, "q", rfq.sw.Stopwatch( "t" ) )


# ── _process_fast_lane ──────────────────────────────────────────────────────
class TestProcessFastLane( _RFQBase ):

    def test_crud_skips_cache( self ):
        rq = self.build( **{ "app debug": True } ); rq._handle_base_agent = MagicMock( return_value="a" )
        rq._process_fast_lane( _CrudFake() )
        rq._handle_base_agent.assert_called_once()

    def test_agent_exact_hit( self ):
        rq = self.build( **{ "app debug": True } ); rq._format_cached_result = MagicMock( return_value="c" )
        rq.snapshot_mgr.get_snapshots_by_question.return_value = [ ( 100.0, _SnapFake( run_date="d" ) ) ]
        rq._process_fast_lane( _AgentBaseFake() )
        rq._format_cached_result.assert_called_once()

    def test_agent_threshold_accept( self ):
        rq = self.build(); rq._format_cached_result = MagicMock( return_value="c" )
        rq.snapshot_mgr.get_snapshots_by_question.return_value = [ ( 95.0, _SnapFake( run_date="d" ) ) ]
        rq._process_fast_lane( _AgentBaseFake() )
        rq._format_cached_result.assert_called_once()

    def test_agent_threshold_reject( self ):
        rq = self.build(); rq._handle_base_agent = MagicMock( return_value="a" )
        rq.snapshot_mgr.get_snapshots_by_question.return_value = [ ( 10.0, _SnapFake( run_date="d" ) ) ]
        rq._process_fast_lane( _AgentBaseFake() )
        rq._handle_base_agent.assert_called_once()

    def test_agent_miss( self ):
        rq = self.build( **{ "app debug": True } ); rq._handle_base_agent = MagicMock( return_value="a" )
        rq.snapshot_mgr.get_snapshots_by_question.return_value = []
        rq._process_fast_lane( _AgentBaseFake() )
        rq._handle_base_agent.assert_called_once()

    def test_snapshot_dispatch( self ):
        rq = self.build(); rq._handle_solution_snapshot = MagicMock( return_value="s" )
        rq._process_fast_lane( _SnapFake() )
        rq._handle_solution_snapshot.assert_called_once()


# ── _handle_agentic_job (legacy/dead-code path, still covered) ───────────────
class TestHandleAgenticJob( _RFQBase ):

    def test_stalled_path( self ):
        rq = self.build()
        job = _AgenticFake( id_hash="ag1", state=JobState.STALLED ); self._enqueue( rq, job )
        out = rq._handle_agentic_job( job, "q", rfq.sw.Stopwatch( "t" ) )
        self.assertIs( out, job )
        rq.jobs_done_queue.push.assert_called_once_with( job )

    def test_stalled_path_io_raises( self ):
        rq = self.build( **{ "app debug": True } )
        job = _AgenticFake( id_hash="ag1b", state=JobState.STALLED, started_at=None ); self._enqueue( rq, job )
        rq.io_tbl.insert_io_row.side_effect = RuntimeError( "io" )
        rq._handle_agentic_job( job, "q", rfq.sw.Stopwatch( "t" ) )

    def test_success_path_with_tfe( self ):
        rq = self.build()
        job = _AgenticFake( id_hash="ag2" ); self._enqueue( rq, job )
        with patch( "cosa.rest.test_suite_completion_watchdog.get_watchdog" ) as gw:
            gw.return_value = MagicMock()
            rq._handle_agentic_job( job, "q", rfq.sw.Stopwatch( "t" ) )
        rq.jobs_done_queue.push.assert_called_once_with( job )

    def test_success_path_tfe_none_and_io_raises( self ):
        rq = self.build( **{ "app debug": True } )
        job = _AgenticFake( id_hash="ag3", started_at=None ); self._enqueue( rq, job )
        rq.io_tbl.insert_io_row.side_effect = RuntimeError( "io" )
        with patch( "cosa.rest.test_suite_completion_watchdog.get_watchdog", return_value=None ):
            rq._handle_agentic_job( job, "q", rfq.sw.Stopwatch( "t" ) )

    def test_success_path_tfe_raises( self ):
        rq = self.build( **{ "app debug": True } )
        job = _AgenticFake( id_hash="ag4", started_at="bad" ); self._enqueue( rq, job )
        with patch( "cosa.rest.test_suite_completion_watchdog.get_watchdog", side_effect=RuntimeError( "tfe" ) ):
            rq._handle_agentic_job( job, "q", rfq.sw.Stopwatch( "t" ) )

    def test_not_complete_routes_dead( self ):
        rq = self.build(); rq._transition_to_dead = MagicMock()
        job = _AgenticFake( id_hash="ag5", _code_ok=False, error="nope" ); self._enqueue( rq, job )
        rq._handle_agentic_job( job, "q", rfq.sw.Stopwatch( "t" ) )
        rq._transition_to_dead.assert_called_once()

    def test_exception_routes_dead( self ):
        rq = self.build(); rq._transition_to_dead = MagicMock()
        job = _AgenticFake( id_hash="ag6", _do_all_exc=RuntimeError( "boom" ) ); self._enqueue( rq, job )
        rq._handle_agentic_job( job, "q", rfq.sw.Stopwatch( "t" ) )
        rq._transition_to_dead.assert_called_once()
        self.assertEqual( job.state, JobState.FAILED )


# ── Option (a) true-monopoly (bug 30398595): kill-switch + hold lifecycle ────
class TestMonopolyKillSwitch( _RFQBase ):
    """The master kill-switch is read FRESH at gate-time (hot-reload, no bounce),
    gating all three surfaces atomically."""

    def test_enabled_reads_config_true_by_default( self ):
        self.assertTrue( self.build()._is_monopolize_enabled() )

    def test_enabled_reads_config_false_when_flipped( self ):
        rq = self.build( **{ "cj flow monopolize enabled": False } )
        self.assertFalse( rq._is_monopolize_enabled() )

    def test_enabled_none_config_defaults_true( self ):
        self.assertTrue( self.build( config_mgr=None )._is_monopolize_enabled() )

    def test_reads_fresh_each_call_no_init_cache( self ):
        """A mid-run INI flip is honored on the NEXT gate read (no __init__ cache)."""
        cfg   = self._cfg()
        state = { "on": True }
        cfg.get.side_effect = lambda key, default=None, return_type=None: (
            state[ "on" ] if key == "cj flow monopolize enabled" else default
        )
        rq = self.build( config_mgr=cfg )
        self.assertTrue( rq._is_monopolize_enabled() )
        state[ "on" ] = False                              # operator flips the INI
        self.assertFalse( rq._is_monopolize_enabled() )    # picked up live


class TestMonopolyHoldLifecycle( _RFQBase ):
    """The monopoly-hold flag: init default, SET on dispatch (kill-switch gated),
    and RELEASE from every terminal path incl. the ghost sweeper."""

    def test_init_defaults( self ):
        rq = self.build()
        self.assertIsNone( rq._monopolize_active )
        self.assertEqual( rq._monopolize_drain_timeout_seconds, 300 )

    def test_init_none_config_drain_default( self ):
        self.assertEqual( self.build( config_mgr=None )._monopolize_drain_timeout_seconds, 300 )

    def test_init_drain_timeout_override( self ):
        rq = self.build( **{ "cj flow monopolize drain timeout seconds": 45 } )
        self.assertEqual( rq._monopolize_drain_timeout_seconds, 45 )

    def test_submit_sets_hold_for_monopolize_job( self ):
        rq  = self.build()
        rq._agentic_pool.submit.return_value = MagicMock( name="future" )
        job = _AgenticFake( id_hash="m1", monopolize=True )
        rq._submit_agentic_job( job )
        self.assertEqual( rq._monopolize_active, "m1" )

    def test_submit_does_not_set_hold_for_nonmonopolize_job( self ):
        rq  = self.build()
        rq._agentic_pool.submit.return_value = MagicMock( name="future" )
        job = _AgenticFake( id_hash="n1", monopolize=False )
        rq._submit_agentic_job( job )
        self.assertIsNone( rq._monopolize_active )

    def test_submit_leaves_hold_untouched_when_kill_switch_disabled( self ):
        """ATOMICITY (Tiberius rider): flag=false → _monopolize_active stays None
        end-to-end through a full submit — no half-state possible."""
        rq  = self.build( **{ "cj flow monopolize enabled": False } )
        rq._agentic_pool.submit.return_value = MagicMock( name="future" )
        job = _AgenticFake( id_hash="m2", monopolize=True )
        rq._submit_agentic_job( job )
        self.assertIsNone( rq._monopolize_active )   # disabled → no-op set

    def test_release_clears_only_matching_owner( self ):
        rq = self.build()
        rq._monopolize_active = "owner"
        rq._release_monopolize_hold( "someone-else" )   # different id → no-op
        self.assertEqual( rq._monopolize_active, "owner" )
        rq._release_monopolize_hold( "owner" )          # owner → clears
        self.assertIsNone( rq._monopolize_active )

    def test_on_agentic_complete_releases_hold( self ):
        rq = self.build(); rq._transition_to_done = MagicMock()
        job = _AgenticFake( id_hash="m3", monopolize=True )
        rq._monopolize_active = "m3"
        fut = MagicMock(); fut.exception.return_value = None; fut.result.return_value = "out"
        rq._on_agentic_complete( job, fut )
        self.assertIsNone( rq._monopolize_active )      # released on completion

    def test_ghost_sweep_dead_letter_releases_hold( self ):
        """ADDED HAZARD: a ghost-swept monopolize job MUST release the hold, else
        a wedged sweep freezes ALL intake permanently."""
        rq = self.build(); rq._transition_to_dead = MagicMock()
        job = _AgenticFake( id_hash="g1", monopolize=True ); self._enqueue( rq, job )
        fut = MagicMock(); fut.done.return_value = True; fut.exception.return_value = None
        rq._agentic_futures = { "g1": fut }
        rq._monopolize_active = "g1"
        rq._ghost_job_sweep()
        rq._transition_to_dead.assert_called_once()
        self.assertIsNone( rq._monopolize_active )      # intake can resume

    def test_ghost_sweep_already_transitioned_releases_hold( self ):
        """The already-transitioned cleanup arc (job gone from queue_dict) also
        releases the hold — idempotent belt."""
        rq = self.build()
        fut = MagicMock(); fut.done.return_value = True
        rq._agentic_futures = { "g2": fut }              # NOT enqueued → get_by_id_hash None
        rq._monopolize_active = "g2"
        rq._ghost_job_sweep()
        self.assertIsNone( rq._monopolize_active )


# ── Option (a) Gate-A drain oracle: await_monopolize_pool_drain ──────────────
class TestAwaitMonopolizePoolDrain( _RFQBase ):

    def test_returns_empty_when_pool_already_clean( self ):
        rq  = self.build()
        rq._agentic_futures = { }                        # no foreign inflight
        job = _AgenticFake( id_hash="sweep" )
        self.assertEqual(
            rq.await_monopolize_pool_drain( job, timeout_seconds=5 ), [ ]
        )

    def test_waits_then_returns_empty_once_drained( self ):
        """Foreign writer present on the first probe, gone on the second →
        returns [] after one poll; heartbeat ticked during the wait."""
        rq  = self.build()
        job = _AgenticFake( id_hash="sweep" )
        rq.get_non_test_inflight_agentic_jobs = MagicMock(
            side_effect=[ [ { "id_hash": "dr1", "job_type": "deep_research" } ], [ ] ]
        )
        hb = MagicMock()
        with patch.object( rfq.time, "sleep" ) as slp:
            out = rq.await_monopolize_pool_drain(
                job, timeout_seconds=100, poll_seconds=0.01, heartbeat_fn=hb
            )
        self.assertEqual( out, [ ] )
        hb.assert_called_once()                          # ticked once during the wait
        slp.assert_called_once_with( 0.01 )

    def test_returns_offenders_on_timeout( self ):
        """Deadline already passed → the loop body never runs; the initial
        offender probe is returned so the caller fails loud."""
        rq  = self.build()
        job = _AgenticFake( id_hash="sweep" )
        offenders = [ { "id_hash": "dr1", "job_type": "deep_research" } ]
        rq.get_non_test_inflight_agentic_jobs = MagicMock( return_value=offenders )
        hb = MagicMock()
        with patch.object( rfq.time, "monotonic", side_effect=[ 1000.0, 2000.0 ] ), \
             patch.object( rfq.time, "sleep" ) as slp:
            out = rq.await_monopolize_pool_drain(
                job, timeout_seconds=0, poll_seconds=1.0, heartbeat_fn=hb
            )
        self.assertEqual( out, offenders )
        hb.assert_not_called()                           # loop body never entered
        slp.assert_not_called()

    def test_no_heartbeat_fn_is_tolerated( self ):
        """heartbeat_fn is optional — the None arc must not raise."""
        rq  = self.build()
        job = _AgenticFake( id_hash="sweep" )
        rq.get_non_test_inflight_agentic_jobs = MagicMock(
            side_effect=[ [ { "id_hash": "x", "job_type": "podcast" } ], [ ] ]
        )
        with patch.object( rfq.time, "sleep" ):
            out = rq.await_monopolize_pool_drain( job, timeout_seconds=100, poll_seconds=0.01 )
        self.assertEqual( out, [ ] )


def isolated_unit_test():
    """
    Run the running_fifo_queue unit tests in isolation.

    Ensures:
        - Returns (success, duration, message) for the smoke-runner harness

    Raises:
        - None
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
    print( f"\n{'✅ PASS' if ok else '❌ FAIL'} running_fifo_queue tests in {secs:.3f}s — {msg}" )
