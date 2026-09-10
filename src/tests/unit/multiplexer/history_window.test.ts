// P0 5ebd2aff (2026-09-10) — Rick's ruling 1: the history-window picker, matching legacy.
// Run via `npx tsx --test src/tests/unit/multiplexer/history_window.test.ts`.
//
// These pin the picker MODEL to the legacy client: the six options verbatim,
// the shared raw storage value both clients read, and the hours a query sends.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  DEFAULT_HISTORY_WINDOW_HOURS,
  HISTORY_WINDOW_KEY,
  HISTORY_WINDOW_OPTIONS,
  SENDERS_VISIBLE_MIN_HOURS,
  effectiveHoursForQuery,
  historyWindowLabel,
  parseStoredHistoryWindow,
  sendersVisiblePath,
  serializeHistoryWindow,
} from "../../../lupin_app/static/js/multiplexer/stores/historyWindow";

test("the six options match legacy notifications.js:422-429 — labels, order, values", () => {
  assert.deepEqual(HISTORY_WINDOW_OPTIONS, [
    { label: "Today",         hours: "today" },
    { label: "Last 24 hours", hours: 24 },
    { label: "Last 2 days",   hours: 48 },
    { label: "Last week",     hours: 168 },
    { label: "Last month",    hours: 720 },
    { label: "All time",      hours: null },
  ]);
});

test("the storage key is the legacy client's raw key", () => {
  assert.equal(HISTORY_WINDOW_KEY, "notifications_history_window");
});

test("parse: 'all' and the pre-fix empty string both mean All time", () => {
  assert.equal(parseStoredHistoryWindow("all"), null);
  assert.equal(parseStoredHistoryWindow(""), null);
});

test("parse: 'today' is kept as the since-midnight sentinel, not a number", () => {
  assert.equal(parseStoredHistoryWindow("today"), "today");
});

test("parse: a stored number is used as hours", () => {
  assert.equal(parseStoredHistoryWindow("168"), 168);
  assert.equal(parseStoredHistoryWindow("720"), 720);
});

test("parse: no stored value, junk, or zero fall back to 48 hours like legacy", () => {
  assert.equal(DEFAULT_HISTORY_WINDOW_HOURS, 48);
  assert.equal(parseStoredHistoryWindow(null), 48);
  assert.equal(parseStoredHistoryWindow("garbage"), 48);
  assert.equal(parseStoredHistoryWindow("0"), 48);
});

test("serialize: All time writes 'all', and every option survives a round trip", () => {
  assert.equal(serializeHistoryWindow(null), "all");
  assert.equal(serializeHistoryWindow("today"), "today");
  assert.equal(serializeHistoryWindow(24), "24");
  for (const option of HISTORY_WINDOW_OPTIONS) {
    assert.equal(parseStoredHistoryWindow(serializeHistoryWindow(option.hours)), option.hours, option.label);
  }
});

test("effective hours: All time sends no hours, a number sends itself", () => {
  const now = new Date(2026, 8, 10, 9, 30);
  assert.equal(effectiveHoursForQuery(null, now), null);
  assert.equal(effectiveHoursForQuery(168, now), 168);
});

test("effective hours: Today is whole hours since local midnight, rounded up", () => {
  assert.equal(effectiveHoursForQuery("today", new Date(2026, 8, 10, 9, 30)), 10);
  assert.equal(effectiveHoursForQuery("today", new Date(2026, 8, 10, 23, 0)), 23);
});

test("effective hours: Today never drops below 1, even at midnight", () => {
  assert.equal(effectiveHoursForQuery("today", new Date(2026, 8, 10, 0, 0, 0)), 1);
  assert.equal(effectiveHoursForQuery("today", new Date(2026, 8, 10, 0, 10)), 1);
});

test("label: each option shows its own label; any other number reads 'Last N hours'", () => {
  for (const option of HISTORY_WINDOW_OPTIONS) {
    assert.equal(historyWindowLabel(option.hours), option.label);
  }
  assert.equal(historyWindowLabel(12), "Last 12 hours");
});

// An unwindowed senders-visible blocks the dev server for ~52 s (41da77bb); the
// strip is filled from the same response, so the window has a 48 h floor.
test("senders-visible path: a window under 48 h is raised to 48, the floor itself and wider windows pass through", () => {
  assert.equal(SENDERS_VISIBLE_MIN_HOURS, 48);
  assert.equal(sendersVisiblePath("rick@example.com", 1),   "/api/notifications/senders-visible/rick%40example.com?hours=48");
  assert.equal(sendersVisiblePath("rick@example.com", 48),  "/api/notifications/senders-visible/rick%40example.com?hours=48");
  assert.equal(sendersVisiblePath("rick@example.com", 49),  "/api/notifications/senders-visible/rick%40example.com?hours=49");
  assert.equal(sendersVisiblePath("rick@example.com", 720), "/api/notifications/senders-visible/rick%40example.com?hours=720");
});

test("senders-visible path: All time sends no hours, like legacy; the email is URI-encoded", () => {
  assert.equal(sendersVisiblePath("a+b@x.com", null), "/api/notifications/senders-visible/a%2Bb%40x.com");
});
