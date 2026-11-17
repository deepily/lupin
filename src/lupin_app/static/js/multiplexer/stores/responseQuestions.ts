/* c8 ignore next */ // tsx phantom-branch artifact on the function declaration line; the body runs for string, label-less object, null and full-option inputs in response_questions.test.ts.
// Multiplexer — the questions an ask carries, read from the REAL wire payload (P0 5ebd2aff step 2).
//
// The server puts `response_options` on the queue update as the dict the asking tool built
// (cosa/utils/notification_utils.py):
//   multiple_choice  → convert_questions_for_api:
//                      { questions: [{ question, header, multi_select, options: [{ label, description }] }] }
//   open_ended_batch → convert_open_ended_batch_for_api:
//                      { questions: [{ question, header, input_type: "text", default_value? }] }
// Legacy reads `notification.response_options.questions` (notifications.js:23495, :23111).
//
// This client used to copy that OBJECT into `options: string[]`. A real multiple-choice ask
// therefore rendered no choices, and its answer had no header to be keyed by, so it could not
// reach the asker. The answer now goes back as legacy sends it — see toWireResponseValue in
// ActionRequiredStore.ts.
//
// Pinned against the real builders by src/tests/unit/test_multiplexer_questions_fixture_matches_the_asking_tools.py.

import type { ActionRequiredOption, ActionRequiredQuestion } from "../shared/types";
import { isFrame } from "./SessionTranscriptStore";

/**
 * Read the questions out of a notification's `response_options`.
 *
 * Requires:
 *   - `raw` is anything the server put in `response_options` (a dict, null, or absent)
 *
 * Ensures:
 *   - returns one ActionRequiredQuestion per well-formed entry of `raw.questions`, in order
 *   - returns [] when `raw` carries no `questions` array (yes_no, open_ended, a malformed payload)
 *   - a missing header falls back to "Question N", as legacy's batch renderer does
 *   - `multiSelect` is true only when the wire says `multi_select: true`
 *   - an option given as a bare string is read as its label
 */
export function parseResponseQuestions(raw: unknown): ReadonlyArray<ActionRequiredQuestion> {
  if (!isFrame(raw) || !Array.isArray(raw.questions)) return [];
  const out: ActionRequiredQuestion[] = [];
  raw.questions.forEach((entry: unknown, idx: number) => {
    if (!isFrame(entry)) return;
    const question: ActionRequiredQuestion = {
      question    : typeof entry.question === "string" ? entry.question : "",
      header      : typeof entry.header === "string" && entry.header !== "" ? entry.header : `Question ${String(idx + 1)}`,
      multiSelect : entry.multi_select === true,
      options     : Array.isArray(entry.options) ? entry.options.flatMap(toOption) : [],
    };
    if (typeof entry.default_value === "string") question.defaultValue = entry.default_value;
    out.push(question);
  });
  return out;
}

/**
 * Converts one raw option value into a list holding zero or one action-required options.
 *
 * A string becomes a label-only option, an object with a string label keeps its non-empty description, and anything else gives an empty list.
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the function declaration line; the body runs for string, label-less object, null and full-option inputs in response_questions.test.ts.
function toOption(raw: unknown): ActionRequiredOption[] {
  if (typeof raw === "string") return [{ label: raw }];
  if (!isFrame(raw) || typeof raw.label !== "string") return [];
  const option: ActionRequiredOption = { label: raw.label };
  if (typeof raw.description === "string" && raw.description !== "") option.description = raw.description;
  return [option];
}

