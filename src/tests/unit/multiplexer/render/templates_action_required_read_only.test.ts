// Multiplexer Phase 5 — actionRequiredReadOnly template tests.
// AC5 floor: ≥4 tests (one per response_type) per design doc § per-file floor.

import { test, before } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { renderActionRequiredReadOnly } from "../../../../fastapi_app/static/js/multiplexer/render/templates/actionRequiredReadOnly";
import type { ActionRequiredItem } from "../../../../fastapi_app/static/js/multiplexer/shared/types";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

function makeItem(over: Partial<ActionRequiredItem> = {}): ActionRequiredItem {
  return {
    id_hash       : "ar1",
    prompt        : "Proceed?",
    response_type : "yes_no",
    options       : [],
    expires_at    : Date.UTC(2026, 4, 5, 14, 7) + 30_000,
    state         : "pending",
    ...over,
  };
}

// ---------------------------------------------------------------------------
// Inertness invariants (D-A + Q-H)
// ---------------------------------------------------------------------------

test("actionRequiredReadOnly: all four inertness markers present (data-phase6-pending, aria-disabled, cursor, microcopy)", () => {
  const el = renderActionRequiredReadOnly(makeItem(), 30_000);
  assert.equal(el.getAttribute("data-phase6-pending"), "true");
  assert.equal(el.getAttribute("aria-disabled"), "true");
  assert.equal(el.style.cursor, "not-allowed");
  const microcopy = el.querySelector(".action-required-pending-notice");
  assert.notEqual(microcopy, null);
  assert.match(microcopy!.textContent ?? "", /next phase/i);
});

test("actionRequiredReadOnly: yes_no renders 2 readonly option chips", () => {
  const el = renderActionRequiredReadOnly(makeItem({ response_type: "yes_no" }), 5000);
  const opts = el.querySelectorAll(".action-required-option-readonly");
  assert.equal(opts.length, 2);
  assert.equal(opts[0]!.textContent, "Yes");
  assert.equal(opts[1]!.textContent, "No");
  assert.equal(el.querySelector(".action-required-response-type-badge")!.textContent, "yes/no");
});

test("actionRequiredReadOnly: multiple_choice renders N readonly chips (per options length)", () => {
  const el = renderActionRequiredReadOnly(
    makeItem({ response_type: "multiple_choice", options: ["red", "green", "blue", "alpha"] }),
    5000,
  );
  const opts = el.querySelectorAll(".action-required-option-readonly");
  assert.equal(opts.length, 4);
  assert.equal(opts[0]!.textContent, "red");
  assert.equal(el.querySelector(".action-required-response-type-badge")!.textContent, "multiple choice");
});

test("actionRequiredReadOnly: open_ended renders text-input placeholder (no option chips)", () => {
  const el = renderActionRequiredReadOnly(makeItem({ response_type: "open_ended" }), 5000);
  assert.equal(el.querySelectorAll(".action-required-option-readonly").length, 0);
  const placeholder = el.querySelector(".action-required-input-placeholder");
  assert.notEqual(placeholder, null);
  assert.match(placeholder!.textContent ?? "", /text input/i);
  assert.match(placeholder!.textContent ?? "", /Phase 6/i);
});

test("actionRequiredReadOnly: open_ended_batch renders batch text-input placeholder", () => {
  const el = renderActionRequiredReadOnly(makeItem({ response_type: "open_ended_batch" }), 5000);
  const placeholder = el.querySelector(".action-required-input-placeholder");
  assert.notEqual(placeholder, null);
  assert.match(placeholder!.textContent ?? "", /batch text input/i);
});

test("actionRequiredReadOnly: countdown text reflects formatCountdown(countdownMs) — pure formatter (D-H)", () => {
  const el = renderActionRequiredReadOnly(makeItem(), 5023);
  const cd = el.querySelector(".action-required-countdown");
  assert.match(cd!.textContent ?? "", /00:05/);
});

test("actionRequiredReadOnly: data-id-hash on root matches item.id_hash (F12)", () => {
  const el = renderActionRequiredReadOnly(makeItem({ id_hash: "ar_special" }), 0);
  assert.equal(el.getAttribute("data-id-hash"), "ar_special");
  assert.equal(el.getAttribute("data-testid"), "multiplexer-action-required");
});
