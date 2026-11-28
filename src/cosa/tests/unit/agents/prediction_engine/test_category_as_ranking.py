"""
Unit tests for category as a ranking signal instead of a hard filter.

The engine tests run on the replay's own TimeSlicedDecisionStore. No test calls a model or reads a database.
"""

from datetime import datetime, timedelta, timezone

import pytest

from cosa.agents.prediction_engine import config as cfg
from cosa.agents.prediction_engine.candidate_filter import rank_with_category
from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
from cosa.research.preference_replay.time_sliced_store import TimeSlicedDecisionStore

START = datetime( 2026, 11, 1, 12, 0, tzinfo=timezone.utc )
OWNER = "owner-1"


def _vector( cosine ):
    """A 768-wide vector of accepted norm 20 with the given cosine to _vector( 1.0 )."""
    return [ 20.0 * cosine, 20.0 * ( 1.0 - cosine ** 2 ) ** 0.5 ] + [ 0.0 ] * 766


def _case( case_id, category, answer="yes", cosine=0.9, response_type="yes_no", question=None ):
    return { "id": case_id, "question": question or f"{case_id} ask?", "category": category, "decision_value": answer,
             "ratification_state": "pending", "data_origin": "organic", "response_type": response_type,
             "question_embedding": _vector( cosine ), "created_at": START.isoformat(), "owner_user_id": OWNER,
             "answer_source": "human", "responded_at": START }


def _ids( pairs ):
    return [ record[ "id" ] for _, record in pairs ]


# ---- rank_with_category --------------------------------------------------------

def test_the_bonus_lifts_a_same_category_case_over_a_slightly_nearer_one():
    same  = [ ( 80.0, _case( "same", "a" ) ) ]
    every = [ ( 84.0, _case( "near", "b" ) ), ( 80.0, _case( "same", "a" ) ), ( 70.0, _case( "far", "b" ) ) ]
    ranked = rank_with_category( same, every, "a", boost=0.05, limit=2 )
    assert _ids( ranked ) == [ "same", "near" ]
    assert [ pct for pct, _ in ranked ] == [ 80.0, 84.0 ]


def test_a_much_nearer_case_of_another_category_still_outranks():
    ranked = rank_with_category( [ ( 60.0, _case( "same", "a" ) ) ], [ ( 90.0, _case( "near", "b" ) ) ], "a", boost=0.05, limit=5 )
    assert _ids( ranked ) == [ "near", "same" ]


# ---- the engine ----------------------------------------------------------------

@pytest.fixture
def engine():
    PredictionEngine.reset()
    eng = PredictionEngine( debug=False )
    eng.retrieval_metric = "cosine"
    yield eng
    PredictionEngine.reset()


def _wire( engine, cases ):
    store = TimeSlicedDecisionStore( cases )
    store.advance_to( START + timedelta( days=1 ) )
    engine._embedding_store = store


def _yes_no( engine ):
    return engine._predict_yes_no( "Delete the branch?", "workflow", _vector( 1.0 ), owner_user_id=OWNER )


def test_the_filter_hides_another_category_with_the_switch_off( engine ):
    _wire( engine, [ _case( "other", "deployment", cosine=0.99 ) ] )
    assert _yes_no( engine ).metadata[ "reason" ] == "no_similar_cases"


def test_the_switch_lets_another_category_vote( engine ):
    _wire( engine, [ _case( "other", "deployment", cosine=0.99 ) ] )
    engine.category_as_ranking = True
    result = _yes_no( engine )
    assert ( result.predicted_value, result.similar_case_count ) == ( "yes", 1 )


def test_a_same_category_case_beyond_the_unfiltered_neighbours_is_still_found( engine ):
    nearer = [ _case( f"other-{i}", "deployment", cosine=0.92 ) for i in range( engine.cbr_top_k + 3 ) ]
    _wire( engine, nearer + [ _case( "mine", "workflow", "no", cosine=0.90 ) ] )
    engine.category_as_ranking = True
    result = _yes_no( engine )
    assert result.metadata[ "votes" ] == { "no": 1.0, "yes": engine.cbr_top_k - 1.0 }


def test_the_fallback_reports_the_similarity_of_the_case_it_answers_with( engine ):
    cases = [ _case( "mine", "workflow", "answer one", cosine=0.90, response_type="open_ended" ),
              _case( "near", "deployment", "answer two", cosine=0.93, response_type="open_ended" ) ]
    _wire( engine, cases )
    engine.category_as_ranking = True
    engine._get_llm_client = lambda: None
    result = engine._predict_open_ended( "Which one?", "workflow", _vector( 1.0 ), owner_user_id=OWNER )
    assert result.predicted_value == "answer one"
    assert result.confidence == pytest.approx( 0.90 )
    assert result.metadata[ "max_similarity" ] == pytest.approx( 0.93 )


def test_it_works_with_the_template_cap( engine ):
    cases = [ _case( f"flood-{i}", "workflow", "no", cosine=0.99, question=f"Delete row {i}?" ) for i in range( 8 ) ]
    _wire( engine, cases + [ _case( "other", "deployment", cosine=0.8 ) ] )
    engine.category_as_ranking = True
    engine.candidate_template_cap_enabled = True
    engine.candidate_template_cap         = 2
    assert _yes_no( engine ).similar_case_count == 3


def test_the_switch_is_off_by_default_and_in_the_config_version_only_when_on( engine ):
    assert cfg.DEFAULT_CATEGORY_AS_RANKING is False and engine.category_as_ranking is False
    seen = { engine.config_version() }
    engine.category_as_ranking = True
    seen.add( engine.config_version() )
    engine.category_rank_boost = 0.2
    seen.add( engine.config_version() )
    assert len( seen ) == 3


def test_the_switch_and_boost_are_read_from_the_ini():
    class Cfg:
        def get( self, key, default=None, return_type=None ):
            table = { "prediction engine category as ranking": True, "prediction engine category rank boost": 0.2,
                      "prediction engine retrieval metric": "cosine" }
            return table.get( key, { "boolean": False, "int": 5, "float": 0.5 }.get( return_type, default ) )

    PredictionEngine.reset()
    eng = PredictionEngine( config_mgr=Cfg() )
    assert ( eng.category_as_ranking, eng.category_rank_boost ) == ( True, 0.2 )
    PredictionEngine.reset()
