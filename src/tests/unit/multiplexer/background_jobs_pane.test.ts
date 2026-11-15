// Tests for the merged jobs list and its pane (rows d540113f, c80ef763), at full coverage.
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
import { renderAccordion, renderJob } from "../../../lupin_app/static/js/multiplexer/jobs/jobsRender";
import type { JobsActions } from "../../../lupin_app/static/js/multiplexer/jobs/jobsRender";
import { abstractMarkdown, mdLink, mdText } from "../../../lupin_app/static/js/multiplexer/jobs/abstractText";
import { CRON_CONFIRM_TEXT, CRON_DRIFT_TEXT, CRON_UNREADABLE_TEXT } from "../../../lupin_app/static/js/multiplexer/jobs/cronFormat";
import type { CronJobRow, CronJobsSummary } from "../../../lupin_app/static/js/multiplexer/jobs/cronFormat";
import { cronOnlyEntry, mergeJobs } from "../../../lupin_app/static/js/multiplexer/jobs/mergedRows";
import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
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

/** A fresh set of list actions each time: `open` is mutable state a test must not share. */
const mkActions = ( over: Partial<JobsActions> = {} ): JobsActions =>
  ( { canRun : true, runNow : async () => "ok", canFlip : true, cronRows : [], requestFlip : () => {}, open : new Set<string>(), ...over } );
const cronRow = ( job: string, over: Partial<CronJobRow> = {} ): CronJobRow => ( {
  job, title : `Title of ${ job }`, schedule : "*/5 * * * *", key : `key-of-${ job }`,
  enabled : true, honoured : true, drift : false, last_changed_by : null, last_changed_at : null, ...over,
} );

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

// ── mergeJobs ───────────────────────────────────────────────────────────────

test( "mergeJobs attaches each job's switch, adds an entry for a switch the summary leaves out, and changes neither input (row c80ef763)", () => {
  const jobs   = [ find( "duplicate-check" ), find( "wiki-librarian" ) ];
  const rows   = [ cronRow( "wiki-librarian" ), cronRow( "duplicate-check", { enabled : false } ), cronRow( "reporting-off" ) ];
  const before = JSON.stringify( [ jobs, rows ] );
  const merged = mergeJobs( jobs, rows );
  assert.deepEqual( merged.map( ( j ) => j.job ), [ "duplicate-check", "wiki-librarian", "reporting-off" ], "the summary's order, then the switches no job names" );
  assert.equal( merged[ 0 ]!.cron!.enabled, false );
  assert.equal( merged[ 1 ]!.cron!.job, "wiki-librarian" );
  assert.equal( merged[ 2 ]!.cron_only, true );
  assert.equal( merged[ 2 ]!.title, "Title of reporting-off" );
  assert.equal( merged[ 0 ]!.cron_only, undefined );
  assert.equal( JSON.stringify( [ jobs, rows ] ), before, "inputs untouched" );
  assert.equal( jobs[ 0 ]!.cron, undefined );
  assert.equal( mergeJobs( jobs, [] )[ 0 ]!.cron, null, "no switch list: the job carries null" );
  assert.deepEqual( mergeJobs( [], [] ), [] );
  assert.equal( mergeJobs( [], rows ).length, 3 );
} );

test( "a switch the summary leaves out is drawn as a NOT REPORTING row with its switch on line 2", () => {
  const entry = cronOnlyEntry( cronRow( "reporting-off", { enabled : false } ) );
  assert.equal( F.badgeText( entry ), "NOT REPORTING" );
  assert.equal( F.lastRunText( entry, TODAY ), "not reported" );
  const item = renderJob( document, entry, TODAY, mkActions( { cronRows : [ entry.cron! ] } ) );
  assert.equal( item.querySelector( "[data-testid=jobs-last-finished]" )!.textContent, "" );
  assert.equal( item.querySelector( "[data-testid=jobs-line2] [data-testid=cron-state]" )!.textContent, "OFF" );
  assert.equal( item.querySelectorAll( "[data-testid=jobs-fig-scan], [data-testid=jobs-fig-fix], [data-testid=jobs-fig-clears]" ).length, 0 );
  assert.equal( item.querySelector( "[data-testid=jobs-line3]" )!.textContent, "Nothing to run by hand, and no targets." );
} );

// ── jobsRender: the line ────────────────────────────────────────────────────

function drawAll( summary: JobsSummary = FIXTURE, actions: JobsActions = mkActions() ): HTMLElement {
  renderAccordion( document, byId( "jobs-accordion" ), summary, actions );
  return byId( "jobs-accordion" );
}

test( "the list draws all 23 jobs by service name A to Z, each with its second and third lines hidden", () => {
  const mount = drawAll();
  const top   = ( [ ...mount.children ] as HTMLElement[] ).filter( ( c ) => c.getAttribute( "data-testid" ) === "jobs-item" );   // the header row is the first child
  assert.equal( top.length, 23 );
  const titles = top.map( ( t ) => ( t.querySelector( "[data-testid=jobs-title]" ) as HTMLElement ).textContent as string );
  assert.deepEqual( titles.slice( 0, 2 ), [ "Commons archival", "Context tick" ] );
  assert.deepEqual( titles, [ ...titles ].sort( ( a, b ) => a.localeCompare( b ) ) );
  assert.equal( mount.querySelectorAll( "[data-testid=jobs-disclose]" ).length, 23 );
  for ( const toggle of mount.querySelectorAll( "[data-testid=jobs-disclose]" ) ) assert.equal( toggle.getAttribute( "aria-expanded" ), "false" );
  for ( const panel of mount.querySelectorAll( "[data-testid=jobs-panel]" ) ) assert.equal( ( panel as HTMLElement ).hidden, true );
  assert.equal( mount.querySelectorAll( "[data-job=side-services]" ).length, 3, "the side-services job and its two target lines" );
  assert.equal( mount.querySelectorAll( "[data-testid=jobs-item] [data-testid=jobs-item]" ).length, 0, "no job is nested inside another's row any more" );
} );

test( "the duplicate check's first line holds Service, Status, Last run and Last finished, and no Scan, Fix or Clears (row c80ef763)", () => {
  const item = drawAll().querySelector( "[data-job=duplicate-check]" ) as HTMLElement;
  const line = item.querySelector( "[data-testid=jobs-line]" ) as HTMLElement;
  const text = ( id: string ) => ( line.querySelector( `[data-testid=${ id }]` ) as HTMLElement ).textContent;
  assert.equal( text( "jobs-title" ), "Duplicate check" );
  assert.equal( text( "jobs-badge" ), "FAILING · BEHIND" );
  assert.equal( text( "jobs-last-run" ), "19:31 failed (stale_branch)" );
  assert.equal( text( "jobs-last-finished" ), "11-06 19:06" );
  assert.equal( line.querySelectorAll( "[data-testid=jobs-scan-cell], [data-testid=jobs-fix-cell], [data-testid=jobs-clears-cell]" ).length, 0 );
  assert.ok( !( line.textContent as string ).includes( "2,124" ), "no scan figure on the first line" );
  assert.ok( !( line.textContent as string ).includes( "unfiled" ), "no fix figure on the first line" );
  assert.ok( line.querySelector( ".jobs-caret" ) === null, "the expand caret is gone" );
  assert.equal( line.querySelectorAll( "button" ).length, 1, "the ⋯ is the only button on the line" );
  assert.equal( line.querySelector( "[data-testid=jobs-disclose]" )!.textContent, "⋯" );
  assert.equal( line.querySelector( "[data-testid=jobs-abstract]" )!.textContent, "📋" );
} );

test( "the ⋯ opens and closes lines 2 and 3, rows are independent, and an open row stays open across a redraw", () => {
  const actions = mkActions();
  const mount   = drawAll( FIXTURE, actions );
  const toggles = [ ...mount.querySelectorAll( "[data-testid=jobs-disclose]" ) ] as HTMLElement[];
  const panelOf = ( t: HTMLElement ) => document.getElementById( t.getAttribute( "aria-controls" ) as string ) as HTMLElement;
  toggles[ 0 ]!.click(); toggles[ 1 ]!.click();
  assert.deepEqual( [ toggles[ 0 ]!.getAttribute( "aria-expanded" ), panelOf( toggles[ 0 ]! ).hidden, panelOf( toggles[ 1 ]! ).hidden ], [ "true", false, false ] );
  assert.equal( panelOf( toggles[ 0 ]! ).querySelectorAll( "[data-testid=jobs-line2], [data-testid=jobs-line3]" ).length, 2, "a second and a third line" );
  toggles[ 0 ]!.click();
  assert.deepEqual( [ toggles[ 0 ]!.getAttribute( "aria-expanded" ), panelOf( toggles[ 0 ]! ).hidden, panelOf( toggles[ 1 ]! ).hidden ], [ "false", true, false ] );
  assert.equal( new Set( [ ...mount.querySelectorAll( "[id]" ) ].map( ( e ) => e.id ) ).size, mount.querySelectorAll( "[id]" ).length, "every id is unique" );
  assert.equal( actions.open.size, 1 );
  renderAccordion( document, mount, FIXTURE, actions );                              // a poll redraws: the second row stays open
  const again = [ ...mount.querySelectorAll( "[data-testid=jobs-disclose]" ) ] as HTMLElement[];
  assert.deepEqual( again.map( ( t ) => t.getAttribute( "aria-expanded" ) ).slice( 0, 3 ), [ "false", "true", "false" ] );
  assert.equal( panelOf( again[ 1 ]! ).hidden, false );
} );

// ── jobsRender: line 2 (figures and switch) and line 3 (Run now and targets) ─

test( "line 2 carries the Scan, Fix and Clears figures that apply, labelled", () => {
  const item = drawAll().querySelector( "[data-job=duplicate-check]" ) as HTMLElement;
  const fig  = ( id: string ) => ( item.querySelector( `[data-testid=jobs-line2] [data-testid=${ id }]` ) as HTMLElement ).textContent;
  assert.equal( fig( "jobs-fig-scan" ), "Scan: 2,124 ▲" );
  assert.equal( fig( "jobs-fig-fix" ), "Fix: unfiled 107 ▲" );
  assert.equal( fig( "jobs-fig-clears" ), "Clears: never at this rate" );
  const reuse = renderJob( document, find( "reuse-behaviour" ), TODAY, mkActions() );
  assert.equal( reuse.querySelectorAll( "[data-testid=jobs-line2] .jobs-fig" ).length, 0, "debts that do not apply are absent" );
  const noClears = find( "duplicate-check" ); noClears.scan_debt!.clears_in = null;
  assert.equal( renderJob( document, noClears, TODAY, mkActions() ).querySelectorAll( "[data-testid=jobs-fig-clears]" ).length, 0 );
} );

test( "line 2 carries the job's switch: schedule, state, who changed it and when, whether the job reads it, and the flip button", () => {
  const row    = cronRow( "duplicate-check", { last_changed_by : "rick@example.test", last_changed_at : "2026-11-13T21:05:44-05:00" } );
  const [ j ]  = mergeJobs( [ find( "duplicate-check" ) ], [ row ] );
  const item   = renderJob( document, j!, TODAY, mkActions( { cronRows : [ row ] } ) );
  const sw     = item.querySelector( "[data-testid=jobs-line2] [data-testid=cron-item]" ) as HTMLElement;
  const text   = ( id: string ) => ( sw.querySelector( `[data-testid=${ id }]` ) as HTMLElement ).textContent;
  assert.equal( sw.getAttribute( "data-job" ), "duplicate-check" );
  assert.equal( text( "cron-schedule" ), "*/5 * * * *" );
  assert.equal( text( "cron-state" ), "ON" );
  assert.equal( text( "cron-changed" ), "rick@example.test, 2026-11-13 21:05" );
  assert.equal( text( "cron-honoured" ), "reads its switch" );
  assert.equal( text( "cron-flip" ), "Turn off" );
  assert.equal( ( sw.querySelector( "[data-testid=cron-error]" ) as HTMLElement ).hidden, true );
  assert.equal( sw.querySelectorAll( "[data-testid=cron-drift], [data-testid=cron-unreadable], [data-testid=cron-inside]" ).length, 0 );
  const bare = renderJob( document, find( "duplicate-check" ), TODAY, mkActions() );
  assert.equal( bare.querySelectorAll( "[data-testid=cron-item]" ).length, 0, "a job without a switch row shows none" );
} );

test( "the switch says drift, unreadable, and off-while-the-host-is-off, and its button is disabled where nothing can be flipped", () => {
  const rows   = [ cronRow( "host", { enabled : false } ), cronRow( "duplicate-check", { drift : true, inside : "host", reads : "tick" } ),
                   cronRow( "wiki-librarian", { enabled : null } ), cronRow( "disk-report", { honoured : false } ), cronRow( "vector-refresh", { enabled : false } ) ];
  const merged = mergeJobs( [ find( "duplicate-check" ), find( "wiki-librarian" ), find( "disk-report" ), find( "vector-refresh" ) ], rows );
  const draw   = ( name: string, canFlip = true ) => renderJob( document, merged.find( ( j ) => j.job === name )!, TODAY, mkActions( { cronRows : rows, canFlip } ) );
  const dup    = draw( "duplicate-check" );
  assert.equal( dup.querySelector( "[data-testid=cron-drift]" )!.textContent, CRON_DRIFT_TEXT );
  assert.equal( dup.querySelector( "[data-testid=cron-inside]" )!.textContent, "off while host is off" );
  assert.equal( dup.querySelector( "[data-testid=cron-honoured]" )!.textContent, "reads its switch every tick" );
  const broken = draw( "wiki-librarian" );
  assert.equal( broken.querySelector( "[data-testid=cron-unreadable]" )!.textContent, CRON_UNREADABLE_TEXT );
  assert.ok( broken.querySelector( "[data-testid=cron-item]" )!.classList.contains( "cron-unreadable" ) );
  assert.equal( ( broken.querySelector( "[data-testid=cron-flip]" ) as HTMLButtonElement ).disabled, true, "no readable key: nothing to flip" );
  assert.equal( ( draw( "disk-report" ).querySelector( "[data-testid=cron-flip]" ) as HTMLButtonElement ).disabled, true, "nothing reads it yet" );
  assert.equal( ( dup.querySelector( "[data-testid=cron-flip]" ) as HTMLButtonElement ).disabled, false );
  const off = draw( "vector-refresh" );
  assert.equal( off.querySelector( "[data-testid=cron-flip]" )!.textContent, "Turn on" );
  assert.equal( ( draw( "duplicate-check", false ).querySelector( "[data-testid=cron-flip]" ) as HTMLButtonElement ).disabled, true, "not an administrator" );
} );

test( "a click on the flip button hands the row, its error span and the button to the list's requestFlip", () => {
  const seen: Array<[ string, string, string ]> = [];
  const row  = cronRow( "duplicate-check" );
  const [ j ] = mergeJobs( [ find( "duplicate-check" ) ], [ row ] );
  const item = renderJob( document, j!, TODAY, mkActions( { cronRows : [ row ], requestFlip : ( r, note, button ) => seen.push( [ r.job, note.getAttribute( "data-testid" ) as string, button.getAttribute( "data-testid" ) as string ] ) } ) );
  ( item.querySelector( "[data-testid=cron-flip]" ) as HTMLElement ).click();
  assert.deepEqual( seen, [ [ "duplicate-check", "cron-error", "cron-flip" ] ] );
} );

test( "line 3 carries Run now, and a job with neither Run now nor targets says so", () => {
  const dup = renderJob( document, find( "duplicate-check" ), TODAY, mkActions() );
  assert.equal( dup.querySelectorAll( "[data-testid=jobs-line3] [data-testid=jobs-run-now]" ).length, 1 );
  const live = renderJob( document, find( "fleet-arbiter" ), TODAY, mkActions() );
  assert.equal( live.querySelector( "[data-testid=jobs-line3]" )!.textContent, "Nothing to run by hand, and no targets." );
  assert.ok( live.querySelector( "[data-testid=jobs-liveness]" ) === null, "the liveness text is in the abstract, not the list" );
} );

test( "targets draw as compact lines inside line 3, each with its own status and 📋, in the picked order", () => {
  const item = renderJob( document, find( "worktree-census" ), TODAY, mkActions( { canRun : false } ) );
  const targets = [ ...item.querySelectorAll( "[data-testid=jobs-line3] [data-testid=jobs-target]" ) ] as HTMLElement[];
  assert.deepEqual( targets.map( ( n ) => n.getAttribute( "data-target" ) ), [ "cosa-voice", "lupin", "planning-is-prompting" ] );
  const lupin = targets.find( ( n ) => n.getAttribute( "data-target" ) === "lupin" ) as HTMLElement;
  assert.equal( lupin.querySelector( "[data-testid=jobs-target-title]" )!.textContent, "Worktree census (lupin)" );
  assert.ok( ( lupin.querySelector( "[data-testid=jobs-target-badge]" )!.textContent as string ).length > 0 );
  assert.ok( ( lupin.querySelector( "[data-testid=jobs-target-last-run]" )!.textContent as string ).length > 0 );
  assert.equal( lupin.getAttribute( "data-state" ), find( "worktree-census" ).targets.find( ( t ) => t.target === "lupin" )!.state );
  assert.equal( lupin.querySelectorAll( "[data-testid=jobs-target-abstract]" ).length, 1 );
  const ids = [ ...item.querySelectorAll( "[id]" ) ].map( ( e ) => e.id );
  assert.equal( new Set( ids ).size, ids.length );
  const parent = { ...mkJob( "p", "healthy" ), targets : [ mkJob( "t", "healthy", "b" ), mkJob( "t", "healthy", "a" ) ] };
  const sorted = renderJob( document, parent, TODAY, mkActions(), { id : "name", direction : "desc" } );
  assert.deepEqual( Array.from( sorted.querySelectorAll( "[data-testid=jobs-target]" ) ).map( ( i ) => i.getAttribute( "data-target" ) ), [ "b", "a" ] );
  const plain = { ...mkJob( "q", "healthy" ), targets : [ { ...mkJob( "t", "healthy" ), target : null } ] };
  assert.equal( renderJob( document, plain, TODAY, mkActions() ).querySelector( "[data-testid=jobs-target-title]" )!.textContent, "t", "a target with no name shows the title alone" );
} );

// ── jobsRender: the 📋 ──────────────────────────────────────────────────────

test( "every row, and every target, carries a 📋 whose raw data-abstract is the job's abstract; the multiplexer's handlers do the opening", () => {
  const mount = drawAll();
  const dup   = mount.querySelector( "[data-job=duplicate-check]" ) as HTMLElement;
  const mark  = dup.querySelector( "[data-testid=jobs-abstract]" ) as HTMLElement;
  assert.ok( mark.classList.contains( "abstract-indicator" ), "the class both clients' delegated handlers listen for" );
  assert.equal( mark.getAttribute( "data-abstract" ), abstractMarkdown( find( "duplicate-check" ), TODAY ) );
  assert.equal( mark.getAttribute( "role" ), "button" );
  assert.equal( mark.getAttribute( "tabindex" ), "0" );
  assert.equal( mount.querySelectorAll( "[data-testid=jobs-abstract]" ).length, 23 );
  assert.equal( mount.querySelectorAll( "[data-testid=jobs-item] [data-testid=jobs-abstract]" ).length, 23 );
  assert.equal( mount.querySelectorAll( "[data-testid=jobs-target-abstract]" ).length, 8, "every target line in the 23-job fixture has its own 📋" );
} );

test( "a job that carries a target name draws it in its title and gives its row an id that names it (a type-level case: the summary nests targets)", () => {
  const item = renderJob( document, { ...find( "duplicate-check" ), target : "x/y" }, TODAY, mkActions() );
  assert.equal( item.querySelector( "[data-testid=jobs-title]" )!.textContent, "Duplicate check (x/y)" );
  assert.equal( item.querySelector( "[data-testid=jobs-panel]" )!.id, "jobs-duplicate-check-x-y-panel" );
  assert.equal( item.getAttribute( "data-target" ), "x/y" );
} );

test( "the multiplexer writes the abstract raw, so a percent sign and a newline are kept as typed", () => {
  const job = find( "duplicate-check" );
  job.reasons[ 0 ]!.text = "100% done\nsecond line";
  const attr = renderJob( document, job, TODAY, mkActions() ).querySelector( "[data-testid=jobs-abstract]" )!.getAttribute( "data-abstract" ) as string;
  assert.ok( attr.includes( "100% done\nsecond line" ) );
  assert.equal( attr, abstractMarkdown( job, TODAY ) );
} );

// ── abstractMarkdown ────────────────────────────────────────────────────────

const headings = ( md: string ) => [ ...md.matchAll( /^## (.+)$/gm ) ].map( ( m ) => m[ 1 ] );

test( "the duplicate check's abstract carries every block the expanded panel used to show, in that order", () => {
  const md = abstractMarkdown( find( "duplicate-check" ), TODAY );
  assert.ok( md.startsWith( "# Duplicate check\n" ) );
  assert.deepEqual( headings( md ), [ "Reasons", "Last attempts", "Scan debt", "Fix debt", "Schedule", "Evidence", "People", "Not reported" ] );
  assert.match( md, /- Count: 2,124 definitions ▲/ );
  assert.match( md, /- Clears in: never at this rate/ );
  assert.match( md, /- Unfiled: 107 ▲/ );
  assert.match( md, /- Own mark: job:duplicate-check/ );
  assert.match( md, /- Grace: 30 minutes/ );
  assert.match( md, /- Tells Rick: every 1 h/ );
  assert.match( md, /- Owner: cheech/ );
  assert.match( md, /\(\/app\/duplicate-check\)/ );
  assert.match( md, /\[Ledger line: io\/duplicate-check-daily\/runs\.jsonl:9\]\(\/app\/docs\?path=lupin\/io\/duplicate-check-daily\/runs\.jsonl\)/ );
  assert.match( md, /\(\/app\/tasks\?correlation_key=job:duplicate-check\)/ );
  assert.match( md, /^\d\. .*MISSED \(due, no run\)$/m );
  assert.equal( ( md.match( /^\d\. /gm ) ?? [] ).length, 5, "the five last attempts" );
  assert.match( md, /never checked/ );
} );

test( "a liveness job has no last attempts or scan debt; a job with no debts has neither block; a missing figure says not reported", () => {
  const live = abstractMarkdown( find( "fleet-arbiter" ), TODAY );
  assert.deepEqual( headings( live ).filter( ( h ) => h === "Last attempts" || h === "Scan debt" ), [] );
  assert.match( live, /- Liveness: systemd unit lupin-arbiter-app\.service/ );
  const reuse = headings( abstractMarkdown( find( "reuse-behaviour" ), TODAY ) );
  assert.equal( reuse.includes( "Scan debt" ) || reuse.includes( "Fix debt" ), false );
  const j = find( "duplicate-check" ); j.scan_debt = null; j.fix_debt = null; j.strip = [];
  const md = abstractMarkdown( j, TODAY );
  assert.match( md, /## Scan debt\n\nnot reported/ );
  assert.match( md, /## Fix debt\n\nnot reported/ );
  assert.match( md, /## Last attempts\n\nnot reported/ );
  const k = find( "duplicate-check" ); k.scan_debt!.unit = null; k.scan_debt!.count = null; k.scan_debt!.points = [];
  assert.match( abstractMarkdown( k, TODAY ), /- Count: not reported\n/ );
  k.scan_debt!.count = 7;
  assert.match( abstractMarkdown( k, TODAY ), /- Count: 7\n/ );
  assert.match( abstractMarkdown( find( "disk-report" ), TODAY ), /- Named, not acted on: 20/ );
  const flat = find( "duplicate-check" ); flat.fix_debt!.points = [];
  assert.match( abstractMarkdown( flat, TODAY ), /- Unfiled: 107\n/ );
  flat.fix_debt!.own_mark = null; flat.fix_debt!.store_href = null;
  const md2 = abstractMarkdown( flat, TODAY );
  assert.match( md2, /- Own mark: not reported/ );
  assert.equal( md2.includes( "Rows in the task store" ), false );
} );

test( "reasons: the empty case, an unknown reason, and the machine-was-off clause", () => {
  assert.match( abstractMarkdown( find( "vector-refresh" ), TODAY ), /## Reasons\n\nNo rule is true: nothing to report\./ );
  assert.match( abstractMarkdown( find( "doc-parity-tick" ), TODAY ), /- Never reported/ );
  assert.match( abstractMarkdown( find( "context-tick" ), TODAY ), /- Missed while the machine was off\./ );
} );

test( "schedule: unverified, unscheduled, and unreported say so; the people block names the owner, the audience and linked rows", () => {
  assert.match( abstractMarkdown( find( "hook-link-tick" ), TODAY ), /- Check: schedule unverified: the installed schedule could not be read/ );
  assert.equal( abstractMarkdown( find( "doc-parity-tick" ), TODAY ).includes( "schedule unverified" ), false );
  const pokes = abstractMarkdown( find( "pokes" ), TODAY );
  assert.match( pokes, /- Runs: unscheduled/ );
  assert.match( pokes, /- Last due: not reported/ );
  assert.match( pokes, /- Told: the owner/ );
  assert.match( pokes, /## Evidence\n\nnot reported/ );
  const named = find( "duplicate-check" ); named.audience = [ "rick", "maria" ];
  assert.match( abstractMarkdown( named, TODAY ), /- Told: rick, maria/ );
  const some = abstractMarkdown( { ...find( "duplicate-check" ), schedule : { entries : [ "0 3 * * *", "0 4 * * *" ], last_due : null, next_due : null, grace_minutes : null, grace_seconds : null } }, TODAY );
  assert.ok( some.includes( "- Runs: 0 3 \\* \\* \\*; 0 4 \\* \\* \\*" ), "the stars are escaped so markdown shows them as written" );
  assert.equal( abstractMarkdown( { ...find( "duplicate-check" ), target : "lupin" }, TODAY ).split( "\n" )[ 0 ], "# Duplicate check (lupin)" );
} );

test( "the abstract never lets job-writer text act as markdown, and only a path on this server becomes a link", () => {
  assert.equal( mdText( "a*b_c`d[e]f<g>#h|i~j\\k{l}" ), "a\\*b\\_c\\`d\\[e\\]f\\<g\\>\\#h\\|i\\~j\\\\k\\{l\\}" );
  assert.equal( mdLink( "/app/docs?path=a b(c)", "x [y]" ), "[x \\[y\\]](/app/docs?path=a%20b%28c%29)" );
  assert.equal( mdLink( "javascript:alert(1)", "x" ), "x" );
  assert.equal( mdLink( null, "a*b" ), "a\\*b" );
  const j = find( "duplicate-check" );
  j.title = "<img src=x onerror=alert(1)>";
  j.reasons[ 0 ]!.text = "<script>alert(2)</script>";
  j.detail_link = "javascript:alert(1)";
  j.evidence[ 0 ]!.href = "https://evil.example/x";
  j.rows[ 0 ]!.href = "//evil.example/y";
  j.fix_debt!.store_href = "javascript:void(0)";
  const md = abstractMarkdown( j, TODAY );
  assert.ok( md.startsWith( "# \\<img src=x onerror=alert(1)\\>" ) );
  assert.equal( md.includes( "<script>" ), false );
  assert.equal( md.includes( "](javascript" ) || md.includes( "](http" ) || md.includes( "](//" ), false );
  assert.equal( md.includes( "Open the detail page" ), false );
  assert.equal( md.includes( "Rows in the task store" ), false );
  assert.match( md, /Ledger line: io\/duplicate-check-daily\/runs\.jsonl:9/ );
} );

// ── jobsRender: Run now ─────────────────────────────────────────────────────

test( "a caller who is not the operator sees no Run now button anywhere", () => {
  const item = renderJob( document, find( "worktree-census" ), TODAY, mkActions( { canRun : false } ) );
  assert.equal( item.querySelectorAll( "[data-testid=jobs-run-now]" ).length, 0 );
  assert.equal( item.querySelectorAll( "[data-testid=jobs-target]" ).length, 3, "its three targets are still drawn" );
  const mount = byId( "jobs-accordion" );
  renderAccordion( document, mount, { ...clone( FIXTURE ), caller_is_operator : false }, mkActions( { canRun : false } ) );
  assert.equal( mount.querySelectorAll( "[data-testid=jobs-run-now]" ).length, 0 );
  renderAccordion( document, mount, FIXTURE, mkActions() );
  assert.equal( mount.querySelectorAll( "[data-testid=jobs-run-now]" ).length > 0, true, "positive control: the operator does see buttons" );
} );

test( "Run now disables the button while it runs, prints the outcome, and reports a rejected promise", async () => {
  let release!: ( s: string ) => void;
  const calls: string[] = [];
  const actions = mkActions( { runNow : ( job: JobEntry ) => { calls.push( job.job ); return new Promise<string>( ( r ) => { release = r; } ); } } );
  const item = renderJob( document, find( "duplicate-check" ), TODAY, actions );
  const btn  = item.querySelector( "[data-testid=jobs-run-now]" ) as HTMLButtonElement;
  const out  = item.querySelector( "[data-testid=jobs-run-status]" ) as HTMLElement;
  btn.click();
  assert.deepEqual( [ btn.disabled, out.textContent, calls ], [ true, "Starting…", [ "duplicate-check" ] ] );
  release( "Started." ); await flush();
  assert.deepEqual( [ btn.disabled, out.textContent ], [ false, "Started." ] );
  const bad  = renderJob( document, find( "duplicate-check" ), TODAY, mkActions( { runNow : () => Promise.reject( new Error( "boom" ) ) } ) );
  const btn2 = bad.querySelector( "[data-testid=jobs-run-now]" ) as HTMLButtonElement;
  btn2.click(); await flush();
  assert.deepEqual( [ btn2.disabled, ( bad.querySelector( "[data-testid=jobs-run-status]" ) as HTMLElement ).textContent ], [ false, "Run now failed: Error: boom" ] );
} );

// ── BackgroundJobsRenderer: the one list ────────────────────────────────────

const CRON = (): CronJobsSummary => ( {
  caller_is_admin : true,
  jobs : [
    cronRow( "duplicate-check", { last_changed_by : "rick@example.test", last_changed_at : "2026-11-13T21:05:44-05:00" } ),
    cronRow( "context-tick", { enabled : false } ),
    cronRow( "fleet-arbiter", { alarm : true, reads : "tick" } ),
    cronRow( "worktree-census", { inside : "fleet-arbiter" } ),
    cronRow( "reporting-off", { enabled : false } ),
  ],
} );

interface Harness {
  api    : BackgroundJobsApi;
  bus    : ReturnType<typeof createEventBusForTesting>;
  gets   : string[];
  posts  : string[];
  puts   : Array<{ path: string; body: unknown }>;
  timers : Array<() => void>;
  cleared: number[];
  answer : { summary: () => Promise<unknown>; cron: () => Promise<unknown>; put: ( path: string, body: unknown ) => Promise<unknown> };
}

function harness( over: { post?: BackgroundJobsApi[ "post" ] } = {} ): Harness {
  const h: Harness = { api : undefined as unknown as BackgroundJobsApi, bus : createEventBusForTesting(), gets : [], posts : [], puts : [], timers : [], cleared : [],
    answer : {
      summary : async () => clone( FIXTURE ),
      cron    : async () => CRON(),
      put     : async () => cronRow( "duplicate-check", { enabled : false } ),
    } };
  h.api = {
    get  : async <T,>( p: string ): Promise<T> => { h.gets.push( p ); return ( p === "/api/jobs/summary" ? await h.answer.summary() : await h.answer.cron() ) as T; },
    post : over.post ?? ( async <T,>( p: string ): Promise<T> => { h.posts.push( p ); return { job : "x", target : null, status : "started", trigger : "hand", pid : 4242, started_at : "2026-11-07T20:31:00-05:00" } as unknown as T; } ),
    put  : async <T,>( p: string, body: unknown ): Promise<T> => { h.puts.push( { path : p, body } ); return await h.answer.put( p, body ) as T; },
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
    api : h.api, eventBus : h.bus,
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

const rowOf   = ( job: string ) => document.querySelector( `[data-testid=jobs-item][data-job=${ job }]` ) as HTMLElement;
const flipOf  = ( job: string ) => rowOf( job ).querySelector( "[data-testid=cron-flip]" ) as HTMLButtonElement;
const stateOf = ( job: string ) => ( rowOf( job ).querySelector( "[data-testid=cron-state]" ) as HTMLElement ).textContent;
const countOf = () => ( document.querySelector( "[data-testid=multiplexer-background-jobs-count]" ) as HTMLElement ).textContent;
const errOf   = () => document.querySelector( "[data-testid=jobs-error]" ) as HTMLElement;
const emit    = ( h: Harness, payload: unknown ) => h.bus.emit( { type : "cron_job_switch_changed", payload, source : "t", ts : 0 } );

test( "the page declares #background-jobs-pane right after the epic board pane, with no Scheduled Jobs pane, sheet or toolbar toggle (row c80ef763)", () => {
  const html = readFileSync( HTML_PATH, "utf8" );
  assert.ok( html.indexOf( 'id="epic-board-pane"' ) < html.indexOf( 'id="background-jobs-pane"' ) );
  assert.ok( html.indexOf( 'id="background-jobs-pane"' ) < html.indexOf( 'id="jobs-pane"' ) );
  assert.equal( html.includes( 'id="cron-jobs-pane"' ), false );
  assert.equal( html.includes( "multiplexer/cron-jobs.css" ), false );
  assert.equal( SECTION_TOGGLES.some( ( t ) => t.sectionId === "cron-jobs-pane" ), false );
  assert.equal( html.includes( "multiplexer/background-jobs.css" ), true );
} );

test( "mounted: asks both doors, draws 23 jobs and the switch no job names, counts them with the off ones, titles the header with the state line, and polls", async () => {
  const h = harness();
  const { root } = await mounted( h );
  assert.deepEqual( [ ...h.gets ].sort(), [ "/api/cron-jobs", "/api/jobs/summary" ] );
  assert.equal( root.querySelectorAll( "[data-testid=jobs-accordion] > [data-testid=jobs-item]" ).length, 24 );
  assert.equal( rowOf( "reporting-off" ).querySelector( "[data-testid=jobs-badge]" )!.textContent, "NOT REPORTING" );
  assert.equal( countOf(), "24 (2 off)" );
  assert.match( root.querySelector( "[data-testid=multiplexer-background-jobs-header]" )!.getAttribute( "title" ) as string, /^23 jobs: 10 healthy, 3 failing, 1 silent, 9 unknown$/ );
  assert.equal( errOf().hidden, true );
  assert.equal( stateOf( "duplicate-check" ), "ON" );
  assert.equal( stateOf( "context-tick" ), "OFF" );
  assert.equal( root.querySelector( "[data-testid=cron-note]" )!.textContent!.startsWith( "Flipping a switch takes effect" ), true );
  assert.equal( h.timers.length, 1 );
  h.timers[ 0 ]!(); await flush();
  assert.equal( h.gets.length, 4 );
} );

test( "a list with nothing off shows the bare count", async () => {
  const h = harness();
  h.answer.cron = async () => ( { caller_is_admin : true, jobs : [ cronRow( "duplicate-check" ) ] } );
  await mounted( h );
  assert.equal( countOf(), "23" );
} );

test( "the header chevron collapses the section", async () => {
  const { root } = await mounted( harness() );
  ( root.querySelector( ".toggle-button" ) as HTMLElement ).click();
  assert.equal( root.getAttribute( "data-collapsed" ), "true" );
} );

test( "a second mount without unmount throws; unmount stops the poll, drops the bus listener, clears the root, and is idempotent", async () => {
  const h = harness();
  const { root, r } = await mounted( h );
  assert.throws( () => r.mount( root ), /already mounted/ );
  r.unmount();
  assert.deepEqual( h.cleared, [ 1 ] );
  assert.equal( root.children.length, 0 );
  emit( h, cronRow( "duplicate-check", { enabled : false } ) );          // the listener is gone: nothing happens
  r.unmount();
  assert.deepEqual( h.cleared, [ 1 ], "a second unmount must not clear again" );
  await r.refresh();                                                        // unmounted: nothing to paint, nothing asked
  assert.equal( h.gets.length, 2 );
  r.mount( root ); await flush();                                           // and it can mount again
  assert.equal( h.gets.length, 4 );
} );

test( "the pane uses the ambient document and timers when none are injected, and replies landing after unmount are dropped", async () => {
  paneFromPage();
  const release: Array<() => void> = [];
  const api: BackgroundJobsApi = {
    get  : <T,>( p: string ) => new Promise<T>( ( res ) => { release.push( () => res( ( p === "/api/jobs/summary" ? clone( FIXTURE ) : CRON() ) as unknown as T ) ); } ),
    post : async () => ( {} as never ),
    put  : async () => ( {} as never ),
  };
  const r = createBackgroundJobsRenderer( { api, eventBus : createEventBusForTesting() } );
  r.mount( byId( "background-jobs-pane" ) );
  r.unmount();
  for ( const go of release ) go();
  await flush();
  assert.equal( byId( "background-jobs-pane" ).children.length, 0 );
} );

test( "hides Run now when the summary says the caller is not the operator", async () => {
  const h = harness();
  h.answer.summary = async () => ( { ...clone( FIXTURE ), caller_is_operator : false } );
  const { root } = await mounted( h );
  assert.equal( root.querySelectorAll( "[data-testid=jobs-item]" ).length, 24 );
  assert.equal( root.querySelectorAll( "[data-testid=jobs-run-now]" ).length, 0 );
} );

test( "the refresh button reloads; a failed summary shows the reason and keeps the last good list", async () => {
  const h = harness();
  const { root } = await mounted( h );
  const btn = root.querySelector( "[data-testid=multiplexer-background-jobs-refresh]" ) as HTMLElement;
  h.answer.summary = async () => { throw new ApiError( 503, "/api/jobs/summary", "down" ); };
  btn.click(); await flush();
  assert.equal( errOf().hidden, false );
  assert.equal( errOf().textContent, "Could not load the jobs: HTTP 503" );
  assert.equal( root.querySelectorAll( "[data-testid=jobs-accordion] > [data-testid=jobs-item]" ).length, 24 );
  h.answer.summary = async () => { throw new Error( "network down" ); };
  btn.click(); await flush();
  assert.equal( errOf().textContent, "Could not load the jobs: Error: network down" );
  h.answer.summary = async () => clone( FIXTURE );
  btn.click(); await flush();
  assert.equal( errOf().hidden, true );
} );

test( "a failed switch list names itself, keeps the jobs drawn, and keeps the last good switches; both failing say both", async () => {
  const h = harness();
  const { root, r } = await mounted( h );
  h.answer.cron = async () => { throw new ApiError( 500, "/api/cron-jobs", "x" ); };
  await r.refresh();
  assert.equal( errOf().textContent, "Could not load the scheduled jobs: HTTP 500" );
  assert.equal( stateOf( "context-tick" ), "OFF", "the last good switches stay" );
  h.answer.summary = async () => { throw new Error( "offline" ); };
  await r.refresh();
  assert.equal( errOf().textContent, "Could not load the jobs: Error: offline Could not load the scheduled jobs: HTTP 500" );
  assert.equal( root.querySelectorAll( "[data-testid=jobs-item]" ).length, 24 );
  h.answer.summary = async () => clone( FIXTURE ); h.answer.cron = async () => CRON();
  await r.refresh();
  assert.equal( errOf().hidden, true );
} );

test( "when the summary has never loaded every switch is still drawn, as a NOT REPORTING row, with the banner; a switch frame repaints it", async () => {
  const h = harness();
  h.answer.summary = async () => { throw new ApiError( 503, "/api/jobs/summary", "down" ); };
  const { root } = await mounted( h );
  assert.equal( root.querySelectorAll( "[data-testid=jobs-accordion] > [data-testid=jobs-item]" ).length, 5, "the five switch rows" );
  assert.equal( rowOf( "duplicate-check" ).querySelector( "[data-testid=jobs-badge]" )!.textContent, "NOT REPORTING" );
  assert.equal( errOf().textContent, "Could not load the jobs: HTTP 503" );
  assert.equal( countOf(), "5 (2 off)" );
  assert.equal( root.querySelector( "[data-testid=multiplexer-background-jobs-header]" )!.getAttribute( "title" ), "0 jobs" );
  ( rowOf( "duplicate-check" ).querySelector( "[data-testid=jobs-disclose]" ) as HTMLElement ).click();
  flipOf( "duplicate-check" ).click(); await flush();
  assert.deepEqual( h.puts, [ { path : "/api/cron-jobs/duplicate-check/enabled", body : { on : false } } ], "the switch still flips" );
  assert.equal( stateOf( "duplicate-check" ), "OFF" );
  emit( h, cronRow( "context-tick", { enabled : true } ) );
  assert.equal( stateOf( "context-tick" ), "ON" );
} );

test( "when neither door has ever answered nothing is drawn but the banner", async () => {
  const h = harness();
  h.answer.summary = async () => { throw new ApiError( 503, "/api/jobs/summary", "down" ); };
  h.answer.cron    = async () => { throw new ApiError( 500, "/api/cron-jobs", "down" ); };
  const { root } = await mounted( h );
  assert.equal( root.querySelectorAll( "[data-testid=jobs-item]" ).length, 0 );
  assert.equal( errOf().textContent, "Could not load the jobs: HTTP 503 Could not load the scheduled jobs: HTTP 500" );
  assert.equal( countOf(), "…" );
  emit( h, cronRow( "duplicate-check", { enabled : false } ) );
  assert.equal( root.querySelectorAll( "[data-testid=jobs-item]" ).length, 0 );
} );

// ── the switch, from line 2 ─────────────────────────────────────────────────

test( "a click on the flip button sends PUT with the opposite of what the row shows, and the row repaints from the server's answer, still open", async () => {
  const h = harness();
  await mounted( h );
  ( rowOf( "duplicate-check" ).querySelector( "[data-testid=jobs-disclose]" ) as HTMLElement ).click();
  flipOf( "duplicate-check" ).click();
  await flush();
  assert.deepEqual( h.puts, [ { path : "/api/cron-jobs/duplicate-check/enabled", body : { on : false } } ] );
  assert.equal( stateOf( "duplicate-check" ), "OFF" );
  assert.equal( countOf(), "24 (3 off)" );
  assert.equal( ( rowOf( "duplicate-check" ).querySelector( "[data-testid=jobs-panel]" ) as HTMLElement ).hidden, false, "the row the reader flipped from stays open" );
  assert.equal( ( rowOf( "context-tick" ).querySelector( "[data-testid=jobs-panel]" ) as HTMLElement ).hidden, true );
  flipOf( "context-tick" ).click();
  await flush();
  assert.deepEqual( h.puts[ 1 ], { path : "/api/cron-jobs/context-tick/enabled", body : { on : true } } );
} );

test( "a refused flip shows its sentence on that row only and leaves the state alone", async () => {
  const h = harness();
  h.answer.put = async () => { throw new ApiError( 403, "/api/cron-jobs/x/enabled", "{\"detail\":\"no\"}" ); };
  await mounted( h );
  flipOf( "duplicate-check" ).click();
  await flush();
  const note = rowOf( "duplicate-check" ).querySelector( "[data-testid=cron-error]" ) as HTMLElement;
  assert.equal( note.hidden, false );
  assert.equal( note.textContent, "Only an administrator can flip a job's switch." );
  assert.equal( ( rowOf( "context-tick" ).querySelector( "[data-testid=cron-error]" ) as HTMLElement ).hidden, true );
  assert.equal( stateOf( "duplicate-check" ), "ON" );
} );

test( "a cron_job_switch_changed frame repaints that row in place; unknown jobs and malformed payloads change nothing", async () => {
  const h = harness();
  await mounted( h );
  emit( h, cronRow( "context-tick", { enabled : true, last_changed_by : "rick", last_changed_at : "2026-11-14T08:00:00-05:00" } ) );
  assert.equal( stateOf( "context-tick" ), "ON" );
  assert.equal( ( rowOf( "context-tick" ).querySelector( "[data-testid=cron-changed]" ) as HTMLElement ).textContent, "rick, 2026-11-14 08:00" );
  const before = document.querySelectorAll( "[data-testid=jobs-item]" ).length;
  emit( h, cronRow( "never-heard-of" ) );
  emit( h, null );
  emit( h, "text" );
  emit( h, { job : 7 } );
  assert.equal( document.querySelectorAll( "[data-testid=jobs-item]" ).length, before );
  assert.equal( stateOf( "duplicate-check" ), "ON" );
} );

test( "anyone who is not an administrator sees every switch read-only, and the note says so", async () => {
  const h = harness();
  h.answer.cron = async () => ( { ...CRON(), caller_is_admin : false } );
  await mounted( h );
  for ( const b of document.querySelectorAll( "[data-testid=cron-flip]" ) ) assert.equal( ( b as HTMLButtonElement ).disabled, true );
  assert.equal( document.querySelector( "[data-testid=cron-note]" )!.textContent, "Read-only: only an administrator can flip a switch." );
} );

test( "the list shows no switch note when the switch list is empty", async () => {
  const h = harness();
  h.answer.cron = async () => ( { caller_is_admin : true, jobs : [] } );
  await mounted( h );
  assert.equal( document.querySelectorAll( "[data-testid=cron-note]" ).length, 0 );
  assert.equal( document.querySelectorAll( "[data-testid=cron-item]" ).length, 0 );
} );

test( "turning off an alarm job takes two clicks: the first asks, sends nothing, and the second sends the PUT", async () => {
  const h = harness();
  await mounted( h );
  flipOf( "fleet-arbiter" ).click();
  await flush();
  assert.deepEqual( h.puts, [], "the first click must not write" );
  assert.equal( flipOf( "fleet-arbiter" ).textContent, "Confirm: turn off" );
  const note = rowOf( "fleet-arbiter" ).querySelector( "[data-testid=cron-error]" ) as HTMLElement;
  assert.equal( note.hidden, false );
  assert.equal( note.textContent, CRON_CONFIRM_TEXT );
  flipOf( "fleet-arbiter" ).click();
  await flush();
  assert.deepEqual( h.puts, [ { path : "/api/cron-jobs/fleet-arbiter/enabled", body : { on : false } } ] );
} );

test( "a redraw drops a half-finished confirmation, so the next click asks again; another alarm job asks for its own", async () => {
  const h = harness();
  const { r } = await mounted( h );
  flipOf( "fleet-arbiter" ).click();
  await flush();
  await r.refresh();                                  // redraw: the button is fresh and the pending job is forgotten
  flipOf( "fleet-arbiter" ).click();
  await flush();
  assert.deepEqual( h.puts, [], "a stale first click must not count as the confirmation" );
  flipOf( "duplicate-check" ).click();                // not an alarm job: one click
  await flush();
  assert.deepEqual( h.puts.map( ( p ) => p.path ), [ "/api/cron-jobs/duplicate-check/enabled" ] );
} );

test( "an alarm job that is off turns on with one click, and a different alarm job's click does not confirm the first", async () => {
  const h = harness();
  const cron = CRON();
  cron.jobs[ 2 ]!.enabled = false;
  cron.jobs.push( cronRow( "health-watcher", { alarm : true } ) );
  h.answer.cron = async () => clone( cron );
  h.answer.summary = async () => { const s = clone( FIXTURE ); s.jobs.push( { ...find( "duplicate-check" ), job : "health-watcher", title : "Health watcher" } ); return s; };
  await mounted( h );
  flipOf( "fleet-arbiter" ).click();
  await flush();
  assert.deepEqual( h.puts, [ { path : "/api/cron-jobs/fleet-arbiter/enabled", body : { on : true } } ] );
  h.puts.length = 0;
  flipOf( "health-watcher" ).click();                 // asks for its own confirmation
  await flush();
  assert.deepEqual( h.puts, [] );
} );

// ── Run now ─────────────────────────────────────────────────────────────────

test( "Run now posts to the job's own door, with ?target= for a target, and prints the outcome", async () => {
  const h = harness();
  await mounted( h );
  const dup = rowOf( "duplicate-check" );
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
  await mounted( harness( { post : async () => { throw err( 409 ); } } ) );
  const dup = rowOf( "duplicate-check" );
  ( dup.querySelector( "[data-testid=jobs-run-now]" ) as HTMLElement ).click(); await flush();
  assert.match( ( dup.querySelector( "[data-testid=jobs-run-status]" ) as HTMLElement ).textContent as string, /run lock is held/ );
} );

test( "the Background Jobs toolbar icon is 🔁, is used by no other toggle, and the section header shows the same icon (row 288165d6)", async () => {
  const mine   = SECTION_TOGGLES.find( ( t ) => t.sectionId === "background-jobs-pane" );
  assert.equal( mine?.icon, "🔁" );
  assert.equal( mine?.title, "Background Jobs", "the title is kept (row c80ef763, Tiberius's review)" );
  const others = SECTION_TOGGLES.filter( ( t ) => t.sectionId !== "background-jobs-pane" );
  assert.ok( others.length > 15, "the other toggles were not found: the uniqueness check would prove nothing" );
  assert.deepEqual( others.filter( ( t ) => t.icon === mine?.icon ), [] );
  const { root } = await mounted( harness() );
  assert.ok( ( root.querySelector( "[data-testid=multiplexer-background-jobs-header]" )!.textContent as string ).startsWith( "🔁" ) );
  assert.ok( ( root.querySelector( "[data-testid=multiplexer-background-jobs-header]" )!.textContent as string ).includes( "Background Jobs" ) );
} );

test( "the list ends with the switched-off line when the server sends one, and with nothing extra when it does not (row 4aa0ba1b)", () => {
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
  renderAccordion( document, mount, summary, mkActions() );
  const heads = () => Array.from( mount.querySelectorAll( "[data-testid=jobs-header] [role=columnheader]" ) ).map( ( h ) => h.textContent );
  assert.deepEqual( heads(), [ "", "", "Service", "Status", "Last run", "Last finished", "" ] );
  const order = () => Array.from( mount.querySelectorAll( ":scope > [data-testid=jobs-item]" ) ).map( ( i ) => i.getAttribute( "data-job" ) );
  assert.deepEqual( order(), [ "aa", "bb", "cc" ], "default order is service name A to Z" );
  ( mount.querySelector( "[data-testid=jobs-sort-name]" ) as HTMLElement ).click();
  assert.deepEqual( order(), [ "aa", "bb", "cc" ] );
  assert.equal( mount.querySelector( "[data-testid=jobs-sort-name]" )!.textContent, "Service ▲" );
  assert.equal( mount.querySelector( "[aria-sort=ascending]" )!.querySelector( "button" )!.getAttribute( "data-testid" ), "jobs-sort-name" );
  ( mount.querySelector( "[data-testid=jobs-sort-name]" ) as HTMLElement ).click();
  assert.deepEqual( order(), [ "cc", "bb", "aa" ] );
  assert.equal( mount.querySelector( "[data-testid=jobs-sort-name]" )!.textContent, "Service ▼" );
  renderAccordion( document, mount, summary, mkActions() );                       // a poll redraws: the pick stays
  assert.deepEqual( order(), [ "cc", "bb", "aa" ] );
  ( mount.querySelector( "[data-testid=jobs-sort-name]" ) as HTMLElement ).click();   // third click: back to default
  assert.deepEqual( order(), [ "aa", "bb", "cc" ] );
  ( mount.querySelector( "[data-testid=jobs-sort-health]" ) as HTMLElement ).click();
  ( mount.querySelector( "[data-testid=jobs-sort-health]" ) as HTMLElement ).click();
  assert.deepEqual( order(), [ "aa", "bb", "cc" ], "health descending: failing, unknown, healthy" );
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
