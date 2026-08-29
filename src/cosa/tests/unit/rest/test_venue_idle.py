"""
Unit tests for cosa.rest.venue_idle — the honest venue-idle check (row e6b8fe56).

Drives the module to 100% lines + branches with ZERO network: every HTTP read goes
through the `opener` seam, so the transport, the old-container arm and the malformed
-payload arm are all exercised deterministically.

WHAT THIS FILE IS GUARDING
    The check it replaces answered idle from `monopolize_id` being null. Measured
    2026-08-25, that field moves for exactly one condition — a monopolize-flagged job
    that has already STARTED — so queued work, inline consumer-thread work and ordinary
    shared-pool work all read as idle. The tests below pin the two properties that make
    the replacement worth having:

      1. every occupied lane, on its own, produces BUSY  (the RED direction)
      2. a signal that could not be read produces UNKNOWN, never IDLE

    Property 2 is the one most likely to be "simplified" away by a later reader who
    finds UNKNOWN inconvenient. It is not a nicety: answering IDLE while missing an
    input is the original defect, one level up.
"""

import contextlib
import io
import json
import unittest
from unittest.mock import patch

import cosa.rest.venue_idle as vi


class _FakeResponse:
    """Minimal context-manager stand-in for what urlopen returns."""

    def __init__( self, body ):
        self._body = body if isinstance( body, bytes ) else body.encode()

    def read( self ):
        return self._body

    def __enter__( self ):
        return self

    def __exit__( self, *exc ):
        return False


def _opener_returning( payload ):
    """Build an opener seam that answers with `payload` (dict -> JSON, or raw text)."""
    body = json.dumps( payload ) if isinstance( payload, dict ) else payload

    def _open( url, timeout=None ):
        _open.calls.append( ( url, timeout ) )
        return _FakeResponse( body )

    _open.calls = []
    return _open


def _opener_raising( exc ):
    """Build an opener seam that fails the way an unreachable venue does."""
    def _open( url, timeout=None ):
        raise exc
    return _open


FULL_IDLE = {
    "run_queue_size"        : 0,
    "todo_queue_size"       : 0,
    "inflight_agentic_jobs" : 0,
    "monopolize_inflight"   : False,
    "monopolize_id"         : None,
}


def _payload( **overrides ):
    p = dict( FULL_IDLE )
    p.update( overrides )
    return p


# -- decide(): the pure verdict ----------------------------------------------
class TestDecide( unittest.TestCase ):

    def test_all_lanes_empty_is_idle( self ):
        verdict, reasons = vi.decide( dict( FULL_IDLE ) )
        self.assertEqual( verdict, vi.IDLE )
        self.assertTrue( reasons )
        self.assertIn( "every lane reported empty", reasons[ 0 ] )

    def test_queued_work_alone_is_busy( self ):
        # THE ROW. Nothing running anywhere; work is merely WAITING. The old check
        # called this idle because no pool field moves for a queued job.
        verdict, reasons = vi.decide( _payload( todo_queue_size=2 ) )
        self.assertEqual( verdict, vi.BUSY )
        self.assertEqual( reasons, [ "todo_queue_size=2" ] )

    def test_inline_consumer_work_alone_is_busy( self ):
        # Row 99b09840's reading: a job running inline on the consumer thread sits in
        # the run FIFO and moves no pool field either.
        verdict, reasons = vi.decide( _payload( run_queue_size=1 ) )
        self.assertEqual( verdict, vi.BUSY )
        self.assertEqual( reasons, [ "run_queue_size=1" ] )

    def test_shared_pool_work_alone_is_busy( self ):
        verdict, reasons = vi.decide( _payload( inflight_agentic_jobs=1 ) )
        self.assertEqual( verdict, vi.BUSY )
        self.assertEqual( reasons, [ "inflight_agentic_jobs=1" ] )

    def test_monopolizer_is_busy_and_names_the_holder( self ):
        verdict, reasons = vi.decide(
            _payload( monopolize_inflight=True, monopolize_id="ts-827a54cd" )
        )
        self.assertEqual( verdict, vi.BUSY )
        self.assertIn( "monopolize_inflight=True", reasons[ 0 ] )
        self.assertIn( "ts-827a54cd", reasons[ 0 ] )

    def test_every_occupied_lane_is_reported_not_just_the_first( self ):
        verdict, reasons = vi.decide( _payload(
            run_queue_size=1, todo_queue_size=2, inflight_agentic_jobs=3,
            monopolize_inflight=True, monopolize_id="m",
        ) )
        self.assertEqual( verdict, vi.BUSY )
        self.assertEqual( len( reasons ), 4 )

    def test_missing_count_signal_is_unknown_not_idle( self ):
        # The old-container arm: everything else clean, todo depth absent.
        verdict, reasons = vi.decide( _payload( todo_queue_size=None ) )
        self.assertEqual( verdict, vi.UNKNOWN )
        self.assertEqual( reasons, [ "todo_queue_size could not be read" ] )

    def test_missing_flag_signal_is_unknown_not_idle( self ):
        verdict, reasons = vi.decide( _payload( monopolize_inflight=None ) )
        self.assertEqual( verdict, vi.UNKNOWN )
        self.assertEqual( reasons, [ "monopolize_inflight could not be read" ] )

    def test_absent_key_counts_as_unreadable( self ):
        # A key that is missing outright, not merely None — decide() must not assume
        # a default of zero for a signal nobody reported.
        verdict, reasons = vi.decide( { "run_queue_size": 0 } )
        self.assertEqual( verdict, vi.UNKNOWN )
        self.assertEqual( len( reasons ), 3 )

    def test_busy_beats_unknown( self ):
        # Proven occupancy is already a decision; ambiguity adds nothing for a caller
        # who now knows to stay off the venue.
        verdict, reasons = vi.decide( _payload( run_queue_size=1, todo_queue_size=None ) )
        self.assertEqual( verdict, vi.BUSY )
        self.assertEqual( reasons, [ "run_queue_size=1" ] )

    def test_empty_signal_bag_is_unknown( self ):
        verdict, reasons = vi.decide( {} )
        self.assertEqual( verdict, vi.UNKNOWN )
        self.assertEqual( len( reasons ), len( vi.REQUIRED_SIGNALS ) )


# -- read_signals(): the HTTP read -------------------------------------------
class TestReadSignals( unittest.TestCase ):

    def test_reads_every_field_and_coerces_types( self ):
        opener = _opener_returning( _payload(
            run_queue_size=1, todo_queue_size=2, inflight_agentic_jobs=3,
            monopolize_inflight=1, monopolize_id="m-1",
        ) )
        s = vi.read_signals( port=8000, opener=opener )
        self.assertEqual( s[ "run_queue_size" ], 1 )
        self.assertEqual( s[ "todo_queue_size" ], 2 )
        self.assertEqual( s[ "inflight_agentic_jobs" ], 3 )
        self.assertIs( s[ "monopolize_inflight" ], True )      # coerced int -> bool
        self.assertEqual( s[ "monopolize_id" ], "m-1" )
        self.assertIsNone( s[ "error" ] )

    def test_hits_the_unfiltered_unauthenticated_door( self ):
        opener = _opener_returning( _payload() )
        vi.read_signals( port=1234, opener=opener )
        self.assertEqual( opener.calls[ 0 ][ 0 ], "http://localhost:1234/api/busy" )

    def test_timeout_is_passed_through( self ):
        opener = _opener_returning( _payload() )
        vi.read_signals( port=8000, timeout=42, opener=opener )
        self.assertEqual( opener.calls[ 0 ][ 1 ], 42 )

    def test_old_container_leaves_absent_fields_as_none( self ):
        # A container predating this row answers with only the original two ints.
        opener = _opener_returning( { "inflight_agentic_jobs": 0, "run_queue_size": 0 } )
        s = vi.read_signals( port=8000, opener=opener )
        self.assertEqual( s[ "run_queue_size" ], 0 )
        self.assertEqual( s[ "inflight_agentic_jobs" ], 0 )
        self.assertIsNone( s[ "todo_queue_size" ] )
        self.assertIsNone( s[ "monopolize_inflight" ] )

    def test_unreachable_venue_yields_all_none_and_an_error_string( self ):
        s = vi.read_signals( port=8000, opener=_opener_raising( OSError( "refused" ) ) )
        for name in vi.REQUIRED_SIGNALS:
            self.assertIsNone( s[ name ] )
        self.assertIn( "OSError", s[ "error" ] )

    def test_garbage_body_is_an_unreadable_venue_not_a_crash( self ):
        s = vi.read_signals( port=8000, opener=_opener_returning( "<html>502</html>" ) )
        self.assertIsNone( s[ "todo_queue_size" ] )
        self.assertIn( "JSONDecodeError", s[ "error" ] )

    def test_default_opener_is_the_real_transport( self ):
        # The seam defaults to urllib.request.urlopen; proven by pointing it at a port
        # nothing listens on and taking the honest failure rather than an exception.
        s = vi.read_signals( port=1, timeout=1 )
        self.assertIsNotNone( s[ "error" ] )


# -- format_report(): what a human reads before acting on the venue ----------
class TestFormatReport( unittest.TestCase ):

    def test_idle_report_names_port_verdict_and_signals( self ):
        signals = dict( FULL_IDLE, error=None )
        text = vi.format_report( 8000, signals, vi.IDLE, [ "all clear" ] )
        self.assertIn( ":8000 -- IDLE", text )
        self.assertIn( "all clear", text )
        self.assertIn( "todo_queue_size=0", text )
        self.assertNotIn( "UNKNOWN IS NOT IDLE", text )

    def test_busy_report_does_not_carry_the_unknown_warning( self ):
        signals = dict( FULL_IDLE, run_queue_size=1, error=None )
        text = vi.format_report( 8000, signals, vi.BUSY, [ "run_queue_size=1" ] )
        self.assertIn( "BUSY", text )
        self.assertNotIn( "UNKNOWN IS NOT IDLE", text )

    def test_unknown_report_is_loud( self ):
        signals = dict( FULL_IDLE, monopolize_inflight=None, todo_queue_size=None, error=None )
        text = vi.format_report( 8000, signals, vi.UNKNOWN, [ "two missing" ] )
        self.assertIn( "UNKNOWN IS NOT IDLE", text )
        self.assertIn( "do not recreate, do not submit", text )
        # Two signals missing -> the cause is NOT specifically a pre-fix container.
        self.assertNotIn( "predates row e6b8fe56", text )

    def test_unknown_names_the_pre_fix_container_and_says_bounce( self ):
        # When the todo depth is the ONLY thing missing, the cause is knowable and the
        # remedy is a BOUNCE — a code pickup, not a --force-recreate.
        signals = dict( FULL_IDLE, todo_queue_size=None, error=None )
        text = vi.format_report( 8000, signals, vi.UNKNOWN, [ "todo missing" ] )
        self.assertIn( "predates row e6b8fe56", text )
        self.assertIn( "BOUNCE", text )
        self.assertIn( "Do not read this as idle", text )

    def test_read_failure_is_quoted_in_the_report( self ):
        signals = { n: None for n in vi.REQUIRED_SIGNALS }
        signals[ "error" ] = "URLError: refused"
        text = vi.format_report( 8000, signals, vi.UNKNOWN, [ "unreachable" ] )
        self.assertIn( "read failed: URLError: refused", text )


# -- check() + main(): the caller-facing surface ------------------------------
class TestCheckAndMain( unittest.TestCase ):

    def test_check_returns_verdict_report_and_signals( self ):
        verdict, report, signals = vi.check( port=8000, opener=_opener_returning( _payload() ) )
        self.assertEqual( verdict, vi.IDLE )
        self.assertIn( "IDLE", report )
        self.assertEqual( signals[ "todo_queue_size" ], 0 )

    def test_check_reports_busy_on_queued_work( self ):
        verdict, _, _ = vi.check(
            port=8000, opener=_opener_returning( _payload( todo_queue_size=1 ) )
        )
        self.assertEqual( verdict, vi.BUSY )

    def _main_against( self, argv, payload ):
        """Drive main() end to end with only the transport stubbed."""
        opener = _opener_returning( payload )
        buf    = io.StringIO()
        with patch( "urllib.request.urlopen", opener ):
            with contextlib.redirect_stdout( buf ):
                code = vi.main( argv )
        return code, buf.getvalue()

    def test_main_exit_codes_are_the_branch_a_caller_reads( self ):
        for payload, want_code, want_word in (
            ( _payload(),                    vi.EXIT_IDLE,    vi.IDLE ),
            ( _payload( todo_queue_size=1 ), vi.EXIT_BUSY,    vi.BUSY ),
            ( { "run_queue_size": 0 },       vi.EXIT_UNKNOWN, vi.UNKNOWN ),
        ):
            with self.subTest( want=want_word ):
                code, out = self._main_against( [ "--port", "8000" ], payload )
                self.assertEqual( code, want_code )
                self.assertIn( want_word, out )

    def test_main_defaults_to_port_8000( self ):
        _, out = self._main_against( [], _payload() )
        self.assertIn( ":8000", out )

    def test_main_honours_an_explicit_port( self ):
        _, out = self._main_against( [ "--port", "1234" ], _payload() )
        self.assertIn( ":1234", out )

    def test_unrecognised_argument_never_costs_a_reading( self ):
        # A typo'd flag, and a trailing --port with no value, must not be the reason a
        # gate step produces no verdict at all.
        code, out = self._main_against( [ "--nonsense", "--port", "1234", "--port" ], _payload() )
        self.assertEqual( code, vi.EXIT_IDLE )
        self.assertIn( ":1234", out )

    def test_main_reads_sys_argv_when_argv_is_none( self ):
        opener = _opener_returning( _payload() )
        buf    = io.StringIO()
        with patch( "sys.argv", [ "venue_idle", "--port", "4321" ] ):
            with patch( "urllib.request.urlopen", opener ):
                with contextlib.redirect_stdout( buf ):
                    code = vi.main( None )
        self.assertEqual( code, vi.EXIT_IDLE )
        self.assertIn( ":4321", buf.getvalue() )


if __name__ == "__main__":
    unittest.main()
