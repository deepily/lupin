"""
Unit tests for cosa.agents.deep_research.cost_tracker.

NEW FILE 2026-05-31 by Rio ⚡ (CoSA coverage campaign, deep_research lane). Pure
cost-accounting logic — no network/LLM (token counts are passed in directly, as the
real callers do from response.usage). Covers pricing tiers, budget enforcement,
aggregation, and report formatting.
"""

import unittest

from cosa.agents.deep_research.cost_tracker import (
    CostTracker,
    UsageRecord,
    SessionSummary,
    BudgetExceededError,
    ModelTier,
    MODEL_PRICING,
    MODEL_NAME_TO_TIER,
)


class TestCalculateCost( unittest.TestCase ):
    """_calculate_cost — tier lookup, unknown fallback, cache pricing."""

    def test_known_model_input_output( self ):
        t = CostTracker( "s" )
        # Sonnet: $3/1M in, $15/1M out → 1M in + 1M out = 3 + 15 = 18.0
        cost = t._calculate_cost( "claude-sonnet-4-5", 1_000_000, 1_000_000 )
        self.assertAlmostEqual( cost, 18.0 )

    def test_opus_pricing( self ):
        t = CostTracker( "s" )
        cost = t._calculate_cost( "claude-opus-4-6", 1_000_000, 0 )   # opus $5/1M in
        self.assertAlmostEqual( cost, 5.0 )

    def test_unknown_model_falls_back_to_sonnet_with_debug( self ):
        t = CostTracker( "s", debug=True )
        cost = t._calculate_cost( "mystery-model", 1_000_000, 0 )     # → Sonnet $3
        self.assertAlmostEqual( cost, 3.0 )

    def test_unknown_model_no_debug( self ):
        # unknown model + debug False → the `if self.debug` FALSE arc (no print), still Sonnet pricing
        t = CostTracker( "s", debug=False )
        cost = t._calculate_cost( "mystery-model", 1_000_000, 0 )
        self.assertAlmostEqual( cost, 3.0 )

    def test_cache_token_pricing( self ):
        t = CostTracker( "s" )
        # Sonnet input $3/1M: cache_create=1M×1.25×3 = 3.75 ; cache_read=1M×0.10×3 = 0.30
        cost = t._calculate_cost( "claude-sonnet-4-5", 0, 0, cache_creation_tokens=1_000_000, cache_read_tokens=1_000_000 )
        self.assertAlmostEqual( cost, 3.75 + 0.30 )


class TestRecordUsage( unittest.TestCase ):
    """record_usage — record creation, budget enforcement, debug arm."""

    def test_records_and_returns_record( self ):
        t = CostTracker( "s", debug=True )
        rec = t.record_usage( "claude-sonnet-4-5", 1000, 500, call_type="planning" )
        self.assertIsInstance( rec, UsageRecord )
        self.assertEqual( rec.input_tokens, 1000 )
        self.assertEqual( rec.output_tokens, 500 )
        self.assertEqual( rec.call_type, "planning" )
        self.assertGreater( rec.cost_usd, 0 )

    def test_no_budget_never_raises( self ):
        t = CostTracker( "s", budget_limit_usd=None )
        # large call, no budget → fine
        t.record_usage( "claude-opus-4-5", 1_000_000, 1_000_000 )
        self.assertEqual( t.get_summary().total_calls, 1 )

    def test_budget_under_limit_ok( self ):
        t = CostTracker( "s", budget_limit_usd=100.0 )
        rec = t.record_usage( "claude-haiku-4-5", 1000, 500 )
        self.assertGreater( rec.cost_usd, 0 )

    def test_budget_exceeded_raises( self ):
        t = CostTracker( "s", budget_limit_usd=0.01 )
        with self.assertRaises( BudgetExceededError ) as cm:
            t.record_usage( "claude-opus-4-5", 1_000_000, 1_000_000 )   # ~$30 ≫ $0.01
        # The error carries the overage details the job-layer handler formats
        # ("${current_cost} spent of ${budget_limit} limit").
        self.assertEqual( cm.exception.budget_limit, 0.01 )
        self.assertGreater( cm.exception.current_cost, 0.01 )   # projected total exceeds the limit

    def test_budget_accumulates_across_calls( self ):
        t = CostTracker( "s", budget_limit_usd=0.02 )
        t.record_usage( "claude-haiku-4-5", 1000, 500 )    # tiny, ok
        with self.assertRaises( BudgetExceededError ):
            t.record_usage( "claude-opus-4-5", 1_000_000, 1_000_000 )   # pushes over


class TestRecordFromResponse( unittest.TestCase ):

    def test_extracts_usage_fields( self ):
        t = CostTracker( "s" )
        rec = t.record_from_response(
            "claude-opus-4-5",
            { "input_tokens": 2000, "output_tokens": 1000,
              "cache_creation_input_tokens": 500, "cache_read_input_tokens": 100 },
            call_type="synthesis",
            subquery_index=2,
        )
        self.assertEqual( rec.input_tokens, 2000 )
        self.assertEqual( rec.cache_creation_tokens, 500 )
        self.assertEqual( rec.cache_read_tokens, 100 )
        self.assertEqual( rec.subquery_index, 2 )

    def test_missing_keys_default_to_zero( self ):
        t = CostTracker( "s" )
        rec = t.record_from_response( "claude-sonnet-4-5", {} )   # empty usage
        self.assertEqual( rec.input_tokens, 0 )
        self.assertEqual( rec.output_tokens, 0 )
        self.assertEqual( rec.cache_creation_tokens, 0 )


class TestGetSummary( unittest.TestCase ):

    def test_empty_summary( self ):
        t = CostTracker( "s" )
        s = t.get_summary()
        self.assertIsInstance( s, SessionSummary )
        self.assertEqual( s.total_calls, 0 )
        self.assertEqual( s.total_cost_usd, 0.0 )
        self.assertIsNone( s.budget_remaining_usd )            # no budget set

    def test_aggregates_by_type_and_model( self ):
        t = CostTracker( "s", budget_limit_usd=1000.0 )
        t.record_usage( "claude-sonnet-4-5", 1000, 500, call_type="planning" )
        t.record_usage( "claude-sonnet-4-5", 2000, 800, call_type="planning" )   # same type+model → 2nd arc
        t.record_usage( "claude-opus-4-5",  500, 200, call_type="synthesis" )
        s = t.get_summary()
        self.assertEqual( s.total_calls, 3 )
        self.assertEqual( s.total_input_tokens, 3500 )
        self.assertEqual( s.calls_by_type[ "planning" ][ "count" ], 2 )
        self.assertIn( "synthesis", s.calls_by_type )
        self.assertIn( "claude-sonnet-4-5", s.cost_by_model )
        self.assertIn( "claude-opus-4-5", s.cost_by_model )
        self.assertIsNotNone( s.budget_remaining_usd )         # budget set → remaining computed
        self.assertLess( s.budget_remaining_usd, 1000.0 )
        self.assertGreaterEqual( s.duration_seconds, 0.0 )


class TestGetCostReport( unittest.TestCase ):

    def test_minimal_report_no_records_no_budget( self ):
        t = CostTracker( "empty-session" )
        report = t.get_cost_report()
        self.assertIn( "Session ID: empty-session", report )
        self.assertIn( "Total Cost: $0.0000", report )
        self.assertNotIn( "Budget Remaining", report )         # no budget
        self.assertNotIn( "Cost by Call Type:", report )       # no records
        self.assertNotIn( "Cost by Model:", report )

    def test_full_report_with_budget_types_and_models( self ):
        t = CostTracker( "rich-session", budget_limit_usd=50.0 )
        t.record_usage( "claude-sonnet-4-5", 1000, 500, call_type="planning" )
        t.record_usage( "claude-opus-4-5", 2000, 1000, call_type="synthesis" )
        report = t.get_cost_report()
        self.assertIn( "Budget Remaining", report )
        self.assertIn( "Cost by Call Type:", report )
        self.assertIn( "planning:", report )
        self.assertIn( "Cost by Model:", report )
        self.assertIn( "claude-opus-4-5:", report )


class TestPricingTables( unittest.TestCase ):

    def test_every_mapped_name_has_pricing( self ):
        for name, tier in MODEL_NAME_TO_TIER.items():
            self.assertIn( tier, MODEL_PRICING )
            self.assertIn( "input", MODEL_PRICING[ tier ] )
            self.assertIn( "output", MODEL_PRICING[ tier ] )

    def test_tier_enum_values( self ):
        self.assertEqual( ModelTier.OPUS_4_5.value, "opus-4-5" )
        self.assertEqual( ModelTier.HAIKU_4_5.value, "haiku-4-5" )


if __name__ == "__main__":
    unittest.main()
