// P0 5ebd2aff (2026-09-10) — the multiplexer TTS preview slider shares its value
// with the legacy client. Run via
// `npx tsx --test src/tests/unit/multiplexer/render/tts_preview_fraction_shared_with_legacy.test.ts`.
//
// Measured in Rick's browser before the fix: legacy key
// `notifications_tts_preview_fraction_runtime` = 0.125 (12.5 %), multiplexer
// `lupin:tts_preview_fraction` = 0 (0 %). One setting, two stores.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import {
  createTtsPreviewSliderRenderer,
  readLegacyFraction,
  LEGACY_TTS_FRACTION_KEY,
  TTS_FRACTION_STORAGE_KEY,
  TTS_FRACTION_STORAGE_SCHEMA,
  type SharedFractionStorage,
} from "../../../../lupin_app/static/js/multiplexer/render/TtsPreviewSliderRenderer";
import { createStorageServiceForTesting, type StorageService } from "../../../../lupin_app/static/js/multiplexer/shared/StorageService";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

function fakeShared(initial: Record<string, string> = {}): SharedFractionStorage & { data: Record<string, string> } {
  const data = { ...initial };
  return {
    data,
    getItem: (k: string) => (k in data ? data[k] as string : null),
    setItem: (k: string, v: string) => { data[k] = v; },
  };
}

function envelope(fraction: number): StorageService {
  const storage = createStorageServiceForTesting();
  storage.setJSON<{ fraction: number }>(TTS_FRACTION_STORAGE_KEY, { fraction }, TTS_FRACTION_STORAGE_SCHEMA);
  return storage;
}

test("Rick's measured state: legacy 0.125 beats the multiplexer's own 0 → slider shows 12.5%", () => {
  const r = createTtsPreviewSliderRenderer({
    storage: envelope(0), iniDefaultFraction: 0.25, sharedStorage: fakeShared({ [LEGACY_TTS_FRACTION_KEY]: "0.125" }),
  });
  assert.equal(r.getFraction(), 0.125);
  const root = document.createElement("div");
  r.mount(root);
  assert.equal(root.querySelector<HTMLInputElement>(".tts-preview-slider-input")!.value, "12.5");
});

test("no legacy value → the multiplexer's own stored override still applies (back-compat)", () => {
  const r = createTtsPreviewSliderRenderer({ storage: envelope(0.5), iniDefaultFraction: 0.25, sharedStorage: fakeShared() });
  assert.equal(r.getFraction(), 0.5);
});

test("a legacy value counts as a user override — a late INI seed does not clobber it", () => {
  const r = createTtsPreviewSliderRenderer({
    storage: createStorageServiceForTesting(), iniDefaultFraction: 0.25, sharedStorage: fakeShared({ [LEGACY_TTS_FRACTION_KEY]: "0.75" }),
  });
  r.seedIniDefault(0.1);
  assert.equal(r.getFraction(), 0.75);
});

test("moving the slider writes the legacy raw key AND the envelope", () => {
  const shared  = fakeShared();
  const storage = createStorageServiceForTesting();
  const r = createTtsPreviewSliderRenderer({ storage, iniDefaultFraction: 0.25, sharedStorage: shared });
  const root = document.createElement("div");
  r.mount(root);
  const input = root.querySelector<HTMLInputElement>(".tts-preview-slider-input")!;
  input.value = "37.5";
  input.dispatchEvent(new Event("input", { bubbles: true }));
  assert.equal(shared.data[LEGACY_TTS_FRACTION_KEY], "0.375");
  assert.equal(storage.getJSON<{ fraction: number }>(TTS_FRACTION_STORAGE_KEY, TTS_FRACTION_STORAGE_SCHEMA)?.fraction, 0.375);
});

test("readLegacyFraction: missing, blank, non-numeric and out-of-range values are ignored", () => {
  assert.equal(readLegacyFraction(null), null);
  assert.equal(readLegacyFraction(fakeShared()), null);
  assert.equal(readLegacyFraction(fakeShared({ [LEGACY_TTS_FRACTION_KEY]: "" })), null);
  assert.equal(readLegacyFraction(fakeShared({ [LEGACY_TTS_FRACTION_KEY]: "abc" })), null);
  assert.equal(readLegacyFraction(fakeShared({ [LEGACY_TTS_FRACTION_KEY]: "2" })), null);
  assert.equal(readLegacyFraction(fakeShared({ [LEGACY_TTS_FRACTION_KEY]: "0" })), 0);
});

test("storage that THROWS (blocked site data) neither crashes the read nor the slider move", () => {
  const throwing: SharedFractionStorage = {
    getItem: () => { throw new Error("SecurityError"); },
    setItem: () => { throw new Error("SecurityError"); },
  };
  assert.equal(readLegacyFraction(throwing), null);
  const storage = envelope(0.5);
  const r = createTtsPreviewSliderRenderer({ storage, iniDefaultFraction: 0.25, sharedStorage: throwing });
  assert.equal(r.getFraction(), 0.5);
  const root = document.createElement("div");
  r.mount(root);
  const input = root.querySelector<HTMLInputElement>(".tts-preview-slider-input")!;
  input.value = "62.5";
  assert.doesNotThrow(() => input.dispatchEvent(new Event("input", { bubbles: true })));
  assert.equal(r.getFraction(), 0.625);
});

test("sharedStorage: null → envelope-only behaviour, no writes attempted", () => {
  const r = createTtsPreviewSliderRenderer({ storage: envelope(0.125), iniDefaultFraction: 0.25, sharedStorage: null });
  assert.equal(r.getFraction(), 0.125);
});
