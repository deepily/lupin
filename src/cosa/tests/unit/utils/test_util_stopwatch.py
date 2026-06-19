"""
Unit tests for cosa.utils.util_stopwatch.Stopwatch.

Pure timing utility. Tests assert on real captured stdout (not just that the
calls execute) so a formatting regression — e.g. the mm:ss elapsed format —
fails loudly. start_time is backdated to exercise the >59-second branch
deterministically.

Assertions strengthened from the module's __main__ demo block (now superseded).
"""

import datetime as dt
import io
import unittest
from contextlib import redirect_stdout

from cosa.utils.util_stopwatch import Stopwatch


def _capture( fn, *args, **kwargs ):
    """Run fn and return everything it printed to stdout."""
    buf = io.StringIO()
    with redirect_stdout( buf ):
        fn( *args, **kwargs )
    return buf.getvalue()


class TestStopwatch( unittest.TestCase ):
    """Timing, context-manager, and formatting behaviour of Stopwatch."""

    def test_init_prints_message_when_not_silent( self ):
        out = _capture( Stopwatch, msg="starting", silent=False )
        self.assertIn( "starting", out )

    def test_init_silent_suppresses( self ):
        out = _capture( Stopwatch, msg="quiet", silent=True )
        self.assertEqual( out, "" )

    def test_context_manager_times_block( self ):
        with Stopwatch( silent=True ) as sw:
            pass
        self.assertIsInstance( sw.interval, int )
        self.assertGreaterEqual( sw.interval, 0 )

    def test_context_manager_prints_done_when_not_silent( self ):
        buf = io.StringIO()
        with redirect_stdout( buf ):
            with Stopwatch( silent=False ):
                pass
        self.assertIn( "Done in", buf.getvalue() )
        self.assertIn( "ms", buf.getvalue() )

    def test_get_delta_ms( self ):
        sw = Stopwatch( silent=True )
        delta = sw.get_delta_ms()
        self.assertIsInstance( delta, int )
        self.assertEqual( sw.delta_ms, delta )

    def test_print_default_message( self ):
        sw = Stopwatch( silent=False )
        self.assertIn( "Finished in", _capture( sw.print ) )      # msg None + init None

    def test_print_uses_init_msg( self ):
        sw = Stopwatch( silent=False )
        sw.init_msg = "job"                                       # init set, msg None
        out = _capture( sw.print )
        self.assertIn( "job in", out )

    def test_print_combines_init_and_msg( self ):
        sw = Stopwatch( silent=False )
        sw.init_msg = "job"
        out = _capture( sw.print, "phase 2", prepend_nl=True )
        self.assertIn( "job phase 2 in", out )

    def test_print_use_millis( self ):
        sw = Stopwatch( silent=False )
        out = _capture( sw.print, use_millis=True )
        self.assertIn( "ms", out )

    def test_print_minutes_seconds_branch( self ):
        sw = Stopwatch( silent=False )
        # Backdate start_time so 61 seconds have "elapsed" -> mm:ss branch.
        sw.start_time = dt.datetime.now() - dt.timedelta( seconds=61 )
        out = _capture( sw.print, "long task" )
        self.assertIn( "long task in 01:01", out )               # 61s -> 01:01

    def test_print_silent_suppresses_output( self ):
        sw = Stopwatch( silent=True )
        sw.start_time = dt.datetime.now() - dt.timedelta( seconds=61 )
        self.assertEqual( _capture( sw.print, "long task", prepend_nl=True, use_millis=True ), "" )


if __name__ == "__main__":
    unittest.main()
