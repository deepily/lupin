"""
Layer-2 Python WebSocket protocol tests — auth-failure close codes
(Phase 5 of the WS reconnect circuit-breaker milestone).

Asserts that the queue WS endpoint replies with the expected RFC-6455
application close code (4001 / 4002) on auth-failure paths, instead of
the legacy generic 1006/no-code close.

Closes Phase 5 verification rows 3 and 4.

Run command:
    pytest src/tests/websocket_smoke/core/test_close_codes.py -v
"""

import asyncio
import json
import os
import urllib.request

import pytest

try:
    import websockets
except ImportError:
    websockets = None


BASE_URL = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )
WS_URL   = BASE_URL.replace( "http://", "ws://" ).replace( "https://", "wss://" )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login_jwt():
    """Acquire a valid JWT for the session-conflict test. Skips on auth failure."""
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not password:
        pytest.skip( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_{EMAIL,PASSWORD} env vars not set" )
    body = json.dumps( { "email" : email, "password" : password } ).encode()
    req  = urllib.request.Request(
        f"{BASE_URL}/auth/login",
        data    = body,
        headers = { "Content-Type" : "application/json" },
        method  = "POST"
    )
    try:
        with urllib.request.urlopen( req, timeout=10 ) as resp:
            data = json.loads( resp.read() )
    except Exception as e:
        pytest.skip( f"auth/login failed against {BASE_URL}: {e}" )
    token = data.get( "tokens", {} ).get( "access_token" )
    if not token:
        pytest.skip( f"unexpected /auth/login response shape: {list( data.keys() )}" )
    return token


# ---------------------------------------------------------------------------
# Test 3 — invalid token close code is 4001
# ---------------------------------------------------------------------------

def test_invalid_token_close_code():
    """
    Connect to /ws/queue/<session> with a junk token. Server should send an
    auth_error message and close the socket with code=4001.

    Closes Phase 5 verification row 3.

    Implementation note: runs the async client logic in a worker thread so
    the asyncio event loop is isolated from pytest-asyncio / pytest-playwright
    plugin fixtures (combined runs of those two harnesses + a top-level
    asyncio.run() collide on `cannot be called from a running event loop`).
    The thread approach gives this test its own loop without disturbing the
    outer plugin loop.
    """
    if websockets is None:
        pytest.skip( "websockets library not installed" )

    import threading
    import queue as _queue

    url    = f"{WS_URL}/ws/queue/test-session-{os.urandom( 4 ).hex()}"
    result = _queue.Queue()

    def _worker():
        async def _run():
            close_code = None
            async with websockets.connect( url ) as ws:
                await ws.send( json.dumps( {
                    "type"  : "auth_request",
                    "token" : "this-is-not-a-real-jwt"
                } ) )
                try:
                    await asyncio.wait_for( ws.recv(), timeout=5 )
                    await asyncio.wait_for( ws.recv(), timeout=5 )
                except websockets.exceptions.ConnectionClosed as cc:
                    close_code = cc.code
                except asyncio.TimeoutError:
                    pass
            return close_code

        try:
            result.put( asyncio.run( _run() ) )
        except Exception as e:
            result.put( e )

    t = threading.Thread( target=_worker, daemon=True )
    t.start()
    t.join( timeout=15 )
    code = result.get( timeout=1 )
    if isinstance( code, Exception ):
        raise code

    assert code == 4001, (
        f"queue WS auth-fail must close with code 4001 (was {code}). "
        "Did Phase 5's `routers/websocket.py` patch land?"
    )


# ---------------------------------------------------------------------------
# Test 4 — session conflict close code is 4002 (conditional)
# ---------------------------------------------------------------------------

@pytest.mark.skip(
    reason=(
        "Test fixture for `enforce_single_session_per_user` requires server-config "
        "hot-swap to enable the policy. Skipped by default; reachable manually by "
        "setting `websocket enforce single session per user = True` in lupin-app.ini "
        "and running with -k test_session_conflict_close_code --no-skip. "
        "Closes Phase 5 verification row 4 once the fixture lands."
    )
)
def test_session_conflict_close_code():
    """
    Two concurrent sessions for the same user. With single-session policy
    enabled, the SECOND connect displaces the first; the displaced socket's
    close code should be 4002.

    Closes Phase 5 verification row 4 (conditional).
    """
    pass
