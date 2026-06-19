// Multiplexer Phase 6b — ttsChrome template tests.
// AC4 floor: ≥15 tests per design doc § AC4 sub-table.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import {
  renderTtsChrome,
  type TtsChromeHandlers,
  type TtsChromeOpts,
} from "../../../../lupin_app/static/js/multiplexer/render/templates/ttsChrome";
import type { AudioPlaybackState } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

interface CallLog {
  pause  : number;
  resume : number;
  stop   : number;
  skip   : number;
}

function makeHandlers(): { handlers: TtsChromeHandlers; calls: CallLog } {
  const calls: CallLog = { pause: 0, resume: 0, stop: 0, skip: 0 };
  const handlers: TtsChromeHandlers = {
    onPause()  : void { calls.pause  += 1; },
    onResume() : void { calls.resume += 1; },
    onStop()   : void { calls.stop   += 1; },
    onSkip()   : void { calls.skip   += 1; },
  };
  return { handlers, calls };
}

function makeOpts(over: Partial<TtsChromeOpts> = {}): TtsChromeOpts {
  return { state: "idle", queueLength: 0, ...over };
}

// ---------------------------------------------------------------------------
// State-driven render (6 cases, one per AudioPlaybackState)
// ---------------------------------------------------------------------------

test("idle: all 3 controls disabled; no state-class on root", () => {
  const el = renderTtsChrome(makeOpts({ state: "idle" }), makeHandlers().handlers);
  const toggle = el.querySelector<HTMLButtonElement>(".tts-btn-toggle")!;
  const stop   = el.querySelector<HTMLButtonElement>(".tts-btn-stop")!;
  const skip   = el.querySelector<HTMLButtonElement>(".tts-btn-skip")!;
  assert.equal(toggle.disabled, true);
  assert.equal(stop.disabled,   true);
  assert.equal(skip.disabled,   true);
  assert.equal(el.classList.contains("is-playing-current"), false);
  assert.equal(el.classList.contains("is-paused-current"),  false);
  assert.equal(el.dataset.state, "idle");
});

test("decoding: all 3 controls disabled (transient)", () => {
  const el = renderTtsChrome(makeOpts({ state: "decoding" }), makeHandlers().handlers);
  assert.equal(el.querySelector<HTMLButtonElement>(".tts-btn-toggle")!.disabled, true);
  assert.equal(el.querySelector<HTMLButtonElement>(".tts-btn-stop")!.disabled,   true);
  assert.equal(el.querySelector<HTMLButtonElement>(".tts-btn-skip")!.disabled,   true);
  assert.equal(el.dataset.state, "decoding");
});

test("playing: toggle label='Pause' enabled; stop+skip enabled; .is-playing-current class set", () => {
  const el = renderTtsChrome(makeOpts({ state: "playing" }), makeHandlers().handlers);
  const toggle = el.querySelector<HTMLButtonElement>(".tts-btn-toggle")!;
  assert.equal(toggle.disabled, false);
  assert.equal(toggle.textContent, "Pause");
  assert.equal(toggle.dataset.action, "pause");
  assert.equal(el.querySelector<HTMLButtonElement>(".tts-btn-stop")!.disabled, false);
  assert.equal(el.querySelector<HTMLButtonElement>(".tts-btn-skip")!.disabled, false);
  assert.ok(el.classList.contains("is-playing-current"), "playing root carries .is-playing-current");
});

test("paused: toggle label='Resume' enabled; stop+skip enabled; .is-paused-current class set", () => {
  const el = renderTtsChrome(makeOpts({ state: "paused" }), makeHandlers().handlers);
  const toggle = el.querySelector<HTMLButtonElement>(".tts-btn-toggle")!;
  assert.equal(toggle.disabled, false);
  assert.equal(toggle.textContent, "Resume");
  assert.equal(toggle.dataset.action, "resume");
  assert.equal(el.querySelector<HTMLButtonElement>(".tts-btn-stop")!.disabled, false);
  assert.equal(el.querySelector<HTMLButtonElement>(".tts-btn-skip")!.disabled, false);
  assert.ok(el.classList.contains("is-paused-current"), "paused root carries .is-paused-current");
});

test("ended: toggle disabled; stop enabled (per AudioStore.stop ended→idle); skip disabled", () => {
  const el = renderTtsChrome(makeOpts({ state: "ended" }), makeHandlers().handlers);
  assert.equal(el.querySelector<HTMLButtonElement>(".tts-btn-toggle")!.disabled, true);
  assert.equal(el.querySelector<HTMLButtonElement>(".tts-btn-stop")!.disabled,   false);
  assert.equal(el.querySelector<HTMLButtonElement>(".tts-btn-skip")!.disabled,   true);
});

test("error: toggle disabled; stop enabled (recovery to idle); skip disabled", () => {
  const el = renderTtsChrome(makeOpts({ state: "error" }), makeHandlers().handlers);
  assert.equal(el.querySelector<HTMLButtonElement>(".tts-btn-toggle")!.disabled, true);
  assert.equal(el.querySelector<HTMLButtonElement>(".tts-btn-stop")!.disabled,   false);
  assert.equal(el.querySelector<HTMLButtonElement>(".tts-btn-skip")!.disabled,   true);
});

// ---------------------------------------------------------------------------
// Click dispatch (4 cases — Pause / Resume / Stop / Skip)
// ---------------------------------------------------------------------------

test("playing toggle click dispatches onPause", () => {
  const { handlers, calls } = makeHandlers();
  const el = renderTtsChrome(makeOpts({ state: "playing" }), handlers);
  el.querySelector<HTMLButtonElement>(".tts-btn-toggle")!.click();
  assert.equal(calls.pause, 1);
  assert.equal(calls.resume, 0);
});

test("paused toggle click dispatches onResume", () => {
  const { handlers, calls } = makeHandlers();
  const el = renderTtsChrome(makeOpts({ state: "paused" }), handlers);
  el.querySelector<HTMLButtonElement>(".tts-btn-toggle")!.click();
  assert.equal(calls.resume, 1);
  assert.equal(calls.pause,  0);
});

test("Stop click dispatches onStop (when enabled)", () => {
  const { handlers, calls } = makeHandlers();
  const el = renderTtsChrome(makeOpts({ state: "playing" }), handlers);
  el.querySelector<HTMLButtonElement>(".tts-btn-stop")!.click();
  assert.equal(calls.stop, 1);
});

test("Skip click dispatches onSkip (when enabled)", () => {
  const { handlers, calls } = makeHandlers();
  const el = renderTtsChrome(makeOpts({ state: "playing" }), handlers);
  el.querySelector<HTMLButtonElement>(".tts-btn-skip")!.click();
  assert.equal(calls.skip, 1);
});

// ---------------------------------------------------------------------------
// currentTrackName + queueLength rendering
// ---------------------------------------------------------------------------

test("currentTrackName rendered when present", () => {
  const el = renderTtsChrome(
    makeOpts({ state: "playing", currentTrackName: "Demo Track #1" }),
    makeHandlers().handlers,
  );
  const track = el.querySelector(".tts-current-track");
  assert.notEqual(track, null);
  assert.match(track!.textContent ?? "", /Playing: Demo Track #1/);
});

test("currentTrackName absent → no .tts-current-track element rendered", () => {
  const el = renderTtsChrome(makeOpts({ state: "playing" }), makeHandlers().handlers);
  assert.equal(el.querySelector(".tts-current-track"), null);
});

test("currentTrackName empty string → no .tts-current-track element rendered (covers '' branch)", () => {
  const el = renderTtsChrome(
    makeOpts({ state: "playing", currentTrackName: "" }),
    makeHandlers().handlers,
  );
  assert.equal(el.querySelector(".tts-current-track"), null);
});

test("queueLength rendered with Queued: prefix + dataset attribute", () => {
  const el = renderTtsChrome(makeOpts({ state: "playing", queueLength: 7 }), makeHandlers().handlers);
  const ql = el.querySelector<HTMLElement>(".tts-queue-length")!;
  assert.match(ql.textContent ?? "", /Queued: 7/);
  assert.equal(ql.dataset.queueLength, "7");
});

// ---------------------------------------------------------------------------
// Storm safety + multi-instance independence
// ---------------------------------------------------------------------------

test("multi-instance independence: two chrome instances dispatch to their own handlers", () => {
  const a = makeHandlers();
  const b = makeHandlers();
  const elA = renderTtsChrome(makeOpts({ state: "playing" }), a.handlers);
  const elB = renderTtsChrome(makeOpts({ state: "paused"  }), b.handlers);
  elA.querySelector<HTMLButtonElement>(".tts-btn-toggle")!.click();   // A: Pause
  elB.querySelector<HTMLButtonElement>(".tts-btn-toggle")!.click();   // B: Resume
  assert.equal(a.calls.pause,  1);
  assert.equal(a.calls.resume, 0);
  assert.equal(b.calls.resume, 1);
  assert.equal(b.calls.pause,  0);
});

test("disabled controls are non-interactive (clicks on disabled stop in idle state are no-ops)", () => {
  const { handlers, calls } = makeHandlers();
  const el = renderTtsChrome(makeOpts({ state: "idle" }), handlers);
  // Force the click anyway; disabled buttons in browsers don't fire listeners,
  // and our renderer attaches listeners conditionally on enabled-state, so calls stay 0.
  el.querySelector<HTMLButtonElement>(".tts-btn-stop")!.click();
  el.querySelector<HTMLButtonElement>(".tts-btn-skip")!.click();
  el.querySelector<HTMLButtonElement>(".tts-btn-toggle")!.click();
  assert.equal(calls.stop,   0);
  assert.equal(calls.skip,   0);
  assert.equal(calls.pause,  0);
  assert.equal(calls.resume, 0);
});

test("data-testid + data-state always set for E2E observability", () => {
  for (const s of ["idle", "decoding", "playing", "paused", "ended", "error"] as AudioPlaybackState[]) {
    const el = renderTtsChrome(makeOpts({ state: s }), makeHandlers().handlers);
    assert.equal(el.getAttribute("data-testid"), "multiplexer-tts-chrome", `testid for ${s}`);
    assert.equal(el.dataset.state, s, `dataset.state for ${s}`);
  }
});

// ---------------------------------------------------------------------------
// AC2e safe-write invariant (Pass 2 a1) — grep ban on unsafe HTML write sinks
// ---------------------------------------------------------------------------

test("AC2e: source file contains zero .innerHTML= / rawHTML( / .outerHTML= sinks", () => {
  const src = readFileSync(
    "src/lupin_app/static/js/multiplexer/render/templates/ttsChrome.ts",
    "utf8",
  );
  const stripped = src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\/\/.*$/gm, "");
  const banned = [
    /\.innerHTML\s*=/,
    /\brawHTML\s*\(/,
    /\.outerHTML\s*=/,
  ];
  for (const re of banned) {
    assert.equal(re.test(stripped), false, `AC2e violation: pattern ${re} found in ttsChrome.ts`);
  }
});
