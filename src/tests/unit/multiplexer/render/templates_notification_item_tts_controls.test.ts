// Multiplexer B4 (01-D, v0.1.9 CC-session parity) — notificationItem per-message
// TTS corner controls (⏸/⏹) + proxy-ratify-link.
//
// Companion to templates_notification_item.test.ts; targets the corner-control +
// ratify-link render branches added in the B4 lane. Run BOTH files under one c8
// process for the 100% gate on notificationItem.ts.
//
// Parity source: legacy notifications.js:13869 (pause), :13919 (stop), :7161
// (createProxyRatifyLink, gated on groupId.startsWith('pr-')). The mux buttons
// are PURE DOM — NO inline listener / NO stopPropagation (F-Krishna-BD4); clicks
// ride NotificationsListRenderer's delegated handler. Default visibility is
// display:none (CSS gate ported in B5); these tests assert PRESENCE + attributes
// only — the active-TTS visibility gate (T2) is a renderer + CSS concern.

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { renderNotificationItem } from "../../../../lupin_app/static/js/multiplexer/render/templates/notificationItem";
import type { Notification } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before(() => {
  if (typeof globalThis.document === "undefined") GlobalRegistrator.register();
});
beforeEach(() => {
  (globalThis as { marked?: { parse: (s: string) => string } }).marked = { parse: (s: string) => `<p>${s}</p>` };
  (globalThis as { DOMPurify?: { sanitize: (s: string) => string } }).DOMPurify = { sanitize: (s: string) => s };
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

// --- Corner ⏸/⏹ presence (incoming, flat) ---------------------------------

test("corner controls: incoming flat bubble carries pause + stop buttons as .sender-message descendants", () => {
  const el = renderNotificationItem(makeNotification(), { appTimezone: "UTC" });
  const pause = el.querySelector(".notification-corner-pause-btn") as HTMLButtonElement | null;
  const stop  = el.querySelector(".notification-corner-stop-btn") as HTMLButtonElement | null;
  assert.notEqual(pause, null);
  assert.notEqual(stop, null);
  // Both are descendants of the outer .sender-message (the CSS gate selector hook).
  assert.ok(el.classList.contains("sender-message"));
  assert.equal(pause!.tagName, "BUTTON");
  assert.equal(stop!.tagName, "BUTTON");
});

test("corner controls: pause button carries legacy attrs (class/type/glyph/data/aria)", () => {
  const el = renderNotificationItem(makeNotification({ id_hash: "abc123" }), { appTimezone: "UTC" });
  const pause = el.querySelector(".notification-corner-pause-btn") as HTMLButtonElement;
  assert.equal(pause.getAttribute("type"), "button");
  assert.equal(pause.textContent, "⏸");
  assert.equal(pause.dataset.notificationId, "abc123");
  assert.equal(pause.dataset.paused, "false");
  assert.equal(pause.getAttribute("aria-label"), "Pause notification audio");
  assert.equal(pause.getAttribute("title"), "Pause this notification's playback");
});

test("corner controls: stop button carries legacy attrs (class/type/glyph/data/aria) — title drops 'advance' (mux COND-2)", () => {
  const el = renderNotificationItem(makeNotification({ id_hash: "abc123" }), { appTimezone: "UTC" });
  const stop = el.querySelector(".notification-corner-stop-btn") as HTMLButtonElement;
  assert.equal(stop.getAttribute("type"), "button");
  assert.equal(stop.textContent, "⏹");
  assert.equal(stop.dataset.notificationId, "abc123");
  assert.equal(stop.getAttribute("aria-label"), "Stop notification audio");
  // mux stop = halt + de-light (NOT advance) per F-Cheech-BD1 → title must NOT say "and advance".
  assert.equal(stop.getAttribute("title"), "Stop this notification's playback");
  assert.equal(/advance/i.test(stop.getAttribute("title") ?? ""), false);
});

test("corner controls: buttons are PURE DOM — no inline onclick (clicks ride delegation, F-Krishna-BD4)", () => {
  const el = renderNotificationItem(makeNotification(), { appTimezone: "UTC" });
  const pause = el.querySelector(".notification-corner-pause-btn") as HTMLButtonElement;
  const stop  = el.querySelector(".notification-corner-stop-btn") as HTMLButtonElement;
  assert.equal(pause.onclick, null);
  assert.equal(stop.onclick, null);
});

// --- Corner ⏸/⏹ presence (incoming, progress-group) -----------------------

test("corner controls: progress-group bubble ALSO carries pause + stop buttons (both branches)", () => {
  const el = renderNotificationItem(makeNotification({ progress_group_id: "grp-7" }), { appTimezone: "UTC" });
  assert.ok( el.querySelector(".notification-corner-pause-btn") !== null );
  assert.ok( el.querySelector(".notification-corner-stop-btn") !== null );
  // sanity: it really is the progress-group branch.
  assert.ok( el.querySelector(".progress-group-head") !== null );
});

// --- Corner ⏸/⏹ gated to incoming (legacy !isResponse) --------------------

test("corner controls: outgoing (response) bubble renders NEITHER corner button", () => {
  const el = renderNotificationItem(makeNotification({ direction: "outgoing" }), { appTimezone: "UTC" });
  assert.ok( el.querySelector(".notification-corner-pause-btn") === null );
  assert.ok( el.querySelector(".notification-corner-stop-btn") === null );
});

// --- Proxy-ratify-link gate (progress_group_id startsWith 'pr-') -----------

test("ratify-link: proxy bubble (pr- group) renders the ratify link with data-batch-id + label", () => {
  const el = renderNotificationItem(makeNotification({ progress_group_id: "pr-1a2b3c4d-7" }), { appTimezone: "UTC" });
  const link = el.querySelector(".proxy-ratify-link") as HTMLAnchorElement | null;
  assert.notEqual(link, null);
  assert.equal(link!.tagName, "A");
  assert.equal(link!.textContent, "Open Ratification →");
  assert.equal(link!.dataset.batchId, "pr-1a2b3c4d-7");
  assert.equal(link!.getAttribute("href"), "#");
});

test("ratify-link: non-proxy progress-group (grp- prefix) renders NO ratify link", () => {
  const el = renderNotificationItem(makeNotification({ progress_group_id: "grp-7" }), { appTimezone: "UTC" });
  assert.ok( el.querySelector(".proxy-ratify-link") === null );
});

test("ratify-link: non-progress-group bubble renders NO ratify link", () => {
  const el = renderNotificationItem(makeNotification(), { appTimezone: "UTC" });
  assert.ok( el.querySelector(".proxy-ratify-link") === null );
});
