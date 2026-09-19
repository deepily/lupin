// Row cd6fe6d6 (follows 0b384107) — the server's `tts_error` frame ends the utterance.
//
// Legacy handleTTSError (notifications.js:4483-4504) marks the stream complete and calls
// onTTSPlaybackComplete, so the queue moves on. The server sends that frame on a quota,
// rate-limit or auth failure and then an audio_streaming_complete with no audio
// (speech.py:1301, :1318); its debug simulation sends the frame and returns with no complete
// frame at all (:1179). The multiplexer subscribed to the frame (AudioTransport.ts:25) and
// nothing read it, so the failed item held the TTS slot forever.
//
// Out of scope, ruled a decision for Rick rather than parity: legacy has no watchdog for an
// audio context whose resume never settles (it awaits it unbounded, :4690-4692), nor for a
// stream that sends no end frame.
//
// Run: npx tsx --test src/tests/unit/multiplexer/tts_error_frame_releases_slot.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createAudioStore } from "../../../lupin_app/static/js/multiplexer/stores/AudioStore";
import { createTtsQueueStore } from "../../../lupin_app/static/js/multiplexer/stores/TtsQueueStore";
import { createStores } from "../../../lupin_app/static/js/multiplexer/stores";
import { createStorageServiceForTesting, InMemoryStorage } from "../../../lupin_app/static/js/multiplexer/shared/StorageService";
import { TTS_STORAGE_KEY, TTS_STORAGE_SCHEMA } from "../../../lupin_app/static/js/multiplexer/stores/TtsQueueStore";
import { wireNotificationTtsIntent } from "../../../lupin_app/static/js/multiplexer/wireTtsIntent";
import type {
  AudioBufferLike,
  AudioBufferSourceLike,
  SchedulableAudioContext,
} from "../../../lupin_app/static/js/multiplexer/stores/AudioStore";
import type { TtsQueueItem } from "../../../lupin_app/static/js/multiplexer/shared/types";

type Bus = ReturnType<typeof createEventBusForTesting>;

// The frame as AudioTransport re-emits it: the envelope minus `type` and `timestamp`
// (speech.py:1301-1308).
function ttsError(bus: Bus): void {
  bus.emit({
    type    : "tts_error",
    payload : { text: "ElevenLabs quota exceeded. TTS unavailable until reset.", error_code: "quota_exceeded", status: "error", provider: "elevenlabs" },
    source  : "AudioTransport",
    ts      : 0,
  });
}

function streamComplete(bus: Bus): void {
  bus.emit({ type: "audio_streaming_complete", payload: {}, source: "AudioTransport", ts: 0 });
}

class Source implements AudioBufferSourceLike {
  buffer  : AudioBufferLike | null = null;
  onended : (() => void) | null    = null;
  connect(): void {}
  start(): void {}
  stop(): void {}
}

class Context implements SchedulableAudioContext {
  currentTime = 0;
  state       = "running" as const;
  readonly destination = {};
  readonly sources : Source[] = [];
  createBuffer(channels: number, length: number, sampleRate: number): AudioBufferLike {
    return { numberOfChannels: channels, length, sampleRate, duration: length / sampleRate, copyToChannel() {} };
  }
  createBufferSource(): AudioBufferSourceLike { const s = new Source(); this.sources.push(s); return s; }
  suspend(): Promise<void> { return Promise.resolve(); }
  resume(): Promise<void> { return Promise.resolve(); }
}

function audioSetup() {
  const bus   = createEventBusForTesting();
  const ctx   = new Context();
  let ended   = 0;
  bus.on("store_audio_ended", () => { ended += 1; });
  const store = createAudioStore({ bus, audioContextFactory: () => ctx, nowFn: () => 1 });
  const send  = (): void => store.binaryHandler(new Int16Array(50).buffer);
  return { bus, store, ctx, send, ended: () => ended };
}

function speech(idHash: string): TtsQueueItem {
  return { id_hash: idHash, ttsText: `say ${idHash}`, addedAt: 1 };
}

// ---------------------------------------------------------------------------
// AudioStore — the frame ends the utterance, once (legacy :4483-4504)
// ---------------------------------------------------------------------------

test("a tts_error before any audio ends the utterance at once, with no complete frame needed (speech.py:1179)", () => {
  const a = audioSetup();
  ttsError(a.bus);
  assert.equal(a.ended(), 1);
});

test("a tts_error followed by the server's trailing complete frame ends it exactly once (speech.py:1301, :1318)", () => {
  const a = audioSetup();
  ttsError(a.bus);
  streamComplete(a.bus);
  assert.equal(a.ended(), 1);
});

test("a tts_error while audio is still playing ends the utterance when that audio finishes, once", () => {
  const a = audioSetup();
  a.send(); a.send();
  ttsError(a.bus);
  assert.equal(a.ended(), 0, "the audio already scheduled plays out");
  streamComplete(a.bus);
  for (const s of a.ctx.sources) s.onended?.();
  assert.equal(a.ended(), 1);
});

// ---------------------------------------------------------------------------
// With the real TTS queue on the same bus
// ---------------------------------------------------------------------------

test("a stray tts_error after Stop, with an item queued but not started, neither starts nor skips it", () => {
  const a   = audioSetup();
  const tts = createTtsQueueStore({ bus: a.bus, nowFn: () => 1 });
  tts.enqueue(speech("A"));
  tts.enqueue(speech("B"));
  a.bus.emit({ type: "store_audio_state_change", payload: { state: "idle", prev: "playing" }, source: "AudioStore", ts: 0 });
  assert.equal(tts.current(), null, "precondition: Stop halted the queue with B waiting");
  ttsError(a.bus);
  assert.equal(tts.current(), null, "a stray error must not start B");
  assert.deepEqual(tts.pending().map((it) => it.id_hash), ["B"]);
});

test("a stray tts_error while restored items wait for the audio socket neither starts nor skips the head", () => {
  const a       = audioSetup();
  const storage = createStorageServiceForTesting(a.bus, new InMemoryStorage());
  storage.setJSON(TTS_STORAGE_KEY, { pending: [speech("R1"), speech("R2")], focusModeActive: false, focusModeNotificationId: null }, TTS_STORAGE_SCHEMA);
  const tts = createTtsQueueStore({ bus: a.bus, nowFn: () => 1, storage });
  ttsError(a.bus);
  assert.equal(tts.current(), null, "the restored head waits for the socket");
  a.bus.emit({ type: "transport_ready", payload: { transport: "AudioTransport" }, source: "AudioTransport", ts: 0 });
  assert.equal(tts.current(), "R1", "R1 starts on the socket, not skipped");
});

test("a tts_error for the item holding the slot moves the queue to the next item", () => {
  const a   = audioSetup();
  const tts = createTtsQueueStore({ bus: a.bus, nowFn: () => 1 });
  tts.enqueue(speech("A"));
  tts.enqueue(speech("B"));
  ttsError(a.bus);
  streamComplete(a.bus);
  assert.equal(tts.current(), "B", "moved on once — not past B");
});

test("assembled: a prompt waiting behind a notification whose speech hits a tts_error activates", () => {
  const bus    = createEventBusForTesting();
  const api    = { get: async () => ({}), post: async () => ({}), patch: async () => ({}) } as never;
  const stores = createStores({ eventBus: bus, storage: createStorageServiceForTesting(bus), api, audioContextFactory: () => new Context() });
  wireNotificationTtsIntent(bus, stores.ttsQueue, () => 1, () => ({ fraction: 1, enabled: false, minChars: 100 }));
  const frame = (idHash: string, prompt: boolean): void => bus.emit({
    type    : "notification_queue_update",
    payload : { notification: {
      id_hash: idHash, message: `msg ${idHash}`, sender_id: "alice@x", priority: "high",
      timestamp: new Date(1_000_000).toISOString(),
      ...(prompt ? { response_requested: true, response_type: "yes_no", timeout_seconds: 30 } : {}),
    } },
    source  : "test",
    ts      : 0,
  });
  frame("N1", false);
  frame("AR", true);
  assert.equal(stores.actionRequired.getById("AR")!.expires_at, null, "precondition: the prompt waits for N1");
  ttsError(bus);
  assert.notEqual(stores.actionRequired.getById("AR")!.expires_at, null);
  assert.equal(stores.ttsQueue.current(), "AR");
});
