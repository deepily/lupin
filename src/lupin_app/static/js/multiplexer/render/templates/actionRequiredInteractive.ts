/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Phase 6b — action-required INTERACTIVE widget template.
//
// AC2e safe-write invariant (per Pass 2 a1 in `09-phase6b-interactive-widgets-design.md`):
//   ALL DOM writes go through the `html` tagged template + `.textContent` / `.value`
//   only. NEVER use `.innerHTML =`, `rawHTML(`, or `.outerHTML =`.
//   This file is verified by AC2e grep test in templates_action_required_interactive.test.ts.
//
// P0 5ebd2aff step 2 — multiple_choice and open_ended_batch render the REAL questions
//   (`item.questions`, parsed from `response_options.questions` by stores/responseQuestions.ts)
//   and submit `{ answers: { <header>: value } }`, the shape legacy sends. Legacy's "Other" free
//   text, 🎤 mic and prediction prefill are NOT ported; they are named in the parity doc.
//
// 360de81b — multiple_choice walks ONE question at a time with Back and Next, as legacy does
//   (renderMultipleChoiceUI :23519, navigateMultipleChoice :23729). Next validates and saves; Back
//   saves only a valid answer and steps back; the last question submits every saved answer. The
//   position and saved answers are reported through `onStep` so the renderer can hand them back
//   after a rebuild. open_ended_batch stays stacked, because legacy stacks it too.
//
// Per Pass 2 A4: the widget root carries `data-id-hash="${item.id_hash}"`
//   (NOT `data-action-required-id`).
//
// Dispatch contract:
//   - yes_no            → 2 buttons, direct on-click → "yes" | "no"
//   - multiple_choice   → one question at a time: a radio group (multiSelect false) or checkbox
//                         group (true); Back / "Next Question →" / "Submit" or "Submit All ✓"
//                         → { answers: { <header>: string | string[] } }
//   - open_ended        → text input + Submit (Enter to submit) → string
//   - open_ended_batch  → per question a text input prefilled from defaultValue, Submit All
//                         → { answers: { <header>: string } }
//   - no questions      → the prompt and "No questions provided.", no controls (legacy batch)
//   - Submit does nothing until EVERY question is answered, and marks the unanswered ones
//     `.invalid` (legacy getCurrentQuestionAnswer, submitOpenEndedBatchAnswers)
//   - default:          → throws (defense against schema drift)

import { html } from "../html";
import type { ActionRequiredItem, ActionRequiredResponse } from "../../shared/types";

/** multiple_choice stepper position: the question on screen and every answer saved so far. */
export interface MultipleChoiceStep {
  index   : number;
  answers : Readonly<Record<string, string | ReadonlyArray<string>>>;
}

export interface ActionRequiredInteractiveHandlers {
  onSubmit(response: ActionRequiredResponse): void;
  /** multiple_choice only: called after every Back, Next and Submit with the new position. */
  onStep?(step: MultipleChoiceStep): void;
}

/**
 * Build an interactive action-required widget.
 *
 * Requires:
 *   - `item.id_hash` non-empty
 *   - `handlers.onSubmit` is a function
 *   - `item.response_type` is one of the four canonical values (else throws)
 *   - `step`, when given, has `0 <= step.index < item.questions.length` (multiple_choice only)
 *
 * Ensures:
 *   - multiple_choice shows the question at `step.index` (default 0) with `step.answers` checked
 *   - Returned HTMLElement carries `data-id-hash` per Pass 2 A4
 *   - User interactions invoke `handlers.onSubmit(response)` at most once per submit gesture
 *   - multiple_choice / open_ended_batch submit `{ answers }` keyed by each question's header
 *   - All writes are safe per AC2e (no .innerHTML / no rawHTML / no .outerHTML)
 *
 * Throws:
 *   - Error if `item.response_type` is unrecognized (schema drift defense)
 */
export function renderActionRequiredInteractive(
  item     : ActionRequiredItem,
  handlers : ActionRequiredInteractiveHandlers,
  step?    : MultipleChoiceStep,
): HTMLElement {
  const root = document.createElement("div");
  root.className = "action-required-widget action-required-widget-interactive";
  root.setAttribute("data-id-hash", item.id_hash);
  root.setAttribute("data-testid", "multiplexer-action-required");

  switch (item.response_type) {
    case "yes_no":
      buildYesNo(root, item, handlers);
      return root;
    case "multiple_choice":
      buildMultipleChoice(root, item, handlers, step);
      return root;
    case "open_ended":
      buildOpenEnded(root, item, handlers);
      return root;
    case "open_ended_batch":
      buildOpenEndedBatch(root, item, handlers);
      return root;
    default:
      throw new Error(`Unknown response_type: ${item.response_type as string}`);
  }
}

// ---------------------------------------------------------------------------
// Sub-builders — each appends DOM into root + wires handlers.
// ---------------------------------------------------------------------------

function buildYesNo(
  root     : HTMLElement,
  item     : ActionRequiredItem,
  handlers : ActionRequiredInteractiveHandlers,
): void {
  const frag = html`
    <div class="action-required-prompt">${item.prompt}</div>
    <div class="action-required-controls">
      <button type="button" class="action-required-btn action-required-btn-yes" data-value="yes">Yes</button>
      <button type="button" class="action-required-btn action-required-btn-no"  data-value="no">No</button>
    </div>
  ` as DocumentFragment;
  root.appendChild(frag);

  const btnYes = root.querySelector<HTMLButtonElement>(".action-required-btn-yes");
  const btnNo  = root.querySelector<HTMLButtonElement>(".action-required-btn-no");
  /* c8 ignore next */ // defensive: html`` template above always produces both buttons; null arms unreachable in practice (test invariant).
  if (btnYes !== null) btnYes.addEventListener("click", () => handlers.onSubmit("yes"));
  /* c8 ignore next */ // defensive: see above — symmetric guard.
  if (btnNo  !== null) btnNo.addEventListener("click",  () => handlers.onSubmit("no"));
}

function buildMultipleChoice(
  root     : HTMLElement,
  item     : ActionRequiredItem,
  handlers : ActionRequiredInteractiveHandlers,
  step     : MultipleChoiceStep | undefined,
): void {
  if (appendNoQuestions(root, item)) return;

  const total   = item.questions.length;
  let index     = step?.index ?? 0;
  // legacy state.collectedAnswers — insertion order is the order answers were first saved.
  const answers : Record<string, string | ReadonlyArray<string>> = { ...step?.answers };

  const prompt  = html`<div class="action-required-prompt">${item.prompt}</div>` as DocumentFragment;
  const stepper = document.createElement("div");
  stepper.className = "action-required-stepper";
  root.append(prompt, stepper);

  const report = (): void => handlers.onStep?.({ index, answers: { ...answers } });

  // legacy saveCurrentQuestionAnswer :23705 — false (and nothing saved) when nothing is ticked.
  const saveCurrent = (block: HTMLElement): boolean => {
    const question = item.questions[index]!;
    const values   = Array.from(block.querySelectorAll<HTMLInputElement>("input:checked"), (input) => input.value);
    if (values.length === 0) return false;
    // legacy getCurrentQuestionAnswer: `question.multi_select ? answers : answers[ 0 ]`
    answers[question.header] = question.multiSelect ? values : values[0]!;
    return true;
  };

  const renderStep = (): void => {
    const q          = item.questions[index]!;
    const inputName  = `ar-${item.id_hash}-q${String(index)}`;
    const inputType  = q.multiSelect ? "checkbox" : "radio";
    const groupClass = q.multiSelect
      ? "action-required-options-group action-required-options-checkbox"
      : "action-required-options-group action-required-options-radio";
    const groupRole  = q.multiSelect ? "group" : "radiogroup";
    const isFirst    = index === 0;
    const isLast     = index === total - 1;
    const optionFrags = q.options.map((opt, idx) => html`
      <label class="action-required-option-label">
        <input type="${inputType}" name="${inputName}" value="${opt.label}" data-option-index="${String(idx)}">
        <span class="action-required-option-text">${opt.label}</span>
        ${opt.description !== undefined ? html`<span class="action-required-option-description">${opt.description}</span>` : null}
      </label>
    `);
    // Button labels are legacy's, verbatim (:23599-23624).
    const frag = html`
      <div class="action-required-question" data-question-index="${String(index)}">
        <div class="action-required-question-indicator">Question ${index + 1} of ${total}</div>
        <div class="action-required-question-header">${q.header}</div>
        <div class="action-required-question-text">${q.question}</div>
        ${q.multiSelect ? html`<div class="action-required-multi-hint">(Select all that apply)</div>` : null}
        <div class="${groupClass}" role="${groupRole}">${optionFrags}</div>
      </div>
      <div class="action-required-controls">
        ${isFirst ? null : html`<button type="button" class="action-required-btn action-required-btn-back">← Back</button>`}
        ${isLast
          ? html`<button type="button" class="action-required-btn action-required-btn-submit">${total === 1 ? "Submit" : "Submit All ✓"}</button>`
          : html`<button type="button" class="action-required-btn action-required-btn-next">Next Question →</button>`}
      </div>
    ` as DocumentFragment;
    stepper.replaceChildren(frag);

    const block  = stepper.querySelector<HTMLElement>(".action-required-question")!;
    const back   = stepper.querySelector<HTMLButtonElement>(".action-required-btn-back");
    const next   = stepper.querySelector<HTMLButtonElement>(".action-required-btn-next");
    const submit = stepper.querySelector<HTMLButtonElement>(".action-required-btn-submit");
    const primary = (next ?? submit)!;
    const saved  = answers[q.header];

    for (const input of Array.from(block.querySelectorAll<HTMLInputElement>("input"))) {
      // legacy :23541-23547 — a saved answer re-checks its options when the question is shown again.
      input.checked = typeof saved === "string" ? saved === input.value : saved?.includes(input.value) === true;
      input.addEventListener("change", () => {
        block.classList.remove("invalid");
        primary.focus({ preventScroll: true });
      });
    }

    if (back !== null) {
      back.addEventListener("click", () => {
        saveCurrent(block);                    // legacy :23747 — kept if valid, ignored if not
        index -= 1;
        report();
        renderStep();
      });
    }
    if (next !== null) {
      next.addEventListener("click", () => {
        if (!saveCurrent(block)) {
          block.classList.add("invalid");
          return;
        }
        index += 1;
        report();
        renderStep();
      });
    }
    if (submit !== null) {
      submit.addEventListener("click", () => {
        if (!saveCurrent(block)) {
          block.classList.add("invalid");
          return;
        }
        report();
        handlers.onSubmit({ answers: { ...answers } });
      });
    }
  };

  renderStep();
}

function buildOpenEnded(
  root     : HTMLElement,
  item     : ActionRequiredItem,
  handlers : ActionRequiredInteractiveHandlers,
): void {
  const frag = html`
    <div class="action-required-prompt">${item.prompt}</div>
    <div class="action-required-controls">
      <input type="text" class="action-required-input" placeholder="${item.default ?? ""}">
      <button type="button" class="action-required-btn action-required-btn-submit">Submit</button>
    </div>
  ` as DocumentFragment;
  root.appendChild(frag);

  const input  = root.querySelector<HTMLInputElement>(".action-required-input");
  const submit = root.querySelector<HTMLButtonElement>(".action-required-btn-submit");
  /* c8 ignore next */ // defensive: both elements always present after html`` above.
  if (input === null || submit === null) return;

  const submitNow = (): void => handlers.onSubmit(input.value);
  submit.addEventListener("click", submitNow);
  input.addEventListener("keydown", (e: KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault();
      submitNow();
    }
  });
}

function buildOpenEndedBatch(
  root     : HTMLElement,
  item     : ActionRequiredItem,
  handlers : ActionRequiredInteractiveHandlers,
): void {
  if (appendNoQuestions(root, item)) return;

  const rowFrags = item.questions.map((q, idx) => html`
    <div class="action-required-batch-row" data-batch-index="${String(idx)}">
      <label class="action-required-batch-label">${q.header}</label>
      <div class="action-required-batch-question">${q.question}</div>
      <input type="text" class="action-required-batch-input" data-batch-header="${q.header}" value="${q.defaultValue ?? ""}" placeholder="Type your answer...">
    </div>
  `);
  const frag = html`
    <div class="action-required-prompt">${item.prompt}</div>
    <div class="action-required-batch-group">${rowFrags}</div>
    <div class="action-required-controls">
      <button type="button" class="action-required-btn action-required-btn-submit-all">Submit All</button>
    </div>
  ` as DocumentFragment;
  root.appendChild(frag);

  const submit = root.querySelector<HTMLButtonElement>(".action-required-btn-submit-all");
  /* c8 ignore next */ // defensive: submit-all button always present after html`` above.
  if (submit === null) return;
  submit.addEventListener("click", () => {
    const answers: Record<string, string> = {};
    let complete = true;
    const inputs = Array.from(root.querySelectorAll<HTMLInputElement>(".action-required-batch-input"));
    inputs.forEach((input, idx) => {
      const value = input.value.trim();
      answers[item.questions[idx]!.header] = value;
      if (value === "") {
        complete = false;
        input.classList.add("invalid");
        return;
      }
      input.classList.remove("invalid");
    });
    if (!complete) return;
    handlers.onSubmit({ answers });
  });
}

// Legacy renderOpenEndedBatchUI shows "No questions provided." for an empty payload; with no
// questions there is no header to key an answer by, so the card offers no controls at all.
function appendNoQuestions(root: HTMLElement, item: ActionRequiredItem): boolean {
  if (item.questions.length > 0) return false;
  /* c8 ignore next 4 */ // tagged-template literal: c8's JSON puts a phantom arm on the ${item.prompt} interpolation (Phase 6a jobCard.ts:251 precedent); both paths of appendNoQuestions are tested.
  const frag = html`
    <div class="action-required-prompt">${item.prompt}</div>
    <div class="action-required-no-questions">No questions provided.</div>
  ` as DocumentFragment;
  root.appendChild(frag);
  return true;
}
