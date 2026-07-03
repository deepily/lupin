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
  ActionRequiredChangeKind,
  LupinEvent,
  StoreActionRequiredChangedPayload,
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

// ---------------------------------------------------------------------------
// F0-a — activeItem() read-only getter (WP4 consume-surface completion)
// ---------------------------------------------------------------------------

test("activeItem: returns the active item object; activeItem().id_hash === current() (consistency)", () => {
  const { store } = setup();
  store.enqueue(item("a"));
  const active = store.activeItem();
  assert.notEqual(active, null);
  assert.equal(active!.id_hash, "a");
  // Clayton's headline getter assert — the object and the id must agree.
  assert.equal(store.activeItem()?.id_hash, store.current());
});

test("activeItem: null when the queue is empty; current() is null too", () => {
  const { store } = setup();
  assert.equal(store.activeItem(), null);
  assert.equal(store.current(), null);
});

test("activeItem: tracks the promoted head across advance() — stays consistent with current()", () => {
  const { store } = setup();
  store.enqueue(item("a"));
  store.enqueue(item("b"));   // b waits in pending
  store.advance();            // a popped, b promoted to active
  assert.equal(store.activeItem()?.id_hash, "b");
  assert.equal(store.activeItem()?.id_hash, store.current());
});

// ===========================================================================
// 70cbff3e — TTS focus mode. ENTER when an ACTIVE action-required item's audio
// completes while unresolved (pause the ROLL); EXIT on responded|expired|
// cancelled matching the focus id, on manual Resume, and (de-focus only) when
// manually paused (A4). `failed` and non-terminal AR changes STAY in focus (A2).
// Legacy parity: notifications.js onTTSPlaybackComplete :17176-17204,
// enterTTSFocusMode :17262, exitTTSFocusMode :17309, toggleTTSFocusMode :17348.
// ===========================================================================

function arItem(idHash: string): TtsQueueItem {
  return { id_hash: idHash, ttsText: `say ${idHash}`, addedAt: 42, action_required: true };
}

function emitArChanged(
  bus       : ReturnType<typeof createEventBusForTesting>,
  changeKind: ActionRequiredChangeKind,
  idHash    : string,
): void {
  bus.emit<StoreActionRequiredChangedPayload>({
    type    : "store_action_required_changed",
    payload : { changeKind, id_hash: idHash },
    source  : "test",
    ts      : 0,
  });
}

test("focus ENTER (T1): active AR item whose audio ends while unresolved holds the roll — focusMode true, active discarded (null), pending untouched, one emit", () => {
  const { bus, store, events } = setup();
  store.enqueue(arItem("ar1"));   // active head
  store.enqueue(item("p1"));      // pending tail (must NOT promote)
  assert.equal(store.current(), "ar1");
  assert.equal(store.focusMode(), false);
  const before = events.length;
  emitAudioEnded(bus);
  assert.equal(store.focusMode(), true, "entered focus");
  assert.equal(store.current(), null, "the completed AR head is discarded (legacy :17201)");
  assert.deepEqual(store.pending().map(i => i.id_hash), ["p1"], "roll paused — p1 NOT promoted");
  assert.equal(events.length, before + 1, "exactly one emit on enter");
  assert.equal(lastPayload(events).activeNotificationId, null);
});

test("focus Path B-2 guard (T2): an AR item RESOLVED before its audio ends does NOT enter focus — it advances normally", () => {
  const { bus, store } = setup();
  store.enqueue(arItem("ar1"));
  store.enqueue(item("p1"));
  emitArChanged(bus, "responded", "ar1");   // resolved WHILE audio still playing
  assert.equal(store.focusMode(), false, "resolution alone does not enter focus");
  emitAudioEnded(bus);
  assert.equal(store.focusMode(), false, "already-resolved AR skips focus (legacy :17196)");
  assert.equal(store.current(), "p1", "advanced normally to the next pending item");
});

test("focus F1 (Clayton fold — resolved-bank reuse): after a resolved AR advances, a LATER same-id AR CAN re-enter focus (the consumed id was dropped from the bank)", () => {
  const { bus, store } = setup();
  // First life: ar1 resolves while playing → Path B-2 skips focus, advances,
  // AND drops ar1 from the resolved bank (F1 delete on the non-focus consume).
  store.enqueue(arItem("ar1"));
  emitArChanged(bus, "responded", "ar1");
  emitAudioEnded(bus);
  assert.equal(store.focusMode(), false, "first life: resolved-before-ended skips focus");
  assert.equal(store.current(), null, "advanced to empty (no pending)");
  // Second life: the SAME id_hash re-arrives (simulating a byId eviction + reuse
  // upstream) and this time is UNRESOLVED when its audio ends. Because F1 dropped
  // the stale entry, resolved.has(ar1) is false → it correctly ENTERS focus.
  // (Without the F1 delete, the stale bank entry would wrongly skip focus here.)
  store.enqueue(arItem("ar1"));
  emitAudioEnded(bus);
  assert.equal(store.focusMode(), true, "second life: bank was cleared → re-entry allowed");
  assert.equal(store.current(), null, "focus discards the AR head (held), so current() is null");
});

test("focus (T3): a NON-action-required item ending advances normally, never enters focus", () => {
  const { bus, store } = setup();
  store.enqueue(item("f1"));     // fire-and-forget (action_required undefined)
  store.enqueue(item("f2"));
  emitAudioEnded(bus);
  assert.equal(store.focusMode(), false);
  assert.equal(store.current(), "f2");
});

test("focus onAudioEnded on an empty queue (dup/late ended): no active head → advance no-op, focusMode stays false", () => {
  const { bus, store, events } = setup();
  emitAudioEnded(bus);
  assert.equal(store.focusMode(), false);
  assert.equal(store.current(), null);
  assert.equal(events.length, 0, "no-op — nothing emitted");
});

test("focus advance() guard (T4): a direct advance() while focused is a hard no-op (pause-the-ROLL belt)", () => {
  const { bus, store, events } = setup();
  store.enqueue(arItem("ar1"));
  store.enqueue(item("p1"));
  emitAudioEnded(bus);                 // enter focus
  const afterEnter = events.length;
  store.advance();                     // stray external advance
  assert.equal(store.focusMode(), true, "still focused");
  assert.equal(store.current(), null, "roll not advanced");
  assert.deepEqual(store.pending().map(i => i.id_hash), ["p1"], "p1 still held");
  assert.equal(events.length, afterEnter, "guarded advance emits nothing");
});

for (const kind of ["responded", "expired", "cancelled"] as const) {
  test(`focus EXIT (T5/6/7): store_action_required_changed{${kind}} on the focus id exits focus and rolls the queue`, () => {
    const { bus, store } = setup();
    store.enqueue(arItem("ar1"));
    store.enqueue(item("p1"));
    emitAudioEnded(bus);               // enter focus, p1 held
    assert.equal(store.focusMode(), true);
    emitArChanged(bus, kind, "ar1");   // terminal resolution of the focus item
    assert.equal(store.focusMode(), false, `${kind} exits focus`);
    assert.equal(store.current(), "p1", "queue rolled to the next pending item");
  });
}

test("focus EXIT ignores a NON-focus id (T8): a terminal AR change for another notification does not exit", () => {
  const { bus, store } = setup();
  store.enqueue(arItem("ar1"));
  store.enqueue(item("p1"));
  emitAudioEnded(bus);
  emitArChanged(bus, "responded", "someone-else");
  assert.equal(store.focusMode(), true, "unrelated resolution leaves focus intact");
  assert.equal(store.current(), null);
});

test("focus A2 (T9): `failed` (respondAndAwait POST rejected) STAYS in focus — the user can retry", () => {
  const { bus, store } = setup();
  store.enqueue(arItem("ar1"));
  store.enqueue(item("p1"));
  emitAudioEnded(bus);
  emitArChanged(bus, "failed", "ar1");
  assert.equal(store.focusMode(), true, "failed does not exit focus");
});

test("focus A2: a non-terminal AR change (`responded-pending`) does not exit focus", () => {
  const { bus, store } = setup();
  store.enqueue(arItem("ar1"));
  emitAudioEnded(bus);
  emitArChanged(bus, "responded-pending", "ar1");
  assert.equal(store.focusMode(), true);
});

test("focus manual Resume (T10): resumeFocus() exits focus and rolls the queue", () => {
  const { bus, store } = setup();
  store.enqueue(arItem("ar1"));
  store.enqueue(item("p1"));
  emitAudioEnded(bus);
  store.resumeFocus();
  assert.equal(store.focusMode(), false);
  assert.equal(store.current(), "p1", "manual Resume promotes the next pending item");
});

test("focus EXIT with empty pending (T11): exit sets current() null AND emits (de-focus repaint, not a stuck header)", () => {
  const { bus, store, events } = setup();
  store.enqueue(arItem("ar1"));      // no pending behind it
  emitAudioEnded(bus);               // enter focus, current() null, pending empty
  assert.equal(store.focusMode(), true);
  const beforeExit = events.length;
  store.resumeFocus();
  assert.equal(store.focusMode(), false);
  assert.equal(store.current(), null, "nothing to promote");
  assert.equal(events.length, beforeExit + 1, "exit STILL emits so the focus header repaints away");
});

test("focus A4 (T12): exiting while manually PAUSED de-focuses WITHOUT rolling (legacy !isTTSPaused)", () => {
  const { bus, store } = setup();
  store.enqueue(arItem("ar1"));
  store.enqueue(item("p1"));
  emitAudioEnded(bus);               // enter focus
  emitAudioState(bus, "paused");     // user manually paused
  store.resumeFocus();               // exit request
  assert.equal(store.focusMode(), false, "focus cleared");
  assert.equal(store.current(), null, "roll HELD — p1 not promoted while paused");
  assert.deepEqual(store.pending().map(i => i.id_hash), ["p1"], "pending retained");
});

test("focus clear() (T-clear): Clear-all while focused with an empty pending queue resets focus + emits", () => {
  const { bus, store, events } = setup();
  store.enqueue(arItem("ar1"));
  emitAudioEnded(bus);               // focus, active null, pending empty
  const beforeClear = events.length;
  store.clear();
  assert.equal(store.focusMode(), false, "clear resets focus even when active+pending already empty");
  assert.equal(events.length, beforeClear + 1, "clear emits the reset");
});

test("focus resumeFocus() when NOT focused is a safe no-op (exit guard)", () => {
  const { store, events } = setup();
  const before = events.length;
  store.resumeFocus();
  assert.equal(store.focusMode(), false);
  assert.equal(events.length, before, "no state change, no emit");
});
