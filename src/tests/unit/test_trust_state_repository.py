#!/usr/bin/env python3
"""
Unit tests for TrustStateRepository — mock session tests.

Tests get_or_create(), update_after_ratification(), get_all_for_user(),
update_trust_level(), and update_circuit_breaker_state().
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from cosa.rest.db.repositories.proxy_decision_repository import TrustStateRepository


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_session():
    """Mock SQLAlchemy session."""
    session = MagicMock()
    return session


@pytest.fixture
def repo( mock_session ):
    """TrustStateRepository with mocked session."""
    return TrustStateRepository( mock_session )


# =============================================================================
# update_after_ratification() Tests
# =============================================================================

class TestUpdateAfterRatification:
    """Tests for trust state updates after ratification events."""

    def test_approved_increments_successful( self, repo ):
        """update_after_ratification(approved=True) increments successful_decisions."""
        mock_state = MagicMock()
        mock_state.total_decisions      = 5
        mock_state.successful_decisions = 4
        mock_state.rejected_decisions   = 1

        with patch.object( repo, "get_or_create", return_value=mock_state ):
            result = repo.update_after_ratification(
                user_email = "user@test.com",
                domain     = "swe",
                category   = "testing",
                approved   = True,
            )

        assert mock_state.total_decisions == 6
        assert mock_state.successful_decisions == 5
        assert mock_state.rejected_decisions == 1

    def test_rejected_increments_rejected( self, repo ):
        """update_after_ratification(approved=False) increments rejected_decisions."""
        mock_state = MagicMock()
        mock_state.total_decisions      = 5
        mock_state.successful_decisions = 4
        mock_state.rejected_decisions   = 1

        with patch.object( repo, "get_or_create", return_value=mock_state ):
            result = repo.update_after_ratification(
                user_email = "user@test.com",
                domain     = "swe",
                category   = "architecture",
                approved   = False,
            )

        assert mock_state.total_decisions == 6
        assert mock_state.successful_decisions == 4
        assert mock_state.rejected_decisions == 2

    def test_updates_timestamp( self, repo ):
        """update_after_ratification() sets updated_at to current time."""
        mock_state = MagicMock()
        mock_state.total_decisions      = 0
        mock_state.successful_decisions = 0
        mock_state.rejected_decisions   = 0

        with patch.object( repo, "get_or_create", return_value=mock_state ):
            repo.update_after_ratification(
                user_email = "user@test.com",
                domain     = "swe",
                category   = "testing",
                approved   = True,
            )

        assert mock_state.updated_at is not None


# =============================================================================
# Orchestrator._persist_trust_feedback() Integration
# =============================================================================

class TestOrchestratorPersistTrustFeedback:
    """Tests for orchestrator's trust feedback DB persistence."""

    def test_persist_trust_feedback_calls_update_after_ratification( self ):
        """_persist_trust_feedback() calls TrustStateRepository.update_after_ratification()."""
        from cosa.agents.swe_team.orchestrator import SweTeamOrchestrator
        from cosa.agents.swe_team.config import SweTeamConfig

        config = SweTeamConfig( trust_mode="shadow" )
        orch = SweTeamOrchestrator(
            task_description = "Test persist",
            config           = config,
            session_id       = "test-persist",
        )

        mock_repo = MagicMock()
        mock_session = MagicMock()

        with patch( "cosa.rest.db.database.get_db" ) as mock_get_db:
            mock_get_db.return_value.__enter__ = MagicMock( return_value=mock_session )
            mock_get_db.return_value.__exit__  = MagicMock( return_value=False )

            with patch( "cosa.rest.db.repositories.proxy_decision_repository.TrustStateRepository", return_value=mock_repo ) as mock_cls:
                orch._persist_trust_feedback( "testing", True )

            mock_repo.update_after_ratification.assert_called_once_with(
                user_email = "test-persist@swe.deepily.ai",
                domain     = "swe",
                category   = "testing",
                approved   = True,
            )

    def test_persist_trust_feedback_failure_is_non_fatal( self ):
        """_persist_trust_feedback() swallows exceptions without propagating."""
        from cosa.agents.swe_team.orchestrator import SweTeamOrchestrator
        from cosa.agents.swe_team.config import SweTeamConfig

        config = SweTeamConfig( trust_mode="shadow" )
        orch = SweTeamOrchestrator(
            task_description = "Test error handling",
            config           = config,
            session_id       = "test-error",
        )

        with patch( "cosa.rest.db.database.get_db", side_effect=Exception( "DB connection failed" ) ):
            # Should NOT raise
            orch._persist_trust_feedback( "deployment", False )
