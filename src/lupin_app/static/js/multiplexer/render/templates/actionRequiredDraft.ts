/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.

// The answer a card's controls hold at the moment the forecast fold opens.
//
// The seen route stores it as prediction_log.draft_at_reveal, so the server can tell an answer given
// unaided from one switched after the forecast was shown. The shape is the one exposure.py documents:
// { value: <the string the submit button would send with the controls as they stand> }.
//
// It is read only. Nothing here marks a field invalid or changes a control.

import type { ActionRequiredItem } from "../../shared/types";
import { buildDraft, type DraftAtReveal } from "../../../shared/draft-at-reveal.js";
import { checkedChoices } from "./actionRequiredInteractive";

// The rules (empty answers, the wire text, the size limit) live in shared/draft-at-reveal.js, which the legacy page reads too.
export { DRAFT_MAX_CHARS, routeLength } from "../../../shared/draft-at-reveal.js";
export type { DraftAtReveal } from "../../../shared/draft-at-reveal.js";

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
  const values = checkedChoices(block);
  if (values.length === 0) return null;
  return { header: question.header, value: question.multiSelect ? values : values[0]! };
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
 *   - returns null when the draft would be over DRAFT_MAX_CHARS as the route counts it (routeLength)
 *   - never returns an empty value
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the exported function-declaration line.
export function draftAtReveal(item: ActionRequiredItem, widget: HTMLElement): DraftAtReveal | null {
  const text   = item.response_type === "open_ended" ? widget.querySelector<HTMLInputElement>("[data-draft='response']")!.value : "";
  const batch  = Array.from(widget.querySelectorAll<HTMLInputElement>(".action-required-batch-input")).map((input): [string, string] => [input.dataset.batchHeader!, input.value]);
  const saved  = item.step?.answers ?? {};
  const shown  = item.response_type === "multiple_choice" ? visibleChoice(item, widget) : null;
  return buildDraft(item.response_type, { text, batch, saved, shown });
}
