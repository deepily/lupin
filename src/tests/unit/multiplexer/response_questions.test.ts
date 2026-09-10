// P0 5ebd2aff step 2 — parseResponseQuestions reads the REAL response_options payload, and the
// answer goes back on the wire as the exact string the Python readers are fed.
//
// The server sends `response_options` as { questions: [...] } (cosa/utils/notification_utils.py).
// This client used to copy that object into `options: string[]`, so a real multiple-choice ask
// rendered no choices and its answer had no header to key by.

import { test } from "node:test";
import assert from "node:assert/strict";

import { parseResponseQuestions } from "../../../lupin_app/static/js/multiplexer/stores/responseQuestions";
import { toWireResponseValue } from "../../../lupin_app/static/js/multiplexer/stores/ActionRequiredStore";
import { QUESTIONS_PAYLOAD } from "./fixtures/actionRequiredQuestionsPayload";

test("multiple_choice: the real convert_questions_for_api payload reads as header, question text, multiSelect and labelled options", () => {
  assert.deepEqual(parseResponseQuestions(QUESTIONS_PAYLOAD.multiple_choice.response_options), [
    {
      question    : "Which database should the service use?",
      header      : "Database",
      multiSelect : false,
      options     : [
        { label: "PostgreSQL", description: "Relational, already deployed" },
        { label: "SQLite",     description: "File-backed, no server" },
      ],
    },
    {
      question    : "Which features ship first?",
      header      : "Features",
      multiSelect : true,
      options     : [
        { label: "Search",    description: "Full-text" },
        { label: "Export",    description: "CSV download" },
        { label: "Audit log", description: "Who changed what" },
      ],
    },
  ]);
});

test("open_ended_batch: the real convert_open_ended_batch_for_api payload reads with no options, and default_value as defaultValue", () => {
  assert.deepEqual(parseResponseQuestions(QUESTIONS_PAYLOAD.open_ended_batch.response_options), [
    { question: "What topic would you like to research?", header: "Topic",  multiSelect: false, options: [] },
    { question: "Would you like to set a budget limit?",  header: "Budget", multiSelect: false, options: [], defaultValue: "no limit" },
  ]);
});

test("a payload with no questions array reads as [] — yes_no's null, the old string list, a scalar, a dict without questions", () => {
  for (const raw of [null, undefined, ["yes", "no"], "yes", 7, {}, { questions: "nope" }]) {
    assert.deepEqual(parseResponseQuestions(raw), [], `raw = ${JSON.stringify(raw)}`);
  }
});

test("malformed entries are skipped; a missing header becomes 'Question N' by position, a missing question '', missing options []", () => {
  assert.deepEqual(
    parseResponseQuestions({ questions: [null, "x", { multi_select: "true" }, { header: "", question: 5, options: "nope" }] }),
    [
      { question: "", header: "Question 3", multiSelect: false, options: [] },
      { question: "", header: "Question 4", multiSelect: false, options: [] },
    ],
  );
});

test("options: a bare string is its label; an entry without a string label is dropped; an empty description is left out", () => {
  const [question] = parseResponseQuestions({
    questions: [{ header: "H", options: ["A", { label: "B", description: "" }, { label: 3 }, null, { label: "C", description: "see" }] }],
  });
  assert.deepEqual(question!.options, [{ label: "A" }, { label: "B" }, { label: "C", description: "see" }]);
});

test("default_value is kept only when it is a string", () => {
  const [question] = parseResponseQuestions({ questions: [{ header: "H", default_value: 5 }] });
  assert.equal("defaultValue" in question!, false);
});

// Mr. Radio's condition on the Python arms (16:23): without this, test_both_clients_answers_read_back_the_same.py
// only tests the fixture, not this client's code. wire_value is what those arms feed the askers' readers.
test("toWireResponseValue writes each fixture answer as its wire_value, byte for byte, and a string answer bare", () => {
  for (const name of ["multiple_choice", "open_ended_batch"] as const) {
    assert.equal(toWireResponseValue(QUESTIONS_PAYLOAD[name].answers), QUESTIONS_PAYLOAD[name].wire_value, name);
  }
  assert.equal(toWireResponseValue("yes"), "yes");
});
