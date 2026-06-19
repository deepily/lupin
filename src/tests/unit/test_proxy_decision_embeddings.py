#!/usr/bin/env python3
"""
Unit tests for ProxyDecisionEmbeddings LanceDB store.

Tests LanceDB round-trip, similarity search ordering, empty table behavior,
and error resilience. Uses tempdir for isolated LanceDB instances.
"""

import tempfile
import numpy as np
import pytest

from cosa.agents.decision_proxy.proxy_decision_embeddings import ProxyDecisionEmbeddings


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


def _make_unnormalized_embedding( seed=42, dim=768, scale=3.0 ):
    """Deterministic NON-unit-norm embedding ( ||vec|| == scale ).

    Exercises the dot-metric over-100% path: with a scale-3 vector the self
    dot-product is ~9, so _distance = 1 - 9 = -8 and ( 1 - distance ) * 100 = 900
    BEFORE clamping. This is the shape of vector that produced the '22123%'
    confidence bug.
    """
    rng = np.random.RandomState( seed )
    vec = rng.randn( dim ).astype( np.float32 )
    vec = ( vec / np.linalg.norm( vec ) ) * scale
    return vec.tolist()


class TestProxyDecisionEmbeddings:
    """Tests for the ProxyDecisionEmbeddings LanceDB store."""

    def test_add_and_retrieve_round_trip( self ):
        """Write a record, search with same embedding, get it back."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ProxyDecisionEmbeddings( db_path=tmpdir, table_name="test_decisions", debug=True )

            embedding = _make_embedding( seed=1 )
            store.add_decision(
                id                  = "test-001",
                question            = "Should I run the tests?",
                category            = "testing",
                decision_value      = "approved",
                ratification_state  = "ratified",
                question_embedding  = embedding,
                created_at          = "2026-02-24T10:00:00Z",
            )

            results = store.find_similar( embedding, threshold=0.50 )

            assert len( results ) >= 1
            similarity, record = results[ 0 ]
            assert similarity > 90.0  # Same vector should be near 100%
            assert record[ "id" ] == "test-001"
            assert record[ "question" ] == "Should I run the tests?"
            assert record[ "category" ] == "testing"
            assert record[ "decision_value" ] == "approved"
            assert record[ "ratification_state" ] == "ratified"

    def test_embedding_dimension_preserved( self ):
        """Stored embedding preserves 768 dimensions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ProxyDecisionEmbeddings( db_path=tmpdir, table_name="test_dims", debug=True )

            embedding = _make_embedding( seed=2 )
            assert len( embedding ) == 768

            store.add_decision(
                id                  = "dim-001",
                question            = "Dimension test",
                category            = "general",
                decision_value      = "approved",
                ratification_state  = "pending",
                question_embedding  = embedding,
                created_at          = "2026-02-24T10:00:00Z",
            )

            results = store.find_similar( embedding, threshold=0.50 )
            assert len( results ) >= 1

            _, record = results[ 0 ]
            stored_embedding = record[ "question_embedding" ]
            assert len( stored_embedding ) == 768

    def test_find_similar_returns_sorted_by_descending_similarity( self ):
        """Results are sorted with most similar first."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ProxyDecisionEmbeddings( db_path=tmpdir, table_name="test_sort", debug=True )

            base_embedding = _make_embedding( seed=10 )

            # Add close match
            close = _make_similar_embedding( base_embedding, noise_level=0.05, seed=20 )
            store.add_decision(
                id="close-001", question="Close match", category="testing",
                decision_value="approved", ratification_state="ratified",
                question_embedding=close, created_at="2026-02-24T10:00:00Z",
            )

            # Add distant match
            distant = _make_similar_embedding( base_embedding, noise_level=0.50, seed=30 )
            store.add_decision(
                id="distant-001", question="Distant match", category="testing",
                decision_value="approved", ratification_state="ratified",
                question_embedding=distant, created_at="2026-02-24T10:01:00Z",
            )

            results = store.find_similar( base_embedding, threshold=0.0 )

            assert len( results ) >= 2
            # First result should be more similar than second
            assert results[ 0 ][ 0 ] >= results[ 1 ][ 0 ]

    def test_similarity_pct_clamped_to_0_100_for_non_unit_vectors( self ):
        """
        Regression ('22123%' confidence bug): the dot metric only yields a value in
        [-1, 1] for UNIT-normalized vectors. With a non-unit vector the self
        dot-product exceeds 1, so ( 1 - _distance ) * 100 blows past 100 — and that
        unclamped percentage propagated to confidence ( similarity_pct / 100 → 2.2,
        ×100 in the UI → 22123% ). find_similar MUST clamp similarity_pct to [0, 100].
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ProxyDecisionEmbeddings( db_path=tmpdir, table_name="test_clamp", debug=True )

            big = _make_unnormalized_embedding( seed=5, scale=3.0 )  # ||big|| = 3 → self-dot ≈ 9
            store.add_decision(
                id="clamp-001", question="non-unit vector", category="testing",
                decision_value="approved", ratification_state="ratified",
                question_embedding=big, created_at="2026-02-24T10:00:00Z",
            )

            results = store.find_similar( big, threshold=0.0 )

            assert len( results ) >= 1
            for similarity, _ in results:
                assert 0.0 <= similarity <= 100.0, f"similarity_pct escaped [0,100]: {similarity}"

    def test_exists_true_for_present_false_for_absent( self ):
        """exists(id) gates the idempotent hint-vote upsert (insert vs update path)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ProxyDecisionEmbeddings( db_path=tmpdir, table_name="test_exists", debug=True )

            assert store.exists( "missing-id" ) is False     # absent before any insert

            store.add_decision(
                id="exists-001", question="present?", category="testing",
                decision_value="approved", ratification_state="approved",
                question_embedding=_make_embedding( seed=3 ), created_at="2026-02-24T10:00:00Z",
            )

            assert store.exists( "exists-001" ) is True       # present after insert
            assert store.exists( "still-missing" ) is False   # other ids stay absent

    def test_empty_table_returns_empty_list( self ):
        """Searching an empty table returns an empty list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ProxyDecisionEmbeddings( db_path=tmpdir, table_name="test_empty", debug=True )

            embedding = _make_embedding( seed=3 )
            results   = store.find_similar( embedding, threshold=0.50 )

            assert results == []

    def test_category_filter( self ):
        """Category filter restricts results to matching category."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ProxyDecisionEmbeddings( db_path=tmpdir, table_name="test_filter", debug=True )

            embedding = _make_embedding( seed=4 )

            store.add_decision(
                id="cat-001", question="Testing question", category="testing",
                decision_value="approved", ratification_state="ratified",
                question_embedding=embedding, created_at="2026-02-24T10:00:00Z",
            )

            similar = _make_similar_embedding( embedding, noise_level=0.05, seed=40 )
            store.add_decision(
                id="cat-002", question="Deployment question", category="deployment",
                decision_value="requires_review", ratification_state="pending",
                question_embedding=similar, created_at="2026-02-24T10:01:00Z",
            )

            # Search with category filter
            results = store.find_similar( embedding, category="testing", threshold=0.0 )

            categories = [ r[ 1 ][ "category" ] for r in results ]
            assert all( c == "testing" for c in categories )

    def test_threshold_filters_low_similarity( self ):
        """Results below threshold are excluded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ProxyDecisionEmbeddings( db_path=tmpdir, table_name="test_threshold", debug=True )

            # Add a record with one embedding
            embedding_a = _make_embedding( seed=5 )
            store.add_decision(
                id="thresh-001", question="Some question", category="general",
                decision_value="approved", ratification_state="ratified",
                question_embedding=embedding_a, created_at="2026-02-24T10:00:00Z",
            )

            # Search with a completely different embedding (orthogonal)
            embedding_b = _make_embedding( seed=999 )

            # High threshold should filter out poor matches
            results = store.find_similar( embedding_b, threshold=0.99 )
            assert len( results ) == 0

    def test_add_decision_failure_does_not_raise( self ):
        """add_decision with bad data doesn't propagate exceptions."""
        store = ProxyDecisionEmbeddings(
            db_path="/nonexistent/path/that/should/not/exist",
            table_name="test_error",
            debug=True,
        )

        # Should not raise
        store.add_decision(
            id="err-001", question="Test", category="general",
            decision_value="approved", ratification_state="pending",
            question_embedding=_make_embedding( seed=6 ),
            created_at="2026-02-24T10:00:00Z",
        )

    def test_exists_failure_returns_false( self ):
        """exists() on a bad store (no table) fails soft to False (never raises)."""
        store = ProxyDecisionEmbeddings(
            db_path="/nonexistent/path/that/should/not/exist",
            table_name="test_exists_err",
            debug=True,
        )
        assert store.exists( "anything" ) is False

    def test_exists_handles_search_exception( self ):
        """If the underlying search raises (table present), exists() swallows it → False."""
        from unittest.mock import MagicMock
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ProxyDecisionEmbeddings( db_path=tmpdir, table_name="test_exists_exc", debug=True )
            store._ensure_table = MagicMock( return_value=True )
            broken = MagicMock()
            broken.search.side_effect = RuntimeError( "boom" )
            store._table = broken
            assert store.exists( "x" ) is False

    def test_find_similar_failure_returns_empty( self ):
        """find_similar with bad store returns empty list."""
        store = ProxyDecisionEmbeddings(
            db_path="/nonexistent/path/that/should/not/exist",
            table_name="test_error",
            debug=True,
        )

        results = store.find_similar( _make_embedding( seed=7 ), threshold=0.50 )
        assert results == []

    def test_update_ratification_state( self ):
        """update_ratification_state modifies existing record."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ProxyDecisionEmbeddings( db_path=tmpdir, table_name="test_update", debug=True )

            embedding = _make_embedding( seed=8 )
            store.add_decision(
                id="upd-001", question="Update test", category="general",
                decision_value="approved", ratification_state="pending",
                question_embedding=embedding, created_at="2026-02-24T10:00:00Z",
            )

            store.update_ratification_state( "upd-001", "ratified" )

            results = store.find_similar( embedding, threshold=0.50 )
            assert len( results ) >= 1

            _, record = results[ 0 ]
            assert record[ "ratification_state" ] == "ratified"

    def test_multiple_records_with_limit( self ):
        """Limit parameter restricts number of results."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ProxyDecisionEmbeddings( db_path=tmpdir, table_name="test_limit", debug=True )

            base = _make_embedding( seed=9 )

            for i in range( 10 ):
                emb = _make_similar_embedding( base, noise_level=0.02 * ( i + 1 ), seed=100 + i )
                store.add_decision(
                    id=f"lim-{i:03d}", question=f"Question {i}", category="testing",
                    decision_value="approved", ratification_state="ratified",
                    question_embedding=emb, created_at=f"2026-02-24T10:{i:02d}:00Z",
                )

            results = store.find_similar( base, limit=3, threshold=0.0 )
            assert len( results ) <= 3
