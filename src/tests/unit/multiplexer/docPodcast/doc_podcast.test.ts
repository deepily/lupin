// Row e23b9ed6 — THE DOC VIEWER'S "MAKE A PODCAST" BUTTON.
//
// The doc viewer page is the one page both clients show a file through, so this module is the one place
// the button's behaviour lives. Every case drives the real module over a real DOM (happy-dom) with the
// network replaced by a scripted fetch. The assertions name the user-visible result: whether the button is
// shown, what the confirmation says, how many posts went out, and what the status line reads.
//
// Run: npx tsx --test src/tests/unit/multiplexer/docPodcast/doc_podcast.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import {
  CHECK_URL, START_URL, FILE_EVENT, IDS,
  humanSize, confirmCopy, refusalText, createDocPodcast, bindDocPodcast,
} from "../../../../lupin_app/static/js/multiplexer/docPodcast/docPodcast";
import type { DocWindowLike } from "../../../../lupin_app/static/js/multiplexer/docPodcast/docPodcast";

before( () => { if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register(); } );

const PATH = "lupin/io/tmp/summary.md";

function buildPage(): void {
  document.body.innerHTML = `
    <div id="${IDS.toolbar}" hidden>
      <button id="${IDS.button}" hidden>Make a podcast</button>
      <span id="${IDS.status}"></span>
    </div>
    <div id="${IDS.panel}" hidden>
      <span id="${IDS.text}"></span>
      <button id="${IDS.yes}">Yes</button>
      <button id="${IDS.cancel}">Cancel</button>
    </div>`;
}
beforeEach( buildPage );

const $ = ( id: string ): HTMLElement => document.getElementById( id ) as HTMLElement;
const answer = ( status: number, body: unknown ): Response =>
  ( { ok: status >= 200 && status < 300, status, json: async () => body } as unknown as Response );
const notJson = ( status: number ): Response =>
  ( { ok: status >= 200 && status < 300, status, json: async () => { throw new SyntaxError( "no json" ); } } as unknown as Response );

interface Call { url: string; init: RequestInit }
function scripted( ...replies: Array<Response | Error | Promise<Response>> ) {
  const calls: Call[] = [];
  const authedFetch = async ( url: string, init: RequestInit ): Promise<Response> => {
    calls.push( { url, init } );
    const next = replies.shift();
    if ( next === undefined ) throw new Error( "unscripted fetch" );
    if ( next instanceof Error ) throw next;
    return next;
  };
  return { calls, authedFetch };
}
const CHECK_OK = () => answer( 200, { ok: true, name: "summary.md", size: 4300 } );
const flush = async (): Promise<void> => { await new Promise( ( r ) => setTimeout( r, 0 ) ); };

// ---- the helpers ----

test( "humanSize reads bytes, kilobytes and megabytes", () => {
  assert.equal( humanSize( 812 ), "812 B" );
  assert.equal( humanSize( 4300 ), "4.2 KB" );
  assert.equal( humanSize( 1363149 ), "1.3 MB" );
} );

test( "the confirmation names the file and its size", () => {
  const text = confirmCopy( "summary.md", 4300 );
  assert.match( text, /summary\.md/ );
  assert.match( text, /4\.2 KB/ );
} );

test( "refusalText prefers the server's sentence and falls back to the status", () => {
  assert.equal( refusalText( 400, { detail: { code: "wrong_kind", message: "It is a .png file." } } ), "It is a .png file." );
  assert.equal( refusalText( 500, null ), "Podcast failed (HTTP 500)" );
  assert.equal( refusalText( 500, { detail: "text" } ), "Podcast failed (HTTP 500)" );
  assert.equal( refusalText( 500, { detail: { message: "" } } ), "Podcast failed (HTTP 500)" );
  assert.equal( refusalText( 500, { detail: { message: 7 } } ), "Podcast failed (HTTP 500)" );
} );

// ---- the check decides whether there is a button ----

test( "a file the server accepts shows the button and the toolbar, and asks with the page's path", async () => {
  const net = scripted( CHECK_OK() );
  const pod = createDocPodcast( { doc: document, authedFetch: net.authedFetch, path: PATH } );
  assert.equal( $( IDS.button ).hidden, true );
  await pod.start();
  assert.equal( pod.state(), "ready" );
  assert.equal( $( IDS.button ).hidden, false );
  assert.equal( $( IDS.toolbar ).hidden, false );
  assert.equal( net.calls.length, 1 );
  assert.equal( net.calls[ 0 ]!.url, `${CHECK_URL}?path=${encodeURIComponent( PATH )}` );
} );

for ( const [ label, reply ] of [
  [ "a 400 refusal", answer( 400, { detail: { code: "wrong_kind", message: "x" } } ) ],
  [ "a 403", answer( 403, { detail: { code: "not_a_person", message: "x" } } ) ],
  [ "a body that is not JSON", notJson( 200 ) ],
  [ "a body with no name", answer( 200, { ok: true } ) ],
  [ "a null body", answer( 200, null ) ],
  [ "a network failure", new Error( "offline" ) ],
] as Array<[ string, Response | Error ]> ) {
  test( `${label} on the check leaves the page without a button`, async () => {
    const net = scripted( reply );
    const pod = createDocPodcast( { doc: document, authedFetch: net.authedFetch, path: PATH } );
    await pod.start();
    assert.equal( pod.state(), "hidden" );
    assert.equal( $( IDS.button ).hidden, true );
    assert.equal( $( IDS.toolbar ).hidden, true );
  } );
}

test( "starting twice asks the server once", async () => {
  const net = scripted( CHECK_OK() );
  const pod = createDocPodcast( { doc: document, authedFetch: net.authedFetch, path: PATH } );
  await pod.start();
  await pod.start();
  assert.equal( net.calls.length, 1 );
} );

// ---- the click, the confirmation, the post ----

async function ready( ...after: Array<Response | Error | Promise<Response>> ) {
  const net = scripted( CHECK_OK(), ...after );
  const pod = createDocPodcast( { doc: document, authedFetch: net.authedFetch, path: PATH } );
  await pod.start();
  return { net, pod };
}

test( "a click opens the confirmation with the file named, and posts nothing", async () => {
  const { net, pod } = await ready();
  $( IDS.button ).click();
  assert.equal( pod.state(), "confirming" );
  assert.equal( $( IDS.panel ).hidden, false );
  assert.match( $( IDS.text ).textContent as string, /summary\.md/ );
  assert.equal( net.calls.length, 1, "only the check has gone out" );
} );

test( "Cancel closes the confirmation, posts nothing and leaves the button usable", async () => {
  const { net, pod } = await ready();
  $( IDS.button ).click();
  $( IDS.cancel ).click();
  assert.equal( pod.state(), "ready" );
  assert.equal( $( IDS.panel ).hidden, true );
  assert.equal( net.calls.length, 1 );
  $( IDS.button ).click();
  assert.equal( pod.state(), "confirming" );
} );

test( "Yes posts the path once and says the job id", async () => {
  const { net, pod } = await ready( answer( 200, { job_id: "pg-1a2b3c4d", status: "waiting", name: "summary.md", queue_position: 1, size: 4300 } ) );
  $( IDS.button ).click();
  $( IDS.yes ).click();
  await flush();
  assert.equal( pod.state(), "done" );
  assert.equal( net.calls.length, 2 );
  assert.equal( net.calls[ 1 ]!.url, START_URL );
  assert.equal( net.calls[ 1 ]!.init.method, "POST" );
  assert.deepEqual( JSON.parse( net.calls[ 1 ]!.init.body as string ), { path: PATH } );
  assert.equal( $( IDS.status ).textContent, "Podcast queued: job pg-1a2b3c4d" );
  assert.equal( $( IDS.status ).classList.contains( "is-ok" ), true, "a success line must not carry the error colour" );
  assert.equal( $( IDS.panel ).hidden, true );
  assert.equal( ( $( IDS.button ) as HTMLButtonElement ).disabled, true );
} );

test( "a second Yes while the first is in flight sends nothing more", async () => {
  let release: ( r: Response ) => void = () => {};
  const slow = new Promise<Response>( ( resolve ) => { release = resolve; } );
  const { net, pod } = await ready( slow );
  $( IDS.button ).click();
  $( IDS.yes ).click();
  assert.equal( pod.state(), "posting" );
  assert.equal( ( $( IDS.yes ) as HTMLButtonElement ).disabled, true );
  $( IDS.yes ).click();
  $( IDS.yes ).click();
  assert.equal( net.calls.length, 2, "check plus exactly one post" );
  release( answer( 200, { job_id: "pg-00000001" } ) );
  await flush();
  assert.equal( pod.state(), "done" );
} );

test( "a click on the button, Cancel or Yes in the wrong state does nothing", async () => {
  const { net, pod } = await ready( answer( 200, { job_id: "pg-1" } ) );
  $( IDS.cancel ).click();
  $( IDS.yes ).click();
  assert.equal( pod.state(), "ready" );
  $( IDS.button ).click();
  $( IDS.button ).click();
  assert.equal( pod.state(), "confirming" );
  $( IDS.yes ).click();
  await flush();
  $( IDS.cancel ).click();
  $( IDS.yes ).click();
  assert.equal( pod.state(), "done" );
  assert.equal( net.calls.length, 2 );
} );

test( "an 'already started' answer says which job and counts as done", async () => {
  const { pod } = await ready( answer( 409, { detail: { code: "spent", message: "m", job_id: "pg-0badf00d" } } ) );
  $( IDS.button ).click();
  $( IDS.yes ).click();
  await flush();
  assert.equal( pod.state(), "done" );
  assert.equal( $( IDS.status ).textContent, "Already started: job pg-0badf00d" );
} );

test( "a refusal says the server's sentence and leaves the button usable", async () => {
  const { pod } = await ready( answer( 409, { detail: { code: "claimed_no_job", message: "A start of this file is under way." } } ) );
  $( IDS.button ).click();
  $( IDS.yes ).click();
  await flush();
  assert.equal( pod.state(), "ready" );
  assert.equal( $( IDS.status ).textContent, "A start of this file is under way." );
  assert.equal( $( IDS.status ).classList.contains( "is-ok" ), false );
  assert.equal( ( $( IDS.button ) as HTMLButtonElement ).disabled, false );
  assert.equal( ( $( IDS.yes ) as HTMLButtonElement ).disabled, false );
} );

test( "a server error with no JSON says the status", async () => {
  const { pod } = await ready( notJson( 502 ) );
  $( IDS.button ).click();
  $( IDS.yes ).click();
  await flush();
  assert.equal( pod.state(), "ready" );
  assert.equal( $( IDS.status ).textContent, "Podcast failed (HTTP 502)" );
} );

test( "a network failure on the post says the server could not be reached", async () => {
  const { pod } = await ready( new Error( "offline" ) );
  $( IDS.button ).click();
  $( IDS.yes ).click();
  await flush();
  assert.equal( pod.state(), "ready" );
  assert.equal( $( IDS.status ).textContent, "Could not reach the server." );
} );

// ---- the binding to the page ----

function windowWith( fetchFn: DocWindowLike[ "__docViewerAuthedFetch" ], path?: string ): DocWindowLike {
  const win: DocWindowLike = {};
  if ( fetchFn !== undefined ) win.__docViewerAuthedFetch = fetchFn;
  if ( path !== undefined ) win.__docViewerFilePath = path;
  return win;
}

test( "the page's event starts the button with the event's path", async () => {
  const net = scripted( CHECK_OK() );
  bindDocPodcast( windowWith( net.authedFetch ), document );
  document.dispatchEvent( new CustomEvent( FILE_EVENT, { detail: { path: PATH } } ) );
  await flush();
  assert.equal( net.calls.length, 1 );
  assert.equal( net.calls[ 0 ]!.url, `${CHECK_URL}?path=${encodeURIComponent( PATH )}` );
  assert.equal( $( IDS.button ).hidden, false );
} );

test( "a path the page left on the window before the module loaded starts it once at boot", async () => {
  const net = scripted( CHECK_OK() );
  bindDocPodcast( windowWith( net.authedFetch, PATH ), document );
  await flush();
  assert.equal( net.calls.length, 1 );
  assert.equal( $( IDS.button ).hidden, false );
} );

test( "with no event and no path the module does nothing", async () => {
  const net = scripted();
  bindDocPodcast( windowWith( net.authedFetch ), document );
  await flush();
  assert.equal( net.calls.length, 0 );
  assert.equal( $( IDS.button ).hidden, true );
} );
