#!/usr/bin/env python3
"""
Unit tests for cosa.agents.notification_proxy.listener.WebSocketListener.

The REST login (requests.post), the WebSocket transport (websockets.connect),
and asyncio.sleep are ALL boundary-mocked → no network, no real backoff
delay. Async methods are driven via asyncio.run with hand-built fake
WebSocket/connection objects.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import requests

import cosa.agents.notification_proxy.listener as ln
from cosa.agents.notification_proxy.listener import WebSocketListener


async def _noop_handler( event_type, data ):
    pass


def _make( on_event=None, debug=True, verbose=True ):
    return WebSocketListener(
        email      = "e@x.y",
        password   = "pw",
        session_id = "wise penguin",
        on_event   = on_event or _noop_handler,
        debug      = debug,
        verbose    = verbose,
    )


class FakeWS:
    """Async-context-manager + async-iterable stand-in for a websockets connection."""

    def __init__( self, auth_response, messages ):
        self._auth     = auth_response
        self._messages = messages
        self.sent      = []
        self.closed    = False

    async def send( self, data ):
        self.sent.append( data )

    async def recv( self ):
        return self._auth

    async def close( self ):
        self.closed = True

    def __aiter__( self ):
        async def gen():
            for m in self._messages:
                yield m
        return gen()


class FakeConnect:
    """Async context manager returned by the patched websockets.connect()."""

    def __init__( self, ws ):
        self.ws = ws

    async def __aenter__( self ):
        return self.ws

    async def __aexit__( self, *a ):
        return False


# ===========================================================================
# Construction / simple state
# ===========================================================================
class TestInitState:

    def test_initial_state( self ):
        l = _make()
        assert l.email        == "e@x.y"
        assert l.session_id   == "wise penguin"
        assert l.is_connected is False


# ===========================================================================
# _login (sync)
# ===========================================================================
class TestLogin:

    def test_success_returns_token( self ):
        l = _make()
        resp = MagicMock( status_code=200 )
        resp.json.return_value = { "tokens": { "access_token": "TKN" } }
        with patch.object( ln.requests, "post", return_value=resp ):
            assert l._login() == "TKN"

    def test_non_200_returns_none_with_help( self ):
        l = _make()
        resp = MagicMock( status_code=401, text="unauthorized" )
        with patch.object( ln.requests, "post", return_value=resp ):
            assert l._login() is None

    def test_connection_error_returns_none( self ):
        l = _make()
        with patch.object( ln.requests, "post", side_effect=requests.ConnectionError() ):
            assert l._login() is None

    def test_timeout_returns_none( self ):
        l = _make()
        with patch.object( ln.requests, "post", side_effect=requests.Timeout() ):
            assert l._login() is None


# ===========================================================================
# stop (async)
# ===========================================================================
class TestStop:

    def test_stop_without_ws( self ):
        l = _make()
        l._ws = None
        asyncio.run( l.stop() )
        assert l._running   is False
        assert l._connected is False

    def test_stop_closes_ws( self ):
        l = _make()
        ws = MagicMock()
        ws.close = AsyncMock()
        l._ws = ws
        asyncio.run( l.stop() )
        ws.close.assert_awaited_once()


# ===========================================================================
# _connect_and_listen (async)
# ===========================================================================
class TestConnectAndListen:

    def test_login_failure_returns_early( self ):
        l = _make()
        with patch.object( l, "_login", return_value=None ):
            asyncio.run( l._connect_and_listen() )
        assert l._connected is False

    def test_auth_success_dispatch_ping_badjson_and_handler_error( self ):
        seen = []

        async def handler( event_type, data ):
            if event_type == "boom":
                raise RuntimeError( "handler boom" )
            seen.append( event_type )

        l = _make( handler )
        l._running = True
        auth = json.dumps( { "type": "auth_success", "user_id": "u1" } )
        messages = [
            json.dumps( { "type": "sys_ping" } ),                       # → sys_pong sent
            json.dumps( { "type": "notification_queue_update" } ),      # → on_event
            "this is not json",                                         # → JSONDecodeError
            json.dumps( { "type": "boom" } ),                           # → handler raises → except
        ]
        ws = FakeWS( auth, messages )
        with patch.object( l, "_login", return_value="TKN" ), \
             patch.object( ln.websockets, "connect", return_value=FakeConnect( ws ) ):
            asyncio.run( l._connect_and_listen() )

        assert l._connected is True
        assert "notification_queue_update" in seen
        assert any( "sys_pong" in s for s in ws.sent )

    def test_auth_success_non_verbose_skips_debug_dump( self ):
        """auth_success with verbose=False → skips the debug auth dump, enters loop (268->278)."""
        l = _make( debug=True, verbose=False )
        l._running = True
        ws = FakeWS( json.dumps( { "type": "auth_success", "user_id": "u9" } ), [] )
        with patch.object( l, "_login", return_value="TKN" ), \
             patch.object( ln.websockets, "connect", return_value=FakeConnect( ws ) ):
            asyncio.run( l._connect_and_listen() )
        assert l._connected is True

    def test_auth_error_returns( self ):
        l = _make()
        l._running = True
        ws = FakeWS( json.dumps( { "type": "auth_error", "message": "bad token" } ), [] )
        with patch.object( l, "_login", return_value="TKN" ), \
             patch.object( ln.websockets, "connect", return_value=FakeConnect( ws ) ):
            asyncio.run( l._connect_and_listen() )
        assert l._connected is False

    def test_unexpected_auth_returns( self ):
        l = _make()
        l._running = True
        ws = FakeWS( json.dumps( { "type": "mystery" } ), [] )
        with patch.object( l, "_login", return_value="TKN" ), \
             patch.object( ln.websockets, "connect", return_value=FakeConnect( ws ) ):
            asyncio.run( l._connect_and_listen() )
        assert l._connected is False

    def test_receive_loop_breaks_when_stopped( self ):
        """Setting _running False mid-stream makes the next iteration break."""
        l = _make()
        l._running = True

        async def handler( event_type, data ):
            l._running = False     # stop after the first dispatched message

        l.on_event = handler
        auth = json.dumps( { "type": "auth_success" } )
        ws = FakeWS( auth, [
            json.dumps( { "type": "evt_one" } ),
            json.dumps( { "type": "evt_two" } ),     # should never be dispatched (break first)
        ] )
        with patch.object( l, "_login", return_value="TKN" ), \
             patch.object( ln.websockets, "connect", return_value=FakeConnect( ws ) ):
            asyncio.run( l._connect_and_listen() )
        assert l._running is False


# ===========================================================================
# run (async reconnect loop)
# ===========================================================================
class TestRun:

    def test_clean_stop_breaks( self ):
        l = _make()

        def stopper( *a ):
            l._running = False     # simulate stop() during the connection

        l._connect_and_listen = AsyncMock( side_effect=stopper )
        asyncio.run( l.run() )
        l._connect_and_listen.assert_awaited()

    def test_exception_then_reconnect_then_stop( self ):
        l = _make()
        calls = { "n": 0 }

        def boom_then_stop( *a ):
            calls[ "n" ] += 1
            if calls[ "n" ] == 1:
                raise RuntimeError( "dropped" )
            l._running = False

        l._connect_and_listen = AsyncMock( side_effect=boom_then_stop )
        with patch.object( ln.asyncio, "sleep", new=AsyncMock() ):
            asyncio.run( l.run() )
        assert calls[ "n" ] == 2

    def test_cancelled_error_breaks( self ):
        l = _make()
        l._connect_and_listen = AsyncMock( side_effect=asyncio.CancelledError() )
        asyncio.run( l.run() )    # caught + break, no raise out of run()

    def test_max_attempts_gives_up( self ):
        """Persistent clean drops (running stays True) → attempts climb to MAX → give up."""
        l = _make()
        l._connect_and_listen = AsyncMock( return_value=None )   # always "drops", never stops
        with patch.object( ln.asyncio, "sleep", new=AsyncMock() ):
            asyncio.run( l.run() )
        assert l._attempt >= ln.RECONNECT_MAX_ATTEMPTS
