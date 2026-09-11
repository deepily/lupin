// Multiplexer Phase 6b — actionRequiredInteractive template tests.
// AC3 floor: ≥15 tests per design doc § AC3 sub-table.
//
// P0 5ebd2aff step 2: multiple_choice and open_ended_batch are driven from the REAL
// response_options payload (fixtures/action_required_questions_payload.json, built by the
// server's own builders), never from a hand-typed option list — a hand-typed list is how this
// client came to believe response_options was string[].

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import {
  renderActionRequiredInteractive,
  type ActionRequiredInteractiveHandlers,
  type MultipleChoiceStep,
} from "../../../../lupin_app/static/js/multiplexer/render/templates/actionRequiredInteractive";
import { parseResponseQuestions } from "../../../../lupin_app/static/js/multiplexer/stores/responseQuestions";
import type {
  ActionRequiredItem,
  ActionRequiredResponse,
} from "../../../../lupin_app/static/js/multiplexer/shared/types";
import { QUESTIONS_PAYLOAD } from "../fixtures/actionRequiredQuestionsPayload";

const MC_QUESTIONS    = parseResponseQuestions(QUESTIONS_PAYLOAD.multiple_choice.response_options);
const BATCH_QUESTIONS = parseResponseQuestions(QUESTIONS_PAYLOAD.open_ended_batch.response_options);

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
    questions     : [],
    expires_at    : Date.UTC(2026, 4, 5, 14, 7) + 30_000,
    timeout_seconds : 30,
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

// 360de81b — handlers that also record every stepper report.
function makeStepHandlers(): { handlers: ActionRequiredInteractiveHandlers; calls: ActionRequiredResponse[]; steps: MultipleChoiceStep[] } {
  const calls: ActionRequiredResponse[] = [];
  const steps: MultipleChoiceStep[] = [];
  const handlers: ActionRequiredInteractiveHandlers = {
    onSubmit(response): void { calls.push(response); },
    onStep(step): void { steps.push(step); },
  };
  return { handlers, calls, steps };
}

function tick(el: HTMLElement, label: string): void {
  el.querySelector<HTMLInputElement>(`input[value="${label}"]`)!.checked = true;
}

// Selecting through the DOM event, as a click does, so the stepper's change listener runs.
function choose(el: HTMLElement, label: string): void {
  const input = el.querySelector<HTMLInputElement>(`input[value="${label}"]`)!;
  input.checked = true;
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

function button(el: HTMLElement, cls: string): HTMLButtonElement | null {
  return el.querySelector<HTMLButtonElement>(`.${cls}`);
}

function indicator(el: HTMLElement): string {
  return el.querySelector(".action-required-question-indicator")!.textContent ?? "";
}

function mcCard(handlers: ActionRequiredInteractiveHandlers, step?: MultipleChoiceStep): HTMLElement {
  return renderActionRequiredInteractive(makeItem({ response_type: "multiple_choice", questions: MC_QUESTIONS }), handlers, step);
}

// ---------------------------------------------------------------------------
// Render shape
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

// ---------------------------------------------------------------------------
// 360de81b — multiple_choice walks ONE question at a time, Back and Next (legacy renderMultipleChoiceUI
// :23519, navigateMultipleChoice :23729). Button labels typed from legacy :23599-23624.
// ---------------------------------------------------------------------------

test("360de81b: multiple_choice (real payload) shows ONE question at a time — 'Question 1 of 2', header, text, radios, no Back, 'Next Question →', no Submit", () => {
  const el = mcCard(makeHandlers().handlers);
  const blocks = el.querySelectorAll<HTMLElement>(".action-required-question");
  assert.equal(blocks.length, 1, "one question on screen, not the whole list");
  assert.equal(indicator(el), "Question 1 of 2");
  assert.equal(blocks[0]!.querySelector(".action-required-question-header")!.textContent, "Database");
  assert.equal(blocks[0]!.querySelector(".action-required-question-text")!.textContent, "Which database should the service use?");

  const radios = blocks[0]!.querySelectorAll<HTMLInputElement>('input[type="radio"]');
  assert.deepEqual(Array.from(radios, r => r.value), ["PostgreSQL", "SQLite"]);
  assert.equal(blocks[0]!.querySelector('input[type="checkbox"]'), null, "a single-select question renders no checkbox");
  assert.equal(blocks[0]!.querySelector(".action-required-options-radio")?.getAttribute("role"), "radiogroup");
  assert.equal(blocks[0]!.querySelector(".action-required-multi-hint"), null, "no multi-select hint on a single-select question");
  assert.deepEqual(
    Array.from(blocks[0]!.querySelectorAll(".action-required-option-description"), d => d.textContent),
    ["Relational, already deployed", "File-backed, no server"],
  );

  assert.equal(button(el, "action-required-btn-back"), null, "Back is hidden on the first question");
  assert.equal(button(el, "action-required-btn-next")!.textContent, "Next Question →");
  assert.equal(button(el, "action-required-btn-submit"), null, "Submit only on the last question");
});

test("360de81b: Next saves the answer and shows question 2 — checkboxes, '(Select all that apply)', Back, 'Submit All ✓', no Next; onStep reports the new position and the saved answer", () => {
  const { handlers, steps, calls } = makeStepHandlers();
  const el = mcCard(handlers);
  choose(el, "PostgreSQL");
  button(el, "action-required-btn-next")!.click();

  assert.equal(indicator(el), "Question 2 of 2");
  assert.equal(el.querySelectorAll(".action-required-question").length, 1);
  assert.equal(el.querySelector(".action-required-question-header")!.textContent, "Features");
  const boxes = el.querySelectorAll<HTMLInputElement>('input[type="checkbox"]');
  assert.deepEqual(Array.from(boxes, b => b.value), ["Search", "Export", "Audit log"]);
  assert.equal(el.querySelector(".action-required-options-checkbox")?.getAttribute("role"), "group");
  assert.equal(el.querySelector(".action-required-multi-hint")!.textContent, "(Select all that apply)");
  assert.equal(button(el, "action-required-btn-back")!.textContent, "← Back");
  assert.equal(button(el, "action-required-btn-submit")!.textContent, "Submit All ✓");
  assert.equal(button(el, "action-required-btn-next"), null);

  assert.deepEqual(steps, [{ index: 1, answers: { Database: "PostgreSQL" } }]);
  assert.deepEqual(calls, [], "Next never submits");
});

test("360de81b: Next on an unanswered question stays put, marks it invalid and reports no step; choosing an option clears the mark and focuses Next (legacy :23798-23807)", () => {
  const { handlers, steps } = makeStepHandlers();
  const el = mcCard(handlers);
  document.body.appendChild(el);
  button(el, "action-required-btn-next")!.click();
  assert.equal(indicator(el), "Question 1 of 2");
  assert.equal(el.querySelector(".action-required-question")!.classList.contains("invalid"), true);
  assert.deepEqual(steps, []);

  choose(el, "SQLite");
  assert.equal(el.querySelector(".action-required-question")!.classList.contains("invalid"), false);
  assert.equal(document.activeElement, button(el, "action-required-btn-next"), "the primary action takes focus so Enter moves on");
  el.remove();
});

test("360de81b: Back keeps the answers — question 2's ticks are saved on the way back, question 1 still shows its choice, and Next again restores the ticks", () => {
  const { handlers, steps } = makeStepHandlers();
  const el = mcCard(handlers);
  choose(el, "PostgreSQL");
  button(el, "action-required-btn-next")!.click();
  choose(el, "Search");
  choose(el, "Audit log");
  button(el, "action-required-btn-back")!.click();

  assert.equal(indicator(el), "Question 1 of 2");
  assert.equal(el.querySelector<HTMLInputElement>('input[value="PostgreSQL"]')!.checked, true);
  assert.equal(el.querySelector<HTMLInputElement>('input[value="SQLite"]')!.checked, false);
  assert.deepEqual(steps.at(-1), { index: 0, answers: { Database: "PostgreSQL", Features: ["Search", "Audit log"] } });

  button(el, "action-required-btn-next")!.click();
  assert.deepEqual(
    Array.from(el.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'), b => [b.value, b.checked]),
    [["Search", true], ["Export", false], ["Audit log", true]],
  );
});

test("360de81b: Back from an unanswered question steps back without an invalid mark and without erasing what was saved before", () => {
  const { handlers, steps } = makeStepHandlers();
  const el = mcCard(handlers, { index: 1, answers: { Database: "SQLite", Features: ["Export"] } });
  for (const box of Array.from(el.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'))) box.checked = false;
  button(el, "action-required-btn-back")!.click();
  assert.equal(indicator(el), "Question 1 of 2");
  assert.equal(el.querySelector(".action-required-question")!.classList.contains("invalid"), false);
  assert.deepEqual(steps, [{ index: 0, answers: { Database: "SQLite", Features: ["Export"] } }]);
});

test("360de81b: Submit All on the last question sends legacy's { answers } — wire unchanged — after reporting the final step; nothing ticked sends nothing and marks it invalid", () => {
  const { handlers, calls, steps } = makeStepHandlers();
  const el = mcCard(handlers);
  choose(el, "PostgreSQL");
  button(el, "action-required-btn-next")!.click();
  button(el, "action-required-btn-submit")!.click();
  assert.deepEqual(calls, []);
  assert.equal(el.querySelector(".action-required-question")!.classList.contains("invalid"), true);

  tick(el, "Search");
  tick(el, "Audit log");
  button(el, "action-required-btn-submit")!.click();
  assert.deepEqual(calls, [QUESTIONS_PAYLOAD.multiple_choice.answers]);
  assert.equal(JSON.stringify(calls[0]), QUESTIONS_PAYLOAD.multiple_choice.wire_value, "byte-identical to what legacy sends");
  assert.deepEqual(steps.at(-1), { index: 1, answers: QUESTIONS_PAYLOAD.multiple_choice.answers.answers });
});

test("360de81b: a one-question card reads 'Question 1 of 1' with no Back, no Next and a plain 'Submit'", () => {
  const { handlers, calls } = makeHandlers();
  const item = makeItem({
    response_type : "multiple_choice",
    questions     : [MC_QUESTIONS[0]!],
  });
  const el = renderActionRequiredInteractive(item, handlers);
  assert.equal(indicator(el), "Question 1 of 1");
  assert.equal(button(el, "action-required-btn-back"), null);
  assert.equal(button(el, "action-required-btn-next"), null);
  assert.equal(button(el, "action-required-btn-submit")!.textContent, "Submit");
  tick(el, "SQLite");
  button(el, "action-required-btn-submit")!.click();
  assert.deepEqual(calls, [{ answers: { Database: "SQLite" } }], "works with no onStep handler");
});

test("360de81b: a step passed in renders that question with its saved answers — how the renderer restores a card it rebuilt", () => {
  const el = mcCard(makeHandlers().handlers, { index: 1, answers: { Database: "PostgreSQL", Features: ["Export"] } });
  assert.equal(indicator(el), "Question 2 of 2");
  assert.deepEqual(
    Array.from(el.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'), b => [b.value, b.checked]),
    [["Search", false], ["Export", true], ["Audit log", false]],
  );
  button(el, "action-required-btn-back")!.click();
  assert.equal(el.querySelector<HTMLInputElement>('input[value="PostgreSQL"]')!.checked, true);
});

test("multiple_choice: an option with no description renders no description element", () => {
  const item = makeItem({
    response_type : "multiple_choice",
    questions     : [{ question: "Q", header: "H", multiSelect: false, options: [{ label: "A" }] }],
  });
  const el = renderActionRequiredInteractive(item, makeHandlers().handlers);
  assert.equal(el.querySelectorAll(".action-required-option-label").length, 1);
  assert.equal(el.querySelectorAll(".action-required-option-description").length, 0);
});

test("multiple_choice: a question's inputs share one name, distinct from the other question's and from another card's", () => {
  const a = mcCard(makeHandlers().handlers);
  const b = renderActionRequiredInteractive(makeItem({ id_hash: "ar2", response_type: "multiple_choice", questions: MC_QUESTIONS }), makeHandlers().handlers);
  const namesOf = (el: HTMLElement): string[] => Array.from(new Set(Array.from(
    el.querySelector<HTMLElement>(".action-required-question")!.querySelectorAll("input"),
    input => input.getAttribute("name")!,
  )));
  const a0 = namesOf(a);
  const b0 = namesOf(b);
  tick(a, "PostgreSQL");
  button(a, "action-required-btn-next")!.click();
  const a1 = namesOf(a);
  assert.equal(a0.length, 1);
  assert.equal(a1.length, 1);
  assert.notEqual(a0[0], a1[0]);
  assert.notEqual(a0[0], b0[0]);
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

test("open_ended_batch (real payload) renders one input per question, labelled by header, prefilled from default_value", () => {
  const el = renderActionRequiredInteractive(makeItem({ response_type: "open_ended_batch", questions: BATCH_QUESTIONS }), makeHandlers().handlers);
  const inputs = el.querySelectorAll<HTMLInputElement>(".action-required-batch-input");
  assert.equal(inputs.length, 2);
  assert.deepEqual(Array.from(el.querySelectorAll(".action-required-batch-label"), l => l.textContent), ["Topic", "Budget"]);
  assert.deepEqual(
    Array.from(el.querySelectorAll(".action-required-batch-question"), q => q.textContent),
    ["What topic would you like to research?", "Would you like to set a budget limit?"],
  );
  assert.equal(inputs[0]!.value, "");
  assert.equal(inputs[1]!.value, "no limit");
  assert.ok( el.querySelector(".action-required-btn-submit-all") !== null );
});

// ---------------------------------------------------------------------------
// Click dispatch
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

test("multiple_choice Submit sends { answers } keyed by header — a string for single-select, string[] for multi-select (legacy getCurrentQuestionAnswer)", () => {
  const { handlers, calls } = makeHandlers();
  const el = mcCard(handlers);
  tick(el, "PostgreSQL");
  button(el, "action-required-btn-next")!.click();
  tick(el, "Search");
  tick(el, "Audit log");
  button(el, "action-required-btn-submit")!.click();
  assert.deepEqual(calls, [QUESTIONS_PAYLOAD.multiple_choice.answers]);
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

test("open_ended_batch Submit All sends { answers } keyed by header, each value trimmed (legacy submitOpenEndedBatchAnswers)", () => {
  const { handlers, calls } = makeHandlers();
  const el = renderActionRequiredInteractive(makeItem({ response_type: "open_ended_batch", questions: BATCH_QUESTIONS }), handlers);
  el.querySelectorAll<HTMLInputElement>(".action-required-batch-input")[0]!.value = "  quantum computing  ";
  el.querySelector<HTMLButtonElement>(".action-required-btn-submit-all")!.click();
  assert.deepEqual(calls, [QUESTIONS_PAYLOAD.open_ended_batch.answers]);
});

// ---------------------------------------------------------------------------
// Edge cases + invariants
// ---------------------------------------------------------------------------

test("multiple_choice: Submit with the last question unanswered sends nothing and marks it invalid; answering it clears the mark and sends", () => {
  const { handlers, calls } = makeHandlers();
  const el = mcCard(handlers);
  tick(el, "PostgreSQL");
  button(el, "action-required-btn-next")!.click();
  const submit = button(el, "action-required-btn-submit")!;
  const block  = el.querySelector<HTMLElement>(".action-required-question")!;
  submit.click();
  assert.deepEqual(calls, []);
  assert.equal(block.classList.contains("invalid"), true, "a multi-select question with nothing ticked is unanswered, as in legacy");
  choose(el, "Export");
  assert.equal(block.classList.contains("invalid"), false);
  submit.click();
  assert.equal(calls.length, 1);
});

test("open_ended_batch: Submit All with a blank field sends nothing and marks that input invalid; filling it clears the mark and sends", () => {
  const { handlers, calls } = makeHandlers();
  const el = renderActionRequiredInteractive(makeItem({ response_type: "open_ended_batch", questions: BATCH_QUESTIONS }), handlers);
  const submit = el.querySelector<HTMLButtonElement>(".action-required-btn-submit-all")!;
  const inputs = el.querySelectorAll<HTMLInputElement>(".action-required-batch-input");
  inputs[0]!.value = "   ";
  submit.click();
  assert.deepEqual(calls, []);
  assert.equal(inputs[0]!.classList.contains("invalid"), true);
  assert.equal(inputs[1]!.classList.contains("invalid"), false);
  inputs[0]!.value = "quantum computing";
  submit.click();
  assert.equal(calls.length, 1);
  assert.equal(inputs[0]!.classList.contains("invalid"), false);
});

test("multiple_choice and open_ended_batch with no questions show 'No questions provided.' and offer no controls", () => {
  for (const rt of ["multiple_choice", "open_ended_batch"] as const) {
    const el = renderActionRequiredInteractive(makeItem({ response_type: rt, prompt: "Pick" }), makeHandlers().handlers);
    assert.equal(el.querySelector(".action-required-prompt")!.textContent, "Pick");
    assert.equal(el.querySelector(".action-required-no-questions")!.textContent, "No questions provided.");
    assert.equal(el.querySelectorAll("button, input").length, 0, `${rt}: no controls`);
  }
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
    const questions = rt === "multiple_choice" ? MC_QUESTIONS : rt === "open_ended_batch" ? BATCH_QUESTIONS : [];
    const item = makeItem({ response_type: rt, prompt: `Q-${rt}`, questions });
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
