// Legacy notifications.js — reading-pane scroll-position preservation (2026-06-06).
//
// Rick's tweak: clicking the abstract icon (📋) in horizontal mode opened the
// reading pane but ALSO jumped the center content pane to the very top. Root
// cause: opening the pane adds `.pane-open`, which flips `.left-column` from
// "window scrolls" into its OWN scroll container (overflow-y:auto) that starts at
// scrollTop=0 — a scroll-container handoff, not an explicit scroll. The fix
// captures the topmost visible center card BEFORE the handoff and re-pins it to
// the same viewport position AFTER (an anchor, so it survives the 80%-width
// reflow). The jump only happens on the closed→open transition, so capture/restore
// is gated on `wasClosed && horizontal`.
//
// happy-dom has no real layout engine, so we stub getBoundingClientRect / scrollTop
// and assert the capture + restore ARITHMETIC and the gating — the logic, not the
// pixels. Real visual confirmation is the master-detail Playwright E2E on :8000.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/reading_pane_scroll_anchor.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

before( () => {
  if ( typeof globalThis.document === "undefined" ) {
    GlobalRegistrator.register();
  }
  const fullSource  = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx     = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  const classOnly   = fullSource.slice( 0, initIdx );
  vm.runInThisContext( classOnly + "\n;globalThis.NotificationsUI = NotificationsUI;" );
  assert.equal( typeof ( globalThis as Record<string, unknown> ).NotificationsUI, "function", "NotificationsUI loaded" );
} );

type AnyUI = Record<string, unknown> & {
  _captureCenterScrollAnchor: () => { el: Element; top: number } | null;
  _restoreCenterScrollAnchor: ( a: unknown ) => void;
  _openContentPane: ( type: string, payload: string, title: string ) => void;
};

function newUI(): AnyUI {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui = Object.create( Ctor.prototype ) as AnyUI;
  ui.debug = false;
  ui.log   = (): void => {};
  return ui;
}

// Stub an element's viewport rect (only `top` matters to the anchor logic).
function stubTop( el: Element, top: number | ( () => number ) ): void {
  ( el as unknown as { getBoundingClientRect: () => { top: number } } ).getBoundingClientRect =
    () => ( { top: typeof top === "function" ? top() : top } as { top: number } );
}

// Build .content-shell > .left-column > .container with the given card tops.
function buildCenterColumn( cardTops: number[] ): { shell: Element; leftColumn: HTMLElement; cards: Element[] } {
  document.body.replaceChildren();
  const shell = document.createElement( "div" );
  shell.className = "content-shell";
  const leftColumn = document.createElement( "div" );
  leftColumn.className = "left-column";
  const container = document.createElement( "div" );
  container.className = "container";
  const cards: Element[] = [];
  cardTops.forEach( ( top, i ) => {
    const card = document.createElement( "div" );
    card.className = "sender-card";
    card.setAttribute( "data-i", String( i ) );
    stubTop( card, top );
    container.appendChild( card );
    cards.push( card );
  } );
  leftColumn.appendChild( container );
  shell.appendChild( leftColumn );
  // The reading-pane DOM _openContentPane requires.
  const pane = document.createElement( "div" );
  pane.id = "content-pane";
  pane.hidden = true;
  const paneBody = document.createElement( "div" );
  paneBody.id = "content-pane-body";
  pane.appendChild( paneBody );
  shell.appendChild( pane );
  document.body.appendChild( shell );
  return { shell, leftColumn, cards };
}

beforeEach( () => { document.body.replaceChildren(); } );

test( "_captureCenterScrollAnchor returns the first card at/below the nav strip (100px)", () => {
  const ui = newUI();
  const { cards } = buildCenterColumn( [ -50, 120, 400 ] );   // card0 scrolled off-top

  const anchor = ui._captureCenterScrollAnchor();

  assert.ok( anchor, "an anchor is returned" );
  assert.equal( anchor?.el, cards[ 1 ], "skips the off-screen card0, anchors on card1 (top=120)" );
  assert.equal( anchor?.top, 120, "records card1's viewport top" );
} );

test( "_captureCenterScrollAnchor returns null when no card is visible below the nav", () => {
  const ui = newUI();
  buildCenterColumn( [ -200, -50 ] );   // every card scrolled above the nav strip
  assert.equal( ui._captureCenterScrollAnchor(), null, "no eligible anchor → null" );
} );

test( "_captureCenterScrollAnchor returns null when the center column is absent", () => {
  const ui = newUI();
  document.body.replaceChildren();
  assert.equal( ui._captureCenterScrollAnchor(), null, "no .left-column .container → null" );
} );

test( "_restoreCenterScrollAnchor scrolls the COLUMN by the drift when the pane is open", () => {
  const ui = newUI();
  const { shell, leftColumn, cards } = buildCenterColumn( [ 120 ] );
  shell.classList.add( "pane-open" );        // pane OPEN → column owns the scroll
  leftColumn.scrollTop = 0;
  // After the reflow the same card now sits at 300 → it drifted DOWN by 180,
  // so the column must scroll down 180 to bring it back to 120.
  stubTop( cards[ 0 ], 300 );

  ui._restoreCenterScrollAnchor( { el: cards[ 0 ], top: 120 } );

  assert.equal( leftColumn.scrollTop, 180, "column scrolled by (newTop - savedTop)" );
} );

test( "_restoreCenterScrollAnchor scrolls the WINDOW by the drift when the pane is closed", () => {
  const ui = newUI();
  const { cards } = buildCenterColumn( [ 120 ] );   // shell has NO .pane-open → window owns scroll
  stubTop( cards[ 0 ], 250 );                        // card drifted down by 130 after close
  const scrollByCalls: Array<[ number, number ]> = [];
  ( window as unknown as { scrollBy: ( x: number, y: number ) => void } ).scrollBy =
    ( x: number, y: number ): void => { scrollByCalls.push( [ x, y ] ); };

  ui._restoreCenterScrollAnchor( { el: cards[ 0 ], top: 120 } );

  assert.deepEqual( scrollByCalls, [ [ 0, 130 ] ], "window scrolled by (newTop - savedTop) when pane closed" );
} );

test( "_restoreCenterScrollAnchor is a no-op for null / detached anchor", () => {
  const ui = newUI();
  const { leftColumn, cards } = buildCenterColumn( [ 120 ] );
  leftColumn.scrollTop = 42;

  ui._restoreCenterScrollAnchor( null );
  assert.equal( leftColumn.scrollTop, 42, "null anchor → untouched" );

  const detached = cards[ 0 ];
  detached.remove();
  ui._restoreCenterScrollAnchor( { el: detached, top: 120 } );
  assert.equal( leftColumn.scrollTop, 42, "detached element → untouched" );
} );

test( "_openContentPane preserves center scroll on the closed→open handoff (horizontal)", () => {
  const ui = newUI();
  ui._contentPaneHistory     = [];
  ui._layoutMode             = "horizontal";
  ui._renderContentPaneEntry = (): void => {};       // skip markdown/iframe render
  ui._updateToolbarPosition  = (): void => {};

  const { shell, leftColumn, cards } = buildCenterColumn( [ 120 ] );
  leftColumn.scrollTop = 0;
  // The card reads 120 while closed, 250 once .pane-open is applied (reflow).
  stubTop( cards[ 0 ], () => ( shell.classList.contains( "pane-open" ) ? 250 : 120 ) );

  ui._openContentPane( "abstract", "**hi**", "Title" );

  assert.ok( shell.classList.contains( "pane-open" ), "pane opened" );
  assert.equal( leftColumn.scrollTop, 130, "column re-pinned by the 130px drift — no jump to top" );
} );

test( "_openContentPane skips scroll work when the pane is already open (no handoff)", () => {
  const ui = newUI();
  ui._contentPaneHistory     = [ { type: "abstract", payload: "x", title: "x" } ];
  ui._layoutMode             = "horizontal";
  ui._renderContentPaneEntry = (): void => {};
  ui._updateToolbarPosition  = (): void => {};

  const { shell, leftColumn, cards } = buildCenterColumn( [ 120 ] );
  shell.classList.add( "pane-open" );                // already open
  leftColumn.scrollTop = 99;
  stubTop( cards[ 0 ], 999 );                        // would move scrollTop if (wrongly) restored

  ui._openContentPane( "abstract", "**hi**", "Title2" );

  assert.equal( leftColumn.scrollTop, 99, "already-open → no capture/restore, scroll untouched" );
} );

test( "_openContentPane does not touch scroll in vertical mode", () => {
  const ui = newUI();
  ui._contentPaneHistory     = [];
  ui._layoutMode             = "vertical";
  ui._renderContentPaneEntry = (): void => {};
  ui._updateToolbarPosition  = (): void => {};

  const { leftColumn, cards } = buildCenterColumn( [ 120 ] );
  leftColumn.scrollTop = 7;
  stubTop( cards[ 0 ], 999 );

  ui._openContentPane( "abstract", "**hi**", "T" );

  assert.equal( leftColumn.scrollTop, 7, "vertical mode → gate skips, scroll untouched" );
} );

// ── Obverse: close-time preservation (2026-06-06, Rick) ───────────────────────

function stubWindowScrollBy(): Array<[ number, number ]> {
  const calls: Array<[ number, number ]> = [];
  ( window as unknown as { scrollBy: ( x: number, y: number ) => void } ).scrollBy =
    ( x: number, y: number ): void => { calls.push( [ x, y ] ); };
  return calls;
}

test( "_closeContentPane re-pins the center column to its calling position (reverse handoff)", () => {
  const ui = newUI();
  ui._contentPaneHistory    = [ { type: "abstract", payload: "x", title: "x" } ];
  ui._layoutMode            = "horizontal";
  ui._updateToolbarPosition = (): void => {};

  const { shell, cards } = buildCenterColumn( [ 120 ] );
  shell.classList.add( "pane-open" );        // currently OPEN
  // Card reads 120 while open (capture), 250 once .pane-open is removed (reflow).
  stubTop( cards[ 0 ], () => ( shell.classList.contains( "pane-open" ) ? 120 : 250 ) );
  const scrollByCalls = stubWindowScrollBy();

  ui._closeContentPane();

  assert.equal( shell.classList.contains( "pane-open" ), false, "pane closed" );
  assert.deepEqual( scrollByCalls, [ [ 0, 130 ] ], "window re-pinned by the 130px drift — no jump to top" );
} );

test( "_closeContentPane does no scroll work when already closed", () => {
  const ui = newUI();
  ui._contentPaneHistory    = [];
  ui._layoutMode            = "horizontal";
  ui._updateToolbarPosition = (): void => {};

  const { cards } = buildCenterColumn( [ 120 ] );   // shell has NO .pane-open
  stubTop( cards[ 0 ], 999 );
  const scrollByCalls = stubWindowScrollBy();

  ui._closeContentPane();

  assert.equal( scrollByCalls.length, 0, "already-closed → no capture/restore" );
} );

test( "_closeContentPane does no scroll work in vertical mode", () => {
  const ui = newUI();
  ui._contentPaneHistory    = [ { type: "abstract", payload: "x", title: "x" } ];
  ui._layoutMode            = "vertical";       // e.g. a switch-to-vertical close
  ui._updateToolbarPosition = (): void => {};

  const { shell, cards } = buildCenterColumn( [ 120 ] );
  shell.classList.add( "pane-open" );
  stubTop( cards[ 0 ], 999 );
  const scrollByCalls = stubWindowScrollBy();

  ui._closeContentPane();

  assert.equal( scrollByCalls.length, 0, "vertical mode → gate skips the reverse-handoff restore" );
} );
