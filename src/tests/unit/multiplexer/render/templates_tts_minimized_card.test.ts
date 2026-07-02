// Multiplexer Lane 1 WP2 — TTS minimized (pending) card template tests.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import {
  renderTtsMinimizedCard,
  type TtsMinimizedCardHandlers,
} from "../../../../lupin_app/static/js/multiplexer/render/templates/ttsMinimizedCard";
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
function handlers(): { h: TtsMinimizedCardHandlers; deleted: string[] } {
  const deleted: string[] = [];
  return { deleted, h: { onDelete( id ) { deleted.push( id ); } } };
}

test( "structure: root class + data-testid + data-item-id + children order", () => {
  const { h } = handlers();
  const card = renderTtsMinimizedCard( item( { id_hash: "zz" } ), 3, h );
  assert.equal( card.className, "tts-minimized" );
  assert.equal( card.getAttribute( "data-testid" ), "multiplexer-tts-minimized-card" );
  assert.equal( card.dataset.itemId, "zz" );
  const classes = Array.from( card.children ).map( c => c.className );
  assert.deepEqual( classes, [ "tts-position", "tts-type-badge", "message-time", "tts-text", "tts-delete-button" ] );
} );

test( "position: 1-indexed value rendered as text", () => {
  const { h } = handlers();
  const card = renderTtsMinimizedCard( item(), 7, h );
  assert.equal( card.querySelector( ".tts-position" )!.textContent, "7" );
} );

test( "priority class: action-required → .tts-minimized.priority", () => {
  const { h } = handlers();
  const card = renderTtsMinimizedCard( item( { notification: notif( { action_required: true } ) } ), 1, h );
  assert.equal( card.className, "tts-minimized priority" );
  assert.equal( card.querySelector( ".tts-type-badge" )!.textContent, "⚠️" );
} );
test( "priority class: non-action-required notification → no priority", () => {
  const { h } = handlers();
  const card = renderTtsMinimizedCard( item( { notification: notif( { action_required: false } ) } ), 1, h );
  assert.equal( card.className, "tts-minimized" );
  assert.equal( card.querySelector( ".tts-type-badge" )!.textContent, "🔔" );
} );
test( "priority class: missing notification → no priority, 🔔 badge", () => {
  const { h } = handlers();
  const card = renderTtsMinimizedCard( item( { notification: undefined } ), 1, h );
  assert.equal( card.className, "tts-minimized" );
  assert.equal( card.querySelector( ".tts-type-badge" )!.textContent, "🔔" );
} );

test( "text: over 50 truncated with ...", () => {
  const { h } = handlers();
  const card = renderTtsMinimizedCard( item( { ttsText: "z".repeat( 90 ) } ), 1, h );
  const txt = card.querySelector( ".tts-text" )!.textContent!;
  assert.equal( txt.length, 50 );
  assert.ok( txt.endsWith( "..." ) );
} );
test( "text: under 50 rendered whole", () => {
  const { h } = handlers();
  const card = renderTtsMinimizedCard( item( { ttsText: "tiny" } ), 1, h );
  assert.equal( card.querySelector( ".tts-text" )!.textContent, "tiny" );
} );
test( "text: missing ttsText → empty string (no throw)", () => {
  const { h } = handlers();
  const card = renderTtsMinimizedCard( item( { ttsText: undefined } ), 1, h );
  assert.equal( card.querySelector( ".tts-text" )!.textContent, "" );
} );

test( "delete button: glyph × and onDelete(id_hash) once, propagation stopped", () => {
  const { h, deleted } = handlers();
  const card = renderTtsMinimizedCard( item( { id_hash: "mid" } ), 2, h );
  const del = card.querySelector( ".tts-delete-button" ) as HTMLButtonElement;
  assert.equal( del.textContent, "×" );
  let parentClicks = 0;
  const parent = document.createElement( "div" );
  parent.addEventListener( "click", () => { parentClicks += 1; } );
  parent.appendChild( card );
  del.click();
  assert.deepEqual( deleted, [ "mid" ] );
  assert.equal( parentClicks, 0 );
} );

test( "AC2e safe-write: source has no innerHTML / rawHTML / outerHTML", () => {
  const src = readFileSync(
    fileURLToPath( new URL(
      "../../../../lupin_app/static/js/multiplexer/render/templates/ttsMinimizedCard.ts",
      import.meta.url,
    ) ),
    "utf8",
  );
  assert.doesNotMatch( src, /\.innerHTML\s*=|rawHTML\(|\.outerHTML\s*=/ );
} );
