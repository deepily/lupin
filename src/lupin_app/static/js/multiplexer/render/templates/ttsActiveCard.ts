/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Lane 1 WP2 (2026-07-02) — TTS active-slot card template.
//
// Ports legacy renderActiveTTSCard (notifications.js:16833): the card for the
// notification whose TTS is currently being SPOKEN (TtsQueueStore.current()).
// icon (⚠️/🔔) · time cell · text truncated to 80 · Stop · delete. AC2e
// safe-write — all dynamic text via .textContent (never .innerHTML / rawHTML /
// .outerHTML), per ttsChrome.ts:1-7. Shared cell logic in ttsCardShared.ts.
//
// Pure template: takes the item + gesture handlers, returns a detached root.
// The renderer (WP4) owns mounting + which item is active.

import type { TtsQueueItem } from "../../shared/types";
import { ttsCardIcon, truncateTtsText, ttsCardTime } from "./ttsCardShared";

/** Active-card gestures. `onStop` halts the currently-spoken item; `onDelete`
 *  removes this item from the queue by its id_hash. */
export interface TtsActiveCardHandlers {
  onStop(): void;
  onDelete( idHash: string ): void;
}

const ACTIVE_TRUNCATE = 80;

/**
 * Build the active-slot TTS card.
 *
 * Requires:
 *   - `item` is the currently-active TtsQueueItem (id_hash present)
 *   - `handlers.onStop` / `handlers.onDelete` are functions
 * Ensures:
 *   - returns a single `.tts-active-card` root (data-testid
 *     `multiplexer-tts-active-card`) with icon / time / message-80 / Stop /
 *     delete children, in legacy order
 *   - Stop click → onStop(); delete click → onDelete(item.id_hash) (and stops
 *     propagation so the card's own click handlers don't also fire)
 *   - all dynamic text set via .textContent (AC2e safe-write)
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function renderTtsActiveCard(
  item     : TtsQueueItem,
  handlers : TtsActiveCardHandlers,
): HTMLElement {
  const card = document.createElement( "div" );
  card.className = "tts-active-card";
  card.setAttribute( "data-testid", "multiplexer-tts-active-card" );

  const iconDiv = document.createElement( "div" );
  iconDiv.className   = "tts-type-icon";
  iconDiv.textContent = ttsCardIcon( item );

  const timeSpan = document.createElement( "span" );
  timeSpan.className   = "message-time";
  timeSpan.textContent = ttsCardTime( item );

  const messageDiv = document.createElement( "div" );
  messageDiv.className   = "tts-message";
  messageDiv.textContent = truncateTtsText( item.ttsText ?? "", ACTIVE_TRUNCATE );

  const stopBtn = document.createElement( "button" );
  stopBtn.type        = "button";
  stopBtn.className    = "tts-stop-button";
  stopBtn.textContent = "⏹️ Stop";
  stopBtn.addEventListener( "click", () => handlers.onStop() );

  const deleteBtn = document.createElement( "button" );
  deleteBtn.type        = "button";
  deleteBtn.className    = "tts-delete-button";
  deleteBtn.textContent = "🗑";
  deleteBtn.title       = "Remove from queue";
  deleteBtn.addEventListener( "click", ( e ) => {
    e.stopPropagation();
    handlers.onDelete( item.id_hash );
  } );

  card.append( iconDiv, timeSpan, messageDiv, stopBtn, deleteBtn );
  return card;
}
