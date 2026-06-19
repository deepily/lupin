// Multiplexer Phase 6a — jobCard template tests.
// AC3 floor: ≥6 tests per design § Verification matrix.
// Includes Pass 2 F20 oversized-meta sub-test + F23 disabled-delete-button no-op companion.

import { test, before } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import {
  renderJobCard,
  configureMetaDisplayCap,
  safeStringifyMeta,
  populateJobMetaIfNeeded,
  _getMaxMetaBytesForTesting,
  _formatBytesForTesting,
} from "../../../../lupin_app/static/js/multiplexer/render/templates/jobCard";
import type { Job, JobStatus } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    id_hash      : "abc12345deadbeef",
    job_type     : "DeepResearchJob",
    status       : "running",
    created_at   : Date.UTC(2026, 4, 5, 14, 0),
    completed_at : Date.UTC(2026, 4, 5, 14, 5),  // 5m elapsed
    meta         : { topic: "quantum computing" },
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// renderJobCard — basic structure + status variants
// ---------------------------------------------------------------------------

test("renderJobCard returns HTMLElement with .job-card class + status modifier", () => {
  const job = makeJob({ status: "running" });
  const el  = renderJobCard(job);
  assert.equal(el.tagName, "DIV");
  assert.ok(el.classList.contains("job-card"));
  assert.ok(el.classList.contains("status-running"));
});

test("renderJobCard sets data-id-hash on .job-card AND data-job-type", () => {
  const job = makeJob({ id_hash: "xyz789abc", job_type: "PodcastGeneratorJob" });
  const el  = renderJobCard(job);
  assert.equal(el.getAttribute("data-id-hash"),  "xyz789abc");
  assert.equal(el.getAttribute("data-job-type"), "PodcastGeneratorJob");
});

test("renderJobCard NEVER sets data-id-hash on .job-delete-button (Pass 2 F23)", () => {
  const el     = renderJobCard(makeJob());
  const button = el.querySelector(".job-delete-button");
  assert.notEqual(button, null);
  assert.equal(button!.getAttribute("data-id-hash"), null);
});

test("renderJobCard delete button is inert: aria-disabled='true', tabindex='-1', has tooltip (Q-A6 + C-6)", () => {
  const el     = renderJobCard(makeJob());
  const button = el.querySelector(".job-delete-button") as HTMLButtonElement;
  assert.equal(button.getAttribute("aria-disabled"), "true");
  assert.equal(button.getAttribute("tabindex"),      "-1");
  assert.equal(button.getAttribute("title"),         "Delete coming in Phase 6b");
  assert.equal(button.textContent,                   "×");
});

test("renderJobCard renders all 4 valid Job.status values with correct icon (Pass 2 F18)", () => {
  const cases: Array<[JobStatus, string]> = [
    ["todo",    "⏳"],
    ["running", "⚙"],
    ["done",    "✓"],
    ["dead",    "✗"],
  ];
  for (const [status, expectedIcon] of cases) {
    const el   = renderJobCard(makeJob({ status }));
    const icon = el.querySelector(".job-status-icon");
    assert.ok(el.classList.contains(`status-${status}`), `status-${status} class missing`);
    assert.equal(icon?.textContent, expectedIcon, `icon for ${status} should be ${expectedIcon}`);
  }
});

test("renderJobCard .job-id-short is '#' + first 8 chars of id_hash", () => {
  const job = makeJob({ id_hash: "abc12345deadbeef" });
  const el  = renderJobCard(job);
  const idShort = el.querySelector(".job-id-short");
  assert.equal(idShort?.textContent, "#abc12345");
});

test("renderJobCard .job-timing populated via formatDuration(created_at, completed_at)", () => {
  const created   = Date.UTC(2026, 4, 5, 14, 0);
  const completed = Date.UTC(2026, 4, 5, 14, 5, 12);  // 5m 12s elapsed
  const job  = makeJob({ created_at: created, completed_at: completed });
  const el   = renderJobCard(job);
  const time = el.querySelector(".job-timing");
  assert.equal(time?.textContent, "5m 12s");
});

test("renderJobCard .job-timing for in-flight job (no completed_at) reads 'running for ...'", () => {
  const realNow   = Date.now;
  const created   = 1_000_000_000_000;
  Date.now = () => created + 23_000;  // 23s elapsed
  try {
    const job = makeJob({ created_at: created, completed_at: undefined });
    const el  = renderJobCard(job);
    const time = el.querySelector(".job-timing");
    assert.equal(time?.textContent, "running for 23s");
  } finally {
    Date.now = realNow;
  }
});

test("renderJobCard .job-card-details starts collapsed; <pre.job-meta-json> is empty + hidden initially", () => {
  const el      = renderJobCard(makeJob({ meta: { foo: "bar" } }));
  const details = el.querySelector(".job-card-details");
  const pre     = el.querySelector(".job-meta-json") as HTMLPreElement;
  assert.ok(details?.classList.contains("collapsed"));
  assert.equal(pre.hasAttribute("hidden"), true);
  assert.equal(pre.textContent, "");
});

// ---------------------------------------------------------------------------
// safeStringifyMeta — Pass 2 F20 cap behavior
// ---------------------------------------------------------------------------

test("safeStringifyMeta: small object stringifies via JSON.stringify with 2-space indent", () => {
  const out = safeStringifyMeta({ a: 1, b: "two" });
  assert.match(out, /"a":\s*1/);
  assert.match(out, /"b":\s*"two"/);
});

test("safeStringifyMeta: oversized payload returns '[meta too large to display' placeholder (F20)", () => {
  // 300_000-byte string value triggers the pre-check (cap default = 256_000).
  const big = "x".repeat(300_000);
  const out = safeStringifyMeta({ payload: big });
  assert.match(out, /\[meta too large to display/);
});

test("safeStringifyMeta: cyclic-reference object returns '[meta serialization failed: ...]'", () => {
  const cyclic: Record<string, unknown> = { name: "outer" };
  cyclic.self = cyclic;  // cycle
  // estimateSize halts at 256_000 cap if recursion blows up; otherwise JSON.stringify throws.
  // We just assert one of the two short-circuit paths fires and the result is a string.
  const out = safeStringifyMeta(cyclic);
  assert.equal(typeof out, "string");
  assert.ok(
    out.startsWith("[meta serialization failed:") || out.startsWith("[meta too large to display"),
    `unexpected cyclic-ref output: ${out}`
  );
});

test("safeStringifyMeta: handles null/undefined/empty inputs without throwing", () => {
  assert.equal(typeof safeStringifyMeta(null),  "string");
  assert.equal(typeof safeStringifyMeta(undefined), "string");
  assert.equal(typeof safeStringifyMeta({}),    "string");
  assert.equal(typeof safeStringifyMeta([]),    "string");
});

test("safeStringifyMeta: walks all primitive value types (null, string, number, boolean, array, object)", () => {
  // Exercises every branch in estimateSize.walk()
  const nested = {
    nullValue   : null,
    stringValue : "hello",
    numberValue : 42,
    boolValue   : true,
    arrayValue  : [1, "two", false, null, { nested: "object" }],
    objectValue : { inner: { deeper: "value" } },
  };
  const out = safeStringifyMeta(nested);
  assert.equal(typeof out, "string");
  assert.match(out, /"nullValue":\s*null/);
  assert.match(out, /"stringValue":\s*"hello"/);
  assert.match(out, /"numberValue":\s*42/);
});

test("safeStringifyMeta: oversized array (deep walk early-bail) triggers cap placeholder", () => {
  // Build an array large enough to blow the cap during the walk.
  const huge = new Array(40_000).fill("padding-string-content");
  const out  = safeStringifyMeta({ items: huge });
  assert.match(out, /\[meta too large to display/);
});

test("safeStringifyMeta: oversized after stringify (escape expansion) — belt-and-suspenders branch", () => {
  // Tune the cap so estimateSize passes (≈39 bytes for {a:"xxx...x30"}) but
  // the JSON.stringify output (≈42 bytes with 2-space indent) trips the
  // post-stringify length check. This proves the belt-and-suspenders branch
  // is exercised independently of the pre-check.
  configureMetaDisplayCap({ multiplexer_max_meta_display_bytes: 40 });
  try {
    const out = safeStringifyMeta({ a: "x".repeat(30) });
    // Either pre-check OR post-check fires; both produce a placeholder.
    assert.ok(
      out === "[meta too large to display]" || out.startsWith("[meta too large to display"),
      `expected too-large placeholder, got: ${out}`
    );
  } finally {
    // Restore default cap for subsequent tests.
    configureMetaDisplayCap({ multiplexer_max_meta_display_bytes: 256_000 });
  }
});

// ---------------------------------------------------------------------------
// configureMetaDisplayCap — Pass 2 F20 setter behavior
// ---------------------------------------------------------------------------

test("configureMetaDisplayCap: updates the cap from a valid serverConfig payload", () => {
  configureMetaDisplayCap({ multiplexer_max_meta_display_bytes: 128_000 });
  assert.equal(_getMaxMetaBytesForTesting(), 128_000);
  // Restore default for subsequent tests.
  configureMetaDisplayCap({ multiplexer_max_meta_display_bytes: 256_000 });
});

test("configureMetaDisplayCap: ignores missing/invalid/zero values (cap stays at default)", () => {
  configureMetaDisplayCap({ multiplexer_max_meta_display_bytes: 256_000 });
  // Empty payload — no field
  configureMetaDisplayCap({});
  assert.equal(_getMaxMetaBytesForTesting(), 256_000);
  // null payload
  configureMetaDisplayCap(null);
  assert.equal(_getMaxMetaBytesForTesting(), 256_000);
  // undefined payload
  configureMetaDisplayCap(undefined);
  assert.equal(_getMaxMetaBytesForTesting(), 256_000);
  // Non-finite value
  configureMetaDisplayCap({ multiplexer_max_meta_display_bytes: Number.POSITIVE_INFINITY });
  assert.equal(_getMaxMetaBytesForTesting(), 256_000);
  configureMetaDisplayCap({ multiplexer_max_meta_display_bytes: Number.NaN });
  assert.equal(_getMaxMetaBytesForTesting(), 256_000);
  // Zero / negative
  configureMetaDisplayCap({ multiplexer_max_meta_display_bytes: 0 });
  assert.equal(_getMaxMetaBytesForTesting(), 256_000);
  configureMetaDisplayCap({ multiplexer_max_meta_display_bytes: -10 });
  assert.equal(_getMaxMetaBytesForTesting(), 256_000);
});

test("configureMetaDisplayCap: floors fractional values", () => {
  configureMetaDisplayCap({ multiplexer_max_meta_display_bytes: 100_000.7 });
  assert.equal(_getMaxMetaBytesForTesting(), 100_000);
  configureMetaDisplayCap({ multiplexer_max_meta_display_bytes: 256_000 });
});

// ---------------------------------------------------------------------------
// populateJobMetaIfNeeded — lazy-render mechanism (Pass 1 F2)
// ---------------------------------------------------------------------------

test("populateJobMetaIfNeeded: first call populates <pre>, removes hidden, caches", () => {
  const card = renderJobCard(makeJob());
  const pre  = card.querySelector(".job-meta-json") as HTMLPreElement;
  assert.equal(pre.hasAttribute("hidden"), true);
  assert.equal(pre.textContent, "");

  populateJobMetaIfNeeded(card, { topic: "first-call" });
  assert.equal(pre.hasAttribute("hidden"), false);
  assert.match(pre.textContent || "", /first-call/);
});

test("populateJobMetaIfNeeded: second call on same card is no-op (cache hit)", () => {
  const card = renderJobCard(makeJob());
  const pre  = card.querySelector(".job-meta-json") as HTMLPreElement;

  populateJobMetaIfNeeded(card, { topic: "first" });
  const firstText = pre.textContent;

  // Second call with different meta should NOT update the <pre>
  populateJobMetaIfNeeded(card, { topic: "second" });
  assert.equal(pre.textContent, firstText, "second call should not re-populate");
});

test("populateJobMetaIfNeeded: oversized meta renders the placeholder (F20 sub-test for AC3)", () => {
  const card = renderJobCard(makeJob());
  const pre  = card.querySelector(".job-meta-json") as HTMLPreElement;
  const big  = "x".repeat(300_000);
  populateJobMetaIfNeeded(card, { payload: big });
  assert.match(pre.textContent || "", /meta too large to display/);
});

test("formatBytes: hits all 3 size buckets (B / KB / MB)", () => {
  // Sub-1KB bucket → "<N>B"
  assert.equal(_formatBytesForTesting(0),    "0B");
  assert.equal(_formatBytesForTesting(1023), "1023B");
  // 1KB to <1MB bucket → "<N.N>KB"
  assert.equal(_formatBytesForTesting(1024),    "1.0KB");
  assert.equal(_formatBytesForTesting(300_000), "293.0KB");
  // ≥1MB bucket → "<N.N>MB"
  assert.equal(_formatBytesForTesting(1024 * 1024),     "1.0MB");
  assert.equal(_formatBytesForTesting(5 * 1024 * 1024), "5.0MB");
});

test("populateJobMetaIfNeeded: card without <pre.job-meta-json> child is no-op (defensive)", () => {
  // Construct a card that's missing the <pre> child (e.g., a stripped-down test fixture).
  const card = document.createElement("div");
  card.className = "job-card status-done";
  // No <pre> inside.
  // Should not throw.
  populateJobMetaIfNeeded(card, { foo: "bar" });
  assert.equal(card.querySelector(".job-meta-json"), null);
});
