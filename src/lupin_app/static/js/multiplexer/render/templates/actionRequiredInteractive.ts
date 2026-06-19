/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Phase 6b — action-required INTERACTIVE widget template.
//
// AC2e safe-write invariant (per Pass 2 a1 in `09-phase6b-interactive-widgets-design.md`):
//   ALL DOM writes go through the `html` tagged template + `.textContent` / `.value`
//   only. NEVER use `.innerHTML =`, `rawHTML(`, or `.outerHTML =`.
//   This file is verified by AC2e grep test in templates_action_required_interactive.test.ts.
//
// Per Pass 2 A2: handler signature accepts the widened response shape
//   `string | ReadonlyArray<string> | Record<string, string>` so the same
//   onSubmit() works for yes_no (string), multiple_choice multi (array),
//   and open_ended_batch (record).
//
// Per Pass 2 A4: the widget root carries `data-id-hash="${item.id_hash}"`
//   (NOT `data-action-required-id`).
//
// Per Pass 2 A6 / Q-B1 dispatch contract:
//   - yes_no                                → 2 buttons, direct on-click
//   - multiple_choice + multiSelect:false   → radio group + Submit
//   - multiple_choice + multiSelect:true    → checkbox group + Submit
//   - open_ended                            → text input + Submit (Enter to submit)
//   - open_ended_batch                      → per-question inputs + Submit-All
//   - default:                              → throws (defense against schema drift)

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
 *   - User interactions invoke `handlers.onSubmit(response)` exactly once per submit gesture
 *   - DOM shape varies per `response_type` (and `multiSelect` when multiple_choice)
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
      if (item.multiSelect === true) buildCheckbox(root, item, handlers);
      else                           buildRadio(root, item, handlers);
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

function buildRadio(
  root     : HTMLElement,
  item     : ActionRequiredItem,
  handlers : ActionRequiredInteractiveHandlers,
): void {
  const radioName = `ar-${item.id_hash}`;
  const optionFrags = item.options.map((opt, idx) => html`
    <label class="action-required-option-label">
      <input type="radio" name="${radioName}" value="${opt}" data-option-index="${String(idx)}">
      <span class="action-required-option-text">${opt}</span>
    </label>
  `);
  const frag = html`
    <div class="action-required-prompt">${item.prompt}</div>
    <div class="action-required-options-group action-required-options-radio" role="radiogroup">${optionFrags}</div>
    <div class="action-required-controls">
      <button type="button" class="action-required-btn action-required-btn-submit">Submit</button>
    </div>
  ` as DocumentFragment;
  root.appendChild(frag);

  const submit = root.querySelector<HTMLButtonElement>(".action-required-btn-submit");
  /* c8 ignore next */ // defensive: submit button always present after html`` above.
  if (submit === null) return;
  submit.addEventListener("click", () => {
    const checked = root.querySelector<HTMLInputElement>(`input[name="${radioName}"]:checked`);
    if (checked === null) return;       // no selection → no-op (UI rule)
    handlers.onSubmit(checked.value);
  });
}

function buildCheckbox(
  root     : HTMLElement,
  item     : ActionRequiredItem,
  handlers : ActionRequiredInteractiveHandlers,
): void {
  const checkboxName = `ar-${item.id_hash}`;
  const optionFrags = item.options.map((opt, idx) => html`
    <label class="action-required-option-label">
      <input type="checkbox" name="${checkboxName}" value="${opt}" data-option-index="${String(idx)}">
      <span class="action-required-option-text">${opt}</span>
    </label>
  `);
  const frag = html`
    <div class="action-required-prompt">${item.prompt}</div>
    <div class="action-required-options-group action-required-options-checkbox" role="group">${optionFrags}</div>
    <div class="action-required-controls">
      <button type="button" class="action-required-btn action-required-btn-submit">Submit</button>
    </div>
  ` as DocumentFragment;
  root.appendChild(frag);

  const submit = root.querySelector<HTMLButtonElement>(".action-required-btn-submit");
  /* c8 ignore next */ // defensive: submit button always present after html`` above.
  if (submit === null) return;
  submit.addEventListener("click", () => {
    const checked = root.querySelectorAll<HTMLInputElement>(`input[name="${checkboxName}"]:checked`);
    const values: string[] = [];
    checked.forEach(input => values.push(input.value));
    handlers.onSubmit(values);
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
  // For batch: each entry in item.options is a "header" / question label.
  // The on-submit payload is Record<header, answer>.
  /* c8 ignore next 6 */ // tagged-template literal: c8 reports phantom branches on $-interpolations (Phase 6a jobCard.ts:251 precedent).
  const inputFrags = item.options.map((header, idx) => html`
    <div class="action-required-batch-row" data-batch-index="${String(idx)}">
      <label class="action-required-batch-label">${header}</label>
      <input type="text" class="action-required-batch-input" data-batch-header="${header}">
    </div>
  `);
  /* c8 ignore next 7 */ // same — phantom-branch artifact of the outer template literal (Phase 6a precedent).
  const frag = html`
    <div class="action-required-prompt">${item.prompt}</div>
    <div class="action-required-batch-group">${inputFrags}</div>
    <div class="action-required-controls">
      <button type="button" class="action-required-btn action-required-btn-submit-all">Submit All</button>
    </div>
  ` as DocumentFragment;
  root.appendChild(frag);

  const submit = root.querySelector<HTMLButtonElement>(".action-required-btn-submit-all");
  /* c8 ignore next */ // defensive: submit-all button always present after html`` above.
  if (submit === null) return;
  submit.addEventListener("click", () => {
    const inputs = root.querySelectorAll<HTMLInputElement>(".action-required-batch-input");
    const out: Record<string, string> = {};
    inputs.forEach(input => {
      const header = input.dataset.batchHeader;
      /* c8 ignore next */ // defensive: data-batch-header always set by the html`` template above.
      if (header === undefined) return;
      out[header] = input.value;
    });
    handlers.onSubmit(out);
  });
}
