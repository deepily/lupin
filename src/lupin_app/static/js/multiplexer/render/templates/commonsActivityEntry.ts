/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Lane D (WP3, 2026-06-10) — commons activity entry template.
//
// Renders ONE `.commons-activity-entry` row for the Recent Activity panel.
// Verbatim class-name + grid-area port of legacy `_renderCommonsEntry`
// (`notifications.js:10724-10848`): icon · name · topic-chip · markdown body
// (collapsible) · Show-more toggle · time.
//
// Returns an `HTMLElement` (the row) so the renderer can (a) attach delegated
// toggle handling and (b) measure body overflow to reveal the Show-more toggle
// (WP11 / F4). Markdown body uses the block `renderMarkdown` (with `<p>` wrap)
// — the panel CSS clamps `.commons-activity-entry-body-content` to 2 lines and
// the `.expanded` class lifts the clamp.

import { html } from "../html";
import { renderMarkdown } from "../markdown";
import { formatHM } from "../time";
import type { CommonsActivityEntry } from "../../shared/types";

interface RenderOptions {
  appTimezone?: string;
}

// `broadcast-acks` bodies are bare status words ("completed" / "skipped" /
// "rejected-malformed") per `_post_ack` in broadcast_handler.py. Reshape to
// descriptive phrasing so the row reads as an event, not a status code
// (port of `notifications.js:10768-10773`).
const ACK_PHRASING: Record<string, string> = {
  "completed"          : "received broadcast",
  "skipped"            : "skipped broadcast",
  "rejected-malformed" : "rejected broadcast (malformed)",
};

/**
 * Render one commons activity entry as a `.commons-activity-entry` row.
 *
 * Requires:
 *   - `entry.topic` + `entry.topic_kind` are present (server contract)
 *   - `window.marked` + `window.DOMPurify` are loaded (markdown body)
 *
 * Ensures:
 *   - Returned element carries the `--persona-color` CSS var when the entry
 *     supplies `persona_color`
 *   - Topic chip is hidden for reserved topics; `dm-<x>` collapses to `@<x>`
 *   - Body is sanitized markdown inside `.commons-activity-entry-body-content`
 *   - The Show-more toggle starts hidden (renderer reveals it on overflow)
 *   - Time is `formatHM`-formatted (TZ-aware); absent/invalid ts → "--:--"
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line (optional-param + return-type erasure).
export function renderCommonsActivityEntry(
  entry: CommonsActivityEntry,
  opts: RenderOptions = {},
): HTMLElement {
  const rawTopic   = entry.topic || "";
  const isReserved = entry.topic_kind === "reserved";
  const chipText   = rawTopic.startsWith("dm-") ? `@${rawTopic.slice(3)}` : rawTopic;

  const personaName = entry.persona_name || "—";
  const personaIcon = entry.persona_icon || "·";

  let bodyText = entry.body || "";
  if (rawTopic === "broadcast-acks") {
    bodyText = ACK_PHRASING[bodyText] ?? bodyText;
  }

  const timeText = formatHM(entry.ts ? Date.parse(entry.ts) : NaN, opts.appTimezone);

  const root = document.createElement("div");
  root.className = "commons-activity-entry";
  if (entry.persona_color) {
    root.style.setProperty("--persona-color", entry.persona_color);
  }

  /* c8 ignore next 13 */ // tagged-template literal: c8 reports phantom branches on each $-interpolation position; the runtime path is straight-line and exercised by every entry-template test fixture.
  const inner = html`
    <div class="commons-activity-entry-icon">${personaIcon}</div>
    <div class="commons-activity-entry-name" title="${personaName}">${personaName}</div>
    <span class="commons-activity-entry-topic-chip" title="${rawTopic}" hidden="${isReserved}">${chipText}</span>
    <div class="commons-activity-entry-body">
      <div class="commons-activity-entry-body-content">${renderMarkdown(bodyText)}</div>
    </div>
    <button class="commons-activity-entry-body-toggle" type="button" hidden>Show more ▾</button>
    <div class="commons-activity-entry-time">${timeText}</div>
  ` as DocumentFragment;
  root.appendChild(inner);

  return root;
}
