#!/usr/bin/env python3
"""
E2E — Multiplexer Lane E WP13: TTS preview-fraction slider (F6).

Exercises TtsPreviewSliderRenderer end-to-end: the 9-stop / 12.5% range input,
the datalist tick track, the live value label, StorageService persistence of a
runtime override, and re-seed from a stored override on reload.

Venue: :8000 (monopolize, scheduled) — `test_multiplexer_*` E2E batch. Authored
by Lane E; RUN by the manager. Per CLAUDE.local.md "USER IS NEVER A TESTER":
every assertion is AI.

Usage:
    pytest src/tests/e2e_ui/test_multiplexer_tts_controls.py -v
    LUPIN_API_URL=http://localhost:8000 pytest src/tests/e2e_ui/test_multiplexer_tts_controls.py -v
"""

from __future__ import annotations

import json
import os

import pytest
import requests

BASE_URL        = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )
MULTIPLEXER_URL = f"{BASE_URL}/app/multiplexer"

# StorageService envelope key for the runtime override (lupin: prefix + schema 1).
TTS_STORAGE_KEY = "lupin:tts_preview_fraction"


def _get_credentials() -> tuple[ str, str ]:
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not password:
        pytest.skip( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / _PASSWORD env vars not set" )
    return email, password


def _login_tokens() -> tuple[ str, str ]:
    email, password = _get_credentials()
    resp = requests.post(
        f"{BASE_URL}/auth/login",
        json    = { "email": email, "password": password },
        timeout = 10,
    )
    assert resp.status_code == 200, f"login failed: { resp.status_code } { resp.text }"
    tokens = resp.json()[ "tokens" ]
    return tokens[ "access_token" ], tokens[ "refresh_token" ]


def _seed_auth( context, access_token: str, refresh_token: str ) -> None:
    context.add_init_script(
        f"window.localStorage.setItem('lupin_access_token', { json.dumps( access_token ) });"
        f"window.localStorage.setItem('lupin_refresh_token', { json.dumps( refresh_token ) });"
    )


def _wait_for_test_hook( page, timeout_ms: int = 10_000 ) -> None:
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=timeout_ms,
    )


def _storage_envelope( fraction: float ) -> str:
    """The StorageService.setJSON envelope shape for the override key."""
    return json.dumps( { "schemaVersion": 1, "payload": { "fraction": fraction }, "ts": 0 } )


class TestTTSFractionSlider:
    """WP13 (F6) — 12.5%-step slider + datalist + persistence."""

    def _open( self, pw, *, pre_override: float | None = None ):
        access, refresh = _login_tokens()
        browser = pw.chromium.launch( headless=True, args=[ "--autoplay-policy=no-user-gesture-required" ] )
        context = browser.new_context()
        _seed_auth( context, access, refresh )
        if pre_override is not None:
            context.add_init_script(
                f"window.localStorage.setItem('{TTS_STORAGE_KEY}', { json.dumps( _storage_envelope( pre_override ) ) });"
            )
        page = context.new_page()
        page.goto( MULTIPLEXER_URL, wait_until="networkidle", timeout=15_000 )
        _wait_for_test_hook( page )
        page.wait_for_selector( "#tts-preview-slider-mount .tts-preview-slider", timeout=3000 )
        return browser, page

    def test_slider_has_nine_stops_at_12_5_step(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser, page = self._open( pw )
            try:
                inp = page.locator( ".tts-preview-slider-input" )
                assert inp.get_attribute( "type" ) == "range"
                assert inp.get_attribute( "min" ) == "0"
                assert inp.get_attribute( "max" ) == "100"
                assert inp.get_attribute( "step" ) == "12.5"
                assert inp.get_attribute( "list" ) == "cc-tts-fraction-ticks"
                assert page.locator( ".tts-preview-slider-ticks option" ).count() == 9
            finally:
                browser.close()

    def test_moving_slider_updates_label_and_persists_override(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser, page = self._open( pw )
            try:
                # Drive an off-integer stop (62.5%) — parseFloat must not truncate.
                page.locator( ".tts-preview-slider-input" ).evaluate(
                    "el => { el.value = '62.5'; el.dispatchEvent( new Event( 'input', { bubbles: true } ) ); }"
                )
                assert page.locator( ".tts-preview-slider-value" ).text_content() == "62.5%"
                stored = page.evaluate( f"() => window.localStorage.getItem('{TTS_STORAGE_KEY}')" )
                assert stored is not None
                assert json.loads( stored )[ "payload" ][ "fraction" ] == 0.625
            finally:
                browser.close()

    def test_stored_override_seeds_slider_on_reload(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser, page = self._open( pw, pre_override=0.875 )
            try:
                assert page.locator( ".tts-preview-slider-input" ).input_value() == "87.5"
                assert page.locator( ".tts-preview-slider-value" ).text_content() == "87.5%"
            finally:
                browser.close()
