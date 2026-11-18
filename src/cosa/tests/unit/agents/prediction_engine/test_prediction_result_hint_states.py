"""
Unit tests for the forecast card payload: to_hint_dict answers in every state.

The payload names one of four states. Only a ready payload carries the value and confidence, so a card in any
other state cannot show a forecast it does not have. The same state is stored on the forecast row as its
display decision, so these tests pin the state names.
"""
import pytest

from cosa.agents.prediction_engine import config as cfg
from cosa.agents.prediction_engine.prediction_result import PredictionResult


def _result( **over ):
    kw = dict( response_type="yes_no", category="permission", strategy=cfg.STRATEGY_CBR_MAJORITY,
               predicted_value="yes", confidence=0.8, similar_case_count=3, metadata={} )
    kw.update( over )
    return PredictionResult( **kw )


class TestTheFourStates:

    def test_a_confident_forecast_is_ready_with_its_value_and_confidence( self ):
        hint = _result().to_hint_dict( 0.5, "dot" )
        assert hint[ "state" ] == "ready"
        assert hint[ "predicted_value" ] == "yes" and hint[ "confidence" ] == 0.8

    def test_a_confidence_exactly_at_the_threshold_is_ready( self ):
        assert _result( confidence=0.5 ).to_hint_dict( 0.5, "dot" )[ "state" ] == "ready"

    def test_a_confidence_under_the_threshold_is_below_threshold_and_hides_the_value( self ):
        hint = _result( confidence=0.49 ).to_hint_dict( 0.5, "dot" )
        assert hint[ "state" ] == "below_threshold"
        assert "predicted_value" not in hint and "confidence" not in hint and "predicted_qualifier" not in hint

    def test_a_cold_start_is_insufficient_evidence( self ):
        cold = _result( strategy=cfg.STRATEGY_COLD_START, predicted_value=None, confidence=0.0, metadata={ "reason": "no_similar_cases" } )
        assert cold.to_hint_dict( 0.5, "dot" )[ "state" ] == "insufficient_evidence"

    @pytest.mark.parametrize( "meta, strategy", [
        ( { "reason": "prediction_error", "error": "x", "error_class": "KeyError" }, cfg.STRATEGY_COLD_START ),
        ( { "reason": "engine_disabled" },                                           cfg.STRATEGY_COLD_START ),
        ( { "reason": "query_vector_refused: zero_norm" },                           cfg.STRATEGY_COLD_START ),
        ( {},                                                                        cfg.STRATEGY_ERROR ),
    ] )
    def test_a_predictor_failure_a_disabled_engine_or_a_refused_vector_is_unavailable( self, meta, strategy ):
        r = _result( strategy=strategy, predicted_value=None, confidence=0.0, metadata=meta )
        assert r.to_hint_dict( 0.5, "dot" )[ "state" ] == "unavailable"

    def test_a_result_with_no_metadata_still_gets_a_state( self ):
        assert _result( metadata=None ).to_hint_dict( 0.5, "dot" )[ "state" ] == "ready"


class TestTheRestOfThePayload:

    def test_every_state_carries_the_retrieval_metric_strategy_and_category( self ):
        for result, metric in [ ( _result(), "dot" ), ( _result( confidence=0.1 ), "cosine" ),
                                ( _result( strategy=cfg.STRATEGY_COLD_START, predicted_value=None, confidence=0.0 ), "dot" ) ]:
            hint = result.to_hint_dict( 0.5, metric )
            assert hint[ "retrieval_metric" ] == metric
            assert hint[ "strategy" ] == result.strategy and hint[ "category" ] == "permission"

    def test_a_yes_no_payload_carries_the_always_yes_rate_it_is_given( self ):
        rate = { "yes": 52, "n": 59, "rate": 0.8814 }
        assert _result().to_hint_dict( 0.5, "dot", rate )[ "always_yes_rate" ] == rate
        assert _result( confidence=0.1 ).to_hint_dict( 0.5, "dot", rate )[ "always_yes_rate" ] == rate

    def test_no_rate_given_means_no_key( self ):
        assert "always_yes_rate" not in _result().to_hint_dict( 0.5, "dot" )

    def test_a_card_that_is_not_yes_no_never_carries_the_rate( self ):
        mc = _result( response_type="multiple_choice", predicted_value={ "answers": { "A": "b" } } )
        assert "always_yes_rate" not in mc.to_hint_dict( 0.5, "dot", { "yes": 1, "n": 1, "rate": 1.0 } )

    def test_the_qualifier_appears_only_in_a_ready_payload( self ):
        r = _result( predicted_qualifier="but careful" )
        assert r.to_hint_dict( 0.5, "dot" )[ "predicted_qualifier" ] == "but careful"
        assert "predicted_qualifier" not in r.to_hint_dict( 0.99, "dot" )
