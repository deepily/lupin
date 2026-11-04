// Tests for the one-click batch links in the multiplexer.
//
// `/app/tasks/approve?rows=a,b&move=queued|dropped[&reason=...]` applies one move to every listed row;
// `/app/tasks/view?rows=a,b` lists every row's status and title first.
// Parsing is tested on its own (bad id, duplicate id, empty list, odd move, drop without reason).
// The click handlers are tested with a recording sender so "a request went out" is read from its calls.
// One case enters through the real ReadingPaneRenderer, in the action-required card, to prove the wiring.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/batch_approve_link.test.ts

import { test, before, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import vm from "node:vm";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createStorageServiceForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/StorageService";
import { createReadingPaneStore } from "../../../../lupin_app/static/js/multiplexer/stores/ReadingPaneStore";
import { createReadingPaneRenderer } from "../../../../lupin_app/static/js/multiplexer/render/ReadingPaneRenderer";
import type { ReadingPaneRenderer, WindowLike, WindowDocLike } from "../../../../lupin_app/static/js/multiplexer/render/ReadingPaneRenderer";
import {
  parseBatchIds, batchLinkOf, batchViewIds, applyBatch, handleBatchApproveLinkClick, handleBatchViewLinkClick, approveRowId, viewRowId,
} from "../../../../lupin_app/static/js/multiplexer/render/approveLink";
import type { ApproveSender, TaskReader } from "../../../../lupin_app/static/js/multiplexer/render/approveLink";
import type { HoldingTransitionResult } from "../../../../lupin_app/static/js/multiplexer/stores/HoldingAreaStore";

const ROW_A = "a3975cf4-c640-4659-9247-0a99fa8a5f4a";
const ROW_B = "0b1c2d3e-4f50-4a61-8b72-93a4b5c6d7e8";
const OK    = ( ids: string[], move = "queued", extra = "" ): string => `/app/tasks/approve?rows=${ ids.join( "," ) }&move=${ move }${ extra }`;
const VIEW  = ( ids: string[] ): string => `/app/tasks/view?rows=${ ids.join( "," ) }`;

const VENDOR = resolve( dirname( fileURLToPath( import.meta.url ) ), "../../../../lupin_app/static/js/vendor" );

let active : ReadingPaneRenderer | null = null;
let calls  : Array<{ id: string; status: string; extras: unknown }>;
let answers: Record<string, HoldingTransitionResult>;

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  vm.runInThisContext( readFileSync( resolve( VENDOR, "marked.min.js" ), "utf8" ) );
  vm.runInThisContext( readFileSync( resolve( VENDOR, "purify.min.js" ), "utf8" ) );
} );
beforeEach( () => { document.body.replaceChildren(); calls = []; answers = {}; } );
afterEach( () => { if ( active !== null ) { active.unmount(); active = null; } } );

const settle = async (): Promise<void> => { for ( let i = 0; i < 8; i++ ) await Promise.resolve(); };

/** A sender that answers each row from `answers` (default ok) and records every call. */
function sender(): ApproveSender {
  return {
    async transitionTask( id, status, extras ) {
      calls.push( { id, status, extras } );
      return answers[ id ] ?? { ok: true };
    },
  };
}

function plant( host: Element, href: string ): HTMLAnchorElement {
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

// ---- parsing ---------------------------------------------------------------

test( "parseBatchIds returns the ids in order", () => {
  assert.deepEqual( parseBatchIds( `${ ROW_B },${ ROW_A }` ), [ ROW_B, ROW_A ] );
} );

test( "parseBatchIds refuses an empty list, a missing list, a short id, an upper-case id and a repeated id", () => {
  assert.equal( parseBatchIds( null ), null );
  assert.equal( parseBatchIds( "" ), null );
  assert.equal( parseBatchIds( `${ ROW_A },a3975cf4` ), null );
  assert.equal( parseBatchIds( ROW_A.toUpperCase() ), null );
  assert.equal( parseBatchIds( `${ ROW_A },${ ROW_B },${ ROW_A }` ), null );
  assert.equal( parseBatchIds( `${ ROW_A },` ), null, "a trailing comma is an empty id" );
} );

test( "batchLinkOf reads an approve and a drop, relative or on a loopback origin", () => {
  assert.deepEqual( batchLinkOf( OK( [ ROW_A, ROW_B ] ) ), { ids: [ ROW_A, ROW_B ], move: "queued", reason: null } );
  assert.deepEqual( batchLinkOf( "http://localhost:7999" + OK( [ ROW_A ], "dropped", "&reason=duplicate%20refile%20%26%20more" ) ), { ids: [ ROW_A ], move: "dropped", reason: "duplicate refile & more" } );
} );

test( "a queued link that carries a reason drops the reason: an approve never sends one", async () => {
  assert.deepEqual( batchLinkOf( OK( [ ROW_A ], "queued", "&reason=x" ) ), { ids: [ ROW_A ], move: "queued", reason: null } );
  const a = plant( document.body, OK( [ ROW_A ], "queued", "&reason=x" ) );
  handleBatchApproveLinkClick( new MouseEvent( "click", { cancelable: true } ), a, sender() );
  await settle();
  assert.deepEqual( calls, [ { id: ROW_A, status: "queued", extras: {} } ] );
} );

test( "batchLinkOf refuses what it cannot trust", () => {
  assert.equal( batchLinkOf( null ), null, "no href" );
  assert.equal( batchLinkOf( "/app/docs?path=lupin/a.md" ), null, "not a batch link" );
  assert.equal( batchLinkOf( `/app/tasks/approve?row=${ ROW_A }` ), null, "the single link is not a batch link" );
  assert.equal( batchLinkOf( OK( [ ROW_A, ROW_A ] ) ), null, "duplicate id" );
  assert.equal( batchLinkOf( "/app/tasks/approve?rows=&move=queued" ), null, "empty list" );
  assert.equal( batchLinkOf( OK( [ "a3975cf4" ] ) ), null, "short id" );
  assert.equal( batchLinkOf( OK( [ ROW_A ], "done" ) ), null, "odd move" );
  assert.equal( batchLinkOf( `/app/tasks/approve?rows=${ ROW_A }` ), null, "no move" );
  assert.equal( batchLinkOf( OK( [ ROW_A ], "dropped" ) ), null, "drop without a reason" );
  assert.equal( batchLinkOf( OK( [ ROW_A ], "dropped", "&reason=%20%20" ) ), null, "drop with a blank reason" );
} );

test( "batchViewIds reads the ids and refuses a bad list", () => {
  assert.deepEqual( batchViewIds( VIEW( [ ROW_A, ROW_B ] ) ), [ ROW_A, ROW_B ] );
  assert.equal( batchViewIds( VIEW( [ ROW_A, ROW_A ] ) ), null );
  assert.equal( batchViewIds( "/app/tasks/approve?rows=" + ROW_A ), null );
  assert.equal( batchViewIds( null ), null );
} );

test( "the single-row readers do not claim a batch href", () => {
  assert.equal( approveRowId( OK( [ ROW_A ] ) ), null );
  assert.equal( viewRowId( VIEW( [ ROW_A ] ) ), null );
} );

// ---- applyBatch ------------------------------------------------------------

test( "applyBatch sends one move per row and names every row, a refusal not hiding the other", async () => {
  answers[ ROW_B ] = { ok: false, message: "only an operator may approve" };
  const lines = await applyBatch( { ids: [ ROW_A, ROW_B ], move: "queued", reason: null }, sender() );
  assert.deepEqual( calls, [ { id: ROW_A, status: "queued", extras: {} }, { id: ROW_B, status: "queued", extras: {} } ] );
  assert.deepEqual( lines, [ "a3975cf4 applied ✅", "0b1c2d3e refused: only an operator may approve" ] );
} );

test( "applyBatch sends the reason with a drop", async () => {
  await applyBatch( { ids: [ ROW_A ], move: "dropped", reason: "duplicate" }, sender() );
  assert.deepEqual( calls, [ { id: ROW_A, status: "dropped", extras: { reason: "duplicate" } } ] );
} );

// ---- the approve click -----------------------------------------------------

test( "a click off any link, or on another link, is not claimed", () => {
  const el = document.createElement( "div" );
  assert.equal( handleBatchApproveLinkClick( new MouseEvent( "click" ), el, sender() ), false );
  const other = plant( document.body, "/app/docs?path=lupin/a.md" );
  assert.equal( handleBatchApproveLinkClick( new MouseEvent( "click" ), other, sender() ), false );
  const single = plant( document.body, `/app/tasks/approve?row=${ ROW_A }` );
  assert.equal( handleBatchApproveLinkClick( new MouseEvent( "click" ), single, sender() ), false );
  assert.deepEqual( calls, [] );
} );

test( "an untrusted batch link is claimed so the browser stays put, and sends nothing", () => {
  const a = plant( document.body, OK( [ ROW_A, ROW_A ] ) );
  assert.equal( click( a ), false, "no listener on this bare body; call the handler directly" );
  const ev = new MouseEvent( "click", { cancelable: true } );
  assert.equal( handleBatchApproveLinkClick( ev, a, sender() ), true );
  assert.equal( ev.defaultPrevented, true );
  assert.deepEqual( calls, [] );
  assert.equal( a.isConnected, true, "the link is left in place" );
  assert.equal( a.getAttribute( "data-approve-state" ), null, "and is not marked pending" );
  assert.equal( a.getAttribute( "aria-disabled" ), null, "or greyed" );
  assert.equal( a.style.opacity, "", "or dimmed" );
} );

test( "a good click applies every row, then shows 'N of N applied' and one line per row", async () => {
  const a  = plant( document.body, OK( [ ROW_A, ROW_B ] ) );
  const ev = new MouseEvent( "click", { cancelable: true } );
  assert.equal( handleBatchApproveLinkClick( ev, a, sender() ), true );
  assert.equal( ev.defaultPrevented, true );
  assert.equal( a.getAttribute( "data-approve-state" ), "pending" );
  await settle();
  assert.equal( calls.length, 2 );
  const out = document.querySelector( ".approve-link-result" ) as HTMLElement;
  assert.equal( out.textContent, "2 of 2 applied\na3975cf4 applied ✅\n0b1c2d3e applied ✅" );
  assert.ok( out.classList.contains( "approve-link-approved" ) );
  assert.equal( document.querySelectorAll( "a" ).length, 0, "the link is gone" );
} );

test( "one refusal marks the summary refused and the other row still reads applied", async () => {
  answers[ ROW_A ] = { ok: false, message: "row not found" };
  const a = plant( document.body, OK( [ ROW_A, ROW_B ] ) );
  handleBatchApproveLinkClick( new MouseEvent( "click", { cancelable: true } ), a, sender() );
  await settle();
  const out = document.querySelector( ".approve-link-result" ) as HTMLElement;
  assert.equal( out.textContent, "1 of 2 applied\na3975cf4 refused: row not found\n0b1c2d3e applied ✅" );
  assert.ok( out.classList.contains( "approve-link-refused" ) );
} );

test( "a second click while the batch is out sends nothing more", async () => {
  const a = plant( document.body, OK( [ ROW_A, ROW_B ] ) );
  handleBatchApproveLinkClick( new MouseEvent( "click", { cancelable: true } ), a, sender() );
  assert.equal( handleBatchApproveLinkClick( new MouseEvent( "click", { cancelable: true } ), a, sender() ), true );
  await settle();
  assert.equal( calls.length, 2, "two rows, one run" );
} );

test( "a batch drop sends the reason with every row", async () => {
  const a = plant( document.body, OK( [ ROW_A, ROW_B ], "dropped", "&reason=duplicate%20refile" ) );
  handleBatchApproveLinkClick( new MouseEvent( "click", { cancelable: true } ), a, sender() );
  await settle();
  assert.deepEqual( calls.map( ( c ) => [ c.id, c.status, c.extras ] ), [
    [ ROW_A, "dropped", { reason: "duplicate refile" } ],
    [ ROW_B, "dropped", { reason: "duplicate refile" } ],
  ] );
} );

// ---- the view click --------------------------------------------------------

function shower(): { shown: Array<{ text: string; title: string }>; show: ( a: Element, t: string, ti: string ) => void } {
  const shown: Array<{ text: string; title: string }> = [];
  return { shown, show: ( _a, text, title ) => { shown.push( { text, title } ); } };
}

test( "a click off any link, or on another link, is not claimed by the batch view handler", () => {
  const { show } = shower();
  const reader: TaskReader = async () => null;
  assert.equal( handleBatchViewLinkClick( new MouseEvent( "click" ), document.createElement( "div" ), reader, show ), false );
  const single = plant( document.body, `/app/tasks/view?row=${ ROW_A }` );
  assert.equal( handleBatchViewLinkClick( new MouseEvent( "click" ), single, reader, show ), false );
} );

test( "the batch view lists every row's status and title, in order, and an unreadable row says so", async () => {
  const { shown, show } = shower();
  const asked: string[] = [];
  const reader: TaskReader = async ( id ) => { asked.push( id ); return id === ROW_A ? { id, title: "Refile dup 1", status: "not_approved" } as never : null; };
  const a  = plant( document.body, VIEW( [ ROW_A, ROW_B ] ) );
  const ev = new MouseEvent( "click", { cancelable: true } );
  assert.equal( handleBatchViewLinkClick( ev, a, reader, show ), true );
  assert.equal( ev.defaultPrevented, true );
  await settle();
  assert.deepEqual( asked, [ ROW_A, ROW_B ] );
  assert.deepEqual( shown, [ { text: "a3975cf4 · not_approved · Refile dup 1\n0b1c2d3e · could not be read", title: "2 held rows" } ] );
} );

test( "a row with no status or title reads as dashes, not undefined", async () => {
  const { shown, show } = shower();
  const a = plant( document.body, VIEW( [ ROW_A ] ) );
  handleBatchViewLinkClick( new MouseEvent( "click", { cancelable: true } ), a, async () => ( {} as never ), show );
  await settle();
  assert.equal( shown[ 0 ]!.text, "a3975cf4 · — · (no title)" );
} );

test( "an untrusted view list says so and reads nothing", () => {
  const { shown, show } = shower();
  let read = 0;
  const a = plant( document.body, VIEW( [ ROW_A, ROW_A ] ) );
  assert.equal( handleBatchViewLinkClick( new MouseEvent( "click", { cancelable: true } ), a, async () => { read++; return null; }, show ), true );
  assert.equal( read, 0 );
  assert.deepEqual( shown, [ { text: "This link does not name a clean list of full ticket ids.", title: "Held rows" } ] );
} );

// ---- through the real renderer --------------------------------------------

function mount( approveSender: ApproveSender, taskReader: TaskReader ): Element {
  const bus     = createEventBusForTesting();
  const storage = createStorageServiceForTesting( bus );
  const store   = createReadingPaneStore( { bus, storage } );
  const win: WindowLike = { open(): WindowDocLike | null { throw new Error( "no tab may open" ); } } as WindowLike;
  const shell = document.createElement( "div" );
  shell.className = "content-shell";
  shell.innerHTML = `
    <div class="left-column">
      <button id="layout-mode-toggle" type="button">⇆</button>
      <button id="doc-roots-toggle" type="button">📂</button>
      <div id="action-required-section"><div id="action-required-content"></div></div>
      <div id="sender-cards-container"></div>
    </div>
    <div id="content-pane-splitter" role="separator"></div>
    <aside class="content-pane" id="content-pane" hidden>
      <button id="content-pane-back" type="button" disabled>←</button><span id="content-pane-title"></span>
      <button id="content-pane-bustout" type="button">⤢</button><button id="content-pane-close" type="button">×</button>
      <div id="content-pane-body"></div>
    </aside>`;
  document.body.appendChild( shell );
  const renderer = createReadingPaneRenderer( {
    eventBus : bus,
    stores   : { readingPane: store, actionRequired: { list: () => [] } },
    windowRef: win,
    approveSender,
    taskReader,
  } );
  renderer.mount( shell );
  active = renderer;
  return shell.querySelector( "#action-required-content" ) as Element;
}

test( "in the action-required card one click on the batch link applies both rows, and the 📋 click reads both", async () => {
  const asked: string[] = [];
  const host = mount( sender(), async ( id ) => { asked.push( id ); return { id, title: "t", status: "not_approved" } as never; } );
  const a = plant( host, OK( [ ROW_A, ROW_B ] ) );
  assert.equal( click( a ), true, "claimed" );
  await settle();
  assert.deepEqual( calls.map( ( c ) => c.id ), [ ROW_A, ROW_B ] );
  assert.match( host.textContent ?? "", /2 of 2 applied/ );
  const v = plant( host, VIEW( [ ROW_A, ROW_B ] ) );
  assert.equal( click( v ), true, "claimed" );
  await settle();
  assert.deepEqual( asked, [ ROW_A, ROW_B ] );
} );
