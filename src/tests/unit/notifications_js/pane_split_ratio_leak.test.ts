// Pane-split-ratio leak regression (Rick 2026-06-09, fixed by Tiffany).
//
// BUG: abstracts in the Reading Pane rendered at 50% width instead of the
// historical ~1/3. Root cause: _enterActionRequiredPaneMode forces the columns
// to a 50/50 inline flex-grow split; when it took the pane with NOTHING stashed
// (the common case — a CC action-required card arriving with no abstract open),
// _exitActionRequiredPaneMode restored _paneSplitRatio to 0.667 IN MEMORY but
// went down the else-branch (_closeContentPane) WITHOUT re-applying it — leaving
// the inline flex-grow stuck at 50.00/50.00. _openContentPane never applied the
// ratio either, so the next abstract inherited the stale 50/50.
//
// FIX (two complementary one-liners):
//   (1) _openContentPane now calls _applyPaneSplitRatio() on every open, so an
//       abstract/doc is self-consistent at the user's reading width (default 1/3).
//   (2) _exitActionRequiredPaneMode's else-branch re-applies the restored ratio
//       before closing, so the inline styles aren't left at 50/50.
// Action-required keeps its own 50/50 (asserted in action_required_pane.test.ts).
//
// These tests use the REAL _applyPaneSplitRatio against a DOM with .left-column +
// #content-pane and assert the actual inline flex-grow (1/3 → "66.7"/"33.3").
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/pane_split_ratio_leak.test.ts

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
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext( fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;" );
} );

function newUI(): Record<string, unknown> {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui = Object.create( Ctor.prototype ) as Record<string, unknown>;
  ui.debug                       = false;
  ui.log                         = (): void => {};
  ui._layoutMode                 = "horizontal";
  ui._contentPaneHistory         = [];
  ui._paneSplitRatio             = 0.667;
  ui._actionRequiredInPane       = false;
  ui._arPaneStash                = null;
  ui.actionRequiredNotifications = new Map();
  // REAL _applyPaneSplitRatio (the thing under test). Stub only its irrelevant
  // toolbar side-effect + the scroll-anchor + markdown plumbing.
  ui._updateToolbarPosition   = (): void => {};
  ui._captureCenterScrollAnchor = (): unknown => null;
  ui._restoreCenterScrollAnchor = (): void => {};
  ui.renderMarkdown           = ( s: string ): string => s;
  ui._normalizeDocLinkHref    = ( s: string ): string => s;
  // Record close calls without tearing the DOM, so we isolate the inline flex-grow
  // left behind by the fix's _applyPaneSplitRatio() that runs just before close.
  ui._closeContentPane = function (): void { const t = this as Record<string, number>; t._closeCalled = ( t._closeCalled || 0 ) + 1; };
  return ui;
}

function buildDOM(): { leftColumn: HTMLElement; pane: HTMLElement } {
  document.body.replaceChildren();
  const section = document.createElement( "div" ); section.id = "action-required-section";
  const content = document.createElement( "div" ); content.id = "action-required-content"; content.className = "section-content";
  content.innerHTML = "<div class='ar-card'>card</div>";
  section.appendChild( content );

  const shell      = document.createElement( "div" ); shell.className = "content-shell";
  const leftColumn = document.createElement( "div" ); leftColumn.className = "left-column";
  const pane       = document.createElement( "div" ); pane.id = "content-pane"; pane.hidden = true;
  const title      = document.createElement( "div" ); title.id = "content-pane-title";
  const body       = document.createElement( "div" ); body.id = "content-pane-body";
  const back       = document.createElement( "button" ); back.id = "content-pane-back";
  pane.appendChild( title ); pane.appendChild( body ); pane.appendChild( back );
  shell.appendChild( leftColumn ); shell.appendChild( pane );
  document.body.appendChild( section );
  document.body.appendChild( shell );
  return { leftColumn, pane };
}

beforeEach( () => { document.body.replaceChildren(); } );

test( "_applyPaneSplitRatio writes 1/3 inline flex-grow at the default 0.667 ratio", () => {
  const ui = newUI();
  const { leftColumn, pane } = buildDOM();
  ( ui._applyPaneSplitRatio as () => void ).call( ui );
  assert.equal( leftColumn.style.flexGrow, "66.7", "left column = 2/3" );
  assert.equal( pane.style.flexGrow, "33.3", "content pane = 1/3 (historical abstract width)" );
} );

test( "_openContentPane re-asserts the 1/3 ratio over stale 50/50 inline styles", () => {
  const ui = newUI();
  const { leftColumn, pane } = buildDOM();
  // Simulate the leftover 50/50 a prior action-required split left behind.
  leftColumn.style.flexGrow = "50";
  pane.style.flexGrow       = "50";

  ( ui._openContentPane as ( t: string, p: string, title: string ) => void ).call( ui, "abstract", "**hi**", "T" );

  assert.equal( pane.style.flexGrow, "33.3", "abstract opens at 1/3, NOT the stale 50%" );
  assert.equal( leftColumn.style.flexGrow, "66.7" );
} );

test( "exit (nothing stashed) re-applies the restored ratio so no 50/50 leaks", () => {
  const ui = newUI();
  const { leftColumn, pane } = buildDOM();

  ( ui._enterActionRequiredPaneMode as () => void ).call( ui );   // priorEntry = null, forces 0.5
  assert.equal( pane.style.flexGrow, "50", "action-required forced 50/50" );

  ( ui._exitActionRequiredPaneMode as () => void ).call( ui );
  assert.equal( ui._paneSplitRatio, 0.667, "ratio restored in memory" );
  assert.equal( pane.style.flexGrow, "33.3", "inline flex-grow re-applied to 1/3 (no stale 50/50)" );
  assert.equal( ui._closeCalled, 1, "pane still closed (nothing prior to restore)" );
} );

test( "end-to-end repro: action-required drains, then an abstract opens at 1/3", () => {
  const ui = newUI();
  const { leftColumn, pane } = buildDOM();

  // 1) An action-required card takes the pane with nothing open before it.
  ( ui._enterActionRequiredPaneMode as () => void ).call( ui );
  assert.equal( pane.style.flexGrow, "50" );

  // 2) Queue drains → exit (else-branch, nothing stashed).
  ( ui._exitActionRequiredPaneMode as () => void ).call( ui );

  // 3) User clicks an abstract link in a CC notification card.
  ( ui._openContentPane as ( t: string, p: string, title: string ) => void ).call( ui, "abstract", "**body**", "Abstract" );

  assert.equal( pane.style.flexGrow, "33.3", "abstract renders at the historical 1/3, not 50%" );
  assert.equal( leftColumn.style.flexGrow, "66.7" );
} );

test( "a user-dragged ratio is preserved across an abstract open (drag not clobbered)", () => {
  const ui = newUI();
  ui._paneSplitRatio = 0.40;   // user dragged the splitter narrower
  const { leftColumn, pane } = buildDOM();

  ( ui._openContentPane as ( t: string, p: string, title: string ) => void ).call( ui, "abstract", "x", "T" );

  assert.equal( pane.style.flexGrow, "60", "abstract honors the user's dragged width, not a forced 1/3" );
  assert.equal( leftColumn.style.flexGrow, "40" );
} );
