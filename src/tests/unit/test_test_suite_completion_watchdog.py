"""
Unit tests for TestSuiteCompletionWatchdog.

Session 1cfcdf73 (2026-04-10): Step 13 implementation tests. Exercises
all 6 eligibility gates, dispatch, recursion guard, and error handling.
"""

from unittest.mock import MagicMock, patch

import pytest

from cosa.rest.test_suite_completion_watchdog import (
    TestSuiteCompletionWatchdog,
    init_watchdog,
    get_watchdog,
    reset_watchdog,
)


# ─────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────


def _make_config_mgr( enabled: bool = True, max_failures: int = 50 ):
    """Build a mock config_mgr with controllable enabled + max_failures."""
    mock = MagicMock()
    def _get( key, default=None, return_type="string" ):
        if key == "test fix expediter auto fix enabled":
            return enabled
        if key == "test fix expediter max cluster seed failures":
            return max_failures
        return default
    mock.get = MagicMock( side_effect=_get )
    return mock


def _make_valid_snapshot( n_failures: int = 2 ):
    return {
        "schema_version": "1.0",
        "timestamp": "2026.04.10-at-14:53",
        "suites_run": [ "unit" ],
        "summary": {
            "total_passed": 2000,
            "total_failed": n_failures,
            "total_errors": 0,
            "total_skipped": 0,
            "all_passed": False,
        },
        "failures": [
            {
                "classname": f"src.tests.unit.test_x.TestX{i}",
                "name": f"test_y{i}", "type": "FAILED",
                "message": f"msg {i}",
                "traceback": f'File "src/foo_{i}.py", line 1',
                "suite": "unit",
            }
            for i in range( n_failures )
        ],
    }


def _make_completed_job(
    job_type: str = "test_suite",
    snapshot: dict = None,
    metadata: dict = None,
    job_id: str = "ts-abc12345",
    auto_fix_on_failure=None,
):
    mock = MagicMock()
    mock.JOB_TYPE = job_type
    mock.id_hash = job_id
    mock.user_id = "u1"
    mock.user_email = "t@t.com"
    mock.session_id = "s1"
    mock.artifacts = {
        "remediation_snapshot": snapshot or _make_valid_snapshot(),
        "remediation_snapshot_path": "test-suite/fake-remediation.json",
    }
    mock.metadata = metadata
    # Explicit per-run override (None == use INI default).
    # MUST be set explicitly because MagicMock auto-creates attrs and would
    # otherwise return a truthy child Mock from getattr( job, "auto_fix_on_failure", None ).
    mock.auto_fix_on_failure = auto_fix_on_failure
    return mock


# ─────────────────────────────────────────────────────────────────────────
# Gate tests
# ─────────────────────────────────────────────────────────────────────────


class TestGate1Enabled:

    def test_disabled_returns_none( self ):
        watchdog = TestSuiteCompletionWatchdog(
            config_mgr=_make_config_mgr( enabled=False ),
        )
        job = _make_completed_job()
        assert watchdog.evaluate( job ) is None

    def test_enabled_passes_gate( self ):
        """When enabled, gate 1 allows us to progress to later gates."""
        watchdog = TestSuiteCompletionWatchdog(
            config_mgr=_make_config_mgr( enabled=True ),
            todo_queue=MagicMock(),
            ask_flow=MagicMock(),
        )
        job = _make_completed_job()
        # Should dispatch (or at least attempt — the MagicMock todo_queue accepts any push)
        result = watchdog.evaluate( job )
        assert result is not None  # dispatched


class TestGate2JobType:

    def test_wrong_job_type_returns_none( self ):
        watchdog = TestSuiteCompletionWatchdog(
            config_mgr=_make_config_mgr( enabled=True ),
        )
        job = _make_completed_job( job_type="presentation_generator" )
        assert watchdog.evaluate( job ) is None

    def test_missing_job_type_returns_none( self ):
        watchdog = TestSuiteCompletionWatchdog(
            config_mgr=_make_config_mgr( enabled=True ),
        )
        mock = MagicMock( spec=[ "artifacts", "metadata", "auto_fix_on_failure" ] )
        mock.artifacts = {}
        mock.metadata = None
        mock.auto_fix_on_failure = None
        # No JOB_TYPE attribute
        assert watchdog.evaluate( mock ) is None


class TestGate3Snapshot:

    def test_no_snapshot_returns_none( self ):
        watchdog = TestSuiteCompletionWatchdog(
            config_mgr=_make_config_mgr( enabled=True ),
        )
        mock = MagicMock()
        mock.JOB_TYPE = "test_suite"
        mock.artifacts = {}  # no remediation_snapshot
        mock.metadata = None
        mock.auto_fix_on_failure = None
        assert watchdog.evaluate( mock ) is None

    def test_non_dict_snapshot_returns_none( self ):
        watchdog = TestSuiteCompletionWatchdog(
            config_mgr=_make_config_mgr( enabled=True ),
        )
        job = _make_completed_job( snapshot="not a dict" )
        assert watchdog.evaluate( job ) is None

    def test_wrong_schema_version_returns_none( self ):
        watchdog = TestSuiteCompletionWatchdog(
            config_mgr=_make_config_mgr( enabled=True ),
        )
        snapshot = _make_valid_snapshot()
        snapshot[ "schema_version" ] = "2.0"
        job = _make_completed_job( snapshot=snapshot )
        assert watchdog.evaluate( job ) is None

    def test_all_passed_returns_none( self ):
        watchdog = TestSuiteCompletionWatchdog(
            config_mgr=_make_config_mgr( enabled=True ),
        )
        snapshot = _make_valid_snapshot()
        snapshot[ "summary" ][ "all_passed" ] = True
        job = _make_completed_job( snapshot=snapshot )
        assert watchdog.evaluate( job ) is None

    def test_empty_failures_returns_none( self ):
        watchdog = TestSuiteCompletionWatchdog(
            config_mgr=_make_config_mgr( enabled=True ),
        )
        snapshot = _make_valid_snapshot()
        snapshot[ "failures" ] = []
        job = _make_completed_job( snapshot=snapshot )
        assert watchdog.evaluate( job ) is None


class TestGate4RecursionGuard:

    def test_triggered_by_tfe_metadata_returns_none( self ):
        watchdog = TestSuiteCompletionWatchdog(
            config_mgr=_make_config_mgr( enabled=True ),
            todo_queue=MagicMock(),
            ask_flow=MagicMock(),
        )
        job = _make_completed_job(
            metadata={ "triggered_by_tfe": "tfe-parent-job" },
        )
        assert watchdog.evaluate( job ) is None

    def test_no_metadata_allows_dispatch( self ):
        watchdog = TestSuiteCompletionWatchdog(
            config_mgr=_make_config_mgr( enabled=True ),
            todo_queue=MagicMock(),
            ask_flow=MagicMock(),
        )
        job = _make_completed_job( metadata=None )
        result = watchdog.evaluate( job )
        assert result is not None  # dispatched

    def test_empty_metadata_allows_dispatch( self ):
        watchdog = TestSuiteCompletionWatchdog(
            config_mgr=_make_config_mgr( enabled=True ),
            todo_queue=MagicMock(),
            ask_flow=MagicMock(),
        )
        job = _make_completed_job( metadata={} )
        result = watchdog.evaluate( job )
        assert result is not None  # dispatched

    def test_unrelated_metadata_allows_dispatch( self ):
        watchdog = TestSuiteCompletionWatchdog(
            config_mgr=_make_config_mgr( enabled=True ),
            todo_queue=MagicMock(),
            ask_flow=MagicMock(),
        )
        job = _make_completed_job( metadata={ "some_other_key": "value" } )
        result = watchdog.evaluate( job )
        assert result is not None


class TestGate5FailureCap:

    def test_over_cap_returns_none( self ):
        watchdog = TestSuiteCompletionWatchdog(
            config_mgr=_make_config_mgr( enabled=True, max_failures=5 ),
            todo_queue=MagicMock(),
            ask_flow=MagicMock(),
        )
        snapshot = _make_valid_snapshot( n_failures=10 )
        job = _make_completed_job( snapshot=snapshot )
        assert watchdog.evaluate( job ) is None

    def test_under_cap_allows_dispatch( self ):
        watchdog = TestSuiteCompletionWatchdog(
            config_mgr=_make_config_mgr( enabled=True, max_failures=50 ),
            todo_queue=MagicMock(),
            ask_flow=MagicMock(),
        )
        snapshot = _make_valid_snapshot( n_failures=10 )
        job = _make_completed_job( snapshot=snapshot )
        result = watchdog.evaluate( job )
        assert result is not None

    def test_at_cap_allows_dispatch( self ):
        watchdog = TestSuiteCompletionWatchdog(
            config_mgr=_make_config_mgr( enabled=True, max_failures=5 ),
            todo_queue=MagicMock(),
            ask_flow=MagicMock(),
        )
        snapshot = _make_valid_snapshot( n_failures=5 )
        job = _make_completed_job( snapshot=snapshot )
        result = watchdog.evaluate( job )
        assert result is not None


class TestGate6RepairTracker:

    def test_repair_tracker_blocks( self ):
        tracker = MagicMock()
        tracker.allow = MagicMock( return_value=False )

        watchdog = TestSuiteCompletionWatchdog(
            config_mgr=_make_config_mgr( enabled=True ),
            todo_queue=MagicMock(),
            ask_flow=MagicMock(),
            repair_tracker=tracker,
        )
        job = _make_completed_job()
        assert watchdog.evaluate( job ) is None
        tracker.allow.assert_called_once()

    def test_repair_tracker_allows( self ):
        tracker = MagicMock()
        tracker.allow = MagicMock( return_value=True )

        watchdog = TestSuiteCompletionWatchdog(
            config_mgr=_make_config_mgr( enabled=True ),
            todo_queue=MagicMock(),
            ask_flow=MagicMock(),
            repair_tracker=tracker,
        )
        job = _make_completed_job()
        result = watchdog.evaluate( job )
        assert result is not None

    def test_repair_tracker_none_allows_by_default( self ):
        """If no repair_tracker is provided, dispatch is allowed."""
        watchdog = TestSuiteCompletionWatchdog(
            config_mgr=_make_config_mgr( enabled=True ),
            todo_queue=MagicMock(),
            ask_flow=MagicMock(),
            repair_tracker=None,
        )
        job = _make_completed_job()
        result = watchdog.evaluate( job )
        assert result is not None

    def test_repair_tracker_exception_allows_by_default( self ):
        """If tracker.allow() raises, dispatch is allowed (soft-fail)."""
        tracker = MagicMock()
        tracker.allow = MagicMock( side_effect=RuntimeError( "tracker broken" ) )

        watchdog = TestSuiteCompletionWatchdog(
            config_mgr=_make_config_mgr( enabled=True ),
            todo_queue=MagicMock(),
            ask_flow=MagicMock(),
            repair_tracker=tracker,
        )
        job = _make_completed_job()
        result = watchdog.evaluate( job )
        assert result is not None


# ─────────────────────────────────────────────────────────────────────────
# Dispatch tests
# ─────────────────────────────────────────────────────────────────────────


class TestDispatch:

    def test_dispatch_constructs_tfe_and_submits( self ):
        """Step 12: the dispatch goes through flow.submit(), not queue.push().

        Every assertion below is unchanged — same job, same fields — because the job
        being handed over is the same job. Only who it is handed to moved.
        """
        queue = MagicMock()
        flow  = MagicMock()
        watchdog = TestSuiteCompletionWatchdog(
            config_mgr=_make_config_mgr( enabled=True ),
            todo_queue=queue,
            ask_flow=flow,
        )
        job = _make_completed_job( job_id="ts-xyz98765" )

        result = watchdog.evaluate( job )

        assert result is not None
        assert result.startswith( "tfe-" )
        queue.push.assert_not_called()          # no private door onto the queue
        flow.submit.assert_called_once()
        pushed_tfe = flow.submit.call_args.kwargs[ "job" ]
        assert pushed_tfe.source_test_suite_job_id == "ts-xyz98765"
        assert pushed_tfe.remediation_snapshot_path == "test-suite/fake-remediation.json"
        assert pushed_tfe.user_id == "u1"
        assert pushed_tfe.user_email == "t@t.com"
        assert pushed_tfe.original_test_types == [ "unit" ]

        # Bug 14 regression guard — auto-dispatched TFE must be Resume-capable.
        # Factory-routed dispatch sets routing_command + original_args on the
        # constructed job; without them, resume_job() returns None → 404.
        assert pushed_tfe.routing_command == "agent router go to test fix expediter"
        assert pushed_tfe.original_args, "original_args must be non-empty for Resume capability"
        assert pushed_tfe.original_args[ "remediation_snapshot_path" ] == "test-suite/fake-remediation.json"
        assert pushed_tfe.original_args[ "source_test_suite_job_id"  ] == "ts-xyz98765"

    def test_missing_snapshot_path_returns_none( self ):
        watchdog = TestSuiteCompletionWatchdog(
            config_mgr=_make_config_mgr( enabled=True ),
            todo_queue=MagicMock(),
            ask_flow=MagicMock(),
        )
        snapshot = _make_valid_snapshot()
        job = _make_completed_job( snapshot=snapshot )
        del job.artifacts[ "remediation_snapshot_path" ]
        assert watchdog.evaluate( job ) is None

    def test_no_todo_queue_returns_none( self ):
        watchdog = TestSuiteCompletionWatchdog(
            config_mgr=_make_config_mgr( enabled=True ),
            todo_queue=None,   # explicitly no queue
        )
        job = _make_completed_job()
        assert watchdog.evaluate( job ) is None

    def test_flow_submit_raises_returns_none( self ):
        flow = MagicMock()
        flow.submit = MagicMock( side_effect=RuntimeError( "flow broken" ) )

        watchdog = TestSuiteCompletionWatchdog(
            config_mgr=_make_config_mgr( enabled=True ),
            todo_queue=MagicMock(),
            ask_flow=flow,
        )
        job = _make_completed_job()
        assert watchdog.evaluate( job ) is None

    def test_no_ask_flow_returns_none( self ):
        """A queue but no flow is a wiring bug, and it must not fall back to a push.

        The watchdog reaches the dispatch — every gate passes — and then has nowhere
        to send the job. It logs and returns None rather than reaching for the queue
        it is still holding.
        """
        queue = MagicMock()
        watchdog = TestSuiteCompletionWatchdog(
            config_mgr=_make_config_mgr( enabled=True ),
            todo_queue=queue,
            ask_flow=None,
        )
        job = _make_completed_job()
        assert watchdog.evaluate( job ) is None
        queue.push.assert_not_called()

    def test_repair_tracker_records_on_dispatch( self ):
        tracker = MagicMock()
        tracker.allow = MagicMock( return_value=True )
        tracker.record_attempt = MagicMock()

        watchdog = TestSuiteCompletionWatchdog(
            config_mgr=_make_config_mgr( enabled=True ),
            todo_queue=MagicMock(),
            ask_flow=MagicMock(),
            repair_tracker=tracker,
        )
        job = _make_completed_job()
        result = watchdog.evaluate( job )

        assert result is not None
        tracker.record_attempt.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────
# Repair key + evaluate() exception safety tests
# ─────────────────────────────────────────────────────────────────────────


class TestRepairKey:

    def test_repair_key_stable( self ):
        """Same job + snapshot → same repair key."""
        job = _make_completed_job( job_id="ts-stable" )
        snapshot = _make_valid_snapshot()
        key1 = TestSuiteCompletionWatchdog._compute_repair_key( job, snapshot )
        key2 = TestSuiteCompletionWatchdog._compute_repair_key( job, snapshot )
        assert key1 == key2

    def test_repair_key_includes_suites( self ):
        job = _make_completed_job( job_id="ts-x" )
        snapshot1 = _make_valid_snapshot()
        snapshot1[ "suites_run" ] = [ "unit" ]
        snapshot2 = _make_valid_snapshot()
        snapshot2[ "suites_run" ] = [ "unit", "integration" ]
        key1 = TestSuiteCompletionWatchdog._compute_repair_key( job, snapshot1 )
        key2 = TestSuiteCompletionWatchdog._compute_repair_key( job, snapshot2 )
        assert key1 != key2


class TestExceptionSafety:

    def test_evaluate_never_raises_on_malformed_job( self ):
        """Even if the job is broken, evaluate returns None silently."""
        watchdog = TestSuiteCompletionWatchdog(
            config_mgr=_make_config_mgr( enabled=True ),
        )
        # A completely bogus object with no expected attributes
        class Bogus:
            def __getattr__( self, name ):
                raise RuntimeError( f"access to {name} explodes" )

        result = watchdog.evaluate( Bogus() )
        assert result is None


# ─────────────────────────────────────────────────────────────────────────
# Singleton init helper tests
# ─────────────────────────────────────────────────────────────────────────


class TestSingletonHelpers:

    def setup_method( self ):
        reset_watchdog()

    def teardown_method( self ):
        reset_watchdog()

    def test_init_and_get( self ):
        cm = _make_config_mgr( enabled=True )
        watchdog = init_watchdog( cm, todo_queue=MagicMock(), ask_flow=MagicMock() )
        assert isinstance( watchdog, TestSuiteCompletionWatchdog )
        assert get_watchdog() is watchdog

    def test_reset_clears( self ):
        init_watchdog( _make_config_mgr(), todo_queue=MagicMock(), ask_flow=MagicMock() )
        assert get_watchdog() is not None
        reset_watchdog()
        assert get_watchdog() is None


# ─────────────────────────────────────────────────────────────────────────
# Per-run override tests (Session 1cfcdf73 — auto_fix_on_failure)
# ─────────────────────────────────────────────────────────────────────────


class TestPerRunOverride:
    """
    Gate 1 reads `completed_job.auto_fix_on_failure` as a tri-state:
        - None  → use INI default (self.enabled)
        - True  → force-enable (proceed regardless of INI)
        - False → force-disable (skip regardless of INI)
    """

    def test_override_false_skips_when_ini_enabled( self ):
        """Per-run False MUST short-circuit even when INI default is True."""
        watchdog = TestSuiteCompletionWatchdog(
            config_mgr=_make_config_mgr( enabled=True ),
            todo_queue=MagicMock(),
            ask_flow=MagicMock(),
        )
        job = _make_completed_job( auto_fix_on_failure=False )
        assert watchdog.evaluate( job ) is None

    def test_override_true_proceeds_when_ini_disabled( self ):
        """Per-run True MUST allow dispatch even when INI default is False."""
        watchdog = TestSuiteCompletionWatchdog(
            config_mgr=_make_config_mgr( enabled=False ),
            todo_queue=MagicMock(),
            ask_flow=MagicMock(),
        )
        job = _make_completed_job( auto_fix_on_failure=True )
        result = watchdog.evaluate( job )
        assert result is not None
        assert result.startswith( "tfe-" )

    def test_override_none_honors_ini_enabled( self ):
        """No override + INI True → proceed."""
        watchdog = TestSuiteCompletionWatchdog(
            config_mgr=_make_config_mgr( enabled=True ),
            todo_queue=MagicMock(),
            ask_flow=MagicMock(),
        )
        job = _make_completed_job( auto_fix_on_failure=None )
        assert watchdog.evaluate( job ) is not None

    def test_override_none_honors_ini_disabled( self ):
        """No override + INI False → skip."""
        watchdog = TestSuiteCompletionWatchdog(
            config_mgr=_make_config_mgr( enabled=False ),
            todo_queue=MagicMock(),
            ask_flow=MagicMock(),
        )
        job = _make_completed_job( auto_fix_on_failure=None )
        assert watchdog.evaluate( job ) is None

    def test_override_true_proceeds_when_ini_enabled( self ):
        """Per-run True + INI True → no double-negation, just proceeds."""
        watchdog = TestSuiteCompletionWatchdog(
            config_mgr=_make_config_mgr( enabled=True ),
            todo_queue=MagicMock(),
            ask_flow=MagicMock(),
        )
        job = _make_completed_job( auto_fix_on_failure=True )
        assert watchdog.evaluate( job ) is not None

    def test_override_false_skips_when_ini_disabled( self ):
        """Per-run False + INI False → skipped (the False short-circuit fires first)."""
        watchdog = TestSuiteCompletionWatchdog(
            config_mgr=_make_config_mgr( enabled=False ),
            todo_queue=MagicMock(),
            ask_flow=MagicMock(),
        )
        job = _make_completed_job( auto_fix_on_failure=False )
        assert watchdog.evaluate( job ) is None
