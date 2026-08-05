#!/usr/bin/env python3
"""
Unit tests for cosa.agents.presentation_generator.api_client (BOUNDED-CC path).

The content-phase client was migrated from the direct firewalled Anthropic SDK
to the in-process Claude Agent SDK (`claude_agent_sdk.query`). These tests mock
`sdk_query` at the module boundary — a fake async generator yields fake
AssistantMessage / TextBlock / ResultMessage objects (the SDK message types are
patched into the module so isinstance checks pass). NO real SDK subprocess,
network call, OAuth, or spend occurs.

D6=STRICT: call_with_json_output recovers JSON from chatty output but RAISES on
unrecoverable content (never silent-default).

quick_smoke_test() and __main__ are coverage-excluded.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

import cosa.agents.presentation_generator.api_client as ac
from cosa.agents.presentation_generator.api_client import (
    APIResponse,
    CostEstimate,
    PresentationAPIClient,
    SDK_AVAILABLE,
    _temperature_to_steer,
)


def _run( coro ):
    return asyncio.run( coro )


# ----------------------------------------------------------------------------
# Fake SDK message types + a fake sdk_query async generator
# ----------------------------------------------------------------------------
class _FakeTextBlock:
    def __init__( self, text ):
        self.text = text


class _FakeAssistantMessage:
    def __init__( self, content ):
        self.content = content


class _FakeResultMessage:
    def __init__( self, usage=None, total_cost_usd=None, stop_reason=None ):
        self.usage          = usage
        self.total_cost_usd = total_cost_usd
        self.stop_reason    = stop_reason


def _patch_sdk_types():
    return patch.multiple(
        ac,
        AssistantMessage = _FakeAssistantMessage,
        TextBlock        = _FakeTextBlock,
        ResultMessage    = _FakeResultMessage,
    )


def _fake_sdk_query( messages, capture ):
    async def _gen( prompt, options ):
        capture[ "prompt" ]  = prompt
        capture[ "options" ] = options
        for m in messages:
            yield m
    return _gen


def _make_client( **kw ):
    return PresentationAPIClient( **kw )


# ----------------------------------------------------------------------------
# _temperature_to_steer
# ----------------------------------------------------------------------------
class TestTemperatureSteer:
    def test_high_temperature_creative( self ):
        assert "creative" in _temperature_to_steer( 0.8 ).lower()

    def test_low_temperature_precise( self ):
        assert "precise" in _temperature_to_steer( 0.2 ).lower()
        assert "precise" in _temperature_to_steer( 0.5 ).lower()

    def test_mid_temperature_none( self ):
        assert _temperature_to_steer( 0.7 ) == ""


# ----------------------------------------------------------------------------
# CostEstimate + APIResponse
# ----------------------------------------------------------------------------
class TestCostEstimate:
    def test_opus_pricing( self ):
        ce = CostEstimate()
        ce.add_usage( "claude-opus-4-6", 1_000_000, 1_000_000 )
        assert ce.estimated_cost_usd == pytest.approx( 90.0 )

    def test_haiku_pricing( self ):
        ce = CostEstimate()
        ce.add_usage( "claude-haiku-4-5", 1_000_000, 1_000_000 )
        assert ce.estimated_cost_usd == pytest.approx( 4.80 )   # 0.80 + 4.0

    def test_sonnet_pricing( self ):
        ce = CostEstimate()
        ce.add_usage( "claude-sonnet-4-6", 1_000_000, 1_000_000 )
        assert ce.estimated_cost_usd == pytest.approx( 18.0 )

    def test_add_sdk_cost( self ):
        ce = CostEstimate()
        ce.add_sdk_cost( 0.21 )
        ce.add_sdk_cost( 0.28 )
        assert ce.total_sdk_cost_usd == pytest.approx( 0.49 )

    def test_summary_disclaimer( self ):
        ce = CostEstimate()
        ce.add_usage( "claude-opus-4-6", 1000, 500 )
        ce.add_sdk_cost( 0.49 )
        s = ce.get_summary()
        assert "API Calls: 1" in s
        assert "1,000 in" in s
        assert "covered by Max plan" in s


class TestAPIResponse:
    def test_defaults( self ):
        r = APIResponse( content="c", model="m", input_tokens=1, output_tokens=2, stop_reason="end_turn" )
        assert r.raw_response is None
        assert r.sdk_cost_usd == 0.0


# ----------------------------------------------------------------------------
# __init__
# ----------------------------------------------------------------------------
class TestInit:
    def test_import_error_when_sdk_unavailable( self ):
        with patch.object( ac, "SDK_AVAILABLE", False ):
            with pytest.raises( ImportError, match="claude_agent_sdk not installed" ):
                PresentationAPIClient()

    def test_default_config_quiet( self, capsys ):
        c = PresentationAPIClient()
        assert c.config is not None
        assert c.cost_estimate.total_api_calls == 0
        assert capsys.readouterr().out == ""

    def test_provided_config_and_debug( self, capsys ):
        from cosa.agents.presentation_generator.config import PresentationConfig
        cfg = PresentationConfig()
        c = PresentationAPIClient( config=cfg, debug=True )
        assert c.config is cfg
        out = capsys.readouterr().out
        assert "Bounded-CC mode" in out
        assert "Content model:" in out


# ----------------------------------------------------------------------------
# call_for_* delegation + call_with_json_output (STRICT)
# ----------------------------------------------------------------------------
class TestCallWrappers:
    @pytest.mark.parametrize( "method,call_type,temp", [
        ( "call_for_analysis",    "narrative_analysis",  0.7 ),
        ( "call_for_outline",     "outline_generation",  0.7 ),
        ( "call_for_elaboration", "elaboration",         0.7 ),
        ( "call_for_mermaid",     "mermaid",             0.3 ),
        ( "call_for_matplotlib",  "matplotlib",          0.2 ),
        ( "call_for_d2",          "d2",                  0.3 ),
    ] )
    def test_call_wrappers_delegate( self, method, call_type, temp ):
        c = _make_client()
        c._call_api = AsyncMock( return_value="RESP" )
        out = _run( getattr( c, method )( "sys", "msg" ) )
        assert out == "RESP"
        kwargs = c._call_api.await_args.kwargs
        assert kwargs[ "call_type" ]   == call_type
        assert kwargs[ "temperature" ] == temp

    def test_json_output_strict_success( self ):
        c = _make_client()
        c._call_api = AsyncMock( return_value=APIResponse(
            content='Here: {"a": 1}', model="m", input_tokens=1, output_tokens=1, stop_reason="end_turn"
        ) )
        out = _run( c.call_with_json_output( "sys", "msg" ) )
        assert out == { "a": 1 }
        assert c._call_api.await_args.kwargs[ "temperature" ] == 0.5

    def test_json_output_strict_raises_on_unrecoverable( self ):
        c = _make_client()
        c._call_api = AsyncMock( return_value=APIResponse(
            content="no json at all", model="m", input_tokens=1, output_tokens=1, stop_reason="end_turn"
        ) )
        with pytest.raises( ValueError, match="recoverable JSON" ):
            _run( c.call_with_json_output( "sys", "msg" ) )


# ----------------------------------------------------------------------------
# _call_api — the bounded-CC sdk_query loop
# ----------------------------------------------------------------------------
class TestCallApi:
    def test_full_extraction_with_steer_and_debug( self, capsys ):
        c = _make_client( debug=True )
        capture  = {}
        messages = [
            _FakeAssistantMessage( [ _FakeTextBlock( "Hello " ), object(), _FakeTextBlock( "world" ) ] ),
            _FakeResultMessage( usage={ "input_tokens": 100, "output_tokens": 50 },
                                total_cost_usd=0.21, stop_reason="end_turn" ),
        ]
        with _patch_sdk_types(), patch.object( ac, "sdk_query", _fake_sdk_query( messages, capture ) ):
            out = _run( c._call_api( model="claude-opus-4-6", system_prompt="SYS",
                                     user_message="hi", call_type="elaboration", temperature=0.8 ) )
        assert out.content       == "Hello world"
        assert out.input_tokens  == 100
        assert out.output_tokens == 50
        assert out.sdk_cost_usd  == pytest.approx( 0.21 )
        assert out.stop_reason   == "end_turn"
        assert capture[ "options" ].system_prompt.startswith( "SYS" )
        assert "creative" in capture[ "options" ].system_prompt.lower()
        assert capture[ "options" ].tools == []
        # "default", not "plan" — plan mode changes what the model PRODUCES, so it
        # returned a plan FOR an outline and the parser rejected it (pr-62254a7f).
        # tools=[] is what keeps this read-only.
        assert capture[ "options" ].permission_mode == "default"
        assert capture[ "options" ].max_turns == c.config.content_max_turns
        assert c.cost_estimate.total_api_calls == 1
        assert c.cost_estimate.total_sdk_cost_usd == pytest.approx( 0.21 )
        printed = capsys.readouterr().out
        assert "sdk_query claude-opus-4-6 for elaboration" in printed
        assert "Response: 100 in, 50 out" in printed

    def test_mid_temp_keeps_system_prompt( self ):
        c = _make_client()
        capture  = {}
        with _patch_sdk_types(), patch.object( ac, "sdk_query",
                _fake_sdk_query( [ _FakeAssistantMessage( [ _FakeTextBlock( "x" ) ] ) ], capture ) ):
            _run( c._call_api( model="m", system_prompt="SYS", user_message="hi", temperature=0.7 ) )
        assert capture[ "options" ].system_prompt == "SYS"

    def test_empty_system_mid_temp_none( self ):
        c = _make_client()
        capture  = {}
        with _patch_sdk_types(), patch.object( ac, "sdk_query",
                _fake_sdk_query( [ _FakeAssistantMessage( [ _FakeTextBlock( "x" ) ] ) ], capture ) ):
            _run( c._call_api( model="m", system_prompt="", user_message="hi", temperature=0.7 ) )
        assert capture[ "options" ].system_prompt is None

    def test_empty_system_with_steer_becomes_steer( self ):
        c = _make_client()
        capture  = {}
        with _patch_sdk_types(), patch.object( ac, "sdk_query",
                _fake_sdk_query( [ _FakeAssistantMessage( [ _FakeTextBlock( "x" ) ] ) ], capture ) ):
            _run( c._call_api( model="m", system_prompt="", user_message="hi", temperature=0.8 ) )
        assert "creative" in capture[ "options" ].system_prompt.lower()

    def test_bare_textblock_resultmessage_defaults_unknown_msg( self, capsys ):
        c = _make_client()
        capture  = {}
        messages = [
            _FakeTextBlock( "bare-text" ),
            object(),
            _FakeResultMessage(),
        ]
        with _patch_sdk_types(), patch.object( ac, "sdk_query", _fake_sdk_query( messages, capture ) ):
            out = _run( c._call_api( model="m", system_prompt="SYS", user_message="hi", temperature=0.7 ) )
        assert out.content       == "bare-text"
        assert out.input_tokens  == 0
        assert out.output_tokens == 0
        assert out.sdk_cost_usd  == 0.0
        assert out.stop_reason   is None   # None stop_reason stays UNKNOWN, not coerced to "end_turn" (bug 98d937c2)
        assert capsys.readouterr().out == ""


# ----------------------------------------------------------------------------
# get_cost_summary + close
# ----------------------------------------------------------------------------
class TestSummaryAndClose:
    def test_get_cost_summary( self ):
        c = _make_client()
        c.cost_estimate.add_usage( "claude-opus-4-6", 100, 50 )
        assert "API Calls: 1" in c.get_cost_summary()

    def test_close_is_noop( self ):
        c = _make_client()
        assert _run( c.close() ) is None


def test_sdk_available_in_env():
    assert SDK_AVAILABLE is True
