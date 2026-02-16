#!/usr/bin/env python3
"""
Unit tests for the Decision Store (Phase 4d).

Tests for:
    - ProxyDecisionRepository (shadow logging, decision logging, pending, ratification, similar)
    - TrustStateRepository (get_or_create, update_after_ratification, trust levels)
    - Decision proxy router endpoints (GET pending, POST ratify, GET trust)
    - Migration SQL syntax validation

All tests use mocked database sessions — no live database required.
"""

import pytest
import uuid
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime, timezone, timedelta


# ===========================================================================
# ProxyDecision + TrustState ORM Model Tests
# ===========================================================================

class TestProxyDecisionModel:
    """Tests for ProxyDecision ORM model definition."""

    def test_proxy_decision_import( self ):
        """ProxyDecision can be imported from postgres_models."""
        from cosa.rest.postgres_models import ProxyDecision
        assert ProxyDecision is not None

    def test_proxy_decision_tablename( self ):
        """ProxyDecision maps to proxy_decisions table."""
        from cosa.rest.postgres_models import ProxyDecision
        assert ProxyDecision.__tablename__ == "proxy_decisions"

    def test_proxy_decision_has_required_columns( self ):
        """ProxyDecision has all required columns."""
        from cosa.rest.postgres_models import ProxyDecision
        required = [
            "id", "notification_id", "domain", "category", "question",
            "sender_id", "action", "decision_value", "confidence",
            "trust_level", "reason", "ratification_state", "ratified_by",
            "ratified_at", "ratification_feedback", "metadata_json", "created_at"
        ]
        for col in required:
            assert hasattr( ProxyDecision, col ), f"Missing column: {col}"

    def test_proxy_decision_repr( self ):
        """ProxyDecision repr includes key fields."""
        from cosa.rest.postgres_models import ProxyDecision
        decision = ProxyDecision(
            id       = uuid.uuid4(),
            domain   = "swe",
            category = "testing",
            action   = "shadow"
        )
        r = repr( decision )
        assert "swe" in r
        assert "testing" in r
        assert "shadow" in r

    def test_proxy_decision_has_indexes( self ):
        """ProxyDecision defines composite indexes."""
        from cosa.rest.postgres_models import ProxyDecision
        # Check __table_args__ has Index tuples
        assert hasattr( ProxyDecision, "__table_args__" )
        assert len( ProxyDecision.__table_args__ ) >= 5


class TestTrustStateModel:
    """Tests for TrustState ORM model definition."""

    def test_trust_state_import( self ):
        """TrustState can be imported from postgres_models."""
        from cosa.rest.postgres_models import TrustState
        assert TrustState is not None

    def test_trust_state_tablename( self ):
        """TrustState maps to trust_states table."""
        from cosa.rest.postgres_models import TrustState
        assert TrustState.__tablename__ == "trust_states"

    def test_trust_state_has_required_columns( self ):
        """TrustState has all required columns."""
        from cosa.rest.postgres_models import TrustState
        required = [
            "id", "user_email", "domain", "category", "trust_level",
            "total_decisions", "successful_decisions", "rejected_decisions",
            "circuit_breaker_state", "created_at", "updated_at"
        ]
        for col in required:
            assert hasattr( TrustState, col ), f"Missing column: {col}"

    def test_trust_state_repr( self ):
        """TrustState repr includes key fields."""
        from cosa.rest.postgres_models import TrustState
        state = TrustState(
            user_email = "test@test.com",
            domain     = "swe",
            category   = "testing",
            trust_level = 3
        )
        r = repr( state )
        assert "test@test.com" in r
        assert "swe" in r
        assert "testing" in r

    def test_trust_state_has_unique_index( self ):
        """TrustState has unique composite index on user_email+domain+category."""
        from cosa.rest.postgres_models import TrustState
        assert hasattr( TrustState, "__table_args__" )
        # Check that at least one index is unique
        has_unique = any(
            getattr( idx, "unique", False )
            for idx in TrustState.__table_args__
            if hasattr( idx, "unique" )
        )
        assert has_unique, "Missing unique composite index"


# ===========================================================================
# ProxyDecisionRepository Tests (Mocked Session)
# ===========================================================================

class TestProxyDecisionRepository:
    """Tests for ProxyDecisionRepository with mocked session."""

    def _make_repo( self ):
        """Create a repository with a mocked session."""
        from cosa.rest.db.repositories.proxy_decision_repository import ProxyDecisionRepository
        mock_session = MagicMock()
        return ProxyDecisionRepository( mock_session ), mock_session

    def test_init_sets_model( self ):
        """Repository is initialized with ProxyDecision model."""
        from cosa.rest.postgres_models import ProxyDecision
        repo, _ = self._make_repo()
        assert repo.model == ProxyDecision

    def test_log_shadow_calls_create( self ):
        """log_shadow creates a decision with action='shadow'."""
        repo, mock_session = self._make_repo()

        with patch.object( repo, "create" ) as mock_create:
            repo.log_shadow(
                notification_id = "abc123",
                domain          = "swe",
                category        = "testing",
                question        = "Run tests?"
            )

            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args[ 1 ]
            assert call_kwargs[ "action" ] == "shadow"
            assert call_kwargs[ "ratification_state" ] == "not_required"
            assert call_kwargs[ "domain" ] == "swe"

    def test_log_decision_with_ratification( self ):
        """log_decision with requires_ratification=True sets pending state."""
        repo, _ = self._make_repo()

        with patch.object( repo, "create" ) as mock_create:
            repo.log_decision(
                notification_id       = "abc123",
                domain                = "swe",
                category              = "deployment",
                question              = "Deploy to prod?",
                action                = "suggest",
                requires_ratification = True
            )

            call_kwargs = mock_create.call_args[ 1 ]
            assert call_kwargs[ "ratification_state" ] == "pending"
            assert call_kwargs[ "action" ] == "suggest"

    def test_log_decision_without_ratification( self ):
        """log_decision with requires_ratification=False sets not_required."""
        repo, _ = self._make_repo()

        with patch.object( repo, "create" ) as mock_create:
            repo.log_decision(
                notification_id       = "abc123",
                domain                = "swe",
                category              = "testing",
                question              = "Run unit tests?",
                action                = "act",
                requires_ratification = False
            )

            call_kwargs = mock_create.call_args[ 1 ]
            assert call_kwargs[ "ratification_state" ] == "not_required"

    def test_get_pending_filters_by_state( self ):
        """get_pending queries for ratification_state='pending'."""
        repo, mock_session = self._make_repo()

        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []

        result = repo.get_pending()
        assert result == []
        mock_session.query.assert_called_once()

    def test_get_pending_applies_domain_filter( self ):
        """get_pending applies domain filter when specified."""
        repo, mock_session = self._make_repo()

        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []

        repo.get_pending( domain="swe" )
        # Two filter calls: one for ratification_state, one for domain
        assert mock_query.filter.call_count == 2

    def test_ratify_approve( self ):
        """ratify with approved=True sets state to 'approved'."""
        repo, _ = self._make_repo()
        mock_decision = MagicMock()
        mock_decision.ratification_state = "pending"

        with patch.object( repo, "get_by_id", return_value=mock_decision ):
            result = repo.ratify(
                decision_id = uuid.uuid4(),
                approved    = True,
                ratified_by = "admin@test.com",
                feedback    = "Looks good"
            )

            assert result.ratification_state == "approved"
            assert result.ratified_by == "admin@test.com"

    def test_ratify_reject( self ):
        """ratify with approved=False sets state to 'rejected'."""
        repo, _ = self._make_repo()
        mock_decision = MagicMock()
        mock_decision.ratification_state = "pending"

        with patch.object( repo, "get_by_id", return_value=mock_decision ):
            result = repo.ratify(
                decision_id = uuid.uuid4(),
                approved    = False,
                ratified_by = "admin@test.com",
                feedback    = "Too risky"
            )

            assert result.ratification_state == "rejected"

    def test_ratify_not_found_returns_none( self ):
        """ratify returns None if decision not found."""
        repo, _ = self._make_repo()

        with patch.object( repo, "get_by_id", return_value=None ):
            result = repo.ratify(
                decision_id = uuid.uuid4(),
                approved    = True,
                ratified_by = "admin@test.com"
            )
            assert result is None

    def test_find_similar_extracts_keywords( self ):
        """find_similar filters by keywords longer than 3 chars."""
        repo, mock_session = self._make_repo()

        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []

        result = repo.find_similar(
            question = "Should I deploy this to production?",
            domain   = "swe",
            category = "deployment"
        )
        assert result == []

    def test_find_similar_returns_empty_for_short_words( self ):
        """find_similar returns empty list when all words are <= 3 chars."""
        repo, _ = self._make_repo()
        result = repo.find_similar(
            question = "is it ok?",
            domain   = "swe",
            category = "testing"
        )
        assert result == []

    def test_get_pending_summary( self ):
        """get_pending_summary returns structured summary dict."""
        repo, mock_session = self._make_repo()

        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = []

        summary = repo.get_pending_summary()
        assert "total_pending" in summary
        assert "by_category" in summary
        assert "by_trust_level" in summary
        assert "oldest_pending" in summary
        assert summary[ "total_pending" ] == 0


# ===========================================================================
# TrustStateRepository Tests (Mocked Session)
# ===========================================================================

class TestTrustStateRepository:
    """Tests for TrustStateRepository with mocked session."""

    def _make_repo( self ):
        """Create a repository with a mocked session."""
        from cosa.rest.db.repositories.proxy_decision_repository import TrustStateRepository
        mock_session = MagicMock()
        return TrustStateRepository( mock_session ), mock_session

    def test_init_sets_model( self ):
        """Repository is initialized with TrustState model."""
        from cosa.rest.postgres_models import TrustState
        repo, _ = self._make_repo()
        assert repo.model == TrustState

    def test_get_by_user_domain_category( self ):
        """get_by_user_domain_category queries the composite key."""
        repo, mock_session = self._make_repo()

        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None

        result = repo.get_by_user_domain_category(
            user_email = "test@test.com",
            domain     = "swe",
            category   = "testing"
        )
        assert result is None
        mock_session.query.assert_called_once()

    def test_get_or_create_returns_existing( self ):
        """get_or_create returns existing state if found."""
        repo, _ = self._make_repo()
        mock_state = MagicMock()

        with patch.object( repo, "get_by_user_domain_category", return_value=mock_state ):
            result = repo.get_or_create( "test@test.com", "swe", "testing" )
            assert result is mock_state

    def test_get_or_create_creates_new( self ):
        """get_or_create creates new state when not found."""
        repo, _ = self._make_repo()
        mock_new_state = MagicMock()

        with patch.object( repo, "get_by_user_domain_category", return_value=None ), \
             patch.object( repo, "create", return_value=mock_new_state ) as mock_create:

            result = repo.get_or_create( "test@test.com", "swe", "testing" )
            assert result is mock_new_state
            call_kwargs = mock_create.call_args[ 1 ]
            assert call_kwargs[ "trust_level" ] == 1
            assert call_kwargs[ "total_decisions" ] == 0

    def test_update_after_ratification_approved( self ):
        """update_after_ratification increments success count for approved."""
        repo, mock_session = self._make_repo()
        mock_state = MagicMock()
        mock_state.total_decisions = 5
        mock_state.successful_decisions = 4
        mock_state.rejected_decisions = 1

        with patch.object( repo, "get_or_create", return_value=mock_state ):
            result = repo.update_after_ratification(
                user_email = "test@test.com",
                domain     = "swe",
                category   = "testing",
                approved   = True
            )

            assert result.total_decisions == 6
            assert result.successful_decisions == 5
            assert result.rejected_decisions == 1

    def test_update_after_ratification_rejected( self ):
        """update_after_ratification increments rejected count for rejection."""
        repo, mock_session = self._make_repo()
        mock_state = MagicMock()
        mock_state.total_decisions = 5
        mock_state.successful_decisions = 4
        mock_state.rejected_decisions = 1

        with patch.object( repo, "get_or_create", return_value=mock_state ):
            result = repo.update_after_ratification(
                user_email = "test@test.com",
                domain     = "swe",
                category   = "testing",
                approved   = False
            )

            assert result.total_decisions == 6
            assert result.rejected_decisions == 2

    def test_get_all_for_user( self ):
        """get_all_for_user queries by user_email."""
        repo, mock_session = self._make_repo()

        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.all.return_value = []

        result = repo.get_all_for_user( "test@test.com" )
        assert result == []

    def test_get_all_for_user_with_domain_filter( self ):
        """get_all_for_user applies domain filter when specified."""
        repo, mock_session = self._make_repo()

        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.all.return_value = []

        repo.get_all_for_user( "test@test.com", domain="swe" )
        # Two filter calls: user_email + domain
        assert mock_query.filter.call_count == 2

    def test_update_trust_level( self ):
        """update_trust_level updates the trust_level field."""
        repo, mock_session = self._make_repo()
        mock_state = MagicMock()
        mock_state.trust_level = 1

        with patch.object( repo, "get_or_create", return_value=mock_state ):
            result = repo.update_trust_level( "test@test.com", "swe", "testing", 3 )
            assert result.trust_level == 3

    def test_update_circuit_breaker_state( self ):
        """update_circuit_breaker_state updates the JSONB field."""
        repo, mock_session = self._make_repo()
        mock_state = MagicMock()
        mock_state.circuit_breaker_state = None

        cb_state = { "tripped": True, "cooldown_remaining": 300 }
        with patch.object( repo, "get_or_create", return_value=mock_state ):
            result = repo.update_circuit_breaker_state( "test@test.com", "swe", "testing", cb_state )
            assert result.circuit_breaker_state == cb_state


# ===========================================================================
# Repository Package Export Tests
# ===========================================================================

class TestRepositoryExports:
    """Tests for repository package exports."""

    def test_proxy_decision_repository_export( self ):
        """ProxyDecisionRepository is exported from repositories package."""
        from cosa.rest.db.repositories import ProxyDecisionRepository
        assert ProxyDecisionRepository is not None

    def test_trust_state_repository_export( self ):
        """TrustStateRepository is exported from repositories package."""
        from cosa.rest.db.repositories import TrustStateRepository
        assert TrustStateRepository is not None


# ===========================================================================
# Router Import Tests
# ===========================================================================

class TestDecisionProxyRouter:
    """Tests for decision proxy router module imports and structure."""

    def test_router_import( self ):
        """Decision proxy router module can be imported."""
        from cosa.rest.routers import decision_proxy
        assert decision_proxy is not None

    def test_router_has_router_object( self ):
        """Router module exports an APIRouter instance."""
        from cosa.rest.routers.decision_proxy import router
        from fastapi import APIRouter
        assert isinstance( router, APIRouter )

    def test_router_prefix( self ):
        """Router has correct prefix."""
        from cosa.rest.routers.decision_proxy import router
        assert router.prefix == "/api/proxy"

    def test_router_has_pending_endpoint( self ):
        """Router has GET /pending/{user_email} endpoint."""
        from cosa.rest.routers.decision_proxy import router
        paths = [ route.path for route in router.routes ]
        assert "/api/proxy/pending/{user_email}" in paths

    def test_router_has_ratify_endpoint( self ):
        """Router has POST /ratify/{decision_id} endpoint."""
        from cosa.rest.routers.decision_proxy import router
        paths = [ route.path for route in router.routes ]
        assert "/api/proxy/ratify/{decision_id}" in paths

    def test_router_has_trust_endpoint( self ):
        """Router has GET /trust/{user_email} endpoint."""
        from cosa.rest.routers.decision_proxy import router
        paths = [ route.path for route in router.routes ]
        assert "/api/proxy/trust/{user_email}" in paths

    def test_router_has_decisions_endpoint( self ):
        """Router has GET /decisions/{domain}/{category} endpoint."""
        from cosa.rest.routers.decision_proxy import router
        paths = [ route.path for route in router.routes ]
        assert "/api/proxy/decisions/{domain}/{category}" in paths


# ===========================================================================
# Migration SQL Tests
# ===========================================================================

class TestMigrationSQL:
    """Tests for the decision proxy migration SQL file."""

    def test_migration_file_exists( self ):
        """Migration SQL file exists at expected path."""
        import os
        import cosa.utils.util as cu
        path = cu.get_project_root() + "/src/scripts/sql/2026.02.14-decision-proxy-schema.sql"
        assert os.path.exists( path ), f"Migration file not found: {path}"

    def test_migration_creates_proxy_decisions_table( self ):
        """Migration SQL contains CREATE TABLE proxy_decisions."""
        import cosa.utils.util as cu
        path = cu.get_project_root() + "/src/scripts/sql/2026.02.14-decision-proxy-schema.sql"
        with open( path, "r" ) as f:
            sql = f.read()
        assert "CREATE TABLE IF NOT EXISTS proxy_decisions" in sql

    def test_migration_creates_trust_states_table( self ):
        """Migration SQL contains CREATE TABLE trust_states."""
        import cosa.utils.util as cu
        path = cu.get_project_root() + "/src/scripts/sql/2026.02.14-decision-proxy-schema.sql"
        with open( path, "r" ) as f:
            sql = f.read()
        assert "CREATE TABLE IF NOT EXISTS trust_states" in sql

    def test_migration_creates_unique_index( self ):
        """Migration SQL creates unique composite index on trust_states."""
        import cosa.utils.util as cu
        path = cu.get_project_root() + "/src/scripts/sql/2026.02.14-decision-proxy-schema.sql"
        with open( path, "r" ) as f:
            sql = f.read()
        assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_trust_states_user_domain_category" in sql

    def test_migration_is_additive_only( self ):
        """Migration SQL does not contain ALTER TABLE (additive only)."""
        import cosa.utils.util as cu
        path = cu.get_project_root() + "/src/scripts/sql/2026.02.14-decision-proxy-schema.sql"
        with open( path, "r" ) as f:
            sql = f.read()
        assert "ALTER TABLE" not in sql


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
