/**
 * ws-channel.js — Per-channel WebSocket state machine for the Lupin
 * notifications front-end.
 *
 * Phase 1 of the WS reconnect circuit-breaker milestone. This module is
 * loaded only by tests during Phase 1; `notifications.js` is wired in
 * during Phase 2.
 *
 * Design source: src/rnd/v0.1.7/2026.05.02-ws-reconnect-circuit-breaker/
 *   - 01-design-review.md §2 (synthesized design + Q1-Q12 frozen)
 *   - 02-phase-1-ws-channel-module.md (module spec)
 *   - 07-test-strategy.md §Layer 1 (unit-test expectations)
 */

"use strict";

// ===========================================================================
// Public state enum (frozen to keep consumers honest)
// ===========================================================================

export const STATE = Object.freeze( {
    DISCONNECTED   : "DISCONNECTED",
    CONNECTING     : "CONNECTING",
    AUTHENTICATING : "AUTHENTICATING",
    CONNECTED      : "CONNECTED",
    BACKOFF        : "BACKOFF",
    OPEN_CIRCUIT   : "OPEN_CIRCUIT"
} );

// ===========================================================================
// Public event names dispatched on `window`
// ===========================================================================

export const CIRCUIT_OPEN_EVENT = "ws-circuit-open";
export const STATE_CHANGE_EVENT = "ws-state-change";

// ===========================================================================
// Class-level constants (per 02-phase-1-ws-channel-module.md §Class-Level
// Constants — NOT made INI keys in v1; tunable via code edit)
// ===========================================================================

const MAX_ATTEMPTS_PER_CHANNEL = 20;
const BACKOFF_BASE_MS          = 1000;
const BACKOFF_CAP_MS           = 30000;
const RAPID_FAIL_COUNT         = 5;
const RAPID_FAIL_WINDOW_MS     = 30000;
const HANDSHAKE_TIMEOUT_MS     = 10000;
const WATCHDOG_INTERVAL_MS     = 30000;

// WebSocket.readyState numeric constants (avoid global-ctor coupling)
const WS_CONNECTING = 0;
const WS_OPEN       = 1;

// Auth-failure close codes — channel reacts by going straight to OPEN_CIRCUIT
// (no attempts decrement, no further reconnect). The consumer (NotificationsUI)
// is responsible for refreshing the token and calling `manualRetry()` if the
// failure is transient (e.g. expired access token). 4001/4002/4003 mapping is
// frozen in 01-design-review.md Q11 and added server-side in Phase 5.
const PERMANENT_CLOSE_CODES = new Set( [ 4001, 4002, 4003 ] );

// ===========================================================================
// Public helper — full-jitter exponential backoff
// (Brooker / AWS Architecture Blog: "Exponential Backoff And Jitter")
// ===========================================================================

/**
 * Full-jitter backoff delay in milliseconds.
 *
 * Requires:
 *   - attempt is a non-negative integer
 *   - base is a positive integer (ms)
 *   - cap is a positive integer (ms) and cap >= base
 *
 * Ensures:
 *   - Returns an integer in [base, min(cap, base * 2^attempt)]
 *   - Lower bound is `base` (NOT zero), so the first retry has a floor
 */
export function fullJitterDelay( attempt, base, cap ) {
    const exp   = Math.min( cap, base * Math.pow( 2, attempt ) );
    const span  = Math.max( 0, exp - base );
    return Math.floor( base + Math.random() * span );
}

// ===========================================================================
// Factory — `createChannel( opts )`
// ===========================================================================

/**
 * Create a per-channel WebSocket state machine.
 *
 * Requires:
 *   - opts.url is a non-empty wss:// or ws:// URL string
 *   - opts.name is a non-empty channel name (e.g. "queue", "audio")
 *   - opts.onMessage (optional) is invoked on every successfully-parsed JSON envelope
 *   - opts.onBinaryMessage (optional) is invoked when a binary frame arrives (Blob or
 *     ArrayBuffer). Required by the audio channel — the audio WebSocket streams MP3/PCM
 *     chunks as binary frames; without this callback, binary frames are silently dropped.
 *   - opts.onAuthSuccess (optional) is invoked on the first envelope with type === "auth_success"
 *   - opts.onCircuitOpen (optional) is invoked when the breaker trips
 *   - opts.onStateChange (optional) is invoked on every state transition
 *   - opts.WebSocketCtor (optional) overrides the global WebSocket — used by tests
 *
 * Ensures:
 *   - Returns { connect, manualRetry, close, destroy, state, attempts, name }
 *   - Exactly one reconnect path: onclose -> scheduleReconnect (onerror NEVER schedules)
 *   - Counter resets only on `auth_success` envelope; never on TCP open, never on timer
 *   - readyState guard prevents `new WebSocket()` while the prior socket is
 *     CONNECTING or OPEN (load-bearing for Chromium 255-pending-handshake fix)
 *   - Generation token increments per connect(); late callbacks dropped
 *   - Cleanup nulls all four `on*` handlers and calls close(1000,"cleanup") on prior socket
 *   - Dispatches CIRCUIT_OPEN_EVENT on window when budget exhausted
 *   - Dispatches STATE_CHANGE_EVENT on window on every state transition
 *   - Auto-attaches window listeners for online/offline/pageshow/pagehide/freeze/resume
 *   - `connect()` no-ops while document.visibilityState === "hidden"
 */
export function createChannel( opts ) {
    if ( !opts || typeof opts.url !== "string" || opts.url.length === 0 ) {
        throw new Error( "ws-channel: opts.url is required (non-empty string)" );
    }
    if ( typeof opts.name !== "string" || opts.name.length === 0 ) {
        throw new Error( "ws-channel: opts.name is required (non-empty string)" );
    }

    const url             = opts.url;
    const name            = opts.name;
    const onMessage       = typeof opts.onMessage       === "function" ? opts.onMessage       : null;
    const onBinaryMessage = typeof opts.onBinaryMessage === "function" ? opts.onBinaryMessage : null;
    const onAuthSuccess   = typeof opts.onAuthSuccess   === "function" ? opts.onAuthSuccess   : null;
    const onCircuitOpen   = typeof opts.onCircuitOpen   === "function" ? opts.onCircuitOpen   : null;
    const onStateChange   = typeof opts.onStateChange   === "function" ? opts.onStateChange   : null;
    // Phase 2 extension: authMessage builder. Channel calls authMessage() once on
    // AUTHENTICATING and sends the JSON-stringified result via the live socket.
    // If absent, channel does nothing — consumer is responsible for sending auth.
    const authMessage   = typeof opts.authMessage   === "function" ? opts.authMessage   : null;
    const WSCtor        = opts.WebSocketCtor || ( typeof window !== "undefined" ? window.WebSocket : undefined );

    if ( typeof WSCtor !== "function" ) {
        throw new Error( "ws-channel: WebSocket constructor not found (pass opts.WebSocketCtor in non-browser environments)" );
    }

    // Internal state (closure-private)
    let ws               = null;
    let state            = STATE.DISCONNECTED;
    let attempts         = 0;
    let generation       = 0;
    let backoffTimerId   = null;
    let handshakeTimerId = null;
    let watchdogTimerId  = null;
    let recentFailures   = [];
    let wasEverOpen      = false;
    let destroyed        = false;

    // -----------------------------------------------------------------------
    // State transition helper — single point of dispatch for STATE_CHANGE_EVENT
    // -----------------------------------------------------------------------
    function setState( newState ) {
        if ( state === newState ) return;
        const prev = state;
        state = newState;
        const detail = { name : name, prev : prev, state : newState, attempts : attempts };
        if ( typeof window !== "undefined" && typeof window.dispatchEvent === "function" ) {
            try {
                window.dispatchEvent( new CustomEvent( STATE_CHANGE_EVENT, { detail : detail } ) );
            } catch ( e ) { /* ignore — older browsers without CustomEvent */ }
        }
        if ( onStateChange ) {
            try { onStateChange( newState, prev, detail ); } catch ( e ) { /* swallow consumer errors */ }
        }
    }

    // -----------------------------------------------------------------------
    // Cleanup — null handlers + close prior socket. Releases Chromium's
    // per-renderer pending-handshake slot.
    // -----------------------------------------------------------------------
    function cleanupSocket( oldWs ) {
        if ( !oldWs ) return;
        oldWs.onopen    = null;
        oldWs.onclose   = null;
        oldWs.onerror   = null;
        oldWs.onmessage = null;
        try { oldWs.close( 1000, "cleanup" ); } catch ( e ) { /* already closed/closing */ }
    }

    // -----------------------------------------------------------------------
    // Cancel any pending timers (does NOT touch generation or attempts)
    // -----------------------------------------------------------------------
    function cancelBackoff() {
        if ( backoffTimerId !== null ) {
            clearTimeout( backoffTimerId );
            backoffTimerId = null;
        }
    }
    function cancelHandshake() {
        if ( handshakeTimerId !== null ) {
            clearTimeout( handshakeTimerId );
            handshakeTimerId = null;
        }
    }

    // -----------------------------------------------------------------------
    // connect() — public entry point. Idempotent under readyState/visibility/
    // OPEN_CIRCUIT/destroyed guards.
    // -----------------------------------------------------------------------
    function connect() {
        if ( destroyed ) return;

        // Visibility guard — hidden tab must NOT spend reconnect budget
        // (the visibility-restore path in NotificationsUI re-arms via connect())
        if ( typeof document !== "undefined" && document.visibilityState === "hidden" ) return;

        // Open-circuit guard — only manualRetry() can leave OPEN_CIRCUIT
        if ( state === STATE.OPEN_CIRCUIT ) return;

        // readyState guard — load-bearing for the 255-slot fix. If a prior
        // socket is CONNECTING or OPEN, we have no business creating another.
        if ( ws && ( ws.readyState === WS_CONNECTING || ws.readyState === WS_OPEN ) ) return;

        // Cancel any pending backoff timer (we're connecting NOW)
        cancelBackoff();

        // Cleanup prior reference (CLOSING/CLOSED — releases the slot)
        if ( ws ) {
            cleanupSocket( ws );
            ws = null;
        }

        // Bind callbacks to a fresh generation token. Late callbacks from the
        // prior generation will check `myGen !== generation` and drop silently.
        generation += 1;
        const myGen = generation;
        wasEverOpen = false;

        setState( STATE.CONNECTING );

        let socket;
        try {
            socket = new WSCtor( url );
        } catch ( err ) {
            // Construction itself failed (rare — invalid URL, CSP, etc.).
            // Treat as a close event so the breaker accounting is honored.
            ws = null;
            scheduleReconnect();
            return;
        }
        ws = socket;

        socket.onopen = function () {
            if ( myGen !== generation ) return;
            wasEverOpen = true;
            cancelHandshake();
            setState( STATE.AUTHENTICATING );
            // Phase 2 extension: send the auth_request the moment we have an
            // OPEN socket. The state-machine view is "AUTHENTICATING means
            // we've sent auth and are awaiting auth_success."
            if ( authMessage && ws && ws.readyState === WS_OPEN ) {
                let payload = null;
                try { payload = authMessage(); } catch ( e ) { /* swallow builder errors */ }
                if ( payload !== null && payload !== undefined ) {
                    try { ws.send( typeof payload === "string" ? payload : JSON.stringify( payload ) ); }
                    catch ( e ) { /* socket may have raced to closing — onclose handles it */ }
                }
            }
        };

        socket.onmessage = function ( ev ) {
            if ( myGen !== generation ) return;
            // Binary frames (audio chunks) bypass JSON parse and route to onBinaryMessage.
            // Without this branch, JSON.parse(Blob) throws, the catch returns, and the
            // frame is silently dropped — the regression that broke notifications-UI TTS
            // playback after the WSChannel facade was introduced.
            if ( ev.data instanceof Blob || ev.data instanceof ArrayBuffer ) {
                if ( onBinaryMessage ) {
                    try { onBinaryMessage( ev.data ); } catch ( e ) { /* swallow */ }
                }
                return;
            }
            let envelope = null;
            try { envelope = JSON.parse( ev.data ); } catch ( e ) { return; }
            if ( envelope && envelope.type === "auth_success" ) {
                attempts       = 0;
                recentFailures = [];
                setState( STATE.CONNECTED );
                if ( onAuthSuccess ) {
                    try { onAuthSuccess( envelope ); } catch ( e ) { /* swallow */ }
                }
            }
            if ( onMessage ) {
                try { onMessage( envelope ); } catch ( e ) { /* swallow */ }
            }
        };

        // RFC 6455 §7.1.4: error MUST precede close. Logging only — never schedule.
        // Double-handling onerror + onclose is the proximate bug we are fixing.
        socket.onerror = function () {
            if ( myGen !== generation ) return;
            // intentionally no-op (close handler is the single owner)
        };

        socket.onclose = function ( ev ) {
            if ( myGen !== generation ) return;
            cancelHandshake();
            const code = ev && typeof ev.code === "number" ? ev.code : 1006;
            if ( PERMANENT_CLOSE_CODES.has( code ) ) {
                // Phase 5: pass the actual close code + reason so the consumer
                // (NotificationsUI) can route 4001 → token-refresh path,
                // 4002 → "session displaced" banner, 4003 → "permission denied".
                openCircuit( "auth-permanent", code );
                return;
            }
            handleClose();
        };

        // Handshake-timeout watchdog: a socket stuck in CONNECTING burns a
        // renderer slot indefinitely. Force-close at HANDSHAKE_TIMEOUT_MS.
        cancelHandshake();
        handshakeTimerId = setTimeout( function () {
            handshakeTimerId = null;
            if ( myGen !== generation ) return;
            if ( state === STATE.CONNECTING || state === STATE.AUTHENTICATING ) {
                if ( ws ) {
                    try { ws.close( 1000, "handshake-timeout" ); } catch ( e ) { /* ignore */ }
                }
            }
        }, HANDSHAKE_TIMEOUT_MS );
    }

    // -----------------------------------------------------------------------
    // handleClose — non-permanent close path. Books rapid-fail accounting
    // BEFORE incrementing the attempt counter (so a rapid-flap can trip the
    // breaker without first burning the 20-attempt budget).
    // -----------------------------------------------------------------------
    function handleClose() {
        if ( !wasEverOpen ) {
            const now = Date.now();
            recentFailures.push( now );
            recentFailures = recentFailures.filter( function ( t ) { return now - t <= RAPID_FAIL_WINDOW_MS; } );
            if ( recentFailures.length >= RAPID_FAIL_COUNT ) {
                openCircuit( "rapid-fail", null );
                return;
            }
        }
        scheduleReconnect();
    }

    // -----------------------------------------------------------------------
    // scheduleReconnect — sole reconnect scheduler. Increments attempts,
    // checks budget, schedules next connect() with jittered delay.
    // -----------------------------------------------------------------------
    function scheduleReconnect() {
        if ( destroyed ) return;
        attempts += 1;
        if ( attempts >= MAX_ATTEMPTS_PER_CHANNEL ) {
            openCircuit( "budget-exhausted", null );
            return;
        }
        setState( STATE.BACKOFF );
        const delay = fullJitterDelay( attempts, BACKOFF_BASE_MS, BACKOFF_CAP_MS );
        cancelBackoff();
        backoffTimerId = setTimeout( function () {
            backoffTimerId = null;
            connect();
        }, delay );
    }

    // -----------------------------------------------------------------------
    // openCircuit — terminal state until manualRetry(). Cancels timers,
    // releases the socket, dispatches CIRCUIT_OPEN_EVENT with detail.reason
    // so the consumer can route the response (Phase 5: auth-permanent →
    // token-refresh path; budget-exhausted / rapid-fail → standard banner).
    //
    // Phase 5: detail now carries `reason` (string) and optional `code`
    // (numeric WebSocket close code) alongside the existing name + attempts.
    //
    // @param {string} [reason] one of "auth-permanent" | "budget-exhausted" |
    //   "rapid-fail" — defaults to "budget-exhausted" for backward compat
    //   with any direct callers that did not pass a reason.
    // @param {number} [code] the underlying WebSocket close code when the
    //   reason is "auth-permanent" (e.g. 4001/4002/4003). null otherwise.
    // -----------------------------------------------------------------------
    function openCircuit( reason, code ) {
        cancelBackoff();
        cancelHandshake();
        if ( ws ) {
            cleanupSocket( ws );
            ws = null;
        }
        setState( STATE.OPEN_CIRCUIT );
        const detail = {
            name     : name,
            attempts : attempts,
            reason   : reason || "budget-exhausted",
            code     : ( typeof code === "number" ) ? code : null
        };
        if ( typeof window !== "undefined" && typeof window.dispatchEvent === "function" ) {
            try {
                window.dispatchEvent( new CustomEvent( CIRCUIT_OPEN_EVENT, { detail : detail } ) );
            } catch ( e ) { /* ignore */ }
        }
        if ( onCircuitOpen ) {
            try { onCircuitOpen( detail ); } catch ( e ) { /* swallow */ }
        }
    }

    // -----------------------------------------------------------------------
    // manualRetry — user-driven half-open probe. Zeros all retry accounting
    // and immediately attempts a fresh connect.
    //
    // Phase 4 idempotency guard: when state === CONNECTED, manualRetry is a
    // no-op. Rationale per `05-phase-4-page-lifecycle.md` §Risks row 3 — the
    // `online` event firing on a flaky network mid-session would otherwise
    // cleanup-and-reconnect already-OPEN channels, breaking live traffic
    // for no benefit. The guard does NOT fire from OPEN_CIRCUIT (Phase 1
    // test 11 still works) or from BACKOFF (the half-open probe fast-paths
    // out of backoff to retry immediately).
    // -----------------------------------------------------------------------
    function manualRetry() {
        if ( destroyed ) return;
        if ( state === STATE.CONNECTED ) return;
        attempts       = 0;
        recentFailures = [];
        cancelBackoff();
        cancelHandshake();
        if ( ws ) {
            cleanupSocket( ws );
            ws = null;
        }
        // Bump generation so any straggler callback bound to the prior socket
        // is dropped before its handler can mutate counters again.
        generation += 1;
        setState( STATE.DISCONNECTED );
        connect();
    }

    // -----------------------------------------------------------------------
    // send — public proxy to ws.send. Returns true if the payload was handed
    // to a live socket; false if the channel is not OPEN. Caller decides
    // whether to retry / queue. Phase 2 extension.
    // -----------------------------------------------------------------------
    function send( payload ) {
        if ( !ws ) return false;
        if ( ws.readyState !== WS_OPEN ) return false;
        const data = typeof payload === "string" ? payload : JSON.stringify( payload );
        try { ws.send( data ); return true; }
        catch ( e ) { return false; }
    }

    // -----------------------------------------------------------------------
    // close — external close. Releases socket, does NOT schedule reconnect.
    // -----------------------------------------------------------------------
    function close() {
        cancelBackoff();
        cancelHandshake();
        if ( ws ) {
            cleanupSocket( ws );
            ws = null;
        }
        // Bump generation to drop any in-flight callbacks
        generation += 1;
        setState( STATE.DISCONNECTED );
    }

    // -----------------------------------------------------------------------
    // tickWatchdog — periodic reconciliation. Re-arms scheduleReconnect ONLY
    // when truly idle (state === DISCONNECTED, no pending timer, no live ws).
    // NEVER touches the attempts counter (Q3 frozen).
    // -----------------------------------------------------------------------
    function tickWatchdog() {
        if ( destroyed ) return;
        if ( typeof document !== "undefined" && document.visibilityState === "hidden" ) return;
        if ( state === STATE.OPEN_CIRCUIT ) return;
        if ( state === STATE.BACKOFF ) return;
        if ( state === STATE.CONNECTING ) return;
        if ( state === STATE.AUTHENTICATING ) return;
        if ( state === STATE.CONNECTED ) return;
        // state === DISCONNECTED
        if ( backoffTimerId !== null ) return;
        if ( ws && ( ws.readyState === WS_CONNECTING || ws.readyState === WS_OPEN ) ) return;
        scheduleReconnect();
    }

    // -----------------------------------------------------------------------
    // Window / document lifecycle handlers (Q9 frozen — v1, not v1.1)
    //
    // These are attached at construction. NotificationsUI's Phase 4 wiring
    // is an additional cross-channel orchestration layer; the handlers are
    // idempotent (manualRetry on CONNECTED no-ops; close on DISCONNECTED
    // no-ops) so the duplication is safe.
    // -----------------------------------------------------------------------
    function _onOnline()   { manualRetry(); }
    function _onOffline()  { close(); }
    function _onPageshow( ev ) { if ( ev && ev.persisted ) manualRetry(); }
    function _onPagehide() { close(); }
    function _onFreeze()   { close(); }
    function _onResume()   { connect(); }

    if ( typeof window !== "undefined" && typeof window.addEventListener === "function" ) {
        window.addEventListener( "online",   _onOnline );
        window.addEventListener( "offline",  _onOffline );
        window.addEventListener( "pageshow", _onPageshow );
        window.addEventListener( "pagehide", _onPagehide );
    }
    if ( typeof document !== "undefined" && typeof document.addEventListener === "function" ) {
        document.addEventListener( "freeze", _onFreeze );
        document.addEventListener( "resume", _onResume );
    }

    // Watchdog timer
    watchdogTimerId = setInterval( tickWatchdog, WATCHDOG_INTERVAL_MS );

    // -----------------------------------------------------------------------
    // destroy — full teardown. Removes window listeners, cancels timers,
    // releases socket. Safe to call multiple times.
    // -----------------------------------------------------------------------
    function destroy() {
        if ( destroyed ) return;
        destroyed = true;
        if ( watchdogTimerId !== null ) {
            clearInterval( watchdogTimerId );
            watchdogTimerId = null;
        }
        close();
        if ( typeof window !== "undefined" && typeof window.removeEventListener === "function" ) {
            window.removeEventListener( "online",   _onOnline );
            window.removeEventListener( "offline",  _onOffline );
            window.removeEventListener( "pageshow", _onPageshow );
            window.removeEventListener( "pagehide", _onPagehide );
        }
        if ( typeof document !== "undefined" && typeof document.removeEventListener === "function" ) {
            document.removeEventListener( "freeze", _onFreeze );
            document.removeEventListener( "resume", _onResume );
        }
    }

    // Public API — frozen so consumers can't reassign methods at runtime
    return Object.freeze( {
        connect       : connect,
        manualRetry   : manualRetry,
        close         : close,
        destroy       : destroy,
        send          : send,
        get state()    { return state;    },
        get attempts() { return attempts; },
        get name()     { return name;     },
        // Test hook — exposed so unit tests can drive the watchdog without
        // waiting WATCHDOG_INTERVAL_MS wall-clock seconds.
        _tickWatchdog : tickWatchdog
    } );
}
