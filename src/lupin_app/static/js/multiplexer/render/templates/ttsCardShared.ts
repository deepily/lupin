/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Lane 1 WP2 (2026-07-02) — shared TTS-card cell helpers.
//
// Single-source cell logic shared by ttsActiveCard.ts + ttsMinimizedCard.ts,
// ported from legacy renderActiveTTSCard/renderMinimizedTTSCard
// (notifications.js:16833/16894): the action-required icon, text truncation,
// and the time cell. Factored into one module so the two card templates never
// diverge on these rules (single-source; a divergence here would break parity
// on only one card and be easy to miss).

import type { TtsQueueItem } from "../../shared/types";

/**
 * Legacy parity icon: ⚠️ for an action-required prompt, 🔔 otherwise. A missing
 * notification is treated as non-action-required (🔔) — the mux TtsQueueItem
 * carries the discriminator on `notification.action_required`, not a `type`.
 */
export function ttsCardIcon( item: TtsQueueItem ): string {
  return item.notification?.action_required === true ? "⚠️" : "🔔";
}

/**
 * Truncate `text` to at most `max` characters, appending "..." when it overran
 * (legacy `substring( 0, max - 3 ) + "..."`). Text at or under `max` is returned
 * unchanged.
 */
export function truncateTtsText( text: string, max: number ): string {
  return text.length > max ? text.substring( 0, max - 3 ) + "..." : text;
}

/**
 * The card's time cell: the backend `time_display` override when present + non
 * empty, else the enqueue time (`addedAt`) formatted HH:MM (24-hour). Mirrors
 * the legacy cards' time logic.
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function ttsCardTime( item: TtsQueueItem ): string {
  const disp = item.notification?.time_display;
  if ( disp ) return disp;
  const ts = new Date( item.addedAt ?? 0 );
  return ts.toLocaleTimeString( "en-US", { hour: "2-digit", minute: "2-digit", hour12: false } );
}
