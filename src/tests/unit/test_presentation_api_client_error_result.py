#!/usr/bin/env python3
"""
Regression: an error ResultMessage must reach the log and the raised failure.

A smoke run (Pocholo's verdict file, cc-error-result, in io/tmp) failed three jobs with only "Claude Code returned an error result: success". The CLI's own
text (`ResultMessage.result`, set when `is_error` is true) was never read, so no log held the cause.
"""

import asyncio
import logging
from unittest.mock import patch

import pytest

import cosa.agents.presentation_generator.api_client as ac
from cosa.agents.presentation_generator.api_client import PresentationAPIClient


class _FakeTextBlock:
    def __init__( self, text ): self.text = text


class _FakeAssistantMessage:
    def __init__( self, content ): self.content = content


class _FakeResultMessage:
    def __init__( self, subtype="success", is_error=False, result=None, errors=None, usage=None, total_cost_usd=None, stop_reason="end_turn" ):
        self.subtype        = subtype
        self.is_error       = is_error
        self.result         = result
        self.errors         = errors
        self.usage          = usage
        self.total_cost_usd = total_cost_usd
        self.stop_reason    = stop_reason


def _call( messages, then_raise=None ):
    async def _gen( prompt, options ):
        for m in messages: yield m
        if then_raise is not None: raise then_raise
    client = PresentationAPIClient()
    with patch.multiple( ac, AssistantMessage=_FakeAssistantMessage, TextBlock=_FakeTextBlock, ResultMessage=_FakeResultMessage ), \
         patch.object( ac, "sdk_query", _gen ):
        return asyncio.run( client._call_api( model="m", system_prompt="SYS", user_message="hi", call_type="narrative" ) )


ERROR = _FakeResultMessage( subtype="success", is_error=True, result="Your credit balance is too low to continue" )


def test_an_error_result_raises_with_the_cli_text_and_the_subtype():
    with pytest.raises( Exception ) as raised:
        _call( [ ERROR ] )
    assert "Your credit balance is too low to continue" in str( raised.value )
    assert "success" in str( raised.value )


def test_an_error_result_is_logged_with_the_cli_text_and_the_call_type( caplog ):
    with caplog.at_level( logging.ERROR, logger=ac.logger.name ):
        with pytest.raises( Exception ):
            _call( [ ERROR ] )
    assert any( "Your credit balance is too low" in r.getMessage() and "narrative" in r.getMessage() for r in caplog.records )


def test_an_error_result_with_no_text_still_raises_and_says_none():
    with pytest.raises( Exception ) as raised:
        _call( [ _FakeResultMessage( subtype="error_max_turns", is_error=True, result=None ) ] )
    assert "error_max_turns" in str( raised.value )
    assert "no text" in str( raised.value )


def test_a_long_error_text_is_cut_to_500_characters():
    with pytest.raises( Exception ) as raised:
        _call( [ _FakeResultMessage( is_error=True, result="x" * 5000 ) ] )
    assert "x" * 500 in str( raised.value )
    assert "x" * 501 not in str( raised.value )


def test_a_clean_result_still_returns_its_text():
    out = _call( [ _FakeAssistantMessage( [ _FakeTextBlock( "fine" ) ] ), _FakeResultMessage() ] )
    assert out.content == "fine"


SDK_RERAISE = Exception( "Claude Code returned an error result: success" )


def test_the_incident_path_names_the_cli_text_when_the_sdk_re_raises_after_the_result():
    """SDK 0.2.88 yields the error result, then re-raises with the subtype only."""
    with pytest.raises( Exception ) as raised:
        _call( [ ERROR ], then_raise=SDK_RERAISE )
    assert "Your credit balance is too low to continue" in str( raised.value )


def test_an_exception_with_no_result_before_it_passes_through_unchanged():
    with pytest.raises( Exception ) as raised:
        _call( [ _FakeAssistantMessage( [ _FakeTextBlock( "x" ) ] ) ], then_raise=SDK_RERAISE )
    assert raised.value is SDK_RERAISE


def test_the_errors_list_of_an_error_result_is_named_beside_the_text():
    with pytest.raises( Exception ) as raised:
        _call( [ _FakeResultMessage( subtype="error_during_execution", is_error=True, result=None, errors=[ "tool died", "disk full" ] ) ] )
    assert "tool died; disk full" in str( raised.value )
