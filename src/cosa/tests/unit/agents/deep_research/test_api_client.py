#!/usr/bin/env python3
"""
Unit tests for cosa.agents.deep_research.api_client (BOUNDED-CC path).

FULL REWRITE 2026-06-18 (Phase 3 bounded-CC migration, Arnold 🪨 on Tiberius 👑's
SWE crew). The research client was migrated from the direct firewalled Anthropic
SDK (`AsyncAnthropic.messages.create` + ApiResourceManager web-search gating) to
the in-process Claude Agent SDK (`claude_agent_sdk.query`), matching the shipped
BFE/TFE + Podcast + Presentation bounded-CC pattern (ratified D-DR1 Option X).

These tests mock `sdk_query` at the module boundary — a fake async generator
yields fake AssistantMessage / TextBlock / ResultMessage objects (the SDK message
types are patched into the module so isinstance checks pass). NO real SDK
subprocess, network call, OAuth, or spend occurs.

D6=STRICT: extract_json_object recovers JSON from chatty output but RAISES on
unrecoverable content (never silent-default).

Web-search migration: the lead agent runs tools=[] (pure reasoning); research
subagents run tools=[WebSearch, WebFetch] (native web_search_20250305 → CC
WebSearch/WebFetch). The legacy ARM acquire/record_call dance is dropped — these
tests assert the bounded options shape, not the retired ARM path.

quick_smoke_test() and __main__ are coverage-excluded (pyproject exclude_also).

Must run via run-sdk-cov.sh (api_client imports the claude_agent_sdk chain).
"""

import asyncio
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import cosa.agents.deep_research.api_client as ac
from cosa.agents.deep_research.api_client import (
    APIResponse,
    ResearchAPIClient,
    SDK_AVAILABLE,
    LEAD_TOOLS,
    SUBAGENT_TOOLS,
    RESEARCH_PERMISSION_MODE_WITH_TOOLS,
    RESEARCH_PERMISSION_MODE_NO_TOOLS,
    extract_json_object,
    _temperature_to_steer,
)
from cosa.agents.deep_research.config import ResearchConfig
from cosa.agents.deep_research.cost_tracker import BudgetExceededError


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


@contextmanager
def _make_client( config=None, cost_tracker=None, debug=False, verbose=False,
                  cfgmgr_raises=False ):
    """Build a ResearchAPIClient with the rate-limiter + ConfigurationManager mocked.

    The WebSearchRateLimiter is retained on the bounded path for CLI time-estimate
    UX only (NOT in the LLM call path); we patch it so no real limiter is built.
    """
    with patch.object( ac, "WebSearchRateLimiter" ) as mock_rl_cls:
        mock_rl = MagicMock()
        mock_rl_cls.return_value = mock_rl

        if cfgmgr_raises:
            cm = patch(
                "cosa.config.configuration_manager.ConfigurationManager",
                side_effect=RuntimeError( "no cfg" ),
            )
        else:
            mock_cfg = MagicMock()
            mock_cfg.get.side_effect = lambda key, default, return_type: default
            cm = patch(
                "cosa.config.configuration_manager.ConfigurationManager",
                return_value=mock_cfg,
            )

        with cm:
            client = ResearchAPIClient(
                config=config, cost_tracker=cost_tracker, debug=debug, verbose=verbose,
            )
        yield client, mock_rl


# ----------------------------------------------------------------------------
# Module constants + SDK availability
# ----------------------------------------------------------------------------
class TestModuleConstants:
    def test_sdk_available_in_env( self ):
        assert SDK_AVAILABLE is True

    def test_anthropic_available_mirrors_sdk( self ):
        # Historical export-compat alias now tracks SDK availability.
        assert ac.ANTHROPIC_AVAILABLE == SDK_AVAILABLE

    def test_tool_surfaces( self ):
        assert LEAD_TOOLS == []
        assert SUBAGENT_TOOLS == [ "WebSearch", "WebFetch" ]
        # Two modes, split by whether the call has tools. "plan" is a real read-only
        # guard for a TOOL-USING call, but with tools=[] it guards nothing and only
        # changes what the model produces — a plan FOR a report instead of a report.
        assert RESEARCH_PERMISSION_MODE_WITH_TOOLS == "plan"
        assert RESEARCH_PERMISSION_MODE_NO_TOOLS   == "default"

    def test_historical_key_constants_retained( self ):
        assert ac.ENV_VAR_NAME  == "ANTHROPIC_API_KEY_FIREWALLED"
        assert ac.KEY_FILE_NAME == "anthropic-api-key-firewalled"


# ----------------------------------------------------------------------------
# _temperature_to_steer (3 branches)
# ----------------------------------------------------------------------------
class TestTemperatureSteer:
    def test_high_temperature_creative( self ):
        assert "creative" in _temperature_to_steer( 0.9 ).lower()
        assert "creative" in _temperature_to_steer( 1.0 ).lower()

    def test_low_temperature_precise( self ):
        assert "precise" in _temperature_to_steer( 0.2 ).lower()
        assert "precise" in _temperature_to_steer( 0.5 ).lower()

    def test_mid_temperature_none( self ):
        assert _temperature_to_steer( 0.7 ) == ""


# ----------------------------------------------------------------------------
# extract_json_object (D6-STRICT — recover then fail-loud)
# ----------------------------------------------------------------------------
class TestExtractJsonObject:
    def test_plain_json( self ):
        assert extract_json_object( '{"a": 1}' ) == { "a": 1 }

    def test_json_fenced( self ):
        assert extract_json_object( '```json\n{"a": 2}\n```' ) == { "a": 2 }

    def test_bare_fenced( self ):
        assert extract_json_object( '```\n{"a": 3}\n```' ) == { "a": 3 }

    def test_prose_wrapped_recovers_via_brace_scan( self ):
        assert extract_json_object( 'Here you go:\n{"a": 4}\nThanks!' ) == { "a": 4 }

    def test_nested_braces_balance( self ):
        assert extract_json_object( 'x {"a": {"b": 5}} y' ) == { "a": { "b": 5 } }

    def test_none_raises( self ):
        with pytest.raises( ValueError, match="empty/blank" ):
            extract_json_object( None )

    def test_blank_raises( self ):
        with pytest.raises( ValueError, match="empty/blank" ):
            extract_json_object( "   " )

    def test_no_brace_raises( self ):
        # start == -1 path → no balanced span → final raise.
        with pytest.raises( ValueError, match="recoverable JSON" ):
            extract_json_object( "no json here at all" )

    def test_balanced_but_invalid_json_breaks_then_raises( self ):
        # A balanced { ... } span that is NOT valid JSON → json.loads fails →
        # break out of the scan → final raise. Covers the break arm.
        with pytest.raises( ValueError, match="recoverable JSON" ):
            extract_json_object( "prefix { not: valid } suffix" )

    def test_unclosed_brace_scan_falls_through_then_raises( self ):
        # An opening { that never balances → the scan loop completes without a
        # break/return → falls through to the final raise (177->190 branch).
        with pytest.raises( ValueError, match="recoverable JSON" ):
            extract_json_object( "prefix { unclosed forever" )


# ----------------------------------------------------------------------------
# APIResponse dataclass
# ----------------------------------------------------------------------------
class TestAPIResponse:
    def test_defaults( self ):
        r = APIResponse(
            content="c", model="m", input_tokens=1, output_tokens=2, stop_reason="end_turn",
        )
        assert r.sdk_cost_usd   == 0.0
        assert r.tool_use       == []
        assert r.search_results == []
        assert r.raw_response is None


# ----------------------------------------------------------------------------
# __init__
# ----------------------------------------------------------------------------
class TestInit:
    def test_import_error_when_sdk_unavailable( self ):
        with patch.object( ac, "SDK_AVAILABLE", False ):
            with pytest.raises( ImportError, match="claude_agent_sdk not installed" ):
                ResearchAPIClient()

    def test_default_config_created_when_none( self ):
        with _make_client( config=None ) as ( client, _rl ):
            assert isinstance( client.config, ResearchConfig )

    def test_provided_config_used( self ):
        cfg = ResearchConfig()
        with _make_client( config=cfg ) as ( client, _rl ):
            assert client.config is cfg

    def test_cfgmgr_success_quiet( self, capsys ):
        with _make_client( debug=False ) as ( client, _rl ):
            assert client._rate_limiter is not None
        assert capsys.readouterr().out == ""

    def test_cfgmgr_success_debug_prints( self, capsys ):
        with _make_client( debug=True ) as ( client, _rl ):
            assert client._rate_limiter is not None
        out = capsys.readouterr().out
        assert "Bounded-CC mode" in out
        assert "Models:" in out

    def test_cfgmgr_unavailable_fallback_debug( self, capsys ):
        # ConfigurationManager raises → except fallback (defaults) + debug print arm.
        with _make_client( cfgmgr_raises=True, debug=True ) as ( client, _rl ):
            assert client._rate_limiter is not None
        assert "ConfigurationManager unavailable" in capsys.readouterr().out

    def test_cfgmgr_unavailable_fallback_no_debug( self, capsys ):
        # except fallback + debug=False false arm (no fallback print).
        with _make_client( cfgmgr_raises=True, debug=False ) as ( client, _rl ):
            assert client._rate_limiter is not None
        assert "ConfigurationManager unavailable" not in capsys.readouterr().out


# ----------------------------------------------------------------------------
# _rate_limit_notify
# ----------------------------------------------------------------------------
class TestRateLimitNotify:
    def test_notify_via_voice_io( self ):
        with _make_client() as ( client, _rl ):
            with patch(
                "cosa.agents.deep_research.voice_io.notify", new=AsyncMock(),
            ) as mock_notify:
                _run( client._rate_limit_notify( "delaying", "high" ) )
            mock_notify.assert_awaited_once_with( "delaying", priority="high" )

    def test_notify_falls_back_on_error_with_debug( self, capsys ):
        with _make_client( debug=True ) as ( client, _rl ):
            with patch(
                "cosa.agents.deep_research.voice_io.notify",
                new=AsyncMock( side_effect=RuntimeError( "no voice" ) ),
            ):
                _run( client._rate_limit_notify( "delaying", "low" ) )   # must not raise
        assert "Rate limit notification" in capsys.readouterr().out

    def test_notify_falls_back_on_error_no_debug( self, capsys ):
        with _make_client( debug=False ) as ( client, _rl ):
            with patch(
                "cosa.agents.deep_research.voice_io.notify",
                new=AsyncMock( side_effect=RuntimeError( "no voice" ) ),
            ):
                _run( client._rate_limit_notify( "delaying", "low" ) )   # must not raise
        assert capsys.readouterr().out == ""


# ----------------------------------------------------------------------------
# get_rate_limiter
# ----------------------------------------------------------------------------
class TestGetRateLimiter:
    def test_returns_rate_limiter_instance( self ):
        with _make_client() as ( client, _rl ):
            assert client.get_rate_limiter() is client._rate_limiter


# ----------------------------------------------------------------------------
# call_lead_agent / call_subagent / call_with_json_output delegation
# ----------------------------------------------------------------------------
class TestCallWrappers:
    def test_call_lead_agent_delegates_lead_tools( self ):
        with _make_client() as ( client, _rl ):
            client._call_sdk = AsyncMock( return_value="sentinel" )
            out = _run( client.call_lead_agent(
                system_prompt="sys", user_message="msg",
                use_extended_thinking=True, max_tokens=123, temperature=0.5,
            ) )
        assert out == "sentinel"
        kwargs = client._call_sdk.await_args.kwargs
        assert kwargs[ "model" ]                 == client.config.lead_model
        assert kwargs[ "tools" ]                 == LEAD_TOOLS
        assert kwargs[ "use_extended_thinking" ] is True
        assert kwargs[ "temperature" ]           == 0.5

    def test_call_subagent_web_search_uses_subagent_tools( self ):
        with _make_client() as ( client, _rl ):
            client._call_sdk = AsyncMock( return_value="r" )
            _run( client.call_subagent(
                "sys", "q", subquery_index=0, use_web_search=True,
            ) )
        kwargs = client._call_sdk.await_args.kwargs
        assert kwargs[ "model" ]                 == client.config.subagent_model
        assert kwargs[ "tools" ]                 == SUBAGENT_TOOLS
        assert kwargs[ "subquery_index" ]        == 0
        assert kwargs[ "use_extended_thinking" ] is False

    def test_call_subagent_no_web_search_uses_lead_tools( self ):
        with _make_client() as ( client, _rl ):
            client._call_sdk = AsyncMock( return_value="r" )
            _run( client.call_subagent(
                "sys", "q", subquery_index=2, use_web_search=False,
            ) )
        assert client._call_sdk.await_args.kwargs[ "tools" ] == LEAD_TOOLS

    def test_call_with_json_output_success( self ):
        with _make_client() as ( client, _rl ):
            client._call_sdk = AsyncMock( return_value=APIResponse(
                content='Sure: {"a": 1}', model="m", input_tokens=1,
                output_tokens=1, stop_reason="end_turn",
            ) )
            out = _run( client.call_with_json_output( "sys", "msg" ) )
        assert out == { "a": 1 }
        assert client._call_sdk.await_args.kwargs[ "tools" ] == LEAD_TOOLS

    def test_call_with_json_output_default_model_is_lead( self ):
        with _make_client() as ( client, _rl ):
            client._call_sdk = AsyncMock( return_value=APIResponse(
                content='{"a": 9}', model="m", input_tokens=1,
                output_tokens=1, stop_reason="end_turn",
            ) )
            _run( client.call_with_json_output( "sys", "msg" ) )
        assert client._call_sdk.await_args.kwargs[ "model" ] == client.config.lead_model

    def test_call_with_json_output_explicit_model( self ):
        with _make_client() as ( client, _rl ):
            client._call_sdk = AsyncMock( return_value=APIResponse(
                content='{"a": 9}', model="m", input_tokens=1,
                output_tokens=1, stop_reason="end_turn",
            ) )
            _run( client.call_with_json_output( "sys", "msg", model="explicit-m" ) )
        assert client._call_sdk.await_args.kwargs[ "model" ] == "explicit-m"

    def test_call_with_json_output_raises_on_unrecoverable( self ):
        # Covers the except ValueError → logger.error/debug → re-raise arm.
        with _make_client() as ( client, _rl ):
            client._call_sdk = AsyncMock( return_value=APIResponse(
                content="no json at all", model="m", input_tokens=1,
                output_tokens=1, stop_reason="end_turn",
            ) )
            with pytest.raises( ValueError, match="recoverable JSON" ):
                _run( client.call_with_json_output( "sys", "msg" ) )


# ----------------------------------------------------------------------------
# _call_sdk — the bounded-CC sdk_query loop
# ----------------------------------------------------------------------------
class TestCallSdk:
    def test_full_extraction_with_steer_cost_and_debug( self, capsys ):
        cost_tracker = MagicMock()
        with _make_client( cost_tracker=cost_tracker, debug=True ) as ( client, _rl ):
            capture  = {}
            messages = [
                _FakeAssistantMessage( [ _FakeTextBlock( "Hello " ), object(), _FakeTextBlock( "world" ) ] ),
                _FakeResultMessage( usage={ "input_tokens": 100, "output_tokens": 50 },
                                    total_cost_usd=0.21, stop_reason="end_turn" ),
            ]
            with _patch_sdk_types(), patch.object( ac, "sdk_query", _fake_sdk_query( messages, capture ) ):
                out = _run( client._call_sdk(
                    model="claude-opus-4-6", system_prompt="SYS", user_message="hi",
                    call_type="research", tools=SUBAGENT_TOOLS, subquery_index=3, temperature=1.0,
                ) )
        assert out.content       == "Hello world"
        assert out.input_tokens  == 100
        assert out.output_tokens == 50
        assert out.sdk_cost_usd  == pytest.approx( 0.21 )
        assert out.stop_reason   == "end_turn"
        assert out.model         == "claude-opus-4-6"
        assert capture[ "prompt" ] == "hi"
        opts = capture[ "options" ]
        assert opts.system_prompt.startswith( "SYS" )
        assert "creative" in opts.system_prompt.lower()
        assert opts.tools           == SUBAGENT_TOOLS
        assert opts.permission_mode == "plan"
        assert opts.max_turns       == client.config.max_research_turns
        cost_tracker.record_from_response.assert_called_once()
        printed = capsys.readouterr().out
        assert "sdk_query claude-opus-4-6 for research" in printed
        assert "Response: 100 in, 50 out" in printed

    def test_mid_temp_keeps_system_prompt_default_tools( self ):
        with _make_client() as ( client, _rl ):
            capture = {}
            with _patch_sdk_types(), patch.object(
                ac, "sdk_query",
                _fake_sdk_query( [ _FakeAssistantMessage( [ _FakeTextBlock( "x" ) ] ) ], capture ),
            ):
                _run( client._call_sdk( model="m", system_prompt="SYS", user_message="hi", temperature=0.7 ) )
        opts = capture[ "options" ]
        assert opts.system_prompt == "SYS"
        # tools defaults to LEAD_TOOLS when not supplied.
        assert opts.tools == LEAD_TOOLS
        # ...and a NO-TOOL call must NOT run in plan mode. The paired assertion at
        # the subagent test above proves the tool-using call still gets "plan", so
        # the two together exercise both sides of the derivation rather than
        # restating the constants. A constant can be right while the call site
        # ignores it — that is the failure this pair is here to catch.
        assert opts.permission_mode == RESEARCH_PERMISSION_MODE_NO_TOOLS
        assert opts.permission_mode == "default"

    def test_empty_system_mid_temp_becomes_none( self ):
        with _make_client() as ( client, _rl ):
            capture = {}
            with _patch_sdk_types(), patch.object(
                ac, "sdk_query",
                _fake_sdk_query( [ _FakeAssistantMessage( [ _FakeTextBlock( "x" ) ] ) ], capture ),
            ):
                _run( client._call_sdk( model="m", system_prompt="", user_message="hi", temperature=0.7 ) )
        assert capture[ "options" ].system_prompt is None

    def test_empty_system_with_steer_becomes_steer( self ):
        with _make_client() as ( client, _rl ):
            capture = {}
            with _patch_sdk_types(), patch.object(
                ac, "sdk_query",
                _fake_sdk_query( [ _FakeAssistantMessage( [ _FakeTextBlock( "x" ) ] ) ], capture ),
            ):
                _run( client._call_sdk( model="m", system_prompt="", user_message="hi", temperature=1.0 ) )
        assert "creative" in capture[ "options" ].system_prompt.lower()

    def test_extended_thinking_adds_max_thinking_tokens( self ):
        with _make_client() as ( client, _rl ):
            capture = {}
            with _patch_sdk_types(), patch.object(
                ac, "sdk_query",
                _fake_sdk_query( [ _FakeAssistantMessage( [ _FakeTextBlock( "x" ) ] ) ], capture ),
            ):
                _run( client._call_sdk(
                    model="m", system_prompt="s", user_message="hi",
                    use_extended_thinking=True, temperature=0.7,
                ) )
        assert capture[ "options" ].max_thinking_tokens == client.config.extended_thinking_budget

    def test_bare_textblock_and_resultmessage_defaults_and_unknown_msg( self, capsys ):
        # bare TextBlock appended; unknown object skipped; ResultMessage with all
        # None falls back to 0 / 0.0 / "end_turn". cost_tracker None → record skipped.
        with _make_client( cost_tracker=None, debug=False ) as ( client, _rl ):
            capture  = {}
            messages = [
                _FakeTextBlock( "bare-text" ),
                object(),
                _FakeResultMessage(),
            ]
            with _patch_sdk_types(), patch.object( ac, "sdk_query", _fake_sdk_query( messages, capture ) ):
                out = _run( client._call_sdk( model="m", system_prompt="SYS", user_message="hi", temperature=0.7 ) )
        assert out.content       == "bare-text"
        assert out.input_tokens  == 0
        assert out.output_tokens == 0
        assert out.sdk_cost_usd  == 0.0
        assert out.stop_reason   == "end_turn"
        assert capsys.readouterr().out == ""

    def test_budget_exceeded_propagates( self ):
        cost_tracker = MagicMock()
        cost_tracker.record_from_response.side_effect = BudgetExceededError( "over" )
        with _make_client( cost_tracker=cost_tracker ) as ( client, _rl ):
            messages = [ _FakeAssistantMessage( [ _FakeTextBlock( "z" ) ] ) ]
            with _patch_sdk_types(), patch.object( ac, "sdk_query", _fake_sdk_query( messages, {} ) ):
                with pytest.raises( BudgetExceededError ):
                    _run( client._call_sdk( model="m", system_prompt="s", user_message="hi" ) )


# ----------------------------------------------------------------------------
# close
# ----------------------------------------------------------------------------
class TestClose:
    def test_close_is_noop( self ):
        with _make_client() as ( client, _rl ):
            assert _run( client.close() ) is None


if __name__ == "__main__":
    import sys
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
