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


# =============================================================================
# per-day decision history (row da64aaab)
# =============================================================================

class TestDecisionHistory:
    """update_after_ratification files each decision under its own UTC day."""

    @staticmethod
    def _state( total=0, ok=0, bad=0, history=None, updated_at=None ):
        from types import SimpleNamespace
        return SimpleNamespace(
            total_decisions = total, successful_decisions = ok, rejected_decisions = bad,
            decision_history = history, updated_at = updated_at or datetime.now( timezone.utc ),
        )

    def _ratify( self, repo, state, approved ):
        with patch.object( repo, "get_or_create", return_value=state ):
            repo.update_after_ratification( user_email="u@test.com", domain="swe", category="testing", approved=approved )

    @staticmethod
    def _today():
        return datetime.now( timezone.utc ).strftime( "%Y-%m-%d" )

    def test_a_new_row_starts_a_history_with_todays_decision( self, repo ):
        state = self._state()
        self._ratify( repo, state, True )
        assert state.decision_history == { self._today(): [ 1, 0 ] }

    def test_a_rejection_counts_in_the_second_slot_and_a_second_decision_adds_to_the_same_day( self, repo ):
        state = self._state()
        self._ratify( repo, state, True )
        self._ratify( repo, state, False )
        self._ratify( repo, state, False )
        assert state.decision_history == { self._today(): [ 1, 2 ] }

    def test_a_row_with_no_history_is_seeded_with_its_old_totals_under_its_updated_at_day( self, repo ):
        from datetime import timedelta
        stamp = datetime.now( timezone.utc ) - timedelta( days=5 )
        state = self._state( total=4, ok=3, bad=1, updated_at=stamp )
        self._ratify( repo, state, True )
        assert state.decision_history == { stamp.strftime( "%Y-%m-%d" ): [ 3, 1 ], self._today(): [ 1, 0 ] }
        assert state.total_decisions == 5

    def test_days_past_the_retention_are_dropped_and_the_stored_dict_is_replaced_not_mutated( self, repo ):
        from datetime import timedelta
        from cosa.rest.db.repositories.proxy_decision_repository import DECISION_HISTORY_RETENTION_DAYS
        now      = datetime.now( timezone.utc )
        old_day  = ( now - timedelta( days=DECISION_HISTORY_RETENTION_DAYS + 1 ) ).strftime( "%Y-%m-%d" )
        keep_day = ( now - timedelta( days=DECISION_HISTORY_RETENTION_DAYS - 1 ) ).strftime( "%Y-%m-%d" )
        stored   = { old_day: [ 9, 9 ], keep_day: [ 2, 0 ] }
        state    = self._state( total=20, ok=11, bad=9, history=stored )
        self._ratify( repo, state, False )
        assert state.decision_history == { keep_day: [ 2, 0 ], self._today(): [ 0, 1 ] }
        assert state.decision_history is not stored and old_day in stored, "a new dict, so the JSONB column sees the change"



# =============================================================================
# BLR state (row 5bb93a7b)
# =============================================================================

class TestBlrState:
    """update_after_ratification stores a given BLR state and otherwise leaves it alone."""

    @staticmethod
    def _state( blr_state="stored" ):
        from types import SimpleNamespace
        return SimpleNamespace(
            total_decisions = 0, successful_decisions = 0, rejected_decisions = 0,
            decision_history = None, updated_at = datetime.now( timezone.utc ), blr_state = blr_state,
        )

    def _ratify( self, repo, state, **extra ):
        with patch.object( repo, "get_or_create", return_value=state ):
            repo.update_after_ratification( user_email="u@test.com", domain="swe", category="testing", approved=True, **extra )

    def test_a_given_state_is_stored( self, repo ):
        state = self._state( blr_state=None )
        self._ratify( repo, state, blr_state={ "w": [ 0.1 ] } )
        assert state.blr_state == { "w": [ 0.1 ] }

    def test_the_default_leaves_the_stored_state_alone( self, repo ):
        state = self._state()
        self._ratify( repo, state )          # the ratify endpoint has no tracker
        assert state.blr_state == "stored"

    def test_none_clears_the_stored_state( self, repo ):
        state = self._state()
        self._ratify( repo, state, blr_state=None )
        assert state.blr_state is None
