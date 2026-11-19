"""
The retune names the best settings on the tune window and reports the final window too.

The synthetic asks put every history case at cosine 0.8 to the later targets and 0.64 to each other.
A threshold up to 0.60 lets history asks predict each other. Up to 0.80 the targets also see the history.
Above that, a target is forecast only from an earlier target at cosine 1.0.
So the best point on the tune window is known in advance.
"""

from datetime import datetime, timedelta, timezone

import pytest

from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
from cosa.research.phi4_flash_lite_study.freeze_corpus import sha256_of_rows
from cosa.research.preference_replay import retune
from cosa.research.preference_replay.retune import ELIGIBLE_TYPES, eligible_asks, frozen_settings, grid, retune as run_retune, split_windows
from cosa.rest.db.vector_store_models import EMBEDDING_DIM

NOON   = datetime( 2026, 11, 10, 12, 0, tzinfo=timezone.utc )
SHA    = "1" * 64
SENDER = "claude.code@lupin.deepily.ai#00000001"
OWNER  = "user-1"


def _vector( weights ):
    """A vector with the given leading components, scaled to sit in the stored-vector band."""
    vector = [ 0.0 ] * EMBEDDING_DIM
    for axis, weight in enumerate( weights ): vector[ axis ] = 20.0 * weight
    return vector


@pytest.fixture
def engine():
    """The real engine, with embedding generation made to fail so a stored vector must be used."""
    PredictionEngine.reset()
    eng = PredictionEngine( debug=False )
    eng._generate_embedding = lambda text: pytest.fail( "the retune embedded a message" )
    yield eng
    PredictionEngine.reset()


def _ask( engine, ask_id, vector, minutes, answer="yes", response_type="yes_no", **extra ):
    """One answered ask `minutes` after noon."""
    message  = f"Should the synthetic worker {ask_id} proceed?"
    category, _ = engine.classifier.classify( message, sender_id=SENDER )
    asked    = NOON + timedelta( minutes=minutes )
    ask = { "id": ask_id, "question": message, "category": category, "decision_value": answer, "ratification_state": "not_required",
            "data_origin": "organic", "response_type": response_type, "question_embedding": vector, "created_at": "2026-11-10",
            "owner_user_id": OWNER, "answer_source": "human", "responded_at": asked + timedelta( minutes=1 ),
            "title": f"Worker {ask_id}", "message": message, "sender_id": SENDER, "asked_at": asked, "recipient_id": OWNER,
            "response_options": None, "actual_value": answer }
    ask.update( extra )
    return ask


def _asks( engine ):
    """Five history asks at cosine 0.8 to the targets, then five targets, well apart in time."""
    history = [ _ask( engine, f"h{i}", _vector( [ 0.8 ] + [ 0.0 ] * i + [ 0.6 ] ), i * 30 ) for i in range( 5 ) ]
    targets = [ _ask( engine, f"t{i}", _vector( [ 1.0 ] ), 200 + i * 30 ) for i in range( 5 ) ]
    return history + targets


def test_the_grid_is_the_plans_and_orders_thresholds_within_each_top_k():
    """Nine thresholds from 0.50 to 0.90 and four top k values."""
    points = grid()
    assert len( points ) == 36
    assert retune.THRESHOLDS[ 0 ] == 0.5 and retune.THRESHOLDS[ -1 ] == 0.9 and len( retune.THRESHOLDS ) == 9
    assert retune.TOP_KS == ( 3, 5, 8, 10 )
    assert points[ :3 ] == [ ( 0.5, 3 ), ( 0.55, 3 ), ( 0.6, 3 ) ] and points[ -1 ] == ( 0.9, 10 )


def test_the_split_is_seventy_thirty_by_position_and_adds_up():
    """The tune window is the floor of seventy percent."""
    assert split_windows( 10 ) == ( 7, 3 )
    assert split_windows( 7 ) == ( 4, 3 )
    assert split_windows( 0 ) == ( 0, 0 )
    assert sum( split_windows( 59 ) ) == 59


def test_only_yes_no_and_multiple_choice_asks_with_a_vector_are_eligible( engine ):
    """Free text and a vectorless ask are left out."""
    asks = [ _ask( engine, "a", _vector( [ 1.0 ] ), 0 ), _ask( engine, "b", _vector( [ 1.0 ] ), 1, response_type="open_ended" ),
             _ask( engine, "c", None, 2 ), _ask( engine, "d", _vector( [ 1.0 ] ), 3, response_type="multiple_choice" ) ]
    assert [ a[ "id" ] for a in eligible_asks( asks ) ] == [ "a", "d" ]
    assert ELIGIBLE_TYPES == ( "yes_no", "multiple_choice" )


def test_the_best_point_wins_on_the_tune_window_and_ties_go_to_the_higher_threshold_then_the_smaller_k( engine ):
    """Thresholds up to 0.60 tie at the top, so 0.60 and the smallest k win."""
    result = run_retune( _asks( engine ), engine, SHA )
    assert result[ "best" ][ "threshold" ] == 0.6 and result[ "best" ][ "top_k" ] == 3
    assert result[ "best" ][ "tune_correct" ] == 6 and result[ "best" ][ "tune_per_100" ] == round( 600 / 7, 4 )
    assert ( result[ "tune_size" ], result[ "final_size" ], result[ "eligible" ] ) == ( 7, 3, 10 )
    by_point = { ( p[ "threshold" ], p[ "top_k" ] ): p for p in result[ "points" ] }
    assert len( by_point ) == 36
    assert by_point[ ( 0.8, 3 ) ][ "tune_correct" ] == 2, "between 0.65 and 0.80 only the two tune-window targets are forecast"
    assert by_point[ ( 0.85, 3 ) ][ "tune_correct" ] == 1, "above 0.80 only the second target sees the first, at cosine 1.0"
    assert by_point[ ( 0.8, 3 ) ][ "final_correct" ] == 3 and by_point[ ( 0.85, 3 ) ][ "final_correct" ] == 3


def test_each_point_reports_the_answer_rate_and_the_accuracy_among_answered_asks( engine ):
    """At 0.80 two tune targets are forecast and one is wrong, so answered and correct differ."""
    asks = _asks( engine )
    asks[ 5 ] = dict( asks[ 5 ], actual_value="no", decision_value="no" )
    result   = run_retune( asks, engine, SHA )
    by_point = { ( p[ "threshold" ], p[ "top_k" ] ): p for p in result[ "points" ] }
    point    = by_point[ ( 0.8, 3 ) ]
    assert ( point[ "tune_answered" ], point[ "tune_correct" ] ) == ( 2, 1 )
    assert point[ "tune_answer_rate_per_100" ] == round( 200 / 7, 4 ) and point[ "tune_accuracy_answered_per_100" ] == 50.0
    assert point[ "final_answered" ] == 3 and point[ "final_answer_rate_per_100" ] == 100.0
    assert point[ "final_correct" ] == 3 and point[ "final_accuracy_answered_per_100" ] == 100.0
    high = by_point[ ( 0.85, 3 ) ]
    assert ( high[ "tune_answered" ], high[ "tune_correct" ] ) == ( 1, 1 ), "above 0.80 only the second target is forecast, from the first"
    assert result[ "best" ][ "tune_per_100" ] == max( p[ "tune_per_100" ] for p in result[ "points" ] ), "the answered figures never decide the winner"


def test_the_final_window_never_decides_the_winner( engine ):
    """The winner is the best on the tune window, whatever the final window says."""
    result = run_retune( _asks( engine ), engine, SHA )
    best_final = max( p[ "final_per_100" ] for p in result[ "points" ] )
    assert result[ "best" ][ "final_per_100" ] <= best_final
    assert max( p[ "tune_per_100" ] for p in result[ "points" ] ) == result[ "best" ][ "tune_per_100" ]


def test_the_tune_cohort_checksum_covers_the_tune_windows_ids_in_time_order( engine ):
    """The sha is the checksum of the first seven ask ids."""
    asks   = _asks( engine )
    result = run_retune( list( reversed( asks ) ), engine, SHA )
    assert result[ "tune_cohort_sha256" ] == sha256_of_rows( [ { "id": a[ "id" ] } for a in asks[ :7 ] ] )


def test_the_engines_settings_are_put_back_even_when_a_replay_raises( engine ):
    """A failure leaves the engine as it was found."""
    before = ( engine.similarity_threshold, engine.cbr_top_k, engine.retrieval_metric )
    run_retune( _asks( engine ), engine, SHA, thresholds=( 0.5, ), top_ks=( 3, ) )
    assert ( engine.similarity_threshold, engine.cbr_top_k, engine.retrieval_metric ) == before
    engine.predict = lambda notification, query_vector=None: (_ for _ in ()).throw( RuntimeError( "boom" ) )
    with pytest.raises( RuntimeError ):
        run_retune( _asks( engine ), engine, SHA, thresholds=( 0.5, ), top_ks=( 3, ) )
    assert ( engine.similarity_threshold, engine.cbr_top_k, engine.retrieval_metric ) == before


def test_the_retune_runs_under_the_cosine_metric( engine ):
    """The grid is scored with the metric the freeze will set."""
    seen = []
    original = engine._predict_yes_no
    engine._predict_yes_no = lambda *a, **k: seen.append( engine.retrieval_metric ) or original( *a, **k )
    engine.retrieval_metric = "dot"
    run_retune( _asks( engine ), engine, SHA, thresholds=( 0.5, ), top_ks=( 3, ) )
    assert seen and set( seen ) == { "cosine" }


def test_no_eligible_asks_is_refused( engine ):
    """There is nothing to tune on."""
    with pytest.raises( ValueError ):
        run_retune( [ _ask( engine, "a", _vector( [ 1.0 ] ), 0, response_type="open_ended" ) ], engine, SHA )


def test_an_empty_window_scores_zero_not_a_division_error():
    """A window with no asks reads 0.0 per 100."""
    assert retune._per_hundred( 0, 0 ) == 0.0 and retune._per_hundred( 1, 4 ) == 25.0


def test_the_frozen_settings_name_the_two_retuned_keys_and_the_cosine_metric_only( engine ):
    """The open-ended keys are not in the freeze."""
    result = run_retune( _asks( engine ), engine, SHA, thresholds=( 0.5, 0.6 ), top_ks=( 3, ) )
    settings = frozen_settings( result )
    assert settings == { "prediction engine cbr similarity threshold": 0.6, "prediction engine cbr top k": 3,
                         "prediction engine retrieval metric": "cosine" }
    assert not any( "open ended" in key for key in settings )
