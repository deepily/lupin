#!/usr/bin/env python3
"""
Self-consistency of the committed synthetic leak fixtures for the replay.

One named leak per class: eventual answer, later status, final notification
state and the target's own stored case. These tests check the data only.

Requires:
    - src/tests/unit/fixtures/preference_replay_leaks/leak_fixtures.json
"""

import json
from datetime import datetime
from pathlib import Path

import pytest

FIXTURE = Path( __file__ ).parent / "fixtures" / "preference_replay_leaks" / "leak_fixtures.json"

CLASS_NAMES = [ "eventual_answer", "later_status", "final_notification_state", "own_stored_case" ]


def _load():
    """
    Load the fixture file.

    Requires:
        - the fixture file exists

    Ensures:
        - returns the parsed dict
    """
    return json.loads( FIXTURE.read_text() )


def _when( text ):
    """
    Parse an ISO time with offset.

    Requires:
        - text is an ISO-8601 string with a UTC offset

    Ensures:
        - returns a timezone-aware datetime
    """
    return datetime.fromisoformat( text )


def test_the_fixture_is_synthetic_and_names_exactly_the_four_classes():
    data = _load()
    assert data[ "synthetic" ] is True
    assert sorted( data[ "classes" ].keys() ) == sorted( CLASS_NAMES )


@pytest.mark.parametrize( "name", CLASS_NAMES )
def test_every_class_asks_before_it_is_answered_and_names_a_leak( name ):
    entry  = _load()[ "classes" ][ name ]
    target = entry[ "target" ]
    assert _when( target[ "asked_at" ] ) < _when( target[ "responded_at" ] )
    assert entry[ "leak" ].strip() != ""
    assert entry[ "expected_neighbour_ids_at_ask_time" ], f"{name} expects at least one neighbour"


@pytest.mark.parametrize( "name", CLASS_NAMES )
def test_expected_and_forbidden_ids_are_cases_and_never_overlap( name ):
    entry    = _load()[ "classes" ][ name ]
    case_ids = [ case[ "id" ] for case in entry[ "cases" ] ]
    assert len( case_ids ) == len( set( case_ids ) ), "case ids are unique"
    expected = entry[ "expected_neighbour_ids_at_ask_time" ]
    forbidden = entry[ "forbidden_ids" ]
    assert set( expected ) <= set( case_ids )
    assert set( forbidden ) <= set( case_ids )
    assert not set( expected ) & set( forbidden )


def test_eventual_answer_expected_cases_were_answered_by_the_ask_and_forbidden_after():
    entry = _load()[ "classes" ][ "eventual_answer" ]
    asked = _when( entry[ "target" ][ "asked_at" ] )
    by_id = { case[ "id" ]: case for case in entry[ "cases" ] }
    for case_id in entry[ "expected_neighbour_ids_at_ask_time" ]:
        assert _when( by_id[ case_id ][ "responded_at" ] ) <= asked, case_id
    assert len( entry[ "forbidden_ids" ] ) == 2
    for case_id in entry[ "forbidden_ids" ]:
        assert _when( by_id[ case_id ][ "responded_at" ] ) > asked, case_id
    boundary = by_id[ "eventual-legit-at-the-ask" ]
    assert _when( boundary[ "responded_at" ] ) == asked, "one case sits exactly on the ask time"


def test_eventual_answer_has_a_decoy_on_another_axis_that_is_not_expected():
    entry  = _load()[ "classes" ][ "eventual_answer" ]
    axis   = entry[ "target" ][ "axis" ]
    decoys = [ case for case in entry[ "cases" ] if case[ "axis" ] != axis ]
    assert [ case[ "id" ] for case in decoys ] == [ "eventual-decoy-other-topic" ]
    assert "eventual-decoy-other-topic" not in entry[ "expected_neighbour_ids_at_ask_time" ]


def test_later_status_the_as_of_ask_value_differs_from_the_final_value():
    entry  = _load()[ "classes" ][ "later_status" ]
    asked  = _when( entry[ "target" ][ "asked_at" ] )
    by_id  = { case[ "id" ]: case for case in entry[ "cases" ] }
    case   = by_id[ "status-revised-after-the-ask" ]
    known  = [ version for version in case[ "versions" ] if _when( version[ "at" ] ) <= asked ]
    as_of  = known[ -1 ]
    final  = case[ "versions" ][ -1 ]
    wanted = entry[ "expected_as_of_ask_time" ][ "status-revised-after-the-ask" ]
    assert { "answer": as_of[ "answer" ], "ratification_state": as_of[ "ratification_state" ] } == wanted
    assert { "answer": final[ "answer" ], "ratification_state": final[ "ratification_state" ] } == entry[ "forbidden_final_values" ][ "status-revised-after-the-ask" ]
    assert wanted != entry[ "forbidden_final_values" ][ "status-revised-after-the-ask" ]
    assert case[ "answer" ] == final[ "answer" ], "the case's stored top-level answer is the final one, the trap"


def test_later_status_a_case_first_answered_after_the_ask_is_forbidden():
    entry = _load()[ "classes" ][ "later_status" ]
    asked = _when( entry[ "target" ][ "asked_at" ] )
    case  = [ c for c in entry[ "cases" ] if c[ "id" ] == "status-answered-after-the-ask" ][ 0 ]
    assert _when( case[ "versions" ][ 0 ][ "at" ] ) > asked
    assert entry[ "store_forbidden_ids" ] == [ "status-answered-after-the-ask" ]
    assert entry[ "forbidden_ids" ] == [ "status-answered-after-the-ask", "status-unrebuildable" ]


def test_later_status_an_unrebuildable_case_was_answered_before_the_ask_and_has_no_history():
    entry = _load()[ "classes" ][ "later_status" ]
    asked = _when( entry[ "target" ][ "asked_at" ] )
    case  = [ c for c in entry[ "cases" ] if c[ "id" ] == "status-unrebuildable" ][ 0 ]
    assert _when( case[ "responded_at" ] ) <= asked
    assert case[ "versions" ] == [] and case[ "ratification_state_final" ] == "rejected"
    assert entry[ "loader_excluded_and_counted_ids" ] == [ "status-unrebuildable" ]


def test_final_state_sentinels_all_sit_in_the_targets_final_state_and_nowhere_else():
    entry     = _load()[ "classes" ][ "final_notification_state" ]
    final     = entry[ "target" ][ "notification_final_state" ]
    sentinels = entry[ "forbidden_sentinels" ]
    assert sorted( sentinels ) == sorted( final.values() )
    assert all( s.startswith( "LEAK-SENTINEL-" ) for s in sentinels )
    outside = json.dumps( [ entry[ "cases" ], entry[ "expected_neighbour_ids_at_ask_time" ] ] )
    assert not any( s in outside for s in sentinels )


def test_own_case_has_the_targets_id_and_vector_and_arrives_after_the_ask():
    entry  = _load()[ "classes" ][ "own_stored_case" ]
    target = entry[ "target" ]
    own    = [ c for c in entry[ "cases" ] if c[ "id" ] == target[ "id" ] ][ 0 ]
    assert own[ "axis" ] == target[ "axis" ]
    assert _when( own[ "responded_at" ] ) == _when( target[ "responded_at" ] )
    assert _when( own[ "responded_at" ] ) > _when( target[ "asked_at" ] )


def test_own_case_retry_copy_is_inside_ten_minutes_and_the_sibling_is_outside():
    entry  = _load()[ "classes" ][ "own_stored_case" ]
    target = entry[ "target" ]
    by_id  = { case[ "id" ]: case for case in entry[ "cases" ] }
    gap    = lambda case_id: ( _when( target[ "asked_at" ] ) - _when( by_id[ case_id ][ "ask" ][ "asked_at" ] ) ).total_seconds()
    assert 0 < gap( "own-case-retry-copy" ) <= 600
    assert gap( "own-case-legit-family-sibling" ) > 600
    for case_id in [ "own-case-retry-copy", "own-case-legit-family-sibling" ]:
        assert by_id[ case_id ][ "ask" ][ "message" ] == target[ "message" ]
    assert entry[ "forbidden_ids" ] == [ "t-own-case", "own-case-retry-copy" ]


def test_every_axis_is_a_valid_basis_index_for_a_768_dimension_vector():
    data = _load()
    axes = []
    for entry in data[ "classes" ].values():
        axes.append( entry[ "target" ][ "axis" ] )
        axes.extend( case[ "axis" ] for case in entry[ "cases" ] )
    assert axes and all( 0 <= axis < 768 for axis in axes )
    assert 5.0 <= data[ "common" ][ "norm" ] <= 60.0
