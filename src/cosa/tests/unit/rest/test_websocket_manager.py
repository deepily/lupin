"""
Unit tests for WebSocketManager — the core WebSocket connection manager.

Tests the full surface of cosa.rest.websocket_manager.WebSocketManager:
- Construction + configuration integration (event-list validation, single-session policy)
- Connection registration / single-session displacement / disconnect cleanup
- Pre-WebSocket session-user registration
- Async broadcast emission with event-subscription filtering + dead-connection cleanup
- Per-session + per-user emission (async + thread-safe sync wrappers)
- Admin-targeted + user-and-admin dual emission
- The user-or-listener dispatch helper (cross-user CC-listener fallback)
- Connection queries, session info, stale-session + heartbeat cleanup
- Event-subscription mutation + subscription statistics

Zero external dependencies: every WebSocket is an AsyncMock, ConfigurationManager
is patched to return controlled values, and asyncio.run_coroutine_threadsafe is
patched so the thread-safe sync wrappers schedule against a fake running loop.
No real sockets, network, event loops, GPU, DB, or LLM calls.
"""

import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import asyncio
from datetime import datetime, timedelta

# Import test infrastructure (kept for parity with sibling rest tests / path side-effects)
import sys
import os
sys.path.append( os.path.join( os.path.dirname( __file__ ), "..", "infrastructure" ) )

from cosa.rest.websocket_manager import WebSocketManager


DEFAULT_EVENTS = [ "notification_update", "audio_update", "job_update", "sys_ping" ]


def _make_manager(
    events            = None,
    single_session    = False,
    app_debug         = False,
    heartbeat_enabled = True,
    cleanup_enabled   = True,
    max_age_hours     = 24,
):
    """
    Construct a WebSocketManager with a fully-controlled mock ConfigurationManager.

    Requires:
        - events is None (→ DEFAULT_EVENTS) or a list of event-name strings

    Ensures:
        - Returns a real WebSocketManager whose config_mgr.get returns the
          supplied values for every key the class reads
        - Patches ConfigurationManager only during construction

    Raises:
        - ValueError (propagated) when events is an empty list — the
          construction-time guard under test
    """
    if events is None:
        events = list( DEFAULT_EVENTS )

    cfg = MagicMock()

    def _get( key, default=None, return_type=None ):
        mapping = {
            "websocket enforce single session per user" : single_session,
            "app debug"                                 : app_debug,
            "websocket available events"                : events,
            "websocket heartbeat enabled"               : heartbeat_enabled,
            "websocket cleanup enabled"                 : cleanup_enabled,
            "websocket session max age hours"           : max_age_hours,
        }
        return mapping.get( key, default )

    cfg.get.side_effect = _get

    with patch( "cosa.rest.websocket_manager.ConfigurationManager", return_value=cfg ):
        mgr = WebSocketManager()
    return mgr


def _make_ws():
    """
    Build a mock WebSocket whose async I/O methods are AsyncMocks.

    Ensures:
        - send_json / send_text / receive_json / receive_text / accept / close
          are all awaitable AsyncMocks
    """
    ws = MagicMock()
    ws.accept       = AsyncMock()
    ws.send_json     = AsyncMock()
    ws.send_text     = AsyncMock()
    ws.receive_json  = AsyncMock()
    ws.receive_text  = AsyncMock()
    ws.close         = AsyncMock()
    return ws


def _running_loop():
    """Return a fake event loop whose is_running() is True."""
    loop = MagicMock()
    loop.is_running.return_value = True
    return loop


def _fake_rcts( coro, loop ):
    """
    Stand-in for asyncio.run_coroutine_threadsafe.

    Consumes the coroutine so Python does not emit "coroutine was never
    awaited" warnings, then returns a fake Future.
    """
    if hasattr( coro, "close" ):
        coro.close()
    return MagicMock()


def _run( coro ):
    """Run a coroutine to completion on a throwaway event loop."""
    return asyncio.run( coro )


class TestWebSocketManagerInit( unittest.TestCase ):
    """Construction + configuration integration."""

    def test_init_populates_state_and_loads_events( self ):
        mgr = _make_manager( single_session=True, app_debug=True )
        self.assertEqual( mgr.active_connections, {} )
        self.assertEqual( mgr.session_to_user, {} )
        self.assertEqual( mgr.user_sessions, {} )
        self.assertEqual( mgr.user_to_email, {} )
        self.assertEqual( mgr.session_is_admin, {} )
        self.assertIsNone( mgr.main_loop )
        self.assertTrue( mgr.single_session_per_user )
        self.assertTrue( mgr.debug )
        self.assertEqual( mgr.available_events, set( DEFAULT_EVENTS ) )

    def test_init_raises_when_events_missing( self ):
        with self.assertRaises( ValueError ):
            _make_manager( events=[] )

    def test_set_event_loop_stores_reference( self ):
        mgr  = _make_manager()
        loop = _running_loop()
        mgr.set_event_loop( loop )
        self.assertIs( mgr.main_loop, loop )


class TestConnect( unittest.TestCase ):
    """connect(): registration, single-session displacement, subscriptions, admin."""

    def test_connect_basic_default_subscriptions( self ):
        mgr = _make_manager()
        ws  = _make_ws()
        mgr.connect( ws, "sess-1", user_id="user-1", email="a@b.com", roles=[ "user" ] )

        self.assertIs( mgr.active_connections[ "sess-1" ], ws )
        self.assertEqual( mgr.session_to_user[ "sess-1" ], "user-1" )
        self.assertEqual( mgr.user_sessions[ "user-1" ], [ "sess-1" ] )
        self.assertEqual( mgr.user_to_email[ "user-1" ], "a@b.com" )
        self.assertFalse( mgr.session_is_admin[ "sess-1" ] )
        self.assertEqual( mgr.session_subscriptions[ "sess-1" ], [ "*" ] )
        self.assertIn( "sess-1", mgr.session_timestamps )

    def test_connect_admin_role_flagged( self ):
        mgr = _make_manager()
        mgr.connect( _make_ws(), "sess-admin", user_id="u-admin", roles=[ "admin" ] )
        self.assertTrue( mgr.session_is_admin[ "sess-admin" ] )

    def test_connect_no_user_id_skips_user_association( self ):
        mgr = _make_manager()
        mgr.connect( _make_ws(), "sess-anon" )
        self.assertNotIn( "sess-anon", mgr.session_to_user )
        self.assertEqual( mgr.user_sessions, {} )

    def test_connect_validates_subscribed_events( self ):
        mgr = _make_manager()
        mgr.connect(
            _make_ws(), "sess-sub", user_id="u-2",
            subscribed_events=[ "job_update", "not_a_real_event", "*" ]
        )
        # "not_a_real_event" filtered out; valid event + "*" kept
        self.assertEqual( mgr.session_subscriptions[ "sess-sub" ], [ "job_update", "*" ] )

    def test_connect_listener_session_type_branch( self ):
        mgr = _make_manager()
        # cc-listener-* prefix exercises the listener session_type branch
        mgr.connect( _make_ws(), "cc-listener-job1", user_id="svc", subscribed_events=[ "job_update" ] )
        self.assertEqual( mgr.session_subscriptions[ "cc-listener-job1" ], [ "job_update" ] )

    def test_connect_existing_user_appends_session_no_dup( self ):
        mgr = _make_manager()
        mgr.connect( _make_ws(), "sess-a", user_id="u-3" )
        mgr.connect( _make_ws(), "sess-b", user_id="u-3" )
        self.assertEqual( mgr.user_sessions[ "u-3" ], [ "sess-a", "sess-b" ] )
        # Re-connect with same session id → no duplicate
        mgr.connect( _make_ws(), "sess-a", user_id="u-3" )
        self.assertEqual( mgr.user_sessions[ "u-3" ].count( "sess-a" ), 1 )

    def test_connect_single_session_closes_old( self ):
        mgr  = _make_manager( single_session=True )
        loop = _running_loop()
        mgr.set_event_loop( loop )
        old_ws = _make_ws()
        mgr.connect( old_ws, "old-sess", user_id="u-4" )

        with patch( "cosa.rest.websocket_manager.asyncio.run_coroutine_threadsafe", side_effect=_fake_rcts ) as rcts:
            mgr.connect( _make_ws(), "new-sess", user_id="u-4" )

        # Old session displaced + cleaned up; new session active
        self.assertNotIn( "old-sess", mgr.active_connections )
        self.assertIn( "new-sess", mgr.active_connections )
        self.assertTrue( rcts.called )

    def test_connect_single_session_close_exception_handled( self ):
        mgr  = _make_manager( single_session=True )
        mgr.set_event_loop( _running_loop() )
        old_ws = _make_ws()
        old_ws.close = MagicMock()                          # non-coroutine: rcts raises before consuming it
        mgr.connect( old_ws, "old-sess", user_id="u-5" )

        with patch( "cosa.rest.websocket_manager.asyncio.run_coroutine_threadsafe", side_effect=RuntimeError( "boom" ) ):
            # Exception inside close-scheduling is swallowed; cleanup still proceeds
            mgr.connect( _make_ws(), "new-sess", user_id="u-5" )
        self.assertNotIn( "old-sess", mgr.active_connections )
        self.assertIn( "new-sess", mgr.active_connections )

    def test_connect_single_session_no_loop_skips_close( self ):
        mgr = _make_manager( single_session=True )
        # main_loop is None → close-scheduling skipped, but disconnect still runs
        mgr.connect( _make_ws(), "old-sess", user_id="u-6" )
        mgr.connect( _make_ws(), "new-sess", user_id="u-6" )
        self.assertNotIn( "old-sess", mgr.active_connections )
        self.assertEqual( mgr.user_sessions[ "u-6" ], [ "new-sess" ] )

    def test_connect_single_session_same_session_id_not_closed( self ):
        mgr = _make_manager( single_session=True )
        mgr.set_event_loop( _running_loop() )
        ws = _make_ws()
        mgr.connect( ws, "same-sess", user_id="u-7" )
        with patch( "cosa.rest.websocket_manager.asyncio.run_coroutine_threadsafe", side_effect=_fake_rcts ) as rcts:
            # Reconnecting with the SAME session id must not close it (old==new branch false)
            mgr.connect( ws, "same-sess", user_id="u-7" )
        self.assertIn( "same-sess", mgr.active_connections )
        self.assertFalse( rcts.called )

    def test_connect_single_session_empty_existing_list( self ):
        mgr = _make_manager( single_session=True )
        # user present in user_sessions but with an empty list → len()==0 branch
        mgr.user_sessions[ "u-8" ] = []
        mgr.connect( _make_ws(), "fresh-sess", user_id="u-8" )
        self.assertEqual( mgr.user_sessions[ "u-8" ], [ "fresh-sess" ] )


class TestDisconnect( unittest.TestCase ):
    """disconnect(): close frame + full state cleanup."""

    def test_disconnect_full_cleanup_last_session( self ):
        mgr  = _make_manager()
        mgr.set_event_loop( _running_loop() )
        ws   = _make_ws()
        mgr.connect( ws, "sess-1", user_id="u-1", email="a@b.com" )

        with patch( "cosa.rest.websocket_manager.asyncio.run_coroutine_threadsafe", side_effect=_fake_rcts ) as rcts:
            mgr.disconnect( "sess-1" )

        self.assertNotIn( "sess-1", mgr.active_connections )
        self.assertNotIn( "sess-1", mgr.session_timestamps )
        self.assertNotIn( "sess-1", mgr.session_subscriptions )
        self.assertNotIn( "sess-1", mgr.session_is_admin )
        self.assertNotIn( "sess-1", mgr.session_to_user )
        self.assertNotIn( "u-1", mgr.user_sessions )       # empty → removed
        self.assertNotIn( "u-1", mgr.user_to_email )       # email purged with last session
        self.assertTrue( rcts.called )

    def test_disconnect_keeps_user_with_remaining_session( self ):
        mgr = _make_manager()
        mgr.connect( _make_ws(), "sess-a", user_id="u-2", email="x@y.com" )
        mgr.connect( _make_ws(), "sess-b", user_id="u-2" )
        mgr.disconnect( "sess-a" )
        self.assertEqual( mgr.user_sessions[ "u-2" ], [ "sess-b" ] )
        self.assertIn( "u-2", mgr.user_to_email )          # still has a session → email kept

    def test_disconnect_missing_session_is_noop( self ):
        mgr = _make_manager()
        # No raise for an unknown session id
        mgr.disconnect( "ghost" )
        self.assertEqual( mgr.active_connections, {} )

    def test_disconnect_listener_type_and_close_exception( self ):
        mgr = _make_manager()
        mgr.set_event_loop( _running_loop() )
        ws  = _make_ws()
        ws.close = MagicMock()                              # non-coroutine: rcts raises before consuming it
        mgr.connect( ws, "cc-listener-job9", user_id="svc" )
        with patch( "cosa.rest.websocket_manager.asyncio.run_coroutine_threadsafe", side_effect=RuntimeError( "boom" ) ):
            # close-scheduling raises → swallowed; connection still removed
            mgr.disconnect( "cc-listener-job9" )
        self.assertNotIn( "cc-listener-job9", mgr.active_connections )

    def test_disconnect_no_loop_skips_close_still_removes( self ):
        mgr = _make_manager()
        mgr.connect( _make_ws(), "sess-x", user_id="u-3" )
        mgr.disconnect( "sess-x" )                          # main_loop None → no close, still removed
        self.assertNotIn( "sess-x", mgr.active_connections )

    def test_disconnect_user_id_not_in_user_sessions_branch( self ):
        mgr = _make_manager()
        mgr.connect( _make_ws(), "sess-1", user_id="u-9" )
        # Force inconsistent state: session_to_user still maps, but user_sessions entry gone
        # → exercises the `if user_id in self.user_sessions` FALSE branch (239->245).
        del mgr.user_sessions[ "u-9" ]
        mgr.disconnect( "sess-1" )
        self.assertNotIn( "sess-1", mgr.session_to_user )
        self.assertNotIn( "sess-1", mgr.active_connections )


class TestRegisterAndQueries( unittest.TestCase ):
    """register_session_user + simple connection queries."""

    def test_register_session_user_new_and_dup( self ):
        mgr = _make_manager()
        mgr.register_session_user( "sess-1", "u-1" )
        self.assertEqual( mgr.session_to_user[ "sess-1" ], "u-1" )
        self.assertEqual( mgr.user_sessions[ "u-1" ], [ "sess-1" ] )
        # Re-register same pair → no duplicate
        mgr.register_session_user( "sess-1", "u-1" )
        self.assertEqual( mgr.user_sessions[ "u-1" ], [ "sess-1" ] )

    def test_get_connection_count( self ):
        mgr = _make_manager()
        self.assertEqual( mgr.get_connection_count(), 0 )
        mgr.connect( _make_ws(), "sess-1" )
        self.assertEqual( mgr.get_connection_count(), 1 )

    def test_is_connected( self ):
        mgr = _make_manager()
        mgr.connect( _make_ws(), "sess-1" )
        self.assertTrue( mgr.is_connected( "sess-1" ) )
        self.assertFalse( mgr.is_connected( "nope" ) )

    def test_is_user_connected( self ):
        mgr = _make_manager()
        self.assertFalse( mgr.is_user_connected( "unknown" ) )      # user not in user_sessions
        mgr.connect( _make_ws(), "sess-1", user_id="u-1" )
        self.assertTrue( mgr.is_user_connected( "u-1" ) )
        # user present but its session not in active_connections → False
        mgr.user_sessions[ "u-2" ] = [ "orphan" ]
        self.assertFalse( mgr.is_user_connected( "u-2" ) )

    def test_get_user_connection_count( self ):
        mgr = _make_manager()
        self.assertEqual( mgr.get_user_connection_count( "unknown" ), 0 )
        mgr.connect( _make_ws(), "sess-1", user_id="u-1" )
        mgr.connect( _make_ws(), "sess-2", user_id="u-1" )
        self.assertEqual( mgr.get_user_connection_count( "u-1" ), 2 )

    def test_set_single_session_policy_toggle( self ):
        mgr = _make_manager()
        mgr.set_single_session_policy( True )
        self.assertTrue( mgr.single_session_per_user )
        mgr.set_single_session_policy( False )
        self.assertFalse( mgr.single_session_per_user )


class TestAsyncEmit( unittest.TestCase ):
    """async_emit / emit_to_session / emit_to_all (the awaitable broadcast core)."""

    def test_async_emit_filters_by_subscription( self ):
        mgr = _make_manager()
        ws_all      = _make_ws()
        ws_filtered = _make_ws()
        ws_other    = _make_ws()
        mgr.connect( ws_all,      "s-all",      subscribed_events=[ "*" ] )
        mgr.connect( ws_filtered, "s-filtered", subscribed_events=[ "job_update" ] )
        mgr.connect( ws_other,    "s-other",    subscribed_events=[ "audio_update" ] )

        _run( mgr.async_emit( "job_update", { "payload": 1 } ) )

        ws_all.send_json.assert_awaited_once()
        ws_filtered.send_json.assert_awaited_once()
        ws_other.send_json.assert_not_awaited()             # not subscribed → skipped
        sent = ws_all.send_json.await_args.args[ 0 ]
        self.assertEqual( sent[ "type" ], "job_update" )
        self.assertIn( "timestamp", sent )

    def test_async_emit_cleans_up_failed_send( self ):
        mgr = _make_manager()
        good = _make_ws()
        bad  = _make_ws()
        bad.send_json.side_effect = RuntimeError( "dead socket" )
        mgr.connect( good, "s-good" )
        mgr.connect( bad,  "s-bad" )

        _run( mgr.async_emit( "job_update", {} ) )
        # Failed connection auto-disconnected
        self.assertNotIn( "s-bad", mgr.active_connections )
        self.assertIn( "s-good", mgr.active_connections )

    def test_async_emit_default_subscription_when_missing( self ):
        mgr = _make_manager()
        ws  = _make_ws()
        mgr.active_connections[ "s-1" ] = ws                # no subscription entry → defaults to ["*"]
        _run( mgr.async_emit( "anything", {} ) )
        ws.send_json.assert_awaited_once()

    def test_emit_to_session_not_connected_returns_early( self ):
        mgr = _make_manager()
        # No raise, no send for an unknown session
        _run( mgr.emit_to_session( "nope", "evt", {} ) )

    def test_emit_to_session_sends( self ):
        mgr = _make_manager()
        ws  = _make_ws()
        mgr.connect( ws, "s-1" )
        _run( mgr.emit_to_session( "s-1", "job_update", { "k": "v" } ) )
        ws.send_json.assert_awaited_once()

    def test_emit_to_session_send_failure_disconnects( self ):
        mgr = _make_manager()
        ws  = _make_ws()
        ws.send_json.side_effect = RuntimeError( "boom" )
        mgr.connect( ws, "s-1" )
        _run( mgr.emit_to_session( "s-1", "job_update", {} ) )
        self.assertNotIn( "s-1", mgr.active_connections )

    def test_emit_to_all_broadcasts( self ):
        mgr = _make_manager()
        ws  = _make_ws()
        mgr.connect( ws, "s-1" )
        _run( mgr.emit_to_all( "job_update", {} ) )
        ws.send_json.assert_awaited_once()


class TestEmitToUserAsync( unittest.TestCase ):
    """emit_to_user(): per-user fan-out with subscription filter + orphan cleanup."""

    def test_emit_to_user_unknown_returns_false( self ):
        mgr = _make_manager()
        self.assertFalse( _run( mgr.emit_to_user( "unknown", "evt", {} ) ) )

    def test_emit_to_user_sends_to_subscribed_sessions( self ):
        mgr = _make_manager()
        ws1 = _make_ws()
        ws2 = _make_ws()
        mgr.connect( ws1, "s-1", user_id="u-1", subscribed_events=[ "*" ] )
        mgr.connect( ws2, "s-2", user_id="u-1", subscribed_events=[ "job_update" ] )
        result = _run( mgr.emit_to_user( "u-1", "job_update", {} ) )
        self.assertTrue( result )
        ws1.send_json.assert_awaited_once()
        ws2.send_json.assert_awaited_once()

    def test_emit_to_user_skips_unsubscribed_session( self ):
        mgr = _make_manager( app_debug=True )
        ws  = _make_ws()
        mgr.connect( ws, "s-1", user_id="u-1", subscribed_events=[ "audio_update" ] )
        result = _run( mgr.emit_to_user( "u-1", "job_update", {} ) )
        self.assertFalse( result )                          # nothing sent → sent_count 0
        ws.send_json.assert_not_awaited()

    def test_emit_to_user_mixed_delivery_reports_BOTH_halves( self ):
        """
        A partial delivery names the deliveries AND the declines, in one line.

        THE REGRESSION THIS PINS, measured 2026-09-01 on row 88347f65. This method
        logged the drop path and said NOTHING on success. A user whose two sockets
        split one-per-transport — a queue socket and an audio socket under one
        user — produced 749 loud "not subscribed" lines and complete silence about
        the frames that DID land. Three seats read that as a six-hour delivery
        outage and hunted a subscription bug in a path that was working correctly:
        every decline was an AUDIO socket properly refusing a QUEUE event.

        The decline count alone is not the defect and never was. The defect was
        that it appeared WITHOUT its denominator.

        Requires:
            - two sessions under one user: one subscribed, one not
            - app_debug FALSE, because the debug flag being off is exactly the
              condition under which the old silence was mistaken for breakage

        Ensures:
            - the subscribed session receives the frame
            - the unsubscribed one does not
            - a summary line carries delivered=1 AND declined=1 AND names the
              declining session
        """
        mgr = _make_manager( app_debug=False )
        ws_yes, ws_no = _make_ws(), _make_ws()
        mgr.connect( ws_yes, "queue-sock", user_id="u-1", subscribed_events=[ "job_update" ] )
        mgr.connect( ws_no,  "audio-sock", user_id="u-1", subscribed_events=[ "audio_update" ] )

        with patch( "builtins.print" ) as mock_print:
            result = _run( mgr.emit_to_user( "u-1", "job_update", {} ) )

        self.assertTrue( result )
        ws_yes.send_json.assert_awaited_once()
        ws_no.send_json.assert_not_awaited()

        printed = " ".join( str( c ) for c in mock_print.call_args_list )
        self.assertIn( "delivered=1", printed )
        self.assertIn( "declined=1", printed )
        self.assertIn( "audio-sock", printed, "the summary must name WHICH session declined" )

    def test_emit_to_user_all_delivered_stays_quiet( self ):
        """
        No declines → no summary line. The line exists to explain a decline, so
        emitting it on a clean delivery would just be new noise replacing old.

        Ensures:
            - a fully-delivered emit prints neither "declined=" nor "sent_count=0"
        """
        mgr = _make_manager( app_debug=False )
        ws  = _make_ws()
        mgr.connect( ws, "s-1", user_id="u-1", subscribed_events=[ "job_update" ] )

        with patch( "builtins.print" ) as mock_print:
            self.assertTrue( _run( mgr.emit_to_user( "u-1", "job_update", {} ) ) )

        printed = " ".join( str( c ) for c in mock_print.call_args_list )
        self.assertNotIn( "declined=", printed )
        self.assertNotIn( "sent_count=0", printed )

    def test_emit_to_user_send_failure_disconnects( self ):
        mgr = _make_manager()
        ws  = _make_ws()
        ws.send_json.side_effect = RuntimeError( "boom" )
        mgr.connect( ws, "s-1", user_id="u-1" )
        result = _run( mgr.emit_to_user( "u-1", "job_update", {} ) )
        self.assertFalse( result )
        self.assertNotIn( "s-1", mgr.active_connections )

    def test_emit_to_user_cleans_orphaned_session( self ):
        mgr = _make_manager()
        # session listed under the user but absent from active_connections → orphaned
        mgr.session_to_user[ "orphan" ] = "u-1"
        mgr.user_sessions[ "u-1" ]       = [ "orphan" ]
        result = _run( mgr.emit_to_user( "u-1", "job_update", {} ) )
        self.assertFalse( result )
        self.assertNotIn( "u-1", mgr.user_sessions )        # orphan cleaned → user emptied


class TestSyncEmitWrappers( unittest.TestCase ):
    """Thread-safe sync wrappers: emit / emit_to_user_sync / emit_to_session_sync / emit_to_admins_sync."""

    # ---- emit() ----
    def test_emit_no_loop_logs_and_returns( self ):
        mgr = _make_manager()
        mgr.emit( "evt", {} )                               # main_loop None → early return, no raise

    def test_emit_loop_not_running_returns( self ):
        mgr  = _make_manager()
        loop = MagicMock()
        loop.is_running.return_value = False
        mgr.main_loop = loop
        mgr.emit( "evt", {} )

    def test_emit_schedules_on_loop_debug_on( self ):
        mgr = _make_manager( app_debug=True )
        mgr.main_loop = _running_loop()
        # Patch the inner async method so no real coroutine object is created
        with patch.object( mgr, "_async_emit", MagicMock( return_value=MagicMock() ) ), \
             patch( "cosa.rest.websocket_manager.asyncio.run_coroutine_threadsafe" ) as rcts:
            mgr.emit( "job_update", {} )
        self.assertTrue( rcts.called )

    def test_emit_schedules_on_loop_debug_off( self ):
        mgr = _make_manager( app_debug=False )
        mgr.main_loop = _running_loop()
        with patch.object( mgr, "_async_emit", MagicMock( return_value=MagicMock() ) ), \
             patch( "cosa.rest.websocket_manager.asyncio.run_coroutine_threadsafe" ) as rcts:
            mgr.emit( "job_update", {} )
        self.assertTrue( rcts.called )

    def test_emit_schedule_exception_logged( self ):
        mgr = _make_manager()
        mgr.main_loop = _running_loop()
        with patch.object( mgr, "_async_emit", MagicMock( return_value=MagicMock() ) ), \
             patch( "cosa.rest.websocket_manager.asyncio.run_coroutine_threadsafe", side_effect=RuntimeError( "x" ) ):
            mgr.emit( "job_update", {} )                    # exception swallowed

    def test_async_emit_internal_wrapper( self ):
        mgr = _make_manager()
        ws  = _make_ws()
        mgr.connect( ws, "s-1" )
        _run( mgr._async_emit( "job_update", {} ) )         # delegates to async_emit
        ws.send_json.assert_awaited_once()

    # ---- emit_to_user_sync() ----
    def test_emit_to_user_sync_no_loop( self ):
        mgr = _make_manager()
        mgr.emit_to_user_sync( "u-1", "evt", {} )

    def test_emit_to_user_sync_loop_not_running( self ):
        mgr  = _make_manager()
        loop = MagicMock()
        loop.is_running.return_value = False
        mgr.main_loop = loop
        mgr.emit_to_user_sync( "u-1", "evt", {} )

    def test_emit_to_user_sync_schedules_with_email( self ):
        mgr = _make_manager()
        mgr.main_loop = _running_loop()
        mgr.connect( _make_ws(), "s-1", user_id="u-1", email="a@b.com" )
        with patch.object( mgr, "emit_to_user", MagicMock( return_value=MagicMock() ) ), \
             patch( "cosa.rest.websocket_manager.asyncio.run_coroutine_threadsafe" ) as rcts:
            mgr.emit_to_user_sync( "u-1", "job_update", {} )
        self.assertTrue( rcts.called )

    def test_emit_to_user_sync_schedule_exception( self ):
        mgr = _make_manager()
        mgr.main_loop = _running_loop()
        with patch.object( mgr, "emit_to_user", MagicMock( return_value=MagicMock() ) ), \
             patch( "cosa.rest.websocket_manager.asyncio.run_coroutine_threadsafe", side_effect=RuntimeError( "x" ) ):
            mgr.emit_to_user_sync( "u-1", "job_update", {} )

    # ---- emit_to_session_sync() ----
    def test_emit_to_session_sync_not_active_returns( self ):
        mgr = _make_manager()
        mgr.main_loop = _running_loop()
        mgr.emit_to_session_sync( "ghost", "evt", {} )      # not in active_connections → early return

    def test_emit_to_session_sync_no_loop( self ):
        mgr = _make_manager()
        mgr.connect( _make_ws(), "s-1" )
        mgr.main_loop = None
        mgr.emit_to_session_sync( "s-1", "evt", {} )

    def test_emit_to_session_sync_loop_not_running( self ):
        mgr  = _make_manager()
        mgr.connect( _make_ws(), "s-1" )
        loop = MagicMock()
        loop.is_running.return_value = False
        mgr.main_loop = loop
        mgr.emit_to_session_sync( "s-1", "evt", {} )

    def test_emit_to_session_sync_schedules( self ):
        mgr = _make_manager()
        mgr.connect( _make_ws(), "s-1" )
        mgr.main_loop = _running_loop()
        with patch.object( mgr, "emit_to_session", MagicMock( return_value=MagicMock() ) ), \
             patch( "cosa.rest.websocket_manager.asyncio.run_coroutine_threadsafe" ) as rcts:
            mgr.emit_to_session_sync( "s-1", "job_update", {} )
        self.assertTrue( rcts.called )

    def test_emit_to_session_sync_schedule_exception( self ):
        mgr = _make_manager()
        mgr.connect( _make_ws(), "s-1" )
        mgr.main_loop = _running_loop()
        with patch.object( mgr, "emit_to_session", MagicMock( return_value=MagicMock() ) ), \
             patch( "cosa.rest.websocket_manager.asyncio.run_coroutine_threadsafe", side_effect=RuntimeError( "x" ) ):
            mgr.emit_to_session_sync( "s-1", "job_update", {} )

    # ---- emit_to_admins_sync() ----
    def test_emit_to_admins_sync_no_loop_returns( self ):
        mgr = _make_manager()
        mgr.emit_to_admins_sync( "evt", {} )                # main_loop None → return

    def test_emit_to_admins_sync_delivers_to_admins_excluding_user( self ):
        mgr = _make_manager( app_debug=True )
        mgr.main_loop = _running_loop()
        mgr.connect( _make_ws(), "s-admin1", user_id="admin-1", email="a@x.com", roles=[ "admin" ] )
        mgr.connect( _make_ws(), "s-admin2", user_id="admin-2", roles=[ "admin" ] )
        mgr.connect( _make_ws(), "s-plain",  user_id="plain",   roles=[ "user" ] )
        with patch.object( mgr, "emit_to_user", MagicMock( return_value=MagicMock() ) ), \
             patch( "cosa.rest.websocket_manager.asyncio.run_coroutine_threadsafe" ) as rcts:
            mgr.emit_to_admins_sync( "job_update", {}, exclude_user_id="admin-2" )
        # admin-1 delivered, admin-2 excluded, plain skipped → exactly one schedule
        self.assertEqual( rcts.call_count, 1 )

    def test_emit_to_admins_sync_schedule_exception( self ):
        mgr = _make_manager()
        mgr.main_loop = _running_loop()
        mgr.connect( _make_ws(), "s-admin", user_id="admin-1", roles=[ "admin" ] )
        with patch.object( mgr, "emit_to_user", MagicMock( return_value=MagicMock() ) ), \
             patch( "cosa.rest.websocket_manager.asyncio.run_coroutine_threadsafe", side_effect=RuntimeError( "x" ) ):
            mgr.emit_to_admins_sync( "job_update", {} )

    def test_emit_to_admins_sync_session_without_user_skipped( self ):
        mgr = _make_manager()
        mgr.main_loop = _running_loop()
        # admin flag set but no user mapping → user_id None → not added
        mgr.session_is_admin[ "s-nouser" ] = True
        with patch( "cosa.rest.websocket_manager.asyncio.run_coroutine_threadsafe" ) as rcts:
            mgr.emit_to_admins_sync( "job_update", {} )
        self.assertEqual( rcts.call_count, 0 )

    # ---- emit_to_user_and_admins_sync() ----
    def test_emit_to_user_and_admins_sync_calls_both( self ):
        mgr = _make_manager()
        with patch.object( mgr, "emit_to_user_sync" ) as user_emit, \
             patch.object( mgr, "emit_to_admins_sync" ) as admin_emit:
            mgr.emit_to_user_and_admins_sync( "u-1", "job_update", { "k": 1 } )
        user_emit.assert_called_once_with( "u-1", "job_update", { "k": 1 } )
        admin_emit.assert_called_once_with( "job_update", { "k": 1 }, exclude_user_id="u-1" )


class TestEmitToUserOrListener( unittest.TestCase ):
    """emit_to_user_or_listener_sync(): user emit + cross-user CC-listener fallback."""

    def test_user_connected_listener_in_fanout( self ):
        mgr = _make_manager()
        mgr.main_loop = _running_loop()
        # listener session belongs to the same user → covered by user fan-out
        mgr.connect( _make_ws(), "u-sess", user_id="u-1" )
        mgr.connect( _make_ws(), "cc-listener-job1", user_id="u-1" )
        with patch.object( mgr, "emit_to_user_sync" ) as user_emit, \
             patch.object( mgr, "emit_to_session_sync" ) as sess_emit:
            result = mgr.emit_to_user_or_listener_sync( "u-1", "job1", "job_update", {} )
        user_emit.assert_called_once()
        sess_emit.assert_not_called()                       # already in fan-out → no duplicate
        self.assertTrue( result[ "user_delivered" ] )
        self.assertTrue( result[ "listener_delivered" ] )
        self.assertTrue( result[ "any_delivered" ] )

    def test_user_connected_listener_separate_session( self ):
        mgr = _make_manager()
        mgr.main_loop = _running_loop()
        mgr.connect( _make_ws(), "u-sess", user_id="u-1" )
        # listener owned by a different (service) user, present in active_connections
        mgr.connect( _make_ws(), "cc-listener-job2", user_id="svc" )
        with patch.object( mgr, "emit_to_user_sync" ) as user_emit, \
             patch.object( mgr, "emit_to_session_sync" ) as sess_emit:
            result = mgr.emit_to_user_or_listener_sync( "u-1", "job2", "job_update", {} )
        user_emit.assert_called_once()
        sess_emit.assert_called_once()                      # independent listener delivery
        self.assertTrue( result[ "user_delivered" ] )
        self.assertTrue( result[ "listener_delivered" ] )

    def test_user_emit_raises_caught( self ):
        mgr = _make_manager()
        mgr.main_loop = _running_loop()
        mgr.connect( _make_ws(), "u-sess", user_id="u-1" )
        with patch.object( mgr, "emit_to_user_sync", side_effect=RuntimeError( "boom" ) ):
            result = mgr.emit_to_user_or_listener_sync( "u-1", None, "job_update", {} )
        self.assertFalse( result[ "user_delivered" ] )
        self.assertFalse( result[ "any_delivered" ] )

    def test_user_not_connected_listener_only( self ):
        mgr = _make_manager()
        mgr.main_loop = _running_loop()
        mgr.connect( _make_ws(), "cc-listener-job3", user_id="svc" )
        with patch.object( mgr, "emit_to_session_sync" ) as sess_emit:
            result = mgr.emit_to_user_or_listener_sync( None, "job3", "job_update", {} )
        sess_emit.assert_called_once()
        self.assertFalse( result[ "user_delivered" ] )
        self.assertTrue( result[ "listener_delivered" ] )

    def test_listener_emit_raises_caught( self ):
        mgr = _make_manager()
        mgr.main_loop = _running_loop()
        mgr.connect( _make_ws(), "cc-listener-job4", user_id="svc" )
        with patch.object( mgr, "emit_to_session_sync", side_effect=RuntimeError( "boom" ) ):
            result = mgr.emit_to_user_or_listener_sync( None, "job4", "job_update", {} )
        self.assertFalse( result[ "listener_delivered" ] )
        self.assertFalse( result[ "any_delivered" ] )

    def test_no_user_no_job_all_false( self ):
        mgr = _make_manager()
        mgr.main_loop = _running_loop()
        result = mgr.emit_to_user_or_listener_sync( None, None, "job_update", {} )
        self.assertFalse( result[ "any_delivered" ] )

    def test_listener_not_in_active_connections( self ):
        mgr = _make_manager()
        mgr.main_loop = _running_loop()
        # job id provided but no matching cc-listener session active
        with patch.object( mgr, "emit_to_session_sync" ) as sess_emit:
            result = mgr.emit_to_user_or_listener_sync( None, "missing-job", "job_update", {} )
        sess_emit.assert_not_called()
        self.assertFalse( result[ "any_delivered" ] )


class TestInfoAndCleanup( unittest.TestCase ):
    """get_session_info / get_all_sessions_info / cleanup / heartbeat / auto_cleanup."""

    def test_get_session_info_none_when_absent( self ):
        mgr = _make_manager()
        self.assertIsNone( mgr.get_session_info( "ghost" ) )

    def test_get_session_info_with_duration( self ):
        mgr = _make_manager()
        mgr.connect( _make_ws(), "s-1", user_id="u-1" )
        info = mgr.get_session_info( "s-1" )
        self.assertEqual( info[ "session_id" ], "s-1" )
        self.assertTrue( info[ "connected" ] )
        self.assertEqual( info[ "user_id" ], "u-1" )
        self.assertIsNotNone( info[ "connected_at" ] )
        self.assertIn( "duration_seconds", info )

    def test_get_session_info_no_timestamp_branch( self ):
        mgr = _make_manager()
        mgr.connect( _make_ws(), "s-1" )
        del mgr.session_timestamps[ "s-1" ]                 # active but no timestamp → connected_at None, no duration
        info = mgr.get_session_info( "s-1" )
        self.assertIsNone( info[ "connected_at" ] )
        self.assertNotIn( "duration_seconds", info )

    def test_get_all_sessions_info_collects( self ):
        mgr = _make_manager()
        mgr.connect( _make_ws(), "s-1" )
        mgr.connect( _make_ws(), "s-2" )
        infos = mgr.get_all_sessions_info()
        self.assertEqual( len( infos ), 2 )

    def test_get_all_sessions_info_skips_falsy_info( self ):
        mgr = _make_manager()
        mgr.connect( _make_ws(), "s-1" )
        # Force the defensive `if info:` false branch via a patched get_session_info
        with patch.object( mgr, "get_session_info", return_value=None ):
            infos = mgr.get_all_sessions_info()
        self.assertEqual( infos, [] )

    def test_cleanup_stale_sessions_removes_old( self ):
        mgr = _make_manager()
        mgr.set_event_loop( _running_loop() )
        mgr.connect( _make_ws(), "old", user_id="u-1" )
        mgr.connect( _make_ws(), "fresh", user_id="u-2" )
        mgr.session_timestamps[ "old" ] = datetime.now() - timedelta( hours=48 )
        with patch( "cosa.rest.websocket_manager.asyncio.run_coroutine_threadsafe", side_effect=_fake_rcts ):
            removed = mgr.cleanup_stale_sessions( max_age_hours=24 )
        self.assertEqual( removed, 1 )
        self.assertNotIn( "old", mgr.active_connections )
        self.assertIn( "fresh", mgr.active_connections )

    def test_cleanup_stale_sessions_none_stale( self ):
        mgr = _make_manager()
        mgr.connect( _make_ws(), "fresh", user_id="u-1" )
        self.assertEqual( mgr.cleanup_stale_sessions( max_age_hours=24 ), 0 )

    def test_heartbeat_check_disabled_returns_zero( self ):
        mgr = _make_manager( heartbeat_enabled=False )
        self.assertEqual( _run( mgr.heartbeat_check() ), 0 )

    def test_heartbeat_check_pings_and_removes_dead( self ):
        mgr = _make_manager( heartbeat_enabled=True )
        good = _make_ws()
        dead = _make_ws()
        dead.send_json.side_effect = RuntimeError( "dead" )
        mgr.connect( good, "good", user_id="u-1" )
        mgr.connect( dead, "dead", user_id="u-2" )
        removed = _run( mgr.heartbeat_check() )
        self.assertEqual( removed, 1 )
        self.assertNotIn( "dead", mgr.active_connections )
        self.assertIn( "good", mgr.active_connections )

    def test_heartbeat_check_all_alive_no_removal( self ):
        mgr = _make_manager( heartbeat_enabled=True )
        mgr.connect( _make_ws(), "good", user_id="u-1" )
        self.assertEqual( _run( mgr.heartbeat_check() ), 0 )

    def test_auto_cleanup_disabled_returns_zero( self ):
        mgr = _make_manager( cleanup_enabled=False )
        self.assertEqual( _run( mgr.auto_cleanup() ), 0 )

    def test_auto_cleanup_runs_and_reports( self ):
        mgr = _make_manager( cleanup_enabled=True, max_age_hours=24 )
        mgr.connect( _make_ws(), "old", user_id="u-1" )
        mgr.session_timestamps[ "old" ] = datetime.now() - timedelta( hours=48 )
        cleaned = _run( mgr.auto_cleanup() )
        self.assertEqual( cleaned, 1 )

    def test_auto_cleanup_nothing_to_clean( self ):
        mgr = _make_manager( cleanup_enabled=True )
        mgr.connect( _make_ws(), "fresh", user_id="u-1" )
        self.assertEqual( _run( mgr.auto_cleanup() ), 0 )


class TestSubscriptions( unittest.TestCase ):
    """update_subscriptions + get_subscription_stats."""

    def test_update_subscriptions_unknown_session_false( self ):
        mgr = _make_manager()
        self.assertFalse( mgr.update_subscriptions( "ghost", [ "job_update" ] ) )

    def test_update_subscriptions_replace( self ):
        mgr = _make_manager()
        mgr.connect( _make_ws(), "s-1", subscribed_events=[ "*" ] )
        ok = mgr.update_subscriptions( "s-1", [ "job_update", "bogus" ], action="replace" )
        self.assertTrue( ok )
        self.assertEqual( mgr.session_subscriptions[ "s-1" ], [ "job_update" ] )

    def test_update_subscriptions_add_no_dup( self ):
        mgr = _make_manager()
        mgr.connect( _make_ws(), "s-1", subscribed_events=[ "job_update" ] )
        mgr.update_subscriptions( "s-1", [ "job_update", "audio_update" ], action="add" )
        self.assertEqual( set( mgr.session_subscriptions[ "s-1" ] ), { "job_update", "audio_update" } )

    def test_update_subscriptions_remove( self ):
        mgr = _make_manager()
        mgr.connect( _make_ws(), "s-1", subscribed_events=[ "job_update", "audio_update" ] )
        mgr.update_subscriptions( "s-1", [ "job_update" ], action="remove" )
        self.assertEqual( mgr.session_subscriptions[ "s-1" ], [ "audio_update" ] )

    def test_update_subscriptions_unknown_action_falls_through( self ):
        mgr = _make_manager()
        mgr.connect( _make_ws(), "s-1", subscribed_events=[ "job_update" ] )
        # action not in {replace, add, remove} → all elifs false (1074->1078); subs unchanged, returns True
        ok = mgr.update_subscriptions( "s-1", [ "audio_update" ], action="noop" )
        self.assertTrue( ok )
        self.assertEqual( mgr.session_subscriptions[ "s-1" ], [ "job_update" ] )

    def test_get_subscription_stats( self ):
        mgr = _make_manager()
        mgr.connect( _make_ws(), "s-wild", subscribed_events=[ "*" ] )
        mgr.connect( _make_ws(), "s-filt", subscribed_events=[ "job_update", "audio_update" ] )
        stats = mgr.get_subscription_stats()
        self.assertEqual( stats[ "total_connections" ], 2 )
        self.assertEqual( stats[ "wildcard_subscribers" ], 1 )
        self.assertEqual( stats[ "filtered_connections" ], 1 )
        self.assertEqual( stats[ "subscription_counts" ][ "job_update" ], 1 )
        self.assertEqual( stats[ "subscription_counts" ][ "audio_update" ], 1 )


if __name__ == "__main__":
    unittest.main()
