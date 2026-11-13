// Tests for the jobs accordion and its multiplexer pane, at full coverage.
//
// The accordion is driven with the committed 23-job fixture; the pane (BackgroundJobsRenderer) is
// mounted into the real #background-jobs-pane section parsed out of multiplexer.html. The data is
// src/tests/fixtures/jobs/jobs-summary.fixture.json, the file the Playwright tests serve. Only the HTTP client is faked. The job count is pinned to the
// literal 23, not derived from the fixture, so a dropped job reddens a test.

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { ApiError } from "../../../lupin_app/static/js/multiplexer/api/ApiClient";
import * as F from "../../../lupin_app/static/js/multiplexer/jobs/jobsFormat";
import { renderAccordion, renderJob, sparkline } from "../../../lupin_app/static/js/multiplexer/jobs/jobsRender";
import { createBackgroundJobsRenderer, runNowFailureText, runNowPath, JOBS_POLL_MS } from "../../../lupin_app/static/js/multiplexer/render/BackgroundJobsRenderer";
import type { BackgroundJobsApi } from "../../../lupin_app/static/js/multiplexer/render/BackgroundJobsRenderer";
import { SECTION_TOGGLES } from "../../../lupin_app/static/js/multiplexer/render/templates/sectionToolbar";
import type { JobEntry, JobsSummary } from "../../../lupin_app/static/js/multiplexer/jobs/types";

const HERE         = dirname( fileURLToPath( import.meta.url ) );
const HTML_PATH    = resolve( HERE, "../../../lupin_app/static/html/multiplexer.html" );
const FIXTURE_PATH = resolve( HERE, "../../fixtures/jobs/jobs-summary.fixture.json" );
const FIXTURE      = JSON.parse( readFileSync( FIXTURE_PATH, "utf8" ) ) as JobsSummary;
const TODAY        = FIXTURE.generated_at;

before( () => { if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register(); } );

beforeEach( () => {
  document.body.innerHTML = `<div id="jobs-accordion"></div>`;
} );

const flush = () => new Promise( ( r ) => setImmediate( r ) );
const byId  = ( id: string ) => document.getElementById( id ) as HTMLElement;
const clone = <T,>( v: T ): T => JSON.parse( JSON.stringify( v ) ) as T;
const find  = ( name: string ): JobEntry => clone( FIXTURE.jobs.find( ( j ) => j.job === name ) as JobEntry );
const NO_ACTIONS = { canRun : true, runNow : async () => "ok" };

// ── the fixture itself ──────────────────────────────────────────────────────

test( "the fixture carries the 23 jobs of design 12.7, every state, and every optional field the page reads", () => {
  assert.equal( FIXTURE.schema, "jobs-summary/1" );
  assert.equal( FIXTURE.jobs.length, 23 );
  assert.deepEqual( [ ...new Set( FIXTURE.jobs.map( ( j ) => j.state ) ) ].sort(), [ "failing", "healthy", "silent", "unknown" ] );
  assert.ok( FIXTURE.jobs.some( ( j ) => j.targets.length > 0 ), "targets" );
  assert.ok( FIXTURE.jobs.some( ( j ) => j.liveness !== null ), "liveness" );
  assert.ok( FIXTURE.jobs.some( ( j ) => j.fix_debt !== null && j.fix_debt.kind === "reported" ), "reported fix debt" );
  assert.ok( FIXTURE.jobs.some( ( j ) => j.audience.length > 0 ), "audience" );
  assert.ok( FIXTURE.jobs.some( ( j ) => j.schedule !== null && j.schedule.grace_seconds !== null ), "grace seconds" );
} );

// ── jobsFormat ──────────────────────────────────────────────────────────────

test( "formatWhen prints HH:MM for today, MM-DD HH:MM for another day, and passes odd text through", () => {
  assert.equal( F.formatWhen( "2026-11-07T19:31:02-05:00", TODAY ), "19:31" );
  assert.equal( F.formatWhen( "2026-11-06T19:06:59-05:00", TODAY ), "11-06 19:06" );
  assert.equal( F.formatWhen( null, TODAY ), "not reported" );
  assert.equal( F.formatWhen( "yesterday", TODAY ), "yesterday" );
} );

test( "formatCount groups thousands and prints null as not reported (never 0)", () => {
  assert.equal( F.formatCount( 2124 ), "2,124" );
  assert.equal( F.formatCount( 0 ), "0" );
  assert.equal( F.formatCount( null ), "not reported" );
} );

test( "trendArrow compares the first and last point", () => {
  const p = ( ...v: number[] ) => v.map( ( value, i ) => ( { at : String( i ), value } ) );
  assert.equal( F.trendArrow( [] ), "" );
  assert.equal( F.trendArrow( p( 5 ) ), "" );
  assert.equal( F.trendArrow( p( 1, 9, 2 ) ), "▲" );
  assert.equal( F.trendArrow( p( 9, 1, 8 ) ), "▼" );
  assert.equal( F.trendArrow( p( 4, 9, 4 ) ), "=" );
} );

test( "sortJobs defaults to service name A to Z, then target, whatever the state, without touching its input (row 1ac04991)", () => {
  const a = { ...find( "duplicate-check" ), state : "healthy" as const, title : "B" };
  const b = { ...find( "duplicate-check" ), state : "failing" as const, title : "Z" };
  const c = { ...find( "duplicate-check" ), state : "healthy" as const, title : "A", target : "y" };
  const d = { ...find( "duplicate-check" ), state : "healthy" as const, title : "A", target : null };
  const e = { ...find( "duplicate-check" ), state : "healthy" as const, title : "A", target : "x" };
  const input = [ a, b, c, d, e ];
  const out   = F.sortJobs( input );
  assert.deepEqual( out.map( ( j ) => `${ j.state }/${ j.title }/${ j.target }` ), [ "healthy/A/null", "healthy/A/x", "healthy/A/y", "healthy/B/null", "failing/Z/null" ] );
  assert.equal( input[ 0 ], a );
  const real = F.sortJobs( FIXTURE.jobs ).map( ( j ) => j.title );
  assert.deepEqual( real.slice( 0, 2 ), [ "Commons archival", "Context tick" ] );
  assert.deepEqual( real, [ ...real ].sort( ( x, y ) => x.localeCompare( y ) ), "title order; no job has a target in the fixture that changes it" );
} );

test( "sortJobs ignores state, running and attempt time by default: the names alone decide (row 1ac04991, replacing row 300af681)", () => {
  const mk = ( name: string, state: JobEntry[ "state" ], at: string | null, running = false ): JobEntry => {
    const base = find( "duplicate-check" );
    const attempt = at === null ? null : { ...( base.last_attempt as NonNullable<JobEntry[ "last_attempt" ]> ), started_at : at };
    return { ...base, job : name, title : name, target : null, state, running, last_attempt : attempt };
  };
  const jobs = [
    mk( "u", "unknown", null ), mk( "s", "silent", "2026-11-09T10:00:00-05:00" ), mk( "f", "failing", "2026-11-09T10:00:00-05:00" ),
    mk( "b", "behind", "2026-11-09T10:00:00-05:00" ), mk( "h-old", "healthy", "2026-11-08T10:00:00-05:00" ), mk( "h-new", "healthy", "2026-11-09T09:00:00-05:00" ),
    mk( "h-none", "healthy", null ), mk( "h-bad", "healthy", "not a time" ), mk( "z-run", "failing", "2026-11-01T10:00:00-05:00", true ),
    mk( "h-utc", "healthy", "2026-11-09T14:30:00+00:00" ),
  ];
  assert.deepEqual( F.sortJobs( jobs ).map( ( j ) => j.job ),
    [ "b", "f", "h-bad", "h-new", "h-none", "h-old", "h-utc", "s", "u", "z-run" ] );
  assert.deepEqual( F.STATE_ORDER, [ "healthy", "behind", "failing", "silent", "unknown" ] );
} );

test( "headerLine counts the states in active-first order", () => {
  assert.equal( F.headerLine( [] ), "0 jobs" );
  assert.equal( F.headerLine( [ find( "wiki-librarian" ) ] ), "1 job: 1 failing" );
  const mixed = [ "failing", "failing", "behind", "healthy" ].map( ( state ) => ( { ...find( "wiki-librarian" ), state } as JobEntry ) );
  assert.equal( F.headerLine( mixed ), "4 jobs: 1 healthy, 1 behind, 2 failing" );
} );

test( "badgeText names the first state, any other state a reason names, and UNSCHEDULED", () => {
  assert.equal( F.badgeText( find( "duplicate-check" ) ), "FAILING · BEHIND" );
  assert.equal( F.badgeText( find( "vector-refresh" ) ), "healthy" );
  const j = find( "pokes" );
  assert.equal( F.badgeText( j ), "UNKNOWN · UNSCHEDULED" );
  j.reasons = [ { state : "healthy", rule : "x", text : "t" } ];
  assert.equal( F.badgeText( j ), "UNKNOWN · UNSCHEDULED", "a healthy reason adds no label" );
  j.schedule_unverified = true;
  assert.equal( F.badgeText( j ), "UNKNOWN · UNSCHEDULED · schedule unverified" );
} );

test( "lastRunText covers liveness, silent, no attempt, failed, skipped, quiet and carried", () => {
  const j = find( "duplicate-check" );
  assert.equal( F.lastRunText( j, TODAY ), "19:31 failed (stale_branch)" );
  j.last_attempt!.failure = null;
  assert.equal( F.lastRunText( j, TODAY ), "19:31 failed" );
  j.last_attempt!.outcome = "skipped";
  assert.equal( F.lastRunText( j, TODAY ), "19:31 skipped" );
  j.last_attempt!.outcome = "clean"; j.work_found_last_run = 0;
  assert.equal( F.lastRunText( j, TODAY ), "ran 19:31, found nothing" );
  j.work_found_last_run = 4;
  assert.equal( F.lastRunText( j, TODAY ), "19:31 clean" );
  j.last_attempt!.outcome = "carried";
  assert.equal( F.lastRunText( j, TODAY ), "19:31 carried" );
  j.last_attempt = null;
  assert.equal( F.lastRunText( j, TODAY ), "no run recorded" );
  j.state = "unknown";
  assert.equal( F.lastRunText( j, TODAY ), "never reported" );
  j.state = "silent";
  assert.equal( F.lastRunText( j, TODAY ), "SILENT, due 19:30, nothing since" );
  j.schedule = null;
  assert.equal( F.lastRunText( j, TODAY ), "SILENT, due not reported, nothing since" );
  const live = find( "fleet-arbiter" );
  assert.equal( F.lastRunText( live, TODAY ), "up (lupin-arbiter-app.service)" );
  live.liveness!.up = false;
  assert.equal( F.lastRunText( live, TODAY ), "down (lupin-arbiter-app.service)" );
  live.liveness!.up = null;
  assert.equal( F.lastRunText( live, TODAY ), "unit lupin-arbiter-app.service is not loaded" );
} );

test( "lastFinishedText prints the time or not reported", () => {
  assert.equal( F.lastFinishedText( find( "duplicate-check" ), TODAY ), "11-06 19:06" );
  assert.equal( F.lastFinishedText( find( "reuse-behaviour" ), TODAY ), "not reported" );
} );

test( "scanText: absent when it does not apply, and each way a figure can be missing", () => {
  assert.equal( F.scanText( find( "reuse-behaviour" ) ), "" );
  assert.equal( F.scanText( find( "duplicate-check" ) ), "2,124 ▲" );
  const j = find( "duplicate-check" );
  j.scan_debt!.points = [];
  assert.equal( F.scanText( j ), "2,124" );
  j.scan_debt!.count = null;
  assert.equal( F.scanText( j ), "not reported" );
  j.scan_debt!.count = 7; j.scan_debt!.unit = null;
  assert.equal( F.scanText( j ), "7" );
  j.scan_debt!.count = null;
  j.scan_debt = null;
  assert.equal( F.scanText( j ), "not reported" );
  assert.equal( F.scanText( find( "vector-refresh" ) ), "age 2 h of 36" );
} );

test( "freshnessText covers a missing block, a missing age, and a missing limit", () => {
  const debt = find( "vector-refresh" ).scan_debt!;
  assert.equal( F.freshnessText( debt ), "age 2 h of 36" );
  debt.freshness!.stale_after_hours = null;
  assert.equal( F.freshnessText( debt ), "age 2 h" );
  debt.freshness!.age_hours = null;
  assert.equal( F.freshnessText( debt ), "age: not reported" );
  debt.freshness = null;
  assert.equal( F.freshnessText( debt ), "age: not reported" );
} );

test( "fixText covers rows, reported piles, and every missing figure", () => {
  assert.equal( F.fixText( find( "vector-refresh" ) ), "" );
  assert.equal( F.fixText( find( "duplicate-check" ) ), "unfiled 107 ▲" );
  const j = find( "duplicate-check" );
  j.fix_debt!.points = [];
  assert.equal( F.fixText( j ), "unfiled 107" );
  j.fix_debt!.unfiled = null;
  assert.equal( F.fixText( j ), "rows: not reported" );
  j.fix_debt = null;
  assert.equal( F.fixText( j ), "rows: not reported" );
  const rep = find( "disk-report" );
  assert.equal( F.fixText( rep ), "named 20, not acted on" );
  rep.fix_debt!.open_reported = null;
  assert.equal( F.fixText( rep ), "named: not reported" );
} );

test( "clearsText covers never, not enough runs, days, one day and missing", () => {
  assert.equal( F.clearsText( find( "duplicate-check" ) ), "never at this rate" );
  assert.equal( F.clearsText( find( "wiki-librarian" ) ), "not enough runs" );
  const j = find( "hook-log-sweep" );
  assert.equal( F.clearsText( j ), "1 day" );
  j.scan_debt!.clears_in = { kind : "days", days : 3.2 };
  assert.equal( F.clearsText( j ), "3.2 days" );
  j.scan_debt!.clears_in = { kind : "days", days : null };
  assert.equal( F.clearsText( j ), "not reported" );
  j.scan_debt!.clears_in = null;
  assert.equal( F.clearsText( j ), "" );
  j.scan_debt = null;
  assert.equal( F.clearsText( j ), "" );
  assert.equal( F.clearsText( find( "reuse-behaviour" ) ), "" );
} );

test( "notReportedNames lists each null by name and skips debts that do not apply", () => {
  assert.deepEqual( F.notReportedNames( find( "reuse-behaviour" ) ), [ "last finished run" ] );
  const wiki = F.notReportedNames( find( "wiki-librarian" ) );
  assert.deepEqual( wiki, [ "never checked", "drained last run", "arrived last interval", "open rows", "rows closed in window" ] );
  const j = find( "duplicate-check" );
  j.scan_debt!.count = null;
  assert.ok( F.notReportedNames( j ).includes( "scan debt count" ) );
  j.scan_debt = null; j.fix_debt = null;
  assert.deepEqual( F.notReportedNames( j ), [ "scan debt", "fix debt" ] );
  const k = find( "duplicate-check" );
  k.fix_debt!.unfiled = null;
  assert.ok( F.notReportedNames( k ).includes( "unfiled rows" ) );
  const rep = find( "disk-report" );
  assert.deepEqual( F.notReportedNames( rep ), [] );
  rep.fix_debt!.open_reported = null;
  assert.deepEqual( F.notReportedNames( rep ), [ "named pile" ] );
  assert.deepEqual( F.notReportedNames( find( "vector-refresh" ) ), [] , "freshness covers the other scan fields" );
  assert.deepEqual( F.notReportedNames( find( "fleet-arbiter" ) ), [ "last finished run" ] );
} );

test( "graceText and notifyIntervalText", () => {
  const j = find( "duplicate-check" );
  assert.equal( F.graceText( j ), "30 minutes" );
  j.schedule!.grace_seconds = 90;
  assert.equal( F.graceText( j ), "90 seconds" );
  j.schedule!.grace_seconds = null; j.schedule!.grace_minutes = null;
  assert.equal( F.graceText( j ), "not reported" );
  j.schedule = null;
  assert.equal( F.graceText( j ), "not reported" );
  const n = ( s: number | null ) => F.notifyIntervalText( { ...j, notify_interval_seconds : s } );
  assert.deepEqual( [ n( 3600 ), n( 86400 ), n( 600 ), n( 45 ), n( null ) ], [ "every 1 h", "every 24 h", "every 10 min", "every 45 s", "not reported" ] );
} );

test( "isSafeHref accepts only a path on this server", () => {
  for ( const ok of [ "/app/docs?path=lupin/x", "/app/tasks/view?row=1" ] ) assert.equal( F.isSafeHref( ok ), true, ok );
  for ( const bad of [ null, "javascript:alert(1)", "https://evil.example/", "//evil.example/", "/a\\b", "relative/path" ] ) assert.equal( F.isSafeHref( bad ), false, String( bad ) );
} );

// ── jobsRender ──────────────────────────────────────────────────────────────

function drawAll( summary: JobsSummary = FIXTURE ): HTMLElement {
  renderAccordion( document, byId( "jobs-accordion" ), summary, NO_ACTIONS );
  return byId( "jobs-accordion" );
}

test( "the accordion draws all 23 jobs (plus nested targets) by service name A to Z, each collapsed", () => {
  const mount = drawAll();
  const top   = ( [ ...mount.children ] as HTMLElement[] ).filter( ( c ) => c.getAttribute( "data-testid" ) === "jobs-item" );   // the header row is the first child
  assert.equal( top.length, 23 );
  const titles = top.map( ( t ) => ( t.querySelector( "[data-testid=jobs-title]" ) as HTMLElement ).textContent as string );
  assert.deepEqual( titles.slice( 0, 2 ), [ "Commons archival", "Context tick" ] );
  assert.deepEqual( titles, [ ...titles ].sort( ( a, b ) => a.localeCompare( b ) ) );
  for ( const line of mount.querySelectorAll( "[data-testid=jobs-line]" ) ) assert.equal( line.getAttribute( "aria-expanded" ), "false" );
  for ( const panel of mount.querySelectorAll( "[data-testid=jobs-panel]" ) ) assert.equal( ( panel as HTMLElement ).hidden, true );
  assert.equal( mount.querySelectorAll( "[data-job=side-services]" ).length, 4, "the side-services job and its three targets" );
} );

test( "the duplicate check's collapsed line reads as design 6 shows it", () => {
  const item = drawAll().querySelector( "[data-job=duplicate-check]" ) as HTMLElement;
  const text = ( id: string ) => ( item.querySelector( `[data-testid=${ id }]` ) as HTMLElement ).textContent;
  assert.equal( text( "jobs-title" ), "Duplicate check" );
  assert.equal( text( "jobs-badge" ), "FAILING · BEHIND" );
  assert.equal( text( "jobs-last-run" ), "19:31 failed (stale_branch)" );
  assert.equal( text( "jobs-last-finished" ), "11-06 19:06" );
  assert.equal( text( "jobs-scan-cell" ), "2,124 ▲" );
  assert.equal( text( "jobs-fix-cell" ), "unfiled 107 ▲" );
  assert.equal( text( "jobs-clears-cell" ), "never at this rate" );
} );

test( "clicking a line expands its panel and clicking again collapses it; lines are independent", () => {
  const mount = drawAll();
  const lines = [ ...mount.querySelectorAll( ":scope > [data-testid=jobs-item] > h2 > [data-testid=jobs-line]" ) ] as HTMLElement[];
  const panelOf = ( l: HTMLElement ) => document.getElementById( l.getAttribute( "aria-controls" ) as string ) as HTMLElement;
  lines[ 0 ]!.click(); lines[ 1 ]!.click();
  assert.deepEqual( [ lines[ 0 ]!.getAttribute( "aria-expanded" ), panelOf( lines[ 0 ]! ).hidden, panelOf( lines[ 1 ]! ).hidden ], [ "true", false, false ] );
  assert.equal( lines[ 0 ]!.querySelector( ".jobs-caret" )!.textContent, "▼" );
  lines[ 0 ]!.click();
  assert.deepEqual( [ lines[ 0 ]!.getAttribute( "aria-expanded" ), panelOf( lines[ 0 ]! ).hidden, panelOf( lines[ 1 ]! ).hidden ], [ "false", true, false ] );
  assert.equal( lines[ 0 ]!.querySelector( ".jobs-caret" )!.textContent, "▶" );
  assert.equal( new Set( [ ...mount.querySelectorAll( "[id]" ) ].map( ( e ) => e.id ) ).size, mount.querySelectorAll( "[id]" ).length, "every id is unique" );
} );

test( "the duplicate check's expanded panel carries every block of design 6", () => {
  const item = drawAll().querySelector( "[data-job=duplicate-check]" ) as HTMLElement;
  const q    = ( id: string ) => item.querySelector( `[data-testid=${ id }]` ) as HTMLElement;
  assert.equal( item.querySelectorAll( "[data-testid=jobs-reason]" ).length, 3 );
  assert.deepEqual( [ ...item.querySelectorAll( "[data-testid=jobs-strip-entry]" ) ].map( ( e ) => e.getAttribute( "data-outcome" ) ), [ "carried", "carried", "missed", "carried", "failed" ] );
  assert.match( item.querySelectorAll( "[data-testid=jobs-strip-entry]" )[ 2 ]!.textContent as string, /MISSED/ );
  assert.equal( q( "jobs-scan-count" ).textContent, "2,124 definitions" );
  assert.equal( q( "jobs-scan-clears" ).textContent, "never at this rate" );
  assert.equal( q( "jobs-fix-unfiled" ).textContent, "107" );
  assert.equal( q( "jobs-fix-mark" ).textContent, "job:duplicate-check" );
  assert.equal( item.querySelectorAll( "[data-testid=jobs-sparkline]" ).length, 2 );
  assert.equal( q( "jobs-schedule-grace" ).textContent, "30 minutes" );
  assert.equal( q( "jobs-notify-interval" ).textContent, "every 1 h" );
  assert.equal( q( "jobs-owner" ).textContent, "cheech" );
  assert.equal( q( "jobs-detail-link" ).getAttribute( "href" ), "/app/duplicate-check" );
  assert.equal( q( "jobs-evidence-link" ).getAttribute( "href" ), "/app/docs?path=lupin/io/duplicate-check-daily/runs.jsonl" );
  assert.equal( item.querySelectorAll( "[data-testid=jobs-row-link]" ).length, 2, "rows are titled links, not bare ids" );
  assert.equal( q( "jobs-fix-store-link" ).getAttribute( "href" ), "/app/tasks?correlation_key=job:duplicate-check" );
  assert.match( q( "jobs-not-reported-names" ).textContent as string, /never checked/ );
  assert.equal( q( "jobs-run-now" ).textContent, "Run now" );
} );

test( "a job whose installed schedule could not be read says so on its line and in its panel", () => {
  const item = renderJob( document, find( "hook-link-tick" ), TODAY, NO_ACTIONS );
  assert.equal( item.querySelector( "[data-testid=jobs-badge]" )!.textContent, "UNKNOWN · schedule unverified" );
  assert.match( item.querySelector( "[data-testid=jobs-schedule-unverified]" )!.textContent as string, /could not be read/ );
  const other = renderJob( document, find( "doc-parity-tick" ), TODAY, NO_ACTIONS );
  assert.ok( other.querySelector( "[data-testid=jobs-schedule-unverified]" ) === null, "other has no [data-testid=jobs-schedule-unverified]" );
  assert.equal( FIXTURE.jobs.filter( ( j ) => j.schedule_unverified ).length, 1 );
} );

test( "a scan count with no unit prints the bare number", () => {
  const j = find( "duplicate-check" ); j.scan_debt!.unit = null;
  const item = renderJob( document, j, TODAY, NO_ACTIONS );
  assert.equal( item.querySelector( "[data-testid=jobs-scan-count]" )!.textContent, "2,124" );
} );

test( "debts that do not apply are absent; debts that apply but are null say not reported", () => {
  const reuse = renderJob( document, find( "reuse-behaviour" ), TODAY, NO_ACTIONS );
  assert.ok( reuse.querySelector( "[data-testid=jobs-scan]" ) === null, "reuse has no [data-testid=jobs-scan]" );
  assert.ok( reuse.querySelector( "[data-testid=jobs-fix]" ) === null, "reuse has no [data-testid=jobs-fix]" );
  const j = find( "duplicate-check" ); j.scan_debt = null; j.fix_debt = null; j.strip = [];
  const item = renderJob( document, j, TODAY, NO_ACTIONS );
  assert.equal( item.querySelector( "[data-testid=jobs-scan] p" )!.textContent, "not reported" );
  assert.equal( item.querySelector( "[data-testid=jobs-fix] p" )!.textContent, "not reported" );
  assert.equal( item.querySelector( "[data-testid=jobs-strip] p" )!.textContent, "not reported" );
} );

test( "a liveness job shows up or down and no strip, scan or run history", () => {
  const item = renderJob( document, find( "fleet-arbiter" ), TODAY, NO_ACTIONS );
  assert.equal( item.querySelector( "[data-testid=jobs-liveness]" )!.textContent, "systemd unit lupin-arbiter-app.service" );
  assert.ok( item.querySelector( "[data-testid=jobs-strip]" ) === null, "item has no [data-testid=jobs-strip]" );
  assert.ok( item.querySelector( "[data-testid=jobs-scan]" ) === null, "item has no [data-testid=jobs-scan]" );
  assert.equal( item.querySelector( "[data-testid=jobs-last-finished]" )!.textContent, "" );
  assert.ok( item.querySelector( "[data-testid=jobs-run-now]" ) === null, "runnable false hides Run now" );
} );

test( "reasons: the empty case, an unknown reason, and the machine-was-off clause", () => {
  const quiet = renderJob( document, find( "vector-refresh" ), TODAY, NO_ACTIONS );
  assert.match( quiet.querySelector( "[data-testid=jobs-reasons] p" )!.textContent as string, /nothing to report/ );
  const unknown = renderJob( document, find( "doc-parity-tick" ), TODAY, NO_ACTIONS );
  assert.match( unknown.querySelector( "[data-testid=jobs-reason]" )!.textContent as string, /Never reported/ );
  const silent = renderJob( document, find( "context-tick" ), TODAY, NO_ACTIONS );
  const texts  = [ ...silent.querySelectorAll( "[data-testid=jobs-reason]" ) ].map( ( e ) => e.textContent as string );
  assert.ok( texts.some( ( t ) => /machine was off/.test( t ) ) );
  assert.equal( silent.querySelector( "[data-testid=jobs-badge]" )!.textContent, "SILENT" );
} );

test( "a reported fix debt reads named, not acted on; unreported evidence and schedule say so", () => {
  const rep = renderJob( document, find( "disk-report" ), TODAY, NO_ACTIONS );
  assert.equal( rep.querySelector( "[data-testid=jobs-fix-reported]" )!.textContent, "20" );
  assert.equal( rep.querySelector( "[data-testid=jobs-evidence] p" )!.textContent, "not reported" );
  const pokes = renderJob( document, find( "pokes" ), TODAY, NO_ACTIONS );
  assert.equal( pokes.querySelector( "[data-testid=jobs-schedule-entries]" )!.textContent, "unscheduled" );
  assert.equal( pokes.querySelector( "[data-testid=jobs-schedule-last-due]" )!.textContent, "not reported" );
  assert.equal( pokes.querySelector( "[data-testid=jobs-schedule-next-due]" )!.textContent, "not reported" );
  assert.equal( pokes.querySelector( "[data-testid=jobs-audience]" )!.textContent, "the owner" );
} );

test( "unsafe hrefs are drawn as text, never as links", () => {
  const j = find( "duplicate-check" );
  j.detail_link = "javascript:alert(1)";
  j.evidence[ 0 ]!.href = "https://evil.example/x";
  j.rows[ 0 ]!.href = "//evil.example/y";
  j.fix_debt!.store_href = "javascript:void(0)";
  const item = renderJob( document, j, TODAY, NO_ACTIONS );
  assert.ok( item.querySelector( "[data-testid=jobs-detail-link]" ) === null, "item has no [data-testid=jobs-detail-link]" );
  assert.ok( item.querySelector( "[data-testid=jobs-fix-store-link]" ) === null, "item has no [data-testid=jobs-fix-store-link]" );
  assert.equal( item.querySelectorAll( "[data-testid=jobs-evidence-link]" ).length, 0 );
  assert.equal( item.querySelectorAll( "[data-testid=jobs-row-link]" ).length, 1 );
  assert.equal( item.querySelector( "[data-testid=jobs-evidence-path]" )!.textContent, "Ledger line: io/duplicate-check-daily/runs.jsonl:9" );
  assert.equal( item.querySelector( "[data-testid=jobs-row-title]" )!.textContent, j.rows[ 0 ]!.title );
  assert.equal( item.querySelectorAll( "a[href^=javascript]" ).length, 0 );
} );

test( "text from a job writer is never parsed as markup", () => {
  const j = find( "duplicate-check" );
  j.title = "<img src=x onerror=alert(1)>";
  j.reasons[ 0 ]!.text = "<script>alert(2)</script>";
  const item = renderJob( document, j, TODAY, NO_ACTIONS );
  assert.equal( item.querySelectorAll( "img, script" ).length, 0 );
  assert.equal( item.querySelector( "[data-testid=jobs-title]" )!.textContent, "<img src=x onerror=alert(1)>" );
} );

test( "sparkline draws nothing under two points and a level line for a flat series", () => {
  const p = ( ...v: number[] ) => v.map( ( value, i ) => ( { at : String( i ), value } ) );
  assert.equal( sparkline( document, p( 3 ), "x" ), null );
  const flat = sparkline( document, p( 4, 4, 4 ), "flat" ) as SVGElement;
  assert.equal( flat.querySelector( "polyline" )!.getAttribute( "points" ), "1.0,12.0 60.0,12.0 119.0,12.0" );
  const up = sparkline( document, p( 0, 10 ), "up" ) as SVGElement;
  assert.equal( up.querySelector( "polyline" )!.getAttribute( "points" ), "1.0,23.0 119.0,1.0" );
  assert.equal( up.getAttribute( "aria-label" ), "up: 0, 10" );
} );

test( "a caller who is not the operator sees no Run now button anywhere, nested targets included", () => {
  const item = renderJob( document, find( "worktree-census" ), TODAY, { canRun : false, runNow : async () => "ok" } );
  assert.equal( item.querySelectorAll( "[data-testid=jobs-run-now]" ).length, 0 );
  assert.equal( item.querySelectorAll( "[data-testid=jobs-item]" ).length, 3, "its three targets are still drawn" );
  const mount = byId( "jobs-accordion" );
  renderAccordion( document, mount, { ...clone( FIXTURE ), caller_is_operator : false }, { canRun : false, runNow : async () => "ok" } );
  assert.equal( mount.querySelectorAll( "[data-testid=jobs-run-now]" ).length, 0 );
  renderAccordion( document, mount, FIXTURE, NO_ACTIONS );
  assert.equal( mount.querySelectorAll( "[data-testid=jobs-run-now]" ).length > 0, true, "positive control: the operator does see buttons" );
} );

test( "Run now disables the button while it runs, prints the outcome, and reports a rejected promise", async () => {
  let release!: ( s: string ) => void;
  const calls: string[] = [];
  const actions = { canRun : true, runNow : ( job: JobEntry ) => { calls.push( job.job ); return new Promise<string>( ( r ) => { release = r; } ); } };
  const item = renderJob( document, find( "duplicate-check" ), TODAY, actions );
  const btn  = item.querySelector( "[data-testid=jobs-run-now]" ) as HTMLButtonElement;
  const out  = item.querySelector( "[data-testid=jobs-run-status]" ) as HTMLElement;
  btn.click();
  assert.deepEqual( [ btn.disabled, out.textContent, calls ], [ true, "Starting…", [ "duplicate-check" ] ] );
  release( "Started." ); await flush();
  assert.deepEqual( [ btn.disabled, out.textContent ], [ false, "Started." ] );
  const bad  = renderJob( document, find( "duplicate-check" ), TODAY, { canRun : true, runNow : () => Promise.reject( new Error( "boom" ) ) } );
  const btn2 = bad.querySelector( "[data-testid=jobs-run-now]" ) as HTMLButtonElement;
  btn2.click(); await flush();
  assert.deepEqual( [ btn2.disabled, ( bad.querySelector( "[data-testid=jobs-run-status]" ) as HTMLElement ).textContent ], [ false, "Run now failed: Error: boom" ] );
} );

test( "targets draw as nested items with ids that cannot collide", () => {
  const item = renderJob( document, find( "worktree-census" ), TODAY, NO_ACTIONS );
  const nested = [ ...item.querySelectorAll( "[data-testid=jobs-panel] [data-testid=jobs-item]" ) ];
  assert.deepEqual( nested.map( ( n ) => n.getAttribute( "data-target" ) ).sort(), [ "cosa-voice", "lupin", "planning-is-prompting" ] );
  const ids = [ ...item.querySelectorAll( "[id]" ) ].map( ( e ) => e.id );
  assert.equal( new Set( ids ).size, ids.length );
  const lupin = nested.find( ( n ) => n.getAttribute( "data-target" ) === "lupin" ) as HTMLElement;
  assert.equal( lupin.querySelector( "[data-testid=jobs-title]" )!.textContent, "Worktree census (lupin)" );
} );

// ── BackgroundJobsRenderer ──────────────────────────────────────────────────

interface Harness { api: BackgroundJobsApi; gets: string[]; posts: string[]; timers: Array<() => void>; cleared: number[] }

function harness( api: Partial<BackgroundJobsApi> = {} ): Harness {
  const h: Harness = { api : undefined as unknown as BackgroundJobsApi, gets : [], posts : [], timers : [], cleared : [] };
  h.api = {
    get  : api.get  ?? ( async <T,>( p: string ): Promise<T> => { h.gets.push( p ); return clone( FIXTURE ) as unknown as T; } ),
    post : api.post ?? ( async <T,>( p: string ): Promise<T> => { h.posts.push( p ); return { job : "x", target : null, status : "started", trigger : "hand", pid : 4242, started_at : "2026-11-07T20:31:00-05:00" } as unknown as T; } ),
  };
  return h;
}

/** The real section from multiplexer.html, so the pane meets its own markup. */
function paneFromPage(): HTMLElement {
  const html = readFileSync( HTML_PATH, "utf8" );
  const tag  = ( html.match( /<section id="background-jobs-pane"[^>]*><\/section>/ ) as RegExpMatchArray )[ 0 ] as string;
  document.body.innerHTML = tag;
  return byId( "background-jobs-pane" );
}

function build( h: Harness ) {
  return createBackgroundJobsRenderer( {
    api : h.api,
    setIntervalFn : ( fn, ms ) => { assert.equal( ms, JOBS_POLL_MS ); h.timers.push( fn ); return h.timers.length; },
    clearIntervalFn : ( id ) => { h.cleared.push( id ); },
  } );
}

const mounted = async ( h: Harness ) => {
  const root = paneFromPage();
  const r    = build( h );
  r.mount( root );
  await flush();
  return { root, r };
};

test( "the page declares #background-jobs-pane right after the epic board pane, and the toolbar names it", () => {
  const html = readFileSync( HTML_PATH, "utf8" );
  assert.ok( html.indexOf( 'id="epic-board-pane"' ) < html.indexOf( 'id="background-jobs-pane"' ) );
  assert.ok( html.indexOf( 'id="background-jobs-pane"' ) < html.indexOf( 'id="jobs-pane"' ) );
} );

test( "mounted: loads the summary once, draws 23 jobs, counts them, titles the header with the state line, and polls", async () => {
  const h = harness();
  const { root } = await mounted( h );
  assert.deepEqual( h.gets, [ "/api/jobs/summary" ] );
  assert.equal( root.querySelectorAll( "[data-testid=jobs-accordion] > [data-testid=jobs-item]" ).length, 23 );
  assert.equal( root.querySelector( "[data-testid=multiplexer-background-jobs-count]" )!.textContent, "23" );
  assert.match( root.querySelector( "[data-testid=multiplexer-background-jobs-header]" )!.getAttribute( "title" ) as string, /^23 jobs: 9 healthy, 3 failing, 2 silent, 9 unknown$/ );
  assert.equal( ( root.querySelector( "[data-testid=jobs-error]" ) as HTMLElement ).hidden, true );
  assert.equal( h.timers.length, 1 );
  h.timers[ 0 ]!(); await flush();
  assert.equal( h.gets.length, 2 );
} );

test( "the header chevron collapses the section", async () => {
  const { root } = await mounted( harness() );
  ( root.querySelector( ".toggle-button" ) as HTMLElement ).click();
  assert.equal( root.getAttribute( "data-collapsed" ), "true" );
} );

test( "a second mount without unmount throws; unmount stops the poll, clears the root, and is idempotent", async () => {
  const h = harness();
  const { root, r } = await mounted( h );
  assert.throws( () => r.mount( root ), /already mounted/ );
  r.unmount();
  assert.deepEqual( h.cleared, [ 1 ] );
  assert.equal( root.children.length, 0 );
  r.unmount();
  assert.deepEqual( h.cleared, [ 1 ] );
  await r.refresh();                                          // unmounted: nothing to paint, nothing thrown
  assert.equal( h.gets.length, 1 );
  r.mount( root ); await flush();                             // and it can mount again
  assert.equal( h.gets.length, 2 );
} );

test( "the pane uses the ambient document and timers when none are injected, and a reply landing after unmount is dropped", async () => {
  paneFromPage();
  let release: ( v: JobsSummary ) => void = () => {};
  const api = { get : <T,>() => new Promise<T>( ( res ) => { release = res as unknown as ( v: JobsSummary ) => void; } ), post : async () => ( {} as never ) };
  const r = createBackgroundJobsRenderer( { api } );
  r.mount( byId( "background-jobs-pane" ) );
  r.unmount();
  release( clone( FIXTURE ) ); await flush();
  assert.equal( byId( "background-jobs-pane" ).children.length, 0 );
} );

test( "hides Run now when the summary says the caller is not the operator", async () => {
  const { root } = await mounted( harness( { get : async <T,>(): Promise<T> => ( { ...clone( FIXTURE ), caller_is_operator : false } ) as unknown as T } ) );
  assert.equal( root.querySelectorAll( "[data-testid=jobs-item]" ).length >= 23, true );
  assert.equal( root.querySelectorAll( "[data-testid=jobs-run-now]" ).length, 0 );
} );

test( "the refresh button reloads; a failed reload shows the reason and keeps the last good accordion", async () => {
  let fail: unknown = null;
  const { root } = await mounted( harness( { get : async <T,>(): Promise<T> => { if ( fail !== null ) throw fail; return clone( FIXTURE ) as unknown as T; } } ) );
  const btn = root.querySelector( "[data-testid=multiplexer-background-jobs-refresh]" ) as HTMLElement;
  const err = root.querySelector( "[data-testid=jobs-error]" ) as HTMLElement;
  fail = new ApiError( 503, "/api/jobs/summary", "down" );
  btn.click(); await flush();
  assert.equal( err.hidden, false );
  assert.equal( err.textContent, "Could not load the jobs: HTTP 503" );
  assert.equal( root.querySelectorAll( "[data-testid=jobs-accordion] > [data-testid=jobs-item]" ).length, 23 );
  fail = new Error( "network down" );
  btn.click(); await flush();
  assert.equal( err.textContent, "Could not load the jobs: Error: network down" );
  fail = null;
  btn.click(); await flush();
  assert.equal( err.hidden, true );
} );

test( "Run now posts to the job's own door, with ?target= for a target, and prints the outcome", async () => {
  const h = harness();
  const { root } = await mounted( h );
  const dup = root.querySelector( "[data-job=duplicate-check]" ) as HTMLElement;
  ( dup.querySelector( "[data-testid=jobs-run-now]" ) as HTMLElement ).click(); await flush();
  assert.deepEqual( h.posts, [ "/api/jobs/duplicate-check/run" ] );
  assert.equal( ( dup.querySelector( "[data-testid=jobs-run-status]" ) as HTMLElement ).textContent, "Started at 2026-11-07T20:31:00-05:00 (pid 4242)." );
  assert.equal( runNowPath( { ...find( "worktree-census" ), job : "a b", target : "x/y" } ), "/api/jobs/a%20b/run?target=x%2Fy" );
} );

test( "a 422 that carries a detail shows the detail; a body without a usable detail falls back to the plain line", () => {
  const detail = "Not started: this server cannot launch /var/planning-is-prompting/x.sh (No such file or directory).";
  const body = ( o: unknown ) => new ApiError( 422, "/u", JSON.stringify( o ) );
  assert.equal( runNowFailureText( body( { status : "refused", reason : "launch_failed", detail } ) ), detail );
  assert.match( runNowFailureText( body( { detail : "" } ) ), /cannot be run by hand/ );
  assert.match( runNowFailureText( body( { detail : 5 } ) ), /cannot be run by hand/ );
  assert.match( runNowFailureText( new ApiError( 422, "/u", "{not json" ) ), /cannot be run by hand/ );
} );

test( "each Run now refusal gets its own plain sentence", async () => {
  const err = ( status: number ) => new ApiError( status, "/u", "m" );
  assert.match( runNowFailureText( err( 403 ) ), /Only Rick's login/ );
  assert.match( runNowFailureText( err( 404 ) ), /does not know/ );
  assert.match( runNowFailureText( err( 409 ) ), /run lock is held/ );
  assert.match( runNowFailureText( err( 422 ) ), /cannot be run by hand/ );
  assert.equal( runNowFailureText( err( 500 ) ), "Run now failed (HTTP 500)." );
  assert.equal( runNowFailureText( new Error( "x" ) ), "Run now failed: Error: x" );
  const { root } = await mounted( harness( { post : async () => { throw err( 409 ); } } ) );
  const dup = root.querySelector( "[data-job=duplicate-check]" ) as HTMLElement;
  ( dup.querySelector( "[data-testid=jobs-run-now]" ) as HTMLElement ).click(); await flush();
  assert.match( ( dup.querySelector( "[data-testid=jobs-run-status]" ) as HTMLElement ).textContent as string, /run lock is held/ );
} );

test( "the Background Jobs toolbar icon is 🔁, is used by no other toggle, and the section header shows the same icon (row 288165d6)", async () => {
  const mine   = SECTION_TOGGLES.find( ( t ) => t.sectionId === "background-jobs-pane" );
  assert.equal( mine?.icon, "🔁" );
  const others = SECTION_TOGGLES.filter( ( t ) => t.sectionId !== "background-jobs-pane" );
  assert.ok( others.length > 15, "the other toggles were not found: the uniqueness check would prove nothing" );
  assert.deepEqual( others.filter( ( t ) => t.icon === mine?.icon ), [] );
  const { root } = await mounted( harness() );
  assert.ok( ( root.querySelector( "[data-testid=multiplexer-background-jobs-header]" )!.textContent as string ).startsWith( "🔁" ) );
} );

test( "the accordion ends with the switched-off line when the server sends one, and with nothing extra when it does not (row 4aa0ba1b)", () => {
  const plain = drawAll();
  assert.ok( plain.querySelector( "[data-testid=background-jobs-off-line]" ) === null, "the off-line is absent" );
  const off = drawAll( { ...clone( FIXTURE ), reporting_off : 8, reporting_off_line : "8 jobs have reporting switched off" } );
  const last = off.lastElementChild as HTMLElement;
  assert.equal( last.getAttribute( "data-testid" ), "background-jobs-off-line" );
  assert.equal( last.textContent, "8 jobs have reporting switched off" );
  assert.equal( off.children.length, 25 );   // header row + 23 jobs + the off line
  const none = drawAll( { ...clone( FIXTURE ), reporting_off : 0, reporting_off_line : null } );
  assert.equal( none.children.length, 24 );   // header row + 23 jobs
} );

// ─── Sort by name and by health, header row (row 4b807ffd) ─────────────────

const mkJob = ( name: string, state: JobEntry[ "state" ], target: string | null = null, running = false ): JobEntry =>
  ( { ...find( "duplicate-check" ), job : name, title : name, target, state, running } );
const names = ( jobs: JobEntry[] ) => jobs.map( ( j ) => `${ j.title }${ j.target === null ? "" : `/${ j.target }` }` );

test( "SORT_ORDERS names the three header orders, one entry each, name first", () => {
  assert.deepEqual( F.SORT_ORDERS.map( ( o ) => [ o.id, o.label ] ), [ [ "name", "Service" ], [ "health", "Status" ], [ "last-run", "Last run" ] ] );
} );

test( "sort by name runs A to Z and Z to A, ignores a running job, breaks a tie by target, and leaves its input alone", () => {
  const input = [ mkJob( "beta", "healthy" ), mkJob( "alpha", "unknown", "y" ), mkJob( "alpha", "failing", "x", true ), mkJob( "Gamma", "silent" ), mkJob( "alpha", "healthy" ) ];
  const before = names( input );
  assert.deepEqual( names( F.sortJobs( input, { id : "name", direction : "asc" } ) ), [ "alpha", "alpha/x", "alpha/y", "beta", "Gamma" ] );
  assert.deepEqual( names( F.sortJobs( input, { id : "name", direction : "desc" } ) ), [ "Gamma", "beta", "alpha/y", "alpha/x", "alpha" ] );
  assert.deepEqual( names( input ), before );
} );

test( "the name comparator breaks a title tie by target with either side missing its target", () => {
  const [ named, bare ] = [ mkJob( "same", "healthy", "x" ), mkJob( "same", "healthy" ) ];
  const byName = ( F.SORT_ORDERS.find( ( o ) => o.id === "name" ) as F.SortOrder ).compare;
  assert.ok( byName( named, bare ) > 0 );
  assert.ok( byName( bare, named ) < 0 );
} );

test( "sort by health runs healthy, behind, silent, unknown, failing (failing most urgent, Rick 11 Nov), and descending is the exact reverse of the states", () => {
  const input = [ mkJob( "u", "unknown" ), mkJob( "h", "healthy" ), mkJob( "s", "silent" ), mkJob( "f", "failing" ), mkJob( "b", "behind" ), mkJob( "run", "silent", null, true ) ];
  assert.deepEqual( F.sortJobs( input, { id : "health", direction : "asc" } ).map( ( j ) => j.state ), [ "healthy", "behind", "silent", "silent", "unknown", "failing" ] );
  assert.deepEqual( F.sortJobs( input, { id : "health", direction : "desc" } ).map( ( j ) => j.state ), [ "failing", "unknown", "silent", "silent", "behind", "healthy" ] );
  assert.equal( F.sortJobs( input, { id : "health", direction : "asc" } )[ 2 ]!.job, "run", "a running silent job sorts first among silent ones: ties fall back to the default order" );
} );

test( "sortJobs refuses a sort id it does not know, and null gives the default order", () => {
  assert.throws( () => F.sortJobs( [ mkJob( "a", "healthy" ) ], { id : "nope", direction : "asc" } ), /unknown sort order: nope/ );
  const input = [ mkJob( "b", "unknown" ), mkJob( "a", "healthy" ) ];
  assert.deepEqual( names( F.sortJobs( input, F.DEFAULT_SORT ) ), [ "a", "b" ] );
} );

test( "nextSort: a new column ascends, the same column descends, then back to the default", () => {
  assert.deepEqual( F.nextSort( F.DEFAULT_SORT, "name" ), { id : "name", direction : "asc" } );
  assert.deepEqual( F.nextSort( { id : "name", direction : "asc" }, "name" ), { id : "name", direction : "desc" } );
  assert.deepEqual( F.nextSort( { id : "name", direction : "desc" }, "name" ), F.DEFAULT_SORT );
  assert.deepEqual( F.nextSort( { id : "name", direction : "desc" }, "health" ), { id : "health", direction : "asc" } );
} );

test( "the accordion draws a header row naming every column, sorts on a heading click, and keeps the pick across a refresh", () => {
  const mount = byId( "jobs-accordion" );
  const summary = { ...clone( FIXTURE ), jobs : [ mkJob( "bb", "unknown" ), mkJob( "aa", "failing" ), mkJob( "cc", "healthy" ) ] } as JobsSummary;
  renderAccordion( document, mount, summary, NO_ACTIONS );
  const heads = () => Array.from( mount.querySelectorAll( "[data-testid=jobs-header] [role=columnheader]" ) ).map( ( h ) => h.textContent );
  assert.deepEqual( heads(), [ "", "", "Service", "Status", "Last run", "Last finished", "Scan", "Fix", "Clears" ] );
  const order = () => Array.from( mount.querySelectorAll( ":scope > [data-testid=jobs-item]" ) ).map( ( i ) => i.getAttribute( "data-job" ) );
  assert.deepEqual( order(), [ "aa", "bb", "cc" ], "default order is service name A to Z" );
  ( mount.querySelector( "[data-testid=jobs-sort-name]" ) as HTMLElement ).click();
  assert.deepEqual( order(), [ "aa", "bb", "cc" ] );
  assert.equal( mount.querySelector( "[data-testid=jobs-sort-name]" )!.textContent, "Service ▲" );
  assert.equal( mount.querySelector( "[aria-sort=ascending]" )!.querySelector( "button" )!.getAttribute( "data-testid" ), "jobs-sort-name" );
  ( mount.querySelector( "[data-testid=jobs-sort-name]" ) as HTMLElement ).click();
  assert.deepEqual( order(), [ "cc", "bb", "aa" ] );
  assert.equal( mount.querySelector( "[data-testid=jobs-sort-name]" )!.textContent, "Service ▼" );
  renderAccordion( document, mount, summary, NO_ACTIONS );                       // a poll redraws: the pick stays
  assert.deepEqual( order(), [ "cc", "bb", "aa" ] );
  ( mount.querySelector( "[data-testid=jobs-sort-name]" ) as HTMLElement ).click();   // third click: back to default
  assert.deepEqual( order(), [ "aa", "bb", "cc" ] );
  ( mount.querySelector( "[data-testid=jobs-sort-health]" ) as HTMLElement ).click();
  ( mount.querySelector( "[data-testid=jobs-sort-health]" ) as HTMLElement ).click();
  assert.deepEqual( order(), [ "aa", "bb", "cc" ], "health descending: failing, unknown, healthy" );
} );

test( "the targets inside a panel follow the picked order too", () => {
  const parent = { ...mkJob( "p", "healthy" ), targets : [ mkJob( "t", "healthy", "b" ), mkJob( "t", "healthy", "a" ) ] };
  const item = renderJob( document, parent, TODAY, NO_ACTIONS, { id : "name", direction : "desc" } );
  assert.deepEqual( Array.from( item.querySelectorAll( ":scope > [data-testid=jobs-panel] > [data-testid=jobs-item]" ) ).map( ( i ) => i.getAttribute( "data-target" ) ), [ "b", "a" ] );
} );

test( "sort by last run goes oldest first ascending and newest first descending, a job that never ran or has an unreadable time at the oldest end", () => {
  const mk = ( name: string, at: string | null ): JobEntry => {
    const base = find( "duplicate-check" );
    return { ...base, job : name, title : name, target : null, state : "healthy", running : false,
      last_attempt : at === null ? null : { ...( base.last_attempt as NonNullable<JobEntry[ "last_attempt" ]> ), started_at : at } };
  };
  const input = [ mk( "new", "2026-11-09T12:00:00-05:00" ), mk( "none", null ), mk( "old", "2026-11-01T12:00:00-05:00" ), mk( "bad", "not a time" ), mk( "utc", "2026-11-09T18:00:00+00:00" ) ];
  assert.deepEqual( F.sortJobs( input, { id : "last-run", direction : "asc" } ).map( ( j ) => j.job ), [ "bad", "none", "old", "new", "utc" ] );   // 18:00Z is 13:00 in New York, an hour after new's 12:00, so the zone is compared, not the text
  assert.deepEqual( F.sortJobs( input, { id : "last-run", direction : "desc" } ).map( ( j ) => j.job ), [ "utc", "new", "old", "bad", "none" ] );
  assert.deepEqual( F.HEALTH_URGENCY, [ "healthy", "behind", "silent", "unknown", "failing" ] );
  assert.deepEqual( F.STATE_ORDER, [ "healthy", "behind", "failing", "silent", "unknown" ], "the default order keeps its own ranking" );
} );
