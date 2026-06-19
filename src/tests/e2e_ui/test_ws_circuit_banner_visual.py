"""
Visual snapshot test for the WS reconnect circuit-breaker banner (Phase 3
verification row 7 from
`src/rnd/v0.1.7/2026.05.02-ws-reconnect-circuit-breaker/04-phase-3-circuit-banner-and-retry.md`).

Captures one snapshot of the `#ws-circuit-banner` element in its
circuit-open state. First run with `--update-snapshots` establishes the
baseline; subsequent runs verify pixel-identity against it.

**Venue**: `:8000` monopolize-mode (e2e_ui suite gate). Schedule via
`POST /api/test-suite/submit` with `pytest_args="-k test_ws_circuit_banner_visual"`.

This is the smallest useful subset of the full visual regression sweep —
one test, one snapshot, scoped to the new banner element. Per the user's
"no deferring" directive, this closes Phase 3 verification row 7.
"""

from .conftest import BASE_URL


# JS fragment injected before navigation to /app/notifications.
# Two purposes:
#   1) Override window.WebSocket with a no-op mock so the page does not
#      authenticate against a real server during the test (which would
#      fire `auth_success` and re-hide the banner the moment we triggered it).
#   2) Expose `window.__fireWsCircuitOpen` so the test can synthesize a
#      circuit-open event without having to drive the channel state machine.
_BANNER_HARNESS_JS = """
( function () {
    class MockWebSocket {
        static CONNECTING = 0; static OPEN = 1; static CLOSING = 2; static CLOSED = 3;
        constructor( url ) {
            this.url = url; this.readyState = 0;
            this.onopen = null; this.onclose = null; this.onerror = null; this.onmessage = null;
        }
        send( data ) { this.lastSent = data; }
        close( code, reason ) { this.readyState = 3; }
    }
    window.WebSocket = MockWebSocket;
    window.__fireWsCircuitOpen = function ( detail ) {
        window.dispatchEvent( new CustomEvent( 'ws-circuit-open', { detail : detail || { name: 'queue', attempts: 20 } } ) );
    };
} )();
"""


# ---------------------------------------------------------------------------
# Visual regression — banner-shown state
# ---------------------------------------------------------------------------

def test_ws_circuit_banner_visual( request, clean_test_db, assert_snapshot, logged_in_page ):
    """
    Capture the circuit-open banner DOM in its visible state.

    Requires:
        - Server running on `:8000` with Testing config (lupin_db_test)
        - logged_in_page fixture (authenticated session)
        - assert_snapshot fixture from pytest-playwright-visual-snapshot

    Ensures:
        - `/app/notifications` loads successfully under authenticated session
        - `_wireCircuitBanner` has run before screenshotting
        - Synthetic `ws-circuit-open` dispatch shows the banner with its
          dev-hint visible (envLabel forced to 'DEVELOPMENT')
        - Snapshot captured against baseline; matches within configured
          threshold (or establishes baseline on first run with
          `--update-snapshots`)
    """
    page = logged_in_page

    # Inject WebSocket override + helper BEFORE navigation. add_init_script
    # registers the script for every subsequent navigation, so the next
    # page.goto() will run it before notifications.js loads.
    page.add_init_script( script=_BANNER_HARNESS_JS )

    # Navigate to the notifications page (init script runs, then page loads).
    page.goto( f"{BASE_URL}/app/notifications?classic=1" )
    page.wait_for_load_state( "networkidle" )

    # Wait for NotificationsUI to construct + the banner wiring to be done.
    page.wait_for_function(
        "() => window.notificationsUI && window.notificationsUI._circuitBannerWired === true",
        timeout=15000
    )

    # Force envLabel to DEVELOPMENT so the dev-hint span is included in the
    # captured snapshot (otherwise the test would be ambiguous about which
    # banner-state we're capturing).
    page.evaluate( "() => { window.notificationsUI.envLabel = 'DEVELOPMENT'; }" )

    # Dispatch the channel-emitted event — banner becomes visible synchronously.
    page.evaluate( "() => window.__fireWsCircuitOpen( { name: 'queue', attempts: 20 } )" )

    # Wait for the banner to be in the visible DOM state.
    page.wait_for_function(
        "() => { const b = document.getElementById( 'ws-circuit-banner' ); return b && !b.hidden; }",
        timeout=2000
    )

    # Capture just the banner element (avoids unrelated page-layout drift).
    banner = page.locator( "#ws-circuit-banner" )
    assert_snapshot( banner, name="ws_circuit_banner_open.png" )

    print( "✓ ws_circuit_banner_open: visual snapshot compared" )
