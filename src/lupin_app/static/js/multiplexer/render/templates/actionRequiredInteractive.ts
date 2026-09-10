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
//   and submit `{ answers: { <header>: value } }`, the shape legacy sends. Every question is
//   stacked in one card with one Submit. Legacy's Back/Next paging, "Other" free text, 🎤 mic
//   and prediction prefill are NOT ported; they are named in the parity doc.
//
// Per Pass 2 A4: the widget root carries `data-id-hash="${item.id_hash}"`
//   (NOT `data-action-required-id`).
//
// Dispatch contract:
//   - yes_no            → 2 buttons, direct on-click → "yes" | "no"
//   - multiple_choice   → per question a radio group (multiSelect false) or checkbox group
//                         (true), one Submit → { answers: { <header>: string | string[] } }
//   - open_ended        → text input + Submit (Enter to submit) → string
//   - open_ended_batch  → per question a text input prefilled from defaultValue, Submit All
//                         → { answers: { <header>: string } }
//   - no questions      → the prompt and "No questions provided.", no controls (legacy batch)
//   - Submit does nothing until EVERY question is answered, and marks the unanswered ones
//     `.invalid` (legacy getCurrentQuestionAnswer, submitOpenEndedBatchAnswers)
//   - default:          → throws (defense against schema drift)

import { html } from "../html";
import type { ActionRequiredItem, ActionRequiredResponse } from "../../shared/types";

export interface ActionRequiredInteractiveHandlers {
  onSubmit(response: ActionRequiredResponse): void;
}

/**
 * Build an interactive action-required widget.
 *
 * Requires:
 *   - `item.id_hash` non-empty
 *   - `handlers.onSubmit` is a function
 *   - `item.response_type` is one of the four canonical values (else throws)
 *
 * Ensures:
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
      buildMultipleChoice(root, item, handlers);
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
): void {
  if (appendNoQuestions(root, item)) return;

  const questionFrags = item.questions.map((q, qIdx) => {
    const inputName  = `ar-${item.id_hash}-q${String(qIdx)}`;
    const inputType  = q.multiSelect ? "checkbox" : "radio";
    const groupClass = q.multiSelect
      ? "action-required-options-group action-required-options-checkbox"
      : "action-required-options-group action-required-options-radio";
    const groupRole  = q.multiSelect ? "group" : "radiogroup";
    const optionFrags = q.options.map((opt, idx) => html`
      <label class="action-required-option-label">
        <input type="${inputType}" name="${inputName}" value="${opt.label}" data-option-index="${String(idx)}">
        <span class="action-required-option-text">${opt.label}</span>
        ${opt.description !== undefined ? html`<span class="action-required-option-description">${opt.description}</span>` : null}
      </label>
    `);
    return html`
      <div class="action-required-question" data-question-index="${String(qIdx)}">
        <div class="action-required-question-header">${q.header}</div>
        <div class="action-required-question-text">${q.question}</div>
        <div class="${groupClass}" role="${groupRole}">${optionFrags}</div>
      </div>
    `;
  });
  const frag = html`
    <div class="action-required-prompt">${item.prompt}</div>
    <div class="action-required-questions">${questionFrags}</div>
    <div class="action-required-controls">
      <button type="button" class="action-required-btn action-required-btn-submit">Submit</button>
    </div>
  ` as DocumentFragment;
  root.appendChild(frag);

  const submit = root.querySelector<HTMLButtonElement>(".action-required-btn-submit");
  /* c8 ignore next */ // defensive: submit button always present after html`` above.
  if (submit === null) return;
  submit.addEventListener("click", () => {
    const answers: Record<string, string | ReadonlyArray<string>> = {};
    let complete = true;
    const blocks = Array.from(root.querySelectorAll<HTMLElement>(".action-required-question"));
    blocks.forEach((block, qIdx) => {
      const question = item.questions[qIdx]!;
      const values   = Array.from(block.querySelectorAll<HTMLInputElement>("input:checked"), (input) => input.value);
      if (values.length === 0) {
        complete = false;
        block.classList.add("invalid");
        return;
      }
      block.classList.remove("invalid");
      // legacy getCurrentQuestionAnswer: `question.multi_select ? answers : answers[ 0 ]`
      answers[question.header] = question.multiSelect ? values : values[0]!;
    });
    if (!complete) return;
    handlers.onSubmit({ answers });
  });
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
