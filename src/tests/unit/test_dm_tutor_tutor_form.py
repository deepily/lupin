#!/usr/bin/env python3
"""
Unit tests for the DM tutor's rewrite path in cosa.agents.dm_tutor.tutor.

The attribution and quantity guards have their own files. This one pins the rest.
That covers what counts as an ask and which slot spec reaches the prompt.
It also covers how a raw reply is cut down to a rewrite and each reason the gate gives.
The last part is how the retry loop reports a failure.
Every model call is a stub, so nothing leaves the process.
"""

from unittest.mock import patch

import pytest

from cosa.agents.dm_tutor import tutor
from cosa.agents.dm_tutor.tutor import (
    CANNED_PS, LIMIT, MAX_TOKENS,
    _asks_something, _attempt, build_prompt, extract, gate, literal_violations, rewrite_to_form,
)

LONG = ( "The build is green. The suite passed. The cache was cleared. "
         "The branch was merged. The log is clean." )
ASKING = LONG + " Can you confirm?"
GOOD   = "The build is green. The cache was cleared."


class _Client:
    """Stub model: returns the queued replies in order and records every call."""
    def __init__( self, *replies ):
        self.replies = list( replies )
        self.calls   = []

    def run( self, prompt, **kwargs ):
        self.calls.append( ( prompt, kwargs ) )
        reply = self.replies.pop( 0 )
        if isinstance( reply, Exception ): raise reply
        return reply


class TestAsksSomething:

    @pytest.mark.parametrize( "text", [
        "Is it done?",
        "Please check the log.",
        "Let me know when it lands.",
        "Tell me which one you want.",
        "All good here, confirm when you can.",
    ] )
    def test_an_ask_is_seen( self, text ):
        assert _asks_something( text ) is True

    @pytest.mark.parametrize( "text", [
        "The build is green.",
        "Done. " + CANNED_PS,
    ] )
    def test_a_statement_and_the_canned_ps_ask_nothing( self, text ):
        assert _asks_something( text ) is False


class TestBuildPrompt:

    @pytest.mark.parametrize( "body", [ "", "   \n" ] )
    def test_a_blank_body_is_refused( self, body ):
        with pytest.raises( ValueError, match="body is empty" ):
            build_prompt( body )

    def test_a_telling_body_gets_the_headline_spec_with_the_body_in_place( self ):
        prompt = build_prompt( LONG )
        assert tutor.SPEC_TELL in prompt
        assert LONG in prompt
        assert "{slot_spec}" not in prompt and "{body}" not in prompt

    @pytest.mark.parametrize( "mode,spec", [
        ( "lead2",    tutor.SPEC_ASK ),
        ( "inside2",  tutor.SPEC_ASK_INSIDE ),
        ( "outside2", tutor.SPEC_ASK_OUTSIDE ),
    ] )
    def test_an_asking_body_gets_exactly_one_ask_spec( self, mode, spec ):
        prompt = build_prompt( ASKING, ask_outside=mode )
        assert spec in prompt
        assert tutor.SPEC_TELL not in prompt
        others = { tutor.SPEC_ASK, tutor.SPEC_ASK_INSIDE, tutor.SPEC_ASK_OUTSIDE } - { spec }
        assert not any( o in prompt for o in others )

    @pytest.mark.parametrize( "mode", [ "lead2", "inside2", "outside2" ] )
    def test_a_telling_body_gets_the_headline_spec_in_every_two_slot_mode( self, mode ):
        assert tutor.SPEC_TELL in build_prompt( LONG, ask_outside=mode )

    @pytest.mark.parametrize( "mode,rule", [
        ( "inside",  tutor.ASK_INSIDE ),
        ( "outside", tutor.ASK_OUTSIDE ),
        ( "lead",    tutor.ASK_AS_LEAD ),
        ( True,      tutor.ASK_OUTSIDE ),
        ( False,     tutor.ASK_INSIDE ),
    ] )
    def test_the_older_modes_append_their_rule_to_the_headline_spec( self, mode, rule ):
        prompt = build_prompt( ASKING, ask_outside=mode )
        assert tutor.SPEC_TELL in prompt
        assert rule in prompt

    def test_braces_in_the_body_are_left_alone( self ):
        prompt = build_prompt( "use {slot_spec} and {braces} here" )
        assert "use {slot_spec} and {braces} here" in prompt


class TestExtract:

    @pytest.mark.parametrize( "raw", [ None, "", "  \n " ] )
    def test_nothing_in_nothing_out( self, raw ):
        assert extract( raw ) is None

    def test_a_plain_reply_is_stripped( self ):
        assert extract( "  One. Two.  \n" ) == "One. Two."

    def test_a_lead_in_line_is_dropped( self ):
        assert extract( "Here is the shortened version:\nOne. Two." ) == "One. Two."

    def test_a_reply_that_is_only_a_lead_in_is_nothing( self ):
        assert extract( "Here is the shortened version:" ) is None

    @pytest.mark.parametrize( "marker", [ "## Rewritten Message:", "---", "***", "**Rewritten:**" ] )
    def test_a_second_pass_is_cut_off( self, marker ):
        assert extract( f"One.\nTwo.\n{marker}\nOne.\nTwo." ) == "One.\nTwo."

    def test_a_reply_that_starts_with_a_second_pass_marker_is_nothing( self ):
        assert extract( "## Heading\nOne. Two." ) is None


class TestLiteralViolations:

    def test_the_same_literals_are_clean( self ):
        assert literal_violations( "See a.py on port 8000.", "Port 8000, see a.py." ) == []

    def test_dropping_a_literal_is_legal( self ):
        assert literal_violations( "See a.py on port 8000.", "See a.py." ) == []

    def test_a_changed_value_is_a_literal_that_was_never_sent( self ):
        found = literal_violations( "Port 8000 is up.", "Port 8001 is up." )
        assert any( "8001" in literal and sent == 0 for literal, sent, _ in found )

    def test_repeating_a_literal_more_often_than_sent_is_flagged( self ):
        assert ( "a.py", 1, 2 ) in literal_violations( "See a.py now.", "See a.py, then a.py." )


class TestGate:

    def test_an_empty_rewrite_is_refused( self ):
        assert gate( LONG, "" ) == ( False, "empty rewrite" )
        assert gate( LONG, "  \n" ) == ( False, "empty rewrite" )

    def test_four_sentences_break_the_limit_of_three( self ):
        assert gate( LONG, "One. Two. Three. Four." ) == ( False, f"4 sentences, limit {LIMIT}" )

    def test_an_ask_outside_the_slots_earns_a_fourth_sentence_only_when_the_original_asked( self ):
        rewrite = "The build is green. The cache was cleared. The branch merged. Can you confirm?"
        assert gate( ASKING, rewrite ) == ( False, f"4 sentences, limit {LIMIT}" )
        assert gate( ASKING, rewrite, ask_outside="outside" ) == ( True, None )
        assert gate( ASKING, rewrite, ask_outside=True ) == ( True, None )
        assert gate( LONG, rewrite, ask_outside="outside" ) == ( False, f"4 sentences, limit {LIMIT}" )

    def test_a_rewrite_longer_than_the_original_is_refused( self ):
        ok, reason = gate( "Done. Yes. Ok. Fine.", "The whole entire thing is complete now. Everything works. Nothing else." )
        assert ok is False
        assert reason.startswith( "longer than the original" )

    def test_an_altered_literal_is_refused_and_named( self ):
        original = "The leak is at judge.py:572. The suite ran. Nobody touched it. It shipped. All is well."
        ok, reason = gate( original, "The leak is at judge.py:573. Nobody touched it. All is well." )
        assert ok is False
        assert "literal(s) altered" in reason

    def test_a_position_put_in_a_name_is_refused( self ):
        original = "Rick asked María about the gate. María ran the suite. It passed. It was green. Done."
        ok, reason = gate( original, "María proposes dropping the gate. It passed. Done." )
        assert ok is False
        assert "attributed a position to 'maría'" in reason

    @pytest.mark.parametrize( "rewrite", [
        "Sorry, that is not something I can do. Fine.",
        "I cannot rewrite this. Fine.",
        "As an AI I will not. Fine.",
    ] )
    def test_a_refusal_is_not_a_rewrite( self, rewrite ):
        assert gate( LONG, rewrite ) == ( False, "model refused rather than rewrote" )

    def test_an_echoed_format_example_is_refused( self ):
        assert gate( LONG, "Your three sentences here. More. Done." ) == \
            ( False, "model echoed the format example instead of rewriting" )

    def test_dropping_the_ask_is_refused( self ):
        assert gate( ASKING, GOOD ) == ( False, "the original asked something and the rewrite does not" )

    def test_a_clean_rewrite_passes( self ):
        assert gate( LONG, GOOD ) == ( True, None )
        assert gate( ASKING, GOOD + " Can you confirm?" ) == ( True, None )


class TestAttempt:

    def test_a_call_that_raises_comes_back_as_an_error( self ):
        client = _Client( RuntimeError( "boom" ) )
        assert _attempt( LONG, client ) == ( None, None, "model call failed: RuntimeError: boom" )

    @pytest.mark.parametrize( "raw", [ "", "  ", None ] )
    def test_an_empty_reply_is_reported( self, raw ):
        assert _attempt( LONG, _Client( raw ) ) == ( None, raw, "model returned nothing" )

    def test_a_reply_with_no_rewrite_in_it_is_reported( self ):
        assert _attempt( LONG, _Client( "## Heading" ) ) == ( None, "## Heading", "no rewrite in response" )

    def test_a_good_reply_is_extracted_and_the_call_is_bounded( self ):
        client = _Client( "Here is it:\n" + GOOD )
        assert _attempt( LONG, client ) == ( GOOD, "Here is it:\n" + GOOD, None )
        prompt, kwargs = client.calls[ 0 ]
        assert LONG in prompt
        assert kwargs == { "max_tokens": MAX_TOKENS, "stop": [ "</s>", "</stop>" ] }


class TestRewriteToForm:

    def test_an_empty_body_is_reported( self ):
        assert rewrite_to_form( "  ", client=_Client() ) == ( None, "empty body", None )

    def test_a_body_already_at_the_limit_is_left_alone( self ):
        client = _Client()
        assert rewrite_to_form( "One. Two. Three.", client=client ) == ( None, "under limit: 3 sentences", None )
        assert client.calls == []

    def test_a_good_rewrite_gets_the_canned_ps( self ):
        delivered, error, attempted = rewrite_to_form( LONG, client=_Client( GOOD ) )
        assert delivered == GOOD + "\n\n" + CANNED_PS
        assert error is None
        assert attempted == GOOD

    def test_the_ps_can_be_left_off( self ):
        delivered, _, _ = rewrite_to_form( LONG, client=_Client( GOOD + "  \n" ), append_ps=False )
        assert delivered == GOOD

    def test_a_rejected_rewrite_is_retried_once_by_default( self ):
        client = _Client( "One. Two. Three. Four.", GOOD )
        delivered, error, attempted = rewrite_to_form( LONG, client=client )
        assert delivered == GOOD + "\n\n" + CANNED_PS
        assert len( client.calls ) == 2

    def test_a_rejection_keeps_the_text_it_rejected( self ):
        client = _Client( "One. Two. Three. Four." )
        assert rewrite_to_form( LONG, client=client, retries=0 ) == \
            ( None, f"gate: 4 sentences, limit {LIMIT}", "One. Two. Three. Four." )

    def test_a_model_that_never_answers_reports_its_last_error( self ):
        client = _Client( RuntimeError( "down" ), RuntimeError( "still down" ) )
        assert rewrite_to_form( LONG, client=client ) == \
            ( None, "model call failed: RuntimeError: still down", None )

    def test_a_model_failure_after_a_rejection_still_returns_the_rejected_text( self ):
        client = _Client( "One. Two. Three. Four.", RuntimeError( "down" ) )
        delivered, error, attempted = rewrite_to_form( LONG, client=client )
        assert delivered is None
        assert error == "model call failed: RuntimeError: down"
        assert attempted == "One. Two. Three. Four."

    def test_without_a_client_the_one_for_the_compression_model_is_built( self ):
        stub = _Client( GOOD )
        with patch( "cosa.agents.dm_compression.compressor.DmCompressionAgent" ) as agent_cls, \
             patch( "cosa.agents.llm_client_factory.LlmClientFactory" ) as factory_cls:
            agent_cls.return_value.model_name = "model-x"
            factory_cls.return_value.get_client.return_value = stub
            delivered, error, _ = rewrite_to_form( LONG )
        factory_cls.return_value.get_client.assert_called_once_with( "model-x", debug=False, verbose=False )
        assert delivered == GOOD + "\n\n" + CANNED_PS
        assert error is None
