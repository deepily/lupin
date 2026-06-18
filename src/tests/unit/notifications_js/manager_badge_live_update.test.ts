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
  // Plain-notification render-path short-circuit: a seeded dedup entry lets a
  // real plain-typed envelope flow through handleNotificationUpdate (so the new
  // top-level-manager_persona reconcile runs for real) and then return at the
  // duplicate guard, BEFORE the deep createSenderCard render path — keeping the
  // test focused on the reconcile under test.
  ui.notificationState = { notifications: [] };
  ui.commonsTrafficVisibilityEnabled = false;
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

// ── The FIX (Tiffany 2026-06-17): self-heal via the top-level manager_persona ──
// The server now stamps top-level `manager_persona` on EVERY CC-sender emit
// (notification_fifo_queue.py _stamp_manager_persona), and handleNotificationUpdate
// reconciles it BEFORE the switch — so any later live event re-carries the lineage
// and the badge appears with no page refresh. These reproduce Rick's symptom (badge
// missing after a raced spawn) and prove the self-heal.

test( "FIX: raced-null persona event leaves no badge, then a later plain notification with top-level manager_persona self-heals it live (no refresh)", async () => {
  const ui = makeUI();
  // 1) voice_persona_assigned races to a null manager at the worker's spawn instant.
  await ui.handleNotificationUpdate( {
    notification: {
      type: "voice_persona_assigned",
      sender_id: NEWBIE,
      voice_persona: PERSONA,
      payload: { session_id: "newbie01", manager_persona: null },
    },
  } );
  assert.equal(
    document.getElementById( ui._stripIconIdFor( NEWBIE ) )!.querySelector( ".cc-strip-manager-badge" ),
    null, "reproduces the bug: no badge after the raced-null persona event" );

  // 2) The worker's NEXT plain notification now carries top-level manager_persona
  //    (server self-heal stamp; bridge settled → resolver succeeds) → badge live-patches.
  ( ui.notificationState as { notifications: unknown[] } ).notifications.push( { id_hash: "dup1" } );
  await ui.handleNotificationUpdate( {
    notification: {
      id_hash: "dup1",            // dedup short-circuit AFTER the reconcile (see makeUI)
      type: "task",
      sender_id: NEWBIE,
      manager_persona: MGR,       // top-level — the new server stamp
      message: "worker progress ping",
    },
  } );
  const badge = document.getElementById( ui._stripIconIdFor( NEWBIE ) )!
    .querySelector( ".cc-strip-manager-badge" ) as HTMLElement;
  assert.ok( badge, "badge self-healed onto the existing icon via the plain notification — NO refresh" );
  assert.equal( badge.textContent, "M", "badge shows the manager's initial" );
  assert.ok( ( ui.managerPersonaMap as Map<string, unknown> ).has( NEWBIE ),
    "managerPersonaMap populated by the plain notification's top-level stamp" );
} );

test( "FIX: plain notification with top-level manager_persona populates the map ahead of the icon, so a later-created icon shows the badge", async () => {
  const ui = makeUI();
  ( ui.notificationState as { notifications: unknown[] } ).notifications.push( { id_hash: "dup2" } );
  // Plain notification arrives BEFORE any icon exists → reconcile sets the map;
  // _setManagerBadgeOnStripIcon no-ops (no icon yet).
  await ui.handleNotificationUpdate( {
    notification: { id_hash: "dup2", type: "task", sender_id: NEWBIE, manager_persona: MGR, message: "hi" },
  } );
  assert.equal( document.getElementById( ui._stripIconIdFor( NEWBIE ) ), null, "no icon yet" );
  assert.ok( ( ui.managerPersonaMap as Map<string, unknown> ).has( NEWBIE ), "map populated ahead of the icon" );

  // Icon created later (e.g. by the persona event) reads the map → badge applied at creation.
  ui._addStripIcon( NEWBIE, "LUPIN", PERSONA, "newbie01" );
  const badge = document.getElementById( ui._stripIconIdFor( NEWBIE ) )!
    .querySelector( ".cc-strip-manager-badge" ) as HTMLElement;
  assert.ok( badge, "badge applied at icon creation, sourced from the pre-populated map" );
  assert.equal( badge.textContent, "M" );
} );
