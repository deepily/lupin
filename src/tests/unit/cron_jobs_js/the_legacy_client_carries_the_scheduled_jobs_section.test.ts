// The legacy notifications client carries the scheduled-jobs section (row 063fc1a8).
//
// cron-jobs.js is plain browser JS in an IIFE, in no tsconfig, so it is loaded the way
// background_jobs_js/ loads its subject: the actual bytes, run through vm.runInThisContext against
// a DOM parsed out of the actual notifications.html. It has no c8 number; these behavioural
// assertions are its gate. The rows are the shape GET /api/cron-jobs returns.
//
// Run via: npx tsx --test src/tests/unit/cron_jobs_js/the_legacy_client_carries_the_scheduled_jobs_section.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE    = dirname( fileURLToPath( import.meta.url ) );
const STATIC  = resolve( HERE, "../../../lupin_app/static" );
const HTML    = readFileSync( resolve( STATIC, "html/notifications.html" ), "utf8" );
const JS_PATH = resolve( STATIC, "js/cron-jobs.js" );
const JS_SRC  = readFileSync( JS_PATH, "utf8" );

type G = Record<string, any>;
const g = globalThis as unknown as G;

const byId  = ( id: string ) => document.getElementById( id ) as HTMLElement;
const flush = () => new Promise( ( r ) => setImmediate( r ) );

const ROW_A = { job : "duplicate-check", title : "Duplicate check", schedule : "cron 0 10-22 * * *", key : "cron job duplicate-check enabled", enabled : true,  honoured : true,  drift : false, last_changed_by : null, last_changed_at : null };
const ROW_B = { job : "wiki-librarian",  title : "Wiki librarian",  schedule : "cron 17 10 * * *",   key : "cron job wiki-librarian enabled",  enabled : false, honoured : true,  drift : false, last_changed_by : "rick@example.com", last_changed_at : "2026-11-13T19:30:00-05:00" };
const ROW_C = { job : "disk-report",     title : "Disk report",     schedule : "cron 0 19 * * 0",    key : "cron job disk-report enabled",     enabled : null,  honoured : true,  drift : false, last_changed_by : null, last_changed_at : null };

const clone = <T,>( v: T ): T => JSON.parse( JSON.stringify( v ) );

function sectionMarkup(): string {
  const m = HTML.match( /<div class="collapsible-section" id="section-cron-jobs">[\s\S]*?\n        <\/div>\n(?=\n)/ );
  assert.ok( m, "notifications.html declares no #section-cron-jobs" );
  return m![ 0 ];
}

interface Call { url: string; opts?: { method?: string; body?: string; headers?: Record<string, string> } }
let calls: Call[];
let listReply: () => { ok: boolean; status: number; json: () => Promise<unknown> };
let putReply: () => { ok: boolean; status: number; json: () => Promise<unknown> };
let timers: Array<() => void>;

before( () => { if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register(); } );

beforeEach( () => {
  document.body.innerHTML = sectionMarkup();
  timers    = [];
  calls     = [];
  g.window.setInterval = ( fn: () => void ) => { timers.push( fn ); return timers.length; };
  listReply = () => ( { ok : true, status : 200, json : async () => ( { jobs : clone( [ ROW_A, ROW_B, ROW_C ] ), caller_is_admin : true } ) } );
  putReply  = () => ( { ok : true, status : 200, json : async () => ( { ...ROW_A, enabled : false, honoured : true,  drift : false, last_changed_by : "rick@example.com", last_changed_at : "2026-11-13T20:00:00-05:00" } ) } );
  g.fetch = async ( url: string, opts?: Call[ "opts" ] ) => { calls.push( { url, opts } ); return opts?.method === "PUT" ? putReply() : listReply(); };
  g.localStorage.setItem( "lupin_access_token", "tok" );
  delete g.window.notificationsUI;
} );

async function load(): Promise<G> {
  delete g.window.cronJobs;
  vm.runInThisContext( JS_SRC, { filename : JS_PATH } );
  await flush();
  return g.window.cronJobs as G;
}

const items = () => Array.from( byId( "cron-jobs-container" ).querySelectorAll( ":scope > [data-testid=cron-item]" ) ) as HTMLElement[];
const item  = ( job: string ) => items().find( ( i ) => i.getAttribute( "data-job" ) === job )!;
const flipButton = ( job: string ) => item( job ).querySelector( "[data-testid=cron-flip]" ) as HTMLButtonElement;
const stateOf = ( job: string ) => item( job ).querySelector( "[data-testid=cron-state]" )!.textContent;

test( "the page puts the section after Background Jobs and before the filter settings, once, with fresh tokens", () => {
  const jobs = HTML.indexOf( 'id="section-background-jobs"' );
  const mine = HTML.indexOf( 'id="section-cron-jobs"' );
  const next = HTML.indexOf( 'id="filter-settings-section"' );
  assert.ok( jobs > 0 && jobs < mine && mine < next, "section order" );
  assert.equal( ( HTML.match( /id="section-cron-jobs"/g ) ?? [] ).length, 1 );
  const js = HTML.match( /\/static\/js\/cron-jobs\.js\?v=([0-9a-f]{12})/ );
  assert.ok( js, "no tokened script tag" );
  assert.equal( js![ 1 ], createHash( "sha256" ).update( readFileSync( JS_PATH ) ).digest( "hex" ).slice( 0, 12 ) );
  const css = HTML.match( /\/static\/css\/cron-jobs-legacy\.css\?v=([0-9a-f]{12})/ );
  assert.ok( css, "no tokened stylesheet link" );
  assert.equal( css![ 1 ], createHash( "sha256" ).update( readFileSync( resolve( STATIC, "css/cron-jobs-legacy.css" ) ) ).digest( "hex" ).slice( 0, 12 ) );
} );

test( "on load it fetches /api/cron-jobs, draws one row per job with its state, counts the off ones, and polls", async () => {
  await load();
  assert.deepEqual( calls.map( ( c ) => c.url ), [ "/api/cron-jobs" ] );
  assert.equal( items().length, 3 );
  assert.deepEqual( [ "duplicate-check", "wiki-librarian", "disk-report" ].map( stateOf ), [ "ON", "OFF", "UNKNOWN" ] );
  assert.equal( byId( "cron-jobs-count" ).textContent, "3 (1 off)" );
  assert.equal( item( "duplicate-check" ).querySelector( "[data-testid=cron-schedule]" )!.textContent, "cron 0 10-22 * * *" );
  assert.equal( item( "duplicate-check" ).querySelector( "[data-testid=cron-changed]" )!.textContent, "not reported" );
  assert.equal( item( "wiki-librarian" ).querySelector( "[data-testid=cron-changed]" )!.textContent, "rick@example.com, 2026-11-13 19:30" );
  assert.equal( byId( "cron-jobs-error" ).hidden, true );
  assert.equal( timers.length, 1 );
  timers[ 0 ]!(); await flush();
  assert.equal( calls.length, 2 );
} );

test( "an administrator sees live buttons; an unknown switch has none to flip", async () => {
  await load();
  assert.equal( flipButton( "duplicate-check" ).disabled, false );
  assert.equal( flipButton( "duplicate-check" ).textContent, "Turn off" );
  assert.equal( flipButton( "wiki-librarian" ).textContent, "Turn on" );
  assert.equal( flipButton( "disk-report" ).disabled, true );
  assert.match( byId( "cron-jobs-container" ).querySelector( "[data-testid=cron-note]" )!.textContent as string, /^Flipping a switch takes effect/ );
} );

test( "anyone who is not an administrator sees every button disabled and a read-only note", async () => {
  listReply = () => ( { ok : true, status : 200, json : async () => ( { jobs : clone( [ ROW_A, ROW_B ] ), caller_is_admin : false } ) } );
  await load();
  assert.ok( items().every( ( i ) => ( i.querySelector( "[data-testid=cron-flip]" ) as HTMLButtonElement ).disabled ) );
  assert.match( byId( "cron-jobs-container" ).querySelector( "[data-testid=cron-note]" )!.textContent as string, /^Read-only/ );
  flipButton( "duplicate-check" ).click(); await flush();
  assert.equal( calls.filter( ( c ) => c.opts?.method === "PUT" ).length, 0 );
} );

test( "a click sends PUT with the opposite state and the bearer token, then draws the row the server returned", async () => {
  await load();
  flipButton( "duplicate-check" ).click(); await flush();
  const put = calls.find( ( c ) => c.opts?.method === "PUT" )!;
  assert.equal( put.url, "/api/cron-jobs/duplicate-check/enabled" );
  assert.deepEqual( JSON.parse( put.opts!.body as string ), { on : false } );
  assert.equal( put.opts!.headers![ "Authorization" ], "Bearer tok" );
  assert.equal( put.opts!.headers![ "Content-Type" ], "application/json" );
  assert.equal( stateOf( "duplicate-check" ), "OFF" );
  assert.equal( byId( "cron-jobs-count" ).textContent, "3 (2 off)" );
  assert.equal( item( "duplicate-check" ).querySelector( "[data-testid=cron-changed]" )!.textContent, "rick@example.com, 2026-11-13 20:00" );
  flipButton( "wiki-librarian" ).click(); await flush();
  assert.deepEqual( JSON.parse( calls.filter( ( c ) => c.opts?.method === "PUT" )[ 1 ]!.opts!.body as string ), { on : true } );
} );

test( "a refused flip says why on the row and leaves the state alone", async () => {
  await load();
  for ( const [ status, detail, expected ] of [
    [ 403, null, /^Only an administrator/ ], [ 404, null, /does not know this job/ ], [ 409, null, /does not carry this job's switch/ ],
    [ 422, "on must be a boolean", /^on must be a boolean/ ], [ 422, null, /HTTP 422/ ], [ 500, null, /HTTP 500/ ],
  ] as Array<[ number, string | null, RegExp ]> ) {
    putReply = () => ( { ok : false, status, json : async () => ( detail === null ? {} : { detail } ) } );
    flipButton( "duplicate-check" ).click(); await flush();
    const note = item( "duplicate-check" ).querySelector( "[data-testid=cron-error]" ) as HTMLElement;
    assert.match( note.textContent as string, expected );
    assert.equal( note.hidden, false );
    assert.equal( stateOf( "duplicate-check" ), "ON" );
  }
  putReply = () => ( { ok : false, status : 500, json : async () => { throw new Error( "not json" ); } } );
  flipButton( "duplicate-check" ).click(); await flush();
  assert.match( item( "duplicate-check" ).querySelector( "[data-testid=cron-error]" )!.textContent as string, /HTTP 500/ );
} );

test( "a network failure on a flip is shown on the row", async () => {
  await load();
  g.fetch = async () => { throw new Error( "offline" ); };
  flipButton( "duplicate-check" ).click(); await flush();
  assert.match( item( "duplicate-check" ).querySelector( "[data-testid=cron-error]" )!.textContent as string, /^Flip failed: Error: offline/ );
} );

test( "a socket frame for a listed job redraws that row; a frame for an unknown job or a malformed frame changes nothing", async () => {
  const cron = await load();
  cron.applyEvent( { type : "cron_job_switch_changed", timestamp : "t", ...ROW_C, enabled : true, last_changed_by : "rick@example.com", last_changed_at : "2026-11-13T21:00:00-05:00" } );
  assert.equal( stateOf( "disk-report" ), "ON" );
  assert.equal( byId( "cron-jobs-count" ).textContent, "3 (1 off)" );
  const before = byId( "cron-jobs-container" ).innerHTML;
  cron.applyEvent( { type : "cron_job_switch_changed", ...ROW_A, job : "no-such-job" } );
  cron.applyEvent( null );
  cron.applyEvent( "text" );
  cron.applyEvent( { type : "cron_job_switch_changed" } );
  assert.equal( byId( "cron-jobs-container" ).innerHTML, before );
} );

test( "a frame that arrives with no section on the page is ignored", async () => {
  const cron = await load();
  document.body.innerHTML = "";
  cron.applyEvent( { type : "cron_job_switch_changed", ...ROW_A } );
} );

test( "a failed load shows the error and keeps the section; the refresh button reloads", async () => {
  listReply = () => ( { ok : false, status : 401, json : async () => ( {} ) } );
  await load();
  assert.equal( byId( "cron-jobs-error" ).hidden, false );
  assert.match( byId( "cron-jobs-error" ).textContent as string, /Could not load the scheduled jobs: HTTP 401/ );
  listReply = () => ( { ok : true, status : 200, json : async () => ( { jobs : clone( [ ROW_A ] ), caller_is_admin : true } ) } );
  byId( "cron-jobs-refresh" ).click(); await flush();
  assert.equal( byId( "cron-jobs-error" ).hidden, true );
  assert.equal( items().length, 1 );
  g.fetch = async () => { throw "plain string"; };
  byId( "cron-jobs-refresh" ).click(); await flush();
  assert.match( byId( "cron-jobs-error" ).textContent as string, /plain string/ );
} );

test( "authedFetch is used when the page offers it; the bare token path says so loudly", async () => {
  let used = 0;
  g.window.notificationsUI = { authedFetch : async ( url: string, opts: unknown ) => { used += 1; calls.push( { url, opts: opts as Call[ "opts" ] } ); return listReply(); } };
  await load();
  assert.equal( used, 1 );
  delete g.window.notificationsUI;
  const seen: unknown[] = [];
  const original = console.error;
  console.error = ( ...a: unknown[] ) => { seen.push( a ); };
  try { await load(); } finally { console.error = original; }
  assert.equal( seen.length, 1 );
} );

test( "with no section mounted the script does nothing", async () => {
  document.body.innerHTML = "";
  const cron = await load();
  await cron.refresh();
  assert.equal( calls.length, 0 );
  cron.applyEvent( { ...ROW_A } );
} );

test( "text goes in through textContent: markup in a title is shown as text", async () => {
  listReply = () => ( { ok : true, status : 200, json : async () => ( { jobs : [ { ...ROW_A, title : "<img src=x onerror=alert(1)>" } ], caller_is_admin : true } ) } );
  await load();
  assert.equal( byId( "cron-jobs-container" ).querySelectorAll( "img" ).length, 0 );
  assert.equal( item( "duplicate-check" ).querySelector( "[data-testid=cron-title]" )!.textContent, "<img src=x onerror=alert(1)>" );
} );

test( "a job that does not read its switch says so and has its button disabled; a drifted row is marked", async () => {
  listReply = () => ( { ok : true, status : 200, json : async () => ( { jobs : [ { ...ROW_A, honoured : false }, { ...ROW_B, drift : true } ], caller_is_admin : true } ) } );
  await load();
  assert.equal( item( "duplicate-check" ).querySelector( "[data-testid=cron-honoured]" )!.textContent, "does not read its switch yet" );
  assert.equal( flipButton( "duplicate-check" ).disabled, true );
  assert.equal( item( "duplicate-check" ).querySelector( "[data-testid=cron-drift]" ), null );
  assert.equal( item( "wiki-librarian" ).querySelector( "[data-testid=cron-honoured]" )!.textContent, "reads its switch" );
  assert.equal( item( "wiki-librarian" ).querySelector( "[data-testid=cron-drift]" )!.textContent, "changed outside the endpoint" );
  assert.equal( flipButton( "wiki-librarian" ).disabled, false );
} );

test( "a 409 that names the unread switch shows the server's words", async () => {
  await load();
  putReply = () => ( { ok : false, status : 409, json : async () => ( { detail : "'x' does not read its switch yet, so a flip would change nothing; nothing was written" } ) } );
  flipButton( "duplicate-check" ).click(); await flush();
  assert.match( item( "duplicate-check" ).querySelector( "[data-testid=cron-error]" )!.textContent as string, /^'x' does not read its switch yet/ );
} );
