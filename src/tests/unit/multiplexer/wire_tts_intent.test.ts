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

test("wire: a store_notification_tts_intent enqueues one TtsQueueItem carrying id_hash + ttsText + injected addedAt", () => {
  const bus      = createEventBusForTesting();
  const recorder = makeRecorder();
  wireNotificationTtsIntent(bus, recorder, () => 4_242);

  emitIntent(bus, { id_hash: "w1", ttsText: "speak me", priority: "high" });

  assert.deepEqual(recorder.items, [ { id_hash: "w1", ttsText: "speak me", addedAt: 4_242 } ]);
});

test("wire: each intent enqueues independently; addedAt reflects the nowFn AT enqueue time", () => {
  const bus      = createEventBusForTesting();
  const recorder = makeRecorder();
  let clock      = 100;
  wireNotificationTtsIntent(bus, recorder, () => clock);

  emitIntent(bus, { id_hash: "a", ttsText: "one",   priority: "urgent" });
  clock = 200;
  emitIntent(bus, { id_hash: "b", ttsText: "two",   priority: "high" });

  assert.equal(recorder.items.length, 2);
  assert.deepEqual(recorder.items[0], { id_hash: "a", ttsText: "one", addedAt: 100 });
  assert.deepEqual(recorder.items[1], { id_hash: "b", ttsText: "two", addedAt: 200 });
});

test("wire: the returned unsubscriber detaches the seam — no further enqueues after it runs", () => {
  const bus      = createEventBusForTesting();
  const recorder = makeRecorder();
  const off      = wireNotificationTtsIntent(bus, recorder, () => 0);

  emitIntent(bus, { id_hash: "before", ttsText: "kept", priority: "high" });
  off();
  emitIntent(bus, { id_hash: "after", ttsText: "dropped", priority: "high" });

  assert.deepEqual(recorder.items.map(i => i.id_hash), [ "before" ]);
});
