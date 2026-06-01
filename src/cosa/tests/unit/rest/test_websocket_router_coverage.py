#!/usr/bin/env python3
"""
Supplemental unit tests — `cosa.rest.routers.websocket` coverage closure.

Complements `test_websocket_router.py`. The pre-existing tests patched
`verify_firebase_token` (NOT the symbol the live code imports — it uses
`verify_token`), so the successful-auth path and the full queue-endpoint
validation matrix were never exercised. This file closes that gap:

    websocket_audio_endpoint:
        - pre-registered-user connect + app_debug branch,
        - in-loop auth_request handling (Bearer strip, success state updates
          with/without email, verify failure → auth_error),
        - sys_ping → sys_pong, malformed-JSON in-loop exception → break,
        - finally: disconnect-when-our-socket vs skip-when-replaced.
    websocket_queue_endpoint:
        - invalid session id → 1008 close,
        - the full auth-validation matrix (JSONDecodeError / disconnect-during-auth
          / parse-exception / not-a-dict / wrong-type / missing-token /
          non-string-token / empty-token),
        - successful verify_token → connect → auth_success,
        - TokenExpiredException + generic verify failure,
        - the outer defensive handlers,
        - post-auth message loop (sys_ping, update_subscriptions, disconnect,
          generic error) + finally disconnect/skip arms.

Boundary-mock discipline: `cosa.rest.auth.verify_token` is patched (AsyncMock —
no real JWT/Firebase); the WebSocket is an AsyncMock with scripted side-effects;
the manager is a Mock with real dict attributes. ZERO network, ZERO real socket.

Run: PYTHONPATH=src:src/cosa/tests/unit/infrastructure \
     src/cosa/.venv/bin/python -m pytest \
     src/cosa/tests/unit/rest/test_websocket_router_coverage.py -v
"""

import sys
import json
import unittest
from unittest.mock import Mock, AsyncMock, patch

from fastapi import WebSocketDisconnect

from cosa.rest.routers.websocket import (
    websocket_audio_endpoint,
    websocket_queue_endpoint,
    is_valid_session_id,
    CLOSE_CODE_AUTH_INVALID_TOKEN,
)
from cosa.rest.auth import TokenExpiredException

_TS = "2026-01-01T12:00:00"
_SID = "wise penguin"


def _patch_fastapi_main( mock_main ):
    """G1 DUAL-KEY patch (see test_websocket_router._patch_fastapi_main)."""
    pkg      = Mock()
    pkg.main = mock_main
    return patch.dict( sys.modules, { "fastapi_app": pkg, "fastapi_app.main": mock_main } )


def _mgr():
    """A WebSocket manager mock with real dict state the endpoints mutate."""
    m = Mock()
    m.session_to_user        = {}
    m.user_sessions          = {}
    m.user_to_email          = {}
    m.session_subscriptions  = {}
    m.available_events       = [ "audio_streaming_status", "audio_streaming_complete", "sys_ping", "queue_update" ]
    m.active_connections     = {}
    m.connect                = Mock()
    m.disconnect             = Mock()
    m.is_user_connected      = Mock( return_value=True )
    m.get_user_connection_count = Mock( return_value=1 )
    m.update_subscriptions   = Mock( return_value=True )
    return m


def _ws():
    ws = AsyncMock()
    ws.accept       = AsyncMock()
    ws.close        = AsyncMock()
    ws.send_json    = AsyncMock()
    ws.receive_text = AsyncMock()
    ws.receive_json = AsyncMock()
    return ws


def _main( manager, debug=True, verbose=True, active_tasks=None ):
    m = Mock()
    m.websocket_manager = manager
    m.active_tasks      = active_tasks if active_tasks is not None else {}
    m.app_debug         = debug
    m.app_verbose       = verbose
    return m


# ───────────────────────── audio endpoint ─────────────────────────
class TestAudioEndpoint( unittest.IsolatedAsyncioTestCase ):
    """
    Exercises websocket_audio_endpoint message-loop + lifecycle paths.

    Ensures:
        - pre-registered user → user-associated connect + debug print
        - in-loop auth_request: Bearer strip, success state updates, verify failure
        - sys_ping → sys_pong; malformed JSON → in-loop exception break
        - finally block disconnects only when our socket is still active
    """

    async def test_preregistered_auth_success_and_ping( self ):
        mgr = _mgr()
        mgr.session_to_user[ _SID ] = "preuser"        # pre-registered → 212-214
        ws  = _ws()
        mgr.active_connections[ _SID ] = ws            # finally: our socket → disconnect
        auth_msg = json.dumps( { "type": "auth_request", "token": "Bearer tok", "subscribed_events": [ "*" ] } )
        ping_msg = json.dumps( { "type": "sys_ping" } )
        ws.receive_text.side_effect = [ auth_msg, ping_msg, WebSocketDisconnect() ]
        with _patch_fastapi_main( _main( mgr ) ), \
             patch( "cosa.rest.auth.verify_token", new=AsyncMock(
                 return_value={ "uid": "u9", "email": "u9@x.com" } ) ), \
             patch( "cosa.utils.util.get_current_datetime_iso", return_value=_TS ), \
             patch( "builtins.print" ):
            await websocket_audio_endpoint( websocket=ws, session_id=_SID )
        # success state updates applied
        self.assertEqual( mgr.session_to_user[ _SID ], "u9" )
        self.assertIn( "u9", mgr.user_sessions )
        self.assertEqual( mgr.user_to_email[ "u9" ], "u9@x.com" )
        # auth_success + sys_pong both sent
        types = [ c.args[ 0 ].get( "type" ) for c in ws.send_json.call_args_list ]
        self.assertIn( "auth_success", types )
        self.assertIn( "sys_pong", types )
        mgr.disconnect.assert_called_once_with( _SID )

    async def test_auth_no_email_and_existing_user_session( self ):
        mgr = _mgr()
        mgr.user_sessions[ "u9" ] = [ _SID ]           # already present → no append
        ws  = _ws()
        auth_msg = json.dumps( { "type": "auth_request", "token": "tok" } )   # no Bearer, no subscribed_events
        ws.receive_text.side_effect = [ auth_msg, WebSocketDisconnect() ]
        with _patch_fastapi_main( _main( mgr, debug=False, verbose=False ) ), \
             patch( "cosa.rest.auth.verify_token", new=AsyncMock(
                 return_value={ "uid": "u9" } ) ), \
             patch( "builtins.print" ):
            await websocket_audio_endpoint( websocket=ws, session_id=_SID )
        # email absent → user_to_email NOT populated
        self.assertNotIn( "u9", mgr.user_to_email )

    async def test_auth_failure_emits_auth_error( self ):
        mgr = _mgr()
        ws  = _ws()
        auth_msg = json.dumps( { "type": "auth_request", "token": "bad" } )
        ws.receive_text.side_effect = [ auth_msg, WebSocketDisconnect() ]
        with _patch_fastapi_main( _main( mgr ) ), \
             patch( "cosa.rest.auth.verify_token", new=AsyncMock( side_effect=Exception( "nope" ) ) ), \
             patch( "builtins.print" ):
            await websocket_audio_endpoint( websocket=ws, session_id=_SID )
        types = [ c.args[ 0 ].get( "type" ) for c in ws.send_json.call_args_list ]
        self.assertIn( "auth_error", types )

    async def test_malformed_json_in_loop_breaks( self ):
        mgr = _mgr()
        ws  = _ws()
        ws.receive_text.side_effect = [ "not-json{", WebSocketDisconnect() ]
        with _patch_fastapi_main( _main( mgr ) ), \
             patch( "builtins.print" ):
            await websocket_audio_endpoint( websocket=ws, session_id=_SID )
        # connection confirmation was sent; loop broke on the JSON error
        self.assertTrue( ws.send_json.called )

    async def test_malformed_json_in_loop_debug_off( self ):
        # debug=False → the in-loop except's `if app_debug` FALSE arm (no print)
        mgr = _mgr()
        ws  = _ws()
        ws.receive_text.side_effect = [ "not-json{", ]
        with _patch_fastapi_main( _main( mgr, debug=False, verbose=False ) ), \
             patch( "builtins.print" ):
            await websocket_audio_endpoint( websocket=ws, session_id=_SID )
        self.assertTrue( ws.send_json.called )

    async def test_unknown_message_type_falls_through( self ):
        # a message that is neither auth_request nor sys_ping → loop fall-through
        mgr = _mgr()
        ws  = _ws()
        other = json.dumps( { "type": "something_else" } )
        ws.receive_text.side_effect = [ other, WebSocketDisconnect() ]
        with _patch_fastapi_main( _main( mgr ) ), patch( "builtins.print" ):
            await websocket_audio_endpoint( websocket=ws, session_id=_SID )
        self.assertTrue( ws.send_json.called )   # only the confirmation

    async def test_confirmation_send_disconnect( self ):
        # the connection-confirmation send_json raises WebSocketDisconnect →
        # the OUTER `except WebSocketDisconnect: pass` arm (before the loop)
        mgr = _mgr()
        ws  = _ws()
        ws.send_json.side_effect = WebSocketDisconnect()
        with _patch_fastapi_main( _main( mgr ) ), patch( "builtins.print" ):
            await websocket_audio_endpoint( websocket=ws, session_id=_SID )
        # reached finally without raising

    async def test_finally_skips_disconnect_when_replaced( self ):
        mgr = _mgr()
        ws  = _ws()
        mgr.active_connections[ _SID ] = object()      # a DIFFERENT socket → skip disconnect
        ws.receive_text.side_effect = [ WebSocketDisconnect() ]
        with _patch_fastapi_main( _main( mgr, debug=False, verbose=False ) ), \
             patch( "builtins.print" ):
            await websocket_audio_endpoint( websocket=ws, session_id=_SID )
        mgr.disconnect.assert_not_called()

    async def test_invalid_session_rejected( self ):
        mgr = _mgr()
        ws  = _ws()
        with _patch_fastapi_main( _main( mgr ) ), patch( "builtins.print" ):
            await websocket_audio_endpoint( websocket=ws, session_id="bad\tsession" )
        ws.close.assert_awaited_once_with( code=1008, reason="Invalid session ID format" )
        ws.accept.assert_not_called()


# ───────────────────────── queue endpoint ─────────────────────────
class TestQueueEndpointValidation( unittest.IsolatedAsyncioTestCase ):
    """
    Exercises the queue endpoint auth-validation matrix (all reject arms).

    Ensures each malformed-auth condition emits an auth_error and closes with
    CLOSE_CODE_AUTH_INVALID_TOKEN, and that disconnect/parse exceptions return.
    """

    async def _run( self, recv_json, main=None ):
        mgr = _mgr()
        ws  = _ws()
        if isinstance( recv_json, list ):
            ws.receive_json.side_effect = recv_json
        else:
            ws.receive_json.return_value = recv_json
        with _patch_fastapi_main( main or _main( mgr ) ), \
             patch( "cosa.utils.util.get_current_datetime_iso", return_value=_TS ), \
             patch( "builtins.print" ):
            await websocket_queue_endpoint( websocket=ws, session_id=_SID )
        return ws

    async def test_invalid_session_rejected( self ):
        mgr = _mgr()
        ws  = _ws()
        with _patch_fastapi_main( _main( mgr ) ), patch( "builtins.print" ):
            await websocket_queue_endpoint( websocket=ws, session_id="bad\nid" )
        ws.close.assert_awaited_once_with( code=1008, reason="Invalid session ID format" )

    async def test_json_decode_error( self ):
        ws = await self._run( [ json.JSONDecodeError( "x", "doc", 0 ) ] )
        ws.close.assert_awaited_with( code=CLOSE_CODE_AUTH_INVALID_TOKEN, reason="invalid_auth_request_json" )

    async def test_disconnect_during_auth( self ):
        ws = await self._run( [ WebSocketDisconnect( code=1006 ) ] )
        ws.close.assert_not_awaited()      # disconnect → just return, no close

    async def test_parse_exception( self ):
        ws = await self._run( [ ValueError( "weird" ) ] )
        ws.close.assert_awaited_with( code=CLOSE_CODE_AUTH_INVALID_TOKEN, reason="invalid_auth_request" )

    # NOTE: the `if not isinstance(auth_message, dict)` shape-check branch
    # (router lines 388-395) is UNREACHABLE: line 363's unconditional
    # `auth_message.get('type')` raises AttributeError for ANY non-dict
    # (receive_json only yields dict/list/scalar; only dict has .get), so a
    # non-dict is diverted to the parse-exception branch BEFORE this check.
    # Flagged to manager as a new-author pragma proposal (contract proof = L363).

    async def test_wrong_type( self ):
        ws = await self._run( { "type": "not_auth" } )
        ws.close.assert_awaited_with( code=CLOSE_CODE_AUTH_INVALID_TOKEN, reason="auth_protocol_violation" )

    async def test_missing_token( self ):
        ws = await self._run( { "type": "auth_request" } )
        ws.close.assert_awaited_with( code=CLOSE_CODE_AUTH_INVALID_TOKEN, reason="missing_token" )

    async def test_non_string_token( self ):
        ws = await self._run( { "type": "auth_request", "token": 12345 } )
        ws.close.assert_awaited_with( code=CLOSE_CODE_AUTH_INVALID_TOKEN, reason="invalid_token_type" )

    async def test_empty_token( self ):
        ws = await self._run( { "type": "auth_request", "token": "   " } )
        ws.close.assert_awaited_with( code=CLOSE_CODE_AUTH_INVALID_TOKEN, reason="empty_token" )

    async def test_parse_exception_send_also_fails( self ):
        # generic parse exception AND the error-response send_json also fails →
        # the inner `except Exception: pass` (socket already closed) arm.
        mgr = _mgr()
        ws  = _ws()
        ws.receive_json.side_effect = [ ValueError( "weird" ) ]
        ws.send_json.side_effect    = Exception( "socket dead" )
        with _patch_fastapi_main( _main( mgr ) ), patch( "builtins.print" ):
            await websocket_queue_endpoint( websocket=ws, session_id=_SID )
        # reached here without raising → defensive arm covered


class TestQueueEndpointAuthOutcomes( unittest.IsolatedAsyncioTestCase ):
    """
    Exercises the queue endpoint verify_token outcomes + post-auth loop.

    Ensures:
        - successful verify → connect + auth_success, then loop handles
          sys_ping / update_subscriptions / disconnect / generic error
        - TokenExpiredException and generic verify failure each close 4001
        - the outer defensive handlers (TokenExpired + generic) are exercised
        - finally disconnects only when our socket is still active
    """

    async def test_success_then_ping_subs_disconnect( self ):
        mgr = _mgr()
        ws  = _ws()
        mgr.active_connections[ _SID ] = ws
        auth = { "type": "auth_request", "token": "Bearer good", "subscribed_events": [ "*" ] }
        ws.receive_json.return_value = auth
        ping = json.dumps( { "type": "sys_ping" } )
        subs = json.dumps( { "type": "update_subscriptions", "events": [ "queue_update" ], "action": "add" } )
        ws.receive_text.side_effect = [ ping, subs, WebSocketDisconnect() ]
        with _patch_fastapi_main( _main( mgr ) ), \
             patch( "cosa.rest.auth.verify_token", new=AsyncMock(
                 return_value={ "uid": "u1", "email": "u1@x.com", "roles": [ "user" ] } ) ), \
             patch( "cosa.utils.util.get_current_datetime_iso", return_value=_TS ), \
             patch( "builtins.print" ):
            await websocket_queue_endpoint( websocket=ws, session_id=_SID )
        mgr.connect.assert_called_once()
        types = [ c.args[ 0 ].get( "type" ) for c in ws.send_json.call_args_list ]
        self.assertIn( "auth_success", types )
        self.assertIn( "sys_pong", types )
        self.assertIn( "subscription_update", types )
        mgr.disconnect.assert_called_once_with( _SID )

    async def test_unknown_message_type_falls_through( self ):
        # post-auth: a message that is neither sys_ping nor update_subscriptions
        mgr = _mgr()
        ws  = _ws()
        ws.receive_json.return_value = { "type": "auth_request", "token": "good" }
        other = json.dumps( { "type": "noop" } )
        ws.receive_text.side_effect = [ other, WebSocketDisconnect() ]
        with _patch_fastapi_main( _main( mgr ) ), \
             patch( "cosa.rest.auth.verify_token", new=AsyncMock( return_value={ "uid": "u1" } ) ), \
             patch( "cosa.utils.util.get_current_datetime_iso", return_value=_TS ), \
             patch( "builtins.print" ):
            await websocket_queue_endpoint( websocket=ws, session_id=_SID )
        types = [ c.args[ 0 ].get( "type" ) for c in ws.send_json.call_args_list ]
        self.assertIn( "auth_success", types )

    async def test_confirmation_send_disconnect( self ):
        # auth_success sends ok, then the connection-confirmation send_json raises
        # WebSocketDisconnect → the OUTER `except WebSocketDisconnect: pass` arm
        mgr = _mgr()
        ws  = _ws()
        ws.receive_json.return_value = { "type": "auth_request", "token": "good" }
        ws.send_json.side_effect = [ None, WebSocketDisconnect() ]   # auth_success ok, confirmation raises
        with _patch_fastapi_main( _main( mgr ) ), \
             patch( "cosa.rest.auth.verify_token", new=AsyncMock( return_value={ "uid": "u1" } ) ), \
             patch( "cosa.utils.util.get_current_datetime_iso", return_value=_TS ), \
             patch( "builtins.print" ):
            await websocket_queue_endpoint( websocket=ws, session_id=_SID )
        # reached finally without raising

    async def test_loop_generic_error_breaks( self ):
        mgr = _mgr()
        ws  = _ws()
        auth = { "type": "auth_request", "token": "good" }
        ws.receive_json.return_value = auth
        # non-JSON text → json.loads raises → generic except → break
        ws.receive_text.side_effect = [ "not json", ]
        with _patch_fastapi_main( _main( mgr ) ), \
             patch( "cosa.rest.auth.verify_token", new=AsyncMock( return_value={ "uid": "u1" } ) ), \
             patch( "cosa.utils.util.get_current_datetime_iso", return_value=_TS ), \
             patch( "builtins.print" ):
            await websocket_queue_endpoint( websocket=ws, session_id=_SID )
        # finally ran; our socket not registered → skip disconnect
        mgr.disconnect.assert_not_called()

    async def test_token_expired_inner( self ):
        mgr = _mgr()
        ws  = _ws()
        ws.receive_json.return_value = { "type": "auth_request", "token": "good" }
        with _patch_fastapi_main( _main( mgr ) ), \
             patch( "cosa.rest.auth.verify_token", new=AsyncMock( side_effect=TokenExpiredException() ) ), \
             patch( "builtins.print" ):
            await websocket_queue_endpoint( websocket=ws, session_id=_SID )
        ws.close.assert_awaited_with( code=CLOSE_CODE_AUTH_INVALID_TOKEN, reason="token_expired" )

    async def test_generic_verify_failure_inner( self ):
        mgr = _mgr()
        ws  = _ws()
        ws.receive_json.return_value = { "type": "auth_request", "token": "good" }
        with _patch_fastapi_main( _main( mgr ) ), \
             patch( "cosa.rest.auth.verify_token", new=AsyncMock( side_effect=Exception( "bad token" ) ) ), \
             patch( "builtins.print" ):
            await websocket_queue_endpoint( websocket=ws, session_id=_SID )
        ws.close.assert_awaited_with( code=CLOSE_CODE_AUTH_INVALID_TOKEN, reason="invalid_token" )

    async def test_outer_token_expired_handler( self ):
        # A validation-branch send_json raises TokenExpiredException → the OUTER
        # defensive TokenExpiredException handler closes the socket (4001).
        mgr = _mgr()
        ws  = _ws()
        ws.receive_json.return_value = { "type": "wrong" }    # → validation send_json path
        ws.send_json.side_effect = TokenExpiredException()
        with _patch_fastapi_main( _main( mgr ) ), patch( "builtins.print" ):
            await websocket_queue_endpoint( websocket=ws, session_id=_SID )
        ws.close.assert_awaited_with( code=CLOSE_CODE_AUTH_INVALID_TOKEN, reason="token_expired" )

    async def test_outer_generic_handler( self ):
        # A validation-branch send_json raises a generic Exception → the OUTER
        # generic handler attempts a close (4001, reason auth_error).
        mgr = _mgr()
        ws  = _ws()
        ws.receive_json.return_value = { "type": "wrong" }
        ws.send_json.side_effect = RuntimeError( "boom mid-send" )
        with _patch_fastapi_main( _main( mgr ) ), patch( "builtins.print" ):
            await websocket_queue_endpoint( websocket=ws, session_id=_SID )
        ws.close.assert_awaited_with( code=CLOSE_CODE_AUTH_INVALID_TOKEN, reason="auth_error" )

    async def test_outer_generic_handler_close_also_fails( self ):
        # Outer generic handler's own close() also fails → its `except Exception: pass`.
        mgr = _mgr()
        ws  = _ws()
        ws.receive_json.return_value = { "type": "wrong" }
        ws.send_json.side_effect = RuntimeError( "boom mid-send" )
        ws.close.side_effect      = RuntimeError( "close also dead" )
        with _patch_fastapi_main( _main( mgr ) ), patch( "builtins.print" ):
            await websocket_queue_endpoint( websocket=ws, session_id=_SID )
        # no raise escaped → defensive close-failure arm covered


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
