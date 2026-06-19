// Multiplexer Phase 6a — jobBucket template tests.
// AC4 floor: ≥6 tests per design § Verification matrix.
// Includes Pass 2 F30 keyboard activation sub-test + aria-expanded reflection.

import { test, before } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { renderJobBucket } from "../../../../lupin_app/static/js/multiplexer/render/templates/jobBucket";
import type { Job, JobBucket } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    id_hash      : "job-1",
    job_type     : "DeepResearchJob",
    status       : "running",
    created_at   : Date.UTC(2026, 4, 5, 14, 0),
    completed_at : Date.UTC(2026, 4, 5, 14, 5),
    meta         : {},
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Default-expansion: todo + running visible; done + dead + history collapsed
// ---------------------------------------------------------------------------

test("renderJobBucket: todo bucket starts EXPANDED (aria-expanded='true', no .collapsed on cards)", () => {
  const el     = renderJobBucket("todo", [ makeJob({ id_hash: "j1" }) ]);
  const header = el.querySelector(".jobs-bucket-header");
  const cards  = el.querySelector(".jobs-bucket-cards");
  assert.equal(header?.getAttribute("aria-expanded"), "true");
  assert.equal(cards?.classList.contains("collapsed"), false);
  assert.equal(el.querySelector(".jobs-bucket-toggle")?.textContent, "▼");
});

test("renderJobBucket: running bucket starts EXPANDED", () => {
  const el     = renderJobBucket("running", [ makeJob({ id_hash: "j1" }) ]);
  const header = el.querySelector(".jobs-bucket-header");
  assert.equal(header?.getAttribute("aria-expanded"), "true");
});

test("renderJobBucket: done bucket starts COLLAPSED (aria-expanded='false', .collapsed on cards)", () => {
  const el     = renderJobBucket("done", [ makeJob({ id_hash: "j1" }) ]);
  const header = el.querySelector(".jobs-bucket-header");
  const cards  = el.querySelector(".jobs-bucket-cards");
  assert.equal(header?.getAttribute("aria-expanded"), "false");
  assert.equal(cards?.classList.contains("collapsed"), true);
  assert.equal(el.querySelector(".jobs-bucket-toggle")?.textContent, "▶");
});

test("renderJobBucket: dead + history buckets start COLLAPSED", () => {
  for (const bucket of ["dead", "history"] as JobBucket[]) {
    const el     = renderJobBucket(bucket, [ makeJob({ id_hash: `j-${bucket}` }) ]);
    const header = el.querySelector(".jobs-bucket-header");
    assert.equal(header?.getAttribute("aria-expanded"), "false", `${bucket} should start collapsed`);
  }
});

// ---------------------------------------------------------------------------
// Section structure + count + accessibility attrs
// ---------------------------------------------------------------------------

test("renderJobBucket: outer is <section>, carries data-bucket + class .jobs-bucket-${name}", () => {
  const el = renderJobBucket("running", []);
  assert.equal(el.tagName, "SECTION");
  assert.equal(el.getAttribute("data-bucket"), "running");
  assert.ok(el.classList.contains("jobs-bucket"));
  assert.ok(el.classList.contains("jobs-bucket-running"));
});

test("renderJobBucket: header has role='button', tabindex='0', aria-controls references cards container id", () => {
  const el     = renderJobBucket("done", [ makeJob({ id_hash: "j1" }) ]);
  const header = el.querySelector(".jobs-bucket-header");
  const cards  = el.querySelector(".jobs-bucket-cards");
  assert.equal(header?.getAttribute("role"),      "button");
  assert.equal(header?.getAttribute("tabindex"),  "0");
  assert.equal(header?.getAttribute("aria-controls"), "bucket-done-content");
  assert.equal(cards?.id, "bucket-done-content");
});

test("renderJobBucket: count display reflects jobs.length", () => {
  const jobs = [
    makeJob({ id_hash: "j1" }),
    makeJob({ id_hash: "j2" }),
    makeJob({ id_hash: "j3" }),
  ];
  const el    = renderJobBucket("running", jobs);
  const count = el.querySelector(".jobs-bucket-count");
  assert.equal(count?.textContent, "(3)");
});

test("renderJobBucket: empty bucket renders per-bucket 'No <name> jobs.' div (Q-A1 strict)", () => {
  const el    = renderJobBucket("history", []);
  const empty = el.querySelector(".jobs-bucket-empty");
  assert.notEqual(empty, null);
  assert.equal(empty?.textContent?.trim(), "No history jobs.");
  // No cards container is rendered for empty buckets.
  assert.equal(el.querySelector(".jobs-bucket-cards"), null);
});

test("renderJobBucket: non-empty bucket populates cards via keyedListMerge keyed by data-id-hash (F12)", () => {
  const jobs = [
    makeJob({ id_hash: "key-a" }),
    makeJob({ id_hash: "key-b" }),
  ];
  const el = renderJobBucket("todo", jobs);
  const cardEls = el.querySelectorAll(".jobs-bucket-cards .job-card");
  assert.equal(cardEls.length, 2);
  assert.equal(cardEls[0]!.getAttribute("data-id-hash"), "key-a");
  assert.equal(cardEls[1]!.getAttribute("data-id-hash"), "key-b");
});

// ---------------------------------------------------------------------------
// Click + keyboard handlers (Pass 2 F30)
// ---------------------------------------------------------------------------

test("renderJobBucket: header click toggles .collapsed on cards container + flips aria-expanded + chevron", () => {
  const el     = renderJobBucket("todo", [ makeJob({ id_hash: "j1" }) ]);
  const header = el.querySelector(".jobs-bucket-header") as HTMLElement;
  const cards  = el.querySelector(".jobs-bucket-cards") as HTMLElement;
  const toggle = el.querySelector(".jobs-bucket-toggle") as HTMLElement;

  // Initial: expanded
  assert.equal(header.getAttribute("aria-expanded"), "true");
  assert.equal(cards.classList.contains("collapsed"), false);
  assert.equal(toggle.textContent, "▼");

  // Click → collapse
  header.click();
  assert.equal(header.getAttribute("aria-expanded"), "false");
  assert.equal(cards.classList.contains("collapsed"), true);
  assert.equal(toggle.textContent, "▶");

  // Click → expand again
  header.click();
  assert.equal(header.getAttribute("aria-expanded"), "true");
  assert.equal(cards.classList.contains("collapsed"), false);
  assert.equal(toggle.textContent, "▼");
});

test("renderJobBucket: Enter keydown toggles bucket (F30 — WAI-ARIA contract for role='button')", () => {
  const el     = renderJobBucket("todo", [ makeJob({ id_hash: "j1" }) ]);
  const header = el.querySelector(".jobs-bucket-header") as HTMLElement;

  assert.equal(header.getAttribute("aria-expanded"), "true");

  const evt = new KeyboardEvent("keydown", { key: "Enter", bubbles: true });
  header.dispatchEvent(evt);
  assert.equal(header.getAttribute("aria-expanded"), "false");
});

test("renderJobBucket: Space keydown toggles bucket AND preventDefault is called (no page scroll)", () => {
  const el     = renderJobBucket("todo", [ makeJob({ id_hash: "j1" }) ]);
  const header = el.querySelector(".jobs-bucket-header") as HTMLElement;

  assert.equal(header.getAttribute("aria-expanded"), "true");

  let prevented = false;
  // Patch preventDefault to track invocation.
  const evt = new KeyboardEvent("keydown", { key: " ", bubbles: true, cancelable: true });
  const origPreventDefault = evt.preventDefault.bind(evt);
  evt.preventDefault = () => { prevented = true; origPreventDefault(); };

  header.dispatchEvent(evt);
  assert.equal(header.getAttribute("aria-expanded"), "false");
  assert.equal(prevented, true, "preventDefault must fire on Space to prevent page scroll");
});

test("renderJobBucket: Tab key does NOT toggle bucket (only Enter/Space activate role='button')", () => {
  const el     = renderJobBucket("todo", [ makeJob({ id_hash: "j1" }) ]);
  const header = el.querySelector(".jobs-bucket-header") as HTMLElement;

  assert.equal(header.getAttribute("aria-expanded"), "true");

  const evt = new KeyboardEvent("keydown", { key: "Tab", bubbles: true });
  header.dispatchEvent(evt);
  // Tab moves focus but does NOT toggle.
  assert.equal(header.getAttribute("aria-expanded"), "true", "Tab should not toggle the bucket");
});

test("renderJobBucket: aria-expanded reflects state and updates on every toggle (F30)", () => {
  const el     = renderJobBucket("done", [ makeJob({ id_hash: "j1" }) ]);
  const header = el.querySelector(".jobs-bucket-header") as HTMLElement;

  // Initial collapsed
  assert.equal(header.getAttribute("aria-expanded"), "false");
  // Toggle 4 times — must alternate every time
  header.click();
  assert.equal(header.getAttribute("aria-expanded"), "true");
  header.click();
  assert.equal(header.getAttribute("aria-expanded"), "false");
  header.click();
  assert.equal(header.getAttribute("aria-expanded"), "true");
  header.click();
  assert.equal(header.getAttribute("aria-expanded"), "false");
});

test("renderJobBucket: empty bucket header click flips aria-expanded but no cards container exists", () => {
  // toggleBucket() must handle the no-cards-container branch (cards === null).
  const el     = renderJobBucket("history", []);
  const header = el.querySelector(".jobs-bucket-header") as HTMLElement;
  assert.equal(el.querySelector(".jobs-bucket-cards"), null);

  // Initial: collapsed (history starts collapsed)
  assert.equal(header.getAttribute("aria-expanded"), "false");
  // Click should not throw despite no cards container; aria-expanded flips.
  header.click();
  assert.equal(header.getAttribute("aria-expanded"), "true");
});
