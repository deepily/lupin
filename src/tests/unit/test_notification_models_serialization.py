"""
Sender parsing, the multiple-choice validator, and the `to_api_params` optional
tail in `notification_models` — row `e2099400`.

WHY THESE. Three unrelated-looking blocks were dark (lines 62-63, 94-108,
309-332, 418-439) and they share one property: **each is the last place a
mistake is cheap.** Everything here happens between a caller building a request
and the bytes going on the wire. A field dropped in `to_api_params` is not a
crash — the notification is delivered without it, and whatever depended on it
simply never happens.

WHAT IS PINNED:

· **`parse_sender_id` never raises and always returns all five keys.** It is fed
  ids that came off the wire, including malformed ones. Its contract is that a
  garbage input yields `"unknown"` rather than an exception, and callers index
  the result directly.

· **The `#session_id` suffix splits from the RIGHT.** `rsplit` matters: an
  agent name containing a `#` would otherwise take the session id with it.

· **The multiple-choice validator's rejections, one at a time.** Nine distinct
  raises, each reached by its own malformed payload. A validator tested only on
  a valid input proves nothing about a validator, which exists entirely for the
  invalid ones.

· **Its rejections are SCOPED TO THE RESPONSE TYPE.** The same malformed
  payload passes for a `yes_no` ask and fails for a `multiple_choice` one. A
  validator that fired unconditionally would reject legitimate requests, and one
  that never fired would be invisible — the pair distinguishes them.

· **Every optional field in `to_api_params` is carried when set and ABSENT when
  not** — not present-and-null. The endpoint reads query params; a `None` that
  became the string "None" would be a silently wrong value rather than a missing
  one.

· **The two booleans serialize as the string "true" and vanish when False.**
  They are query params, not JSON.

· **`sender_id` is resolved explicit-first, then from the message prefix.** The
  prefix extraction is what stamps a notification with its project, and a wrong
  precedence here would let a `[LUPIN]` prefix overwrite a caller's deliberate
  sender.

· **`to_api_params` refuses to serialize an unresolved `target_user`** rather
  than sending a notification to nobody.

See: row e2099400
"""

import json

import pytest
from pydantic import ValidationError

from lupin_cli.notifications.notification_models import (
    NotificationRequest,
    ResponseType,
    extract_sender_from_message,
    parse_sender_id,
    resolve_target_user,
)


def _request( **overrides ):
    base = dict( message="Approve?", response_type=ResponseType.YES_NO,
                 target_user="someone@example.com" )
    base.update( overrides )
    return NotificationRequest( **base )


class TestExtractSenderFromMessage:

    def test_a_bracket_prefix_becomes_a_project_scoped_sender( self ):
        assert extract_sender_from_message( "[LUPIN] Build complete" ) == \
               "claude.code@lupin.deepily.ai"

    def test_the_project_is_lowercased( self ):
        assert extract_sender_from_message( "[COSA] done" ).startswith( "claude.code@cosa." )

    def test_the_agent_type_is_substitutable( self ):
        assert extract_sender_from_message( "[LUPIN] done", "deep.research" ) == \
               "deep.research@lupin.deepily.ai"

    def test_no_prefix_yields_none_rather_than_a_guess( self ):
        assert extract_sender_from_message( "No prefix here" ) is None

    def test_a_prefix_that_is_not_at_the_start_is_not_a_prefix( self ):
        assert extract_sender_from_message( "Build [LUPIN] complete" ) is None

    def test_a_lowercase_or_mixed_bracket_is_not_a_prefix( self ):
        """The pattern is uppercase-only on purpose — arbitrary bracketed text
        in a message must not be read as a project name."""
        assert extract_sender_from_message( "[lupin] done" ) is None
        assert extract_sender_from_message( "[Lupin] done" ) is None

    def test_an_empty_message_yields_none( self ):
        assert extract_sender_from_message( "" ) is None


class TestParseSenderId:
    """Fed ids that came off the wire. Contract: never raises, always five keys."""

    def test_the_old_format_parses_with_a_null_session_id( self ):
        parsed = parse_sender_id( "claude.code@lupin.deepily.ai" )
        assert parsed[ "agent_type" ] == "claude.code"
        assert parsed[ "project" ]    == "lupin"
        assert parsed[ "session_id" ] is None

    def test_the_new_format_carries_the_session_id( self ):
        parsed = parse_sender_id( "claude.code@lupin.deepily.ai#a1b2c3d4" )
        assert parsed[ "session_id" ]     == "a1b2c3d4"
        assert parsed[ "base_sender_id" ] == "claude.code@lupin.deepily.ai"
        assert parsed[ "full_sender_id" ] == "claude.code@lupin.deepily.ai#a1b2c3d4"

    def test_the_session_suffix_splits_from_the_right( self ):
        """An agent name containing a '#' would otherwise take the session id
        with it and both fields would be wrong."""
        parsed = parse_sender_id( "weird#agent@lupin.deepily.ai#sess99" )
        assert parsed[ "session_id" ]     == "sess99"
        assert parsed[ "base_sender_id" ] == "weird#agent@lupin.deepily.ai"

    def test_a_malformed_id_yields_unknown_rather_than_raising( self ):
        parsed = parse_sender_id( "not-an-address" )
        assert parsed[ "agent_type" ] == "unknown"
        assert parsed[ "project" ]    == "unknown"

    def test_an_empty_id_yields_unknown_rather_than_raising( self ):
        parsed = parse_sender_id( "" )
        assert parsed[ "agent_type" ] == "unknown"

    def test_the_full_id_is_echoed_back_even_when_unparseable( self ):
        """Callers log it. Losing the original on the failure path is losing the
        only evidence of what arrived."""
        assert parse_sender_id( "garbage" )[ "full_sender_id" ] == "garbage"

    def test_every_result_carries_all_five_keys( self ):
        """Callers index the dict directly; a missing key is a KeyError at the
        call site rather than a handled parse failure."""
        for sid in ( "claude.code@lupin.deepily.ai", "a@b.c#s", "garbage", "" ):
            assert set( parse_sender_id( sid ) ) == {
                "agent_type", "project", "session_id", "full_sender_id", "base_sender_id" }


_VALID_MC = { "questions": [ {
    "question": "Which?", "header": "Pick", "multi_select": False,
    "options": [ { "label": "A" }, { "label": "B" } ] } ] }


class TestTheMultipleChoiceValidator:
    """It exists entirely for the invalid inputs."""

    def test_a_well_formed_payload_is_accepted( self ):
        req = _request( response_type=ResponseType.MULTIPLE_CHOICE,
                        response_options=_VALID_MC )
        assert req.response_options == _VALID_MC

    def test_none_is_always_accepted( self ):
        assert _request( response_type=ResponseType.MULTIPLE_CHOICE,
                         response_options=None ).response_options is None

    @pytest.mark.parametrize( "bad, because", [
        ( { "no_questions": [] },                              "no questions key" ),
        ( { "questions": "not a list" },                       "questions not a list" ),
        ( { "questions": [ "not a dict" ] },                   "question not a dict" ),
        ( { "questions": [ { "options": [ { "label": "A" }, { "label": "B" } ] } ] },
                                                               "question text missing" ),
        ( { "questions": [ { "question": "Q?" } ] },           "options missing" ),
        ( { "questions": [ { "question": "Q?", "options": "nope" } ] },
                                                               "options not a list" ),
        ( { "questions": [ { "question": "Q?", "options": [ { "label": "only one" } ] } ] },
                                                               "fewer than two options" ),
        ( { "questions": [ { "question": "Q?",
                             "options": [ { "label": str( i ) } for i in range( 21 ) ] } ] },
                                                               "more than twenty options" ),
        ( { "questions": [ { "question": "Q?",
                             "options": [ { "label": "A" }, { "no_label": "B" } ] } ] },
                                                               "option without a label" ),
        ( { "questions": [ { "question": "Q?",
                             "options": [ { "label": "A" }, "not a dict" ] } ] },
                                                               "option not a dict" ),
    ] )
    def test_each_malformed_shape_is_rejected( self, bad, because ):
        with pytest.raises( ValidationError ):
            _request( response_type=ResponseType.MULTIPLE_CHOICE, response_options=bad )

    def test_exactly_twenty_options_is_accepted( self ):
        """The boundary. 2-20 inclusive; an off-by-one here rejects a legal ask."""
        payload = { "questions": [ { "question": "Q?",
                    "options": [ { "label": str( i ) } for i in range( 20 ) ] } ] }
        assert _request( response_type=ResponseType.MULTIPLE_CHOICE,
                         response_options=payload ).response_options == payload

    def test_exactly_two_options_is_accepted( self ):
        assert _request( response_type=ResponseType.MULTIPLE_CHOICE,
                         response_options=_VALID_MC ) is not None

    def test_the_same_payload_passes_for_a_different_response_type( self ):
        """THE CONTROL. The checks are scoped to multiple_choice; a validator
        that fired unconditionally would reject legitimate yes_no requests, and
        one that never fired would be invisible."""
        junk = { "anything": "at all" }
        assert _request( response_type=ResponseType.YES_NO,
                         response_options=junk ).response_options == junk
        with pytest.raises( ValidationError ):
            _request( response_type=ResponseType.MULTIPLE_CHOICE, response_options=junk )


class TestTheOpenEndedBatchValidator:

    def test_a_well_formed_batch_is_accepted( self ):
        payload = { "questions": [ { "question": "One?" }, { "question": "Two?" } ] }
        assert _request( response_type=ResponseType.OPEN_ENDED_BATCH,
                         response_options=payload ).response_options == payload

    @pytest.mark.parametrize( "bad", [
        { "no_questions": [] },
        { "questions": "not a list" },
        { "questions": [ "not a dict" ] },
        { "questions": [ { "header": "no question text" } ] },
    ] )
    def test_each_malformed_batch_is_rejected( self, bad ):
        with pytest.raises( ValidationError ):
            _request( response_type=ResponseType.OPEN_ENDED_BATCH, response_options=bad )

    def test_a_batch_question_needs_no_options( self ):
        """Unlike multiple_choice — the difference between the two branches."""
        payload = { "questions": [ { "question": "Free text?" } ] }
        assert _request( response_type=ResponseType.OPEN_ENDED_BATCH,
                         response_options=payload ) is not None


class TestToApiParamsOptionalTail:
    """Absent, not present-and-null. These are query params."""

    def test_unset_optionals_are_absent_entirely( self ):
        params = _request().to_api_params()
        for key in ( "response_default", "human_only", "title", "response_options",
                     "abstract", "session_name", "job_id", "suppress_ding",
                     "display_qualifier_widget", "idempotency_key" ):
            assert key not in params

    @pytest.mark.parametrize( "field, value", [
        ( "title",           "deploy gate" ),
        ( "abstract",        "the long version" ),
        ( "session_name",    "Mr. Radio" ),
        ( "job_id",          "dr-a1b2c3d4" ),
        ( "idempotency_key", "key-123" ),
    ] )
    def test_a_set_optional_is_carried_verbatim( self, field, value ):
        assert _request( **{ field: value } ).to_api_params()[ field ] == value

    def test_response_options_are_json_serialized( self ):
        """They ride a query param, so they have to be a string."""
        params = _request( response_type=ResponseType.MULTIPLE_CHOICE,
                           response_options=_VALID_MC ).to_api_params()
        assert json.loads( params[ "response_options" ] ) == _VALID_MC

    @pytest.mark.parametrize( "flag", [ "human_only", "suppress_ding",
                                        "display_qualifier_widget" ] )
    def test_a_true_flag_serializes_as_the_string_true( self, flag ):
        assert _request( **{ flag: True } ).to_api_params()[ flag ] == "true"

    @pytest.mark.parametrize( "flag", [ "human_only", "suppress_ding",
                                        "display_qualifier_widget" ] )
    def test_a_false_flag_is_omitted_rather_than_sent_as_false( self, flag ):
        """The server and the WebSocket event both default it to False; sending
        the string "false" would be truthy on the far side."""
        assert flag not in _request( **{ flag: False } ).to_api_params()

    def test_an_explicit_sender_id_wins_over_the_message_prefix( self ):
        params = _request( message="[LUPIN] done",
                           sender_id="deep.research@cosa.deepily.ai" ).to_api_params()
        assert params[ "sender_id" ] == "deep.research@cosa.deepily.ai"

    def test_the_message_prefix_supplies_the_sender_when_none_was_given( self ):
        params = _request( message="[LUPIN] done" ).to_api_params()
        assert params[ "sender_id" ] == "claude.code@lupin.deepily.ai"

    def test_no_sender_and_no_prefix_omits_the_field( self ):
        assert "sender_id" not in _request( message="plain message" ).to_api_params()

    def test_the_required_fields_are_always_present( self ):
        params = _request().to_api_params()
        assert params[ "response_requested" ] == "true"
        assert params[ "response_type" ]      == "yes_no"
        assert params[ "target_user" ]        == "someone@example.com"

    def test_an_unresolved_target_user_refuses_to_serialize( self ):
        """Sending this would deliver a notification to nobody, silently."""
        req = _request()
        object.__setattr__( req, "target_user", None )
        with pytest.raises( ValueError, match="target_user is None" ):
            req.to_api_params()


class TestResolveTargetUser:

    def test_an_explicit_value_wins( self, monkeypatch ):
        monkeypatch.setenv( "LUPIN_DEV_EMAIL", "env@example.com" )
        assert resolve_target_user( "explicit@example.com" ) == "explicit@example.com"

    def test_the_env_var_is_used_next( self, monkeypatch ):
        monkeypatch.setenv( "LUPIN_DEV_EMAIL", "env@example.com" )
        assert resolve_target_user() == "env@example.com"

    def test_it_fails_loud_when_nothing_resolves( self, monkeypatch ):
        """Silently defaulting would send someone else's notifications to a
        stranger; there is no safe fallback recipient."""
        monkeypatch.delenv( "LUPIN_DEV_EMAIL", raising=False )
        import cosa.utils.config_loader as loader
        monkeypatch.setattr( loader, "get_api_config", lambda env: {} )
        with pytest.raises( ValueError, match="Cannot resolve target_user" ):
            resolve_target_user()

    def test_a_broken_config_still_fails_loud_rather_than_raising_its_own_error( self, monkeypatch ):
        monkeypatch.delenv( "LUPIN_DEV_EMAIL", raising=False )
        import cosa.utils.config_loader as loader
        def boom( env ): raise RuntimeError( "no config file" )
        monkeypatch.setattr( loader, "get_api_config", boom )
        with pytest.raises( ValueError, match="Cannot resolve target_user" ):
            resolve_target_user()
