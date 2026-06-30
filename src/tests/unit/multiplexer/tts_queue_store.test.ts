// Multiplexer F0 (00b) — TtsQueueStore unit tests.
// Run via `npx tsx --test src/tests/unit/multiplexer/tts_queue_store.test.ts`.
// Coverage (c8 --100 lines/branches/functions):
//   npx c8 --100 --include='src/lupin_app/static/js/multiplexer/stores/TtsQueueStore.ts' \
//     --reporter=text npx tsx --test src/tests/unit/multiplexer/tts_queue_store.test.ts
//
// Covers F0-a (active-item id), F0-b (notification-level item queue), and F0-f
// (completion-driven self-advance via store_audio_ended + stop-clear via
// store_audio_state_change{idle}). The store has NO DOM surface — its parity is
// behavioral, proven here + by downstream consumption (Plan 01 B4 / 02 / 03).

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createTtsQueueStore } from "../../../lupin_app/static/js/multiplexer/stores/TtsQueueStore";
import type {
  LupinEvent,
  StoreAudioStateChangePayload,
  StoreTtsQueueChangedPayload,
  TtsQueueItem,
  AudioPlaybackState,
} from "../../../lupin_app/static/js/multiplexer/shared/types";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function setup() {
  const bus    = createEventBusForTesting();
  const events : LupinEvent<StoreTtsQueueChangedPayload>[] = [];
  bus.on<StoreTtsQueueChangedPayload>("store_tts_queue_changed", (e) => events.push(e));
  const store  = createTtsQueueStore({ bus, nowFn: () => 1_000_000 });
  return { bus, store, events };
}

function item(idHash: string): TtsQueueItem {
  return { id_hash: idHash, ttsText: `say ${idHash}`, addedAt: 42 };
}

function emitAudioEnded(bus: ReturnType<typeof createEventBusForTesting>): void {
  bus.emit({ type: "store_audio_ended", payload: {}, source: "test", ts: 0 });
}

function emitAudioState(
  bus  : ReturnType<typeof createEventBusForTesting>,
  state: AudioPlaybackState,
): void {
  bus.emit<StoreAudioStateChangePayload>({
    type    : "store_audio_state_change",
    payload : { state, prev: "playing" },
    source  : "test",
    ts      : 0,
  });
}

function lastPayload(events: LupinEvent<StoreTtsQueueChangedPayload>[]): StoreTtsQueueChangedPayload {
  assert.ok(events.length > 0, "expected at least one store_tts_queue_changed emission");
  return events[events.length - 1].payload;
}

// ===========================================================================
// F0-a / F0-b — initial state + enqueue
// ===========================================================================

test("initial state: current() is null, pending() empty, itemQueueLength 0, no emission", () => {
  const { store, events } = setup();
  assert.equal(store.current(), null);
  assert.deepEqual(store.pending(), []);
  assert.equal(store.itemQueueLength(), 0);
  assert.equal(events.length, 0, "construction emits nothing");
});

test("enqueue on an empty queue: the item becomes the active head (current === id_hash)", () => {
  const { store, events } = setup();
  store.enqueue(item("X"));
  assert.equal(store.current(), "X");
  assert.deepEqual(store.pending(), [], "active head is not part of pending");
  assert.equal(store.itemQueueLength(), 0);
  const p = lastPayload(events);
  assert.equal(p.activeNotificationId, "X");
  assert.deepEqual(p.pending, []);
});

test("enqueue while an item is active: appends to pending; current() unchanged", () => {
  const { store, events } = setup();
  store.enqueue(item("X"));
  const before = events.length;
  store.enqueue(item("Y"));
  assert.equal(store.current(), "X", "active head does not change on append");
  assert.equal(store.itemQueueLength(), 1);
  assert.deepEqual(store.pending().map(i => i.id_hash), ["Y"]);
  assert.ok(events.length > before, "append emits a change");
  assert.deepEqual(lastPayload(events).pending.map(i => i.id_hash), ["Y"]);
});

test("two enqueues from empty: first is active, second is pending (FIFO)", () => {
  const { store } = setup();
  store.enqueue(item("A"));
  store.enqueue(item("B"));
  assert.equal(store.current(), "A");
  assert.deepEqual(store.pending().map(i => i.id_hash), ["B"]);
});

test("pending() preserves FIFO order across multiple appends", () => {
  const { store } = setup();
  store.enqueue(item("A"));   // active
  store.enqueue(item("B"));
  store.enqueue(item("C"));
  store.enqueue(item("D"));
  assert.equal(store.current(), "A");
  assert.deepEqual(store.pending().map(i => i.id_hash), ["B", "C", "D"]);
  assert.equal(store.itemQueueLength(), 3);
});

// ===========================================================================
// F0-b — advance
// ===========================================================================

test("advance: pops the active head and promotes the next pending to current()", () => {
  const { store, events } = setup();
  store.enqueue(item("A"));
  store.enqueue(item("B"));
  const before = events.length;
  store.advance();
  assert.equal(store.current(), "B", "next head promoted");
  assert.deepEqual(store.pending(), [], "B left the pending tail when promoted");
  assert.ok(events.length > before);
  assert.equal(lastPayload(events).activeNotificationId, "B");
});

test("advance with an active item but empty pending: current() becomes null (no stale id)", () => {
  const { store, events } = setup();
  store.enqueue(item("A"));
  const before = events.length;
  store.advance();
  assert.equal(store.current(), null);
  assert.equal(store.itemQueueLength(), 0);
  assert.ok(events.length > before, "advancing to empty still emits the de-light");
  assert.equal(lastPayload(events).activeNotificationId, null);
});

test("advance on a fully empty queue: safe no-op, emits nothing", () => {
  const { store, events } = setup();
  store.advance();
  assert.equal(store.current(), null);
  assert.equal(events.length, 0, "no-op advance does not emit");
});

test("advance through a multi-item queue lands each item then null", () => {
  const { store } = setup();
  store.enqueue(item("A"));
  store.enqueue(item("B"));
  store.enqueue(item("C"));
  assert.equal(store.current(), "A");
  store.advance();
  assert.equal(store.current(), "B");
  store.advance();
  assert.equal(store.current(), "C");
  store.advance();
  assert.equal(store.current(), null);
});

// ===========================================================================
// F0-b — removeById
// ===========================================================================

test("removeById of a pending item: excises it; current() unchanged", () => {
  const { store, events } = setup();
  store.enqueue(item("A"));   // active
  store.enqueue(item("B"));
  store.enqueue(item("C"));
  const before = events.length;
  store.removeById("B");
  assert.equal(store.current(), "A", "current untouched");
  assert.deepEqual(store.pending().map(i => i.id_hash), ["C"]);
  assert.ok(events.length > before);
});

test("removeById of the CURRENT item: resyncs — next pending becomes current()", () => {
  const { store, events } = setup();
  store.enqueue(item("A"));   // active
  store.enqueue(item("B"));
  const before = events.length;
  store.removeById("A");
  assert.equal(store.current(), "B", "removing current promotes next");
  assert.deepEqual(store.pending(), []);
  assert.ok(events.length > before);
  assert.equal(lastPayload(events).activeNotificationId, "B");
});

test("removeById of the CURRENT item with empty pending: current() becomes null", () => {
  const { store } = setup();
  store.enqueue(item("A"));
  store.removeById("A");
  assert.equal(store.current(), null);
  assert.equal(store.itemQueueLength(), 0);
});

test("removeById of an absent id: safe no-op, emits nothing", () => {
  const { store, events } = setup();
  store.enqueue(item("A"));
  const before = events.length;
  store.removeById("ZZZ");
  assert.equal(store.current(), "A");
  assert.equal(events.length, before, "absent-id removeById does not emit");
});

test("removeById a pending item while NO item is active (post stop-clear): excises it", () => {
  const { bus, store } = setup();
  store.enqueue(item("A"));   // active
  store.enqueue(item("B"));   // pending
  emitAudioState(bus, "idle");          // stop-clear: active → null, pending retained
  assert.equal(store.current(), null);
  assert.deepEqual(store.pending().map(i => i.id_hash), ["B"]);
  store.removeById("B");                 // active===null branch + pending splice
  assert.deepEqual(store.pending(), []);
});

test("removeById an absent id while NO item is active: safe no-op", () => {
  const { bus, store, events } = setup();
  store.enqueue(item("A"));
  emitAudioState(bus, "idle");          // active → null
  const before = events.length;
  store.removeById("nope");              // active===null, findIndex === -1
  assert.equal(events.length, before, "no emission for absent-id no-op");
});

// ===========================================================================
// F0-b — clear
// ===========================================================================

test("clear: empties the active head AND pending; current() → null", () => {
  const { store, events } = setup();
  store.enqueue(item("A"));
  store.enqueue(item("B"));
  const before = events.length;
  store.clear();
  assert.equal(store.current(), null);
  assert.deepEqual(store.pending(), []);
  assert.equal(store.itemQueueLength(), 0);
  assert.ok(events.length > before);
  assert.equal(lastPayload(events).activeNotificationId, null);
});

test("clear on an already-empty queue: safe no-op, emits nothing", () => {
  const { store, events } = setup();
  store.clear();
  assert.equal(events.length, 0, "no-op clear does not emit");
});

// ===========================================================================
// F0-a — emission payload integrity
// ===========================================================================

test("emitted pending[] is a defensive copy — mutating it does not affect the store", () => {
  const { store, events } = setup();
  store.enqueue(item("A"));
  store.enqueue(item("B"));
  const p = lastPayload(events);
  ( p.pending as TtsQueueItem[] ).push(item("EVIL"));
  assert.deepEqual(store.pending().map(i => i.id_hash), ["B"], "store array untouched by caller mutation");
});

test("pending() returns a defensive copy — mutating it does not affect the store", () => {
  const { store } = setup();
  store.enqueue(item("A"));
  store.enqueue(item("B"));
  const snap = store.pending() as TtsQueueItem[];
  snap.length = 0;
  assert.deepEqual(store.pending().map(i => i.id_hash), ["B"], "internal queue unaffected");
});

// ===========================================================================
// F0-f — completion-driven self-advance (store_audio_ended)
// ===========================================================================

test("store_audio_ended advances exactly one item (head pop + next current + event)", () => {
  const { bus, store, events } = setup();
  store.enqueue(item("A"));
  store.enqueue(item("B"));
  const before = events.length;
  emitAudioEnded(bus);
  assert.equal(store.current(), "B", "natural completion advances to next");
  assert.deepEqual(store.pending(), []);
  assert.ok(events.length > before, "self-advance fires store_tts_queue_changed");
  assert.equal(lastPayload(events).activeNotificationId, "B");
});

test("store_audio_ended on the last item advances to null (queue drains)", () => {
  const { bus, store } = setup();
  store.enqueue(item("A"));
  emitAudioEnded(bus);
  assert.equal(store.current(), null, "empty after advance → current null");
});

test("a duplicate / late store_audio_ended on an empty queue is a no-op (no stale id, no emit)", () => {
  const { bus, store, events } = setup();
  store.enqueue(item("A"));
  emitAudioEnded(bus);           // drains to null
  const before = events.length;
  emitAudioEnded(bus);           // late duplicate — nothing to advance
  assert.equal(store.current(), null);
  assert.equal(events.length, before, "late ended on empty queue emits nothing");
});

// ===========================================================================
// F0-f — stop-clear (store_audio_state_change{idle}) — de-light WITHOUT advancing
// ===========================================================================

test("store_audio_state_change{idle} clears current() → null WITHOUT a head pop", () => {
  const { bus, store, events } = setup();
  store.enqueue(item("A"));   // active
  store.enqueue(item("B"));   // pending
  const before = events.length;
  emitAudioState(bus, "idle");
  assert.equal(store.current(), null, "stop de-lights the active bubble");
  assert.deepEqual(store.pending().map(i => i.id_hash), ["B"], "pending NOT advanced/popped by stop");
  assert.ok(events.length > before, "de-light emits a change");
  assert.equal(lastPayload(events).activeNotificationId, null);
});

test("stop ≠ ended: after a stop-clear, the retained pending head can still be advanced", () => {
  const { bus, store } = setup();
  store.enqueue(item("A"));
  store.enqueue(item("B"));
  emitAudioState(bus, "idle");          // de-light, B retained in pending
  assert.equal(store.current(), null);
  store.advance();                       // promotes the retained B (active null, queue non-empty)
  assert.equal(store.current(), "B");
});

test("store_audio_state_change{idle} when nothing is active: safe no-op, emits nothing", () => {
  const { bus, store, events } = setup();
  const before = events.length;
  emitAudioState(bus, "idle");          // active already null
  assert.equal(store.current(), null);
  assert.equal(events.length, before, "idle with no active id emits nothing");
});

test("a non-idle store_audio_state_change is id-blind: does NOT touch the active id", () => {
  const { bus, store, events } = setup();
  store.enqueue(item("A"));
  const before = events.length;
  emitAudioState(bus, "playing");        // non-idle — ignored by F0
  emitAudioState(bus, "paused");         // non-idle — ignored by F0
  assert.equal(store.current(), "A", "playback sub-states do not move current()");
  assert.equal(events.length, before, "non-idle states emit no queue change");
});

// ===========================================================================
// disposeForTesting — listeners detach (no further self-drive after dispose)
// ===========================================================================

test("disposeForTesting detaches the bus subscriptions (audio events no longer self-drive)", () => {
  const { bus, store } = setup();
  store.enqueue(item("A"));
  store.enqueue(item("B"));
  store.disposeForTesting();
  emitAudioEnded(bus);                    // would advance if still subscribed
  emitAudioState(bus, "idle");            // would de-light if still subscribed
  assert.equal(store.current(), "A", "post-dispose the store ignores audio events");
});
