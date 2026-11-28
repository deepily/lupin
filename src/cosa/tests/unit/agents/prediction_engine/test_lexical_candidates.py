"""
Unit tests for BM25 word-overlap candidates beside, or instead of, cosine neighbours.

The engine tests run on the replay's own TimeSlicedDecisionStore. No test calls a model or reads a database.
"""

from datetime import datetime, timedelta, timezone

import pytest

from cosa.agents.prediction_engine import config as cfg
from cosa.agents.prediction_engine.candidate_filter import lexical_candidates
from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
from cosa.research.preference_replay.time_sliced_store import TimeSlicedDecisionStore

START = datetime( 2026, 11, 1, 12, 0, tzinfo=timezone.utc )
OWNER = "owner-1"
ASK   = "Delete the stale branch?"


def _vector( cosine ):
    """A 768-wide vector of accepted norm 20 with the given cosine to _vector( 1.0 )."""
    return [ 20.0 * cosine, 20.0 * ( 1.0 - cosine ** 2 ) ** 0.5 ] + [ 0.0 ] * 766


def _case( case_id, question, answer="yes", cosine=0.9, category="workflow" ):
    return { "id": case_id, "question": question, "category": category, "decision_value": answer,
             "ratification_state": "pending", "data_origin": "organic", "response_type": "yes_no",
             "question_embedding": _vector( cosine ), "created_at": START.isoformat(), "owner_user_id": OWNER,
             "answer_source": "human", "responded_at": START }


def _ids( pairs ):
    return [ record[ "id" ] for _, record in pairs ]


# ---- lexical_candidates --------------------------------------------------------

def test_pairs_come_back_by_word_overlap_with_their_own_similarity():
    pool   = [ ( 90.0, _case( "unrelated", "Push the tag now?" ) ), ( 40.0, _case( "one", "Keep the branch?" ) ),
               ( 20.0, _case( "two", "Delete the stale branch today?" ) ) ]
    ranked = lexical_candidates( pool, ASK, limit=2 )
    assert _ids( ranked ) == [ "two", "one" ]
    assert [ pct for pct, _ in ranked ] == [ 20.0, 40.0 ]


def test_a_case_sharing_no_word_and_a_case_with_no_question_are_left_out():
    pool = [ ( 90.0, _case( "none", "Ship it." ) ), ( 80.0, _case( "blank", None ) ) ]
    assert lexical_candidates( pool, ASK, limit=5 ) == []
    assert lexical_candidates( [], ASK, limit=5 ) == []


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
    return engine._predict_yes_no( ASK, "workflow", _vector( 1.0 ), owner_user_id=OWNER )


def test_words_alone_do_not_reach_a_case_below_the_threshold_with_the_switch_off( engine ):
    _wire( engine, [ _case( "words", "Delete the stale branch, yes or no?", "no", cosine=0.2 ) ] )
    assert _yes_no( engine ).metadata[ "reason" ] == "no_similar_cases"


@pytest.mark.parametrize( "mode", [ "fused", "lexical" ] )
def test_the_switch_reaches_a_case_below_the_cosine_threshold( engine, mode ):
    _wire( engine, [ _case( "words", "Delete the stale branch, yes or no?", "no", cosine=0.2 ) ] )
    engine.lexical_candidates_enabled = True
    engine.lexical_candidates_mode    = mode
    result = _yes_no( engine )
    assert result.similar_case_count == 1
    assert result.metadata[ "max_similarity" ] == pytest.approx( 0.2 )


def test_fused_keeps_both_sources_and_lexical_keeps_only_the_words( engine ):
    _wire( engine, [ _case( "near", "Ship it.", cosine=0.95 ), _case( "words", "Delete the stale branch?", "no", cosine=0.2 ) ] )
    engine.lexical_candidates_enabled = True
    assert _yes_no( engine ).similar_case_count == 2
    engine.lexical_candidates_mode = "lexical"
    assert _yes_no( engine ).similar_case_count == 1


def test_the_category_filter_still_applies_to_words_unless_category_ranks( engine ):
    _wire( engine, [ _case( "other", "Delete the stale branch?", cosine=0.2, category="deployment" ) ] )
    engine.lexical_candidates_enabled = True
    assert _yes_no( engine ).similar_case_count == 0
    engine.category_as_ranking = True
    assert _yes_no( engine ).similar_case_count == 1


def test_no_more_than_the_neighbour_limit_comes_back_and_the_cap_still_thins( engine ):
    words = [ _case( f"w{i}", f"Delete the stale branch {i}?", cosine=0.2 ) for i in range( 9 ) ]
    near  = [ _case( f"n{i}", f"Ship item {i}.", cosine=0.95 ) for i in range( 9 ) ]
    _wire( engine, words + near )
    engine.lexical_candidates_enabled = True
    assert _yes_no( engine ).similar_case_count == engine.cbr_top_k
    engine.candidate_template_cap_enabled = True
    engine.candidate_template_cap         = 1
    assert _yes_no( engine ).similar_case_count == 2


@pytest.mark.parametrize( "response_type, predict", [
    ( "multiple_choice", "_predict_multiple_choice" ),
    ( "open_ended",      "_predict_open_ended" ),
] )
def test_the_other_predictors_search_words_too( engine, response_type, predict ):
    case = { **_case( "words", ASK, '{"answers": {"A": "x"}}', cosine=0.2 ), "response_type": response_type }
    _wire( engine, [ case ] )
    engine.lexical_candidates_enabled = True
    engine._get_llm_client            = lambda: None
    assert getattr( engine, predict )( ASK, "workflow", _vector( 1.0 ), owner_user_id=OWNER ).similar_case_count == 1


def test_the_switch_is_off_by_default_and_in_the_config_version_only_when_on( engine ):
    assert cfg.DEFAULT_LEXICAL_CANDIDATES_ENABLED is False and engine.lexical_candidates_enabled is False
    assert engine.lexical_candidates_mode == "fused"
    seen = { engine.config_version() }
    engine.lexical_candidates_enabled = True
    seen.add( engine.config_version() )
    engine.lexical_candidates_mode = "lexical"
    seen.add( engine.config_version() )
    assert len( seen ) == 3


def _config( **table ):
    class Cfg:
        def get( self, key, default=None, return_type=None ):
            return table.get( key.replace( " ", "_" ), { "boolean": False, "int": 5, "float": 0.5 }.get( return_type, default ) )
    return Cfg()


def test_the_switch_and_mode_are_read_from_the_ini():
    PredictionEngine.reset()
    eng = PredictionEngine( config_mgr=_config( prediction_engine_lexical_candidates_enabled=True,
                            prediction_engine_lexical_candidates_mode="lexical", prediction_engine_retrieval_metric="cosine" ) )
    assert ( eng.lexical_candidates_enabled, eng.lexical_candidates_mode ) == ( True, "lexical" )
    PredictionEngine.reset()


@pytest.mark.parametrize( "table, match", [
    ( { "prediction_engine_lexical_candidates_mode": "both", "prediction_engine_retrieval_metric": "cosine" }, "lexical candidates mode" ),
    ( { "prediction_engine_lexical_candidates_enabled": True, "prediction_engine_retrieval_metric": "dot" }, "cosine" ),
] )
def test_a_setting_that_cannot_work_is_refused_at_start( table, match ):
    PredictionEngine.reset()
    with pytest.raises( ValueError, match=match ):
        PredictionEngine( config_mgr=_config( **table ) )
    PredictionEngine.reset()
