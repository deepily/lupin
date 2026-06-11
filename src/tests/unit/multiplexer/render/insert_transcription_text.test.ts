// Multiplexer WP6 (F5 insert-at-caret port) — pure splice helper tests.
// Mirrors the legacy `_insertTranscriptionText` contract (2026-06-01, Rick):
// insert at caret, replace only a highlighted range, never clobber the rest;
// no-caret elements get an append with caret positioning skipped.

import { test } from "node:test";
import assert from "node:assert/strict";

import { insertTranscriptionText } from "../../../../lupin_app/static/js/multiplexer/render/insertTranscriptionText";

test("empty field: value is exactly the text, caret at end", () => {
  const r = insertTranscriptionText("", 0, 0, "hello world");
  assert.equal(r.value, "hello world");
  assert.equal(r.caret, "hello world".length);
});

test("caret mid-text, no selection: text spliced in, surroundings intact", () => {
  const r = insertTranscriptionText("Hello world", 6, 6, "brave ");
  assert.equal(r.value, "Hello brave world");
  assert.equal(r.caret, 6 + "brave ".length);
});

test("caret at end: text appended, nothing lost", () => {
  const r = insertTranscriptionText("Hello", 5, 5, " world");
  assert.equal(r.value, "Hello world");
  assert.equal(r.caret, 11);
});

test("caret at start: text prepended", () => {
  const r = insertTranscriptionText("world", 0, 0, "Hello ");
  assert.equal(r.value, "Hello world");
  assert.equal(r.caret, 6);
});

test("highlighted range: ONLY the selection is replaced", () => {
  // "Hello cruel world" with "cruel" selected [6, 11).
  const r = insertTranscriptionText("Hello cruel world", 6, 11, "brave");
  assert.equal(r.value, "Hello brave world");
  assert.equal(r.caret, 6 + "brave".length);
});

test("full-field selection: replace-all degenerate case still works", () => {
  const r = insertTranscriptionText("old take", 0, 8, "new take");
  assert.equal(r.value, "new take");
  assert.equal(r.caret, 8);
});

test("null selStart (no caret): appends and reports null caret", () => {
  const r = insertTranscriptionText("existing", null, null, " more");
  assert.equal(r.value, "existing more");
  assert.equal(r.caret, null);
});

test("undefined selStart (no caret): appends and reports null caret", () => {
  const r = insertTranscriptionText("existing", undefined, undefined, " more");
  assert.equal(r.value, "existing more");
  assert.equal(r.caret, null);
});

test("caret present but selEnd null: treated as collapsed selection at selStart", () => {
  const r = insertTranscriptionText("ab", 1, null, "X");
  assert.equal(r.value, "aXb");
  assert.equal(r.caret, 2);
});

test("empty transcription: value unchanged through a collapsed caret, caret stays", () => {
  const r = insertTranscriptionText("keep me", 4, 4, "");
  assert.equal(r.value, "keep me");
  assert.equal(r.caret, 4);
});
