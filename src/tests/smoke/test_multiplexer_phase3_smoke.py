#!/usr/bin/env python3
"""
Phase 3 multiplexer page-load smoke (AC#8 + AC#7 positive path via observable WS frames).

Verifies:
  AC#8 — load /app/multiplexer in Playwright headless; QueueTransport +
         AudioTransport reach `transport_ready` within 10s; no transport-related
         console errors.
  AC#7 — observable side: auth_request → auth_success roundtrip on both
         queue and audio sockets.

The reconnect-after-disconnect bullets of AC#7 are covered by the
ConnectionStateMachine unit tests under src/tests/unit/multiplexer/. The
server-side server-compatibility bullets are covered by
src/tests/websocket_smoke/test_multiplexer_transport.py.

Venue: :7999 (AI-discretionary). Non-destructive.

Usage:
    pytest src/tests/smoke/test_multiplexer_phase3_smoke.py -v
"""

from __future__ import annotations

import os
import time

import pytest

from tests.smoke.multiplexer_auth import login_tokens, seed_multiplexer_auth


BASE_URL = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )


def test_phase3_page_load_transports_reach_auth_success():
    """
    AC#8:
      - Load /app/multiplexer in Playwright headless.
      - Both queue + audio WSs open.
      - Both receive `auth_success` frames within 10s.
      - No console errors related to transports.
    """
    from playwright.sync_api import sync_playwright

    auth_tokens = login_tokens()

    queue_ws_seen      : list[ object ]   = []
    audio_ws_seen      : list[ object ]   = []
    queue_auth_success : list[ str ]      = []
    audio_auth_success : list[ str ]      = []
    console_errors     : list[ str ]      = []

    with sync_playwright() as p:
        browser = p.chromium.launch( headless=True )
        try:
            context = browser.new_context()

            # Inject the multiplexer's expected localStorage key BEFORE the
            # page script runs. The init script runs on every navigation;
            # because we set it before page.goto, AuthManager will hydrate
            # from this token on construction.
            seed_multiplexer_auth( context, auth_tokens )

            page = context.new_page()

            # WebSocket lifecycle hook — captures every WS the page opens.
            def _on_ws( ws ):
                url = ws.url
                if "/ws/queue/" in url:
                    queue_ws_seen.append( ws )
                    ws.on( "framereceived", lambda payload: _on_queue_frame( payload ) )
                elif "/ws/audio/" in url:
                    audio_ws_seen.append( ws )
                    ws.on( "framereceived", lambda payload: _on_audio_frame( payload ) )

            def _on_queue_frame( payload ):
                # Playwright Python frames-received payload may be a string
                # (text frame) or bytes (binary).
                text = _coerce_to_text( payload )
                if text and '"auth_success"' in text:
                    queue_auth_success.append( text )

            def _on_audio_frame( payload ):
                text = _coerce_to_text( payload )
                if text and '"auth_success"' in text:
                    audio_auth_success.append( text )

            page.on( "websocket", _on_ws )

            # Capture console errors.
            page.on( "console", lambda msg: (
                console_errors.append( msg.text ) if msg.type == "error" else None
            ) )

            page.goto( f"{BASE_URL}/app/multiplexer", wait_until="domcontentloaded", timeout=15_000 )

            # Wait up to 10s for both auth_success frames.
            deadline = time.time() + 10.0
            while time.time() < deadline:
                if queue_auth_success and audio_auth_success:
                    break
                page.wait_for_timeout( 100 )

            assert queue_ws_seen, "no /ws/queue/ WebSocket opened"
            assert audio_ws_seen, "no /ws/audio/ WebSocket opened"
            assert queue_auth_success, (
                f"queue auth_success not received within 10s; "
                f"queue WS count={ len( queue_ws_seen ) }, console errors={ console_errors }"
            )
            assert audio_auth_success, (
                f"audio auth_success not received within 10s; "
                f"audio WS count={ len( audio_ws_seen ) }, console errors={ console_errors }"
            )

            # No transport-related console errors. Filter for transport-ish
            # keywords so we don't fail on unrelated page noise (e.g. CSS warnings).
            transport_errs = [
                e for e in console_errors
                if any( kw in e.lower() for kw in (
                    "queuetransport", "audiotransport",
                    "websocket", "connectionstatemachine", "auth_request",
                ) )
            ]
            assert not transport_errs, (
                f"transport-related console errors: { transport_errs }"
            )

        finally:
            browser.close()


def _coerce_to_text( payload ) -> str:
    """Playwright framereceived payload may arrive as str or bytes."""
    if isinstance( payload, str ):
        return payload
    if isinstance( payload, ( bytes, bytearray ) ):
        try:
            return payload.decode( "utf-8" )
        except UnicodeDecodeError:
            return ""
    # Some Playwright versions wrap as {"payload": str}.
    if isinstance( payload, dict ):
        inner = payload.get( "payload" )
        if isinstance( inner, str ):
            return inner
    return ""


if __name__ == "__main__":
    raise SystemExit( pytest.main( [ __file__, "-v", "--tb=short" ] ) )
