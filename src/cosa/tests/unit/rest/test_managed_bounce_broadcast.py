"""
Unit tests for `cosa.rest.managed_bounce_broadcast` (managed-bounce R4/R5).

Design of record: src/rnd/v0.1.9/2026.08.01-managed-bounce-review-tiffany.md +
2026.08.01-managed-bounce-for-7999.md Rev 2.

Covers the full pure/injectable surface to 100% (lines + branches):
  · build_bounce_message         — warning, all-clear (self-distinguishing), unknown kind
  · next_boot_id                 — increment, missing/garbage/negative file, write failure
  · emit_bounce_broadcast_in_process — happy, 429 loud log, >=400 log, no-status, exception
  · count_acked_sessions         — distinct-session dedupe, wrong id/status/type filters
  · poll_acks_until_satisfied    — immediate, zero-expected, after-polls, deadline expiry
  · wait_for_recipients          — ready immediately, after polls, deadline-with-zero (the
                                    emitted!=heard guard: fire-to-zero is NOT a satisfied fire)

Zero external dependencies: clock, sleep, session/entry readers, and the
broadcast executor are all injected or boundary-mocked. No real network, DB, or
timing; the filesystem is touched only via tempfiles for the boot counter.
"""

import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest.mock import MagicMock

from cosa.rest.managed_bounce_broadcast import (
    build_bounce_message,
    next_boot_id,
    emit_bounce_broadcast_in_process,
    count_acked_sessions,
    poll_acks_until_satisfied,
    wait_for_recipients,
    all_clear_fire_reason,
    resolve_ack_timing,
    FLEET_BROADCAST_USER_ID,
)


class _FakeClock:
    """Returns each supplied time in turn, then repeats the last one forever."""
    def __init__( self, times ):
        self.times = list( times )
        self.i     = 0
    def __call__( self ):
        v = self.times[ self.i ]
        if self.i < len( self.times ) - 1:
            self.i += 1
        return v


def _ack( broadcast_id, sender_session_id, status="completed" ):
    return { "sender_session_id": sender_session_id, "metadata": { "broadcast_id": broadcast_id, "status": status } }


# ─── build_bounce_message ───────────────────────────────────────────────────


class BuildBounceMessageTests( unittest.TestCase ):

    def test_warning_message_names_the_server_and_the_hold( self ):
        msg = build_bounce_message( "warning" )
        self.assertIn( ":7999", msg )
        self.assertIn( "hold notifications", msg )
        self.assertNotIn( "<system-reminder>", msg.lower() )

    def test_all_clear_is_self_distinguishing_by_boot_id( self ):
        a = build_bounce_message( "all-clear", boot_id=41, boot_started="2026-08-01T12:00:00", uptime_seconds=3.2 )
        b = build_bounce_message( "all-clear", boot_id=42, boot_started="2026-08-01T12:00:20", uptime_seconds=3.4 )
        self.assertIn( "boot #41", a )
        self.assertIn( "boot #42", b )
        self.assertIn( "up 3.2s", a )
        self.assertNotEqual( a, b )     # a crash-loop reads as N distinct lines, not one

    def test_all_clear_tolerates_unknown_uptime( self ):
        msg = build_bounce_message( "all-clear", boot_id=1, boot_started="t", uptime_seconds=None )
        self.assertIn( "up ?s", msg )

    def test_unknown_kind_raises( self ):
        with self.assertRaises( ValueError ):
            build_bounce_message( "shutdown-ish" )


# ─── next_boot_id ───────────────────────────────────────────────────────────


class NextBootIdTests( unittest.TestCase ):

    def test_increments_existing_counter_and_persists( self ):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join( d, "sub", "boot-counter.txt" )
            os.makedirs( os.path.dirname( path ) )
            with open( path, "w" ) as f:
                f.write( "40" )
            self.assertEqual( next_boot_id( path ), 41 )
            with open( path ) as f:
                self.assertEqual( f.read().strip(), "41" )

    def test_missing_file_starts_at_one_and_creates_parent( self ):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join( d, "made", "here", "boot-counter.txt" )
            self.assertEqual( next_boot_id( path ), 1 )
            self.assertTrue( os.path.exists( path ) )

    def test_garbage_content_restarts_at_one( self ):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join( d, "boot-counter.txt" )
            with open( path, "w" ) as f:
                f.write( "not-a-number" )
            self.assertEqual( next_boot_id( path ), 1 )

    def test_negative_stored_value_restarts_at_one( self ):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join( d, "boot-counter.txt" )
            with open( path, "w" ) as f:
                f.write( "-5" )
            self.assertEqual( next_boot_id( path ), 1 )

    def test_write_failure_is_swallowed_and_value_still_advances( self ):
        # Point the counter at a DIRECTORY: read raises IsADirectoryError (OSError,
        # caught → current 0), and write_text on a dir raises too (caught → warn).
        with tempfile.TemporaryDirectory() as d:
            buf = io.StringIO()
            with redirect_stderr( buf ):
                result = next_boot_id( d )     # d is the dir itself
            self.assertEqual( result, 1 )
            self.assertIn( "could not persist boot counter", buf.getvalue() )


# ─── emit_bounce_broadcast_in_process ───────────────────────────────────────


class EmitBounceBroadcastTests( unittest.TestCase ):

    def _kwargs( self, execute_fn ):
        return dict(
            kind                             = "all-clear",
            message                          = "hi",
            user_id                          = FLEET_BROADCAST_USER_ID,
            store                            = MagicMock(),
            rate_limiter                     = MagicMock(),
            ack_watcher                      = MagicMock(),
            notification_queue               = MagicMock(),
            active_session_threshold_seconds = 28800.0,
            raw_sessions_fn                  = lambda: [],
            bridge_loader                    = lambda p: None,
            build_sender_id                  = lambda s: "sid",
            execute_broadcast_fn             = execute_fn,
            broadcast_request_cls            = lambda **kw: kw,
        )

    def test_happy_path_returns_result_and_passes_wiring( self ):
        execute = MagicMock( return_value={ "http_status": 200, "recipients": 3 } )
        result  = emit_bounce_broadcast_in_process( **self._kwargs( execute ) )
        self.assertEqual( result[ "recipients" ], 3 )
        # body was built via the injected request class and forwarded
        _, kwargs = execute.call_args
        self.assertEqual( kwargs[ "authenticated_user_id" ], FLEET_BROADCAST_USER_ID )
        self.assertEqual( kwargs[ "body" ][ "message" ], "hi" )

    def test_rate_limit_429_writes_a_loud_line( self ):
        execute = MagicMock( return_value={ "http_status": 429, "retry_after": 5 } )
        buf = io.StringIO()
        with redirect_stderr( buf ):
            result = emit_bounce_broadcast_in_process( **self._kwargs( execute ) )
        self.assertEqual( result[ "http_status" ], 429 )
        self.assertIn( "SUPPRESSED by the rate limiter", buf.getvalue() )
        self.assertIn( "Silence is not proof", buf.getvalue() )

    def test_other_error_status_writes_a_loud_line( self ):
        execute = MagicMock( return_value={ "http_status": 400, "detail": "bad" } )
        buf = io.StringIO()
        with redirect_stderr( buf ):
            emit_bounce_broadcast_in_process( **self._kwargs( execute ) )
        self.assertIn( "returned 400", buf.getvalue() )

    def test_missing_http_status_is_not_treated_as_error( self ):
        execute = MagicMock( return_value={ "recipients": 1 } )     # no http_status key
        buf = io.StringIO()
        with redirect_stderr( buf ):
            result = emit_bounce_broadcast_in_process( **self._kwargs( execute ) )
        self.assertEqual( result[ "recipients" ], 1 )
        self.assertEqual( buf.getvalue(), "" )

    def test_exception_degrades_to_error_dict_and_never_raises( self ):
        def boom( **kw ):
            raise RuntimeError( "kaboom" )
        buf = io.StringIO()
        with redirect_stderr( buf ):
            result = emit_bounce_broadcast_in_process( **self._kwargs( boom ) )
        self.assertEqual( result, { "error": "kaboom" } )
        self.assertIn( "raised, not sent", buf.getvalue() )

    def test_unwired_commons_returns_none_without_calling_executor( self ):
        # The not-wired guard (moved here from main.py so it's measured): if any
        # of store / rate_limiter / ack_watcher is None, skip + log + return None,
        # and never touch the executor.
        for missing in ( "store", "rate_limiter", "ack_watcher" ):
            execute = MagicMock( return_value={ "http_status": 200 } )
            kwargs  = self._kwargs( execute )
            kwargs[ missing ] = None
            buf = io.StringIO()
            with redirect_stderr( buf ):
                result = emit_bounce_broadcast_in_process( **kwargs )
            self.assertIsNone( result, missing )
            self.assertIn( "commons not wired", buf.getvalue() )
            execute.assert_not_called()


class AllClearFireReasonTests( unittest.TestCase ):

    def test_threshold_met_when_ready( self ):
        self.assertEqual( all_clear_fire_reason( True ), "threshold met" )

    def test_deadline_expired_when_not_ready( self ):
        self.assertEqual( all_clear_fire_reason( False ), "deadline expired" )


# ─── count_acked_sessions ───────────────────────────────────────────────────


class CountAckedSessionsTests( unittest.TestCase ):

    def test_dedupes_duplicate_acks_from_the_same_session( self ):
        # The 22f7a215 case: one session acked twice → must count ONCE.
        entries = [
            _ack( "bid", "sessA" ),
            _ack( "bid", "sessA" ),     # duplicate
            _ack( "bid", "sessB" ),
        ]
        self.assertEqual( count_acked_sessions( entries, "bid" ), 2 )

    def test_filters_other_broadcast_status_and_bad_session_type( self ):
        entries = [
            _ack( "bid",   "sessA" ),                    # counts
            _ack( "OTHER", "sessB" ),                    # wrong broadcast
            _ack( "bid",   "sessC", status="skipped" ),  # wrong status
            _ack( "bid",   None ),                       # non-str session
            { "metadata": None },                        # missing session + metadata None branch
        ]
        self.assertEqual( count_acked_sessions( entries, "bid" ), 1 )

    def test_skipped_then_completed_same_session_counts_once( self ):
        entries = [
            _ack( "bid", "sessA", status="skipped" ),
            _ack( "bid", "sessA", status="completed" ),
        ]
        self.assertEqual( count_acked_sessions( entries, "bid", status="completed" ), 1 )


# ─── poll_acks_until_satisfied ──────────────────────────────────────────────


class PollAcksTests( unittest.TestCase ):

    def test_zero_recipients_is_satisfied_immediately_without_sleeping( self ):
        sleep = MagicMock()
        res = poll_acks_until_satisfied(
            read_entries_fn=lambda: [], broadcast_id="bid", expected_recipients=0,
            deadline_seconds=10, poll_interval_seconds=1,
            now_fn=_FakeClock( [ 0, 0 ] ), sleep_fn=sleep,
        )
        self.assertTrue( res[ "satisfied" ] )
        self.assertEqual( res[ "acked" ], 0 )
        sleep.assert_not_called()

    def test_satisfied_after_two_polls( self ):
        # First read: 1 ack; second read: 2 acks → satisfied when count reaches 2.
        reads = [ [ _ack( "bid", "A" ) ], [ _ack( "bid", "A" ), _ack( "bid", "B" ) ] ]
        seq   = iter( reads )
        sleep = MagicMock()
        res = poll_acks_until_satisfied(
            read_entries_fn=lambda: next( seq ), broadcast_id="bid", expected_recipients=2,
            deadline_seconds=10, poll_interval_seconds=0.5,
            now_fn=_FakeClock( [ 0, 1, 2 ] ), sleep_fn=sleep,
        )
        self.assertTrue( res[ "satisfied" ] )
        self.assertEqual( res[ "acked" ], 2 )
        sleep.assert_called_once_with( 0.5 )

    def test_deadline_expiry_reports_partial_reach( self ):
        res = poll_acks_until_satisfied(
            read_entries_fn=lambda: [ _ack( "bid", "A" ) ], broadcast_id="bid", expected_recipients=3,
            deadline_seconds=10, poll_interval_seconds=1,
            now_fn=_FakeClock( [ 0, 1, 100 ] ), sleep_fn=MagicMock(),
        )
        self.assertFalse( res[ "satisfied" ] )
        self.assertEqual( res[ "acked" ], 1 )
        self.assertEqual( res[ "expected" ], 3 )


# ─── wait_for_recipients (the emitted != heard guard) ───────────────────────


class WaitForRecipientsTests( unittest.TestCase ):

    def test_ready_immediately_when_fleet_already_present( self ):
        sleep = MagicMock()
        res = wait_for_recipients(
            count_sessions_fn=lambda: 3, minimum=1, deadline_seconds=10,
            poll_interval_seconds=0.5, now_fn=_FakeClock( [ 0, 0 ] ), sleep_fn=sleep,
        )
        self.assertTrue( res[ "ready" ] )
        self.assertEqual( res[ "count" ], 3 )
        sleep.assert_not_called()

    def test_ready_after_sessions_rejoin( self ):
        counts = iter( [ 0, 2 ] )
        sleep  = MagicMock()
        res = wait_for_recipients(
            count_sessions_fn=lambda: next( counts ), minimum=1, deadline_seconds=10,
            poll_interval_seconds=0.5, now_fn=_FakeClock( [ 0, 1, 2 ] ), sleep_fn=sleep,
        )
        self.assertTrue( res[ "ready" ] )
        self.assertEqual( res[ "count" ], 2 )
        sleep.assert_called_once_with( 0.5 )

    def test_fire_to_zero_is_NOT_ready_at_deadline( self ):
        # Rio's guard: emitted != heard. If nobody ever reconnects, the gate must
        # return ready=False with count 0 — NOT a satisfied fire. Mutation-proof:
        # revert `count >= minimum` and this goes red while the ready tests stay green.
        res = wait_for_recipients(
            count_sessions_fn=lambda: 0, minimum=1, deadline_seconds=10,
            poll_interval_seconds=1, now_fn=_FakeClock( [ 0, 1, 100 ] ), sleep_fn=MagicMock(),
        )
        self.assertFalse( res[ "ready" ] )
        self.assertEqual( res[ "count" ], 0 )


class ResolveAckTimingTests( unittest.TestCase ):

    def test_reads_both_keys_from_config( self ):
        cfg = MagicMock()
        cfg.get.side_effect = lambda key, default=None, return_type=None: {
            "managed bounce warning ack deadline seconds":      12.0,
            "managed bounce warning ack poll interval seconds": 0.5,
        }[ key ]
        deadline, poll = resolve_ack_timing( cfg, default_deadline=8.0, default_poll=0.25 )
        self.assertEqual( ( deadline, poll ), ( 12.0, 0.5 ) )

    def test_forwards_defaults_for_absent_keys( self ):
        # A config that echoes the caller's default (key absent) → defaults win.
        cfg = MagicMock()
        cfg.get.side_effect = lambda key, default=None, return_type=None: default
        self.assertEqual(
            resolve_ack_timing( cfg, default_deadline=8.0, default_poll=0.25 ),
            ( 8.0, 0.25 ),
        )


if __name__ == "__main__":
    unittest.main()
