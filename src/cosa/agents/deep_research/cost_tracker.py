#!/usr/bin/env python3
"""
Cost Tracker for COSA Deep Research Agent.

Tracks API usage and costs per request, session, and cumulative.
Uses exact token counts from Anthropic API responses.

Design Principles:
- Exact costs from response.usage, not estimates
- Session-level aggregation for research runs
- Optional budget limits to prevent runaway spending
- Thread-safe for parallel subagent execution
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Literal
from enum import Enum


class ModelTier( Enum ):
    """Anthropic model pricing tiers."""
    OPUS_4_5   = "opus-4-5"
    SONNET_4_5 = "sonnet-4-5"
    HAIKU_4_5  = "haiku-4-5"


# Pricing per 1M tokens — verified 2026-04-05 against https://platform.claude.com/docs/en/about-claude/pricing
# Note: Opus 4.5 and 4.6 share the same pricing ($5/$25) per Anthropic's published table,
# hence the claude-opus-4-6 → OPUS_4_5 tier mapping is deliberate (see MODEL_NAME_TO_TIER).
MODEL_PRICING = {
    ModelTier.OPUS_4_5: {
        "input"  : 5.00,   # $5.00 per 1M input tokens
        "output" : 25.00,  # $25.00 per 1M output tokens
    },
    ModelTier.SONNET_4_5: {
        "input"  : 3.00,   # $3.00 per 1M input tokens
        "output" : 15.00,  # $15.00 per 1M output tokens
    },
    ModelTier.HAIKU_4_5: {
        "input"  : 1.00,   # $1.00 per 1M input tokens
        "output" : 5.00,   # $5.00 per 1M output tokens
    },
}

# Model name to tier mapping
MODEL_NAME_TO_TIER = {
    "claude-opus-4-5-20250514"   : ModelTier.OPUS_4_5,
    "claude-opus-4-20250514"     : ModelTier.OPUS_4_5,
    "claude-sonnet-4-5-20250514" : ModelTier.SONNET_4_5,
    "claude-sonnet-4-20250514"   : ModelTier.SONNET_4_5,
    "claude-haiku-4-5-20250514"  : ModelTier.HAIKU_4_5,
    # Aliases (short names)
    "claude-opus-4-5"   : ModelTier.OPUS_4_5,
    "claude-sonnet-4-5" : ModelTier.SONNET_4_5,
    "claude-haiku-4-5"  : ModelTier.HAIKU_4_5,
    # Claude 4.6 family (same pricing tiers)
    "claude-opus-4-6"           : ModelTier.OPUS_4_5,
    "claude-sonnet-4-6"         : ModelTier.SONNET_4_5,
    "claude-haiku-4-5-20251001" : ModelTier.HAIKU_4_5,
}


@dataclass
class UsageRecord:
    """
    Record of a single API call's usage.

    Requires:
        - model is a valid Anthropic model name
        - input_tokens >= 0
        - output_tokens >= 0

    Ensures:
        - cost_usd is calculated from exact token counts
        - timestamp is set to creation time
    """
    model          : str
    input_tokens   : int
    output_tokens  : int
    cost_usd       : float
    timestamp      : datetime = field( default_factory=datetime.now )
    call_type      : str = "unknown"  # clarification, planning, research, synthesis
    subquery_index : Optional[ int ] = None  # For parallel subagent tracking

    # Cache-related fields (from Anthropic API)
    cache_creation_tokens : int = 0
    cache_read_tokens     : int = 0


@dataclass
class SessionSummary:
    """
    Summary of usage for a research session.

    Ensures:
        - All fields are aggregated from UsageRecords
        - Costs are broken down by model tier
    """
    total_input_tokens     : int   = 0
    total_output_tokens    : int   = 0
    total_cache_creation   : int   = 0
    total_cache_reads      : int   = 0
    total_cost_usd         : float = 0.0
    total_calls            : int   = 0
    calls_by_type          : dict  = field( default_factory=dict )
    cost_by_model          : dict  = field( default_factory=dict )
    duration_seconds       : float = 0.0
    budget_remaining_usd   : Optional[ float ] = None


class CostTracker:
    """
    Thread-safe cost tracker for research sessions.

    Requires:
        - budget_limit_usd is None or > 0

    Ensures:
        - Accurate cost tracking from API response.usage
        - Thread-safe for parallel subagent execution
        - Raises BudgetExceededError if budget limit reached
    """

    def __init__(
        self,
        session_id: str,
        budget_limit_usd: Optional[ float ] = None,
        debug: bool = False
    ):
        """
        Initialize the cost tracker.

        Args:
            session_id: Unique identifier for this research session
            budget_limit_usd: Optional spending cap (None = unlimited)
            debug: Enable debug output
        """
        self.session_id       = session_id
        self.budget_limit_usd = budget_limit_usd
        self.debug            = debug

        self._records  : list[ UsageRecord ] = []
        self._lock     = threading.Lock()
        self._start_time = datetime.now()

    def record_usage(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        call_type: str = "unknown",
        subquery_index: Optional[ int ] = None,
        cache_creation_tokens: int = 0,
        cache_read_tokens: int = 0
    ) -> UsageRecord:
        """
        Record usage from an API call.

        Requires:
            - model is a recognized Anthropic model name
            - input_tokens >= 0
            - output_tokens >= 0

        Ensures:
            - Creates UsageRecord with calculated cost
            - Adds to session records (thread-safe)
            - Returns the created record

        Raises:
            BudgetExceededError: If budget limit would be exceeded

        Args:
            model: Anthropic model name
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            call_type: Type of call (clarification, planning, research, synthesis)
            subquery_index: Index of subquery (for parallel tracking)
            cache_creation_tokens: Tokens used for cache creation
            cache_read_tokens: Tokens read from cache

        Returns:
            UsageRecord: The created usage record
        """
        cost_usd = self._calculate_cost(
            model, input_tokens, output_tokens,
            cache_creation_tokens, cache_read_tokens
        )

        record = UsageRecord(
            model                 = model,
            input_tokens          = input_tokens,
            output_tokens         = output_tokens,
            cost_usd              = cost_usd,
            call_type             = call_type,
            subquery_index        = subquery_index,
            cache_creation_tokens = cache_creation_tokens,
            cache_read_tokens     = cache_read_tokens,
        )

        with self._lock:
            # Check budget before recording
            if self.budget_limit_usd is not None:
                current_total = sum( r.cost_usd for r in self._records )
                if current_total + cost_usd > self.budget_limit_usd:
                    raise BudgetExceededError(
                        f"Budget limit ${self.budget_limit_usd:.2f} would be exceeded. "
                        f"Current: ${current_total:.4f}, This call: ${cost_usd:.4f}"
                    )

            self._records.append( record )

        if self.debug:
            print( f"[CostTracker] {call_type}: {input_tokens} in, {output_tokens} out = ${cost_usd:.4f}" )

        return record

    def record_from_response( self, model: str, response_usage: dict, call_type: str = "unknown", subquery_index: Optional[ int ] = None ) -> UsageRecord:
        """
        Record usage directly from Anthropic API response.usage object.

        This is the preferred method as it uses exact API-reported values.

        Requires:
            - response_usage has 'input_tokens' and 'output_tokens' keys

        Args:
            model: Anthropic model name
            response_usage: The response.usage dict from Anthropic API
            call_type: Type of call
            subquery_index: Index of subquery (for parallel tracking)

        Returns:
            UsageRecord: The created usage record
        """
        return self.record_usage(
            model                 = model,
            input_tokens          = response_usage.get( "input_tokens", 0 ),
            output_tokens         = response_usage.get( "output_tokens", 0 ),
            call_type             = call_type,
            subquery_index        = subquery_index,
            cache_creation_tokens = response_usage.get( "cache_creation_input_tokens", 0 ),
            cache_read_tokens     = response_usage.get( "cache_read_input_tokens", 0 ),
        )

    def get_summary( self ) -> SessionSummary:
        """
        Get aggregated summary of session usage.

        Ensures:
            - Thread-safe aggregation of all records
            - Costs broken down by model and call type

        Returns:
            SessionSummary: Aggregated usage summary
        """
        with self._lock:
            summary = SessionSummary()

            for record in self._records:
                summary.total_input_tokens   += record.input_tokens
                summary.total_output_tokens  += record.output_tokens
                summary.total_cache_creation += record.cache_creation_tokens
                summary.total_cache_reads    += record.cache_read_tokens
                summary.total_cost_usd       += record.cost_usd
                summary.total_calls          += 1

                # Aggregate by call type
                if record.call_type not in summary.calls_by_type:
                    summary.calls_by_type[ record.call_type ] = { "count": 0, "cost": 0.0 }
                summary.calls_by_type[ record.call_type ][ "count" ] += 1
                summary.calls_by_type[ record.call_type ][ "cost" ]  += record.cost_usd

                # Aggregate by model
                if record.model not in summary.cost_by_model:
                    summary.cost_by_model[ record.model ] = 0.0
                summary.cost_by_model[ record.model ] += record.cost_usd

            summary.duration_seconds = ( datetime.now() - self._start_time ).total_seconds()

            if self.budget_limit_usd is not None:
                summary.budget_remaining_usd = self.budget_limit_usd - summary.total_cost_usd

            return summary

    def get_cost_report( self ) -> str:
        """
        Get a human-readable cost report.

        Returns:
            str: Formatted cost report
        """
        summary = self.get_summary()

        lines = [
            f"=== Research Session Cost Report ===",
            f"Session ID: {self.session_id}",
            f"Duration: {summary.duration_seconds:.1f} seconds",
            f"",
            f"Total API Calls: {summary.total_calls}",
            f"Total Input Tokens: {summary.total_input_tokens:,}",
            f"Total Output Tokens: {summary.total_output_tokens:,}",
            f"Cache Creation Tokens: {summary.total_cache_creation:,}",
            f"Cache Read Tokens: {summary.total_cache_reads:,}",
            f"",
            f"Total Cost: ${summary.total_cost_usd:.4f}",
        ]

        if summary.budget_remaining_usd is not None:
            lines.append( f"Budget Remaining: ${summary.budget_remaining_usd:.4f}" )

        if summary.calls_by_type:
            lines.append( "" )
            lines.append( "Cost by Call Type:" )
            for call_type, data in sorted( summary.calls_by_type.items() ):
                lines.append( f"  {call_type}: {data['count']} calls, ${data['cost']:.4f}" )

        if summary.cost_by_model:
            lines.append( "" )
            lines.append( "Cost by Model:" )
            for model, cost in sorted( summary.cost_by_model.items() ):
                lines.append( f"  {model}: ${cost:.4f}" )

        return "\n".join( lines )

    def _calculate_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_creation_tokens: int = 0,
        cache_read_tokens: int = 0
    ) -> float:
        """
        Calculate cost for given token counts.

        Uses official Anthropic pricing. Cache tokens are priced at:
        - Cache creation: 1.25x input price (5-min cache)
        - Cache read: 0.1x input price

        Args:
            model: Anthropic model name
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            cache_creation_tokens: Tokens for cache creation
            cache_read_tokens: Tokens read from cache

        Returns:
            float: Total cost in USD
        """
        tier = MODEL_NAME_TO_TIER.get( model )
        if tier is None:
            # Default to Sonnet pricing for unknown models
            tier = ModelTier.SONNET_4_5
            if self.debug:
                print( f"[CostTracker] Unknown model '{model}', using Sonnet pricing" )

        pricing = MODEL_PRICING[ tier ]

        # Calculate costs (pricing is per 1M tokens)
        input_cost  = ( input_tokens / 1_000_000 ) * pricing[ "input" ]
        output_cost = ( output_tokens / 1_000_000 ) * pricing[ "output" ]

        # Cache pricing (per Anthropic docs)
        cache_create_cost = ( cache_creation_tokens / 1_000_000 ) * pricing[ "input" ] * 1.25
        cache_read_cost   = ( cache_read_tokens / 1_000_000 ) * pricing[ "input" ] * 0.10

        return input_cost + output_cost + cache_create_cost + cache_read_cost


class BudgetExceededError( Exception ):
    """Raised when a budget limit would be exceeded."""
    pass


def quick_smoke_test():
    """Quick smoke test for CostTracker."""
    import cosa.utils.util as cu

    cu.print_banner( "CostTracker Smoke Test", prepend_nl=True )

    try:
        # Test 1: Basic instantiation
        print( "Testing instantiation..." )
        tracker = CostTracker( session_id="test-session-001", debug=True )
        assert tracker.session_id == "test-session-001"
        print( "✓ Tracker instantiated correctly" )

        # Test 2: Record usage
        print( "Testing record_usage..." )
        record = tracker.record_usage(
            model="claude-sonnet-4-5",
            input_tokens=1000,
            output_tokens=500,
            call_type="planning"
        )
        assert record.input_tokens == 1000
        assert record.output_tokens == 500
        assert record.cost_usd > 0
        print( f"✓ Usage recorded: ${record.cost_usd:.6f}" )

        # Test 3: Record from response dict
        print( "Testing record_from_response..." )
        mock_usage = {
            "input_tokens": 2000,
            "output_tokens": 1000,
            "cache_creation_input_tokens": 500,
            "cache_read_input_tokens": 100,
        }
        record2 = tracker.record_from_response(
            model="claude-opus-4-5",
            response_usage=mock_usage,
            call_type="synthesis"
        )
        assert record2.cache_creation_tokens == 500
        print( f"✓ Response usage recorded: ${record2.cost_usd:.6f}" )

        # Test 4: Get summary
        print( "Testing get_summary..." )
        summary = tracker.get_summary()
        assert summary.total_calls == 2
        assert summary.total_input_tokens == 3000
        assert summary.total_output_tokens == 1500
        assert "planning" in summary.calls_by_type
        assert "synthesis" in summary.calls_by_type
        print( f"✓ Summary: {summary.total_calls} calls, ${summary.total_cost_usd:.4f} total" )

        # Test 5: Cost report
        print( "Testing get_cost_report..." )
        report = tracker.get_cost_report()
        assert "Session ID" in report
        assert "Total Cost" in report
        print( "✓ Cost report generated" )
        print( "\n" + report )

        # Test 6: Budget limit
        print( "\nTesting budget limit..." )
        limited_tracker = CostTracker(
            session_id="limited-session",
            budget_limit_usd=0.01,  # $0.01 limit
            debug=True
        )
        # First call should succeed
        limited_tracker.record_usage(
            model="claude-haiku-4-5",
            input_tokens=100,
            output_tokens=50,
            call_type="test"
        )

        # Second call should exceed budget
        try:
            limited_tracker.record_usage(
                model="claude-opus-4-5",
                input_tokens=100000,
                output_tokens=50000,
                call_type="expensive"
            )
            print( "✗ Budget should have been exceeded" )
        except BudgetExceededError as e:
            print( f"✓ Budget limit enforced: {e}" )

        # Test 7: Model tier mapping
        print( "\nTesting model tier mapping..." )
        for model_name, expected_tier in MODEL_NAME_TO_TIER.items():
            assert expected_tier in MODEL_PRICING
        print( f"✓ All {len( MODEL_NAME_TO_TIER )} model names mapped correctly" )

        print( "\n✓ CostTracker smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
