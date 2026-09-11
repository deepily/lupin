/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// 360de81b — the minimized row for an Action Required card waiting behind the active one.
//
// Legacy parity: renderMinimizedNotificationDOM (notifications.js:21498) — a #N position badge, a
// type icon, the message cut to 57 characters plus "..." when it runs past 60, and the ask's
// timeout (formatTimeoutDisplay :21546). Clicking a legacy row only shows "Please respond to the
// current notification first" (:21565); here that sentence is the row's title, and the row has no
// controls, so a queued card cannot be answered out of turn.
//
// NOT ported: legacy's persona badge on the row (named in the parity doc).
//
// AC2e safe-write invariant: all DOM writes go through the `html` tagged template. NEVER use
// `.innerHTML =`, `rawHTML(`, or `.outerHTML =` (grep-tested in templates_action_required_queue_row.test.ts).

import { html } from "../html";
import type { ActionRequiredItem } from "../../shared/types";

// A switch, not an object lookup: no_lookup_walks_the_prototype_chain.test.ts bans `obj[key]` on a
// plain object, where a key like "constructor" would return Object.prototype's member.
function typeIcon(responseType: ActionRequiredItem["response_type"]): string {
  switch (responseType) {
    case "yes_no":          return "❓";
    case "open_ended":      return "💬";
    case "multiple_choice": return "📋";
    default:                return "📢";
  }
}

/**
 * Format a queued card's timeout as legacy does.
 *
 * Requires:
 *   - seconds is a non-negative number
 *
 * Ensures:
 *   - returns "<whole minutes>m" when seconds >= 60, else "<seconds>s"
 */
export function formatQueueTimeout(seconds: number): string {
  if (seconds >= 60) return `${Math.floor(seconds / 60)}m`;
  return `${seconds}s`;
}

/**
 * Build the minimized row for a queued card.
 *
 * Requires:
 *   - position is the card's 1-indexed place in the queue (the active card is not counted)
 *
 * Ensures:
 *   - returned element carries `data-id-hash` and `data-testid="multiplexer-action-required-queued"`
 *   - shows `#<position>`, the type icon, the (truncated) prompt as text, and the timeout
 *   - contains no button or input
 */
export function renderActionRequiredQueueRow(item: ActionRequiredItem, position: number): HTMLElement {
  const row = document.createElement("div");
  row.className = "action-required-minimized";
  row.setAttribute("data-id-hash", item.id_hash);
  row.setAttribute("data-testid", "multiplexer-action-required-queued");
  row.setAttribute("title", "Please respond to the current notification first");

  const message = item.prompt.length > 60 ? item.prompt.substring(0, 57) + "..." : item.prompt;
  const icon    = typeIcon(item.response_type);

  /* c8 ignore next 6 */ // tagged-template literal: c8 reports a phantom branch on the last $-interpolation (jobBucket.ts:109 precedent); the path is straight-line and every test here renders it.
  row.appendChild(html`
    <div class="action-required-minimized-position">#${position}</div>
    <div class="action-required-minimized-icon">${icon}</div>
    <div class="action-required-minimized-message">${message}</div>
    <div class="action-required-minimized-timeout">${formatQueueTimeout(item.timeout_seconds)}</div>
  ` as DocumentFragment);
  return row;
}
