// Legacy notifications.js — `session_reaped` handler unit test (2026-06-05).
//
// Rick's TARGET UI is the legacy `notifications.html` page (`notifications.js`):
// the focus bar (`#cc-session-strip`) + the broadcast card both live ONLY here.
// This is the real deliverable for the reap → focus-bar/broadcast feature.
//
// The file is ~18.5k lines and at load runs `new NotificationsUI()` with a heavy
// constructor (audio elements, WebSocket, token timers) — so it can't be imported
// whole into node. Instead we:
//   1. read the source, slice OFF the trailing `// INITIALIZATION` block (the
//      `new NotificationsUI()` call), and expose the class on globalThis,
//   2. run it in a happy-dom context so the class definition loads,
//   3. build an instance via Object.create() to BYPASS the constructor,
//   4. stub only the handful of fields/DOM the `session_reaped` case touches,
//   5. drive the REAL `handleNotificationUpdate` and assert the strip badge is
//      removed + the broadcast card is refreshed.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/session_reaped_handler.test.ts
// See: src/rnd/v0.1.8/2026.06.05-reap-event-focus-bar-and-broadcast-refresh.md

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
  // Load ONLY the class definition (drop the trailing `new NotificationsUI()`
  // init block that would fire the heavy constructor), then expose the class.
  const fullSource  = readFileSync( NOTIFICATIONS_JS, "utf8" );
  // Slice at the UNIQUE bottom-of-file init marker ("// INITIALIZATION" also
  // appears as a section comment at ~line 386 inside the class, so it can't be
  // used). Everything before this is the full class definition; everything
  // after is the `new NotificationsUI()` boot we must NOT run.
  const initIdx     = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  const classOnly   = fullSource.slice( 0, initIdx );
  assert.ok( classOnly.includes( "class NotificationsUI" ), "sliced source must still contain the class" );
  vm.runInThisContext( classOnly + "\n;globalThis.NotificationsUI = NotificationsUI;" );
  assert.equal( typeof ( globalThis as Record<string, unknown> ).NotificationsUI, "function", "NotificationsUI loaded" );
} );

const WORKER = "claude.code@lupin.deepily.ai#worker";
const SURVIVOR = "claude.code@lupin.deepily.ai#survivor";

// Build a constructor-bypassed instance with only what the session_reaped
// case reads, plus a minimal strip DOM.
function makeUI( opts: { broadcastPanel?: boolean } = {} ): {
  ui: Record<string, unknown> & { handleNotificationUpdate: ( e: unknown ) => Promise<void> };
  refreshCalls: number[];
} {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui = Object.create( Ctor.prototype ) as Record<string, unknown> & {
    handleNotificationUpdate: ( e: unknown ) => Promise<void>;
    _stripIconIdFor: ( s: string ) => string;
  };

  ui.debug                = false;
  ui.log                  = (): void => {};                 // silence Design-by-Contract logging
  ui.senderPersonaMap     = new Map( [ [ WORKER, { name: "Worker" } ], [ SURVIVOR, { name: "Survivor" } ] ] );
  // managerPersonaMap: the session_reaped / voice_persona handlers now also clear
  // the manager-badge map (manager-badge work) — stub it so the .delete() call in
  // the production handler doesn't throw on this Object.create()-bypassed instance.
  ui.managerPersonaMap    = new Map();
  ui.ccFocusState         = { enabled: false, focused_sender_id: null };
  ui.ccStripUnreadCounts  = {};
  ui.ccHideInactiveStrip  = false;

  // Minimal focus-bar DOM: a strip with one icon per sender.
  document.body.replaceChildren();
  const strip = document.createElement( "div" );
  strip.id = "cc-session-strip";
  const icons = document.createElement( "div" );
  icons.id = "cc-strip-icons";
  for ( const sid of [ WORKER, SURVIVOR ] ) {
    const icon = document.createElement( "span" );
    icon.className = "cc-strip-icon";
    icon.id = ui._stripIconIdFor( sid );
    icon.setAttribute( "data-sender-id", sid );
    icons.appendChild( icon );
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

test( "session_reaped removes the reaped worker's strip badge + refreshes the broadcast card", async () => {
  const { ui, refreshCalls } = makeUI();

  await ui.handleNotificationUpdate( { notification: { type: "session_reaped", sender_id: WORKER } } );

  const reapedIcon   = document.getElementById( ( ui as { _stripIconIdFor: ( s: string ) => string } )._stripIconIdFor( WORKER ) );
  const survivorIcon = document.getElementById( ( ui as { _stripIconIdFor: ( s: string ) => string } )._stripIconIdFor( SURVIVOR ) );

  assert.equal( reapedIcon, null, "reaped worker's strip badge removed from the focus bar" );
  assert.ok( survivorIcon, "other sender's badge survives (scoped removal)" );
  assert.equal( refreshCalls.length, 1, "broadcast card recipient list refreshed exactly once" );
} );

test( "session_reaped still refreshes the broadcast card even with no sender_id", async () => {
  const { ui, refreshCalls } = makeUI();

  await ui.handleNotificationUpdate( { notification: { type: "session_reaped" } } );

  assert.equal( refreshCalls.length, 1, "broadcast refresh fires independent of sender_id" );
} );

test( "session_reaped is a clean no-op when window.broadcastPanel is absent", async () => {
  const { ui } = makeUI( { broadcastPanel: false } );

  // Must not throw when broadcastPanel hasn't loaded yet.
  await ui.handleNotificationUpdate( { notification: { type: "session_reaped", sender_id: WORKER } } );

  const reapedIcon = document.getElementById( ( ui as { _stripIconIdFor: ( s: string ) => string } )._stripIconIdFor( WORKER ) );
  assert.equal( reapedIcon, null, "badge still removed without a broadcast panel present" );
} );
