// Tests for one-click ticket approval in the multiplexer.
//
// Each case enters through the real ReadingPaneRenderer and its document-level click listener.
// The links are planted in `#action-required-content`, the pane-resident surface whose doc
// links open a new tab. An approve link there must be claimed first, send once, and draw its answer.
//
// The sender is a recorder, so "a request went out" is read from its calls and not from the DOM.
// The task-list store resolves as done without sending when the row is not in its cache.
// A stray "approved ✅" on screen therefore proves nothing, and the first case asserts a call.
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
import { approveRowId, viewRowId, taskOverlayText, markApproveLinks, handleViewLinkClick, taskReaderFor } from "../../../../lupin_app/static/js/multiplexer/render/approveLink";
import type { ApproveSender, TaskReader } from "../../../../lupin_app/static/js/multiplexer/render/approveLink";
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

function setup( approveSender?: ApproveSender, taskReader?: TaskReader ): HTMLElement {
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
    ...( taskReader === undefined ? {} : { taskReader } ),
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
    a.textContent = "approve ☐";
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

test( "success replaces the link with a disabled approved ✅", async () => {
  const shell = setup( recorder() );
  const host  = shell.querySelector( "#action-required-content" ) as Element;
  const [ a ] = plant( host, [ APPROVE( ROW_A ) ] );
  click( a! );
  release[ 0 ]!( { ok: true } );
  await settle();
  assert.equal( host.querySelector( "a" ), null );
  const done = host.querySelector( ".approve-link-approved" ) as Element;
  assert.equal( done.textContent, "approved ✅" );
  assert.equal( done.getAttribute( "aria-disabled" ), "true", "no second click is possible" );
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


// ---------------------------------------------------------------------------
// Row 192fecdf — the 📄 view link; row 39624bae — the state of a card drawn after a reload
// ---------------------------------------------------------------------------

const VIEW   = ( id: string ): string => `/app/tasks/view?row=${ id }`;
const flush  = async (): Promise<void> => { await settle(); await new Promise( ( r ) => setTimeout( r, 0 ) ); await settle(); };
type Row = { title?: string; priority?: string | null; owner_persona?: string | null; status?: string; body?: string | null };

/** A reader that answers from a table and records every id it was asked for. */
function table( rows: Record<string, Row | null> ): { reader: TaskReader; asked: string[] } {
  const asked: string[] = [];
  return { asked, reader: async ( id ) => { asked.push( id ); return rows[ id ] ?? null; } };
}

test( "a 📄 link opens the overlay with title, priority, owner, status and the full body, and navigates nowhere", async () => {
  const { reader, asked } = table( { [ ROW_A ]: { title: "Fix X", priority: "P2", owner_persona: "krishna", status: "not_approved", body: "line one\nline two" } } );
  const shell = setup( recorder(), reader );
  const [ a ] = plant( shell.querySelector( "#action-required-content" ) as Element, [ VIEW( ROW_A ) ] );
  assert.equal( click( a! ), true, "claimed" );
  await flush();
  assert.deepEqual( asked, [ ROW_A ] );
  const overlay = document.getElementById( "task-body-overlay" ) as Element;
  assert.equal( overlay.querySelector( ".task-body-overlay-header" )?.textContent, `Task ${ ROW_A.slice( 0, 8 ) }` );
  assert.equal( overlay.querySelector( ".task-body-overlay-body" )?.textContent, "Fix X\nPriority: P2 · Owner: krishna · Status: not_approved\n\nline one\nline two" );
  assert.deepEqual( opens, [], "no new tab" );
  assert.deepEqual( calls, [], "viewing sends no approve" );
} );

test( "a 📄 link on a row that cannot be read says so in the overlay", async () => {
  const { reader } = table( {} );
  const shell = setup( recorder(), reader );
  const [ a ] = plant( shell.querySelector( "#action-required-content" ) as Element, [ VIEW( ROW_A ) ] );
  click( a! );
  await flush();
  assert.equal( document.querySelector( ".task-body-overlay-body" )?.textContent, "Could not read this ticket." );
} );

test( "without a reader a 📄 link is left alone", () => {
  const shell = setup( recorder() );
  const [ a ] = plant( shell.querySelector( "#action-required-content" ) as Element, [ VIEW( ROW_A ) ] );
  assert.equal( click( a! ), false );
} );

test( "viewRowId reads both href forms and refuses the approve path and malformed ids", () => {
  assert.equal( viewRowId( VIEW( ROW_A ) ), ROW_A );
  assert.equal( viewRowId( `http://localhost:7999${ VIEW( ROW_A ) }` ), ROW_A );
  for ( const bad of [ null, "/app/tasks/view?row=a3975cf4", APPROVE( ROW_A ), DOC_HREF ] ) assert.equal( viewRowId( bad ), null, String( bad ) );
} );

test( "handleViewLinkClick reports false for a click off any link", () => {
  const el = document.createElement( "div" );
  assert.equal( handleViewLinkClick( new MouseEvent( "click" ), el, async () => null ), false );
} );

test( "taskOverlayText fills a missing field with a dash, unowned or (no body), never undefined", () => {
  assert.equal( taskOverlayText( {} ), "(no title)\nPriority: — · Owner: unowned · Status: —\n\n(no body)" );
  assert.equal( taskOverlayText( { title: "T", priority: null, owner_persona: null, body: null, status: "queued" } ), "T\nPriority: — · Owner: unowned · Status: queued\n\n(no body)" );
} );

test( "a card drawn later: a held row keeps its live link, a live or done row reads approved ✅ and is disabled", async () => {
  const { reader } = table( {
    [ ROW_A ]: { status: "not_approved" }, [ ROW_B ]: { status: "queued" }, [ ROW_C ]: { status: "done" },
  } );
  const shell = setup( recorder(), reader );
  const host  = shell.querySelector( "#action-required-content" ) as Element;
  plant( host, [ APPROVE( ROW_A ), APPROVE( ROW_B ), APPROVE( ROW_C ) ] );
  await flush();
  assert.deepEqual( [ ...host.querySelectorAll( "a" ) ].map( ( e ) => e.getAttribute( "href" ) ), [ APPROVE( ROW_A ) ], "only the held row keeps a link" );
  const done = [ ...host.querySelectorAll( ".approve-link-approved" ) ];
  assert.deepEqual( done.map( ( e ) => e.textContent ), [ "approved ✅", "approved ✅" ] );
  assert.ok( done.every( ( e ) => e.getAttribute( "aria-disabled" ) === "true" ) );
} );

test( "a dropped or wont_fix row reads as its plain status, never approved", async () => {
  const { reader } = table( { [ ROW_A ]: { status: "dropped" }, [ ROW_B ]: { status: "wont_fix" } } );
  const shell = setup( recorder(), reader );
  const host  = shell.querySelector( "#action-required-content" ) as Element;
  plant( host, [ APPROVE( ROW_A ), APPROVE( ROW_B ) ] );
  await flush();
  assert.deepEqual( [ ...host.querySelectorAll( ".approve-link-closed" ) ].map( ( e ) => e.textContent ), [ "dropped", "wont_fix" ] );
  assert.equal( host.querySelector( ".approve-link-approved" ), null );
  assert.equal( host.querySelector( "a" ), null );
} );

test( "a failed read, or a row with no status, leaves the live link", async () => {
  const { reader } = table( { [ ROW_B ]: {} } );
  const shell = setup( recorder(), reader );
  const host  = shell.querySelector( "#action-required-content" ) as Element;
  plant( host, [ APPROVE( ROW_A ), APPROVE( ROW_B ) ] );
  await flush();
  assert.equal( host.querySelectorAll( "a" ).length, 2 );
} );

test( "the same row id twice in one card is read once and both links are drawn the same", async () => {
  const { reader, asked } = table( { [ ROW_A ]: { status: "in_progress" } } );
  const shell = setup( recorder(), reader );
  const host  = shell.querySelector( "#action-required-content" ) as Element;
  plant( host, [ APPROVE( ROW_A ), APPROVE( ROW_A ) ] );
  await flush();
  assert.deepEqual( asked, [ ROW_A ], "one read" );
  assert.equal( host.querySelectorAll( ".approve-link-approved" ).length, 2 );
} );

test( "links already on the page when the renderer mounts are checked too", async () => {
  const { reader, asked } = table( { [ ROW_A ]: { status: "queued" } } );
  const early = document.createElement( "div" );
  early.innerHTML = `<a href="${ APPROVE( ROW_A ) }">approve ☐</a>`;
  document.body.appendChild( early );
  setup( recorder(), reader );
  await flush();
  assert.deepEqual( asked, [ ROW_A ] );
  assert.equal( early.textContent, "approved ✅" );
} );

test( "a link clicked before the read answers is not replaced by the read", async () => {
  const { reader } = table( { [ ROW_A ]: { status: "queued" } } );
  const shell = setup( recorder(), reader );
  const host  = shell.querySelector( "#action-required-content" ) as Element;
  const [ a ] = plant( host, [ APPROVE( ROW_A ) ] );
  click( a! );
  await flush();
  assert.ok( host.contains( a! ), "the pending link stays until the click's own answer" );
  release[ 0 ]!( { ok: true } );
  await settle();
  assert.equal( host.querySelector( ".approve-link-approved" )?.textContent, "approved ✅" );
} );

test( "a link already checked is not read again, and a disconnected one is skipped", async () => {
  const { reader, asked } = table( { [ ROW_A ]: { status: "queued" } } );
  const host = document.createElement( "div" );
  const a    = document.createElement( "a" );
  a.setAttribute( "href", APPROVE( ROW_A ) );
  host.appendChild( a );
  const pending = markApproveLinks( [ host ], reader );
  a.remove();
  await pending;
  await markApproveLinks( [ host ], reader );
  const b = document.createElement( "a" );
  b.setAttribute( "href", APPROVE( ROW_A ) );
  b.setAttribute( "data-approve-checked", "1" );
  host.appendChild( b );
  await markApproveLinks( [ host ], reader );
  assert.deepEqual( asked, [ ROW_A ], "one read in total" );
  assert.equal( host.contains( b ), true, "an already-checked link is untouched" );
} );

test( "an anchor passed directly as a root is checked", async () => {
  const { reader } = table( { [ ROW_A ]: { status: "done" } } );
  const host = document.createElement( "div" );
  const a    = document.createElement( "a" );
  a.setAttribute( "href", APPROVE( ROW_A ) );
  host.appendChild( a );
  document.body.appendChild( host );
  await markApproveLinks( [ a ], reader );
  assert.equal( host.textContent, "approved ✅" );
} );

test( "unmount stops the watch: a card drawn afterwards is not read", async () => {
  const { reader, asked } = table( { [ ROW_A ]: { status: "queued" } } );
  const shell = setup( recorder(), reader );
  active!.unmount(); active = null;
  plant( shell.querySelector( "#action-required-content" ) as Element, [ APPROVE( ROW_A ) ] );
  await flush();
  assert.deepEqual( asked, [] );
} );

test( "text nodes drawn into the page start no read", async () => {
  const { reader, asked } = table( {} );
  setup( recorder(), reader );
  document.body.appendChild( document.createTextNode( "plain text" ) );
  await flush();
  assert.deepEqual( asked, [] );
} );

test( "with a reader set, a doc link is still not claimed as a view link", () => {
  const shell = setup( recorder(), table( {} ).reader );
  const [ d ] = plant( shell.querySelector( "#sender-cards-container" ) as Element, [ DOC_HREF ] );
  click( d! );
  assert.equal( document.getElementById( "task-body-overlay" ), null );
  assert.deepEqual( calls, [] );
} );

test( "a ticket body carrying an img tag is shown as text and creates no element in the overlay", async () => {
  const evil = '<img src=x onerror="window.__pwned=1">';
  const { reader } = table( { [ ROW_A ]: { title: evil, status: "queued", body: `before ${ evil } after` } } );
  const shell = setup( recorder(), reader );
  const [ a ] = plant( shell.querySelector( "#action-required-content" ) as Element, [ VIEW( ROW_A ) ] );
  click( a! );
  await flush();
  const overlay = document.getElementById( "task-body-overlay" ) as Element;
  assert.ok( overlay.querySelector( ".task-body-overlay-body" )?.textContent?.includes( `before ${ evil } after` ), "the tag is visible as characters" );
  assert.equal( overlay.querySelector( "img" ), null, "no img element exists" );
  assert.equal( ( globalThis as unknown as { __pwned?: number } ).__pwned, undefined );
} );

test( "taskReaderFor reads the row's own path with the id encoded, and answers null when the read fails", async () => {
  const asked: string[] = [];
  const ok = taskReaderFor( { get: async <T,>( path: string ): Promise<T> => { asked.push( path ); return { status: "queued" } as unknown as T; } } );
  assert.deepEqual( await ok( "a/b?c#d" ), { status: "queued" } );
  assert.deepEqual( asked, [ "/api/tasks/a%2Fb%3Fc%23d" ] );
  const down = taskReaderFor( { get: async (): Promise<never> => { throw new Error( "down" ); } } );
  assert.equal( await down( ROW_A ), null );
} );
