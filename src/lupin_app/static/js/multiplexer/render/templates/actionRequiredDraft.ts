/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.

// The answer a card's controls hold at the moment the forecast fold opens.
//
// The seen route stores it as prediction_log.draft_at_reveal, so the server can tell an answer given
// unaided from one switched after the forecast was shown. The shape is the one exposure.py documents:
// { value: <the string the submit button would send with the controls as they stand> }.
//
// It is read only. Nothing here marks a field invalid or changes a control.

import type { ActionRequiredItem } from "../../shared/types";
import { MC_OTHER_VALUE } from "./actionRequiredInteractive";

/** The server's limit on a draft, counted in characters of its JSON text. */
export const DRAFT_MAX_CHARS = 4096;

/** The draft the seen route takes: the wire string of the answer so far. */
export interface DraftAtReveal {
  value : string;
}

/**
 * Read the multiple-choice question on screen the way Next would save it.
 *
 * Requires:
 *   - widget is the card's root element
 *
 * Ensures:
 *   - returns { header, value } for the question on screen, or null when nothing is chosen
 *   - a ticked Other counts through its trimmed text, and counts for nothing when that text is empty
 *   - value is a list for a multi-select question and a single string otherwise
 */
function visibleChoice(item: ActionRequiredItem, widget: HTMLElement): { header: string; value: string | string[] } | null {
  const block = widget.querySelector<HTMLElement>(".action-required-question");
  if (block === null) return null;
  const question = item.questions[Number(block.dataset.questionIndex)]!;
  const values: string[] = [];
  for (const input of Array.from(block.querySelectorAll<HTMLInputElement>(".action-required-option-input:checked"))) {
    if (input.value !== MC_OTHER_VALUE) {
      values.push(input.value);
      continue;
    }
    const text = block.querySelector<HTMLInputElement>(".mc-other-input")!.value.trim();
    if (text !== "") values.push(text);
  }
  if (values.length === 0) return null;
  return { header: question.header, value: question.multiSelect ? values : values[0]! };
}

/**
 * Read a batch card's typed answers, leaving out the empty ones.
 *
 * Requires:
 *   - widget is the card's root element
 *
 * Ensures:
 *   - returns { header: trimmed text } for each answer field that holds text
 */
function batchAnswers(widget: HTMLElement): Record<string, string> {
  const answers: Record<string, string> = {};
  for (const input of Array.from(widget.querySelectorAll<HTMLInputElement>(".action-required-batch-input"))) {
    const text = input.value.trim();
    if (text !== "") answers[input.dataset.batchHeader!] = text;
  }
  return answers;
}

/**
 * Say what a card's answer would be if submitted now, as the seen route stores it.
 *
 * Requires:
 *   - widget is the card's interactive root element
 *   - item is the card's item, whose `step` holds the multiple-choice answers saved so far
 *
 * Ensures:
 *   - a yes/no card returns null, because choosing is submitting
 *   - an open-ended card returns its trimmed text, or null when the box is empty
 *   - a multiple-choice card returns the saved answers plus the question on screen, and a batch card its non-empty fields,
 *     as the JSON text of { answers: { header: pick or [picks] } }, or null when no answer is held
 *   - returns null when the draft would be over DRAFT_MAX_CHARS as the route counts it
 *   - never returns an empty value
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the exported function-declaration line.
export function draftAtReveal(item: ActionRequiredItem, widget: HTMLElement): DraftAtReveal | null {
  let wire: string | null = null;
  if (item.response_type === "open_ended") {
    const text = widget.querySelector<HTMLInputElement>("[data-draft='response']")!.value.trim();
    wire = text === "" ? null : text;
  } else if (item.response_type === "open_ended_batch") {
    const answers = batchAnswers(widget);
    wire = Object.keys(answers).length === 0 ? null : JSON.stringify({ answers });
  } else if (item.response_type === "multiple_choice") {
    const answers: Record<string, string | ReadonlyArray<string>> = { ...item.step?.answers };
    const shown = visibleChoice(item, widget);
    if (shown !== null) answers[shown.header] = shown.value;
    wire = Object.keys(answers).length === 0 ? null : JSON.stringify({ answers });
  }
  if (wire === null) return null;
  const draft = { value: wire };
  return JSON.stringify(draft).length > DRAFT_MAX_CHARS ? null : draft;
}
