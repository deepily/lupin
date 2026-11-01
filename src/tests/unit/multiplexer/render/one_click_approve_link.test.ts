// Tests for one-click ticket approval in the multiplexer.
//
// Each case enters through the real ReadingPaneRenderer and its document-level click listener.
// The links are planted in `#action-required-content`, the pane-resident surface whose doc
// links open a new tab. An approve link there must be claimed first, send once, and draw its answer.
//
// The sender is a recorder, so "a request went out" is read from its calls and not from the DOM.
// The task-list store resolves as done without sending when the row is not in its cache.
// A stray "Approved ✓" on screen therefore proves nothing, and the first case asserts a call.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/one_click_approve_link.test.ts

import { test, before, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createStorageServiceForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/StorageService";
import { createReadingPaneStore } from "../../../../lupin_app/static/js/multiplexer/stores/ReadingPaneStore";
import { createReadingPaneRenderer } from "../../../../lupin_app/static/js/multiplexer/render/ReadingPaneRenderer";
import type { ReadingPaneRenderer, WindowLike, WindowDocLike } from "../../../../lupin_app/static/js/multiplexer/render/ReadingPaneRenderer";
import { approveRowId } from "../../../../lupin_app/static/js/multiplexer/render/approveLink";
import type { ApproveSender } from "../../../../lupin_app/static/js/multiplexer/render/approveLink";
import type { HoldingTransitionResult } from "../../../../lupin_app/static/js/multiplexer/stores/HoldingAreaStore";

const ROW_A    = "a3975cf4-c640-4659-9247-0a99fa8a5f4a";
const ROW_B    = "0b1c2d3e-4f50-4a61-8b72-93a4b5c6d7e8";
const ROW_C    = "c3d4e5f6-0718-4293-a4b5-c6d7e8f90a1b";
const APPROVE  = ( id: string ): string => `/app/tasks/approve?row=${ id }`;
const DOC_HREF = "/app/docs?path=lupin/src/rnd/a-real-doc.md";

let active  : ReadingPaneRenderer | null = null;
let calls   : Array<{ id: string; status: string; extras: unknown }>;
let release : Array<( r: HoldingTransitionResult ) => void>;
let opens   : unknown[];

before( () => { if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register(); } );
beforeEach( () => { document.body.replaceChildren(); calls = []; release = []; opens = []; } );
afterEach( () => { if ( active !== null ) { active.unmount(); active = null; } } );

const settle = async (): Promise<void> => { for ( let i = 0; i < 5; i++ ) await Promise.resolve(); };

function recorder(): ApproveSender {
  return {
    transitionTask( id, status, extras ) {
      calls.push( { id, status, extras } );
      return new Promise<HoldingTransitionResult>( ( res ) => { release.push( res ); } );
    },
  };
}

function setup( approveSender?: ApproveSender ): HTMLElement {
  const bus     = createEventBusForTesting();
  const storage = createStorageServiceForTesting( bus );
  const store   = createReadingPaneStore( { bus, storage } );
  const win: WindowLike = {
    open( ...args: unknown[] ): WindowDocLike | null { opens.push( args ); return { document: { open() {}, write() {}, close() {} } }; },
  } as WindowLike;
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
    ...( approveSender === undefined ? {} : { approveSender } ),
  } );
  renderer.mount( shell );
  active = renderer;
  return shell;
}

function plant( host: Element, hrefs: string[] ): HTMLAnchorElement[] {
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

function click( a: Element ): boolean {
  const ev = new MouseEvent( "click", { bubbles: true, cancelable: true } );
  a.dispatchEvent( ev );
  return ev.defaultPrevented;
}

test( "an approve link in the action-required card is claimed, sent once with the row id, and opens no tab", () => {
  const shell = setup( recorder() );
  const [ a ] = plant( shell.querySelector( "#action-required-content" ) as Element, [ APPROVE( ROW_A ) ] );
  assert.equal( click( a! ), true, "claimed" );
  assert.deepEqual( calls, [ { id: ROW_A, status: "queued", extras: {} } ], "a request was made: one, for this row, to queued" );
  assert.deepEqual( opens, [], "no new tab, though a doc link in this card would open one" );
} );

test( "success replaces the link with Approved ✓", async () => {
  const shell = setup( recorder() );
  const host  = shell.querySelector( "#action-required-content" ) as Element;
  const [ a ] = plant( host, [ APPROVE( ROW_A ) ] );
  click( a! );
  release[ 0 ]!( { ok: true } );
  await settle();
  assert.equal( host.querySelector( "a" ), null );
  assert.equal( host.querySelector( ".approve-link-approved" )?.textContent, "Approved ✓" );
} );

test( "a refusal shows the server's words; a pending answer shows its message too", async () => {
  const shell = setup( recorder() );
  const host  = shell.querySelector( "#action-required-content" ) as Element;
  const [ a, b ] = plant( host, [ APPROVE( ROW_A ), APPROVE( ROW_B ) ] );
  click( a! ); click( b! );
  release[ 0 ]!( { ok: false, message: "only an operator may approve" } );
  release[ 1 ]!( { ok: false, message: "Waiting on Rick — he has not been asked yet.", pending: true, ticketId: "t1" } );
  await settle();
  const texts = [ ...host.querySelectorAll( ".approve-link-refused" ) ].map( ( e ) => e.textContent );
  assert.deepEqual( texts, [ "only an operator may approve", "Waiting on Rick — he has not been asked yet." ] );
  assert.equal( host.querySelector( ".approve-link-approved" ), null );
} );

test( "a second click while the request is out sends nothing", () => {
  const shell = setup( recorder() );
  const [ a ] = plant( shell.querySelector( "#action-required-content" ) as Element, [ APPROVE( ROW_A ) ] );
  click( a! );
  assert.equal( click( a! ), true, "still claimed" );
  assert.equal( calls.length, 1 );
  assert.equal( a!.getAttribute( "aria-disabled" ), "true" );
} );

test( "three links: two clicks send exactly those two rows", () => {
  const shell = setup( recorder() );
  const anchors = plant( shell.querySelector( "#action-required-content" ) as Element, [ APPROVE( ROW_A ), APPROVE( ROW_B ), APPROVE( ROW_C ) ] );
  click( anchors[ 0 ]! ); click( anchors[ 2 ]! );
  assert.deepEqual( calls.map( ( c ) => c.id ), [ ROW_A, ROW_C ] );
} );

test( "doc links are unchanged: history opens the pane, the card opens a tab, no approve is sent", () => {
  const shell = setup( recorder() );
  const [ h ] = plant( shell.querySelector( "#sender-cards-container" ) as Element, [ DOC_HREF ] );
  assert.equal( click( h! ), true );
  const [ c ] = plant( shell.querySelector( "#action-required-content" ) as Element, [ DOC_HREF ] );
  assert.equal( click( c! ), true );
  assert.equal( opens.length, 1, "the card's doc link still opens a new tab" );
  assert.deepEqual( calls, [] );
} );

test( "without a sender an approve link is left alone", () => {
  const shell = setup();
  const [ a ] = plant( shell.querySelector( "#action-required-content" ) as Element, [ APPROVE( ROW_A ) ] );
  assert.equal( click( a! ), false );
  assert.deepEqual( calls, [] );
} );

test( "approveRowId reads both href forms and refuses short, upper-case, empty and foreign ones", () => {
  assert.equal( approveRowId( APPROVE( ROW_A ) ), ROW_A );
  assert.equal( approveRowId( `http://localhost:7999${ APPROVE( ROW_A ) }` ), ROW_A );
  for ( const bad of [ null, "", "/app/tasks/approve?row=a3975cf4", APPROVE( ROW_A.toUpperCase() ), "/app/tasks/approve", "https://example.com/x", DOC_HREF ] ) {
    assert.equal( approveRowId( bad ), null, String( bad ) );
  }
} );

test( "an external link and a click off any link are left alone", () => {
  const shell = setup( recorder() );
  const [ e ] = plant( shell.querySelector( "#action-required-content" ) as Element, [ "https://example.com/x" ] );
  assert.equal( click( e! ), false );
  assert.equal( click( shell.querySelector( "#action-required-content" ) as Element ), false );
  assert.deepEqual( calls, [] );
} );
