/*
 * Scheduled jobs: each cron job's on/off switch, for the legacy notifications client (rows 063fc1a8, c80ef763).
 *
 * Row c80ef763 merged the Scheduled Jobs section into the Background Jobs list. This file no longer
 * owns a section: it reads each switch from lupin-app.ini through GET /api/cron-jobs, draws a job's
 * switch for line 2 of its row (switchCells), and lets an administrator flip it with
 * PUT /api/cron-jobs/{job}/enabled. background-jobs.js owns the list, the polling and the redraw, and
 * calls load() and switchCells(); this file must load first. A flip edits the INI key the job reads
 * at its next start, or at its next tick for a loop inside a server; it does not stop a run already
 * going. Anyone who is not an administrator sees the switches read-only: the server's
 * `caller_is_admin` decides, never this file.
 *
 * Turning off an alarm job (row.alarm, set in the registry) takes two clicks: the first asks for
 * confirmation, because an alarm job being off silences what would report it (Rick, 13 Nov).
 * A switch the server could not read shows as a red "switch unreadable" note (row c38a49bd).
 *
 * Every text goes in through textContent, never innerHTML. The multiplexer has its own copy
 * (jobs/cronFormat.ts and render/BackgroundJobsRenderer.ts): no shared runtime code between the two
 * clients, ruling 87812328.
 *
 * The queue socket's `cron_job_switch_changed` frame reaches applyEvent through notifications.js.
 * Exposes window.cronJobs for background-jobs.js, the unit tests and the console.
 */

( function() {
    "use strict";

    const LIST_URL      = "/api/cron-jobs";
    const NOT_REPORTED  = "not reported";
    const DRIFT_TEXT    = "changed outside the endpoint";
    const STATE_TEXT    = { true : "ON", false : "OFF", null : "UNKNOWN" };
    const READS_TEXT    = { run : "reads its switch at each run", tick : "reads its switch every tick" };
    const UNREADABLE    = "switch unreadable: the key is missing from the configuration file or holds neither true nor false";
    const CONFIRM_TEXT  = "Turning this off also silences what would report it. Click again to confirm.";

    let current        = { jobs : [], caller_is_admin : false };
    let pendingConfirm = null;      // the job whose turn-off is waiting for its confirming click
    let listener       = null;      // what to call when a row changed: the list's repaint

    // ─── Text rules (no DOM, no clock) ─────────────────────────────────

    function stateText( enabled ) { return STATE_TEXT[ String( enabled ) ]; }

    function readsText( row ) {
        if ( row.reads in READS_TEXT ) return READS_TEXT[ row.reads ];
        return row.honoured ? "reads its switch" : "does not read its switch yet";
    }

    // A job that runs inside another job's tick is off while that job is off, whatever its own switch says.
    function insideText( row, jobs ) {
        if ( typeof row.inside !== "string" ) return null;
        const host = jobs.find( ( j ) => j.job === row.inside );
        return host !== undefined && host.enabled === false ? "off while " + row.inside + " is off" : null;
    }

    function changedText( row ) {
        if ( row.last_changed_by === null || row.last_changed_at === null ) return NOT_REPORTED;
        return row.last_changed_by + ", " + row.last_changed_at.slice( 0, 16 ).replace( "T", " " );
    }

    function flipFailureText( status, detail ) {
        if ( status === 403 ) return "Only an administrator can flip a job's switch.";
        if ( status === 404 ) return "The server does not know this job.";
        if ( status === 409 ) return typeof detail === "string" && detail.includes( "does not read its switch" ) ? detail : "The configuration file does not carry this job's switch yet.";
        if ( status === 422 && typeof detail === "string" && detail !== "" ) return detail;
        return "Flip failed (HTTP " + status + ").";
    }

    // ─── DOM ───────────────────────────────────────────────────────────

    function el( tag, cls, text, testid ) {
        const node = document.createElement( tag );
        if ( cls ) node.className = cls;
        if ( text !== null && text !== undefined ) node.textContent = text;
        if ( testid ) node.setAttribute( "data-testid", testid );
        return node;
    }

    // One job's switch for line 2 of its row: schedule, state, changed, reads, the notes, Turn on / Turn off and the error span.
    function switchCells( row ) {
        const unreadable = row.honoured && row.enabled === null;
        const item = el( "span", unreadable ? "cron-item cron-unreadable" : "cron-item", null, "cron-item" );
        item.setAttribute( "data-job", row.job );
        item.appendChild( el( "span", "cron-schedule", row.schedule, "cron-schedule" ) );
        item.appendChild( el( "span", "cron-state cron-state-" + stateText( row.enabled ).toLowerCase(), stateText( row.enabled ), "cron-state" ) );
        item.appendChild( el( "span", "cron-changed", changedText( row ), "cron-changed" ) );
        item.appendChild( el( "span", "cron-honoured", readsText( row ), "cron-honoured" ) );
        if ( row.drift ) item.appendChild( el( "span", "cron-drift", DRIFT_TEXT, "cron-drift" ) );
        if ( unreadable ) item.appendChild( el( "span", "cron-unreadable-note", UNREADABLE, "cron-unreadable" ) );
        const inside = insideText( row, current.jobs );
        if ( inside !== null ) item.appendChild( el( "span", "cron-inside", inside, "cron-inside" ) );
        const button = el( "button", "cron-flip", row.enabled === true ? "Turn off" : "Turn on", "cron-flip" );
        button.type = "button";
        button.disabled = !current.caller_is_admin || row.enabled === null || !row.honoured;     // no key to flip yet, or nothing reads it
        button.addEventListener( "click", () => requestFlip( row ) );
        item.appendChild( button );
        const note = el( "span", "cron-error", null, "cron-error" );
        note.setAttribute( "role", "alert" );
        note.hidden = true;
        item.appendChild( note );
        return item;
    }

    // ─── Network + wiring ──────────────────────────────────────────────

    // notificationsUI.authedFetch refreshes the access token before it sends (row 399a266f).
    function authFetch( url, opts ) {
        const ui = window.notificationsUI;
        if ( ui && typeof ui.authedFetch === "function" ) return ui.authedFetch( url, opts || {} );
        console.error( "[cron-jobs] notificationsUI.authedFetch unavailable — sending an UNREFRESHED token; expect 401 after the access-token TTL" );
        const headers = Object.assign( { "Authorization": "Bearer " + ( localStorage.getItem( "lupin_access_token" ) || "" ) }, ( opts && opts.headers ) || {} );
        return fetch( url, Object.assign( {}, opts, { headers } ) );
    }

    function flipPath( job ) { return LIST_URL + "/" + encodeURIComponent( job.job ) + "/enabled"; }

    function itemFor( jobName ) {
        for ( const item of document.querySelectorAll( "#background-jobs-container .cron-item" ) ) if ( item.getAttribute( "data-job" ) === jobName ) return item;
        return null;
    }

    function showError( jobName, text ) {
        const item = itemFor( jobName );
        if ( item === null ) return;
        const note = item.querySelector( ".cron-error" );
        note.textContent = text;
        note.hidden = false;
    }

    // Ask the switch list again. Rejects with the reason, so the list can name it.
    async function load() {
        const resp = await authFetch( LIST_URL );
        if ( !resp.ok ) throw new Error( "HTTP " + resp.status );
        current = await resp.json();
        return current;
    }

    // One row came back from the server (a flip's answer, or another client's event): swap it in place and tell the list.
    function applyRow( row ) {
        const index = current.jobs.findIndex( ( j ) => j.job === row.job );
        if ( index === -1 ) return;
        current.jobs[ index ] = row;
        if ( listener !== null ) listener();
    }

    // The queue socket frame is { type, timestamp, ...row }.
    function applyEvent( frame ) {
        if ( frame === null || typeof frame !== "object" || typeof frame.job !== "string" ) return;
        applyRow( frame );
    }

    // The click handler: an alarm job's turn-off waits for a second, confirming click.
    function requestFlip( row ) {
        if ( row.alarm === true && row.enabled === true && pendingConfirm !== row.job ) {
            pendingConfirm = row.job;
            const item = itemFor( row.job );
            if ( item !== null ) item.querySelector( ".cron-flip" ).textContent = "Confirm: turn off";
            showError( row.job, CONFIRM_TEXT );
            return Promise.resolve( "confirm" );
        }
        pendingConfirm = null;
        return flip( row );
    }

    async function flip( row ) {
        try {
            const resp = await authFetch( flipPath( row ), {
                method  : "PUT",
                headers : { "Content-Type" : "application/json" },
                body    : JSON.stringify( { on : row.enabled !== true } ),
            } );
            if ( !resp.ok ) {
                const refused = await resp.json().catch( () => null );
                showError( row.job, flipFailureText( resp.status, refused === null ? null : refused.detail ) );
                return;
            }
            applyRow( await resp.json() );
        } catch ( err ) {
            showError( row.job, "Flip failed: " + String( err ) );
        }
    }

    // The rows the last load or event left in hand.
    function jobRows() { return current.jobs; }

    // Whether the server said the caller is an administrator.
    function callerCanFlip() { return current.caller_is_admin; }

    // Register what to call when a row changed: the list's repaint.
    function setChangeListener( fn ) { listener = fn; }

    // Forget a turn-off that was waiting for its confirming click.
    function resetPendingConfirm() { pendingConfirm = null; }

    window.cronJobs = {
        load, switchCells, el, authFetch, applyEvent, flip, requestFlip, stateText, readsText, insideText, changedText, flipFailureText, flipPath,
        rows         : jobRows,
        canFlip      : callerCanFlip,
        onChange     : setChangeListener,
        resetConfirm : resetPendingConfirm,
    };
} )();
