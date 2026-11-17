#!/usr/bin/env python3
"""
Unit tests for the prior-weighted yes/no vote in PredictionEngine._predict_yes_no.

"no" is predicted only when its tally beats the yes tally by yes_no_no_margin
(default 1.35 = ln(527/137), the log-odds of the 79.4% yes prior). All mocked, no DB
or server, so :7999-eligible.
"""

from unittest.mock import MagicMock

from cosa.agents.prediction_engine.config import DEFAULT_YES_NO_NO_MARGIN
from cosa.agents.prediction_engine.prediction_engine import PredictionEngine


def _engine( cases ):
    """Engine whose store returns `cases` ( list of ( similarity_pct, record ) )."""
    engine = PredictionEngine( debug=False )
    engine._embedding_store = MagicMock()
    engine._embedding_store.find_similar.return_value = cases
    return engine


def _cases( yes, no, state="pending" ):
    """`yes` yes-cases then `no` no-cases, all 90% similar."""
    return (
        [ ( 90.0, { "decision_value": "yes", "ratification_state": state } ) for _ in range( yes ) ] +
        [ ( 90.0, { "decision_value": "no",  "ratification_state": state } ) for _ in range( no  ) ]
    )


class TestYesNoPriorMargin:
    def test_default_margin_is_log_odds_of_the_yes_prior( self ):
        assert DEFAULT_YES_NO_NO_MARGIN == 1.35
        assert PredictionEngine().yes_no_no_margin == 1.35

    def test_ini_key_is_read_when_a_config_manager_is_given( self ):
        PredictionEngine._instance = None
        try:
            cfg = MagicMock()
            cfg.get.side_effect = lambda key, default=None, return_type=None: 2.5 if key == "prediction engine yes no no margin" else default
            engine = PredictionEngine( config_mgr=cfg )
            assert engine.yes_no_no_margin == 2.5
        finally:
            PredictionEngine._instance = None

    def test_lead_of_one_is_overturned_to_yes( self ):
        # 3 no vs 2 yes: plain majority says "no"; lead 1 < 1.35 so prior wins
        result = _engine( _cases( yes=2, no=3 ) )._predict_yes_no( "q", "general", [ 0.1 ] )
        assert result.predicted_value == "yes"
        assert result.metadata[ "no_suppressed_by_prior" ] is True
        assert result.confidence > 0.0     # yes tally 2.0 of positive mass 5.0

    def test_lead_of_two_stands_as_no( self ):
        # 3 no vs 1 yes: lead 2 >= 1.35
        result = _engine( _cases( yes=1, no=3 ) )._predict_yes_no( "q", "general", [ 0.1 ] )
        assert result.predicted_value == "no"
        assert result.metadata[ "no_suppressed_by_prior" ] is False

    def test_all_no_with_lead_of_one_gives_yes_at_zero_confidence( self ):
        # only one "no" neighbour, no yes key at all: lead 1.0 < 1.35 → yes, confidence 0
        result = _engine( _cases( yes=0, no=1 ) )._predict_yes_no( "q", "general", [ 0.1 ] )
        assert result.predicted_value == "yes"
        assert result.confidence == 0.0
        assert "yes" not in result.metadata[ "votes" ]     # votes metadata stays the raw tally

    def test_yes_majority_is_untouched( self ):
        result = _engine( _cases( yes=3, no=2 ) )._predict_yes_no( "q", "general", [ 0.1 ] )
        assert result.predicted_value == "yes"
        assert result.metadata[ "no_suppressed_by_prior" ] is False

    def test_margin_zero_restores_plain_majority( self ):
        engine = _engine( _cases( yes=2, no=3 ) )
        engine.yes_no_no_margin = 0.0
        assert engine._predict_yes_no( "q", "general", [ 0.1 ] ).predicted_value == "no"

    def test_a_thumbs_up_no_can_clear_the_margin_alone( self ):
        # two approved no (4.0) vs one pending yes (1.0): lead 3.0 → no
        engine = _engine( _cases( yes=1, no=0 ) + _cases( yes=0, no=2, state="approved" ) )
        assert engine._predict_yes_no( "q", "general", [ 0.1 ] ).predicted_value == "no"

    def test_lead_exactly_equal_to_the_margin_stands_as_no( self ):
        # margin 2.0, 3 no vs 1 yes: lead == margin, so "no" stands ( >=, not > )
        engine = _engine( _cases( yes=1, no=3 ) )
        engine.yes_no_no_margin = 2.0
        result = engine._predict_yes_no( "q", "general", [ 0.1 ] )
        assert result.predicted_value == "no"
        assert result.metadata[ "no_suppressed_by_prior" ] is False
