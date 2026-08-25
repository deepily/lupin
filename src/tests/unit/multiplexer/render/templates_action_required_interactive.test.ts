// Multiplexer Phase 6b — actionRequiredInteractive template tests.
// AC3 floor: ≥15 tests per design doc § AC3 sub-table.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import {
  renderActionRequiredInteractive,
  type ActionRequiredInteractiveHandlers,
} from "../../../../lupin_app/static/js/multiplexer/render/templates/actionRequiredInteractive";
import type {
  ActionRequiredItem,
  ActionRequiredResponse,
} from "../../../../lupin_app/static/js/multiplexer/shared/types";

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

function makeHandlers(): { handlers: ActionRequiredInteractiveHandlers; calls: ActionRequiredResponse[] } {
  const calls: ActionRequiredResponse[] = [];
  const handlers: ActionRequiredInteractiveHandlers = {
    onSubmit(response): void { calls.push(response); },
  };
  return { handlers, calls };
}

// ---------------------------------------------------------------------------
// Render shape (5 happy paths — one per response_type / multiSelect variant)
// ---------------------------------------------------------------------------

test("yes_no renders 2 buttons + carries data-id-hash + correct testid", () => {
  const el = renderActionRequiredInteractive(makeItem(), makeHandlers().handlers);
  assert.equal(el.getAttribute("data-id-hash"), "ar1");
  assert.equal(el.getAttribute("data-testid"), "multiplexer-action-required");
  const yes = el.querySelector(".action-required-btn-yes");
  const no  = el.querySelector(".action-required-btn-no");
  assert.notEqual(yes, null, "Yes button rendered");
  assert.notEqual(no,  null, "No button rendered");
  assert.equal(yes!.textContent, "Yes");
  assert.equal(no!.textContent,  "No");
});

test("multiple_choice + multiSelect:false renders radio group with N options", () => {
  const item = makeItem({ response_type: "multiple_choice", options: ["red", "green", "blue"], multiSelect: false });
  const el = renderActionRequiredInteractive(item, makeHandlers().handlers);
  const radios = el.querySelectorAll<HTMLInputElement>('input[type="radio"]');
  assert.equal(radios.length, 3);
  assert.equal(radios[0]!.value, "red");
  assert.equal(radios[1]!.value, "green");
  assert.equal(radios[2]!.value, "blue");
  assert.equal(el.querySelector(".action-required-options-radio")?.getAttribute("role"), "radiogroup");
});

test("multiple_choice + multiSelect:true renders checkbox group with N options", () => {
  const item = makeItem({ response_type: "multiple_choice", options: ["a", "b"], multiSelect: true });
  const el = renderActionRequiredInteractive(item, makeHandlers().handlers);
  const checkboxes = el.querySelectorAll<HTMLInputElement>('input[type="checkbox"]');
  assert.equal(checkboxes.length, 2);
  assert.equal(el.querySelector(".action-required-options-checkbox")?.getAttribute("role"), "group");
});

test("open_ended renders text input with placeholder + Submit", () => {
  const item = makeItem({ response_type: "open_ended", default: "type here" });
  const el = renderActionRequiredInteractive(item, makeHandlers().handlers);
  const input  = el.querySelector<HTMLInputElement>(".action-required-input");
  const submit = el.querySelector(".action-required-btn-submit");
  assert.notEqual(input,  null);
  assert.notEqual(submit, null);
  assert.equal(input!.getAttribute("placeholder"), "type here");
});

test("open_ended_batch renders one input per option (treated as headers)", () => {
  const item = makeItem({ response_type: "open_ended_batch", options: ["Topic", "Budget", "Audience"] });
  const el = renderActionRequiredInteractive(item, makeHandlers().handlers);
  const inputs = el.querySelectorAll<HTMLInputElement>(".action-required-batch-input");
  assert.equal(inputs.length, 3);
  assert.equal(inputs[0]!.dataset.batchHeader, "Topic");
  assert.equal(inputs[1]!.dataset.batchHeader, "Budget");
  assert.equal(inputs[2]!.dataset.batchHeader, "Audience");
  assert.ok( el.querySelector(".action-required-btn-submit-all") !== null );
});

// ---------------------------------------------------------------------------
// Click dispatch (5 cases — one per response_type / multiSelect variant)
// ---------------------------------------------------------------------------

test("yes_no Yes click dispatches onSubmit('yes')", () => {
  const { handlers, calls } = makeHandlers();
  const el = renderActionRequiredInteractive(makeItem(), handlers);
  el.querySelector<HTMLButtonElement>(".action-required-btn-yes")!.click();
  assert.deepEqual(calls, ["yes"]);
});

test("yes_no No click dispatches onSubmit('no')", () => {
  const { handlers, calls } = makeHandlers();
  const el = renderActionRequiredInteractive(makeItem(), handlers);
  el.querySelector<HTMLButtonElement>(".action-required-btn-no")!.click();
  assert.deepEqual(calls, ["no"]);
});

test("multiple_choice radio: select + Submit dispatches onSubmit(string)", () => {
  const { handlers, calls } = makeHandlers();
  const item = makeItem({ response_type: "multiple_choice", options: ["red", "green", "blue"] });
  const el = renderActionRequiredInteractive(item, handlers);
  el.querySelectorAll<HTMLInputElement>('input[type="radio"]')[1]!.checked = true;
  el.querySelector<HTMLButtonElement>(".action-required-btn-submit")!.click();
  assert.deepEqual(calls, ["green"]);
});

test("multiple_choice checkbox: select N + Submit dispatches onSubmit(array)", () => {
  const { handlers, calls } = makeHandlers();
  const item = makeItem({ response_type: "multiple_choice", options: ["a", "b", "c"], multiSelect: true });
  const el = renderActionRequiredInteractive(item, handlers);
  const cb = el.querySelectorAll<HTMLInputElement>('input[type="checkbox"]');
  cb[0]!.checked = true;
  cb[2]!.checked = true;
  el.querySelector<HTMLButtonElement>(".action-required-btn-submit")!.click();
  assert.deepEqual(calls, [["a", "c"]]);
});

test("open_ended Enter key on input submits text value", () => {
  const { handlers, calls } = makeHandlers();
  const el = renderActionRequiredInteractive(makeItem({ response_type: "open_ended" }), handlers);
  const input = el.querySelector<HTMLInputElement>(".action-required-input")!;
  input.value = "hello world";
  input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
  assert.deepEqual(calls, ["hello world"]);
});

test("open_ended Submit click also submits text value", () => {
  const { handlers, calls } = makeHandlers();
  const el = renderActionRequiredInteractive(makeItem({ response_type: "open_ended" }), handlers);
  el.querySelector<HTMLInputElement>(".action-required-input")!.value = "click submit";
  el.querySelector<HTMLButtonElement>(".action-required-btn-submit")!.click();
  assert.deepEqual(calls, ["click submit"]);
});

test("open_ended_batch Submit-All dispatches onSubmit({header: value, ...})", () => {
  const { handlers, calls } = makeHandlers();
  const item = makeItem({ response_type: "open_ended_batch", options: ["Topic", "Budget"] });
  const el = renderActionRequiredInteractive(item, handlers);
  const inputs = el.querySelectorAll<HTMLInputElement>(".action-required-batch-input");
  inputs[0]!.value = "AI";
  inputs[1]!.value = "100";
  el.querySelector<HTMLButtonElement>(".action-required-btn-submit-all")!.click();
  assert.deepEqual(calls, [{ Topic: "AI", Budget: "100" }]);
});

// ---------------------------------------------------------------------------
// Edge cases + invariants
// ---------------------------------------------------------------------------

test("multiple_choice radio: Submit with no selection is no-op (no onSubmit call)", () => {
  const { handlers, calls } = makeHandlers();
  const item = makeItem({ response_type: "multiple_choice", options: ["red", "green"] });
  const el = renderActionRequiredInteractive(item, handlers);
  el.querySelector<HTMLButtonElement>(".action-required-btn-submit")!.click();
  assert.deepEqual(calls, []);
});

test("multiple_choice checkbox: Submit with no selection dispatches onSubmit([])", () => {
  const { handlers, calls } = makeHandlers();
  const item = makeItem({ response_type: "multiple_choice", options: ["a", "b"], multiSelect: true });
  const el = renderActionRequiredInteractive(item, handlers);
  el.querySelector<HTMLButtonElement>(".action-required-btn-submit")!.click();
  assert.deepEqual(calls, [[]]);
});

test("multiple_choice with multiSelect undefined defaults to radio (single-select)", () => {
  const { handlers, calls } = makeHandlers();
  const item = makeItem({ response_type: "multiple_choice", options: ["red", "blue"] });
  // multiSelect omitted → undefined → falls to radio path.
  const el = renderActionRequiredInteractive(item, handlers);
  assert.ok( el.querySelector(".action-required-options-radio") !== null );
  assert.ok( el.querySelector(".action-required-options-checkbox") === null );
  el.querySelector<HTMLInputElement>('input[type="radio"]')!.checked = true;
  el.querySelector<HTMLButtonElement>(".action-required-btn-submit")!.click();
  assert.deepEqual(calls, ["red"]);
});

test("open_ended_batch with empty options renders zero rows + Submit-All sends empty record", () => {
  const { handlers, calls } = makeHandlers();
  const item = makeItem({ response_type: "open_ended_batch", options: [] });
  const el = renderActionRequiredInteractive(item, handlers);
  assert.equal(el.querySelectorAll(".action-required-batch-input").length, 0);
  el.querySelector<HTMLButtonElement>(".action-required-btn-submit-all")!.click();
  assert.deepEqual(calls, [{}]);
});

test("unknown response_type throws Error (schema-drift defense)", () => {
  const item = { ...makeItem(), response_type: "BOGUS" as ActionRequiredItem["response_type"] };
  assert.throws(
    () => renderActionRequiredInteractive(item, makeHandlers().handlers),
    /Unknown response_type: BOGUS/,
  );
});

test("multi-instance independence: two widgets dispatch to their own handlers", () => {
  const a = makeHandlers();
  const b = makeHandlers();
  const elA = renderActionRequiredInteractive(makeItem({ id_hash: "ar1" }), a.handlers);
  const elB = renderActionRequiredInteractive(makeItem({ id_hash: "ar2" }), b.handlers);
  elA.querySelector<HTMLButtonElement>(".action-required-btn-yes")!.click();
  elB.querySelector<HTMLButtonElement>(".action-required-btn-no")!.click();
  assert.deepEqual(a.calls, ["yes"]);
  assert.deepEqual(b.calls, ["no"]);
});

test("prompt renders inside .action-required-prompt across all response_types", () => {
  for (const rt of ["yes_no", "multiple_choice", "open_ended", "open_ended_batch"] as const) {
    const item = makeItem({ response_type: rt, prompt: `Q-${rt}`, options: rt === "multiple_choice" || rt === "open_ended_batch" ? ["x", "y"] : [] });
    const el = renderActionRequiredInteractive(item, makeHandlers().handlers);
    const prompt = el.querySelector(".action-required-prompt");
    assert.notEqual(prompt, null, `prompt rendered for ${rt}`);
    assert.equal(prompt!.textContent, `Q-${rt}`, `prompt text matches for ${rt}`);
  }
});

test("widget root carries .action-required-widget-interactive (distinct from read-only Phase 5)", () => {
  const el = renderActionRequiredInteractive(makeItem(), makeHandlers().handlers);
  assert.ok(el.classList.contains("action-required-widget"),             "shared base class");
  assert.ok(el.classList.contains("action-required-widget-interactive"), "Phase 6b distinguishing class");
});

// ---------------------------------------------------------------------------
// AC2e safe-write invariant (Pass 2 a1) — grep ban on unsafe HTML write sinks
// ---------------------------------------------------------------------------

test("AC2e: source file contains zero .innerHTML= / rawHTML( / .outerHTML= sinks", () => {
  const src = readFileSync(
    "src/lupin_app/static/js/multiplexer/render/templates/actionRequiredInteractive.ts",
    "utf8",
  );
  // Strip all comments (single-line + multi-line) so doc-comments mentioning the banned tokens don't trigger.
  const stripped = src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\/\/.*$/gm, "");
  const banned = [
    /\.innerHTML\s*=/,
    /\brawHTML\s*\(/,
    /\.outerHTML\s*=/,
  ];
  for (const re of banned) {
    assert.equal(re.test(stripped), false, `AC2e violation: pattern ${re} found in actionRequiredInteractive.ts`);
  }
});
