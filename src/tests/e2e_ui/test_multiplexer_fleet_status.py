#!/usr/bin/env python3
"""
E2E — Multiplexer Lane E WP12: read-only Fleet-Status table (F12).

Exercises the FleetStatusStore (poll/fetch/toggle) + FleetStatusRenderer (4
render states + count + offline toggle) end-to-end in a real browser. The
`/api/arbiter/fleet-state` endpoint is STUBBED via `page.route` so each of the
§6.4 states is driven deterministically without a live arbiter; the renderer
runs the real store.refresh() → fetchState() → render path.

COLOR (WP12 follow-on, landed): the verdict-based color scheme (status-dot +
row left-accent + %-window heat-tint) is now asserted by CLASS PRESENCE — the
class is the WCAG-1.4.1 redundancy carrier (always paired with the verdict WORD
/ numeric %), so a class assertion is exactly the right check, not a brittle
computed-pixel-color read. See `fleetVerdictClass` / `fleetHeatClass`.

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


def _open_with_fleet( page, fleet_body: dict ):
    """Seed auth on the managed page's context, stub the fleet endpoint, navigate.

    Uses the pytest-playwright `page` fixture (loop-managed) — NOT a manual
    `sync_playwright()` launch, which trips "Sync API inside the asyncio loop"
    under the plugin's event loop. `_seed_auth` uses add_init_script, so the
    raw lupin_* tokens are set before app boot on goto; routing before goto
    keeps the boot startPolling() immediate refresh on the stub.
    """
    access, refresh = _login_tokens()
    _seed_auth( page.context, access, refresh )
    page.route( FLEET_ROUTE, _fulfill_fleet( fleet_body ) )
    page.goto( MULTIPLEXER_URL, wait_until="networkidle", timeout=15_000 )
    _wait_for_test_hook( page )


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

# Color follow-on fixture: one live manager + quiet / stale / (no-liveness=unknown)
# workers — all NON-offline so all stay visible under the live-only default. Heat
# buckets: 12%→low, 65%→mid, 88%→high, and WkrUnknown omitted from personas →
# unmeasured "—" (must stay UNTINTED).
_COLOR_STATES = {
    "app_timezone"  : "UTC",
    "fleet_arbiter" : {
        "sessions" : [
            { "persona": "MgrLive", "role": "manager",
              "liveness": { "verdict": "live", "bridge_age_s": 1, "freshest_age_s": 1 } },
            { "persona": "WkrQuiet", "role": "worker", "manager": "MgrLive",
              "liveness": { "verdict": "quiet (idle)", "bridge_age_s": 120, "freshest_age_s": 120 } },
            { "persona": "WkrStale", "role": "worker", "manager": "MgrLive",
              "liveness": { "verdict": "stale", "bridge_age_s": 1800, "freshest_age_s": 1800 } },
            { "persona": "WkrUnknown", "role": "worker", "manager": "MgrLive" },  # no liveness → unknown
        ],
    },
    "context_pressure" : {
        "personas" : {
            "MgrLive"  : { "consumption_pct_of_window": 12.0, "window_size": 200000 },  # low
            "WkrQuiet" : { "consumption_pct_of_window": 65.0, "window_size": 200000 },  # mid
            "WkrStale" : { "consumption_pct_of_window": 88.0, "window_size": 200000 },  # high
            # WkrUnknown intentionally absent → unmeasured → untinted "—"
        },
    },
}


# ---------------------------------------------------------------------------
# §6.4 render states
# ---------------------------------------------------------------------------

def test_fleet_unreachable_shows_offline_banner( page ):
    _open_with_fleet( page, _UNREACHABLE )
    page.wait_for_selector( ".fleet-status-container .fleet-status-offline", timeout=3000 )
    assert page.locator( '[data-testid="multiplexer-fleet-status-count"]' ).text_content() == "0"


def test_fleet_auth_required_shows_signin_banner( page ):
    def _handler( route ):
        route.fulfill( status=401, content_type="application/json", body=json.dumps( { "detail": "unauthorized" } ) )

    access, refresh = _login_tokens()
    _seed_auth( page.context, access, refresh )
    page.route( FLEET_ROUTE, _handler )
    page.goto( MULTIPLEXER_URL, wait_until="networkidle", timeout=15_000 )
    _wait_for_test_hook( page )
    page.wait_for_selector( ".fleet-status-container .fleet-status-signin", timeout=3000 )


def test_fleet_empty_shows_no_active_sessions( page ):
    _open_with_fleet( page, _EMPTY )
    el = page.wait_for_selector( ".fleet-status-container .fleet-status-empty", timeout=3000 )
    assert el.text_content() == "No active sessions."
    assert page.locator( ".fleet-offline-toggle" ).count() == 0


def test_fleet_populated_renders_grouped_table_with_context_columns( page ):
    _open_with_fleet( page, _POPULATED )
    page.wait_for_selector( ".fleet-status-table", timeout=3000 )
    # Manager group header carries the 👑 marker.
    header = page.locator( ".fleet-group-header" ).first
    assert "Tiberius" in header.text_content()
    assert "👑" in header.text_content()
    # Manager row + worker row(s); offline worker hidden by default (live-only).
    assert page.locator( ".fleet-row-manager" ).count() == 1
    assert page.locator( ".fleet-row-worker" ).count() == 1   # Ghost is offline → hidden
    # Live-only count excludes the offline Ghost (2 live of 3).
    assert page.locator( '[data-testid="multiplexer-fleet-status-count"]' ).text_content() == "2"
    # Context columns joined per-persona for Tiberius.
    row = page.locator( "tbody .fleet-row-manager" )
    assert row.locator( ".fleet-col-window-pct" ).text_content() == "33.3%"
    assert row.locator( ".fleet-col-window" ).text_content() == "200K"
    # Color follow-on: the live manager row carries the verdict-live class,
    # a status-dot, and a low (green) heat-tint at 33.3% (class, not pixels).
    assert "fleet-verdict-live" in ( row.get_attribute( "class" ) or "" )
    assert row.locator( ".fleet-col-liveness .fleet-liveness-dot" ).count() == 1
    assert row.locator( ".fleet-col-window-pct.fleet-pct-low" ).count() == 1
    # An "updated HH:MM:SS" stamp is set on a real fetch.
    assert page.locator( ".fleet-status-updated" ).text_content().startswith( "updated " )


# ---------------------------------------------------------------------------
# Live-only default + offline toggle
# ---------------------------------------------------------------------------

def test_fleet_offline_toggle_reveals_hidden_sessions( page ):
    _open_with_fleet( page, _POPULATED )
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
    assert page.locator( '[data-testid="multiplexer-fleet-status-count"]' ).text_content() == "3"


def test_fleet_all_offline_shows_no_live_sessions_with_toggle( page ):
    _open_with_fleet( page, _ALL_OFFLINE )
    page.wait_for_selector( ".fleet-status-container .fleet-status-empty", timeout=3000 )
    assert page.locator( ".fleet-status-empty" ).text_content() == "No live sessions."
    assert page.locator( ".fleet-offline-toggle-btn" ).count() == 1
    assert page.locator( '[data-testid="multiplexer-fleet-status-count"]' ).text_content() == "0"


# ---------------------------------------------------------------------------
# Color follow-on — verdict classes + heat-tint buckets (class presence only)
# ---------------------------------------------------------------------------

def test_fleet_color_coding_verdict_and_heat_classes( page ):
    _open_with_fleet( page, _COLOR_STATES )
    page.wait_for_selector( ".fleet-status-table", timeout=3000 )
    # All four rows are non-offline → visible under the live-only default.
    page.wait_for_function(
        "() => document.querySelectorAll('.fleet-row-worker').length === 3",
        timeout=2000,
    )
    # Verdict color classes — redundant with the Liveness WORD (WCAG 1.4.1).
    assert page.locator( "tr.fleet-verdict-live" ).count()    == 1   # MgrLive
    assert page.locator( "tr.fleet-verdict-quiet" ).count()   == 1   # WkrQuiet
    assert page.locator( "tr.fleet-verdict-stale" ).count()   == 1   # WkrStale
    assert page.locator( "tr.fleet-verdict-unknown" ).count() == 1   # WkrUnknown (no liveness)
    # Each visible row's Liveness cell carries a status-dot.
    assert page.locator( ".fleet-col-liveness .fleet-liveness-dot" ).count() == 4
    # Heat-tint buckets — class presence, NOT computed pixel color.
    assert page.locator( ".fleet-col-window-pct.fleet-pct-low" ).count()  == 1   # 12%
    assert page.locator( ".fleet-col-window-pct.fleet-pct-mid" ).count()  == 1   # 65%
    assert page.locator( ".fleet-col-window-pct.fleet-pct-high" ).count() == 1   # 88%
    # Unmeasured "—" cell (WkrUnknown) stays UNTINTED — no fleet-pct-* class.
    unknown_pct = page.locator( "tr.fleet-verdict-unknown .fleet-col-window-pct" )
    assert unknown_pct.text_content() == "—"
    assert "fleet-pct-" not in ( unknown_pct.get_attribute( "class" ) or "" )


# ---------------------------------------------------------------------------
# Manual ⟳ refresh re-fetches
# ---------------------------------------------------------------------------

def test_fleet_manual_refresh_button_refetches( page ):
    hits = { "n": 0 }

    def _counting_handler( route ):
        hits[ "n" ] += 1
        route.fulfill( status=200, content_type="application/json", body=json.dumps( _EMPTY ) )

    access, refresh = _login_tokens()
    _seed_auth( page.context, access, refresh )
    page.route( FLEET_ROUTE, _counting_handler )
    page.goto( MULTIPLEXER_URL, wait_until="networkidle", timeout=15_000 )
    _wait_for_test_hook( page )
    page.wait_for_selector( ".fleet-status-empty", timeout=3000 )
    before = hits[ "n" ]
    page.locator( ".fleet-status-refresh" ).click()
    # Allow the click's async refresh to flush, then assert one more hit.
    time.sleep( 0.3 )
    assert hits[ "n" ] >= before + 1
