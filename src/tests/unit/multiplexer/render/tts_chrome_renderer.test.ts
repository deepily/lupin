// Multiplexer Phase 6b — TtsChromeRenderer unit tests.
// AC5b floor: ≥13 cases per design doc § AC5b enumeration sub-table.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createTtsChromeRenderer,
  type TtsChromeRenderer,
  type AudioStoreLike,
} from "../../../../lupin_app/static/js/multiplexer/render/TtsChromeRenderer";
import type {
  AudioPlaybackState,
  StoreAudioStateChangePayload,
  StoreAudioChunkDecodedPayload,
} from "../../../../lupin_app/static/js/multiplexer/shared/types";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

// ---------------------------------------------------------------------------
// Test fixtures
// ---------------------------------------------------------------------------

interface FakeAudioCalls {
  pause  : number;
  resume : number;
  stop   : number;
  skip   : number;
  /** Tracks queue length when stop() is invoked (for stop-semantics test). */
  queueAtStop: number;
}

function makeAudioStore(initialState: AudioPlaybackState = "playing", initialQueue: number = 0): {
  store: AudioStoreLike;
  calls: FakeAudioCalls;
  setState: (s: AudioPlaybackState) => void;
  setQueue: (n: number) => void;
} {
  let state = initialState;
  let queue = initialQueue;
  const calls: FakeAudioCalls = { pause: 0, resume: 0, stop: 0, skip: 0, queueAtStop: -1 };
  const store: AudioStoreLike = {
    state       : (): AudioPlaybackState => state,
    queueLength : (): number             => queue,
    pause       : (): void => { calls.pause  += 1; },
    resume      : (): void => { calls.resume += 1; },
    stop        : (): void => {
      calls.stop += 1;
      calls.queueAtStop = queue;
      // Phase 1.3 contract: stop() clears queue + transitions to idle.
      queue = 0;
      state = "idle";
    },
    skip        : (): void => { calls.skip += 1; },
  };
  return {
    store,
    calls,
    setState: (s: AudioPlaybackState): void => { state = s; },
    setQueue: (n: number): void => { queue = n; },
  };
}

interface RafHarness {
  raf: (cb: FrameRequestCallback) => number;
  caf: (h: number) => void;
  flush(): void;
  pendingCount(): number;
}

function makeRafHarness(): RafHarness {
  let nextId = 1;
  const queued = new Map<number, FrameRequestCallback>();
  return {
    raf: (cb: FrameRequestCallback): number => {
      const id = nextId++;
      queued.set(id, cb);
      return id;
    },
    caf: (h: number): void => { queued.delete(h); },
    flush(): void {
      const snap = Array.from(queued.entries());
      queued.clear();
      for (const [, cb] of snap) cb(performance.now());
    },
    pendingCount: (): number => queued.size,
  };
}

interface Setup {
  bus      : ReturnType<typeof createEventBusForTesting>;
  audio    : ReturnType<typeof makeAudioStore>;
  raf      : RafHarness;
  renderer : TtsChromeRenderer;
  root     : HTMLElement;
}

function setupRenderer(initialState: AudioPlaybackState = "playing", initialQueue: number = 0): Setup {
  const bus   = createEventBusForTesting();
  const audio = makeAudioStore(initialState, initialQueue);
  const raf   = makeRafHarness();
  const renderer = createTtsChromeRenderer({
    eventBus               : bus,
    stores                 : { audio: audio.store },
    requestAnimationFrameFn: raf.raf,
    cancelAnimationFrameFn : raf.caf,
  });
  const root = document.createElement("div");
  root.id = "tts-pane";
  document.body.appendChild(root);
  return { bus, audio, raf, renderer, root };
}

function emitState(bus: ReturnType<typeof createEventBusForTesting>, payload: StoreAudioStateChangePayload): void {
  bus.emit({ type: "store_audio_state_change", payload, source: "test", ts: 0 });
}

function emitChunk(bus: ReturnType<typeof createEventBusForTesting>, payload: StoreAudioChunkDecodedPayload): void {
  bus.emit({ type: "store_audio_chunk_decoded", payload, source: "test", ts: 0 });
}

// ===========================================================================
// Mount + idempotency
// ===========================================================================

test("mount: renders chrome on initial paint; root contains .tts-chrome", () => {
  const { renderer, root } = setupRenderer("idle");
  renderer.mount(root);
  assert.notEqual(root.querySelector(".tts-chrome"), null);
  renderer.unmount();
});

test("mount idempotency: second mount throws Error('TtsChromeRenderer already mounted')", () => {
  const { renderer, root } = setupRenderer();
  renderer.mount(root);
  assert.throws(() => renderer.mount(root), /TtsChromeRenderer already mounted/);
  renderer.unmount();
});

test("unmount: clears root + cancels pending RAF + is idempotent", () => {
  const { renderer, root, bus, raf } = setupRenderer("idle");
  renderer.mount(root);
  // Fire an event but DON'T flush — RAF is pending.
  emitState(bus, { state: "decoding", prev: "idle" });
  assert.equal(raf.pendingCount(), 1, "RAF queued");
  renderer.unmount();
  assert.equal(raf.pendingCount(), 0, "pending RAF cancelled on unmount");
  assert.equal(root.children.length, 0, "root cleared");
  // Idempotent.
  renderer.unmount();
});

// ===========================================================================
// 7 state-driven render transitions
// ===========================================================================

const TRANSITIONS: Array<[AudioPlaybackState, AudioPlaybackState, string]> = [
  ["idle",     "decoding", "idle → decoding"],
  ["decoding", "playing",  "decoding → playing"],
  ["playing",  "paused",   "playing → paused"],
  ["paused",   "playing",  "paused → playing"],
  ["playing",  "ended",    "playing → ended"],
  ["ended",    "idle",     "ended → idle (post-stop)"],
  ["playing",  "error",    "playing → error (any → error)"],
];

for (const [from, to, label] of TRANSITIONS) {
  test(`state transition: ${label} re-renders chrome with new data-state`, () => {
    const { renderer, root, bus, audio, raf } = setupRenderer(from);
    renderer.mount(root);
    assert.equal(root.querySelector<HTMLElement>(".tts-chrome")!.dataset.state, from);
    audio.setState(to);
    emitState(bus, { state: to, prev: from });
    raf.flush();
    assert.equal(root.querySelector<HTMLElement>(".tts-chrome")!.dataset.state, to, `data-state reflects ${to}`);
    renderer.unmount();
  });
}

// ===========================================================================
// 4 control wiring tests — Pause / Resume / Stop / Skip dispatched correctly
// ===========================================================================

test("Pause/Resume toggle in playing state dispatches AudioStore.pause()", () => {
  const { renderer, root, audio } = setupRenderer("playing");
  renderer.mount(root);
  root.querySelector<HTMLButtonElement>(".tts-btn-toggle")!.click();
  assert.equal(audio.calls.pause,  1);
  assert.equal(audio.calls.resume, 0);
  renderer.unmount();
});

test("Pause/Resume toggle in paused state dispatches AudioStore.resume()", () => {
  const { renderer, root, audio } = setupRenderer("paused");
  renderer.mount(root);
  root.querySelector<HTMLButtonElement>(".tts-btn-toggle")!.click();
  assert.equal(audio.calls.resume, 1);
  assert.equal(audio.calls.pause,  0);
  renderer.unmount();
});

test("Stop button dispatches AudioStore.stop() (Pass 2 A6)", () => {
  const { renderer, root, audio } = setupRenderer("playing", 3);
  renderer.mount(root);
  root.querySelector<HTMLButtonElement>(".tts-btn-stop")!.click();
  assert.equal(audio.calls.stop, 1, "stop() invoked exactly once");
});

test("Skip button dispatches AudioStore.skip()", () => {
  const { renderer, root, audio } = setupRenderer("playing");
  renderer.mount(root);
  root.querySelector<HTMLButtonElement>(".tts-btn-skip")!.click();
  assert.equal(audio.calls.skip, 1);
  renderer.unmount();
});

// ===========================================================================
// 2 storm-safety tests (Pass 1 F-13 + Q-B9 RAF coalescing)
// ===========================================================================

test("storm safety (a): 100 chunk_decoded events coalesce into ≤1 render cycle", () => {
  const { renderer, root, bus, raf, audio } = setupRenderer("playing", 0);
  renderer.mount(root);
  const initialChromeEl = root.querySelector(".tts-chrome");
  // Track render cycles by counting chrome replacements via MutationObserver-free
  // proxy: spy via `forceRenderForTesting` emulation? Simpler: count actual
  // RAF invocations needed to flush all queued events.
  for (let i = 0; i < 100; i++) {
    audio.setQueue(i);
    emitChunk(bus, { durationMs: 10, sampleRate: 24000, frameCount: 240 });
  }
  // Even after 100 events, only ONE RAF should be pending (storm coalescing).
  assert.equal(raf.pendingCount(), 1, "100 chunk events → 1 pending RAF");
  raf.flush();
  // After flush: queueLength should be 99 (last value set), and only one
  // chrome replacement happened.
  assert.match(root.querySelector(".tts-queue-length")!.textContent ?? "", /Queued: 99/);
  // The chrome element identity changed (one replacement), but only once.
  const finalChromeEl = root.querySelector(".tts-chrome");
  assert.notEqual(finalChromeEl, initialChromeEl, "chrome replaced after flush");
  renderer.unmount();
});

test("storm safety (b): 5 state_change events coalesce into ≤1 render cycle", () => {
  const { renderer, root, bus, raf, audio } = setupRenderer("idle");
  renderer.mount(root);
  // Fire 5 transitions synchronously.
  const states: AudioPlaybackState[] = ["decoding", "playing", "paused", "playing", "ended"];
  for (const s of states) {
    audio.setState(s);
    emitState(bus, { state: s, prev: "idle" });
  }
  assert.equal(raf.pendingCount(), 1, "5 state_change events → 1 pending RAF (coalesced)");
  raf.flush();
  // Final state in DOM matches last emitted.
  assert.equal(root.querySelector<HTMLElement>(".tts-chrome")!.dataset.state, "ended");
  renderer.unmount();
});

// ===========================================================================
// stop() semantics test (Pass 2 A6 + Phase 1.3 contract)
// ===========================================================================

test("stop semantics: clicking Stop clears queue to 0 + transitions state to idle (Phase 1 prereq #10)", () => {
  const { renderer, root, audio, bus, raf } = setupRenderer("playing", 5);
  renderer.mount(root);
  // Verify initial paint shows queue=5 + state=playing.
  assert.match(root.querySelector(".tts-queue-length")!.textContent ?? "", /Queued: 5/);
  assert.equal(root.querySelector<HTMLElement>(".tts-chrome")!.dataset.state, "playing");
  // Click Stop.
  root.querySelector<HTMLButtonElement>(".tts-btn-stop")!.click();
  // Phase 1.3 contract: stop() recorded queue=5 BEFORE clearing it.
  assert.equal(audio.calls.queueAtStop, 5, "stop() observed queue=5 before clearing");
  // Simulate the AudioStore-emitted state_change(idle, prev: playing) that fires after stop().
  emitState(bus, { state: "idle", prev: "playing" });
  raf.flush();
  // Re-render reflects: state=idle + queue=0.
  assert.equal(root.querySelector<HTMLElement>(".tts-chrome")!.dataset.state, "idle");
  assert.match(root.querySelector(".tts-queue-length")!.textContent ?? "", /Queued: 0/);
  renderer.unmount();
});

// ===========================================================================
// Mixed-event coalescing + forceRenderForTesting
// ===========================================================================

test("mixed-event storm: state_change + chunk_decoded events share the same pendingRender flag", () => {
  const { renderer, root, bus, raf, audio } = setupRenderer("idle");
  renderer.mount(root);
  audio.setState("playing");
  emitState(bus, { state: "playing", prev: "idle" });
  audio.setQueue(7);
  emitChunk(bus, { durationMs: 10, sampleRate: 24000, frameCount: 240 });
  emitChunk(bus, { durationMs: 10, sampleRate: 24000, frameCount: 240 });
  // Three events of two kinds → still just ONE pending RAF (shared flag).
  assert.equal(raf.pendingCount(), 1);
  raf.flush();
  assert.equal(root.querySelector<HTMLElement>(".tts-chrome")!.dataset.state, "playing");
  assert.match(root.querySelector(".tts-queue-length")!.textContent ?? "", /Queued: 7/);
  renderer.unmount();
});

test("forceRenderForTesting: synchronous re-render (bypasses RAF)", () => {
  const { renderer, root, audio } = setupRenderer("playing", 0);
  renderer.mount(root);
  // Mutate audio store WITHOUT firing an event.
  audio.setQueue(42);
  // Without forceRenderForTesting, DOM still shows queue=0 (no event fired).
  assert.match(root.querySelector(".tts-queue-length")!.textContent ?? "", /Queued: 0/);
  renderer.forceRenderForTesting();
  // Now DOM reflects queue=42.
  assert.match(root.querySelector(".tts-queue-length")!.textContent ?? "", /Queued: 42/);
  renderer.unmount();
});

test("forceRenderForTesting before mount is a no-op (no throw)", () => {
  const { renderer } = setupRenderer();
  renderer.forceRenderForTesting();
});
