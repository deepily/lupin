// Parity A-2 #3e (row d51bc8f4) — the "TTS is playing" signal, TTS side of the
// AR→TTS deferral coupling. A-2 #2d (row dcaeb0fc) consumes it.
//
// Legacy, verified at 2847ea74 (Phase 2 A4 item 6 names no line; A3 R3's had drifted):
//   - notifications.js:21779-21785  addActionRequiredNotification: an arrival defers while
//                   `this.activeTTSItem` is set  → TtsQueueStore.isPlaying()
//   - notifications.js:22781-22786  onTTSPlaybackComplete: the deferred prompt activates when the CURRENT item
//                   completes, before the queue rolls on → store_tts_slot_released
//
// Run: npx tsx --test src/tests/unit/multiplexer/tts_playing_signal.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createTtsQueueStore, TTS_STORAGE_KEY, TTS_STORAGE_SCHEMA } from "../../../lupin_app/static/js/multiplexer/stores/TtsQueueStore";
import { createStorageServiceForTesting, InMemoryStorage } from "../../../lupin_app/static/js/multiplexer/shared/StorageService";
import type {
  AudioPlaybackState,
  StoreActionRequiredChangedPayload,
  StoreAudioStateChangePayload,
  StoreTtsSlotReleasedPayload,
  TtsQueueItem,
} from "../../../lupin_app/static/js/multiplexer/shared/types";

type Bus = ReturnType<typeof createEventBusForTesting>;

function setup() {
  const bus      = createEventBusForTesting();
  const log      : string[] = [];
  const released : string[] = [];
  bus.on("store_tts_queue_changed", () => log.push("queue"));
  bus.on<StoreTtsSlotReleasedPayload>("store_tts_slot_released", (e) => {
    log.push(`released:${e.payload.releasedId}`);
    released.push(e.payload.releasedId);
  });
  const store = createTtsQueueStore({ bus, nowFn: () => 7 });
  return { bus, store, log, released };
}

function item(idHash: string, actionRequired = false): TtsQueueItem {
  return { id_hash: idHash, ttsText: `say ${idHash}`, addedAt: 1, action_required: actionRequired };
}

function ended(bus: Bus): void {
  bus.emit({ type: "store_audio_ended", payload: {}, source: "test", ts: 0 });
}

function audio(bus: Bus, state: AudioPlaybackState): void {
  bus.emit<StoreAudioStateChangePayload>({
    type: "store_audio_state_change", payload: { state, prev: "playing" }, source: "test", ts: 0,
  });
}

function resolveAr(bus: Bus, idHash: string): void {
  bus.emit<StoreActionRequiredChangedPayload>({
    type: "store_action_required_changed",
    payload: { id_hash: idHash, changeKind: "responded" },
    source: "test", ts: 0,
  });
}

// ---------------------------------------------------------------------------
// isPlaying() — the arrival-time read (legacy :21779)
// ---------------------------------------------------------------------------

test("isPlaying: false on an empty store, true once an item takes the slot", () => {
  const { store } = setup();
  assert.equal(store.isPlaying(), false);
  store.enqueue(item("A"));
  assert.equal(store.isPlaying(), true);
});

test("isPlaying: stays true through a manual pause, as legacy keeps activeTTSItem while paused", () => {
  const { bus, store } = setup();
  store.enqueue(item("A"));
  audio(bus, "paused");
  assert.equal(store.isPlaying(), true);
  ended(bus);   // held by the pause (A-2 #3c) — the slot is still A's
  assert.equal(store.isPlaying(), true);
  assert.equal(store.current(), "A");
});

test("isPlaying: false after the last item ends, after stop, and after clear", () => {
  const { bus, store } = setup();
  store.enqueue(item("A"));
  ended(bus);
  assert.equal(store.isPlaying(), false, "drained");
  store.enqueue(item("B"));
  audio(bus, "idle");
  assert.equal(store.isPlaying(), false, "stopped");
  store.enqueue(item("C"));
  store.clear();
  assert.equal(store.isPlaying(), false, "cleared");
});

test("isPlaying: false in focus mode — the action-required item's audio is over", () => {
  const { bus, store } = setup();
  store.enqueue(item("AR", true));
  store.enqueue(item("B"));
  ended(bus);
  assert.equal(store.focusMode(), true);
  assert.equal(store.isPlaying(), false);
});

test("isPlaying: false while restored items wait for the audio socket", () => {
  const bus     = createEventBusForTesting();
  const storage = createStorageServiceForTesting(bus, new InMemoryStorage());
  storage.setJSON(TTS_STORAGE_KEY, { pending: [item("R")], focusModeActive: false, focusModeNotificationId: null }, TTS_STORAGE_SCHEMA);
  const store = createTtsQueueStore({ bus, nowFn: () => 7, storage });
  assert.equal(store.itemQueueLength(), 1);
  assert.equal(store.isPlaying(), false);
});

// ---------------------------------------------------------------------------
// store_tts_slot_released — the release point (legacy :22782-22786)
// ---------------------------------------------------------------------------

test("slot released on the roll to the next pending item — current() never passes through null", () => {
  const { bus, store, released } = setup();
  store.enqueue(item("A"));
  store.enqueue(item("B"));
  ended(bus);
  assert.deepEqual(released, ["A"]);
  assert.equal(store.current(), "B");
  assert.equal(store.isPlaying(), true, "B plays on; the release still fired for A");
});

test("slot released after the queue event, with the store already showing the new state", () => {
  const { bus, store, log } = setup();
  let seenCurrent: string | null = "unset";
  bus.on("store_tts_slot_released", () => { seenCurrent = store.current(); });
  store.enqueue(item("A"));
  store.enqueue(item("B"));
  log.length = 0;
  ended(bus);
  assert.deepEqual(log, ["queue", "released:A"]);
  assert.equal(seenCurrent, "B");
});

test("slot released on every way out: drain, stop, remove, clear, focus entry", () => {
  const { bus, store, released } = setup();
  store.enqueue(item("A"));
  ended(bus);                          // drain
  store.enqueue(item("B"));
  audio(bus, "idle");                  // stop
  store.enqueue(item("C"));
  store.removeById("C");               // remove the active item
  store.enqueue(item("D"));
  store.clear();                       // clear
  store.enqueue(item("AR", true));
  ended(bus);                          // focus entry
  assert.deepEqual(released, ["A", "B", "C", "D", "AR"]);
});

test("no release while the slot is held: queueing behind, removing a pending item, a held pause", () => {
  const { bus, store, released } = setup();
  store.enqueue(item("A"));
  store.enqueue(item("B"));
  store.enqueue(item("C"));
  store.removeById("C");
  audio(bus, "paused");
  ended(bus);
  assert.deepEqual(released, []);
  audio(bus, "playing");               // the held completion applies now
  assert.deepEqual(released, ["A"]);
});

test("no release when nothing was playing: focus exit onto an empty slot, a promote from empty", () => {
  const { bus, store, released } = setup();
  store.enqueue(item("AR", true));
  ended(bus);
  released.length = 0;
  resolveAr(bus, "AR");                // exits focus; nothing pending to promote
  store.enqueue(item("B"));
  assert.deepEqual(released, []);
  assert.equal(store.isPlaying(), true);
});
