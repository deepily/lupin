// Tests for the one-click priority link in the multiplexer (row 54d62c0e).
//
// Each case enters through the real ReadingPaneRenderer and its document-level click listener.
// The links are planted in `#action-required-content`, the pane-resident surface whose doc
// links open a new tab. An approve link there must be claimed first, send once, and draw its answer.
//
// The sender is a recorder, so "a request went out" is read from its calls and not from the DOM.
// The task-list store resolves as done without sending when the row is not in its cache.
// A stray "approved ✅" on screen therefore proves nothing, and the first case asserts a call.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/promote_p0_link.test.ts

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
import { createAbstractTooltip } from "../../../../lupin_app/static/js/multiplexer/render/abstractTooltip";
import type { AbstractTooltip } from "../../../../lupin_app/static/js/multiplexer/render/abstractTooltip";
import { createReadingPaneRenderer } from "../../../../lupin_app/static/js/multiplexer/render/ReadingPaneRenderer";
import type { ReadingPaneRenderer, WindowLike, WindowDocLike } from "../../../../lupin_app/static/js/multiplexer/render/ReadingPaneRenderer";
import { approveRowId, approvePriorityLink, handleApprovePriorityLinkClick, markApproveLinks } from "../../../../lupin_app/static/js/multiplexer/render/approveLink";
import type { ApproveSender, TaskReader } from "../../../../lupin_app/static/js/multiplexer/render/approveLink";
import type { HoldingTransitionResult } from "../../../../lupin_app/static/js/multiplexer/stores/HoldingAreaStore";

const ROW_A    = "a3975cf4-c640-4659-9247-0a99fa8a5f4a";
const ROW_B    = "0b1c2d3e-4f50-4a61-8b72-93a4b5c6d7e8";
const ROW_C    = "c3d4e5f6-0718-4293-a4b5-c6d7e8f90a1b";
const APPROVE  = ( id: string ): string => `/app/tasks/approve?row=${ id }`;
const P0LINK   = ( id: string ): string => `/app/tasks/approve?row=${ id }&priority=P0`;
const DOC_HREF = "/app/docs?path=lupin/src/rnd/a-real-doc.md";

let active  : ReadingPaneRenderer | null = null;
let tip     : AbstractTooltip | null = null;
let calls   : Array<{ id: string; status: string; extras: unknown }>;
let release : Array<( r: HoldingTransitionResult ) => void>;
let opens   : unknown[];
let globalOpens: unknown[];

const VENDOR = resolve( dirname( fileURLToPath( import.meta.url ) ), "../../../../lupin_app/static/js/vendor" );

// The real vendored marked and DOMPurify, so the pane and the tooltip render the way the page does.
before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  vm.runInThisContext( readFileSync( resolve( VENDOR, "marked.min.js" ), "utf8" ) );
  vm.runInThisContext( readFileSync( resolve( VENDOR, "purify.min.js" ), "utf8" ) );
} );
beforeEach( () => {
  document.body.replaceChildren(); calls = []; release = []; opens = []; globalOpens = [];
  // A global spy, so a stray window.open from any module reddens a test, not only one through the renderer's windowRef.
  ( globalThis as unknown as { open: unknown } ).open = ( ...args: unknown[] ): null => { globalOpens.push( args ); return null; };
} );

/** Neither the renderer's window nor the global window opened a tab. */
function assertNoTab(): void {
  assert.deepEqual( opens, [], "no new tab through the renderer's window" );
  assert.deepEqual( globalOpens, [], "no new tab through the global window.open" );
}
afterEach( () => { if ( active !== null ) { active.unmount(); active = null; } if ( tip !== null ) { tip.unmount(); tip = null; } } );

const settle = async (): Promise<void> => { for ( let i = 0; i < 5; i++ ) await Promise.resolve(); };

function recorder(): ApproveSender {
  return {
    transitionTask( id, status, extras ) {
      calls.push( { id, status, extras } );
      return new Promise<HoldingTransitionResult>( ( res ) => { release.push( res ); } );
    },
  };
}

/** Mount the renderer, vertical by default; `withTooltip: false` builds no tooltip. */
function setup( approveSender?: ApproveSender, taskReader?: TaskReader, layout: "vertical" | "horizontal" = "vertical", withTooltip = true, arOwnsPane = false ): HTMLElement {
  const bus     = createEventBusForTesting();
  const storage = createStorageServiceForTesting( bus );
  const store   = createReadingPaneStore( { bus, storage } );
  const win: WindowLike = {
    open( ...args: unknown[] ): WindowDocLike | null { opens.push( args ); return { document: { open() {}, write() {}, close() {} } }; },
  } as WindowLike;
  const tooltip = createAbstractTooltip( { getLayoutMode: () => store.getLayoutMode(), schedule: ( fn ) => fn() } );
  if ( withTooltip ) { tooltip.mount(); tip = tooltip; }
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
    stores   : { readingPane: store, actionRequired: { list: () => ( arOwnsPane ? [ { state: "pending" } ] : [] ) } },
    windowRef: win,
    ...( approveSender === undefined ? {} : { approveSender } ),
    ...( taskReader === undefined ? {} : { taskReader } ),
    ...( withTooltip ? { tooltip } : {} ),
  } );
  renderer.mount( shell );
  active = renderer;
  if ( layout === "horizontal" ) ( shell.querySelector( "#layout-mode-toggle" ) as HTMLElement ).click();
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


test( "a P0 link in the card is claimed and sends queued with promote_priority P0 once, opening no tab", () => {
  const shell = setup( recorder() );
  const [ a ] = plant( shell.querySelector( "#action-required-content" ) as Element, [ P0LINK( ROW_A ) ] );
  assert.equal( click( a! ), true, "claimed" );
  assert.equal( click( a! ), true, "still claimed on a second click" );
  assert.deepEqual( calls, [ { id: ROW_A, status: "queued", extras: { promote_priority: "P0" } } ], "one request, carrying the level" );
  assertNoTab();
} );

test( "the plain approve link sends no P0 flag and the P0 link is not read as a plain approve link", () => {
  const shell = setup( recorder() );
  const [ plain ] = plant( shell.querySelector( "#action-required-content" ) as Element, [ APPROVE( ROW_A ) ] );
  click( plain! );
  assert.deepEqual( calls, [ { id: ROW_A, status: "queued", extras: {} } ] );
  assert.equal( approveRowId( P0LINK( ROW_A ) ), null );
  assert.equal( approvePriorityLink( APPROVE( ROW_A ) ), null );
  assert.deepEqual( approvePriorityLink( `/app/tasks/approve?row=${ ROW_A }&priority=P3` ), { rowId: ROW_A, priority: "P3" } );
  assert.equal( approvePriorityLink( `/app/tasks/approve?row=${ ROW_A }&priority=P6` ), null, "a level outside P0..P5" );
} );

test( "success draws approved at <level> ✅, disabled", async () => {
  const shell = setup( recorder() );
  const host  = shell.querySelector( "#action-required-content" ) as Element;
  const [ a ] = plant( host, [ `/app/tasks/approve?row=${ ROW_A }&priority=P2` ] );
  click( a! );
  release[ 0 ]!( { ok: true } );
  await settle();
  assert.ok( host.querySelector( "a" ) === null );
  const done = host.querySelector( ".approve-link-approved" ) as Element;
  assert.equal( done.textContent, "approved at P2 ✅" );
  assert.equal( done.getAttribute( "aria-disabled" ), "true" );
} );

test( "a refusal shows the server's words, not an approval", async () => {
  const shell = setup( recorder() );
  const host  = shell.querySelector( "#action-required-content" ) as Element;
  const [ a ] = plant( host, [ P0LINK( ROW_A ) ] );
  click( a! );
  release[ 0 ]!( { ok: false, message: "Promote-to-P0 is honoured only for Rick's login." } );
  await settle();
  assert.equal( host.querySelector( ".approve-link-refused" )?.textContent, "Promote-to-P0 is honoured only for Rick's login." );
  assert.ok( host.querySelector( ".approve-link-approved" ) === null );
} );

test( "malformed P0 hrefs are not claimed; without a sender the link is left alone", () => {
  assert.equal( approvePriorityLink( null ), null );
  assert.equal( approvePriorityLink( "/app/tasks/approve?row=a3975cf4&priority=P0" ), null );
  const shell = setup();
  const [ a ] = plant( shell.querySelector( "#action-required-content" ) as Element, [ P0LINK( ROW_A ) ] );
  assert.equal( click( a! ), false );
  const off = document.createElement( "div" );
  assert.equal( handleApprovePriorityLinkClick( new Event( "click" ), off, recorder() ), false, "not inside an anchor" );
  const other = plant( shell.querySelector( "#sender-cards-container" ) as Element, [ DOC_HREF ] )[ 0 ]!;
  assert.equal( handleApprovePriorityLinkClick( new Event( "click" ), other, recorder() ), false, "an ordinary link" );
  assert.deepEqual( calls, [] );
} );

test( "a drawn P0 link for a row that already left the holding area reads approved ✅", async () => {
  const shell = setup();
  const host  = shell.querySelector( "#action-required-content" ) as Element;
  plant( host, [ P0LINK( ROW_A ) ] );
  await markApproveLinks( [ host ], async () => ( { status: "queued" } as never ) );
  assert.equal( host.querySelector( ".approve-link-approved" )?.textContent, "approved ✅" );
} );
