#!/usr/bin/env python3
"""
Row 08919110 — bounce_busy_probe.py, the helper that turns GET /api/busy into the exit
code bounce-dev-server.sh reads (0 idle / 10 busy / 20 unreachable).

Two things must not silently break:
  · the OR TRIGGER — EITHER count > 0 is a live job, so the runq-only and inflight-only
    cases must BOTH read busy (a trigger that only watched one field would pass a probe
    that watched the wrong one);
  · FAIL-OPEN honesty — a network error, a non-200, bad JSON, or a missing field must all
    return UNREACHABLE, never a guessed idle, because guessing idle would let the script
    bounce straight through a live job.
Both are asserted with the network stubbed, so the checks are deterministic and red-capable.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

import cosa.utils.util as cu

sys.path.insert( 0, cu.get_project_root() + "/src/scripts" )
import bounce_busy_probe as bp


def _cm( body_bytes ):
    """A stand-in for urlopen()'s context manager: `with urlopen(...) as r: r.read()`."""
    resp = MagicMock()
    resp.read.return_value = body_bytes
    ctx = MagicMock()
    ctx.__enter__.return_value = resp
    ctx.__exit__.return_value  = False
    return ctx


def _probe_returning( body_bytes ):
    with patch( "bounce_busy_probe.urllib.request.urlopen", MagicMock( return_value=_cm( body_bytes ) ) ):
        return bp.probe( "http://stub/api/busy" )


def _probe_raising( exc ):
    with patch( "bounce_busy_probe.urllib.request.urlopen", MagicMock( side_effect=exc ) ):
        return bp.probe( "http://stub/api/busy" )


class TestClassifyOrTrigger( unittest.TestCase ):

    def test_both_zero_is_idle( self ):
        self.assertEqual( bp.classify( 0, 0 ), bp.EXIT_IDLE )

    def test_inflight_only_is_busy( self ):
        self.assertEqual( bp.classify( 1, 0 ), bp.EXIT_BUSY )

    def test_run_queue_only_is_busy( self ):
        # The half of the OR that a one-field guard would miss.
        self.assertEqual( bp.classify( 0, 1 ), bp.EXIT_BUSY )

    def test_both_positive_is_busy( self ):
        self.assertEqual( bp.classify( 2, 3 ), bp.EXIT_BUSY )


class TestProbeExitCodes( unittest.TestCase ):

    def test_idle_json_returns_idle( self ):
        self.assertEqual(
            _probe_returning( b'{"inflight_agentic_jobs": 0, "run_queue_size": 0}' ),
            bp.EXIT_IDLE )

    def test_inflight_only_returns_busy( self ):
        self.assertEqual(
            _probe_returning( b'{"inflight_agentic_jobs": 1, "run_queue_size": 0}' ),
            bp.EXIT_BUSY )

    def test_run_queue_only_returns_busy( self ):
        self.assertEqual(
            _probe_returning( b'{"inflight_agentic_jobs": 0, "run_queue_size": 2}' ),
            bp.EXIT_BUSY )

    def test_connection_error_fails_open( self ):
        import urllib.error
        self.assertEqual( _probe_raising( urllib.error.URLError( "refused" ) ), bp.EXIT_UNREACHABLE )

    def test_malformed_json_fails_open( self ):
        self.assertEqual( _probe_returning( b'not json at all' ), bp.EXIT_UNREACHABLE )

    def test_missing_field_fails_open( self ):
        # A 200 with the wrong shape is UNREACHABLE, not idle — never guess idle.
        self.assertEqual( _probe_returning( b'{"inflight_agentic_jobs": 1}' ), bp.EXIT_UNREACHABLE )


class TestExitCodeWireContract( unittest.TestCase ):
    """
    The bounce script reads these exit codes as LITERALS (case 0 / 10 / *). Every other
    assertion in this file compares against the SYMBOLS (bp.EXIT_*), which move WITH the
    code — so if a constant's value drifts, those stay green (Maria's mutation 2:
    EXIT_UNREACHABLE 20->10 passed a 15-green suite while making an unreachable probe
    report BUSY, i.e. fail CLOSED). These pin the wire NUMBERS so that drift reddens.
    """

    def test_the_three_exit_codes_are_their_wire_literals( self ):
        self.assertEqual( bp.EXIT_IDLE, 0 )
        self.assertEqual( bp.EXIT_BUSY, 10 )
        self.assertEqual( bp.EXIT_UNREACHABLE, 20 )

    def test_unreachable_returns_literal_20_not_the_refuse_code_10( self ):
        # The hazard end-to-end: if unreachable returned 10, the script's case would REFUSE
        # (fail closed) instead of failing open. Assert the LITERAL, and assert it is NOT 10.
        import urllib.error
        rc = _probe_raising( urllib.error.URLError( "refused" ) )
        self.assertEqual( rc, 20 )
        self.assertNotEqual( rc, 10 )   # never the refuse code

    def test_idle_and_busy_return_their_wire_literals( self ):
        self.assertEqual( _probe_returning( b'{"inflight_agentic_jobs": 0, "run_queue_size": 0}' ), 0 )
        self.assertEqual( _probe_returning( b'{"inflight_agentic_jobs": 1, "run_queue_size": 0}' ), 10 )


if __name__ == "__main__":
    unittest.main()
