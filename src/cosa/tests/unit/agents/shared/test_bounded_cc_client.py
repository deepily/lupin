"""
Unit tests for cosa.agents.shared.bounded_cc_client, through a small stub subclass.
"""

import asyncio
import logging
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from cosa.agents.shared.bounded_cc_client import BoundedCCClientBase, BoundedCCCostEstimate


@dataclass
class _Cost( BoundedCCCostEstimate ):
    pass


class _Config:
    def __init__( self ):
        self.fast_model = "FAST"
        self.slow_model = "SLOW"


_LOG = logging.getLogger( "stub.client" )


class _Client( BoundedCCClientBase ):
    CONFIG_CLASS        = _Config
    COST_ESTIMATE_CLASS = _Cost
    LABEL               = "StubClient"
    BANNER_NOUN         = "Fast"
    BANNER_FIELD        = "fast_model"
    JSON_MODEL_FIELD    = "slow_model"
    _logger             = _LOG

    def __init__( self, config=None, debug=False, verbose=False, sdk_available=True ):
        super().__init__( config, debug, verbose, sdk_available )
        self.calls = []
        self.reply = '{"a": 1}'

    def _recover_json( self, text ):
        import json
        try: return json.loads( text )
        except ValueError: return None

    async def _call_api( self, **kwargs ):
        self.calls.append( kwargs )
        return SimpleNamespace( content=self.reply )


def test_init_raises_import_error_without_the_sdk():
    with pytest.raises( ImportError, match="claude_agent_sdk not installed" ):
        _Client( sdk_available=False )


def test_init_builds_the_default_config_and_cost_estimate_and_stays_quiet( capsys ):
    client = _Client()
    assert isinstance( client.config, _Config ) and isinstance( client.cost_estimate, _Cost )
    assert ( client.debug, client.verbose ) == ( False, False )
    assert capsys.readouterr().out == ""


def test_init_keeps_a_given_config_and_prints_two_banner_lines_with_debug( capsys ):
    config = _Config()
    config.fast_model = "OTHER"
    client = _Client( config=config, debug=True, verbose=True )
    assert client.config is config and client.verbose is True
    assert capsys.readouterr().out.splitlines() == [
        "[StubClient] Bounded-CC mode (in-process sdk_query, Max-plan OAuth)",
        "[StubClient] Fast model: OTHER",
    ]


def test_call_typed_passes_every_value_to_call_api_as_a_keyword():
    client = _Client()
    out    = asyncio.run( client._call_typed( "M", "kind", "SYS", "MSG", 11, 0.4 ) )
    assert out.content == '{"a": 1}'
    assert client.calls == [ { "model": "M", "system_prompt": "SYS", "user_message": "MSG",
                               "max_tokens": 11, "temperature": 0.4, "call_type": "kind" } ]


def test_json_output_uses_the_json_model_field_at_temperature_half_and_returns_the_object():
    client = _Client()
    assert asyncio.run( client.call_with_json_output( "SYS", "MSG" ) ) == { "a": 1 }
    assert client.calls == [ { "model": "SLOW", "system_prompt": "SYS", "user_message": "MSG",
                               "max_tokens": 4096, "temperature": 0.5, "call_type": "json_output" } ]


def test_json_output_that_cannot_be_recovered_logs_on_the_subclass_logger_and_raises( caplog ):
    client       = _Client()
    client.reply = "no json here"
    with caplog.at_level( logging.DEBUG, logger="stub.client" ):
        with pytest.raises( ValueError, match="recoverable JSON object" ):
            asyncio.run( client.call_with_json_output( "SYS", "MSG", 9 ) )
    assert [ ( r.name, r.levelname, r.getMessage() ) for r in caplog.records ] == [
        ( "stub.client", "ERROR", "Failed to recover JSON object from response" ),
        ( "stub.client", "DEBUG", "Raw content: no json here" ),
    ]
    assert client.calls[ 0 ][ "max_tokens" ] == 9


def test_cost_estimate_accumulates_sdk_cost_and_summarises():
    cost = _Cost()
    cost.add_sdk_cost( 0.5 )
    cost.add_sdk_cost( 0.25 )
    cost.total_api_calls, cost.total_input_tokens, cost.total_output_tokens, cost.estimated_cost_usd = 2, 1234, 5, 0.00012
    assert cost.get_summary() == (
        "API Calls: 2 | Tokens: 1,234 in, 5 out | Est. Cost: $0.0001 | "
        "SDK telemetry: $0.7500 (covered by Max plan — not billed per-token)"
    )


class TestSharedAddUsage:
    """The token tally and the price estimate that the podcast and presentation estimates share."""

    def test_opus_is_priced_at_the_opus_pair( self ):
        ce = _Cost()
        ce.add_usage( "claude-OPUS-4", 1_000_000, 1_000_000 )
        assert ce.estimated_cost_usd == pytest.approx( 90.0 )

    def test_any_other_name_is_priced_as_sonnet( self ):
        ce = _Cost()
        ce.add_usage( "claude-haiku-4-5", 1_000_000, 1_000_000 )
        assert ce.estimated_cost_usd == pytest.approx( 18.0 )

    def test_tokens_calls_and_cost_accumulate_over_calls( self ):
        ce = _Cost()
        ce.add_usage( "sonnet", 1_000, 2_000 )
        ce.add_usage( "opus", 3_000, 4_000 )
        assert ( ce.total_input_tokens, ce.total_output_tokens, ce.total_api_calls ) == ( 4_000, 6_000, 2 )
        assert ce.estimated_cost_usd == pytest.approx( 0.033 + 0.345 )


class _NoCostClient( _Client ):
    COST_ESTIMATE_CLASS = None


def test_a_client_with_no_cost_estimate_class_keeps_cost_estimate_none():
    assert _NoCostClient().cost_estimate is None


class _OwnBannerClient( _Client ):
    def _banner_model_line( self ):
        return "Custom banner"


def test_the_banner_model_line_is_the_subclass_hook( capsys ):
    _OwnBannerClient( debug=True )
    assert capsys.readouterr().out.splitlines() == [
        "[StubClient] Bounded-CC mode (in-process sdk_query, Max-plan OAuth)",
        "[StubClient] Custom banner",
    ]


def test_the_default_banner_model_line_names_the_noun_and_the_field_model():
    assert _Client()._banner_model_line() == "Fast model: FAST"
