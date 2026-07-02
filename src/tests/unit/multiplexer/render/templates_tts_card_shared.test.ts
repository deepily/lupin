// Multiplexer Lane 1 WP2 — shared TTS-card cell helper tests.
// Pure functions (no DOM) — covers every branch of ttsCardShared.ts.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  ttsCardIcon,
  truncateTtsText,
  ttsCardTime,
} from "../../../../lupin_app/static/js/multiplexer/render/templates/ttsCardShared";
import type { TtsQueueItem } from "../../../../lupin_app/static/js/multiplexer/shared/types";

// Minimal notification fixture — only action_required / time_display are read.
function notif( over: { action_required?: boolean; time_display?: string } ): TtsQueueItem[ "notification" ] {
  return over as unknown as TtsQueueItem[ "notification" ];
}
function item( over: Partial<TtsQueueItem> = {} ): TtsQueueItem {
  return { id_hash: "h1", ...over };
}

// ---- ttsCardIcon ----------------------------------------------------------
test( "ttsCardIcon: action-required notification → ⚠️", () => {
  assert.equal( ttsCardIcon( item( { notification: notif( { action_required: true } ) } ) ), "⚠️" );
} );
test( "ttsCardIcon: non-action-required notification → 🔔", () => {
  assert.equal( ttsCardIcon( item( { notification: notif( { action_required: false } ) } ) ), "🔔" );
} );
test( "ttsCardIcon: missing notification → 🔔", () => {
  assert.equal( ttsCardIcon( item() ), "🔔" );
} );

// ---- truncateTtsText ------------------------------------------------------
test( "truncateTtsText: over max → truncated to exactly max with trailing ...", () => {
  const out = truncateTtsText( "x".repeat( 100 ), 80 );
  assert.equal( out.length, 80 );
  assert.equal( out, "x".repeat( 77 ) + "..." );
} );
test( "truncateTtsText: at/under max → returned unchanged", () => {
  assert.equal( truncateTtsText( "short", 80 ), "short" );
  assert.equal( truncateTtsText( "x".repeat( 80 ), 80 ), "x".repeat( 80 ) );
} );

// ---- ttsCardTime ----------------------------------------------------------
test( "ttsCardTime: non-empty time_display → used verbatim", () => {
  assert.equal(
    ttsCardTime( item( { notification: notif( { time_display: "09:30 EDT" } ) } ) ),
    "09:30 EDT",
  );
} );
test( "ttsCardTime: notification present but no time_display → addedAt HH:MM", () => {
  const out = ttsCardTime( item( { notification: notif( {} ), addedAt: 0 } ) );
  assert.match( out, /^\d{2}:\d{2}$/ );
} );
test( "ttsCardTime: no notification and no addedAt → epoch-0 HH:MM (no throw)", () => {
  const out = ttsCardTime( item() );
  assert.match( out, /^\d{2}:\d{2}$/ );
} );
test( "ttsCardTime: empty-string time_display is falsy → falls back to addedAt", () => {
  const out = ttsCardTime( item( { notification: notif( { time_display: "" } ), addedAt: 0 } ) );
  assert.match( out, /^\d{2}:\d{2}$/ );
} );
