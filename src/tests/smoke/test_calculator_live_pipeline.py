#!/usr/bin/env python3
"""
Smoke test for Calculator agent via live pipeline (Steps 24 & 25 of testing ladder).

Verifies the full end-to-end pipeline:
  TodoFifoQueue -> mode bypass -> CalculatorAgent -> Phi-4 intent extraction
  -> dispatch -> TTS response

Step 24 (default): Explicitly sets calculator mode, bypassing LORA router.
Step 25 (--auto-route): No mode set — verifies LORA router classifies queries correctly.

Tests 6 queries covering: unit conversion, price comparison, mortgage calculation.

Usage:
    # Step 24: Run all 6 queries with explicit calculator mode (default)
    python src/tests/smoke/test_calculator_live_pipeline.py

    # Step 25: Run all 6 queries via LORA auto-routing
    python src/tests/smoke/test_calculator_live_pipeline.py --auto-route

    # Run only query 0 (CONVERT_KM)
    python src/tests/smoke/test_calculator_live_pipeline.py --queries 0

    # Run queries 0, 2, 4
    python src/tests/smoke/test_calculator_live_pipeline.py -q 0,2,4

    # Combined: specific queries + auto-route
    python src/tests/smoke/test_calculator_live_pipeline.py --auto-route -q 0,1,4

Query index reference:
    0: CONVERT_KM      — How many miles is 10 kilometers?
    1: CONVERT_TEMP    — Convert 72 Fahrenheit to Celsius
    2: CONVERT_WEIGHT  — 500 grams in pounds
    3: COMPARE_PRICE   — Compare 12 oz at $3.49 vs 24 oz at $5.99
    4: MORTGAGE        — Monthly payment on $300k mortgage at 6.5% for 30 years
    5: CONVERT_ML      — What's 500 ml in cups?

Requires:
    - Server running on localhost:7999
    - Phi-4 LLM server running for intent extraction
    - Environment variables:
        LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD

Created: 2026-02-10 (Session 172)
Updated: 2026-02-11 — Added --auto-route flag for Step 25 (LORA routing verification)
Refactored: 2026-02-13 — Migrated to LivePipelineTestBase
"""

import os
import sys

# Bootstrap path setup
lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root:
    sys.path.insert( 0, os.path.join( lupin_root, "src" ) )

from tests.smoke.utilities.live_pipeline_base import LivePipelineTestBase


# ═══════════════════════════════════════════════════════════════════════════════
# Test Matrix
# ═══════════════════════════════════════════════════════════════════════════════

CALCULATOR_QUERIES = [
    {
        "id"               : "ARITHMETIC_SUBTRACT",
        "query"            : "How much is 789 minus 456?",
        "expected_op"      : "arithmetic",
        "expected_keywords" : [ "333" ],
    },
    {
        "id"               : "ARITHMETIC_SUM",
        "query"            : "What is the sum of 98, 134, and 201?",
        "expected_op"      : "arithmetic",
        "expected_keywords" : [ "433" ],
    },
    {
        "id"               : "ARITHMETIC_PRODUCT",
        "query"            : "What is the product of 64 and 23?",
        "expected_op"      : "arithmetic",
        "expected_keywords" : [ "1,472", "1472" ],
    },
    {
        "id"               : "CONVERT_KM",
        "query"            : "How many miles is 10 kilometers?",
        "expected_op"      : "convert",
        "expected_keywords" : [ "6.21", "6.2" ],
    },
    {
        "id"               : "CONVERT_TEMP",
        "query"            : "Convert 72 Fahrenheit to Celsius",
        "expected_op"      : "convert",
        "expected_keywords" : [ "22.2", "22.22" ],
    },
    {
        "id"               : "CONVERT_WEIGHT",
        "query"            : "500 grams in pounds",
        "expected_op"      : "convert",
        "expected_keywords" : [ "1.1", "1.10" ],
    },
    {
        "id"               : "COMPARE_PRICE",
        "query"            : "Compare 12 oz at $3.49 vs 24 oz at $5.99",
        "expected_op"      : "compare_prices",
        "expected_keywords" : [ "cheaper", "better", "value", "per" ],
    },
    {
        "id"               : "MORTGAGE",
        "query"            : "Monthly payment on $300k mortgage at 6.5% for 30 years",
        "expected_op"      : "mortgage",
        "expected_keywords" : [ "1,896", "1896", "1,897", "1897" ],
    },
    {
        "id"               : "CONVERT_ML",
        "query"            : "What's 500 ml in cups?",
        "expected_op"      : "convert",
        "expected_keywords" : [ "2.1", "2.11" ],
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# Calculator Test Class
# ═══════════════════════════════════════════════════════════════════════════════

class CalculatorPipelineTest( LivePipelineTestBase ):
    """
    Smoke test for Calculator agent via live pipeline.

    Requires:
        - Server running on port 7999
        - Phi-4 LLM server running for intent extraction

    Ensures:
        - Step 24: Explicit calculator mode routes correctly
        - Step 25: LORA auto-routing classifies queries to CalculatorAgent
    """

    TEST_NAME       = "Calculator Live Pipeline"
    SCENARIOS       = CALCULATOR_QUERIES
    DEFAULT_TIMEOUT = 120

    def build_argparser( self ):
        """Add calculator-specific CLI arguments."""
        parser = super().build_argparser()
        parser.add_argument(
            "--queries", "-q",
            type=str,
            default=None,
            help="Comma-separated query indices to run (e.g., '0,1,3'). Default: all."
        )
        parser.add_argument(
            "--auto-route", "-a",
            action="store_true",
            default=False,
            help="Skip setting calculator mode. Tests LORA auto-routing (Step 25)."
        )
        return parser

    def get_scenario_indices( self, args ):
        """
        Parse --queries flag for selective query execution.

        Ensures:
            - Returns list of valid indices into CALCULATOR_QUERIES
        """
        if hasattr( args, "queries" ) and args.queries:
            return [ int( x.strip() ) for x in args.queries.split( "," ) if int( x.strip() ) < len( self.SCENARIOS ) ]
        return list( range( len( self.SCENARIOS ) ) )

    def get_mode_for_scenario( self, scenario ):
        """
        Return 'calculator' for explicit mode, or None for auto-route.

        Ensures:
            - Returns 'calculator' if not in auto-route mode
            - Returns None if auto-route mode is active
        """
        if self._auto_route:
            return None
        return "calculator"

    def validate_result( self, scenario, job_data ):
        """
        Validate answer keywords and optionally verify LORA routing.

        Ensures:
            - Checks agent_type == CalculatorAgent in auto-route mode
            - Checks answer contains expected keywords
        """
        # Auto-route: verify LORA routed to CalculatorAgent
        if self._auto_route:
            agent_type = job_data.get( "agent_type", "" )
            if agent_type != "CalculatorAgent":
                return {
                    "status"         : "fail",
                    "answer_preview" : "",
                    "details"        : f"Routed to {agent_type}, expected CalculatorAgent",
                }
            print( f"    Routing: correctly routed to {agent_type}" )

        # Default keyword validation
        result = super().validate_result( scenario, job_data )

        # Append auto-route note to passing results
        if self._auto_route and result[ "status" ] == "pass":
            result[ "details" ] += " (auto-routed)"

        return result

    def _print_scenario_header( self, scenario ):
        """Print calculator-specific scenario details."""
        print( f"  Question: \"{scenario[ 'query' ]}\"" )
        print( f"  Expected op: {scenario[ 'expected_op' ]}" )
        print( f"  Expected keywords: {scenario[ 'expected_keywords' ]}" )

    def run_scenarios( self, args=None ):
        """
        Override to capture auto_route state before running.

        Ensures:
            - self._auto_route is set before scenario execution
        """
        self._auto_route = getattr( args, "auto_route", False )

        # Update test label based on routing mode
        if self._auto_route:
            self.TEST_NAME = "Calculator Auto-Route (LORA routing)"
        else:
            self.TEST_NAME = "Calculator Live Pipeline"

        return super().run_scenarios( args )


# ═══════════════════════════════════════════════════════════════════════════════
# Pytest + CLI Entry Points
# ═══════════════════════════════════════════════════════════════════════════════

def quick_smoke_test( query_indices=None, auto_route=False ):
    """
    Backward-compatible entry point for direct invocation.

    Requires:
        - query_indices is None (all) or list of valid ints
        - auto_route is a boolean

    Ensures:
        - Returns True if all selected queries pass
    """
    import argparse
    test = CalculatorPipelineTest()
    args = argparse.Namespace(
        queries    = ",".join( str( i ) for i in query_indices ) if query_indices else None,
        auto_route = auto_route,
        debug      = False,
        verbose    = False,
    )
    return test.run_scenarios( args )


def test_calculator_live_pipeline():
    """Pytest entry point."""
    assert quick_smoke_test()


if __name__ == "__main__":
    test    = CalculatorPipelineTest()
    success = test.run( sys.argv[ 1: ] )
    sys.exit( 0 if success else 1 )
