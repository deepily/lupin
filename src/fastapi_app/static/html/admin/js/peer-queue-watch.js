/**
 * Peer Queue Watch — admin UI widget.
 *
 * Thin controller around the server-side watcher at
 *   POST /api/admin/peer-queue-watch/start
 *   POST /api/admin/peer-queue-watch/stop
 *   GET  /api/admin/peer-queue-watch/status
 *
 * The backend fires the high-priority voice notification on drain;
 * this UI just observes and visualizes state.
 */

( function() {
    'use strict';

    // Allowed peer hosts. Values MUST match the config whitelist
    // ('peer queue allowed hosts' in lupin-app.ini). These are the
    // docker-compose service names + in-container port (7999), not the
    // host-mapped ports — the dev container reaches peers via the
    // compose network, not via localhost.
    const ALLOWED_HOSTS = [
        { value: 'lupin-rest-test:7999', label: 'lupin-rest-test:7999 (test server, host :8000)' },
        { value: 'lupin-rest-dev:7999',  label: 'lupin-rest-dev:7999 (dev server,  host :7999)' }
    ];

    const STORAGE_KEY     = 'lupin:pqw:settings';
    const STATUS_POLL_MS  = 10000;   // UI refresh rate (separate from watcher interval)
    const MAX_LOG_ENTRIES = 50;

    let statusPollHandle = null;
    let lastDrainedAt    = null;     // remember so we only log the drain transition once

    // ========================================================================
    // DOM
    // ========================================================================
    const $ = ( id ) => document.getElementById( id );

    function qs() {
        return {
            hostSel      : $( 'pqw-host' ),
            signalSel    : $( 'pqw-signal' ),
            intervalIn   : $( 'pqw-interval' ),
            stableForIn  : $( 'pqw-stable-for' ),
            startBtn     : $( 'pqw-start-btn' ),
            stopBtn      : $( 'pqw-stop-btn' ),
            indicator    : $( 'pqw-indicator' ),
            state        : $( 'pqw-state' ),
            hostVal      : $( 'pqw-host-val' ),
            runVal       : $( 'pqw-run-val' ),
            todoVal      : $( 'pqw-todo-val' ),
            zeroVal      : $( 'pqw-zero-val' ),
            lastPoll     : $( 'pqw-last-poll' ),
            errorLine    : $( 'pqw-error' ),
            log          : $( 'pqw-log' )
        };
    }

    // ========================================================================
    // localStorage
    // ========================================================================
    function loadSettings() {
        try {
            const raw = localStorage.getItem( STORAGE_KEY );
            return raw ? JSON.parse( raw ) : null;
        } catch ( e ) {
            return null;
        }
    }

    function saveSettings( s ) {
        try { localStorage.setItem( STORAGE_KEY, JSON.stringify( s ) ); }
        catch ( e ) { /* ignore */ }
    }

    function currentFormValues() {
        const el = qs();
        return {
            host       : el.hostSel.value,
            signal     : el.signalSel.value,
            interval   : parseInt( el.intervalIn.value, 10 ),
            stable_for : parseInt( el.stableForIn.value, 10 )
        };
    }

    // ========================================================================
    // Log
    // ========================================================================
    function log( msg, klass ) {
        const el = qs().log;
        const ts = new Date().toLocaleTimeString();
        const entry = document.createElement( 'div' );
        entry.className = 'pqw-log-entry' + ( klass ? ' ' + klass : '' );
        entry.textContent = `[${ts}] ${msg}`;
        el.appendChild( entry );
        while ( el.children.length > MAX_LOG_ENTRIES ) el.removeChild( el.firstChild );
        el.scrollTop = el.scrollHeight;
    }

    // ========================================================================
    // API
    // ========================================================================
    async function callStart() {
        const v = currentFormValues();
        const body = {
            host             : v.host,
            signal           : v.signal,
            interval_seconds : v.interval,
            stable_for       : v.stable_for,
            priority         : 'high'
        };
        return await apiCall( '/api/admin/peer-queue-watch/start', 'POST', body );
    }

    async function callStop() {
        return await apiCall( '/api/admin/peer-queue-watch/stop', 'POST', {} );
    }

    async function callStatus() {
        return await apiCall( '/api/admin/peer-queue-watch/status', 'GET' );
    }

    // ========================================================================
    // Status render
    // ========================================================================
    function render( s ) {
        const el = qs();

        el.indicator.classList.toggle( 'active', !!s.active );
        el.state.textContent    = s.active ? 'active' : 'inactive';
        el.state.className      = 'pqw-stat-value' + ( s.active ? ' running' : '' );
        el.hostVal.textContent  = s.host || '—';
        el.runVal.textContent   = ( s.last_run  === null || s.last_run  === undefined ) ? '—' : String( s.last_run );
        el.todoVal.textContent  = ( s.last_todo === null || s.last_todo === undefined ) ? '—' : String( s.last_todo );
        el.zeroVal.textContent  = String( s.consecutive_zero || 0 );
        el.lastPoll.textContent = s.last_poll_at ? new Date( s.last_poll_at ).toLocaleTimeString() : '—';

        const drained = s.last_run === 0 && ( s.signal !== 'run+todo' || s.last_todo === 0 );
        if ( drained ) {
            el.runVal.className  = 'pqw-stat-value drained';
            el.todoVal.className = 'pqw-stat-value drained';
        } else {
            el.runVal.className  = 'pqw-stat-value';
            el.todoVal.className = 'pqw-stat-value';
        }

        if ( s.last_error ) {
            el.errorLine.style.display = 'block';
            el.errorLine.textContent   = `Last error: ${s.last_error}`;
        } else {
            el.errorLine.style.display = 'none';
        }

        el.startBtn.disabled = !!s.active;
        el.stopBtn.disabled  = !s.active;

        // Detect drain transition (first time we see drained_at)
        if ( s.drained_at && s.drained_at !== lastDrainedAt ) {
            lastDrainedAt = s.drained_at;
            log( `DRAIN: ${s.host} drained at ${new Date( s.drained_at ).toLocaleTimeString()} — voice notification dispatched by backend`, 'drain' );
        }
    }

    // ========================================================================
    // Status polling
    // ========================================================================
    async function pollStatus() {
        try {
            const s = await callStatus();
            render( s );
        } catch ( e ) {
            console.error( 'status poll failed:', e );
            log( `status poll failed: ${e.message}`, 'error' );
        }
    }

    function startStatusPolling() {
        if ( statusPollHandle !== null ) return;
        pollStatus();
        statusPollHandle = setInterval( pollStatus, STATUS_POLL_MS );
    }

    function stopStatusPolling() {
        if ( statusPollHandle !== null ) {
            clearInterval( statusPollHandle );
            statusPollHandle = null;
        }
    }

    // ========================================================================
    // Handlers
    // ========================================================================
    async function onStart() {
        const el = qs();
        el.startBtn.disabled = true;
        saveSettings( currentFormValues() );
        log( `Starting watcher on ${el.hostSel.value} (signal=${el.signalSel.value}, interval=${el.intervalIn.value}s, stable_for=${el.stableForIn.value})` );
        try {
            const r = await callStart();
            log( r.message );
            lastDrainedAt = null;
            await pollStatus();
        } catch ( e ) {
            log( `Start failed: ${e.message}`, 'error' );
            el.startBtn.disabled = false;
        }
    }

    async function onStop() {
        const el = qs();
        el.stopBtn.disabled = true;
        try {
            const r = await callStop();
            log( `Stop: ${r.message}` );
            await pollStatus();
        } catch ( e ) {
            log( `Stop failed: ${e.message}`, 'error' );
            el.stopBtn.disabled = false;
        }
    }

    // ========================================================================
    // Init
    // ========================================================================
    function populateHostSelector() {
        const sel = qs().hostSel;
        ALLOWED_HOSTS.forEach( h => {
            const opt = document.createElement( 'option' );
            opt.value = h.value;
            opt.textContent = h.label;
            sel.appendChild( opt );
        } );
    }

    function restoreSettings() {
        const s = loadSettings();
        if ( !s ) return;
        const el = qs();
        const validHosts = ALLOWED_HOSTS.map( h => h.value );
        if ( s.host && validHosts.includes( s.host ) ) el.hostSel.value = s.host;
        if ( s.signal )     el.signalSel.value   = s.signal;
        if ( s.interval )   el.intervalIn.value  = s.interval;
        if ( s.stable_for ) el.stableForIn.value = s.stable_for;
    }

    document.addEventListener( 'DOMContentLoaded', async function() {
        // Populate UI first so the page is usable even if the admin guard
        // is async or non-returning. If requireAdmin() redirects on failure,
        // we never reach startStatusPolling() anyway.
        populateHostSelector();
        restoreSettings();

        qs().startBtn.addEventListener( 'click', onStart );
        qs().stopBtn.addEventListener(  'click', onStop  );

        if ( typeof requireAdmin === 'function' ) {
            try { await requireAdmin(); } catch ( e ) { /* auth.js handles redirect */ }
        }

        log( 'Widget initialized. Backend will fire voice notification on drain.' );
        startStatusPolling();
    } );

    window.addEventListener( 'beforeunload', stopStatusPolling );

} )();
