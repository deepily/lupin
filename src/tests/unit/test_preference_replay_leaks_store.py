#!/usr/bin/env python3
"""
Named leak fixtures run against the time-sliced case store.

Each class plants a case the store must not show at ask time. The store is
queried by cosine and by dot. A control advances past every answer, so the
assertion can fail.

Requires:
    - src/tests/unit/fixtures/preference_replay_leaks/leak_fixtures.json
    - cosa.research.preference_replay.time_sliced_store
"""

import json
from datetime import datetime, timedelta

import pytest

from cosa.research.preference_replay.time_sliced_store import TimeSlicedDecisionStore
from tests.helpers.preference_leak_fixture import basis_vector, load_fixture


CLASS_NAMES = [ "eventual_answer", "later_status", "final_notification_state", "own_stored_case" ]

STORE_VISIBLE_KEY = { "eventual_answer": "expected_neighbour_ids_at_ask_time", "later_status": "store_visible_ids_at_ask_time",
                      "final_notification_state": "expected_neighbour_ids_at_ask_time", "own_stored_case": "store_visible_ids_at_ask_time" }

STORE_FORBIDDEN_KEY = { "eventual_answer": "forbidden_ids", "later_status": "store_forbidden_ids",
                        "final_notification_state": "forbidden_ids", "own_stored_case": "store_forbidden_ids" }




def _store_for( name ):
    """
    Build the store and the query for one fixture class.

    Requires:
        - name is a key of the fixture's classes

    Ensures:
        - returns ( store, query_vector, ask_time ) with the store not yet advanced
    """
    data   = load_fixture()
    entry  = data[ "classes" ][ name ]
    common = data[ "common" ]
    cases  = []
    for case in entry[ "cases" ]:
        cases.append( { "id": case[ "id" ], "question": case[ "id" ], "category": common[ "category" ], "decision_value": case[ "answer" ],
                        "ratification_state": "not_required", "data_origin": "organic", "response_type": common[ "response_type" ],
                        "question_embedding": basis_vector( case[ "axis" ], common[ "norm" ] ), "created_at": "2026-11-01",
                        "owner_user_id": None, "answer_source": "human", "responded_at": datetime.fromisoformat( case[ "responded_at" ] ) } )
    target = entry[ "target" ]
    return TimeSlicedDecisionStore( cases ), basis_vector( target[ "axis" ], common[ "norm" ] ), datetime.fromisoformat( target[ "asked_at" ] )


def _ids( store, query, metric, category ):
    """
    List the ids of the neighbours above a half-way floor.

    Requires:
        - store has been advanced

    Ensures:
        - returns ids strongest first; an orthogonal case scores 0 and is dropped
    """
    return [ record[ "id" ] for _, record in store.find_similar( query, category=category, limit=10, threshold=0.5, metric=metric ) ]


@pytest.mark.parametrize( "metric", [ "cosine", "dot" ] )
@pytest.mark.parametrize( "name", CLASS_NAMES )
def test_the_planted_leak_is_absent_and_the_knowable_cases_are_present( name, metric ):
    entry                  = load_fixture()[ "classes" ][ name ]
    store, query, ask_time = _store_for( name )
    store.advance_to( ask_time )
    ids       = _ids( store, query, metric, load_fixture()[ "common" ][ "category" ] )
    expected  = entry[ STORE_VISIBLE_KEY[ name ] ]
    forbidden = entry[ STORE_FORBIDDEN_KEY[ name ] ]
    assert sorted( ids ) == sorted( expected ), ( name, metric )
    assert not set( ids ) & set( forbidden ), ( name, metric )


@pytest.mark.parametrize( "name", [ "eventual_answer", "later_status", "own_stored_case" ] )
def test_control_the_planted_case_appears_once_the_clock_passes_its_answer( name ):
    entry                  = load_fixture()[ "classes" ][ name ]
    store, query, ask_time = _store_for( name )
    store.advance_to( ask_time + timedelta( days = 1 ) )
    ids = _ids( store, query, "cosine", load_fixture()[ "common" ][ "category" ] )
    assert set( entry[ STORE_FORBIDDEN_KEY[ name ] ] ) <= set( ids ), "the instrument can see a leak when there is one"


def test_the_visible_set_at_the_ask_is_exactly_what_the_fixture_says_for_every_class():
    for name in CLASS_NAMES:
        entry                  = load_fixture()[ "classes" ][ name ]
        store, _, ask_time     = _store_for( name )
        store.advance_to( ask_time )
        knowable = set( store.visible_ids() ) - set( [ c[ "id" ] for c in entry[ "cases" ] if c[ "axis" ] != entry[ "target" ][ "axis" ] ] )
        assert knowable == set( entry[ STORE_VISIBLE_KEY[ name ] ] ), name


def test_the_final_state_class_gives_the_store_no_field_that_could_carry_the_sentinels():
    entry              = load_fixture()[ "classes" ][ "final_notification_state" ]
    store, query, ask  = _store_for( "final_notification_state" )
    store.advance_to( ask )
    results = store.find_similar( query, category=load_fixture()[ "common" ][ "category" ], limit=10, threshold=0.0 )
    text    = json.dumps( [ record for _, record in results ], default=str )
    assert results, "the store returned records to inspect"
    assert not any( sentinel in text for sentinel in entry[ "forbidden_sentinels" ] )
