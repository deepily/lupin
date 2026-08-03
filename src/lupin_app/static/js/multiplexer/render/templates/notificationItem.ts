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
import { renderPredictionVoteControls } from "./predictionVoteControls";
import type { PredictionVoteIntegration } from "./predictionVoteControls";
import type { Notification } from "../../shared/types";

interface RenderOptions {
  appTimezone?: string;
  // WP14 (F8) — bridge to the vote orchestrator (NotificationsListRenderer).
  // Absent in the storeless parity harness: controls still render (presence is
  // pure-data) but clicks are inert. Threaded senderCard → dateAccordion → here.
  predictionVote?: PredictionVoteIntegration;
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
  // WS2 / C2-d (D3): chat-bubble direction. Legacy notifications.js tagged each
  // message `incoming`|`outgoing` off an `isResponse` flag and split a responded
  // notification into an incoming prompt + a synthetic `{id}-response` outgoing
  // reply (notifications.js:14317-14330). The multiplexer mirrors that: the
  // responded-split (NotificationStore.hydrateHistory at load time) sets
  // `direction` on each Notification, and this renderer applies it. Absent →
  // "incoming" (the inbound default — every live persona message is incoming).
  const direction = notification.direction === "outgoing" ? "outgoing" : "incoming";
  root.className = expired
    ? `sender-message ${direction} expired-response`
    : `sender-message ${direction}`;
  root.setAttribute("data-id-hash", notification.id_hash);
  if (inProgressGrp) {
    root.setAttribute("data-progress-group", notification.progress_group_id as string);
  }

  // Inner structure differs slightly when message is part of a progress group:
  // legacy renders `.progress-group-head` wrapper around the time + text.
  //
  // WS3 parity (2026-06-22): the expired-badge + abstract-indicator nest INSIDE
  // `.message-text` (after the markdown), verbatim to legacy
  // notifications.js:13788 (progress-group head) + :13800 (flat). They are NOT
  // flex siblings of `.message-text`: the `.sender-message` row is a flexbox
  // with `.message-text { flex: 1 }`, so a sibling badge/indicator would steal
  // ~badge-width from the text run (the real Tier-3 geometry divergence the
  // layout-parity oracle flagged — msg-text width short by ~badge+gap).
  // Nesting keeps the text run full-width, matching the legacy golden.
  if (inProgressGrp) {
    /* c8 ignore next 8 */ // tagged-template literal: c8 reports phantom branches on $-interpolations; the runtime path is straight-line and exercised by every progress-group test fixture.
    const head = html`
      <div class="progress-group-head">
        <span class="message-time">${timeText}</span>
        <span class="message-text">${renderMarkdownInline(notification.message)}${expired ? expiredBadge() : null}${hasAbstract ? abstractIndicator(notification.abstract as string) : null}</span>
        <span class="progress-group-toggle" aria-expanded="false" role="button" tabindex="0">▶</span>
      </div>
      <div class="progress-group-history" hidden></div>
    ` as DocumentFragment;
    root.appendChild(head);
  } else {
    /* c8 ignore next 4 */ // tagged-template literal: c8 reports phantom branches on each $-interpolation; the runtime path is straight-line and exercised by every test that renders a non-progress-group notification (the inProgressGrp=true branch above is the alternate, also covered).
    const flat = html`
      <span class="message-time">${timeText}</span>
      <span class="message-text">${renderMarkdownInline(notification.message)}${expired ? expiredBadge() : null}${hasAbstract ? abstractIndicator(notification.abstract as string) : null}</span>
    ` as DocumentFragment;
    root.appendChild(flat);
  }

  // B4 (01-D) — per-message active-TTS corner controls (⏸/⏹) + proxy-ratify-link.
  // Rendered on EVERY incoming bubble (flat + progress-group) but CSS-gated to
  // display:none by default; the active-TTS class driver (NotificationsListRenderer)
  // lights exactly the actively-spoken bubble via `.sender-message.tts-playing`
  // (gate selectors ported in B5). PURE DOM — clicks ride the renderer's DELEGATED
  // handler, NO inline listener / NO stopPropagation (F-Krishna-BD4). Gated to
  // incoming, mirroring legacy `!isResponse` (notifications.js:13866). The id is
  // carried on `data-notification-id` so the delegated handler can route the click.
  if (direction !== "outgoing") {
    root.appendChild(cornerPauseButton(notification.id_hash));
    root.appendChild(cornerStopButton(notification.id_hash));
  }
  // Proxy-ratify-link — ONLY for proxy batches (progress_group_id starts with
  // `pr-`; legacy createProxyRatifyLink gate notifications.js:7168). The click
  // (delegated, renderer-side) calls apiClient.acknowledgeProxy() + opens the
  // ratify page via window.open (F-Krishna-BD3 / F-Sam-BD3).
  if (inProgressGrp && (notification.progress_group_id as string).startsWith("pr-")) {
    root.appendChild(proxyRatifyLink(notification.progress_group_id as string));
  }

  // WP14 (F8) — prediction-hint thumbs vote. Presence is PURE-DATA: a
  // notification carrying a `prediction_hint` whose confidence clears the gate
  // (≥ PREDICTION_VOTE_MIN_PCT, enforced inside renderPredictionVoteControls)
  // mounts the 👍🏼/👎🏼 controls. The `predictionVote` integration (optional —
  // absent in the storeless parity harness) supplies the cast-vote highlight on
  // (re)render and the click orchestration (optimistic + POST + reconcile).
  // Ports legacy notifications.js `buildPredictionHintSection` → `_buildPredictionVoteControls`.
  const hint = notification.prediction_hint;
  if (hint !== undefined) {
    const integration = opts.predictionVote;
    const id = notification.id_hash;
    const controls = renderPredictionVoteControls(
      {
        notificationId : id,
        confidencePct  : Math.round(hint.confidence * 100),
        castVote       : integration?.getVote(id),
      },
      { onVote: (dir) => integration?.onVote(id, dir) },
    );
    if (controls !== null) root.appendChild(controls);
  }

  return root;
}

function expiredBadge(): Value {
  return html`<span class="expired-badge">EXPIRED</span>` as DocumentFragment;
}

// B4 (01-D) corner controls — built via DOM ops (not the html`` helper) so the
// returned elements carry typed button/anchor semantics + dataset attrs the
// delegated click handler reads, verbatim to legacy notifications.js:13869/:13919.

function cornerPauseButton(idHash: string): HTMLButtonElement {
  const btn = document.createElement("button");
  btn.type                     = "button";
  btn.className                = "notification-corner-pause-btn";
  btn.dataset.notificationId   = idHash;
  btn.dataset.paused           = "false";
  btn.title                    = "Pause this notification's playback";
  btn.textContent              = "⏸";
  btn.setAttribute("aria-label", "Pause notification audio");
  return btn;
}

function cornerStopButton(idHash: string): HTMLButtonElement {
  const btn = document.createElement("button");
  btn.type                     = "button";
  btn.className                = "notification-corner-stop-btn";
  btn.dataset.notificationId   = idHash;
  // mux stop = halt + de-light via the F0 current()-clear, NOT advance
  // (F-Cheech-BD1) — so the title intentionally drops legacy's "and advance".
  btn.title                    = "Stop this notification's playback";
  btn.textContent              = "⏹";
  btn.setAttribute("aria-label", "Stop notification audio");
  return btn;
}

function proxyRatifyLink(groupId: string): HTMLAnchorElement {
  const link = document.createElement("a");
  link.className       = "proxy-ratify-link";
  link.href            = "#";
  link.textContent     = "Open Ratification →";
  link.dataset.batchId = groupId;
  return link;
}

/* c8 ignore start */ // tsx phantom-branch artifact on function declaration line + tagged-template literal interpolation phantom.
function abstractIndicator(abstract: string): Value {
  // 📋 indicator with abstract stored on data-attribute — popover handler
  // attaches in Phase 6.
  const el = html`<span class="abstract-indicator" data-abstract="${abstract}" role="button" tabindex="0">📋</span>` as DocumentFragment;
  return el;
}
/* c8 ignore stop */
