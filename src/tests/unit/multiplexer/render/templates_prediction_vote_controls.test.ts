// Multiplexer Lane E WP14 — predictionVoteControls template tests.
// 100% lines/branches/functions per the multiplexer coverage mandate.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import {
  renderPredictionVoteControls,
  type PredictionVoteHandlers,
} from "../../../../lupin_app/static/js/multiplexer/render/templates/predictionVoteControls";
import { PREDICTION_VOTE_MIN_PCT } from "../../../../lupin_app/static/js/multiplexer/stores/PredictionVoteStore";
import type { PredictionVoteDir } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

function makeHandlers(): { handlers: PredictionVoteHandlers; votes: PredictionVoteDir[] } {
  const votes: PredictionVoteDir[] = [];
  const handlers: PredictionVoteHandlers = { onVote(dir): void { votes.push(dir); } };
  return { handlers, votes };
}

// ---------------------------------------------------------------------------
// Gate
// ---------------------------------------------------------------------------

test("returns null when notificationId is empty", () => {
  const { handlers } = makeHandlers();
  assert.equal(renderPredictionVoteControls({ notificationId: "", confidencePct: 90 }, handlers), null);
});

test("returns null when confidence is below the 50% threshold", () => {
  const { handlers } = makeHandlers();
  assert.equal(renderPredictionVoteControls({ notificationId: "n1", confidencePct: 49 }, handlers), null);
});

test("renders at exactly the threshold (>= gate, not >)", () => {
  const { handlers } = makeHandlers();
  const el = renderPredictionVoteControls({ notificationId: "n1", confidencePct: PREDICTION_VOTE_MIN_PCT }, handlers);
  assert.ok(el);
  assert.ok(el.classList.contains("prediction-hint-vote"));
});

// ---------------------------------------------------------------------------
// Structure
// ---------------------------------------------------------------------------

test("renders up + down buttons with testids + medium-light-skin glyphs", () => {
  const { handlers } = makeHandlers();
  const el = renderPredictionVoteControls({ notificationId: "n1", confidencePct: 80 }, handlers)!;
  const up = el.querySelector<HTMLButtonElement>(".prediction-vote-up");
  const down = el.querySelector<HTMLButtonElement>(".prediction-vote-down");
  assert.ok(up);
  assert.ok(down);
  assert.equal(up.getAttribute("data-testid"), "prediction-vote-up");
  assert.equal(down.getAttribute("data-testid"), "prediction-vote-down");
  assert.equal(up.textContent, "👍🏼");
  assert.equal(down.textContent, "👎🏼");
});

test("no inline onclick attribute (delegated listeners only)", () => {
  const { handlers } = makeHandlers();
  const el = renderPredictionVoteControls({ notificationId: "n1", confidencePct: 80 }, handlers)!;
  for (const btn of Array.from(el.querySelectorAll("button"))) {
    assert.equal(btn.getAttribute("onclick"), null);
  }
});

// ---------------------------------------------------------------------------
// Click delegation
// ---------------------------------------------------------------------------

test("up button click fires onVote('up')", () => {
  const { handlers, votes } = makeHandlers();
  const el = renderPredictionVoteControls({ notificationId: "n1", confidencePct: 80 }, handlers)!;
  el.querySelector<HTMLButtonElement>(".prediction-vote-up")!.click();
  assert.deepEqual(votes, ["up"]);
});

test("down button click fires onVote('down')", () => {
  const { handlers, votes } = makeHandlers();
  const el = renderPredictionVoteControls({ notificationId: "n1", confidencePct: 80 }, handlers)!;
  el.querySelector<HTMLButtonElement>(".prediction-vote-down")!.click();
  assert.deepEqual(votes, ["down"]);
});

// ---------------------------------------------------------------------------
// Optimistic local highlight on click (markSelected) — instant feedback before
// the POST round-trips; the orchestrator reconciles afterward.
// ---------------------------------------------------------------------------

test("up click optimistically marks root .voted + up .selected (before any reconcile)", () => {
  const { handlers } = makeHandlers();
  const el = renderPredictionVoteControls({ notificationId: "n1", confidencePct: 80 }, handlers)!;
  el.querySelector<HTMLButtonElement>(".prediction-vote-up")!.click();
  assert.ok(el.classList.contains("voted"));
  assert.ok(el.querySelector(".prediction-vote-up")!.classList.contains("selected"));
  assert.equal(el.querySelector(".prediction-vote-down")!.classList.contains("selected"), false);
});

test("clicking down then up toggles the optimistic selection (only the latest is .selected)", () => {
  const { handlers } = makeHandlers();
  const el = renderPredictionVoteControls({ notificationId: "n1", confidencePct: 80 }, handlers)!;
  el.querySelector<HTMLButtonElement>(".prediction-vote-down")!.click();
  assert.ok(el.querySelector(".prediction-vote-down")!.classList.contains("selected"));
  el.querySelector<HTMLButtonElement>(".prediction-vote-up")!.click();
  assert.ok(el.querySelector(".prediction-vote-up")!.classList.contains("selected"));
  assert.equal(el.querySelector(".prediction-vote-down")!.classList.contains("selected"), false);
  assert.ok(el.classList.contains("voted"));
});

// ---------------------------------------------------------------------------
// castVote reflection
// ---------------------------------------------------------------------------

test("no castVote → root has no .voted and neither button is .selected", () => {
  const { handlers } = makeHandlers();
  const el = renderPredictionVoteControls({ notificationId: "n1", confidencePct: 80 }, handlers)!;
  assert.equal(el.classList.contains("voted"), false);
  assert.equal(el.querySelector(".prediction-vote-up")!.classList.contains("selected"), false);
  assert.equal(el.querySelector(".prediction-vote-down")!.classList.contains("selected"), false);
});

test("castVote='up' marks root .voted + up button .selected", () => {
  const { handlers } = makeHandlers();
  const el = renderPredictionVoteControls({ notificationId: "n1", confidencePct: 80, castVote: "up" }, handlers)!;
  assert.ok(el.classList.contains("voted"));
  assert.ok(el.querySelector(".prediction-vote-up")!.classList.contains("selected"));
  assert.equal(el.querySelector(".prediction-vote-down")!.classList.contains("selected"), false);
});

test("castVote='down' marks root .voted + down button .selected", () => {
  const { handlers } = makeHandlers();
  const el = renderPredictionVoteControls({ notificationId: "n1", confidencePct: 80, castVote: "down" }, handlers)!;
  assert.ok(el.classList.contains("voted"));
  assert.ok(el.querySelector(".prediction-vote-down")!.classList.contains("selected"));
  assert.equal(el.querySelector(".prediction-vote-up")!.classList.contains("selected"), false);
});

// ---------------------------------------------------------------------------
// Safe-write invariant
// ---------------------------------------------------------------------------

test("source file contains zero .innerHTML= / rawHTML( / .outerHTML= sinks + no inline onclick string", () => {
  const src = readFileSync(
    "src/lupin_app/static/js/multiplexer/render/templates/predictionVoteControls.ts",
    "utf8",
  );
  const stripped = src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\/\/.*$/gm, "");
  const banned = [/\.innerHTML\s*=/, /\brawHTML\s*\(/, /\.outerHTML\s*=/, /onclick=/];
  for (const re of banned) {
    assert.equal(re.test(stripped), false, `violation: ${re} in predictionVoteControls.ts`);
  }
});
