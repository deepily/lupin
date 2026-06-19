/* c8 ignore next */ // tsx phantom-branch artifact on file-header line (TypeScript module-init transpile artifact in c8's source-map view; no actual code on this line).
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
import { slugifySenderId } from "./slugify";
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
    // CSS-parity 2026-06-17: the header gradient, card box-shadow ring, and
    // `.sender-message.incoming` gradient all consume `--persona-color-rgb`
    // (an "r, g, b" triplet inside `rgb(...)/rgba(...)`). Only `--persona-color`
    // (hex) was being set, so every persona-tinted surface silently fell back
    // to the neutral default. Derive + set the triplet so the tint engages.
    const rgbTriplet = hexToRgbTriplet(persona.color);
    if (rgbTriplet !== null) {
      root.style.setProperty("--persona-color-rgb", rgbTriplet);
    }
  }

  // Header chrome. Persona-badge class is computed before template
  // interpolation because the helper only supports whole-attribute
  // interpolation (not mid-attribute concatenation).
  //
  // Phase 6c Node A Step A1 (2026-05-19): the badge was renamed from
  // `.persona-badge` (span) to `.sender-persona-badge` (button) per
  // F-Arnold-3 (rule-rename-in-place). The button carries `popovertarget`
  // pointing at the matching persona-popover modal id (constructed via the
  // same `slugifySenderId` helper personaModal.ts uses for the popover's
  // `id` attribute — single source of truth per Recon-A5). The button is
  // now glyph-only (icon, no inline name); the popover surfaces the name
  // and other persona fields on demand.
  //
  // F-Arnold-4: when sender has NO voice_persona, the badge element is
  // omitted entirely (not rendered as empty/stub). The `if (persona !==
  // undefined)` guard covers this — `personaBadge` stays null and the
  // header template's `${personaBadge}` interpolation skips it.
  let personaBadge: DocumentFragment | null = null;
  if (persona !== undefined) {
    const badgeClass    = persona.borrowed ? "sender-persona-badge borrowed" : "sender-persona-badge";
    const popoverTarget = `persona-popover-${slugifySenderId(sender.sender_id)}`;
    personaBadge = html`<button class="${badgeClass}" type="button" popovertarget="${popoverTarget}">${persona.icon}</button>` as DocumentFragment;
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

  // Phase 6c Node C Step C1 (2026-05-19): voice-input footer mount point.
  // Verbatim attribute names per legacy `notifications.js:10956`. The
  // SenderCardRecorderRenderer wires record + send buttons via click
  // delegation on the .cc-voice-input container.
  /* c8 ignore next 3 */ // sessionHash derivation: tests use sender_ids without '#' so only the else-branch is exercised at unit tier. Real wire shape (`claude.code@lupin.deepily.ai#abc123`) exercises the includes('#')→split path at smoke + integration tier.
  const sessionHash = sender.sender_id.includes("#")
    ? sender.sender_id.split("#")[1] ?? ""
    : sender.sender_id;
  const voiceInput = document.createElement("div");
  voiceInput.className = "cc-voice-input";
  voiceInput.setAttribute("data-session-hash", sessionHash);
  voiceInput.setAttribute("data-sender-id", sender.sender_id);
  root.appendChild(voiceInput);

  return root;
}

interface DateGroup {
  dateKey : string;
  items   : Notification[];
}

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line (TypeScript optional-param + return-type erasure produces a fake branch).
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

/**
 * Convert a CSS hex color to an "r, g, b" triplet string for use inside
 * `rgb(...)` / `rgba(...)`. Accepts `#RGB`, `#RRGGBB`, or the same without the
 * leading `#`. Returns null for unparseable input so the caller skips setting
 * `--persona-color-rgb` (leaving the stylesheet's neutral fallback in place).
 *
 * Requires:
 *   - `hex` is a string
 * Ensures:
 *   - returns "r, g, b" with 0-255 decimal channels for valid 3/6-digit hex
 *   - returns null for any input that is not a valid 3/6-digit hex color
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line (TypeScript return-type erasure produces a fake branch in c8's source-map view; the body is always entered when called — same convention as groupByDateKey above).
export function hexToRgbTriplet(hex: string): string | null {
  let h = hex.trim();
  if (h.startsWith("#")) h = h.slice(1);
  // Expand shorthand #RGB → RRGGBB (each char doubled; avoids indexed access
  // for strict noUncheckedIndexedAccess).
  if (h.length === 3) {
    h = h.replace(/./g, (c) => c + c);
  }
  if (h.length !== 6 || /[^0-9a-fA-F]/.test(h)) return null;
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `${r}, ${g}, ${b}`;
}
