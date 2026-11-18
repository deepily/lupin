"""
parse_field_selections reads a multiple-choice or batch answer as one record per field.

Each case names the shape it pins. The synthetic export supplies the write-ins and the
free text, so the round trip is checked against committed data, not a hand-built answer.
"""

import json
from pathlib import Path

import pytest

from cosa.utils.notification_utils import parse_field_selections

EXPORT = Path( __file__ ).resolve().parents[ 1 ] / "fixtures" / "preference_learning" / "synthetic-export.json"


def _answers( payload ):
    """The JSON string the router stores for an answers map."""
    return json.dumps( { "answers": payload } )


def test_a_single_pick_is_a_one_item_list():
    got = parse_field_selections( _answers( { "DB": "PostgreSQL" } ) )
    assert got == { "DB": { "mode": "single", "selected": [ "PostgreSQL" ], "text": "PostgreSQL" } }


def test_a_multi_select_keeps_every_pick_in_order_and_strips_each():
    got = parse_field_selections( _answers( { "Features": [ " Auth", "Caching " ] } ) )
    assert got[ "Features" ] == { "mode": "multi", "selected": [ "Auth", "Caching" ], "text": None }


def test_an_empty_multi_select_is_a_legal_empty_set():
    got = parse_field_selections( _answers( { "Tags": [] } ) )
    assert got == { "Tags": { "mode": "multi", "selected": [], "text": None } }


def test_a_blank_string_is_an_empty_selection_but_keeps_its_text():
    got = parse_field_selections( _answers( { "Tags": "" } ) )
    assert got[ "Tags" ] == { "mode": "single", "selected": [], "text": "" }


def test_mixed_select_modes_come_back_per_field_in_the_order_given():
    got = parse_field_selections( _answers( { "Venue": "Staging box", "Tags": [ "a", "b" ], "Note": "free text" } ) )
    assert list( got ) == [ "Venue", "Tags", "Note" ]
    assert [ got[ h ][ "mode" ] for h in got ] == [ "single", "multi", "single" ]


def test_non_string_list_items_and_values_are_kept_as_given_or_as_text():
    got = parse_field_selections( _answers( { "Pick": [ 1, "x" ], "Count": 3 } ) )
    assert got[ "Pick" ][ "selected" ] == [ 1, "x" ]
    assert got[ "Count" ] == { "mode": "single", "selected": [ "3" ], "text": "3" }


@pytest.mark.parametrize( "value, stance, qualifier", [
    ( "yes",                          "yes",     None ),
    ( "no [comment: not ready]",      "no",      "not ready" ),
    ( "neither [comment: re-frame]",  "neither", "re-frame" ),
] )
def test_the_three_stances_carry_a_stance_and_qualifier( value, stance, qualifier ):
    got = parse_field_selections( _answers( { "Go": value } ) )[ "Go" ]
    assert ( got[ "stance" ], got[ "qualifier" ] ) == ( stance, qualifier )


def test_a_string_that_is_not_a_stance_has_no_stance_keys():
    got = parse_field_selections( _answers( { "Go": "Maybe later" } ) )[ "Go" ]
    assert "stance" not in got and "qualifier" not in got


def test_a_dict_is_accepted_as_well_as_a_json_string():
    assert parse_field_selections( { "answers": { "DB": "PG" } } )[ "DB" ][ "selected" ] == [ "PG" ]


def test_an_empty_answers_map_is_an_empty_result_not_none():
    assert parse_field_selections( _answers( {} ) ) == {}


def test_an_answers_map_stored_as_json_under_value_is_read_through_the_wrapper():
    wrapped = json.dumps( { "value": json.dumps( { "answers": { "DB": "PG", "Tags": [ "a" ] } } ) } )
    got     = parse_field_selections( wrapped )
    assert ( got[ "DB" ][ "selected" ], got[ "Tags" ][ "mode" ] ) == ( [ "PG" ], "multi" )


def test_a_cancelled_answer_stored_under_value_is_an_empty_result():
    assert parse_field_selections( { "value": '{"cancelled":true,"answers":{}}' } ) == {}


@pytest.mark.parametrize( "value", [
    None, "", "   ", "not json", "[1, 2]", "42", json.dumps( { "value": "yes" } ), json.dumps( { "value": "not json" } ),
    json.dumps( { "answers": "yes" } ), json.dumps( { "answers": [ "a" ] } ), 7,
] )
def test_anything_that_is_not_an_answers_map_is_none( value ):
    assert parse_field_selections( value ) is None


def test_every_multiple_choice_answer_in_the_synthetic_export_round_trips():
    rows = [ r for r in json.loads( EXPORT.read_text() )[ "predictions" ] if r[ "response_type" ] == "multiple_choice" ]
    assert len( rows ) == 9
    for row in rows:
        got = parse_field_selections( row[ "actual" ] )
        assert got is not None and list( got ) == list( row[ "actual" ][ "answers" ] )
        for header, value in row[ "actual" ][ "answers" ].items():
            assert got[ header ][ "text" ] == value
