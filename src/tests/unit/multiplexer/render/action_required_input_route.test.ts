// Capture fields: each card reports how its answer was given.
//
// Routes are click, typed, comment and voice. The cards are driven from the real
// response_options payload, never a hand-typed option list.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import {
  renderActionRequiredInteractive,
  type ActionRequiredInteractiveHandlers,
} from "../../../../lupin_app/static/js/multiplexer/render/templates/actionRequiredInteractive";
import { parseResponseQuestions } from "../../../../lupin_app/static/js/multiplexer/stores/responseQuestions";
import type {
  ActionRequiredItem,
  ActionRequiredResponse,
  ActionRequiredRoute,
} from "../../../../lupin_app/static/js/multiplexer/shared/types";
import { QUESTIONS_PAYLOAD } from "../fixtures/actionRequiredQuestionsPayload";

const MC_QUESTIONS    = parseResponseQuestions(QUESTIONS_PAYLOAD.multiple_choice.response_options);
const BATCH_QUESTIONS = parseResponseQuestions(QUESTIONS_PAYLOAD.open_ended_batch.response_options);

before(() => {
  if (typeof globalThis.document === "undefined") GlobalRegistrator.register();
});

type Sent = { response: ActionRequiredResponse; route: ActionRequiredRoute | undefined };

function item(over: Partial<ActionRequiredItem>): ActionRequiredItem {
  return {
    id_hash : "ar1", prompt: "Proceed?", response_type: "yes_no", questions: [],
    expires_at: Date.UTC(2026, 4, 5, 14, 7) + 30_000, timeout_seconds: 30, state: "pending", ...over,
  };
}

function render(it: ActionRequiredItem, withMic = true): { el: HTMLElement; sent: Sent[]; fillMic: (words: string) => void } {
  const sent: Sent[] = [];
  let target: HTMLInputElement | null = null;
  const handlers: ActionRequiredInteractiveHandlers = {
    onSubmit(response, route): void { sent.push({ response, route }); },
    ...(withMic ? { onMic: (_c: string, _b: HTMLButtonElement, input: HTMLInputElement) => { target = input; } } : {}),
  };
  const el = renderActionRequiredInteractive(it, handlers);
  // The mic fills the field once the words are in, the way actionRequiredMic does.
  const fillMic = (words: string): void => { target!.value = words; target!.dispatchEvent(new Event("input", { bubbles: true })); };
  return { el, sent, fillMic };
}

const q = <T extends Element>(el: HTMLElement, sel: string): T => el.querySelector<T>(sel)!;
const typeInto = (input: HTMLInputElement, text: string): void => {
  input.dispatchEvent(new KeyboardEvent("keydown", { key: "a", bubbles: true }));
  input.value = text;
  input.dispatchEvent(new Event("input", { bubbles: true }));
};

// ---- yes / no
test("yes_no: a plain click is a click", () => {
  const { el, sent } = render(item({}));
  q<HTMLButtonElement>(el, ".action-required-btn-yes").click();
  assert.deepEqual(sent, [ { response: "yes", route: "click" } ]);
});

test("yes_no: a typed comment makes the route comment", () => {
  const { el, sent } = render(item({}));
  typeInto(q<HTMLInputElement>(el, ".yes-no-comment-input"), "but leave config alone");
  q<HTMLButtonElement>(el, ".action-required-btn-no").click();
  assert.deepEqual(sent, [ { response: "no [comment: but leave config alone]", route: "comment" } ]);
});

test("yes_no: a comment from the mic is voice, until the person types in it", () => {
  const { el, sent, fillMic } = render(item({}));
  q<HTMLButtonElement>(el, ".yes-no-comment-mic").click();
  fillMic("dictated words");
  q<HTMLButtonElement>(el, ".action-required-btn-yes").click();
  assert.equal(sent[ 0 ]!.route, "voice");
  typeInto(q<HTMLInputElement>(el, ".yes-no-comment-input"), "edited by hand");
  q<HTMLButtonElement>(el, ".action-required-btn-yes").click();
  assert.equal(sent[ 1 ]!.route, "comment");
});

test("yes_no: Enter in the comment box does not clear the voice mark", () => {
  const { el, sent, fillMic } = render(item({}));
  const input = q<HTMLInputElement>(el, ".yes-no-comment-input");
  q<HTMLButtonElement>(el, ".yes-no-comment-mic").click();
  fillMic("dictated");
  input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
  q<HTMLButtonElement>(el, ".action-required-btn-yes").click();
  assert.equal(sent[ 0 ]!.route, "voice");
});

test("yes_no: with no onMic the mic click is inert and the route stays comment", () => {
  const { el, sent } = render(item({}), false);
  q<HTMLButtonElement>(el, ".yes-no-comment-mic").click();
  typeInto(q<HTMLInputElement>(el, ".yes-no-comment-input"), "words");
  q<HTMLButtonElement>(el, ".action-required-btn-yes").click();
  assert.equal(sent[ 0 ]!.route, "comment", "typing after the mic click clears the voice mark");
});

// ---- open ended
test("open_ended: typed text is typed, mic text is voice", () => {
  const { el, sent, fillMic } = render(item({ response_type: "open_ended" }));
  const input = q<HTMLInputElement>(el, ".action-required-input");
  typeInto(input, "hello");
  q<HTMLButtonElement>(el, ".action-required-btn-submit").click();
  q<HTMLButtonElement>(el, ".response-mic").click();
  fillMic("spoken");
  q<HTMLButtonElement>(el, ".action-required-btn-submit").click();
  assert.deepEqual(sent.map((s) => s.route), [ "typed", "voice" ]);
});

// ---- multiple choice
function mc(): ReturnType<typeof render> {
  return render(item({ response_type: "multiple_choice", questions: [ MC_QUESTIONS[ 0 ]! ] }));
}

test("multiple_choice: ticking a listed option is a click", () => {
  const { el, sent } = mc();
  const label = MC_QUESTIONS[ 0 ]!.options[ 0 ]!.label;
  const input = q<HTMLInputElement>(el, `input[value="${label}"]`);
  input.checked = true;
  q<HTMLButtonElement>(el, ".action-required-btn-submit").click();
  assert.deepEqual(sent[ 0 ]!.route, { [ MC_QUESTIONS[ 0 ]!.header ]: "click" });
});

test("multiple_choice: Other's text equal to a label is typed, not a click", () => {
  const { el, sent } = mc();
  const label = MC_QUESTIONS[ 0 ]!.options[ 0 ]!.label;
  q<HTMLInputElement>(el, ".mc-other-radio").checked = true;
  typeInto(q<HTMLInputElement>(el, ".mc-other-input"), label);
  q<HTMLButtonElement>(el, ".action-required-btn-submit").click();
  const header = MC_QUESTIONS[ 0 ]!.header;
  assert.deepEqual(sent[ 0 ]!.response, { answers: { [ header ]: label } });
  assert.deepEqual(sent[ 0 ]!.route, { [ header ]: "typed" });
});

test("multiple_choice: Other's text from the mic is voice, and typing over it makes it typed", () => {
  const { el, sent, fillMic } = mc();
  const header = MC_QUESTIONS[ 0 ]!.header;
  q<HTMLButtonElement>(el, ".mc-other-mic").click();
  fillMic("spoken answer");
  q<HTMLButtonElement>(el, ".action-required-btn-submit").click();
  assert.deepEqual(sent[ 0 ]!.route, { [ header ]: "voice" });
  typeInto(q<HTMLInputElement>(el, ".mc-other-input"), "typed over it");
  q<HTMLButtonElement>(el, ".action-required-btn-submit").click();
  assert.deepEqual(sent[ 1 ]!.route, { [ header ]: "typed" });
});

test("multiple_choice: ticking a label after using Other goes back to a click", () => {
  const { el, sent } = mc();
  const label = MC_QUESTIONS[ 0 ]!.options[ 0 ]!.label;
  q<HTMLInputElement>(el, ".mc-other-radio").checked = true;
  typeInto(q<HTMLInputElement>(el, ".mc-other-input"), "custom");
  q<HTMLButtonElement>(el, ".action-required-btn-submit").click();
  q<HTMLInputElement>(el, ".mc-other-radio").checked = false;
  q<HTMLInputElement>(el, `input[value="${label}"]`).checked = true;
  q<HTMLButtonElement>(el, ".action-required-btn-submit").click();
  assert.deepEqual(sent.map((s) => s.route), [ { [ MC_QUESTIONS[ 0 ]!.header ]: "typed" }, { [ MC_QUESTIONS[ 0 ]!.header ]: "click" } ]);
});

// ---- batch
test("open_ended_batch: every question is typed", () => {
  const { el, sent } = render(item({ response_type: "open_ended_batch", questions: BATCH_QUESTIONS }));
  for (const input of Array.from(el.querySelectorAll<HTMLInputElement>(".action-required-batch-input"))) input.value = "an answer";
  q<HTMLButtonElement>(el, ".action-required-btn-submit-all").click();
  const expected: Record<string, string> = {};
  for (const question of BATCH_QUESTIONS) expected[ question.header ] = "typed";
  assert.deepEqual(sent[ 0 ]!.route, expected);
});
