// Multiplexer Lane E WP13 — ttsPreviewSlider template tests.
// 100% lines/branches/functions per the multiplexer coverage mandate.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import {
  renderTtsPreviewSlider,
  TTS_FRACTION_STOPS_PCT,
  type TtsPreviewSliderHandlers,
} from "../../../../lupin_app/static/js/multiplexer/render/templates/ttsPreviewSlider";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

function makeHandlers(): { handlers: TtsPreviewSliderHandlers; calls: number[] } {
  const calls: number[] = [];
  const handlers: TtsPreviewSliderHandlers = {
    onInput( percent: number ): void { calls.push(percent); },
  };
  return { handlers, calls };
}

// ---------------------------------------------------------------------------
// Structure
// ---------------------------------------------------------------------------

test("renders a .tts-preview-slider root with data-testid", () => {
  const { handlers } = makeHandlers();
  const el = renderTtsPreviewSlider({ percent: 25 }, handlers);
  assert.ok(el.classList.contains("tts-preview-slider"));
  assert.equal(el.getAttribute("data-testid"), "multiplexer-tts-preview-slider");
});

test("range input has min=0 / max=100 / step=12.5 + list binding", () => {
  const { handlers } = makeHandlers();
  const el = renderTtsPreviewSlider({ percent: 25 }, handlers);
  const input = el.querySelector<HTMLInputElement>(".tts-preview-slider-input");
  assert.ok(input);
  assert.equal(input.getAttribute("type"), "range");
  assert.equal(input.getAttribute("min"), "0");
  assert.equal(input.getAttribute("max"), "100");
  assert.equal(input.getAttribute("step"), "12.5");
  assert.equal(input.getAttribute("list"), "cc-tts-fraction-ticks");
});

test("datalist renders exactly 9 option ticks matching the canonical stops", () => {
  const { handlers } = makeHandlers();
  const el = renderTtsPreviewSlider({ percent: 50 }, handlers);
  const opts = el.querySelectorAll(".tts-preview-slider-ticks option");
  assert.equal(opts.length, TTS_FRACTION_STOPS_PCT.length);
  assert.equal(opts.length, 9);
  const values = Array.from(opts).map((o) => o.getAttribute("value"));
  assert.deepEqual(values, TTS_FRACTION_STOPS_PCT.map(String));
});

test("value label is seeded from opts.percent with a % suffix", () => {
  const { handlers } = makeHandlers();
  const el = renderTtsPreviewSlider({ percent: 37.5 }, handlers);
  const label = el.querySelector(".tts-preview-slider-value");
  assert.ok(label);
  assert.equal(label.textContent, "37.5%");
  const input = el.querySelector<HTMLInputElement>(".tts-preview-slider-input");
  assert.equal(input?.getAttribute("value"), "37.5");
});

// ---------------------------------------------------------------------------
// Input handler
// ---------------------------------------------------------------------------

test("input event fires onInput with parseFloat'd value (off-integer stop preserved)", () => {
  const { handlers, calls } = makeHandlers();
  const el = renderTtsPreviewSlider({ percent: 25 }, handlers);
  const input = el.querySelector<HTMLInputElement>(".tts-preview-slider-input");
  assert.ok(input);
  input.value = "62.5";
  input.dispatchEvent(new Event("input"));
  assert.deepEqual(calls, [62.5]);
});

test("integer stop also flows through onInput", () => {
  const { handlers, calls } = makeHandlers();
  const el = renderTtsPreviewSlider({ percent: 0 }, handlers);
  const input = el.querySelector<HTMLInputElement>(".tts-preview-slider-input");
  assert.ok(input);
  input.value = "100";
  input.dispatchEvent(new Event("input"));
  assert.deepEqual(calls, [100]);
});

// ---------------------------------------------------------------------------
// Safe-write invariant (mirrors ttsChrome AC2e)
// ---------------------------------------------------------------------------

test("source file contains zero .innerHTML= / rawHTML( / .outerHTML= sinks", () => {
  const src = readFileSync(
    "src/lupin_app/static/js/multiplexer/render/templates/ttsPreviewSlider.ts",
    "utf8",
  );
  const stripped = src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\/\/.*$/gm, "");
  const banned = [/\.innerHTML\s*=/, /\brawHTML\s*\(/, /\.outerHTML\s*=/];
  for (const re of banned) {
    assert.equal(re.test(stripped), false, `safe-write violation: ${re} in ttsPreviewSlider.ts`);
  }
});
