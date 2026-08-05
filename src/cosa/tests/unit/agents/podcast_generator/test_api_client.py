#!/usr/bin/env python3
"""
Unit tests for cosa.agents.podcast_generator.api_client (BOUNDED-CC path).

The script-phase client was migrated from the direct firewalled Anthropic SDK
to the in-process Claude Agent SDK (`claude_agent_sdk.query`). These tests mock
`sdk_query` at the module boundary — a fake async generator yields fake
AssistantMessage / TextBlock / ResultMessage objects (the SDK message types are
patched into the module so isinstance checks pass). NO real SDK subprocess,
network call, OAuth, or spend occurs.

quick_smoke_test() and __main__ are coverage-excluded.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import cosa.agents.podcast_generator.api_client as ac
from cosa.agents.podcast_generator.api_client import (
    APIResponse,
    CostEstimate,
    PodcastAPIClient,
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
    """Patch the SDK message types into the module so isinstance() matches fakes."""
    return patch.multiple(
        ac,
        AssistantMessage = _FakeAssistantMessage,
        TextBlock        = _FakeTextBlock,
        ResultMessage    = _FakeResultMessage,
    )


def _fake_sdk_query( messages, capture ):
    """Build a fake `sdk_query` that records (prompt, options) and yields messages."""
    async def _gen( prompt, options ):
        capture[ "prompt" ]  = prompt
        capture[ "options" ] = options
        for m in messages:
            yield m
    return _gen


def _make_client( **kw ):
    """Build a PodcastAPIClient (SDK is available in this env — no API key needed)."""
    return PodcastAPIClient( **kw )


# ----------------------------------------------------------------------------
# _temperature_to_steer
# ----------------------------------------------------------------------------
class TestTemperatureSteer:
    """The legacy temperature → system-prompt creativity steer mapping."""

    def test_high_temperature_creative_steer( self ):
        assert "creative" in _temperature_to_steer( 0.8 ).lower()

    def test_low_temperature_precise_steer( self ):
        assert "precise" in _temperature_to_steer( 0.5 ).lower()

    def test_mid_temperature_no_steer( self ):
        assert _temperature_to_steer( 0.7 ) == ""
        assert _temperature_to_steer( 0.6 ) == ""


# ----------------------------------------------------------------------------
# CostEstimate + APIResponse
# ----------------------------------------------------------------------------
class TestCostEstimate:
    """CostEstimate accrual (opus vs non-opus), SDK telemetry, and summary."""

    def test_add_usage_opus_pricing( self ):
        ce = CostEstimate()
        ce.add_usage( "claude-opus-4-6", 1_000_000, 1_000_000 )
        assert ce.estimated_cost_usd == pytest.approx( 90.0 )   # 15 + 75
        assert ce.total_api_calls == 1

    def test_add_usage_sonnet_pricing( self ):
        ce = CostEstimate()
        ce.add_usage( "claude-sonnet-4-6", 1_000_000, 1_000_000 )
        assert ce.estimated_cost_usd == pytest.approx( 18.0 )   # 3 + 15

    def test_add_sdk_cost_accumulates( self ):
        ce = CostEstimate()
        ce.add_sdk_cost( 0.10 )
        ce.add_sdk_cost( 0.05 )
        assert ce.total_sdk_cost_usd == pytest.approx( 0.15 )

    def test_get_summary_format_and_disclaimer( self ):
        ce = CostEstimate()
        ce.add_usage( "claude-opus-4-6", 1000, 500 )
        ce.add_sdk_cost( 0.2051 )
        summary = ce.get_summary()
        assert "API Calls: 1" in summary
        assert "1,000 in" in summary
        assert "500 out" in summary
        assert "covered by Max plan" in summary


class TestAPIResponse:
    """APIResponse dataclass defaults."""

    def test_defaults( self ):
        r = APIResponse( content="c", model="m", input_tokens=1, output_tokens=2, stop_reason="end_turn" )
        assert r.raw_response is None
        assert r.sdk_cost_usd == 0.0


# ----------------------------------------------------------------------------
# __init__
# ----------------------------------------------------------------------------
class TestInit:
    """Constructor: SDK-availability guard, default vs provided config, debug print."""

    def test_import_error_when_sdk_unavailable( self ):
        with patch.object( ac, "SDK_AVAILABLE", False ):
            with pytest.raises( ImportError, match="claude_agent_sdk not installed" ):
                PodcastAPIClient()

    def test_default_config_no_debug_quiet( self, capsys ):
        c = PodcastAPIClient()
        assert c.config is not None
        assert c.cost_estimate.total_api_calls == 0
        assert capsys.readouterr().out == ""           # debug=False → no prints

    def test_provided_config_and_debug_prints( self, capsys ):
        from cosa.agents.podcast_generator.config import PodcastConfig
        cfg = PodcastConfig()
        c = PodcastAPIClient( config=cfg, debug=True )
        assert c.config is cfg
        out = capsys.readouterr().out
        assert "Bounded-CC mode" in out
        assert "Script model:" in out


# ----------------------------------------------------------------------------
# call_for_* delegation + call_with_json_output
# ----------------------------------------------------------------------------
class TestCallWrappers:
    """Public call_for_* delegate to _call_api with the right call_type+temperature."""

    def test_call_for_analysis_delegates( self ):
        c = _make_client()
        c._call_api = AsyncMock( return_value="RESP" )
        out = _run( c.call_for_analysis( "sys", "msg" ) )
        assert out == "RESP"
        kwargs = c._call_api.await_args.kwargs
        assert kwargs[ "call_type" ]   == "analysis"
        assert kwargs[ "temperature" ] == 0.7

    def test_call_for_script_delegates( self ):
        c = _make_client()
        c._call_api = AsyncMock( return_value="RESP" )
        _run( c.call_for_script( "sys", "msg" ) )
        assert c._call_api.await_args.kwargs[ "call_type" ]   == "script_generation"
        assert c._call_api.await_args.kwargs[ "temperature" ] == 0.8

    def test_call_for_revision_delegates( self ):
        c = _make_client()
        c._call_api = AsyncMock( return_value="RESP" )
        _run( c.call_for_revision( "sys", "msg" ) )
        assert c._call_api.await_args.kwargs[ "call_type" ]   == "revision"
        assert c._call_api.await_args.kwargs[ "temperature" ] == 0.6

    def test_json_output_success_lenient( self ):
        c = _make_client()
        c._call_api = AsyncMock( return_value=APIResponse(
            content='Here you go: {"a": 1}', model="m", input_tokens=1, output_tokens=1, stop_reason="end_turn"
        ) )
        out = _run( c.call_with_json_output( "sys", "msg" ) )
        assert out == { "a": 1 }
        # json_output uses the precise (0.5) steer
        assert c._call_api.await_args.kwargs[ "temperature" ] == 0.5

    def test_json_output_unrecoverable_raises_value_error( self ):
        c = _make_client()
        c._call_api = AsyncMock( return_value=APIResponse(
            content="not json at all", model="m", input_tokens=1, output_tokens=1, stop_reason="end_turn"
        ) )
        with pytest.raises( ValueError, match="recoverable JSON" ):
            _run( c.call_with_json_output( "sys", "msg" ) )


# ----------------------------------------------------------------------------
# _call_api — the bounded-CC sdk_query loop
# ----------------------------------------------------------------------------
class TestCallApi:
    """
    _call_api content extraction, options construction, usage/cost capture.

    Covers: steer-append vs no-steer vs steer-only(empty system); the
    AssistantMessage inner block loop (text + non-text); the bare-TextBlock
    branch; ResultMessage usage/cost/stop extraction (present + None defaults);
    an unknown message (all-isinstance-false arc); debug prints on/off.
    """

    def test_full_extraction_with_steer_and_debug( self, capsys ):
        c = _make_client( debug=True )
        capture  = {}
        messages = [
            _FakeAssistantMessage( [ _FakeTextBlock( "Hello " ), object(), _FakeTextBlock( "world" ) ] ),
            _FakeResultMessage( usage={ "input_tokens": 100, "output_tokens": 50 },
                                total_cost_usd=0.2051, stop_reason="end_turn" ),
        ]
        with _patch_sdk_types(), patch.object( ac, "sdk_query", _fake_sdk_query( messages, capture ) ):
            out = _run( c._call_api( model="claude-opus-4-6", system_prompt="SYS",
                                     user_message="hi", call_type="script_generation", temperature=0.8 ) )
        assert out.content       == "Hello world"
        assert out.input_tokens  == 100
        assert out.output_tokens == 50
        assert out.sdk_cost_usd  == pytest.approx( 0.2051 )
        assert out.stop_reason   == "end_turn"
        # steer (0.8 → creative) appended to the system prompt
        assert capture[ "options" ].system_prompt.startswith( "SYS" )
        assert "creative" in capture[ "options" ].system_prompt.lower()
        # bounded-CC options: no tools, read-only, capped turns
        assert capture[ "options" ].tools == []
        # "default", not "plan" (5c45edf6): plan mode changes what the model
        # PRODUCES — asked for a script it wrote a plan FOR a script, and the
        # JSON parser correctly rejected it. tools=[] is what keeps it read-only.
        assert capture[ "options" ].permission_mode == "default"
        assert capture[ "options" ].max_turns == c.config.script_max_turns
        # usage recorded
        assert c.cost_estimate.total_api_calls == 1
        assert c.cost_estimate.total_sdk_cost_usd == pytest.approx( 0.2051 )
        printed = capsys.readouterr().out
        assert "sdk_query claude-opus-4-6 for script_generation" in printed
        assert "Response: 100 in, 50 out" in printed

    def test_mid_temp_keeps_system_prompt_unchanged( self ):
        c = _make_client()
        capture  = {}
        messages = [ _FakeAssistantMessage( [ _FakeTextBlock( "x" ) ] ) ]
        with _patch_sdk_types(), patch.object( ac, "sdk_query", _fake_sdk_query( messages, capture ) ):
            _run( c._call_api( model="m", system_prompt="SYS", user_message="hi", temperature=0.7 ) )
        assert capture[ "options" ].system_prompt == "SYS"   # no steer appended

    def test_empty_system_and_mid_temp_yields_none_system_prompt( self ):
        c = _make_client()
        capture  = {}
        messages = [ _FakeAssistantMessage( [ _FakeTextBlock( "x" ) ] ) ]
        with _patch_sdk_types(), patch.object( ac, "sdk_query", _fake_sdk_query( messages, capture ) ):
            _run( c._call_api( model="m", system_prompt="", user_message="hi", temperature=0.7 ) )
        assert capture[ "options" ].system_prompt is None    # "" → None

    def test_empty_system_with_steer_becomes_steer_only( self ):
        c = _make_client()
        capture  = {}
        messages = [ _FakeAssistantMessage( [ _FakeTextBlock( "x" ) ] ) ]
        with _patch_sdk_types(), patch.object( ac, "sdk_query", _fake_sdk_query( messages, capture ) ):
            _run( c._call_api( model="m", system_prompt="", user_message="hi", temperature=0.8 ) )
        assert "creative" in capture[ "options" ].system_prompt.lower()

    def test_bare_textblock_and_resultmessage_defaults_and_unknown_msg( self, capsys ):
        # bare top-level TextBlock branch; ResultMessage with usage=None / cost=None /
        # stop=None falling to defaults; an unknown message exercising the all-false arc.
        c = _make_client()                                   # debug=False → no prints
        capture  = {}
        messages = [
            _FakeTextBlock( "bare-text" ),
            object(),                                        # unknown → no branch taken
            _FakeResultMessage(),                            # usage None, cost None, stop None
        ]
        with _patch_sdk_types(), patch.object( ac, "sdk_query", _fake_sdk_query( messages, capture ) ):
            out = _run( c._call_api( model="m", system_prompt="SYS", user_message="hi", temperature=0.7 ) )
        assert out.content       == "bare-text"
        assert out.input_tokens  == 0
        assert out.output_tokens == 0
        assert out.sdk_cost_usd  == 0.0
        assert out.stop_reason   == "end_turn"               # None → default
        assert capsys.readouterr().out == ""                 # debug=False


# ----------------------------------------------------------------------------
# get_cost_summary + close
# ----------------------------------------------------------------------------
class TestSummaryAndClose:
    """get_cost_summary proxies CostEstimate; close is a stateless no-op."""

    def test_get_cost_summary( self ):
        c = _make_client()
        c.cost_estimate.add_usage( "claude-opus-4-6", 100, 50 )
        assert "API Calls: 1" in c.get_cost_summary()

    def test_close_is_noop( self ):
        c = _make_client()
        assert _run( c.close() ) is None                     # must not raise


def test_sdk_available_truthy_in_this_env():
    """Sanity: the SDK is installed in the canonical test venv."""
    assert SDK_AVAILABLE is True
