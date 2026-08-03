// Multiplexer F0-d — wireNotificationTtsIntent unit tests.
// Run via `npx tsx --test src/tests/unit/multiplexer/wire_tts_intent.test.ts`.
//
// Covers the boot-level producer→consumer glue that subscribes the
// store_notification_tts_intent seam (emitted by NotificationStore) to
// TtsQueueStore.enqueue(). boot.ts is the esbuild entry point (Playwright-tested,
// not unit-covered), so the wire lives in its own module to be 100% c8-gated here.

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { wireNotificationTtsIntent } from "../../../lupin_app/static/js/multiplexer/wireTtsIntent";
import type { TtsQueueItem, StoreNotificationTtsIntentPayload } from "../../../lupin_app/static/js/multiplexer/shared/types";

// A minimal enqueuer that records every item it receives.
function makeRecorder() {
  const items: TtsQueueItem[] = [];
  return { items, enqueue(item: TtsQueueItem): void { items.push(item); } };
}

function emitIntent(bus: ReturnType<typeof createEventBusForTesting>, payload: StoreNotificationTtsIntentPayload): void {
  bus.emit<StoreNotificationTtsIntentPayload>({
    type    : "store_notification_tts_intent",
    payload,
    source  : "test",
    ts      : 0,
  });
}

test("wire: a store_notification_tts_intent enqueues one TtsQueueItem carrying id_hash + ttsText + injected addedAt + action_required", () => {
  const bus      = createEventBusForTesting();
  const recorder = makeRecorder();
  wireNotificationTtsIntent(bus, recorder, () => 4_242);

  emitIntent(bus, { id_hash: "w1", ttsText: "speak me", priority: "high", action_required: false });

  assert.deepEqual(recorder.items, [ { id_hash: "w1", ttsText: "speak me", addedAt: 4_242, action_required: false } ]);
});

test("wire: each intent enqueues independently; addedAt reflects the nowFn AT enqueue time", () => {
  const bus      = createEventBusForTesting();
  const recorder = makeRecorder();
  let clock      = 100;
  wireNotificationTtsIntent(bus, recorder, () => clock);

  emitIntent(bus, { id_hash: "a", ttsText: "one",   priority: "urgent", action_required: false });
  clock = 200;
  emitIntent(bus, { id_hash: "b", ttsText: "two",   priority: "high", action_required: false });

  assert.equal(recorder.items.length, 2);
  assert.deepEqual(recorder.items[0], { id_hash: "a", ttsText: "one", addedAt: 100, action_required: false });
  assert.deepEqual(recorder.items[1], { id_hash: "b", ttsText: "two", addedAt: 200, action_required: false });
});

test("wire: 70cbff3e — the intent's action_required flag is stamped onto the enqueued item (AR case)", () => {
  const bus      = createEventBusForTesting();
  const recorder = makeRecorder();
  wireNotificationTtsIntent(bus, recorder, () => 7);

  emitIntent(bus, { id_hash: "ar1", ttsText: "respond please", priority: "urgent", action_required: true });

  assert.deepEqual(recorder.items, [ { id_hash: "ar1", ttsText: "respond please", addedAt: 7, action_required: true } ]);
});

test("wire: 766bb609 — a payload voice_id is stamped onto the enqueued item; absent → the key is OMITTED", () => {
  const bus      = createEventBusForTesting();
  const recorder = makeRecorder();
  wireNotificationTtsIntent(bus, recorder, () => 9);

  // present → stamped
  emitIntent(bus, { id_hash: "v1", ttsText: "hi", priority: "high", action_required: false, voice_id: "vox-rachel" });
  // absent → key omitted (byte-identical pre-766bb609 item)
  emitIntent(bus, { id_hash: "v2", ttsText: "yo", priority: "high", action_required: false });

  assert.deepEqual(recorder.items[0], { id_hash: "v1", ttsText: "hi", addedAt: 9, action_required: false, voice_id: "vox-rachel" });
  assert.deepEqual(recorder.items[1], { id_hash: "v2", ttsText: "yo", addedAt: 9, action_required: false });
  assert.equal(Object.prototype.hasOwnProperty.call(recorder.items[1], "voice_id"), false, "no-persona item omits voice_id");
});

test("wire: the returned unsubscriber detaches the seam — no further enqueues after it runs", () => {
  const bus      = createEventBusForTesting();
  const recorder = makeRecorder();
  const off      = wireNotificationTtsIntent(bus, recorder, () => 0);

  emitIntent(bus, { id_hash: "before", ttsText: "kept", priority: "high", action_required: false });
  off();
  emitIntent(bus, { id_hash: "after", ttsText: "dropped", priority: "high", action_required: false });

  assert.deepEqual(recorder.items.map(i => i.id_hash), [ "before" ]);
});
