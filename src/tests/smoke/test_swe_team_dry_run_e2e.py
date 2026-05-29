#!/usr/bin/env python3
"""
Tier-2 smoke test: SWE Team dry-run end-to-end through the REAL notify path.

This is the legitimate end-to-end "regression" check that the now-rewritten
`TestDryRunRegression` class in `src/tests/unit/test_swe_team_orchestrator.py`
USED to pretend to be. The unit-test version mocks everything for speed
(<100ms per test); this smoke test verifies the actual wires are still
connected by calling `orch.run()` against the real
`cosa.agents.swe_team.cosa_interface` dispatcher with no mocks.

Authored 2026-04-30 (Session b195a160) as part of the
test_swe_team_orchestrator.py performance fix. Design + diagnosis at
src/rnd/v0.1.7/2026.04.30-swe-team-orchestrator-test-perf-fix.md.

Venue: :8000 (scheduled monopolize-mode). Initially designed for :7999, but the
real dispatcher takes ~196s wall-clock, exceeding the 2-min :7999 cap per the
testing-venues rubric in CLAUDE.md. Submit via /api/test-suite/submit with
non-overlapping scheduled_at — DO NOT side-door inject. Non-destructive
(dry_run=True), no DB writes, ~3-4 minute runtime.

Usage:
    # Standalone CLI
    python src/tests/smoke/test_swe_team_dry_run_e2e.py

    # Via pytest
    pytest src/tests/smoke/test_swe_team_dry_run_e2e.py -v

Requires:
    - cosa.agents.swe_team is importable (LUPIN_ROOT or PYTHONPATH set up)
    - Real notify dispatcher reachable (will exercise the IPC/HTTP path)

Note: this test does NOT require a live server because the dispatcher's
fire-and-forget notify_progress writes to a thread pool; failures are logged
but don't propagate. So even in CLI mode the dry-run completes. The PURPOSE
of this smoke is to catch a hung dispatcher (would manifest as wall-clock >30s).
"""

import asyncio
import os
import sys
import time

# Bootstrap path setup
lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root:
    sys.path.insert( 0, os.path.join( lupin_root, "src" ) )

import cosa.utils.util as cu


# Wall-clock budget. Reality check from first run on 2026-04-30:
# the smoke completes in ~196s under typical load — each of the 7+ breadcrumb
# notifications goes through asyncio.to_thread(_notify_user_async, ...) and
# takes ~25-30s through the dispatcher's IPC layer. The 240s budget gives
# ~25% margin over observed; a hung dispatcher (>240s wall-clock) trips this
# loudly. If you see budget exhaustion frequently, treat as a dispatcher
# performance regression — file a follow-up.
#
# Note: this slowness is INTENTIONAL test surface. The Tier-1 unit tests in
# test_swe_team_orchestrator.py mock the dispatcher and run in milliseconds;
# this Tier-2 smoke specifically exercises the unmocked path so dispatcher
# health is observable.
WALL_CLOCK_BUDGET_SECONDS = 240


def quick_smoke_test():
    """
    End-to-end dry-run smoke against the real notify dispatcher.

    Returns:
        bool: True if dry-run completes within budget, False on failure
    """
    cu.print_banner( "SWE Team Dry-Run E2E Smoke Test", prepend_nl=True )

    try:
        from cosa.agents.swe_team.config import SweTeamConfig
        from cosa.agents.swe_team.orchestrator import SweTeamOrchestrator
        from cosa.agents.swe_team.state import OrchestratorState

        print( "\nStep 1: Constructing dry-run orchestrator..." )
        config = SweTeamConfig( dry_run=True )
        orch = SweTeamOrchestrator(
            task_description = "Smoke test: add a /health endpoint",
            config           = config,
        )
        print( f"  Constructed: session_id={orch.session_id}" )

        print( "\nStep 2: Running orch.run() against real notify dispatcher..." )
        t0 = time.time()
        result = asyncio.run( orch.run() )
        elapsed = time.time() - t0
        print( f"  Completed in {elapsed:.1f}s (budget: {WALL_CLOCK_BUDGET_SECONDS}s)" )

        if elapsed > WALL_CLOCK_BUDGET_SECONDS:
            print( f"  FAIL: dry-run took {elapsed:.1f}s, exceeded budget {WALL_CLOCK_BUDGET_SECONDS}s." )
            print( "  Likely cause: notify dispatcher hung / system load too high." )
            return False

        print( "\nStep 3: Asserting outcome shape..." )
        if result is None:
            print( "  FAIL: orch.run() returned None" )
            return False
        if "Dry-run complete" not in result:
            print( f"  FAIL: result missing 'Dry-run complete' marker: {result[ :120 ]}..." )
            return False
        if orch.current_state != OrchestratorState.COMPLETED:
            print( f"  FAIL: state is {orch.current_state}, expected COMPLETED" )
            return False
        print( f"  ✓ result shape OK: '{result[ :80 ]}...'" )
        print( f"  ✓ state         : {orch.current_state}" )
        print( f"  ✓ session_id    : {orch.session_id}" )

        print( "\nPASS: dry-run end-to-end smoke completed cleanly" )
        return True

    except Exception as e:
        print( f"\nFAIL: {type( e ).__name__}: {e}" )
        import traceback
        traceback.print_exc()
        return False


def test_swe_team_dry_run_e2e():
    """Pytest entry point."""
    assert quick_smoke_test()


if __name__ == "__main__":
    success = quick_smoke_test()
    sys.exit( 0 if success else 1 )
