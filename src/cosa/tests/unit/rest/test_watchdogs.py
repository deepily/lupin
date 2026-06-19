"""
Unit tests for the unified watchdog facade (cosa.rest.watchdogs).

Covers init_watchdogs: both-succeed (ENABLED/ENABLED), both-raise
(failure prints + DISABLED/DISABLED), and present-but-disabled
(is-not-None-true × enabled-false arc) — to genuine 100% line + branch + function.

The two underlying init_watchdog factories are boundary-mocked. ZERO real
watchdog construction, ZERO threads.
"""

import unittest
from unittest.mock import Mock, patch

from cosa.rest import watchdogs


class TestInitWatchdogs( unittest.TestCase ):
    def test_both_enabled( self ):
        bfe = Mock( enabled=True )
        tfe = Mock( enabled=True )
        with patch.object( watchdogs, "init_bfe_watchdog", return_value=bfe ) as mbfe, \
             patch.object( watchdogs, "init_tfe_watchdog", return_value=tfe ) as mtfe, \
             patch( "builtins.print" ) as mp:
            out_bfe, out_tfe = watchdogs.init_watchdogs( "cfg", "todoq", debug=True, verbose=True )
        self.assertIs( out_bfe, bfe )
        self.assertIs( out_tfe, tfe )
        mbfe.assert_called_once()
        mtfe.assert_called_once()
        self.assertTrue( any( "BFE=ENABLED, TFE=ENABLED" in str( c ) for c in mp.call_args_list ) )

    def test_both_fail_returns_none_and_logs( self ):
        with patch.object( watchdogs, "init_bfe_watchdog", side_effect=Exception( "bfe boom" ) ), \
             patch.object( watchdogs, "init_tfe_watchdog", side_effect=Exception( "tfe boom" ) ), \
             patch( "builtins.print" ) as mp:
            out_bfe, out_tfe = watchdogs.init_watchdogs( "cfg", "todoq" )
        self.assertIsNone( out_bfe )
        self.assertIsNone( out_tfe )
        logged = " ".join( str( c ) for c in mp.call_args_list )
        self.assertIn( "BFE init FAILED", logged )
        self.assertIn( "TFE init FAILED", logged )
        self.assertIn( "BFE=DISABLED, TFE=DISABLED", logged )

    def test_present_but_disabled( self ):
        bfe = Mock( enabled=False )   # constructed but not enabled → DISABLED via enabled-false arc
        tfe = Mock( enabled=True )
        with patch.object( watchdogs, "init_bfe_watchdog", return_value=bfe ), \
             patch.object( watchdogs, "init_tfe_watchdog", return_value=tfe ), \
             patch( "builtins.print" ) as mp:
            watchdogs.init_watchdogs( "cfg", "todoq" )
        self.assertTrue( any( "BFE=DISABLED, TFE=ENABLED" in str( c ) for c in mp.call_args_list ) )


def isolated_unit_test():
    """
    Run the watchdogs facade unit tests in isolation.

    Ensures:
        - Returns (success, duration, message) for the smoke-runner harness
    """
    import time
    start_time = time.time()
    suite = unittest.TestLoader().loadTestsFromModule( __import__( __name__ ) )
    result = unittest.TextTestRunner( verbosity=2 ).run( suite )
    duration = time.time() - start_time
    success = result.wasSuccessful()
    message = f"{result.testsRun} run, {len( result.failures )} failed, {len( result.errors )} errors"
    return success, duration, message


if __name__ == "__main__":
    ok, secs, msg = isolated_unit_test()
    print( f"\n{'✅ PASS' if ok else '❌ FAIL'} watchdogs tests in {secs:.3f}s — {msg}" )
