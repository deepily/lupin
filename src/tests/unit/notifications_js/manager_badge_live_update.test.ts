// Manager-ownership badge on the LIVE-update path (Arnold 2026-06-17).
//
// Coverage gap filled: voice_persona_assigned_handler.test.ts asserts the new
// worker's persona ICON appears live, and manager_badge_strip.test.ts unit-tests
// the badge BUILDERS in isolation — but NOTHING exercised the manager-BADGE branch
// of the real handleNotificationUpdate("voice_persona_assigned") path end-to-end.
//
// These tests drive the REAL handler with an event carrying payload.manager_persona
// (exactly what voice_persona.py:462-463 emits) and assert the corner badge lands on
// the freshly-spawned worker's strip icon WITHOUT a page refresh — both orderings:
//   (a) the persona event creates the icon (badge applied at creation), and
//   (b) a prior event created the icon first, then the persona event live-patches it.
//
// This LOCKS IN the client behavior so any future regression in the live-update
// badge path fails here. NOTE (root cause, see the findings doc): with these passing,
// the live-badge MISS Rick reports is NOT a client-render gap — it is a spawn-time
// timing/delivery race where payload.manager_persona is null at emit (or the event
// never reaches the dashboard while a plain notification paints the icon first).
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/manager_badge_live_update.test.ts

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
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext( fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;" );
} );

const NEWBIE  = "claude.code@lupin.deepily.ai#newbie01";
const PERSONA = { name: "Rachel", display_name: "Rachel", color: "#CE93D8" };
// Shape exactly as _resolve_manager_persona() returns it (voice_persona.py:96-101).
const MGR     = { icon: "🦉", initial: "M", color: "#FFA000", name: "mr radio" };

type LiveUI = Record<string, unknown> & {
  handleNotificationUpdate: ( e: unknown ) => Promise<void>;
  _stripIconIdFor: ( s: string ) => string;
  _addStripIcon: ( a: string, b: string, c: unknown, d: string ) => void;
};

function makeUI(): LiveUI {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui = Object.create( Ctor.prototype ) as LiveUI;
  ui.debug = false;
  ui.log = (): void => {};
  ui.senderPersonaMap = new Map();
  ui.managerPersonaMap = new Map();
  ui.ccFocusState = { enabled: false, focused_sender_id: null };
  ui.ccHideInactiveStrip = false;
  ui.conversationModes = {};
  ui._setPersonaBadgeOnCard = (): void => {};
  ui._applyHideInactiveStripFilter = (): void => {};
  document.body.replaceChildren();
  const strip = document.createElement( "div" );
  strip.id = "cc-session-strip"; strip.setAttribute( "hidden", "" );
  const icons = document.createElement( "div" ); icons.id = "cc-strip-icons";
  strip.appendChild( icons ); document.body.appendChild( strip );
  ( window as unknown as Record<string, unknown> ).broadcastPanel = { refreshSessions: (): void => {} };
  return ui;
}

beforeEach( () => { document.body.replaceChildren(); } );

test( "live voice_persona_assigned WITH manager_persona renders the badge on a new worker (no refresh)", async () => {
  const ui = makeUI();
  await ui.handleNotificationUpdate( {
    notification: {
      type: "voice_persona_assigned",
      sender_id: NEWBIE,
      voice_persona: PERSONA,
      payload: { session_id: "newbie01", manager_persona: MGR },
    },
  } );
  const icon = document.getElementById( ui._stripIconIdFor( NEWBIE ) ) as HTMLElement;
  assert.ok( icon, "strip icon created" );
  assert.equal( icon.getAttribute( "data-has-manager" ), "true", "manager flag set" );
  const badge = icon.querySelector( ".cc-strip-manager-badge" ) as HTMLElement;
  assert.ok( badge, "manager badge present on the live-added worker icon" );
  assert.equal( badge.textContent, "M", "badge shows the manager's initial" );
  assert.equal( badge.getAttribute( "title" ), "Spawned by mr radio" );
  assert.ok( ( ui.managerPersonaMap as Map<string, unknown> ).has( NEWBIE ), "managerPersonaMap populated live" );
} );

test( "icon created by a prior event first, THEN live persona event patches the badge", async () => {
  const ui = makeUI();
  // Simulate a plain notification creating the icon BEFORE the persona event
  // (managerPersonaMap empty → no badge at first paint).
  ui._addStripIcon( NEWBIE, "LUPIN", PERSONA, "newbie01" );
  assert.equal(
    document.getElementById( ui._stripIconIdFor( NEWBIE ) )!.querySelector( ".cc-strip-manager-badge" ),
    null, "no badge before the persona event"
  );
  await ui.handleNotificationUpdate( {
    notification: {
      type: "voice_persona_assigned",
      sender_id: NEWBIE,
      voice_persona: PERSONA,
      payload: { session_id: "newbie01", manager_persona: MGR },
    },
  } );
  const badge = document.getElementById( ui._stripIconIdFor( NEWBIE ) )!
    .querySelector( ".cc-strip-manager-badge" ) as HTMLElement;
  assert.ok( badge, "manager badge live-patched onto the pre-existing icon (no refresh)" );
  assert.equal( badge.textContent, "M" );
} );

test( "live event with manager_persona=null leaves the worker badge-less (root / unresolved-at-emit)", async () => {
  const ui = makeUI();
  await ui.handleNotificationUpdate( {
    notification: {
      type: "voice_persona_assigned",
      sender_id: NEWBIE,
      voice_persona: PERSONA,
      payload: { session_id: "newbie01", manager_persona: null },
    },
  } );
  const icon = document.getElementById( ui._stripIconIdFor( NEWBIE ) ) as HTMLElement;
  assert.ok( icon, "icon still painted" );
  assert.equal( icon.querySelector( ".cc-strip-manager-badge" ), null,
    "no badge when the server could not resolve the manager at emit time — this is the race surface" );
} );
