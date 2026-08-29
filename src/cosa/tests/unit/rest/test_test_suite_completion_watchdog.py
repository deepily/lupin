"""
Unit tests for TestSuiteCompletionWatchdog (cosa.rest.test_suite_completion_watchdog).

Covers __init__ (debug print), evaluate (inner result / exception-swallow with
debug-on traceback + debug-off), _evaluate_inner (all six eligibility gates, each
skip arc + the all-pass dispatch), _repair_tracker_allows (None / method-true /
method-false / method-raises / no-known-method), _compute_repair_key (id_hash /
unknown), _dispatch_tfe (no-queue / no-path / factory-None / factory-raises /
push-raises / success-with-tracker-record / success-without-tracker),
_repair_tracker_record (None / method / method-raises / no-known-method), and the
init/get/reset singleton helpers — to genuine 100% line + branch + function.

create_agentic_job is boundary-mocked; config_mgr / todo_queue / repair_tracker
are mocks. ZERO real job construction, ZERO queue, ZERO threads.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from cosa.rest import test_suite_completion_watchdog as tscw
from cosa.rest.test_suite_completion_watchdog import (
    TestSuiteCompletionWatchdog, init_watchdog, get_watchdog, reset_watchdog,
)


def _cfg( enabled=True, max_failures=50 ):
    m = Mock( name="config_mgr" )
    def _get( key, default=None, return_type=None ):
        if key == "test fix expediter auto fix enabled":          return enabled
        if key == "test fix expediter max cluster seed failures":  return max_failures
        return default
    m.get.side_effect = _get
    return m


def _snapshot( **over ):
    snap = {
        "schema_version" : "1.0",
        "summary"        : { "all_passed": False },
        "failures"       : [ "f1" ],
        "suites_run"     : [ "unit" ],
    }
    snap.update( over )
    return snap


def _job( snapshot=None, **over ):
    if snapshot is None:
        snapshot = _snapshot()
    job = SimpleNamespace(
        JOB_TYPE   = "test_suite",
        artifacts  = { "remediation_snapshot": snapshot, "remediation_snapshot_path": "/snap/path" },
        metadata   = {},
        id_hash    = "tsj-1",
        user_id    = "u1",
        user_email = "u@e.com",
        session_id = "s1",
    )
    for k, v in over.items():
        setattr( job, k, v )
    return job


def _wd( enabled=True, max_failures=50, todo_queue=None, repair_tracker=None, debug=True,
         ask_flow=None ):
    # Step 12: the dispatch submits through the ask flow. The queue is still held —
    # the gates read it — but nothing here pushes onto it any more.
    return TestSuiteCompletionWatchdog(
        config_mgr=_cfg( enabled, max_failures ),
        todo_queue=todo_queue if todo_queue is not None else Mock( name="todo" ),
        repair_tracker=repair_tracker, debug=debug,
        ask_flow=ask_flow if ask_flow is not None else Mock( name="flow" ),
    )


class TestInit( unittest.TestCase ):
    def test_caches_config_and_prints_when_debug( self ):
        with patch( "builtins.print" ) as mp:
            wd = _wd( enabled=True, max_failures=7, debug=True )
        self.assertTrue( wd.enabled )
        self.assertEqual( wd.max_failures, 7 )
        self.assertTrue( any( "initialized" in str( c ) for c in mp.call_args_list ) )


class TestEvaluate( unittest.TestCase ):
    def test_returns_inner_result( self ):
        wd = _wd()
        wd._evaluate_inner = Mock( return_value="tfe-1" )
        self.assertEqual( wd.evaluate( _job() ), "tfe-1" )

    def test_swallows_exception_with_debug_traceback( self ):
        wd = _wd( debug=True )
        wd._evaluate_inner = Mock( side_effect=RuntimeError( "boom" ) )
        with patch( "traceback.print_exc" ) as mtb:
            self.assertIsNone( wd.evaluate( _job() ) )
        mtb.assert_called_once()

    def test_swallows_exception_debug_off_no_traceback( self ):
        wd = _wd( debug=False )
        wd._evaluate_inner = Mock( side_effect=RuntimeError( "boom" ) )
        with patch( "traceback.print_exc" ) as mtb:
            self.assertIsNone( wd.evaluate( _job() ) )
        mtb.assert_not_called()


class TestEvaluateInnerGates( unittest.TestCase ):
    def test_gate1_override_false( self ):
        wd = _wd( enabled=True )
        self.assertIsNone( wd._evaluate_inner( _job( auto_fix_on_failure=False ) ) )

    def test_gate1_override_none_and_disabled( self ):
        wd = _wd( enabled=False )
        self.assertIsNone( wd._evaluate_inner( _job() ) )   # no override attr → None

    def test_gate2_wrong_job_type( self ):
        wd = _wd( enabled=False )
        # override True forces past gate 1 even though INI disabled
        self.assertIsNone( wd._evaluate_inner( _job( auto_fix_on_failure=True, JOB_TYPE="other" ) ) )

    def test_gate3_no_snapshot( self ):
        wd = _wd( enabled=True )
        job = _job()
        job.artifacts = {}
        self.assertIsNone( wd._evaluate_inner( job ) )

    def test_gate3_bad_schema_version( self ):
        wd = _wd( enabled=True )
        self.assertIsNone( wd._evaluate_inner( _job( snapshot=_snapshot( schema_version="2.0" ) ) ) )

    def test_gate3_all_passed( self ):
        wd = _wd( enabled=True )
        self.assertIsNone( wd._evaluate_inner( _job( snapshot=_snapshot( summary={ "all_passed": True } ) ) ) )

    def test_gate3_summary_not_dict( self ):
        wd = _wd( enabled=True )
        self.assertIsNone( wd._evaluate_inner( _job( snapshot=_snapshot( summary="nope" ) ) ) )

    def test_gate3_no_failures( self ):
        wd = _wd( enabled=True )
        self.assertIsNone( wd._evaluate_inner( _job( snapshot=_snapshot( failures=[] ) ) ) )

    def test_gate3_failures_not_list( self ):
        wd = _wd( enabled=True )
        self.assertIsNone( wd._evaluate_inner( _job( snapshot=_snapshot( failures="x" ) ) ) )

    def test_gate4_recursion_guard( self ):
        wd = _wd( enabled=True )
        self.assertIsNone( wd._evaluate_inner( _job( metadata={ "triggered_by_tfe": "tfe-prev" } ) ) )

    def test_gate5_failure_cap( self ):
        wd = _wd( enabled=True, max_failures=0 )
        self.assertIsNone( wd._evaluate_inner( _job() ) )   # 1 failure > cap 0

    def test_gate6_repair_tracker_blocks( self ):
        tracker = Mock()
        tracker.allow.return_value = False
        wd = _wd( enabled=True, repair_tracker=tracker )
        self.assertIsNone( wd._evaluate_inner( _job() ) )

    def test_all_gates_pass_dispatches( self ):
        wd = _wd( enabled=True )
        wd._dispatch_tfe = Mock( return_value="tfe-new" )
        self.assertEqual( wd._evaluate_inner( _job() ), "tfe-new" )

    def test_gate6_repair_tracker_allows_then_dispatches( self ):
        tracker = Mock(); tracker.allow.return_value = True
        wd = _wd( enabled=True, repair_tracker=tracker )
        wd._dispatch_tfe = Mock( return_value="tfe-ok" )
        self.assertEqual( wd._evaluate_inner( _job() ), "tfe-ok" )   # 176->185 allows→dispatch


class TestEvaluateInnerGatesDebugOff( unittest.TestCase ):
    """debug=False variants — exercise the if-debug FALSE arcs in every gate skip path."""

    def test_gate1_override_false( self ):
        self.assertIsNone( _wd( enabled=True, debug=False )._evaluate_inner( _job( auto_fix_on_failure=False ) ) )

    def test_gate1_override_none_disabled( self ):
        self.assertIsNone( _wd( enabled=False, debug=False )._evaluate_inner( _job() ) )

    def test_gate3_no_snapshot( self ):
        job = _job(); job.artifacts = {}
        self.assertIsNone( _wd( enabled=True, debug=False )._evaluate_inner( job ) )

    def test_gate3_bad_schema( self ):
        self.assertIsNone( _wd( enabled=True, debug=False )._evaluate_inner(
            _job( snapshot=_snapshot( schema_version="2.0" ) ) ) )

    def test_gate3_all_passed( self ):
        self.assertIsNone( _wd( enabled=True, debug=False )._evaluate_inner(
            _job( snapshot=_snapshot( summary={ "all_passed": True } ) ) ) )

    def test_gate3_no_failures( self ):
        self.assertIsNone( _wd( enabled=True, debug=False )._evaluate_inner(
            _job( snapshot=_snapshot( failures=[] ) ) ) )

    def test_gate4_recursion_guard( self ):
        self.assertIsNone( _wd( enabled=True, debug=False )._evaluate_inner(
            _job( metadata={ "triggered_by_tfe": "tfe-prev" } ) ) )

    def test_gate6_blocked( self ):
        tracker = Mock(); tracker.allow.return_value = False
        self.assertIsNone( _wd( enabled=True, debug=False, repair_tracker=tracker )._evaluate_inner( _job() ) )


class TestRepairTrackerAllows( unittest.TestCase ):
    def test_none_allows( self ):
        wd = _wd( repair_tracker=None )
        self.assertTrue( wd._repair_tracker_allows( ( "k", ) ) )

    def test_method_true( self ):
        tracker = Mock(); tracker.allow.return_value = True
        wd = _wd( repair_tracker=tracker )
        self.assertTrue( wd._repair_tracker_allows( ( "k", ) ) )

    def test_method_false( self ):
        tracker = Mock(); tracker.allow.return_value = False
        wd = _wd( repair_tracker=tracker )
        self.assertFalse( wd._repair_tracker_allows( ( "k", ) ) )

    def test_method_raises_allows_by_default( self ):
        tracker = Mock(); tracker.allow.side_effect = RuntimeError( "boom" )
        wd = _wd( repair_tracker=tracker )
        self.assertTrue( wd._repair_tracker_allows( ( "k", ) ) )

    def test_no_known_method_allows( self ):
        wd = _wd( repair_tracker=SimpleNamespace() )   # none of allow/is_allowed/check/can_attempt
        self.assertTrue( wd._repair_tracker_allows( ( "k", ) ) )


class TestComputeRepairKey( unittest.TestCase ):
    def test_with_id_hash( self ):
        key = TestSuiteCompletionWatchdog._compute_repair_key(
            SimpleNamespace( id_hash="j1" ), { "suites_run": [ "b", "a" ] }
        )
        self.assertEqual( key, ( "j1", ( "a", "b" ) ) )

    def test_unknown_id_hash( self ):
        key = TestSuiteCompletionWatchdog._compute_repair_key( SimpleNamespace(), {} )
        self.assertEqual( key, ( "unknown", () ) )


class TestDispatchTfe( unittest.TestCase ):
    def test_no_todo_queue( self ):
        wd = TestSuiteCompletionWatchdog( config_mgr=_cfg(), todo_queue=None, debug=True )
        self.assertIsNone( wd._dispatch_tfe( _job(), _snapshot() ) )

    def test_missing_snapshot_path( self ):
        wd = _wd( enabled=True )
        job = _job()
        job.artifacts = { "remediation_snapshot_path": "" }
        self.assertIsNone( wd._dispatch_tfe( job, _snapshot() ) )

    def test_factory_returns_none( self ):
        wd = _wd( enabled=True )
        with patch( "cosa.rest.agentic_job_factory.create_agentic_job", return_value=None ):
            self.assertIsNone( wd._dispatch_tfe( _job(), _snapshot() ) )

    def test_factory_raises( self ):
        wd = _wd( enabled=True )
        with patch( "cosa.rest.agentic_job_factory.create_agentic_job",
                    side_effect=RuntimeError( "factory boom" ) ):
            self.assertIsNone( wd._dispatch_tfe( _job(), _snapshot() ) )

    def test_submit_raises( self ):
        flow = Mock(); flow.submit.side_effect = RuntimeError( "submit boom" )
        wd = _wd( enabled=True, ask_flow=flow )
        with patch( "cosa.rest.agentic_job_factory.create_agentic_job",
                    return_value=SimpleNamespace( id_hash="tfe-1" ) ):
            self.assertIsNone( wd._dispatch_tfe( _job(), _snapshot() ) )

    def test_no_ask_flow_returns_none_and_never_pushes( self ):
        """A wiring gap must not become a private door back onto the queue."""
        todo = Mock()
        wd = TestSuiteCompletionWatchdog( config_mgr=_cfg( True, 50 ), todo_queue=todo,
                                          repair_tracker=None, debug=True, ask_flow=None )
        with patch( "cosa.rest.agentic_job_factory.create_agentic_job",
                    return_value=SimpleNamespace( id_hash="tfe-1" ) ):
            self.assertIsNone( wd._dispatch_tfe( _job(), _snapshot() ) )
        todo.push.assert_not_called()

    def test_success_with_tracker_records( self ):
        todo    = Mock()
        flow    = Mock()
        tracker = Mock()
        wd = _wd( enabled=True, todo_queue=todo, repair_tracker=tracker, ask_flow=flow )
        with patch( "cosa.rest.agentic_job_factory.create_agentic_job",
                    return_value=SimpleNamespace( id_hash="tfe-1" ) ):
            self.assertEqual( wd._dispatch_tfe( _job(), _snapshot() ), "tfe-1" )
        flow.submit.assert_called_once()
        todo.push.assert_not_called()
        tracker.record_attempt.assert_called_once()

    def test_success_without_tracker( self ):
        todo = Mock()
        wd = _wd( enabled=True, todo_queue=todo, repair_tracker=None )
        with patch( "cosa.rest.agentic_job_factory.create_agentic_job",
                    return_value=SimpleNamespace( id_hash="tfe-2" ) ):
            self.assertEqual( wd._dispatch_tfe( _job(), _snapshot() ), "tfe-2" )


class TestRepairTrackerRecord( unittest.TestCase ):
    def test_none_returns( self ):
        wd = _wd( repair_tracker=None )
        wd._repair_tracker_record( ( "k", ) )   # no raise

    def test_method_called( self ):
        tracker = Mock()
        wd = _wd( repair_tracker=tracker )
        wd._repair_tracker_record( ( "k", ) )
        tracker.record_attempt.assert_called_once_with( ( "k", ) )

    def test_method_raises_logs( self ):
        tracker = Mock(); tracker.record_attempt.side_effect = RuntimeError( "boom" )
        wd = _wd( repair_tracker=tracker )
        wd._repair_tracker_record( ( "k", ) )   # swallowed

    def test_no_known_method( self ):
        wd = _wd( repair_tracker=SimpleNamespace() )
        wd._repair_tracker_record( ( "k", ) )   # loop ends, no raise


class TestSingletonHelpers( unittest.TestCase ):
    def tearDown( self ):
        reset_watchdog()

    def test_init_get_reset( self ):
        self.assertIsNone( get_watchdog() )
        wd = init_watchdog( config_mgr=_cfg(), todo_queue=Mock() )
        self.assertIs( get_watchdog(), wd )
        reset_watchdog()
        self.assertIsNone( get_watchdog() )


def isolated_unit_test():
    """
    Run the TestSuiteCompletionWatchdog unit tests in isolation.

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
    print( f"\n{'✅ PASS' if ok else '❌ FAIL'} TestSuiteCompletionWatchdog tests in {secs:.3f}s — {msg}" )
