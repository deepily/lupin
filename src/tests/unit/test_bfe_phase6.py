"""
Unit tests for BFE Phase 6: Automated Repair Loop.

Tests the watchdog evaluation, cooldown, direct-retry,
BFE submission, resubmit logic, and state model additions.
"""

import time
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from cosa.rest.dead_queue_watchdog import (
    DeadQueueWatchdog,
    FailureCategory,
    classify_failure,
    is_eligible_for_auto_fix,
)
from cosa.agents.bug_fix_expediter.state import BFEPhase, FixResult, DeadJobContext
from cosa.rest.job_state import JobState


# =============================================================================
# Fixtures
# =============================================================================

class MockConfigMgr:
    """Mock ConfigurationManager with auto-fix defaults."""
    def __init__( self, overrides=None ):
        self._values = {
            "auto fix enabled"              : True,
            "auto fix eligible job types"    : "presentation, deep_research, podcast, test_suite",
            "auto fix max attempts per job"  : 3,
            "auto fix max cost usd"          : 10.0,
            "auto fix max wall clock seconds": 1800,
            "auto fix cooldown seconds"      : 60,
        }
        if overrides:
            self._values.update( overrides )

    def get( self, key, default=None, return_type=None ):
        val = self._values.get( key, default )
        if return_type == "boolean":
            if isinstance( val, str ): return val.lower() in ( "true", "1", "yes" )
            return bool( val )
        if return_type == "int":   return int( val )
        if return_type == "float": return float( val )
        return val


class MockJob:
    """Mock agentic job for watchdog testing."""
    def __init__( self, job_type="presentation", state=JobState.FAILED,
                  error="KeyError: 'missing_key'", user_id="user1",
                  user_email="test@test.com", session_id="wise-penguin" ):
        self.job_type   = job_type
        self.JOB_TYPE   = job_type
        self.state      = state
        self.error      = error
        self.id_hash    = f"pr-test1234::{user_id}"
        self.user_id    = user_id
        self.user_email = user_email
        self.session_id = session_id
        self.artifacts  = {}


class MockTodoQueue:
    """Mock todo queue that captures push calls."""
    def __init__( self ):
        self.pushed_jobs = []

    def push( self, job ):
        self.pushed_jobs.append( job )

    def push_job( self, question, session_id, user_id, user_email ):
        self.pushed_jobs.append( {
            "question"   : question,
            "session_id" : session_id,
            "user_id"    : user_id,
            "user_email" : user_email,
        } )
        return { "message": "queued", "job_id": "retry-mock-id" }


# =============================================================================
# Failure Classification
# =============================================================================

class TestFailureClassification:
    """Tests for classify_failure()."""

    def test_code_bug_keyerror( self ):
        assert classify_failure( "KeyError: 'missing'" ) == FailureCategory.CODE_BUG

    def test_code_bug_import( self ):
        assert classify_failure( "ImportError: No module named 'foo'" ) == FailureCategory.CODE_BUG

    def test_code_bug_pydantic( self ):
        assert classify_failure( "pydantic.ValidationError" ) == FailureCategory.CODE_BUG

    def test_code_bug_attribute( self ):
        assert classify_failure( "AttributeError: 'NoneType' has no 'bar'" ) == FailureCategory.CODE_BUG

    def test_code_bug_name_error( self ):
        assert classify_failure( "NameError: name 'foo' is not defined" ) == FailureCategory.CODE_BUG

    def test_infra_timeout( self ):
        assert classify_failure( "TimeoutError: operation timed out" ) == FailureCategory.INFRA_TIMEOUT

    def test_infra_async_timeout( self ):
        assert classify_failure( "asyncio.TimeoutError" ) == FailureCategory.INFRA_TIMEOUT

    def test_infra_oom( self ):
        assert classify_failure( "MemoryError" ) == FailureCategory.INFRA_OOM

    def test_infra_cuda_oom( self ):
        assert classify_failure( "CUDA out of memory" ) == FailureCategory.INFRA_OOM

    def test_infra_rate_limit( self ):
        assert classify_failure( "RateLimitError: 429" ) == FailureCategory.INFRA_RATE_LIMIT

    def test_infra_rate_limit_429( self ):
        assert classify_failure( "Too Many Requests" ) == FailureCategory.INFRA_RATE_LIMIT

    def test_infra_environment_docker( self ):
        assert classify_failure( "Docker credential not found" ) == FailureCategory.INFRA_ENVIRONMENT

    def test_infra_environment_connection( self ):
        assert classify_failure( "Connection refused (ECONNREFUSED)" ) == FailureCategory.INFRA_ENVIRONMENT

    def test_infra_environment_permission( self ):
        assert classify_failure( "PermissionError: [Errno 13]" ) == FailureCategory.INFRA_ENVIRONMENT

    def test_unknown_fallback( self ):
        assert classify_failure( "Something went wrong" ) == FailureCategory.UNKNOWN

    def test_empty_string( self ):
        assert classify_failure( "" ) == FailureCategory.UNKNOWN

    def test_stack_trace_signal( self ):
        assert classify_failure( "job failed", "Traceback...\\nImportError: no module" ) == FailureCategory.CODE_BUG

    def test_infra_priority_over_code( self ):
        """Infra patterns checked first — if both match, infra wins."""
        assert classify_failure( "TimeoutError", "ImportError: no module" ) == FailureCategory.INFRA_TIMEOUT


# =============================================================================
# Eligibility
# =============================================================================

class TestEligibility:
    """Tests for is_eligible_for_auto_fix()."""

    def test_eligible_presentation( self ):
        job = MockJob( "presentation" )
        ok, reason = is_eligible_for_auto_fix( job, [ "presentation" ] )
        assert ok, f"Should be eligible: {reason}"

    def test_eligible_deep_research( self ):
        job = MockJob( "deep_research" )
        ok, _ = is_eligible_for_auto_fix( job, [ "deep_research" ] )
        assert ok

    def test_bfe_recursion_blocked( self ):
        job = MockJob( "bug_fix_expediter" )
        ok, reason = is_eligible_for_auto_fix( job, [ "bug_fix_expediter" ] )
        assert not ok
        assert "excluded" in reason.lower()

    def test_swe_team_excluded( self ):
        job = MockJob( "swe_team" )
        ok, reason = is_eligible_for_auto_fix( job, [ "swe_team" ] )
        assert not ok
        assert "excluded" in reason.lower()

    def test_not_in_eligible_list( self ):
        job = MockJob( "presentation" )
        ok, reason = is_eligible_for_auto_fix( job, [ "deep_research" ] )
        assert not ok
        assert "not in eligible" in reason.lower()

    def test_max_attempts_reached( self ):
        job = MockJob( "presentation" )
        ok, reason = is_eligible_for_auto_fix( job, [ "presentation" ], max_attempts=3, attempt_count=3 )
        assert not ok
        assert "max attempts" in reason.lower()

    def test_max_attempts_boundary( self ):
        """attempt_count=2 with max=3 should be eligible (attempt 3 of 3)."""
        job = MockJob( "presentation" )
        ok, _ = is_eligible_for_auto_fix( job, [ "presentation" ], max_attempts=3, attempt_count=2 )
        assert ok

    def test_oom_blocked( self ):
        job = MockJob( "presentation", error="MemoryError: out of memory" )
        ok, reason = is_eligible_for_auto_fix( job, [ "presentation" ] )
        assert not ok
        assert "oom" in reason.lower()

    def test_environment_blocked( self ):
        job = MockJob( "presentation", error="ECONNREFUSED" )
        ok, reason = is_eligible_for_auto_fix( job, [ "presentation" ] )
        assert not ok
        assert "environment" in reason.lower()

    def test_cancelled_not_eligible( self ):
        job = MockJob( "presentation", state=JobState.CANCELLED )
        ok, reason = is_eligible_for_auto_fix( job, [ "presentation" ] )
        assert not ok
        assert "not FAILED" in reason

    def test_no_job_type( self ):
        job = MagicMock( spec=[] )  # no attributes
        ok, reason = is_eligible_for_auto_fix( job, [ "presentation" ] )
        assert not ok
        assert "no job_type" in reason.lower()


# =============================================================================
# Watchdog — Cooldown
# =============================================================================

class TestWatchdogCooldown:
    """Tests for cooldown enforcement."""

    def test_cooldown_elapsed_first_time( self ):
        watchdog = DeadQueueWatchdog( MockConfigMgr(), MockTodoQueue() )
        assert watchdog._cooldown_elapsed( "new-job" ) is True

    def test_cooldown_not_elapsed( self ):
        watchdog = DeadQueueWatchdog( MockConfigMgr(), MockTodoQueue() )
        watchdog._record_attempt_time( "job-1" )
        assert watchdog._cooldown_elapsed( "job-1" ) is False

    def test_cooldown_elapsed_after_wait( self ):
        watchdog = DeadQueueWatchdog( MockConfigMgr( { "auto fix cooldown seconds": 0 } ), MockTodoQueue() )
        watchdog._record_attempt_time( "job-1" )
        # With 0-second cooldown, it should immediately be elapsed
        assert watchdog._cooldown_elapsed( "job-1" ) is True

    def test_attempt_counting( self ):
        watchdog = DeadQueueWatchdog( MockConfigMgr(), MockTodoQueue() )
        assert watchdog.get_attempt_count( "job-1" ) == 0
        watchdog.increment_attempt( "job-1" )
        assert watchdog.get_attempt_count( "job-1" ) == 1
        watchdog.increment_attempt( "job-1" )
        assert watchdog.get_attempt_count( "job-1" ) == 2


# =============================================================================
# Watchdog — evaluate()
# =============================================================================

class TestWatchdogEvaluate:
    """Tests for the main evaluate() method."""

    def test_disabled_returns_none( self ):
        watchdog = DeadQueueWatchdog(
            MockConfigMgr( { "auto fix enabled": False } ), MockTodoQueue()
        )
        job = MockJob()
        assert watchdog.evaluate( job ) is None

    def test_ineligible_type_returns_none( self ):
        watchdog = DeadQueueWatchdog(
            MockConfigMgr( { "auto fix eligible job types": "deep_research" } ),
            MockTodoQueue()
        )
        job = MockJob( "presentation" )
        assert watchdog.evaluate( job ) is None

    @patch( "cosa.rest.dead_queue_watchdog.DeadQueueWatchdog._submit_bfe" )
    def test_eligible_triggers_bfe( self, mock_submit ):
        mock_submit.return_value = "bfe-test-123"
        watchdog = DeadQueueWatchdog( MockConfigMgr(), MockTodoQueue() )
        job = MockJob( "presentation", error="KeyError: 'oops'" )
        result = watchdog.evaluate( job )
        assert result == "bfe-test-123"
        mock_submit.assert_called_once()

    @patch( "cosa.rest.dead_queue_watchdog.DeadQueueWatchdog._direct_retry" )
    def test_timeout_triggers_direct_retry( self, mock_retry ):
        mock_retry.return_value = "retry-123"
        watchdog = DeadQueueWatchdog( MockConfigMgr(), MockTodoQueue() )
        job = MockJob( "presentation", error="TimeoutError: timed out" )
        result = watchdog.evaluate( job )
        mock_retry.assert_called_once()

    @patch( "cosa.rest.dead_queue_watchdog.DeadQueueWatchdog._direct_retry" )
    def test_rate_limit_triggers_direct_retry( self, mock_retry ):
        mock_retry.return_value = "retry-456"
        watchdog = DeadQueueWatchdog( MockConfigMgr(), MockTodoQueue() )
        job = MockJob( "presentation", error="RateLimitError: 429 Too Many Requests" )
        result = watchdog.evaluate( job )
        mock_retry.assert_called_once()


# =============================================================================
# State Model Additions
# =============================================================================

class TestPhase6StateModel:
    """Tests for Phase 6 additions to BFE state models."""

    def test_resubmitting_phase_exists( self ):
        assert BFEPhase.RESUBMITTING.value == "resubmitting"

    def test_bfe_phase_count( self ):
        """11 phases total after adding RESUBMITTING."""
        assert len( BFEPhase ) == 11

    def test_fix_result_has_resubmitted_job_id( self ):
        result = FixResult( applied=True, success=True, details="Fixed" )
        assert result.resubmitted_job_id is None

    def test_fix_result_resubmitted_job_id_set( self ):
        result = FixResult(
            applied=True, success=True, details="Fixed",
            resubmitted_job_id="pr-new-123::user1"
        )
        assert result.resubmitted_job_id == "pr-new-123::user1"

    def test_dead_job_context_has_routing_command( self ):
        ctx = DeadJobContext(
            id_hash="pr-test::user1", job_type="presentation",
            user_id="user1", user_email="test@test.com", session_id="s1",
            status="failed", question_text="make slides",
            routing_command="agent router go to presentation generator"
        )
        assert ctx.routing_command == "agent router go to presentation generator"

    def test_dead_job_context_has_metadata_json( self ):
        ctx = DeadJobContext(
            id_hash="pr-test::user1", job_type="presentation",
            user_id="user1", user_email="test@test.com", session_id="s1",
            status="failed", question_text="make slides",
            metadata_json={ "source_path": "/tmp/research.md" }
        )
        assert ctx.metadata_json[ "source_path" ] == "/tmp/research.md"
