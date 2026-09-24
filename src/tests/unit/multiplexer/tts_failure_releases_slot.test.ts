// Row 0b384107 — a failed utterance releases the TTS slot.
//
// Legacy moves on when speech fails: the playTTS catch (notifications.js:22394-22396) and
// audio.onerror (:4336-4340) both call onTTSPlaybackComplete. The multiplexer did neither: a
// failed speech request was swallowed (wireTtsPlayback) and an audio error completed nothing
// (AudioStore), so the item held the slot forever. Since A-2 #2d an Action Required card that
// arrives behind it waits forever too.
//
// Run: npx tsx --test src/tests/unit/multiplexer/tts_failure_releases_slot.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createTtsQueueStore } from "../../../lupin_app/static/js/multiplexer/stores/TtsQueueStore";
import { createAudioStore } from "../../../lupin_app/static/js/multiplexer/stores/AudioStore";
import { createStores } from "../../../lupin_app/static/js/multiplexer/stores";
import { createStorageServiceForTesting } from "../../../lupin_app/static/js/multiplexer/shared/StorageService";
import { wireTtsPlayback } from "../../../lupin_app/static/js/multiplexer/wireTtsPlayback";
import { wireNotificationTtsIntent } from "../../../lupin_app/static/js/multiplexer/wireTtsIntent";
import type {
  AudioBufferLike,
  AudioBufferSourceLike,
  SchedulableAudioContext,
} from "../../../lupin_app/static/js/multiplexer/stores/AudioStore";
import type {
  StoreAudioStateChangePayload,
  StoreTtsSlotReleasedPayload,
  TtsQueueItem,
  TtsRequestFailedPayload,
} from "../../../lupin_app/static/js/multiplexer/shared/types";

type Bus = ReturnType<typeof createEventBusForTesting>;

function speech(idHash: string, actionRequired = false): TtsQueueItem {
  return { id_hash: idHash, ttsText: `say ${idHash}`, addedAt: 1, action_required: actionRequired };
}

function failed(bus: Bus, idHash: string): void {
  bus.emit<TtsRequestFailedPayload>({ type: "tts_request_failed", payload: { idHash }, source: "test", ts: 0 });
}

function audio(bus: Bus, state: StoreAudioStateChangePayload["state"]): void {
  bus.emit<StoreAudioStateChangePayload>({
    type: "store_audio_state_change", payload: { state, prev: "playing" }, source: "test", ts: 0,
  });
}

function streamComplete(bus: Bus): void {
  bus.emit({ type: "audio_streaming_complete", payload: {}, source: "test", ts: 0 });
}

const flush = (): Promise<void> => new Promise((r) => setTimeout(r, 0));

function ttsSetup() {
  const bus      = createEventBusForTesting();
  const released : string[] = [];
  bus.on<StoreTtsSlotReleasedPayload>("store_tts_slot_released", (e) => released.push(e.payload.releasedId));
  return { bus, released, tts: createTtsQueueStore({ bus, nowFn: () => 7 }) };
}

// ---------------------------------------------------------------------------
// TtsQueueStore — a failed request is the item's completion (legacy :22394-22396)
// ---------------------------------------------------------------------------

test("a failed request for the playing item releases the slot and moves to the next item", () => {
  const { bus, tts, released } = ttsSetup();
  tts.enqueue(speech("A"));
  tts.enqueue(speech("B"));
  failed(bus, "A");
  assert.equal(tts.current(), "B");
  assert.deepEqual(released, ["A"]);
});

test("a late failure for an item that already left the slot changes nothing", () => {
  const { bus, tts, released } = ttsSetup();
  tts.enqueue(speech("A"));
  tts.enqueue(speech("B"));
  bus.emit({ type: "store_audio_ended", payload: {}, source: "test", ts: 0 });
  released.length = 0;
  failed(bus, "A");
  assert.equal(tts.current(), "B");
  assert.deepEqual(released, []);
});

test("a failure with nothing playing changes nothing", () => {
  const { bus, tts, released } = ttsSetup();
  failed(bus, "A");
  assert.equal(tts.isPlaying(), false);
  assert.deepEqual(released, []);
});

test("a failed request for an Action Required item enters focus, as a natural end does", () => {
  const { bus, tts } = ttsSetup();
  tts.enqueue(speech("AR", true));
  tts.enqueue(speech("B"));
  failed(bus, "AR");
  assert.equal(tts.focusMode(), true);
  assert.equal(tts.current(), null);
});

test("a failure during a manual pause is held until Play, like a natural end (A-2 #3c)", () => {
  const { bus, tts } = ttsSetup();
  tts.enqueue(speech("A"));
  tts.enqueue(speech("B"));
  audio(bus, "paused");
  failed(bus, "A");
  assert.equal(tts.current(), "A");
  audio(bus, "playing");
  assert.equal(tts.current(), "B");
});

// ---------------------------------------------------------------------------
// wireTtsPlayback — the failure is announced, not swallowed
// ---------------------------------------------------------------------------

function wireSetup(reject: boolean) {
  const bus    = createEventBusForTesting();
  const events : string[] = [];
  bus.on<TtsRequestFailedPayload>("tts_request_failed", (e) => events.push(e.payload.idHash));
  const tts = createTtsQueueStore({ bus, nowFn: () => 7 });
  wireTtsPlayback(bus, tts, { post: <T>() => (reject ? Promise.reject(new Error("503")) : Promise.resolve({} as T)) }, "wise penguin", { ttsMode: () => "instant" });
  return { bus, tts, events };
}

test("a rejected speech request announces tts_request_failed for that item, and the queue moves on", async () => {
  const { tts, events } = wireSetup(true);
  tts.enqueue(speech("A"));
  tts.enqueue(speech("B"));
  await flush();
  assert.deepEqual(events.slice(0, 1), ["A"]);
  assert.notEqual(tts.current(), "A");
});

test("a speech request that succeeds announces nothing", async () => {
  const { tts, events } = wireSetup(false);
  tts.enqueue(speech("A"));
  await flush();
  assert.deepEqual(events, []);
  assert.equal(tts.current(), "A");
});

// ---------------------------------------------------------------------------
// AudioStore — a failed utterance still ends, once (legacy audio.onerror :4336-4340)
// ---------------------------------------------------------------------------

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

function audioSetup(opts: { factoryThrows?: boolean; decodeFails?: (n: number) => boolean } = {}) {
  const bus    = createEventBusForTesting();
  const ctx    = new Context();
  let ended    = 0;
  let errors   = 0;
  let chunk    = 0;
  bus.on("store_audio_ended", () => { ended += 1; });
  bus.on<StoreAudioStateChangePayload>("store_audio_state_change", (e) => { if (e.payload.state === "error") errors += 1; });
  const store = createAudioStore({
    bus,
    audioContextFactory : () => { if (opts.factoryThrows) throw new Error("blocked"); return ctx; },
    decodeArrayBufferFn : (data, c, rate) => {
      chunk += 1;
      if (opts.decodeFails?.(chunk)) throw new Error("malformed PCM");
      return c.createBuffer(1, data.byteLength / 2, rate);
    },
    nowFn : () => 1,
  });
  const send = (): void => store.binaryHandler(new Int16Array(50).buffer);
  return { bus, store, ctx, send, ended: () => ended, errors: () => errors };
}

test("every chunk failing to decode: the stream-complete frame ends the utterance exactly once", () => {
  const a = audioSetup({ decodeFails: () => true });
  a.send(); a.send(); a.send();
  assert.ok(a.errors() >= 6, "precondition: each failed chunk emits two error changes");
  assert.equal(a.ended(), 0, "not per error");
  streamComplete(a.bus);
  streamComplete(a.bus);
  assert.equal(a.ended(), 1);
});

test("an audio context that cannot be built: the stream-complete frame ends the utterance once", () => {
  const a = audioSetup({ factoryThrows: true });
  a.send(); a.send();
  streamComplete(a.bus);
  assert.equal(a.ended(), 1);
});

test("a stream with no chunks and no failure still completes nothing", () => {
  const a = audioSetup();
  streamComplete(a.bus);
  assert.equal(a.ended(), 0);
});

test("stop clears a failure, so a later stream-complete frame ends nothing", () => {
  const a = audioSetup({ decodeFails: (n) => n === 2 });
  a.send();                       // plays — the machine can now be stopped
  a.send();                       // fails
  a.store.stop();
  streamComplete(a.bus);
  assert.equal(a.ended(), 0);
});

test("one failed chunk inside a playing utterance: it ends once, when its last source finishes", () => {
  const a = audioSetup({ decodeFails: (n) => n === 2 });
  a.send(); a.send(); a.send();
  streamComplete(a.bus);
  assert.equal(a.ended(), 0, "sources are still playing");
  for (const s of a.ctx.sources) s.onended?.();
  assert.equal(a.ended(), 1);
});

// ---------------------------------------------------------------------------
// Assembled — the A-2 #2d card no longer waits forever behind a failed item
// ---------------------------------------------------------------------------

function arrive(bus: Bus, idHash: string, priority: string, prompt: boolean): void {
  bus.emit({
    type    : "notification_queue_update",
    payload : { notification: {
      id_hash: idHash, message: `msg ${idHash}`, sender_id: "alice@x", priority,
      timestamp: new Date(1_000_000).toISOString(),
      ...(prompt ? { response_requested: true, response_type: "yes_no", timeout_seconds: 30 } : {}),
    } },
    source  : "test",
    ts      : 0,
  });
}

function assembled(post: () => Promise<unknown>, audioContextFactory?: () => SchedulableAudioContext) {
  const bus    = createEventBusForTesting();
  const api    = { get: async () => ({}), post, patch: async () => ({}) } as never;
  const stores = createStores({ eventBus: bus, storage: createStorageServiceForTesting(bus), api, audioContextFactory });
  wireNotificationTtsIntent(bus, stores.ttsQueue, () => 1, () => ({ fraction: 1, enabled: false, minChars: 100 }));
  wireTtsPlayback(bus, stores.ttsQueue, api, "wise penguin", { ttsMode: () => "instant" });
  return { bus, stores };
}

test("assembled: a prompt behind a notification whose speech request fails activates once the failure lands", async () => {
  let calls = 0;
  const { bus, stores } = assembled(() => { calls += 1; return calls === 1 ? Promise.reject(new Error("503")) : Promise.resolve({}); });
  arrive(bus, "N1", "high", false);
  arrive(bus, "AR", "high", true);
  assert.equal(stores.actionRequired.getById("AR")!.expires_at, null, "precondition: the prompt waits for N1");
  await flush();
  assert.notEqual(stores.actionRequired.getById("AR")!.expires_at, null);
  assert.equal(stores.ttsQueue.current(), "AR");
});

test("assembled: a prompt behind a notification whose audio cannot play activates at the stream-complete frame", () => {
  const { bus, stores } = assembled(() => new Promise(() => {}), () => { throw new Error("blocked"); });
  arrive(bus, "N1", "high", false);
  arrive(bus, "AR", "high", true);
  stores.audio.binaryHandler(new Int16Array(50).buffer);
  assert.equal(stores.actionRequired.getById("AR")!.expires_at, null, "precondition: the prompt waits for N1");
  streamComplete(bus);
  assert.notEqual(stores.actionRequired.getById("AR")!.expires_at, null);
});
