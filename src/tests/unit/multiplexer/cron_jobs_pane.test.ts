// Tests for the multiplexer's Scheduled Jobs pane, at full coverage.
//
// The pane is mounted into the real #cron-jobs-pane section parsed out of multiplexer.html. Only the HTTP
// client is faked. The row count is pinned to literals, never derived from the fixture rows themselves.

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { ApiError } from "../../../lupin_app/static/js/multiplexer/api/ApiClient";
import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createCronJobsRenderer, cronChangedText, cronFlipFailureText, cronFlipPath, cronStateText,
  CRON_DRIFT_TEXT, CRON_JOBS_PATH, CRON_JOBS_POLL_MS, CRON_NOT_REPORTED,
} from "../../../lupin_app/static/js/multiplexer/render/CronJobsRenderer";
import type { CronJobRow, CronJobsApi, CronJobsSummary } from "../../../lupin_app/static/js/multiplexer/render/CronJobsRenderer";
import { SECTION_TOGGLES } from "../../../lupin_app/static/js/multiplexer/render/templates/sectionToolbar";

const HERE      = dirname( fileURLToPath( import.meta.url ) );
const HTML_PATH = resolve( HERE, "../../../lupin_app/static/html/multiplexer.html" );

before( () => { if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register(); } );

const flush = () => new Promise( ( r ) => setImmediate( r ) );
const byId  = ( id: string ) => document.getElementById( id ) as HTMLElement;
const clone = <T,>( v: T ): T => JSON.parse( JSON.stringify( v ) ) as T;

function row( job: string, over: Partial<CronJobRow> = {} ): CronJobRow {
  return {
    job, title : `Title of ${ job }`, schedule : "*/5 * * * *", key : `cron job ${ job } enabled`,
    enabled : true, honoured : true, drift : false, last_changed_by : null, last_changed_at : null, ...over,
  };
}

const SUMMARY = (): CronJobsSummary => ( {
  caller_is_admin : true,
  jobs : [
    row( "duplicate-check", { last_changed_by : "rick@example.test", last_changed_at : "2026-11-13T21:05:44-05:00" } ),
    row( "context-tick",    { enabled : false } ),
    row( "no-key",          { enabled : null } ),
    row( "not-read",        { honoured : false } ),
    row( "drifted",         { drift : true } ),
  ],
} );

beforeEach( () => {
  document.body.innerHTML = `<section id="cron-jobs-pane"></section>`;
} );

interface Rig {
  r      : ReturnType<typeof createCronJobsRenderer>;
  bus    : ReturnType<typeof createEventBusForTesting>;
  gets   : string[];
  puts   : Array<{ path: string; body: unknown }>;
  ticks  : Array<() => void>;
  cleared: number[];
  answer : { get: () => Promise<CronJobsSummary>; put: ( path: string, body: unknown ) => Promise<CronJobRow> };
}

function rig( summary: () => CronJobsSummary = SUMMARY ): Rig {
  const bus     = createEventBusForTesting();
  const gets: string[] = [];
  const puts: Array<{ path: string; body: unknown }> = [];
  const ticks: Array<() => void> = [];
  const cleared: number[] = [];
  const answer = {
    get : async (): Promise<CronJobsSummary> => summary(),
    put : async ( _p: string, body: unknown ): Promise<CronJobRow> => { void body; return row( "duplicate-check", { enabled : false } ); },
  };
  const api: CronJobsApi = {
    get : async <T,>( path: string ) => { gets.push( path ); return await answer.get() as T; },
    put : async <T,>( path: string, body: unknown ) => { puts.push( { path, body } ); return await answer.put( path, body ) as T; },
  };
  const r = createCronJobsRenderer( {
    api, eventBus : bus,
    setIntervalFn   : ( fn, ms ) => { assert.equal( ms, CRON_JOBS_POLL_MS ); ticks.push( fn ); return ticks.length; },
    clearIntervalFn : ( id ) => { cleared.push( id ); },
  } );
  return { r, bus, gets, puts, ticks, cleared, answer };
}

const items  = () => [ ...document.querySelectorAll( "[data-testid=cron-item]" ) ] as HTMLElement[];
const item   = ( job: string ) => items().find( ( i ) => i.getAttribute( "data-job" ) === job ) as HTMLElement;
const flipOf = ( job: string ) => item( job ).querySelector( "[data-testid=cron-flip]" ) as HTMLButtonElement;
const text   = ( job: string, testid: string ) => ( item( job ).querySelector( `[data-testid=${ testid }]` ) as HTMLElement ).textContent;

// ── text rules ──────────────────────────────────────────────────────────────

test( "the text rules: state words, the changed line, the flip path", () => {
  assert.equal( cronStateText( true ), "ON" );
  assert.equal( cronStateText( false ), "OFF" );
  assert.equal( cronStateText( null ), "UNKNOWN" );
  assert.equal( cronChangedText( row( "a" ) ), CRON_NOT_REPORTED );
  assert.equal( cronChangedText( row( "a", { last_changed_by : "x", last_changed_at : null } ) ), CRON_NOT_REPORTED );
  assert.equal( cronChangedText( row( "a", { last_changed_by : null, last_changed_at : "2026-11-13T21:05:44-05:00" } ) ), CRON_NOT_REPORTED );
  assert.equal( cronChangedText( row( "a", { last_changed_by : "rick", last_changed_at : "2026-11-13T21:05:44-05:00" } ) ), "rick, 2026-11-13 21:05" );
  assert.equal( cronFlipPath( "duplicate-check" ), "/api/cron-jobs/duplicate-check/enabled" );
  assert.equal( cronFlipPath( "a b/c" ), "/api/cron-jobs/a%20b%2Fc/enabled" );
  assert.equal( CRON_JOBS_PATH, "/api/cron-jobs" );
} );

test( "each refusal gets its own sentence; a 409 or 422 detail wins over the generic line", () => {
  const refused = ( status: number, body: string ) => new ApiError( status, "/api/cron-jobs/x/enabled", body );
  assert.equal( cronFlipFailureText( new Error( "boom" ) ), "Flip failed: Error: boom" );
  assert.equal( cronFlipFailureText( refused( 403, "{}" ) ), "Only an administrator can flip a job's switch." );
  assert.equal( cronFlipFailureText( refused( 404, "{}" ) ), "The server does not know this job." );
  assert.equal( cronFlipFailureText( refused( 409, "{\"detail\":\"'x' does not read its switch yet\"}" ) ), "'x' does not read its switch yet" );
  assert.equal( cronFlipFailureText( refused( 409, "no body" ) ), "The configuration file does not carry this job's switch yet." );
  assert.equal( cronFlipFailureText( refused( 409, "{\"detail\":\"\"}" ) ), "The configuration file does not carry this job's switch yet." );
  assert.equal( cronFlipFailureText( refused( 409, "{\"detail\":7}" ) ), "The configuration file does not carry this job's switch yet." );
  assert.equal( cronFlipFailureText( refused( 409, "{not json" ) ), "The configuration file does not carry this job's switch yet." );
  assert.equal( cronFlipFailureText( refused( 422, "{\"detail\":\"bad body\"}" ) ), "bad body" );
  assert.equal( cronFlipFailureText( refused( 422, "{}" ) ), "The server refused this flip." );
  assert.equal( cronFlipFailureText( refused( 500, "{}" ) ), "Flip failed (HTTP 500)." );
} );

// ── the page ────────────────────────────────────────────────────────────────

test( "the page declares #cron-jobs-pane right after the background jobs pane, links its sheet, and the toolbar names it", () => {
  const html = readFileSync( HTML_PATH, "utf8" );
  assert.ok( html.indexOf( 'id="background-jobs-pane"' ) < html.indexOf( 'id="cron-jobs-pane"' ) );
  assert.ok( html.indexOf( 'id="cron-jobs-pane"' ) < html.indexOf( 'id="jobs-pane"' ) );
  assert.match( html, /<section id="cron-jobs-pane"[^>]*><\/section>/ );
  assert.ok( html.includes( '/static/css/multiplexer/cron-jobs.css' ) );
  const ids  = SECTION_TOGGLES.map( ( t ) => t.sectionId );
  assert.equal( ids[ ids.indexOf( "background-jobs-pane" ) + 1 ], "cron-jobs-pane" );
  assert.deepEqual( SECTION_TOGGLES.find( ( t ) => t.sectionId === "cron-jobs-pane" ), {
    sectionId : "cron-jobs-pane", icon : "⏰", title : "Scheduled Jobs", testid : "multiplexer-section-toolbar-cron-jobs",
  } );
} );

// ── mount, paint, unmount ───────────────────────────────────────────────────

test( "mount paints one row per job with state, schedule, changed line and honoured text; the count says how many are off", async () => {
  const g = rig();
  g.r.mount( byId( "cron-jobs-pane" ) );
  await flush();
  assert.deepEqual( g.gets, [ "/api/cron-jobs" ] );
  assert.equal( items().length, 5 );
  assert.equal( ( document.querySelector( "[data-testid=multiplexer-cron-jobs-count]" ) as HTMLElement ).textContent, "5 (1 off)" );
  assert.equal( text( "duplicate-check", "cron-state" ), "ON" );
  assert.equal( text( "duplicate-check", "cron-title" ), "Title of duplicate-check" );
  assert.equal( text( "duplicate-check", "cron-schedule" ), "*/5 * * * *" );
  assert.equal( text( "duplicate-check", "cron-changed" ), "rick@example.test, 2026-11-13 21:05" );
  assert.equal( text( "duplicate-check", "cron-honoured" ), "reads its switch" );
  assert.equal( text( "context-tick", "cron-state" ), "OFF" );
  assert.equal( text( "no-key", "cron-state" ), "UNKNOWN" );
  assert.equal( text( "not-read", "cron-honoured" ), "does not read its switch yet" );
  assert.equal( text( "drifted", "cron-drift" ), CRON_DRIFT_TEXT );
  assert.equal( item( "duplicate-check" ).querySelector( "[data-testid=cron-drift]" ), null );
  assert.match( ( document.querySelector( "[data-testid=cron-note]" ) as HTMLElement ).textContent as string, /^Flipping a switch takes effect/ );
  assert.equal( ( document.querySelector( "[data-testid=cron-jobs-error]" ) as HTMLElement ).hidden, true );
  g.r.unmount();
} );

test( "a list with nothing off shows the bare count", async () => {
  const g = rig( () => ( { caller_is_admin : true, jobs : [ row( "a" ) ] } ) );
  g.r.mount( byId( "cron-jobs-pane" ) );
  await flush();
  assert.equal( ( document.querySelector( "[data-testid=multiplexer-cron-jobs-count]" ) as HTMLElement ).textContent, "1" );
  g.r.unmount();
} );

test( "an admin gets an enabled button only where a switch exists and something reads it", async () => {
  const g = rig();
  g.r.mount( byId( "cron-jobs-pane" ) );
  await flush();
  assert.equal( flipOf( "duplicate-check" ).disabled, false );
  assert.equal( flipOf( "duplicate-check" ).textContent, "Turn off" );
  assert.equal( flipOf( "context-tick" ).disabled, false );
  assert.equal( flipOf( "context-tick" ).textContent, "Turn on" );
  assert.equal( flipOf( "no-key" ).disabled, true );
  assert.equal( flipOf( "not-read" ).disabled, true );
  g.r.unmount();
} );

test( "anyone who is not an admin sees every switch read-only, and the note says so", async () => {
  const g = rig( () => ( { ...SUMMARY(), caller_is_admin : false } ) );
  g.r.mount( byId( "cron-jobs-pane" ) );
  await flush();
  for ( const i of items() ) assert.equal( ( i.querySelector( "[data-testid=cron-flip]" ) as HTMLButtonElement ).disabled, true );
  assert.equal( ( document.querySelector( "[data-testid=cron-note]" ) as HTMLElement ).textContent, "Read-only: only an administrator can flip a switch." );
  g.r.unmount();
} );

test( "a second mount throws; unmount stops the poll, drops the bus listener, clears the root, and is idempotent", async () => {
  const g = rig();
  const root = byId( "cron-jobs-pane" );
  g.r.mount( root );
  assert.throws( () => g.r.mount( root ), /already mounted/ );
  await flush();
  g.r.unmount();
  assert.deepEqual( g.cleared, [ 1 ] );
  assert.equal( root.children.length, 0 );
  g.bus.emit( { type : "cron_job_switch_changed", payload : row( "duplicate-check", { enabled : false } ), source : "t", ts : 0 } );
  g.r.unmount();
  assert.deepEqual( g.cleared, [ 1 ], "a second unmount must not clear again" );
  await g.r.refresh();
  assert.deepEqual( g.gets, [ "/api/cron-jobs" ], "refresh after unmount asks nothing" );
} );

test( "the poll timer and the refresh button each ask the list door again", async () => {
  const g = rig();
  g.r.mount( byId( "cron-jobs-pane" ) );
  await flush();
  g.ticks[ 0 ]();
  await flush();
  ( document.querySelector( "[data-testid=multiplexer-cron-jobs-refresh]" ) as HTMLElement ).click();
  await flush();
  assert.equal( g.gets.length, 3 );
  g.r.unmount();
} );

test( "the default timer functions are the window's own", async () => {
  const bus = createEventBusForTesting();
  const r   = createCronJobsRenderer( { api : { get : async <T,>() => SUMMARY() as T, put : async <T,>() => row( "a" ) as T }, eventBus : bus } );
  r.mount( byId( "cron-jobs-pane" ) );
  await flush();
  assert.equal( items().length, 5 );
  r.unmount();
} );

test( "a failed list shows the banner with the status, or the error text; the next good answer hides it", async () => {
  const g = rig();
  g.answer.get = async () => { throw new ApiError( 503, "/api/cron-jobs", "down" ); };
  g.r.mount( byId( "cron-jobs-pane" ) );
  await flush();
  const banner = document.querySelector( "[data-testid=cron-jobs-error]" ) as HTMLElement;
  assert.equal( banner.hidden, false );
  assert.equal( banner.textContent, "Could not load the scheduled jobs: HTTP 503" );
  g.answer.get = async () => { throw new Error( "offline" ); };
  await g.r.refresh();
  assert.equal( banner.textContent, "Could not load the scheduled jobs: Error: offline" );
  g.answer.get = async () => SUMMARY();
  await g.r.refresh();
  assert.equal( banner.hidden, true );
  g.r.unmount();
} );

test( "a list that lands after unmount paints nothing", async () => {
  const g = rig();
  let release: () => void = () => {};
  g.answer.get = () => new Promise<CronJobsSummary>( ( ok ) => { release = () => ok( SUMMARY() ); } );
  g.r.mount( byId( "cron-jobs-pane" ) );
  g.r.unmount();
  release();
  await flush();
  assert.equal( items().length, 0 );
} );

// ── the flip ────────────────────────────────────────────────────────────────

test( "a click sends PUT with the opposite of what the row shows, and the row repaints from the server's answer", async () => {
  const g = rig();
  g.r.mount( byId( "cron-jobs-pane" ) );
  await flush();
  flipOf( "duplicate-check" ).click();
  await flush();
  assert.deepEqual( g.puts, [ { path : "/api/cron-jobs/duplicate-check/enabled", body : { on : false } } ] );
  assert.equal( text( "duplicate-check", "cron-state" ), "OFF" );
  assert.equal( ( document.querySelector( "[data-testid=multiplexer-cron-jobs-count]" ) as HTMLElement ).textContent, "5 (2 off)" );
  flipOf( "context-tick" ).click();
  await flush();
  assert.deepEqual( g.puts[ 1 ], { path : "/api/cron-jobs/context-tick/enabled", body : { on : true } } );
  g.r.unmount();
} );

test( "a refused flip shows its sentence on that row only and leaves the state alone", async () => {
  const g = rig();
  g.answer.put = async () => { throw new ApiError( 403, "/api/cron-jobs/x/enabled", "{\"detail\":\"no\"}" ); };
  g.r.mount( byId( "cron-jobs-pane" ) );
  await flush();
  flipOf( "duplicate-check" ).click();
  await flush();
  const note = item( "duplicate-check" ).querySelector( "[data-testid=cron-error]" ) as HTMLElement;
  assert.equal( note.hidden, false );
  assert.equal( note.textContent, "Only an administrator can flip a job's switch." );
  assert.equal( ( item( "context-tick" ).querySelector( "[data-testid=cron-error]" ) as HTMLElement ).hidden, true );
  assert.equal( text( "duplicate-check", "cron-state" ), "ON" );
  g.r.unmount();
} );

// ── the socket frame ────────────────────────────────────────────────────────

test( "a cron_job_switch_changed frame repaints that row in place; unknown jobs and malformed payloads change nothing", async () => {
  const g = rig();
  g.r.mount( byId( "cron-jobs-pane" ) );
  await flush();
  const emit = ( payload: unknown ) => g.bus.emit( { type : "cron_job_switch_changed", payload, source : "t", ts : 0 } );
  emit( row( "context-tick", { enabled : true, last_changed_by : "rick", last_changed_at : "2026-11-14T08:00:00-05:00" } ) );
  assert.equal( text( "context-tick", "cron-state" ), "ON" );
  assert.equal( text( "context-tick", "cron-changed" ), "rick, 2026-11-14 08:00" );
  const before = items().length;
  emit( row( "never-heard-of" ) );
  emit( null );
  emit( "text" );
  emit( { job : 7 } );
  assert.equal( items().length, before );
  assert.equal( text( "duplicate-check", "cron-state" ), "ON" );
  g.r.unmount();
} );

test( "the clone helper keeps fixtures independent", () => {
  const a = SUMMARY(); const b = clone( a ); b.jobs[ 0 ].enabled = false;
  assert.equal( a.jobs[ 0 ].enabled, true );
} );
