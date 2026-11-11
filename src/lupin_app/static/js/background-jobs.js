/*
 * Background jobs: the accordion section of the legacy notifications client (row d540113f).
 *
 * Rick ruled that the accordion belongs to the legacy client and the multiplexer, not to a page of
 * its own. This file is the legacy copy. The multiplexer has its own
 * (js/multiplexer/render/BackgroundJobsRenderer.ts and jobs/); the two share no runtime code, by
 * Rick's no-shared-code ruling (row 87812328).
 *
 * The section computes no health. It asks GET /api/jobs/summary and formats the answer. Its one
 * action is Run now: POST /api/jobs/{job}/run. Every text goes in through textContent, never
 * innerHTML, and a link is drawn only for a path on this server, because the reader passes through
 * strings that job writers produced.
 *
 * Mounts into #background-jobs-container and #background-jobs-count; the page owns the section chrome.
 * Exposes window.backgroundJobs = { refresh, formatWhen, ... } for the unit tests and the console.
 */

( function() {
    "use strict";

    const SUMMARY_URL   = "/api/jobs/summary";
    const POLL_MS       = 60 * 1000;
    const SVG_NS        = "http://www.w3.org/2000/svg";
    const NOT_REPORTED  = "not reported";
    const STATE_ORDER   = [ "healthy", "behind", "failing", "silent", "unknown" ];   // active first (Rick, 9 Nov, row 300af681); a running job goes above all of them
    const DEFAULT_SORT  = { id : null, direction : "asc" };   // no header picked: the active-first order
    const STATE_LABEL   = { unknown : "UNKNOWN", silent : "SILENT", failing : "FAILING", behind : "BEHIND", healthy : "healthy" };

    // ─── Text rules (no DOM, no clock) ─────────────────────────────────

    function formatWhen( iso, todayIso ) {
        if ( iso === null ) return NOT_REPORTED;
        const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}:\d{2})/.exec( iso );
        if ( match === null ) return iso;
        const day = match[ 1 ] + "-" + match[ 2 ] + "-" + match[ 3 ];
        return todayIso.startsWith( day ) ? match[ 4 ] : match[ 2 ] + "-" + match[ 3 ] + " " + match[ 4 ];
    }

    function formatCount( n ) { return n === null ? NOT_REPORTED : String( n ).replace( /\B(?=(\d{3})+(?!\d))/g, "," ); }   // thousands commas without the locale API: a count carries no time zone

    function trendArrow( points ) {
        if ( points.length < 2 ) return "";
        const first = points[ 0 ].value;
        const last  = points[ points.length - 1 ].value;
        if ( last > first ) return "▲";
        return last < first ? "▼" : "=";
    }

    // The states by urgency, least urgent first (Rick, 11 Nov, row 4b807ffd): failing is the most urgent. Not STATE_ORDER, which ranks the default order.
    const HEALTH_URGENCY = [ "healthy", "behind", "silent", "unknown", "failing" ];

    // When a job's last attempt began, in milliseconds; a job with none, or a time that does not parse, counts as -1 (oldest).
    function attemptTime( j ) { return j.last_attempt === null ? -1 : ( Date.parse( j.last_attempt.started_at ) || -1 ); }

    // The default order: active first (running now, healthy, behind, failing, silent, never reported). Inside one rank the most
    // recent attempt comes first (a job with none, last), then title, then target.
    function defaultCompare( a, b ) {
        const rank    = ( j ) => j.running ? -1 : STATE_ORDER.indexOf( j.state );
        return rank( a ) - rank( b ) || attemptTime( b ) - attemptTime( a ) || a.title.localeCompare( b.title ) || ( a.target ?? "" ).localeCompare( b.target ?? "" );
    }

    // The sort orders a reader can pick from the column headers (row 4b807ffd). One entry each: a third order is one more entry
    // here and nothing else. `compare` runs in the ascending direction; "desc" flips it, and ties fall back to the default order.
    // Health runs by HEALTH_URGENCY, healthy at one end and failing at the other. Last run is oldest first when ascending, a job that never ran first.
    const SORT_ORDERS = [
        { id : "name",   label : "Service", compare : ( a, b ) => a.title.localeCompare( b.title ) || ( a.target ?? "" ).localeCompare( b.target ?? "" ) },
        { id : "health", label : "Status",  compare : ( a, b ) => HEALTH_URGENCY.indexOf( a.state ) - HEALTH_URGENCY.indexOf( b.state ) },
        { id : "last-run", label : "Last run", compare : ( a, b ) => attemptTime( a ) - attemptTime( b ) },
    ];

    // orderId null gives the default order. Never mutates its input.
    function sortJobs( jobs, orderId = null, direction = "asc" ) {
        if ( orderId === null ) return [ ...jobs ].sort( defaultCompare );
        const order = SORT_ORDERS.find( ( o ) => o.id === orderId );
        if ( order === undefined ) throw new Error( "unknown sort order: " + orderId );
        const sign = direction === "desc" ? -1 : 1;
        return [ ...jobs ].sort( ( a, b ) => sign * order.compare( a, b ) || defaultCompare( a, b ) );
    }

    function headerLine( jobs ) {
        const parts = [];
        for ( const state of STATE_ORDER ) {
            const n = jobs.filter( ( j ) => j.state === state ).length;
            if ( n > 0 ) parts.push( n + " " + state );
        }
        const noun = jobs.length === 1 ? "job" : "jobs";
        return parts.length === 0 ? jobs.length + " " + noun : jobs.length + " " + noun + ": " + parts.join( ", " );
    }

    function badgeText( job ) {
        const states = [ job.state ];
        for ( const reason of job.reasons ) {
            if ( !states.includes( reason.state ) && reason.state !== "healthy" ) states.push( reason.state );
        }
        const labels = states.map( ( s ) => STATE_LABEL[ s ] );
        if ( job.unscheduled ) labels.push( "UNSCHEDULED" );
        if ( job.schedule_unverified ) labels.push( "schedule unverified" );
        return labels.join( " · " );
    }

    function lastRunText( job, todayIso ) {
        if ( job.liveness !== null ) {
            if ( job.liveness.up === null ) return "unit " + job.liveness.unit + " is not loaded";
            return job.liveness.up ? "up (" + job.liveness.unit + ")" : "down (" + job.liveness.unit + ")";
        }
        if ( job.state === "silent" ) {
            const due = job.schedule === null ? null : job.schedule.last_due;
            return "SILENT, due " + formatWhen( due, todayIso ) + ", nothing since";
        }
        const attempt = job.last_attempt;
        if ( attempt === null ) return job.state === "unknown" ? "never reported" : "no run recorded";
        const at = formatWhen( attempt.started_at, todayIso );
        if ( attempt.outcome === "failed" ) {
            return attempt.failure === null ? "last run " + at + " failed" : "last run " + at + " failed (" + attempt.failure + ")";
        }
        if ( attempt.outcome === "skipped" ) return "last run " + at + " skipped";
        if ( attempt.outcome === "clean" && job.work_found_last_run === 0 ) return "ran " + at + ", found nothing";
        return "last run " + at + " " + attempt.outcome;
    }

    function lastFinishedText( job, todayIso ) {
        if ( job.last_finished === null ) return "last finished: " + NOT_REPORTED;
        return "last finished " + formatWhen( job.last_finished.started_at, todayIso );
    }

    function freshnessText( debt ) {
        const f = debt.freshness;
        if ( f === null || f.age_hours === null ) return "age: " + NOT_REPORTED;
        const age = Math.round( f.age_hours );
        return f.stale_after_hours === null ? "age " + age + " h" : "age " + age + " h of " + f.stale_after_hours;
    }

    function scanText( job ) {
        if ( !job.applies.scan_debt ) return "";
        const debt = job.scan_debt;
        if ( debt === null ) return "scan: " + NOT_REPORTED;
        if ( debt.freshness !== null ) return freshnessText( debt );
        if ( debt.count === null ) return "scan: " + NOT_REPORTED;
        return ( "scan " + formatCount( debt.count ) + " " + trendArrow( debt.points ) ).trimEnd();
    }

    function fixText( job ) {
        if ( !job.applies.fix_debt ) return "";
        const debt = job.fix_debt;
        if ( debt === null ) return "rows: " + NOT_REPORTED;
        if ( debt.kind === "reported" ) {
            return debt.open_reported === null ? "named: " + NOT_REPORTED : "named " + formatCount( debt.open_reported ) + ", not acted on";
        }
        if ( debt.unfiled === null ) return "rows: " + NOT_REPORTED;
        return ( "unfiled " + formatCount( debt.unfiled ) + " " + trendArrow( debt.points ) ).trimEnd();
    }

    function clearsText( job ) {
        const clears = job.scan_debt === null ? null : job.scan_debt.clears_in;
        if ( !job.applies.scan_debt || clears === null ) return "";
        if ( clears.kind === "never_at_this_rate" ) return "clears: never at this rate";
        if ( clears.kind === "not_enough_runs" ) return "clears: not enough runs";
        if ( clears.days === null ) return "clears: " + NOT_REPORTED;
        return "clears: " + ( clears.days === 1 ? "1 day" : clears.days + " days" );
    }

    function notReportedNames( job ) {
        const names = [];
        if ( job.last_finished === null ) names.push( "last finished run" );
        if ( job.liveness === null && job.applies.scan_debt ) {
            const debt = job.scan_debt;
            if ( debt === null ) names.push( "scan debt" );
            else {
                if ( debt.count === null && debt.freshness === null ) names.push( "scan debt count" );
                if ( debt.never_checked === null && debt.freshness === null ) names.push( "never checked" );
                if ( debt.drained_last_run === null && debt.freshness === null ) names.push( "drained last run" );
                if ( debt.arrived_last_interval === null && debt.freshness === null ) names.push( "arrived last interval" );
            }
        }
        if ( job.applies.fix_debt ) {
            const debt = job.fix_debt;
            if ( debt === null ) names.push( "fix debt" );
            else if ( debt.kind === "rows" ) {
                if ( debt.unfiled === null ) names.push( "unfiled rows" );
                if ( debt.open_now === null ) names.push( "open rows" );
                if ( debt.closed_in_window === null ) names.push( "rows closed in window" );
            } else if ( debt.open_reported === null ) names.push( "named pile" );
        }
        return names;
    }

    function graceText( job ) {
        const s = job.schedule;
        if ( s === null ) return NOT_REPORTED;
        if ( s.grace_seconds !== null ) return s.grace_seconds + " seconds";
        return s.grace_minutes === null ? NOT_REPORTED : s.grace_minutes + " minutes";
    }

    function notifyIntervalText( job ) {
        const secs = job.notify_interval_seconds;
        if ( secs === null ) return NOT_REPORTED;
        if ( secs % 3600 === 0 ) return "every " + ( secs / 3600 ) + " h";
        if ( secs % 60 === 0 ) return "every " + ( secs / 60 ) + " min";
        return "every " + secs + " s";
    }

    function isSafeHref( href ) {
        return href !== null && href.startsWith( "/" ) && !href.startsWith( "//" ) && !href.includes( "\\" );
    }

    // ─── DOM ───────────────────────────────────────────────────────────

    function el( tag, className, text, testid ) {
        const node = document.createElement( tag );
        if ( className !== null ) node.className = className;
        if ( text !== null ) node.textContent = text;
        if ( testid !== null ) node.setAttribute( "data-testid", testid );
        return node;
    }

    function link( href, text, testid ) {
        const a = document.createElement( "a" );
        a.href = href;
        a.textContent = text;
        a.setAttribute( "data-testid", testid );
        return a;
    }

    function sparkline( points, label ) {
        if ( points.length < 2 ) return null;
        const values = points.map( ( p ) => p.value );
        const lo     = Math.min( ...values );
        const span   = Math.max( ...values ) - lo;
        const coords = values.map( ( v, i ) => {
            const x = ( i / ( values.length - 1 ) ) * 118 + 1;
            const y = span === 0 ? 12 : 23 - ( ( v - lo ) / span ) * 22;
            return x.toFixed( 1 ) + "," + y.toFixed( 1 );
        } );
        const svg = document.createElementNS( SVG_NS, "svg" );
        svg.setAttribute( "viewBox", "0 0 120 24" );
        svg.setAttribute( "width", "120" );
        svg.setAttribute( "height", "24" );
        svg.setAttribute( "role", "img" );
        svg.setAttribute( "aria-label", label + ": " + values.join( ", " ) );
        svg.setAttribute( "data-testid", "jobs-sparkline" );
        const line = document.createElementNS( SVG_NS, "polyline" );
        line.setAttribute( "points", coords.join( " " ) );
        line.setAttribute( "fill", "none" );
        line.setAttribute( "stroke", "currentColor" );
        line.setAttribute( "stroke-width", "1.5" );
        svg.appendChild( line );
        return svg;
    }

    function addRow( list, name, value, testid ) {
        list.appendChild( el( "dt", null, name, null ) );
        list.appendChild( el( "dd", null, value, testid ) );
    }

    function block( title, testid ) {
        const section = el( "section", "jobs-block", null, testid );
        section.appendChild( el( "h3", null, title, null ) );
        return section;
    }

    function notReportedParagraph( section ) {
        section.appendChild( el( "p", null, NOT_REPORTED, null ) );
        return section;
    }

    function reasonsBlock( job ) {
        const section = block( "Reasons", "jobs-reasons" );
        if ( job.reasons.length === 0 && job.unknown_reason === null ) {
            section.appendChild( el( "p", null, "No rule is true: nothing to report.", null ) );
            return section;
        }
        const ul = document.createElement( "ul" );
        for ( const reason of job.reasons ) ul.appendChild( el( "li", null, reason.text, "jobs-reason" ) );
        if ( job.unknown_reason !== null ) ul.appendChild( el( "li", null, job.unknown_reason, "jobs-reason" ) );
        if ( job.machine_was_off ) ul.appendChild( el( "li", null, "Missed while the machine was off.", "jobs-reason" ) );
        section.appendChild( ul );
        return section;
    }

    function stripBlock( job, todayIso ) {
        const section = block( "Last attempts", "jobs-strip" );
        if ( job.strip.length === 0 ) return notReportedParagraph( section );
        const ol = document.createElement( "ol" );
        ol.className = "jobs-strip-list";
        for ( const entry of job.strip ) {
            const text = entry.outcome === "missed"
                ? formatWhen( entry.at, todayIso ) + " MISSED (due, no run)"
                : formatWhen( entry.at, todayIso ) + " " + entry.outcome;
            const li = el( "li", "jobs-strip-" + entry.outcome, text, "jobs-strip-entry" );
            li.setAttribute( "data-outcome", entry.outcome );
            ol.appendChild( li );
        }
        section.appendChild( ol );
        return section;
    }

    function scanBlock( job, todayIso ) {
        if ( !job.applies.scan_debt || job.liveness !== null ) return null;
        const section = block( "Scan debt", "jobs-scan" );
        const debt    = job.scan_debt;
        if ( debt === null ) return notReportedParagraph( section );
        const dl = document.createElement( "dl" );
        addRow( dl, "Count", debt.count === null ? NOT_REPORTED : ( formatCount( debt.count ) + " " + ( debt.unit ?? "" ) ).trim(), "jobs-scan-count" );
        addRow( dl, "As of", formatWhen( debt.as_of, todayIso ), "jobs-scan-as-of" );
        addRow( dl, "Drained last run", formatCount( debt.drained_last_run ), "jobs-scan-drained" );
        addRow( dl, "Arrived last interval", formatCount( debt.arrived_last_interval ), "jobs-scan-arrived" );
        addRow( dl, "Never checked", formatCount( debt.never_checked ), "jobs-scan-never" );
        addRow( dl, "Clears in", clearsText( job ).replace( /^clears: /, "" ) || NOT_REPORTED, "jobs-scan-clears" );
        section.appendChild( dl );
        const spark = sparkline( debt.points, "scan debt" );
        if ( spark !== null ) section.appendChild( spark );
        return section;
    }

    function fixBlock( job ) {
        if ( !job.applies.fix_debt ) return null;
        const section = block( "Fix debt", "jobs-fix" );
        const debt    = job.fix_debt;
        if ( debt === null ) return notReportedParagraph( section );
        const dl = document.createElement( "dl" );
        if ( debt.kind === "reported" ) {
            addRow( dl, "Named, not acted on", formatCount( debt.open_reported ), "jobs-fix-reported" );
        } else {
            addRow( dl, "Unfiled", formatCount( debt.unfiled ), "jobs-fix-unfiled" );
            addRow( dl, "Filed in total", formatCount( debt.filed_total ), "jobs-fix-filed" );
            addRow( dl, "Open now", formatCount( debt.open_now ), "jobs-fix-open" );
            addRow( dl, "Closed in window", formatCount( debt.closed_in_window ), "jobs-fix-closed" );
            addRow( dl, "Own mark", debt.own_mark ?? NOT_REPORTED, "jobs-fix-mark" );
        }
        section.appendChild( dl );
        const spark = sparkline( debt.points, "rows opened" );
        if ( spark !== null ) section.appendChild( spark );
        if ( isSafeHref( debt.store_href ) ) section.appendChild( link( debt.store_href, "Rows in the task store", "jobs-fix-store-link" ) );
        return section;
    }

    function scheduleBlock( job, todayIso ) {
        const section = block( "Schedule", "jobs-schedule" );
        const dl      = document.createElement( "dl" );
        const s       = job.schedule;
        if ( job.liveness !== null ) addRow( dl, "Liveness", job.liveness.kind + " unit " + job.liveness.unit, "jobs-liveness" );
        if ( job.schedule_unverified ) addRow( dl, "Check", "schedule unverified: the installed schedule could not be read", "jobs-schedule-unverified" );
        addRow( dl, "Runs", s === null || s.entries.length === 0 ? "unscheduled" : s.entries.join( "; " ), "jobs-schedule-entries" );
        addRow( dl, "Last due", s === null ? NOT_REPORTED : formatWhen( s.last_due, todayIso ), "jobs-schedule-last-due" );
        addRow( dl, "Next due", s === null ? NOT_REPORTED : formatWhen( s.next_due, todayIso ), "jobs-schedule-next-due" );
        addRow( dl, "Grace", graceText( job ), "jobs-schedule-grace" );
        addRow( dl, "Tells Rick", notifyIntervalText( job ), "jobs-notify-interval" );
        section.appendChild( dl );
        return section;
    }

    function evidenceBlock( job ) {
        const section = block( "Evidence", "jobs-evidence" );
        if ( job.evidence.length === 0 ) return notReportedParagraph( section );
        const ul = document.createElement( "ul" );
        for ( const item of job.evidence ) {
            const li = document.createElement( "li" );
            if ( isSafeHref( item.href ) ) li.appendChild( link( item.href, item.label + ": " + item.path, "jobs-evidence-link" ) );
            else li.appendChild( el( "span", null, item.label + ": " + item.path, "jobs-evidence-path" ) );
            ul.appendChild( li );
        }
        section.appendChild( ul );
        return section;
    }

    function peopleBlock( job ) {
        const section = block( "People", "jobs-people" );
        const dl      = document.createElement( "dl" );
        addRow( dl, "Owner", job.owner, "jobs-owner" );
        addRow( dl, "Told", job.audience.length === 0 ? "the owner" : job.audience.join( ", " ), "jobs-audience" );
        section.appendChild( dl );
        if ( job.rows.length > 0 ) {
            const ul = document.createElement( "ul" );
            for ( const row of job.rows ) {
                const li = document.createElement( "li" );
                if ( isSafeHref( row.href ) ) li.appendChild( link( row.href, row.title, "jobs-row-link" ) );
                else li.appendChild( el( "span", null, row.title, "jobs-row-title" ) );
                ul.appendChild( li );
            }
            section.appendChild( ul );
        }
        if ( isSafeHref( job.detail_link ) ) section.appendChild( link( job.detail_link, "Open the detail page", "jobs-detail-link" ) );
        return section;
    }

    function notReportedBlock( job ) {
        const section = block( "Not reported", "jobs-not-reported" );
        const names   = notReportedNames( job );
        section.appendChild( el( "p", null, names.length === 0 ? "Every figure was reported." : names.join( ", " ), "jobs-not-reported-names" ) );
        return section;
    }

    function runNowBlock( job, actions ) {
        if ( !actions.canRun || !job.runnable ) return null;
        const wrap   = el( "div", "jobs-actions", null, null );
        const button = document.createElement( "button" );
        button.type = "button";
        button.textContent = "Run now";
        button.setAttribute( "data-testid", "jobs-run-now" );
        const status = el( "span", "jobs-run-status", null, "jobs-run-status" );
        status.setAttribute( "role", "status" );
        button.addEventListener( "click", () => {
            button.disabled = true;
            status.textContent = "Starting…";
            actions.runNow( job ).then(
                ( message ) => { status.textContent = message; button.disabled = false; },
                ( err ) => { status.textContent = "Run now failed: " + String( err ); button.disabled = false; }
            );
        } );
        wrap.appendChild( button );
        wrap.appendChild( status );
        return wrap;
    }

    function itemId( job ) {
        return ( "jobs-" + job.job + ( job.target === null ? "" : "-" + job.target ) ).replace( /[^A-Za-z0-9_-]/g, "-" );
    }

    function renderJob( job, todayIso, actions, sort = DEFAULT_SORT ) {
        const id      = itemId( job );
        const item    = el( "section", "jobs-item", null, "jobs-item" );
        item.setAttribute( "data-job", job.job );
        item.setAttribute( "data-target", job.target ?? "" );
        item.setAttribute( "data-state", job.state );

        const heading = document.createElement( "h4" );
        heading.className = "jobs-heading";
        const button = document.createElement( "button" );
        button.type = "button";
        button.className = "jobs-line";
        button.id = id + "-line";
        button.setAttribute( "aria-expanded", "false" );
        button.setAttribute( "aria-controls", id + "-panel" );
        button.setAttribute( "data-testid", "jobs-line" );
        const cells = [
            [ "jobs-caret", "▶" ],
            [ "jobs-dot jobs-state-" + job.state, "●" ],
            [ "jobs-title", job.target === null ? job.title : job.title + " (" + job.target + ")" ],
            [ "jobs-badge", badgeText( job ) ],
            [ "jobs-last-run", lastRunText( job, todayIso ) ],
            [ "jobs-last-finished", job.liveness === null ? lastFinishedText( job, todayIso ) : "" ],
            [ "jobs-scan-cell", scanText( job ) ],
            [ "jobs-fix-cell", fixText( job ) ],
            [ "jobs-clears-cell", clearsText( job ) ],
        ];
        for ( const [ cls, text ] of cells ) {
            const span = el( "span", cls, text, cls.split( " " )[ 0 ] );
            if ( cls.startsWith( "jobs-dot" ) ) span.setAttribute( "aria-hidden", "true" );
            button.appendChild( span );
        }
        heading.appendChild( button );
        item.appendChild( heading );

        const panel = el( "div", "jobs-panel", null, "jobs-panel" );
        panel.id = id + "-panel";
        panel.setAttribute( "role", "region" );
        panel.setAttribute( "aria-labelledby", button.id );
        panel.hidden = true;
        panel.appendChild( reasonsBlock( job ) );
        if ( job.liveness === null ) panel.appendChild( stripBlock( job, todayIso ) );
        for ( const part of [ scanBlock( job, todayIso ), fixBlock( job ) ] ) if ( part !== null ) panel.appendChild( part );
        panel.appendChild( scheduleBlock( job, todayIso ) );
        panel.appendChild( evidenceBlock( job ) );
        panel.appendChild( peopleBlock( job ) );
        panel.appendChild( notReportedBlock( job ) );
        const run = runNowBlock( job, actions );
        if ( run !== null ) panel.appendChild( run );
        for ( const target of sortJobs( job.targets, sort.id, sort.direction ) ) panel.appendChild( renderJob( target, todayIso, actions, sort ) );
        item.appendChild( panel );

        button.addEventListener( "click", () => {
            const open = button.getAttribute( "aria-expanded" ) === "true";
            button.setAttribute( "aria-expanded", open ? "false" : "true" );
            panel.hidden = open;
            button.querySelector( ".jobs-caret" ).textContent = open ? "▶" : "▼";
        } );
        return item;
    }

    // The columns of one collapsed line, in grid order. `sortId` names the SORT_ORDERS entry a header click picks, or null.
    const COLUMNS = [
        { cls : "jobs-caret",         label : "",              sortId : null },
        { cls : "jobs-dot",           label : "",              sortId : null },
        { cls : "jobs-title",         label : "Service",       sortId : "name" },
        { cls : "jobs-badge",         label : "Status",        sortId : "health" },
        { cls : "jobs-last-run",      label : "Last run",      sortId : "last-run" },
        { cls : "jobs-last-finished", label : "Last finished", sortId : null },
        { cls : "jobs-scan-cell",     label : "Scan",          sortId : null },
        { cls : "jobs-fix-cell",      label : "Fix",           sortId : null },
        { cls : "jobs-clears-cell",   label : "Clears",        sortId : null },
    ];

    // Clicking a sortable header: a new column sorts ascending, a second click descending, a third returns to the default order.
    function nextSort( sort, sortId ) {
        if ( sort.id !== sortId ) return { id : sortId, direction : "asc" };
        return sort.direction === "asc" ? { id : sortId, direction : "desc" } : { id : null, direction : "asc" };
    }

    function headerRow( sort, onSort ) {
        const row = el( "div", "jobs-header jobs-line-grid", null, "jobs-header" );
        row.setAttribute( "role", "row" );
        for ( const col of COLUMNS ) {
            const cell = el( "span", "jobs-head-cell " + col.cls, null, null );
            cell.setAttribute( "role", "columnheader" );
            if ( col.sortId === null ) cell.textContent = col.label;
            else {
                const active = sort.id === col.sortId;
                const button = el( "button", "jobs-sort-button", col.label + ( active ? ( sort.direction === "asc" ? " ▲" : " ▼" ) : "" ), "jobs-sort-" + col.sortId );
                button.type = "button";
                button.addEventListener( "click", () => onSort( nextSort( sort, col.sortId ) ) );
                cell.setAttribute( "aria-sort", active ? ( sort.direction === "asc" ? "ascending" : "descending" ) : "none" );
                cell.appendChild( button );
            }
            row.appendChild( cell );
        }
        return row;
    }

    let currentSort = DEFAULT_SORT;

    function renderAccordion( mount, summary, actions, sort = currentSort ) {
        mount.replaceChildren();
        currentSort = sort;
        mount.appendChild( headerRow( sort, ( next ) => renderAccordion( mount, summary, actions, next ) ) );
        for ( const job of sortJobs( summary.jobs, sort.id, sort.direction ) ) mount.appendChild( renderJob( job, summary.generated_at, actions, sort ) );
        if ( summary.reporting_off_line ) {                      // row 4aa0ba1b: the server drops a switched-off job and says how many
            const line = document.createElement( "p" );
            line.className = "jobs-off-line";
            line.setAttribute( "data-testid", "background-jobs-off-line" );
            line.textContent = summary.reporting_off_line;
            mount.appendChild( line );
        }
    }

    // ─── Network + wiring ──────────────────────────────────────────────

    // Row 399a266f: notificationsUI.authedFetch refreshes the access token before it sends; the bare
    // localStorage read below is the fallback only, and it is loud because it brings the 401 back.
    function authFetch( url, opts ) {
        const ui = window.notificationsUI;
        if ( ui && typeof ui.authedFetch === "function" ) return ui.authedFetch( url, opts || {} );
        console.error( "[background-jobs] notificationsUI.authedFetch unavailable — sending an UNREFRESHED token; expect 401 after the access-token TTL (row 399a266f)" );
        const headers = Object.assign( { "Authorization": "Bearer " + ( localStorage.getItem( "lupin_access_token" ) || "" ) }, ( opts && opts.headers ) || {} );
        return fetch( url, Object.assign( {}, opts, { headers } ) );
    }

    function runNowPath( job ) {
        const base = "/api/jobs/" + encodeURIComponent( job.job ) + "/run";
        return job.target === null ? base : base + "?target=" + encodeURIComponent( job.target );
    }

    function runNowFailureText( status, detail ) {
        if ( status === 422 && typeof detail === "string" && detail !== "" ) return detail;
        if ( status === 403 ) return "Only Rick's login can run a job by hand.";
        if ( status === 404 ) return "The reader does not know this job.";
        if ( status === 409 ) return "Not started: the job's run lock is held, so a run is already going.";
        if ( status === 422 ) return "This job cannot be run by hand.";
        return "Run now failed (HTTP " + status + ").";
    }

    async function runNow( job ) {
        try {
            const resp = await authFetch( runNowPath( job ), { method : "POST" } );
            if ( !resp.ok ) {
                const refused = await resp.json().catch( () => null );
                return runNowFailureText( resp.status, refused === null ? null : refused.detail );
            }
            const started = await resp.json();
            return "Started at " + started.started_at + " (pid " + started.pid + ").";
        } catch ( err ) {
            return "Run now failed: " + String( err );
        }
    }

    async function refresh() {
        const mount   = document.getElementById( "background-jobs-container" );
        const count   = document.getElementById( "background-jobs-count" );
        const errorEl = document.getElementById( "background-jobs-error" );
        const summaryEl = document.getElementById( "background-jobs-summary" );
        if ( mount === null || count === null || errorEl === null || summaryEl === null ) return;
        try {
            const resp = await authFetch( SUMMARY_URL );
            if ( !resp.ok ) throw new Error( "HTTP " + resp.status );
            const summary = await resp.json();
            renderAccordion( mount, summary, { canRun : summary.caller_is_operator, runNow } );
            count.textContent = String( summary.jobs.length );
            summaryEl.textContent = headerLine( summary.jobs );
            errorEl.hidden = true;
        } catch ( err ) {
            errorEl.textContent = "Could not load the jobs: " + ( err instanceof Error ? err.message : String( err ) );
            errorEl.hidden = false;
        }
    }

    function start() {
        const button = document.getElementById( "background-jobs-refresh" );
        if ( button !== null ) button.addEventListener( "click", ( e ) => { e.stopPropagation(); refresh(); } );
        refresh();
        window.setInterval( refresh, POLL_MS );
    }

    window.backgroundJobs = { refresh, start, renderAccordion, renderJob, sortJobs, SORT_ORDERS, HEALTH_URGENCY, headerLine, formatWhen, runNowPath, runNowFailureText, isSafeHref };

    if ( document.readyState === "loading" ) document.addEventListener( "DOMContentLoaded", start );
    else start();
} )();
