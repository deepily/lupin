#!/usr/bin/env python3
"""
Named leak fixtures run through the replay loop on the live engine.

Each class plants a leak the loop must not let into the target's forecast.
Neighbours come from the real engine's evidence ids. Later status checks the
rows handed to the store. Final state checks everything the engine is handed.

Requires:
    - src/tests/unit/fixtures/preference_replay_leaks/leak_fixtures.json
    - cosa.research.preference_replay.replay_loop
"""

import json
from datetime import datetime, timedelta

import pytest

from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
from cosa.research.preference_replay.replay_loop import ENGINE_ARM, replay, rows_as_of
from cosa.research.preference_replay.time_sliced_store import TimeSlicedDecisionStore
from tests.helpers.preference_leak_fixture import basis_vector, load_fixture

SHA     = "0" * 64
OWNER   = "synthetic-owner"




@pytest.fixture
def engine():
    """The real engine, with embedding generation made to fail so a stored vector must be used."""
    PredictionEngine.reset()
    eng = PredictionEngine( debug=False )
    eng._generate_embedding = lambda text: pytest.fail( "the replay embedded a message" )
    yield eng
    PredictionEngine.reset()


def _asks_for( engine, name ):
    """
    Turn one fixture class into the ask list the loop replays.

    Requires:
        - name is a key of the fixture's classes

    Ensures:
        - returns ( asks, target_id ); the target is one ask, and a case whose id is the target's is the target itself
        - a case without its own ask times is asked one minute before it was answered
        - the target carries the fixture's notification final state, if any, under final_-prefixed keys so no real field is overwritten
    """
    data    = load_fixture()
    entry   = data[ "classes" ][ name ]
    common  = data[ "common" ]
    target  = entry[ "target" ]
    people  = [ ( target, target ) ] + [ ( case, case ) for case in entry[ "cases" ] if case[ "id" ] != target[ "id" ] ]
    asks    = []
    for item, _ in people:
        ask_part  = item.get( "ask", {} )
        responded = datetime.fromisoformat( item[ "responded_at" ] )
        asked     = datetime.fromisoformat( ask_part.get( "asked_at", item.get( "asked_at", ( responded - timedelta( minutes=1 ) ).isoformat() ) ) )
        message   = ask_part.get( "message", item.get( "message", f"Should the synthetic worker {item[ 'id' ]} proceed?" ) )
        title     = ask_part.get( "title", item.get( "title", f"Worker {item[ 'id' ]}" ) )
        category, _ = engine.classifier.classify( message, sender_id=common[ "sender_id" ] )
        ask = {
            "id": item[ "id" ], "question": message, "category": category, "decision_value": item[ "answer" ],
            "ratification_state": "not_required", "data_origin": "organic", "response_type": common[ "response_type" ],
            "question_embedding": basis_vector( item[ "axis" ], common[ "norm" ] ), "created_at": "2026-11-10", "owner_user_id": OWNER,
            "answer_source": "human", "responded_at": responded, "title": title, "message": message,
            "sender_id": common[ "sender_id" ], "asked_at": asked, "recipient_id": OWNER, "response_options": None,
            "actual_value": item[ "answer" ],
        }
        if "versions" in item: ask[ "versions" ] = item[ "versions" ]
        if item is target and "notification_final_state" in item: ask.update( { f"final_{key}": value for key, value in item[ "notification_final_state" ].items() } )
        asks.append( ask )
    return asks, target[ "id" ]


def _neighbours( run, asks, ask_id ):
    """
    Read the neighbour ids the engine used for one ask.

    Requires:
        - ask_id names an ask that was replayed

    Ensures:
        - returns the ids in the engine's evidence order
    """
    index  = [ ask[ "id" ] for ask in asks ].index( ask_id )
    record = next( r for r in run[ "records" ][ ENGINE_ARM ] if r[ "frozen_index" ] == index )
    return record[ "meta" ][ "neighbour_ids" ]


class _CapturingStore( TimeSlicedDecisionStore ):
    """A time-sliced store that remembers the rows it was built from."""

    built = []

    def __init__( self, cases ):
        cases = list( cases )
        type( self ).built.append( cases )
        super().__init__( cases )


def test_eventual_answer_late_answers_never_reach_the_forecast( engine ):
    entry        = load_fixture()[ "classes" ][ "eventual_answer" ]
    asks, target = _asks_for( engine, "eventual_answer" )
    run          = replay( asks, engine, SHA )
    neighbours   = _neighbours( run, asks, target )
    assert sorted( neighbours ) == sorted( entry[ "expected_neighbour_ids_at_ask_time" ] )
    assert not set( neighbours ) & set( entry[ "forbidden_ids" ] )
    late = "eventual-late-by-ten-minutes"
    assert target in _neighbours( run, asks, late ), "control: an ask made after the target does see its answer"


def test_later_status_the_store_is_given_the_value_the_case_had_at_the_ask( engine ):
    entry        = load_fixture()[ "classes" ][ "later_status" ]
    asks, target = _asks_for( engine, "later_status" )
    _CapturingStore.built = []
    replay( asks, engine, SHA, store_factory=_CapturingStore )
    index   = [ ask[ "id" ] for ask in asks ].index( target )
    ordered = sorted( range( len( asks ) ), key=lambda i: ( asks[ i ][ "asked_at" ], i ) )
    rows    = _CapturingStore.built[ [ i for i in ordered if asks[ i ][ "question_embedding" ] is not None ].index( index ) ]
    by_id   = { row[ "id" ]: row for row in rows }
    wanted  = entry[ "expected_as_of_ask_time" ][ "status-revised-after-the-ask" ]
    final   = entry[ "forbidden_final_values" ][ "status-revised-after-the-ask" ]
    revised = by_id[ "status-revised-after-the-ask" ]
    assert { "answer": revised[ "decision_value" ], "ratification_state": revised[ "ratification_state" ] } == wanted
    assert wanted != final
    assert "versions" not in revised


def test_later_status_a_case_the_loader_cannot_rebuild_is_left_out_and_counted( engine ):
    entry        = load_fixture()[ "classes" ][ "later_status" ]
    asks, target = _asks_for( engine, "later_status" )
    run          = replay( asks, engine, SHA )
    neighbours   = _neighbours( run, asks, target )
    assert "status-unrebuildable" not in neighbours
    assert sorted( neighbours ) == sorted( entry[ "expected_neighbour_ids_at_ask_time" ] )
    assert not set( neighbours ) & set( entry[ "forbidden_ids" ] )
    assert run[ "unrebuildable_cases" ] == len( entry[ "loader_excluded_and_counted_ids" ] )


def test_later_status_rows_as_of_names_the_unrebuildable_case_for_the_target_ask( engine ):
    asks, target = _asks_for( engine, "later_status" )
    ask          = next( a for a in asks if a[ "id" ] == target )
    rows, lost   = rows_as_of( asks, ask[ "asked_at" ] )
    assert lost == load_fixture()[ "classes" ][ "later_status" ][ "loader_excluded_and_counted_ids" ]
    assert "status-unrebuildable" not in [ row[ "id" ] for row in rows ]


def test_final_notification_state_never_reaches_what_the_engine_is_handed( engine ):
    entry        = load_fixture()[ "classes" ][ "final_notification_state" ]
    asks, target = _asks_for( engine, "final_notification_state" )
    handed       = []
    real_predict = engine.predict
    engine.predict = lambda notification, query_vector=None: ( handed.append( json.dumps( [ notification, query_vector is not None ], default=str ) ), real_predict( notification, query_vector=query_vector ) )[ 1 ]
    run          = replay( asks, engine, SHA )
    assert handed, "the engine was called"
    everything = "".join( handed ) + json.dumps( run, default=str )
    for sentinel in entry[ "forbidden_sentinels" ]:
        assert sentinel not in everything, sentinel
    assert any( sentinel in json.dumps( asks, default=str ) for sentinel in entry[ "forbidden_sentinels" ] ), "control: the sentinels are on the ask"


def test_own_stored_case_and_its_retry_group_are_left_out_of_the_neighbours( engine ):
    entry        = load_fixture()[ "classes" ][ "own_stored_case" ]
    asks, target = _asks_for( engine, "own_stored_case" )
    run          = replay( asks, engine, SHA )
    neighbours   = _neighbours( run, asks, target )
    assert neighbours == entry[ "expected_neighbour_ids_at_ask_time" ]
    assert not set( neighbours ) & set( entry[ "forbidden_ids" ] )
    assert "own-case-retry-copy" in entry[ "loop_forbidden_ids" ]


def test_eventual_answer_the_baseline_arm_ignores_cases_answered_after_the_ask( engine ):
    entry        = load_fixture()[ "classes" ][ "eventual_answer" ]
    asks, target = _asks_for( engine, "eventual_answer" )
    run          = replay( asks, engine, SHA )
    index        = [ ask[ "id" ] for ask in asks ].index( target )
    record       = next( r for r in run[ "records" ][ "prior_majority" ] if r[ "frozen_index" ] == index )
    assert record[ "meta" ][ "forecast" ] == entry[ "prior_majority_baseline_at_ask_time" ]
    assert record[ "meta" ][ "forecast" ] != entry[ "prior_majority_baseline_if_late_answers_leaked" ]
