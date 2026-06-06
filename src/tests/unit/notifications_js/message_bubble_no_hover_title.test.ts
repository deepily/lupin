// Legacy notifications.js — notification bubble has NO duplicative hover title (2026-06-06).
//
// Rick's tweak (2026-06-06): the `.message-text` notification bubbles in the Claude
// Code session cards carried a `title="<full message>"` attribute. On hover the
// browser re-rendered the whole message as a native tooltip — duplicating the text
// already visible right beneath it. Distracting + annoying. The fix removes the
// `title` attribute from every `.message-text` bubble render path.
//
// This test drives the REAL `addMessageToSenderCard` (the simplest of the bubble
// render paths) via the same constructor-bypass harness as the reap/spin-up tests
// and asserts the rendered bubble carries no `title` attribute — a regression guard
// against re-introducing the hover.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/message_bubble_no_hover_title.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../fastapi_app/static/js/notifications.js" );

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

const SENDER = "claude.code@lupin.deepily.ai#sender01";

function makeUI(): Record<string, unknown> & {
  addMessageToSenderCard: ( senderId: string, notification: unknown, isResponse?: boolean ) => void;
} {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui = Object.create( Ctor.prototype ) as Record<string, unknown> & {
    addMessageToSenderCard: ( senderId: string, notification: unknown, isResponse?: boolean ) => void;
  };
  ui.debug = false;
  ui.log   = (): void => {};

  // The message container the function appends into.
  document.body.replaceChildren();
  const container = document.createElement( "div" );
  container.id = `sender-messages-${SENDER.replace( /[@.#]/g, "-" )}`;
  document.body.appendChild( container );
  return ui;
}

beforeEach( () => {
  document.body.replaceChildren();
} );

test( "addMessageToSenderCard renders a .message-text bubble with NO title hover", () => {
  const ui = makeUI();

  ui.addMessageToSenderCard( SENDER, { message: "Build completed successfully", time_display: "14:05 EST" } );

  const bubble = document.querySelector( ".message-text" );
  assert.ok( bubble, "message bubble rendered" );
  assert.equal( bubble?.hasAttribute( "title" ), false, "no duplicative title-hover on the bubble" );
  assert.match( bubble?.textContent ?? "", /Build completed successfully/, "visible message text is intact" );
} );

test( "no hover title even when the message contains quotes (would have escaped into title before)", () => {
  const ui = makeUI();

  ui.addMessageToSenderCard( SENDER, { message: 'He said "ship it"', time_display: "14:06 EST" }, true );

  const bubble = document.querySelector( ".message-text" );
  assert.ok( bubble, "message bubble rendered" );
  assert.equal( bubble?.hasAttribute( "title" ), false, "still no title attribute regardless of content" );
} );
