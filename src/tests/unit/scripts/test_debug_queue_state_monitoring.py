"""
Coverage ramp for `src/scripts/debug/debug_queue_state_monitoring.py` — 84 statements,
previously a flat 0.0% (second pass of the 96% push, Mr Radio 🦉 2026-08-30).

🔴 WHAT THIS FILE IS, STATED PLAINLY. The script under test is a debug one-shot that nothing
imports. These tests were written to move a coverage number, not because the script earned
tests on merit. Every branch is really executed and really asserted; this is not evidence the
script is well-covered infrastructure.

Import-SAFE: one async function behind a `__main__` guard. `aiohttp` is replaced on the module
object, and `asyncio.sleep` is stubbed on the module too — the script waits 2 real seconds
between submitting jobs and re-reading the queues, which is 2 seconds this suite will not pay
on every test.

⚠️ `test_queue_state_monitoring_debug` is a TRAP NAME — imported directly, pytest would
collect it and it would open real HTTP connections to :7999. Reached via the module object.

THE SHAPE THAT MATTERS: the script has FOUR early `return False` exits (a bad status or an
exception, in each of step 1 and step 4). Where a run stops is the thing worth asserting, so
every test here checks the REQUEST COUNT as well as the return value — the console output
alone cannot distinguish "stopped at step 1" from "walked the whole thing".
"""

import asyncio
import importlib
import os
import sys
from types import MappingProxyType

import pytest

_ROOT = os.environ.get( "LUPIN_ROOT", os.getcwd() )
for _p in ( os.path.join( _ROOT, "src", "scripts", "debug" ), os.path.join( _ROOT, "src" ) ):
    if _p not in sys.path:
        sys.path.insert( 0, _p )

_mod = importlib.import_module( "debug_queue_state_monitoring" )

QUEUE_TYPES = [ "todo", "run", "done", "dead" ]
RAISE       = object()

# A full clean pass: 4 initial GETs + 3 POSTs + 4 final GETs.
FULL_PASS_REQUESTS = 11


class _FakeResponse:
    def __init__( self, status=200, json_body=None, text_body="error body" ):
        self.status     = status
        self._json_body = json_body if json_body is not None else { "queue": [], "size": 0 }
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
    """
    Stands in for aiohttp.ClientSession.

    GET and POST outcomes are scripted separately because the script interleaves them, and the
    last entry of each list repeats so a test only spells out the prefix it cares about.
    """

    def __init__( self, get_outcomes, post_outcomes ):
        self.get_outcomes  = get_outcomes
        self.post_outcomes = post_outcomes
        self.gets          = []
        self.posts         = []

    async def __aenter__( self ):
        return self

    async def __aexit__( self, *args ):
        return False

    def get( self, url, headers=None ):
        index   = min( len( self.gets ), len( self.get_outcomes ) - 1 )
        outcome = self.get_outcomes[ index ]
        self.gets.append( url )
        if outcome is RAISE: raise OSError( "get refused" )
        return outcome

    def post( self, url, headers=None, json=None ):
        index   = min( len( self.posts ), len( self.post_outcomes ) - 1 )
        outcome = self.post_outcomes[ index ]
        self.posts.append( { "url": url, "json": json } )
        if outcome is RAISE: raise OSError( "post refused" )
        return outcome


class _FakeAiohttp:
    def __init__( self, session ):
        self._session = session

    def ClientSession( self ):
        return self._session


async def _no_sleep( seconds ):
    """Stand-in for asyncio.sleep — the script's 2s wait is not worth paying per test."""
    return None


def _run( monkeypatch, get_outcomes=None, post_outcomes=None ):
    """
    Drive one pass of the script.

    Ensures:
        - returns ( result, session ) so a test can read where the run actually stopped
        - no real HTTP call and no real sleeping
    """
    session = _FakeSession(
        get_outcomes  if get_outcomes  is not None else [ _FakeResponse() ],
        post_outcomes if post_outcomes is not None else [ _FakeResponse() ],
    )
    monkeypatch.setattr( _mod, "aiohttp", _FakeAiohttp( session ) )
    monkeypatch.setattr( _mod.asyncio, "sleep", _no_sleep )

    result = asyncio.run( _mod.test_queue_state_monitoring_debug() )
    return result, session


def test_clean_run_walks_every_step_and_returns_true( monkeypatch, capsys ):
    """The happy path: four queues read, three jobs submitted, four queues re-read."""
    result, session = _run( monkeypatch )

    assert result is True
    assert len( session.gets )  == 8
    assert len( session.posts ) == 3
    assert len( session.gets ) + len( session.posts ) == FULL_PASS_REQUESTS

    out = capsys.readouterr().out
    assert "Queue state monitoring debug completed successfully!" in out
    assert out.count( "State comparison possible" ) == 4


def test_jobs_are_submitted_to_the_v2_door_with_distinct_messages( monkeypatch ):
    """
    Reads the POST payloads.

    `/api/push` was retired to a 410 on 2026-08-21 and this script was updated to `/api/v2/ask`
    — asserting the URL is what stops a silent regression back to the dead door. The three
    messages must also differ, or the loop is not really iterating.
    """
    _, session = _run( monkeypatch )

    assert [ p[ "url" ] for p in session.posts ] == [ "http://localhost:7999/api/v2/ask" ] * 3

    questions = [ p[ "json" ][ "question" ] for p in session.posts ]
    assert questions == [
        "State monitoring test job 1",
        "State monitoring test job 2",
        "State monitoring test job 3",
    ]
    assert all( p[ "json" ][ "websocket_id" ] == "wise penguin" for p in session.posts )


def test_initial_queue_error_stops_before_submitting_anything( monkeypatch, capsys ):
    """
    A bad status in step 1 returns False immediately.

    The request count is the assertion that matters: nothing may be submitted after a failed
    initial read, and the console says nothing about that either way.
    """
    result, session = _run( monkeypatch, get_outcomes=[ _FakeResponse( status=500 ) ] )

    assert result is False
    assert len( session.gets )  == 1
    assert session.posts == []
    assert "❌ todo ERROR (500)" in capsys.readouterr().out


def test_initial_queue_exception_stops_the_run( monkeypatch, capsys ):
    """Same early exit, reached through the exception arm instead of a status check."""
    result, session = _run( monkeypatch, get_outcomes=[ RAISE ] )

    assert result is False
    assert len( session.gets ) == 1
    assert session.posts == []
    assert "❌ todo EXCEPTION: get refused" in capsys.readouterr().out


def test_a_later_initial_queue_failure_stops_mid_scan( monkeypatch ):
    """
    The third queue fails, so the fourth is never read.

    A uniform-failure test cannot tell an early return from a loop that finishes and then
    reports — this one can.
    """
    result, session = _run( monkeypatch, get_outcomes=[
        _FakeResponse(), _FakeResponse(), _FakeResponse( status=503 ), _FakeResponse(),
    ] )

    assert result is False
    assert len( session.gets ) == 3


def test_failed_job_submission_does_not_stop_the_run( monkeypatch, capsys ):
    """
    Step 2 has NO early return — a rejected job is reported and the script carries on.

    This asymmetry with step 1 is worth pinning: all three submissions are attempted and the
    run still reaches its final verdict.
    """
    result, session = _run( monkeypatch, post_outcomes=[ _FakeResponse( status=422, text_body="bad job" ) ] )

    assert result is True
    assert len( session.posts ) == 3

    out = capsys.readouterr().out
    assert out.count( "❌ Job" ) == 3
    assert "bad job" in out


def test_job_submission_exception_does_not_stop_the_run( monkeypatch, capsys ):
    """The exception arm of step 2 — also non-fatal."""
    result, session = _run( monkeypatch, post_outcomes=[ RAISE ] )

    assert result is True
    assert len( session.posts ) == 3
    assert capsys.readouterr().out.count( "EXCEPTION: post refused" ) == 3


def test_final_queue_error_reports_the_five_hundred_source( monkeypatch, capsys ):
    """
    The failure the whole script exists to catch: the final read 500s.

    It prints the "likely the 500 error source" line and then tries for JSON detail.
    """
    result, session = _run( monkeypatch, get_outcomes=[
        _FakeResponse(), _FakeResponse(), _FakeResponse(), _FakeResponse(),
        _FakeResponse( status=500, json_body={ "detail": "queue exploded" } ),
    ] )

    assert result is False
    assert len( session.gets ) == 5     # four initial, then the first final read fails
    assert len( session.posts ) == 3

    out = capsys.readouterr().out
    assert "This is likely the 500 error source!" in out
    assert "'detail': 'queue exploded'" in out


def test_final_queue_error_with_unparseable_detail_is_swallowed( monkeypatch, capsys ):
    """
    The inner `except: pass` — the error body is not JSON, so no detail line is printed and
    the script still returns False rather than raising.
    """
    result, _ = _run( monkeypatch, get_outcomes=[
        _FakeResponse(), _FakeResponse(), _FakeResponse(), _FakeResponse(),
        _FakeResponse( status=500, json_body=RAISE ),
    ] )

    assert result is False

    out = capsys.readouterr().out
    assert "This is likely the 500 error source!" in out
    assert "Error details:" not in out


def test_final_queue_exception_stops_the_run( monkeypatch, capsys ):
    """The exception arm of step 4."""
    result, session = _run( monkeypatch, get_outcomes=[
        _FakeResponse(), _FakeResponse(), _FakeResponse(), _FakeResponse(), RAISE,
    ] )

    assert result is False
    assert len( session.gets ) == 5
    assert "❌ todo EXCEPTION: get refused" in capsys.readouterr().out


def test_non_dict_state_is_reported_as_unexpected_format( monkeypatch, capsys ):
    """
    Step 5's `else` arm: a body that is not a dict makes the comparison impossible.

    🔴 THE OBVIOUS FIXTURE DOES NOT REACH THIS BRANCH. A list body looks like the natural
    "not a dict" case and never gets here: step 1 calls `list(data.keys())`, a list has no
    `.keys()`, the AttributeError is caught by that step's own handler and the script returns
    False at the first queue. Measured — the first version of this test asserted True and got
    False from four steps earlier than it thought.

    So the fixture has to be a mapping-LIKE object: it answers `.keys()` so steps 1 and 4
    survive, while `isinstance(x, dict)` is False so step 5 takes the arm under test.
    """
    result, _ = _run( monkeypatch, get_outcomes=[ _FakeResponse( json_body=MappingProxyType( { "queue": [] } ) ) ] )

    assert result is True
    assert capsys.readouterr().out.count( "Unexpected state format" ) == 4
    assert "State comparison possible" not in capsys.readouterr().out
