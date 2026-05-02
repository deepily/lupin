"""
Layer-3 in-page browser-integration tests for the Page Lifecycle wiring
(Phase 4 of the WS reconnect circuit-breaker milestone).

Closes Phase 4 verification rows 2-7 from
`src/rnd/v0.1.7/2026.05.02-ws-reconnect-circuit-breaker/05-phase-4-page-lifecycle.md`.

Run command:
    pytest src/tests/ws_channel_browser/test_ws_lifecycle.py -v

Same authentication + MockWebSocket harness pattern as the Phase 3 banner
tests in `test_ws_circuit_banner.py`. Lives in the sibling `ws_channel_browser`
dir (not `e2e_ui/`) to avoid the autouse fixture mandating `:8000` lupin_db_test.
"""

import json
import os
import urllib.request

import pytest


BASE_URL = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )


# ---------------------------------------------------------------------------
# Auth + page fixtures (same shape as Phase 3 banner tests)
# ---------------------------------------------------------------------------

@pytest.fixture( scope="module" )
def jwt_token():
    """
    Acquire a JWT for the test session. Skips if env vars missing or auth fails.
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


@pytest.fixture
def lifecycle_page( page, jwt_token ):
    """
    Authenticated `/app/notifications` page with both `_circuitBannerWired`
    AND `_pageLifecycleAttached` complete, plus a richer `MockWebSocket` that
    tracks instances + exposes `_open` / `_close` driver methods so tests
    can drive channel state without real network.
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
        # Richer mock: tracks instances; exposes _open/_close drivers.
        "  class MockWebSocket { "
        "    static CONNECTING = 0; static OPEN = 1; static CLOSING = 2; static CLOSED = 3; "
        "    static instances = []; "
        "    constructor( url ) { "
        "      this.url = url; this.readyState = 0; "
        "      this.onopen = null; this.onclose = null; this.onerror = null; this.onmessage = null; "
        "      MockWebSocket.instances.push( this ); "
        "    } "
        "    send( data ) { this.lastSent = data; } "
        "    close( code, reason ) { "
        "      if ( this.readyState === 3 ) return; "
        "      this.readyState = 3; "
        "      const cb = this.onclose; "
        "      const evt = { code: code === undefined ? 1000 : code, reason: reason || '', wasClean: ( code === 1000 || code === undefined ) }; "
        "      queueMicrotask( () => { if ( typeof cb === 'function' ) cb( evt ); } ); "
        "    } "
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
        "} )();"
    )
    page.add_init_script( script=init_script )

    page.goto( f"{BASE_URL}/app/notifications" )
    # Wait for both wiring flags so Phase 3 + Phase 4 are fully attached.
    page.wait_for_function(
        "() => window.notificationsUI && window.notificationsUI._circuitBannerWired === true"
        " && window.notificationsUI._pageLifecycleAttached === true",
        timeout=15000
    )
    return page


# ---------------------------------------------------------------------------
# Test 1 — visibilityState=hidden defers further connect attempts
# ---------------------------------------------------------------------------

def test_visibility_hidden_pauses_connect( lifecycle_page ):
    page = lifecycle_page
    # Capture instance count baseline (after init's initial connect)
    before = page.evaluate( "() => window.MockWebSocket.instances.length" )
    # Force visibilityState to hidden
    page.evaluate(
        "() => { Object.defineProperty( document, 'visibilityState', { get: () => 'hidden', configurable: true } ); }"
    )
    # Drive 3 close events on the queue channel's current ws — each onclose
    # fires backoff → connect(), which should no-op due to the visibility guard.
    for _ in range( 3 ):
        page.evaluate(
            "() => { const insts = window.MockWebSocket.instances; "
            "  const ws = insts[ insts.length - 1 ]; "
            "  if ( ws ) ws._close( 1006 ); }"
        )
        # Allow the channel's onclose -> scheduleReconnect microtask to run
        page.wait_for_timeout( 50 )

    after = page.evaluate( "() => window.MockWebSocket.instances.length" )
    assert after == before, (
        f"connect() must no-op while document.visibilityState === 'hidden'; "
        f"instance count grew from {before} to {after}"
    )


# ---------------------------------------------------------------------------
# Test 2 — visibilityState back to visible triggers connect()
# ---------------------------------------------------------------------------

def test_visibility_visible_resumes_connect( lifecycle_page ):
    page = lifecycle_page
    # Force hidden first so any in-flight connects pause
    page.evaluate(
        "() => { Object.defineProperty( document, 'visibilityState', { get: () => 'hidden', configurable: true } ); }"
    )
    # Close current sockets so channels are in BACKOFF/DISCONNECTED with
    # connect() ready to run on visible-restore.
    page.evaluate(
        "() => { window.MockWebSocket.instances.forEach( ( w ) => { try { w._close( 1006 ); } catch ( e ) {} } ); }"
    )
    page.wait_for_timeout( 100 )
    before = page.evaluate( "() => window.MockWebSocket.instances.length" )

    # Restore visible + dispatch visibilitychange
    page.evaluate(
        "() => { "
        "  Object.defineProperty( document, 'visibilityState', { get: () => 'visible', configurable: true } ); "
        "  document.dispatchEvent( new Event( 'visibilitychange' ) ); "
        "}"
    )
    page.wait_for_timeout( 100 )

    after = page.evaluate( "() => window.MockWebSocket.instances.length" )
    assert after > before, (
        f"visibility-visible must call channel.connect() on both channels; "
        f"instance count went from {before} to {after}"
    )


# ---------------------------------------------------------------------------
# Test 3 — pageshow.persisted=true triggers manualRetry on both channels
# ---------------------------------------------------------------------------

def test_pageshow_persisted_full_reset_lifecycle( lifecycle_page ):
    page = lifecycle_page
    before = page.evaluate( "() => ( { q: window.notificationsUI.queueChannel.attempts, a: window.notificationsUI.audioChannel.attempts } )" )

    # Force both channels into a non-CONNECTED state with attempts > 0 so
    # manualRetry is observably distinct from a no-op (the Phase 4 guard
    # makes manualRetry a no-op on CONNECTED channels).
    page.evaluate(
        "() => { window.MockWebSocket.instances.forEach( ( w ) => { try { w._close( 1006 ); } catch ( e ) {} } ); }"
    )
    page.wait_for_timeout( 100 )

    # Dispatch pageshow with persisted=true
    page.evaluate(
        "() => { const ev = new Event( 'pageshow' ); "
        "  Object.defineProperty( ev, 'persisted', { value: true } ); "
        "  window.dispatchEvent( ev ); }"
    )
    page.wait_for_timeout( 100 )

    after = page.evaluate( "() => ( { q: window.notificationsUI.queueChannel.attempts, a: window.notificationsUI.audioChannel.attempts } )" )
    # manualRetry zeros attempts on both
    assert after[ "q" ] == 0, f"queueChannel.attempts must zero on pageshow.persisted (was {after['q']})"
    assert after[ "a" ] == 0, f"audioChannel.attempts must zero on pageshow.persisted (was {after['a']})"


# ---------------------------------------------------------------------------
# Test 4 — offline event closes both channels
# ---------------------------------------------------------------------------

def test_offline_closes_sockets( lifecycle_page ):
    page = lifecycle_page
    # Dispatch offline
    page.evaluate( "() => window.dispatchEvent( new Event( 'offline' ) )" )
    page.wait_for_timeout( 100 )

    state = page.evaluate(
        "() => ( { q: window.notificationsUI.queueChannel.state, a: window.notificationsUI.audioChannel.state } )"
    )
    assert state[ "q" ] == "DISCONNECTED", f"queueChannel.state must be DISCONNECTED after offline (was {state['q']})"
    assert state[ "a" ] == "DISCONNECTED", f"audioChannel.state must be DISCONNECTED after offline (was {state['a']})"


# ---------------------------------------------------------------------------
# Test 5 — online event triggers manualRetry on both channels
# ---------------------------------------------------------------------------

def test_online_triggers_retry_lifecycle( lifecycle_page ):
    page = lifecycle_page
    # Take channels offline first so we observe the manualRetry transition
    page.evaluate( "() => window.dispatchEvent( new Event( 'offline' ) )" )
    page.wait_for_timeout( 100 )
    state_before = page.evaluate(
        "() => ( { q: window.notificationsUI.queueChannel.state, a: window.notificationsUI.audioChannel.state } )"
    )
    assert state_before[ "q" ] == "DISCONNECTED"
    assert state_before[ "a" ] == "DISCONNECTED"

    # Dispatch online
    page.evaluate( "() => window.dispatchEvent( new Event( 'online' ) )" )
    page.wait_for_timeout( 100 )

    state_after = page.evaluate(
        "() => ( { q: window.notificationsUI.queueChannel.state, a: window.notificationsUI.audioChannel.state } )"
    )
    # manualRetry → DISCONNECTED → connect() → CONNECTING
    assert state_after[ "q" ] == "CONNECTING", f"queueChannel.state must be CONNECTING after online (was {state_after['q']})"
    assert state_after[ "a" ] == "CONNECTING", f"audioChannel.state must be CONNECTING after online (was {state_after['a']})"


# ---------------------------------------------------------------------------
# Test 6 — pagehide closes both channels (BFCache eligibility)
# ---------------------------------------------------------------------------

def test_pagehide_closes_for_bfcache( lifecycle_page ):
    page = lifecycle_page
    # Dispatch pagehide
    page.evaluate( "() => window.dispatchEvent( new Event( 'pagehide' ) )" )
    page.wait_for_timeout( 100 )

    state = page.evaluate(
        "() => ( { q: window.notificationsUI.queueChannel.state, a: window.notificationsUI.audioChannel.state } )"
    )
    assert state[ "q" ] == "DISCONNECTED", f"queueChannel.state must be DISCONNECTED after pagehide (was {state['q']})"
    assert state[ "a" ] == "DISCONNECTED", f"audioChannel.state must be DISCONNECTED after pagehide (was {state['a']})"
