"""
Layer-1 unit tests for src/fastapi_app/static/js/ws-channel.js.

Phase 1 of the WS reconnect circuit-breaker milestone. Pure state-machine
assertions driven through Playwright's `page.evaluate()` against a
MockWebSocket + TestClock injected into a blank page. NO real WebSocket,
NO real network, NO real backoff timers fire.

Strategy doc: src/rnd/v0.1.7/2026.05.02-ws-reconnect-circuit-breaker/
              07-test-strategy.md §Layer 1
Module under test: src/fastapi_app/static/js/ws-channel.js

Placement note: tests live in `src/tests/ws_channel_unit/` rather than
`src/tests/e2e_ui/` because the e2e_ui conftest enforces a `:8000`
lupin_db_test environment that is irrelevant for these pure-JS unit
tests. Strategy doc's `:7999` routing is preserved in spirit (these are
AI-discretionary, server-free, fast).

Run command:
    pytest src/tests/ws_channel_unit/ -v
"""

import json
import pathlib
import re
import textwrap

import pytest


# ---------------------------------------------------------------------------
# Module loader — read ws-channel.js from disk and rewrite ES-module exports
# into top-level identifiers + a single window namespace, so the script can
# run in a non-module page context (about:blank).
# ---------------------------------------------------------------------------

_MODULE_PATH = (
    pathlib.Path( __file__ ).resolve().parents[ 2 ]
    / "fastapi_app" / "static" / "js" / "ws-channel.js"
)


def _load_module_source():
    """
    Read ws-channel.js, strip `export ` prefixes, append a window namespace.

    Requires:
        - ws-channel.js exists at the canonical path
        - All `export` keywords are top-level (`export const` or `export function`)

    Ensures:
        - Returns a JS string with no `export` keywords
        - Appends `window.__WSChannel = { STATE, CIRCUIT_OPEN_EVENT, ... }`
          so test code can reach the API via that namespace
    """
    src = _MODULE_PATH.read_text()
    src_no_export = re.sub( r"^export ", "", src, flags=re.MULTILINE )
    footer = textwrap.dedent( """
        ;window.__WSChannel = {
            STATE              : STATE,
            CIRCUIT_OPEN_EVENT : CIRCUIT_OPEN_EVENT,
            STATE_CHANGE_EVENT : STATE_CHANGE_EVENT,
            fullJitterDelay    : fullJitterDelay,
            createChannel      : createChannel
        };
    """ )
    return src_no_export + footer


_MODULE_SOURCE = _load_module_source()


# ---------------------------------------------------------------------------
# Test harness — JS that runs in the page before ws-channel.js loads.
#
# Installs:
#   - MockWebSocket on window (so createChannel({WebSocketCtor}) can use it)
#   - TestClock on window.__clock with .fireOne(), .fireAll(), .pending(),
#     .pendingDelays() helpers; replaces window.setTimeout / clearTimeout
#   - No-op stubs for setInterval / clearInterval (so the watchdog never
#     fires automatically; tests drive it via channel._tickWatchdog())
# ---------------------------------------------------------------------------

_HARNESS_JS = r"""
"use strict";

class MockWebSocket {
    static CONNECTING = 0;
    static OPEN       = 1;
    static CLOSING    = 2;
    static CLOSED     = 3;
    static instances  = [];
    static reset() { MockWebSocket.instances = []; }

    constructor( url ) {
        this.url        = url;
        this.readyState = MockWebSocket.CONNECTING;
        this.onopen     = null;
        this.onclose    = null;
        this.onerror    = null;
        this.onmessage  = null;
        this.lastSent   = null;
        this._closed    = false;
        MockWebSocket.instances.push( this );
    }

    send( data ) { this.lastSent = data; }

    close( code, reason ) {
        // The real WebSocket fires onclose asynchronously when close() is called
        // by the application. We mimic that with queueMicrotask.
        if ( this._closed ) return;
        this._closed = true;
        this.readyState = MockWebSocket.CLOSED;
        const cb = this.onclose;
        const evt = { code : code === undefined ? 1000 : code, reason : reason || "", wasClean : ( code === 1000 || code === undefined ) };
        queueMicrotask( () => { if ( typeof cb === "function" ) cb( evt ); } );
    }

    // ----- Test-driver helpers (synchronous side-effects, async callbacks) -----

    _open() {
        this.readyState = MockWebSocket.OPEN;
        const cb = this.onopen;
        queueMicrotask( () => { if ( typeof cb === "function" ) cb( {} ); } );
    }

    _msg( payload ) {
        const cb = this.onmessage;
        const data = JSON.stringify( payload );
        queueMicrotask( () => { if ( typeof cb === "function" ) cb( { data : data } ); } );
    }

    _close( code, reason ) {
        if ( this._closed ) return;
        this._closed = true;
        this.readyState = MockWebSocket.CLOSED;
        const cb = this.onclose;
        const evt = { code : code === undefined ? 1006 : code, reason : reason || "", wasClean : false };
        queueMicrotask( () => { if ( typeof cb === "function" ) cb( evt ); } );
    }

    _error() {
        const cb = this.onerror;
        queueMicrotask( () => { if ( typeof cb === "function" ) cb( {} ); } );
    }
}

window.MockWebSocket = MockWebSocket;

class TestClock {
    constructor() {
        this._timers = new Map();
        this._next   = 1;
    }
    setTimeout( fn, delay ) {
        const id = this._next++;
        this._timers.set( id, { fn : fn, delay : delay || 0, scheduledAt : Date.now() } );
        return id;
    }
    clearTimeout( id ) { this._timers.delete( id ); }

    pending() { return this._timers.size; }
    pendingDelays() {
        return Array.from( this._timers.values() ).map( ( t ) => t.delay );
    }

    // Fire the earliest-scheduled (smallest delay) pending timer.
    // Returns true if something fired, false if the queue was empty.
    fireOne() {
        const entries = Array.from( this._timers.entries() );
        if ( entries.length === 0 ) return false;
        entries.sort( ( a, b ) => a[ 1 ].delay - b[ 1 ].delay );
        const [ id, { fn } ] = entries[ 0 ];
        this._timers.delete( id );
        try { fn(); } catch ( e ) { /* swallow */ }
        return true;
    }

    fireAll( max ) {
        const cap = max || 1000;
        let fired = 0;
        while ( this._timers.size > 0 && fired < cap ) {
            this.fireOne();
            fired += 1;
        }
        return fired;
    }
}

window.__clock          = new TestClock();
window.__origSetTimeout = window.setTimeout;
window.setTimeout       = ( fn, delay ) => window.__clock.setTimeout( fn, delay );
window.clearTimeout     = ( id ) => window.__clock.clearTimeout( id );
// Watchdog timer — disable auto-fire; tests drive via channel._tickWatchdog()
window.setInterval      = () => 1;
window.clearInterval    = () => {};

// flushMicrotasks helper — return a Promise that resolves after current
// microtask queue drains. Used by tests that await async onclose etc.
window.__flushMicro = function () {
    return new Promise( ( resolve ) => queueMicrotask( resolve ) );
};
"""


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def channel_page( page ):
    """
    Return a Playwright `page` already wired with the harness + ws-channel.js.

    Each test calls `channel_page.evaluate(...)` with its own JS body. Because
    init scripts run on every navigation, navigating to `about:blank` is the
    minimal way to land in a clean page-with-harness.
    """
    page.add_init_script( script=_HARNESS_JS )
    page.add_init_script( script=_MODULE_SOURCE )
    page.goto( "about:blank" )
    return page


# ---------------------------------------------------------------------------
# Test 1 — close schedules exactly one reconnect (not two)
# ---------------------------------------------------------------------------

def test_close_schedules_one_reconnect( channel_page ):
    result = channel_page.evaluate( r"""
        async () => {
            MockWebSocket.reset();
            const ch = window.__WSChannel.createChannel( {
                url            : "ws://test/queue",
                name           : "queue",
                WebSocketCtor  : MockWebSocket
            } );
            ch.connect();
            const ws1 = MockWebSocket.instances[ 0 ];
            ws1._close( 1006, "transport-fail" );
            await window.__flushMicro();
            // After onclose handler runs, exactly one backoff timer should be pending
            const pendingAfterClose = window.__clock.pending();
            // Fire backoff timer — that re-runs connect() once, creating WS2
            window.__clock.fireOne();
            return {
                pendingAfterClose : pendingAfterClose,
                instanceCount     : MockWebSocket.instances.length,
                state             : ch.state,
                attempts          : ch.attempts
            };
        }
    """ )
    assert result[ "pendingAfterClose" ] == 1, "exactly one backoff timer should be pending after one close"
    assert result[ "instanceCount" ]    == 2, "exactly one new WebSocket should have been created on reconnect (total = 2)"
    assert result[ "attempts" ]         == 1, "attempts increments by 1 per close"


# ---------------------------------------------------------------------------
# Test 2 — onerror does NOT double-schedule
# ---------------------------------------------------------------------------

def test_onerror_does_not_double_schedule( channel_page ):
    result = channel_page.evaluate( r"""
        async () => {
            MockWebSocket.reset();
            const ch = window.__WSChannel.createChannel( {
                url            : "ws://test/queue",
                name           : "queue",
                WebSocketCtor  : MockWebSocket
            } );
            ch.connect();
            // Baseline: handshake-timeout timer is pending (10000ms)
            const pendingAtConnect = window.__clock.pending();
            const delaysAtConnect  = window.__clock.pendingDelays().slice();
            const attemptsAtConnect = ch.attempts;

            const ws1 = MockWebSocket.instances[ 0 ];
            ws1._error();
            await window.__flushMicro();
            // After onerror: NO new timer should be added; attempts unchanged
            const pendingAfterError  = window.__clock.pending();
            const attemptsAfterError = ch.attempts;

            ws1._close( 1006 );
            await window.__flushMicro();
            // After onclose: handshake canceled (-1), backoff scheduled (+1) => still 1
            // Critical assertion: total instances should NOT have grown beyond 1
            const pendingAfterClose  = window.__clock.pending();
            const attemptsAfterClose = ch.attempts;
            return {
                pendingAtConnect    : pendingAtConnect,
                delaysAtConnect     : delaysAtConnect,
                attemptsAtConnect   : attemptsAtConnect,
                pendingAfterError   : pendingAfterError,
                attemptsAfterError  : attemptsAfterError,
                pendingAfterClose   : pendingAfterClose,
                attemptsAfterClose  : attemptsAfterClose,
                instanceCount       : MockWebSocket.instances.length
            };
        }
    """ )
    # Baseline: only the handshake-timeout timer (10s) is pending after connect.
    assert result[ "pendingAtConnect" ]   == 1, "handshake-timeout is the only pending timer at connect"
    assert result[ "delaysAtConnect" ]    == [ 10000 ], "the pending timer is the 10000ms handshake watchdog"
    assert result[ "attemptsAtConnect" ]  == 0
    # onerror must NOT add any new timer and must NOT touch attempts.
    assert result[ "pendingAfterError" ]  == 1, "onerror must NOT schedule a new timer (only handshake remains)"
    assert result[ "attemptsAfterError" ] == 0, "onerror must NOT increment attempts"
    # onclose: handshake canceled, backoff scheduled => still exactly 1 pending timer.
    assert result[ "pendingAfterClose" ]  == 1, "after close: handshake canceled and backoff scheduled (net 1)"
    assert result[ "attemptsAfterClose" ] == 1, "attempts incremented exactly once (by close, not error)"
    assert result[ "instanceCount" ]      == 1, "no new WebSocket constructed yet (backoff hasn't fired)"


# ---------------------------------------------------------------------------
# Test 3 — per-channel counter isolation
# ---------------------------------------------------------------------------

def test_per_channel_counter_isolation( channel_page ):
    result = channel_page.evaluate( r"""
        async () => {
            MockWebSocket.reset();
            const queue = window.__WSChannel.createChannel( { url:"ws://test/queue", name:"queue", WebSocketCtor:MockWebSocket } );
            const audio = window.__WSChannel.createChannel( { url:"ws://test/audio", name:"audio", WebSocketCtor:MockWebSocket } );
            queue.connect();
            audio.connect();
            // Fail the audio channel three times in a row
            for ( let i = 0; i < 3; i++ ) {
                const idx = MockWebSocket.instances.length - 1;
                MockWebSocket.instances[ idx ]._close( 1006 );
                await window.__flushMicro();
                window.__clock.fireOne();  // backoff -> reconnect
            }
            return { queueAttempts : queue.attempts, audioAttempts : audio.attempts };
        }
    """ )
    # Audio failed 3x then reconnected; the 3rd fire-one re-ran connect which spawned a new ws
    # but didn't fail again. So attempts went 1, 2, 3 (last fire produces a new ws still in CONNECTING)
    # Audio attempts >= 3, queue attempts == 0.
    assert result[ "queueAttempts" ] == 0, "queue channel must not be affected by audio failures"
    assert result[ "audioAttempts" ] >= 1, "audio channel attempts increased independently"


# ---------------------------------------------------------------------------
# Test 4 — auth_success resets counter
# ---------------------------------------------------------------------------

def test_auth_success_resets_counter( channel_page ):
    result = channel_page.evaluate( r"""
        async () => {
            MockWebSocket.reset();
            const ch = window.__WSChannel.createChannel( { url:"ws://test/queue", name:"queue", WebSocketCtor:MockWebSocket } );
            ch.connect();
            // Drive 5 OPEN-then-CLOSE cycles (so wasEverOpen=true and rapid-fail
            // tripwire does NOT fire — we want all 5 to count as scheduleReconnect).
            for ( let i = 0; i < 5; i++ ) {
                const idx = MockWebSocket.instances.length - 1;
                const ws  = MockWebSocket.instances[ idx ];
                ws._open();
                await window.__flushMicro();
                ws._close( 1006 );
                await window.__flushMicro();
                if ( ch.state === "BACKOFF" ) window.__clock.fireOne();
            }
            const before = ch.attempts;
            // Most recent ws is in CONNECTING. Open it, then send auth_success.
            const lastWs = MockWebSocket.instances[ MockWebSocket.instances.length - 1 ];
            lastWs._open();
            await window.__flushMicro();
            lastWs._msg( { type : "auth_success", session_id : "test" } );
            await window.__flushMicro();
            return { before : before, after : ch.attempts, state : ch.state };
        }
    """ )
    assert result[ "before" ] >= 5, "attempts should be at least 5 before auth_success"
    assert result[ "after" ]  == 0, "auth_success must zero the attempts counter"
    assert result[ "state" ]  == "CONNECTED", "state transitions to CONNECTED on auth_success"


# ---------------------------------------------------------------------------
# Test 5 — TCP open does NOT reset counter
# ---------------------------------------------------------------------------

def test_tcp_open_does_not_reset_counter( channel_page ):
    result = channel_page.evaluate( r"""
        async () => {
            MockWebSocket.reset();
            const ch = window.__WSChannel.createChannel( { url:"ws://test/queue", name:"queue", WebSocketCtor:MockWebSocket } );
            ch.connect();
            for ( let i = 0; i < 3; i++ ) {
                const idx = MockWebSocket.instances.length - 1;
                MockWebSocket.instances[ idx ]._close( 1006 );
                await window.__flushMicro();
                window.__clock.fireOne();
            }
            const before = ch.attempts;
            // Open the most recent ws WITHOUT sending auth_success
            const lastWs = MockWebSocket.instances[ MockWebSocket.instances.length - 1 ];
            lastWs._open();
            await window.__flushMicro();
            return { before : before, after : ch.attempts, state : ch.state };
        }
    """ )
    assert result[ "before" ] >= 3
    assert result[ "after" ]  == result[ "before" ], "TCP open alone must NOT reset attempts"
    assert result[ "state" ]  == "AUTHENTICATING", "state transitions to AUTHENTICATING on TCP open, not CONNECTED"


# ---------------------------------------------------------------------------
# Test 6 — circuit opens at MAX_ATTEMPTS (20)
# ---------------------------------------------------------------------------

def test_circuit_opens_at_max_attempts( channel_page ):
    result = channel_page.evaluate( r"""
        async () => {
            MockWebSocket.reset();
            let circuitOpenFired = 0;
            window.addEventListener( "ws-circuit-open", () => { circuitOpenFired += 1; } );
            const ch = window.__WSChannel.createChannel( { url:"ws://test/queue", name:"queue", WebSocketCtor:MockWebSocket } );
            ch.connect();
            // Open & fail every socket (so wasEverOpen=true on each) to defeat the rapid-fail tripwire.
            // Drive 20 close cycles.
            for ( let i = 0; i < 20; i++ ) {
                const idx = MockWebSocket.instances.length - 1;
                const ws  = MockWebSocket.instances[ idx ];
                ws._open();
                await window.__flushMicro();
                ws._close( 1006 );
                await window.__flushMicro();
                if ( ch.state === "BACKOFF" ) window.__clock.fireOne();
                if ( ch.state === "OPEN_CIRCUIT" ) break;
            }
            return {
                state             : ch.state,
                attempts          : ch.attempts,
                circuitOpenFired  : circuitOpenFired,
                lastInstanceCount : MockWebSocket.instances.length
            };
        }
    """ )
    assert result[ "state" ]            == "OPEN_CIRCUIT", "state must reach OPEN_CIRCUIT after MAX_ATTEMPTS"
    assert result[ "circuitOpenFired" ] == 1,              "ws-circuit-open event fires exactly once"
    assert result[ "attempts" ]         >= 20,             "attempts reaches 20 before circuit trip"


# ---------------------------------------------------------------------------
# Test 7 — rapid-fail tripwire opens circuit before reaching 20 attempts
# ---------------------------------------------------------------------------

def test_rapid_fail_opens_circuit_early( channel_page ):
    result = channel_page.evaluate( r"""
        async () => {
            MockWebSocket.reset();
            const ch = window.__WSChannel.createChannel( { url:"ws://test/queue", name:"queue", WebSocketCtor:MockWebSocket } );
            ch.connect();
            // Fail FIVE consecutive times WITHOUT opening (wasEverOpen stays false)
            for ( let i = 0; i < 5; i++ ) {
                const idx = MockWebSocket.instances.length - 1;
                MockWebSocket.instances[ idx ]._close( 1006 );
                await window.__flushMicro();
                if ( ch.state === "BACKOFF" ) window.__clock.fireOne();
                if ( ch.state === "OPEN_CIRCUIT" ) break;
            }
            return { state : ch.state, attempts : ch.attempts };
        }
    """ )
    assert result[ "state" ]    == "OPEN_CIRCUIT", "5 rapid no-open closes within 30s must trip the circuit"
    assert result[ "attempts" ] < 20,              "rapid-fail trip must NOT have burned the full 20-attempt budget"


# ---------------------------------------------------------------------------
# Test 8 — fullJitterDelay statistical bounds (1000 trials)
# ---------------------------------------------------------------------------

def test_full_jitter_bounds_statistical( channel_page ):
    result = channel_page.evaluate( r"""
        () => {
            const fj   = window.__WSChannel.fullJitterDelay;
            const BASE = 1000;
            const CAP  = 30000;
            let minObs =  Infinity;
            let maxObs = -Infinity;
            let outOfBounds = 0;
            for ( let attempt = 0; attempt <= 15; attempt++ ) {
                const exp = Math.min( CAP, BASE * Math.pow( 2, attempt ) );
                for ( let i = 0; i < 1000; i++ ) {
                    const d = fj( attempt, BASE, CAP );
                    if ( d < BASE || d > CAP ) outOfBounds += 1;
                    if ( d < minObs ) minObs = d;
                    if ( d > maxObs ) maxObs = d;
                }
            }
            return { minObs : minObs, maxObs : maxObs, outOfBounds : outOfBounds };
        }
    """ )
    assert result[ "outOfBounds" ] == 0,        f"all delays must be in [BASE, CAP] — observed {result['outOfBounds']} OOB"
    assert result[ "minObs" ]      >= 1000,     "lower bound is BASE_MS (1000)"
    assert result[ "maxObs" ]      <= 30000,    "upper bound is CAP_MS (30000)"


# ---------------------------------------------------------------------------
# Test 9 — generation token drops late callbacks
# ---------------------------------------------------------------------------

def test_generation_token_drops_late_callbacks( channel_page ):
    result = channel_page.evaluate( r"""
        async () => {
            MockWebSocket.reset();
            const ch = window.__WSChannel.createChannel( { url:"ws://test/queue", name:"queue", WebSocketCtor:MockWebSocket } );
            ch.connect();
            const ws1     = MockWebSocket.instances[ 0 ];
            const handler = ws1.onclose;  // capture closure bound to gen=1
            // Bump generation via close()
            ch.close();
            const beforeAttempts = ch.attempts;
            // Now invoke the OLD handler directly — must be a no-op (gen mismatch)
            if ( typeof handler === "function" ) handler( { code : 1006 } );
            return { beforeAttempts : beforeAttempts, afterAttempts : ch.attempts, state : ch.state };
        }
    """ )
    assert result[ "afterAttempts" ] == result[ "beforeAttempts" ], (
        "late callback from a stale generation must NOT increment attempts"
    )
    assert result[ "state" ] == "DISCONNECTED", "state remains DISCONNECTED after stale callback"


# ---------------------------------------------------------------------------
# Test 10 — readyState guard prevents double-construction
# ---------------------------------------------------------------------------

def test_readystate_guard_prevents_double_construction( channel_page ):
    result = channel_page.evaluate( r"""
        async () => {
            MockWebSocket.reset();
            const ch = window.__WSChannel.createChannel( { url:"ws://test/queue", name:"queue", WebSocketCtor:MockWebSocket } );
            ch.connect();
            const countAfterFirst = MockWebSocket.instances.length;
            // ws[0] is in CONNECTING — second connect() must be a no-op
            ch.connect();
            ch.connect();
            const countAfterRepeats = MockWebSocket.instances.length;
            // Now open ws[0] — readyState becomes OPEN. connect() must STILL no-op.
            MockWebSocket.instances[ 0 ]._open();
            await window.__flushMicro();
            ch.connect();
            const countAfterOpen = MockWebSocket.instances.length;
            return { countAfterFirst : countAfterFirst, countAfterRepeats : countAfterRepeats, countAfterOpen : countAfterOpen };
        }
    """ )
    assert result[ "countAfterFirst" ]   == 1, "first connect() creates exactly one socket"
    assert result[ "countAfterRepeats" ] == 1, "connect() while CONNECTING must NOT create a new socket"
    assert result[ "countAfterOpen" ]    == 1, "connect() while OPEN must NOT create a new socket"


# ---------------------------------------------------------------------------
# Test 11 — manualRetry resets state from OPEN_CIRCUIT
# ---------------------------------------------------------------------------

def test_manual_retry_resets_state( channel_page ):
    result = channel_page.evaluate( r"""
        async () => {
            MockWebSocket.reset();
            const ch = window.__WSChannel.createChannel( { url:"ws://test/queue", name:"queue", WebSocketCtor:MockWebSocket } );
            ch.connect();
            // Drive the rapid-fail trip
            for ( let i = 0; i < 5; i++ ) {
                const idx = MockWebSocket.instances.length - 1;
                MockWebSocket.instances[ idx ]._close( 1006 );
                await window.__flushMicro();
                if ( ch.state === "BACKOFF" ) window.__clock.fireOne();
                if ( ch.state === "OPEN_CIRCUIT" ) break;
            }
            const tripState    = ch.state;
            const tripAttempts = ch.attempts;
            ch.manualRetry();
            return {
                tripState        : tripState,
                tripAttempts     : tripAttempts,
                postRetryState   : ch.state,
                postRetryAttempts: ch.attempts,
                instanceCount    : MockWebSocket.instances.length
            };
        }
    """ )
    assert result[ "tripState" ]         == "OPEN_CIRCUIT"
    assert result[ "postRetryState" ]    == "CONNECTING", "manualRetry must transition to CONNECTING"
    assert result[ "postRetryAttempts" ] == 0,            "manualRetry must zero the attempts counter"
    # After manualRetry: prior socket cleaned up, new one created
    assert result[ "instanceCount" ]     >= 2,            "manualRetry creates a fresh WebSocket"


# ---------------------------------------------------------------------------
# Test 12 — handshake timeout closes the socket
# ---------------------------------------------------------------------------

def test_handshake_timeout_closes_socket( channel_page ):
    result = channel_page.evaluate( r"""
        async () => {
            MockWebSocket.reset();
            const ch = window.__WSChannel.createChannel( { url:"ws://test/queue", name:"queue", WebSocketCtor:MockWebSocket } );
            ch.connect();
            const ws = MockWebSocket.instances[ 0 ];
            const stateBefore = ws.readyState;
            // Pending timers should include the handshake timer
            const delays = window.__clock.pendingDelays();
            const hasHandshake = delays.indexOf( 10000 ) !== -1;
            // Find and fire the handshake timer specifically
            // (It's the 10000ms one; our fireOne() picks earliest, so manually find it)
            // Since the only pending timer is the handshake (no backoff yet), fireOne fires it.
            window.__clock.fireOne();
            await window.__flushMicro();
            const stateAfter = ws.readyState;
            return { stateBefore : stateBefore, stateAfter : stateAfter, hasHandshake : hasHandshake };
        }
    """ )
    assert result[ "hasHandshake" ] is True,             "handshake-timeout timer (10000ms) is scheduled at connect time"
    assert result[ "stateBefore" ] == 0,                 "socket starts in CONNECTING (readyState=0)"
    assert result[ "stateAfter" ]  == 3,                 "after handshake timeout, socket is CLOSED (readyState=3)"


# ---------------------------------------------------------------------------
# Test 13 — cleanupSocket nulls all four on* handlers
# ---------------------------------------------------------------------------

def test_cleanupSocket_nulls_handlers( channel_page ):
    result = channel_page.evaluate( r"""
        async () => {
            MockWebSocket.reset();
            const ch = window.__WSChannel.createChannel( { url:"ws://test/queue", name:"queue", WebSocketCtor:MockWebSocket } );
            ch.connect();
            const ws1 = MockWebSocket.instances[ 0 ];
            // Verify handlers exist before cleanup
            const beforeAllSet = (
                typeof ws1.onopen    === "function" &&
                typeof ws1.onclose   === "function" &&
                typeof ws1.onerror   === "function" &&
                typeof ws1.onmessage === "function"
            );
            // Force cleanup via close()
            ch.close();
            return {
                beforeAllSet     : beforeAllSet,
                afterOnopen      : ws1.onopen,
                afterOnclose     : ws1.onclose,
                afterOnerror     : ws1.onerror,
                afterOnmessage   : ws1.onmessage
            };
        }
    """ )
    assert result[ "beforeAllSet" ]    is True
    assert result[ "afterOnopen" ]    is None, "onopen nulled by cleanup"
    assert result[ "afterOnclose" ]   is None, "onclose nulled by cleanup"
    assert result[ "afterOnerror" ]   is None, "onerror nulled by cleanup"
    assert result[ "afterOnmessage" ] is None, "onmessage nulled by cleanup"


# ---------------------------------------------------------------------------
# Test 14 — visibility hidden defers connect
# ---------------------------------------------------------------------------

def test_visibility_hidden_defers_connect( channel_page ):
    result = channel_page.evaluate( r"""
        () => {
            MockWebSocket.reset();
            // Force visibilityState to "hidden"
            Object.defineProperty( document, "visibilityState", { get : () => "hidden", configurable : true } );
            const ch = window.__WSChannel.createChannel( { url:"ws://test/queue", name:"queue", WebSocketCtor:MockWebSocket } );
            ch.connect();
            const countWhileHidden = MockWebSocket.instances.length;
            // Restore to "visible" and try again
            Object.defineProperty( document, "visibilityState", { get : () => "visible", configurable : true } );
            ch.connect();
            const countWhileVisible = MockWebSocket.instances.length;
            return {
                countWhileHidden  : countWhileHidden,
                countWhileVisible : countWhileVisible,
                stateWhileHidden  : "DISCONNECTED"  // implicitly: connect was a no-op
            };
        }
    """ )
    assert result[ "countWhileHidden" ]  == 0, "connect() while hidden must not create a socket"
    assert result[ "countWhileVisible" ] == 1, "connect() while visible creates a socket"


# ---------------------------------------------------------------------------
# Test 15 — pageshow with persisted=true triggers manualRetry
# ---------------------------------------------------------------------------

def test_pageshow_persisted_full_reset( channel_page ):
    result = channel_page.evaluate( r"""
        async () => {
            MockWebSocket.reset();
            const ch = window.__WSChannel.createChannel( { url:"ws://test/queue", name:"queue", WebSocketCtor:MockWebSocket } );
            ch.connect();
            // Drive a few failures so attempts > 0
            for ( let i = 0; i < 3; i++ ) {
                const idx = MockWebSocket.instances.length - 1;
                MockWebSocket.instances[ idx ]._close( 1006 );
                await window.__flushMicro();
                if ( ch.state === "BACKOFF" ) window.__clock.fireOne();
            }
            const beforeAttempts = ch.attempts;
            // Dispatch a pageshow event with persisted=true
            const ev = new Event( "pageshow" );
            Object.defineProperty( ev, "persisted", { value : true } );
            window.dispatchEvent( ev );
            return {
                beforeAttempts : beforeAttempts,
                afterAttempts  : ch.attempts,
                afterState     : ch.state
            };
        }
    """ )
    assert result[ "beforeAttempts" ] >= 1
    assert result[ "afterAttempts" ]  == 0,           "pageshow.persisted=true must zero attempts (manualRetry path)"
    assert result[ "afterState" ]     == "CONNECTING", "pageshow.persisted=true triggers manualRetry which calls connect()"


# ---------------------------------------------------------------------------
# Test 16 — online dispatches manualRetry
# ---------------------------------------------------------------------------

def test_online_triggers_retry( channel_page ):
    result = channel_page.evaluate( r"""
        async () => {
            MockWebSocket.reset();
            const ch = window.__WSChannel.createChannel( { url:"ws://test/queue", name:"queue", WebSocketCtor:MockWebSocket } );
            ch.connect();
            // Fail a few times
            for ( let i = 0; i < 3; i++ ) {
                const idx = MockWebSocket.instances.length - 1;
                MockWebSocket.instances[ idx ]._close( 1006 );
                await window.__flushMicro();
                if ( ch.state === "BACKOFF" ) window.__clock.fireOne();
            }
            const beforeAttempts = ch.attempts;
            window.dispatchEvent( new Event( "online" ) );
            return {
                beforeAttempts : beforeAttempts,
                afterAttempts  : ch.attempts,
                afterState     : ch.state
            };
        }
    """ )
    assert result[ "beforeAttempts" ] >= 1
    assert result[ "afterAttempts" ]  == 0,            "online event must zero attempts (manualRetry)"
    assert result[ "afterState" ]     == "CONNECTING", "online triggers manualRetry → connect()"


# ---------------------------------------------------------------------------
# Test 17 — offline closes the socket (state to DISCONNECTED)
# ---------------------------------------------------------------------------

def test_offline_closes_socket( channel_page ):
    result = channel_page.evaluate( r"""
        async () => {
            MockWebSocket.reset();
            const ch = window.__WSChannel.createChannel( { url:"ws://test/queue", name:"queue", WebSocketCtor:MockWebSocket } );
            ch.connect();
            // Open the ws so we're in AUTHENTICATING (or further)
            MockWebSocket.instances[ 0 ]._open();
            await window.__flushMicro();
            const beforeState = ch.state;
            window.dispatchEvent( new Event( "offline" ) );
            return {
                beforeState : beforeState,
                afterState  : ch.state
            };
        }
    """ )
    assert result[ "beforeState" ] in ( "AUTHENTICATING", "CONNECTING" )
    assert result[ "afterState" ]  == "DISCONNECTED", "offline event must close the socket → DISCONNECTED"


# ---------------------------------------------------------------------------
# Test 18 — watchdog only fires scheduleReconnect when CLOSED + no pending
# ---------------------------------------------------------------------------

def test_watchdog_only_fires_when_closed_and_no_pending( channel_page ):
    result = channel_page.evaluate( r"""
        async () => {
            MockWebSocket.reset();
            const ch = window.__WSChannel.createChannel( { url:"ws://test/queue", name:"queue", WebSocketCtor:MockWebSocket } );
            // ----- Case A: state=BACKOFF (timer pending) — watchdog must no-op -----
            ch.connect();
            const ws1 = MockWebSocket.instances[ 0 ];
            ws1._close( 1006 );
            await window.__flushMicro();
            // Now state=BACKOFF, attempts=1
            const stateBackoff = ch.state;
            const attemptsBackoff = ch.attempts;
            ch._tickWatchdog();
            const stateAfterBackoffTick = ch.state;
            const attemptsAfterBackoffTick = ch.attempts;
            // ----- Case B: state=CONNECTED — watchdog must no-op -----
            // Get to CONNECTED via auth_success
            window.__clock.fireOne();  // backoff fires → connect → ws2
            const ws2 = MockWebSocket.instances[ 1 ];
            ws2._open();
            await window.__flushMicro();
            ws2._msg( { type : "auth_success" } );
            await window.__flushMicro();
            const stateConnected = ch.state;
            const attemptsConnected = ch.attempts;
            ch._tickWatchdog();
            const attemptsAfterConnectedTick = ch.attempts;
            // ----- Case C: state=DISCONNECTED, no pending timer, no live ws — watchdog schedules -----
            ch.close();
            // Now state=DISCONNECTED, no backoff timer, ws nulled
            const pendingBeforeTick = window.__clock.pending();
            ch._tickWatchdog();
            const stateAfterIdleTick = ch.state;
            const pendingAfterTick = window.__clock.pending();
            return {
                stateBackoff             : stateBackoff,
                stateAfterBackoffTick    : stateAfterBackoffTick,
                attemptsBackoff          : attemptsBackoff,
                attemptsAfterBackoffTick : attemptsAfterBackoffTick,
                stateConnected           : stateConnected,
                attemptsConnected        : attemptsConnected,
                attemptsAfterConnectedTick : attemptsAfterConnectedTick,
                pendingBeforeTick        : pendingBeforeTick,
                stateAfterIdleTick       : stateAfterIdleTick,
                pendingAfterTick         : pendingAfterTick
            };
        }
    """ )
    # Case A: BACKOFF, watchdog no-op
    assert result[ "stateBackoff" ]            == "BACKOFF"
    assert result[ "stateAfterBackoffTick" ]   == "BACKOFF",  "watchdog must NOT mutate state in BACKOFF"
    assert result[ "attemptsAfterBackoffTick" ] == result[ "attemptsBackoff" ], "watchdog must NEVER touch attempts"
    # Case B: CONNECTED, watchdog no-op
    assert result[ "stateConnected" ]               == "CONNECTED"
    assert result[ "attemptsAfterConnectedTick" ]   == 0,     "watchdog leaves CONNECTED unchanged"
    # Case C: DISCONNECTED + idle, watchdog schedules a reconnect
    assert result[ "pendingBeforeTick" ]   == 0
    assert result[ "stateAfterIdleTick" ]  == "BACKOFF",  "watchdog from idle DISCONNECTED schedules reconnect → BACKOFF"
    assert result[ "pendingAfterTick" ]    == 1,          "watchdog scheduleReconnect adds exactly one timer"


# ---------------------------------------------------------------------------
# Test 19 — watchdog ticks NEVER reset the counter
# ---------------------------------------------------------------------------

def test_watchdog_never_resets_counter( channel_page ):
    result = channel_page.evaluate( r"""
        async () => {
            MockWebSocket.reset();
            const ch = window.__WSChannel.createChannel( { url:"ws://test/queue", name:"queue", WebSocketCtor:MockWebSocket } );
            ch.connect();
            // Drive 5 OPEN-then-CLOSE cycles (so wasEverOpen=true and rapid-fail
            // tripwire does NOT fire — we want 5 honest scheduleReconnect bumps).
            for ( let i = 0; i < 5; i++ ) {
                const idx = MockWebSocket.instances.length - 1;
                const ws  = MockWebSocket.instances[ idx ];
                ws._open();
                await window.__flushMicro();
                ws._close( 1006 );
                await window.__flushMicro();
                if ( ch.state === "BACKOFF" ) window.__clock.fireOne();
            }
            const before = ch.attempts;
            for ( let i = 0; i < 10; i++ ) ch._tickWatchdog();
            return { before : before, after : ch.attempts };
        }
    """ )
    assert result[ "before" ] >= 5
    assert result[ "after" ]  == result[ "before" ], "10 watchdog ticks must NOT change attempts"


# ---------------------------------------------------------------------------
# Test 20 — close 4001 immediately opens the circuit (no decrement)
# ---------------------------------------------------------------------------

def test_close_4001_immediate_open_circuit( channel_page ):
    result = channel_page.evaluate( r"""
        async () => {
            MockWebSocket.reset();
            let circuitOpenFired = 0;
            window.addEventListener( "ws-circuit-open", () => { circuitOpenFired += 1; } );
            const ch = window.__WSChannel.createChannel( { url:"ws://test/queue", name:"queue", WebSocketCtor:MockWebSocket } );
            ch.connect();
            const ws1 = MockWebSocket.instances[ 0 ];
            // Drive 3 normal failures first so attempts > 0
            for ( let i = 0; i < 3; i++ ) {
                const idx = MockWebSocket.instances.length - 1;
                const ws  = MockWebSocket.instances[ idx ];
                ws._open();
                await window.__flushMicro();
                ws._close( 1006 );
                await window.__flushMicro();
                if ( ch.state === "BACKOFF" ) window.__clock.fireOne();
            }
            const beforeAttempts = ch.attempts;
            const beforeState    = ch.state;
            // Now close with 4001 on the latest socket
            const lastWs = MockWebSocket.instances[ MockWebSocket.instances.length - 1 ];
            lastWs._open();
            await window.__flushMicro();
            lastWs._close( 4001, "invalid token" );
            await window.__flushMicro();
            return {
                beforeAttempts   : beforeAttempts,
                beforeState      : beforeState,
                afterAttempts    : ch.attempts,
                afterState       : ch.state,
                circuitOpenFired : circuitOpenFired
            };
        }
    """ )
    assert result[ "beforeAttempts" ] >= 3
    assert result[ "afterState" ]     == "OPEN_CIRCUIT", "close code 4001 must trip the circuit immediately"
    assert result[ "afterAttempts" ]  == result[ "beforeAttempts" ], (
        "close 4001 must NOT decrement attempts (test 20 invariant)"
    )
    assert result[ "circuitOpenFired" ] == 1, "ws-circuit-open dispatched exactly once on 4001"
