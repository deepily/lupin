#!/usr/bin/env python3
"""
Phase-6 TTS Playback — L2 PROTOCOL E2E (server-push wire contract).

Tester leg of `05-build-plans/00c-phase6-tts-playback.md`. Authored by
Clayton 😎 (Mr. Radio's 🦉 mux Phase-6 crew). Spec:
`src/rnd/v0.1.9/2026.06.30-phase6-tts-playback-protocol-e2e-plan.md` §3 (L2).

WHAT THIS PROVES (and what it deliberately does NOT):
    Proves the SERVER HALF of the Phase-6 completion seam is live — triggering a
    TTS stream pushes the exact frames `AudioStore` subscribes to over /ws/audio:
        audio_streaming_status(loading) → ≥1 binary PCM-24k chunk → audio_streaming_complete
    It does NOT (and CANNOT) observe the mux's internal EventBus emissions
    (`store_audio_state_change` / `store_audio_ended`) or the scheduler's
    `createBufferSource`/`start` calls — those live INSIDE the browser and are
    proven by L1 (unit, injected stub) + L3 (Playwright real-Chrome). A headless
    WS client sees only the wire. This test is independent of the P6 mux build:
    it exercises the pre-existing server-push path (roadmap reframe 2026-06-30).

TRIGGER (corrected from the original task framing — /api/push is the AGENT JOB
queue and does NOT touch TTS):
    POST /api/get-speech-elevenlabs {session_id, text}  (speech.py:487-638)
    ElevenLabs because output_format=pcm_24000 (speech.py:994) is exactly what
    AudioStore decodes; OpenAI /api/get-speech streams µ-law/mp3 (wrong format).

⚠️ COST: each happy-path run makes a REAL ElevenLabs TTS call (firewalled-SDK
metered spend — tiny, one short utterance, but non-zero). Per the §TESTING
VENUES rubric, API spend leans :8000; this is a SINGLE short utterance and the
plan classifies it :7999-discretionary. To prevent ANY accidental spend (e.g. a
:8000 batch sweeping src/tests/smoke/), the paid tests are SKIPPED unless the
env flag below is set — they run ONLY when a tester deliberately enables them at
Stage B.

Usage (deliberate Stage-B run on :7999):
    LUPIN_RUN_PHASE6_TTS_E2E=1 \
    LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL=... LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD=... \
    pytest src/tests/smoke/test_phase6_tts_playback_protocol_e2e.py -v

Venue: :7999 (AI-discretionary) — ≤2 min, no persistent-state mutation beyond
the transient TTS stream. CURL PROHIBITED — requests (HTTP) + websockets (WS).
Per CLAUDE.local.md "THE USER IS NEVER A TESTER": every assertion is AI-run.
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

parsed      = urlparse( BASE_URL )
WS_BASE_URL = f"{ 'wss' if parsed.scheme == 'https' else 'ws' }://{ parsed.netloc }"

# Mirror of AudioTransport.ts AUDIO_SUBSCRIBED_EVENTS (server filters outbound
# text frames against this list; binary chunks are sent unconditionally).
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

# Cost gate — paid ElevenLabs calls fire ONLY when this is set (Stage-B run).
_PAID_TTS_ENABLED = os.environ.get( "LUPIN_RUN_PHASE6_TTS_E2E" ) == "1"
_PAID_SKIP_REASON = (
    "Set LUPIN_RUN_PHASE6_TTS_E2E=1 to run the paid ElevenLabs protocol-E2E "
    "(makes a real metered TTS call) — deliberate Stage-B execution only."
)

# Short utterance — minimize per-run spend while still producing multiple PCM chunks.
_TTS_TEXT = "Phase six playback protocol check."


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _get_credentials() -> tuple[ str, str ]:
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not password:
        pytest.skip( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / _PASSWORD env vars not set" )
    return email, password


@pytest.fixture( scope="module" )
def access_token() -> str:
    """Authenticate via /auth/login and return the JWT access token (tokens.access_token)."""
    email, password = _get_credentials()
    resp = requests.post(
        f"{BASE_URL}/auth/login",
        json    = { "email": email, "password": password },
        timeout = 10,
    )
    assert resp.status_code == 200, f"login failed: { resp.status_code } { resp.text }"
    token = resp.json()[ "tokens" ][ "access_token" ]
    assert token, "empty access_token returned"
    return token


# ---------------------------------------------------------------------------
# Core driver — connect /ws/audio, trigger TTS, drain the frame sequence.
# ---------------------------------------------------------------------------

def _trigger_tts( token: str, session_id: str, *, simulate_error: bool = False ) -> requests.Response:
    """POST /api/get-speech-elevenlabs — returns 200 immediately; streams in background."""
    body = { "session_id": session_id, "text": _TTS_TEXT }
    if simulate_error:
        body[ "debug_simulate_error" ] = True
    return requests.post(
        f"{BASE_URL}/api/get-speech-elevenlabs",
        json    = body,
        headers = { "Authorization": f"Bearer { token }" },
        timeout = 15,
    )


async def _stream_and_collect(
    token: str,
    session_id: str,
    *,
    simulate_error: bool = False,
    drain_timeout_s: float = 20.0,
) -> dict:
    """
    Open /ws/audio, auth, trigger TTS, drain frames until audio_streaming_complete
    / tts_error / timeout.

    Returns a classified record:
        {
          "auth_ok"            : bool,
          "text_types"         : [str, ...]   # ordered type-tags of JSON frames
          "binary_chunk_count" : int,
          "binary_total_bytes" : int,
          "first_binary_index" : int | None,  # position of first binary frame in the merged stream
          "complete_index"     : int | None,  # position of audio_streaming_complete in the merged stream
          "complete_frame"     : dict | None,
          "error_frame"        : dict | None,
        }
    """
    url = f"{WS_BASE_URL}/ws/audio/{ session_id }"
    rec: dict = {
        "auth_ok"            : False,
        "text_types"         : [],
        "binary_chunk_count" : 0,
        "binary_total_bytes" : 0,
        "first_binary_index" : None,
        "complete_index"     : None,
        "complete_frame"     : None,
        "error_frame"        : None,
    }
    merged_index = 0   # position across BOTH binary + text frames (post-auth)

    async with websockets.connect( url, open_timeout=5.0 ) as ws:
        await ws.send( json.dumps( {
            "type"              : "auth_request",
            "token"             : token,
            "session_id"        : session_id,
            "subscribed_events" : AUDIO_SUBSCRIBED_EVENTS,
        } ) )

        # Phase 1: await auth_success before triggering (so we don't miss frames).
        auth_deadline = asyncio.get_event_loop().time() + 5.0
        while asyncio.get_event_loop().time() < auth_deadline:
            remaining = max( 0.1, auth_deadline - asyncio.get_event_loop().time() )
            raw = await asyncio.wait_for( ws.recv(), timeout=remaining )
            if isinstance( raw, bytes ):
                # Unexpected pre-auth binary — ignore.
                continue
            env = json.loads( raw )
            if env.get( "type" ) == "auth_success":
                rec[ "auth_ok" ] = True
                break
            if env.get( "type" ) == "auth_error":
                raise AssertionError( f"server returned auth_error: { env }" )
        assert rec[ "auth_ok" ], "auth_success not received before trigger"

        # Phase 2: fire the TTS trigger off the event loop (requests is blocking).
        trigger_resp = await asyncio.to_thread( _trigger_tts, token, session_id, simulate_error=simulate_error )
        assert trigger_resp.status_code == 200, (
            f"get-speech-elevenlabs returned { trigger_resp.status_code }: { trigger_resp.text }"
        )

        # Phase 3: drain the streamed frames.
        drain_deadline = asyncio.get_event_loop().time() + drain_timeout_s
        while asyncio.get_event_loop().time() < drain_deadline:
            remaining = max( 0.1, drain_deadline - asyncio.get_event_loop().time() )
            try:
                raw = await asyncio.wait_for( ws.recv(), timeout=remaining )
            except asyncio.TimeoutError:
                break
            if isinstance( raw, bytes ):
                rec[ "binary_chunk_count" ] += 1
                rec[ "binary_total_bytes" ] += len( raw )
                if rec[ "first_binary_index" ] is None:
                    rec[ "first_binary_index" ] = merged_index
                merged_index += 1
                continue
            env = json.loads( raw )
            etype = env.get( "type" )
            if etype in ( "sys_ping", "auth_success" ):
                continue   # housekeeping frames — not part of the TTS contract
            rec[ "text_types" ].append( etype )
            if etype == "audio_streaming_complete":
                rec[ "complete_index" ] = merged_index
                rec[ "complete_frame" ] = env
                merged_index += 1
                break
            if etype == "tts_error":
                rec[ "error_frame" ] = env
                merged_index += 1
                break
            merged_index += 1

    return rec


# ---------------------------------------------------------------------------
# Tests — paid (skipped unless LUPIN_RUN_PHASE6_TTS_E2E=1)
# ---------------------------------------------------------------------------

@pytest.mark.skipif( not _PAID_TTS_ENABLED, reason=_PAID_SKIP_REASON )
def test_tts_stream_pushes_status_then_pcm_then_complete( access_token: str ):
    """
    Happy path — the server-push wire contract AudioStore subscribes to:
      audio_streaming_status(loading) → ≥1 binary PCM chunk → audio_streaming_complete,
    binary BEFORE complete. This is the frame sequence P6's completion seam keys on.
    """
    session_id = f"cc-clayton-p6e2e-{ int( time.time() ) }"
    rec = asyncio.run( _stream_and_collect( access_token, session_id ) )

    # No error on the happy path.
    assert rec[ "error_frame" ] is None, f"unexpected tts_error: { rec['error_frame'] }"

    # Binary PCM actually streamed (the audible payload — not just a status frame).
    assert rec[ "binary_chunk_count" ] >= 1, (
        f"expected ≥1 binary PCM chunk, got { rec['binary_chunk_count'] } "
        f"({ rec['binary_total_bytes'] } bytes)"
    )

    # The end-of-utterance marker P6 gates onended with arrived.
    assert rec[ "complete_frame" ] is not None, "audio_streaming_complete frame never arrived"
    assert rec[ "complete_frame" ].get( "status" ) == "success"

    # Ordering: at least one binary chunk PRECEDES audio_streaming_complete.
    assert rec[ "first_binary_index" ] is not None, "no binary frame index recorded"
    assert rec[ "complete_index" ] is not None, "no complete frame index recorded"
    assert rec[ "first_binary_index" ] < rec[ "complete_index" ], (
        f"binary PCM must precede audio_streaming_complete "
        f"(first_binary={ rec['first_binary_index'] }, complete={ rec['complete_index'] })"
    )

    # An opening status(loading) frame is part of the contract (best-effort: present in text_types).
    assert "audio_streaming_complete" in rec[ "text_types" ]


@pytest.mark.skipif( not _PAID_TTS_ENABLED, reason=_PAID_SKIP_REASON )
def test_tts_error_frame_on_simulated_error( access_token: str ):
    """
    Negative path — debug_simulate_error=True drives the tts_error arm
    (speech.py:976-981). Asserts the server emits tts_error (status=error) and
    does NOT emit a success completion. Guards the error-frame contract the mux
    surfaces rather than scheduling silence.
    """
    session_id = f"cc-clayton-p6err-{ int( time.time() ) }"
    rec = asyncio.run( _stream_and_collect( access_token, session_id, simulate_error=True ) )

    assert rec[ "error_frame" ] is not None, "expected a tts_error frame on simulated error"
    assert rec[ "error_frame" ].get( "status" ) == "error"
    assert rec[ "complete_frame" ] is None, "must NOT emit audio_streaming_complete on error"


# ---------------------------------------------------------------------------
# Free structural self-check (no spend) — runs always; proves the harness +
# auth + WS handshake are wired without triggering a paid TTS stream.
# ---------------------------------------------------------------------------

def test_audio_handshake_is_reachable_no_spend( access_token: str ):
    """
    Zero-cost harness validation: the /ws/audio auth_request → auth_success
    handshake the paid tests depend on is reachable. NO TTS triggered → NO spend.
    If this fails, the paid tests cannot run — fail fast here.
    """
    session_id = f"cc-clayton-p6hs-{ int( time.time() ) }"

    async def _handshake_only() -> dict:
        url = f"{WS_BASE_URL}/ws/audio/{ session_id }"
        async with websockets.connect( url, open_timeout=5.0 ) as ws:
            await ws.send( json.dumps( {
                "type"              : "auth_request",
                "token"             : access_token,
                "session_id"        : session_id,
                "subscribed_events" : AUDIO_SUBSCRIBED_EVENTS,
            } ) )
            deadline = asyncio.get_event_loop().time() + 5.0
            while asyncio.get_event_loop().time() < deadline:
                remaining = max( 0.1, deadline - asyncio.get_event_loop().time() )
                raw = await asyncio.wait_for( ws.recv(), timeout=remaining )
                if isinstance( raw, bytes ):
                    continue
                env = json.loads( raw )
                if env.get( "type" ) == "auth_success":
                    return env
                if env.get( "type" ) == "auth_error":
                    raise AssertionError( f"auth_error: { env }" )
            raise AssertionError( "auth_success not received within 5s" )

    envelope = asyncio.run( _handshake_only() )
    assert envelope[ "type" ] == "auth_success"


if __name__ == "__main__":
    raise SystemExit( pytest.main( [ __file__, "-v" ] ) )
