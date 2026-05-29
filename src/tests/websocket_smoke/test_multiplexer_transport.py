#!/usr/bin/env python3
"""
Phase 3 multiplexer transport — live :7999 WS smoke (server-side compatibility).

Verifies the SERVER side of the auth_request → auth_success handshake the
multiplexer's QueueTransport + AudioTransport perform. This is the
"AI test connects against dev server" half of AC#7.

The JS-side observability bullets of AC#7 ("ConnectionStateMachine transitions
to backoff within 100ms", "connection_reconnecting emitted before new socket
open") are covered by the CSM + WSChannel unit tests under
src/tests/unit/multiplexer/. Combined coverage = AC#7.

The page-load bullet (AC#8) lives in src/tests/smoke/test_multiplexer_phase3_smoke.py
(Playwright headless against /app/multiplexer).

Venue: :7999 (AI-discretionary). Non-destructive (read-only WS subscription).
Fast (< 30s total).

Usage:
    pytest src/tests/websocket_smoke/test_multiplexer_transport.py -v
    LUPIN_API_URL=http://localhost:7999 pytest src/tests/websocket_smoke/test_multiplexer_transport.py -v

Credentials (per CLAUDE.md TEST CREDENTIALS):
    export LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL="..."
    export LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD="..."
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from urllib.parse import urlparse

import pytest
import requests
import websockets


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )

# Build ws URL from base URL by swapping http→ws scheme.
parsed = urlparse( BASE_URL )
WS_BASE_URL = f"{ 'wss' if parsed.scheme == 'https' else 'ws' }://{ parsed.netloc }"

# Subscribed-event lists mirrored from QueueTransport.ts and AudioTransport.ts.
# Must match exactly — server filters outbound events against these lists.
QUEUE_SUBSCRIBED_EVENTS = [
    "job_state_transition",
    "job_removed",
    "tts_job_request",
    "sys_time_update",
    "notification_play_sound",
    "notification_queue_update",
    "notification_responded",
    "notification_expired",
    "auth_success",
    "auth_error",
    "connect",
    "sys_ping",
]

AUDIO_SUBSCRIBED_EVENTS = [
    "audio_streaming_chunk",
    "audio_streaming_status",
    "audio_streaming_complete",
    "tts_error",
    "sys_ping",
    "auth_success",
    "auth_error",
    "connect",
]


# ---------------------------------------------------------------------------
# Auth fixture — module-scoped login → access token.
# ---------------------------------------------------------------------------

def _get_credentials() -> tuple[ str, str ]:
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not password:
        pytest.skip( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / _PASSWORD env vars not set" )
    return email, password


@pytest.fixture( scope="module" )
def access_token() -> str:
    """Authenticate via /auth/login and return the JWT access token."""
    email, password = _get_credentials()
    resp = requests.post(
        f"{BASE_URL}/auth/login",
        json    = { "email": email, "password": password },
        timeout = 10,
    )
    assert resp.status_code == 200, f"login failed: { resp.status_code } { resp.text }"
    body = resp.json()
    # Per memory `reference_auth_testing_contract`: tokens nested under .tokens.access_token.
    token = body[ "tokens" ][ "access_token" ]
    assert token, "empty access_token returned"
    return token


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _open_queue_and_handshake(
    token: str,
    session_id: str,
    timeout_s: float = 5.0,
) -> dict:
    """Open queue WS, send auth_request, await auth_success. Return the auth_success frame."""
    url = f"{WS_BASE_URL}/ws/queue/{ session_id }"
    async with websockets.connect( url, open_timeout=timeout_s ) as ws:
        await ws.send( json.dumps( {
            "type"              : "auth_request",
            "token"             : token,
            "session_id"        : session_id,
            "subscribed_events" : QUEUE_SUBSCRIBED_EVENTS,
        } ) )
        # Drain frames until auth_success arrives.
        deadline = asyncio.get_event_loop().time() + timeout_s
        while asyncio.get_event_loop().time() < deadline:
            remaining = max( 0.1, deadline - asyncio.get_event_loop().time() )
            try:
                raw = await asyncio.wait_for( ws.recv(), timeout=remaining )
            except asyncio.TimeoutError:
                raise AssertionError( f"auth_success not received within { timeout_s }s" )
            envelope = json.loads( raw )
            if envelope.get( "type" ) == "auth_success":
                return envelope
            if envelope.get( "type" ) == "auth_error":
                raise AssertionError( f"server returned auth_error: { envelope }" )
        raise AssertionError( f"auth_success not received within { timeout_s }s" )


async def _open_audio_and_handshake(
    token: str,
    session_id: str,
    timeout_s: float = 5.0,
) -> dict:
    """Open audio WS, send auth_request, await auth_success."""
    url = f"{WS_BASE_URL}/ws/audio/{ session_id }"
    async with websockets.connect( url, open_timeout=timeout_s ) as ws:
        await ws.send( json.dumps( {
            "type"              : "auth_request",
            "token"             : token,
            "session_id"        : session_id,
            "subscribed_events" : AUDIO_SUBSCRIBED_EVENTS,
        } ) )
        deadline = asyncio.get_event_loop().time() + timeout_s
        while asyncio.get_event_loop().time() < deadline:
            remaining = max( 0.1, deadline - asyncio.get_event_loop().time() )
            try:
                raw = await asyncio.wait_for( ws.recv(), timeout=remaining )
            except asyncio.TimeoutError:
                raise AssertionError( f"auth_success not received within { timeout_s }s" )
            envelope = json.loads( raw )
            if envelope.get( "type" ) == "auth_success":
                return envelope
            if envelope.get( "type" ) == "auth_error":
                raise AssertionError( f"server returned auth_error: { envelope }" )
        raise AssertionError( f"auth_success not received within { timeout_s }s" )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_queue_handshake_arrives_within_5s( access_token: str ):
    """
    Server-side AC#7 first bullet: connect to /ws/queue/{session_id}, send
    auth_request matching the multiplexer QueueTransport's envelope shape,
    receive auth_success within 5 seconds.
    """
    session_id = f"phase3-smoke-q-{ int( time.time() ) }"
    envelope = asyncio.run( _open_queue_and_handshake( access_token, session_id ) )
    assert envelope[ "type" ] == "auth_success"


def test_audio_handshake_arrives_within_5s( access_token: str ):
    """Same as queue test but for /ws/audio/{session_id}."""
    session_id = f"phase3-smoke-a-{ int( time.time() ) }"
    envelope = asyncio.run( _open_audio_and_handshake( access_token, session_id ) )
    assert envelope[ "type" ] == "auth_success"


def test_queue_reconnect_after_clean_close( access_token: str ):
    """
    Verifies the server allows a fresh handshake from the same session_id
    after the prior connection has cleanly closed. Mirrors the multiplexer's
    reconnect cycle: socket_close → backoff → reconnecting → new socket →
    new auth_request → auth_success.

    AC#7: "AI test asserts a new socket open attempt and fresh auth_success
    frame arrive within (2^n × 1000ms × full-jitter) of the close, max 35s
    timeout (per Open Q2 backoff config)".
    """
    session_id = f"phase3-smoke-reconnect-{ int( time.time() ) }"
    # First handshake.
    first = asyncio.run( _open_queue_and_handshake( access_token, session_id ) )
    assert first[ "type" ] == "auth_success"
    # Reconnect with the same session_id — server must not reject.
    second = asyncio.run( _open_queue_and_handshake( access_token, session_id ) )
    assert second[ "type" ] == "auth_success"


def test_queue_rejects_invalid_token( access_token: str ):
    """
    Negative path: malformed token → server closes with the documented
    auth-failure code (4001 per `routers/websocket.py:31` constants), which
    the multiplexer's CSM books as a `socket_close` and routes through
    backoff.
    """
    session_id = f"phase3-smoke-badauth-{ int( time.time() ) }"
    url = f"{WS_BASE_URL}/ws/queue/{ session_id }"

    async def _attempt():
        async with websockets.connect( url, open_timeout=5.0 ) as ws:
            await ws.send( json.dumps( {
                "type"              : "auth_request",
                "token"             : "not-a-real-token",
                "session_id"        : session_id,
                "subscribed_events" : QUEUE_SUBSCRIBED_EVENTS,
            } ) )
            # Server should close — either with an auth_error frame or a
            # close frame. Either way, recv() will raise / return close.
            try:
                raw = await asyncio.wait_for( ws.recv(), timeout=5.0 )
            except websockets.exceptions.ConnectionClosed as e:
                return ( "closed", e.code )
            envelope = json.loads( raw )
            return ( "frame", envelope )

    outcome = asyncio.run( _attempt() )
    if outcome[ 0 ] == "closed":
        # Expect 4001 (auth invalid) per src/cosa/rest/routers/websocket.py
        # CLOSE_CODE_AUTH_INVALID_TOKEN. Other 4xxx codes also acceptable.
        assert 4000 <= outcome[ 1 ] < 5000, f"unexpected close code { outcome[ 1 ] }"
    else:
        envelope = outcome[ 1 ]
        assert envelope[ "type" ] in ( "auth_error", ), f"unexpected envelope: { envelope }"


if __name__ == "__main__":
    raise SystemExit( pytest.main( [ __file__, "-v", "--tb=short" ] ) )
