// Tests for the one-click batch links in the legacy client.
//
// `[approve all 2 ☐](/app/tasks/approve?rows=a,b&move=queued)` applies one move to every listed row;
// `[📋](/app/tasks/view?rows=a,b)` lists every row's status and title. The links are planted inside
// `#action-required-content`, where the card lives. `_transitionTask` and `_readTask` are recorders and
// `_showAbstractFor` captures what the 📋 would show, so a request is read from calls, not from the DOM.
//
// Run: npx tsx --test src/tests/unit/notifications_js/batch_approve_link.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE             = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

const ROW_A = "a3975cf4-c640-4659-9247-0a99fa8a5f4a";
const ROW_B = "0b1c2d3e-4f50-4a61-8b72-93a4b5c6d7e8";
const OK    = ( ids: string[], move = "queued", extra = "" ): string => `/app/tasks/approve?rows=${ ids.join( "," ) }&move=${ move }${ extra }`;
const VIEW  = ( ids: string[] ): string => `/app/tasks/view?rows=${ ids.join( "," ) }`;

type Result = { ok: boolean; message?: string };
type Row    = { title?: string; status?: string };

let calls   : Array<{ id: string; status: string; extras: unknown }>;
let answers : Record<string, Result>;
let table   : Record<string, Row | null>;
let asked   : string[];
let shown   : Array<{ text: string; title: string }>;
let tabOpens: unknown[];
let ui      : Record<string, unknown>;

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

function plant( href: string ): HTMLAnchorElement {
  const host = document.getElementById( "action-required-content" ) as Element;
  host.replaceChildren();
  const a = document.createElement( "a" );
  a.setAttribute( "href", href );
  a.textContent = "approve all ☐";
  host.appendChild( a );
  return a;
}

function click( a: Element ): boolean {
  const ev = new MouseEvent( "click", { bubbles: true, cancelable: true } );
  a.dispatchEvent( ev );
  return ev.defaultPrevented;
}

const settle = async (): Promise<void> => { for ( let i = 0; i < 8; i++ ) await Promise.resolve(); };

function mountOnce(): void {
  buildDOM();
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  ui = Object.create( Ctor.prototype ) as Record<string, unknown>;
  ui.debug = false;
  ui._contentPaneHistory = [];
  ui.log   = (): void => {};
  ui.error = (): void => {};
  ui._openContentPane = (): void => {};
  ui._initPaneSplitter              = (): void => {};
  ui._updateLayoutModeButtonTooltip = (): void => {};
  ui._handleEmbeddedAudioClick      = (): void => {};
  ui._handleIoFileDownloadClick     = (): void => {};
  ui._toggleLayoutMode              = (): void => {};
  ui._transitionTask = async ( id: string, status: string, extras: unknown ): Promise<Result> => {
    calls.push( { id, status, extras } );
    return answers[ id ] ?? { ok: true };
  };
  ui._readTask = async ( id: string ): Promise<Row | null> => { asked.push( id ); return table[ id ] ?? null; };
  ui._showAbstractFor = ( _a: Element, text: string, title: string ): void => { shown.push( { text, title } ); };
  ( globalThis as unknown as { open: unknown } ).open = ( ...args: unknown[] ): null => { tabOpens.push( args ); return null; };
  ( ui as unknown as { _initMasterDetailLayout(): void } )._initMasterDetailLayout();
}

beforeEach( () => {
  calls = []; answers = {}; table = {}; asked = []; shown = []; tabOpens = [];
  buildDOM();
} );

before( async () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  await import( "../../../lupin_app/static/js/shared/approve-link.js" );   // row 009d2d53: notifications.js reads the shared module off window
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext( fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;", { filename: NOTIFICATIONS_JS } );
  mountOnce();
} );

// ---- parsing ---------------------------------------------------------------

// Row 009d2d53: the parsing lives in shared/approve-link.js; notifications.js reads it off window.
const lib   = (): Record<string, ( ...a: any[] ) => any> => ( window as unknown as { LUPIN_APPROVE_LINK: Record<string, ( ...a: any[] ) => any> } ).LUPIN_APPROVE_LINK;
const parse = ( list: string | null ): string[] | null => lib().parseBatchIds!( list );
const link  = ( href: string | null ): unknown => lib().batchLinkOf!( href );

test( "parseBatchIds keeps order and refuses empty, short, upper-case, repeated and trailing-comma lists", () => {
  assert.deepEqual( parse( `${ ROW_B },${ ROW_A }` ), [ ROW_B, ROW_A ] );
  assert.equal( parse( null ), null );
  assert.equal( parse( "" ), null );
  assert.equal( parse( `${ ROW_A },a3975cf4` ), null );
  assert.equal( parse( ROW_A.toUpperCase() ), null );
  assert.equal( parse( `${ ROW_A },${ ROW_A }` ), null );
  assert.equal( parse( `${ ROW_A },` ), null );
} );

test( "batchLinkOf reads an approve and a drop, and refuses what it cannot trust", () => {
  assert.deepEqual( link( OK( [ ROW_A, ROW_B ] ) ), { ids: [ ROW_A, ROW_B ], move: "queued", reason: null } );
  assert.deepEqual( link( OK( [ ROW_A ], "dropped", "&reason=duplicate%20refile" ) ), { ids: [ ROW_A ], move: "dropped", reason: "duplicate refile" } );
  assert.equal( link( null ), null );
  assert.equal( link( `/app/tasks/approve?row=${ ROW_A }` ), null, "the single link" );
  assert.equal( link( OK( [ ROW_A, ROW_A ] ) ), null, "duplicate" );
  assert.equal( link( OK( [ ROW_A ], "done" ) ), null, "odd move" );
  assert.equal( link( `/app/tasks/approve?rows=${ ROW_A }` ), null, "no move" );
  assert.equal( link( OK( [ ROW_A ], "dropped" ) ), null, "drop without reason" );
  assert.equal( link( OK( [ ROW_A ], "dropped", "&reason=%20" ) ), null, "drop with blank reason" );
} );

// ---- the approve click -----------------------------------------------------

test( "a click on any other link is not claimed, and a click off any link does nothing", () => {
  const other = plant( "/somewhere/else" );
  assert.equal( click( other ), false );
  const single = plant( `/app/tasks/approve?row=${ ROW_A }` );
  click( single );
  assert.deepEqual( calls.map( ( c ) => c.id ), [ ROW_A ], "the single link is the single handler's, not the batch one's" );
  document.body.click();
  assert.equal( calls.length, 1 );
} );

test( "an untrusted batch link is claimed, sends nothing, is left untouched and the handler does not throw", async () => {
  const a = plant( OK( [ ROW_A, ROW_A ] ) );
  const ev = new MouseEvent( "click", { cancelable: true } );
  Object.defineProperty( ev, "target", { value: a } );
  await ( ui._handleBatchApproveLinkClick as ( e: Event ) => Promise<void> ).call( ui, ev );
  assert.equal( ev.defaultPrevented, true );
  assert.equal( click( a ), true );
  await settle();
  assert.deepEqual( calls, [] );
  assert.equal( a.isConnected, true );
  assert.equal( a.dataset.approveState, undefined, "not marked pending" );
  assert.equal( a.getAttribute( "aria-disabled" ), null, "not greyed" );
  assert.equal( a.style.opacity, "", "not dimmed" );
  assert.deepEqual( tabOpens, [] );
} );

test( "one click applies every row, then shows 'N of N applied' and one line per row", async () => {
  const a = plant( OK( [ ROW_A, ROW_B ] ) );
  assert.equal( click( a ), true );
  await settle();
  assert.deepEqual( calls, [ { id: ROW_A, status: "queued", extras: {} }, { id: ROW_B, status: "queued", extras: {} } ] );
  const out = document.querySelector( ".approve-link-result" ) as HTMLElement;
  assert.equal( out.textContent, "2 of 2 applied\na3975cf4 applied ✅\n0b1c2d3e applied ✅" );
  assert.ok( out.classList.contains( "approve-link-approved" ) );
  assert.equal( document.querySelectorAll( "#action-required-content a" ).length, 0 );
  assert.deepEqual( tabOpens, [] );
} );

test( "a queued link that carries a reason sends no reason", async () => {
  assert.deepEqual( link( OK( [ ROW_A ], "queued", "&reason=x" ) ), { ids: [ ROW_A ], move: "queued", reason: null } );
  click( plant( OK( [ ROW_A ], "queued", "&reason=x" ) ) );
  await settle();
  assert.deepEqual( calls, [ { id: ROW_A, status: "queued", extras: {} } ] );
} );

test( "one refusal marks the summary refused and the other row still reads applied", async () => {
  answers[ ROW_B ] = { ok: false, message: "only an operator may approve" };
  click( plant( OK( [ ROW_A, ROW_B ] ) ) );
  await settle();
  const out = document.querySelector( ".approve-link-result" ) as HTMLElement;
  assert.equal( out.textContent, "1 of 2 applied\na3975cf4 applied ✅\n0b1c2d3e refused: only an operator may approve" );
  assert.ok( out.classList.contains( "approve-link-refused" ) );
} );

test( "a second click while the batch is out sends nothing more", async () => {
  const a = plant( OK( [ ROW_A, ROW_B ] ) );
  click( a );
  assert.equal( click( a ), true );
  await settle();
  assert.equal( calls.length, 2 );
} );

test( "a batch drop sends the reason with every row", async () => {
  click( plant( OK( [ ROW_A, ROW_B ], "dropped", "&reason=duplicate%20refile" ) ) );
  await settle();
  assert.deepEqual( calls.map( ( c ) => [ c.id, c.status, c.extras ] ), [
    [ ROW_A, "dropped", { reason: "duplicate refile" } ],
    [ ROW_B, "dropped", { reason: "duplicate refile" } ],
  ] );
} );

// ---- the view click --------------------------------------------------------

test( "the batch view handler ignores other links", async () => {
  assert.equal( click( plant( "/somewhere/else" ) ), false );
  document.body.click();
  click( plant( `/app/tasks/view?row=${ ROW_A }` ) );
  await settle();
  assert.deepEqual( asked, [ ROW_A ], "the single 📋 link is the single handler's: one read, no batch line" );
  assert.equal( shown.length, 1 );
  assert.ok( !shown[ 0 ]!.title.endsWith( "held rows" ) );
} );

test( "the batch view lists every row's status and title in order, and an unreadable row says so", async () => {
  table[ ROW_A ] = { title: "Refile dup 1", status: "not_approved" };
  assert.equal( click( plant( VIEW( [ ROW_A, ROW_B ] ) ) ), true );
  await settle();
  assert.deepEqual( asked, [ ROW_A, ROW_B ] );
  assert.deepEqual( shown, [ { text: "a3975cf4 · not_approved · Refile dup 1\n0b1c2d3e · could not be read", title: "2 held rows" } ] );
} );

test( "a row with no status or title reads as dashes", async () => {
  table[ ROW_A ] = {};
  click( plant( VIEW( [ ROW_A ] ) ) );
  await settle();
  assert.equal( shown[ 0 ]!.text, "a3975cf4 · — · (no title)" );
} );

test( "an untrusted view list says so and reads nothing", async () => {
  assert.equal( click( plant( VIEW( [ ROW_A, ROW_A ] ) ) ), true );
  await settle();
  assert.deepEqual( asked, [] );
  assert.deepEqual( shown, [ { text: "This link does not name a clean list of full ticket ids.", title: "Held rows" } ] );
} );
