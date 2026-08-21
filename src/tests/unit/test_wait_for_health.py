#!/usr/bin/env python3
"""
Unit tests: wait-for-health.sh requires N successes IN A ROW.

THE DEFECT THIS GUARDS ( row 1c36199e ): a liveness reader that trusts ONE health 200
is wrong in two directions we have both hit. Too early — the OLD process still answers
in the moment after `docker restart` is issued (Tiberius, :7999, 2026-08-19). Too noisy —
a loaded server answers in bursts, so one call is a coin flip (:8000 under a monopolize
run: /health at 0.47s, then a timeout 36 seconds later).

Every test below drives the real script against a real local HTTP server whose answers
are scripted. The bounce script itself is never run — it restarts a container and
broadcasts to the fleet, and a test must never need either.
"""
import http.server
import os
import subprocess
import threading

import pytest

SCRIPT = os.path.join( os.environ[ "LUPIN_ROOT" ], "src/scripts/lib/wait-for-health.sh" )


class _ScriptedHealth( http.server.BaseHTTPRequestHandler ):
    """Answers with the next code in the class-level script; repeats the last one forever."""

    codes = [ 200 ]
    hits  = 0

    def do_GET( self ):
        cls      = type( self )
        index    = min( cls.hits, len( cls.codes ) - 1 )
        code     = cls.codes[ index ]
        cls.hits += 1
        self.send_response( code )
        self.send_header( "Content-Length", "2" )
        self.end_headers()
        self.wfile.write( b"ok" )

    def log_message( self, *args ):
        pass                                   # keep pytest output clean


@pytest.fixture
def health_server():
    """Start a scripted health endpoint; yields (url, handler_class)."""
    handler = type( "Scripted", ( _ScriptedHealth, ), { "codes": [ 200 ], "hits": 0 } )
    server  = http.server.HTTPServer( ( "127.0.0.1", 0 ), handler )
    thread  = threading.Thread( target=server.serve_forever, daemon=True )
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/health", handler
    finally:
        server.shutdown()
        server.server_close()


def _run( url, *args, timeout=30 ):
    return subprocess.run(
        [ "bash", SCRIPT, url, "--interval", "0.05", *args ],
        capture_output=True, text=True, timeout=timeout
    )


def test_a_steady_server_passes( health_server ):
    url, handler = health_server
    handler.codes = [ 200 ]
    result = _run( url, "--consecutive", "3", "--timeout", "10" )
    assert result.returncode == 0, result.stderr
    assert handler.hits >= 3, "passed without actually making three calls"


def test_one_lucky_200_is_not_enough( health_server ):
    """THE POINT OF THE FILE. 200 then failures forever must NOT be accepted."""
    url, handler = health_server
    handler.codes = [ 200, 500 ]               # one success, then 500 forever
    result = _run( url, "--consecutive", "3", "--timeout", "3" )
    assert result.returncode == 1, "a single 200 was accepted as healthy"
    assert "did not reach 3 consecutive" in result.stderr


def test_a_broken_streak_restarts_the_count( health_server ):
    """200,200,500,... must fail: two in a row is not three, and the 500 resets it."""
    url, handler = health_server
    handler.codes = [ 200, 200, 500 ]
    result = _run( url, "--consecutive", "3", "--timeout", "3" )
    assert result.returncode == 1, "a broken streak was counted as continuous"
    assert "streak broken at 2/3" in result.stdout


def test_it_recovers_once_the_server_settles( health_server ):
    """500s first, then steady 200s — the wait must succeed, not give up early."""
    url, handler = health_server
    handler.codes = [ 500, 500, 500, 200 ]
    result = _run( url, "--consecutive", "3", "--timeout", "10" )
    assert result.returncode == 0, result.stderr


def test_consecutive_one_reproduces_the_old_defect( health_server ):
    """
    THE CONTROL. With --consecutive 1 the script accepts the single lucky 200 — i.e. it
    behaves exactly like the code this replaces. If this test ever goes red the guard is
    no longer the thing doing the work in the test above.
    """
    url, handler = health_server
    handler.codes = [ 200, 500 ]
    result = _run( url, "--consecutive", "1", "--timeout", "3" )
    assert result.returncode == 0, "even --consecutive 1 rejected a first 200 — the test is measuring something else"


def test_a_dead_port_fails_rather_than_hanging():
    """Nothing listening at all must exit 1 on the deadline, not hang."""
    result = _run( "http://127.0.0.1:1/health", "--consecutive", "2", "--timeout", "2" )
    assert result.returncode == 1
    assert "best streak ended at 0" in result.stderr


@pytest.mark.parametrize( "bad", [ "0", "-1", "three" ] )
def test_a_nonsense_streak_is_refused( bad ):
    """A bad --consecutive must be a usage error, never a silent fallback to 1."""
    result = _run( "http://127.0.0.1:1/health", "--consecutive", bad, "--timeout", "2" )
    assert result.returncode == 2
    assert "positive integer" in result.stderr
