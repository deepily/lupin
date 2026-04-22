#!/usr/bin/env python3
"""
Unit tests for Presentation Generator API Client.

Tests cover:
    - APIResponse and CostEstimate dataclasses
    - Cost tracking accumulation and summary formatting
    - API key resolution priority chain (without live API calls)
"""

import pytest

from cosa.agents.presentation_generator.api_client import (
    APIResponse,
    CostEstimate,
    ANTHROPIC_AVAILABLE,
    ENV_VAR_NAME,
    KEY_FILE_NAME,
)


# =============================================================================
# APIResponse Tests
# =============================================================================

class TestAPIResponse:
    """Tests for APIResponse dataclass."""

    def test_construction( self ):
        """APIResponse stores all fields correctly."""
        resp = APIResponse(
            content       = "Analysis result",
            model         = "claude-opus-4-6",
            input_tokens  = 1500,
            output_tokens = 800,
            stop_reason   = "end_turn",
        )
        assert resp.content == "Analysis result"
        assert resp.model == "claude-opus-4-6"
        assert resp.input_tokens == 1500
        assert resp.output_tokens == 800
        assert resp.stop_reason == "end_turn"
        assert resp.raw_response is None

    def test_raw_response_optional( self ):
        """raw_response defaults to None."""
        resp = APIResponse(
            content="x", model="m", input_tokens=0,
            output_tokens=0, stop_reason="end_turn"
        )
        assert resp.raw_response is None

    def test_raw_response_set( self ):
        """raw_response can be set to any value."""
        resp = APIResponse(
            content="x", model="m", input_tokens=0,
            output_tokens=0, stop_reason="end_turn",
            raw_response={ "test": True }
        )
        assert resp.raw_response == { "test": True }


# =============================================================================
# CostEstimate Tests
# =============================================================================

class TestCostEstimate:
    """Tests for CostEstimate tracking."""

    def test_initial_state( self ):
        """New CostEstimate starts at zero."""
        cost = CostEstimate()
        assert cost.total_input_tokens == 0
        assert cost.total_output_tokens == 0
        assert cost.total_api_calls == 0
        assert cost.estimated_cost_usd == 0.0

    def test_add_single_usage( self ):
        """Single usage updates all counters."""
        cost = CostEstimate()
        cost.add_usage( "claude-opus-4", 1000, 500 )
        assert cost.total_input_tokens == 1000
        assert cost.total_output_tokens == 500
        assert cost.total_api_calls == 1
        assert cost.estimated_cost_usd > 0

    def test_add_multiple_usage( self ):
        """Multiple usages accumulate correctly."""
        cost = CostEstimate()
        cost.add_usage( "claude-opus-4", 1000, 500 )
        cost.add_usage( "claude-opus-4", 2000, 1000 )
        assert cost.total_input_tokens == 3000
        assert cost.total_output_tokens == 1500
        assert cost.total_api_calls == 2

    def test_opus_pricing( self ):
        """Opus pricing uses correct rates."""
        cost = CostEstimate()
        cost.add_usage( "claude-opus-4", 1_000_000, 1_000_000 )
        # Opus: $15/M input + $75/M output = $90
        assert abs( cost.estimated_cost_usd - 90.0 ) < 0.01

    def test_sonnet_pricing( self ):
        """Non-opus models use Sonnet pricing."""
        cost = CostEstimate()
        cost.add_usage( "claude-sonnet-4", 1_000_000, 1_000_000 )
        # Sonnet: $3/M input + $15/M output = $18
        assert abs( cost.estimated_cost_usd - 18.0 ) < 0.01

    def test_mixed_model_pricing( self ):
        """Mixed Opus+Sonnet usage tracked correctly."""
        cost = CostEstimate()
        cost.add_usage( "claude-opus-4", 100, 50 )
        cost.add_usage( "claude-sonnet-4", 200, 100 )
        assert cost.total_api_calls == 2
        assert cost.total_input_tokens == 300
        assert cost.total_output_tokens == 150

    def test_summary_format( self ):
        """get_summary returns formatted string with all fields."""
        cost = CostEstimate()
        cost.add_usage( "claude-opus-4", 1000, 500 )
        summary = cost.get_summary()
        assert "API Calls: 1" in summary
        assert "1,000 in" in summary
        assert "500 out" in summary
        assert "$" in summary

    def test_summary_empty( self ):
        """get_summary works when no usage recorded."""
        cost = CostEstimate()
        summary = cost.get_summary()
        assert "API Calls: 0" in summary
        assert "$0.0000" in summary


# =============================================================================
# Module Constants Tests
# =============================================================================

class TestModuleConstants:
    """Tests for module-level constants."""

    def test_anthropic_available( self ):
        """anthropic SDK should be available in test environment."""
        assert ANTHROPIC_AVAILABLE is True

    def test_env_var_name( self ):
        """Firewalled env var name is correct."""
        assert ENV_VAR_NAME == "ANTHROPIC_API_KEY_FIREWALLED"

    def test_key_file_name( self ):
        """Key file name matches expected pattern."""
        assert KEY_FILE_NAME == "anthropic-api-key-firewalled"
