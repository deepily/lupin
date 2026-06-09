// Manager-lineage corner badge on the focus-bar strip icon (Rick 2026-06-08).
//
// _addStripIcon reads this.managerPersonaMap.get(senderId) and, when present,
// appends a `.cc-strip-manager-badge` child (manager glyph + initial, tinted with
// the manager's color) to the worker's strip icon, and sets data-has-manager.
// Roots / unknown-manager get no badge. happy-dom has no layout engine, so we
// assert the DOM the method builds — the CSS places it; visual confirmation is the
// master-detail Playwright E2E on :8000.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/manager_badge_strip.test.ts

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

type StripUI = Record<string, unknown> & {
  managerPersonaMap: Map<string, unknown>;
  _addStripIcon: ( senderId: string, project: string, persona: unknown, sessionId: string ) => void;
  _stripIconIdFor: ( senderId: string ) => string;
};

function newUI(): StripUI {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui = Object.create( Ctor.prototype ) as StripUI;
  ui.debug                = false;
  ui.log                  = (): void => {};
  ui.managerPersonaMap    = new Map();
  ui.ccFocusState         = { enabled: false, focused_sender_id: null };
  ui.conversationModes    = {};
  ui.ccHideInactiveStrip  = false;
  ui.ccStripUnreadCounts  = {};
  return ui;
}

function buildStripDOM(): void {
  document.body.replaceChildren();
  const strip = document.createElement( "div" );
  strip.id = "cc-session-strip";
  strip.setAttribute( "hidden", "" );
  const icons = document.createElement( "div" );
  icons.id = "cc-strip-icons";
  strip.appendChild( icons );
  document.body.appendChild( strip );
}

beforeEach( () => { document.body.replaceChildren(); } );

test( "manager badge is appended when managerPersonaMap has the sender", () => {
  const ui = newUI();
  buildStripDOM();
  const senderId = "claude.code@lupin.deepily.ai#worker01";
  ui.managerPersonaMap.set( senderId, { icon: "👑", initial: "T", color: "#3F51B5", name: "Tiberius" } );

  ui._addStripIcon( senderId, "LUPIN", { name: "Rio", color: "#28a745" }, "worker01" );

  const icon = document.getElementById( ui._stripIconIdFor( senderId ) ) as HTMLElement;
  assert.ok( icon, "strip icon created" );
  assert.equal( icon.getAttribute( "data-has-manager" ), "true" );
  const badge = icon.querySelector( ".cc-strip-manager-badge" ) as HTMLElement;
  assert.ok( badge, "manager badge child present" );
  assert.equal( badge.textContent, "👑T", "badge shows manager glyph + initial" );
  assert.equal( badge.getAttribute( "title" ), "Spawned by Tiberius" );
  assert.equal( badge.style.getPropertyValue( "--manager-color" ), "#3F51B5" );
} );

test( "no manager badge when the sender has no manager (root session)", () => {
  const ui = newUI();
  buildStripDOM();
  const senderId = "claude.code@lupin.deepily.ai#root01";
  // managerPersonaMap deliberately empty for this sender.

  ui._addStripIcon( senderId, "LUPIN", { name: "Rio", color: "#28a745" }, "root01" );

  const icon = document.getElementById( ui._stripIconIdFor( senderId ) ) as HTMLElement;
  assert.ok( icon, "strip icon still created" );
  assert.equal( icon.getAttribute( "data-has-manager" ), null, "no data-has-manager flag" );
  assert.equal( icon.querySelector( ".cc-strip-manager-badge" ), null, "no badge child" );
} );

test( "manager badge tolerates a missing initial / glyph (renders what it has)", () => {
  const ui = newUI();
  buildStripDOM();
  const senderId = "claude.code@lupin.deepily.ai#worker02";
  ui.managerPersonaMap.set( senderId, { icon: "👑", color: "#3F51B5" } );   // no initial, no name

  ui._addStripIcon( senderId, "LUPIN", { name: "Rio" }, "worker02" );

  const badge = document.getElementById( ui._stripIconIdFor( senderId ) )!
    .querySelector( ".cc-strip-manager-badge" ) as HTMLElement;
  assert.ok( badge, "badge present" );
  assert.equal( badge.textContent, "👑", "glyph only when no initial" );
  assert.equal( badge.getAttribute( "title" ), "Spawned by manager", "falls back to generic name" );
} );

if ( typeof process !== "undefined" && process.argv.includes( "--run" ) ) { /* node --test entry */ }
