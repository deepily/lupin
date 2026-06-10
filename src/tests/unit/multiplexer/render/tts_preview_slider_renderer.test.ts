// Multiplexer Lane E WP13 — TtsPreviewSliderRenderer unit tests.
// 100% lines/branches/functions per the multiplexer coverage mandate.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import {
  createTtsPreviewSliderRenderer,
  clampFraction,
  resolveInitialFraction,
  DEFAULT_TTS_FRACTION,
  TTS_FRACTION_STORAGE_KEY,
  TTS_FRACTION_STORAGE_SCHEMA,
} from "../../../../lupin_app/static/js/multiplexer/render/TtsPreviewSliderRenderer";
import {
  createStorageServiceForTesting,
  type StorageService,
} from "../../../../lupin_app/static/js/multiplexer/shared/StorageService";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

interface StoredFraction { fraction: number; }

function seedStorage(fraction: number): StorageService {
  const storage = createStorageServiceForTesting();
  storage.setJSON<StoredFraction>(TTS_FRACTION_STORAGE_KEY, { fraction }, TTS_FRACTION_STORAGE_SCHEMA);
  return storage;
}

// ---------------------------------------------------------------------------
// clampFraction
// ---------------------------------------------------------------------------

test("clampFraction accepts valid fractions in [0,1]", () => {
  assert.equal(clampFraction(0), 0);
  assert.equal(clampFraction(0.25), 0.25);
  assert.equal(clampFraction(1), 1);
});

test("clampFraction rejects non-numbers", () => {
  assert.equal(clampFraction("0.5"), null);
  assert.equal(clampFraction(null), null);
  assert.equal(clampFraction(undefined), null);
  assert.equal(clampFraction({}), null);
});

test("clampFraction rejects non-finite numbers", () => {
  assert.equal(clampFraction(NaN), null);
  assert.equal(clampFraction(Infinity), null);
  assert.equal(clampFraction(-Infinity), null);
});

test("clampFraction rejects out-of-range numbers", () => {
  assert.equal(clampFraction(-0.01), null);
  assert.equal(clampFraction(1.01), null);
});

// ---------------------------------------------------------------------------
// resolveInitialFraction
// ---------------------------------------------------------------------------

test("resolveInitialFraction: valid stored override wins over INI default", () => {
  assert.equal(resolveInitialFraction(0.75, 0.25), 0.75);
});

test("resolveInitialFraction: invalid stored falls back to INI default", () => {
  assert.equal(resolveInitialFraction(null, 0.5), 0.5);
  assert.equal(resolveInitialFraction(2, 0.5), 0.5);
});

test("resolveInitialFraction: both invalid falls back to DEFAULT_TTS_FRACTION", () => {
  assert.equal(resolveInitialFraction(null, NaN), DEFAULT_TTS_FRACTION);
  assert.equal(resolveInitialFraction("x", undefined), DEFAULT_TTS_FRACTION);
});

// ---------------------------------------------------------------------------
// Construction — fraction resolution from storage + INI
// ---------------------------------------------------------------------------

test("constructor uses INI default when no stored override", () => {
  const storage = createStorageServiceForTesting();
  const r = createTtsPreviewSliderRenderer({ storage, iniDefaultFraction: 0.5 });
  assert.equal(r.getFraction(), 0.5);
});

test("constructor uses valid stored override over INI default", () => {
  const storage = seedStorage(0.875);
  const r = createTtsPreviewSliderRenderer({ storage, iniDefaultFraction: 0.25 });
  assert.equal(r.getFraction(), 0.875);
});

test("constructor ignores out-of-range stored override, falls back to INI", () => {
  const storage = seedStorage(5); // out of range; resolveInitialFraction rejects
  const r = createTtsPreviewSliderRenderer({ storage, iniDefaultFraction: 0.125 });
  assert.equal(r.getFraction(), 0.125);
});

// ---------------------------------------------------------------------------
// mount / render
// ---------------------------------------------------------------------------

test("mount renders slider seeded to the resolved percent", () => {
  const storage = seedStorage(0.375);
  const r = createTtsPreviewSliderRenderer({ storage, iniDefaultFraction: 0.25 });
  const root = document.createElement("div");
  r.mount(root);
  const input = root.querySelector<HTMLInputElement>(".tts-preview-slider-input");
  const label = root.querySelector(".tts-preview-slider-value");
  assert.equal(input?.getAttribute("value"), "37.5");
  assert.equal(label?.textContent, "37.5%");
});

test("second mount without unmount throws", () => {
  const storage = createStorageServiceForTesting();
  const r = createTtsPreviewSliderRenderer({ storage, iniDefaultFraction: 0.25 });
  r.mount(document.createElement("div"));
  assert.throws(() => r.mount(document.createElement("div")), /already mounted/);
});

// ---------------------------------------------------------------------------
// Input handler — fraction update + label + persistence + onChange
// ---------------------------------------------------------------------------

test("slider input updates fraction, label, persists, and fires onChange", () => {
  const storage = createStorageServiceForTesting();
  const changes: number[] = [];
  const r = createTtsPreviewSliderRenderer({
    storage,
    iniDefaultFraction: 0.25,
    onChange: (f) => changes.push(f),
  });
  const root = document.createElement("div");
  r.mount(root);

  const input = root.querySelector<HTMLInputElement>(".tts-preview-slider-input");
  assert.ok(input);
  input.value = "62.5";
  input.dispatchEvent(new Event("input"));

  assert.equal(r.getFraction(), 0.625);
  assert.equal(root.querySelector(".tts-preview-slider-value")?.textContent, "62.5%");
  assert.deepEqual(changes, [0.625]);

  // Persisted: a fresh renderer reads it back as the override.
  const r2 = createTtsPreviewSliderRenderer({ storage, iniDefaultFraction: 0.25 });
  assert.equal(r2.getFraction(), 0.625);
});

test("slider input works without an onChange callback (optional)", () => {
  const storage = createStorageServiceForTesting();
  const r = createTtsPreviewSliderRenderer({ storage, iniDefaultFraction: 0.25 });
  const root = document.createElement("div");
  r.mount(root);
  const input = root.querySelector<HTMLInputElement>(".tts-preview-slider-input");
  assert.ok(input);
  input.value = "0";
  assert.doesNotThrow(() => input.dispatchEvent(new Event("input")));
  assert.equal(r.getFraction(), 0);
});

// ---------------------------------------------------------------------------
// unmount
// ---------------------------------------------------------------------------

test("unmount clears the DOM and allows a re-mount", () => {
  const storage = createStorageServiceForTesting();
  const r = createTtsPreviewSliderRenderer({ storage, iniDefaultFraction: 0.25 });
  const root = document.createElement("div");
  r.mount(root);
  assert.ok(root.querySelector(".tts-preview-slider"));
  r.unmount();
  assert.equal(root.querySelector(".tts-preview-slider"), null);
  assert.doesNotThrow(() => r.mount(root));
});

test("unmount before mount is a no-op (idempotent)", () => {
  const storage = createStorageServiceForTesting();
  const r = createTtsPreviewSliderRenderer({ storage, iniDefaultFraction: 0.25 });
  assert.doesNotThrow(() => r.unmount());
  assert.doesNotThrow(() => r.unmount());
});

// ---------------------------------------------------------------------------
// seedIniDefault — late INI default from the non-blocking config fetch
// ---------------------------------------------------------------------------

test("seedIniDefault updates fraction + live DOM when no user override", () => {
  const storage = createStorageServiceForTesting(); // no stored override
  const r = createTtsPreviewSliderRenderer({ storage, iniDefaultFraction: 0.25 });
  const root = document.createElement("div");
  r.mount(root);
  r.seedIniDefault(0.5);
  assert.equal(r.getFraction(), 0.5);
  assert.equal(root.querySelector<HTMLInputElement>(".tts-preview-slider-input")?.value, "50");
  assert.equal(root.querySelector(".tts-preview-slider-value")?.textContent, "50%");
});

test("seedIniDefault is a no-op when a stored override exists", () => {
  const storage = seedStorage(0.875);
  const r = createTtsPreviewSliderRenderer({ storage, iniDefaultFraction: 0.25 });
  r.mount(document.createElement("div"));
  r.seedIniDefault(0.5);
  assert.equal(r.getFraction(), 0.875); // user override preserved
});

test("seedIniDefault is a no-op after the user moves the slider this session", () => {
  const storage = createStorageServiceForTesting();
  const r = createTtsPreviewSliderRenderer({ storage, iniDefaultFraction: 0.25 });
  const root = document.createElement("div");
  r.mount(root);
  const input = root.querySelector<HTMLInputElement>(".tts-preview-slider-input")!;
  input.value = "75";
  input.dispatchEvent(new Event("input"));
  r.seedIniDefault(0.5);
  assert.equal(r.getFraction(), 0.75); // session move wins
});

test("seedIniDefault ignores an out-of-range value", () => {
  const storage = createStorageServiceForTesting();
  const r = createTtsPreviewSliderRenderer({ storage, iniDefaultFraction: 0.25 });
  r.mount(document.createElement("div"));
  r.seedIniDefault(5);
  assert.equal(r.getFraction(), 0.25);
});

test("seedIniDefault before mount updates fraction without touching DOM", () => {
  const storage = createStorageServiceForTesting();
  const r = createTtsPreviewSliderRenderer({ storage, iniDefaultFraction: 0.25 });
  r.seedIniDefault(0.625); // not mounted: input/label null branches
  assert.equal(r.getFraction(), 0.625);
});
