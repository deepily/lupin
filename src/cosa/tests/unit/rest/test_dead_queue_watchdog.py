"""
Unit tests for DeadQueueWatchdog (cosa.rest.dead_queue_watchdog).

Covers classify_failure (each infra category / code-bug / unknown / empty),
is_eligible_for_auto_fix (no-type / excluded / not-eligible / max-attempts /
wrong-state / OOM / environment / eligible debug-on/off), __init__ + _reload_config,
get/increment attempt, evaluate (disabled / no-job-id / circuit-breaker /
ineligible / cooldown / transient→direct_retry / code→submit_bfe / tracker-None),
_cooldown_elapsed (first / within), _direct_retry (success / job-not-found /
non-dict-result / exception), _submit_bfe (success / dry_run+overrides+tracker /
factory-None / exception), _notify_ineligible (max-attempts / other), and the
init/get singleton — to genuine 100% line + branch + function.

All factory / tracker / persistence seams are boundary-mocked. ZERO real jobs,
ZERO queue, ZERO DB.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from cosa.rest import dead_queue_watchdog as dqw
from cosa.rest.dead_queue_watchdog import (
    DeadQueueWatchdog, FailureCategory, classify_failure, is_eligible_for_auto_fix,
    init_watchdog, get_watchdog,
)
from cosa.rest.job_state import JobState


# ─── Module-level classifier ────────────────────────────────────────────────
class TestClassifyFailure( unittest.TestCase ):
    def test_empty_is_unknown( self ):
        self.assertEqual( classify_failure( "" ), FailureCategory.UNKNOWN )

    def test_timeout( self ):
        self.assertEqual( classify_failure( "TimeoutError: timed out" ), FailureCategory.INFRA_TIMEOUT )

    def test_oom( self ):
        self.assertEqual( classify_failure( "MemoryError" ), FailureCategory.INFRA_OOM )

    def test_rate_limit( self ):
        self.assertEqual( classify_failure( "RateLimitError" ), FailureCategory.INFRA_RATE_LIMIT )

    def test_environment( self ):
        self.assertEqual( classify_failure( "ECONNREFUSED" ), FailureCategory.INFRA_ENVIRONMENT )

    def test_code_bug( self ):
        self.assertEqual( classify_failure( "KeyError: x" ), FailureCategory.CODE_BUG )

    def test_user_input_research_doc_not_found( self ):
        # bug f16c7ce1: this message carries no FileNotFoundError/"No such file"
        # token, so it used to fall through to UNKNOWN → BFE. It is a user-input
        # error, not a code bug.
        self.assertEqual(
            classify_failure( "Research document not found: my write-up on the lighthouse" ),
            FailureCategory.USER_INPUT
        )

    def test_user_input_wins_over_code_bug_token( self ):
        # Checked before code-bug patterns, so a user-input message that happens
        # to contain a bug-ish word still classifies as USER_INPUT.
        self.assertEqual(
            classify_failure( "no matching document (ValueError-ish phrasing)" ),
            FailureCategory.USER_INPUT
        )

    def test_unknown_fallback( self ):
        self.assertEqual( classify_failure( "weird non-matching text" ), FailureCategory.UNKNOWN )


# ─── Eligibility ──────────────────────────────────────────────────────────────
def _job( **over ):
    job = SimpleNamespace(
        id_hash="j1", job_type="presentation", state=JobState.FAILED,
        error="KeyError: x", artifacts={}, user_id="u", user_email="e@x",
        session_id="s", dry_run=False, original_args={},
    )
    for k, v in over.items():
        setattr( job, k, v )
    return job


class TestIsEligible( unittest.TestCase ):
    def test_no_job_type( self ):
        ok, reason = is_eligible_for_auto_fix( SimpleNamespace(), [ "presentation" ] )
        self.assertFalse( ok )
        self.assertIn( "No job_type", reason )

    def test_excluded_type( self ):
        job = _job( job_type="bug_fix_expediter", JOB_TYPE="bug_fix_expediter" )
        ok, reason = is_eligible_for_auto_fix( job, [ "bug_fix_expediter" ] )
        self.assertFalse( ok )
        self.assertIn( "excluded", reason.lower() )

    def test_not_in_eligible_list( self ):
        job = _job( JOB_TYPE="presentation" )
        ok, reason = is_eligible_for_auto_fix( job, [ "deep_research" ] )
        self.assertFalse( ok )
        self.assertIn( "not in eligible", reason.lower() )

    def test_max_attempts( self ):
        job = _job( JOB_TYPE="presentation" )
        ok, reason = is_eligible_for_auto_fix( job, [ "presentation" ], max_attempts=3, attempt_count=3 )
        self.assertFalse( ok )
        self.assertIn( "max attempts", reason.lower() )

    def test_wrong_state( self ):
        job = _job( JOB_TYPE="presentation", state="running" )
        ok, reason = is_eligible_for_auto_fix( job, [ "presentation" ] )
        self.assertFalse( ok )
        self.assertIn( "not FAILED", reason )

    def test_oom_ineligible( self ):
        job = _job( JOB_TYPE="presentation", error="MemoryError" )
        ok, reason = is_eligible_for_auto_fix( job, [ "presentation" ] )
        self.assertFalse( ok )
        self.assertIn( "OOM", reason )

    def test_environment_ineligible( self ):
        job = _job( JOB_TYPE="presentation", error="ECONNREFUSED" )
        ok, reason = is_eligible_for_auto_fix( job, [ "presentation" ] )
        self.assertFalse( ok )
        self.assertIn( "environment", reason.lower() )

    def test_user_input_ineligible( self ):
        # bug f16c7ce1: a missing-research-doc failure must NOT be sent to BFE.
        job = _job( JOB_TYPE="presentation", error="Research document not found: the KISS explainer" )
        ok, reason = is_eligible_for_auto_fix( job, [ "presentation" ] )
        self.assertFalse( ok )
        self.assertIn( "user-input", reason.lower() )

    def test_eligible_state_none_debug_on( self ):
        job = _job( JOB_TYPE="presentation", state=None, artifacts={ "stack_trace": "KeyError" } )
        with patch( "builtins.print" ) as mp:
            ok, reason = is_eligible_for_auto_fix( job, [ "presentation" ], debug=True )
        self.assertTrue( ok )
        self.assertTrue( any( "eligible" in str( c ) for c in mp.call_args_list ) )

    def test_eligible_debug_off_silent( self ):
        job = _job( JOB_TYPE="presentation" )
        with patch( "builtins.print" ) as mp:
            ok, _ = is_eligible_for_auto_fix( job, [ "presentation" ], debug=False )
        self.assertTrue( ok )
        mp.assert_not_called()

    def test_non_dict_artifacts_skips_stack_trace( self ):
        # truthy non-dict artifacts → `isinstance(artifacts, dict)` False arc
        job = _job( JOB_TYPE="presentation", artifacts=[ "not", "a", "dict" ] )
        ok, _ = is_eligible_for_auto_fix( job, [ "presentation" ] )
        self.assertTrue( ok )


# ─── Watchdog ───────────────────────────────────────────────────────────────
def _cfg( **over ):
    defaults = {
        "auto fix enabled"               : True,
        "auto fix eligible job types"    : "presentation, deep_research",
        "auto fix max attempts per job"  : 3,
        "auto fix max cost usd"          : 10.0,
        "auto fix max wall clock seconds": 1800,
        "auto fix cooldown seconds"      : 60,
    }
    defaults.update( over )
    m = Mock( name="config_mgr" )
    def _get( key, default=None, return_type=None ):
        val = defaults.get( key, default )
        if return_type == "boolean": return bool( val )
        if return_type == "int":     return int( val )
        if return_type == "float":   return float( val )
        return val
    m.get.side_effect = _get
    return m


class TestInitAndConfig( unittest.TestCase ):
    def test_reload_config_parses_eligible_types( self ):
        wd = DeadQueueWatchdog( _cfg(), Mock(), debug=False )
        self.assertTrue( wd.enabled )
        self.assertEqual( wd.eligible_types, [ "presentation", "deep_research" ] )
        self.assertEqual( wd.max_attempts, 3 )

    def test_attempt_counter( self ):
        wd = DeadQueueWatchdog( _cfg(), Mock() )
        self.assertEqual( wd.get_attempt_count( "j1" ), 0 )
        self.assertEqual( wd.increment_attempt( "j1" ), 1 )
        self.assertEqual( wd.increment_attempt( "j1" ), 2 )


class TestEvaluate( unittest.TestCase ):
    def _wd( self, **cfg ):
        return DeadQueueWatchdog( _cfg( **cfg ), Mock(), debug=True )

    def test_disabled_returns_none( self ):
        wd = self._wd( **{ "auto fix enabled": False } )
        with patch( "builtins.print" ):
            self.assertIsNone( wd.evaluate( _job() ) )

    def test_no_job_id_returns_none( self ):
        wd = self._wd()
        job = _job( id_hash=None )
        self.assertIsNone( wd.evaluate( job ) )

    def test_circuit_breaker_blocks( self ):
        wd = self._wd()
        tracker = Mock(); tracker.can_attempt.return_value = ( False, "breaker open" )
        with patch( "cosa.rest.repair_attempt_tracker.get_tracker", return_value=tracker ), \
             patch( "builtins.print" ):
            self.assertIsNone( wd.evaluate( _job() ) )

    def test_ineligible_returns_none( self ):
        wd = self._wd()
        job = _job( JOB_TYPE="not_eligible", job_type="not_eligible" )
        with patch( "cosa.rest.repair_attempt_tracker.get_tracker", return_value=None ), \
             patch( "builtins.print" ):
            self.assertIsNone( wd.evaluate( job ) )

    def test_cooldown_not_elapsed( self ):
        wd = self._wd()
        wd._record_attempt_time( "j1" )      # cooldown now active
        with patch( "cosa.rest.repair_attempt_tracker.get_tracker", return_value=None ), \
             patch( "builtins.print" ):
            self.assertIsNone( wd.evaluate( _job() ) )

    def test_transient_routes_to_direct_retry( self ):
        wd = self._wd()
        wd._direct_retry = Mock( return_value="retry-1" )
        with patch( "cosa.rest.repair_attempt_tracker.get_tracker", return_value=None ):
            self.assertEqual( wd.evaluate( _job( error="TimeoutError" ) ), "retry-1" )

    def test_code_bug_routes_to_submit_bfe( self ):
        wd = self._wd()
        wd._submit_bfe = Mock( return_value="bfe-1" )
        tracker = Mock(); tracker.can_attempt.return_value = ( True, "ok" )
        with patch( "cosa.rest.repair_attempt_tracker.get_tracker", return_value=tracker ):
            self.assertEqual( wd.evaluate( _job( error="KeyError: x" ) ), "bfe-1" )

    def test_non_dict_artifacts_skips_stack_trace( self ):
        # exercise the `isinstance(artifacts, dict)` False arc inside evaluate()
        wd = self._wd()
        wd._submit_bfe = Mock( return_value="bfe-2" )
        with patch( "cosa.rest.repair_attempt_tracker.get_tracker", return_value=None ):
            self.assertEqual(
                wd.evaluate( _job( error="KeyError: x", artifacts=[ "not", "dict" ] ) ), "bfe-2"
            )


class TestCooldownElapsed( unittest.TestCase ):
    def test_first_attempt_elapsed( self ):
        wd = DeadQueueWatchdog( _cfg(), Mock() )
        self.assertTrue( wd._cooldown_elapsed( "j1" ) )

    def test_within_cooldown_blocked( self ):
        wd = DeadQueueWatchdog( _cfg(), Mock() )
        wd._record_attempt_time( "j1" )
        self.assertFalse( wd._cooldown_elapsed( "j1" ) )


class TestDirectRetry( unittest.TestCase ):
    def _wd( self ):
        return DeadQueueWatchdog( _cfg(), Mock(), debug=False )

    def test_success( self ):
        wd = self._wd()
        wd.todo_queue.push_job.return_value = { "job_id": "new-1" }
        with patch( "cosa.rest.job_persistence.get_job_by_id_hash",
                    return_value={ "question_text": "q?" } ), \
             patch( "builtins.print" ):
            self.assertEqual( wd._direct_retry( _job(), 0, FailureCategory.INFRA_TIMEOUT ), "new-1" )

    def test_job_not_found( self ):
        wd = self._wd()
        with patch( "cosa.rest.job_persistence.get_job_by_id_hash", return_value=None ), \
             patch( "builtins.print" ):
            self.assertIsNone( wd._direct_retry( _job(), 0, FailureCategory.INFRA_TIMEOUT ) )

    def test_non_dict_result_yields_none_job_id( self ):
        wd = self._wd()
        wd.todo_queue.push_job.return_value = "not-a-dict"
        with patch( "cosa.rest.job_persistence.get_job_by_id_hash",
                    return_value={ "question_text": "q?" } ), \
             patch( "builtins.print" ):
            self.assertIsNone( wd._direct_retry( _job(), 0, FailureCategory.INFRA_RATE_LIMIT ) )

    def test_exception_returns_none( self ):
        wd = self._wd()
        with patch( "cosa.rest.job_persistence.get_job_by_id_hash",
                    side_effect=RuntimeError( "db boom" ) ), \
             patch( "builtins.print" ):
            self.assertIsNone( wd._direct_retry( _job(), 0, FailureCategory.INFRA_TIMEOUT ) )


class TestSubmitBfe( unittest.TestCase ):
    def _wd( self, debug=False ):
        return DeadQueueWatchdog( _cfg(), Mock(), debug=debug )

    def test_success_no_overrides_no_tracker( self ):
        wd = self._wd()
        bfe = SimpleNamespace( id_hash="bfe-raw" )
        ujt = Mock(); ujt.register_scoped_job.return_value = "bfe-scoped"
        with patch( "cosa.rest.agentic_job_factory.create_agentic_job", return_value=bfe ), \
             patch( "cosa.rest.queue_extensions.user_job_tracker", ujt ), \
             patch( "cosa.rest.repair_attempt_tracker.get_tracker", return_value=None ), \
             patch( "builtins.print" ):
            self.assertEqual( wd._submit_bfe( _job(), 0 ), "bfe-scoped" )
        wd.todo_queue.push.assert_called_once()

    def test_success_dry_run_overrides_and_tracker( self ):
        wd = self._wd( debug=True )
        bfe = SimpleNamespace( id_hash="bfe-raw" )
        ujt = Mock(); ujt.register_scoped_job.return_value = "bfe-scoped"
        tracker = Mock()
        job = _job( dry_run=True, original_args={
            "bfe_lead_model_override": "sonnet", "bfe_worker_model_override": "haiku" } )
        with patch( "cosa.rest.agentic_job_factory.create_agentic_job", return_value=bfe ) as mk, \
             patch( "cosa.rest.queue_extensions.user_job_tracker", ujt ), \
             patch( "cosa.rest.repair_attempt_tracker.get_tracker", return_value=tracker ), \
             patch( "builtins.print" ):
            self.assertEqual( wd._submit_bfe( job, 1 ), "bfe-scoped" )
        args = mk.call_args.kwargs[ "args_dict" ]
        self.assertTrue( args[ "dry_run" ] )
        self.assertEqual( args[ "lead_model_override" ], "sonnet" )
        self.assertEqual( args[ "worker_model_override" ], "haiku" )
        tracker.record_attempt.assert_called_once()

    def test_factory_returns_none( self ):
        wd = self._wd()
        with patch( "cosa.rest.agentic_job_factory.create_agentic_job", return_value=None ), \
             patch( "cosa.rest.queue_extensions.user_job_tracker", Mock() ), \
             patch( "builtins.print" ):
            self.assertIsNone( wd._submit_bfe( _job(), 0 ) )

    def test_exception_returns_none( self ):
        wd = self._wd()
        with patch( "cosa.rest.agentic_job_factory.create_agentic_job",
                    side_effect=RuntimeError( "factory boom" ) ), \
             patch( "cosa.rest.queue_extensions.user_job_tracker", Mock() ), \
             patch( "builtins.print" ):
            self.assertIsNone( wd._submit_bfe( _job(), 0 ) )


class TestNotifyIneligible( unittest.TestCase ):
    def test_non_actionable_reason_silent( self ):
        wd = DeadQueueWatchdog( _cfg(), Mock() )
        with patch( "builtins.print" ) as mp:
            wd._notify_ineligible( _job(), "Job type not eligible" )
        mp.assert_not_called()

    def test_max_attempts_reason_logs( self ):
        wd = DeadQueueWatchdog( _cfg(), Mock() )
        with patch( "builtins.print" ) as mp:
            wd._notify_ineligible( _job(), "Max attempts (3) reached" )
        self.assertTrue( any( "ESCALATION" in str( c ) for c in mp.call_args_list ) )


class TestSingleton( unittest.TestCase ):
    def test_init_and_get( self ):
        with patch( "builtins.print" ):
            wd = init_watchdog( _cfg(), Mock(), debug=False )
        self.assertIs( get_watchdog(), wd )


def isolated_unit_test():
    """
    Run the DeadQueueWatchdog unit tests in isolation.

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
    print( f"\n{'✅ PASS' if ok else '❌ FAIL'} DeadQueueWatchdog tests in {secs:.3f}s — {msg}" )
