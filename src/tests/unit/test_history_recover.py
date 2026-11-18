"""
Recovery by response family: each answered ask is read in the shape of its family.

Each row below is shaped like a stored notification. The real-data check is in the `local_data` file.
"""

import json

import pytest

from cosa.agents.prediction_engine.history_derive import asks_of, derive_dataset
from cosa.agents.prediction_engine.history_recover import STATUSES, offered_fields, recover_by_family, recover_example

RECIPIENT = "0cf47e2d-d5a1-4cd4-addf-79810fd32b15"

OFFER = { "questions": [ { "question": "Which database?", "header": "DB", "multi_select": False, "options": [ { "label": "PostgreSQL" }, { "label": "SQLite" } ] },
                         { "question": "Which extras?", "header": "Tags", "multi_select": True, "options": [ { "label": "x" }, { "label": "y" } ] } ] }


def raw( id="n1", response_type="yes_no", value=None, created_at="2026-11-01T10:00:00Z", title="Approve", message="Approve the fix?", options=None ):
    """One stored notification, built so a test names only what it varies."""
    return { "id": id, "recipient_id": RECIPIENT, "sender_id": "claude.code@lupin.deepily.ai#aaaa1111", "title": title, "message": message,
             "response_type": response_type, "state": "responded", "created_at": created_at, "thread_id": None, "job_id": None,
             "reply_to": None, "response_options": options, "response_value": value }


def answered( text ):
    """A stored response_value in the common envelope."""
    return { "value": text, "source": "ui", "answered_by": { "method": "jwt", "user_id": RECIPIENT } }


def one( row, state="reconstructed" ):
    """Derive one row and recover it."""
    example = derive_dataset( [ row ] )[ 0 ][ 0 ]
    return recover_example( row, example, state )


def test_a_qualified_yes_keeps_its_comment_and_a_bare_yes_is_not_qualified():
    got = one( raw( value=answered( "yes [comment: after lunch]" ) ) )
    assert ( got[ "status" ], got[ "recovered" ] ) == ( "recovered", { "stance": "yes", "qualified": True, "qualifier": "after lunch" } )
    assert one( raw( value=answered( "yes" ) ) )[ "recovered" ] == { "stance": "yes", "qualified": False, "qualifier": None }


def test_a_neither_answer_is_recovered_from_its_raw_string():
    assert one( raw( value=answered( "neither [comment: re-frame it]" ) ) )[ "recovered" ][ "stance" ] == "neither"


def test_a_yes_no_string_that_is_not_a_stance_is_unread_with_its_text():
    got = one( raw( value=answered( "yes, but later" ) ) )
    assert ( got[ "status" ], got[ "recovered" ] ) == ( "unread", { "text": "yes, but later" } )


def test_a_row_with_no_stored_answer_is_no_answer_and_recovers_nothing():
    got = one( raw( value=None ) )
    assert ( got[ "status" ], got[ "recovered" ] ) == ( "no_answer", None )


def test_the_offered_fields_are_read_in_order_with_their_option_labels():
    assert offered_fields( raw( options=OFFER ) ) == {
        "DB"  : { "question": "Which database?", "multi_select": False, "options": [ "PostgreSQL", "SQLite" ] },
        "Tags": { "question": "Which extras?",    "multi_select": True,  "options": [ "x", "y" ] } }
    assert list( offered_fields( raw( options=OFFER ) ) ) == [ "DB", "Tags" ]


@pytest.mark.parametrize( "options", [ None, {}, { "timeout": 5 }, { "questions": None } ] )
def test_a_row_that_offered_no_questions_has_no_offered_fields( options ):
    assert offered_fields( raw( options=options ) ) == {}


def test_a_multiple_choice_pick_is_checked_against_the_options_that_were_offered():
    stored = answered( json.dumps( { "answers": { "DB": "PostgreSQL", "Tags": [ "x", "y" ] } } ) )
    got    = one( raw( response_type="multiple_choice", value=stored, options=OFFER ) )
    assert got[ "status" ] == "recovered"
    assert got[ "recovered" ][ "fields" ] == {
        "DB"  : { "prompt": "Which database?", "offered": [ "PostgreSQL", "SQLite" ], "selected": [ "PostgreSQL" ], "in_offer": True },
        "Tags": { "prompt": "Which extras?",    "offered": [ "x", "y" ],              "selected": [ "x", "y" ],     "in_offer": True } }


def test_a_write_in_is_not_in_the_offer_and_the_whole_pick_stays_recovered():
    stored = answered( json.dumps( { "answers": { "DB": "DuckDB" } } ) )
    got    = one( raw( response_type="multiple_choice", value=stored, options=OFFER ) )
    assert ( got[ "status" ], got[ "recovered" ][ "fields" ][ "DB" ][ "in_offer" ] ) == ( "recovered", False )


def test_one_wrong_pick_among_many_makes_the_multi_select_not_in_the_offer():
    stored = answered( json.dumps( { "answers": { "Tags": [ "x", "z" ] } } ) )
    assert one( raw( response_type="multiple_choice", value=stored, options=OFFER ) )[ "recovered" ][ "fields" ][ "Tags" ][ "in_offer" ] is False


def test_an_empty_multi_select_is_in_the_offer_because_no_pick_is_outside_it():
    stored = answered( json.dumps( { "answers": { "Tags": [] } } ) )
    assert one( raw( response_type="multiple_choice", value=stored, options=OFFER ) )[ "recovered" ][ "fields" ][ "Tags" ][ "in_offer" ] is True


def test_a_header_nobody_offered_makes_the_recovery_partial_and_leaves_its_prompt_empty():
    stored = answered( json.dumps( { "answers": { "DB": "SQLite", "Colour": "red" } } ) )
    got    = one( raw( response_type="multiple_choice", value=stored, options=OFFER ) )
    assert got[ "status" ] == "partial"
    assert got[ "recovered" ][ "fields" ][ "Colour" ] == { "prompt": None, "offered": None, "selected": [ "red" ], "in_offer": None }


def test_a_field_answer_with_no_offered_schema_is_no_offer_and_keeps_the_picks():
    stored = answered( json.dumps( { "answers": { "DB": "SQLite" } } ) )
    got    = one( raw( response_type="multiple_choice", value=stored, options=None ) )
    assert ( got[ "status" ], got[ "recovered" ][ "fields" ][ "DB" ] ) == ( "no_offer", { "prompt": None, "offered": None, "selected": [ "SQLite" ], "in_offer": None } )


def test_a_batch_answer_pairs_each_field_prompt_with_its_answer():
    stored = answered( json.dumps( { "answers": { "DB": "SQLite" } } ) )
    got    = one( raw( response_type="open_ended_batch", value=stored, options=OFFER ) )
    assert ( got[ "response_type" ], got[ "recovered" ][ "fields" ][ "DB" ][ "prompt" ] ) == ( "open_ended_batch", "Which database?" )


def test_an_unreadable_field_answer_is_unread_not_guessed():
    got = one( raw( response_type="multiple_choice", value=answered( "not json" ), options=OFFER ) )
    assert ( got[ "status" ], got[ "recovered" ] ) == ( "unread", { "text": "not json" } )


def test_an_open_ended_answer_is_paired_with_its_prompt_and_context_state_and_waits_for_review():
    got = one( raw( response_type="open_ended", value=answered( "use the staging box" ), message="Where should it run?" ), state="ambiguous_only" )
    assert got[ "recovered" ] == { "prompt": "Where should it run?", "response": "use the staging box", "context_state": "ambiguous_only", "reviewed": False }


def test_the_ask_dicts_carry_exactly_what_classify_asks_reads():
    assert asks_of( [ raw( title="T", message="M" ) ] ) == [ { "response_type": "yes_no", "category": None, "title": "T", "message": "M",
                                                                  "sender_id": "claude.code@lupin.deepily.ai#aaaa1111", "asked_at": "2026-11-01T10:00:00Z" } ]


def _batch():
    """Four rows: two yes/no in one family, a multiple choice, and an unanswered yes/no."""
    rows = [ raw( id="a", value=answered( "yes" ), created_at="2026-11-01T10:00:00Z", title="Approve", message="Approve fix 1?" ),
             raw( id="b", value=answered( "no" ),  created_at="2026-11-01T12:00:00Z", title="Approve", message="Approve fix 2?" ),
             raw( id="c", response_type="multiple_choice", value=answered( json.dumps( { "answers": { "DB": "SQLite" } } ) ), options=OFFER, title="Pick" ),
             raw( id="d", value=None, title="Ship", message="Ship it?" ) ]
    derived = derive_dataset( rows )[ 0 ]
    return rows, derived, { r[ "id" ]: "reconstructed" for r in rows }


def test_every_row_is_counted_once_and_each_response_types_statuses_sum_to_its_rows():
    rows, derived, states = _batch()
    recovered, counts     = recover_by_family( rows, derived, states )
    assert [ r[ "notification_id" ] for r in recovered ] == [ "a", "b", "c", "d" ]
    assert { t: c[ "rows" ] for t, c in counts.items() } == { "yes_no": 3, "multiple_choice": 1 }
    for c in counts.values(): assert sum( c[ "statuses" ].values() ) == c[ "rows" ]
    assert counts[ "yes_no" ][ "statuses" ] == { "recovered": 2, "partial": 0, "no_offer": 0, "unread": 0, "no_answer": 1 }
    assert all( set( c[ "statuses" ] ) == set( STATUSES ) for c in counts.values() )


def test_the_rows_are_grouped_by_the_normalised_title_of_the_family_key():
    rows, derived, states = _batch()
    families = recover_by_family( rows, derived, states )[ 1 ][ "yes_no" ][ "families" ]
    assert { name: f[ "rows" ] for name, f in families.items() } == { "approve": 2, "ship": 1 }


def test_a_mismatched_pair_of_lists_is_refused_by_length():
    rows, derived, states = _batch()
    with pytest.raises( ValueError, match="4 rows but derived has 3" ): recover_by_family( rows, derived[ :3 ], states )


def test_an_example_with_no_context_state_is_named_in_the_error():
    rows, derived, states = _batch()
    del states[ "b" ]
    with pytest.raises( KeyError, match="b" ): recover_by_family( rows, derived, states )


def test_the_option_labels_keep_the_order_they_were_offered_in_not_alphabetical():
    offer = { "questions": [ { "question": "Which first?", "header": "Order", "multi_select": False, "options": [ { "label": "Zulu" }, { "label": "Alpha" }, { "label": "Mike" } ] } ] }
    assert offered_fields( raw( options=offer ) )[ "Order" ][ "options" ] == [ "Zulu", "Alpha", "Mike" ]
