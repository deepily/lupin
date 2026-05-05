// Multiplexer Phase 5 — sender card template (`.sender-card`).
//
// Per Q-C: legacy class names verbatim — `.sender-card`, `.sender-card-header`,
// `.sender-card-dates`, `.sender-active-indicator`, `.persona-badge`,
// `.sender-new-count`, `.sender-message-count`, `.sender-last-activity`.
//
// Persona color flows through the `--persona-color` CSS custom property via
// `element.style.setProperty()` POST-render — design doc § DOM grouping
// explicitly avoids inline `style="${...}"` interpolation in the helper.
// Per F12: the outer element carries `data-id-hash="${sender.sender_id}"`.
//
// Date grouping is the renderer's responsibility (sender → date → messages).
// `renderSenderCard` accepts a list of notifications already filtered to this
// sender; it groups by `formatDateKey(ts)` internally.

import { html } from "../html";
import { keyedListMerge } from "../dom";
import { formatDateKey, formatHM } from "../time";
import { renderDateAccordion } from "./dateAccordion";
import type { SenderRecord, Notification } from "../../shared/types";

interface RenderOptions {
  appTimezone?: string;
}

/**
 * Render a `.sender-card` for one sender + their notifications.
 *
 * Requires:
 *   - `sender` has `sender_id`, `display_name`
 *   - `notifications` is the list of messages from this sender (already
 *     filtered upstream); may be empty (renders chrome only)
 *
 * Ensures:
 *   - Returned element carries `data-id-hash="${sender.sender_id}"` (F12)
 *     AND `data-sender-id="${sender.sender_id}"` (legacy attribute name)
 *   - Voice-persona color applied via `style.setProperty("--persona-color", ...)`
 *     when sender carries a persona — NO inline `style=` interpolation
 *   - Notifications grouped by date, descending; date accordions carry their
 *     own keyed-merge IDs for re-render stability
 */
export function renderSenderCard(
  sender: SenderRecord,
  notifications: ReadonlyArray<Notification>,
  opts: RenderOptions = {},
): HTMLElement {
  const root = document.createElement("div");
  root.className = "sender-card";
  root.setAttribute("data-id-hash",  sender.sender_id);
  root.setAttribute("data-sender-id", sender.sender_id);

  const persona = sender.voice_persona;
  if (persona !== undefined) {
    root.style.setProperty("--persona-color", persona.color);
  }

  // Header chrome. Persona-badge class is computed before template interpolation
  // because the helper only supports whole-attribute interpolation (not
  // mid-attribute concatenation like `class="persona-badge${borrowed}"`).
  let personaBadge: DocumentFragment | null = null;
  if (persona !== undefined) {
    const badgeClass = persona.borrowed ? "persona-badge borrowed" : "persona-badge";
    personaBadge = html`<span class="${badgeClass}">${persona.icon} ${persona.name}</span>` as DocumentFragment;
  }

  const lastActivityText = sender.last_active_ts > 0
    ? `Last: ${formatHM(sender.last_active_ts, opts.appTimezone)}`
    : "";

  const headerFrag = html`
    <div class="sender-card-header" role="button" tabindex="0">
      <span class="sender-active-indicator">●</span>
      <span class="sender-display-name">${sender.display_name || sender.sender_id}</span>
      <span class="sender-stats-group">
        ${personaBadge}
        ${sender.unread_count > 0
          ? html`<span class="sender-new-count">${sender.unread_count}</span>`
          : null}
        <span class="sender-message-count">(${notifications.length})</span>
        <span class="sender-last-activity">${lastActivityText}</span>
      </span>
    </div>
    <div class="sender-card-dates"></div>
  ` as DocumentFragment;
  root.appendChild(headerFrag);

  // Group notifications by date key.
  const datesContainer = root.querySelector(".sender-card-dates") as HTMLElement;
  const groupedByDate = groupByDateKey(notifications, opts.appTimezone);

  keyedListMerge({
    parent  : datesContainer,
    entries : groupedByDate.map(g => ({ idHash: g.dateKey, group: g })),
    create  : (e) => renderDateAccordion(e.group.dateKey, e.group.items, opts),
  });

  return root;
}

interface DateGroup {
  dateKey : string;
  items   : Notification[];
}

function groupByDateKey(notifications: ReadonlyArray<Notification>, appTimezone?: string): DateGroup[] {
  const buckets = new Map<string, Notification[]>();
  for (const n of notifications) {
    const key = formatDateKey(n.ts, appTimezone);
    let arr = buckets.get(key);
    if (arr === undefined) {
      arr = [];
      buckets.set(key, arr);
    }
    arr.push(n);
  }
  // Sort each bucket newest-first (legacy `.date-accordion-messages` order).
  for (const arr of buckets.values()) {
    arr.sort((a, b) => b.ts - a.ts);
  }
  // Sort dates descending (newest date at top — legacy `.sender-card-dates` order).
  const groups: DateGroup[] = [];
  for (const [dateKey, items] of buckets) {
    groups.push({ dateKey, items });
  }
  groups.sort((a, b) => b.dateKey.localeCompare(a.dateKey));
  return groups;
}
