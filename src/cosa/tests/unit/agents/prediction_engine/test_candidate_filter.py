"""
Unit tests for thinning retrieved cases: retry copies and the per-template cap.

The engine tests run on the replay's own TimeSlicedDecisionStore, so the neighbour limit is the real one.
No test calls a model or reads a database.
"""

from datetime import datetime, timedelta, timezone

import pytest

from cosa.agents.prediction_engine import config as cfg
from cosa.agents.prediction_engine.candidate_filter import thin_candidates
from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
from cosa.research.preference_replay.time_sliced_store import TimeSlicedDecisionStore

START = datetime( 2026, 11, 1, 12, 0, tzinfo=timezone.utc )
OWNER = "owner-1"


def _vector( cosine ):
    """A 768-wide vector of accepted norm 20 with the given cosine to _vector( 1.0 )."""
    return [ 20.0 * cosine, 20.0 * ( 1.0 - cosine ** 2 ) ** 0.5 ] + [ 0.0 ] * 766


def _case( case_id, question, answer, cosine=0.9, minutes=0, state="pending", response_type="yes_no", created_at="" ):
    stamp = START + timedelta( minutes=minutes )
    return { "id": case_id, "question": question, "category": "workflow", "decision_value": answer, "ratification_state": state,
             "data_origin": "organic", "response_type": response_type, "question_embedding": _vector( cosine ),
             "created_at": stamp.isoformat() if created_at == "" else created_at, "owner_user_id": OWNER, "answer_source": "human",
             "responded_at": stamp }


def _pairs( *cases ):
    """The ( similarity_pct, record ) list find_similar returns, in the order given."""
    return [ ( 99.0 - i, case ) for i, case in enumerate( cases ) ]


def _ids( pairs ):
    return [ record[ "id" ] for _, record in pairs ]


# ---- thin_candidates ---------------------------------------------------------

def test_with_nothing_asked_for_the_list_is_only_cut_to_the_limit():
    pairs = _pairs( _case( "a", "Run it?", "yes" ), _case( "b", "Run it?", "yes" ), _case( "c", "Run it?", "yes" ) )
    assert _ids( thin_candidates( pairs, limit=2 ) ) == [ "a", "b" ]


def test_retry_copies_within_ten_minutes_count_once_and_the_earliest_is_kept():
    pairs = _pairs( _case( "second", "Delete row 5?", "no", minutes=4 ), _case( "first", "Delete row 9?", "yes", minutes=0 ),
                    _case( "later", "Delete row 7?", "no", minutes=30 ), _case( "other", "Push now?", "yes", minutes=1 ) )
    assert _ids( thin_candidates( pairs, limit=10, dedupe=True ) ) == [ "first", "later", "other" ]


def test_a_voted_copy_is_kept_over_an_earlier_unvoted_one():
    pairs = _pairs( _case( "plain", "Run it?", "yes", minutes=0 ), _case( "voted", "Run it?", "yes", minutes=2, state="rejected" ) )
    assert _ids( thin_candidates( pairs, limit=10, dedupe=True ) ) == [ "voted" ]


def test_a_case_with_no_readable_time_never_joins_a_group():
    pairs = _pairs( _case( "a", "Run it?", "yes" ), _case( "b", "Run it?", "yes", created_at=None ), _case( "c", "Run it?", "yes", created_at="junk" ) )
    assert _ids( thin_candidates( pairs, limit=10, dedupe=True ) ) == [ "a", "b", "c" ]


def test_the_cap_keeps_the_strongest_cases_of_one_template():
    pairs = _pairs( _case( "a", "Delete row 1?", "no" ), _case( "b", "Delete row 2?", "no" ), _case( "c", "Delete row 3?", "no" ),
                    _case( "d", "Push now?", "yes" ) )
    assert _ids( thin_candidates( pairs, limit=10, template_cap=2 ) ) == [ "a", "b", "d" ]


def test_questions_that_normalise_to_nothing_are_never_capped():
    pairs = _pairs( _case( "a", "123", "no" ), _case( "b", "456", "no" ), _case( "c", None, "no" ) )
    assert _ids( thin_candidates( pairs, limit=10, template_cap=1 ) ) == [ "a", "b", "c" ]


@pytest.mark.parametrize( "kwargs", [ { "limit": 0 }, { "limit": 3, "template_cap": 0 } ] )
def test_a_limit_or_cap_below_one_is_refused( kwargs ):
    with pytest.raises( ValueError ):
        thin_candidates( [], **kwargs )


# ---- the engine ---------------------------------------------------------------

@pytest.fixture
def engine():
    PredictionEngine.reset()
    eng = PredictionEngine( debug=False )
    eng.retrieval_metric = "cosine"
    yield eng
    PredictionEngine.reset()


def _wire( engine, cases ):
    store = TimeSlicedDecisionStore( cases )
    store.advance_to( START + timedelta( days=9 ) )
    engine._embedding_store = store


def _flood():
    """Twelve copies of one template saying no, nearer than three other asks saying yes."""
    flood = [ _case( f"flood-{i}", f"Delete row {i}?", "no", cosine=0.99, minutes=i * 30 ) for i in range( 12 ) ]
    rest  = [ _case( f"rest-{i}", q, "yes", cosine=0.9, minutes=1000 + i * 30 ) for i, q in enumerate( ( "Push now?", "Run the suite?", "Merge it?" ) ) ]
    return flood + rest


def _yes_no( engine ):
    return engine._predict_yes_no( "Delete the branch?", "workflow", _vector( 1.0 ), owner_user_id=OWNER )


def test_one_template_fills_every_neighbour_with_both_switches_off( engine ):
    _wire( engine, _flood() )
    result = _yes_no( engine )
    assert result.predicted_value == "no" and result.similar_case_count == engine.cbr_top_k


def test_the_cap_switch_lets_other_templates_vote( engine ):
    _wire( engine, _flood() )
    engine.candidate_template_cap_enabled = True
    engine.candidate_template_cap         = 2
    result = _yes_no( engine )
    assert result.predicted_value == "yes" and result.similar_case_count == 5


def test_the_dedupe_switch_counts_a_burst_of_retries_once( engine ):
    burst = [ _case( f"retry-{i}", "Delete the branch?", "no", cosine=0.99, minutes=i ) for i in range( 8 ) ]
    _wire( engine, burst + [ _case( "other", "Push now?", "yes", cosine=0.9, minutes=500 ) ] )
    off = _yes_no( engine )
    assert ( off.predicted_value, off.similar_case_count ) == ( "no", engine.cbr_top_k )
    engine.candidate_retry_dedupe_enabled = True
    on  = _yes_no( engine )
    assert ( on.predicted_value, on.similar_case_count ) == ( "yes", 2 )


@pytest.mark.parametrize( "response_type, predict", [
    ( "multiple_choice", "_predict_multiple_choice" ),
    ( "open_ended",      "_predict_open_ended" ),
] )
def test_the_other_predictors_are_thinned_too( engine, response_type, predict ):
    cases = [ _case( f"c{i}", f"Delete row {i}?", '{"answers": {"A": "x"}}', cosine=0.99, minutes=i * 30, response_type=response_type ) for i in range( 6 ) ]
    _wire( engine, cases )
    engine.candidate_template_cap_enabled = True
    engine.candidate_template_cap         = 1
    result = getattr( engine, predict )( "Delete row 99?", "workflow", _vector( 1.0 ), owner_user_id=OWNER )
    assert result.similar_case_count == 1


def test_both_switches_are_off_by_default_and_change_the_config_version_only_when_on( engine ):
    assert cfg.DEFAULT_CANDIDATE_RETRY_DEDUPE_ENABLED is False and cfg.DEFAULT_CANDIDATE_TEMPLATE_CAP_ENABLED is False
    assert engine.candidate_retry_dedupe_enabled is False and engine.candidate_template_cap_enabled is False
    seen = { engine.config_version() }
    engine.candidate_retry_dedupe_enabled = True
    seen.add( engine.config_version() )
    engine.candidate_template_cap_enabled = True
    seen.add( engine.config_version() )
    engine.candidate_template_cap = engine.candidate_template_cap + 1
    seen.add( engine.config_version() )
    assert len( seen ) == 4


def test_the_switches_are_read_from_the_ini():
    class Cfg:
        def get( self, key, default=None, return_type=None ):
            table = { "prediction engine candidate retry dedupe enabled": True, "prediction engine candidate template cap enabled": True,
                      "prediction engine candidate template cap": 7, "prediction engine retrieval metric": "cosine" }
            return table.get( key, { "boolean": False, "int": 5, "float": 0.5 }.get( return_type, default ) )

    PredictionEngine.reset()
    eng = PredictionEngine( config_mgr=Cfg() )
    assert ( eng.candidate_retry_dedupe_enabled, eng.candidate_template_cap_enabled, eng.candidate_template_cap ) == ( True, True, 7 )
    PredictionEngine.reset()
