"""
Layer-3 in-page browser-integration tests for the auth-permanent close-code
handling (Phase 5 of the WS reconnect circuit-breaker milestone).

Closes Phase 5 verification rows 5, 6, and 9 from
`src/rnd/v0.1.7/2026.05.02-ws-reconnect-circuit-breaker/06-phase-5-server-side-hardening.md`.

Run command:
    pytest src/tests/ws_channel_browser/test_ws_close_codes.py -v

Same harness pattern as `test_ws_circuit_banner.py` and `test_ws_lifecycle.py`.
"""

import json
import os
import urllib.request

import pytest


BASE_URL = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )


@pytest.fixture( scope="module" )
def jwt_token():
    """Acquire JWT for the test session (same pattern as banner / lifecycle tests)."""
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
    return { "token" : token, "user" : data.get( "user", {} ) }


@pytest.fixture
def close_codes_page( page, jwt_token ):
    """
    Authenticated `/app/notifications` page with banner + lifecycle wiring,
    plus a richer MockWebSocket exposing `_close(code)` and a window helper
    `__fireQueueClose(code)` that drives a close on the queue channel's
    most-recent socket. Also stubs `notificationsUI.refreshAccessToken`
    so the 4001 token-refresh path is testable without an HTTP round-trip.
    """
    user = jwt_token[ "user" ]
    localstorage_seed = json.dumps( {
        "lupin_access_token"  : jwt_token[ "token" ],
        "lupin_refresh_token" : jwt_token[ "token" ],
        "user_data"           : json.dumps( user )
    } )

    init_script = (
        "( function () { "
        "  const seed = " + localstorage_seed + ";"
        "  for ( const [ k, v ] of Object.entries( seed ) ) { "
        "    try { localStorage.setItem( k, v ); } catch ( e ) {} "
        "  } "
        "  class MockWebSocket { "
        "    static CONNECTING = 0; static OPEN = 1; static CLOSING = 2; static CLOSED = 3; "
        "    static instances = []; "
        "    constructor( url ) { "
        "      this.url = url; this.readyState = 0; "
        "      this.onopen = null; this.onclose = null; this.onerror = null; this.onmessage = null; "
        "      MockWebSocket.instances.push( this ); "
        "    } "
        "    send( data ) { this.lastSent = data; } "
        "    close( code, reason ) { if ( this.readyState === 3 ) return; this.readyState = 3; } "
        "    _close( code, reason ) { "
        "      if ( this.readyState === 3 ) return; "
        "      this.readyState = 3; "
        "      const cb = this.onclose; "
        "      const evt = { code: code === undefined ? 1006 : code, reason: reason || '', wasClean: false }; "
        "      queueMicrotask( () => { if ( typeof cb === 'function' ) cb( evt ); } ); "
        "    } "
        "  } "
        "  window.WebSocket = MockWebSocket; "
        "  window.MockWebSocket = MockWebSocket; "
        # Test helper: drive a close on the queue channel's most-recent socket.
        # The queue channel is the FIRST instance because notifications.js
        # constructs queueChannel before audioChannel.
        "  window.__fireQueueClose = function ( code ) { "
        "    const insts = MockWebSocket.instances; "
        "    if ( insts.length > 0 ) insts[ 0 ]._close( code, 'test' ); "
        "  }; "
        "} )();"
    )
    page.add_init_script( script=init_script )
    page.goto( f"{BASE_URL}/app/notifications" )
    page.wait_for_function(
        "() => window.notificationsUI"
        " && window.notificationsUI._circuitBannerWired === true"
        " && window.notificationsUI._pageLifecycleAttached === true",
        timeout=15000
    )
    return page


# ---------------------------------------------------------------------------
# Test 5 — close 4001 immediately opens the circuit (state=OPEN_CIRCUIT in 1 tick)
# ---------------------------------------------------------------------------

def test_close_4001_opens_circuit_immediately( close_codes_page ):
    page = close_codes_page

    # Stub refreshAccessToken to FAIL so the test sees the auth-permanent
    # banner path (without this stub, refreshAccessToken would attempt a real
    # HTTP call and pollute the assertion).
    page.evaluate(
        "() => { window.notificationsUI.refreshAccessToken = () => Promise.resolve( false ); }"
    )

    before_attempts = page.evaluate( "() => window.notificationsUI.queueChannel.attempts" )

    # Drive a 4001 close on the queue channel
    page.evaluate( "() => window.__fireQueueClose( 4001 )" )
    page.wait_for_timeout( 200 )

    state = page.evaluate( "() => window.notificationsUI.queueChannel.state" )
    after_attempts = page.evaluate( "() => window.notificationsUI.queueChannel.attempts" )
    assert state == "OPEN_CIRCUIT", (
        f"close 4001 must transition to OPEN_CIRCUIT in one tick (was {state})"
    )
    # 4001 path does NOT increment attempts beyond the pre-existing value
    # (per Phase 1 test 20 invariant — also tested at the channel level).
    assert after_attempts == before_attempts, (
        f"4001 close must not bump attempts (was {before_attempts}, now {after_attempts})"
    )


# ---------------------------------------------------------------------------
# Test 6 — close 4001 with refresh failure shows the auth-permanent banner copy
# ---------------------------------------------------------------------------

def test_close_4001_banner_message( close_codes_page ):
    page = close_codes_page
    # Stub refreshAccessToken to FAIL → banner is shown with auth-permanent copy
    page.evaluate(
        "() => { window.notificationsUI.refreshAccessToken = () => Promise.resolve( false ); }"
    )
    page.evaluate( "() => window.__fireQueueClose( 4001 )" )
    # Wait for the refresh promise to resolve (microtask) and banner to render
    page.wait_for_function(
        "() => { const b = document.getElementById( 'ws-circuit-banner' ); return b && !b.hidden; }",
        timeout=2000
    )
    text = page.evaluate(
        "() => document.querySelector( '#ws-circuit-banner .ws-circuit-banner-text' ).textContent.trim()"
    )
    reason = page.evaluate(
        "() => document.querySelector( '#ws-circuit-banner .ws-circuit-banner-text' ).getAttribute( 'data-reason' )"
    )
    assert "Authentication failed" in text, (
        f"4001 banner copy must reflect auth-permanent semantics (was: {text!r})"
    )
    assert reason == "auth-permanent", (
        f"banner data-reason attribute must be 'auth-permanent' for 4001 (was {reason!r})"
    )


# ---------------------------------------------------------------------------
# Test 7 (verification row 9) — close 4001 triggers the token-refresh path
# ---------------------------------------------------------------------------

def test_4001_triggers_token_refresh_path( close_codes_page ):
    page = close_codes_page
    # Wire a counting stub for refreshAccessToken — assert it's invoked exactly
    # once on a 4001 close. Resolve to false so the auth-permanent banner shows
    # (the no-banner-flash variant is tested in test 8 below).
    page.evaluate(
        "() => { "
        "  window.__refreshCalls = 0; "
        "  window.notificationsUI.authRefreshAttempted = false; "
        "  window.notificationsUI.refreshAccessToken = () => { "
        "    window.__refreshCalls += 1; "
        "    return Promise.resolve( false ); "
        "  }; "
        "}"
    )
    page.evaluate( "() => window.__fireQueueClose( 4001 )" )
    page.wait_for_timeout( 200 )

    refresh_calls = page.evaluate( "() => window.__refreshCalls" )
    assert refresh_calls == 1, (
        f"4001 close must invoke refreshAccessToken exactly once (was {refresh_calls})"
    )


# ---------------------------------------------------------------------------
# Test 8 — close 4001 + refresh-success path → no banner flash
# ---------------------------------------------------------------------------

def test_4001_refresh_success_no_banner_flash( close_codes_page ):
    page = close_codes_page
    # Stub refreshAccessToken to SUCCEED → banner should NEVER become visible
    page.evaluate(
        "() => { "
        "  window.notificationsUI.authRefreshAttempted = false; "
        "  window.notificationsUI.refreshAccessToken = () => Promise.resolve( true ); "
        "}"
    )
    page.evaluate( "() => window.__fireQueueClose( 4001 )" )
    # Wait for the refresh promise + manualRetry chain to drain
    page.wait_for_timeout( 200 )

    is_hidden = page.evaluate(
        "() => document.getElementById( 'ws-circuit-banner' ).hidden"
    )
    assert is_hidden is True, (
        "banner must NOT be shown when refresh succeeds (no banner flash)"
    )
