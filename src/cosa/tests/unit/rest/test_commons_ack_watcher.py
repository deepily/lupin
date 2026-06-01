"""
Unit tests for CommonsAckWatcher (cosa.rest.commons_ack_watcher).

Covers __init__, register_broadcast (insert / collision-reraise),
unregister_broadcast, is_in_flight (present / expired-pruned / unknown),
_initialize_last_seen_ts (entries / empty / exception with debug-on/off),
tick (FileNotFoundError-zero / rich multi-entry dispatch walking every
update-cursor + skip + inflight arc / all-ts-None final-skip /
latest-equals-last-seen final-skip), and _push_ack_event (success /
exception with debug-on/off) — to genuine 100% line + branch + function.

No threads, no network: store + push_notification_fn are boundary-mocked; tick
and _push_ack_event are invoked directly. ZERO disk, ZERO real daemon.
"""

import unittest
from unittest.mock import Mock, patch

from cosa.rest.commons_ack_watcher import CommonsAckWatcher, _InFlightEntry


class _AckBase( unittest.TestCase ):
    def setUp( self ):
        self.store = Mock( name="store" )
        self.push  = Mock( name="push_fn" )
        self.w     = CommonsAckWatcher( store=self.store, push_notification_fn=self.push,
                                        poll_interval_seconds=1.0, in_flight_ttl_seconds=300.0,
                                        debug=True )


class TestInit( _AckBase ):
    def test_stores_push_fn_and_thread_name( self ):
        self.assertIs( self.w.push_notification_fn, self.push )
        self.assertEqual( self.w._thread_name, "CommonsAckWatcher" )


class TestRegisterBroadcast( _AckBase ):
    def test_insert( self ):
        self.w.register_broadcast( "b1", "user-1", 3 )
        self.assertTrue( self.w.is_in_flight( "b1" ) )

    def test_collision_reraises_domain_message( self ):
        self.w.register_broadcast( "b1", "user-1", 3 )
        with self.assertRaises( ValueError ) as ctx:
            self.w.register_broadcast( "b1", "user-1", 3 )
        self.assertIn( "broadcast_id collision", str( ctx.exception ) )


class TestUnregisterBroadcast( _AckBase ):
    def test_removes_entry( self ):
        self.w.register_broadcast( "b1", "user-1", 3 )
        self.w.unregister_broadcast( "b1" )
        self.assertFalse( self.w.is_in_flight( "b1" ) )

    def test_silent_on_unknown( self ):
        self.w.unregister_broadcast( "nope" )


class TestIsInFlight( _AckBase ):
    def test_present( self ):
        self.w.register_broadcast( "b1", "user-1", 3 )
        self.assertTrue( self.w.is_in_flight( "b1" ) )

    def test_expired_is_pruned( self ):
        self.w.register_broadcast( "b1", "user-1", 3 )
        self.w._in_flight[ "b1" ].expires_at_monotonic = 0.0   # force expiry
        self.assertFalse( self.w.is_in_flight( "b1" ) )

    def test_unknown( self ):
        self.assertFalse( self.w.is_in_flight( "ghost" ) )


class TestInitializeLastSeenTs( _AckBase ):
    def test_with_entries_sets_cursor( self ):
        self.store.read.return_value = [ { "ts": "2026-01-01T00:00:00Z" } ]
        self.w._initialize_last_seen_ts()
        self.assertEqual( self.w._last_seen_ts, "2026-01-01T00:00:00Z" )
        self.assertTrue( self.w._initialized_last_seen )

    def test_empty_leaves_cursor_none( self ):
        self.store.read.return_value = []
        self.w._initialize_last_seen_ts()
        self.assertIsNone( self.w._last_seen_ts )
        self.assertTrue( self.w._initialized_last_seen )

    def test_exception_debug_on_prints( self ):
        self.store.read.side_effect = RuntimeError( "store down" )
        with patch( "builtins.print" ) as mp:
            self.w._initialize_last_seen_ts()
        self.assertTrue( self.w._initialized_last_seen )
        self.assertTrue( any( "startup _last_seen_ts init failed" in str( c ) for c in mp.call_args_list ) )

    def test_exception_debug_off_silent( self ):
        self.w.debug = False
        self.store.read.side_effect = RuntimeError( "store down" )
        with patch( "builtins.print" ) as mp:
            self.w._initialize_last_seen_ts()
        mp.assert_not_called()
        self.assertTrue( self.w._initialized_last_seen )


class TestTick( _AckBase ):
    def test_file_not_found_returns_zero( self ):
        self.store.read.side_effect = FileNotFoundError
        self.assertEqual( self.w.tick(), 0 )

    def test_rich_multi_entry_dispatch( self ):
        self.w.register_broadcast( "b1", "user-1", 5 )
        self.store.read.return_value = [
            { "ts": None,  "metadata": {} },                                   # ts None skip; no bid → continue
            { "ts": "t1",  "metadata": { "broadcast_id": "unknown" } },        # latest None→t1; inflight None → continue
            { "ts": "t2",  "metadata": { "broadcast_id": "b1", "status": "ok", "body_summary": "x" },
              "sender_session_id": "s", "persona_name": "p", "persona_icon": "i", "persona_color": "c" },  # t2>t1 update; dispatch
            { "ts": "t0",  "metadata": { "broadcast_id": "b1" } },             # t0>t2 False no-update; dispatch
        ]
        dispatched = self.w.tick()
        self.assertEqual( dispatched, 2 )
        self.assertEqual( self.w._last_seen_ts, "t2" )          # final update (latest != None)
        self.assertEqual( self.w._in_flight[ "b1" ].received_acks, 2 )
        self.assertEqual( self.push.call_count, 2 )

    def test_all_ts_none_dispatches_without_cursor_update( self ):
        self.w.register_broadcast( "b1", "user-1", 5 )
        self.store.read.return_value = [ { "ts": None, "metadata": { "broadcast_id": "b1" } } ]
        self.assertEqual( self.w.tick(), 1 )
        self.assertIsNone( self.w._last_seen_ts )               # latest_ts None → final skip

    def test_latest_equals_last_seen_no_update( self ):
        self.w._last_seen_ts = "t5"
        self.w.register_broadcast( "b1", "user-1", 5 )
        self.store.read.return_value = [ { "ts": "t5", "metadata": { "broadcast_id": "b1" } } ]
        self.assertEqual( self.w.tick(), 1 )
        self.assertEqual( self.w._last_seen_ts, "t5" )          # latest == last_seen → final skip


class TestPushAckEvent( _AckBase ):
    def test_success_passes_payload( self ):
        entry = { "sender_session_id": "s", "persona_name": "p",
                  "persona_icon": "i", "persona_color": "c" }
        self.w._push_ack_event( entry, "b1", "user-1", { "status": "ok", "body_summary": "z" } )
        kwargs = self.push.call_args.kwargs
        self.assertEqual( kwargs[ "type" ], "commons_broadcast_ack" )
        self.assertEqual( kwargs[ "user_id" ], "user-1" )
        self.assertEqual( kwargs[ "payload" ][ "broadcast_id" ], "b1" )

    def test_exception_debug_on_prints( self ):
        self.push.side_effect = RuntimeError( "push boom" )
        with patch( "builtins.print" ) as mp:
            self.w._push_ack_event( {}, "b1", "user-1", {} )
        self.assertTrue( any( "push failed for b1" in str( c ) for c in mp.call_args_list ) )

    def test_exception_debug_off_silent( self ):
        self.w.debug = False
        self.push.side_effect = RuntimeError( "push boom" )
        with patch( "builtins.print" ) as mp:
            self.w._push_ack_event( {}, "b1", "user-1", {} )
        mp.assert_not_called()


def isolated_unit_test():
    """
    Run the CommonsAckWatcher unit tests in isolation.

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
    print( f"\n{'✅ PASS' if ok else '❌ FAIL'} CommonsAckWatcher tests in {secs:.3f}s — {msg}" )
