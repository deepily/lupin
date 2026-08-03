/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Lane 1 WP2 (2026-07-02) — TTS minimized (pending) card template.
//
// Ports legacy renderMinimizedTTSCard (notifications.js:16894): a queued item
// waiting to be spoken. 1-indexed position · type badge (⚠️/🔔) · time cell ·
// text truncated to 50 · delete; `.priority` class on action-required. AC2e
// safe-write — .textContent only. Shared cell logic in ttsCardShared.ts.
//
// Pure template: the caller (WP4) passes `position`, derived from the
// TtsQueueStore.pending() array order, so the template reads no store state and
// the mux re-derives positions by re-rendering the pending list wholesale.

import type { TtsQueueItem } from "../../shared/types";
import { ttsCardIcon, truncateTtsText, ttsCardTime } from "./ttsCardShared";

/** Minimized-card gestures. `onDelete` removes this pending item by id_hash. */
export interface TtsMinimizedCardHandlers {
  onDelete( idHash: string ): void;
}

const MINIMIZED_TRUNCATE = 50;

/**
 * Build a minimized (pending) TTS card.
 *
 * Requires:
 *   - `item` is a pending TtsQueueItem (id_hash present)
 *   - `position` is the item's 1-indexed queue position
 *   - `handlers.onDelete` is a function
 * Ensures:
 *   - returns a single `.tts-minimized` root (data-testid
 *     `multiplexer-tts-minimized-card`, `data-item-id` = id_hash) with the
 *     `.priority` class iff action-required, and position / badge / time /
 *     text-50 / delete children in legacy order
 *   - delete click → onDelete(item.id_hash) (propagation stopped)
 *   - all dynamic text set via .textContent (AC2e safe-write)
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function renderTtsMinimizedCard(
  item     : TtsQueueItem,
  position : number,
  handlers : TtsMinimizedCardHandlers,
): HTMLElement {
  const card = document.createElement( "div" );
  card.className = item.notification?.action_required === true
    ? "tts-minimized priority"
    : "tts-minimized";
  card.setAttribute( "data-testid", "multiplexer-tts-minimized-card" );
  card.dataset.itemId = item.id_hash;

  const positionDiv = document.createElement( "div" );
  positionDiv.className   = "tts-position";
  positionDiv.textContent = String( position );

  const badgeDiv = document.createElement( "div" );
  badgeDiv.className   = "tts-type-badge";
  badgeDiv.textContent = ttsCardIcon( item );

  const timeSpan = document.createElement( "span" );
  timeSpan.className   = "message-time";
  timeSpan.textContent = ttsCardTime( item );

  const textDiv = document.createElement( "div" );
  textDiv.className   = "tts-text";
  textDiv.textContent = truncateTtsText( item.ttsText ?? "", MINIMIZED_TRUNCATE );

  const deleteBtn = document.createElement( "button" );
  deleteBtn.type        = "button";
  deleteBtn.className    = "tts-delete-button";
  deleteBtn.textContent = "×";   // × — legacy minimized-card delete glyph
  deleteBtn.title       = "Remove from queue";
  deleteBtn.addEventListener( "click", ( e ) => {
    e.stopPropagation();
    handlers.onDelete( item.id_hash );
  } );

  card.append( positionDiv, badgeDiv, timeSpan, textDiv, deleteBtn );
  return card;
}
