// Multiplexer Phase 5 — render/time.ts unit tests.
// AC5 floor: ≥4 tests per design doc § Verification matrix.
// formatCountdown is a PURE formatter (D-H invariant).

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  formatCountdown,
  formatHM,
  formatDateKey,
  formatDuration,
} from "../../../../lupin_app/static/js/multiplexer/render/time";

// ---------------------------------------------------------------------------
// formatCountdown — D-H purity invariant
// ---------------------------------------------------------------------------

test("formatCountdown(5000) === '00:05' regardless of Date.now() (D-H purity)", () => {
  // Save and clobber Date.now to prove the formatter doesn't read it.
  const realNow = Date.now;
  Date.now = () => 999_999_999_999;
  try {
    assert.equal(formatCountdown(5000), "00:05");
  } finally {
    Date.now = realNow;
  }
});

test("formatCountdown handles boundary values: 0, negative, large", () => {
  assert.equal(formatCountdown(0), "00:00");
  assert.equal(formatCountdown(-1000), "00:00");
  assert.equal(formatCountdown(60_000), "01:00");
  assert.equal(formatCountdown(3_661_000), "61:01");
});

test("formatCountdown padding: single-digit minutes + seconds zero-pad to 2 chars", () => {
  assert.equal(formatCountdown(1_000),  "00:01");
  assert.equal(formatCountdown(9_000),  "00:09");
  assert.equal(formatCountdown(59_000), "00:59");
  assert.equal(formatCountdown(61_000), "01:01");
});

// ---------------------------------------------------------------------------
// formatHM
// ---------------------------------------------------------------------------

test("formatHM emits zero-padded HH:MM 24-hour", () => {
  // 2026-05-05 14:07 UTC — using UTC TZ to make the assertion deterministic
  // across CI timezones.
  const ts = Date.UTC(2026, 4, 5, 14, 7);
  assert.equal(formatHM(ts, "UTC"), "14:07");
});

test("formatHM with appTimezone='America/New_York' shifts to local TZ", () => {
  const ts = Date.UTC(2026, 4, 5, 14, 7);   // 14:07 UTC = 10:07 EDT
  assert.equal(formatHM(ts, "America/New_York"), "10:07");
});

test("formatHM with NaN/Infinity returns '--:--'", () => {
  assert.equal(formatHM(Number.NaN), "--:--");
  assert.equal(formatHM(Number.POSITIVE_INFINITY), "--:--");
});

// ---------------------------------------------------------------------------
// formatDateKey
// ---------------------------------------------------------------------------

test("formatDateKey emits ISO-style YYYY-MM-DD", () => {
  const ts = Date.UTC(2026, 4, 5, 14, 7);   // 2026-05-05
  assert.equal(formatDateKey(ts, "UTC"), "2026-05-05");
});

test("formatDateKey timezone boundary: midnight UTC vs America/Los_Angeles is previous day", () => {
  // 2026-05-05 00:30 UTC → 2026-05-04 17:30 PDT (previous calendar day)
  const ts = Date.UTC(2026, 4, 5, 0, 30);
  assert.equal(formatDateKey(ts, "UTC"),                  "2026-05-05");
  assert.equal(formatDateKey(ts, "America/Los_Angeles"),  "2026-05-04");
});

test("formatDateKey with NaN/Infinity returns '----------'", () => {
  assert.equal(formatDateKey(Number.NaN), "----------");
  assert.equal(formatDateKey(Number.POSITIVE_INFINITY), "----------");
});

// ---------------------------------------------------------------------------
// formatDuration — Phase 6a Pass 2 F24 (Genuinely New)
// ---------------------------------------------------------------------------

test("formatDuration with undefined endTs returns 'running for Ns' (sub-minute, Date.now stubbed)", () => {
  // Stub Date.now so the elapsed window is deterministic.
  const realNow = Date.now;
  const start   = 1_000_000_000_000;        // arbitrary fixed start
  Date.now = () => start + 23_000;          // 23s later
  try {
    assert.equal(formatDuration(start), "running for 23s");
  } finally {
    Date.now = realNow;
  }
});

test("formatDuration sub-minute completion: '<N>s'", () => {
  const start = 1_000_000_000_000;
  const end   = start + 23_000;             // 23s
  assert.equal(formatDuration(start, end), "23s");
  // Boundary: 0s elapsed.
  assert.equal(formatDuration(start, start), "0s");
  // Boundary: 59s elapsed.
  assert.equal(formatDuration(start, start + 59_000), "59s");
});

test("formatDuration sub-hour completion: '<N>m <M>s'", () => {
  const start = 1_000_000_000_000;
  // 5m 12s → 312s
  assert.equal(formatDuration(start, start + 312_000), "5m 12s");
  // Exactly 60s → "1m 0s" (boundary case from <60 to <3600)
  assert.equal(formatDuration(start, start + 60_000), "1m 0s");
  // 59m 59s → still in middle bucket
  assert.equal(formatDuration(start, start + (59 * 60 + 59) * 1000), "59m 59s");
});

test("formatDuration multi-hour completion: '<N>h <M>m'", () => {
  const start = 1_000_000_000_000;
  // 1h 47m → 1*3600 + 47*60 = 6420s
  assert.equal(formatDuration(start, start + 6420_000), "1h 47m");
  // Exactly 3600s → "1h 0m" (boundary case from <3600 to ≥3600)
  assert.equal(formatDuration(start, start + 3600_000), "1h 0m");
  // 2h 0m
  assert.equal(formatDuration(start, start + 7200_000), "2h 0m");
});

test("formatDuration with NaN/Infinity startTs returns '--'", () => {
  assert.equal(formatDuration(Number.NaN), "--");
  assert.equal(formatDuration(Number.POSITIVE_INFINITY), "--");
  assert.equal(formatDuration(Number.NEGATIVE_INFINITY, 1_000_000_000_000), "--");
});

test("formatDuration with finite startTs but NaN/Infinity endTs returns '--'", () => {
  const start = 1_000_000_000_000;
  assert.equal(formatDuration(start, Number.NaN), "--");
  assert.equal(formatDuration(start, Number.POSITIVE_INFINITY), "--");
});

test("formatDuration with endTs < startTs (clock skew) clamps to '0s'", () => {
  const start = 1_000_000_000_000;
  // Negative elapsed: completion before start (clock skew). Math.max clamps to 0.
  assert.equal(formatDuration(start, start - 5_000), "0s");
});

test("formatDuration running case across hour boundary: 'running for Nh Mm'", () => {
  const realNow = Date.now;
  const start   = 1_000_000_000_000;
  Date.now = () => start + 6420_000;        // 1h 47m later
  try {
    assert.equal(formatDuration(start), "running for 1h 47m");
  } finally {
    Date.now = realNow;
  }
});
