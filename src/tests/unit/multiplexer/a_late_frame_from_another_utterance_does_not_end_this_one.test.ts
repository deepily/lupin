// A complete or error frame that names another utterance is ignored.
//
// The server does not cancel a speech stream when the client moves on, so the
// frames of an abandoned stream keep arriving. Before this row its late
// `audio_streaming_complete` set the one shared flag in AudioStore, and the next
// utterance ended as soon as the audio it had so far finished playing: cut short.
//
// Each request now sends `utterance_id`, the server echoes it on the stream's
// frames (speech.py `stream_frame`), and AudioStore drops a frame naming another.
//
// Run: npx tsx --test src/tests/unit/multiplexer/a_late_frame_from_another_utterance_does_not_end_this_one.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createAudioStore } from "../../../lupin_app/static/js/multiplexer/stores/AudioStore";
import { createTtsQueueStore } from "../../../lupin_app/static/js/multiplexer/stores/TtsQueueStore";
import { wireTtsPlayback } from "../../../lupin_app/static/js/multiplexer/wireTtsPlayback";
import type {
  AudioBufferLike,
  AudioBufferSourceLike,
  SchedulableAudioContext,
} from "../../../lupin_app/static/js/multiplexer/stores/AudioStore";
import type { TtsQueueItem } from "../../../lupin_app/static/js/multiplexer/shared/types";

type Bus = ReturnType<typeof createEventBusForTesting>;

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

// The frames as AudioTransport re-emits them: the envelope minus `type` and `timestamp`.
function complete(bus: Bus, utteranceId?: unknown): void {
  const payload: Record<string, unknown> = { text: "ElevenLabs streaming complete (2 chunks, 0.4s)", status: "success", provider: "elevenlabs" };
  if (utteranceId !== undefined) payload.utterance_id = utteranceId;
  bus.emit({ type: "audio_streaming_complete", payload, source: "AudioTransport", ts: 0 });
}

function ttsError(bus: Bus, utteranceId?: unknown): void {
  const payload: Record<string, unknown> = { text: "Too many TTS requests. Please wait a moment.", error_code: "rate_limit", status: "error", provider: "elevenlabs" };
  if (utteranceId !== undefined) payload.utterance_id = utteranceId;
  bus.emit({ type: "tts_error", payload, source: "AudioTransport", ts: 0 });
}

function requested(bus: Bus, idHash: string, utteranceId?: string): void {
  const payload = utteranceId === undefined ? { idHash } : { idHash, utteranceId };
  bus.emit({ type: "tts_request_started", payload, source: "wireTtsPlayback", ts: 0 });
}

function audioSetup() {
  const bus   = createEventBusForTesting();
  const ctx   = new Context();
  let ended   = 0;
  bus.on("store_audio_ended", () => { ended += 1; });
  const store = createAudioStore({ bus, audioContextFactory: () => ctx, nowFn: () => 1, setTimeoutFn: () => 0, clearTimeoutFn: () => {} });
  const chunk = (): void => store.binaryHandler(new Int16Array(50).buffer);
  const playOut = (): void => { for (const s of ctx.sources) s.onended?.(); };
  return { bus, store, ctx, chunk, playOut, ended: () => ended };
}

// ---------------------------------------------------------------------------
// AudioStore alone
// ---------------------------------------------------------------------------

test("a complete frame naming another utterance does not end this one; its own complete frame does", () => {
  const a = audioSetup();
  requested(a.bus, "B", "B:2");
  a.chunk();
  complete(a.bus, "A:1");
  a.playOut();
  assert.equal(a.ended(), 0, "the late frame of A ended B");
  a.chunk();
  complete(a.bus, "B:2");
  a.playOut();
  assert.equal(a.ended(), 1);
});

test("control: with no id on the frame, the same late complete frame does end the utterance", () => {
  // What the id prevents. The sequence is the one above, minus the ids on the frames.
  const a = audioSetup();
  requested(a.bus, "B", "B:2");
  a.chunk();
  complete(a.bus);
  a.playOut();
  assert.equal(a.ended(), 1);
});

test("a tts_error naming another utterance does not fail this one; its own error does", () => {
  const a = audioSetup();
  requested(a.bus, "B", "B:2");
  ttsError(a.bus, "A:1");
  assert.equal(a.ended(), 0, "the late error of A ended B");
  ttsError(a.bus, "B:2");
  assert.equal(a.ended(), 1);
});

test("a frame is handled as before when the request sent no id, whatever the frame says", () => {
  const a = audioSetup();
  requested(a.bus, "B");
  a.chunk();
  complete(a.bus, "A:1");
  a.playOut();
  assert.equal(a.ended(), 1);
});

test("a later request with no id forgets the id the earlier request sent", () => {
  const a = audioSetup();
  requested(a.bus, "A", "A:1");
  requested(a.bus, "B");
  ttsError(a.bus, "Z:9");
  assert.equal(a.ended(), 1);
});

test("a frame whose utterance_id is not a string is handled as before", () => {
  for (const odd of [ 7, null, { id: "A:1" }, [ "A:1" ] ]) {
    const a = audioSetup();
    requested(a.bus, "B", "B:2");
    ttsError(a.bus, odd);
    assert.equal(a.ended(), 1, `utterance_id ${ JSON.stringify(odd) }`);
  }
});

test("before any request, a frame with an id is handled as before", () => {
  const a = audioSetup();
  ttsError(a.bus, "A:1");
  assert.equal(a.ended(), 1);
});

// ---------------------------------------------------------------------------
// Assembled: the real request wire, queue store and audio store on one bus
// ---------------------------------------------------------------------------

function speech(idHash: string): TtsQueueItem {
  return { id_hash: idHash, ttsText: `say ${idHash}`, addedAt: 1 };
}

function assembled() {
  const a     = audioSetup();
  const tts   = createTtsQueueStore({ bus: a.bus, nowFn: () => 1 });
  const posts : Array<{ text: string; utterance_id: string }> = [];
  const api   = { post<T>(_path: string, body: unknown): Promise<T> {
    posts.push(body as { text: string; utterance_id: string });
    return Promise.resolve(undefined as T);
  } };
  wireTtsPlayback(a.bus, tts, api, "wise penguin", { ttsMode: () => "instant" });
  return { ...a, tts, posts };
}

test("assembled: the late complete frame of a removed item does not cut the next item short", () => {
  const s = assembled();
  s.tts.enqueue(speech("A"));
  s.tts.enqueue(speech("B"));
  s.chunk();                                   // A is speaking
  s.tts.removeById("A");                       // the client moves on; the server keeps sending A
  assert.equal(s.tts.current(), "B", "precondition: B took the slot");
  assert.deepEqual(s.posts.map((p) => p.text), [ "say A", "say B" ]);
  const [ idA, idB ] = s.posts.map((p) => p.utterance_id);
  assert.notEqual(idA, idB);

  const endedBefore = s.ended();
  s.chunk();                                   // B's first audio
  complete(s.bus, idA);                        // A's stream finishes, late
  s.playOut();                                 // what B has so far finishes playing
  assert.equal(s.ended(), endedBefore, "A's late complete frame ended B");
  assert.equal(s.tts.current(), "B", "B lost the slot to A's late frame");

  s.chunk();                                   // the rest of B
  complete(s.bus, idB);
  s.playOut();
  assert.equal(s.ended(), endedBefore + 1);
  assert.equal(s.tts.current(), null, "B finished and the queue drained");
});

test("assembled control: an echo-less server reproduces the cut-short, so the test above can see it", () => {
  const s = assembled();
  s.tts.enqueue(speech("A"));
  s.tts.enqueue(speech("B"));
  s.chunk();
  s.tts.removeById("A");
  const endedBefore = s.ended();
  s.chunk();
  complete(s.bus);                             // A's late frame, with no id to tell it apart
  s.playOut();
  assert.equal(s.ended(), endedBefore + 1, "expected the old defect without ids");
  assert.equal(s.tts.current(), null, "B was cut short and released the slot");
});
