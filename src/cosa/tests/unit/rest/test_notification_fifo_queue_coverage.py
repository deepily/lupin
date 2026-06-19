#!/usr/bin/env python3
"""
Supplemental unit tests — `cosa.rest.notification_fifo_queue` coverage closure.

Complements `test_notification_fifo_queue.py` (mark_played emission regression).
This file closes the remaining gap across both classes:

    NotificationItem:
        - `_get_local_timestamp` / `_get_time_display` happy paths (the
          `lupin_app.main` config branch — exercised via a G1 DUAL-KEY
          sys.modules patch so the `import lupin_app.main as m` binding
          resolves to a mock regardless of full-suite import ordering),
    NotificationFifoQueue:
        - `__init__` debug print, `push` debug print,
        - `push_notification` urgent/high priority-insert branch + debug print,
        - `_emit_notification_added` broadcast (user_id=None) + cc-listener arms,
          plus the user-targeted debug print,
        - `mark_played` not-found + success debug prints,
        - `get_next_unplayed`, `get_user_notifications`,
        - `_log_to_io_tbl` / `_log_playback_to_io_tbl` verbose + exception arms.

Boundary-mock discipline: `InputAndOutputTable` is patched at import-site so
construction never touches a DB/embedding layer; `du.get_current_datetime_raw`
is patched in the timestamp tests for determinism; `websocket_mgr` is a Mock.
ZERO DB, ZERO embeddings, ZERO network, ZERO TTS.

Run: PYTHONPATH=src:src/cosa/tests/unit/infrastructure \
     src/cosa/.venv/bin/python -m pytest \
     src/cosa/tests/unit/rest/test_notification_fifo_queue_coverage.py -v
"""

import sys
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch


def _patch_fastapi_main( app_debug=True, tz="America/New_York" ):
    """G1 DUAL-KEY patch: bind BOTH `lupin_app` (with `.main`) and
    `lupin_app.main` so `import lupin_app.main as m` resolves to the mock
    whether the binding goes through the package attribute or the submodule
    key (the gotcha that passes in isolation but fails under suite ordering)."""
    cfg          = MagicMock()
    cfg.get.return_value = tz
    main         = MagicMock()
    main.config_mgr = cfg
    main.app_debug  = app_debug
    pkg          = MagicMock()
    pkg.main     = main
    return patch.dict( sys.modules, { "lupin_app": pkg, "lupin_app.main": main } )


class _Base( unittest.TestCase ):
    """Shared harness — patches InputAndOutputTable so no DB layer is touched."""

    def setUp( self ):
        self._io_patch     = patch( "cosa.rest.notification_fifo_queue.InputAndOutputTable" )
        self._io_cls       = self._io_patch.start()
        self._io_cls.return_value = MagicMock()
        from cosa.rest.notification_fifo_queue import NotificationFifoQueue, NotificationItem
        self.NFQ  = NotificationFifoQueue
        self.NI   = NotificationItem
        self.ws   = MagicMock()

    def tearDown( self ):
        self._io_patch.stop()


class TestNotificationItemTimestamps( _Base ):
    """
    Exercises NotificationItem timestamp helpers' happy paths.

    Ensures:
        - `_get_local_timestamp` uses the configured timezone and returns ISO
          (with the app_debug print branch taken)
        - `_get_time_display` returns the "HH:MM TZ" formatted string
    """

    def test_get_local_timestamp_happy_path( self ):
        fixed = datetime( 2026, 1, 1, 12, 0, 0 )
        with _patch_fastapi_main( app_debug=True ), \
             patch( "cosa.rest.notification_fifo_queue.du.get_current_datetime_raw", return_value=fixed ):
            item = self.NI( message="m" )
        self.assertEqual( item.timestamp, "2026-01-01T12:00:00" )

    def test_get_time_display_happy_path( self ):
        fixed = datetime( 2026, 1, 1, 14, 30, 0 )
        with _patch_fastapi_main( app_debug=False ), \
             patch( "cosa.rest.notification_fifo_queue.du.get_current_datetime_raw", return_value=fixed ):
            item = self.NI( message="m" )
            display = item._get_time_display()
        self.assertTrue( display.startswith( "14:30" ) )


class TestInitAndPushDebug( _Base ):
    """
    Exercises the debug-print branches of __init__ and push.

    Ensures:
        - constructing with debug=True executes the init debug print
        - push() with debug=True executes its debug print and enqueues
    """

    def test_init_debug_print( self ):
        q = self.NFQ( debug=True )
        self.assertEqual( q.size(), 0 )

    def test_push_debug_print( self ):
        q    = self.NFQ( websocket_mgr=self.ws, emit_enabled=True, debug=True )
        item = self.NI( message="m", priority="medium", user_id="u1" )
        q.push( item )
        self.assertEqual( q.size(), 1 )


class TestPushNotificationPriority( _Base ):
    """
    Exercises `push_notification` priority placement.

    Ensures:
        - high/urgent notifications insert ahead of normal ones but after other
          high/urgent ones (the insert-index scan, including the break)
        - inserting into an empty queue places at index 0
        - the debug print branch fires when debug=True
    """

    def test_high_priority_inserts_after_other_highs( self ):
        q = self.NFQ( websocket_mgr=self.ws, emit_enabled=True, debug=True )
        q.push_notification( message="h1", priority="high",   user_id="u1" )
        q.push_notification( message="h2", priority="urgent", user_id="u1" )
        q.push_notification( message="m1", priority="medium", user_id="u1" )
        # h3 should land at index 2 (after h1,h2; before m1 — loop breaks at m1)
        q.push_notification( message="h3", priority="high",   user_id="u1" )
        order = [ n.message for n in q.queue_list ]
        self.assertEqual( order, [ "h1", "h2", "h3", "m1" ] )

    def test_high_priority_into_empty_queue( self ):
        q = self.NFQ( websocket_mgr=self.ws, emit_enabled=True )
        q.push_notification( message="h1", priority="high", user_id="u1" )
        self.assertEqual( q.queue_list[ 0 ].message, "h1" )


class TestEmitNotificationAdded( _Base ):
    """
    Exercises `_emit_notification_added` dispatch arms.

    Ensures:
        - user_id set → emit_to_user_or_listener_sync (user-targeted), debug print
        - user_id None → broadcast emit; with job_id also a cc-listener emit
    """

    def test_user_targeted_dispatch( self ):
        q = self.NFQ( websocket_mgr=self.ws, emit_enabled=True, debug=True )
        q.push_notification( message="m", priority="medium", user_id="u1", job_id="dr-a1b2c3d4" )
        self.ws.emit_to_user_or_listener_sync.assert_called_once()
        kw = self.ws.emit_to_user_or_listener_sync.call_args.kwargs
        self.assertEqual( kw[ "user_id" ], "u1" )
        self.assertEqual( kw[ "event" ], "notification_queue_update" )

    def test_broadcast_dispatch_with_listener( self ):
        q = self.NFQ( websocket_mgr=self.ws, emit_enabled=True, debug=True )
        # user_id=None → broadcast; job_id set → additional listener emit
        q.push_notification( message="m", priority="medium", user_id=None, job_id="dr-a1b2c3d4" )
        self.ws.emit.assert_called_once()
        self.assertEqual( self.ws.emit.call_args.args[ 0 ], "notification_queue_update" )
        # listener emit with user_id=None
        self.ws.emit_to_user_or_listener_sync.assert_called_once()
        self.assertIsNone( self.ws.emit_to_user_or_listener_sync.call_args.kwargs[ "user_id" ] )

    def test_broadcast_without_job_id_no_listener( self ):
        q = self.NFQ( websocket_mgr=self.ws, emit_enabled=True )
        q.push_notification( message="m", priority="medium", user_id=None )
        self.ws.emit.assert_called_once()
        self.ws.emit_to_user_or_listener_sync.assert_not_called()


class TestMarkPlayedDebug( _Base ):
    """
    Exercises `mark_played` debug-print branches.

    Ensures:
        - unknown id with debug=True prints the not-found message, returns False
        - successful mark with debug=True prints the success message, returns True
    """

    def test_unknown_id_debug( self ):
        q = self.NFQ( websocket_mgr=self.ws, emit_enabled=True, debug=True )
        self.assertFalse( q.mark_played( "no-such-id" ) )

    def test_success_debug( self ):
        q = self.NFQ( websocket_mgr=self.ws, emit_enabled=True, debug=True )
        n = q.push_notification( message="m", priority="medium", user_id="u1" )
        self.assertTrue( q.mark_played( n.id_hash ) )
        self.assertTrue( n.played )


class TestGetNextUnplayed( _Base ):
    """
    Exercises `get_next_unplayed`.

    Ensures:
        - returns the first unplayed item for the user
        - skips items belonging to a different user when user_id is given
        - returns None when all items are played
    """

    def setUp( self ):
        super().setUp()
        self.q = self.NFQ( websocket_mgr=self.ws, emit_enabled=True )

    def test_returns_first_unplayed( self ):
        n1 = self.q.push_notification( message="a", priority="medium", user_id="u1" )
        self.q.push_notification( message="b", priority="medium", user_id="u1" )
        n1.played = True
        nxt = self.q.get_next_unplayed( "u1" )
        self.assertEqual( nxt.message, "b" )

    def test_skips_other_user( self ):
        self.q.push_notification( message="a", priority="medium", user_id="other" )
        nxt = self.q.get_next_unplayed( "u1" )
        self.assertIsNone( nxt )

    def test_none_when_all_played( self ):
        n1 = self.q.push_notification( message="a", priority="medium", user_id="u1" )
        n1.played = True
        self.assertIsNone( self.q.get_next_unplayed( "u1" ) )


class TestGetUserNotifications( _Base ):
    """
    Exercises `get_user_notifications`.

    Ensures:
        - returns all of a user's notifications when include_played=True
        - filters out played ones when include_played=False
    """

    def setUp( self ):
        super().setUp()
        self.q = self.NFQ( websocket_mgr=self.ws, emit_enabled=True )
        self.n1 = self.q.push_notification( message="a", priority="medium", user_id="u1" )
        self.n2 = self.q.push_notification( message="b", priority="medium", user_id="u1" )
        self.q.push_notification( message="c", priority="medium", user_id="other" )
        self.n1.played = True

    def test_include_played( self ):
        result = self.q.get_user_notifications( "u1", include_played=True )
        self.assertEqual( { n.message for n in result }, { "a", "b" } )

    def test_exclude_played( self ):
        result = self.q.get_user_notifications( "u1", include_played=False )
        self.assertEqual( { n.message for n in result }, { "b" } )


class TestIoTblLogging( _Base ):
    """
    Exercises `_log_to_io_tbl` and `_log_playback_to_io_tbl` arms.

    Ensures:
        - verbose=True logs the success message after a normal insert
        - an insert exception is swallowed (debug=True prints the failure)
    """

    def test_log_to_io_tbl_verbose_success( self ):
        q = self.NFQ( websocket_mgr=self.ws, emit_enabled=True, verbose=True )
        # default mocked _io_tbl.insert_io_row succeeds
        q.push_notification( message="m", priority="medium", user_id="u1" )
        q._io_tbl.insert_io_row.assert_called()

    def test_log_to_io_tbl_exception_swallowed( self ):
        q = self.NFQ( websocket_mgr=self.ws, emit_enabled=True, debug=True )
        q._io_tbl.insert_io_row.side_effect = Exception( "db down" )
        # must not raise
        q.push_notification( message="m", priority="medium", user_id="u1" )

    def test_log_to_io_tbl_exception_swallowed_debug_off( self ):
        # debug=False → the except's `if self.debug` FALSE arm (no print)
        q = self.NFQ( websocket_mgr=self.ws, emit_enabled=True, debug=False )
        q._io_tbl.insert_io_row.side_effect = Exception( "db down" )
        q.push_notification( message="m", priority="medium", user_id="u1" )

    def test_log_playback_verbose_success( self ):
        q = self.NFQ( websocket_mgr=self.ws, emit_enabled=True, verbose=True )
        n = q.push_notification( message="m", priority="medium", user_id="u1" )
        q.mark_played( n.id_hash )
        # playback insert called at least once
        self.assertTrue( q._io_tbl.insert_io_row.called )

    def test_log_playback_exception_swallowed( self ):
        q = self.NFQ( websocket_mgr=self.ws, emit_enabled=True, debug=True )
        n = q.push_notification( message="m", priority="medium", user_id="u1" )
        # now make the NEXT insert (playback) raise
        q._io_tbl.insert_io_row.side_effect = Exception( "db down" )
        self.assertTrue( q.mark_played( n.id_hash ) )   # swallowed, still returns True

    def test_log_playback_exception_swallowed_debug_off( self ):
        # debug=False → the playback except's `if self.debug` FALSE arm (no print)
        q = self.NFQ( websocket_mgr=self.ws, emit_enabled=True, debug=False )
        n = q.push_notification( message="m", priority="medium", user_id="u1" )
        q._io_tbl.insert_io_row.side_effect = Exception( "db down" )
        self.assertTrue( q.mark_played( n.id_hash ) )


def isolated_unit_test():
    """
    Run this module's tests in isolation.

    Ensures:
        - returns True when all tests pass, False otherwise
    """
    suite  = unittest.TestLoader().loadTestsFromModule( sys.modules[ __name__ ] )
    result = unittest.TextTestRunner( verbosity=2 ).run( suite )
    return result.wasSuccessful()


if __name__ == "__main__":
    isolated_unit_test()
