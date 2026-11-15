// The legacy client carries each job's switch in the jobs list (rows 063fc1a8, c80ef763).
//
// Row c80ef763 merged the Scheduled Jobs section into the Background Jobs list: cron-jobs.js no longer owns a
// section, it supplies the switch (window.cronJobs.switchCells) that background-jobs.js draws on line 2 of a
// job's row. Both scripts are plain browser JS in IIFEs, in no tsconfig, so they are loaded the way
// background_jobs_js/ loads its subject: the actual bytes, run through vm.runInThisContext against a DOM
// parsed out of the actual notifications.html. They have no c8 number; these behavioural assertions are
// their gate. The switch rows are the shape GET /api/cron-jobs returns.
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

const HERE       = dirname( fileURLToPath( import.meta.url ) );
const STATIC     = resolve( HERE, "../../../lupin_app/static" );
const HTML       = readFileSync( resolve( STATIC, "html/notifications.html" ), "utf8" );
const CRON_PATH  = resolve( STATIC, "js/cron-jobs.js" );
const CRON_SRC   = readFileSync( CRON_PATH, "utf8" );
const JOBS_PATH  = resolve( STATIC, "js/background-jobs.js" );
const JOBS_SRC   = readFileSync( JOBS_PATH, "utf8" );
const FIXTURE    = JSON.parse( readFileSync( resolve( HERE, "../../fixtures/jobs/jobs-summary.fixture.json" ), "utf8" ) );

type G = Record<string, any>;
const g = globalThis as unknown as G;

const byId  = ( id: string ) => document.getElementById( id ) as HTMLElement;
const flush = () => new Promise( ( r ) => setImmediate( r ) );

const ROW_A = { job : "duplicate-check", title : "Duplicate check", schedule : "cron 0 10-22 * * *", key : "k-a", enabled : true,  honoured : true,  drift : false, last_changed_by : null, last_changed_at : null };
const ROW_B = { job : "wiki-librarian",  title : "Wiki librarian",  schedule : "cron 17 10 * * *",   key : "k-b", enabled : false, honoured : true,  drift : false, last_changed_by : "rick@example.com", last_changed_at : "2026-11-13T19:30:00-05:00" };
const ROW_C = { job : "disk-report",     title : "Disk report",     schedule : "cron 0 19 * * 0",    key : "k-c", enabled : null,  honoured : true,  drift : false, last_changed_by : null, last_changed_at : null };

const clone = <T,>( v: T ): T => JSON.parse( JSON.stringify( v ) );

/** The section exactly as the page declares it: the one list. */
function sectionMarkup(): string {
  const m = HTML.match( /<div class="collapsible-section" id="section-background-jobs">[\s\S]*?\n        <\/div>\n(?=\n)/ );
  assert.ok( m, "notifications.html declares no #section-background-jobs" );
  return m![ 0 ];
}

interface Call { url: string; opts?: { method?: string; body?: string; headers?: Record<string, string> } }
type Reply = () => { ok: boolean; status: number; json: () => Promise<unknown> };
let calls: Call[];
let summaryReply: Reply;
let listReply: Reply;
let putReply: Reply;
let timers: Array<() => void>;

before( () => { if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register(); } );

beforeEach( () => {
  document.body.innerHTML = sectionMarkup();
  timers       = [];
  calls        = [];
  g.window.setInterval = ( fn: () => void ) => { timers.push( fn ); return timers.length; };
  summaryReply = () => ( { ok : true, status : 200, json : async () => clone( FIXTURE ) } );
  listReply    = () => ( { ok : true, status : 200, json : async () => ( { jobs : clone( [ ROW_A, ROW_B, ROW_C ] ), caller_is_admin : true } ) } );
  putReply     = () => ( { ok : true, status : 200, json : async () => ( { ...ROW_A, enabled : false, honoured : true,  drift : false, last_changed_by : "rick@example.com", last_changed_at : "2026-11-13T20:00:00-05:00" } ) } );
  g.fetch = async ( url: string, opts?: Call[ "opts" ] ) => {
    calls.push( { url, opts } );
    if ( opts?.method === "PUT" ) return putReply();
    return url === "/api/cron-jobs" ? listReply() : summaryReply();
  };
  g.localStorage.setItem( "lupin_access_token", "tok" );
  delete g.window.notificationsUI;
} );

/** Load both scripts the way the page does: the switch module first, then the list. */
async function load(): Promise<G> {
  delete g.window.cronJobs;
  delete g.window.backgroundJobs;
  vm.runInThisContext( CRON_SRC, { filename : CRON_PATH } );
  vm.runInThisContext( JOBS_SRC, { filename : JOBS_PATH } );
  await flush();
  return g.window.cronJobs as G;
}

const items = () => Array.from( byId( "background-jobs-container" ).querySelectorAll( "[data-testid=cron-item]" ) ) as HTMLElement[];
const item  = ( job: string ) => items().find( ( i ) => i.getAttribute( "data-job" ) === job )!;
const flipButton = ( job: string ) => item( job ).querySelector( "[data-testid=cron-flip]" ) as HTMLButtonElement;
const stateOf = ( job: string ) => item( job ).querySelector( "[data-testid=cron-state]" )!.textContent;
const errorOf = () => byId( "background-jobs-error" );

test( "the page has no Scheduled Jobs section or sheet; the switch script loads before the list script, and both tokens are fresh", () => {
  assert.equal( HTML.includes( 'id="section-cron-jobs"' ), false );
  assert.equal( HTML.includes( "cron-jobs-legacy.css" ), false );
  assert.equal( HTML.includes( "cron-jobs-container" ), false );
  const cron = HTML.match( /\/static\/js\/cron-jobs\.js\?v=([0-9a-f]{12})/ );
  const jobs = HTML.match( /\/static\/js\/background-jobs\.js\?v=([0-9a-f]{12})/ );
  assert.ok( cron && jobs, "no tokened script tags" );
  assert.ok( cron!.index! < jobs!.index!, "cron-jobs.js must load first: background-jobs.js calls it" );
  assert.equal( cron![ 1 ], createHash( "sha256" ).update( readFileSync( CRON_PATH ) ).digest( "hex" ).slice( 0, 12 ) );
  assert.equal( jobs![ 1 ], createHash( "sha256" ).update( readFileSync( JOBS_PATH ) ).digest( "hex" ).slice( 0, 12 ) );
} );

test( "on load the list asks both doors, draws a switch on each job's second line, counts the off ones, and polls", async () => {
  await load();
  assert.deepEqual( calls.map( ( c ) => c.url ).sort(), [ "/api/cron-jobs", "/api/jobs/summary" ] );
  assert.equal( items().length, 3 );
  assert.deepEqual( [ "duplicate-check", "wiki-librarian", "disk-report" ].map( stateOf ), [ "ON", "OFF", "UNKNOWN" ] );
  assert.equal( byId( "background-jobs-count" ).textContent, "23 (1 off)" );
  assert.equal( item( "duplicate-check" ).querySelector( "[data-testid=cron-schedule]" )!.textContent, "cron 0 10-22 * * *" );
  assert.equal( item( "duplicate-check" ).querySelector( "[data-testid=cron-changed]" )!.textContent, "not reported" );
  assert.equal( item( "wiki-librarian" ).querySelector( "[data-testid=cron-changed]" )!.textContent, "rick@example.com, 2026-11-13 19:30" );
  assert.equal( item( "duplicate-check" ).parentElement!.getAttribute( "data-testid" ), "jobs-line2", "the switch is on line 2" );
  assert.equal( errorOf().hidden, true );
  assert.equal( timers.length, 1 );
  timers[ 0 ]!(); await flush();
  assert.equal( calls.length, 4 );
} );

test( "an administrator sees live buttons; an unknown switch has none to flip", async () => {
  await load();
  assert.equal( flipButton( "duplicate-check" ).disabled, false );
  assert.equal( flipButton( "duplicate-check" ).textContent, "Turn off" );
  assert.equal( flipButton( "wiki-librarian" ).textContent, "Turn on" );
  assert.equal( flipButton( "disk-report" ).disabled, true );
  assert.match( byId( "background-jobs-container" ).querySelector( "[data-testid=cron-note]" )!.textContent as string, /^Flipping a switch takes effect/ );
} );

test( "anyone who is not an administrator sees every button disabled and a read-only note", async () => {
  listReply = () => ( { ok : true, status : 200, json : async () => ( { jobs : clone( [ ROW_A, ROW_B ] ), caller_is_admin : false } ) } );
  await load();
  assert.ok( items().every( ( i ) => ( i.querySelector( "[data-testid=cron-flip]" ) as HTMLButtonElement ).disabled ) );
  assert.match( byId( "background-jobs-container" ).querySelector( "[data-testid=cron-note]" )!.textContent as string, /^Read-only/ );
  flipButton( "duplicate-check" ).click(); await flush();
  assert.equal( calls.filter( ( c ) => c.opts?.method === "PUT" ).length, 0 );
} );

test( "a click sends PUT with the opposite state and the bearer token, then draws the row the server returned, with its second line still open", async () => {
  await load();
  ( byId( "background-jobs-container" ).querySelector( "[data-job=duplicate-check] [data-testid=jobs-disclose]" ) as HTMLElement ).click();
  flipButton( "duplicate-check" ).click(); await flush();
  const put = calls.find( ( c ) => c.opts?.method === "PUT" )!;
  assert.equal( put.url, "/api/cron-jobs/duplicate-check/enabled" );
  assert.deepEqual( JSON.parse( put.opts!.body as string ), { on : false } );
  assert.equal( put.opts!.headers![ "Authorization" ], "Bearer tok" );
  assert.equal( put.opts!.headers![ "Content-Type" ], "application/json" );
  assert.equal( stateOf( "duplicate-check" ), "OFF" );
  assert.equal( byId( "background-jobs-count" ).textContent, "23 (2 off)" );
  assert.equal( item( "duplicate-check" ).querySelector( "[data-testid=cron-changed]" )!.textContent, "rick@example.com, 2026-11-13 20:00" );
  assert.equal( ( item( "duplicate-check" ).closest( "[data-testid=jobs-panel]" ) as HTMLElement ).hidden, false, "the row flipped from stays open" );
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
  assert.equal( byId( "background-jobs-count" ).textContent, "23 (1 off)" );
  const before = byId( "background-jobs-container" ).innerHTML;
  cron.applyEvent( { type : "cron_job_switch_changed", ...ROW_A, job : "no-such-job" } );
  cron.applyEvent( null );
  cron.applyEvent( "text" );
  cron.applyEvent( { type : "cron_job_switch_changed" } );
  assert.equal( byId( "background-jobs-container" ).innerHTML, before );
} );

test( "a frame that arrives with no section on the page is ignored", async () => {
  const cron = await load();
  document.body.innerHTML = "";
  cron.applyEvent( { type : "cron_job_switch_changed", ...ROW_A } );
} );

test( "a failed switch list names itself and the jobs still draw; a failed summary names itself; the refresh button reloads", async () => {
  listReply = () => ( { ok : false, status : 401, json : async () => ( {} ) } );
  await load();
  assert.equal( errorOf().hidden, false );
  assert.equal( errorOf().textContent, "Could not load the scheduled jobs: HTTP 401" );
  assert.equal( byId( "background-jobs-container" ).querySelectorAll( ":scope > [data-testid=jobs-item]" ).length, 23 );
  assert.equal( items().length, 0 );
  summaryReply = () => ( { ok : false, status : 503, json : async () => ( {} ) } );
  byId( "background-jobs-refresh" ).click(); await flush();
  assert.equal( errorOf().textContent, "Could not load the jobs: HTTP 503 Could not load the scheduled jobs: HTTP 401" );
  summaryReply = () => ( { ok : true, status : 200, json : async () => clone( FIXTURE ) } );
  listReply = () => ( { ok : true, status : 200, json : async () => ( { jobs : clone( [ ROW_A ] ), caller_is_admin : true } ) } );
  byId( "background-jobs-refresh" ).click(); await flush();
  assert.equal( errorOf().hidden, true );
  assert.equal( items().length, 1 );
  g.fetch = async () => { throw "plain string"; };
  byId( "background-jobs-refresh" ).click(); await flush();
  assert.match( errorOf().textContent as string, /plain string/ );
} );

test( "authedFetch is used when the page offers it; the bare token path says so loudly", async () => {
  let used = 0;
  g.window.notificationsUI = { authedFetch : async ( url: string, opts: unknown ) => { used += 1; calls.push( { url, opts: opts as Call[ "opts" ] } ); return url === "/api/cron-jobs" ? listReply() : summaryReply(); } };
  await load();
  assert.equal( used, 2, "both doors go through it" );
  delete g.window.notificationsUI;
  const seen: unknown[] = [];
  const original = console.error;
  console.error = ( ...a: unknown[] ) => { seen.push( a ); };
  try { await load(); } finally { console.error = original; }
  assert.ok( seen.length >= 1 );
} );

test( "with no list on the page the scripts do nothing", async () => {
  document.body.innerHTML = "";
  await load();
  await g.window.backgroundJobs.refresh();
  assert.equal( calls.length, 0 );
  g.window.cronJobs.applyEvent( { ...ROW_A } );
} );

test( "text goes in through textContent: markup in a schedule is shown as text", async () => {
  listReply = () => ( { ok : true, status : 200, json : async () => ( { jobs : [ { ...ROW_A, schedule : "<img src=x onerror=alert(1)>" } ], caller_is_admin : true } ) } );
  await load();
  assert.equal( byId( "background-jobs-container" ).querySelectorAll( "img" ).length, 0 );
  assert.equal( item( "duplicate-check" ).querySelector( "[data-testid=cron-schedule]" )!.textContent, "<img src=x onerror=alert(1)>" );
} );

test( "a job that does not read its switch says so and has its button disabled; a drifted row is marked", async () => {
  listReply = () => ( { ok : true, status : 200, json : async () => ( { jobs : [ { ...ROW_A, honoured : false }, { ...ROW_B, drift : true } ], caller_is_admin : true } ) } );
  await load();
  assert.equal( item( "duplicate-check" ).querySelector( "[data-testid=cron-honoured]" )!.textContent, "does not read its switch yet" );
  assert.equal( flipButton( "duplicate-check" ).disabled, true );
  assert.equal( item( "duplicate-check" ).querySelectorAll( "[data-testid=cron-drift]" ).length, 0 );
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

test( "a switch whose job the summary leaves out still gets its own row, marked NOT REPORTING", async () => {
  listReply = () => ( { ok : true, status : 200, json : async () => ( { jobs : [ { ...ROW_A }, { ...ROW_B, job : "reporting-off", title : "Reporting off" } ], caller_is_admin : true } ) } );
  await load();
  const row = byId( "background-jobs-container" ).querySelector( "[data-job=reporting-off]" ) as HTMLElement;
  assert.equal( row.querySelector( "[data-testid=jobs-badge]" )!.textContent, "NOT REPORTING" );
  assert.equal( row.querySelector( "[data-testid=jobs-title]" )!.textContent, "Reporting off" );
  assert.equal( byId( "background-jobs-count" ).textContent, "24 (1 off)" );
  assert.equal( stateOf( "reporting-off" ), "OFF" );
} );

// ── Row c38a49bd step 7: how a row says it reads its switch, an unreadable switch, alarm jobs, and a job inside another ──

const ARBITER = { ...ROW_A, job : "fleet-arbiter",    title : "Fleet arbiter (:8001)", key : "k-arb", reads : "tick", alarm : true,  inside : null };
const JANITOR = { ...ROW_A, job : "worktree-janitor", title : "Worktree janitor",      key : "k-jan", reads : "tick", alarm : false, inside : "fleet-arbiter" };
const putCount = () => calls.filter( ( c ) => c.opts?.method === "PUT" ).length;

test( "a row says whether its job reads the switch at each run or every tick", async () => {
  listReply = () => ( { ok : true, status : 200, json : async () => ( { jobs : [ { ...ROW_A, reads : "run" }, { ...ARBITER } ], caller_is_admin : true } ) } );
  await load();
  assert.equal( item( "duplicate-check" ).querySelector( "[data-testid=cron-honoured]" )!.textContent, "reads its switch at each run" );
  assert.equal( item( "fleet-arbiter" ).querySelector( "[data-testid=cron-honoured]" )!.textContent, "reads its switch every tick" );
} );

test( "a switch the server could not read is a red row that says so, with no button to flip", async () => {
  await load();
  assert.equal( item( "disk-report" ).classList.contains( "cron-unreadable" ), true );
  assert.match( item( "disk-report" ).querySelector( "[data-testid=cron-unreadable]" )!.textContent as string, /^switch unreadable: / );
  assert.equal( flipButton( "disk-report" ).disabled, true );
  assert.equal( item( "duplicate-check" ).classList.contains( "cron-unreadable" ), false );
  assert.equal( item( "duplicate-check" ).querySelectorAll( "[data-testid=cron-unreadable]" ).length, 0 );
} );

test( "turning off an alarm job takes a confirming second click; the first sends nothing", async () => {
  listReply = () => ( { ok : true, status : 200, json : async () => ( { jobs : [ { ...ARBITER } ], caller_is_admin : true } ) } );
  putReply  = () => ( { ok : true, status : 200, json : async () => ( { ...ARBITER, enabled : false } ) } );
  await load();
  flipButton( "fleet-arbiter" ).click(); await flush();
  assert.equal( putCount(), 0 );
  assert.equal( flipButton( "fleet-arbiter" ).textContent, "Confirm: turn off" );
  assert.match( item( "fleet-arbiter" ).querySelector( "[data-testid=cron-error]" )!.textContent as string, /silences what would report it/ );
  flipButton( "fleet-arbiter" ).click(); await flush();
  assert.equal( putCount(), 1 );
  assert.deepEqual( JSON.parse( calls.find( ( c ) => c.opts?.method === "PUT" )!.opts!.body as string ), { on : false } );
  assert.equal( stateOf( "fleet-arbiter" ), "OFF" );
} );

test( "a redraw between the two clicks cancels the confirmation, so one later click only asks again", async () => {
  listReply = () => ( { ok : true, status : 200, json : async () => ( { jobs : [ { ...ARBITER } ], caller_is_admin : true } ) } );
  await load();
  flipButton( "fleet-arbiter" ).click(); await flush();
  await g.window.backgroundJobs.refresh();
  flipButton( "fleet-arbiter" ).click(); await flush();
  assert.equal( putCount(), 0 );
  assert.equal( flipButton( "fleet-arbiter" ).textContent, "Confirm: turn off" );
} );

test( "turning an alarm job on, or any other job off, takes one click", async () => {
  listReply = () => ( { ok : true, status : 200, json : async () => ( { jobs : [ { ...ARBITER, enabled : false }, { ...JANITOR } ], caller_is_admin : true } ) } );
  await load();
  flipButton( "fleet-arbiter" ).click(); await flush();
  assert.equal( putCount(), 1 );
  flipButton( "worktree-janitor" ).click(); await flush();
  assert.equal( putCount(), 2 );
} );

test( "a job that runs inside another says it is off while that job is off", async () => {
  listReply = () => ( { ok : true, status : 200, json : async () => ( { jobs : [ { ...ARBITER, enabled : false }, { ...JANITOR } ], caller_is_admin : true } ) } );
  await load();
  assert.equal( item( "worktree-janitor" ).querySelector( "[data-testid=cron-inside]" )!.textContent, "off while fleet-arbiter is off" );
  listReply = () => ( { ok : true, status : 200, json : async () => ( { jobs : [ { ...ARBITER }, { ...JANITOR } ], caller_is_admin : true } ) } );
  await load();
  assert.equal( item( "worktree-janitor" ).querySelectorAll( "[data-testid=cron-inside]" ).length, 0 );
  listReply = () => ( { ok : true, status : 200, json : async () => ( { jobs : [ { ...JANITOR, inside : "no-such-job" } ], caller_is_admin : true } ) } );
  await load();
  assert.equal( item( "worktree-janitor" ).querySelectorAll( "[data-testid=cron-inside]" ).length, 0 );
} );
