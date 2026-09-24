// Parity A-2 #3c (row 254b3ba2, 2026-09-18, Chloé 🗼) — a manual pause blocks
// queue advance. Mirrors legacy `onTTSPlaybackComplete` (notifications.js:22730-22736),
// which returns before advancing, or entering focus, while `isTTSPaused` is
// set, and `activateNextTTS` (notifications.js:22290-22296), which refuses to
// promote the next item while paused. In the multiplexer a manual pause is
// the audio machine's `paused` state: only the Pause button, the corner pause
// and the action-required countdown pause can reach it.
//
// Where this departs from legacy: legacy drops the completion that arrived
// during the pause, so resuming leaves the queue stuck on a finished item.
// The multiplexer holds that completion and applies it on Play. A Stop drops
// it, since Stop de-lights without advancing (F0-f).

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createTtsQueueStore } from "../../../lupin_app/static/js/multiplexer/stores/TtsQueueStore";
import { wireTtsPlayback } from "../../../lupin_app/static/js/multiplexer/wireTtsPlayback";
import type {
  AudioPlaybackState,
  StoreAudioStateChangePayload,
  TtsQueueItem,
} from "../../../lupin_app/static/js/multiplexer/shared/types";

type Bus = ReturnType<typeof createEventBusForTesting>;

function setup() {
  const bus   = createEventBusForTesting();
  const store = createTtsQueueStore({ bus, nowFn: () => 0 });
  return { bus, store };
}

function item(idHash: string, over: Partial<TtsQueueItem> = {}): TtsQueueItem {
  return { id_hash: idHash, ttsText: `say ${idHash}`, ...over };
}

function audio(bus: Bus, state: AudioPlaybackState): void {
  bus.emit<StoreAudioStateChangePayload>({
    type: "store_audio_state_change", payload: { state, prev: "playing" }, source: "test", ts: 0,
  });
}

function ended(bus: Bus): void {
  bus.emit({ type: "store_audio_ended", payload: {}, source: "test", ts: 0 });
}

function pendingIds(store: ReturnType<typeof createTtsQueueStore>): string[] {
  return store.pending().map((it) => it.id_hash);
}

test("#3c a completion that lands while manually paused does NOT advance the queue", () => {
  const { bus, store } = setup();
  store.enqueue(item("a"));
  store.enqueue(item("b"));
  audio(bus, "playing");
  audio(bus, "paused");

  ended(bus);

  assert.equal(store.current(), "a", "the paused item stays active");
  assert.deepEqual(pendingIds(store), [ "b" ], "b is not promoted");
});

test("#3c the next item's audio is not requested while paused (assembled with wireTtsPlayback)", () => {
  const { bus, store } = setup();
  const posted: string[] = [];
  wireTtsPlayback(bus, store, { post: (_url: string, body: unknown) => {
    posted.push((body as { text: string }).text);
    return Promise.resolve(undefined as never);
  } }, "session-1", { ttsMode: () => "instant" });

  store.enqueue(item("a"));
  store.enqueue(item("b"));
  audio(bus, "playing");
  audio(bus, "paused");
  ended(bus);

  assert.deepEqual(posted, [ "say a" ], "no request for b while the operator holds the pause");
});

test("#3c an action-required item finishing while paused does not enter focus mode yet", () => {
  const { bus, store } = setup();
  store.enqueue(item("ar", { action_required: true }));
  audio(bus, "playing");
  audio(bus, "paused");

  ended(bus);

  assert.equal(store.focusMode(), false);
  assert.equal(store.current(), "ar");
});

test("#3c Play applies the held completion: the queue advances once", () => {
  const { bus, store } = setup();
  store.enqueue(item("a"));
  store.enqueue(item("b"));
  store.enqueue(item("c"));
  audio(bus, "playing");
  audio(bus, "paused");
  ended(bus);
  assert.equal(store.current(), "a", "held, not applied, while paused");

  audio(bus, "playing");

  assert.equal(store.current(), "b");
  assert.deepEqual(pendingIds(store), [ "c" ]);

  audio(bus, "paused");
  audio(bus, "playing");
  assert.equal(store.current(), "b", "a pause/play with nothing held does not advance");
});

test("#3c Play applies a held action-required completion by entering focus", () => {
  const { bus, store } = setup();
  store.enqueue(item("ar", { action_required: true }));
  store.enqueue(item("b"));
  audio(bus, "playing");
  audio(bus, "paused");
  ended(bus);
  assert.equal(store.focusMode(), false, "held, not applied, while paused");

  audio(bus, "playing");

  assert.equal(store.focusMode(), true);
  assert.equal(store.current(), null);
  assert.deepEqual(pendingIds(store), [ "b" ]);
});

test("#3c Stop drops the held completion: de-light without advancing", () => {
  const { bus, store } = setup();
  store.enqueue(item("a"));
  store.enqueue(item("b"));
  audio(bus, "playing");
  audio(bus, "paused");
  ended(bus);

  audio(bus, "idle");
  assert.equal(store.current(), null);
  assert.deepEqual(pendingIds(store), [ "b" ]);

  audio(bus, "playing");
  assert.equal(store.current(), null, "the dropped completion is not replayed later");
  assert.deepEqual(pendingIds(store), [ "b" ]);
});

test("#3c Skip out of the pause drops the held completion, as a plain Skip never advances", () => {
  const { bus, store } = setup();
  store.enqueue(item("a"));
  store.enqueue(item("b"));
  audio(bus, "playing");
  audio(bus, "paused");
  ended(bus);

  audio(bus, "ended");
  audio(bus, "playing");

  assert.equal(store.current(), "a");
  assert.deepEqual(pendingIds(store), [ "b" ]);
});

test("#3c not paused: a completion advances at once (the guard is the pause, nothing else)", () => {
  const { bus, store } = setup();
  store.enqueue(item("a"));
  store.enqueue(item("b"));
  audio(bus, "playing");

  ended(bus);

  assert.equal(store.current(), "b");
});
