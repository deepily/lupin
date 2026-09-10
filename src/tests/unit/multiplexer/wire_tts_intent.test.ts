// Multiplexer F0-d — wireNotificationTtsIntent unit tests.
// Run via `npx tsx --test src/tests/unit/multiplexer/wire_tts_intent.test.ts`.
//
// Covers the boot-level producer→consumer glue that subscribes the
// store_notification_tts_intent seam (emitted by NotificationStore) to
// TtsQueueStore.enqueue(). boot.ts is the esbuild entry point (Playwright-tested,
// not unit-covered), so the wire lives in its own module to be 100% c8-gated here.
//
// P0 (Rick's broadcast a090b845, 2026-09-10): the wire now applies the TTS preview
// slider. Before it, every notification was spoken in full with the slider at 0%.

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { wireNotificationTtsIntent } from "../../../lupin_app/static/js/multiplexer/wireTtsIntent";
import type { TtsPreviewSettings } from "../../../lupin_app/static/js/multiplexer/shared/ttsPreview";
import type { TtsQueueItem, StoreNotificationTtsIntentPayload } from "../../../lupin_app/static/js/multiplexer/shared/types";

// Slider at 100%: the pre-slider behaviour, used where a test is about something else.
const FULL: () => TtsPreviewSettings = () => ( { fraction: 1, enabled: true, minChars: 100 } );

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
  wireNotificationTtsIntent(bus, recorder, () => 4_242, FULL);

  emitIntent(bus, { id_hash: "w1", ttsText: "speak me", priority: "high", action_required: false });

  assert.deepEqual(recorder.items, [ { id_hash: "w1", ttsText: "speak me", addedAt: 4_242, action_required: false } ]);
});

test("wire: each intent enqueues independently; addedAt reflects the nowFn AT enqueue time", () => {
  const bus      = createEventBusForTesting();
  const recorder = makeRecorder();
  let clock      = 100;
  wireNotificationTtsIntent(bus, recorder, () => clock, FULL);

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
  wireNotificationTtsIntent(bus, recorder, () => 7, FULL);

  emitIntent(bus, { id_hash: "ar1", ttsText: "respond please", priority: "urgent", action_required: true });

  assert.deepEqual(recorder.items, [ { id_hash: "ar1", ttsText: "respond please", addedAt: 7, action_required: true } ]);
});

test("wire: 766bb609 — a payload voice_id is stamped onto the enqueued item; absent → the key is OMITTED", () => {
  const bus      = createEventBusForTesting();
  const recorder = makeRecorder();
  wireNotificationTtsIntent(bus, recorder, () => 9, FULL);

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
  const off      = wireNotificationTtsIntent(bus, recorder, () => 0, FULL);

  emitIntent(bus, { id_hash: "before", ttsText: "kept", priority: "high", action_required: false });
  off();
  emitIntent(bus, { id_hash: "after", ttsText: "dropped", priority: "high", action_required: false });

  assert.deepEqual(recorder.items.map(i => i.id_hash), [ "before" ]);
});

// ---------------------------------------------------------------------------
// P0 a090b845 — the slider governs what is spoken
// ---------------------------------------------------------------------------

const LONG = "First sentence of a long agent report. Second sentence carries more detail. "
           + "Third sentence goes on further still. Fourth sentence closes it out now.";

test("wire: P0 — a slider at 0 enqueues NOTHING, even while the feature flag is still loading", () => {
  const bus      = createEventBusForTesting();
  const recorder = makeRecorder();
  wireNotificationTtsIntent(bus, recorder, () => 1, () => ( { fraction: 0, enabled: false, minChars: 100 } ));

  emitIntent(bus, { id_hash: "z1", ttsText: LONG, priority: "high", action_required: false });
  emitIntent(bus, { id_hash: "z2", ttsText: "short", priority: "urgent", action_required: true });

  assert.deepEqual(recorder.items, []);
});

test("wire: P0 — a partial slider enqueues the boundary cut, not the whole text", () => {
  const bus      = createEventBusForTesting();
  const recorder = makeRecorder();
  wireNotificationTtsIntent(bus, recorder, () => 1, () => ( { fraction: 0.25, enabled: true, minChars: 100 } ));

  emitIntent(bus, { id_hash: "p1", ttsText: LONG, priority: "high", action_required: false });

  assert.equal(recorder.items.length, 1);
  // LONG is 148 chars; 25% puts the scan at index 37, which is the first period.
  assert.equal(recorder.items[0]?.ttsText, "First sentence of a long agent report.");
});

test("wire: P0 — settings are read at EACH arrival, so a slider move applies to the next notification", () => {
  const bus      = createEventBusForTesting();
  const recorder = makeRecorder();
  let fraction   = 1;
  wireNotificationTtsIntent(bus, recorder, () => 1, () => ( { fraction, enabled: true, minChars: 100 } ));

  emitIntent(bus, { id_hash: "m1", ttsText: LONG, priority: "high", action_required: false });
  fraction = 0;
  emitIntent(bus, { id_hash: "m2", ttsText: LONG, priority: "high", action_required: false });

  assert.deepEqual(recorder.items.map(i => [ i.id_hash, i.ttsText ]), [ [ "m1", LONG ] ]);
});
