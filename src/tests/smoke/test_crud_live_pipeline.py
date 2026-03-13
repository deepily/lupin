#!/usr/bin/env python3
"""
Smoke test for CRUD agent via live pipeline.

Verifies the full end-to-end pipeline:
  TodoFifoQueue -> mode bypass -> CrudForDataFramesAgent -> Phi-4 intent extraction
  -> dispatch -> storage -> voice confirmation -> TTS response

Tests 8 scenarios covering: add, query, dedup guard, delete with confirmation,
calendar schema, and LORA routing.

Usage:
    # Direct-mode only — scenarios 0-5, no LORA needed (DEFAULT)
    python src/tests/smoke/test_crud_live_pipeline.py --mode direct

    # LORA routing tests — scenarios 6-7, requires trained adapter
    python src/tests/smoke/test_crud_live_pipeline.py --mode lora

    # All scenarios — direct + LORA (requires trained adapter)
    python src/tests/smoke/test_crud_live_pipeline.py --mode all

    # With auto-proxy for auto-confirmed delete (single terminal!):
    python src/tests/smoke/test_crud_live_pipeline.py --mode direct --auto-proxy

    # Without auto-proxy (manual proxy in separate terminal):
    # Terminal 2: python -m cosa.agents.notification_proxy --profile crud --debug
    # Terminal 3: python src/tests/smoke/test_crud_live_pipeline.py --mode direct

Requires:
    - Server running on localhost:7999
    - Phi-4 LLM server running for intent extraction
    - Environment variables:
        LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD

Created: 2026-02-11 (Session 189)
Refactored: 2026-02-13 — Migrated to InteractiveSmokeTest
"""

import os
import sys

# Bootstrap path setup
lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root:
    sys.path.insert( 0, os.path.join( lupin_root, "src" ) )

from tests.smoke.utilities.interactive_smoke_test import InteractiveSmokeTest


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario Matrix
# ═══════════════════════════════════════════════════════════════════════════════

CRUD_SCENARIOS = [
    # --- Direct-mode scenarios (0-5) ---
    {
        "id"                : "ADD_TODO",
        "query"             : "add buy milk to my grocery list",
        "mode"              : "todo",
        "needs_confirm"     : False,
        "expected_keywords" : [ "done", "added", "milk", "already exists" ],
        "expected_status"   : [ "added", "duplicate" ],
    },
    {
        "id"                : "ADD_TODO_2",
        "query"             : "add buy bread to my grocery list",
        "mode"              : "todo",
        "needs_confirm"     : False,
        "expected_keywords" : [ "done", "added", "bread", "already exists" ],
        "expected_status"   : [ "added", "duplicate" ],
    },
    {
        "id"                : "QUERY_TODO",
        "query"             : "what's on my grocery list?",
        "mode"              : "todo",
        "needs_confirm"     : False,
        "expected_keywords" : [ "found", "milk", "bread", "item" ],
        "expected_status"   : [ "ok" ],
    },
    {
        "id"                : "ADD_DUPLICATE",
        "query"             : "add buy milk to my grocery list",
        "mode"              : "todo",
        "needs_confirm"     : False,
        "expected_keywords" : [ "already exists", "duplicate" ],
        "expected_status"   : [ "duplicate" ],
    },
    {
        "id"                : "DELETE_TODO",
        "query"             : "delete buy bread from my grocery list",
        "mode"              : "todo",
        "needs_confirm"     : True,
        "timeout"           : 180,
        "expected_keywords" : [ "done", "deleted", "removed", "cancelled", "cancel" ],
        "expected_status"   : [ "deleted", "cancelled" ],
    },
    {
        "id"                : "ADD_CALENDAR",
        "query"             : "add dentist appointment on March 15 at 2pm",
        "mode"              : "calendar",
        "needs_confirm"     : False,
        "expected_keywords" : [ "done", "added", "dentist", "already exists" ],
        "expected_status"   : [ "added", "duplicate" ],
    },
    # --- LORA routing scenarios (6-7) ---
    {
        "id"                : "LORA_ADD_TODO",
        "query"             : "put eggs on my shopping list",
        "mode"              : None,
        "needs_confirm"     : False,
        "expected_keywords" : [ "done", "added", "eggs" ],
        "expected_status"   : [ "added" ],
    },
    {
        "id"                : "LORA_QUERY_TODO",
        "query"             : "what do I need to buy?",
        "mode"              : None,
        "needs_confirm"     : False,
        "expected_keywords" : [ "found", "item", "milk", "eggs" ],
        "expected_status"   : [ "ok" ],
    },
]

# Mode -> scenario index mapping
MODE_SCENARIOS = {
    "direct" : [ 0, 1, 2, 3, 4, 5 ],
    "lora"   : [ 6, 7 ],
    "all"    : [ 0, 1, 2, 3, 4, 5, 6, 7 ],
}


# ═══════════════════════════════════════════════════════════════════════════════
# CRUD Test Class
# ═══════════════════════════════════════════════════════════════════════════════

class CrudPipelineTest( InteractiveSmokeTest ):
    """
    Smoke test for CRUD agent via live pipeline.

    Requires:
        - Server running on port 7999
        - Phi-4 LLM server running for intent extraction
        - For delete scenarios: notification proxy (manual or --auto-proxy)

    Ensures:
        - Correct mode switching per scenario
        - Add, query, dedup, delete, and calendar operations work
        - LORA routing classifies CRUD queries correctly
    """

    TEST_NAME       = "CRUD Live Pipeline"
    SCENARIOS       = CRUD_SCENARIOS
    DEFAULT_TIMEOUT = 120
    PROXY_PROFILE   = "crud"
    PROXY_STRATEGY  = "auto"

    def build_argparser( self ):
        """Add CRUD-specific CLI arguments."""
        parser = super().build_argparser()
        parser.add_argument(
            "--mode", "-m",
            choices=[ "direct", "lora", "all" ],
            default="direct",
            help="Test mode: 'direct' (no LORA, default), 'lora' (LORA routing only), 'all' (everything)"
        )
        return parser

    def get_scenario_indices( self, args ):
        """
        Map --mode flag to scenario indices.

        Ensures:
            - Returns indices matching the selected mode
        """
        mode = getattr( args, "mode", "direct" )
        return MODE_SCENARIOS.get( mode, MODE_SCENARIOS[ "direct" ] )

    def get_mode_for_scenario( self, scenario ):
        """
        Return per-scenario mode for CRUD (dynamic mode switching).

        Ensures:
            - Returns mode from scenario dict, or None for LORA routing
        """
        return scenario.get( "mode" )

    def _print_scenario_header( self, scenario ):
        """Print CRUD-specific scenario details."""
        print( f"  Query: \"{scenario[ 'query' ]}\"" )
        print( f"  Mode: {scenario[ 'mode' ] or 'system (LORA routing)'}" )
        print( f"  Confirm: {'Yes' if scenario[ 'needs_confirm' ] else 'No'}" )
        print( f"  Expected keywords: {scenario[ 'expected_keywords' ]}" )

    def run_scenarios( self, args=None ):
        """
        Override to update label with selected mode.

        Ensures:
            - TEST_NAME reflects the selected mode
        """
        mode = getattr( args, "mode", "direct" )
        self.TEST_NAME = f"CRUD Live Pipeline ({mode} mode)"
        return super().run_scenarios( args )


# ═══════════════════════════════════════════════════════════════════════════════
# Pytest + CLI Entry Points
# ═══════════════════════════════════════════════════════════════════════════════

def quick_smoke_test( mode="direct" ):
    """
    Backward-compatible entry point for direct invocation.

    Requires:
        - mode is one of: "direct", "lora", "all"

    Ensures:
        - Returns True if all selected scenarios pass
    """
    import argparse
    test = CrudPipelineTest()
    args = argparse.Namespace(
        mode        = mode,
        auto_proxy  = False,
        proxy_debug = False,
        debug       = False,
        verbose     = False,
    )
    return test.run_scenarios( args )


def test_crud_live_pipeline():
    """Pytest entry point."""
    assert quick_smoke_test()


if __name__ == "__main__":
    test    = CrudPipelineTest()
    success = test.run( sys.argv[ 1: ] )
    sys.exit( 0 if success else 1 )
