// Parity A-2 #3b (row cca3da67, 2026-09-18, Chloé 🗼) — separate Pause and Play
// buttons with disabled states. Mirrors legacy `#tts-pause-btn` / `#tts-play-btn`
// (notifications.html:445-452, both starting disabled) and their enable rule
// `updateTTSPausePlayButtons` (notifications.js:23010-23032): nothing playing →
// both disabled; playing → Pause enabled, Play disabled; paused → Pause
// disabled, Play enabled. The multiplexer keys "playing" / "paused" on the audio
// machine, because AudioStore.pause() and resume() are no-ops outside those two
// states — an enabled button there would do nothing when clicked.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import {
  renderTtsChrome,
  type TtsChromeHandlers,
} from "../../../../lupin_app/static/js/multiplexer/render/templates/ttsChrome";
import type { AudioPlaybackState } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before(() => {
  if (typeof globalThis.document === "undefined") GlobalRegistrator.register();
});

function render(state: AudioPlaybackState): { el: HTMLElement; calls: { pause: number; resume: number } } {
  const calls = { pause: 0, resume: 0 };
  const handlers: TtsChromeHandlers = {
    onPause  : () => { calls.pause  += 1; },
    onResume : () => { calls.resume += 1; },
    onStop   : () => {},
    onSkip   : () => {},
  };
  return { el: renderTtsChrome({ state, queueLength: 0, queueEmpty: false }, handlers), calls };
}

function buttons(el: HTMLElement): { pause: HTMLButtonElement; play: HTMLButtonElement } {
  const pause = el.querySelector<HTMLButtonElement>('[data-testid="multiplexer-tts-pause-btn"]');
  const play  = el.querySelector<HTMLButtonElement>('[data-testid="multiplexer-tts-play-btn"]');
  assert.ok(pause !== null, "a dedicated Pause button exists (legacy #tts-pause-btn)");
  assert.ok(play  !== null, "a dedicated Play button exists (legacy #tts-play-btn)");
  return { pause, play };
}

test("#3b two buttons, not one toggle: Pause ⏸️ and Play ▶️ carry legacy's titles", () => {
  const { el } = render("playing");
  const { pause, play } = buttons(el);
  assert.ok(pause !== play, "two distinct buttons, not one toggle");
  assert.equal(pause.textContent, "⏸️");
  assert.equal(play.textContent,  "▶️");
  assert.equal(pause.title, "Pause playback");
  assert.equal(play.title,  "Resume playback");
  assert.ok(el.querySelector(".tts-btn-toggle") === null, "the single derived toggle is gone");
});

// The legacy three-branch rule, one row per audio state.
const MATRIX: ReadonlyArray<[ AudioPlaybackState, boolean, boolean ]> = [
  [ "idle",     false, false ],
  [ "decoding", false, false ],
  [ "playing",  true,  false ],
  [ "paused",   false, true  ],
  [ "ended",    false, false ],
  [ "error",    false, false ],
];

for (const [ state, pauseEnabled, playEnabled ] of MATRIX) {
  test(`#3b ${state}: Pause ${pauseEnabled ? "enabled" : "disabled"}, Play ${playEnabled ? "enabled" : "disabled"}`, () => {
    const { pause, play } = buttons(render(state).el);
    assert.equal(pause.disabled, !pauseEnabled);
    assert.equal(play.disabled,  !playEnabled);
    assert.equal(pause.classList.contains("disabled"), !pauseEnabled, "legacy's .disabled class mirrors the state");
    assert.equal(play.classList.contains("disabled"),  !playEnabled);
  });
}

test("#3b playing: Pause dispatches onPause; the disabled Play is inert", () => {
  const { el, calls } = render("playing");
  const { pause, play } = buttons(el);
  pause.click();
  play.click();
  assert.deepEqual(calls, { pause: 1, resume: 0 });
});

test("#3b paused: Play dispatches onResume; the disabled Pause is inert", () => {
  const { el, calls } = render("paused");
  const { pause, play } = buttons(el);
  pause.click();
  play.click();
  assert.deepEqual(calls, { pause: 0, resume: 1 });
});

test("#3b nothing playing: neither button dispatches", () => {
  const { el, calls } = render("idle");
  const { pause, play } = buttons(el);
  pause.click();
  play.click();
  assert.deepEqual(calls, { pause: 0, resume: 0 });
});
