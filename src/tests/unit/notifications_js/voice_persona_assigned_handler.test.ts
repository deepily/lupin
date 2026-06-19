// Legacy notifications.js — `voice_persona_assigned` spin-up symmetry unit test (2026-06-06).
//
// Companion to session_reaped_handler.test.ts. Where `session_reaped` REMOVES a
// worker's focus-bar badge + refreshes the broadcast card, `voice_persona_assigned`
// must do the SYMMETRIC spin-up: a freshly-spawned worker (no sender card yet) gets
// its focus-bar badge added immediately + the broadcast recipient list refreshed —
// so it appears WITHOUT a page reload or a manual broadcast-refresh click (Rick's
// 2026-06-06 directive).
//
// Same constructor-bypass harness as the reap test: read the source, slice OFF the
// trailing `new NotificationsUI()` boot block, load the class definition under
// happy-dom, build an instance via Object.create(), stub only the fields/DOM the
// `voice_persona_assigned` case touches, and drive the REAL handleNotificationUpdate.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/voice_persona_assigned_handler.test.ts
// See: src/rnd/v0.1.8/2026.06.05-reap-event-focus-bar-and-broadcast-refresh.md (§ Spin-up symmetry)

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
  assert.ok( classOnly.includes( "class NotificationsUI" ), "sliced source must still contain the class" );
  vm.runInThisContext( classOnly + "\n;globalThis.NotificationsUI = NotificationsUI;" );
  assert.equal( typeof ( globalThis as Record<string, unknown> ).NotificationsUI, "function", "NotificationsUI loaded" );
} );

const NEWBIE   = "claude.code@lupin.deepily.ai#newbie01";
const EXISTING = "claude.code@lupin.deepily.ai#existing1";
const PERSONA  = { name: "Rachel", display_name: "Rachel", color: "#CE93D8", assigned_at: "2026-06-06T17:45:33+00:00" };

// Build a constructor-bypassed instance with only what the voice_persona_assigned
// case (and the real _addStripIcon it calls) reads, plus a minimal strip DOM.
function makeUI( opts: { broadcastPanel?: boolean; seedExisting?: boolean } = {} ): {
  ui: Record<string, unknown> & {
    handleNotificationUpdate: ( e: unknown ) => Promise<void>;
    _stripIconIdFor: ( s: string ) => string;
  };
  refreshCalls: number[];
} {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui = Object.create( Ctor.prototype ) as Record<string, unknown> & {
    handleNotificationUpdate: ( e: unknown ) => Promise<void>;
    _stripIconIdFor: ( s: string ) => string;
  };

  ui.debug                       = false;
  ui.log                         = (): void => {};                 // silence Design-by-Contract logging
  ui.senderPersonaMap            = new Map();
  // managerPersonaMap: the voice_persona / session_reaped handlers now also touch
  // the manager-badge map (manager-badge work) — stub it so the production handler's
  // .delete() doesn't throw on this Object.create()-bypassed instance.
  ui.managerPersonaMap           = new Map();
  ui.ccFocusState                = { enabled: false, focused_sender_id: null };
  ui.ccHideInactiveStrip         = false;
  ui.conversationModes           = {};
  // Stub the two card-side helpers the case calls — there is no sender card in this
  // harness, so both are no-ops (they're exercised by their own card-render tests).
  ui._setPersonaBadgeOnCard      = (): void => {};
  ui._applyHideInactiveStripFilter = (): void => {};

  // Minimal focus-bar DOM: empty strip (the spin-up adds the first icon).
  document.body.replaceChildren();
  const strip = document.createElement( "div" );
  strip.id = "cc-session-strip";
  strip.setAttribute( "hidden", "" );
  const icons = document.createElement( "div" );
  icons.id = "cc-strip-icons";
  if ( opts.seedExisting ) {
    const icon = document.createElement( "span" );
    icon.className = "cc-strip-icon";
    icon.id = ui._stripIconIdFor( EXISTING );
    icon.setAttribute( "data-sender-id", EXISTING );
    icons.appendChild( icon );
    strip.removeAttribute( "hidden" );
  }
  strip.appendChild( icons );
  document.body.appendChild( strip );

  const refreshCalls: number[] = [];
  if ( opts.broadcastPanel !== false ) {
    ( window as unknown as Record<string, unknown> ).broadcastPanel = {
      refreshSessions: (): void => { refreshCalls.push( 1 ); },
    };
  } else {
    delete ( window as unknown as Record<string, unknown> ).broadcastPanel;
  }

  return { ui, refreshCalls };
}

beforeEach( () => {
  document.body.replaceChildren();
} );

test( "voice_persona_assigned adds the new worker's strip badge + refreshes the broadcast card", async () => {
  const { ui, refreshCalls } = makeUI();

  await ui.handleNotificationUpdate(
    { notification: { type: "voice_persona_assigned", sender_id: NEWBIE, voice_persona: PERSONA } }
  );

  const newIcon = document.getElementById( ui._stripIconIdFor( NEWBIE ) );
  assert.ok( newIcon, "freshly-spawned worker's strip badge appears without a reload" );
  assert.equal( newIcon?.getAttribute( "data-sender-id" ), NEWBIE, "badge carries the worker's sender_id" );
  assert.equal( newIcon?.textContent, "R", "badge initial derives from the persona display name" );
  assert.equal( refreshCalls.length, 1, "broadcast card recipient list refreshed exactly once" );
  assert.ok( ( ui.senderPersonaMap as Map<string, unknown> ).has( NEWBIE ), "persona map updated" );
} );

test( "voice_persona_assigned is idempotent — re-assigning the same sender does not duplicate the badge", async () => {
  const { ui, refreshCalls } = makeUI( { seedExisting: true } );

  await ui.handleNotificationUpdate(
    { notification: { type: "voice_persona_assigned", sender_id: EXISTING, voice_persona: PERSONA } }
  );

  const icons = document.querySelectorAll( `#cc-strip-icons [data-sender-id="${EXISTING}"]` );
  assert.equal( icons.length, 1, "no duplicate strip icon for an already-present sender" );
  assert.equal( refreshCalls.length, 1, "broadcast still refreshed (freshness on every assign)" );
} );

test( "voice_persona_assigned is a clean no-op when window.broadcastPanel is absent", async () => {
  const { ui } = makeUI( { broadcastPanel: false } );

  // Must not throw when broadcastPanel hasn't loaded yet.
  await ui.handleNotificationUpdate(
    { notification: { type: "voice_persona_assigned", sender_id: NEWBIE, voice_persona: PERSONA } }
  );

  const newIcon = document.getElementById( ui._stripIconIdFor( NEWBIE ) );
  assert.ok( newIcon, "badge still added without a broadcast panel present" );
} );

test( "voice_persona_assigned with no voice_persona is skipped (guard) — no badge, no refresh", async () => {
  const { ui, refreshCalls } = makeUI();

  await ui.handleNotificationUpdate(
    { notification: { type: "voice_persona_assigned", sender_id: NEWBIE } }
  );

  const newIcon = document.getElementById( ui._stripIconIdFor( NEWBIE ) );
  assert.equal( newIcon, null, "no badge added when the persona is missing" );
  assert.equal( refreshCalls.length, 0, "no broadcast refresh when the guard skips" );
} );
