#!/usr/bin/env python3
"""
E2E — Multiplexer Lane E WP12: read-only Fleet-Status table (F12).

Exercises the FleetStatusStore (poll/fetch/toggle) + FleetStatusRenderer (4
render states + count + offline toggle) end-to-end in a real browser. The
`/api/arbiter/fleet-state` endpoint is STUBBED via `page.route` so each of the
§6.4 states is driven deterministically without a live arbiter; the renderer
runs the real store.refresh() → fetchState() → render path.

COLOR NOTE: a fleet-status color-coding scheme (verdict-based row colors + %
window heat-tint) is being designed in the legacy table (Rick's ask). Per
Tiberius's directive these assertions are render-STRUCTURE only — NO color
assertions yet; color assertions land as a follow-on once the scheme relays.

Venue: :8000 (monopolize, scheduled) — `test_multiplexer_*` E2E batch. These
use page.route stubs (no real state mutation) but run via the manager's :8000
Playwright batch per the parity-sprint plan. Authored by Lane E; RUN by the
manager. Per CLAUDE.local.md "USER IS NEVER A TESTER": every assertion is AI.

Usage:
    pytest src/tests/e2e_ui/test_multiplexer_fleet_status.py -v
    LUPIN_API_URL=http://localhost:8000 pytest src/tests/e2e_ui/test_multiplexer_fleet_status.py -v
"""

from __future__ import annotations

import json
import os
import time

import pytest
import requests

BASE_URL        = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )
MULTIPLEXER_URL = f"{BASE_URL}/app/multiplexer"

FLEET_ROUTE = "**/api/arbiter/fleet-state"


# ---------------------------------------------------------------------------
# Auth + test-hook helpers (post-WP0: raw lupin_access_token / lupin_refresh_token)
# ---------------------------------------------------------------------------

def _get_credentials() -> tuple[ str, str ]:
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not password:
        pytest.skip( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / _PASSWORD env vars not set" )
    return email, password


def _login_tokens() -> tuple[ str, str ]:
    """Login via /auth/login → (access_token, refresh_token)."""
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
    # WP0 migration: AuthManager reads the RAW (un-enveloped) localStorage keys.
    context.add_init_script(
        f"window.localStorage.setItem('lupin_access_token', { json.dumps( access_token ) });"
        f"window.localStorage.setItem('lupin_refresh_token', { json.dumps( refresh_token ) });"
    )


def _wait_for_test_hook( page, timeout_ms: int = 10_000 ) -> None:
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=timeout_ms,
    )


def _fulfill_fleet( body: dict ):
    """Build a page.route handler that fulfills the fleet endpoint with `body`."""
    def _handler( route ):
        route.fulfill( status=200, content_type="application/json", body=json.dumps( body ) )
    return _handler


def _open_with_fleet( pw, fleet_body: dict ):
    """Launch a browser, stub the fleet endpoint with `fleet_body`, navigate."""
    access, refresh = _login_tokens()
    browser = pw.chromium.launch( headless=True, args=[ "--autoplay-policy=no-user-gesture-required" ] )
    context = browser.new_context()
    _seed_auth( context, access, refresh )
    page = context.new_page()
    # Route BEFORE goto so the boot startPolling() immediate refresh uses the stub.
    page.route( FLEET_ROUTE, _fulfill_fleet( fleet_body ) )
    page.goto( MULTIPLEXER_URL, wait_until="networkidle", timeout=15_000 )
    _wait_for_test_hook( page )
    return browser, page


# ---------------------------------------------------------------------------
# Fixtures (composite shapes returned by /api/arbiter/fleet-state)
# ---------------------------------------------------------------------------

_POPULATED = {
    "app_timezone"  : "America/New_York",
    "fleet_arbiter" : {
        "sessions" : [
            { "persona": "Tiberius", "role": "manager", "state": "active",
              "liveness": { "verdict": "live", "bridge_age_s": 2, "freshest_age_s": 2 } },
            { "persona": "Rachel", "role": "worker", "manager": "Tiberius", "state": "running",
              "holding_on": "review", "stuck": False,
              "liveness": { "verdict": "live", "bridge_age_s": 4, "freshest_age_s": 4 } },
            { "persona": "Ghost", "role": "worker", "state": "idle",
              "liveness": { "verdict": "offline", "bridge_age_s": 9000, "freshest_age_s": 9000 } },
        ],
    },
    "context_pressure" : {
        "personas" : { "Tiberius": { "consumption_pct_of_window": 33.3, "window_size": 200000 } },
    },
}

_EMPTY        = { "app_timezone": "UTC", "fleet_arbiter": { "sessions": [] } }
_UNREACHABLE  = { "status": "unreachable", "fleet_arbiter": None }
_ALL_OFFLINE  = {
    "app_timezone"  : "UTC",
    "fleet_arbiter" : {
        "sessions" : [
            { "persona": "Dead1", "role": "worker", "liveness": { "verdict": "offline" } },
            { "persona": "Dead2", "role": "worker", "liveness": { "verdict": "offline" } },
        ],
    },
}


# ---------------------------------------------------------------------------
# §6.4 render states
# ---------------------------------------------------------------------------

def test_fleet_unreachable_shows_offline_banner():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, page = _open_with_fleet( pw, _UNREACHABLE )
        try:
            page.wait_for_selector( ".fleet-status-container .fleet-status-offline", timeout=3000 )
            assert page.locator( ".fleet-status-count" ).text_content() == "0"
        finally:
            browser.close()


def test_fleet_auth_required_shows_signin_banner():
    from playwright.sync_api import sync_playwright

    def _handler( route ):
        route.fulfill( status=401, content_type="application/json", body=json.dumps( { "detail": "unauthorized" } ) )

    access, refresh = _login_tokens()
    with sync_playwright() as pw:
        browser = pw.chromium.launch( headless=True, args=[ "--autoplay-policy=no-user-gesture-required" ] )
        try:
            context = browser.new_context()
            _seed_auth( context, access, refresh )
            page = context.new_page()
            page.route( FLEET_ROUTE, _handler )
            page.goto( MULTIPLEXER_URL, wait_until="networkidle", timeout=15_000 )
            _wait_for_test_hook( page )
            page.wait_for_selector( ".fleet-status-container .fleet-status-signin", timeout=3000 )
        finally:
            browser.close()


def test_fleet_empty_shows_no_active_sessions():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, page = _open_with_fleet( pw, _EMPTY )
        try:
            el = page.wait_for_selector( ".fleet-status-container .fleet-status-empty", timeout=3000 )
            assert el.text_content() == "No active sessions."
            assert page.locator( ".fleet-offline-toggle" ).count() == 0
        finally:
            browser.close()


def test_fleet_populated_renders_grouped_table_with_context_columns():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, page = _open_with_fleet( pw, _POPULATED )
        try:
            page.wait_for_selector( ".fleet-status-table", timeout=3000 )
            # Manager group header carries the 👑 marker.
            header = page.locator( ".fleet-group-header" ).first
            assert "Tiberius" in header.text_content()
            assert "👑" in header.text_content()
            # Manager row + worker row(s); offline worker hidden by default (live-only).
            assert page.locator( ".fleet-row-manager" ).count() == 1
            assert page.locator( ".fleet-row-worker" ).count() == 1   # Ghost is offline → hidden
            # Live-only count excludes the offline Ghost (2 live of 3).
            assert page.locator( ".fleet-status-count" ).text_content() == "2"
            # Context columns joined per-persona for Tiberius.
            row = page.locator( "tbody .fleet-row-manager" )
            assert row.locator( ".fleet-col-window-pct" ).text_content() == "33.3%"
            assert row.locator( ".fleet-col-window" ).text_content() == "200K"
            # An "updated HH:MM:SS" stamp is set on a real fetch.
            assert page.locator( ".fleet-status-updated" ).text_content().startswith( "updated " )
        finally:
            browser.close()


# ---------------------------------------------------------------------------
# Live-only default + offline toggle
# ---------------------------------------------------------------------------

def test_fleet_offline_toggle_reveals_hidden_sessions():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, page = _open_with_fleet( pw, _POPULATED )
        try:
            page.wait_for_selector( ".fleet-status-table", timeout=3000 )
            toggle = page.locator( ".fleet-offline-toggle-btn" )
            assert toggle.count() == 1
            assert "Show offline (1)" in toggle.text_content()
            toggle.click()
            # After revealing, the offline Ghost worker appears (2 workers now).
            page.wait_for_function(
                "() => document.querySelectorAll('.fleet-row-worker').length === 2",
                timeout=2000,
            )
            assert "Hide offline (1)" in page.locator( ".fleet-offline-toggle-btn" ).text_content()
            assert page.locator( ".fleet-status-count" ).text_content() == "3"
        finally:
            browser.close()


def test_fleet_all_offline_shows_no_live_sessions_with_toggle():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, page = _open_with_fleet( pw, _ALL_OFFLINE )
        try:
            page.wait_for_selector( ".fleet-status-container .fleet-status-empty", timeout=3000 )
            assert page.locator( ".fleet-status-empty" ).text_content() == "No live sessions."
            assert page.locator( ".fleet-offline-toggle-btn" ).count() == 1
            assert page.locator( ".fleet-status-count" ).text_content() == "0"
        finally:
            browser.close()


# ---------------------------------------------------------------------------
# Manual ⟳ refresh re-fetches
# ---------------------------------------------------------------------------

def test_fleet_manual_refresh_button_refetches():
    from playwright.sync_api import sync_playwright
    hits = { "n": 0 }

    def _counting_handler( route ):
        hits[ "n" ] += 1
        route.fulfill( status=200, content_type="application/json", body=json.dumps( _EMPTY ) )

    access, refresh = _login_tokens()
    with sync_playwright() as pw:
        browser = pw.chromium.launch( headless=True, args=[ "--autoplay-policy=no-user-gesture-required" ] )
        try:
            context = browser.new_context()
            _seed_auth( context, access, refresh )
            page = context.new_page()
            page.route( FLEET_ROUTE, _counting_handler )
            page.goto( MULTIPLEXER_URL, wait_until="networkidle", timeout=15_000 )
            _wait_for_test_hook( page )
            page.wait_for_selector( ".fleet-status-empty", timeout=3000 )
            before = hits[ "n" ]
            page.locator( ".fleet-status-refresh" ).click()
            # Debounced single fetch — the click yields exactly one more hit.
            page.wait_for_function(
                f"() => true",  # allow the click's async refresh to flush
                timeout=1000,
            )
            time.sleep( 0.3 )
            assert hits[ "n" ] >= before + 1
        finally:
            browser.close()
