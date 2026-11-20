"""
Unit tests for the three-way stance challenger.

The vectors are short and hand-built, so every cosine and every weight can be worked out on paper.
No model is called and nothing is stored.
"""
from datetime import datetime, timedelta, timezone

import pytest

from cosa.agents.prediction_engine import config as cfg
from cosa.agents.prediction_engine import three_way_stance as tw
from cosa.agents.prediction_engine.prediction_engine import PredictionEngine

NOON   = datetime( 2026, 11, 10, 12, 0, tzinfo=timezone.utc )
OWNER  = "user-1"
SENDER = "claude.code@lupin.deepily.ai#00000001"
HL     = 14


def _case( case_id, answer, vector=( 1.0, 0.0 ), days_ago=0.0, **over ):
    """One answered yes/no case, answered `days_ago` days before noon."""
    row = {
        "id": case_id, "question": f"q {case_id}", "category": "permission", "decision_value": answer,
        "ratification_state": "not_required", "data_origin": "organic", "response_type": "yes_no",
        "question_embedding": None if vector is None else list( vector ), "created_at": "2026-11-01",
        "owner_user_id": OWNER, "answer_source": "human", "responded_at": NOON - timedelta( days=days_ago ),
        "title": f"Title {case_id}", "message": f"Message {case_id}", "sender_id": SENDER, "asked_at": NOON - timedelta( days=days_ago, minutes=1 ),
    }
    row.update( over )
    return row


def _ask( vector=( 1.0, 0.0 ), **over ):
    """The ask at noon."""
    ask = { "id": "ask", "response_type": "yes_no", "category": "permission", "title": "Ask title", "message": "Ask message",
            "sender_id": SENDER, "asked_at": NOON, "question_embedding": list( vector ), "owner_user_id": OWNER }
    ask.update( over )
    return ask


class TestUsableCases:

    def test_each_kind_of_case_that_may_not_vote_is_left_out( self ):
        cases = [
            _case( "ok", "yes" ),
            _case( "type", "yes", response_type="open_ended" ),
            _case( "proxy", "yes", answer_source="proxy" ),
            _case( "other", "yes", owner_user_id="user-2" ),
            _case( "down", "yes", ratification_state="REJECTED" ),
            _case( "gibberish", "maybe" ),
            _case( "late", "yes", days_ago=-1 ),
            _case( "open", "yes", responded_at=None ),
        ]
        assert [ c[ "id" ] for c in tw.usable_cases( _ask(), cases ) ] == [ "ok" ]

    def test_an_ask_with_no_owner_keeps_nothing( self ):
        assert tw.usable_cases( _ask( owner_user_id=None ), [ _case( "a", "yes" ) ] ) == []

    def test_the_cases_keep_their_order_and_an_ask_with_no_time_keeps_late_ones( self ):
        ask = _ask(); del ask[ "asked_at" ]
        got = tw.usable_cases( ask, [ _case( "b", "no" ), _case( "a", "yes", days_ago=-2 ) ] )
        assert [ c[ "id" ] for c in got ] == [ "b", "a" ]

    def test_a_ratification_state_of_none_is_an_ordinary_case( self ):
        assert len( tw.usable_cases( _ask(), [ _case( "a", "yes", ratification_state=None ) ] ) ) == 1


class TestLevels:

    def test_a_row_missing_a_field_has_no_levels( self ):
        row = _case( "a", "yes" ); del row[ "title" ]
        assert tw.levels_of( row ) == ( None, None )

    def test_a_known_project_and_the_family_come_from_the_row( self ):
        family, project = tw.levels_of( _case( "a", "yes", sender_id="claude.code@lupin.deepily.ai#1", title="Deploy" ) )
        assert project == "lupin" and family == ( "yes_no", "permission", "deploy" )

    def test_a_sender_with_no_project_gives_none( self ):
        assert tw.levels_of( _case( "a", "yes", sender_id=None ) )[ 1 ] is None


class TestBackoffPrior:

    def test_with_no_cases_the_prior_is_uniform( self ):
        prior, sizes = tw.backoff_prior( _ask(), [], HL )
        assert prior == { "yes": pytest.approx( 1 / 3 ), "no": pytest.approx( 1 / 3 ), "neither": pytest.approx( 1 / 3 ) }
        assert sizes == { "overall": 0, "project": 0, "family": 0 }

    def test_at_zero_family_and_project_counts_the_prior_is_the_overall_prior( self ):
        # three yes at age zero: overall = ( count + 1 ) / ( 3 + 3 ), yes 4/6, the others 1/6 each
        cases = [ _case( f"c{i}", "yes", sender_id="x@other.example.org", title=f"Other {i}" ) for i in range( 3 ) ]
        prior, sizes = tw.backoff_prior( _ask(), cases, HL )
        assert prior == { "yes": pytest.approx( 4 / 6 ), "no": pytest.approx( 1 / 6 ), "neither": pytest.approx( 1 / 6 ) }
        assert sizes == { "overall": 3, "project": 0, "family": 0 }

    def test_an_ask_with_no_sender_skips_the_project_level( self ):
        cases = [ _case( f"c{i}", "no", title=f"Other {i}" ) for i in range( 3 ) ]
        no_project, sizes = tw.backoff_prior( _ask( sender_id=None ), cases, HL )
        assert sizes[ "project" ] == 0
        assert no_project[ "no" ] == pytest.approx( 4 / 6 )

    def test_the_project_pulls_the_prior_toward_its_own_answers( self ):
        mine   = [ _case( f"m{i}", "no", title=f"M{i}" ) for i in range( 4 ) ]
        theirs = [ _case( f"t{i}", "yes", sender_id="x@elsewhere.example.org", title=f"T{i}" ) for i in range( 4 ) ]
        prior, sizes = tw.backoff_prior( _ask( title="Fresh" ), mine + theirs, HL )
        # overall: yes 5/11, no 5/11, neither 1/11. project ( 4 no ): no ( 4 + 2 * 5/11 ) / 6
        assert sizes == { "overall": 8, "project": 4, "family": 0 }
        assert prior[ "no" ] == pytest.approx( ( 4 + 2 * 5 / 11 ) / 6 )
        assert prior[ "no" ] > prior[ "yes" ]
        assert sum( prior.values() ) == pytest.approx( 1.0 )

    def test_the_family_pulls_the_prior_toward_its_own_answers_over_the_projects( self ):
        same   = [ _case( f"f{i}", "neither", title="Same title" ) for i in range( 3 ) ]
        others = [ _case( f"o{i}", "yes", title=f"Other {i}" ) for i in range( 6 ) ]
        prior, sizes = tw.backoff_prior( _ask( title="Same title" ), same + others, HL )
        assert sizes == { "overall": 9, "project": 9, "family": 3 }
        # overall yes 7/12, no 1/12, neither 4/12; project ( 6 yes, 3 neither ) pulls to neither 1/3;
        # family ( 3 neither ) then gives neither ( 3 + 2 * 1/3 ) / 5 and no ( 0 + 2 * 1/66 ) / 5
        assert prior[ "neither" ] == pytest.approx( 0.733333, abs=1e-5 )
        assert prior[ "no" ] == pytest.approx( 0.006061, abs=1e-5 )
        assert sum( prior.values() ) == pytest.approx( 1.0 )

    def test_an_older_answer_counts_less_in_the_overall_level( self ):
        fresh = tw.backoff_prior( _ask( sender_id=None ), [ _case( "a", "no", days_ago=0 ), _case( "b", "yes", days_ago=0 ) ], HL )[ 0 ]
        aged  = tw.backoff_prior( _ask( sender_id=None ), [ _case( "a", "no", days_ago=0 ), _case( "b", "yes", days_ago=42 ) ], HL )[ 0 ]
        assert fresh[ "no" ] == pytest.approx( fresh[ "yes" ] )
        assert aged[ "no" ] > aged[ "yes" ]


class TestNeighbours:

    def test_the_weight_is_cosine_times_recency_times_independence( self ):
        # cosine of ( 1, 0 ) with ( 3, 4 ) is 0.6; a 14-day-old answer weighs 0.500074
        got = tw.neighbours_of( _ask(), [ _case( "a", "yes", vector=( 3.0, 4.0 ), days_ago=14 ) ], HL )
        assert len( got ) == 1
        assert got[ 0 ][ "cosine" ] == pytest.approx( 0.6 )
        assert got[ 0 ][ "recency" ] == pytest.approx( 0.500074, abs=1e-5 )
        assert got[ 0 ][ "independence" ] == 1.0
        assert got[ 0 ][ "weight" ] == pytest.approx( 0.6 * 0.500074, abs=1e-5 )

    def test_copies_of_one_question_share_a_single_vote( self ):
        cases = [ _case( f"copy{i}", "no" ) for i in range( 3 ) ]
        got   = tw.neighbours_of( _ask(), cases, HL )
        assert [ n[ "independence" ] for n in got ] == [ pytest.approx( 1.0 ), pytest.approx( 1 / 2 ), pytest.approx( 1 / 3 ) ]
        # the copies' cosine and recency are all 1.0, so each weight is its independence alone
        assert [ n[ "weight" ] for n in got ] == [ pytest.approx( 1.0 ), pytest.approx( 1 / 2 ), pytest.approx( 1 / 3 ) ]

    def test_two_questions_that_differ_each_keep_a_full_vote( self ):
        got = tw.neighbours_of( _ask(), [ _case( "a", "no", vector=( 1.0, 0.0 ) ), _case( "b", "no", vector=( 1.0, 0.6 ) ) ], HL )
        assert [ n[ "independence" ] for n in got ] == [ 1.0, 1.0 ]

    def test_a_case_below_the_cosine_floor_or_with_no_vector_is_never_a_neighbour( self ):
        cases = [ _case( "far", "no", vector=( 0.0, 1.0 ) ), _case( "none", "no", vector=None ), _case( "near", "yes", vector=( 1.0, 0.1 ) ) ]
        assert [ n[ "case" ][ "id" ] for n in tw.neighbours_of( _ask(), cases, HL ) ] == [ "near" ]

    def test_only_the_ten_strongest_are_kept_strongest_first( self ):
        cases = [ _case( f"c{i}", "yes", vector=( 1.0, i * 0.05 ) ) for i in range( 14 ) ]
        got   = tw.neighbours_of( _ask(), cases, HL )
        assert len( got ) == 10 and [ n[ "case" ][ "id" ] for n in got ] == [ f"c{i}" for i in range( 10 ) ]


class TestPinnedConstants:
    """
    The numbers that set the challenger's behaviour.

    Each is pinned at a worked value, or on both sides of its edge.
    """

    def test_the_prior_strength_is_two( self ):
        # one no at cosine 1 and age 0, nothing at family or project level: overall prior no 2/4, yes and neither 1/4;
        # probability = ( count + strength * prior ) / ( total + strength ) with strength 2
        got = tw.three_way_forecast( _ask( sender_id=None ), [ _case( "a", "no", title="Elsewhere" ) ], HL )[ "probabilities" ]
        assert got == { "no": pytest.approx( 2 / 3 ), "yes": pytest.approx( 1 / 6 ), "neither": pytest.approx( 1 / 6 ) }

    def test_a_case_at_exactly_the_cosine_floor_is_a_neighbour_and_one_just_under_is_not( self ):
        ask = _ask( vector=( 1.0, 0.0, 0.0, 0.0 ) )
        at  = _case( "at", "no", vector=( 1.0, 1.0, 1.0, 1.0 ) )          # dot 1, norms 1 and 2: cosine exactly 0.5
        under = _case( "under", "no", vector=( 1.0, 1.0, 1.0, 1.0001 ) )  # cosine 0.49998750
        assert [ n[ "case" ][ "id" ] for n in tw.neighbours_of( ask, [ at ], HL ) ] == [ "at" ]
        assert tw.neighbours_of( ask, [ under ], HL ) == []

    def test_copies_are_judged_either_side_of_the_duplicate_edge( self ):
        # cosine 0.9806 to the first is a copy and shares its vote; 0.9701 is not. The exact 0.98 edge is not pinned:
        # no pair of short vectors gives it without rounding, so only both sides of it are.
        near = tw.neighbours_of( _ask(), [ _case( "a", "no", vector=( 1.0, 0.0 ) ), _case( "b", "no", vector=( 1.0, 0.2 ) ) ], HL )
        far  = tw.neighbours_of( _ask(), [ _case( "a", "no", vector=( 1.0, 0.0 ) ), _case( "b", "no", vector=( 1.0, 0.25 ) ) ], HL )
        assert [ n[ "independence" ] for n in near ] == [ 1.0, pytest.approx( 1 / 2 ) ]
        assert [ n[ "independence" ] for n in far ] == [ 1.0, 1.0 ]


class TestQualifier:

    def test_the_qualifier_follows_weight_not_cosine( self ):
        # the closest neighbour is 56 days old, so a fresher, less similar one outweighs it
        cases = [ _case( "close-old", "no [comment: stale]", vector=( 1.0, 0.0 ), days_ago=56 ),
                  _case( "near-new", "no [comment: fresh]", vector=( 1.0, 0.6 ), days_ago=0 ) ]
        got = tw.neighbours_of( _ask(), cases, HL )
        assert got[ 0 ][ "case" ][ "id" ] == "close-old" and got[ 0 ][ "cosine" ] > got[ 1 ][ "cosine" ]
        assert got[ 1 ][ "weight" ] > got[ 0 ][ "weight" ]
        assert tw.predict_qualifier( got, "no" ) == "fresh"

    def test_the_heaviest_neighbour_of_the_predicted_stance_that_wrote_one_gives_it( self ):
        cases = [ _case( "a", "no [comment: light]", vector=( 1.0, 0.5 ) ), _case( "b", "no [comment: heavy]", vector=( 1.0, 0.0 ) ),
                  _case( "c", "yes [comment: other side]", vector=( 1.0, 0.0 ) ) ]
        got = tw.neighbours_of( _ask(), cases, HL )
        assert tw.predict_qualifier( got, "no" ) == "heavy"

    def test_no_qualifier_on_the_stance_gives_none( self ):
        got = tw.neighbours_of( _ask(), [ _case( "a", "yes [comment: x]" ), _case( "b", "no" ) ], HL )
        assert tw.predict_qualifier( got, "no" ) is None


class TestForecast:

    def test_with_no_usable_case_the_probabilities_are_uniform_and_the_value_is_yes( self ):
        got = tw.three_way_forecast( _ask(), [], HL )
        assert got[ "value" ] == "yes" and got[ "confidence" ] == pytest.approx( 1 / 3 )
        assert got[ "probabilities" ] == { s: pytest.approx( 1 / 3 ) for s in tw.STANCES }
        assert got[ "neighbour_ids" ] == [] and got[ "qualifier" ] is None
        assert got[ "levels" ] == { "overall": 0, "project": 0, "family": 0, "neighbours": 0 }

    def test_a_no_stands_with_no_margin_where_the_margin_rule_would_say_yes( self ):
        # three no against two yes: the 1.35 rule needs a lead of 1.35 and a unit-vote lead is 1
        cases = [ _case( f"n{i}", "no", vector=( 1.0, 0.1 * i ) ) for i in range( 3 ) ] + [ _case( f"y{i}", "yes", vector=( 1.0, 0.05 + 0.1 * i ) ) for i in range( 2 ) ]
        got   = tw.three_way_forecast( _ask(), cases, HL )
        assert got[ "value" ] == "no"
        assert sum( got[ "probabilities" ].values() ) == pytest.approx( 1.0 )
        assert got[ "confidence" ] == got[ "probabilities" ][ "no" ]

    def test_a_neither_majority_is_forecast_neither( self ):
        cases = [ _case( f"e{i}", "neither", vector=( 1.0, 0.1 * i ) ) for i in range( 4 ) ]
        got   = tw.three_way_forecast( _ask(), cases, HL )
        assert got[ "value" ] == "neither" and got[ "neighbour_ids" ] == [ "e0", "e1", "e2", "e3" ]

    def test_a_tie_goes_to_yes_then_no_then_neither( self ):
        # one neighbour each of yes and no at the same cosine and the same age, with the same project counts: a dead heat
        cases = [ _case( "y", "yes", vector=( 1.0, 0.0 ) ), _case( "n", "no", vector=( 1.0, 0.6 ) ) ]
        got   = tw.three_way_forecast( _ask( sender_id=None ), cases, HL )
        assert got[ "probabilities" ][ "yes" ] > got[ "probabilities" ][ "no" ]  # the stronger cosine wins the vote
        tied  = tw.three_way_forecast( _ask( sender_id=None ), [ _case( "y", "yes", vector=( 1.0, 0.3 ) ), _case( "n", "no", vector=( 1.0, -0.3 ) ) ], HL )
        assert tied[ "probabilities" ][ "yes" ] == pytest.approx( tied[ "probabilities" ][ "no" ] ) and tied[ "value" ] == "yes"

    def test_the_prior_decides_when_there_is_no_neighbour( self ):
        cases = [ _case( f"c{i}", "no", vector=( 0.0, 1.0 ) ) for i in range( 8 ) ]   # orthogonal: none is a neighbour
        got   = tw.three_way_forecast( _ask(), cases, HL )
        assert got[ "levels" ][ "neighbours" ] == 0 and got[ "value" ] == "no"

    def test_the_qualifier_is_chosen_from_the_forecast_stance( self ):
        cases = [ _case( f"n{i}", f"no [comment: reason {i}]", vector=( 1.0, 0.1 * i ) ) for i in range( 3 ) ]
        assert tw.three_way_forecast( _ask(), cases, HL )[ "qualifier" ] == "reason 0"


class TestEngineMethod:

    @pytest.fixture
    def engine( self ):
        PredictionEngine.reset()
        yield PredictionEngine()
        PredictionEngine.reset()

    def test_the_switch_and_the_half_life_default_off_and_fourteen( self, engine ):
        assert cfg.DEFAULT_THREE_WAY_ENABLED is False and cfg.DEFAULT_RECENCY_HALF_LIFE_DAYS == 14
        assert engine.three_way_enabled is False and engine.recency_half_life_days == 14

    def test_the_committed_ini_keeps_the_switch_off_and_the_half_life_at_fourteen( self ):
        import cosa.utils.util as cu
        ini = open( cu.get_project_root() + "/src/conf/lupin-app.ini" ).read()
        assert "prediction engine three way enabled                         = false" in ini
        assert "prediction engine recency half life days                    = 14" in ini

    def test_with_the_switch_off_it_returns_none( self, engine ):
        assert engine.three_way_forecast( _ask(), [ _case( "a", "no" ) ] ) is None

    def test_with_the_switch_on_it_forecasts_with_the_engines_half_life( self, engine ):
        cases = [ _case( "old", "no", days_ago=28 ), _case( "new", "yes", vector=( 1.0, 0.4 ), days_ago=0 ) ]
        engine.three_way_enabled = True
        short = engine.three_way_forecast( _ask(), cases )
        engine.recency_half_life_days = 1400
        long  = engine.three_way_forecast( _ask(), cases )
        assert short[ "probabilities" ] != long[ "probabilities" ]
        assert long[ "probabilities" ][ "no" ] > short[ "probabilities" ][ "no" ]

    def test_the_settings_are_read_from_the_config_manager( self ):
        class _Cfg:
            def get( self, key, default=None, return_type=None ):
                if key == "prediction engine three way enabled": return True
                if key == "prediction engine recency half life days": return 21.0
                return { "int": lambda: int( default ), "float": lambda: float( default ),
                         "boolean": lambda: str( default ).lower() == "true" }.get( return_type, lambda: default )()
        PredictionEngine.reset()
        try:
            engine = PredictionEngine( config_mgr=_Cfg() )
            assert engine.three_way_enabled is True and engine.recency_half_life_days == 21.0
        finally: PredictionEngine.reset()
