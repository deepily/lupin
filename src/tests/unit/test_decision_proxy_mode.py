#!/usr/bin/env python3
"""
Unit tests for Decision Proxy trust mode hot-reload endpoints (Phase 8).

Tests for:
    - GET /api/proxy/mode — returns INI + running + effective mode
    - PUT /api/proxy/mode — validates input, hot-reloads or queues
    - TrustModeUpdateRequest validation
"""

from unittest.mock import MagicMock, patch

import pytest

from cosa.rest.routers.decision_proxy import (
    TrustModeUpdateRequest,
    _find_running_swe_job,
    VALID_TRUST_MODES,
)


# =============================================================================
# TrustModeUpdateRequest Validation
# =============================================================================

class TestTrustModeUpdateRequest:
    """Pydantic model validation tests."""

    def test_valid_modes_accepted( self ):
        """All 4 valid trust modes should be accepted."""
        for mode in ( "disabled", "shadow", "suggest", "active" ):
            req = TrustModeUpdateRequest( mode=mode )
            assert req.mode == mode
            assert req.domain == "swe"  # default

    def test_invalid_mode_rejected( self ):
        """Invalid mode string should raise ValidationError."""
        from pydantic import ValidationError
        with pytest.raises( ValidationError ):
            TrustModeUpdateRequest( mode="turbo" )

    def test_custom_domain( self ):
        """Domain can be overridden from default 'swe'."""
        req = TrustModeUpdateRequest( mode="shadow", domain="ml" )
        assert req.domain == "ml"


# =============================================================================
# _find_running_swe_job
# =============================================================================

class TestFindRunningSweJob:
    """Tests for the helper that locates running SWE jobs in the run queue."""

    def test_none_queue_returns_none( self ):
        """None run_queue returns None."""
        assert _find_running_swe_job( None ) is None

    def test_empty_queue_returns_none( self ):
        """Empty job list returns None."""
        mock_queue = MagicMock()
        mock_queue.get_all_jobs.return_value = []
        assert _find_running_swe_job( mock_queue ) is None

    def test_non_swe_jobs_skipped( self ):
        """Non-SweTeamJob instances are skipped."""
        mock_queue = MagicMock()
        mock_job   = MagicMock()  # Not a SweTeamJob
        mock_queue.get_all_jobs.return_value = [ mock_job ]
        assert _find_running_swe_job( mock_queue ) is None

    def test_swe_job_without_orchestrator_skipped( self ):
        """SweTeamJob with _orchestrator=None is skipped."""
        from cosa.agents.swe_team.job import SweTeamJob

        job = SweTeamJob(
            task       = "test",
            user_id    = "u1",
            user_email = "t@t.com",
            session_id = "s1",
            dry_run    = True,
        )
        mock_queue = MagicMock()
        mock_queue.get_all_jobs.return_value = [ job ]
        assert _find_running_swe_job( mock_queue ) is None

    def test_swe_job_with_orchestrator_found( self ):
        """SweTeamJob with live _orchestrator is returned."""
        from cosa.agents.swe_team.job import SweTeamJob

        job = SweTeamJob(
            task       = "test",
            user_id    = "u1",
            user_email = "t@t.com",
            session_id = "s1",
            dry_run    = True,
        )
        job._orchestrator = MagicMock()

        mock_queue = MagicMock()
        mock_queue.get_all_jobs.return_value = [ job ]
        assert _find_running_swe_job( mock_queue ) is job


# =============================================================================
# VALID_TRUST_MODES constant
# =============================================================================

class TestValidTrustModes:
    """Verify the VALID_TRUST_MODES constant."""

    def test_contains_all_modes( self ):
        """VALID_TRUST_MODES should contain exactly 4 modes."""
        assert len( VALID_TRUST_MODES ) == 4
        assert "disabled" in VALID_TRUST_MODES
        assert "shadow" in VALID_TRUST_MODES
        assert "suggest" in VALID_TRUST_MODES
        assert "active" in VALID_TRUST_MODES
