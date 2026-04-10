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


# =============================================================================
# Phase 6 Dry-Run Repair Loop Hooks (Step 2-4)
# =============================================================================

class TestDryRunRepairLoopHooks:
    """
    Tests for the Phase 6 dry-run repair loop plumbing:
      - Watchdog propagates dry_run=True from failed mock jobs to spawned BFE
      - AgenticJobBase._raise_forced_failure() raises correct exception types
    """

    @patch( "cosa.rest.queue_extensions.user_job_tracker.register_scoped_job" )
    @patch( "cosa.rest.agentic_job_factory.create_agentic_job" )
    def test_watchdog_propagates_dry_run_to_bfe( self, mock_create, mock_register ):
        """When failed job has dry_run=True, spawned BFE args_dict must contain dry_run=True."""
        mock_bfe_job = MagicMock()
        mock_bfe_job.id_hash = "bfx-dryrun-test::user1"
        mock_create.return_value = mock_bfe_job
        mock_register.return_value = "bfx-dryrun-test::user1"

        watchdog = DeadQueueWatchdog( MockConfigMgr(), MockTodoQueue() )
        job = MockJob( "presentation", error="KeyError: 'oops'" )
        job.dry_run = True

        result = watchdog._submit_bfe( job, attempt_count=0 )

        assert result == "bfx-dryrun-test::user1"
        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs[ "args_dict" ][ "dry_run" ] is True, \
            "Spawned BFE must inherit dry_run=True when dead job is a dry-run mock"
        assert call_kwargs[ "args_dict" ][ "dead_job_id" ] == job.id_hash

    @patch( "cosa.rest.queue_extensions.user_job_tracker.register_scoped_job" )
    @patch( "cosa.rest.agentic_job_factory.create_agentic_job" )
    def test_watchdog_does_not_propagate_dry_run_for_live_failures( self, mock_create, mock_register ):
        """Live failures (no dry_run attribute) must not inject dry_run into BFE args."""
        mock_bfe_job = MagicMock()
        mock_bfe_job.id_hash = "bfx-live-test::user1"
        mock_create.return_value = mock_bfe_job
        mock_register.return_value = "bfx-live-test::user1"

        watchdog = DeadQueueWatchdog( MockConfigMgr(), MockTodoQueue() )
        job = MockJob( "presentation", error="KeyError: 'oops'" )
        # no dry_run attribute set → defaults to False via getattr

        watchdog._submit_bfe( job, attempt_count=0 )

        call_kwargs = mock_create.call_args.kwargs
        assert "dry_run" not in call_kwargs[ "args_dict" ], \
            "Live failures must not inject dry_run into spawned BFE"

    @pytest.mark.asyncio
    async def test_raise_forced_failure_code_bug( self ):
        """force_failure_mode='code_bug' must raise KeyError."""
        from cosa.agents.agentic_job_base import AgenticJobBase

        stub = MagicMock( spec=AgenticJobBase )
        stub.id_hash           = "test-123"
        stub.force_failure_mode = "code_bug"
        voice_io = MagicMock()
        voice_io.notify = AsyncMock()

        with pytest.raises( KeyError ) as exc_info:
            await AgenticJobBase._raise_forced_failure( stub, voice_io )
        assert "Phase 6" in str( exc_info.value )

    @pytest.mark.asyncio
    async def test_raise_forced_failure_infra_timeout( self ):
        """force_failure_mode='infra_timeout' must raise asyncio.TimeoutError."""
        import asyncio
        from cosa.agents.agentic_job_base import AgenticJobBase

        stub = MagicMock( spec=AgenticJobBase )
        stub.id_hash           = "test-123"
        stub.force_failure_mode = "infra_timeout"
        voice_io = MagicMock()
        voice_io.notify = AsyncMock()

        with pytest.raises( asyncio.TimeoutError ):
            await AgenticJobBase._raise_forced_failure( stub, voice_io )

    @pytest.mark.asyncio
    async def test_raise_forced_failure_rate_limit( self ):
        """force_failure_mode='rate_limit' must raise Exception with RateLimitError prefix."""
        from cosa.agents.agentic_job_base import AgenticJobBase

        stub = MagicMock( spec=AgenticJobBase )
        stub.id_hash           = "test-123"
        stub.force_failure_mode = "rate_limit"
        voice_io = MagicMock()
        voice_io.notify = AsyncMock()

        with pytest.raises( Exception ) as exc_info:
            await AgenticJobBase._raise_forced_failure( stub, voice_io )
        assert "RateLimitError" in str( exc_info.value )
        assert "429" in str( exc_info.value )

    @pytest.mark.asyncio
    async def test_raise_forced_failure_unknown_mode( self ):
        """Unknown force_failure_mode must raise ValueError."""
        from cosa.agents.agentic_job_base import AgenticJobBase

        stub = MagicMock( spec=AgenticJobBase )
        stub.id_hash           = "test-123"
        stub.force_failure_mode = "nonsense"
        voice_io = MagicMock()
        voice_io.notify = AsyncMock()

        with pytest.raises( ValueError ) as exc_info:
            await AgenticJobBase._raise_forced_failure( stub, voice_io )
        assert "Unknown force_failure_mode" in str( exc_info.value )

    def test_failure_classification_matches_forced_errors( self ):
        """The exceptions raised by _raise_forced_failure must classify correctly in the watchdog."""
        # code_bug → CODE_BUG
        assert classify_failure( "KeyError: 'source_path' — simulated mock failure" ) == FailureCategory.CODE_BUG
        # infra_timeout → INFRA_TIMEOUT
        assert classify_failure( "asyncio.TimeoutError: simulated mock timeout" ) == FailureCategory.INFRA_TIMEOUT
        # rate_limit → INFRA_RATE_LIMIT
        assert classify_failure( "RateLimitError: 429 Too Many Requests — simulated" ) == FailureCategory.INFRA_RATE_LIMIT


# =============================================================================
# MockJobSubmitRequest force_failure_mode validation (Step 1)
# =============================================================================

class TestMockJobForceFailureMode:
    """Tests for the force_failure_mode field on MockJobSubmitRequest."""

    def test_force_failure_mode_defaults_to_none( self ):
        from cosa.rest.routers.mock_job import MockJobSubmitRequest
        req = MockJobSubmitRequest()
        assert req.force_failure_mode is None

    def test_force_failure_mode_accepts_code_bug( self ):
        from cosa.rest.routers.mock_job import MockJobSubmitRequest
        req = MockJobSubmitRequest( force_failure_mode="code_bug" )
        assert req.force_failure_mode == "code_bug"

    def test_force_failure_mode_accepts_infra_timeout( self ):
        from cosa.rest.routers.mock_job import MockJobSubmitRequest
        req = MockJobSubmitRequest( force_failure_mode="infra_timeout" )
        assert req.force_failure_mode == "infra_timeout"

    def test_force_failure_mode_accepts_rate_limit( self ):
        from cosa.rest.routers.mock_job import MockJobSubmitRequest
        req = MockJobSubmitRequest( force_failure_mode="rate_limit" )
        assert req.force_failure_mode == "rate_limit"

    def test_force_failure_mode_rejects_invalid( self ):
        from cosa.rest.routers.mock_job import MockJobSubmitRequest
        from pydantic import ValidationError
        with pytest.raises( ValidationError ):
            MockJobSubmitRequest( force_failure_mode="garbage" )


# =============================================================================
# Persistence Round-Trip (CJ Flow fix: routing_command + original_args)
# =============================================================================

class TestPersistenceRoundTrip:
    """
    Tests that every CJ Flow job carries `routing_command` and `original_args`
    and that the persistence layer whitelists and preserves them.
    """

    def test_agentic_job_base_has_attributes( self ):
        """Fresh DeepResearchJob (via AgenticJobBase) has the persistence attrs as None defaults."""
        from cosa.agents.deep_research.job import DeepResearchJob
        job = DeepResearchJob(
            query      = "x",
            user_id    = "u1",
            user_email = "t@t.com",
            session_id = "s1",
        )
        assert hasattr( job, "routing_command" )
        assert hasattr( job, "original_args" )
        assert job.routing_command is None
        assert job.original_args   is None

    def test_factory_sets_routing_command_and_original_args( self ):
        """create_agentic_job() must populate both fields on the returned job."""
        from cosa.rest.agentic_job_factory import create_agentic_job
        args_dict = { "query": "phase6 test", "budget": 1.0, "audience": "expert" }
        job = create_agentic_job(
            command    = "agent router go to deep research",
            args_dict  = args_dict,
            user_id    = "u1",
            user_email = "t@t.com",
            session_id = "s1",
        )
        assert job is not None
        assert job.routing_command == "agent router go to deep research"
        assert job.original_args   == { "query": "phase6 test", "budget": 1.0, "audience": "expert" }

    def test_factory_copies_args_dict_defensively( self ):
        """Mutating args_dict after factory call must NOT mutate job.original_args."""
        from cosa.rest.agentic_job_factory import create_agentic_job
        args_dict = { "query": "phase6 test", "budget": 1.0 }
        job = create_agentic_job(
            command    = "agent router go to deep research",
            args_dict  = args_dict,
            user_id    = "u1",
            user_email = "t@t.com",
            session_id = "s1",
        )
        args_dict[ "budget" ]  = 999.0
        args_dict[ "injected" ] = "bad"
        assert job.original_args[ "budget" ] == 1.0, "factory must defensively copy args_dict"
        assert "injected" not in job.original_args

    def test_build_metadata_json_preserves_original_args( self ):
        """_build_metadata_json() whitelists `original_args`."""
        from cosa.rest.job_persistence import _build_metadata_json
        result = _build_metadata_json( {
            "agent_type"   : "deep_research",
            "original_args": { "query": "q", "budget": 1.0, "audience": "expert" },
            "stack_trace"  : "traceback...",
        } )
        assert result[ "original_args" ] == { "query": "q", "budget": 1.0, "audience": "expert" }
        assert result[ "stack_trace" ]   == "traceback..."

    def test_build_metadata_json_null_safe_when_original_args_absent( self ):
        """Missing `original_args` must not appear in the output (not even as None)."""
        from cosa.rest.job_persistence import _build_metadata_json
        result = _build_metadata_json( { "agent_type": "deep_research" } )
        assert "original_args" not in result

    def test_build_metadata_json_drops_explicit_none( self ):
        """Passing `original_args=None` should also NOT appear in the output."""
        from cosa.rest.job_persistence import _build_metadata_json
        result = _build_metadata_json( { "agent_type": "deep_research", "original_args": None } )
        assert "original_args" not in result
