#!/usr/bin/env python3
"""
THE FLEET CENSUS COSTS ONE READ PER SESSION, NOT ONE DIRECTORY SCAN PER SESSION.

Row ff85f78f. The census classified each session with `find_session_path_by_id`, which
globs and json-loads cc-*.json until it hits: 704 sessions x ~352 files = 248,160 visits,
9 s per call, on the server's event loop. Every other census test injects a classifier or
patches the census, so the real scan never ran.

This file counts FILE READS through a counting `open` rather than timing a clock, drives
the real `_live_fleet_counts` against bridges planted under a temp directory, and drives
the assembled app to show the handler does not block the event loop. Nothing here touches
~/.claude/sessions: SESSION_DIR is redirected to tmp_path.
"""
import asyncio
import builtins
import inspect
import json
import os
import subprocess
import sys
import time

import pytest
from fastapi import FastAPI
import httpx

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.routers import arbiter
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt
from lupin_cli.claude_code.hooks.lib import session_bridge as sb
from lupin_mcp import fleet_size_cap, session_spawner


@pytest.fixture
def sessions_dir( tmp_path, monkeypatch ):
    directory = tmp_path / "sessions"
    directory.mkdir()
    monkeypatch.setattr( sb, "SESSION_DIR", directory )
    return directory


@pytest.fixture
def no_pid_check( monkeypatch ):
    """Planted files carry invented pids; liveness is not what these arms measure."""
    monkeypatch.setattr( sb, "_can_trust_host_pids", lambda: False )


def _plant( directory, name, session_id, role=None, spawned_by=None, persona=True ):
    payload = { "session_id": session_id, "cwd": str( directory ) }
    if persona:
        payload[ "voice_persona" ] = { "name": session_id }
    if role is not None:
        payload[ "role" ] = role
    if spawned_by is not None:
        payload[ "spawned_by" ] = spawned_by
    ( directory / name ).write_text( json.dumps( payload ) )


def _plant_many( directory, n ):
    for i in range( n ):
        _plant( directory, f"cc-{10000 + i}.json", f"{i:08x}-0000-4000-8000-000000000000",
                role="author", spawned_by="21dff055" )


class _ReadCounter:
    """Counts opens of cc-*.json files inside one directory."""
    def __init__( self, monkeypatch, directory ):
        self.reads = 0
        real_open  = builtins.open
        directory  = str( directory )

        def counting_open( file, *args, **kwargs ):
            if str( file ).startswith( directory ) and str( file ).endswith( ".json" ):
                self.reads += 1
            return real_open( file, *args, **kwargs )

        monkeypatch.setattr( builtins, "open", counting_open )


def _reads_for( n, sessions_dir, monkeypatch ):
    _plant_many( sessions_dir, n )
    counter = _ReadCounter( monkeypatch, sessions_dir )
    live    = arbiter._live_fleet_counts()
    assert live == { "total": n, "managers": 0, "workers": n, "unknown": 0 }, (
        f"POSITIVE CONTROL: all {n} planted seats must be counted as workers — saw {live}" )
    return counter.reads


# ──────────────────────── (a) cost is a COUNT, and it is linear ────────────────────────

def test_the_pane_census_reads_a_bounded_number_of_files_per_session( sessions_dir, no_pid_check, monkeypatch ):
    reads = _reads_for( 300, sessions_dir, monkeypatch )
    assert reads <= 3 * 300, (
        f"{reads} file reads for 300 seats. The old per-session directory rescan read "
        f"~45,000; more than 3 per seat means a rescan crept back." )


def test_the_census_read_count_doubles_when_the_fleet_doubles( tmp_path, no_pid_check, monkeypatch ):
    counts = {}
    for n in ( 300, 600 ):
        directory = tmp_path / f"s{n}"
        directory.mkdir()
        monkeypatch.setattr( sb, "SESSION_DIR", directory )
        counts[ n ] = _reads_for( n, directory, monkeypatch )
        monkeypatch.undo()                       # drop the counting open before the next arm
        monkeypatch.setattr( sb, "_can_trust_host_pids", lambda: False )
    assert counts[ 600 ] <= 2.2 * counts[ 300 ], (
        f"reads went {counts[ 300 ]} -> {counts[ 600 ]}: more than double for double the "
        f"fleet is the squared cost a fixed bound would miss." )


def test_the_spawn_gate_census_reads_a_bounded_number_of_files( sessions_dir, no_pid_check, monkeypatch ):
    _plant_many( sessions_dir, 200 )
    monkeypatch.setattr( fleet_size_cap, "config_file_path", lambda: str( sessions_dir / "none.ini" ) )
    counter = _ReadCounter( monkeypatch, sessions_dir )
    refusal = session_spawner.default_fleet_gate( 1, config_fn=lambda: None, census_fn=None )
    assert refusal is None or "200" in refusal, refusal      # DEFAULT_FLEET_CAP=8 refuses at 200
    assert counter.reads <= 3 * 200, f"{counter.reads} reads for 200 seats at the spawn gate"


def test_the_spawn_gate_still_refuses_at_the_cap_when_census_fn_returns_a_generator( sessions_dir, no_pid_check, monkeypatch ):
    """
    The gate walks its census twice (path map, then the count). A one-shot generator
    would reach the count already exhausted: total 0, an UNDER-count, the direction that
    lets a spawn through. 10 planted seats against the shipped cap of 8 must refuse.
    """
    _plant_many( sessions_dir, 10 )
    monkeypatch.setattr( fleet_size_cap, "config_file_path", lambda: str( sessions_dir / "none.ini" ) )
    refusal = session_spawner.default_fleet_gate(
        1, config_fn=lambda: None,
        census_fn=lambda: ( t for t in sb.find_active_sessions( require_persona=False ) ) )
    assert refusal is not None and "already running 10" in refusal, refusal


# ───────────── (b) the counts are the old implementation's, on live/dead/foreign ─────────────

def _old_counts( sessions, unreadable ):
    return fleet_size_cap.census( sessions, fleet_size_cap.default_counting_classifier,
                                  unreadable=len( unreadable ) )


def test_counts_match_the_old_classifier_on_live_dead_and_foreign_entries( sessions_dir, monkeypatch ):
    live_procs = [ subprocess.Popen( [ "sleep", "120" ] ) for _ in range( 3 ) ]
    dead       = subprocess.Popen( [ "true" ] )
    dead.wait()
    try:
        _plant( sessions_dir, f"cc-{live_procs[ 0 ].pid}.json", "aaaaaaaa-1", role="manager" )
        _plant( sessions_dir, f"cc-{live_procs[ 1 ].pid}.json", "bbbbbbbb-2", role="author", spawned_by="aaaaaaaa" )
        _plant( sessions_dir, f"cc-{live_procs[ 2 ].pid}.json", "cccccccc-3", persona=False )   # undeclared top-level
        _plant( sessions_dir, f"cc-{dead.pid}.json", "dddddddd-4", role="author", spawned_by="x" )   # dead
        ( sessions_dir / "cc-listener-9.json" ).write_text( "{}" )                                    # foreign
        ( sessions_dir / "cc-buffer-9.json" ).write_text( "{}" )                                      # foreign
        ( sessions_dir / "other.json" ).write_text( "{}" )                                            # foreign
        ( sessions_dir / "cc-4242424.json" ).write_text( "{not json" )                                # corrupt, dead pid

        unreadable = []
        sessions   = sb.find_active_sessions( require_persona=False, unreadable_out=unreadable )
        old        = _old_counts( sessions, unreadable )
        new        = fleet_size_cap.census( sessions, fleet_size_cap.counting_classifier_for( sessions ),
                                            unreadable=len( unreadable ) )
        assert old == new == { "total": 3, "managers": 2, "workers": 1, "unknown": 0 }, ( old, new )
        assert arbiter._live_fleet_counts() == new
    finally:
        for p in live_procs:
            p.terminate()
            p.wait()


# ────────────── (c) the path map reads each seat's OWN file ──────────────

def test_two_seats_sharing_an_eight_character_prefix_are_each_read_from_their_own_file( sessions_dir, no_pid_check, monkeypatch ):
    _plant( sessions_dir, "cc-10001.json", "abcdef12-0000-4000-8000-00000000000a", role="manager" )
    _plant( sessions_dir, "cc-10002.json", "abcdef12-1111-4000-8000-00000000000b", role="author", spawned_by="abcdef12" )
    _plant( sessions_dir, "cc-10003.json", "99999999-0000-4000-8000-00000000000c", role="author", spawned_by="abcdef12" )
    sessions = sb.find_active_sessions( require_persona=False )
    assert len( sessions ) == 3

    classify = fleet_size_cap.counting_classifier_for( sessions )
    by_id    = { sid: classify( sid ) for _, sid, _ in sessions }
    assert by_id == { "abcdef12-0000-4000-8000-00000000000a": "manager",
                      "abcdef12-1111-4000-8000-00000000000b": "worker",
                      "99999999-0000-4000-8000-00000000000c": "worker" }, by_id

    # The old route resolved the second seat by its 8-char prefix, and the first bridge in
    # glob order wins. Pin glob order to name order so the difference is deterministic: the
    # old classifier reads seat A's file for seat B and calls B a manager (WRONG); the path
    # map calls it a worker (RIGHT, per its own file).
    real_iter = sb.iter_live_bridges
    monkeypatch.setattr( sb, "iter_live_bridges", lambda: iter( sorted( real_iter(), key=lambda t: t[ 0 ].name ) ) )
    assert fleet_size_cap.default_counting_classifier( "abcdef12-1111-4000-8000-00000000000b" ) == "manager"
    assert fleet_size_cap.census( sessions, classify )[ "managers" ] == 1


def test_a_session_with_no_known_path_classifies_as_unknown_and_bare_ids_are_tolerated():
    classify = fleet_size_cap.counting_classifier_for( [ ( "/nope/cc-1.json", "sid-1", {} ), "bare-id", ( "p", ) ] )
    assert classify( "sid-2" ) == fleet_size_cap.SEAT_UNKNOWN
    assert classify( "bare-id" ) == fleet_size_cap.SEAT_UNKNOWN
    assert classify( "sid-1" ) == fleet_size_cap.SEAT_UNKNOWN      # path does not exist


# ──────────────── (d) the handler does not block the event loop ────────────────

def test_the_dial_handlers_are_plain_functions_so_they_run_in_the_threadpool():
    assert not inspect.iscoroutinefunction( arbiter.get_fleet_size_cap )
    assert not inspect.iscoroutinefunction( arbiter.put_fleet_size_cap )


def test_a_slow_census_does_not_stall_the_event_loop( monkeypatch ):
    monkeypatch.setattr( arbiter, "_fleet_size_cap_payload", lambda: time.sleep( 1.0 ) or { "cap": 8, "ceiling": 18, "live": None } )
    app = FastAPI()
    app.include_router( arbiter.router )
    app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "test-user"

    @app.get( "/ping" )
    async def ping():
        return { "ok": True }

    async def drive():
        async with httpx.AsyncClient( transport=httpx.ASGITransport( app=app ), base_url="http://t" ) as c:
            slow = asyncio.create_task( c.get( "/api/arbiter/fleet-size-cap" ) )
            # The clock starts BEFORE the yield: if the handler blocks the loop, even this
            # sleep cannot resume until the census returns, so the elapsed time shows it.
            t0 = time.monotonic()
            await asyncio.sleep( 0.1 )                          # let the slow call start
            r  = await c.get( "/ping" )
            took = time.monotonic() - t0
            await slow
            return r.status_code, took

    status, took = asyncio.run( drive() )
    assert status == 200
    assert took < 0.5, f"a trivial GET waited {took:.2f}s behind the census: the loop is blocked"
