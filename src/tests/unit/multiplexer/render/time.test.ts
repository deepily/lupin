// Multiplexer Phase 5 — render/time.ts unit tests.
// AC5 floor: ≥4 tests per design doc § Verification matrix.
// formatCountdown is a PURE formatter (D-H invariant).

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  formatCountdown,
  formatHM,
  formatDateKey,
} from "../../../../fastapi_app/static/js/multiplexer/render/time";

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
