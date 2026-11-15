/*
 * Background jobs: the one jobs list of the legacy notifications client (rows d540113f, c80ef763).
 *
 * Rick ruled that the list belongs to the legacy client and the multiplexer, not to a page of its
 * own, and (row c80ef763) that the Scheduled Jobs list is part of it. This file is the legacy copy.
 * The multiplexer has its own (js/multiplexer/render/BackgroundJobsRenderer.ts and jobs/); the two
 * share no runtime code, by Rick's no-shared-code ruling (row 87812328).
 *
 * One row per service. The collapsed line holds Service, Status, Last run and Last finished, a ⋯
 * button and a 📋. The ⋯ opens a second line (the Scan, Fix and Clears figures and the job's on/off
 * switch, drawn by cron-jobs.js, which must load first) and a third (Run now and the job's
 * targets). The long text is the 📋 abstract; notifications.js's delegated click handler opens it.
 *
 * The list computes no health. It asks GET /api/jobs/summary and GET /api/cron-jobs together and
 * joins them by job id. Its action is Run now: POST /api/jobs/{job}/run; the switch is cron-jobs.js's.
 * Every text goes in through textContent, never innerHTML, and a link is drawn only for a path on
 * this server, because the reader passes through strings that job writers produced.
 *
 * Mounts into #background-jobs-container and #background-jobs-count; the page owns the section chrome.
 * Exposes window.backgroundJobs = { refresh, formatWhen, ... } for the unit tests and the console.
 */

( function() {
    "use strict";

    const SUMMARY_URL   = "/api/jobs/summary";
    const POLL_MS       = 60 * 1000;
    const NOT_REPORTED  = "not reported";
    const DRIFT_TEXT      = "changed outside the endpoint";                  // the words cron-jobs.js shows on the switch, repeated for the abstract
    const UNREADABLE_TEXT = "switch unreadable: the key is missing from the configuration file or holds neither true nor false";
    const STATE_ORDER   = [ "healthy", "behind", "failing", "silent", "unknown" ];   // the order of the header line's counts
    const DEFAULT_SORT  = { id : null, direction : "asc" };   // no header picked: service name A to Z
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

    // The states by urgency, least urgent first (Rick, 11 Nov, row 4b807ffd): failing is the most urgent. Not STATE_ORDER, which orders the header line.
    const HEALTH_URGENCY = [ "healthy", "behind", "silent", "unknown", "failing" ];

    // When a job's last attempt began, in milliseconds; a job with none, or a time that does not parse, counts as -1 (oldest).
    function attemptTime( j ) { return j.last_attempt === null ? -1 : ( Date.parse( j.last_attempt.started_at ) || -1 ); }

    // The default order is service name A to Z (Rick, 11 Nov, row 1ac04991): title, then target.
    function defaultCompare( a, b ) {
        return a.title.localeCompare( b.title ) || ( a.target ?? "" ).localeCompare( b.target ?? "" );
    }

    // The sort orders a reader can pick from the column headers (row 4b807ffd). One entry each: a third order is one more entry
    // here and nothing else. `compare` runs in the ascending direction; "desc" flips it, and ties fall back to the default order.
    // Health runs by HEALTH_URGENCY, healthy at one end and failing at the other. Last run is oldest first when ascending, a job that never ran first.
    const SORT_ORDERS = [
        { id : "name",   label : "Service", compare : defaultCompare },
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
        if ( job.cron_only === true ) return "NOT REPORTING";      // a switch whose job the summary leaves out (reporting switched off)
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
        if ( job.cron_only === true ) return NOT_REPORTED;
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
            return attempt.failure === null ? at + " failed" : at + " failed (" + attempt.failure + ")";
        }
        if ( attempt.outcome === "skipped" ) return at + " skipped";
        if ( attempt.outcome === "clean" && job.work_found_last_run === 0 ) return "ran " + at + ", found nothing";
        return at + " " + attempt.outcome;
    }

    function lastFinishedText( job, todayIso ) {
        if ( job.last_finished === null ) return NOT_REPORTED;
        return formatWhen( job.last_finished.started_at, todayIso );
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
        if ( debt === null ) return NOT_REPORTED;
        if ( debt.freshness !== null ) return freshnessText( debt );
        if ( debt.count === null ) return NOT_REPORTED;
        return ( formatCount( debt.count ) + " " + trendArrow( debt.points ) ).trimEnd();
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
        if ( clears.kind === "never_at_this_rate" ) return "never at this rate";
        if ( clears.kind === "not_enough_runs" ) return "not enough runs";
        if ( clears.days === null ) return NOT_REPORTED;
        return clears.days === 1 ? "1 day" : clears.days + " days";
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

    // ─── Merge the two doors ───────────────────────────────────────────

    // The entry for a switch the summary does not report on (a job with reporting switched off).
    function cronOnlyEntry( row ) {
        return {
            job : row.job, target : null, title : row.title, owner : "", audience : [], notify_interval_seconds : null,
            state : "unknown", running : false, unscheduled : false, schedule_unverified : false, machine_was_off : false,
            reasons : [], applies : { scan_debt : false, fix_debt : false }, last_attempt : null, last_finished : null,
            consecutive_failures : null, work_found_last_run : null, strip : [], scan_debt : null, fix_debt : null,
            schedule : null, liveness : null, evidence : [], rows : [], detail_link : null, runnable : false,
            unknown_reason : null, targets : [], cron : row, cron_only : true,
        };
    }

    // One entry per summary job (a copy carrying its switch row, or null), then one per switch no summary job names. Inputs untouched.
    function mergeJobs( jobs, cronRows ) {
        const byJob  = new Map( cronRows.map( ( r ) => [ r.job, r ] ) );
        const merged = jobs.map( ( j ) => ( { ...j, cron : byJob.get( j.job ) ?? null } ) );
        const named  = new Set( jobs.map( ( j ) => j.job ) );
        return [ ...merged, ...cronRows.filter( ( r ) => !named.has( r.job ) ).map( cronOnlyEntry ) ];
    }

    // ─── The 📋 abstract (markdown; no DOM, no clock) ──────────────────

    function mdText( text ) { return text.replace( /[\\`*_{}[\]<>#|~]/g, ( c ) => "\\" + c ); }

    function mdLink( href, label ) {
        if ( !isSafeHref( href ) ) return mdText( label );
        return "[" + mdText( label ) + "](" + href.replace( /[() ]/g, ( c ) => "%" + c.charCodeAt( 0 ).toString( 16 ).toUpperCase() ) + ")";
    }

    function mdSection( title, lines, level = 2 ) { return "#".repeat( level ) + " " + title + "\n\n" + lines.join( "\n" ) + "\n"; }

    // The series the old sparkline drew, as the text its aria-label carried ("scan debt: 1, 2, 3"). Nothing under two points.
    function trendLines( label, points ) {
        return points.length < 2 ? [] : [ "- Trend (" + label + "): " + points.map( ( p ) => p.value ).join( ", " ) ];
    }

    function reasonLines( job ) {
        if ( job.reasons.length === 0 && job.unknown_reason === null ) return [ "No rule is true: nothing to report." ];
        const lines = job.reasons.map( ( r ) => "- " + mdText( r.text ) );
        if ( job.unknown_reason !== null ) lines.push( "- " + mdText( job.unknown_reason ) );
        if ( job.machine_was_off ) lines.push( "- Missed while the machine was off." );
        return lines;
    }

    function stripLines( job, todayIso ) {
        if ( job.strip.length === 0 ) return [ NOT_REPORTED ];
        return job.strip.map( ( e, i ) => ( i + 1 ) + ". " + formatWhen( e.at, todayIso ) + " " + ( e.outcome === "missed" ? "MISSED (due, no run)" : mdText( e.outcome ) ) );
    }

    function scanLines( job, todayIso ) {
        const debt = job.scan_debt;
        if ( debt === null ) return [ NOT_REPORTED ];
        const count = debt.count === null ? NOT_REPORTED : ( formatCount( debt.count ) + " " + ( debt.unit ?? "" ) ).trim();
        const trend = trendArrow( debt.points );
        return [
            "- Count: " + mdText( count ) + ( trend === "" ? "" : " " + trend ),
            "- As of: " + formatWhen( debt.as_of, todayIso ),
            "- Drained last run: " + formatCount( debt.drained_last_run ),
            "- Arrived last interval: " + formatCount( debt.arrived_last_interval ),
            "- Never checked: " + formatCount( debt.never_checked ),
            "- Clears in: " + ( clearsText( job ) || NOT_REPORTED ),
            ...trendLines( "scan debt", debt.points ),
        ];
    }

    function fixLines( job ) {
        const debt = job.fix_debt;
        if ( debt === null ) return [ NOT_REPORTED ];
        if ( debt.kind === "reported" ) return [ "- Named, not acted on: " + formatCount( debt.open_reported ), ...trendLines( "rows opened", debt.points ) ];
        const trend = trendArrow( debt.points );
        const lines = [
            "- Unfiled: " + formatCount( debt.unfiled ) + ( trend === "" ? "" : " " + trend ),
            "- Filed in total: " + formatCount( debt.filed_total ),
            "- Open now: " + formatCount( debt.open_now ),
            "- Closed in window: " + formatCount( debt.closed_in_window ),
            "- Own mark: " + mdText( debt.own_mark ?? NOT_REPORTED ),
        ];
        lines.push( ...trendLines( "rows opened", debt.points ) );
        if ( isSafeHref( debt.store_href ) ) lines.push( "- " + mdLink( debt.store_href, "Rows in the task store" ) );
        return lines;
    }

    function scheduleLines( job, todayIso ) {
        const s     = job.schedule;
        const lines = [];
        if ( job.liveness !== null ) lines.push( "- Liveness: " + mdText( job.liveness.kind ) + " unit " + mdText( job.liveness.unit ) );
        if ( job.schedule_unverified ) lines.push( "- Check: schedule unverified: the installed schedule could not be read" );
        lines.push( "- Runs: " + ( s === null || s.entries.length === 0 ? "unscheduled" : mdText( s.entries.join( "; " ) ) ) );
        lines.push( "- Last due: " + ( s === null ? NOT_REPORTED : formatWhen( s.last_due, todayIso ) ) );
        lines.push( "- Next due: " + ( s === null ? NOT_REPORTED : formatWhen( s.next_due, todayIso ) ) );
        lines.push( "- Grace: " + graceText( job ) );
        lines.push( "- Tells Rick: " + notifyIntervalText( job ) );
        return lines;
    }

    // What the old Scheduled Jobs row showed: state, schedule, who flipped it and when, how it reads the switch, and the three warnings.
    // The text rules are cron-jobs.js's, which must load first.
    function switchLines( row, cronRows ) {
        const cron  = window.cronJobs;
        const lines = [
            "- State: " + cron.stateText( row.enabled ),
            "- Cron schedule: " + mdText( row.schedule ),
            "- Last changed: " + mdText( cron.changedText( row ) ),
            "- Reads: " + cron.readsText( row ),
        ];
        if ( row.drift ) lines.push( "- Check: " + DRIFT_TEXT );
        if ( row.honoured && row.enabled === null ) lines.push( "- Check: " + UNREADABLE_TEXT );
        const inside = cron.insideText( row, cronRows );
        if ( inside !== null ) lines.push( "- Check: " + mdText( inside ) );
        return lines;
    }

    function peopleLines( job ) {
        const lines = [ "- Owner: " + mdText( job.owner ), "- Told: " + ( job.audience.length === 0 ? "the owner" : mdText( job.audience.join( ", " ) ) ) ];
        for ( const row of job.rows ) lines.push( "- " + mdLink( row.href, row.title ) );
        if ( isSafeHref( job.detail_link ) ) lines.push( "- " + mdLink( job.detail_link, "Open the detail page" ) );
        return lines;
    }

    // The sections every job has, at a heading level; a target's block uses the same ones one level down. `switchPart` goes after Schedule.
    function jobSections( job, todayIso, level, switchPart ) {
        const parts = [ mdSection( "Reasons", reasonLines( job ), level ) ];
        if ( job.liveness === null ) parts.push( mdSection( "Last attempts", stripLines( job, todayIso ), level ) );
        if ( job.applies.scan_debt && job.liveness === null ) parts.push( mdSection( "Scan debt", scanLines( job, todayIso ), level ) );
        if ( job.applies.fix_debt ) parts.push( mdSection( "Fix debt", fixLines( job ), level ) );
        parts.push( mdSection( "Schedule", scheduleLines( job, todayIso ), level ) );
        if ( switchPart !== null ) parts.push( switchPart );
        parts.push( mdSection( "Evidence", job.evidence.length === 0 ? [ NOT_REPORTED ] : job.evidence.map( ( e ) => "- " + mdLink( e.href, e.label + ": " + e.path ) ), level ) );
        parts.push( mdSection( "People", peopleLines( job ), level ) );
        const names = notReportedNames( job );
        parts.push( mdSection( "Not reported", [ names.length === 0 ? "Every figure was reported." : mdText( names.join( ", " ) ) ], level ) );
        return parts;
    }

    // The markdown abstract for one job: what the old fold showed, behind the 📋. Its switch (Switch section), a Target block per target, and its trends as text.
    // A switch-only job (cron_only) carries its title, its Switch and one line saying why nothing else is reported.
    function abstractMarkdown( job, todayIso, cronRows = [] ) {
        const title = "# " + mdText( job.title ) + ( job.target === null ? "" : " (" + mdText( job.target ) + ")" ) + "\n";
        const row   = job.cron ?? null;
        const own   = row === null ? null : mdSection( "Switch", switchLines( row, cronRows ) );
        if ( job.cron_only === true && own !== null ) return [ title, own, "No run reports for this job: reporting is switched off.\n" ].join( "\n" );
        const parts = [ title, ...jobSections( job, todayIso, 2, own ) ];
        for ( const target of job.targets ) {
            parts.push( "## Target: " + mdText( target.title ) + ( target.target === null ? "" : " (" + mdText( target.target ) + ")" ) + "\n" );
            parts.push( ...jobSections( target, todayIso, 3, null ) );
        }
        return parts.join( "\n" );
    }

    // ─── DOM ───────────────────────────────────────────────────────────

    function el( tag, className, text, testid ) {
        const node = document.createElement( tag );
        if ( className !== null ) node.className = className;
        if ( text !== null ) node.textContent = text;
        if ( testid !== null ) node.setAttribute( "data-testid", testid );
        return node;
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

    // The ids of the rows whose ⋯ is open: a repaint reads it and a toggle writes it, so a redraw keeps a row open.
    const openIds = new Set();

    // The 📋 that opens the job's abstract; notifications.js's delegated click handler does the rest.
    function abstractIndicator( job, todayIso, testid, cronRows ) {
        const span = el( "span", "abstract-indicator jobs-abstract", "📋", testid );
        span.setAttribute( "data-abstract", encodeURIComponent( abstractMarkdown( job, todayIso, cronRows ) ) );      // URI-encoded: the legacy handler decodes it
        span.setAttribute( "role", "button" );
        span.setAttribute( "tabindex", "0" );
        span.setAttribute( "title", "View details" );
        return span;
    }

    // Line 2: the figures that apply to the job, then its switch (drawn by cron-jobs.js).
    function lineTwo( job ) {
        const line = el( "div", "jobs-line2", null, "jobs-line2" );
        const figures = [ [ "Scan", scanText( job ), "jobs-fig-scan" ], [ "Fix", fixText( job ), "jobs-fig-fix" ], [ "Clears", clearsText( job ), "jobs-fig-clears" ] ];
        for ( const [ label, text, testid ] of figures ) if ( text !== "" ) line.appendChild( el( "span", "jobs-fig", label + ": " + text, testid ) );
        if ( job.cron !== undefined && job.cron !== null ) line.appendChild( window.cronJobs.switchCells( job.cron ) );
        return line;
    }

    // One target of a job, as a compact line inside the parent's third line.
    function targetLine( target, todayIso ) {
        const line = el( "div", "jobs-target", null, "jobs-target" );
        line.setAttribute( "data-job", target.job );
        line.setAttribute( "data-target", target.target ?? "" );
        line.setAttribute( "data-state", target.state );
        line.append(
            el( "span", "jobs-dot jobs-state-" + target.state, "●", null ),
            el( "span", "jobs-title", target.target === null ? target.title : target.title + " (" + target.target + ")", "jobs-target-title" ),
            el( "span", "jobs-badge", badgeText( target ), "jobs-target-badge" ),
            el( "span", "jobs-last-run", lastRunText( target, todayIso ), "jobs-target-last-run" ),
            abstractIndicator( target, todayIso, "jobs-target-abstract", [] )      // a target has no switch of its own
        );
        return line;
    }

    // Line 3: Run now, then the job's targets.
    function lineThree( job, todayIso, actions, sort ) {
        const line = el( "div", "jobs-line3", null, "jobs-line3" );
        const run  = runNowBlock( job, actions );
        if ( run !== null ) line.appendChild( run );
        for ( const target of sortJobs( job.targets, sort.id, sort.direction ) ) line.appendChild( targetLine( target, todayIso ) );
        if ( line.childElementCount === 0 ) line.textContent = "Nothing to run by hand, and no targets.";
        return line;
    }

    // One job: the collapsed line and its hidden second and third lines. The ⋯ button's aria-expanded tracks them.
    function renderJob( job, todayIso, actions, sort = DEFAULT_SORT ) {
        const id      = itemId( job );
        const item    = el( "section", "jobs-item", null, "jobs-item" );
        item.setAttribute( "data-job", job.job );
        item.setAttribute( "data-target", job.target ?? "" );
        item.setAttribute( "data-state", job.state );

        const heading = document.createElement( "h4" );
        heading.className = "jobs-heading";
        const line = el( "div", "jobs-line", null, "jobs-line" );
        line.id = id + "-line";

        const toggle = document.createElement( "button" );
        toggle.type = "button";
        toggle.className = "task-disclose-button jobs-disclose";
        toggle.setAttribute( "data-task-id", id );
        toggle.setAttribute( "data-testid", "jobs-disclose" );
        toggle.setAttribute( "aria-controls", id + "-panel" );
        toggle.setAttribute( "title", "Show row controls" );
        toggle.textContent = "⋯";
        const last = el( "span", "jobs-disclose-cell", null, null );
        last.appendChild( toggle );
        const cells = [
            [ "jobs-dot jobs-state-" + job.state, "●" ],
            [ "jobs-title", job.target === null ? job.title : job.title + " (" + job.target + ")" ],
            [ "jobs-badge", badgeText( job ) ],
            [ "jobs-last-run", lastRunText( job, todayIso ) ],
            [ "jobs-last-finished", job.liveness === null && job.cron_only !== true ? lastFinishedText( job, todayIso ) : "" ],
        ];
        for ( const [ cls, text ] of cells ) {
            const span = el( "span", cls, text, cls.split( " " )[ 0 ] );
            if ( cls.startsWith( "jobs-dot" ) ) span.setAttribute( "aria-hidden", "true" );
            line.appendChild( span );
        }
        line.appendChild( abstractIndicator( job, todayIso, "jobs-abstract", window.cronJobs.rows() ) );
        line.appendChild( last );      // Rick, 15 Nov: the ⋯ sits at the right-hand end of the row
        heading.appendChild( line );
        item.appendChild( heading );

        const panel = el( "div", "jobs-panel", null, "jobs-panel" );
        panel.id = id + "-panel";
        panel.setAttribute( "role", "region" );
        panel.setAttribute( "aria-labelledby", line.id );
        panel.append( lineTwo( job ), lineThree( job, todayIso, actions, sort ) );
        const opened = openIds.has( id );
        panel.hidden = !opened;
        toggle.setAttribute( "aria-expanded", opened ? "true" : "false" );
        item.appendChild( panel );

        toggle.addEventListener( "click", () => {
            const open = toggle.getAttribute( "aria-expanded" ) === "true";
            toggle.setAttribute( "aria-expanded", open ? "false" : "true" );
            panel.hidden = open;
            if ( open ) openIds.delete( id ); else openIds.add( id );
        } );
        return item;
    }

    // The columns of one collapsed line, in grid order. `sortId` names the SORT_ORDERS entry a header click picks, or null.
    const COLUMNS = [
        { cls : "jobs-dot",          label : "",              sortId : null },
        { cls : "jobs-title",         label : "Service",       sortId : "name" },
        { cls : "jobs-badge",         label : "Status",        sortId : "health" },
        { cls : "jobs-last-run",      label : "Last run",      sortId : "last-run" },
        { cls : "jobs-last-finished", label : "Last finished", sortId : null },
        { cls : "jobs-abstract",      label : "",              sortId : null },
        { cls : "jobs-disclose-cell", label : "",              sortId : null },
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

    // `summary.jobs` is already merged (mergeJobs): every item is one job, with its switch when it has one.
    function renderAccordion( mount, summary, actions, sort = currentSort ) {
        mount.replaceChildren();
        currentSort = sort;
        const cron = window.cronJobs;
        if ( cron.rows().length > 0 ) mount.appendChild( el( "p", "cron-note", cron.canFlip()
            ? "Flipping a switch takes effect at the job's next start, or next tick for a loop. A run already going is not stopped."
            : "Read-only: only an administrator can flip a switch.", "cron-note" ) );
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

    let lastSummary = null;          // the last good summary; a failed poll leaves it on screen

    const failureText = ( err ) => err instanceof Error ? err.message : String( err );

    // Draw the list from the last good answers. Before the summary has arrived, every switch is drawn as a row of its own.
    function repaint() {
        const mount     = document.getElementById( "background-jobs-container" );
        const count     = document.getElementById( "background-jobs-count" );
        const summaryEl = document.getElementById( "background-jobs-summary" );
        if ( mount === null || count === null || summaryEl === null ) return;
        if ( lastSummary === null && window.cronJobs.rows().length === 0 ) return;
        const summary = lastSummary ?? { generated_at : "", caller_is_operator : false, jobs : [] };
        window.cronJobs.resetConfirm();      // a redraw drops a half-finished confirmation, so one stale click never turns a job off
        const merged = mergeJobs( summary.jobs, window.cronJobs.rows() );
        renderAccordion( mount, { ...summary, jobs : merged }, { canRun : summary.caller_is_operator, runNow } );
        const off = window.cronJobs.rows().filter( ( j ) => j.enabled === false ).length;
        count.textContent = merged.length + ( off > 0 ? " (" + off + " off)" : "" );
        summaryEl.textContent = headerLine( summary.jobs );
    }

    async function refresh() {
        const errorEl = document.getElementById( "background-jobs-error" );
        if ( document.getElementById( "background-jobs-container" ) === null || errorEl === null ) return;
        const [ jobs, cron ] = await Promise.allSettled( [
            authFetch( SUMMARY_URL ).then( ( resp ) => { if ( !resp.ok ) throw new Error( "HTTP " + resp.status ); return resp.json(); } ),
            window.cronJobs.load(),
        ] );
        const problems = [];
        if ( jobs.status === "fulfilled" ) lastSummary = jobs.value;
        else problems.push( "Could not load the jobs: " + failureText( jobs.reason ) );
        if ( cron.status === "rejected" ) problems.push( "Could not load the scheduled jobs: " + failureText( cron.reason ) );
        repaint();
        errorEl.textContent = problems.join( " " );
        errorEl.hidden = problems.length === 0;
    }

    function start() {
        const button = document.getElementById( "background-jobs-refresh" );
        if ( button !== null ) button.addEventListener( "click", ( e ) => { e.stopPropagation(); refresh(); } );
        window.cronJobs.onChange( repaint );      // a flip, or another client's frame, repaints the list
        refresh();
        window.setInterval( refresh, POLL_MS );
    }

    window.backgroundJobs = { refresh, start, repaint, renderAccordion, renderJob, sortJobs, mergeJobs, abstractMarkdown, SORT_ORDERS, HEALTH_URGENCY, headerLine, formatWhen, runNowPath, runNowFailureText, isSafeHref };

    if ( document.readyState === "loading" ) document.addEventListener( "DOMContentLoaded", start );
    else start();
} )();
