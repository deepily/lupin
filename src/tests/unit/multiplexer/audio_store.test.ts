// Multiplexer Phase 4 — AudioStore unit tests.
// Run via `npx tsx --test src/tests/unit/multiplexer/audio_store.test.ts`.
// AC4 floor: ≥ 18 tests per design doc § Verification matrix per-store floor.

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createAudioStore } from "../../../lupin_app/static/js/multiplexer/stores/AudioStore";
// Parity B-1b — the REAL decoder, so the fail-once-then-succeed arm below decodes
// for real on its second call rather than through a second stub.
import { pcm16ToAudioBuffer as realDecodeArrayBuffer } from "../../../lupin_app/static/js/multiplexer/audio/pcm-decoder";
import type {
  AudioBufferSourceLike,
  AudioContextStateLike,
  AudioDestinationNodeLike,
  SchedulableAudioContext,
} from "../../../lupin_app/static/js/multiplexer/stores/AudioStore";
import type {
  AudioBufferLike,
} from "../../../lupin_app/static/js/multiplexer/audio/pcm-decoder";
import type {
  LupinEvent,
  StoreAudioChunkDecodedPayload,
  StoreAudioStateChangePayload,
  StoreAudioEndedPayload,
  StoreTtsModeChangedPayload,
} from "../../../lupin_app/static/js/multiplexer/shared/types";

// ---------------------------------------------------------------------------
// Stub Audio types — full real Web Audio is not needed in Node. The stub
// implements the SchedulableAudioContext SUPERSET (COND-4 / F-Krishna-A4):
// createBuffer (decode) + createBufferSource / currentTime / destination /
// state / suspend / resume (schedule + autoplay). It RECORDS every scheduler
// call so the gapless math, pause/resume/stop, completion seam, and autoplay
// arms are all deterministically observable.
// ---------------------------------------------------------------------------

class StubAudioBuffer implements AudioBufferLike {
  readonly numberOfChannels : number;
  readonly length           : number;
  readonly sampleRate       : number;
  readonly duration         : number;
  constructor(channels: number, length: number, sampleRate: number) {
    this.numberOfChannels = channels;
    this.length           = length;
    this.sampleRate       = sampleRate;
    this.duration         = length / sampleRate;
  }
  copyToChannel(_src: Float32Array, _ch: number, _off?: number): void {}
}

// One scheduled source. Records its scheduled start time(s) + stop; exposes
// fireEnded() so a test can drive the onended completion gate deterministically.
class StubBufferSource implements AudioBufferSourceLike {
  buffer  : AudioBufferLike | null = null;
  onended : ( () => void ) | null  = null;
  readonly startTimes : number[] = [];
  connectCount = 0;
  stopped      = false;
  connect(_destination: AudioDestinationNodeLike): void { this.connectCount++; }
  start(when?: number): void { this.startTimes.push(when as number); }
  stop(): void { this.stopped = true; }
  fireEnded(): void { if (this.onended) this.onended(); }
}

class StubSchedulableContext implements SchedulableAudioContext {
  // Mutable clock so a test can advance time between chunks (past-due restart).
  currentTime : number;
  state       : AudioContextStateLike;
  readonly destination : AudioDestinationNodeLike = {};
  // Recording.
  createBufferCalls = 0;
  readonly createdSources : StubBufferSource[] = [];
  suspendCount = 0;
  resumeCount  = 0;
  // Controllable suspend/resume results (rejection-capable per F-Sam-C1).
  private readonly suspendResult : () => Promise<void>;
  private readonly resumeResult  : () => Promise<void>;

  constructor(opts: {
    currentTime    ?: number;
    state          ?: AudioContextStateLike;
    suspendResult  ?: () => Promise<void>;
    resumeResult   ?: () => Promise<void>;
  } = {}) {
    this.currentTime   = opts.currentTime ?? 0;
    this.state         = opts.state ?? "running";
    this.suspendResult = opts.suspendResult ?? (() => Promise.resolve());
    this.resumeResult  = opts.resumeResult ?? (() => Promise.resolve());
  }
  createBuffer(channels: number, length: number, sampleRate: number): AudioBufferLike {
    this.createBufferCalls++;
    return new StubAudioBuffer(channels, length, sampleRate);
  }
  createBufferSource(): AudioBufferSourceLike {
    const src = new StubBufferSource();
    this.createdSources.push(src);
    return src;
  }
  suspend(): Promise<void> { this.suspendCount++; return this.suspendResult(); }
  resume(): Promise<void> { this.resumeCount++; return this.resumeResult(); }
}

function makePCM16(byteLength: number = 100): ArrayBuffer {
  const arr = new Int16Array(byteLength / 2);
  for (let i = 0; i < arr.length; i++) {
    arr[i] = (i % 256) - 128;
  }
  return arr.buffer;
}

// ---------------------------------------------------------------------------
// Test setup
// ---------------------------------------------------------------------------

function setup(opts: {
  factoryThrows ?: boolean;
  decodeThrows  ?: boolean;
  // P6 — initial AudioContext config (autoplay + gapless clock).
  ctxState      ?: AudioContextStateLike;
  currentTime   ?: number;
  resumeResult  ?: () => Promise<void>;
  suspendResult ?: () => Promise<void>;
} = {}) {
  const bus    = createEventBusForTesting();
  const stateEvents : LupinEvent<StoreAudioStateChangePayload>[]   = [];
  const chunkEvents : LupinEvent<StoreAudioChunkDecodedPayload>[]  = [];
  const endedEvents : LupinEvent<StoreAudioEndedPayload>[]         = [];
  bus.on<StoreAudioStateChangePayload>("store_audio_state_change", (e) => stateEvents.push(e));
  bus.on<StoreAudioChunkDecodedPayload>("store_audio_chunk_decoded", (e) => chunkEvents.push(e));
  bus.on<StoreAudioEndedPayload>("store_audio_ended", (e) => endedEvents.push(e));

  let factoryCallCount = 0;
  // Captured so tests can read the recorded scheduler calls. The factory is
  // invoked once (lazy on first chunk); subsequent chunks reuse this instance.
  let ctx: StubSchedulableContext | null = null;
  const audioContextFactory = (): SchedulableAudioContext => {
    factoryCallCount++;
    if (opts.factoryThrows) throw new Error("AudioContext blocked by autoplay policy");
    ctx = new StubSchedulableContext({
      currentTime   : opts.currentTime,
      state         : opts.ctxState,
      resumeResult  : opts.resumeResult,
      suspendResult : opts.suspendResult,
    });
    return ctx;
  };

  const store = createAudioStore({
    bus,
    audioContextFactory,
    decodeArrayBufferFn : opts.decodeThrows
      ? () => { throw new Error("malformed PCM"); }
      : undefined,
    nowFn : () => 1_000_000,
  });

  // Inject an audio_streaming_complete server frame on the bus (the completion
  // seam AudioStore subscribes to in P6-c).
  const sendStreamComplete = (): void => {
    bus.emit({ type: "audio_streaming_complete", payload: {}, source: "test", ts: 1_000_000 });
  };

  return {
    bus,
    store,
    stateEvents,
    chunkEvents,
    endedEvents,
    sendStreamComplete,
    getFactoryCallCount: () => factoryCallCount,
    // Non-null accessor — every test that reads the ctx has driven >=1 chunk.
    getCtx: (): StubSchedulableContext => {
      if (ctx === null) throw new Error("test bug: AudioContext not yet constructed");
      return ctx;
    },
  };
}

// ===========================================================================
// 1-3 : Initial state + Function.name + binaryHandler signature
// ===========================================================================

test("initial state: idle; burstLength=0", () => {
  const { store } = setup();
  assert.equal(store.state(), "idle");
  assert.equal(store.burstLength(), 0);
});

test("binaryHandler.name === 'audioStoreBinaryHandler' (AC9 invariant)", () => {
  const { store } = setup();
  assert.equal(store.binaryHandler.name, "audioStoreBinaryHandler");
});

test("binaryHandler is callable from the AudioTransport contract surface", () => {
  const { store } = setup();
  // Should not throw; should advance state machine.
  assert.doesNotThrow(() => {
    store.binaryHandler(makePCM16(100));
  });
});

// ===========================================================================
// 4-7 : First-chunk path + lazy AudioContext + state transition
// ===========================================================================

test("first ArrayBuffer chunk: idle → decoding → playing transition (sync decode)", () => {
  const { store, stateEvents } = setup();
  store.binaryHandler(makePCM16(200));
  assert.equal(store.state(), "playing");
  // Should see at least decoding then playing transitions.
  const states = stateEvents.map(e => e.payload.state);
  assert.ok(states.includes("decoding"));
  assert.ok(states.includes("playing"));
});

test("AudioContext factory called exactly once on first chunk; reused on subsequent", () => {
  const ctx = setup();
  ctx.store.binaryHandler(makePCM16(100));
  assert.equal(ctx.getFactoryCallCount(), 1);
  ctx.store.binaryHandler(makePCM16(100));
  ctx.store.binaryHandler(makePCM16(100));
  assert.equal(ctx.getFactoryCallCount(), 1, "factory must be reused across chunks");
});

test("AudioContext factory throws → emits error state with audiocontext-blocked reason", () => {
  const { store, stateEvents } = setup({ factoryThrows: true });
  store.binaryHandler(makePCM16(100));
  const errorEvent = stateEvents.find(e => e.payload.state === "error");
  assert.ok(errorEvent);
  assert.ok(errorEvent!.payload.reason?.startsWith("audiocontext-blocked"));
});

test("ArrayBuffer chunk emits store_audio_chunk_decoded with frameCount + sampleRate + durationMs", () => {
  const { store, chunkEvents } = setup();
  // 200-byte buffer → 100 Int16 samples → 100 frames at 24kHz → ~4.17ms.
  store.binaryHandler(makePCM16(200));
  assert.equal(chunkEvents.length, 1);
  const p = chunkEvents[0]!.payload;
  assert.equal(p.frameCount, 100);
  assert.equal(p.sampleRate, 24000);
  assert.ok(Math.abs(p.durationMs - (100 / 24000) * 1000) < 0.001);
});

// ===========================================================================
// 8-9 : Blob (async) path
// ===========================================================================

test("Blob chunk: async decode → playing state + chunk_decoded emission", async () => {
  const { store, stateEvents, chunkEvents } = setup();
  const blob = new Blob([makePCM16(200)]);
  store.binaryHandler(blob);
  // Wait a microtask for async decode.
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(store.state(), "playing");
  assert.equal(chunkEvents.length, 1);
  // State events should include decoding + playing.
  const states = stateEvents.map(e => e.payload.state);
  assert.ok(states.includes("decoding"));
  assert.ok(states.includes("playing"));
});

test("multiple chunks: state cycles decoding ↔ playing", () => {
  const { store } = setup();
  store.binaryHandler(makePCM16(100));
  assert.equal(store.state(), "playing");
  store.binaryHandler(makePCM16(100));
  assert.equal(store.state(), "playing");      // decoding → playing per chunk
  store.binaryHandler(makePCM16(100));
  assert.equal(store.state(), "playing");
});

// ===========================================================================
// 10-12 : Decoder failure paths
// ===========================================================================

test("decoder rejection (sync ArrayBuffer): transitions to error state with decode-failed reason", () => {
  const { store, stateEvents } = setup({ decodeThrows: true });
  store.binaryHandler(makePCM16(100));
  assert.equal(store.state(), "error");
  const errorEvent = stateEvents.find(e =>
    e.payload.state === "error" && e.payload.reason?.startsWith("decode-failed"),
  );
  assert.ok(errorEvent);
});

test("after error, subsequent chunk attempts a fresh decoding cycle (recovery)", () => {
  const ctx = setup({ decodeThrows: true });
  ctx.store.binaryHandler(makePCM16(100));
  assert.equal(ctx.store.state(), "error");
  // Recreate store with non-throwing decoder for second attempt.
  // (In practice the user retries by playing different content; the design
  // says state graph allows error → decoding via CHUNK_ARRIVED.)
  // For this test we verify the state graph supports the recovery transition.
  // We simulate by directly calling binaryHandler again — but the decoder is
  // still throwing in this fixture. The state machine WILL try decoding again
  // (CHUNK_ARRIVED is in error.on).
  ctx.store.binaryHandler(makePCM16(100));
  // Stays in error after second decode failure — recovery transition fires
  // but the decoder fails again so we land back in error.
  assert.equal(ctx.store.state(), "error");
});

test("burstLength tracks chunks-in-burst", () => {
  const { store } = setup();
  store.binaryHandler(makePCM16(100));
  store.binaryHandler(makePCM16(100));
  store.binaryHandler(makePCM16(100));
  assert.equal(store.burstLength(), 3);
});

// ===========================================================================
// 13-15 : pause / resume / skip
// ===========================================================================

test("pause(): playing → paused transition", () => {
  const { store, stateEvents } = setup();
  store.binaryHandler(makePCM16(100));               // → playing
  const before = stateEvents.length;
  store.pause();
  assert.equal(store.state(), "paused");
  const transition = stateEvents.slice(before).find(e => e.payload.state === "paused");
  assert.ok(transition);
});

test("resume(): paused → playing transition", () => {
  const { store } = setup();
  store.binaryHandler(makePCM16(100));
  store.pause();
  store.resume();
  assert.equal(store.state(), "playing");
});

test("skip() from playing: → ended; burstLength reset", () => {
  const { store } = setup();
  store.binaryHandler(makePCM16(100));
  store.binaryHandler(makePCM16(100));
  store.skip();
  assert.equal(store.state(), "ended");
  assert.equal(store.burstLength(), 0);
});

test("pause() in idle is a no-op (state machine has no transition)", () => {
  const { store } = setup();
  store.pause();
  assert.equal(store.state(), "idle");
});

test("resume() in playing is a no-op", () => {
  const { store } = setup();
  store.binaryHandler(makePCM16(100));
  store.resume();
  assert.equal(store.state(), "playing");
});

test("skip() in idle is a no-op", () => {
  const { store } = setup();
  store.skip();
  assert.equal(store.state(), "idle");
});

// ===========================================================================
// 16-17 : ended → resume on new chunk
// ===========================================================================

test("ended state: new chunk reactivates pipeline → decoding → playing", () => {
  const { store } = setup();
  store.binaryHandler(makePCM16(100));
  store.skip();
  assert.equal(store.state(), "ended");
  store.binaryHandler(makePCM16(100));
  assert.equal(store.state(), "playing");
});

test("state-change events carry both `state` and `prev`", () => {
  const { store, stateEvents } = setup();
  store.binaryHandler(makePCM16(100));
  // First state-change is idle → decoding.
  const firstChange = stateEvents[0]!;
  assert.equal(firstChange.payload.state, "decoding");
  assert.equal(firstChange.payload.prev, "idle");
});

// ===========================================================================
// 18-20 : State-machine-graph coverage (per AC5 + Pass 1 F6)
// ===========================================================================

test("state-machine reachability: idle → decoding → playing → paused → playing → ended", () => {
  const { store } = setup();
  assert.equal(store.state(), "idle");
  store.binaryHandler(makePCM16(100));
  assert.equal(store.state(), "playing");          // decoding is transient
  store.pause();
  assert.equal(store.state(), "paused");
  store.resume();
  assert.equal(store.state(), "playing");
  store.skip();
  assert.equal(store.state(), "ended");
});

test("state-machine reachability: idle → decoding → error path", () => {
  const { store } = setup({ decodeThrows: true });
  assert.equal(store.state(), "idle");
  store.binaryHandler(makePCM16(100));
  assert.equal(store.state(), "error");
});

test("emit count: each state mutation emits exactly one state_change (via subscribe)", () => {
  const { store, stateEvents } = setup();
  store.binaryHandler(makePCM16(100));
  // idle → decoding + decoding → playing = 2 emissions.
  // (The companion error-emission only fires on the failure path.)
  assert.equal(stateEvents.length, 2);
});

// ===========================================================================
// Phase 6b — stop() (per Pass 2 A6) — full halt to idle, queue cleared,
// distinct from skip() (which goes to ended).
// ===========================================================================

test("stop() from playing: → idle; burstLength=0; emits state-change to idle", () => {
  const { store, stateEvents } = setup();
  store.binaryHandler(makePCM16(100));
  store.binaryHandler(makePCM16(100));
  assert.equal(store.state(), "playing");
  assert.equal(store.burstLength(), 2);
  const before = stateEvents.length;
  store.stop();
  assert.equal(store.state(),       "idle");
  assert.equal(store.burstLength(), 0);
  const idleTransition = stateEvents.slice(before).find(e => e.payload.state === "idle");
  assert.ok(idleTransition, "stop() emits a state-change to idle");
  assert.equal(idleTransition!.payload.prev, "playing");
});

test("stop() from paused: → idle; burstLength=0", () => {
  const { store } = setup();
  store.binaryHandler(makePCM16(100));
  store.pause();
  assert.equal(store.state(), "paused");
  store.stop();
  assert.equal(store.state(),       "idle");
  assert.equal(store.burstLength(), 0);
});

test("stop() from ended: → idle (explicit reset, distinct from skip's terminal-ended)", () => {
  const { store } = setup();
  store.binaryHandler(makePCM16(100));
  store.skip();
  assert.equal(store.state(), "ended");
  store.stop();
  assert.equal(store.state(), "idle");
});

test("stop() from idle is a no-op (no event emission)", () => {
  const { store, stateEvents } = setup();
  const before = stateEvents.length;
  store.stop();
  assert.equal(store.state(), "idle");
  assert.equal(stateEvents.length, before, "no state-change emitted from idle stop");
});

test("stop() vs skip() — stop ends in idle, skip ends in ended (semantic distinction)", () => {
  const a = setup();
  const b = setup();
  a.store.binaryHandler(makePCM16(100));
  b.store.binaryHandler(makePCM16(100));
  a.store.stop();
  b.store.skip();
  assert.equal(a.store.state(), "idle",  "stop returns to idle");
  assert.equal(b.store.state(), "ended", "skip terminates at ended");
});

test("stop() from error: → idle (recovery path)", () => {
  const { store } = setup({ decodeThrows: true });
  store.binaryHandler(makePCM16(100));
  assert.equal(store.state(), "error");
  store.stop();
  assert.equal(store.state(), "idle");
});

// ===========================================================================
// Phase 6 (00c) — P6-a: gapless Web-Audio scheduler
// ===========================================================================

test("P6-a: first chunk starts at currentTime, never NaN (nextStartTime inits to 0)", () => {
  const { store, getCtx } = setup({ currentTime: 5 });
  store.binaryHandler(makePCM16(240));
  const ctx = getCtx();
  assert.equal(ctx.createdSources.length, 1);
  const when = ctx.createdSources[0]!.startTimes[0]!;
  // Math.max(0, 5) === 5 — first chunk at the live clock. NaN would mean an
  // uninitialized nextStartTime (Math.max(undefined, 5) === NaN) → silent fail.
  assert.equal(when, 5);
  assert.ok(!Number.isNaN(when));
});

test("P6-a: consecutive chunks schedule gaplessly (each starts at prior end)", () => {
  const { store, getCtx } = setup({ currentTime: 0 });
  store.binaryHandler(makePCM16(240));   // 120 frames @ 24kHz → 0.005s
  store.binaryHandler(makePCM16(240));
  store.binaryHandler(makePCM16(240));
  const ctx = getCtx();
  const dur = 120 / 24000;
  assert.equal(ctx.createdSources.length, 3);
  const starts = ctx.createdSources.map((s) => s.startTimes[0]!);
  // Each chunk starts exactly where the prior one ends — gapless.
  assert.ok(Math.abs(starts[0]! - 0) < 1e-9);
  assert.ok(Math.abs(starts[1]! - (starts[0]! + dur)) < 1e-9);
  assert.ok(Math.abs(starts[2]! - (starts[1]! + dur)) < 1e-9);
});

test("P6-a: a slow chunk never schedules in the past (past-due restart, OQ-P6.2)", () => {
  const { store, getCtx } = setup({ currentTime: 0 });
  store.binaryHandler(makePCM16(240));   // start 0, nextStartTime = 0.005
  const ctx = getCtx();
  // The context clock jumps far past the schedule cursor (slow chunk arrival).
  ctx.currentTime = 10;
  store.binaryHandler(makePCM16(240));
  // Math.max(0.005, 10) === 10 — restart at the live clock, never in the past.
  assert.equal(ctx.createdSources[1]!.startTimes[0]!, 10);
});

test("P6-a: scheduler reuses the decoded AudioBuffer — no second createBuffer/decode", () => {
  const { store, getCtx } = setup();
  store.binaryHandler(makePCM16(240));
  store.binaryHandler(makePCM16(240));
  const ctx = getCtx();
  // One createBuffer per decode; the scheduler consumes that buffer — it does
  // NOT createBuffer/decode a second time. So createBuffer calls === #chunks.
  assert.equal(ctx.createBufferCalls, 2);
  assert.equal(ctx.createdSources.length, 2);
  // Each source carries the already-decoded buffer + was connected once.
  for (const src of ctx.createdSources) {
    assert.ok(src.buffer !== null);
    assert.equal(src.connectCount, 1);
  }
});

test("P6-a negative: a straggler chunk decoded AFTER stop() is dropped (F-Sam-A3 race guard)", async () => {
  const bus = createEventBusForTesting();
  let ctx: StubSchedulableContext | null = null;
  let resolveBlob: ((b: AudioBufferLike) => void) | null = null;
  const blobPromise = new Promise<AudioBufferLike>((res) => { resolveBlob = res; });
  const store = createAudioStore({
    bus,
    audioContextFactory : () => { ctx = new StubSchedulableContext(); return ctx; },
    decodeBlobFn        : () => blobPromise,
    nowFn               : () => 1,
  });
  // 1. Blob chunk → idle→decoding; async decode pending.
  store.binaryHandler(new Blob([makePCM16(100)]));
  assert.equal(store.state(), "decoding");
  // 2. Sync chunk → decoding→playing; one source scheduled.
  store.binaryHandler(makePCM16(100));
  assert.equal(store.state(), "playing");
  assert.equal(ctx!.createdSources.length, 1);
  // 3. stop() → playing→idle; sources halted, cursor reset.
  store.stop();
  assert.equal(store.state(), "idle");
  // 4. Blob decode resolves AFTER stop(): onDecoded runs in idle; CHUNK_DECODED
  //    is a no-op there → the scheduler guard drops it BEFORE createBufferSource.
  resolveBlob!(new StubAudioBuffer(1, 50, 24000));
  await new Promise((r) => setImmediate(r));
  assert.equal(store.state(), "idle", "straggler must not restart playback");
  assert.equal(ctx!.createdSources.length, 1, "straggler yields ZERO new createBufferSource");
});

// ===========================================================================
// Phase 6 (00c) — P6-b: pause / resume / stop on real audio
// ===========================================================================

test("P6-b: pause() suspends the AudioContext", () => {
  const { store, getCtx } = setup();
  store.binaryHandler(makePCM16(240));
  store.pause();
  assert.equal(store.state(), "paused");
  assert.equal(getCtx().suspendCount, 1);
});

test("P6-b: resume() resumes the AudioContext", () => {
  const { store, getCtx } = setup();
  store.binaryHandler(makePCM16(240));
  store.pause();
  store.resume();
  assert.equal(store.state(), "playing");
  // Only the public resume() touched resume(); the running context never armed
  // the autoplay path, so this is exactly one call.
  assert.equal(getCtx().resumeCount, 1);
});

test("P6-b: stop() halts all scheduled sources + resets the gapless cursor to 0", () => {
  const { store, getCtx } = setup({ currentTime: 0 });
  store.binaryHandler(makePCM16(240));   // start 0
  store.binaryHandler(makePCM16(240));   // start 0.005 ; nextStartTime = 0.010
  const ctx = getCtx();
  store.stop();
  assert.ok(ctx.createdSources[0]!.stopped, "first source halted");
  assert.ok(ctx.createdSources[1]!.stopped, "second source halted");
  // A fresh chunk after stop() starts at currentTime (0), proving nextStartTime
  // reset to 0 — NOT 0.010 (which is what a non-reset cursor would yield).
  store.binaryHandler(makePCM16(240));
  assert.equal(ctx.createdSources[2]!.startTimes[0]!, 0);
});

// ===========================================================================
// Phase 6 (00c) — P6-c: completion-signal seam (signal-OUT only)
// ===========================================================================

test("P6-c: completion emits store_audio_ended exactly once (flag set, then last onended)", () => {
  const { store, getCtx, endedEvents, sendStreamComplete } = setup();
  store.binaryHandler(makePCM16(240));
  const ctx = getCtx();
  sendStreamComplete();                         // flag set, source still pending
  assert.equal(endedEvents.length, 0, "no completion while a source is still playing");
  ctx.createdSources[0]!.fireEnded();           // last source ends
  assert.equal(endedEvents.length, 1);
  assert.equal(store.state(), "ended", "PLAYBACK_ENDED drove XState to ended");
});

test("P6-c: an onended BEFORE the stream-complete flag does NOT complete (gate)", () => {
  const { store, getCtx, endedEvents } = setup();
  store.binaryHandler(makePCM16(240));
  const ctx = getCtx();
  ctx.createdSources[0]!.fireEnded();           // ends with flag still false
  assert.equal(endedEvents.length, 0, "no completion before the stream-complete flag");
  assert.equal(store.state(), "playing");
});

test("P6-c: a mid-stream source onended does NOT complete (only the last drains the set)", () => {
  const { store, getCtx, endedEvents, sendStreamComplete } = setup();
  store.binaryHandler(makePCM16(240));
  store.binaryHandler(makePCM16(240));
  const ctx = getCtx();
  sendStreamComplete();                         // flag set; 2 sources live
  ctx.createdSources[0]!.fireEnded();           // first source ends — one still live
  assert.equal(endedEvents.length, 0, "mid-stream onended must not complete");
  ctx.createdSources[1]!.fireEnded();           // last source ends — set drains
  assert.equal(endedEvents.length, 1);
});

test("P6-c (F-Sam-B2 drop-race): flag set AFTER the last onended still emits exactly once", () => {
  const { store, getCtx, endedEvents, sendStreamComplete } = setup();
  store.binaryHandler(makePCM16(240));
  const ctx = getCtx();
  ctx.createdSources[0]!.fireEnded();           // last onended fires FIRST (flag false)
  assert.equal(endedEvents.length, 0);
  sendStreamComplete();                         // flag arrives after — symmetric immediate emit
  assert.equal(endedEvents.length, 1);
  // A duplicate/late complete frame on an already-drained utterance is a no-op
  // (flag was reset to false by the one-shot completion).
  sendStreamComplete();
  assert.equal(endedEvents.length, 1, "no double emit on a late duplicate frame");
});

test("P6-c (F-Sam-B1 multi-utterance): utterance 2's first onended does NOT carry over utterance 1's flag", () => {
  const { store, getCtx, endedEvents, sendStreamComplete } = setup();
  // Utterance 1 — complete it.
  store.binaryHandler(makePCM16(240));
  const ctx = getCtx();
  sendStreamComplete();
  ctx.createdSources[0]!.fireEnded();
  assert.equal(endedEvents.length, 1);
  assert.equal(store.state(), "ended");
  // Utterance 2 — a fresh burst from "ended" resets the flag to false.
  store.binaryHandler(makePCM16(240));
  assert.equal(store.state(), "playing");
  ctx.createdSources[1]!.fireEnded();           // utterance 2's first onended — flag is false
  assert.equal(endedEvents.length, 1, "no premature completion from a carried-over flag");
  sendStreamComplete();                         // now legitimately complete utterance 2
  assert.equal(endedEvents.length, 2);
});

test("P6-c ownership boundary: store_audio_ended is a bare marker; AudioStore takes no TtsQueueStore", () => {
  const { store, getCtx, endedEvents, sendStreamComplete } = setup();
  store.binaryHandler(makePCM16(240));
  const ctx = getCtx();
  sendStreamComplete();
  ctx.createdSources[0]!.fireEnded();
  assert.equal(endedEvents.length, 1);
  // Signal-OUT only: the payload is a bare marker (F0 reads no fields), and the
  // store was constructed with NO queue-store injection — P6 structurally
  // cannot call TtsQueueStore.advance() / mutate the active id (COND-2).
  assert.deepEqual(endedEvents[0]!.payload, {});
  assert.equal(endedEvents[0]!.source, "AudioStore");
});

// ===========================================================================
// Phase 6 (00c) — P6-d / P6-e: autoplay-gesture recovery
// ===========================================================================

test("P6-d/e: a suspended context is resumed on first chunk; chunks are retained (F-Sam-C3)", () => {
  const { store, getCtx } = setup({ ctxState: "suspended" });
  store.binaryHandler(makePCM16(240));
  const ctx = getCtx();
  assert.ok(ctx.resumeCount >= 1, "suspended context resumed for autoplay recovery");
  // The chunk is still scheduled (retained) — it plays once the context resumes.
  assert.equal(ctx.createdSources.length, 1);
  assert.equal(store.state(), "playing");
});

test("P6-d/e: a running context needs no resume (no-op, no gesture listener)", () => {
  const { store, getCtx } = setup({ ctxState: "running" });
  store.binaryHandler(makePCM16(240));
  assert.equal(getCtx().resumeCount, 0, "already-unlocked context is never resumed");
});

test("P6-e (F-Sam-C1): resume() rejection on a suspended context emits audiocontext-blocked", async () => {
  const { store, stateEvents } = setup({
    ctxState     : "suspended",
    resumeResult : () => Promise.reject(new Error("autoplay blocked by gesture policy")),
  });
  store.binaryHandler(makePCM16(240));
  await new Promise((r) => setImmediate(r));    // let the rejected resume() settle
  const blocked = stateEvents.find(
    (e) => e.payload.state === "error" && e.payload.reason?.startsWith("audiocontext-blocked"),
  );
  assert.ok(blocked, "autoplay-blocked error emitted from the resume() rejection arm");
});

// ===========================================================================
// Parity B-1b — the per-utterance first-chunk flag (firstInUtterance)
//
// The TTFA stamp is taken on this flag, which is legacy's `isFirstChunk` branch
// in the PCM schedule path.
//
// 🔴 THE FLAG EXISTS BECAUSE `burstLength() === 1` IS NOT THE SAME PREDICATE, and
// the difference is invisible for exactly one utterance. `chunksInBurst` is reset
// by skip() and stop() and by NOTHING ELSE — the natural completion path
// (maybeComplete) leaves it standing — so on the second utterance it reads N+1 and
// never 1 again. A consumer keyed on the counter would stamp TTFA once per page
// load and then silently stop. The two-utterance test below is the one that
// separates the two implementations; a single-utterance test passes either way.
// ===========================================================================

test("B-1b: the first decoded chunk of an utterance carries firstInUtterance", () => {
  const { store, chunkEvents } = setup();
  store.binaryHandler(makePCM16(240));
  assert.equal(chunkEvents.length, 1);
  assert.equal(chunkEvents[0]!.payload.firstInUtterance, true);
});

test("B-1b: every LATER chunk of the same utterance carries it false", () => {
  const { store, chunkEvents } = setup();
  store.binaryHandler(makePCM16(240));
  store.binaryHandler(makePCM16(240));
  store.binaryHandler(makePCM16(240));
  assert.deepEqual(
    chunkEvents.map((e) => e.payload.firstInUtterance),
    [true, false, false],
  );
});

test("B-1b: a SECOND utterance flags its first chunk again, after a natural completion", () => {
  // The discriminating case. Note what is NOT done here: no skip(), no stop(). The
  // utterance ends the way a real one does — the stream-complete frame plus the last
  // source's onended — which is precisely the path that leaves chunksInBurst alone.
  const { store, getCtx, chunkEvents, endedEvents, sendStreamComplete } = setup();

  store.binaryHandler(makePCM16(240));
  store.binaryHandler(makePCM16(240));
  const ctx = getCtx();
  sendStreamComplete();
  ctx.createdSources[0]!.fireEnded();
  ctx.createdSources[1]!.fireEnded();
  assert.equal(endedEvents.length, 1, "utterance 1 must have completed naturally");

  // The counter is the thing that CANNOT tell you this is a new utterance.
  assert.equal(store.burstLength(), 2, "chunksInBurst survives a natural completion");

  store.binaryHandler(makePCM16(240));
  assert.equal(chunkEvents.length, 3);
  assert.equal(
    chunkEvents[2]!.payload.firstInUtterance, true,
    "the second utterance's first chunk must flag, though burstLength() is now 3",
  );
  assert.equal(store.burstLength(), 3);
});

test("B-1b: a chunk whose DECODE THREW does not consume the flag — the NEXT one carries it", () => {
  // TTFA is time to first AUDIO. A chunk that failed to decode produced none, so the
  // stamp belongs to whichever chunk first actually plays.
  //
  // This needs a decoder that fails ONCE and then works, which `setup`'s boolean
  // cannot express — its decodeThrows stub throws forever, so the store would never
  // emit a chunk event and the assertion below could not fail. Built by hand instead.
  const bus = createEventBusForTesting();
  const chunkEvents: LupinEvent<StoreAudioChunkDecodedPayload>[] = [];
  bus.on<StoreAudioChunkDecodedPayload>("store_audio_chunk_decoded", (e) => chunkEvents.push(e));

  let decodeCalls = 0;
  const store = createAudioStore({
    bus,
    audioContextFactory : (): SchedulableAudioContext => new StubSchedulableContext({}),
    decodeArrayBufferFn : (buf, ctx, rate) => {
      decodeCalls++;
      if (decodeCalls === 1) throw new Error("malformed PCM");
      return realDecodeArrayBuffer(buf, ctx, rate);
    },
    nowFn : () => 1_000_000,
  });

  store.binaryHandler(makePCM16(240));                 // decode 1 — throws
  assert.equal(chunkEvents.length, 0, "a failed decode emits no chunk event");

  store.binaryHandler(makePCM16(240));                 // decode 2 — succeeds
  assert.equal(chunkEvents.length, 1);
  assert.equal(
    chunkEvents[0]!.payload.firstInUtterance, true,
    "the flag must survive a decode that produced no audio",
  );
});

test("B-1b: after a stop(), the next chunk flags as first", () => {
  const { store, chunkEvents } = setup();
  store.binaryHandler(makePCM16(240));
  store.stop();
  store.binaryHandler(makePCM16(240));
  assert.deepEqual(
    chunkEvents.map((e) => e.payload.firstInUtterance),
    [true, true],
  );
});

// ---------------------------------------------------------------------------
// The TTS-mode seam. It arrived with the Q&A pane and shipped with no test:
// the coverage gate never said so because the TypeScript tier had been dying on
// its RSS ceiling before c8 reached the report, so `setTtsMode` / `ttsMode` sat
// at 0 behind a run that never produced a number. Measured 2026-09-23 at
// 11a6f9f3 once the tier could finish: AudioStore.ts 647/661 lines, 31/33
// functions, and the two missing functions are these.
//
// The no-op guard is the part worth pinning. `setTtsMode` returns early on a
// write of the value already held, so a restore path that re-asserts the
// current mode emits nothing and the pane does not repaint. An assertion on the
// stored value alone cannot see that — it reads "instant" either way — so every
// arm below counts the EVENTS.
// ---------------------------------------------------------------------------

function ttsModeSetup() {
  const bus = createEventBusForTesting();
  const modeEvents : LupinEvent<StoreTtsModeChangedPayload>[] = [];
  bus.on<StoreTtsModeChangedPayload>( "store_tts_mode_changed", ( e ) => modeEvents.push( e ) );
  const store = createAudioStore( {
    bus,
    audioContextFactory : (): SchedulableAudioContext => new StubSchedulableContext( {} ),
    nowFn               : () => 1_000_000,
  } );
  return { bus, store, modeEvents };
}

test( "the store starts in instant mode and has emitted nothing to say so", () => {
  const { store, modeEvents } = ttsModeSetup();
  assert.equal( store.ttsMode(), "instant" );
  assert.equal( modeEvents.length, 0, "the initial value is a default, not a change" );
} );

test( "a real mode change is stored and announced once, carrying the new mode", () => {
  const { store, modeEvents } = ttsModeSetup();
  store.setTtsMode( "reliable" );
  assert.equal( store.ttsMode(), "reliable" );
  assert.equal( modeEvents.length, 1 );
  assert.equal( modeEvents[0]!.payload.mode, "reliable" );
  assert.equal( modeEvents[0]!.source, "AudioStore" );
  assert.equal( modeEvents[0]!.ts, 1_000_000 );
} );

test( "writing the mode it already holds emits nothing — the no-op guard", () => {
  const { store, modeEvents } = ttsModeSetup();
  store.setTtsMode( "instant" );                       // the value it starts on
  assert.equal( modeEvents.length, 0, "a no-op write must not reach the bus" );
  store.setTtsMode( "reliable" );
  store.setTtsMode( "reliable" );                      // and again once moved
  assert.equal( modeEvents.length, 1, "only the first of the two reached the bus" );
  assert.equal( store.ttsMode(), "reliable" );
} );

test( "the mode moves back, so the guard is on equality and not on a one-way latch", () => {
  const { store, modeEvents } = ttsModeSetup();
  store.setTtsMode( "reliable" );
  store.setTtsMode( "instant" );
  assert.deepEqual( modeEvents.map( ( e ) => e.payload.mode ), [ "reliable", "instant" ] );
  assert.equal( store.ttsMode(), "instant" );
} );
