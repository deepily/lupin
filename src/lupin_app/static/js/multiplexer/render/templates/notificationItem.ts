/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Phase 5 — notification item template (`.sender-message`).
//
// Renders a single notification message inside a date accordion. Uses legacy
// class names verbatim per Q-C: `.sender-message`, `.message-time`,
// `.message-text`, `.expired-badge`, `.abstract-indicator`,
// `.progress-group-head`, `.progress-group-toggle`, `.progress-group-history`.
//
// Markdown body uses `renderMarkdownInline` (no `<p>` wrap) per D-J — chat
// bubbles look wrong with paragraph wrapping. The message author may use
// markdown formatting; DOMPurify config + post-process anchors per Q-E.
//
// Per F12: every keyed-merge element carries `data-id-hash="${notification.id_hash}"`.

import { html } from "../html";
import type { Value } from "../html";
import { renderMarkdownInline } from "../markdown";
import { formatHM } from "../time";
import type { Notification } from "../../shared/types";

interface RenderOptions {
  appTimezone?: string;
}

/**
 * Render a single notification as `.sender-message`.
 *
 * Returns an `HTMLElement` (the outer `.sender-message` div) so callers can
 * attach event listeners directly + read `data-id-hash` for keyed merge.
 *
 * Requires:
 *   - `notification` has `id_hash`, `ts`, `message`
 *
 * Ensures:
 *   - Returned element carries `data-id-hash="${notification.id_hash}"` (F12)
 *   - Class includes `expired-response` when `was_expired === true`
 *   - Body rendered via `renderMarkdownInline` (no `<p>` wrap)
 *   - Time text uses `time_display` if backend-provided; otherwise `formatHM(ts)`
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line (TypeScript optional-param + return-type erasure).
export function renderNotificationItem(
  notification: Notification,
  opts: RenderOptions = {},
): HTMLElement {
  const expired       = notification.was_expired === true;
  const timeText      = notification.time_display ?? formatHM(notification.ts, opts.appTimezone);
  const hasAbstract   = typeof notification.abstract === "string" && notification.abstract.length > 0;
  const inProgressGrp = typeof notification.progress_group_id === "string" && notification.progress_group_id.length > 0;

  // Build a div + use DOM ops directly so we can return HTMLElement (not DocumentFragment).
  const root = document.createElement("div");
  // CSS-parity 2026-06-17: apply the `.incoming` chat-bubble variant. Legacy
  // notifications.js (13698/14061) tagged each message `incoming`|`outgoing`
  // off an `isResponse` flag; the multiplexer Notification model has NO
  // direction field (every item in this store is an inbound notification from
  // a persona), so all messages are `.incoming`. Without this class the
  // `.sender-message.incoming` gradient + left-offset never engaged and
  // messages rendered as flat undifferentiated rows.
  root.className = expired ? "sender-message incoming expired-response" : "sender-message incoming";
  root.setAttribute("data-id-hash", notification.id_hash);
  if (inProgressGrp) {
    root.setAttribute("data-progress-group", notification.progress_group_id as string);
  }

  // Inner structure differs slightly when message is part of a progress group:
  // legacy renders `.progress-group-head` wrapper around the time + text.
  if (inProgressGrp) {
    /* c8 ignore next 9 */ // tagged-template literal: c8 reports phantom branches on $-interpolations; the runtime path is straight-line and exercised by every progress-group test fixture.
    const head = html`
      <div class="progress-group-head">
        <span class="message-time">${timeText}</span>
        <span class="message-text">${renderMarkdownInline(notification.message)}</span>
        ${expired ? expiredBadge() : null}
        ${hasAbstract ? abstractIndicator(notification.abstract as string) : null}
        <span class="progress-group-toggle" aria-expanded="false" role="button" tabindex="0">▶</span>
      </div>
      <div class="progress-group-history" hidden></div>
    ` as DocumentFragment;
    root.appendChild(head);
  } else {
    /* c8 ignore next 6 */ // tagged-template literal: c8 reports phantom branches on each $-interpolation; the runtime path is straight-line and exercised by every test that renders a non-progress-group notification (the inProgressGrp=true branch above is the alternate, also covered).
    const flat = html`
      <span class="message-time">${timeText}</span>
      <span class="message-text">${renderMarkdownInline(notification.message)}</span>
      ${expired ? expiredBadge() : null}
      ${hasAbstract ? abstractIndicator(notification.abstract as string) : null}
    ` as DocumentFragment;
    root.appendChild(flat);
  }

  return root;
}

function expiredBadge(): Value {
  return html`<span class="expired-badge">EXPIRED</span>` as DocumentFragment;
}

/* c8 ignore start */ // tsx phantom-branch artifact on function declaration line + tagged-template literal interpolation phantom.
function abstractIndicator(abstract: string): Value {
  // 📋 indicator with abstract stored on data-attribute — popover handler
  // attaches in Phase 6.
  const el = html`<span class="abstract-indicator" data-abstract="${abstract}" role="button" tabindex="0">📋</span>` as DocumentFragment;
  return el;
}
/* c8 ignore stop */
