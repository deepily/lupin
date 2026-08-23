// 🔴 QUARANTINED — DO NOT RUN THIS FILE, BY ANY INVOCATION.
//
// This file is named `.quarantined.ts`, not `.test.ts`, so that `npm test`
// (glob: "src/tests/**/*.test.ts") cannot pick it up. That is deliberate and it is
// the only thing keeping it out of the suite. Do not rename it back.
//
// WHY. Running it has killed two Claude Code sessions on this box:
//   · 2026-08-23 13:02:50 — `tsx --test` uncapped. systemd-oomd killed 52 processes
//     in scope ccworker-cc_tmux_session_5ed54994 (pressure 74.67% > 50%).
//   · 2026-08-23 16:06:34 — `timeout 300 node --test-concurrency=1 --import tsx --test`
//     on this one file. systemd-oomd killed 30 processes in scope
//     ccworker-cc_tmux_session_d87d84e7 (pressure 74.81% > 50%).
//
// One worker, one file, a five-minute cap — the most cautious shape available — died
// anyway. Concurrency caps and timeouts do NOT mitigate this. The allocator has not
// been identified: the test's 218 lines and the 140-line module under test were both
// read line by line and neither allocates. Whatever is doing it lives in the runner
// path, and 77 of this repo's 119 *.test.ts files import the same
// @happy-dom/global-registrator, so this file is not the only one carrying it.
//
// Rick's ruling, 2026-08-23: the worktree this came from is never touched again, and
// this file is preserved as a RECORD of intended behaviour, not as a runnable gate.
//
// Full incident: src/rnd/v0.2.0/2026.08.23-typescript-test-runner-oom-hazard.md
//
// ---------------------------------------------------------------------------------
// PHASE 4, CLAIM A — the Q&A card carries an argument interview to completion.
//
// THE GATE THIS FILE IS. The plan's phase-4 gate read "an agentic job completes end to
// end from the Q&A card alone", which packs two claims into one sentence; §7a now names
// them separately. Claim A is the card's half and it is what this file asserts. Claim B
// — the queue then drains the job — is CJ Flow's, lives on :8000, and is sequenced
// behind row 7451bebe. See 2026.08.22-qa-card-phase-4-observation-method.md.
//
// WHY THE OTHER TIERS ARE NOT DUPLICATED HERE. The endpoint half is already covered
// (test_v2_ask.py's resume tests) and the live server half is covered at integration
// tier by test_v2_resume_live.py, which proves the SHIPPED app parks a location-less
// weather question and accepts a resume. The card is the only uncovered half, and the
// card is what phase 4 adds.
//
// (The original file carried a `Run:` line here. It has been removed: see the
//  quarantine header above — running this is what kills the session.)

import { test, before } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import {
  isAnswerable,
  resumeBody,
  renderArgQuestion,
  clearArgQuestion,
  publishOnWindow,
} from "../../../lupin_app/static/js/shared/arg-interview.js";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

// The three shapes the flow emits on path "needs_input" — only the first is answerable.
// Field values follow flow.py:_needs_input / _submit_needs_input.
function parked(overrides: Record<string, unknown> = {}) {
  return {
    path: "needs_input", status: "parked", route_reason: "args_incomplete",
    answer: "What location?", command: "agent router go to weather",
    pending_id: "pend-1", args_missing: ["location"], args_known: [],
    ...overrides,
  };
}

// The submit door's NON-PARKING refusal: no pending_id, deliberately — there is no
// human behind a submit to answer it (v2_ask.py's own docstring says so).
function submitRefusal() {
  return parked({ status: "needs_input", pending_id: null });
}

// A park whose entry is gone. Resuming it would fail again.
function expired() {
  return parked({ status: "expired", pending_id: null, answer: "That request expired." });
}

function done() {
  return { path: "agent", status: "done", route_reason: "resumed", answer: "72F and sunny",
           command: "agent router go to weather", pending_id: null, args_missing: [] };
}

function freshContainer(): HTMLElement {
  const el = document.createElement("div");
  el.id = "qa-arg-interview";
  el.hidden = true;
  document.body.replaceChildren(el);
  return el;
}

// ===========================================================================
// isAnswerable — the distinction the whole module turns on
// ===========================================================================

test("a parked question with a pending_id is answerable", () => {
  assert.equal(isAnswerable(parked()), true);
});

test("the submit door's non-parking refusal is NOT answerable", () => {
  // path is "needs_input" but nothing was stored, so there is nothing to resume.
  // Rendering a box here gives the user an input whose submit cannot succeed.
  assert.equal(isAnswerable(submitRefusal()), false);
});

test("an expired park is NOT answerable", () => {
  assert.equal(isAnswerable(expired()), false);
});

test("a terminal result is not answerable", () => {
  assert.equal(isAnswerable(done()), false);
});

test("a question with no text is not answerable", () => {
  // A pending_id with nothing to ask would render an empty prompt above an input.
  assert.equal(isAnswerable(parked({ answer: "" })), false);
});

test("isAnswerable never throws on a missing or malformed result", () => {
  assert.equal(isAnswerable(null), false);
  assert.equal(isAnswerable(undefined), false);
  assert.equal(isAnswerable({} as never), false);
});

// ===========================================================================
// The render
// ===========================================================================

test("the question renders with an input and a submit button, and the box becomes visible", () => {
  const container = freshContainer();
  const wired = renderArgQuestion(container, parked());
  assert.ok(wired);
  assert.equal(container.hidden, false);
  assert.equal(container.querySelector(".qa-arg-question")?.textContent, "What location?");
  assert.equal(wired.input.tagName, "INPUT");
  assert.equal(wired.button.tagName, "BUTTON");
});

test("the input names the argument that stalled", () => {
  // So a reader of the DOM can see WHICH argument the flow is waiting on, not just
  // that it is waiting.
  const container = freshContainer();
  renderArgQuestion(container, parked());
  assert.equal(container.querySelector("input")?.getAttribute("data-arg"), "location");
});

test("a question with no args_missing still renders, without the arg attribute", () => {
  const container = freshContainer();
  renderArgQuestion(container, parked({ args_missing: [] }));
  assert.equal(container.querySelector("input")?.hasAttribute("data-arg"), false);
});

test("carries the testids the E2E suite locates it by", () => {
  const container = freshContainer();
  renderArgQuestion(container, parked());
  assert.ok(container.querySelector('[data-testid="notifications-qa-arg-input"]'));
  assert.ok(container.querySelector('[data-testid="notifications-qa-arg-submit-btn"]'));
});

test("an unanswerable result renders NOTHING and returns null", () => {
  // The caller-forgot-to-check case. A dead box that looks live is worse than no box.
  const container = freshContainer();
  assert.equal(renderArgQuestion(container, submitRefusal()), null);
  assert.equal(container.children.length, 0);
  assert.equal(container.hidden, true);
});

// ===========================================================================
// The multi-argument loop — the thing "to completion" actually means
// ===========================================================================

test("a second question REPLACES the first rather than stacking under it", () => {
  // A two-argument interview asks twice. Appending would leave three dead boxes down
  // the card, two of them carrying stale pending_ids.
  const container = freshContainer();
  renderArgQuestion(container, parked());
  renderArgQuestion(container, parked({ answer: "What budget?", pending_id: "pend-2", args_missing: ["budget"] }));
  assert.equal(container.querySelectorAll(".qa-arg-question").length, 1);
  assert.equal(container.querySelector(".qa-arg-question")?.textContent, "What budget?");
  assert.equal(container.querySelectorAll("input").length, 1);
});

test("the interview ends: a terminal result takes the box down", () => {
  const container = freshContainer();
  renderArgQuestion(container, parked());
  assert.equal(container.hidden, false);
  renderArgQuestion(container, done());
  assert.equal(container.children.length, 0);
  assert.equal(container.hidden, true);
});

test("clearArgQuestion empties AND hides", () => {
  // Emptied-but-visible leaves a stray gap in the card that reads as a rendering bug.
  const container = freshContainer();
  renderArgQuestion(container, parked());
  clearArgQuestion(container);
  assert.equal(container.children.length, 0);
  assert.equal(container.hidden, true);
});

test("clearArgQuestion is safe when nothing was rendered", () => {
  clearArgQuestion(freshContainer());
  clearArgQuestion(null as never);
});

// ===========================================================================
// The resume payload
// ===========================================================================

test("the answer is posted against the pending_id the question came with", () => {
  // Never one the caller invented: resume is only meaningful against the entry the
  // flow parked, and a mismatched id is an expired-shaped failure.
  assert.deepEqual(resumeBody(parked(), "Boston", "ws-1"), {
    pending_id: "pend-1", answer: "Boston", websocket_id: "ws-1",
  });
});

test("the second turn carries the SECOND pending_id, not the first", () => {
  // The loop's load-bearing detail: each resume returns a NEW pending_id, and
  // answering turn two against turn one's id resumes the wrong entry.
  const second = parked({ answer: "What budget?", pending_id: "pend-2", args_missing: ["budget"] });
  assert.equal(resumeBody(second, "50", "ws-1").pending_id, "pend-2");
});

// ===========================================================================
// The window publish
// ===========================================================================

test("publishOnWindow puts the full surface on the target", () => {
  const target: Record<string, Record<string, unknown>> = {};
  assert.equal(publishOnWindow(target), true);
  for (const name of ["isAnswerable", "resumeBody", "renderArgQuestion", "clearArgQuestion"]) {
    assert.equal(typeof target.LUPIN_ARG_INTERVIEW[name], "function", `missing ${name}`);
  }
});

test("publishOnWindow writes nothing when there is no global to write to", () => {
  assert.equal(publishOnWindow(null), false);
  assert.equal(publishOnWindow(undefined), false);
});
