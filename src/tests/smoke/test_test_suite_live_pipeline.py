#!/usr/bin/env python3
"""
Smoke test for Test Suite agent via live pipeline.

⚠️ VENUE: :8000 (test), NOT :7999 — AND THIS FILE IS STILL RUN BY THE :7999 SMOKE TIER,
   SO IT IS EXPECTED RED THERE. Recorded 2026-08-26 (row 554e5d3e); NOT MOVED, deliberately.

   Criterion tripped (CLAUDE.md § TESTING VENUES — a file is :8000 if ANY apply):
     - runtime > 2 minutes
     - enqueues real work (drives a TestSuiteJob end-to-end through the queue)
   Evidence, from this file:
     - `DEFAULT_TIMEOUT = 1200  # 20 min (real E2E can take ~19 min)`
     - submits through the live pipeline: request -> TodoFifoQueue -> TestSuiteJob
   WHY IT WAS NOT MOVED. `run-smoke-tests.sh` runs the whole `src/tests/smoke/` directory,
   so this file is executed on :7999 by the smoke merge gate regardless of what its
   docstring says. Relocating it, or excluding it from the runner the way
   test_proxy_integration.py is excluded, would deselect it from that gate — a change to
   what the gate covers, which is an owner's decision and not a drive-by while clearing a
   red list. So it stays, it stays red on :7999, and the reason is written here instead of
   being re-derived by the next reader.

   HOW TO RUN IT PROPERLY: submit via `POST /api/test-suite/submit` against :8000 on a
   verified-idle server (`PYTHONPATH=src python3 -m cosa.rest.venue_idle --port 8000`,
   exit 0 = IDLE). Never side-door it via curl or a direct queue push.

Verifies the full end-to-end pipeline:
  TestSuiteSubmitRequest -> REST endpoint -> TodoFifoQueue -> TestSuiteJob

Usage:
    # Dry run only (fast — no real tests executed)
    python src/tests/smoke/test_test_suite_live_pipeline.py

    # Run specific scenario
    python src/tests/smoke/test_test_suite_live_pipeline.py -q 0

Scenario index reference:
    0: DRY_RUN_BOTH — Dry run with integration + e2e (fast validation)

Requires:
    - Server running on localhost:7999
    - Environment variables:
        LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD

Created: 2026-03-31
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

TEST_SUITE_SCENARIOS = [
    {
        "id"                : "DRY_RUN_BOTH",
        "query"             : "run both integration and e2e tests in dry run mode",
        "expected_keywords" : [ "dry run", "complete", "would have run" ],
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# Test Suite Test Class
# ═══════════════════════════════════════════════════════════════════════════════

class TestSuitePipelineTest( LivePipelineTestBase ):
    """
    Smoke test for Test Suite agent via live pipeline.

    Requires:
        - Server running on port 7999

    Ensures:
        - Dry run mode exercises pipeline wiring without running real tests
    """

    TEST_NAME       = "Test Suite Live Pipeline"
    SCENARIOS       = TEST_SUITE_SCENARIOS
    DEFAULT_TIMEOUT = 1200  # 20 min (real E2E can take ~19 min)

    def build_argparser( self ):
        """Add test-suite-specific CLI arguments."""
        parser = super().build_argparser()
        parser.add_argument(
            "--queries", "-q",
            type=str,
            default=None,
            help="Comma-separated scenario indices to run (e.g., '0'). Default: all."
        )
        return parser

    def get_scenario_indices( self, args ):
        """
        Parse --queries flag for selective scenario execution.

        Ensures:
            - Returns list of valid indices into TEST_SUITE_SCENARIOS
        """
        if hasattr( args, "queries" ) and args.queries:
            return [ int( x.strip() ) for x in args.queries.split( "," ) if int( x.strip() ) < len( self.SCENARIOS ) ]
        return list( range( len( self.SCENARIOS ) ) )

    def get_mode_for_scenario( self, scenario ):
        """
        Return 'test_suite' for explicit mode routing.

        Ensures:
            - Returns 'test_suite' to bypass LORA routing
        """
        return "test_suite"


# ═══════════════════════════════════════════════════════════════════════════════
# Pytest + Standalone Entry Points
# ═══════════════════════════════════════════════════════════════════════════════

def quick_smoke_test():
    import argparse
    test = TestSuitePipelineTest()
    args = argparse.Namespace( queries=None, debug=False, verbose=False )
    return test.run_scenarios( args )


def test_test_suite_live_pipeline():
    assert quick_smoke_test()


if __name__ == "__main__":
    test    = TestSuitePipelineTest()
    success = test.run( sys.argv[ 1: ] )
    sys.exit( 0 if success else 1 )
