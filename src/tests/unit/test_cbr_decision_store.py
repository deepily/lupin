#!/usr/bin/env python3
"""
Unit tests for CBRDecisionStore.

Uses mock embedding store to test CBR prediction logic:
majority vote, confidence scoring, empty store, mixed cases.
"""

import pytest
from unittest.mock import MagicMock

from cosa.agents.decision_proxy.cbr_decision_store import CBRDecisionStore, CBRPrediction


def _mock_store( results ):
    """
    Create a mock ProxyDecisionEmbeddings that returns given results.

    Args:
        results: list of ( similarity_pct, record_dict ) tuples
    """
    store = MagicMock()
    store.find_similar = MagicMock( return_value=results )
    return store


class TestCBRDecisionStore:
    """Tests for CBRDecisionStore prediction logic."""

    def test_empty_store_returns_none_verdict( self ):
        """No similar cases → verdict=None, confidence=0.0."""
        store = _mock_store( [] )
        cbr   = CBRDecisionStore( embedding_store=store, debug=True )

        prediction = cbr.predict( "test question", "testing", [ 0.0 ] * 768 )

        assert prediction.verdict is None
        assert prediction.confidence == 0.0
        assert prediction.case_count == 0
        assert prediction.similar_cases == []

    def test_five_consistent_cases( self ):
        """5 cases all with same verdict → high confidence."""
        results = [
            ( 95.0, { "decision_value": "approved", "id": f"c{i}" } )
            for i in range( 5 )
        ]
        store = _mock_store( results )
        cbr   = CBRDecisionStore( embedding_store=store, debug=True )

        prediction = cbr.predict( "test question", "testing", [ 0.0 ] * 768 )

        assert prediction.verdict == "approved"
        assert prediction.case_count == 5
        # confidence = max_similarity(0.95) * consistency(1.0) = 0.95
        assert abs( prediction.confidence - 0.95 ) < 0.01

    def test_mixed_cases_reduced_confidence( self ):
        """3 approved + 2 requires_review → reduced confidence."""
        results = [
            ( 90.0, { "decision_value": "approved" } ),
            ( 88.0, { "decision_value": "approved" } ),
            ( 85.0, { "decision_value": "approved" } ),
            ( 82.0, { "decision_value": "requires_review" } ),
            ( 80.0, { "decision_value": "requires_review" } ),
        ]
        store = _mock_store( results )
        cbr   = CBRDecisionStore( embedding_store=store, debug=True )

        prediction = cbr.predict( "test question", "testing", [ 0.0 ] * 768 )

        assert prediction.verdict == "approved"
        assert prediction.case_count == 5
        # confidence = max_similarity(0.90) * consistency(3/5=0.60) = 0.54
        expected = 0.90 * 0.60
        assert abs( prediction.confidence - expected ) < 0.01

    def test_single_case( self ):
        """Single case → confidence = max_similarity * 1.0."""
        results = [
            ( 78.0, { "decision_value": "approved" } ),
        ]
        store = _mock_store( results )
        cbr   = CBRDecisionStore( embedding_store=store, debug=True )

        prediction = cbr.predict( "test question", "testing", [ 0.0 ] * 768 )

        assert prediction.verdict == "approved"
        assert prediction.case_count == 1
        # confidence = max_similarity(0.78) * consistency(1.0) = 0.78
        assert abs( prediction.confidence - 0.78 ) < 0.01

    def test_tie_picks_first_most_common( self ):
        """Equal split picks whichever Counter.most_common returns first."""
        results = [
            ( 90.0, { "decision_value": "approved" } ),
            ( 85.0, { "decision_value": "requires_review" } ),
        ]
        store = _mock_store( results )
        cbr   = CBRDecisionStore( embedding_store=store, debug=True )

        prediction = cbr.predict( "test question", "testing", [ 0.0 ] * 768 )

        # Either verdict is acceptable in a tie; confidence = 0.90 * 0.50 = 0.45
        assert prediction.verdict in ( "approved", "requires_review" )
        assert prediction.case_count == 2
        assert abs( prediction.confidence - 0.45 ) < 0.01

    def test_prediction_includes_similar_cases( self ):
        """Prediction carries the similar_cases list."""
        case_data = { "decision_value": "approved", "id": "abc-123", "question": "test" }
        results   = [ ( 92.0, case_data ) ]
        store     = _mock_store( results )
        cbr       = CBRDecisionStore( embedding_store=store, debug=True )

        prediction = cbr.predict( "test question", "testing", [ 0.0 ] * 768 )

        assert len( prediction.similar_cases ) == 1
        assert prediction.similar_cases[ 0 ][ "id" ] == "abc-123"

    def test_cbr_prediction_dataclass_defaults( self ):
        """CBRPrediction default values are sensible."""
        p = CBRPrediction( verdict=None, confidence=0.0 )
        assert p.similar_cases == []
        assert p.case_count == 0

    def test_top_k_passed_to_store( self ):
        """CBR passes top_k as limit to embedding store."""
        store = _mock_store( [] )
        cbr   = CBRDecisionStore( embedding_store=store, top_k=10, debug=True )

        cbr.predict( "test question", "testing", [ 0.0 ] * 768 )

        store.find_similar.assert_called_once()
        call_kwargs = store.find_similar.call_args
        assert call_kwargs.kwargs[ "limit" ] == 10
