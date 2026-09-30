"""
Coverage ramp for `src/scripts/debug/debug_websocket_auth_validation.py` — 97 statements,
previously a flat 0.0% (assigned by Mr Radio 🦉 2026-08-30 for the 96% push).

🔴 WHAT THIS FILE IS, STATED PLAINLY. The script under test is a debug one-shot that nothing
imports. These tests were written to move a coverage number, not because the script earned
tests on merit. They are honest tests — every branch below is really executed and really
asserted — but nobody should read this suite as evidence that the debug script is
well-covered infrastructure. See the commit message for the fleet decision behind it.

LOAD MECHANISM: `src/scripts/debug` on `sys.path`, then `importlib.import_module`. Unlike its
two siblings in this ramp, this module is import-SAFE: everything lives inside one async
function behind an `if __name__ == "__main__"` guard, so importing it executes nothing.

⚠️ THE FUNCTION IS NAMED `test_websocket_auth_validation`, WHICH IS A TRAP. Importing that
name into this module by `from … import test_websocket_auth_validation` would hand pytest a
coroutine function whose name matches `python_functions`, and pytest would collect it as a
test of its own — one that opens real sockets to :7999. It is therefore reached ONLY through
the module object (`_mod.test_websocket_auth_validation`), never imported by name.

🔴 NO REAL SOCKETS. `websockets.connect` is replaced on the module object (`_mod.websockets`)
with a stand-in, never by patching the real `websockets` package, which would reach through
to every other importer in the process. Each test scripts a list of per-connection behaviors;
one full pass of the function opens exactly 16 connections (8 malformed + 7 invalid-token +
1 valid), so a scripted list shorter than that is a bug in the test, not in the script.
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

_mod = importlib.import_module( "debug_websocket_auth_validation" )

# One pass of the function opens this many connections. Asserted in a test below rather than
# left as a comment, so a change to the case lists reddens something instead of silently
# making every scripted list here too short.
MALFORMED_CASES    = 8
INVALID_TOKEN_CASES = 7
TOTAL_CONNECTS     = MALFORMED_CASES + INVALID_TOKEN_CASES + 1

# Sentinels for scripting a connection's behavior.
CONNECT_RAISES = "connect-raises"

REJECTED = json.dumps( { "type": "auth_error", "message": "nope" } )
ACCEPTED = json.dumps( { "type": "auth_success", "user": "test" } )
NOT_AUTH = json.dumps( { "type": "something_else" } )


class _FakeWebSocket:
    """
    Stands in for one open connection.

    Requires:
        - behavior is either a string to return from recv(), or an Exception to raise

    Ensures:
        - send() records the payload and never touches a socket
        - recv() reproduces the scripted outcome exactly once per call
    """

    def __init__( self, behavior ):
        self.behavior = behavior
        self.sent     = []

    async def send( self, message ):
        self.sent.append( message )

    async def recv( self ):
        if isinstance( self.behavior, BaseException ): raise self.behavior
        return self.behavior


class _FakeConnect:
    """Async context manager returned by the stand-in `websockets.connect`."""

    def __init__( self, behavior, recorder ):
        self.behavior = behavior
        self.recorder = recorder
        self.socket   = None

    async def __aenter__( self ):
        if self.behavior == CONNECT_RAISES: raise OSError( "connection refused" )
        self.socket = _FakeWebSocket( self.behavior )
        self.recorder.append( self.socket )
        return self.socket

    async def __aexit__( self, *args ):
        return False


class _FakeWebsocketsModule:
    """
    Replaces `mod.websockets`. Hands out one scripted behavior per connect() call.

    Requires:
        - behaviors has at least one entry

    Ensures:
        - the last entry repeats if connect() is called more times than scripted, so a test
          that only cares about the tail does not have to spell out all 16
    """

    def __init__( self, behaviors ):
        self.behaviors = list( behaviors )
        self.calls     = []
        self.sockets   = []

    def connect( self, uri ):
        index    = min( len( self.calls ), len( self.behaviors ) - 1 )
        behavior = self.behaviors[ index ]
        self.calls.append( uri )
        return _FakeConnect( behavior, self.sockets )


def _run( monkeypatch, behaviors ):
    """
    Drive one full pass of the script's async entry point against scripted connections.

    Requires:
        - behaviors is a non-empty list of per-connection scripted outcomes

    Ensures:
        - returns ( result, fake ) where result is the function's own bool return
        - no real socket is opened
    """
    fake = _FakeWebsocketsModule( behaviors )
    monkeypatch.setattr( _mod, "websockets", fake )
    result = asyncio.run( _mod.test_websocket_auth_validation() )
    return result, fake


def test_all_invalid_input_rejected_and_valid_auth_accepted_returns_true( monkeypatch ):
    """The clean path: everything bad is refused, the good token is accepted."""
    behaviors = [ REJECTED ] * ( TOTAL_CONNECTS - 1 ) + [ ACCEPTED ]
    result, fake = _run( monkeypatch, behaviors )

    assert result is True
    assert len( fake.calls ) == TOTAL_CONNECTS


def test_one_pass_opens_exactly_sixteen_connections( monkeypatch ):
    """
    Pins the connection count the scripted lists in this file depend on.

    Without this, adding a case to either list in the script would leave every other test
    here silently reusing its last behavior for the new case.
    """
    behaviors = [ REJECTED ] * ( TOTAL_CONNECTS - 1 ) + [ ACCEPTED ]
    _, fake = _run( monkeypatch, behaviors )

    assert len( fake.calls ) == 16
    assert all( uri.startswith( "ws://localhost:7999/ws/queue/" ) for uri in fake.calls )


def test_server_accepting_malformed_and_invalid_input_returns_false( monkeypatch ):
    """
    The failure the script exists to detect: the server answers something other than
    auth_error, so the bad input was NOT rejected.
    """
    result, fake = _run( monkeypatch, [ NOT_AUTH ] * TOTAL_CONNECTS )

    assert result is False
    assert len( fake.calls ) == TOTAL_CONNECTS


def test_recv_timeout_counts_as_rejection( monkeypatch ):
    """No answer within the window is treated as a refusal, not a failure."""
    behaviors = [ asyncio.TimeoutError() ] * ( TOTAL_CONNECTS - 1 ) + [ ACCEPTED ]
    result, _ = _run( monkeypatch, behaviors )

    assert result is True


def test_unparseable_response_counts_as_rejection( monkeypatch ):
    """A non-JSON answer is a refusal — exercises the JSONDecodeError arm."""
    behaviors = [ "{not json at all" ] * ( TOTAL_CONNECTS - 1 ) + [ ACCEPTED ]
    result, _ = _run( monkeypatch, behaviors )

    assert result is True


def test_unexpected_recv_error_counts_as_rejection( monkeypatch ):
    """Any other error while reading the answer is a refusal — the bare `except` arm."""
    behaviors = [ RuntimeError( "socket exploded" ) ] * ( TOTAL_CONNECTS - 1 ) + [ ACCEPTED ]
    result, _ = _run( monkeypatch, behaviors )

    assert result is True


def test_connection_refused_counts_as_rejection( monkeypatch ):
    """A connection that never opens is a refusal — the outer `except` arm on both loops."""
    behaviors = [ CONNECT_RAISES ] * ( TOTAL_CONNECTS - 1 ) + [ ACCEPTED ]
    result, _ = _run( monkeypatch, behaviors )

    assert result is True


def test_valid_auth_rejected_returns_false( monkeypatch ):
    """
    Bad input handled correctly but the GOOD token refused — the `elif not valid_passed` arm.

    This is the case the two failure counters cannot express: zero critical failures and
    still a broken server.
    """
    behaviors = [ REJECTED ] * ( TOTAL_CONNECTS - 1 ) + [ NOT_AUTH ]
    result, _ = _run( monkeypatch, behaviors )

    assert result is False


def test_valid_auth_recv_error_returns_false( monkeypatch ):
    """The valid-auth read itself fails — inner `except` on the valid-auth block."""
    behaviors = [ REJECTED ] * ( TOTAL_CONNECTS - 1 ) + [ RuntimeError( "read failed" ) ]
    result, _ = _run( monkeypatch, behaviors )

    assert result is False


def test_valid_auth_connection_failure_returns_false( monkeypatch ):
    """The valid-auth connection never opens — outer `except` on the valid-auth block."""
    behaviors = [ REJECTED ] * ( TOTAL_CONNECTS - 1 ) + [ CONNECT_RAISES ]
    result, _ = _run( monkeypatch, behaviors )

    assert result is False


def test_auth_payloads_carry_the_scripted_tokens( monkeypatch ):
    """
    Reads the DATA the script sends, not just its return value.

    A test that only asserts True/False cannot tell a working script from one that sends the
    same token sixteen times, because the fake would answer identically either way.
    """
    behaviors = [ REJECTED ] * ( TOTAL_CONNECTS - 1 ) + [ ACCEPTED ]
    _, fake = _run( monkeypatch, behaviors )

    payloads = [ socket.sent[ 0 ] for socket in fake.sockets ]
    assert len( payloads ) == TOTAL_CONNECTS

    # The malformed block sends raw strings; the token blocks send auth_request envelopes.
    assert payloads[ 0 ] == "not json"

    token_payloads = payloads[ MALFORMED_CASES: ]
    tokens         = [ json.loads( p )[ "token" ] for p in token_payloads ]

    # Every scripted invalid token is distinct from the valid one, and the valid one is last.
    assert tokens[ -1 ] == "mock_token_test_user"
    assert "invalid_format" in tokens
    assert None in tokens
    assert len( set( str( t ) for t in tokens ) ) == len( tokens )
