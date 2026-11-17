#!/usr/bin/env python3
"""
Unit tests: blank shadow / deferred rows cast no vote in the CBR and yes/no readers.

A blank row used to cast a "" verdict in CBRDecisionStore.predict and a
"no" vote in PredictionEngine._predict_yes_no. All mocked, no DB or server, so
:7999-eligible.
"""

from unittest.mock import MagicMock

import pytest

from cosa.agents.decision_proxy.cbr_decision_store import CBRDecisionStore, is_blank_case
from cosa.agents.prediction_engine.prediction_engine import PredictionEngine


def _cbr( results ):
    """CBRDecisionStore whose embedding store returns `results`."""
    store = MagicMock()
    store.find_similar.return_value = results
    return CBRDecisionStore( embedding_store=store )


def _engine( cases ):
    """PredictionEngine whose embedding store returns `cases`."""
    engine = PredictionEngine( debug=False )
    engine._embedding_store = MagicMock()
    engine._embedding_store.find_similar.return_value = cases
    return engine


class TestIsBlankCase:
    @pytest.mark.parametrize( "record, expected", [
        ( { "ratification_state": "shadow", "decision_value": "yes" }, True  ),
        ( { "ratification_state": " Shadow ", "decision_value": "yes" }, True ),
        ( { "decision_value": "" },                                      True  ),
        ( { "decision_value": "   " },                                   True  ),
        ( { "decision_value": None },                                    True  ),
        ( {},                                                            True  ),
        ( { "ratification_state": None, "decision_value": "yes" },       False ),
        ( { "ratification_state": "approved", "decision_value": "no" },  False ),
    ] )
    def test_blank_predicate( self, record, expected ):
        assert is_blank_case( record ) is expected


class TestCBRSkipsBlankRows:
    def test_blank_row_casts_no_verdict( self ):
        """Two blank rows outnumber one real row; the real row must still win."""
        results = [
            ( 95.0, { "decision_value": "",  "ratification_state": "shadow" } ),
            ( 94.0, { "decision_value": "" } ),
            ( 90.0, { "decision_value": "approved" } ),
        ]
        prediction = _cbr( results ).predict( "q", "c", [ 0.0 ] * 768 )

        assert prediction.verdict == "approved"
        assert prediction.case_count == 1
        assert prediction.similar_cases == [ results[ 2 ][ 1 ] ]
        # max similarity comes from the surviving case, not the skipped 95
        assert abs( prediction.confidence - 0.90 ) < 0.001

    def test_all_blank_rows_give_an_empty_prediction( self ):
        results = [ ( 95.0, { "decision_value": "", "ratification_state": "shadow" } ) ]
        prediction = _cbr( results ).predict( "q", "c", [ 0.0 ] * 768 )

        assert prediction.verdict is None
        assert prediction.confidence == 0.0
        assert prediction.case_count == 0


class TestYesNoSkipsBlankRows:
    def test_blank_rows_cast_no_no_vote( self ):
        """Three blank rows used to out-vote one yes by 3 to 1 for "no"."""
        cases = [ ( 90.0, { "decision_value": "", "ratification_state": "shadow" } ) for _ in range( 3 ) ]
        cases.append( ( 80.0, { "decision_value": "yes" } ) )
        result = _engine( cases )._predict_yes_no( "q", "c", [ 0.1 ] )

        assert result.predicted_value == "yes"
        assert result.metadata[ "votes" ] == { "yes": 1.0 }
        assert result.similar_case_count == 1
        assert result.metadata[ "max_similarity" ] == 0.8

    def test_all_blank_rows_give_cold_start( self ):
        cases  = [ ( 90.0, { "decision_value": "", "ratification_state": "shadow" } ) ]
        result = _engine( cases )._predict_yes_no( "q", "c", [ 0.1 ] )

        assert result.predicted_value is None
        assert result.similar_case_count == 0
        assert result.metadata[ "reason" ] == "no_similar_cases"
