/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Phase 5 — date accordion template (`.date-accordion`).
//
// Per Q-C / Q-G: legacy class names verbatim; collapsed-by-default toggle;
// progress-group history rendered eagerly empty + lazy-fills on first
// toggle-expand click (orchestrator owns the click handler).
//
// Returns an `HTMLElement` so the orchestrator can attach delegated handlers
// + reuse for keyed-merge slot reuse.

import { html } from "../html";
import { keyedListMerge } from "../dom";
import { renderNotificationItem } from "./notificationItem";
import type { Notification } from "../../shared/types";

interface RenderOptions {
  appTimezone?: string;
}

/**
 * Render a `.date-accordion` for one calendar date within a sender card.
 *
 * Requires:
 *   - `dateKey` is "YYYY-MM-DD"
 *   - `notifications` is the (non-empty) list of messages for that date,
 *     newest-first per legacy ordering
 *
 * Ensures:
 *   - Returned element carries `data-id-hash="${dateKey}"` for keyed merge
 *   - `.date-accordion-header` carries the date text + per-date count + toggle
 *   - `.date-accordion-messages` contains the notification items in order
 *   - `data-collapsed="false"` initial state (matches design — first paint
 *     visible; collapse is a user-driven toggle)
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line (TypeScript optional-param + return-type erasure).
export function renderDateAccordion(
  dateKey: string,
  notifications: ReadonlyArray<Notification>,
  opts: RenderOptions = {},
): HTMLElement {
  // Build outer structure via tagged-template helper.
  const root = document.createElement("div");
  root.className = "date-accordion";
  root.setAttribute("data-id-hash",  dateKey);
  root.setAttribute("data-date-key", dateKey);
  root.setAttribute("data-collapsed", "false");

  /* c8 ignore next 7 */ // tagged-template literal: c8 reports phantom branches on interpolation positions ($-expressions); the runtime path is straight-line and exercised by every test that invokes renderDateAccordion.
  const headerFrag = html`
    <div class="date-accordion-header" role="button" tabindex="0">
      <span class="date-text">${dateKey}</span>
      <span class="date-count">(${notifications.length})</span>
      <span class="date-toggle">▼</span>
    </div>
    <div class="date-accordion-messages"></div>
  ` as DocumentFragment;
  root.appendChild(headerFrag);

  // Populate the messages container via keyedListMerge so subsequent
  // re-renders preserve DOM identity.
  const messagesContainer = root.querySelector(".date-accordion-messages") as HTMLElement;
  keyedListMerge({
    parent : messagesContainer,
    entries: notifications.map(n => ({ idHash: n.id_hash, notification: n })),
    create : (e) => renderNotificationItem(e.notification, opts),
  });

  return root;
}
