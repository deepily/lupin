"""
Unit tests for reading a typed forecast in the multiple-choice comparators.

A write-in or a re-frame is kept by parse_full_reply in "fields" but left out of "answers".
"""

import pytest

from cosa.agents.prediction_engine.accuracy_comparators import (
    compare_complete_action_multiple_choice,
    compare_multiple_choice,
    predicted_answers_of,
)

OPTIONS = { "questions": [ { "header": "DB", "options": [ { "label": "Postgres" }, { "label": "SQLite" } ] },
                           { "header": "Mode", "options": [ { "label": "Fast" }, { "label": "Safe" } ] } ] }


def _forecast( answers, fields ):
    return { "answers": answers, "fields": fields }


def test_a_forecast_whose_only_field_is_a_write_in_reads_as_that_text():
    predicted = _forecast( {}, { "DB": { "write_in": "DuckDB" } } )
    assert predicted_answers_of( predicted ) == { "DB": "DuckDB" }


def test_a_reframe_reads_as_its_text_and_a_chosen_label_is_kept_beside_it():
    predicted = _forecast( { "Mode": "Fast" }, { "Mode": { "option_ids": [ "o1" ] }, "DB": { "reframe": "Why a database at all?" } } )
    assert predicted_answers_of( predicted ) == { "Mode": "Fast", "DB": "Why a database at all?" }


def test_an_answers_entry_is_never_replaced_by_a_fields_entry():
    predicted = _forecast( { "DB": "SQLite" }, { "DB": { "write_in": "DuckDB" } } )
    assert predicted_answers_of( predicted ) == { "DB": "SQLite" }


def test_a_forecast_with_no_fields_key_or_a_batch_gist_adds_nothing():
    assert predicted_answers_of( { "answers": { "DB": "SQLite" } } ) == { "DB": "SQLite" }
    assert predicted_answers_of( _forecast( {}, { "DB": { "gist": "text" } } ) ) == {}
    assert predicted_answers_of( _forecast( {}, { "DB": { "option_ids": [ "o1" ] } } ) ) == {}


@pytest.mark.parametrize( "per_field", [ False, True ] )
def test_the_exact_write_in_forecast_is_scored_not_called_empty( per_field ):
    predicted = _forecast( {}, { "DB": { "write_in": "DuckDB" } } )
    match, detail = compare_multiple_choice( predicted, { "answers": { "DB": "DuckDB" } }, OPTIONS, per_field=per_field )
    assert detail.get( "reason" ) != "empty_answers"
    if per_field: assert ( match, detail[ "other_write_in" ] ) == ( None, 1 )   # a typed Other stays outside the score, as live
    else: assert ( match, detail[ "matches" ], detail[ "total" ] ) == ( True, 1, 1 )


def test_a_wrong_write_in_forecast_is_a_miss_when_per_field_is_off():
    match, detail = compare_multiple_choice( _forecast( {}, { "DB": { "write_in": "Mongo" } } ), { "answers": { "DB": "DuckDB" } }, OPTIONS )
    assert ( match, detail[ "matches" ] ) == ( False, 0 )


def test_the_complete_action_measure_passes_the_exact_write_in_and_fails_the_wrong_one():
    actual = { "answers": { "DB": "DuckDB" } }
    assert compare_complete_action_multiple_choice( _forecast( {}, { "DB": { "write_in": "DuckDB" } } ), actual, OPTIONS )[ 0 ] is True
    assert compare_complete_action_multiple_choice( _forecast( {}, { "DB": { "write_in": "Mongo" } } ), actual, OPTIONS )[ 0 ] is False


def test_a_forecast_with_nothing_readable_is_still_an_abstention():
    match, detail = compare_complete_action_multiple_choice( _forecast( {}, { "DB": { "option_ids": [ "o1" ] } } ), { "answers": { "DB": "DuckDB" } }, OPTIONS )
    assert ( match, detail[ "abstained" ] ) == ( False, True )
    assert compare_multiple_choice( _forecast( {}, {} ), { "answers": { "DB": "DuckDB" } }, OPTIONS ) == ( None, { "reason": "empty_answers" } )
