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

// CSS-parity 2026-06-17: every message is an inbound notification → `.incoming`
// chat-bubble variant must be applied (the Notification model has no direction
// field, so there is no `.outgoing` case). Covers both the plain and the
// expired class-string branches.
test("notificationItem: applies .incoming on the plain message", () => {
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
