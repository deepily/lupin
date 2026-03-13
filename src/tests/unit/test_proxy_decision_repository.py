#!/usr/bin/env python3
"""
Unit tests for ProxyDecisionRepository — mock session tests.

Tests log_shadow(), log_decision(), get_pending(), ratify(), and
get_pending_summary() with mocked SQLAlchemy sessions.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from cosa.rest.db.repositories.proxy_decision_repository import (
    ProxyDecisionRepository,
)


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
    """ProxyDecisionRepository with mocked session."""
    return ProxyDecisionRepository( mock_session )


# =============================================================================
# log_shadow() Tests
# =============================================================================

class TestLogShadow:
    """Tests for shadow decision logging."""

    def test_log_shadow_calls_create( self, repo ):
        """log_shadow() calls create() with shadow action and not_required ratification."""
        with patch.object( repo, "create", return_value=MagicMock() ) as mock_create:
            result = repo.log_shadow(
                notification_id = "notif-123",
                domain          = "swe",
                category        = "testing",
                question        = "Run integration tests?",
                sender_id       = "swe.coder@lupin.deepily.ai",
                confidence      = 0.85,
                trust_level     = 1,
            )

            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs[ "action" ] == "shadow"
            assert call_kwargs[ "ratification_state" ] == "not_required"
            assert call_kwargs[ "domain" ] == "swe"
            assert call_kwargs[ "category" ] == "testing"
            assert call_kwargs[ "confidence" ] == 0.85

    def test_log_shadow_default_reason( self, repo ):
        """log_shadow() uses default reason when none provided."""
        with patch.object( repo, "create", return_value=MagicMock() ) as mock_create:
            repo.log_shadow(
                notification_id = "notif-123",
                domain          = "swe",
                category        = "deployment",
                question        = "Deploy to staging?",
            )

            call_kwargs = mock_create.call_args.kwargs
            assert "shadow" in call_kwargs[ "reason" ].lower()


# =============================================================================
# log_decision() Tests
# =============================================================================

class TestLogDecision:
    """Tests for suggest/act/defer decision logging."""

    def test_log_decision_suggest_sets_pending( self, repo ):
        """log_decision() with requires_ratification=True sets state to pending."""
        with patch.object( repo, "create", return_value=MagicMock() ) as mock_create:
            repo.log_decision(
                notification_id      = "notif-456",
                domain               = "swe",
                category             = "architecture",
                question             = "Refactor auth module?",
                action               = "suggest",
                decision_value       = "approved",
                requires_ratification = True,
            )

            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs[ "ratification_state" ] == "pending"
            assert call_kwargs[ "action" ] == "suggest"

    def test_log_decision_act_sets_not_required( self, repo ):
        """log_decision() with requires_ratification=False sets not_required."""
        with patch.object( repo, "create", return_value=MagicMock() ) as mock_create:
            repo.log_decision(
                notification_id      = "notif-789",
                domain               = "swe",
                category             = "testing",
                question             = "Run unit tests?",
                action               = "act",
                decision_value       = "approved",
                requires_ratification = False,
            )

            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs[ "ratification_state" ] == "not_required"
            assert call_kwargs[ "action" ] == "act"

    def test_log_decision_preserves_all_fields( self, repo ):
        """log_decision() passes all parameters through to create()."""
        with patch.object( repo, "create", return_value=MagicMock() ) as mock_create:
            repo.log_decision(
                notification_id      = "notif-abc",
                domain               = "swe",
                category             = "deps",
                question             = "Add requests library?",
                action               = "suggest",
                decision_value       = "approved",
                sender_id            = "swe.lead@lupin.deepily.ai",
                confidence           = 0.92,
                trust_level          = 3,
                reason               = "Standard dependency",
                requires_ratification = True,
                metadata_json        = { "version": "2.31.0" },
            )

            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs[ "confidence" ] == 0.92
            assert call_kwargs[ "trust_level" ] == 3
            assert call_kwargs[ "reason" ] == "Standard dependency"
            assert call_kwargs[ "metadata_json" ] == { "version": "2.31.0" }


# =============================================================================
# Responder._persist_decision() Integration
# =============================================================================

class TestResponderPersistDecision:
    """Tests for DecisionResponder._persist_decision() non-fatal DB writes."""

    def test_persist_decision_shadow_calls_log_shadow( self ):
        """_persist_decision() with shadow action calls log_shadow()."""
        from cosa.agents.decision_proxy.responder import DecisionResponder

        responder = DecisionResponder( debug=True )
        responder.domain_strategy = MagicMock()
        responder.domain_strategy.name = "swe_engineering"

        mock_result = MagicMock()
        mock_result.action      = "shadow"
        mock_result.category    = "testing"
        mock_result.confidence  = 0.85
        mock_result.trust_level = 1
        mock_result.reason      = "L1 shadow"
        mock_result.value       = None

        mock_repo = MagicMock()
        mock_session = MagicMock()

        with patch( "cosa.rest.db.database.get_db" ) as mock_get_db:
            mock_get_db.return_value.__enter__ = MagicMock( return_value=mock_session )
            mock_get_db.return_value.__exit__  = MagicMock( return_value=False )

            with patch( "cosa.rest.db.repositories.proxy_decision_repository.ProxyDecisionRepository", return_value=mock_repo ):
                responder._persist_decision( "notif-123", mock_result, "Run tests?" )

            mock_repo.log_shadow.assert_called_once()

    def test_persist_decision_failure_is_non_fatal( self ):
        """_persist_decision() swallows exceptions without propagating."""
        from cosa.agents.decision_proxy.responder import DecisionResponder

        responder = DecisionResponder( debug=False )
        responder.domain_strategy = MagicMock()
        responder.domain_strategy.name = "swe_engineering"

        mock_result = MagicMock()
        mock_result.action = "shadow"

        with patch( "cosa.rest.db.database.get_db", side_effect=Exception( "DB down" ) ):
            # Should NOT raise
            responder._persist_decision( "notif-123", mock_result, "Question" )


# =============================================================================
# delete_pending() Tests
# =============================================================================

class TestDeletePending:
    """Tests for permanent deletion of pending decisions."""

    def test_delete_pending_success( self, repo, mock_session ):
        """delete_pending() deletes a pending decision and returns True."""
        mock_decision = MagicMock()
        mock_decision.ratification_state = "pending"

        with patch.object( repo, "get_by_id", return_value=mock_decision ):
            result = repo.delete_pending( "fake-uuid" )

        assert result is True
        mock_session.delete.assert_called_once_with( mock_decision )
        mock_session.flush.assert_called_once()

    def test_delete_pending_not_found( self, repo, mock_session ):
        """delete_pending() returns False when decision not found."""
        with patch.object( repo, "get_by_id", return_value=None ):
            result = repo.delete_pending( "nonexistent-uuid" )

        assert result is False
        mock_session.delete.assert_not_called()

    def test_delete_pending_rejects_approved( self, repo, mock_session ):
        """delete_pending() raises ValueError for approved decisions."""
        mock_decision = MagicMock()
        mock_decision.ratification_state = "approved"

        with patch.object( repo, "get_by_id", return_value=mock_decision ):
            with pytest.raises( ValueError, match="approved" ):
                repo.delete_pending( "fake-uuid" )

        mock_session.delete.assert_not_called()

    def test_delete_pending_rejects_rejected( self, repo, mock_session ):
        """delete_pending() raises ValueError for rejected decisions."""
        mock_decision = MagicMock()
        mock_decision.ratification_state = "rejected"

        with patch.object( repo, "get_by_id", return_value=mock_decision ):
            with pytest.raises( ValueError, match="rejected" ):
                repo.delete_pending( "fake-uuid" )

        mock_session.delete.assert_not_called()
