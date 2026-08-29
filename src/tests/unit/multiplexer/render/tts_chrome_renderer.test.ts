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
  type TtsQueueStoreLike,
} from "../../../../lupin_app/static/js/multiplexer/render/TtsChromeRenderer";
import type {
  AudioPlaybackState,
  StoreAudioStateChangePayload,
  StoreAudioChunkDecodedPayload,
  TtsQueueItem,
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
    burstLength : (): number             => queue,   // OQ-F0.4 rename
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

// WP4 — TtsQueueStore mock (active head + pending tail + mutator call tracking).
// 70cbff3e — extended with focusMode() read + resumeFocus() mutator.
interface FakeTtsQueueCalls {
  removeById  : string[];
  clear       : number;
  resumeFocus : number;
}

function makeTtsQueueStore(): {
  store      : TtsQueueStoreLike;
  calls      : FakeTtsQueueCalls;
  setActive  : (item: TtsQueueItem | null) => void;
  setPending : (items: TtsQueueItem[]) => void;
  setFocus   : (on: boolean) => void;
} {
  let active    : TtsQueueItem | null = null;
  let pending   : TtsQueueItem[] = [];
  let focusMode = false;
  const calls : FakeTtsQueueCalls = { removeById: [], clear: 0, resumeFocus: 0 };
  const store : TtsQueueStoreLike = {
    current        : (): string | null => (active === null ? null : active.id_hash),
    activeItem     : (): TtsQueueItem | null => active,
    pending        : (): ReadonlyArray<TtsQueueItem> => pending.slice(),
    itemQueueLength: (): number => pending.length,
    removeById     : (id: string): void => { calls.removeById.push(id); },
    clear          : (): void => { calls.clear += 1; },
    focusMode      : (): boolean => focusMode,
    resumeFocus    : (): void => { calls.resumeFocus += 1; },
  };
  return {
    store,
    calls,
    setActive : (item: TtsQueueItem | null): void => { active = item; },
    setPending: (items: TtsQueueItem[]): void => { pending = items; },
    setFocus  : (on: boolean): void => { focusMode = on; },
  };
}

// N dummy pending items — for the count-driven tests that predate the WP4 queue.
function pendingItems(n: number): TtsQueueItem[] {
  return Array.from({ length: n }, (_v, i) => ({ id_hash: `seed-${i}`, ttsText: `say ${i}`, addedAt: 0 }));
}

function ttsItem(idHash: string, over: Partial<TtsQueueItem> = {}): TtsQueueItem {
  return { id_hash: idHash, ttsText: `say ${idHash}`, addedAt: 0, ...over };
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
  ttsQueue : ReturnType<typeof makeTtsQueueStore>;
  raf      : RafHarness;
  renderer : TtsChromeRenderer;
  root     : HTMLElement;
}

function setupRenderer(initialState: AudioPlaybackState = "playing", initialQueue: number = 0): Setup {
  const bus      = createEventBusForTesting();
  const audio    = makeAudioStore(initialState, initialQueue);
  const ttsQueue = makeTtsQueueStore();
  // WP4 — the header/queue count is now sourced from the item queue (pending),
  // not the audio burst. Seed pending = initialQueue so the pre-WP4 count tests
  // stay valid against the new source.
  ttsQueue.setPending(pendingItems(initialQueue));
  const raf      = makeRafHarness();
  const renderer = createTtsChromeRenderer({
    eventBus               : bus,
    stores                 : { audio: audio.store, ttsQueue: ttsQueue.store },
    requestAnimationFrameFn: raf.raf,
    cancelAnimationFrameFn : raf.caf,
  });
  const root = document.createElement("div");
  root.id = "tts-pane";
  document.body.appendChild(root);
  return { bus, audio, ttsQueue, raf, renderer, root };
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
  assert.ok( root.querySelector(".tts-chrome") !== null );
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
    // desync-fix: seed 1 pending so the chrome (queue-driven non-empty) renders
    // for EVERY audio state incl. idle — this test asserts the chrome's
    // data-state tracks the audio state, which requires a non-empty queue (an
    // empty queue renders the empty panel, always data-state idle).
    const { renderer, root, bus, audio, raf } = setupRenderer(from, 1);
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
  const { renderer, root, audio } = setupRenderer("playing", 1);   // desync-fix: seed queue → chrome renders controls
  renderer.mount(root);
  root.querySelector<HTMLButtonElement>(".tts-btn-toggle")!.click();
  assert.equal(audio.calls.pause,  1);
  assert.equal(audio.calls.resume, 0);
  renderer.unmount();
});

test("Pause/Resume toggle in paused state dispatches AudioStore.resume()", () => {
  const { renderer, root, audio } = setupRenderer("paused", 1);   // desync-fix: seed queue → chrome renders controls
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
  const { renderer, root, audio } = setupRenderer("playing", 1);   // desync-fix: seed queue → chrome renders controls
  renderer.mount(root);
  root.querySelector<HTMLButtonElement>(".tts-btn-skip")!.click();
  assert.equal(audio.calls.skip, 1);
  renderer.unmount();
});

// ===========================================================================
// 2 storm-safety tests (Pass 1 F-13 + Q-B9 RAF coalescing)
// ===========================================================================

test("storm safety (a): 100 chunk_decoded events coalesce into ≤1 render cycle", () => {
  const { renderer, root, bus, raf, ttsQueue } = setupRenderer("playing", 0);
  renderer.mount(root);
  const initialChromeEl = root.querySelector(".tts-chrome");
  // Track render cycles by counting chrome replacements via MutationObserver-free
  // proxy: spy via `forceRenderForTesting` emulation? Simpler: count actual
  // RAF invocations needed to flush all queued events.
  for (let i = 0; i < 100; i++) {
    ttsQueue.setPending(pendingItems(i));
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
  // desync-fix: seed 1 pending so the chrome tracks each audio state (empty queue
  // would render the empty panel, always data-state idle).
  const { renderer, root, bus, raf, audio } = setupRenderer("idle", 1);
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
  // desync-fix: after stop→idle the audio state is idle, but the item queue's
  // pending tail is RETAINED (stop de-lights the active head, keeps pending —
  // F0-f), so the pane is queue-driven NON-empty → the chrome renders at
  // state=idle (all controls disabled), NOT the empty panel. (Pre-fix this
  // asserted the empty panel because the empty-state was audio-idle-driven.)
  assert.equal(root.querySelector<HTMLElement>(".tts-chrome")!.dataset.state, "idle");
  assert.match(root.querySelector(".tts-queue-length")!.textContent ?? "", /Queued: 5/, "pending retained after stop");
  assert.ok( root.querySelector(".tts-queue-empty-state") === null, "pending retained → not the empty panel" );
  renderer.unmount();
});

// ===========================================================================
// Mixed-event coalescing + forceRenderForTesting
// ===========================================================================

test("mixed-event storm: state_change + chunk_decoded events share the same pendingRender flag", () => {
  const { renderer, root, bus, raf, audio, ttsQueue } = setupRenderer("idle");
  renderer.mount(root);
  audio.setState("playing");
  emitState(bus, { state: "playing", prev: "idle" });
  ttsQueue.setPending(pendingItems(7));
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
  // desync-fix: seed pending=1 (not 0) so the chrome (queue-driven non-empty)
  // renders throughout — pending=0 would render the empty panel (no queue-length).
  const { renderer, root, ttsQueue } = setupRenderer("playing", 1);
  renderer.mount(root);
  // Initial paint shows the seeded pending count.
  assert.match(root.querySelector(".tts-queue-length")!.textContent ?? "", /Queued: 1/);
  // Mutate the item queue WITHOUT firing an event.
  ttsQueue.setPending(pendingItems(42));
  // Without forceRenderForTesting, DOM still shows the old count (no event fired).
  assert.match(root.querySelector(".tts-queue-length")!.textContent ?? "", /Queued: 1/);
  renderer.forceRenderForTesting();
  // Now DOM reflects queue=42.
  assert.match(root.querySelector(".tts-queue-length")!.textContent ?? "", /Queued: 42/);
  renderer.unmount();
});

test("forceRenderForTesting before mount is a no-op (no throw)", () => {
  const { renderer } = setupRenderer();
  renderer.forceRenderForTesting();
});

// ===========================================================================
// Lane 0a — uniform section-header bar (🔊 Playing + queue count + collapse)
// ===========================================================================

test("Lane 0a: TTS pane renders the .section-header bar (🔊 Playing), count = queue length, chrome nested in .section-content", () => {
  const { renderer, root, ttsQueue } = setupRenderer("playing", 3);
  renderer.mount(root);

  const header = root.querySelector(".section-header") as HTMLElement;
  assert.notEqual(header, null, "section-header bar present");
  assert.ok(header.querySelector("h3")!.textContent!.includes("🔊 Playing"), "🔊 Playing title");
  assert.ok( root.firstElementChild === header, "header is above the body" );

  const count = root.querySelector(".section-header-count") as HTMLElement;
  assert.equal(count.textContent, "3", "header count = initial queue length");

  // Transport chrome lives in the content wrapper below the header.
  assert.ok( root.querySelector(".section-content .tts-queue-length") !== null, "chrome nested in section-content" );

  // Count tracks the queue length on re-render.
  ttsQueue.setPending(pendingItems(5));
  renderer.forceRenderForTesting();
  assert.equal(count.textContent, "5", "header count updated to 5");
  renderer.unmount();
});

test("Lane 0a: clicking the TTS header toggles session-only collapse (data-collapsed + chevron)", () => {
  const { renderer, root } = setupRenderer("playing", 0);
  renderer.mount(root);
  const header = root.querySelector(".section-header") as HTMLElement;
  const chevron = header.querySelector(".toggle-button") as HTMLElement;

  (header.querySelector("h3") as HTMLElement).dispatchEvent(new Event("click", { bubbles: true }));
  assert.equal(root.getAttribute("data-collapsed"), "true");
  assert.equal(chevron.textContent, "▶");

  chevron.dispatchEvent(new Event("click", { bubbles: true }));
  assert.equal(root.getAttribute("data-collapsed"), "false");
  assert.equal(chevron.textContent, "▼");
  renderer.unmount();
});

// ===========================================================================
// WP4 — active/pending/empty rendering + store_tts_queue_changed + handlers
// ===========================================================================

test("WP4: active + pending render one .tts-active-card + N .tts-minimized; header count = TOTAL", () => {
  const { renderer, root, ttsQueue } = setupRenderer("playing", 0);
  ttsQueue.setActive(ttsItem("A"));
  ttsQueue.setPending([ttsItem("p1"), ttsItem("p2")]);
  renderer.mount(root);
  assert.equal(root.querySelectorAll(".tts-active-card").length, 1);
  assert.equal(root.querySelectorAll(".tts-minimized").length, 2);
  assert.equal(root.querySelector(".section-header-count")!.textContent, "3", "count = 1 active + 2 pending");
  renderer.unmount();
});

test("WP4: pending minimized cards render in 1-indexed queue order", () => {
  const { renderer, root, ttsQueue } = setupRenderer("playing", 0);
  ttsQueue.setActive(ttsItem("A"));
  ttsQueue.setPending([ttsItem("p1"), ttsItem("p2"), ttsItem("p3")]);
  renderer.mount(root);
  const positions = Array.from(root.querySelectorAll(".tts-minimized .tts-position")).map(e => e.textContent);
  assert.deepEqual(positions, ["1", "2", "3"]);
  renderer.unmount();
});

test("WP4: empty queue (no active, no pending) → no cards; idle chrome shows empty panel; count 0", () => {
  const { renderer, root } = setupRenderer("idle", 0);
  renderer.mount(root);
  assert.ok( root.querySelector(".tts-active-card") === null );
  assert.ok( root.querySelector(".tts-minimized") === null );
  assert.match(root.querySelector(".tts-queue-empty-state")!.textContent ?? "", /Nothing in the queue/);
  assert.equal(root.querySelector(".section-header-count")!.textContent, "0");
  renderer.unmount();
});

test("WP4 CLEAR-PRIOR-THEN-SET: current() A→B leaves exactly one active card (=B), never both", () => {
  const { renderer, root, ttsQueue, bus, raf } = setupRenderer("playing", 0);
  ttsQueue.setActive(ttsItem("A", { ttsText: "alpha" }));
  renderer.mount(root);
  assert.equal(root.querySelectorAll(".tts-active-card").length, 1);
  assert.match(root.querySelector(".tts-active-card .tts-message")!.textContent ?? "", /alpha/);
  // Store advanced A→B; emit the queue-changed event → coalesced re-render.
  ttsQueue.setActive(ttsItem("B", { ttsText: "bravo" }));
  bus.emit({ type: "store_tts_queue_changed", payload: { activeNotificationId: "B", pending: [] }, source: "test", ts: 0 });
  raf.flush();
  const actives = root.querySelectorAll(".tts-active-card");
  assert.equal(actives.length, 1, "exactly one active card after A→B — the prior bubble is cleared before the new one is set");
  assert.match(root.querySelector(".tts-active-card .tts-message")!.textContent ?? "", /bravo/);
  renderer.unmount();
});

test("WP4: store_tts_queue_changed schedules a coalesced render (RAF), NOT a direct paint", () => {
  const { renderer, root, ttsQueue, bus, raf } = setupRenderer("playing", 0);
  renderer.mount(root);
  ttsQueue.setActive(ttsItem("A"));
  bus.emit({ type: "store_tts_queue_changed", payload: { activeNotificationId: "A", pending: [] }, source: "test", ts: 0 });
  assert.equal(raf.pendingCount(), 1, "queue-changed → 1 pending RAF");
  raf.flush();
  assert.equal(root.querySelectorAll(".tts-active-card").length, 1);
  renderer.unmount();
});

test("WP4: active-card delete dispatches ttsQueue.removeById(id_hash) (consume-only mutator)", () => {
  const { renderer, root, ttsQueue } = setupRenderer("playing", 0);
  ttsQueue.setActive(ttsItem("act-id"));
  renderer.mount(root);
  (root.querySelector(".tts-active-card .tts-delete-button") as HTMLButtonElement).click();
  assert.deepEqual(ttsQueue.calls.removeById, ["act-id"]);
  renderer.unmount();
});

test("WP4: active-card Stop dispatches audio.stop()", () => {
  const { renderer, root, ttsQueue, audio } = setupRenderer("playing", 0);
  ttsQueue.setActive(ttsItem("A"));
  renderer.mount(root);
  (root.querySelector(".tts-active-card .tts-stop-button") as HTMLButtonElement).click();
  assert.equal(audio.calls.stop, 1);
  renderer.unmount();
});

test("WP4: minimized-card delete dispatches ttsQueue.removeById(id_hash)", () => {
  const { renderer, root, ttsQueue } = setupRenderer("playing", 0);
  ttsQueue.setActive(ttsItem("A"));
  ttsQueue.setPending([ttsItem("pend-id")]);
  renderer.mount(root);
  (root.querySelector(".tts-minimized .tts-delete-button") as HTMLButtonElement).click();
  assert.deepEqual(ttsQueue.calls.removeById, ["pend-id"]);
  renderer.unmount();
});

test("WP4: Clear-all dispatches ttsQueue.clear() (non-empty queue)", () => {
  const { renderer, root, ttsQueue } = setupRenderer("playing", 0);
  ttsQueue.setActive(ttsItem("A"));
  ttsQueue.setPending([ttsItem("p1")]);   // non-empty → clear-all enabled
  renderer.mount(root);
  (root.querySelector(".tts-btn-clear-all") as HTMLButtonElement).click();
  assert.equal(ttsQueue.calls.clear, 1);
  renderer.unmount();
});

// ---------------------------------------------------------------------------
// 70cbff3e — focus-mode integration (renderer reads focusMode() + wires
// onFocusResume, and its queueEmpty is focus-aware).
// ---------------------------------------------------------------------------

test("70cbff3e (T13): focus mode renders 'Paused: N waiting' header + Resume button (active discarded, pending held)", () => {
  const { renderer, root, ttsQueue } = setupRenderer("ended", 0);
  ttsQueue.setActive(null);                              // AR head discarded at enter
  ttsQueue.setPending([ttsItem("p1"), ttsItem("p2")]);  // held pending tail
  ttsQueue.setFocus(true);
  renderer.mount(root);
  const header = root.querySelector(".tts-playing-header")!;
  assert.match(header.textContent ?? "", /Paused: 2 waiting/);
  assert.equal(header.className, "tts-playing-header focus-mode");
  assert.ok( root.querySelector(".tts-btn-resume") !== null, "Resume present in focus mode" );
  renderer.unmount();
});

test("70cbff3e (T13b): focus with ZERO pending still renders the chrome (focus-aware queueEmpty), never the empty panel", () => {
  const { renderer, root, ttsQueue } = setupRenderer("ended", 0);
  ttsQueue.setActive(null);
  ttsQueue.setPending([]);
  ttsQueue.setFocus(true);
  renderer.mount(root);
  assert.ok( root.querySelector(".tts-queue-empty-state") === null, "focused ⟹ not the empty panel" );
  assert.match((root.querySelector(".tts-playing-header")!).textContent ?? "", /Paused: 0 waiting/);
  renderer.unmount();
});

test("70cbff3e (T14): clicking the focus Resume button dispatches ttsQueue.resumeFocus(), NOT audio.resume()", () => {
  const { renderer, root, ttsQueue, audio } = setupRenderer("ended", 0);
  ttsQueue.setActive(null);
  ttsQueue.setPending([ttsItem("p1")]);
  ttsQueue.setFocus(true);
  renderer.mount(root);
  (root.querySelector(".tts-btn-resume") as HTMLButtonElement).click();
  assert.equal(ttsQueue.calls.resumeFocus, 1, "focus Resume → resumeFocus()");
  assert.equal(audio.calls.resume, 0, "focus Resume must NOT unpause audio");
  renderer.unmount();
});
