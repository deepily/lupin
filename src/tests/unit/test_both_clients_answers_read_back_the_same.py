"""
BOTH CLIENTS' ANSWERS READ BACK THE SAME — P0 5ebd2aff, found by Mr. Radio 2026-09-10 (row 4311c503).

`/api/notify/response` stores what `_stored_response_dict` makes of the request body, and every
reader takes the answer out with `.get( "value" )` (`_extract_response_value` here; the
`notify_user_sync` poll does the same inline). The multiplexer's Action Required card used to send
`response_value: { response: "yes" }`, which was stored as sent and read back as no answer, so a
promotion ask answered from the multiplexer was refused.

These tests put each client's REAL request body through the server's own wrap and reader:
  - legacy notifications.js sends the bare answer (submitResponse, notifications.js:24015), and
    JSON.stringify( { answers } ) for multiple choice and batch (:23451, :23855);
  - the multiplexer now sends a string answer bare (ActionRequiredStore.toWireResponseValue,
    pinned by action_required_store.test.ts).

⚠️ Multiple choice and batch from the multiplexer are NOT covered yet: that client does not parse
response_options.questions, so it has no header to key an answer by. Step 2 on 5ebd2aff.
"""

import json

from cosa.rest.routers.notifications import _extract_response_value, _stored_response_dict


def _read_back( request_response_value ):
    """
    What a reader sees after the server stores this request body's response_value.

    Requires:
        - request_response_value is a str or dict, as a client puts it on the wire

    Ensures:
        - returns the string `_extract_response_value` yields for the stored record
    """
    return _extract_response_value( _stored_response_dict( request_response_value ) )


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


def test_the_old_multiplexer_wrapper_reads_back_as_no_answer():
    """
    The control: the shape this fix removed. If it ever read back as "yes", the tests above
    could pass for the wrong reason.
    """
    assert _read_back( { "response": "yes" } ) != "yes"


def test_a_dict_that_already_carries_value_is_stored_as_sent():
    body = { "value": "no", "source": "api" }
    assert _stored_response_dict( body ) is body
    assert _read_back( body ) == "no"
