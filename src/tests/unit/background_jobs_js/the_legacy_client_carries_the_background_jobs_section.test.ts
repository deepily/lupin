// The legacy notifications client carries the background-jobs section (row d540113f).
//
// Rick ruled that the accordion belongs in the legacy client and the multiplexer, not on a page of
// its own. This file is the legacy half's witness. background-jobs.js is plain browser JS in an
// IIFE with no exports and in no tsconfig, so it is loaded the way notifications_js/ loads its
// subject: the actual bytes, run through vm.runInThisContext against a DOM parsed out of the
// actual notifications.html. It has no c8 number, because c8 cannot see a vm-run string. These
// behavioural assertions are its gate. The data is the committed 23-job fixture.
//
// The two clients share no runtime code (ruling 87812328). The last test compares what each draws
// for every fixture job: two independent copies that agree on 23 jobs, not one copy twice.
//
// Run via: npx tsx --test src/tests/unit/background_jobs_js/the_legacy_client_carries_the_background_jobs_section.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { renderAccordion as muxRender } from "../../../lupin_app/static/js/multiplexer/jobs/jobsRender";
import type { JobsSummary } from "../../../lupin_app/static/js/multiplexer/jobs/types";

const HERE      = dirname( fileURLToPath( import.meta.url ) );
const STATIC    = resolve( HERE, "../../../lupin_app/static" );
const HTML      = readFileSync( resolve( STATIC, "html/notifications.html" ), "utf8" );
const JS_PATH   = resolve( STATIC, "js/background-jobs.js" );
const JS_SRC    = readFileSync( JS_PATH, "utf8" );
const FIXTURE   = JSON.parse( readFileSync( resolve( HERE, "../../fixtures/jobs/jobs-summary.fixture.json" ), "utf8" ) ) as JobsSummary;

type G = Record<string, any>;
const g = globalThis as unknown as G;

const clone = <T,>( v: T ): T => JSON.parse( JSON.stringify( v ) ) as T;
const byId  = ( id: string ) => document.getElementById( id ) as HTMLElement;
const flush = () => new Promise( ( r ) => setImmediate( r ) );

/** The section exactly as the page declares it. */
function sectionMarkup(): string {
  const m = HTML.match( /<div class="collapsible-section" id="section-background-jobs">[\s\S]*?\n        <\/div>\n(?=\n)/ );
  assert.ok( m, "notifications.html declares no #section-background-jobs" );
  return m![ 0 ];
}

interface Net { urls: string[]; posts: string[]; reply: () => { ok: boolean; status: number; json: () => Promise<unknown> } }
let net: Net;
let timers: Array<() => void>;

before( () => { if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register(); } );

beforeEach( () => {
  document.body.innerHTML = sectionMarkup();
  timers = [];
  g.window.setInterval = ( fn: () => void ) => { timers.push( fn ); return timers.length; };
  net = { urls : [], posts : [], reply : () => ( { ok : true, status : 200, json : async () => clone( FIXTURE ) } ) };
  g.fetch = async ( url: string, opts?: { method?: string } ) => {
    ( opts?.method === "POST" ? net.posts : net.urls ).push( url );
    return net.reply();
  };
  g.localStorage.setItem( "lupin_access_token", "tok" );
} );

async function load(): Promise<G> {
  delete g.window.backgroundJobs;
  vm.runInThisContext( JS_SRC, { filename : JS_PATH } );
  await flush();
  return g.window.backgroundJobs as G;
}

test( "the page puts the section right after the Epic Board, with a toolbar button after the Epic Board button", () => {
  const epic = HTML.indexOf( 'id="section-epic-board"' );
  const mine = HTML.indexOf( 'id="section-background-jobs"' );
  const next = HTML.indexOf( 'id="filter-settings-section"' );
  assert.ok( epic > 0 && epic < mine && mine < next, "section order" );
  const bar = HTML.indexOf( 'data-section="section-epic-board"' );
  assert.ok( bar > 0 && HTML.indexOf( 'data-section="section-background-jobs"' ) > bar );
  assert.ok( HTML.includes( 'data-testid="background-jobs-toolbar-btn"' ) );
  assert.equal( ( HTML.match( /id="section-background-jobs"/g ) ?? [] ).length, 1 );
} );

test( "the script tag's ?v= token is the first 12 hex of the file's sha256, so a changed file cannot be served stale", () => {
  const m = HTML.match( /\/static\/js\/background-jobs\.js\?v=([0-9a-f]{12})/ );
  assert.ok( m, "no tokened script tag" );
  assert.equal( m![ 1 ], createHash( "sha256" ).update( readFileSync( JS_PATH ) ).digest( "hex" ).slice( 0, 12 ) );
  const css = HTML.match( /\/static\/css\/background-jobs-legacy\.css\?v=([0-9a-f]{12})/ );
  assert.ok( css, "no tokened stylesheet link" );
  assert.equal( css![ 1 ], createHash( "sha256" ).update( readFileSync( resolve( STATIC, "css/background-jobs-legacy.css" ) ) ).digest( "hex" ).slice( 0, 12 ) );
} );

test( "on load it fetches /api/jobs/summary with the bearer token, draws 23 jobs, counts and summarises them, and polls", async () => {
  await load();
  assert.deepEqual( net.urls, [ "/api/jobs/summary" ] );
  assert.equal( byId( "background-jobs-container" ).querySelectorAll( ":scope > [data-testid=jobs-item]" ).length, 23 );
  assert.equal( byId( "background-jobs-count" ).textContent, "23" );
  assert.match( byId( "background-jobs-summary" ).textContent as string, /^23 jobs: 9 unknown, 2 silent, 3 failing, 9 healthy$/ );
  assert.equal( byId( "background-jobs-error" ).hidden, true );
  assert.equal( timers.length, 1 );
  timers[ 0 ]!(); await flush();
  assert.equal( net.urls.length, 2 );
} );

test( "the request carries Authorization: Bearer <token> and merges caller headers", async () => {
  let seen: Record<string, string> = {};
  g.fetch = async ( _u: string, o: { headers: Record<string, string> } ) => { seen = o.headers; return net.reply(); };
  await load();
  assert.equal( seen.Authorization, "Bearer tok" );
  g.localStorage.removeItem( "lupin_access_token" );
  await g.window.backgroundJobs.refresh();
  assert.equal( seen.Authorization, "Bearer " );
} );

test( "the refresh button reloads without collapsing the section; a failed reload shows the reason and keeps the last good list", async () => {
  await load();
  const btn = byId( "background-jobs-refresh" );
  net.reply = () => ( { ok : false, status : 503, json : async () => ( {} ) } );
  btn.click(); await flush();
  assert.equal( byId( "background-jobs-error" ).hidden, false );
  assert.equal( byId( "background-jobs-error" ).textContent, "Could not load the jobs: HTTP 503" );
  assert.equal( byId( "background-jobs-container" ).children.length, 23 );
  g.fetch = async () => { throw new Error( "network down" ); };
  btn.click(); await flush();
  assert.equal( byId( "background-jobs-error" ).textContent, "Could not load the jobs: network down" );
  g.fetch = async () => { throw "plain text"; };
  btn.click(); await flush();
  assert.equal( byId( "background-jobs-error" ).textContent, "Could not load the jobs: plain text" );
  g.fetch = async () => net.reply();
  net.reply = () => ( { ok : true, status : 200, json : async () => clone( FIXTURE ) } );
  btn.click(); await flush();
  assert.equal( byId( "background-jobs-error" ).hidden, true );
} );

test( "a page without the section does nothing and throws nothing", async () => {
  document.body.innerHTML = "";
  const api = await load();
  assert.equal( net.urls.length, 0 );
  await api.refresh();
  assert.equal( net.urls.length, 0 );
} );

test( "a script loaded while the page is still parsing waits for DOMContentLoaded", async () => {
  Object.defineProperty( document, "readyState", { value : "loading", configurable : true } );
  try {
    delete g.window.backgroundJobs;
    vm.runInThisContext( JS_SRC, { filename : JS_PATH } );
    await flush();
    assert.equal( net.urls.length, 0 );
    document.dispatchEvent( new Event( "DOMContentLoaded" ) ); await flush();
    assert.equal( net.urls.length, 1 );
  } finally { delete ( document as unknown as G ).readyState; }
} );

test( "Run now is hidden when the caller is not the operator", async () => {
  net.reply = () => ( { ok : true, status : 200, json : async () => ( { ...clone( FIXTURE ), caller_is_operator : false } ) } );
  await load();
  assert.equal( byId( "background-jobs-container" ).querySelectorAll( "[data-testid=jobs-run-now]" ).length, 0 );
} );

test( "Run now posts to the job's own door and prints the outcome beside the button", async () => {
  await load();
  const dup = byId( "background-jobs-container" ).querySelector( "[data-job=duplicate-check]" ) as HTMLElement;
  const btn = dup.querySelector( "[data-testid=jobs-run-now]" ) as HTMLButtonElement;
  net.reply = () => ( { ok : true, status : 200, json : async () => ( { started_at : "2026-11-07T20:31:00-05:00", pid : 4242 } ) } );
  btn.click();
  assert.equal( btn.disabled, true );
  await flush();
  assert.deepEqual( net.posts, [ "/api/jobs/duplicate-check/run" ] );
  assert.equal( ( dup.querySelector( "[data-testid=jobs-run-status]" ) as HTMLElement ).textContent, "Started at 2026-11-07T20:31:00-05:00 (pid 4242)." );
  assert.equal( btn.disabled, false );
} );

test( "each Run now refusal gets its own plain sentence, and a network failure is named", async () => {
  const api = await load();
  const cases: Array<[ number, RegExp ]> = [ [ 403, /Only Rick's login/ ], [ 404, /does not know/ ], [ 409, /run lock is held/ ], [ 422, /cannot be run by hand/ ] ];
  for ( const [ status, re ] of cases ) assert.match( api.runNowFailureText( status ), re );
  assert.equal( api.runNowFailureText( 500 ), "Run now failed (HTTP 500)." );
  const dup = byId( "background-jobs-container" ).querySelector( "[data-job=duplicate-check]" ) as HTMLElement;
  const btn = dup.querySelector( "[data-testid=jobs-run-now]" ) as HTMLButtonElement;
  const status = () => ( dup.querySelector( "[data-testid=jobs-run-status]" ) as HTMLElement ).textContent;
  net.reply = () => ( { ok : false, status : 409, json : async () => ( {} ) } );
  btn.click(); await flush();
  assert.match( status() as string, /run lock is held/ );
  g.fetch = async () => { throw new Error( "boom" ); };
  btn.click(); await flush();
  assert.equal( status(), "Run now failed: Error: boom" );
  assert.equal( api.runNowPath( { job : "a b", target : "x/y" } ), "/api/jobs/a%20b/run?target=x%2Fy" );
  assert.equal( api.runNowPath( { job : "a", target : null } ), "/api/jobs/a/run" );
  // a rejected runNow promise (not reached through runNow itself) is reported too
  const item = api.renderJob( { ...clone( FIXTURE.jobs[ 0 ]! ), runnable : true, targets : [] }, FIXTURE.generated_at, { canRun : true, runNow : () => Promise.reject( "nope" ) } ) as HTMLElement;
  ( item.querySelector( "[data-testid=jobs-run-now]" ) as HTMLElement ).click(); await flush();
  assert.equal( ( item.querySelector( "[data-testid=jobs-run-status]" ) as HTMLElement ).textContent, "Run now failed: nope" );
} );

test( "clicking a line expands its panel and clicking again collapses it; every job starts collapsed", async () => {
  await load();
  const first = byId( "background-jobs-container" ).querySelector( "[data-testid=jobs-item]" ) as HTMLElement;
  const line  = first.querySelector( "[data-testid=jobs-line]" ) as HTMLElement;
  const panel = first.querySelector( "[data-testid=jobs-panel]" ) as HTMLElement;
  assert.deepEqual( [ line.getAttribute( "aria-expanded" ), panel.hidden ], [ "false", true ] );
  line.click();
  assert.deepEqual( [ line.getAttribute( "aria-expanded" ), panel.hidden, line.querySelector( ".jobs-caret" )!.textContent ], [ "true", false, "▼" ] );
  line.click();
  assert.deepEqual( [ line.getAttribute( "aria-expanded" ), panel.hidden, line.querySelector( ".jobs-caret" )!.textContent ], [ "false", true, "▶" ] );
} );

test( "unsafe hrefs are drawn as text, never as links, and writer text is never parsed as markup", async () => {
  const api = await load();
  for ( const bad of [ null, "http://x/y", "//evil/x", "/a\\b", "javascript:alert(1)" ] ) assert.equal( api.isSafeHref( bad ), false, String( bad ) );
  assert.equal( api.isSafeHref( "/app/docs?path=lupin/x.md" ), true );
  const job = clone( FIXTURE.jobs.find( ( j ) => j.rows.length > 0 && j.evidence.length > 0 )! );
  job.rows[ 0 ]!.href = "javascript:alert(1)"; job.rows[ 0 ]!.title = "<img src=x onerror=alert(1)>";
  job.evidence[ 0 ]!.href = "//evil/x";
  job.detail_link = "http://evil/x";
  const item = api.renderJob( job, FIXTURE.generated_at, { canRun : false, runNow : async () => "" } ) as HTMLElement;
  assert.equal( item.querySelector( "img" ), null );
  assert.equal( item.querySelector( "[data-testid=jobs-row-title]" )!.textContent, "<img src=x onerror=alert(1)>" );
  assert.equal( item.querySelector( "[data-testid=jobs-evidence-path]" ) !== null, true );
  assert.equal( item.querySelector( "[data-testid=jobs-detail-link]" ), null );
} );

test( "the legacy copy and the multiplexer's copy DRAW THE SAME THING for all 23 fixture jobs (two copies, no shared code)", async () => {
  const api = await load();
  const legacy = byId( "background-jobs-container" );
  const mux    = document.createElement( "div" );
  document.body.appendChild( mux );
  muxRender( document, mux, clone( FIXTURE ), { canRun : true, runNow : async () => "" } );
  // Heading levels differ (h2 in the multiplexer, h4 here), so compare text and test ids.
  const shape = ( root: Element ) => [ ...root.querySelectorAll( "[data-testid]" ) ].map( ( e ) => `${ e.getAttribute( "data-testid" ) }|${ e.textContent }` );
  const a = shape( legacy ), b = shape( mux );
  assert.ok( a.length > 900, `only ${ a.length } nodes compared: the comparison is not reaching the jobs` );
  assert.deepEqual( a, b );
  assert.equal( api.headerLine( [] ), "0 jobs" );
  assert.equal( api.headerLine( [ FIXTURE.jobs[ 0 ]! ] ).startsWith( "1 job: 1 " ), true );
  assert.equal( api.formatWhen( "2026-11-07T19:31:02-05:00", FIXTURE.generated_at ), "19:31" );
  assert.equal( api.formatWhen( null, "" ), "not reported" );
  assert.equal( api.formatWhen( "soon", "" ), "soon" );
} );
