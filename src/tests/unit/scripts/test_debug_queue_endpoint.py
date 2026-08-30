"""
Coverage ramp for `src/scripts/debug/debug_queue_endpoint.py` — 32 statements, previously a
flat 0.0% (second pass of the 96% push, Mr Radio 🦉 2026-08-30).

🔴 WHAT THIS FILE IS, STATED PLAINLY. The script under test is a debug one-shot that nothing
imports. These tests were written to move a coverage number, not because the script earned
tests on merit. Every branch below is really executed and really asserted — but this suite is
not evidence that the debug script is well-covered infrastructure.

This one is import-SAFE: one async function behind a `__main__` guard, so importing executes
nothing. `aiohttp` is replaced on the module object, never on the real package.

⚠️ THE FUNCTION IS NAMED `test_queue_endpoint`, WHICH IS A TRAP. Importing that name directly
would hand pytest a coroutine matching `python_functions` and it would be collected as a test
of its own — one that opens real HTTP connections to :7999. Reach it through the module object
only.
"""

import asyncio
import importlib
import os
import sys

import pytest

_ROOT = os.environ.get( "LUPIN_ROOT", os.getcwd() )
for _p in ( os.path.join( _ROOT, "src", "scripts", "debug" ), os.path.join( _ROOT, "src" ) ):
    if _p not in sys.path:
        sys.path.insert( 0, _p )

_mod = importlib.import_module( "debug_queue_endpoint" )

QUEUE_TYPES = [ "todo", "run", "done", "dead" ]
RAISE       = object()   # sentinel: the request itself blows up


class _FakeResponse:
    """
    Stands in for an aiohttp response used as an async context manager.

    Requires:
        - status is an int
        - json_body may be RAISE to make .json() throw, which is how the script falls
          through to .text()
    """

    def __init__( self, status=200, json_body=None, text_body="error text" ):
        self.status     = status
        self._json_body = json_body if json_body is not None else { "queue": [] }
        self._text_body = text_body

    async def __aenter__( self ):
        return self

    async def __aexit__( self, *args ):
        return False

    async def json( self ):
        if self._json_body is RAISE: raise ValueError( "not json" )
        return self._json_body

    async def text( self ):
        return self._text_body


class _FakeSession:
    """Stands in for aiohttp.ClientSession, itself an async context manager."""

    def __init__( self, outcomes ):
        self.outcomes = outcomes
        self.requests = []

    async def __aenter__( self ):
        return self

    async def __aexit__( self, *args ):
        return False

    def get( self, url, headers=None ):
        index   = min( len( self.requests ), len( self.outcomes ) - 1 )
        outcome = self.outcomes[ index ]
        self.requests.append( { "url": url, "headers": headers } )
        if outcome is RAISE: raise OSError( "connection refused" )
        return outcome


class _FakeAiohttp:
    """Replaces `mod.aiohttp` — hands out one scripted session."""

    def __init__( self, outcomes ):
        self.session = _FakeSession( outcomes )

    def ClientSession( self ):
        return self.session


def _run( monkeypatch, outcomes ):
    """
    Drive one pass of the script against scripted per-queue outcomes.

    Ensures:
        - returns the fake session so a test can read the requests actually made
        - no real HTTP call is issued
    """
    fake = _FakeAiohttp( outcomes )
    monkeypatch.setattr( _mod, "aiohttp", fake )
    asyncio.run( _mod.test_queue_endpoint() )
    return fake.session


def test_all_four_queues_succeed( monkeypatch, capsys ):
    """The clean path: every queue answers 200 with a dict body."""
    session = _run( monkeypatch, [ _FakeResponse() ] )

    out = capsys.readouterr().out
    assert out.count( "✅ SUCCESS (200)" ) == 4
    assert "Queue endpoint testing complete" in out

    # Reads the URLs actually requested — a script that hit one queue four times would print
    # an identical four-success banner.
    assert [ r[ "url" ] for r in session.requests ] == [
        f"http://localhost:7999/api/get-queue/{q}" for q in QUEUE_TYPES
    ]


def test_requests_carry_the_bearer_token( monkeypatch ):
    """The auth header is the reason this script reproduces the real call at all."""
    session = _run( monkeypatch, [ _FakeResponse() ] )

    for request in session.requests:
        assert request[ "headers" ][ "Authorization" ] == "Bearer mock_token_test_user"
        assert request[ "headers" ][ "Content-Type" ] == "application/json"


def test_non_dict_body_is_reported_as_its_type( monkeypatch, capsys ):
    """
    A 200 whose body is a list takes the `else type(data)` arm.

    Asserted because a list body is exactly what a queue endpoint might regress into, and the
    script's job is to say what it got.
    """
    _run( monkeypatch, [ _FakeResponse( json_body=[ 1, 2, 3 ] ) ] )

    out = capsys.readouterr().out
    assert "<class 'list'>" in out


def test_error_status_with_json_details_is_reported( monkeypatch, capsys ):
    """The 500 this script exists to chase, when the server explains itself in JSON."""
    _run( monkeypatch, [ _FakeResponse( status=500, json_body={ "detail": "boom" } ) ] )

    out = capsys.readouterr().out
    assert out.count( "❌ ERROR (500)" ) == 4
    assert "'detail': 'boom'" in out


def test_error_status_with_unparseable_body_falls_back_to_text( monkeypatch, capsys ):
    """When the error body is not JSON, the script must still surface something."""
    _run( monkeypatch, [ _FakeResponse( status=502, json_body=RAISE, text_body="upstream died" ) ] )

    out = capsys.readouterr().out
    assert "upstream died" in out


def test_connection_failure_is_caught_per_queue( monkeypatch, capsys ):
    """A refused connection is a result, not a crash — and the loop continues to the next."""
    _run( monkeypatch, [ RAISE ] )

    out = capsys.readouterr().out
    assert out.count( "❌ CONNECTION ERROR" ) == 4
    assert "Queue endpoint testing complete" in out


def test_a_mid_run_failure_does_not_stop_the_remaining_queues( monkeypatch, capsys ):
    """
    Mixed outcomes: the second queue fails and the last two still run.

    This is the case a uniform-outcome test cannot see — the script has no early return, and
    a regression that added one would pass every other test in this file.
    """
    session = _run( monkeypatch, [
        _FakeResponse(),
        _FakeResponse( status=500, json_body={ "detail": "bad" } ),
        _FakeResponse(),
        _FakeResponse(),
    ] )

    out = capsys.readouterr().out
    assert out.count( "✅ SUCCESS (200)" ) == 3
    assert out.count( "❌ ERROR (500)" ) == 1
    assert len( session.requests ) == 4
