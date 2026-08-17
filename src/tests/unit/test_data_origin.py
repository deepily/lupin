#!/usr/bin/env python3
"""
Unit tests for data_origin provenance tracking.

Tests that data_origin round-trips through PostgreSQL (via the repository layer)
and that defaults are correct.

Session 268: Work Item 1 — data provenance tracking for proxy decisions.

TRIMMED 2026-08-17 by Pocholo (LanceDB total-removal sweep, Lane A, rows
5ff7b8f5 / 8098838f): TestDataOriginEmbeddings drove ProxyDecisionEmbeddings
through a real LanceDB store in a tmpdir, pinned to the lancedb backend by an
autouse fixture. That store and that backend are gone; the same behaviour is
covered against the repository in
src/cosa/tests/unit/agents/decision_proxy/test_proxy_decision_embeddings.py.
Deleted, not skipped — and the pin went with it.
"""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from cosa.rest.db.repositories.proxy_decision_repository import ProxyDecisionRepository



# =============================================================================
# Helpers
# =============================================================================

def _make_embedding( seed=42, dim=768 ):
    """Generate a deterministic normalized 768-dim embedding."""
    rng = np.random.RandomState( seed )
    vec = rng.randn( dim ).astype( np.float32 )
    vec = vec / np.linalg.norm( vec )
    return vec.tolist()


def _make_similar_embedding( base_embedding, noise_level=0.05, seed=99 ):
    """Create an embedding similar to base with small perturbation."""
    rng  = np.random.RandomState( seed )
    base = np.array( base_embedding, dtype=np.float32 )
    noise = rng.randn( len( base ) ).astype( np.float32 ) * noise_level
    vec   = base + noise
    vec   = vec / np.linalg.norm( vec )
    return vec.tolist()


# =============================================================================
# PostgreSQL Repository Tests (Mocked)
# =============================================================================

class TestDataOriginRepository:
    """Tests for data_origin pass-through in ProxyDecisionRepository."""

    @pytest.fixture
    def mock_session( self ):
        """Mock SQLAlchemy session."""
        return MagicMock()

    @pytest.fixture
    def repo( self, mock_session ):
        """ProxyDecisionRepository with mocked session."""
        return ProxyDecisionRepository( mock_session )

    def test_log_decision_default_origin_is_organic( self, repo ):
        """log_decision() defaults data_origin to 'organic' when not specified."""
        with patch.object( repo, "create", return_value=MagicMock() ) as mock_create:
            repo.log_decision(
                notification_id = "notif-origin-001",
                domain          = "swe",
                category        = "testing",
                question        = "Run the test suite?",
                action          = "suggest",
            )

            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs[ "data_origin" ] == "organic"

    def test_log_decision_passes_custom_origin( self, repo ):
        """log_decision() passes explicit data_origin to create()."""
        with patch.object( repo, "create", return_value=MagicMock() ) as mock_create:
            repo.log_decision(
                notification_id = "notif-origin-002",
                domain          = "swe",
                category        = "deployment",
                question        = "Deploy to prod?",
                action          = "suggest",
                data_origin     = "synthetic_seed",
            )

            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs[ "data_origin" ] == "synthetic_seed"

    def test_log_decision_synthetic_generated_origin( self, repo ):
        """log_decision() passes synthetic_generated origin correctly."""
        with patch.object( repo, "create", return_value=MagicMock() ) as mock_create:
            repo.log_decision(
                notification_id = "notif-origin-003",
                domain          = "swe",
                category        = "architecture",
                question        = "Refactor auth module?",
                action          = "suggest",
                data_origin     = "synthetic_generated",
            )

            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs[ "data_origin" ] == "synthetic_generated"

    def test_log_shadow_default_origin_is_organic( self, repo ):
        """log_shadow() defaults data_origin to 'organic' when not specified."""
        with patch.object( repo, "create", return_value=MagicMock() ) as mock_create:
            repo.log_shadow(
                notification_id = "notif-origin-004",
                domain          = "swe",
                category        = "testing",
                question        = "Run tests?",
            )

            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs[ "data_origin" ] == "organic"

    def test_log_shadow_passes_custom_origin( self, repo ):
        """log_shadow() passes explicit data_origin to create()."""
        with patch.object( repo, "create", return_value=MagicMock() ) as mock_create:
            repo.log_shadow(
                notification_id = "notif-origin-005",
                domain          = "swe",
                category        = "destructive",
                question        = "Delete temp files?",
                data_origin     = "synthetic_seed",
            )

            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs[ "data_origin" ] == "synthetic_seed"


class TestDataOriginOrmModel:
    """Tests for ProxyDecision ORM model data_origin field."""

    def test_proxy_decision_has_data_origin_attribute( self ):
        """ProxyDecision model class has data_origin column."""
        from cosa.rest.postgres_models import ProxyDecision
        assert hasattr( ProxyDecision, "data_origin" )

    def test_proxy_decision_data_origin_default( self ):
        """ProxyDecision model default for data_origin is 'organic'."""
        from cosa.rest.postgres_models import ProxyDecision

        # Check the column default via mapped_column
        column = ProxyDecision.__table__.columns[ "data_origin" ]
        assert column.default.arg == "organic"
        assert column.server_default.arg == "organic"

    def test_proxy_decision_data_origin_not_nullable( self ):
        """data_origin column is NOT NULL."""
        from cosa.rest.postgres_models import ProxyDecision

        column = ProxyDecision.__table__.columns[ "data_origin" ]
        assert column.nullable is False
