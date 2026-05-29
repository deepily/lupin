"""
Layer-3 in-page browser-integration tests for the WS reconnect circuit-breaker
banner (Phase 3 of the WS reconnect circuit-breaker milestone).

Closes Phase 3 verification rows 3-6 from
`src/rnd/v0.1.7/2026.05.02-ws-reconnect-circuit-breaker/04-phase-3-circuit-banner-and-retry.md`.

Run command:
    pytest src/tests/ws_channel_browser/ -v

Requires:
    - Dev server on `:7999` (LUPIN_API_URL overrideable)
    - LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / _PASSWORD env vars set
    - Auth contract: POST /auth/login -> response.tokens.access_token
      (per `feedback_auth_contract_lookup` memory)

Placement note: lives in `src/tests/ws_channel_browser/` rather than
`src/tests/e2e_ui/` because the e2e_ui conftest declares an autouse
`verify_test_environment` fixture mandating `:8000` lupin_db_test, which
is unrelated to these `:7999`-routed banner-DOM tests.
"""

import json
import os
import urllib.request

import pytest


BASE_URL = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )


# ---------------------------------------------------------------------------
# Auth helper — POST /auth/login per the canonical contract
# ---------------------------------------------------------------------------

@pytest.fixture( scope="module" )
def jwt_token():
    """
    Acquire a JWT for the test session.

    Requires:
        - LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL and LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD
          set in the env (per project CLAUDE.md §TEST CREDENTIALS)
    Ensures:
        - Returns a non-empty access-token string
        - Skips the test if the dev server is unreachable or auth fails
    """
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not password:
        pytest.skip( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_{EMAIL,PASSWORD} env vars not set" )

    body = json.dumps( { "email" : email, "password" : password } ).encode( "utf-8" )
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
    return { "token" : token, "user" : data.get( "user", {} ) }


# ---------------------------------------------------------------------------
# Page fixture — pre-populate localStorage + navigate to /app/notifications,
# wait for notificationsUI to construct + banner to be wired.
# ---------------------------------------------------------------------------

@pytest.fixture
def notifications_page( page, jwt_token ):
    """
    Authenticated `/app/notifications` page with `_wireCircuitBanner` complete.

    Pre-loads the JWT + minimal user_data into localStorage via add_init_script,
    so notifications.js's auth flow finds tokens and proceeds through init.
    Also registers a synthetic-event helper `window.__fireWsCircuitOpen(detail)`
    so each test can dispatch the channel-emitted event without driving a real
    socket close cycle.
    """
    user = jwt_token[ "user" ]
    localstorage_seed = json.dumps( {
        "lupin_access_token"  : jwt_token[ "token" ],
        "lupin_refresh_token" : jwt_token[ "token" ],
        "user_data"           : json.dumps( user )
    } )

    # Override window.WebSocket with a mock that never auto-opens or auto-sends.
    # This prevents the real :7999 WebSocket from authenticating, which would
    # fire a live auth_success message and call _hideCircuitBanner during the
    # tests (race vs the synthetic events we drive). Mock instances only do
    # what the test explicitly tells them to.
    init_script = (
        "( function () { "
        "  const seed = " + localstorage_seed + ";"
        "  for ( const [ k, v ] of Object.entries( seed ) ) { "
        "    try { localStorage.setItem( k, v ); } catch ( e ) {} "
        "  } "
        "  class MockWebSocket { "
        "    static CONNECTING = 0; static OPEN = 1; static CLOSING = 2; static CLOSED = 3; "
        "    constructor( url ) { "
        "      this.url = url; this.readyState = 0; "
        "      this.onopen = null; this.onclose = null; this.onerror = null; this.onmessage = null; "
        "    } "
        "    send( data ) { this.lastSent = data; } "
        "    close( code, reason ) { this.readyState = 3; } "
        "  } "
        "  window.WebSocket = MockWebSocket; "
        "  window.__fireWsCircuitOpen = function ( detail ) { "
        "    window.dispatchEvent( new CustomEvent( 'ws-circuit-open', { detail : detail || { name: 'queue', attempts: 20 } } ) ); "
        "  }; "
        "} )();"
    )
    page.add_init_script( script=init_script )

    page.goto( f"{BASE_URL}/app/notifications" )
    # Wait for notificationsUI to exist AND _wireCircuitBanner to have run
    # (signaled by _circuitBannerWired === true).
    page.wait_for_function(
        "() => window.notificationsUI && window.notificationsUI._circuitBannerWired === true",
        timeout=15000
    )
    return page


# ---------------------------------------------------------------------------
# Test 1 — circuit-open event makes the banner visible
# ---------------------------------------------------------------------------

def test_circuit_open_shows_banner( notifications_page ):
    page = notifications_page
    # Banner is hidden by default
    is_hidden_before = page.evaluate(
        "() => document.getElementById( 'ws-circuit-banner' ).hidden"
    )
    assert is_hidden_before is True, "banner is hidden before any circuit-open event"

    # Dispatch the channel-emitted event
    page.evaluate( "() => window.__fireWsCircuitOpen( { name: 'queue', attempts: 20 } )" )

    # Banner should now be visible (hidden=false)
    is_hidden_after = page.evaluate(
        "() => document.getElementById( 'ws-circuit-banner' ).hidden"
    )
    assert is_hidden_after is False, "banner becomes visible after ws-circuit-open dispatch"


# ---------------------------------------------------------------------------
# Test 2 — Retry-now click + auth_success hides the banner
# ---------------------------------------------------------------------------

def test_retry_now_clears_breaker_and_reconnects( notifications_page ):
    page = notifications_page
    # Trip
    page.evaluate( "() => window.__fireWsCircuitOpen( { name: 'queue', attempts: 20 } )" )
    assert page.evaluate( "() => document.getElementById( 'ws-circuit-banner' ).hidden" ) is False

    # Click Retry-now (handler calls manualRetry on both channels)
    page.evaluate( "() => document.getElementById( 'ws-circuit-retry-btn' ).click()" )

    # Drive a synthetic auth_success directly into the queue handler
    # (bypasses the live socket — the wiring under test is _hideCircuitBanner
    # being called from the auth_success branch, not the socket path itself).
    page.evaluate(
        "() => window.notificationsUI.handleQueueMessage( { data : JSON.stringify( { type : 'auth_success', user_id : 'test' } ) } )"
    )

    is_hidden = page.evaluate(
        "() => document.getElementById( 'ws-circuit-banner' ).hidden"
    )
    assert is_hidden is True, "banner hides on first auth_success after Retry-now click"


# ---------------------------------------------------------------------------
# Test 3 — Retry-now click disables the button
# ---------------------------------------------------------------------------

def test_retry_button_disables_during_reconnect( notifications_page ):
    page = notifications_page
    # Trip + click
    page.evaluate( "() => window.__fireWsCircuitOpen( { name: 'queue', attempts: 20 } )" )
    page.evaluate( "() => document.getElementById( 'ws-circuit-retry-btn' ).click()" )

    # Immediately after click the button should be disabled (visual feedback)
    is_disabled = page.evaluate(
        "() => document.getElementById( 'ws-circuit-retry-btn' ).disabled"
    )
    assert is_disabled is True, "button is disabled immediately after Retry-now click"


# ---------------------------------------------------------------------------
# Test 4 — dev-mode hint visibility tracks envLabel
# ---------------------------------------------------------------------------

def test_dev_hint_visible_only_in_dev( notifications_page ):
    page = notifications_page

    # ----- DEVELOPMENT envLabel -> dev hint visible -----
    page.evaluate( "() => { window.notificationsUI.envLabel = 'DEVELOPMENT'; window.__fireWsCircuitOpen( { name: 'queue', attempts: 20 } ); }" )
    dev_hint_hidden_dev = page.evaluate(
        "() => document.querySelector( '#ws-circuit-banner .ws-circuit-banner-dev-hint' ).hidden"
    )
    assert dev_hint_hidden_dev is False, "dev hint visible when envLabel === 'DEVELOPMENT'"

    # ----- non-DEVELOPMENT envLabel -> dev hint hidden -----
    # First reset banner state by dispatching auth_success
    page.evaluate(
        "() => window.notificationsUI.handleQueueMessage( { data : JSON.stringify( { type : 'auth_success', user_id : 'test' } ) } )"
    )
    page.evaluate( "() => { window.notificationsUI.envLabel = 'PRODUCTION'; window.__fireWsCircuitOpen( { name: 'queue', attempts: 20 } ); }" )
    dev_hint_hidden_prod = page.evaluate(
        "() => document.querySelector( '#ws-circuit-banner .ws-circuit-banner-dev-hint' ).hidden"
    )
    assert dev_hint_hidden_prod is True, "dev hint hidden when envLabel !== 'DEVELOPMENT'"
