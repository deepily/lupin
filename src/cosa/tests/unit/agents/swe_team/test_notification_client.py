"""
Unit tests for swe_team/notification_client.py — OrchestratorNotificationClient:
  - __init__   : session_id formatting + shared queue/event wiring
  - _login     : in-process JWT generation (success / user-not-found / exception)
  - _on_event  : filter + queue + urgent-interrupt logic
  - start      : daemon-thread spawn running self.run() (success + except arc)
  - stop_sync  : ws-close + thread-join (ws present/None, alive/not, exception)

The base WebSocket listener never connects on construction. JWT-service imports
inside _login are injected via sys.modules; self.run is mocked. NO real
network/WS/DB/JWT/LLM. Threads are joined so their bodies are measured.

Created 2026-05-31 by Extra 1 🪨 (CoSA coverage campaign, swe_team lane, mid tier).
"""

import asyncio
import queue
import sys
import threading
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import cosa.agents.swe_team.notification_client as nc


def _make_client( debug=False ):
    return nc.OrchestratorNotificationClient(
        user_email    = "u@x.ai",
        job_id        = "swe-abc",
        message_queue = queue.Queue(),
        urgent_event  = threading.Event(),
        debug         = debug,
    )


class TestInit( unittest.TestCase ):

    def test_session_id_and_wiring( self ):
        c = _make_client()
        self.assertEqual( c.session_id, "swe-notif-swe-abc" )
        self.assertEqual( c._target_job_id, "swe-abc" )
        self.assertIsInstance( c._message_queue, queue.Queue )
        self.assertIsNone( c._thread )


class TestLogin( unittest.TestCase ):

    def _patched_jwt_modules( self, user=MagicMock(), token="TKN" ):
        """Inject fake jwt_service / db modules so _login's late imports resolve."""
        jwt_mod = MagicMock()
        jwt_mod.create_access_token = MagicMock( return_value=token )

        db_mod = MagicMock()
        ctx = MagicMock()
        ctx.__enter__ = MagicMock( return_value=MagicMock() )
        ctx.__exit__  = MagicMock( return_value=False )
        db_mod.get_db = MagicMock( return_value=ctx )

        repo_mod = MagicMock()
        repo_instance = MagicMock()
        repo_instance.get_by_email = MagicMock( return_value=user )
        repo_mod.UserRepository = MagicMock( return_value=repo_instance )

        return {
            "cosa.rest.jwt_service"                      : jwt_mod,
            "cosa.rest.db.database"                      : db_mod,
            "cosa.rest.db.repositories.user_repository"  : repo_mod,
        }, jwt_mod

    def test_login_success_returns_token( self ):
        user = MagicMock( id=7, roles=[ "admin" ] )
        mods, jwt_mod = self._patched_jwt_modules( user=user, token="JWT123" )
        c = _make_client( debug=True )
        with patch.dict( sys.modules, mods ):
            tok = c._login()
        self.assertEqual( tok, "JWT123" )
        jwt_mod.create_access_token.assert_called_once()
        self.assertEqual( jwt_mod.create_access_token.call_args.kwargs[ "roles" ], [ "admin" ] )

    def test_login_user_without_roles_defaults_to_user( self ):
        user = MagicMock( id=1, roles=None )    # `user.roles or ["user"]` → ["user"]
        mods, jwt_mod = self._patched_jwt_modules( user=user, token="T" )
        c = _make_client()
        with patch.dict( sys.modules, mods ):
            c._login()
        self.assertEqual( jwt_mod.create_access_token.call_args.kwargs[ "roles" ], [ "user" ] )

    def test_login_user_not_found_returns_none( self ):
        mods, _ = self._patched_jwt_modules( user=None )
        c = _make_client()
        with patch.dict( sys.modules, mods ):
            self.assertIsNone( c._login() )

    def test_login_exception_returns_none( self ):
        jwt_mod = MagicMock()
        jwt_mod.create_access_token = MagicMock()
        db_mod = MagicMock()
        db_mod.get_db = MagicMock( side_effect=RuntimeError( "db down" ) )
        repo_mod = MagicMock()
        mods = {
            "cosa.rest.jwt_service"                     : jwt_mod,
            "cosa.rest.db.database"                     : db_mod,
            "cosa.rest.db.repositories.user_repository" : repo_mod,
        }
        c = _make_client()
        with patch.dict( sys.modules, mods ):
            self.assertIsNone( c._login() )


class TestOnEvent( unittest.TestCase ):

    def test_non_notification_event_ignored( self ):
        c = _make_client()
        asyncio.run( c._on_event( "job_state_transition", { "job_id": "swe-abc" } ) )
        self.assertTrue( c._message_queue.empty() )

    def test_matching_message_queued( self ):
        c = _make_client()
        asyncio.run( c._on_event( "notification_queue_update", { "notification": {
            "type": "user_initiated_message", "job_id": "swe-abc",
            "message": "use auth module", "priority": "normal",
        } } ) )
        msg = c._message_queue.get_nowait()
        self.assertEqual( msg[ "message" ], "use auth module" )

    def test_notification_type_fallback_key( self ):
        # `notification.get("type") or notification.get("notification_type")`:
        # type absent → fallback to notification_type.
        c = _make_client()
        asyncio.run( c._on_event( "notification_queue_update", { "notification": {
            "notification_type": "user_initiated_message", "job_id": "swe-abc",
            "message": "via fallback key", "priority": "normal",
        } } ) )
        self.assertFalse( c._message_queue.empty() )

    def test_wrong_type_ignored( self ):
        c = _make_client()
        asyncio.run( c._on_event( "notification_queue_update", { "notification": {
            "type": "progress", "job_id": "swe-abc", "message": "x",
        } } ) )
        self.assertTrue( c._message_queue.empty() )

    def test_wrong_job_id_ignored_debug_on( self ):
        c = _make_client( debug=True )   # exercises the debug-print arc
        asyncio.run( c._on_event( "notification_queue_update", { "notification": {
            "type": "user_initiated_message", "job_id": "other-job", "message": "x",
        } } ) )
        self.assertTrue( c._message_queue.empty() )

    def test_wrong_job_id_ignored_debug_off( self ):
        c = _make_client( debug=False )   # 189->191 debug-skip arc
        asyncio.run( c._on_event( "notification_queue_update", { "notification": {
            "type": "user_initiated_message", "job_id": "other-job", "message": "x",
        } } ) )
        self.assertTrue( c._message_queue.empty() )

    def test_urgent_sets_event_debug_on( self ):
        c = _make_client( debug=True )
        asyncio.run( c._on_event( "notification_queue_update", { "notification": {
            "type": "user_initiated_message", "job_id": "swe-abc",
            "message": "STOP", "priority": "urgent",
        } } ) )
        self.assertTrue( c._urgent_event.is_set() )
        self.assertFalse( c._message_queue.empty() )

    def test_urgent_sets_event_debug_off( self ):
        c = _make_client( debug=False )   # 212->exit debug-skip arc
        asyncio.run( c._on_event( "notification_queue_update", { "notification": {
            "type": "user_initiated_message", "job_id": "swe-abc",
            "message": "STOP", "priority": "urgent",
        } } ) )
        self.assertTrue( c._urgent_event.is_set() )


class TestStart( unittest.TestCase ):

    def test_start_spawns_daemon_thread_running_run( self ):
        c = _make_client( debug=True )
        with patch.object( c, "run", AsyncMock( return_value=None ) ):
            c.start()
            c._thread.join( timeout=5 )
        self.assertIsNotNone( c._thread )
        self.assertFalse( c._thread.is_alive() )

    def test_start_loop_exception_is_logged( self ):
        c = _make_client()
        with patch.object( c, "run", AsyncMock( side_effect=RuntimeError( "loop boom" ) ) ):
            c.start()
            c._thread.join( timeout=5 )
        self.assertFalse( c._thread.is_alive() )   # finally: loop.close() still ran


class TestStopSync( unittest.TestCase ):

    def test_stop_sync_with_ws_and_live_thread( self ):
        c = _make_client( debug=True )
        c._ws = MagicMock()
        c._ws.close = AsyncMock()
        # Mock a still-alive thread so the join + debug-print block (269-271) runs
        # deterministically without a real blocked thread.
        c._thread = MagicMock()
        c._thread.is_alive.return_value = True
        c.stop_sync()
        self.assertFalse( c._running )
        self.assertFalse( c._connected )
        c._thread.join.assert_called_once_with( timeout=5.0 )

    def test_stop_sync_live_thread_debug_off( self ):
        # 270->exit: live thread joined but debug False → skip the print.
        c = _make_client( debug=False )
        c._ws = None
        c._thread = MagicMock()
        c._thread.is_alive.return_value = True
        c.stop_sync()
        c._thread.join.assert_called_once_with( timeout=5.0 )

    def test_stop_sync_ws_close_exception_swallowed( self ):
        c = _make_client()
        c._ws = MagicMock()
        c._ws.close = AsyncMock( side_effect=RuntimeError( "ws boom" ) )
        c._thread = None
        c.stop_sync()   # must not raise

    def test_stop_sync_no_ws_no_thread( self ):
        c = _make_client()
        c._ws = None
        c._thread = None
        c.stop_sync()   # both guards false


if __name__ == "__main__":
    unittest.main()
