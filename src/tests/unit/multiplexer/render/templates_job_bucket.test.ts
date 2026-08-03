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

// ---------------------------------------------------------------------------
// W2 — per-bucket delete-all 🗑 button (plan 04 §W2)
// ---------------------------------------------------------------------------

test("renderJobBucket: every bucket header carries exactly one .queue-delete-all-btn[data-bucket]=🗑, just before the chevron (W2)", () => {
  for (const bucket of ["todo", "running", "done", "dead", "history"] as JobBucket[]) {
    const el   = renderJobBucket(bucket, [ makeJob({ id_hash: `j-${bucket}` }) ]);
    const btns = el.querySelectorAll(".jobs-bucket-header .queue-delete-all-btn");
    assert.equal(btns.length, 1, `${bucket} should have exactly one delete-all button`);
    const btn = btns[0] as HTMLButtonElement;
    assert.equal(btn.getAttribute("data-bucket"), bucket);
    assert.equal(btn.type, "button");
    assert.equal(btn.textContent, "🗑");
    const toggle = el.querySelector(".jobs-bucket-toggle") as HTMLElement;
    assert.equal(btn.nextElementSibling, toggle, `${bucket}: 🗑 sits immediately before the chevron`);
  }
});

test("renderJobBucket: empty bucket STILL renders the delete-all 🗑 (W2 — it confirms '0 jobs')", () => {
  const el  = renderJobBucket("done", []);
  const btn = el.querySelector(".queue-delete-all-btn");
  assert.notEqual(btn, null, "delete-all present even on an empty bucket");
});

test("renderJobBucket: clicking the delete-all 🗑 does NOT toggle the bucket (W2 click target-guard)", () => {
  const el     = renderJobBucket("todo", [ makeJob({ id_hash: "j1" }) ]);
  const header = el.querySelector(".jobs-bucket-header") as HTMLElement;
  const btn    = el.querySelector(".queue-delete-all-btn") as HTMLButtonElement;
  const cards  = el.querySelector(".jobs-bucket-cards") as HTMLElement;

  assert.equal(header.getAttribute("aria-expanded"), "true");
  btn.click();   // bubbles to the header listener, which target-guards on the button
  assert.equal(header.getAttribute("aria-expanded"), "true", "delete-all click must not collapse the bucket");
  assert.equal(cards.classList.contains("collapsed"), false, "cards stay expanded");
});

test("renderJobBucket: Enter/Space keydown ON the delete-all 🗑 does NOT toggle the bucket (W2 keyboard target-guard)", () => {
  const el     = renderJobBucket("todo", [ makeJob({ id_hash: "j1" }) ]);
  const header = el.querySelector(".jobs-bucket-header") as HTMLElement;
  const btn    = el.querySelector(".queue-delete-all-btn") as HTMLButtonElement;

  assert.equal(header.getAttribute("aria-expanded"), "true");
  // A keydown originating on the button bubbles to the header keydown listener;
  // the target-guard leaves the native <button> to own the key (no bucket toggle).
  btn.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
  btn.dispatchEvent(new KeyboardEvent("keydown", { key: " ", bubbles: true }));
  assert.equal(header.getAttribute("aria-expanded"), "true", "a key on 🗑 must not toggle the bucket");
});

// ---------------------------------------------------------------------------
// W3 — history time-window <select> (plan 04 §W3)
// ---------------------------------------------------------------------------

test("renderJobBucket: history header renders a .history-time-select with the 5 legacy option values (W3)", () => {
  const el     = renderJobBucket("history", [], { historyWindowDays: 30, historyLoadedCount: 0, historyTotalCount: 0 });
  const select = el.querySelector(".jobs-bucket-header .history-time-select") as HTMLSelectElement;
  assert.notEqual(select, null, "history header has a time-window select");
  const values = Array.from(select.querySelectorAll("option")).map(o => (o as HTMLOptionElement).value);
  assert.deepEqual(values, ["1", "7", "14", "30", "all"]);
});

test("renderJobBucket: history select reflects the current window (30 → '30'; undefined → 'all') (W3)", () => {
  const el30 = renderJobBucket("history", [], { historyWindowDays: 30, historyLoadedCount: 0, historyTotalCount: 0 });
  assert.equal((el30.querySelector(".history-time-select") as HTMLSelectElement).value, "30");
  const elAll = renderJobBucket("history", [], { historyWindowDays: undefined, historyLoadedCount: 0, historyTotalCount: 0 });
  assert.equal((elAll.querySelector(".history-time-select") as HTMLSelectElement).value, "all");
});

test("renderJobBucket: non-history buckets render NO time-window select (W3)", () => {
  for (const bucket of ["todo", "running", "done", "dead"] as JobBucket[]) {
    const el = renderJobBucket(bucket, [ makeJob({ id_hash: `j-${bucket}` }) ]);
    assert.equal(el.querySelector(".history-time-select"), null, `${bucket} must not render a time-window select`);
  }
});

test("renderJobBucket: history count badge reflects total when provided; falls back to loaded length otherwise (W3)", () => {
  const withTotal = renderJobBucket("history", [ makeJob({ id_hash: "h1" }) ], { historyTotalCount: 42, historyLoadedCount: 1, historyWindowDays: 30 });
  assert.equal(withTotal.querySelector(".jobs-bucket-count")?.textContent, "(42)");
  const noOpts = renderJobBucket("history", [ makeJob({ id_hash: "h1" }) ]);   // no historyTotalCount → base count
  assert.equal(noOpts.querySelector(".jobs-bucket-count")?.textContent, "(1)");
});

test("renderJobBucket: clicking the history time-window select does NOT toggle the bucket (W3 target-guard)", () => {
  const el     = renderJobBucket("history", [], { historyWindowDays: 30, historyLoadedCount: 0, historyTotalCount: 0 });
  const header = el.querySelector(".jobs-bucket-header") as HTMLElement;
  const select = el.querySelector(".history-time-select") as HTMLSelectElement;
  assert.equal(header.getAttribute("aria-expanded"), "false");   // history starts collapsed
  select.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  assert.equal(header.getAttribute("aria-expanded"), "false", "a click on the select must not toggle the bucket");
});

// ---------------------------------------------------------------------------
// W4 — history Load-More affordance (plan 04 §W4)
// ---------------------------------------------------------------------------

test("renderJobBucket: history renders Load-More iff loaded < total; absent when caught up / unset; never on live buckets (W4)", () => {
  const gated = renderJobBucket("history", [ makeJob({ id_hash: "h1" }) ], { historyLoadedCount: 1, historyTotalCount: 5, historyWindowDays: 30 });
  assert.notEqual(gated.querySelector(".history-load-more"), null, "present when loaded < total");

  const caught = renderJobBucket("history", [ makeJob({ id_hash: "h1" }) ], { historyLoadedCount: 5, historyTotalCount: 5, historyWindowDays: 30 });
  assert.equal(caught.querySelector(".history-load-more"), null, "absent when caught up (loaded === total)");

  const bare = renderJobBucket("history", []);   // no counts → 0 < 0 → absent
  assert.equal(bare.querySelector(".history-load-more"), null, "absent when counts unset");

  const live = renderJobBucket("done", [ makeJob({ id_hash: "d1" }) ], { historyLoadedCount: 1, historyTotalCount: 5 });
  assert.equal(live.querySelector(".history-load-more"), null, "never on a live bucket");
});
