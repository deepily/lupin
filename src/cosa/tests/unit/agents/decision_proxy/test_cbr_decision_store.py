#!/usr/bin/env python3
"""
Unit tests for cosa.agents.decision_proxy.cbr_decision_store.

CBRDecisionStore runs a Retrieve→Reuse CBR pipeline: it delegates retrieval
to an injected embedding_store and computes a verdict via majority vote with
confidence = max_similarity * verdict_consistency. The embedding_store is
mocked at the boundary (no real vector search / I/O).
"""

from unittest.mock import MagicMock

from cosa.agents.decision_proxy.cbr_decision_store import CBRDecisionStore, CBRPrediction


def _store( find_similar_result, **kwargs ):
    es = MagicMock()
    es.find_similar.return_value = find_similar_result
    return CBRDecisionStore( es, **kwargs ), es


# ----------------------------------------------------------------------------
# CBRPrediction dataclass
# ----------------------------------------------------------------------------
def test_cbr_prediction_defaults():
    p = CBRPrediction( verdict="yes", confidence=0.5 )
    assert p.verdict == "yes"
    assert p.confidence == 0.5
    assert p.similar_cases == []
    assert p.case_count == 0


def test_cbr_prediction_full():
    cases = [ { "decision_value": "yes" } ]
    p = CBRPrediction( verdict="yes", confidence=0.9, similar_cases=cases, case_count=1 )
    assert p.similar_cases == cases
    assert p.case_count == 1


# ----------------------------------------------------------------------------
# __init__
# ----------------------------------------------------------------------------
def test_init_stores_params():
    es = MagicMock()
    store = CBRDecisionStore( es, top_k=3, confidence_threshold=0.5, debug=True )
    assert store.embedding_store is es
    assert store.top_k == 3
    assert store.confidence_threshold == 0.5
    assert store.debug is True


# ----------------------------------------------------------------------------
# predict — no cases
# ----------------------------------------------------------------------------
def test_predict_no_cases_returns_empty_prediction():
    store, es = _store( [] )
    pred = store.predict( "q?", "deploy", [ 0.1, 0.2 ] )
    assert pred.verdict is None
    assert pred.confidence == 0.0
    assert pred.similar_cases == []
    assert pred.case_count == 0
    es.find_similar.assert_called_once_with( [ 0.1, 0.2 ], category="deploy", limit=5, threshold=0.0 )


def test_predict_no_cases_debug_prints( capsys ):
    store, _ = _store( [], debug=True )
    store.predict( "q?", "deploy", [ 0.1 ] )
    assert "No similar cases" in capsys.readouterr().out


# ----------------------------------------------------------------------------
# predict — with cases
# ----------------------------------------------------------------------------
def test_predict_majority_vote_and_confidence():
    results = [
        ( 90.0, { "decision_value": "yes" } ),
        ( 80.0, { "decision_value": "yes" } ),
        ( 70.0, { "decision_value": "no" } ),
    ]
    store, _ = _store( results, top_k=3 )
    pred = store.predict( "q?", "deploy", [ 1.0 ] )
    assert pred.verdict == "yes"
    assert pred.case_count == 3
    # max_similarity = 90/100 = 0.9 ; consistency = 2/3 ; confidence = 0.6
    assert abs( pred.confidence - 0.6 ) < 1e-9
    assert pred.similar_cases == [ record for _, record in results ]


def test_predict_passes_top_k_as_limit():
    store, es = _store( [ ( 50.0, { "decision_value": "x" } ) ], top_k=7 )
    store.predict( "q?", "testing", [ 0.5 ] )
    es.find_similar.assert_called_once_with( [ 0.5 ], category="testing", limit=7, threshold=0.0 )


def test_predict_debug_prints_with_cases( capsys ):
    store, _ = _store( [ ( 88.0, { "decision_value": "go" } ) ], debug=True )
    store.predict( "q?", "deploy", [ 0.9 ] )
    assert "Prediction" in capsys.readouterr().out


def test_predict_missing_decision_value_defaults_to_empty():
    results = [ ( 60.0, {} ), ( 50.0, {} ) ]
    store, _ = _store( results )
    pred = store.predict( "q?", "deploy", [ 0.1 ] )
    assert pred.verdict == ""
    assert pred.case_count == 2
