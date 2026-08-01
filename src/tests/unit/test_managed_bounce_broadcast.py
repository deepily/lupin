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
  · wait_for_reconnection_plateau — plateau after N equal reads, single-read does NOT fire
                                    (the emitted!=heard guard), climb→deadline, plateau-at-zero
  · missed_sessions              — roster minus present, sorted + deduped
  · resolve_ack_timing           — reads both config keys, forwards defaults

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
    boot_counter_path,
    next_boot_id,
    emit_bounce_broadcast_in_process,
    count_acked_sessions,
    poll_acks_until_satisfied,
    wait_for_reconnection_plateau,
    missed_sessions,
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

    def test_warning_hold_is_self_limiting( self ):
        # The hold's exit must NOT be the all-clear alone — a missed all-clear
        # would otherwise suppress a session indefinitely (Tiffany's own case).
        msg = build_bounce_message( "warning" ).lower()
        self.assertIn( "all-clear", msg )
        self.assertIn( "confirm the server is healthy yourself", msg )

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

    def test_a_non_default_label_reaches_BOTH_message_kinds( self ):
        """
        Bug 652271f3: the test server announced itself as the dev server.

        Both containers run the same main.py, so the label must come from config
        and travel to BOTH builders. Asserting only the default proves nothing
        here — the default IS the bug — so this passes ":8000" and demands the
        dev port be absent from each message, not merely that the test port appear.
        """
        warning   = build_bounce_message( "warning", server_label=":8000" )
        all_clear = build_bounce_message( "all-clear", boot_id=3, boot_started="t", uptime_seconds=1.0,
                                          server_label=":8000" )

        for msg in ( warning, all_clear ):
            self.assertIn(    ":8000", msg )
            self.assertNotIn( ":7999", msg )


# ─── next_boot_id ───────────────────────────────────────────────────────────


class BootCounterPathTests( unittest.TestCase ):
    """
    Bug 652271f3, second symptom: `io/` is bind-mounted into BOTH containers, so
    one shared counter file interleaved dev and test boots. The number a watcher
    is told to expect for a specific bounce was therefore unpredictable.
    """

    def test_two_servers_get_two_different_files( self ):
        dev  = boot_counter_path( "/repo", ":7999" )
        test = boot_counter_path( "/repo", ":8000" )

        self.assertNotEqual( dev, test )
        self.assertEqual( dev.name,  "boot-counter-7999.txt" )
        self.assertEqual( test.name, "boot-counter-8000.txt" )
        self.assertTrue( str( dev ).endswith( "io/managed-bounce/boot-counter-7999.txt" ) )

    def test_default_label_is_the_dev_server( self ):
        self.assertEqual( boot_counter_path( "/repo" ).name, "boot-counter-7999.txt" )

    def test_a_label_cannot_escape_the_counter_directory( self ):
        # A label is config, not user input — but a path separator in it would
        # silently write outside io/managed-bounce/, so it collapses like any
        # other non-alphanumeric.
        path = boot_counter_path( "/repo", "../../etc/passwd" )

        self.assertEqual( path.parent.as_posix(), "/repo/io/managed-bounce" )
        self.assertNotIn( "/", path.name )

    def test_a_label_with_no_alphanumerics_falls_back_rather_than_hiding( self ):
        # "" or "///" must not yield "boot-counter-.txt" — a name that reads as
        # a bug and sorts oddly. Fall back to an explicit slug instead.
        self.assertEqual( boot_counter_path( "/repo", "///" ).name, "boot-counter-default.txt" )
        self.assertEqual( boot_counter_path( "/repo", ""    ).name, "boot-counter-default.txt" )

    def test_the_two_servers_sequences_do_not_interleave( self ):
        """End-to-end: advancing one server's counter must not move the other's."""
        with tempfile.TemporaryDirectory() as root:
            dev  = boot_counter_path( root, ":7999" )
            test = boot_counter_path( root, ":8000" )
            os.makedirs( dev.parent )

            self.assertEqual( next_boot_id( dev ),  1 )
            self.assertEqual( next_boot_id( test ), 1 )   # NOT 2 — separate sequences
            self.assertEqual( next_boot_id( dev ),  2 )
            self.assertEqual( next_boot_id( dev ),  3 )
            self.assertEqual( next_boot_id( test ), 2 )   # unmoved by the three dev boots


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


class MissedSessionsTests( unittest.TestCase ):

    def test_returns_roster_minus_present_sorted( self ):
        # Named on deadline expiry: who was expected back (roster) but has no socket.
        self.assertEqual( missed_sessions( [ "c", "a", "b" ], [ "b" ] ), [ "a", "c" ] )

    def test_empty_when_everyone_present( self ):
        self.assertEqual( missed_sessions( [ "a", "b" ], [ "a", "b", "x" ] ), [ ] )

    def test_dedupes_repeated_roster_ids( self ):
        self.assertEqual( missed_sessions( [ "a", "a", "b" ], [ ] ), [ "a", "b" ] )


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


# ─── wait_for_reconnection_plateau (the emitted != heard guard) ─────────────


class PlateauGateTests( unittest.TestCase ):

    def test_plateau_fires_after_stable_polls_consecutive_equal_reads( self ):
        # count climbs 3 → 7 → 7; with stable_polls=2 the second equal 7 is the plateau.
        counts = iter( [ 3, 7, 7 ] )
        sleep  = MagicMock()
        res = wait_for_reconnection_plateau(
            count_fn=lambda: next( counts ), minimum=1, stable_polls=2, deadline_seconds=10,
            poll_interval_seconds=0.5, now_fn=_FakeClock( [ 0, 0, 0, 0 ] ), sleep_fn=sleep,
        )
        self.assertEqual( res[ "reason" ], "plateau" )
        self.assertEqual( res[ "count" ], 7 )
        self.assertEqual( res[ "curve" ], [ 3, 7, 7 ] )
        self.assertEqual( sleep.call_count, 2 )     # did NOT fire on the first 7

    def test_single_stable_read_does_NOT_fire_needs_two( self ):
        # THE fires-on-a-single-plateau guard. count is 7 from the first poll; a naive
        # gate fires immediately. With stable_polls=2 it must wait for a SECOND equal
        # read before firing. PREDICTED FAILURE if stable_polls is mis-implemented as
        # run>=1 (fires on a single read): the gate returns at the first poll, so
        # `sleep.assert_called_once()` fails with "Expected 'mock' to be called once.
        # Called 0 times." and res["curve"] would be [7] not [7, 7].
        counts = iter( [ 7, 7 ] )
        sleep  = MagicMock()
        res = wait_for_reconnection_plateau(
            count_fn=lambda: next( counts ), minimum=1, stable_polls=2, deadline_seconds=10,
            poll_interval_seconds=0.5, now_fn=_FakeClock( [ 0, 0, 0 ] ), sleep_fn=sleep,
        )
        self.assertEqual( res[ "reason" ], "plateau" )
        self.assertEqual( res[ "curve" ], [ 7, 7 ] )
        sleep.assert_called_once()                  # exactly one wait: the first 7 did NOT fire

    def test_never_stabilizes_rides_to_deadline( self ):
        # A strictly-climbing count never plateaus → deadline fire, curve preserved.
        counts = iter( [ 1, 2, 3 ] )
        res = wait_for_reconnection_plateau(
            count_fn=lambda: next( counts ), minimum=1, stable_polls=2, deadline_seconds=10,
            poll_interval_seconds=1, now_fn=_FakeClock( [ 0, 0, 1, 100 ] ), sleep_fn=MagicMock(),
        )
        self.assertEqual( res[ "reason" ], "deadline" )
        self.assertEqual( res[ "curve" ], [ 1, 2, 3 ] )

    def test_plateau_at_zero_below_minimum_rides_to_deadline( self ):
        # A plateau at 0 is NOT a settled fleet — nobody came back. Mutation-proof:
        # drop the `count >= minimum` guard and this flips to reason "plateau".
        res = wait_for_reconnection_plateau(
            count_fn=lambda: 0, minimum=1, stable_polls=2, deadline_seconds=10,
            poll_interval_seconds=1, now_fn=_FakeClock( [ 0, 0, 100 ] ), sleep_fn=MagicMock(),
        )
        self.assertEqual( res[ "reason" ], "deadline" )
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
