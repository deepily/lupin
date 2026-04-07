"""
Integration smoke tests for the full automated repair loop.

Tests the complete cycle: failed job → watchdog evaluates → BFE triggered →
tracker records attempt → circuit breakers fire. All with mocks, no server needed.
"""

import pytest
from unittest.mock import MagicMock, patch

from cosa.rest.dead_queue_watchdog import (
    DeadQueueWatchdog,
    FailureCategory,
    classify_failure,
)
from cosa.rest.repair_attempt_tracker import (
    RepairAttemptTracker,
    RepairChain,
    RepairAttempt,
    cosine_similarity,
    is_semantically_duplicate,
)
from cosa.rest.job_state import JobState


# =============================================================================
# Fixtures
# =============================================================================

class MockConfigMgr:
    """Mock ConfigurationManager."""
    def __init__( self, overrides=None ):
        self._values = {
            "auto fix enabled"              : True,
            "auto fix eligible job types"    : "presentation, deep_research, podcast, test_suite",
            "auto fix max attempts per job"  : 3,
            "auto fix max cost usd"          : 10.0,
            "auto fix max wall clock seconds": 1800,
            "auto fix cooldown seconds"      : 0,   # No cooldown for tests
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
    """Mock failed agentic job."""
    def __init__( self, job_type="presentation", error="KeyError: 'missing_key'",
                  user_id="user1", user_email="test@test.com" ):
        self.job_type   = job_type
        self.JOB_TYPE   = job_type
        self.state      = JobState.FAILED
        self.error      = error
        self.id_hash    = f"pr-test1234::{user_id}"
        self.user_id    = user_id
        self.user_email = user_email
        self.session_id = "wise-penguin"
        self.artifacts  = {}


class MockTodoQueue:
    """Captures push calls."""
    def __init__( self ):
        self.pushed = []

    def push( self, job ):
        self.pushed.append( job )

    def push_job( self, question, session_id, user_id, user_email ):
        self.pushed.append( { "question": question, "user_id": user_id } )
        return { "message": "queued", "job_id": "retry-mock" }


# =============================================================================
# Full Cycle: Watchdog → BFE Submission
# =============================================================================

class TestFullCycleWatchdogToBFE:
    """Integration: failed job → watchdog → BFE job created."""

    def test_watchdog_submits_bfe_for_code_bug( self ):
        """Code bug → watchdog creates BFE job → pushes to queue."""
        todo_queue = MockTodoQueue()
        watchdog   = DeadQueueWatchdog( MockConfigMgr(), todo_queue, debug=True )
        job        = MockJob( "presentation", error="KeyError: 'missing_key'" )

        # Mock _submit_bfe to avoid factory/queue_extensions imports
        watchdog._submit_bfe = MagicMock( return_value="bfe-auto-001" )

        result = watchdog.evaluate( job )

        assert result == "bfe-auto-001"
        watchdog._submit_bfe.assert_called_once()

    def test_watchdog_blocks_bfe_recursion( self ):
        """BFE job type → rejected (recursion prevention)."""
        watchdog = DeadQueueWatchdog( MockConfigMgr(), MockTodoQueue(), debug=True )
        job = MockJob( "bug_fix_expediter", error="KeyError: 'oops'" )
        result = watchdog.evaluate( job )
        assert result is None

    def test_watchdog_disabled_returns_none( self ):
        """auto fix enabled = false → nothing happens."""
        watchdog = DeadQueueWatchdog(
            MockConfigMgr( { "auto fix enabled": False } ), MockTodoQueue()
        )
        job = MockJob()
        assert watchdog.evaluate( job ) is None


# =============================================================================
# Circuit Breakers via Tracker
# =============================================================================

class TestCircuitBreakers:
    """Integration: tracker circuit breakers block watchdog."""

    def test_max_attempts_blocks_watchdog( self ):
        """After max attempts, tracker.can_attempt() returns False."""
        cfg     = MockConfigMgr()
        tracker = RepairAttemptTracker( cfg, debug=True )

        # Simulate 3 attempts
        tracker.record_attempt( "pr-dead::user1", "bfe-1" )
        tracker.record_attempt( "pr-dead::user1", "bfe-2" )
        tracker.record_attempt( "pr-dead::user1", "bfe-3" )

        ok, reason = tracker.can_attempt( "pr-dead::user1" )
        assert not ok
        assert "max attempts" in reason.lower()

    def test_cost_budget_blocks_watchdog( self ):
        """After exceeding cost budget, tracker blocks."""
        cfg     = MockConfigMgr( { "auto fix max cost usd": 5.0 } )
        tracker = RepairAttemptTracker( cfg, debug=True )

        tracker.record_attempt( "pr-dead::user1", "bfe-1" )
        tracker.update_attempt( "pr-dead::user1", cost_usd=3.0 )
        tracker.record_attempt( "pr-dead::user1", "bfe-2" )
        tracker.update_attempt( "pr-dead::user1", cost_usd=2.5 )

        ok, reason = tracker.can_attempt( "pr-dead::user1" )
        assert not ok
        assert "cost budget" in reason.lower()

    def test_wall_clock_blocks_watchdog( self ):
        """After wall-clock timeout, tracker blocks."""
        cfg     = MockConfigMgr( { "auto fix max wall clock seconds": 0 } )
        tracker = RepairAttemptTracker( cfg, debug=True )

        ok, reason = tracker.can_attempt( "pr-dead::user1" )
        assert not ok
        assert "wall-clock" in reason.lower()


# =============================================================================
# Semantic Deduplication
# =============================================================================

class TestSemanticDedup:
    """Integration: semantic dedup detects stuck agents."""

    def test_identical_fix_detected( self ):
        """Same embedding across attempts → duplicate detected."""
        tracker = RepairAttemptTracker( MockConfigMgr(), debug=True )

        tracker.record_attempt( "job-1", "bfe-1" )
        tracker.update_attempt( "job-1",
            fix_gist="Fix missing import in foo.py",
            fix_gist_embedding=[ 0.9, 0.1, 0.05 ]
        )

        is_dup, sim, match = tracker.check_semantic_dedup(
            "job-1", [ 0.91, 0.09, 0.04 ]
        )
        assert is_dup
        assert sim > 0.92
        assert match == 1

    def test_different_fix_passes( self ):
        """Orthogonal embedding → not duplicate."""
        tracker = RepairAttemptTracker( MockConfigMgr(), debug=True )

        tracker.record_attempt( "job-1", "bfe-1" )
        tracker.update_attempt( "job-1",
            fix_gist="Fix missing import in foo.py",
            fix_gist_embedding=[ 1.0, 0.0, 0.0 ]
        )

        is_dup, sim, match = tracker.check_semantic_dedup(
            "job-1", [ 0.0, 1.0, 0.0 ]
        )
        assert not is_dup
        assert sim < 0.1

    def test_no_prior_embeddings( self ):
        """No prior embeddings → not duplicate."""
        tracker = RepairAttemptTracker( MockConfigMgr(), debug=True )
        tracker.record_attempt( "job-1", "bfe-1" )

        is_dup, sim, match = tracker.check_semantic_dedup(
            "job-1", [ 0.5, 0.5, 0.5 ]
        )
        assert not is_dup


# =============================================================================
# Direct Retry for Transient Failures
# =============================================================================

class TestDirectRetry:
    """Integration: transient failures bypass BFE."""

    def test_timeout_triggers_direct_retry( self ):
        """TimeoutError → direct retry, no BFE."""
        watchdog = DeadQueueWatchdog( MockConfigMgr(), MockTodoQueue(), debug=True )
        watchdog._direct_retry = MagicMock( return_value="retry-id" )
        watchdog._submit_bfe   = MagicMock( return_value="bfe-id" )

        job = MockJob( "presentation", error="TimeoutError: request timed out" )
        watchdog.evaluate( job )

        watchdog._direct_retry.assert_called_once()
        watchdog._submit_bfe.assert_not_called()

    def test_rate_limit_triggers_direct_retry( self ):
        """429 rate limit → direct retry, no BFE."""
        watchdog = DeadQueueWatchdog( MockConfigMgr(), MockTodoQueue(), debug=True )
        watchdog._direct_retry = MagicMock( return_value="retry-id" )
        watchdog._submit_bfe   = MagicMock( return_value="bfe-id" )

        job = MockJob( "presentation", error="429 Too Many Requests" )
        watchdog.evaluate( job )

        watchdog._direct_retry.assert_called_once()
        watchdog._submit_bfe.assert_not_called()

    def test_code_bug_triggers_bfe_not_retry( self ):
        """KeyError → BFE, not direct retry."""
        watchdog = DeadQueueWatchdog( MockConfigMgr(), MockTodoQueue(), debug=True )
        watchdog._direct_retry = MagicMock( return_value="retry-id" )
        watchdog._submit_bfe   = MagicMock( return_value="bfe-id" )

        job = MockJob( "presentation", error="KeyError: 'foo'" )
        watchdog.evaluate( job )

        watchdog._submit_bfe.assert_called_once()
        watchdog._direct_retry.assert_not_called()


# =============================================================================
# Repair Chain Summary
# =============================================================================

class TestRepairChainSummary:
    """Integration: chain summary for observability."""

    def test_chain_summary_structure( self ):
        tracker = RepairAttemptTracker( MockConfigMgr(), debug=True )

        tracker.record_attempt( "job-X", "bfe-X1" )
        tracker.update_attempt( "job-X", cost_usd=1.5, outcome="fix_failed",
                                fix_gist="Attempted import fix" )
        tracker.record_attempt( "job-X", "bfe-X2" )
        tracker.update_attempt( "job-X", cost_usd=2.0, outcome="fixed",
                                resubmitted_job_id="pr-resubmit-X2" )

        summary = tracker.get_chain_summary( "job-X" )
        assert summary[ "original_job_id" ] == "job-X"
        assert summary[ "attempt_count" ] == 2
        assert summary[ "cumulative_cost" ] == 3.5
        assert len( summary[ "attempts" ] ) == 2
        assert summary[ "attempts" ][ 0 ][ "outcome" ] == "fix_failed"
        assert summary[ "attempts" ][ 1 ][ "outcome" ] == "fixed"
        assert summary[ "attempts" ][ 1 ][ "resubmitted_job_id" ] == "pr-resubmit-X2"

    def test_nonexistent_chain_returns_none( self ):
        tracker = RepairAttemptTracker( MockConfigMgr() )
        assert tracker.get_chain_summary( "nonexistent" ) is None
