"""
Pins for the podcast and presentation clients, written before their shared base.

Each call_for_* wrapper hands _call_api the same model, call type and defaults as before.
The debug banner and the cost summary text do not move.
"""

import asyncio
from unittest.mock import AsyncMock

import pytest

from cosa.agents.podcast_generator.api_client import PodcastAPIClient
from cosa.agents.podcast_generator.config import PodcastConfig
from cosa.agents.presentation_generator.api_client import PresentationAPIClient
from cosa.agents.presentation_generator.config import PresentationConfig


def _podcast( debug=False ):
    return PodcastAPIClient( config=PodcastConfig( script_model="SCRIPT-M" ), debug=debug )


def _presentation( debug=False ):
    return PresentationAPIClient( config=PresentationConfig( content_model="CONTENT-M" ), debug=debug )


CASES = [
    ( _podcast,      "call_for_analysis",     "SCRIPT-M",  "analysis",           4096, 0.7 ),
    ( _podcast,      "call_for_script",       "SCRIPT-M",  "script_generation",  8192, 0.8 ),
    ( _podcast,      "call_for_revision",     "SCRIPT-M",  "revision",           8192, 0.6 ),
    ( _presentation, "call_for_analysis",     "CONTENT-M", "narrative_analysis", 4096, 0.7 ),
    ( _presentation, "call_for_outline",      "CONTENT-M", "outline_generation", 4096, 0.7 ),
    ( _presentation, "call_for_elaboration",  "CONTENT-M", "elaboration",        8192, 0.7 ),
    ( _presentation, "call_for_mermaid",      "CONTENT-M", "mermaid",            2048, 0.3 ),
    ( _presentation, "call_for_matplotlib",   "CONTENT-M", "matplotlib",         4096, 0.2 ),
    ( _presentation, "call_for_d2",           "CONTENT-M", "d2",                 2048, 0.3 ),
]


@pytest.mark.parametrize( "make, method, model, call_type, max_tokens, temperature", CASES )
def test_each_wrapper_passes_its_model_call_type_and_defaults( make, method, model, call_type, max_tokens, temperature ):
    client      = make()
    client._call_api = AsyncMock( return_value="R" )
    assert asyncio.run( getattr( client, method )( "SYS", "MSG" ) ) == "R"
    assert client._call_api.await_args.kwargs == {
        "model": model, "system_prompt": "SYS", "user_message": "MSG",
        "max_tokens": max_tokens, "temperature": temperature, "call_type": call_type,
    }


@pytest.mark.parametrize( "make, method, model, call_type, max_tokens, temperature", CASES )
def test_each_wrapper_honours_explicit_max_tokens_and_temperature( make, method, model, call_type, max_tokens, temperature ):
    client      = make()
    client._call_api = AsyncMock( return_value="R" )
    asyncio.run( getattr( client, method )( "SYS", "MSG", 7, 0.11 ) )
    kwargs = client._call_api.await_args.kwargs
    assert ( kwargs[ "max_tokens" ], kwargs[ "temperature" ] ) == ( 7, 0.11 )


@pytest.mark.parametrize( "make, model", [ ( _podcast, "SCRIPT-M" ), ( _presentation, "CONTENT-M" ) ] )
def test_json_output_uses_the_same_model_field_at_temperature_half( make, model ):
    from cosa.agents.podcast_generator.api_client import APIResponse
    client      = make()
    client._call_api = AsyncMock( return_value=APIResponse( content='{"k": 1}', model="m", input_tokens=1, output_tokens=1, stop_reason="end_turn" ) )
    assert asyncio.run( client.call_with_json_output( "SYS", "MSG", 99 ) ) == { "k": 1 }
    assert client._call_api.await_args.kwargs == {
        "model": model, "system_prompt": "SYS", "user_message": "MSG",
        "max_tokens": 99, "temperature": 0.5, "call_type": "json_output",
    }


def test_the_debug_banners_name_each_clients_own_model_field( capsys ):
    _podcast( debug=True )
    _presentation( debug=True )
    out = capsys.readouterr().out.splitlines()
    assert out == [
        "[PodcastAPIClient] Bounded-CC mode (in-process sdk_query, Max-plan OAuth)",
        "[PodcastAPIClient] Script model: SCRIPT-M",
        "[PresentationAPIClient] Bounded-CC mode (in-process sdk_query, Max-plan OAuth)",
        "[PresentationAPIClient] Content model: CONTENT-M",
    ]


def test_both_cost_summaries_read_the_same_way():
    from cosa.agents.podcast_generator.api_client import CostEstimate as PodcastCost
    from cosa.agents.presentation_generator.api_client import CostEstimate as PresentationCost
    for cls in ( PodcastCost, PresentationCost ):
        estimate = cls()
        estimate.add_usage( "claude-sonnet-x", 1000, 2000 )
        estimate.add_sdk_cost( 0.25 )
        assert estimate.get_summary() == (
            "API Calls: 1 | Tokens: 1,000 in, 2,000 out | Est. Cost: $0.0330 | "
            "SDK telemetry: $0.2500 (covered by Max plan — not billed per-token)"
        )
