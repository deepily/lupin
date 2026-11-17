// Tests for one-click ticket approval in the legacy client.
//
// A card lists held rows as `[approve ☐](/app/tasks/approve?row=<uuid>) [📋](/app/tasks/view?row=<uuid>)`. The click handler must
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
import v8 from "node:v8";

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
type Row = { title?: string; priority?: string | null; owner_persona?: string | null; status?: string; body?: string | null };
let table    : Record<string, Row | null>;
let asked    : string[];

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
    a.textContent = "approve ☐";
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
  ui._contentPaneHistory = [];
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
  // The reader: answers from `table` and records every id asked for.
  ui._readTask = async ( id: string ): Promise<Row | null> => { asked.push( id ); return table[ id ] ?? null; };
  ( globalThis as unknown as { open: unknown } ).open = ( ...args: unknown[] ): null => { tabOpens.push( args ); return null; };
  ( ui as unknown as { _initMasterDetailLayout(): void } )._initMasterDetailLayout();
}

// Row 009d2d53: the link parsing lives in shared/approve-link.js; notifications.js reads it off window.
const LIB = (): Record<string, ( ...a: any[] ) => any> => ( window as unknown as { LUPIN_APPROVE_LINK: Record<string, ( ...a: any[] ) => any> } ).LUPIN_APPROVE_LINK;

beforeEach( () => {
  calls = []; tabOpens = []; paneOpens = []; release = []; table = {}; asked = [];
  buildDOM();
  document.getElementById( "task-body-overlay" )?.remove();
  document.getElementById( "abstract-tooltip" )?.remove();
} );

// happy-dom keeps a MutationObserver's callback only behind a WeakRef, so a garbage collection
// between two tests silences the observer and the "card drawn later" tests read nothing.
// Measured 3 Nov 2026: forcing gc() before the first of them failed 3 of 3 runs; CPU load failed 2 of 6.
// This shim pins every referent for the life of the process, as a browser does for a live observer.
const PINNED: unknown[] = [];
class PinnedWeakRef<T extends object> {
  readonly #target: T;
  constructor( target: T ) { this.#target = target; PINNED.push( target ); }
  deref(): T { return this.#target; }
}

before( async () => {
  ( globalThis as unknown as { WeakRef: unknown } ).WeakRef = PinnedWeakRef;
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  await import( "../../../lupin_app/static/js/shared/approve-link.js" );   // row 009d2d53: notifications.js reads the shared module off window
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

test( "success replaces the link with a disabled approved ✅", async () => {
  const [ a ] = plantCard( [ APPROVE( ROW_A ) ] );
  click( a! );
  release[ 0 ]!( { ok: true } );
  await settle();
  const host = document.getElementById( "action-required-content" ) as Element;
  assert.ok( host.querySelector( "a" ) === null, "the link is gone" );
  const done = host.querySelector( ".approve-link-approved" ) as Element;
  assert.equal( done.textContent, "approved ✅" );
  assert.equal( done.getAttribute( "aria-disabled" ), "true", "no second click is possible" );
} );

test( "a refusal shows the server's words and nothing else", async () => {
  const [ a ] = plantCard( [ APPROVE( ROW_A ) ] );
  click( a! );
  release[ 0 ]!( { ok: false, message: "only an operator may approve" } );
  await settle();
  const host = document.getElementById( "action-required-content" ) as Element;
  assert.ok( host.querySelector( "a" ) === null );
  assert.equal( host.querySelector( ".approve-link-refused" )?.textContent, "only an operator may approve" );
  assert.ok( host.querySelector( ".approve-link-approved" ) === null );
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


// ---------------------------------------------------------------------------
// Row 192fecdf — the 📋 view link; row 39624bae — the state of a card drawn after a reload
// ---------------------------------------------------------------------------

const VIEW  = ( id: string ): string => `/app/tasks/view?row=${ id }`;
const flush = async (): Promise<void> => { await settle(); await new Promise( ( r ) => setTimeout( r, 0 ) ); await settle(); };
const host  = (): Element => document.getElementById( "action-required-content" ) as Element;

const FIX_X = { title: "Fix X", priority: "P2", owner_persona: "krishna", status: "not_approved", body: "line one\nline two" };
const FACTS = "Fix X\nPriority: P2 · Owner: krishna · Status: not_approved\n\nline one\nline two";

/** The floating tooltip the 📋 uses, with the content box the code writes into. */
function plantTooltip(): Element {
  document.getElementById( "abstract-tooltip" )?.remove();
  const tip = document.createElement( "div" );
  tip.id = "abstract-tooltip";
  tip.className = "abstract-tooltip";
  tip.innerHTML = '<div class="abstract-tooltip-content"></div>';
  document.body.appendChild( tip );
  return tip;
}

test( "horizontal: a 📋 link shows the row in the content pane like the 📋, with no overlay and no new tab", async () => {
  table[ ROW_A ] = FIX_X;
  ui._layoutMode = "horizontal";
  const [ a ] = plantCard( [ VIEW( ROW_A ) ], "notification-list" );
  assert.equal( click( a! ), true, "claimed" );
  await flush();
  assert.deepEqual( asked, [ ROW_A ] );
  assert.deepEqual( paneOpens, [ FACTS ], "the pane got the row text" );
  assert.ok( document.getElementById( "task-body-overlay" ) === null, "no overlay" );
  assert.deepEqual( tabOpens, [], "no new tab" );
  assert.deepEqual( calls, [], "viewing sends no approve" );
} );

test( "horizontal: a 📋 link inside the action-required card uses the tooltip, as that card's own 📋 does", async () => {
  table[ ROW_A ] = FIX_X;
  ui._layoutMode = "horizontal";
  const tip = plantTooltip();
  const [ a ] = plantCard( [ VIEW( ROW_A ) ] );
  click( a! );
  await flush();
  assert.equal( tip.querySelector( ".abstract-tooltip-content" )?.textContent, FACTS );
  assert.deepEqual( paneOpens, [], "the pane is left to the live response buttons" );
} );

test( "horizontal: while an action-required card owns the pane, a 📋 link in the list uses the tooltip", async () => {
  table[ ROW_A ] = FIX_X;
  ui._layoutMode = "horizontal";
  ui._actionRequiredInPane = true;
  const tip = plantTooltip();
  const [ a ] = plantCard( [ VIEW( ROW_A ) ], "notification-list" );
  click( a! );
  await flush();
  ui._actionRequiredInPane = false;
  assert.equal( tip.querySelector( ".abstract-tooltip-content" )?.textContent, FACTS );
  assert.deepEqual( paneOpens, [], "the pane guard would have dropped it" );
} );

test( "horizontal: a 📋 link inside the open tooltip replaces the tooltip text, not the pane", async () => {
  table[ ROW_A ] = FIX_X;
  ui._layoutMode = "horizontal";
  const tip = plantTooltip();
  const [ a ] = plantCard( [ VIEW( ROW_A ) ], "notification-list" );
  tip.querySelector( ".abstract-tooltip-content" )!.appendChild( a! );
  click( a! );
  await flush();
  assert.equal( tip.querySelector( ".abstract-tooltip-content" )?.textContent, FACTS );
  assert.deepEqual( paneOpens, [] );
} );

test( "vertical: a 📋 link in the plain notification list shows the tooltip and never the pane", async () => {
  table[ ROW_A ] = FIX_X;
  ui._layoutMode = "vertical";
  const tip = plantTooltip();
  const [ a ] = plantCard( [ VIEW( ROW_A ) ], "notification-list" );
  assert.equal( click( a! ), true, "claimed" );
  await flush();
  assert.equal( tip.querySelector( ".abstract-tooltip-content" )?.textContent, FACTS );
  assert.deepEqual( paneOpens, [], "vertical layout never opens the pane" );
  assert.deepEqual( tabOpens, [], "no new tab" );
} );

test( "vertical: a 📋 link shows the row in the abstract tooltip, with no pane, no overlay and no new tab", async () => {
  table[ ROW_A ] = FIX_X;
  ui._layoutMode = "vertical";
  const tip = plantTooltip();
  const [ a ] = plantCard( [ VIEW( ROW_A ) ] );
  assert.equal( click( a! ), true, "claimed" );
  await flush();
  assert.equal( tip.classList.contains( "visible" ), true );
  assert.equal( tip.querySelector( ".abstract-tooltip-content" )?.textContent, FACTS );
  assert.deepEqual( paneOpens, [], "no pane" );
  assert.ok( document.getElementById( "task-body-overlay" ) === null, "no overlay" );
  assert.deepEqual( tabOpens, [], "no new tab" );
} );

test( "a 📋 link on a row that cannot be read says so, in the pane and in the tooltip", async () => {
  ui._layoutMode = "horizontal";
  const [ a ] = plantCard( [ VIEW( ROW_A ) ], "notification-list" );
  click( a! );
  await flush();
  assert.deepEqual( paneOpens, [ "Could not read this ticket." ] );
  ui._layoutMode = "vertical";
  const tip = plantTooltip();
  const [ b ] = plantCard( [ VIEW( ROW_A ) ] );
  click( b! );
  await flush();
  assert.equal( tip.querySelector( ".abstract-tooltip-content" )?.textContent, "Could not read this ticket." );
} );

test( "a malformed 📋 link and a click off any link are not claimed as views", () => {
  const [ a ] = plantCard( [ "/app/tasks/view?row=a3975cf4" ] );
  click( a! );
  click( host() );
  assert.deepEqual( asked, [] );
  assert.ok( document.getElementById( "task-body-overlay" ) === null );
} );

test( "a card drawn later: a held row keeps its live link, a live or done row reads approved ✅ and is disabled", async () => {
  table[ ROW_A ] = { status: "not_approved" }; table[ ROW_B ] = { status: "queued" }; table[ "c3d4e5f6-0718-4293-a4b5-c6d7e8f90a1b" ] = { status: "done" };
  plantCard( [ APPROVE( ROW_A ), APPROVE( ROW_B ), APPROVE( "c3d4e5f6-0718-4293-a4b5-c6d7e8f90a1b" ) ] );
  await flush();
  assert.deepEqual( [ ...host().querySelectorAll( "a" ) ].map( ( e ) => e.getAttribute( "href" ) ), [ APPROVE( ROW_A ) ], "only the held row keeps a link" );
  const done = [ ...host().querySelectorAll( ".approve-link-approved" ) ];
  assert.deepEqual( done.map( ( e ) => e.textContent ), [ "approved ✅", "approved ✅" ] );
  assert.ok( done.every( ( e ) => e.getAttribute( "aria-disabled" ) === "true" ) );
} );

test( "a card drawn after a full garbage collection is still read: the observer survives gc", async () => {
  v8.setFlagsFromString( "--expose-gc" );
  const gc = vm.runInNewContext( "gc" ) as () => void;
  await new Promise( ( r ) => setTimeout( r, 5 ) );
  gc(); gc();
  table[ ROW_A ] = { status: "queued" };
  plantCard( [ APPROVE( ROW_A ) ] );
  await flush();
  assert.deepEqual( asked, [ ROW_A ], "the observer must still deliver after gc" );
  assert.equal( host().querySelectorAll( "a" ).length, 0, "a queued row's link is replaced" );
} );

test( "a dropped or wont_fix row reads as its plain status, never approved", async () => {
  table[ ROW_A ] = { status: "dropped" }; table[ ROW_B ] = { status: "wont_fix" };
  plantCard( [ APPROVE( ROW_A ), APPROVE( ROW_B ) ] );
  await flush();
  assert.deepEqual( [ ...host().querySelectorAll( ".approve-link-closed" ) ].map( ( e ) => e.textContent ), [ "dropped", "wont_fix" ] );
  assert.ok( host().querySelector( ".approve-link-approved" ) === null );
  assert.ok( host().querySelector( "a" ) === null );
} );

test( "a failed read, or a row with no status, leaves the live link", async () => {
  table[ ROW_B ] = {};
  plantCard( [ APPROVE( ROW_A ), APPROVE( ROW_B ) ] );
  await flush();
  assert.equal( host().querySelectorAll( "a" ).length, 2 );
} );

test( "the same row id twice in one card is read once and both links are drawn the same", async () => {
  table[ ROW_A ] = { status: "in_progress" };
  plantCard( [ APPROVE( ROW_A ), APPROVE( ROW_A ) ] );
  await flush();
  assert.deepEqual( asked, [ ROW_A ], "one read" );
  assert.equal( host().querySelectorAll( ".approve-link-approved" ).length, 2 );
} );

test( "a link clicked before the read answers is not replaced by the read", async () => {
  table[ ROW_A ] = { status: "queued" };
  const [ a ] = plantCard( [ APPROVE( ROW_A ) ] );
  click( a! );
  await flush();
  assert.ok( host().contains( a! ), "the pending link stays until the click's own answer" );
  release[ 0 ]!( { ok: true } );
  await settle();
  assert.equal( host().querySelector( ".approve-link-approved" )?.textContent, "approved ✅" );
} );

test( "a link already checked is not read again, and a disconnected one is skipped", async () => {
  table[ ROW_A ] = { status: "queued" };
  const box = document.createElement( "div" );
  const a   = document.createElement( "a" );
  a.setAttribute( "href", APPROVE( ROW_A ) );
  box.appendChild( a );
  const n = { _markApproveLinks: ( roots: Element[] ): Promise<void> => LIB().markApproveLinks!( roots, ( id: string ) => ui._readTask( id ) ) };
  const pending = n._markApproveLinks( [ box ] );
  a.remove();
  await pending;
  await n._markApproveLinks( [ box ] );
  const b = document.createElement( "a" );
  b.setAttribute( "href", APPROVE( ROW_A ) );
  b.setAttribute( "data-approve-checked", "1" );
  box.appendChild( b );
  await n._markApproveLinks( [ box ] );
  assert.deepEqual( asked, [ ROW_A ], "one read in total" );
  assert.equal( box.contains( b ), true, "an already-checked link is untouched" );
} );

test( "an anchor passed directly as a root is checked", async () => {
  table[ ROW_A ] = { status: "done" };
  const [ a ] = plantCard( [ APPROVE( ROW_A ) ] );
  await LIB().markApproveLinks!( [ a! ], ( id: string ) => ui._readTask( id ) );
  assert.equal( host().querySelector( ".approve-link-approved" )?.textContent, "approved ✅" );
} );

test( "text nodes drawn into the page start no read", async () => {
  document.body.appendChild( document.createTextNode( "plain text" ) );
  await flush();
  assert.deepEqual( asked, [] );
} );

test( "taskOverlayText fills a missing field with a dash, unowned or (no body), never undefined", () => {
  const f = ( r: Row ): string => LIB().taskOverlayText!( r );
  assert.equal( f( {} ), "(no title)\nPriority: — · Owner: unowned · Status: —\n\n(no body)" );
  assert.equal( f( { title: "T", status: "queued" } ), "T\nPriority: — · Owner: unowned · Status: queued\n\n(no body)" );
} );

test( "_readTask returns the row on 2xx, null on a non-2xx answer, and null when the fetch throws", async () => {
  const real = ( Object.getPrototypeOf( ui ) as { _readTask( id: string ): Promise<Row | null> } )._readTask;
  const reader = ( impl: () => Promise<unknown> ): Promise<Row | null> => real.call( { authedFetch: impl }, ROW_A );
  assert.deepEqual( await reader( async () => ( { ok: true, json: async () => ( { status: "queued" } ) } ) ), { status: "queued" } );
  assert.equal( await reader( async () => ( { ok: false } ) ), null );
  assert.equal( await reader( async () => { throw new Error( "down" ); } ), null );
} );

// happy-dom does not run DOMPurify's removals, so this proves the routing: the row text reaches renderMarkdown in
// both layouts, and what the sanitizer strips never becomes an element. The real browser proof is in
// test_one_click_approve_link_both_clients.py.
test( "a ticket body carrying an img tag goes through renderMarkdown and creates no img element in the pane or the tooltip", async () => {
  const evil = '<img src=x onerror="window.__pwned=1">';
  const seen: string[] = [];
  ui.renderMarkdown = ( text: string ): string => { seen.push( text ); return text.replace( /<img[^>]*>/g, "" ); };
  table[ ROW_A ] = { title: evil, status: "queued", body: `before ${ evil } after` };
  ui._layoutMode = "vertical";
  const tip = plantTooltip();
  const [ a ] = plantCard( [ VIEW( ROW_A ) ] );
  click( a! );
  await flush();
  assert.ok( seen.some( ( t ) => t.includes( `before ${ evil } after` ) ), "the row text reached renderMarkdown" );
  assert.ok( tip.textContent?.includes( "before" ), "the row was drawn" );
  assert.ok( tip.querySelector( "img" ) === null, "no img element exists" );
  assert.equal( ( globalThis as unknown as { __pwned?: number } ).__pwned, undefined );
  // Horizontal hands the text to _openContentPane, whose own renderer is covered by the pane's tests.
  ui._layoutMode = "horizontal";
  paneOpens.length = 0;
  const [ b ] = plantCard( [ VIEW( ROW_A ) ], "notification-list" );
  click( b! );
  await flush();
  assert.ok( paneOpens[ 0 ]!.includes( `before ${ evil } after` ), "the pane was given the row text, to render as markdown" );
} );

// A view link is found by its address, so a card sent before the label changed to 📋 still works.
for ( const label of [ "\u{1F4CB}", "\u{1F4C4}" ] ) {
  test( `a view link labelled ${ label } is claimed and shows the row`, async () => {
    table[ ROW_A ] = FIX_X;
    ui._layoutMode = "horizontal";
    const [ a ] = plantCard( [ VIEW( ROW_A ) ], "notification-list" );
    a!.textContent = label;
    assert.equal( click( a! ), true, "claimed" );
    await flush();
    assert.deepEqual( asked, [ ROW_A ] );
    assert.deepEqual( paneOpens, [ FACTS ] );
  } );
}
