"""
BOTH CLIENTS' ANSWERS READ BACK THE SAME — P0 5ebd2aff, found by Mr. Radio 2026-09-10 (row 4311c503).

`/api/notify/response` stores what `_stored_response_dict` makes of the request body, and every
reader takes the answer out with `.get( "value" )` (`_extract_response_value` here; the
`notify_user_sync` poll does the same inline). The multiplexer's Action Required card used to send
`response_value: { response: "yes" }`, which was stored as sent and read back as no answer, so a
promotion ask answered from the multiplexer was refused.

These tests put each client's REAL request body through the server's own wrap and reader:
  - legacy notifications.js sends the bare answer (submitResponse, notifications.js:24015), and
    JSON.stringify( { answers } ) for multiple choice and batch (:23855, :23451);
  - the multiplexer sends exactly the same (ActionRequiredStore.toWireResponseValue, pinned by
    action_required_store.test.ts).

Step 2: a multiple-choice or batch answer from the multiplexer is `wire_value` in
src/tests/unit/multiplexer/fixtures/action_required_questions_payload.json — the string the TS store test
asserts the client POSTs. Here it goes through the wrap and then the asker's own reader:
cosa_voice_mcp._parse_multiple_choice_response and _parse_open_ended_batch_response.
"""

import json

import cosa.utils.util as cu
from cosa.rest.routers.notifications import _extract_response_value, _stored_response_dict
from lupin_mcp.cosa_voice_mcp import _parse_multiple_choice_response, _parse_open_ended_batch_response

FIXTURE_PATH = cu.get_project_root() + "/src/tests/unit/multiplexer/fixtures/action_required_questions_payload.json"

READERS = {
    "multiple_choice"  : _parse_multiple_choice_response,
    "open_ended_batch" : _parse_open_ended_batch_response,
}


def _read_back( request_response_value ):
    """
    What a reader sees after the server stores this request body's response_value.

    Requires:
        - request_response_value is a str or dict, as a client puts it on the wire

    Ensures:
        - returns the string `_extract_response_value` yields for the stored record
    """
    return _extract_response_value( _stored_response_dict( request_response_value ) )


def _fixture():
    """
    Load the fixture the multiplexer tests read.

    Requires:
        - FIXTURE_PATH exists and holds JSON

    Ensures:
        - returns the parsed fixture dict
    """
    with open( FIXTURE_PATH, encoding="utf-8" ) as f:
        return json.load( f )


def test_a_bare_string_is_stored_under_value():
    assert _stored_response_dict( "yes" ) == { "value": "yes", "source": "ui" }


def test_legacy_and_multiplexer_yes_no_answers_read_back_identically():
    legacy_body      = "yes"   # notifications.js submitResponse( id, "yes" )
    multiplexer_body = "yes"   # ActionRequiredStore.toWireResponseValue( "yes" )
    assert _read_back( legacy_body ) == "yes"
    assert _read_back( multiplexer_body ) == _read_back( legacy_body )


def test_a_legacy_multiple_choice_answer_reads_back_as_its_json():
    body = json.dumps( { "answers": { "Pick": "a" } } )   # JSON.stringify( { answers } )
    assert json.loads( _read_back( body ) ) == { "answers": { "Pick": "a" } }


def test_a_multiplexer_multiple_choice_or_batch_answer_reaches_the_askers_reader():
    # The literal answers, written out here rather than read back from the fixture, so a fixture
    # that drifted together with its own expectation cannot pass this test.
    literal_answers = {
        "multiple_choice"  : { "answers": { "Database": "PostgreSQL", "Features": [ "Search", "Audit log" ] } },
        "open_ended_batch" : { "answers": { "Topic": "quantum computing", "Budget": "no limit" } },
    }
    for name, parse in READERS.items():
        case             = _fixture()[ name ]
        multiplexer_body = case[ "wire_value" ]              # toWireResponseValue( { answers } ), pinned byte for byte in response_questions.test.ts
        legacy_body      = json.dumps( case[ "answers" ] )   # JSON.stringify( { answers } ), spacing aside
        assert parse( _read_back( multiplexer_body ) ) == literal_answers[ name ], name
        assert parse( _read_back( multiplexer_body ) ) == parse( _read_back( legacy_body ) ), name


def test_the_old_multiplexer_wrapper_reads_back_as_no_answer():
    """
    The control: the shape this fix removed. If it ever read back as the answer, the tests above
    could pass for the wrong reason.
    """
    assert _read_back( { "response": "yes" } ) != "yes"
    for name, parse in READERS.items():
        answers = _fixture()[ name ][ "answers" ]
        assert parse( _read_back( { "response": answers } ) ) != answers, name


def test_a_dict_that_already_carries_value_is_stored_as_sent():
    body = { "value": "no", "source": "api" }
    assert _stored_response_dict( body ) is body
    assert _read_back( body ) == "no"
