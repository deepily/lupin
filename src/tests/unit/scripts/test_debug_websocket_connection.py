"""
Coverage ramp for `src/scripts/debug/debug_websocket_connection.py` — 36 statements,
previously a flat 0.0% (second pass of the 96% push, Mr Radio 🦉 2026-08-30).

🔴 WHAT THIS FILE IS, STATED PLAINLY. The script under test is a debug one-shot that nothing
imports. These tests were written to move a coverage number, not because the script earned
tests on merit. Every branch is really executed and really asserted; this is not evidence the
script is well-covered infrastructure.

Import-SAFE: one async function behind a `__main__` guard. `websockets` is replaced on the
module object, never on the real package, so no other importer in the process is affected.

⚠️ `test_basic_connection` is a TRAP NAME — importing it directly would have pytest collect it
as a test that opens real sockets to :7999. Reached through the module object only.

THE EARLY RETURN IS THE POINT. The script walks four session-ID formats and returns True on
the FIRST success, so a test that makes every case succeed exercises exactly one iteration.
The scripted-outcome list below is per-connection for that reason.
"""

import asyncio
import importlib
import json
import os
import sys

import pytest

_ROOT = os.environ.get( "LUPIN_ROOT", os.getcwd() )
for _p in ( os.path.join( _ROOT, "src", "scripts", "debug" ), os.path.join( _ROOT, "src" ) ):
    if _p not in sys.path:
        sys.path.insert( 0, _p )

_mod = importlib.import_module( "debug_websocket_connection" )

SESSION_IDS    = [ "wise penguin", "test_penguin", "clever fox", "brave tiger" ]
CONNECT_RAISES = "connect-raises"

SUCCESS = json.dumps( { "type": "auth_success" } )
REFUSED = json.dumps( { "type": "auth_error", "reason": "bad token" } )


class _FakeWebSocket:
    def __init__( self, behavior ):
        self.behavior = behavior
        self.sent     = []

    async def send( self, message ):
        self.sent.append( message )

    async def recv( self ):
        if isinstance( self.behavior, BaseException ): raise self.behavior
        return self.behavior


class _FakeConnect:
    def __init__( self, behavior, recorder ):
        self.behavior = behavior
        self.recorder = recorder

    async def __aenter__( self ):
        if self.behavior == CONNECT_RAISES: raise OSError( "refused" )
        socket = _FakeWebSocket( self.behavior )
        self.recorder.append( socket )
        return socket

    async def __aexit__( self, *args ):
        return False


class _FakeWebsockets:
    """
    Replaces `mod.websockets`.

    Ensures:
        - the last scripted behavior repeats, so a test only has to spell out the prefix it
          cares about
    """

    def __init__( self, behaviors ):
        self.behaviors = list( behaviors )
        self.uris      = []
        self.sockets   = []

    def connect( self, uri ):
        index    = min( len( self.uris ), len( self.behaviors ) - 1 )
        behavior = self.behaviors[ index ]
        self.uris.append( uri )
        return _FakeConnect( behavior, self.sockets )


def _run( monkeypatch, behaviors ):
    """Drive one pass; returns ( result, fake )."""
    fake = _FakeWebsockets( behaviors )
    monkeypatch.setattr( _mod, "websockets", fake )
    result = asyncio.run( _mod.test_basic_connection() )
    return result, fake


def test_first_session_id_authenticates_and_returns_early( monkeypatch, capsys ):
    """
    Success on the first case returns True immediately.

    Asserting the connection COUNT is what proves the early return; the printed banner looks
    the same whether it stopped at one or walked all four.
    """
    result, fake = _run( monkeypatch, [ SUCCESS ] )

    assert result is True
    assert len( fake.uris ) == 1
    assert "Authentication successful!" in capsys.readouterr().out


def test_all_four_session_ids_are_tried_when_none_authenticates( monkeypatch, capsys ):
    """Every case refused: all four are attempted and the function reports failure."""
    result, fake = _run( monkeypatch, [ REFUSED ] )

    assert result is False
    assert len( fake.uris ) == 4
    assert capsys.readouterr().out.count( "❌ Authentication failed" ) == 4


def test_session_ids_are_url_encoded( monkeypatch ):
    """
    The space in "wise penguin" must be percent-encoded.

    This is the script's actual subject — it exists to test session-ID formats — so the URI
    is the data worth asserting, not the console text.
    """
    _, fake = _run( monkeypatch, [ REFUSED ] )

    assert fake.uris[ 0 ] == "ws://localhost:7999/ws/queue/wise%20penguin"
    assert fake.uris[ 1 ] == "ws://localhost:7999/ws/queue/test_penguin"
    assert len( fake.uris ) == len( SESSION_IDS )


def test_auth_payload_carries_the_mock_token( monkeypatch ):
    """Reads what was sent, not just that something was sent."""
    _, fake = _run( monkeypatch, [ SUCCESS ] )

    payload = json.loads( fake.sockets[ 0 ].sent[ 0 ] )
    assert payload[ "type" ]  == "auth_request"
    assert payload[ "token" ] == "mock_token_test_user"
    assert payload[ "subscribed_events" ] == [ "*" ]


def test_recv_timeout_is_reported_and_the_walk_continues( monkeypatch, capsys ):
    """No answer within 3s — the TimeoutError arm, and the loop moves to the next case."""
    result, fake = _run( monkeypatch, [ asyncio.TimeoutError() ] )

    assert result is False
    assert len( fake.uris ) == 4
    assert capsys.readouterr().out.count( "No response received (timeout)" ) == 4


def test_unexpected_recv_error_is_reported( monkeypatch, capsys ):
    """Any other read failure — the generic `except` inside the response block."""
    result, _ = _run( monkeypatch, [ RuntimeError( "socket died" ) ] )

    assert result is False
    assert "Response error: socket died" in capsys.readouterr().out


def test_connection_failure_is_reported_per_case( monkeypatch, capsys ):
    """The outer `except` — the connection never opens at all."""
    result, _ = _run( monkeypatch, [ CONNECT_RAISES ] )

    assert result is False
    assert capsys.readouterr().out.count( "❌ Connection failed" ) == 4


def test_a_later_session_id_can_still_succeed( monkeypatch, capsys ):
    """
    The first three fail in three different ways and the fourth authenticates.

    This is the case every uniform-outcome test misses: it proves the loop actually advances
    through distinct cases rather than retrying one, and that a success after failures still
    returns True.
    """
    result, fake = _run( monkeypatch, [
        CONNECT_RAISES,
        asyncio.TimeoutError(),
        REFUSED,
        SUCCESS,
    ] )

    assert result is True
    assert len( fake.uris ) == 4

    out = capsys.readouterr().out
    assert "❌ Connection failed" in out
    assert "No response received (timeout)" in out
    assert "❌ Authentication failed" in out
    assert "✅ Authentication successful!" in out
