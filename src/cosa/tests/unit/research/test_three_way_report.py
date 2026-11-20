"""
Unit tests for the three-way challenger's replay arm and its report.

There are two layers. The first is hand-built runs, where every count and p value can be worked out on paper.
The second is one real replay over eight synthetic asks, run through the harness the report is built for.
The embedding service is made to fail, so a passing test proves the stored vectors were used.
"""
from datetime import datetime, timedelta, timezone

import pytest

from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
from cosa.research.preference_replay import three_way_report as report
from cosa.research.preference_replay.replay_loop import ENGINE_ARM, always_yes_arm, replay
from cosa.rest.db.vector_store_models import EMBEDDING_DIM

SHA    = "0" * 64
NOON   = datetime( 2026, 11, 10, 12, 0, tzinfo=timezone.utc )
OWNER  = "user-1"
SENDER = "claude.code@lupin.deepily.ai#00000001"
FLOOR  = 6


def _records( name, forecasts, correct ):
    """One arm's records for asks a0, a1 and so on, each with its forecast and its correct flag."""
    return [ { "arm": name, "meta": { "notification_id": f"a{i}", "correct": ok, "response_type": "yes_no",
                                      "forecast": None if value is None else { "value": value } } }
             for i, ( value, ok ) in enumerate( zip( forecasts, correct ) ) ]


def _asks( answers ):
    return [ { "id": f"a{i}", "actual_value": { "value": answer } } for i, answer in enumerate( answers ) ]


def _run( answers, challenger, margin, challenger_ok, margin_ok ):
    """A run over answers, with always-yes scored by the answers themselves."""
    return { "records": {
        report.THREE_WAY_ARM : _records( report.THREE_WAY_ARM, challenger, challenger_ok ),
        ENGINE_ARM           : _records( ENGINE_ARM, margin, margin_ok ),
        report.BASELINE_ARM  : _records( report.BASELINE_ARM, [ "yes" ] * len( answers ), [ a == "yes" for a in answers ] ),
    }, "not_replayable": 0, "unrebuildable_cases": 0, "families": 4 }


class TestBuildReport:

    ANSWERS = [ "no", "no", "no", "no", "no", "no", "neither", "neither", "yes", "yes" ]

    def test_the_counts_name_what_each_arm_found_and_falsely_raised( self ):
        challenger = [ "no", "no", "no", "no", "no", "yes", "neither", "yes", "no", "yes" ]
        margin     = [ "yes", "yes", "no", "yes", "yes", "yes", "yes", "yes", "yes", "yes" ]
        run  = _run( self.ANSWERS, challenger, margin, [ c == a for c, a in zip( challenger, self.ANSWERS ) ], [ m == a for m, a in zip( margin, self.ANSWERS ) ] )
        got  = report.build_report( run, _asks( self.ANSWERS ), FLOOR )
        assert got[ "arms" ][ report.THREE_WAY_ARM ][ "counts" ] == {
            "genuine_no": 5, "genuine_neither": 1, "false_alarms": 1, "no_forecast": 0, "answered_no": 6, "answered_neither": 2 }
        assert got[ "arms" ][ ENGINE_ARM ][ "counts" ] == {
            "genuine_no": 1, "genuine_neither": 0, "false_alarms": 0, "no_forecast": 0, "answered_no": 6, "answered_neither": 2 }

    def test_a_yes_answer_forecast_neither_is_a_false_alarm_like_a_forecast_no( self ):
        answers = [ "yes", "yes" ]
        run = _run( answers, [ "neither", "no" ], [ "yes", "yes" ], [ False, False ], [ True, True ] )
        counts = report.build_report( run, _asks( answers ), FLOOR )[ "arms" ][ report.THREE_WAY_ARM ][ "counts" ]
        assert counts[ "false_alarms" ] == 2 and counts[ "genuine_no" ] == 0 and counts[ "genuine_neither" ] == 0

    def test_an_arm_with_no_forecast_is_counted_and_never_found_or_falsely_raised( self ):
        answers = [ "no", "yes" ]
        run = _run( answers, [ None, None ], [ "yes", "yes" ], [ False, False ], [ False, True ] )
        counts = report.build_report( run, _asks( answers ), FLOOR )[ "arms" ][ report.THREE_WAY_ARM ][ "counts" ]
        assert counts[ "no_forecast" ] == 2 and counts[ "genuine_no" ] == 0 and counts[ "false_alarms" ] == 0

    def test_a_challenger_decisively_better_than_always_yes_may_go_on_display( self ):
        answers = [ "no" ] * 8
        run = _run( answers, [ "no" ] * 8, [ "yes" ] * 8, [ True ] * 8, [ False ] * 8 )
        got = report.build_report( run, _asks( answers ), FLOOR )
        pair = got[ "arms" ][ report.THREE_WAY_ARM ][ "versus_always_yes" ]
        assert ( pair[ "engine_only_right" ], pair[ "baseline_only_right" ] ) == ( 8, 0 )
        assert pair[ "mcnemar" ][ "p_value" ] == pytest.approx( 2 / 2 ** 8 )
        assert pair[ "verdict" ] == "engine better"
        assert got[ "display" ] is True and got[ "verdict_text" ] == report.DISPLAY_READY

    def test_below_the_floor_it_stays_in_shadow_however_lopsided_the_few_pairs( self ):
        answers = [ "no" ] * 3 + [ "yes" ] * 5
        run = _run( answers, [ "no" ] * 3 + [ "yes" ] * 5, [ "yes" ] * 8, [ True ] * 8, [ a == "yes" for a in answers ] )
        got = report.build_report( run, _asks( answers ), FLOOR )
        assert got[ "arms" ][ report.THREE_WAY_ARM ][ "versus_always_yes" ][ "verdict" ] == "not decisive"
        assert got[ "display" ] is False and got[ "verdict_text" ] == report.STAYS_IN_SHADOW

    def test_a_challenger_worse_than_always_yes_stays_in_shadow( self ):
        answers = [ "yes" ] * 8
        run = _run( answers, [ "no" ] * 8, [ "yes" ] * 8, [ False ] * 8, [ True ] * 8 )
        got = report.build_report( run, _asks( answers ), FLOOR )
        assert got[ "arms" ][ report.THREE_WAY_ARM ][ "versus_always_yes" ][ "verdict" ] == "baseline better"
        assert got[ "arms" ][ report.THREE_WAY_ARM ][ "counts" ][ "false_alarms" ] == 8
        assert got[ "display" ] is False

    def test_the_challenger_is_also_paired_against_the_margin_rule( self ):
        answers = [ "no" ] * 8
        run = _run( answers, [ "no" ] * 8, [ "yes" ] * 8, [ True ] * 8, [ False ] * 8 )
        versus = report.build_report( run, _asks( answers ), FLOOR )[ "arms" ][ report.THREE_WAY_ARM ][ "versus_margin_rule" ]
        assert versus[ "baseline" ] == ENGINE_ARM and versus[ "verdict" ] == "engine better"

    def test_an_answer_held_as_a_bare_string_is_read_too( self ):
        run  = _run( [ "no" ], [ "no" ], [ "yes" ], [ True ], [ False ] )
        asks = [ { "id": "a0", "actual_value": "no [comment: because]" } ]
        assert report.build_report( run, asks, FLOOR )[ "arms" ][ report.THREE_WAY_ARM ][ "counts" ][ "genuine_no" ] == 1


class TestMakeArm:

    def _ask( self, **over ):
        ask = { "id": "ask", "response_type": "yes_no", "category": "permission", "title": "T", "message": "M", "sender_id": SENDER,
                "asked_at": NOON, "question_embedding": [ 1.0, 0.0 ], "owner_user_id": OWNER }
        ask.update( over )
        return ask

    def test_a_card_that_is_not_yes_no_or_has_no_vector_gets_no_forecast( self ):
        arm = report.make_three_way_arm( 14 )
        assert arm( self._ask( response_type="multiple_choice" ), [] ) is None
        assert arm( self._ask( question_embedding=None ), [] ) is None

    def test_a_yes_no_card_gets_a_value_and_a_chosen_qualifier( self ):
        arm  = report.make_three_way_arm( 14 )
        case = lambda i, answer: { "id": f"c{i}", "question": "q", "category": "permission", "decision_value": answer,
                                   "ratification_state": "not_required", "data_origin": "organic", "response_type": "yes_no",
                                   "question_embedding": [ 1.0, 0.0 ], "created_at": "x", "owner_user_id": OWNER,
                                   "answer_source": "human", "responded_at": NOON - timedelta( days=1 ) }
        assert arm( self._ask(), [] ) == { "value": "yes" }
        assert arm( self._ask(), [ case( 0, "no [comment: not today]" ) ] ) == { "value": "no", "qualifier": "not today" }


@pytest.fixture
def engine():
    PredictionEngine.reset()
    eng = PredictionEngine( debug=False )
    eng._generate_embedding = lambda text: pytest.fail( "the replay embedded a message" )
    yield eng
    PredictionEngine.reset()


def _vector():
    vector = [ 0.0 ] * EMBEDDING_DIM
    vector[ 0 ] = 20.0
    return vector


def test_the_challenger_runs_through_the_real_replay_and_beats_always_yes_on_a_run_of_nos( engine ):
    """
    Eight asks on one vector, all answered no; the first has no history.

    The messages differ by word, not by digit. The replay reads messages that differ only in digits as retry
    copies of one ask, and hides their history from each other.
    """
    asks = []
    for i, name in enumerate( [ "alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel" ] ):
        message = f"Should the synthetic worker {name} proceed?"
        asked   = NOON + timedelta( minutes=2 * i )
        category, _ = engine.classifier.classify( message, sender_id=SENDER )
        asks.append( {
            "id": f"n{i}", "question": message, "category": category, "decision_value": "no", "ratification_state": "not_required",
            "data_origin": "organic", "response_type": "yes_no", "question_embedding": _vector(), "created_at": "2026-11-10",
            "owner_user_id": OWNER, "answer_source": "human", "responded_at": asked + timedelta( minutes=1 ),
            "title": f"Worker {i}", "message": message, "sender_id": SENDER, "asked_at": asked, "recipient_id": OWNER,
            "response_options": None, "actual_value": "no" } )
    run = replay( asks, engine, SHA, baselines={ report.BASELINE_ARM: always_yes_arm, report.THREE_WAY_ARM: report.make_three_way_arm( 14 ) },
                  target_types=[ "yes_no" ] )
    got = report.build_report( run, asks, FLOOR )
    counts = got[ "arms" ][ report.THREE_WAY_ARM ][ "counts" ]
    assert counts == { "genuine_no": 7, "genuine_neither": 0, "false_alarms": 0, "no_forecast": 0, "answered_no": 8, "answered_neither": 0 }
    assert got[ "arms" ][ ENGINE_ARM ][ "counts" ][ "answered_no" ] == 8
    pair = got[ "arms" ][ report.THREE_WAY_ARM ][ "versus_always_yes" ]
    assert ( pair[ "engine_only_right" ], pair[ "baseline_only_right" ] ) == ( 7, 0 )
    assert got[ "display" ] is True
