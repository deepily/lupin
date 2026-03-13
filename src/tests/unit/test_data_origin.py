#!/usr/bin/env python3
"""
Unit tests for data_origin provenance tracking.

Tests that data_origin round-trips through PostgreSQL (via repository layer)
and LanceDB (via ProxyDecisionEmbeddings), that defaults are correct, and
that find_similar() can filter by origin.

Session 268: Work Item 1 — data provenance tracking for proxy decisions.
"""

import tempfile
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from cosa.agents.decision_proxy.proxy_decision_embeddings import ProxyDecisionEmbeddings
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


# =============================================================================
# LanceDB Embeddings Tests (Real LanceDB)
# =============================================================================

class TestDataOriginEmbeddings:
    """Tests for data_origin in ProxyDecisionEmbeddings LanceDB store."""

    def test_add_decision_default_origin_is_organic( self ):
        """add_decision() defaults data_origin to 'organic'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ProxyDecisionEmbeddings( db_path=tmpdir, table_name="test_origin_default", debug=True )

            embedding = _make_embedding( seed=100 )
            store.add_decision(
                id                  = "origin-default-001",
                question            = "Should I run the tests?",
                category            = "testing",
                decision_value      = "approved",
                ratification_state  = "ratified",
                question_embedding  = embedding,
                created_at          = "2026-02-25T10:00:00Z",
            )

            results = store.find_similar( embedding, threshold=0.50 )
            assert len( results ) >= 1
            _, record = results[ 0 ]
            assert record[ "data_origin" ] == "organic"

    def test_add_decision_synthetic_seed_round_trip( self ):
        """data_origin='synthetic_seed' round-trips through LanceDB."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ProxyDecisionEmbeddings( db_path=tmpdir, table_name="test_origin_seed", debug=True )

            embedding = _make_embedding( seed=101 )
            store.add_decision(
                id                  = "origin-seed-001",
                question            = "Deploy hotfix to prod?",
                category            = "deployment",
                decision_value      = "requires_review",
                ratification_state  = "pending",
                question_embedding  = embedding,
                created_at          = "2026-02-25T10:00:00Z",
                data_origin         = "synthetic_seed",
            )

            results = store.find_similar( embedding, threshold=0.50 )
            assert len( results ) >= 1
            _, record = results[ 0 ]
            assert record[ "data_origin" ] == "synthetic_seed"

    def test_add_decision_synthetic_generated_round_trip( self ):
        """data_origin='synthetic_generated' round-trips through LanceDB."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ProxyDecisionEmbeddings( db_path=tmpdir, table_name="test_origin_gen", debug=True )

            embedding = _make_embedding( seed=102 )
            store.add_decision(
                id                  = "origin-gen-001",
                question            = "Refactor auth module?",
                category            = "architecture",
                decision_value      = "requires_review",
                ratification_state  = "pending",
                question_embedding  = embedding,
                created_at          = "2026-02-25T10:00:00Z",
                data_origin         = "synthetic_generated",
            )

            results = store.find_similar( embedding, threshold=0.50 )
            assert len( results ) >= 1
            _, record = results[ 0 ]
            assert record[ "data_origin" ] == "synthetic_generated"

    def test_find_similar_filter_by_origin_includes( self ):
        """find_similar() with data_origin filter returns only matching records."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ProxyDecisionEmbeddings( db_path=tmpdir, table_name="test_origin_filter", debug=True )

            base_embedding = _make_embedding( seed=200 )

            # Add organic decision
            store.add_decision(
                id="filter-organic-001", question="Organic test question",
                category="testing", decision_value="approved",
                ratification_state="ratified", question_embedding=base_embedding,
                created_at="2026-02-25T10:00:00Z", data_origin="organic",
            )

            # Add synthetic_seed decision (similar embedding)
            seed_embedding = _make_similar_embedding( base_embedding, noise_level=0.02, seed=201 )
            store.add_decision(
                id="filter-seed-001", question="Synthetic seed test question",
                category="testing", decision_value="approved",
                ratification_state="pending", question_embedding=seed_embedding,
                created_at="2026-02-25T10:01:00Z", data_origin="synthetic_seed",
            )

            # Filter for organic only
            organic_results = store.find_similar(
                base_embedding, threshold=0.0, data_origin="organic"
            )
            assert len( organic_results ) >= 1
            for _, record in organic_results:
                assert record[ "data_origin" ] == "organic"

            # Filter for synthetic_seed only
            seed_results = store.find_similar(
                base_embedding, threshold=0.0, data_origin="synthetic_seed"
            )
            assert len( seed_results ) >= 1
            for _, record in seed_results:
                assert record[ "data_origin" ] == "synthetic_seed"

    def test_find_similar_no_filter_returns_all_origins( self ):
        """find_similar() without data_origin filter returns records of all origins."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ProxyDecisionEmbeddings( db_path=tmpdir, table_name="test_origin_all", debug=True )

            base_embedding = _make_embedding( seed=300 )

            # Add one organic, one synthetic_seed
            store.add_decision(
                id="all-organic-001", question="Organic question",
                category="testing", decision_value="approved",
                ratification_state="ratified", question_embedding=base_embedding,
                created_at="2026-02-25T10:00:00Z", data_origin="organic",
            )

            similar_emb = _make_similar_embedding( base_embedding, noise_level=0.02, seed=301 )
            store.add_decision(
                id="all-seed-001", question="Synthetic seed question",
                category="testing", decision_value="approved",
                ratification_state="pending", question_embedding=similar_emb,
                created_at="2026-02-25T10:01:00Z", data_origin="synthetic_seed",
            )

            # No origin filter — should get both
            all_results = store.find_similar( base_embedding, threshold=0.0 )
            origins = { record[ "data_origin" ] for _, record in all_results }
            assert "organic" in origins
            assert "synthetic_seed" in origins

    def test_find_similar_combined_category_and_origin_filter( self ):
        """find_similar() can filter by both category AND data_origin simultaneously."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ProxyDecisionEmbeddings( db_path=tmpdir, table_name="test_combined_filter", debug=True )

            base_embedding = _make_embedding( seed=400 )

            # Organic testing decision
            store.add_decision(
                id="combo-001", question="Run unit tests?",
                category="testing", decision_value="approved",
                ratification_state="ratified", question_embedding=base_embedding,
                created_at="2026-02-25T10:00:00Z", data_origin="organic",
            )

            # Synthetic deployment decision (similar embedding, different category)
            similar_emb = _make_similar_embedding( base_embedding, noise_level=0.02, seed=401 )
            store.add_decision(
                id="combo-002", question="Deploy to staging?",
                category="deployment", decision_value="requires_review",
                ratification_state="pending", question_embedding=similar_emb,
                created_at="2026-02-25T10:01:00Z", data_origin="synthetic_seed",
            )

            # Synthetic testing decision
            similar_emb2 = _make_similar_embedding( base_embedding, noise_level=0.03, seed=402 )
            store.add_decision(
                id="combo-003", question="Run integration tests?",
                category="testing", decision_value="approved",
                ratification_state="pending", question_embedding=similar_emb2,
                created_at="2026-02-25T10:02:00Z", data_origin="synthetic_seed",
            )

            # Filter: category=testing AND data_origin=organic → only combo-001
            results = store.find_similar(
                base_embedding, category="testing", data_origin="organic", threshold=0.0
            )
            assert len( results ) >= 1
            ids = { record[ "id" ] for _, record in results }
            assert "combo-001" in ids
            assert "combo-002" not in ids  # wrong category
            assert "combo-003" not in ids  # wrong origin


# =============================================================================
# ORM Model Tests
# =============================================================================

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
