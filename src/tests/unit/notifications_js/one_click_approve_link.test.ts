// Tests for one-click ticket approval in the legacy client.
//
// A card lists held rows as `[✅ approve](/app/tasks/approve?row=<uuid>)`. The click handler must
// claim the link, send the approve move once, and draw the answer where the link was.
//
// The links are planted inside `#action-required-content`, where the card lives.
// The pane-resident branch of the doc-link listener sends any click there to a new tab.
// A link planted in the history list would pass without exercising that trap.
// `_transitionTask` is replaced by a recorder, so a sent request is read from its calls.
//
// Run: npx tsx --test src/tests/unit/notifications_js/one_click_approve_link.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE             = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

const ROW_A    = "a3975cf4-c640-4659-9247-0a99fa8a5f4a";
const ROW_B    = "0b1c2d3e-4f50-4a61-8b72-93a4b5c6d7e8";
const APPROVE  = ( id: string ): string => `/app/tasks/approve?row=${ id }`;
const DOC_HREF = "/app/docs?path=lupin/src/rnd/a-real-doc.md";

type Result = { ok: boolean; message?: string };
interface Call { id: string; status: string; extras: unknown }

let calls    : Call[];
let tabOpens : unknown[];
let paneOpens: string[];
let release  : Array<( r: Result ) => void>;
let ui       : Record<string, unknown>;

function buildDOM(): void {
  document.body.replaceChildren();
  const host = document.createElement( "div" );
  host.innerHTML = `
    <div class="content-shell"><div class="left-column">
      <button id="layout-mode-toggle" type="button">⇆</button>
      <button id="doc-roots-toggle" type="button">📂</button>
      <div id="action-required-content"></div>
      <div id="notification-list"></div>
    </div></div>`;
  document.body.appendChild( host );
}

/** Plant a bulleted card with one link per entry in `hrefs`; return the anchors. */
function plantCard( hrefs: string[], hostId = "action-required-content" ): HTMLAnchorElement[] {
  const host = document.getElementById( hostId ) as Element;
  host.replaceChildren();
  return hrefs.map( ( href ) => {
    const li = document.createElement( "li" );
    const a  = document.createElement( "a" );
    a.setAttribute( "href", href );
    a.textContent = "✅ approve";
    li.appendChild( a );
    host.appendChild( li );
    return a;
  } );
}

/** Click and report whether the app claimed it. */
function click( a: Element ): boolean {
  const ev = new MouseEvent( "click", { bubbles: true, cancelable: true } );
  a.dispatchEvent( ev );
  return ev.defaultPrevented;
}

/** Let pending promise callbacks run. */
const settle = async (): Promise<void> => { for ( let i = 0; i < 5; i++ ) await Promise.resolve(); };

/** Register the listeners one time; each mount adds document listeners that stay. */
function mountOnce(): void {
  buildDOM();
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  ui = Object.create( Ctor.prototype ) as Record<string, unknown>;
  ui.debug = false;
  ui.log   = (): void => {};
  ui.error = (): void => {};
  ui._openContentPane = ( _k: string, payload: string ): void => { paneOpens.push( payload ); };
  ui._initPaneSplitter              = (): void => {};
  ui._updateLayoutModeButtonTooltip = (): void => {};
  ui._handleEmbeddedAudioClick      = (): void => {};
  ui._handleIoFileDownloadClick     = (): void => {};
  ui._toggleLayoutMode              = (): void => {};
  // The recorder: each call parks until the test releases it with a chosen answer.
  ui._transitionTask = ( id: string, status: string, extras: unknown ): Promise<Result> => {
    calls.push( { id, status, extras } );
    return new Promise<Result>( ( res ) => { release.push( res ); } );
  };
  ( globalThis as unknown as { open: unknown } ).open = ( ...args: unknown[] ): null => { tabOpens.push( args ); return null; };
  ( ui as unknown as { _initMasterDetailLayout(): void } )._initMasterDetailLayout();
}

beforeEach( () => {
  calls = []; tabOpens = []; paneOpens = []; release = [];
  buildDOM();
} );

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext( fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;", { filename: NOTIFICATIONS_JS } );
  mountOnce();
} );

test( "an approve link in the action-required card is claimed, sent once with the row id, and opens no tab", async () => {
  const [ a ] = plantCard( [ APPROVE( ROW_A ) ] );
  const claimed = click( a! );
  assert.equal( claimed, true, "the approve branch must claim the click before the pane-resident branch sees it" );
  assert.deepEqual( calls, [ { id: ROW_A, status: "queued", extras: {} } ], "one request, for this row, to queued" );
  assert.deepEqual( tabOpens, [], "no new tab" );
  assert.deepEqual( paneOpens, [], "no pane open" );
} );

test( "success replaces the link with Approved ✓", async () => {
  const [ a ] = plantCard( [ APPROVE( ROW_A ) ] );
  click( a! );
  release[ 0 ]!( { ok: true } );
  await settle();
  const host = document.getElementById( "action-required-content" ) as Element;
  assert.equal( host.querySelector( "a" ), null, "the link is gone" );
  assert.equal( host.querySelector( ".approve-link-approved" )?.textContent, "Approved ✓" );
} );

test( "a refusal shows the server's words and nothing else", async () => {
  const [ a ] = plantCard( [ APPROVE( ROW_A ) ] );
  click( a! );
  release[ 0 ]!( { ok: false, message: "only an operator may approve" } );
  await settle();
  const host = document.getElementById( "action-required-content" ) as Element;
  assert.equal( host.querySelector( "a" ), null );
  assert.equal( host.querySelector( ".approve-link-refused" )?.textContent, "only an operator may approve" );
  assert.equal( host.querySelector( ".approve-link-approved" ), null );
} );

test( "a second click while the request is out sends nothing", async () => {
  const [ a ] = plantCard( [ APPROVE( ROW_A ) ] );
  click( a! );
  const claimedAgain = click( a! );
  assert.equal( claimedAgain, true, "still claimed: the browser must not follow it" );
  assert.equal( calls.length, 1, "exactly one request for two clicks" );
  assert.equal( a!.getAttribute( "aria-disabled" ), "true", "the waiting link is greyed" );
} );

test( "three links are independent: two clicks send exactly those two rows", async () => {
  const anchors = plantCard( [ APPROVE( ROW_A ), APPROVE( ROW_B ), APPROVE( "c3d4e5f6-0718-4293-a4b5-c6d7e8f90a1b" ) ] );
  click( anchors[ 0 ]! );
  click( anchors[ 2 ]! );
  assert.deepEqual( calls.map( ( c ) => c.id ), [ ROW_A, "c3d4e5f6-0718-4293-a4b5-c6d7e8f90a1b" ] );
  assert.equal( anchors[ 1 ]!.getAttribute( "data-approve-state" ), null, "the skipped link is untouched" );
} );

test( "the absolute-loopback form is claimed too", () => {
  const [ a ] = plantCard( [ `http://localhost:7999${ APPROVE( ROW_A ) }` ] );
  assert.equal( click( a! ), true );
  assert.equal( calls[ 0 ]?.id, ROW_A );
} );

test( "a short or malformed row id is not claimed and sends nothing", () => {
  for ( const href of [ "/app/tasks/approve?row=a3975cf4", "/app/tasks/approve?row=", "/app/tasks/approve?row=A3975CF4-C640-4659-9247-0A99FA8A5F4A", "/app/tasks/approve" ] ) {
    const [ a ] = plantCard( [ href ] );
    click( a! );
  }
  assert.deepEqual( calls, [] );
} );

test( "doc links behave as before: history opens the pane, the card opens a tab, neither sends an approve", () => {
  const [ historyDoc ] = plantCard( [ DOC_HREF ], "notification-list" );
  assert.equal( click( historyDoc! ), true );
  assert.deepEqual( paneOpens, [ DOC_HREF ] );
  const [ cardDoc ] = plantCard( [ DOC_HREF ] );
  assert.equal( click( cardDoc! ), true );
  assert.equal( tabOpens.length, 1, "the card's doc link still opens a new tab" );
  assert.deepEqual( calls, [], "no doc link ever sends an approve" );
} );

test( "an external link and a click off any link are left alone", () => {
  const [ ext ] = plantCard( [ "https://example.com/x" ] );
  assert.equal( click( ext! ), false );
  const host = document.getElementById( "action-required-content" ) as Element;
  assert.equal( click( host ), false );
  assert.deepEqual( calls, [] );
} );
