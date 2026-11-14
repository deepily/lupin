// Multiplexer quiet workers: speech gate, sender flag and card chip.
//
// Run via `npx tsx --test src/tests/unit/multiplexer/worker_quiet.test.ts`.
//
// The server stamps `worker_quiet: true` on the notifications of a spawned, non-manager session whose speakerphone is
// off. The multiplexer reads it in three places, and each has its own tests below:
//   NotificationStore  a quiet worker's `high` is not spoken; its `urgent` is; `medium` never was
//   SenderStore        the stamp sets the sender's quiet flag; a speakerphone_changed turning it on clears it;
//                      an event without the stamp clears it
//   senderCard         the quiet chip, from the sender's flag
// `conversation_mode_active` is the pinned-conversation flag and is never touched by the stamp.

import { test, before, describe } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createStorageServiceForTesting, InMemoryStorage } from "../../../lupin_app/static/js/multiplexer/shared/StorageService";
import { createNotificationStore } from "../../../lupin_app/static/js/multiplexer/stores/NotificationStore";
import { createSenderStore } from "../../../lupin_app/static/js/multiplexer/stores/SenderStore";
import { renderSenderCard } from "../../../lupin_app/static/js/multiplexer/render/templates/senderCard";
import type { SenderRecord, StoreNotificationTtsIntentPayload } from "../../../lupin_app/static/js/multiplexer/shared/types";

before(() => {
  if (typeof globalThis.document === "undefined") GlobalRegistrator.register();
});

const SENDER = "claude.code@lupin.deepily.ai#worker01";

function bus() { return createEventBusForTesting(); }
type Bus = ReturnType<typeof bus>;

function emit(b: Bus, notification: Record<string, unknown>): void {
  b.emit({ type: "notification_queue_update", payload: { notification }, source: "test", ts: 0 });
}

// --- NotificationStore: medium, high and urgent, quiet and not ---------------------------------------------------

function spokenIntents(workerQuiet: boolean | undefined, priority: string): StoreNotificationTtsIntentPayload[] {
  const b       = bus();
  const storage = createStorageServiceForTesting(b, new InMemoryStorage());
  createNotificationStore({
    bus: b, storage, isAdmin: () => true,
    setTimeoutFn: (() => 0) as (cb: () => void, ms: number) => unknown,
    clearTimeoutFn: (() => undefined) as (id: unknown) => void,
    nowFn: () => 1_700_000_000_000,
  });
  const intents: StoreNotificationTtsIntentPayload[] = [];
  b.on<StoreNotificationTtsIntentPayload>("store_notification_tts_intent", (e) => intents.push(e.payload));
  emit(b, { id_hash: `n-${priority}`, sender_id: SENDER, message: "hello", priority, ...(workerQuiet === undefined ? {} : { worker_quiet: workerQuiet }) });
  return intents;
}

describe("NotificationStore speech gate for a quiet worker", () => {
  test("medium never speaks, quiet or not", () => {
    assert.deepEqual(spokenIntents(true, "medium"), []);
    assert.deepEqual(spokenIntents(undefined, "medium"), []);
  });
  test("high from a quiet worker is not spoken", () => {
    assert.deepEqual(spokenIntents(true, "high"), []);
  });
  test("high with no stamp, or a false stamp, is spoken as before", () => {
    assert.equal(spokenIntents(undefined, "high").length, 1);
    assert.equal(spokenIntents(false, "high").length, 1);
  });
  test("URGENT from a quiet worker still speaks, with the Urgent! prefix (Rick's required test)", () => {
    const intents = spokenIntents(true, "urgent");
    assert.equal(intents.length, 1);
    assert.equal(intents[0]!.ttsText, "Urgent! hello");
    assert.equal(intents[0]!.priority, "urgent");
  });
  test("urgent with no stamp speaks as before", () => {
    assert.equal(spokenIntents(undefined, "urgent").length, 1);
  });
});

// --- SenderStore ---------------------------------------------------------------------------------------------------

function senderSetup() {
  const b     = bus();
  const store = createSenderStore({ bus: b, nowFn: () => 1_000_000 });
  return { b, store };
}

describe("SenderStore quiet flag", () => {
  test("a stamped first notification creates the sender quiet, and never touches conversation_mode_active", () => {
    const { b, store } = senderSetup();
    emit(b, { type: "task", sender_id: SENDER, timestamp: "2026-11-14T10:00:00Z", worker_quiet: true });
    const rec = store.list().find((s) => s.sender_id === SENDER)!;
    assert.equal(rec.worker_quiet, true);
    assert.equal(rec.conversation_mode_active, false);
  });
  test("an unstamped first notification creates the sender with no flag", () => {
    const { b, store } = senderSetup();
    emit(b, { type: "task", sender_id: SENDER, timestamp: "2026-11-14T10:00:00Z" });
    assert.equal("worker_quiet" in store.list()[0]!, false);
  });
  test("a stamped later notification sets it, an unstamped one clears it", () => {
    const { b, store } = senderSetup();
    emit(b, { type: "task", sender_id: SENDER, timestamp: "2026-11-14T10:00:00Z" });
    emit(b, { type: "task", sender_id: SENDER, timestamp: "2026-11-14T10:01:00Z", worker_quiet: true });
    assert.equal(store.list()[0]!.worker_quiet, true);
    emit(b, { type: "task", sender_id: SENDER, timestamp: "2026-11-14T10:02:00Z" });
    assert.equal("worker_quiet" in store.list()[0]!, false);
  });
  test("Rick turning the speakerphone on clears the flag; turning it off does not set it", () => {
    const { b, store } = senderSetup();
    emit(b, { type: "task", sender_id: SENDER, timestamp: "2026-11-14T10:00:00Z", worker_quiet: true });
    emit(b, { type: "speakerphone_changed", sender_id: SENDER, timestamp: "2026-11-14T10:01:00Z", payload: { on: true } });
    assert.equal("worker_quiet" in store.list()[0]!, false);
    emit(b, { type: "speakerphone_changed", sender_id: SENDER, timestamp: "2026-11-14T10:02:00Z", payload: { on: false } });
    assert.equal("worker_quiet" in store.list()[0]!, false);
  });
  test("a speakerphone_changed off leaves a quiet worker quiet", () => {
    const { b, store } = senderSetup();
    emit(b, { type: "task", sender_id: SENDER, timestamp: "2026-11-14T10:00:00Z", worker_quiet: true });
    emit(b, { type: "speakerphone_changed", sender_id: SENDER, timestamp: "2026-11-14T10:01:00Z", payload: { on: false } });
    assert.equal(store.list()[0]!.worker_quiet, true);
  });
});

// --- senderCard chip -------------------------------------------------------------------------------------------------

function record(over: Partial<SenderRecord> = {}): SenderRecord {
  return { sender_id: SENDER, display_name: "lupin", last_active_ts: 1_000_000, unread_count: 0, conversation_mode_active: false, ...over };
}

describe("sender card quiet chip", () => {
  test("a quiet worker's card carries the chip and the attribute", () => {
    const root = renderSenderCard(record({ worker_quiet: true }), []);
    const chip = root.querySelector(".sender-quiet-chip");
    assert.ok(chip, "no quiet chip rendered");
    assert.match(chip!.textContent ?? "", /quiet/);
    assert.equal(root.getAttribute("data-worker-quiet"), "true");
  });
  test("any other card has neither", () => {
    const root = renderSenderCard(record(), []);
    assert.equal(root.querySelectorAll(".sender-quiet-chip").length, 0);
    assert.equal(root.hasAttribute("data-worker-quiet"), false);
  });
});
