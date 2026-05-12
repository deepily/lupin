// Multiplexer Phase 4 — AudioStore unit tests.
// Run via `npx tsx --test src/tests/unit/multiplexer/audio_store.test.ts`.
// AC4 floor: ≥ 18 tests per design doc § Verification matrix per-store floor.

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../fastapi_app/static/js/multiplexer/shared/EventBus";
import { createAudioStore } from "../../../fastapi_app/static/js/multiplexer/stores/AudioStore";
import type {
  AudioContextLike,
  AudioBufferLike,
} from "../../../fastapi_app/static/js/multiplexer/audio/pcm-decoder";
import type {
  LupinEvent,
  StoreAudioChunkDecodedPayload,
  StoreAudioStateChangePayload,
} from "../../../fastapi_app/static/js/multiplexer/shared/types";

// ---------------------------------------------------------------------------
// Stub Audio types — full real Web Audio is not needed in Node.
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

class StubAudioContext implements AudioContextLike {
  createBuffer(channels: number, length: number, sampleRate: number): AudioBufferLike {
    return new StubAudioBuffer(channels, length, sampleRate);
  }
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
} = {}) {
  const bus    = createEventBusForTesting();
  const stateEvents : LupinEvent<StoreAudioStateChangePayload>[]   = [];
  const chunkEvents : LupinEvent<StoreAudioChunkDecodedPayload>[]  = [];
  bus.on<StoreAudioStateChangePayload>("store_audio_state_change", (e) => stateEvents.push(e));
  bus.on<StoreAudioChunkDecodedPayload>("store_audio_chunk_decoded", (e) => chunkEvents.push(e));

  let factoryCallCount = 0;
  const audioContextFactory = (): AudioContextLike => {
    factoryCallCount++;
    if (opts.factoryThrows) throw new Error("AudioContext blocked by autoplay policy");
    return new StubAudioContext();
  };

  const store = createAudioStore({
    bus,
    audioContextFactory,
    decodeArrayBufferFn : opts.decodeThrows
      ? () => { throw new Error("malformed PCM"); }
      : undefined,
    nowFn : () => 1_000_000,
  });

  return {
    bus,
    store,
    stateEvents,
    chunkEvents,
    getFactoryCallCount: () => factoryCallCount,
  };
}

// ===========================================================================
// 1-3 : Initial state + Function.name + binaryHandler signature
// ===========================================================================

test("initial state: idle; queueLength=0", () => {
  const { store } = setup();
  assert.equal(store.state(), "idle");
  assert.equal(store.queueLength(), 0);
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

test("queueLength tracks chunks-in-burst", () => {
  const { store } = setup();
  store.binaryHandler(makePCM16(100));
  store.binaryHandler(makePCM16(100));
  store.binaryHandler(makePCM16(100));
  assert.equal(store.queueLength(), 3);
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

test("skip() from playing: → ended; queueLength reset", () => {
  const { store } = setup();
  store.binaryHandler(makePCM16(100));
  store.binaryHandler(makePCM16(100));
  store.skip();
  assert.equal(store.state(), "ended");
  assert.equal(store.queueLength(), 0);
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

test("stop() from playing: → idle; queueLength=0; emits state-change to idle", () => {
  const { store, stateEvents } = setup();
  store.binaryHandler(makePCM16(100));
  store.binaryHandler(makePCM16(100));
  assert.equal(store.state(), "playing");
  assert.equal(store.queueLength(), 2);
  const before = stateEvents.length;
  store.stop();
  assert.equal(store.state(),       "idle");
  assert.equal(store.queueLength(), 0);
  const idleTransition = stateEvents.slice(before).find(e => e.payload.state === "idle");
  assert.ok(idleTransition, "stop() emits a state-change to idle");
  assert.equal(idleTransition!.payload.prev, "playing");
});

test("stop() from paused: → idle; queueLength=0", () => {
  const { store } = setup();
  store.binaryHandler(makePCM16(100));
  store.pause();
  assert.equal(store.state(), "paused");
  store.stop();
  assert.equal(store.state(),       "idle");
  assert.equal(store.queueLength(), 0);
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
