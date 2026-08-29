"""
Control-proof for run-presentation-regression.sh tier classification (row 89bfcc8f).

The runner must classify each tier by its pytest EXIT CODE, not collapse every
non-zero into "failed":
    exit 0        → PASSED
    exit 1        → FAILED       (tests collected, some failed)
    any other !=0 → NOT EXECUTED (usage 4 / no-collect 5 / interrupted 2 /
                    internal 3 / timeout 124 / unknown) — the tier never ran,
                    so it must NOT read as a failure. Only exit 0 is ever green.

Driven via the PYTEST_CMD test seam: a stub returns a chosen exit code per tier,
so the REAL shipping script's classification is exercised with zero LLM spend.
Venue :7999/unit — spawns a bash subprocess that only exits; no server, no state.
"""

import os
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT = Path( __file__ ).resolve().parents[ 1 ] / "run-presentation-regression.sh"

# Stub pytest: exit code chosen per tier via env, keyed on the test file in argv.
_STUB = """#!/bin/bash
case "$*" in
  *render_only_smoke*) exit ${STUB_RENDER_EXIT:-0} ;;
  *presentation_live_smoke*) exit ${STUB_LIVE_EXIT:-0} ;;
  *) exit 0 ;;
esac
"""


def _run( render_exit, live_exit ):
    """Run the real script with a stub pytest; return (stdout, returncode)."""
    with tempfile.NamedTemporaryFile( "w", suffix=".sh", delete=False ) as f:
        f.write( _STUB )
        stub = f.name
    os.chmod( stub, os.stat( stub ).st_mode | stat.S_IEXEC )
    env = os.environ.copy()
    env[ "PYTEST_CMD" ]       = f"bash {stub}"
    env[ "STUB_RENDER_EXIT" ] = str( render_exit )
    env[ "STUB_LIVE_EXIT" ]   = str( live_exit )
    try:
        proc = subprocess.run(
            [ "bash", str( SCRIPT ) ],
            capture_output=True, text=True, env=env, timeout=120
        )
        return proc.stdout, proc.returncode
    finally:
        os.unlink( stub )


class TestTierClassification( unittest.TestCase ):
    """
    Ensures:
        - both tiers pass → Passed:2, script exit 0
        - both tiers exit 1 → Failed:2, script exit 1
        - a pre-collection rejection (exit 4) → NOT EXECUTED, exit 1, code named
        - an unmapped code (exit 3) → NOT EXECUTED (never green), code named
        - mixed genuine-fail + not-executed are bucketed separately
    """

    def test_all_pass_is_green( self ):
        """Ensures: exit 0 on every tier → Passed:2 / Not executed:0 / script exit 0."""
        out, rc = _run( 0, 0 )
        self.assertIn( "Passed: 2", out )
        self.assertIn( "Not executed: 0", out )
        self.assertEqual( rc, 0 )

    def test_genuine_failure_reads_failed( self ):
        """Ensures: exit 1 → FAILED (not NOT EXECUTED); script exit 1."""
        out, rc = _run( 1, 1 )
        self.assertIn( "Failed: 2", out )
        self.assertIn( "Not executed: 0", out )
        self.assertIn( "✗ FAIL", out )
        self.assertEqual( rc, 1 )

    def test_pre_collection_rejection_is_not_executed( self ):
        """Ensures: exit 4 (unrecognized-arg) → NOT EXECUTED, code named, exit 1."""
        out, rc = _run( 4, 4 )
        self.assertIn( "Not executed: 2", out )
        self.assertIn( "Failed: 0", out )
        self.assertIn( "⊘ NOT EXECUTED", out )
        self.assertIn( "exit code 4", out )
        self.assertEqual( rc, 1 )

    def test_unmapped_code_never_green( self ):
        """Ensures: exit 3 (internal error, unmapped) → NOT EXECUTED, code named,
        never PASSED."""
        out, rc = _run( 3, 3 )
        self.assertIn( "Not executed: 2", out )
        self.assertIn( "exit code 3", out )
        self.assertNotIn( "Passed: 2", out )
        self.assertEqual( rc, 1 )

    def test_mixed_fail_and_not_executed_bucketed_separately( self ):
        """Ensures: one genuine fail (exit 1) + one not-run (exit 4) → Failed:1,
        Not executed:1 — the real bug shape, no longer both 'failed'."""
        out, rc = _run( 1, 4 )
        self.assertIn( "Failed: 1", out )
        self.assertIn( "Not executed: 1", out )
        self.assertEqual( rc, 1 )


def quick_smoke_test():
    """Run this module's tests with a banner + pass/fail summary."""
    print( "=" * 72 )
    print( "  Presentation Regression Tier-Classification Control-Proof" )
    print( "=" * 72 )
    start  = time.time()
    suite  = unittest.TestLoader().loadTestsFromTestCase( TestTierClassification )
    result = unittest.TextTestRunner( verbosity=2 ).run( suite )
    elapsed = time.time() - start
    if result.wasSuccessful():
        print( f"\n✓ All {result.testsRun} tests passed in {elapsed:.3f}s" )
    else:
        print( f"\n✗ {len( result.failures )} failures, {len( result.errors )} errors "
               f"out of {result.testsRun} tests" )
    return result.wasSuccessful()


if __name__ == "__main__":
    quick_smoke_test()
