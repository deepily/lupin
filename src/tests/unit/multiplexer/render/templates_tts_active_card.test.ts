// Multiplexer Lane 1 WP2 — TTS active-slot card template tests.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import {
  renderTtsActiveCard,
  type TtsActiveCardHandlers,
} from "../../../../lupin_app/static/js/multiplexer/render/templates/ttsActiveCard";
import type { TtsQueueItem } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

function notif( over: { action_required?: boolean; time_display?: string } ): TtsQueueItem[ "notification" ] {
  return over as unknown as TtsQueueItem[ "notification" ];
}
function item( over: Partial<TtsQueueItem> = {} ): TtsQueueItem {
  return { id_hash: "h1", ttsText: "hello", notification: notif( { time_display: "09:30" } ), ...over };
}
interface Calls { stop: number; deleted: string[]; }
function handlers(): { h: TtsActiveCardHandlers; calls: Calls } {
  const calls: Calls = { stop: 0, deleted: [] };
  return {
    calls,
    h: { onStop() { calls.stop += 1; }, onDelete( id ) { calls.deleted.push( id ); } },
  };
}

test( "structure: root class + data-testid + children order", () => {
  const { h } = handlers();
  const card = renderTtsActiveCard( item(), h );
  assert.equal( card.className, "tts-active-card" );
  assert.equal( card.getAttribute( "data-testid" ), "multiplexer-tts-active-card" );
  const classes = Array.from( card.children ).map( c => c.className );
  assert.deepEqual( classes, [ "tts-type-icon", "message-time", "tts-message", "tts-stop-button", "tts-delete-button" ] );
} );

test( "icon: action-required → ⚠️", () => {
  const { h } = handlers();
  const card = renderTtsActiveCard( item( { notification: notif( { action_required: true } ) } ), h );
  assert.equal( card.querySelector( ".tts-type-icon" )!.textContent, "⚠️" );
} );
test( "icon: default (non-action-required) → 🔔", () => {
  const { h } = handlers();
  const card = renderTtsActiveCard( item( { notification: notif( { action_required: false } ) } ), h );
  assert.equal( card.querySelector( ".tts-type-icon" )!.textContent, "🔔" );
} );

test( "message: text over 80 truncated with ...", () => {
  const { h } = handlers();
  const card = renderTtsActiveCard( item( { ttsText: "y".repeat( 100 ) } ), h );
  const msg = card.querySelector( ".tts-message" )!.textContent!;
  assert.equal( msg.length, 80 );
  assert.ok( msg.endsWith( "..." ) );
} );
test( "message: text under 80 rendered whole", () => {
  const { h } = handlers();
  const card = renderTtsActiveCard( item( { ttsText: "brief" } ), h );
  assert.equal( card.querySelector( ".tts-message" )!.textContent, "brief" );
} );
test( "message: missing ttsText → empty string (no throw)", () => {
  const { h } = handlers();
  const card = renderTtsActiveCard( item( { ttsText: undefined } ), h );
  assert.equal( card.querySelector( ".tts-message" )!.textContent, "" );
} );

test( "time: time_display rendered in .message-time", () => {
  const { h } = handlers();
  const card = renderTtsActiveCard( item( { notification: notif( { time_display: "23:59" } ) } ), h );
  assert.equal( card.querySelector( ".message-time" )!.textContent, "23:59" );
} );

test( "Stop button → onStop() once", () => {
  const { h, calls } = handlers();
  const card = renderTtsActiveCard( item(), h );
  ( card.querySelector( ".tts-stop-button" ) as HTMLButtonElement ).click();
  assert.equal( calls.stop, 1 );
} );

test( "delete button → onDelete(id_hash) once and stops propagation", () => {
  const { h, calls } = handlers();
  const card = renderTtsActiveCard( item( { id_hash: "abc" } ), h );
  let parentClicks = 0;
  const parent = document.createElement( "div" );
  parent.addEventListener( "click", () => { parentClicks += 1; } );
  parent.appendChild( card );
  ( card.querySelector( ".tts-delete-button" ) as HTMLButtonElement ).click();
  assert.deepEqual( calls.deleted, [ "abc" ] );
  assert.equal( parentClicks, 0, "delete click must not bubble to the card/parent" );
} );

test( "AC2e safe-write: source has no innerHTML / rawHTML / outerHTML", () => {
  const src = readFileSync(
    fileURLToPath( new URL(
      "../../../../lupin_app/static/js/multiplexer/render/templates/ttsActiveCard.ts",
      import.meta.url,
    ) ),
    "utf8",
  );
  assert.doesNotMatch( src, /\.innerHTML\s*=|rawHTML\(|\.outerHTML\s*=/ );
} );
