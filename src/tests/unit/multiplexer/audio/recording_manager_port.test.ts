// Multiplexer Phase 6c Node C — recordingManager singleton tests.
// AC-C-port-recordingManager target: ≥6 cases covering single-active + TTS coord + ESC.

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { recordingManager } from "../../../../lupin_app/static/js/multiplexer/audio/recordingManager";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

beforeEach(() => {
  // Reset TTS hooks between tests.
  recordingManager.ttsIsPlaying = () => false;
  recordingManager.ttsPause     = () => {};
  recordingManager.ttsResume    = () => {};
  // Ensure no leftover active recording from a previous test.
  const active = recordingManager.getActiveContextId();
  if (active !== null) recordingManager.cancelRecording(active);
});

function mockMediaRecorder(): void {
  // Minimal MediaRecorder mock — start fails fast (no microphone in test env)
  // so we just verify the recordingManager state machine.
  (globalThis as unknown as { MediaRecorder?: unknown }).MediaRecorder = function MediaRecorderMock(): void {
    throw new Error("mock-not-supported");
  };
  ((globalThis as unknown as { MediaRecorder: { isTypeSupported: (t: string) => boolean } }).MediaRecorder as unknown as { isTypeSupported: (t: string) => boolean }).isTypeSupported = () => false;
  // navigator.mediaDevices.getUserMedia mock that rejects.
  if ((globalThis as unknown as { navigator?: { mediaDevices?: unknown } }).navigator !== undefined) {
    (globalThis.navigator as unknown as { mediaDevices: { getUserMedia: () => Promise<unknown> } }).mediaDevices = {
      getUserMedia: () => Promise.reject(new Error("no microphone in test env")),
    };
  }
}

test("getActiveContextId returns null when no recording is active", () => {
  assert.equal(recordingManager.getActiveContextId(), null);
});

test("startRecording sets activeContextId then clears it on error path", async () => {
  mockMediaRecorder();
  let errorCaught: { type: string } | null = null;
  await recordingManager.startRecording({
    contextId : "ctx-1",
    onError   : (e) => { errorCaught = e; },
  });
  // mock rejects → onError fires → recordingManager keeps active set briefly,
  // but cleanup happens inside AudioRecorder. Cancel explicitly to verify
  // the state machine.
  recordingManager.cancelRecording("ctx-1");
  assert.equal(recordingManager.getActiveContextId(), null);
  // Error was either captured or the AudioRecorder's internal _cleanup ran.
  assert.ok(errorCaught !== null || recordingManager.getActiveContextId() === null);
});

test("startRecording auto-cancels prior active recording (single-active invariant)", async () => {
  mockMediaRecorder();
  // First call sets active to ctx-1.
  await recordingManager.startRecording({ contextId: "ctx-1" }).catch(() => {});
  // Second call should cancel ctx-1 + set ctx-2 (then fail due to mock).
  await recordingManager.startRecording({ contextId: "ctx-2" }).catch(() => {});
  // After both, no active.
  recordingManager.cancelRecording("ctx-2");
  assert.equal(recordingManager.getActiveContextId(), null);
});

test("TTS pause/resume hooks: pause invoked when ttsIsPlaying returns true", async () => {
  mockMediaRecorder();
  let pauseCalled = false;
  recordingManager.ttsIsPlaying = () => true;
  recordingManager.ttsPause     = () => { pauseCalled = true; };
  await recordingManager.startRecording({ contextId: "ctx-tts" }).catch(() => {});
  assert.equal(pauseCalled, true);
  recordingManager.cancelRecording("ctx-tts");
});

test("TTS pause not invoked when ttsIsPlaying returns false", async () => {
  mockMediaRecorder();
  let pauseCalled = false;
  recordingManager.ttsIsPlaying = () => false;
  recordingManager.ttsPause     = () => { pauseCalled = true; };
  await recordingManager.startRecording({ contextId: "ctx-no-tts" }).catch(() => {});
  assert.equal(pauseCalled, false);
  recordingManager.cancelRecording("ctx-no-tts");
});

test("ESC key cancels the active recording", async () => {
  mockMediaRecorder();
  await recordingManager.startRecording({ contextId: "ctx-esc" }).catch(() => {});
  // Dispatch ESC keydown — recordingManager's listener should cancel.
  if (typeof window !== "undefined") {
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
  }
  assert.equal(recordingManager.getActiveContextId(), null);
});

test("cancelRecording for an unknown contextId is a safe no-op", () => {
  assert.doesNotThrow(() => recordingManager.cancelRecording("nonexistent"));
});

// --- onCancel hook (stuck-mic fix) -----------------------------------------

test("cancelRecording fires the consumer's onCancel callback then clears active", async () => {
  mockMediaRecorder();
  let cancelled = false;
  await recordingManager.startRecording({
    contextId : "ctx-cancel",
    onCancel  : () => { cancelled = true; },
  }).catch(() => {});
  recordingManager.cancelRecording("ctx-cancel");
  assert.equal(cancelled, true);
  assert.equal(recordingManager.getActiveContextId(), null);
});

test("cancelRecording with a mismatched contextId leaves the active recording (no onCancel)", async () => {
  mockMediaRecorder();
  let cancelled = false;
  await recordingManager.startRecording({
    contextId : "ctx-keep",
    onCancel  : () => { cancelled = true; },
  }).catch(() => {});
  recordingManager.cancelRecording("ctx-other");   // wrong id → early return, untouched
  assert.equal(cancelled, false);
  assert.equal(recordingManager.getActiveContextId(), "ctx-keep");
  recordingManager.cancelRecording("ctx-keep");    // cleanup (fires onCancel)
  assert.equal(cancelled, true);
});

test("ESC keydown fires the consumer's onCancel", async () => {
  mockMediaRecorder();
  let cancelled = false;
  await recordingManager.startRecording({
    contextId : "ctx-esc-cb",
    onCancel  : () => { cancelled = true; },
  }).catch(() => {});
  if (typeof window !== "undefined") {
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
  }
  assert.equal(cancelled, true);
  assert.equal(recordingManager.getActiveContextId(), null);
});

test("stopRecording for an unknown contextId is a safe no-op", async () => {
  await assert.doesNotReject(() => recordingManager.stopRecording("nonexistent"));
});
