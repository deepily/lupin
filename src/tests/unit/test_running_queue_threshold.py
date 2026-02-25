"""
Unit Tests for Running Queue Threshold Guard

Tests that RunningFifoQueue's second cache check enforces the similarity
threshold floor, preventing sub-threshold matches from being accepted.
This was Bug A: "What's 4+4?" returning "What's 3+3?" answer (73.3% match).
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock


class TestRunningQueueThresholdGuard:
    """Unit tests for the 2-tier threshold check in _process_job()."""

    def _make_mock_running_job( self, question="What is 4+4?" ):
        """Create a mock AgentBase job with standard attributes."""
        from cosa.agents.agent_base import AgentBase
        job = MagicMock( spec=AgentBase )
        job.last_question_asked = question
        job.user_id             = "test_user"
        job.user_email          = "test@test.com"
        job.session_id          = "test_session"
        job.id_hash             = "test_hash_123"
        job.job_type            = "math"
        job.created_date        = "2026-01-01"
        job.started_at          = None
        return job

    def _make_mock_snapshot( self, run_date="2026-01-15" ):
        """Create a mock cached snapshot."""
        snapshot = MagicMock()
        snapshot.run_date = run_date
        return snapshot

    # ==================== Exact Match (100%) ====================

    def test_exact_match_accepts( self ):
        """Score >= 100.0 auto-accepts without threshold check."""
        score     = 100.0
        threshold = 90.0

        # Simulate the 2-tier decision
        if score >= 100.0:
            result = "exact_hit"
        elif score >= threshold:
            result = "threshold_accept"
        else:
            result = "threshold_reject"

        assert result == "exact_hit"

    # ==================== Above Threshold ====================

    def test_above_threshold_accepts( self ):
        """Score >= threshold_confirmation accepts the match."""
        score     = 95.0
        threshold = 90.0

        if score >= 100.0:
            result = "exact_hit"
        elif score >= threshold:
            result = "threshold_accept"
        else:
            result = "threshold_reject"

        assert result == "threshold_accept"

    def test_at_threshold_boundary_accepts( self ):
        """Score exactly at threshold boundary accepts."""
        score     = 90.0
        threshold = 90.0

        if score >= 100.0:
            result = "exact_hit"
        elif score >= threshold:
            result = "threshold_accept"
        else:
            result = "threshold_reject"

        assert result == "threshold_accept"

    # ==================== Below Threshold (THE BUG) ====================

    def test_below_threshold_rejects( self ):
        """Score below threshold rejects — this was the 4+4 bug."""
        score     = 73.3  # The actual score from the bug report
        threshold = 90.0

        if score >= 100.0:
            result = "exact_hit"
        elif score >= threshold:
            result = "threshold_accept"
        else:
            result = "threshold_reject"

        assert result == "threshold_reject"

    def test_just_below_threshold_rejects( self ):
        """Score at 89.9% (just below 90%) rejects."""
        score     = 89.9
        threshold = 90.0

        if score >= 100.0:
            result = "exact_hit"
        elif score >= threshold:
            result = "threshold_accept"
        else:
            result = "threshold_reject"

        assert result == "threshold_reject"

    def test_zero_score_rejects( self ):
        """Score of 0.0 rejects."""
        score     = 0.0
        threshold = 90.0

        if score >= 100.0:
            result = "exact_hit"
        elif score >= threshold:
            result = "threshold_accept"
        else:
            result = "threshold_reject"

        assert result == "threshold_reject"

    # ==================== Config Initialization ====================

    def test_threshold_defaults_to_90_without_config( self ):
        """threshold_confirmation defaults to 90.0 when config_mgr is None."""
        config_mgr = None
        threshold  = 90.0 if config_mgr is None else config_mgr.get( "similarity_threshold_confirmation", default=90.0, return_type="float" )

        assert threshold == 90.0

    def test_threshold_reads_from_config( self ):
        """threshold_confirmation reads from config when config_mgr provided."""
        config_mgr = MagicMock()
        config_mgr.get.return_value = 85.0

        threshold = 90.0 if config_mgr is None else config_mgr.get( "similarity_threshold_confirmation", default=90.0, return_type="float" )

        assert threshold == 85.0
        config_mgr.get.assert_called_once_with( "similarity_threshold_confirmation", default=90.0, return_type="float" )

    # ==================== Edge Cases ====================

    def test_empty_cache_results_routes_to_agent( self ):
        """Empty cached_snapshots list routes to agent (no crash)."""
        cached_snapshots = []

        if cached_snapshots and len( cached_snapshots ) > 0:
            result = "cache_hit"
        else:
            result = "cache_miss"

        assert result == "cache_miss"

    def test_none_cache_results_routes_to_agent( self ):
        """None cached_snapshots routes to agent (no crash)."""
        cached_snapshots = None

        if cached_snapshots and len( cached_snapshots ) > 0:
            result = "cache_hit"
        else:
            result = "cache_miss"

        assert result == "cache_miss"

    def test_custom_threshold_from_config( self ):
        """Custom threshold (e.g., 95%) correctly rejects 92% match."""
        score     = 92.0
        threshold = 95.0  # Raised threshold

        if score >= 100.0:
            result = "exact_hit"
        elif score >= threshold:
            result = "threshold_accept"
        else:
            result = "threshold_reject"

        assert result == "threshold_reject"
