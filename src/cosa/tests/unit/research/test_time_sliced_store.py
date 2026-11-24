"""
The time-sliced store shows a forecast only the cases answered before the ask.

The named leak test plants a perfect match that was answered after the ask. It asserts the match is absent
from the neighbours. The rest pin the rules around it: the boundary instant counts, a case
never answered never counts, and the engine cannot write a case in.
"""

import inspect
from datetime import datetime, timedelta, timezone

import pytest

from cosa.agents.decision_proxy.proxy_decision_embeddings import ProxyDecisionEmbeddings
from cosa.research.preference_replay.time_sliced_store import RECORD_FIELDS, TimeSlicedDecisionStore
from cosa.rest.db.vector_store_models import EMBEDDING_DIM

ASK    = datetime( 2026, 8, 1, 12, 0, tzinfo=timezone.utc )
BEFORE = ASK - timedelta( hours = 1 )
AFTER  = ASK + timedelta( hours = 1 )


def _vector( *first, scale=20.0 ):
    """A 768-vector with ``first`` as its leading components, times ``scale``."""
    return [ x * scale for x in list( first ) + [ 0.0 ] * ( EMBEDDING_DIM - len( first ) ) ]


def _case( case_id, vector, responded_at, **overrides ):
    """One case dict with every record field."""
    case = { "id": case_id, "question": f"q_{case_id}", "category": "permission", "decision_value": "yes",
             "ratification_state": "not_required", "data_origin": "organic", "response_type": "yes_no",
             "question_embedding": vector, "created_at": "2026-07-01", "owner_user_id": None,
             "answer_source": "unknown", "responded_at": responded_at }
    case.update( overrides )
    return case


def test_a_late_answer_is_absent_from_the_neighbours_even_when_it_matches_perfectly():
    """A perfect match answered after the ask never appears."""
    store = TimeSlicedDecisionStore( [ _case( "early-near", _vector( 1.0, 0.2 ), BEFORE ),
                                       _case( "late-exact", _vector( 1.0, 0.0 ), AFTER ) ] )
    store.advance_to( ASK )
    for metric in ( "dot", "cosine" ):
        ids = [ record[ "id" ] for _, record in store.find_similar( _vector( 1.0, 0.0 ), limit=5, threshold=0.0, metric=metric ) ]
        assert ids == [ "early-near" ], metric
    store.advance_to( AFTER )
    assert "late-exact" in [ r[ "id" ] for _, r in store.find_similar( _vector( 1.0, 0.0 ), limit=5, threshold=0.0 ) ]


def test_an_answer_at_the_exact_ask_instant_counts_and_a_later_microsecond_does_not():
    """Visible means responded_at at or before the ask."""
    store = TimeSlicedDecisionStore( [ _case( "at", _vector( 1.0 ), ASK ),
                                       _case( "just-after", _vector( 1.0 ), ASK + timedelta( microseconds=1 ) ) ] )
    store.advance_to( ASK )
    assert store.visible_ids() == [ "at" ]


def test_a_case_that_was_never_answered_is_never_visible():
    """responded_at None means the answer never arrived."""
    store = TimeSlicedDecisionStore( [ _case( "never", _vector( 1.0 ), None ) ] )
    store.advance_to( AFTER )
    assert store.visible_ids() == [] and store.find_similar( _vector( 1.0 ), threshold=0.0 ) == []


def test_nothing_is_visible_before_the_store_is_advanced():
    """A store that has not been told the time knows nothing."""
    store = TimeSlicedDecisionStore( [ _case( "early", _vector( 1.0 ), BEFORE ) ] )
    assert store.visible_ids() == [] and store.find_similar( _vector( 1.0 ), threshold=0.0 ) == []


def test_the_store_grows_as_the_time_moves_forward():
    """Advancing reveals the cases in the order they were answered."""
    store = TimeSlicedDecisionStore( [ _case( "a", _vector( 1.0 ), BEFORE ), _case( "b", _vector( 1.0 ), AFTER ) ] )
    seen  = []
    for moment in ( BEFORE - timedelta( hours=1 ), BEFORE, ASK, AFTER ):
        store.advance_to( moment )
        seen.append( store.visible_ids() )
    assert seen == [ [], [ "a" ], [ "a" ], [ "a", "b" ] ]


def test_add_decision_stores_nothing_and_counts_the_attempt():
    """The engine cannot write a case in; the harness can assert refused_writes stayed 0."""
    store = TimeSlicedDecisionStore( [] )
    store.advance_to( ASK )
    assert store.add_decision( id="x", question="q", question_embedding=_vector( 1.0 ) ) is None
    assert store.refused_writes == 1 and store.visible_ids() == []


def test_find_similar_takes_the_same_arguments_as_the_wrapper_the_engine_normally_uses():
    """Parameter names, order and defaults match the wrapper's find_similar."""
    ours   = inspect.signature( TimeSlicedDecisionStore.find_similar ).parameters
    theirs = inspect.signature( ProxyDecisionEmbeddings.find_similar ).parameters
    assert list( ours ) == list( theirs )
    assert { name: p.default for name, p in ours.items() } == { name: p.default for name, p in theirs.items() }


def test_a_record_carries_exactly_the_record_fields_and_hands_back_a_copy_of_the_vector():
    """Changing a returned vector cannot change the store."""
    store = TimeSlicedDecisionStore( [ _case( "a", _vector( 1.0 ), BEFORE ) ] )
    store.advance_to( ASK )
    _, record = store.find_similar( _vector( 1.0 ), threshold=0.0 )[ 0 ]
    assert tuple( record.keys() ) == RECORD_FIELDS
    record[ "question_embedding" ][ 0 ] = -1.0
    assert store.find_similar( _vector( 1.0 ), threshold=0.0 )[ 0 ][ 1 ][ "question_embedding" ][ 0 ] == 20.0


def test_a_case_missing_a_field_raises_key_error_at_load():
    """Every record field is required."""
    case = _case( "a", _vector( 1.0 ), BEFORE )
    del case[ "owner_user_id" ]
    with pytest.raises( KeyError ):
        TimeSlicedDecisionStore( [ case ] )


def test_a_store_with_no_vectors_answers_with_nothing():
    """No cases, or only cases without vectors, gives an empty answer on both metrics."""
    for cases in ( [], [ _case( "novec", None, BEFORE ) ] ):
        store = TimeSlicedDecisionStore( cases )
        store.advance_to( ASK )
        assert store.find_similar( _vector( 1.0 ), threshold=0.0 ) == []
        assert store.find_similar( _vector( 1.0 ), threshold=0.0, metric="cosine" ) == []


def test_the_threshold_drops_weak_neighbours_after_the_limit():
    """The threshold drops a weak case inside the limit and pulls none in."""
    store = TimeSlicedDecisionStore( [ _case( "strong", _vector( 1.0, 0.0 ), BEFORE ),
                                       _case( "weak",   _vector( 1.0, 1.0 ), BEFORE ),
                                       _case( "weaker", _vector( 1.0, 3.0 ), BEFORE ) ] )
    store.advance_to( ASK )
    kept = store.find_similar( _vector( 1.0, 0.0 ), limit=2, threshold=0.7, metric="cosine" )
    assert [ r[ "id" ] for _, r in kept ] == [ "strong", "weak" ]
    assert [ r[ "id" ] for _, r in store.find_similar( _vector( 1.0, 0.0 ), limit=2, threshold=0.9, metric="cosine" ) ] == [ "strong" ]


def test_a_filter_is_applied_before_the_limit():
    """The strongest case fails the filter, so the limit goes to the best that passes."""
    store = TimeSlicedDecisionStore( [ _case( "wrong-owner", _vector( 1.0, 0.0 ), BEFORE, owner_user_id="ana" ),
                                       _case( "right-owner", _vector( 1.0, 0.5 ), BEFORE, owner_user_id="rick" ) ] )
    store.advance_to( ASK )
    assert [ r[ "id" ] for _, r in store.find_similar( _vector( 1.0, 0.0 ), limit=1, threshold=0.0, owner_user_id="rick" ) ] == [ "right-owner" ]


def test_an_unknown_metric_raises_value_error():
    """Only dot and cosine are scores."""
    with pytest.raises( ValueError ):
        TimeSlicedDecisionStore( [] ).find_similar( _vector( 1.0 ), metric="euclid" )


def test_visible_cases_gives_whole_copies_of_only_the_visible_cases():
    """Visible cases come back whole, and editing a copy never edits the store."""
    store = TimeSlicedDecisionStore( [ _case( "early", _vector( 1.0 ), BEFORE ), _case( "late", _vector( 1.0 ), AFTER ), _case( "novec", None, BEFORE ) ] )
    assert store.visible_cases() == [], "nothing is visible before advance_to"
    store.advance_to( ASK )
    seen = store.visible_cases()
    assert [ case[ "id" ] for case in seen ] == [ "early", "novec" ] and seen[ 0 ][ "responded_at" ] == BEFORE and seen[ 1 ][ "question_embedding" ] is None
    seen[ 0 ][ "question_embedding" ][ 0 ] = -1.0
    assert store.visible_cases()[ 0 ][ "question_embedding" ][ 0 ] == 20.0
