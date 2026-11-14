/*
 * Scheduled jobs: the accordion section of the legacy notifications client (row 063fc1a8).
 *
 * Shows each cron job's on/off switch, read from lupin-app.ini by GET /api/cron-jobs, and lets an
 * administrator flip it with PUT /api/cron-jobs/{job}/enabled. A flip edits the INI key the job
 * reads at its next start; it does not stop a run already going. Anyone who is not an administrator
 * sees the switches read-only: the server's `caller_is_admin` decides, never this file.
 *
 * Every text goes in through textContent, never innerHTML. The multiplexer gets its own copy later
 * (no shared runtime code between the two clients, ruling 87812328).
 *
 * Mounts into #cron-jobs-container and #cron-jobs-count; the page owns the section chrome.
 * The queue socket's `cron_job_switch_changed` frame reaches applyEvent through notifications.js.
 * Exposes window.cronJobs for the unit tests and the console.
 */

( function() {
    "use strict";

    const LIST_URL      = "/api/cron-jobs";
    const POLL_MS       = 60 * 1000;
    const NOT_REPORTED  = "not reported";
    const DRIFT_TEXT    = "changed outside the endpoint";
    const STATE_TEXT    = { true : "ON", false : "OFF", null : "UNKNOWN" };

    let current = { jobs : [], caller_is_admin : false };

    // ─── Text rules (no DOM, no clock) ─────────────────────────────────

    function stateText( enabled ) { return STATE_TEXT[ String( enabled ) ]; }

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

    function renderRow( row, canFlip, onFlip ) {
        const item = el( "div", "cron-item", null, "cron-item" );
        item.setAttribute( "data-job", row.job );
        item.appendChild( el( "span", "cron-title", row.title, "cron-title" ) );
        item.appendChild( el( "span", "cron-schedule", row.schedule, "cron-schedule" ) );
        item.appendChild( el( "span", "cron-state cron-state-" + stateText( row.enabled ).toLowerCase(), stateText( row.enabled ), "cron-state" ) );
        item.appendChild( el( "span", "cron-changed", changedText( row ), "cron-changed" ) );
        item.appendChild( el( "span", "cron-honoured", row.honoured ? "reads its switch" : "does not read its switch yet", "cron-honoured" ) );
        if ( row.drift ) item.appendChild( el( "span", "cron-drift", DRIFT_TEXT, "cron-drift" ) );
        const button = el( "button", "cron-flip", row.enabled === true ? "Turn off" : "Turn on", "cron-flip" );
        button.type = "button";
        button.disabled = !canFlip || row.enabled === null || !row.honoured;     // no key to flip yet, or nothing reads it
        button.addEventListener( "click", () => onFlip( row ) );
        item.appendChild( button );
        const note = el( "span", "cron-error", null, "cron-error" );
        note.setAttribute( "role", "alert" );
        note.hidden = true;
        item.appendChild( note );
        return item;
    }

    function render( mount, summary, onFlip ) {
        current = summary;
        mount.replaceChildren();
        mount.appendChild( el( "p", "cron-note", summary.caller_is_admin
            ? "Flipping a switch takes effect at the job's next start. A run already going is not stopped."
            : "Read-only: only an administrator can flip a switch.", "cron-note" ) );
        for ( const row of summary.jobs ) mount.appendChild( renderRow( row, summary.caller_is_admin, onFlip ) );
        const count = document.getElementById( "cron-jobs-count" );
        const off   = summary.jobs.filter( ( j ) => j.enabled === false ).length;
        if ( count !== null ) count.textContent = summary.jobs.length + ( off > 0 ? " (" + off + " off)" : "" );
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
        for ( const item of document.querySelectorAll( "#cron-jobs-container .cron-item" ) ) if ( item.getAttribute( "data-job" ) === jobName ) return item;
        return null;
    }

    function showError( jobName, text ) {
        const item = itemFor( jobName );
        if ( item === null ) return;
        const note = item.querySelector( ".cron-error" );
        note.textContent = text;
        note.hidden = false;
    }

    function mount() { return document.getElementById( "cron-jobs-container" ); }

    // One row came back from the server (a flip's answer, or another client's event): swap it in place.
    function applyRow( row ) {
        const target = mount();
        if ( target === null ) return;
        const index = current.jobs.findIndex( ( j ) => j.job === row.job );
        if ( index === -1 ) return;
        current.jobs[ index ] = row;
        render( target, current, flip );
    }

    // The queue socket frame is { type, timestamp, ...row }.
    function applyEvent( frame ) {
        if ( frame === null || typeof frame !== "object" || typeof frame.job !== "string" ) return;
        applyRow( frame );
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

    async function refresh() {
        const target  = mount();
        const errorEl = document.getElementById( "cron-jobs-error" );
        if ( target === null || errorEl === null ) return;
        try {
            const resp = await authFetch( LIST_URL );
            if ( !resp.ok ) throw new Error( "HTTP " + resp.status );
            const summary = await resp.json();
            render( target, summary, flip );
            errorEl.hidden = true;
        } catch ( err ) {
            errorEl.textContent = "Could not load the scheduled jobs: " + ( err instanceof Error ? err.message : String( err ) );
            errorEl.hidden = false;
        }
    }

    function start() {
        const button = document.getElementById( "cron-jobs-refresh" );
        if ( button !== null ) button.addEventListener( "click", ( e ) => { e.stopPropagation(); refresh(); } );
        refresh();
        window.setInterval( refresh, POLL_MS );
    }

    window.cronJobs = { refresh, start, render, renderRow, applyEvent, flip, stateText, changedText, flipFailureText, flipPath };

    if ( document.readyState === "loading" ) document.addEventListener( "DOMContentLoaded", start );
    else start();
} )();
