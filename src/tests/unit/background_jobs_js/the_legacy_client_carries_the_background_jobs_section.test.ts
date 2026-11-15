// The legacy client carries the background-jobs list (rows d540113f, c80ef763).
//
// Rick ruled that the accordion belongs in the legacy client and the multiplexer, not on a page of
// its own, and (row c80ef763) that each job's on/off switch is on its second line. This file is the
// legacy half's witness. background-jobs.js and cron-jobs.js are plain browser JS in an
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
import { mergeJobs as muxMerge } from "../../../lupin_app/static/js/multiplexer/jobs/mergedRows";
import { abstractMarkdown as muxAbstract } from "../../../lupin_app/static/js/multiplexer/jobs/abstractText";
import type { JobsSummary } from "../../../lupin_app/static/js/multiplexer/jobs/types";

const HERE      = dirname( fileURLToPath( import.meta.url ) );
const STATIC    = resolve( HERE, "../../../lupin_app/static" );
const HTML      = readFileSync( resolve( STATIC, "html/notifications.html" ), "utf8" );
const JS_PATH   = resolve( STATIC, "js/background-jobs.js" );
const JS_SRC    = readFileSync( JS_PATH, "utf8" );
const CRON_PATH = resolve( STATIC, "js/cron-jobs.js" );
const CRON_SRC  = readFileSync( CRON_PATH, "utf8" );
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

type Reply = () => { ok: boolean; status: number; json: () => Promise<unknown> };
interface Net { urls: string[]; posts: string[]; reply: Reply; cron: Reply }

// The switch rows the page asks for beside the summary (shape of GET /api/cron-jobs). "reporting-off" names no summary job.
const CRON_ROWS = [
  { job : "duplicate-check", title : "Duplicate check", schedule : "cron 0 10-22 * * *", key : "k-a", enabled : true,  honoured : true, drift : false, last_changed_by : null, last_changed_at : null },
  { job : "wiki-librarian",  title : "Wiki librarian",  schedule : "cron 17 10 * * *",   key : "k-b", enabled : false, honoured : true, drift : false, last_changed_by : null, last_changed_at : null },
  { job : "reporting-off",   title : "Reporting off",   schedule : "cron 0 1 * * *",     key : "k-c", enabled : false, honoured : true, drift : false, last_changed_by : null, last_changed_at : null },
];
let net: Net;
let timers: Array<() => void>;

before( () => { if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register(); } );

beforeEach( () => {
  document.body.innerHTML = sectionMarkup();
  timers = [];
  g.window.setInterval = ( fn: () => void ) => { timers.push( fn ); return timers.length; };
  net = { urls : [], posts : [], reply : () => ( { ok : true, status : 200, json : async () => clone( FIXTURE ) } ),
          cron : () => ( { ok : true, status : 200, json : async () => ( { jobs : clone( CRON_ROWS ), caller_is_admin : true } ) } ) };
  g.fetch = async ( url: string, opts?: { method?: string } ) => {
    ( opts?.method === "POST" ? net.posts : net.urls ).push( url );
    return url === "/api/cron-jobs" ? net.cron() : net.reply();
  };
  g.localStorage.setItem( "lupin_access_token", "tok" );
  delete g.window.notificationsUI;
} );

async function load(): Promise<G> {
  delete g.window.backgroundJobs;
  delete g.window.cronJobs;
  vm.runInThisContext( CRON_SRC, { filename : CRON_PATH } );        // the switch module loads first, as on the page
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
  const cron = HTML.match( /\/static\/js\/cron-jobs\.js\?v=([0-9a-f]{12})/ );
  assert.ok( cron, "no tokened script tag for the switch module" );
  assert.equal( cron![ 1 ], createHash( "sha256" ).update( readFileSync( CRON_PATH ) ).digest( "hex" ).slice( 0, 12 ) );
  assert.ok( cron!.index! < m!.index!, "cron-jobs.js loads first: the list calls it" );
  const css = HTML.match( /\/static\/css\/background-jobs-legacy\.css\?v=([0-9a-f]{12})/ );
  assert.ok( css, "no tokened stylesheet link" );
  assert.equal( css![ 1 ], createHash( "sha256" ).update( readFileSync( resolve( STATIC, "css/background-jobs-legacy.css" ) ) ).digest( "hex" ).slice( 0, 12 ) );
} );

test( "on load it fetches both doors with the bearer token, draws 23 jobs and the switch no job names, counts and summarises them, and polls", async () => {
  await load();
  assert.deepEqual( [ ...net.urls ].sort(), [ "/api/cron-jobs", "/api/jobs/summary" ] );
  assert.equal( byId( "background-jobs-container" ).querySelectorAll( ":scope > [data-testid=jobs-item]" ).length, 24 );
  assert.equal( byId( "background-jobs-count" ).textContent, "24 (2 off)" );
  assert.match( byId( "background-jobs-summary" ).textContent as string, /^23 jobs: 10 healthy, 3 failing, 1 silent, 9 unknown$/ );
  assert.equal( byId( "background-jobs-error" ).hidden, true );
  assert.equal( timers.length, 1 );
  timers[ 0 ]!(); await flush();
  assert.equal( net.urls.length, 4 );
} );

test( "the request carries Authorization: Bearer <token> and merges caller headers", async () => {
  let seen: Record<string, string> = {};
  g.fetch = async ( u: string, o: { headers: Record<string, string> } ) => { seen = o.headers; return u === "/api/cron-jobs" ? net.cron() : net.reply(); };
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
  assert.equal( byId( "background-jobs-container" ).children.length, 26 );   // switch note + header row + 24 jobs
  g.fetch = async () => { throw new Error( "network down" ); };
  btn.click(); await flush();
  assert.equal( byId( "background-jobs-error" ).textContent, "Could not load the jobs: network down Could not load the scheduled jobs: network down" );
  g.fetch = async () => { throw "plain text"; };
  btn.click(); await flush();
  assert.match( byId( "background-jobs-error" ).textContent as string, /^Could not load the jobs: plain text/ );
  g.fetch = async ( url: string ) => ( url === "/api/cron-jobs" ? net.cron() : net.reply() );
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
    assert.equal( net.urls.length, 2 );
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

test( "a 422 with a detail shows the detail on the button's status line; one without falls back", async () => {
  const api = await load();
  assert.equal( api.runNowFailureText( 422, "Not started: cannot launch /x.sh" ), "Not started: cannot launch /x.sh" );
  assert.match( api.runNowFailureText( 422, "" ), /cannot be run by hand/ );
  const dup = byId( "background-jobs-container" ).querySelector( "[data-job=duplicate-check]" ) as HTMLElement;
  const btn = dup.querySelector( "[data-testid=jobs-run-now]" ) as HTMLButtonElement;
  const status = () => ( dup.querySelector( "[data-testid=jobs-run-status]" ) as HTMLElement ).textContent;
  net.reply = () => ( { ok : false, status : 422, json : async () => ( { detail : "Not started: cannot launch /var/pip/x.sh" } ) } );
  btn.click(); await flush();
  assert.equal( status(), "Not started: cannot launch /var/pip/x.sh" );
  net.reply = () => ( { ok : false, status : 422, json : async () => { throw new Error( "no body" ); } } );
  btn.click(); await flush();
  assert.match( status() as string, /cannot be run by hand/ );
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

test( "the ⋯ opens and closes lines 2 and 3, every job starts closed, and an open row stays open across a redraw", async () => {
  const api = await load();
  const first = byId( "background-jobs-container" ).querySelector( "[data-testid=jobs-item]" ) as HTMLElement;
  const toggle = first.querySelector( "[data-testid=jobs-disclose]" ) as HTMLElement;
  const panel  = first.querySelector( "[data-testid=jobs-panel]" ) as HTMLElement;
  assert.deepEqual( [ toggle.getAttribute( "aria-expanded" ), panel.hidden, toggle.textContent ], [ "false", true, "⋯" ] );
  assert.equal( first.querySelectorAll( "[data-testid=jobs-line]" ).length, 1 );
  assert.ok( first.querySelector( ".jobs-caret" ) === null, "the expand caret is gone" );
  toggle.click();
  assert.deepEqual( [ toggle.getAttribute( "aria-expanded" ), panel.hidden ], [ "true", false ] );
  assert.equal( panel.querySelectorAll( "[data-testid=jobs-line2], [data-testid=jobs-line3]" ).length, 2 );
  api.repaint();                                                                 // a poll redraws: the row stays open
  const again = byId( "background-jobs-container" ).querySelector( "[data-testid=jobs-item]" ) as HTMLElement;
  assert.equal( again.querySelector( "[data-testid=jobs-disclose]" )!.getAttribute( "aria-expanded" ), "true" );
  ( again.querySelector( "[data-testid=jobs-disclose]" ) as HTMLElement ).click();
  assert.deepEqual( [ again.querySelector( "[data-testid=jobs-disclose]" )!.getAttribute( "aria-expanded" ), ( again.querySelector( "[data-testid=jobs-panel]" ) as HTMLElement ).hidden ], [ "false", true ] );
} );

test( "the first line carries no Scan, Fix or Clears; line 2 carries the figures that apply; line 3 carries Run now or says there is none", async () => {
  await load();
  const dup = byId( "background-jobs-container" ).querySelector( "[data-job=duplicate-check]" ) as HTMLElement;
  const line = dup.querySelector( "[data-testid=jobs-line]" ) as HTMLElement;
  assert.equal( line.querySelectorAll( "[data-testid=jobs-scan-cell], [data-testid=jobs-fix-cell], [data-testid=jobs-clears-cell]" ).length, 0 );
  assert.ok( !( line.textContent as string ).includes( "2,124" ) );
  assert.deepEqual( [ "jobs-fig-scan", "jobs-fig-fix", "jobs-fig-clears" ].map( ( id ) => ( dup.querySelector( `[data-testid=jobs-line2] [data-testid=${ id }]` ) as HTMLElement ).textContent ),
    [ "Scan: 2,124 ▲", "Fix: unfiled 107 ▲", "Clears: never at this rate" ] );
  assert.equal( dup.querySelectorAll( "[data-testid=jobs-line3] [data-testid=jobs-run-now]" ).length, 1 );
  const arbiter = byId( "background-jobs-container" ).querySelector( "[data-job=fleet-arbiter]" ) as HTMLElement;
  assert.equal( arbiter.querySelector( "[data-testid=jobs-line3]" )!.textContent, "Nothing to run by hand, and no targets." );
  const census = byId( "background-jobs-container" ).querySelector( "[data-job=worktree-census]" ) as HTMLElement;
  assert.deepEqual( Array.from( census.querySelectorAll( "[data-testid=jobs-target]" ) ).map( ( t ) => t.getAttribute( "data-target" ) ), [ "cosa-voice", "lupin", "planning-is-prompting" ] );
  assert.equal( census.querySelectorAll( "[data-testid=jobs-target-abstract]" ).length, 3 );
} );

test( "unsafe hrefs are drawn as text in the abstract, never as links, and writer text is never parsed as markup", async () => {
  const api = await load();
  for ( const bad of [ null, "http://x/y", "//evil/x", "/a\\b", "javascript:alert(1)" ] ) assert.equal( api.isSafeHref( bad ), false, String( bad ) );
  assert.equal( api.isSafeHref( "/app/docs?path=lupin/x.md" ), true );
  const job = clone( FIXTURE.jobs.find( ( j ) => j.rows.length > 0 && j.evidence.length > 0 )! );
  job.rows[ 0 ]!.href = "javascript:alert(1)"; job.rows[ 0 ]!.title = "<img src=x onerror=alert(1)>";
  job.evidence[ 0 ]!.href = "//evil/x";
  job.detail_link = "http://evil/x";
  const md = api.abstractMarkdown( job, FIXTURE.generated_at ) as string;
  assert.equal( /(^|[^\\])<img/.test( md ), false, "every < is escaped" );
  assert.ok( md.includes( "\\<img src=x onerror=alert(1)\\>" ) );
  assert.equal( md.includes( "](javascript" ) || md.includes( "](//" ) || md.includes( "](http" ), false );
  assert.equal( md.includes( "Open the detail page" ), false );
  const item = api.renderJob( job, FIXTURE.generated_at, { canRun : false, runNow : async () => "" } ) as HTMLElement;
  assert.ok( item.querySelector( "img" ) === null, "item has no img" );
  assert.equal( decodeURIComponent( item.querySelector( "[data-testid=jobs-abstract]" )!.getAttribute( "data-abstract" ) as string ), md, "the 📋 carries the URI-encoded abstract" );
  assert.ok( item.querySelector( "[data-testid=jobs-abstract]" )!.classList.contains( "abstract-indicator" ) );
  assert.equal( api.mdLink === undefined, true, "the markdown helpers stay private; only abstractMarkdown is exposed" );
} );

test( "the 📋 attribute keeps a percent sign and a newline: %25 and %0A in the attribute, and the same text back out", async () => {
  const api = await load();
  const job = clone( FIXTURE.jobs[ 0 ]! );
  job.reasons[ 0 ]!.text = "100% done\nsecond line";
  const item = api.renderJob( job, FIXTURE.generated_at, { canRun : false, runNow : async () => "" } ) as HTMLElement;
  const attr = item.querySelector( "[data-testid=jobs-abstract]" )!.getAttribute( "data-abstract" ) as string;
  assert.ok( attr.includes( "100%25%20done%0Asecond%20line" ), "the percent is %25 and the newline is %0A" );
  assert.equal( decodeURIComponent( attr ), api.abstractMarkdown( job, FIXTURE.generated_at ) );
  assert.ok( decodeURIComponent( attr ).includes( "100% done\nsecond line" ) );
} );

test( "before the summary has loaded every switch is still drawn, as a NOT REPORTING row, with the banner; a frame repaints it", async () => {
  net.reply = () => ( { ok : false, status : 503, json : async () => ( {} ) } );
  await load();
  const mount = byId( "background-jobs-container" );
  assert.equal( mount.querySelectorAll( ":scope > [data-testid=jobs-item]" ).length, 3, "the three switch rows" );
  assert.equal( mount.querySelector( "[data-job=duplicate-check] [data-testid=jobs-badge]" )!.textContent, "NOT REPORTING" );
  assert.equal( byId( "background-jobs-error" ).textContent, "Could not load the jobs: HTTP 503" );
  assert.equal( byId( "background-jobs-count" ).textContent, "3 (2 off)" );
  assert.equal( byId( "background-jobs-summary" ).textContent, "0 jobs" );
  g.window.cronJobs.applyEvent( { ...CRON_ROWS[ 0 ], enabled : false } );
  assert.equal( mount.querySelector( "[data-job=duplicate-check] [data-testid=cron-state]" )!.textContent, "OFF" );
} );

test( "when neither door has ever answered the list draws nothing but the banner", async () => {
  net.reply = () => ( { ok : false, status : 503, json : async () => ( {} ) } );
  net.cron  = () => ( { ok : false, status : 500, json : async () => ( {} ) } );
  await load();
  const mount = byId( "background-jobs-container" );
  assert.equal( mount.children.length, 0 );
  assert.equal( byId( "background-jobs-error" ).textContent, "Could not load the jobs: HTTP 503 Could not load the scheduled jobs: HTTP 500" );
  assert.equal( byId( "background-jobs-count" ).textContent, "…" );
  g.window.cronJobs.applyEvent( { ...CRON_ROWS[ 0 ], enabled : false } );
  assert.equal( mount.children.length, 0 );
} );

test( "the legacy copy and the multiplexer's copy DRAW THE SAME THING for all 23 fixture jobs (two copies, no shared code)", async () => {
  const api = await load();
  const legacy = byId( "background-jobs-container" );
  const mux    = document.createElement( "div" );
  document.body.appendChild( mux );
  const merged = muxMerge( FIXTURE.jobs, clone( CRON_ROWS ) as never );
  muxRender( document, mux, { ...clone( FIXTURE ), jobs : merged }, { canRun : true, runNow : async () => "", canFlip : true, cronRows : clone( CRON_ROWS ) as never, requestFlip : () => {}, open : new Set() } );
  // Heading levels differ (h2 in the multiplexer, h4 here), so compare text and test ids.
  const shape = ( root: Element ) => [ ...root.querySelectorAll( "[data-testid]" ) ].map( ( e ) => `${ e.getAttribute( "data-testid" ) }|${ e.textContent }` );
  const a = shape( legacy ), b = shape( mux );
  assert.ok( a.length > 300, `only ${ a.length } nodes compared: the comparison is not reaching the jobs` );
  assert.deepEqual( a, b );
  const abstracts = ( root: Element, decode: boolean ) => [ ...root.querySelectorAll( ".abstract-indicator" ) ].map( ( e ) => decode ? decodeURIComponent( e.getAttribute( "data-abstract" ) as string ) : e.getAttribute( "data-abstract" ) );
  assert.equal( abstracts( legacy, true ).length, 24 + 8, "24 rows and 8 target lines" );
  assert.deepEqual( abstracts( legacy, true ), abstracts( mux, false ), "the two copies write the same abstract for every row and target" );
  assert.equal( muxAbstract( FIXTURE.jobs[ 0 ]!, FIXTURE.generated_at ), api.abstractMarkdown( FIXTURE.jobs[ 0 ]!, FIXTURE.generated_at ) );
  assert.equal( api.headerLine( [] ), "0 jobs" );
  assert.equal( api.headerLine( [ FIXTURE.jobs[ 0 ]! ] ).startsWith( "1 job: 1 " ), true );
  assert.equal( api.formatWhen( "2026-11-07T19:31:02-05:00", FIXTURE.generated_at ), "19:31" );
  assert.equal( api.formatWhen( null, "" ), "not reported" );
  assert.equal( api.formatWhen( "soon", "" ), "soon" );
} );

test( "the legacy toolbar button and section header both carry 🔁, and no other toolbar button does (row 288165d6)", () => {
  const buttons = [ ...HTML.matchAll( /<button class="toolbar-btn[^>]*>([^<]*)<\/button>/g ) ].map( ( m ) => m[ 0 ] );
  assert.ok( buttons.length > 15, "the toolbar buttons were not found: the uniqueness check would prove nothing" );
  const mine = buttons.filter( ( b ) => b.includes( 'data-testid="background-jobs-toolbar-btn"' ) );
  assert.equal( mine.length, 1 );
  assert.ok( mine[ 0 ]!.endsWith( ">🔁</button>" ) );
  assert.deepEqual( buttons.filter( ( b ) => b !== mine[ 0 ] && b.includes( ">🔁<" ) ), [] );
  document.body.innerHTML = sectionMarkup();
  assert.ok( ( document.querySelector( "#section-background-jobs h3" )!.textContent as string ).startsWith( "🔁 Background Jobs" ) );
} );

test( "the legacy sort defaults to service name A to Z, whatever the state, running flag or attempt time (row 1ac04991, replacing row 300af681)", async () => {
  const api = await load();
  const base = FIXTURE.jobs[ 0 ]!;
  const mk = ( name: string, state: string, at: string | null, running = false ) =>
    ( { ...clone( base ), job : name, title : name, target : null, state, running, last_attempt : at === null ? null : { ...clone( base.last_attempt! ), started_at : at } } );
  const jobs = [
    mk( "u", "unknown", null ), mk( "s", "silent", "2026-11-09T10:00:00-05:00" ), mk( "f", "failing", "2026-11-09T10:00:00-05:00" ),
    mk( "b", "behind", "2026-11-09T10:00:00-05:00" ), mk( "h-old", "healthy", "2026-11-08T10:00:00-05:00" ), mk( "h-new", "healthy", "2026-11-09T09:00:00-05:00" ),
    mk( "h-none", "healthy", null ), mk( "h-bad", "healthy", "not a time" ), mk( "z-run", "failing", "2026-11-01T10:00:00-05:00", true ),
    mk( "h-utc", "healthy", "2026-11-09T14:30:00+00:00" ),
  ];
  const before = jobs.map( ( j ) => j.job );
  assert.deepEqual( api.sortJobs( jobs ).map( ( j: { job: string } ) => j.job ), [ "b", "f", "h-bad", "h-new", "h-none", "h-old", "h-utc", "s", "u", "z-run" ] );
  assert.deepEqual( jobs.map( ( j ) => j.job ), before, "sortJobs must not touch its input" );
  assert.equal( api.headerLine( jobs.filter( ( j ) => [ "u", "f", "h-old" ].includes( j.job ) ) ), "3 jobs: 1 healthy, 1 failing, 1 unknown" );
} );

test( "the legacy accordion ends with the switched-off line when the server sends one (row 4aa0ba1b)", async () => {
  const api = await load();
  const mount = byId( "background-jobs-container" );
  api.renderAccordion( mount, clone( FIXTURE ), { canRun : false, runNow : async () => "" } );
  assert.ok( mount.querySelector( "[data-testid=background-jobs-off-line]" ) === null, "the off-line is absent" );
  api.renderAccordion( mount, { ...clone( FIXTURE ), reporting_off_line : "8 jobs have reporting switched off" }, { canRun : false, runNow : async () => "" } );
  const last = mount.lastElementChild as HTMLElement;
  assert.equal( last.getAttribute( "data-testid" ), "background-jobs-off-line" );
  assert.equal( last.textContent, "8 jobs have reporting switched off" );
  assert.equal( mount.children.length, 26 );   // switch note + header row + 23 jobs + the off line
} );

test( "row 399a266f: with notificationsUI present the request goes through its authedFetch, so a stale stored token is refreshed before it is sent", async () => {
  const sent: Array<Record<string, string>> = [];
  let refreshed = 0;
  g.localStorage.setItem( "lupin_access_token", "stale" );
  g.window.notificationsUI = {
    authedFetch : async ( url: string, o: { headers?: Record<string, string> } ) => {
      refreshed++;
      g.localStorage.setItem( "lupin_access_token", "fresh" );          // what ensureValidToken does
      return g.fetch( url, { ...o, headers : { Authorization : "Bearer fresh", ...( o.headers ?? {} ) } } );
    }
  };
  g.fetch = async ( u: string, o: { headers: Record<string, string> } ) => { sent.push( o.headers ); return u === "/api/cron-jobs" ? net.cron() : net.reply(); };
  await load();
  assert.equal( refreshed, 2, "both doors" );
  assert.equal( sent.length, 2 );
  assert.equal( sent[ 0 ]!.Authorization, "Bearer fresh" );
} );

test( "row 399a266f: without notificationsUI the fallback still sends the stored token, and says so loudly on the console", async () => {
  const errs: string[] = [];
  const orig = console.error;
  console.error = ( ...a: unknown[] ) => { errs.push( a.join( " " ) ); };
  try { await load(); } finally { console.error = orig; }
  assert.deepEqual( [ ...net.urls ].sort(), [ "/api/cron-jobs", "/api/jobs/summary" ] );
  assert.ok( errs.some( ( e ) => e.includes( "UNREFRESHED" ) ), "no loud console error" );
} );

// ─── Sort by name and by health, header row (row 4b807ffd) ─────────────────

test( "the legacy sort orders: name A-Z and Z-A, health healthy-to-unknown and back, unknown ids refused, input untouched", async () => {
  const api = await load();
  const base = FIXTURE.jobs[ 0 ]!;
  const mk = ( name: string, state: string, target: string | null = null, running = false ) => ( { ...clone( base ), job : name, title : name, target, state, running } );
  const jobs = [ mk( "beta", "unknown" ), mk( "alpha", "healthy", "y" ), mk( "alpha", "silent", "x", true ), mk( "Gamma", "failing" ), mk( "d", "behind" ) ];
  const before = jobs.map( ( j ) => j.job + ( j.target ?? "" ) );
  const label = ( out: Array<{ title: string; target: string | null }> ) => out.map( ( j ) => j.title + ( j.target === null ? "" : "/" + j.target ) );
  assert.deepEqual( api.SORT_ORDERS.map( ( o: { id: string; label: string } ) => [ o.id, o.label ] ), [ [ "name", "Service" ], [ "health", "Status" ], [ "last-run", "Last run" ] ] );
  assert.deepEqual( label( api.sortJobs( jobs, "name", "asc" ) ), [ "alpha/x", "alpha/y", "beta", "d", "Gamma" ] );
  assert.deepEqual( label( api.sortJobs( jobs, "name", "desc" ) ), [ "Gamma", "d", "beta", "alpha/y", "alpha/x" ] );
  assert.deepEqual( api.sortJobs( jobs, "health", "asc" ).map( ( j: { state: string } ) => j.state ), [ "healthy", "behind", "silent", "unknown", "failing" ] );
  assert.deepEqual( api.sortJobs( jobs, "health", "desc" ).map( ( j: { state: string } ) => j.state ), [ "failing", "unknown", "silent", "behind", "healthy" ] );
  const at = ( name: string, when: string | null ) => ( { ...clone( base ), job : name, title : name, target : null, state : "healthy", running : false,
    last_attempt : when === null ? null : { ...clone( base.last_attempt! ), started_at : when } } );
  const runs = [ at( "new", "2026-11-09T12:00:00-05:00" ), at( "none", null ), at( "old", "2026-11-01T12:00:00-05:00" ), at( "bad", "not a time" ), at( "utc", "2026-11-09T18:00:00+00:00" ) ];
  assert.deepEqual( api.sortJobs( runs, "last-run", "asc" ).map( ( j: { job: string } ) => j.job ), [ "bad", "none", "old", "new", "utc" ] );
  assert.deepEqual( api.sortJobs( runs, "last-run", "desc" ).map( ( j: { job: string } ) => j.job ), [ "utc", "new", "old", "bad", "none" ] );
  assert.throws( () => api.sortJobs( jobs, "nope", "asc" ), /unknown sort order: nope/ );
  assert.deepEqual( jobs.map( ( j ) => j.job + ( j.target ?? "" ) ), before );
} );

test( "the legacy accordion draws a header row naming every column, sorts on a heading click, and keeps the pick across a refresh", async () => {
  const api = await load();
  const mount = byId( "background-jobs-container" );
  const heads = Array.from( mount.querySelectorAll( "[data-testid=jobs-header] [role=columnheader]" ) ).map( ( h ) => h.textContent );
  assert.deepEqual( heads, [ "", "", "Service", "Status", "Last run", "Last finished", "" ] );
  const titles = () => Array.from( mount.querySelectorAll( ":scope > [data-testid=jobs-item] > .jobs-heading [data-testid=jobs-title]" ) ).map( ( t ) => t.textContent );
  const click  = ( id: string ) => ( mount.querySelector( "[data-testid=" + id + "]" ) as HTMLElement ).click();
  click( "jobs-sort-name" );
  const asc = titles();
  assert.deepEqual( asc, [ ...asc ].sort( ( a, b ) => a!.localeCompare( b! ) ) );
  assert.equal( mount.querySelector( "[data-testid=jobs-sort-name]" )!.textContent, "Service ▲" );
  click( "jobs-sort-name" );
  assert.deepEqual( titles(), [ ...asc ].reverse() );
  await api.refresh(); await flush();                                             // a poll redraws: the pick stays
  assert.deepEqual( titles(), [ ...asc ].reverse() );
  click( "jobs-sort-name" );
  assert.ok( mount.querySelector( "[aria-sort=ascending]" ) === null, "third click returns to the default order" );
  click( "jobs-sort-health" ); click( "jobs-sort-health" );
  const states = Array.from( mount.querySelectorAll( ":scope > [data-testid=jobs-item]" ) ).map( ( i ) => i.getAttribute( "data-state" ) );
  assert.equal( states[ 0 ], "failing" );
  assert.equal( states[ states.length - 1 ], "healthy" );
} );

test( "both sheets size the line grid so it fits its container: the ⋯, dot and 📋 tracks and the status track are fixed, every text track can shrink (rows 4b807ffd, c80ef763)", () => {
  for ( const sheet of [ "css/background-jobs-legacy.css", "css/multiplexer/background-jobs.css" ] ) {
    const css = readFileSync( resolve( STATIC, sheet ), "utf8" );
    const m   = css.match( /\.jobs-line,\s*\.jobs-line-grid \{[^}]*?grid-template-columns\s*:\s*([^;]+);/ );
    assert.ok( m, sheet + " declares no line grid" );
    const tracks = m![ 1 ]!.replace( /\/\*.*$/, "" ).match( /minmax\([^)]*\)|\S+/g )!;
    assert.equal( tracks.length, 7, sheet );
    assert.deepEqual( tracks.slice( 0, 2 ), [ "1.75rem", "1.25rem" ] );
    assert.equal( tracks[ 3 ], "8rem", "the status column stays narrow" );
    assert.equal( tracks[ 6 ], "1.75rem", "the 📋 column is narrow" );
    for ( const i of [ 2, 4, 5 ] ) assert.match( tracks[ i ]!, /^minmax\(0, [\d.]+fr\)$/, sheet + " track " + i + " must shrink" );
  }
} );
