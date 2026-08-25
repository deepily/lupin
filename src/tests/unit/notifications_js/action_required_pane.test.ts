// Action-required-in-reading-pane mode (Rick 2026-06-08).
//
// In HORIZONTAL layout, _enterActionRequiredPaneMode LIFTS-AND-MOVES the live
// #action-required-content element into the reader pane at a forced 0.5 split,
// stashing the prior pane content + divider position. _exitActionRequiredPaneMode
// moves it back home and restores BOTH the prior content AND the divider (split
// ratio) — or closes the pane if nothing was stashed. happy-dom asserts the DOM
// moves + stash/restore arithmetic; visual confirmation is the Playwright E2E.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/action_required_pane.test.ts

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
  // Stubs for the pane plumbing the mode methods call.
  ui._applyPaneSplitRatio   = (): void => {};
  ui._updateToolbarPosition = (): void => {};
  ui._renderContentPaneEntry = function ( entry: unknown ): void { ( this as Record<string, unknown> )._renderedEntry = entry; };
  ui._closeContentPane = function (): void { const t = this as Record<string, number>; t._closeCalled = ( t._closeCalled || 0 ) + 1; };
  return ui;
}

function buildDOM(): { section: HTMLElement; content: HTMLElement; shell: HTMLElement; pane: HTMLElement; body: HTMLElement } {
  document.body.replaceChildren();
  const section = document.createElement( "div" ); section.id = "action-required-section";
  const content = document.createElement( "div" ); content.id = "action-required-content"; content.className = "section-content";
  content.innerHTML = "<div class='ar-card'>card</div>";
  section.appendChild( content );
  const shell = document.createElement( "div" ); shell.className = "content-shell";
  const pane  = document.createElement( "div" ); pane.id = "content-pane"; pane.hidden = true;
  const title = document.createElement( "div" ); title.id = "content-pane-title";
  const body  = document.createElement( "div" ); body.id = "content-pane-body";
  pane.appendChild( title ); pane.appendChild( body );
  shell.appendChild( pane );
  document.body.appendChild( section );
  document.body.appendChild( shell );
  return { section, content, shell, pane, body };
}

beforeEach( () => { document.body.replaceChildren(); } );

test( "enter: lifts content into the pane, hides home, forces 0.5, stashes prior ratio", () => {
  const ui = newUI();
  const { section, content, shell, pane, body } = buildDOM();

  ( ui._enterActionRequiredPaneMode as () => void ).call( ui );

  assert.equal( ui._actionRequiredInPane, true );
  assert.ok( content.parentNode === body, "content moved into the pane body" );
  assert.ok( content.classList.contains( "in-reading-pane" ) );
  assert.equal( section.style.display, "none", "home section hidden" );
  assert.ok( shell.classList.contains( "pane-open" ) );
  assert.equal( pane.hidden, false );
  assert.equal( ui._paneSplitRatio, 0.5, "split forced to 0.5" );
  assert.equal( ( ui._arPaneStash as Record<string, unknown> ).priorRatio, 0.667, "prior ratio stashed" );
  assert.equal( ( ui._arPaneStash as Record<string, unknown> ).priorEntry, null );
} );

test( "enter: no-op in vertical mode", () => {
  const ui = newUI(); ui._layoutMode = "vertical";
  const { content, body } = buildDOM();
  ( ui._enterActionRequiredPaneMode as () => void ).call( ui );
  assert.equal( ui._actionRequiredInPane, false );
  assert.ok( content.parentNode !== body, "content NOT moved in vertical mode" );
} );

test( "enter: idempotent when already in pane mode", () => {
  const ui = newUI();
  buildDOM();
  ( ui._enterActionRequiredPaneMode as () => void ).call( ui );
  const stash1 = ui._arPaneStash;
  ( ui._enterActionRequiredPaneMode as () => void ).call( ui );
  assert.equal( ui._arPaneStash, stash1, "second enter is a no-op (stash object unchanged)" );
} );

test( "exit (nothing stashed): content home, section shown, pane closed, ratio restored", () => {
  const ui = newUI();
  const { section, content } = buildDOM();
  ( ui._enterActionRequiredPaneMode as () => void ).call( ui );   // priorEntry = null
  ( ui._exitActionRequiredPaneMode as () => void ).call( ui );

  assert.equal( ui._actionRequiredInPane, false );
  assert.ok( content.parentNode === section, "content moved back to its home section" );
  assert.ok( !content.classList.contains( "in-reading-pane" ) );
  assert.equal( section.style.display, "", "home section shown again" );
  assert.equal( ui._paneSplitRatio, 0.667, "divider/ratio restored" );
  assert.equal( ui._closeCalled, 1, "pane closed (nothing prior to restore)" );
} );

test( "exit: restores the prior abstract AND the divider position", () => {
  const ui = newUI();
  ui._paneSplitRatio     = 0.72;
  ui._contentPaneHistory = [ { type: "abstract", payload: "**hi**", title: "Prior" } ];
  const { section, content } = buildDOM();

  ( ui._enterActionRequiredPaneMode as () => void ).call( ui );    // stashes priorEntry + 0.72
  assert.equal( ui._paneSplitRatio, 0.5, "forced to 0.5 while up" );

  ( ui._exitActionRequiredPaneMode as () => void ).call( ui );
  assert.ok( content.parentNode === section, "content back home" );
  assert.deepEqual( ui._renderedEntry, { type: "abstract", payload: "**hi**", title: "Prior" }, "prior abstract re-rendered" );
  assert.equal( ui._paneSplitRatio, 0.72, "divider/ratio restored EXACTLY" );
  assert.equal( ui._closeCalled, undefined, "pane NOT closed (prior content restored instead)" );
} );

test( "exit: no-op when not in pane mode", () => {
  const ui = newUI();
  buildDOM();
  ( ui._exitActionRequiredPaneMode as () => void ).call( ui );
  assert.equal( ui._actionRequiredInPane, false );
  assert.equal( ui._closeCalled, undefined );
} );
