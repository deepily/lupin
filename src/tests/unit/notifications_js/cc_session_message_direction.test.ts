// Phase 3 §4 — sendCCSessionMessage direction tag (frontend voice/text-in → human_to_ai).
//
// The CC-session send path POSTs /api/notify with type=user_initiated_message; this
// test pins that it now also carries direction=human_to_ai (the provenance axis,
// orthogonal to `type`), completing the direction model on the frontend send path.
//
// Mirrors the established notifications.js harness (fleet_status_panel.test.ts):
// load the class via vm.runInThisContext (sliced before the DOM-ready init),
// Object.create the prototype to skip the constructor, hand-set the few fields the
// method reads, stub fetch, then drive the method directly under happy-dom.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/cc_session_message_direction.test.ts
// Coverage (c8):
//   npx c8 --include='src/lupin_app/static/js/notifications.js' --reporter=text \
//       npx tsx --test src/tests/unit/notifications_js/cc_session_message_direction.test.ts

import { test, before } from "node:test";
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
  vm.runInThisContext(
    fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;",
    { filename: NOTIFICATIONS_JS }
  );
} );

type CCUI = Record<string, unknown> & {
  sendCCSessionMessage: ( sessionHash: string ) => Promise<void>;
};

function newUI(): CCUI {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui = Object.create( Ctor.prototype ) as Record<string, unknown>;
  ui.debug                       = false;
  ui.log                         = (): void => {};
  ui.error                       = (): void => {};
  ui.currentUserEmail            = "rick@example.com";
  ui.getAuthHeader               = (): string => "Bearer test-token";
  ui.ensureValidToken            = async (): Promise<void> => {};
  ui.getLocalTimeDisplay         = (): string => "12:00 PM";
  ui.addNotificationToSenderGroup = (): void => {};
  return ui as CCUI;
}

function buildDOM( hash: string, senderId: string, message: string ): HTMLInputElement {
  document.body.replaceChildren();
  const input = document.createElement( "input" );
  input.id    = `cc-session-input-${hash}`;
  input.value = message;
  const sendBtn = document.createElement( "button" );
  sendBtn.id    = `cc-session-send-${hash}`;
  const voice = document.createElement( "div" );
  voice.className = "cc-voice-input";
  voice.setAttribute( "data-session-hash", hash );
  voice.setAttribute( "data-sender-id", senderId );
  document.body.append( input, sendBtn, voice );
  return input;
}

async function withFetch( capture: { url: string }, fn: () => Promise<void> ): Promise<void> {
  const orig = globalThis.fetch;
  globalThis.fetch = ( async ( url: string ): Promise<unknown> => {
    capture.url = String( url );
    return { ok: true, status: 200, json: async (): Promise<unknown> => ( {} ) };
  } ) as unknown as typeof fetch;
  try {
    await fn();
  } finally {
    globalThis.fetch = orig;
  }
}

test( "sendCCSessionMessage tags the /api/notify push with direction=human_to_ai", async () => {
  const hash = "abc12345";
  buildDOM( hash, "listener@example.com#abc12345", "fix the failing tests" );

  const capture = { url: "" };
  await withFetch( capture, async () => {
    await newUI().sendCCSessionMessage( hash );
  } );

  assert.ok( capture.url.includes( "/api/notify?" ), `expected an /api/notify POST, got: ${capture.url}` );
  assert.ok( capture.url.includes( "direction=human_to_ai" ), `expected direction=human_to_ai in: ${capture.url}` );
  // The direction axis is orthogonal to type — both must ride the push.
  assert.ok( capture.url.includes( "type=user_initiated_message" ), `expected type=user_initiated_message in: ${capture.url}` );
} );

test( "sendCCSessionMessage with empty input does not POST (no direction tag, early return)", async () => {
  const hash  = "def67890";
  const input = buildDOM( hash, "listener@example.com#def67890", "   " );  // whitespace → trimmed empty

  const capture = { url: "" };
  await withFetch( capture, async () => {
    await newUI().sendCCSessionMessage( hash );
  } );

  assert.equal( capture.url, "", "no fetch should fire on empty input" );
  assert.equal( input.disabled, false, "controls stay enabled on the empty-input early return" );
} );
