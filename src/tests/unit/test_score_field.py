"""
score_field and compare_multiple_choice score a card field by field, by the stored schema.

Each case names the shape it pins. The card below mixes a single-select and a multi-select
field, which the answer-scanning dispatch could not score.
"""

import pytest

from cosa.agents.prediction_engine.accuracy_comparators import (
    compare_multiple_choice,
    confidence_band,
    get_comparator,
    score_field,
)

SINGLE = { "header": "DB", "multi_select": False }
MULTI  = { "header": "Features", "multi_select": True }
CARD   = { "questions": [ SINGLE, MULTI ] }


def test_a_single_select_field_is_exact_on_the_same_pick():
    got = score_field( SINGLE, "PG", "PG" )
    assert ( got[ "mode" ], got[ "exact" ], got[ "jaccard" ] ) == ( "single", True, None )


def test_a_single_select_field_is_not_exact_on_another_pick():
    assert score_field( SINGLE, "MySQL", "PG" )[ "exact" ] is False


def test_a_multi_select_field_is_exact_on_the_same_set_in_any_order():
    got = score_field( MULTI, [ "B", "A" ], [ "A", "B" ] )
    assert ( got[ "mode" ], got[ "exact" ], got[ "jaccard" ] ) == ( "multi", True, 1.0 )
    assert got[ "predicted" ] == [ "A", "B" ]


def test_a_multi_select_field_overlap_is_scored_but_not_exact():
    got = score_field( MULTI, [ "A", "B" ], [ "A", "C" ] )
    assert ( got[ "exact" ], got[ "jaccard" ] ) == ( False, 0.333 )


def test_two_empty_sets_are_an_exact_match_with_full_overlap():
    got = score_field( MULTI, [], [] )
    assert ( got[ "exact" ], got[ "jaccard" ] ) == ( True, 1.0 )


def test_a_missing_prediction_is_an_empty_set_not_a_crash():
    got = score_field( MULTI, None, [ "A" ] )
    assert ( got[ "exact" ], got[ "jaccard" ], got[ "predicted" ] ) == ( False, 0.0, [] )


def test_the_schema_decides_the_mode_not_the_shape_of_the_answer():
    assert score_field( MULTI, "A", "A" )[ "mode" ] == "multi"
    assert score_field( SINGLE, [ "A" ], [ "A" ] )[ "mode" ] == "single"


def test_a_write_in_is_scored_as_its_own_text():
    assert score_field( SINGLE, "A hybrid mode", "A hybrid mode" )[ "exact" ] is True
    assert score_field( SINGLE, "Hybrid", "A hybrid mode" )[ "exact" ] is False


def test_a_half_right_mixed_card_is_not_a_match_and_scores_one_of_two():
    predicted = { "answers": { "DB": "PG", "Features": [ "A", "B" ] } }
    actual    = { "answers": { "DB": "PG", "Features": [ "A", "C" ] } }
    match, detail = compare_multiple_choice( predicted, actual, CARD )
    assert match is False
    assert ( detail[ "matches" ], detail[ "total" ] ) == ( 1, 2 )
    assert [ f[ "header" ] for f in detail[ "fields" ] ] == [ "DB", "Features" ]
    assert [ f[ "exact" ] for f in detail[ "fields" ] ] == [ True, False ]


def test_a_fully_right_mixed_card_is_a_match():
    answers = { "answers": { "DB": "PG", "Features": [ "B", "A" ] } }
    match, detail = compare_multiple_choice( answers, { "answers": { "DB": "PG", "Features": [ "A", "B" ] } }, CARD )
    assert ( match, detail[ "matches" ], detail[ "total" ] ) == ( True, 2, 2 )


def test_a_header_the_schema_does_not_list_is_scored_as_single_select():
    match, detail = compare_multiple_choice( { "answers": { "Other": "x" } }, { "answers": { "Other": "x" } }, CARD )
    assert ( match, detail[ "fields" ][ 0 ][ "mode" ] ) == ( True, "single" )


def test_a_card_with_no_questions_still_scores_by_single_select():
    match, _ = compare_multiple_choice( { "answers": { "A": "1" } }, { "answers": { "A": "2" } }, {} )
    assert match is False


@pytest.mark.parametrize( "predicted, actual, reason", [
    ( None,                         { "answers": { "A": "1" } }, "missing_data" ),
    ( { "answers": { "A": "1" } },  None,                        "missing_data" ),
    ( { "answers": {} },            { "answers": { "A": "1" } }, "empty_answers" ),
    ( { "answers": { "A": "1" } },  { "answers": {} },           "empty_answers" ),
] )
def test_a_missing_or_empty_side_is_not_scored( predicted, actual, reason ):
    assert compare_multiple_choice( predicted, actual, CARD ) == ( None, { "reason": reason } )


def test_the_schema_dispatch_ignores_the_shape_of_the_answers():
    comparator = get_comparator( "multiple_choice", response_options=CARD )
    assert comparator.func is compare_multiple_choice
    assert comparator( { "answers": { "DB": "PG" } }, { "answers": { "DB": "PG" } } )[ 0 ] is True


@pytest.mark.parametrize( "confidence, band", [
    ( 0.0, 0.0 ), ( 0.39, 0.0 ),
    ( 0.4, 0.4 ), ( 0.59, 0.4 ),
    ( 0.6, 0.6 ), ( 0.79, 0.6 ),
    ( 0.8, 0.8 ), ( 0.99, 0.8 ), ( 1.0, 0.8 ),
] )
def test_each_confidence_band_edge_belongs_to_the_band_that_starts_there( confidence, band ):
    assert confidence_band( confidence ) == band


@pytest.mark.parametrize( "confidence", [ -0.01, 1.01 ] )
def test_a_confidence_outside_zero_to_one_has_no_band( confidence ):
    assert confidence_band( confidence ) is None


@pytest.mark.parametrize( "confidence", [ None, float( "nan" ), float( "inf" ), float( "-inf" ) ] )
def test_a_confidence_that_is_missing_or_not_finite_has_no_band( confidence ):
    assert confidence_band( confidence ) is None


@pytest.mark.parametrize( "schema", [
    "not a dict", [ { "header": "DB" } ], 7,
    { "questions": "DB" }, { "questions": { "header": "DB" } },
    { "questions": [ "DB" ] }, { "questions": [ { "multi_select": True } ] }, { "questions": [ { "header": 3 } ] },
    { "questions": [ { "header": "DB" }, None ] },
] )
def test_a_malformed_stored_schema_still_scores_the_card_and_names_the_reason( schema ):
    answers = { "answers": { "DB": "PG" } }
    match, detail = compare_multiple_choice( answers, answers, schema )
    assert ( match, detail[ "schema_reason" ], detail[ "fields" ][ 0 ][ "mode" ] ) == ( True, "malformed_schema", "single" )


@pytest.mark.parametrize( "schema", [ "not a dict", { "questions": "DB" }, { "questions": [ { "multi_select": True } ] } ] )
def test_a_malformed_schema_does_not_hide_a_wrong_answer( schema ):
    match, detail = compare_multiple_choice( { "answers": { "DB": "PG" } }, { "answers": { "DB": "MySQL" } }, schema )
    assert ( match, detail[ "matches" ], detail[ "total" ] ) == ( False, 0, 1 )


@pytest.mark.parametrize( "schema", [ {}, { "questions": [] }, { "other": 1 } ] )
def test_a_schema_with_no_questions_is_valid_and_scores_every_field_as_a_single_select( schema ):
    answers = { "answers": { "DB": "PG" } }
    match, detail = compare_multiple_choice( answers, answers, schema )
    assert ( match, "schema_reason" in detail ) == ( True, False )
