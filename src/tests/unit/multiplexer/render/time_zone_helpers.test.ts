// The shared zone helpers show the server zone, else labelled UTC.
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  displayZone,
  zoneLabel,
  formatClock,
  hoursSinceMidnight,
  formatHM,
  formatDateKey,
} from "../../../../lupin_app/static/js/multiplexer/render/time";

const AT = Date.UTC(2026, 0, 14, 23, 30, 0);   // 08:30 the next morning in Tokyo

function inBrowserZone<T>(zone: string, fn: () => T): T {
  const saved = process.env.TZ;
  process.env.TZ = zone;
  try { return fn(); } finally { if (saved === undefined) delete process.env.TZ; else process.env.TZ = saved; }
}

test("displayZone and zoneLabel: a server zone is used unlabelled, anything empty means labelled UTC", () => {
  assert.equal(displayZone("Asia/Tokyo"), "Asia/Tokyo");
  assert.equal(zoneLabel("Asia/Tokyo"), "");
  for (const none of [undefined, null, ""]) {
    assert.equal(displayZone(none), "UTC");
    assert.equal(zoneLabel(none), " UTC");
  }
});

test("formatClock: the zone decides the clock, whatever the browser zone is", () => {
  inBrowserZone("America/Los_Angeles", () => {
    const when = new Date(AT);
    assert.equal(formatClock(when, "Asia/Tokyo", "en-US", { hour: "2-digit", minute: "2-digit", hour12: false }), "08:30");
    assert.equal(formatClock(when, undefined, "en-US", { hour: "2-digit", minute: "2-digit", hour12: false }), "23:30 UTC");
    assert.equal(formatClock(when, null, "en-US"), "11:30:00 PM UTC");
  });
});

test("hoursSinceMidnight: counted from midnight in the display zone, rounded up, at least one", () => {
  inBrowserZone("America/Los_Angeles", () => {
    assert.equal(hoursSinceMidnight(new Date(AT), "Asia/Tokyo"), 9);
    assert.equal(hoursSinceMidnight(new Date(AT), undefined), 24);
    assert.equal(hoursSinceMidnight(new Date(Date.UTC(2026, 0, 14, 0, 0, 0)), null), 1);
    assert.equal(hoursSinceMidnight(new Date(Date.UTC(2026, 0, 14, 0, 0, 0, 500)), "UTC"), 1);
    assert.equal(hoursSinceMidnight(new Date(Date.UTC(2026, 0, 14, 1, 0, 0, 500)), "UTC"), 2);
  });
});

test("formatHM and formatDateKey: no zone shows UTC (HM labelled, the date key not), whatever the browser zone is", () => {
  inBrowserZone("Asia/Tokyo", () => {
    assert.equal(formatHM(AT), "23:30 UTC");
    assert.equal(formatHM(AT, ""), "23:30 UTC");
    assert.equal(formatHM(AT, "Asia/Tokyo"), "08:30");
    assert.equal(formatDateKey(AT), "2026-01-14");
    assert.equal(formatDateKey(AT, "Asia/Tokyo"), "2026-01-15");
    assert.equal(formatHM(Number.NaN), "--:--");
    assert.equal(formatDateKey(Number.NaN), "----------");
  });
});
