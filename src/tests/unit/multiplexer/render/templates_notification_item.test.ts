// Multiplexer Phase 5 — notificationItem template tests.
// AC5 floor: ≥4 tests.

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { renderNotificationItem } from "../../../../lupin_app/static/js/multiplexer/render/templates/notificationItem";
import type { Notification } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

beforeEach(() => {
  // Mock marked + DOMPurify globals — same shim shape as markdown.test.ts.
  (globalThis as { marked?: { parse: (s: string) => string } }).marked = {
    parse: (s: string) => `<p>${s}</p>`,
  };
  (globalThis as { DOMPurify?: { sanitize: (s: string) => string } }).DOMPurify = {
    sanitize: (s: string) => s,
  };
});

function makeNotification(overrides: Partial<Notification> = {}): Notification {
  return {
    id_hash         : "n1",
    ts              : Date.UTC(2026, 4, 5, 14, 7),
    sender_id       : "sess_42",
    message         : "hello",
    action_required : false,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------

test("notificationItem: carries data-id-hash on the outer .sender-message (F12)", () => {
  const el = renderNotificationItem(makeNotification(), { appTimezone: "UTC" });
  assert.equal(el.getAttribute("data-id-hash"), "n1");
  assert.ok(el.classList.contains("sender-message"));
});

test("notificationItem: was_expired=true adds .expired-response class + EXPIRED badge", () => {
  const el = renderNotificationItem(makeNotification({ was_expired: true }), { appTimezone: "UTC" });
  assert.ok(el.classList.contains("expired-response"));
  const badge = el.querySelector(".expired-badge");
  assert.notEqual(badge, null);
  assert.equal(badge!.textContent, "EXPIRED");
});

// WS2 / C2-d (D3): direction is `incoming` by default (absent direction) and
// `outgoing` when the Notification carries direction="outgoing" (the synthetic
// `{id}-response` reply from the responded-split). Covers both the plain and
// the expired class-string branches for BOTH directions.
test("notificationItem: applies .incoming on the plain message (default direction)", () => {
  const el = renderNotificationItem(makeNotification(), { appTimezone: "UTC" });
  assert.ok(el.classList.contains("sender-message"));
  assert.ok(el.classList.contains("incoming"));
  assert.equal(el.classList.contains("outgoing"), false);
});

test("notificationItem: applies .incoming alongside .expired-response", () => {
  const el = renderNotificationItem(makeNotification({ was_expired: true }), { appTimezone: "UTC" });
  assert.ok(el.classList.contains("sender-message"));
  assert.ok(el.classList.contains("incoming"));
  assert.ok(el.classList.contains("expired-response"));
});

test("notificationItem: direction='outgoing' applies .outgoing, not .incoming", () => {
  const el = renderNotificationItem(makeNotification({ direction: "outgoing" }), { appTimezone: "UTC" });
  assert.ok(el.classList.contains("sender-message"));
  assert.ok(el.classList.contains("outgoing"));
  assert.equal(el.classList.contains("incoming"), false);
});

test("notificationItem: direction='outgoing' composes with .expired-response", () => {
  const el = renderNotificationItem(makeNotification({ direction: "outgoing", was_expired: true }), { appTimezone: "UTC" });
  assert.ok(el.classList.contains("outgoing"));
  assert.ok(el.classList.contains("expired-response"));
  assert.equal(el.classList.contains("incoming"), false);
});

test("notificationItem: explicit direction='incoming' applies .incoming", () => {
  const el = renderNotificationItem(makeNotification({ direction: "incoming" }), { appTimezone: "UTC" });
  assert.ok(el.classList.contains("incoming"));
  assert.equal(el.classList.contains("outgoing"), false);
});

test("notificationItem: time_display backend override beats formatHM", () => {
  const el = renderNotificationItem(makeNotification({ time_display: "23:10 EST" }), { appTimezone: "UTC" });
  const timeText = el.querySelector(".message-time")!.textContent;
  assert.equal(timeText, "23:10 EST");
});

test("notificationItem: time_display absent → formatHM(ts) renders HH:MM", () => {
  // ts = 2026-05-05 14:07 UTC
  const el = renderNotificationItem(makeNotification(), { appTimezone: "UTC" });
  const timeText = el.querySelector(".message-time")!.textContent;
  assert.equal(timeText, "14:07");
});

test("notificationItem: progress_group_id triggers .progress-group-head wrapper + history container", () => {
  const el = renderNotificationItem(makeNotification({ progress_group_id: "pg_1" }), { appTimezone: "UTC" });
  const head = el.querySelector(".progress-group-head");
  const hist = el.querySelector(".progress-group-history");
  assert.notEqual(head, null);
  assert.notEqual(hist, null);
  assert.equal((hist as HTMLElement).hasAttribute("hidden"), true);
  assert.equal(el.getAttribute("data-progress-group"), "pg_1");
});

test("notificationItem: abstract present → .abstract-indicator with data-abstract", () => {
  const el = renderNotificationItem(makeNotification({ abstract: "long form context" }), { appTimezone: "UTC" });
  const indicator = el.querySelector(".abstract-indicator");
  assert.notEqual(indicator, null);
  assert.equal(indicator!.getAttribute("data-abstract"), "long form context");
});

// WS3 parity (2026-06-22): expired-badge + abstract-indicator must nest INSIDE
// `.message-text` (verbatim legacy notifications.js:13800), NOT be flex siblings
// of it — otherwise they steal width from the flex:1 text run and the Tier-3
// geometry oracle flags a message-text width divergence.
test("notificationItem: expired-badge + abstract-indicator nest INSIDE .message-text (flat, parity)", () => {
  const el = renderNotificationItem(
    makeNotification({ was_expired: true, abstract: "ctx" }),
    { appTimezone: "UTC" },
  );
  const text = el.querySelector(".message-text")!;
  assert.notEqual(text.querySelector(".expired-badge"), null, "badge must be a CHILD of .message-text");
  assert.notEqual(text.querySelector(".abstract-indicator"), null, "indicator must be a CHILD of .message-text");
  // And NOT a direct sibling of .message-text under .sender-message.
  assert.equal(el.querySelector(":scope > .expired-badge"), null, "badge must NOT be a flex sibling of .message-text");
  assert.equal(el.querySelector(":scope > .abstract-indicator"), null, "indicator must NOT be a flex sibling of .message-text");
});

test("notificationItem: progress-group head nests badge + indicator INSIDE .message-text (parity)", () => {
  const el = renderNotificationItem(
    makeNotification({ progress_group_id: "pg_1", was_expired: true, abstract: "ctx" }),
    { appTimezone: "UTC" },
  );
  const text = el.querySelector(".progress-group-head .message-text")!;
  assert.notEqual(text.querySelector(".expired-badge"), null, "badge nests in .message-text within the head");
  assert.notEqual(text.querySelector(".abstract-indicator"), null, "indicator nests in .message-text within the head");
});
