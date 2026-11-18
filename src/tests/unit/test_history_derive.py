"""
The derived history keeps every row, decodes each answer and names its actor.

Each row below is shaped like a stored notification. The real-data check is in the `local_data` file.
"""

import json

import pytest

import cosa.agents.prediction_engine.history_derive as hd
from cosa.agents.prediction_engine.history_derive import attribution_tier, derive_answer, derive_dataset, write_dataset

RECIPIENT = "0cf47e2d-d5a1-4cd4-addf-79810fd32b15"


def raw( id="n1", response_type="yes_no", value=None, created_at="2026-11-01T10:00:00Z", message="Approve the fix?", **extra ):
    """One stored notification, built so a test names only what it varies."""
    row = { "id": id, "recipient_id": RECIPIENT, "sender_id": "claude.code@lupin.deepily.ai#aaaa1111", "title": "Approve", "message": message,
            "response_type": response_type, "state": "responded", "created_at": created_at, "thread_id": None, "job_id": None,
            "reply_to": None, "response_options": None, "response_value": value }
    row.update( extra )
    return row


def answered( text, source="ui", user=RECIPIENT ):
    """A stored response_value in the common envelope."""
    return { "value": text, "source": source, "answered_by": { "method": "jwt", "user_id": user } if user else None }


@pytest.mark.parametrize( "value, tier", [
    ( None,                                  "none" ),
    ( "bare string",                         "none" ),
    ( answered( "yes", source="timeout_default" ), "timeout_default" ),
    ( answered( "yes", user=None ),          "unknown_actor" ),
    ( answered( "yes" ),                     "recipient" ),
    ( answered( "yes", user="someone-else" ), "other_account" ),
] )
def test_the_attribution_tier_names_who_answered( value, tier ):
    assert attribution_tier( raw( value=value ) ) == tier


def test_a_yes_no_answer_gives_its_stance_and_qualifier():
    got, failure = derive_answer( raw( value=answered( "no [comment: not ready]" ) ) )
    assert ( got, failure ) == ( { "kind": "stance", "stance": "no", "qualifier": "not ready" }, None )


def test_a_yes_no_value_that_is_not_a_stance_is_kept_as_unread_text():
    got, failure = derive_answer( raw( value=answered( "yes, but later" ) ) )
    assert ( got, failure ) == ( { "kind": "unread", "text": "yes, but later" }, "stance_not_recognised" )


def test_a_non_string_yes_no_value_is_unread_not_guessed():
    got, failure = derive_answer( raw( value={ "value": 7 } ) )
    assert ( got[ "kind" ], failure ) == ( "unread", "stance_not_recognised" )


def test_a_multiple_choice_answer_is_read_per_field_from_the_json_under_value():
    stored = answered( json.dumps( { "answers": { "Pick one": "A", "Pick many": [ "x", "y" ] } } ) )
    got, failure = derive_answer( raw( response_type="multiple_choice", value=stored ) )
    assert failure is None
    assert got[ "fields" ][ "Pick one" ][ "selected" ] == [ "A" ]
    assert got[ "fields" ][ "Pick many" ][ "mode" ] == "multi"


def test_a_batch_answer_that_is_not_an_answers_map_is_unread():
    got, failure = derive_answer( raw( response_type="open_ended_batch", value=answered( "plain words" ) ) )
    assert ( got, failure ) == ( { "kind": "unread", "text": "plain words" }, "fields_not_readable" )


def test_an_open_ended_answer_keeps_its_text_and_a_row_with_no_answer_is_none():
    assert derive_answer( raw( response_type="open_ended", value=answered( "write it up" ) ) ) == ( { "kind": "text", "text": "write it up" }, None )
    assert derive_answer( raw( value=None ) ) == ( { "kind": "none" }, None )


def test_the_dataset_has_one_example_per_row_and_drops_none_even_a_retry_copy():
    rows = [ raw( id="a", value=answered( "yes" ) ), raw( id="b", created_at="2026-11-01T10:05:00Z", value=answered( "yes" ) ), raw( id="c", value=None, message="Other?" ) ]
    derived, counts = derive_dataset( rows )
    assert [ d[ "notification_id" ] for d in derived ] == [ "a", "b", "c" ]
    assert [ d[ "is_retry_copy" ] for d in derived ] == [ False, True, False ]
    assert ( counts[ "rows" ], counts[ "answered" ], counts[ "tiers" ] ) == ( 3, 2, { "recipient": 2, "none": 1 } )


def test_a_parse_failure_is_counted_by_reason():
    _, counts = derive_dataset( [ raw( value=answered( "perhaps" ) ), raw( id="n2", message="B?", value=answered( "perhaps" ) ) ] )
    assert counts[ "unread_by_reason" ] == { "stance_not_recognised": 2 }


def test_the_derived_row_keeps_the_ids_a_context_rebuild_reads_and_its_versions():
    row = raw( thread_id="t1", job_id="j1", reply_to="p1", response_options={ "questions": [ { "header": "h" } ] }, value=answered( "yes" ) )
    got = derive_dataset( [ row ] )[ 0 ][ 0 ]
    assert ( got[ "sender_id" ], got[ "thread_id" ], got[ "job_id" ], got[ "reply_to" ] ) == ( row[ "sender_id" ], "t1", "j1", "p1" )
    assert ( got[ "schema_version" ], got[ "backfill_version" ], got[ "source_pointer" ], got[ "has_offered_schema" ] ) == ( 1, "opl-history-1", "notifications:n1", True )


def test_the_dataset_is_written_verified_and_reproduced_byte_for_byte( tmp_path ):
    rows  = [ raw( id="a", value=answered( "yes" ) ), raw( id="b", message="Other?", value=None ) ]
    first = write_dataset( rows, str( tmp_path / "one" ) )
    again = write_dataset( rows, str( tmp_path / "two" ) )
    assert ( first[ "originals_sha256" ], first[ "derived_sha256" ] ) == ( again[ "originals_sha256" ], again[ "derived_sha256" ] )
    assert [ json.loads( line ) for line in open( tmp_path / "one" / "originals.jsonl" ) ] == rows


def test_no_original_rows_is_refused():
    with pytest.raises( ValueError, match="no original rows" ):
        write_dataset( [], "/nonexistent" )


def test_a_file_that_fails_its_check_is_refused_by_name( tmp_path, monkeypatch ):
    monkeypatch.setattr( hd, "verify_snapshot", lambda snapshot, manifest: ( False, "row count 1 != manifest 2" ) )
    with pytest.raises( ValueError, match="originals.jsonl failed its check: row count" ):
        write_dataset( [ raw( value=None ) ], str( tmp_path ) )
