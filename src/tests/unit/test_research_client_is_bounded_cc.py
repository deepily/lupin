"""
Tests that ResearchAPIClient is a BoundedCCClientBase and keeps what made it different.

One behaviour per test: the debug banner text, the absent cost estimate, the cost tracker, the
shared SDK refusal and the client's own call_with_json_output signature.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from cosa.agents.deep_research import api_client as ac
from cosa.agents.deep_research.api_client import APIResponse, ResearchAPIClient
from cosa.agents.deep_research.config import ResearchConfig
from cosa.agents.shared.bounded_cc_client import BoundedCCClientBase


def test_the_research_client_is_a_bounded_cc_client():
    assert issubclass( ResearchAPIClient, BoundedCCClientBase )
    assert isinstance( ResearchAPIClient( config=ResearchConfig() ), BoundedCCClientBase )


def test_the_debug_banner_keeps_its_two_lines_and_names_both_models( capsys ):
    ResearchAPIClient( config=ResearchConfig( lead_model="LEAD-M", subagent_model="SUB-M" ), debug=True )
    lines = [ line for line in capsys.readouterr().out.splitlines() if line.startswith( "[ResearchAPIClient]" ) and ( "Bounded-CC mode" in line or "Models:" in line ) ]
    assert lines == [
        "[ResearchAPIClient] Bounded-CC mode (in-process sdk_query, Max-plan OAuth)",
        "[ResearchAPIClient] Models: lead=LEAD-M, subagent=SUB-M",
    ]


def test_the_research_client_has_no_cost_estimate_and_keeps_its_cost_tracker():
    tracker = object()
    client  = ResearchAPIClient( config=ResearchConfig(), cost_tracker=tracker )
    assert client.cost_estimate is None
    assert client.cost_tracker is tracker


def test_the_research_client_refuses_without_the_sdk_through_the_shared_check():
    with patch.object( ac, "SDK_AVAILABLE", False ):
        with pytest.raises( ImportError, match="claude_agent_sdk not installed" ):
            ResearchAPIClient()


def test_json_output_still_takes_a_model_and_a_call_type_and_defaults_to_the_lead_model():
    config = ResearchConfig( lead_model="LEAD-M" )
    client = ResearchAPIClient( config=config )
    client._call_sdk = AsyncMock( return_value=APIResponse( content='{"k": 1}', model="m", input_tokens=1, output_tokens=1, stop_reason="end_turn" ) )
    assert asyncio.run( client.call_with_json_output( "SYS", "MSG" ) ) == { "k": 1 }
    assert client._call_sdk.await_args.kwargs[ "model" ] == "LEAD-M"
    assert client._call_sdk.await_args.kwargs[ "call_type" ] == "structured"
    asyncio.run( client.call_with_json_output( "SYS", "MSG", model="OTHER-M", call_type="custom" ) )
    assert ( client._call_sdk.await_args.kwargs[ "model" ], client._call_sdk.await_args.kwargs[ "call_type" ] ) == ( "OTHER-M", "custom" )
