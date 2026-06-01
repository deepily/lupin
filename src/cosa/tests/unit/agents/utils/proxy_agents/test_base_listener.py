"""
Unit tests for cosa/agents/utils/proxy_agents/base_listener.py.

Every external seam is boundary-mocked so NOTHING leaves the process:
- `requests.post`        — JWT login (_login)
- `websockets.connect`   — replaced with a fake async-context-manager ws
- `asyncio.sleep`        — patched to a no-op so reconnect backoff is instant
ZERO API spend; no real socket/HTTP.
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import requests

import cosa.agents.utils.proxy_agents.base_listener as mod
from cosa.agents.utils.proxy_agents.base_listener import BaseWebSocketListener


def _run( coro ):
    return asyncio.run( coro )


def _make_listener( on_event=None, **over ):
    kwargs = dict(
        email             = "a@x.com",
        password          = "pw",
        session_id        = "wise penguin",
        on_event          = on_event or AsyncMock(),
        subscribed_events = [ "notification_update" ],
    )
    kwargs.update( over )
    return BaseWebSocketListener( **kwargs )


class _FakeWS:
    """Fake websocket: recv() returns the auth response; iteration yields messages."""
    def __init__( self, auth_response, messages=None ):
        self._auth     = auth_response
        self._messages = messages or []
        self.sent      = []
        self.closed     = False

    async def send( self, m ):
        self.sent.append( m )

    async def recv( self ):
        return self._auth

    async def __aiter__( self ):
        for m in self._messages:
            yield m

    async def close( self ):
        self.closed = True


class _FakeConnect:
    """Async context manager standing in for websockets.connect( uri )."""
    def __init__( self, ws ):
        self.ws = ws

    async def __aenter__( self ):
        return self.ws

    async def __aexit__( self, *exc ):
        return False


def _patch_ws( ws ):
    return patch.object( mod.websockets, "connect", return_value=_FakeConnect( ws ) )


def _login_resp( status_code=200, token="jwt123" ):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = { "tokens": { "access_token": token } }
    r.text = "error body"
    return r


# =========================================================================== #
# __init__ / is_connected
# =========================================================================== #
def test_init_defaults_and_is_connected_false():
    li = _make_listener()
    assert li.email == "a@x.com"
    assert li.is_connected is False
    assert li._attempt == 0
    assert li._ws is None


# =========================================================================== #
# _login
# =========================================================================== #
def test_login_success_returns_token():
    li = _make_listener( debug=True )
    with patch.object( mod.requests, "post", return_value=_login_resp( 200, "tok-abc" ) ):
        assert li._login() == "tok-abc"


def test_login_connection_error_returns_none():
    li = _make_listener()
    with patch.object( mod.requests, "post", side_effect=requests.ConnectionError( "down" ) ):
        assert li._login() is None


def test_login_timeout_returns_none():
    li = _make_listener()
    with patch.object( mod.requests, "post", side_effect=requests.Timeout( "slow" ) ):
        assert li._login() is None


def test_login_non_200_prints_help_returns_none( capsys ):
    li = _make_listener()
    with patch.object( mod.requests, "post", return_value=_login_resp( 401 ) ):
        assert li._login() is None
    assert "Login failed: 401" in capsys.readouterr().out


# =========================================================================== #
# stop
# =========================================================================== #
def test_stop_closes_open_ws():
    li = _make_listener()
    ws = MagicMock()
    ws.close = AsyncMock()
    li._ws = ws
    _run( li.stop() )
    assert li._running is False
    assert li._connected is False
    ws.close.assert_awaited_once()


def test_stop_no_ws_is_safe():
    li = _make_listener()
    li._ws = None
    _run( li.stop() )
    assert li._running is False


# =========================================================================== #
# run  ( reconnect loop )
# =========================================================================== #
def test_run_clean_stop_breaks():
    li = _make_listener()
    async def _cl():
        li._running = False   # simulate stop() during the connection
    with patch.object( li, "_connect_and_listen", side_effect=_cl ):
        _run( li.run() )
    assert li._attempt == 0   # never entered reconnect branch


def test_run_cancelled_error_breaks():
    li = _make_listener()
    with patch.object( li, "_connect_and_listen", side_effect=asyncio.CancelledError() ):
        _run( li.run() )      # must return, not raise
    assert li._running is True  # cancelled breaks before any flag flip


def test_run_connection_drop_then_stop_reconnects():
    li = _make_listener()
    calls = { "n": 0 }
    async def _cl():
        calls[ "n" ] += 1
        if calls[ "n" ] >= 2:
            li._running = False   # stop after the first reconnect cycle
        # else: return normally → reconnect branch
    with patch.object( li, "_connect_and_listen", side_effect=_cl ), \
         patch.object( mod.asyncio, "sleep", new=AsyncMock() ):
        _run( li.run() )
    assert li._attempt >= 1       # reconnect branch executed


def test_run_generic_exception_then_stop():
    li = _make_listener()
    calls = { "n": 0 }
    async def _cl():
        calls[ "n" ] += 1
        if calls[ "n" ] == 1:
            raise RuntimeError( "boom" )   # except branch
        li._running = False
    with patch.object( li, "_connect_and_listen", side_effect=_cl ), \
         patch.object( mod.asyncio, "sleep", new=AsyncMock() ):
        _run( li.run() )
    assert li._attempt >= 1


def test_run_max_attempts_gives_up( capsys ):
    li = _make_listener()
    async def _cl():
        return   # always "drops" → keeps reconnecting until max attempts
    with patch.object( li, "_connect_and_listen", side_effect=_cl ), \
         patch.object( mod.asyncio, "sleep", new=AsyncMock() ):
        _run( li.run() )
    assert li._attempt >= mod.RECONNECT_MAX_ATTEMPTS
    assert "Max reconnection attempts" in capsys.readouterr().out


# =========================================================================== #
# _connect_and_listen
# =========================================================================== #
def test_connect_login_failure_returns_early( capsys ):
    li = _make_listener()
    with patch.object( li, "_login", return_value=None ):
        _run( li._connect_and_listen() )
    assert "Authentication failed" in capsys.readouterr().out
    assert li._connected is False


def test_connect_auth_success_empty_stream():
    on_event = AsyncMock()
    li = _make_listener( on_event=on_event, debug=True, verbose=True )
    li._running = True
    ws = _FakeWS( json.dumps( { "type": "auth_success", "user_id": "u1" } ), messages=[] )
    with patch.object( li, "_login", return_value="jwt" ), _patch_ws( ws ):
        _run( li._connect_and_listen() )
    assert li._connected is True
    assert li._user_id == "u1"
    assert li._attempt == 0
    # auth_request was sent
    assert any( "auth_request" in s for s in ws.sent )


def test_connect_auth_error_returns( capsys ):
    li = _make_listener()
    li._running = True
    ws = _FakeWS( json.dumps( { "type": "auth_error", "message": "bad creds" } ) )
    with patch.object( li, "_login", return_value="jwt" ), _patch_ws( ws ):
        _run( li._connect_and_listen() )
    assert "Authentication failed: bad creds" in capsys.readouterr().out
    assert li._connected is False


def test_connect_unexpected_auth_response_returns( capsys ):
    li = _make_listener()
    li._running = True
    ws = _FakeWS( json.dumps( { "type": "mystery" } ) )
    with patch.object( li, "_login", return_value="jwt" ), _patch_ws( ws ):
        _run( li._connect_and_listen() )
    assert "Unexpected auth response" in capsys.readouterr().out


def test_connect_ping_replies_pong_then_dispatches():
    on_event = AsyncMock()
    li = _make_listener( on_event=on_event, verbose=True )
    li._running = True
    messages = [
        json.dumps( { "type": "sys_ping" } ),
        json.dumps( { "type": "notification_update", "id": 7 } ),
    ]
    ws = _FakeWS( json.dumps( { "type": "auth_success" } ), messages=messages )
    with patch.object( li, "_login", return_value="jwt" ), _patch_ws( ws ):
        _run( li._connect_and_listen() )
    # pong sent in response to ping
    assert any( "sys_pong" in s for s in ws.sent )
    # the non-ping event was dispatched
    on_event.assert_awaited_once()
    assert on_event.await_args[ 0 ][ 0 ] == "notification_update"


def test_connect_stops_when_running_flips_false():
    # on_event flips _running False → next loop iteration breaks (line 292-293)
    li = _make_listener()
    li._running = True
    async def _on_event( etype, data ):
        li._running = False
    li.on_event = _on_event
    messages = [
        json.dumps( { "type": "evt_a" } ),
        json.dumps( { "type": "evt_b" } ),   # never dispatched — loop breaks first
    ]
    ws = _FakeWS( json.dumps( { "type": "auth_success" } ), messages=messages )
    with patch.object( li, "_login", return_value="jwt" ), _patch_ws( ws ):
        _run( li._connect_and_listen() )
    assert li._running is False


def test_connect_invalid_json_message_logged( capsys ):
    li = _make_listener()
    li._running = True
    ws = _FakeWS( json.dumps( { "type": "auth_success" } ), messages=[ "this is not json" ] )
    with patch.object( li, "_login", return_value="jwt" ), _patch_ws( ws ):
        _run( li._connect_and_listen() )
    assert "Invalid JSON received" in capsys.readouterr().out


def test_connect_handler_exception_prints_when_no_log( capsys ):
    li = _make_listener( on_event=AsyncMock( side_effect=RuntimeError( "handler boom" ) ) )
    li._running = True
    ws = _FakeWS( json.dumps( { "type": "auth_success" } ), messages=[ json.dumps( { "type": "evt" } ) ] )
    with patch.object( li, "_login", return_value="jwt" ), _patch_ws( ws ):
        _run( li._connect_and_listen() )
    assert "Error handling message" in capsys.readouterr().out


def test_connect_handler_exception_uses_log_hook():
    li = _make_listener( on_event=AsyncMock( side_effect=RuntimeError( "handler boom" ) ) )
    li._running = True
    li._log = MagicMock()   # presence of _log routes the error through it (line 313-314)
    ws = _FakeWS( json.dumps( { "type": "auth_success" } ), messages=[ json.dumps( { "type": "evt" } ) ] )
    with patch.object( li, "_login", return_value="jwt" ), _patch_ws( ws ):
        _run( li._connect_and_listen() )
    li._log.assert_called_once()
    assert "Error handling message" in li._log.call_args[ 0 ][ 0 ]
