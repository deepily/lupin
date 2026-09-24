// Parity A-2 #2d (row dcaeb0fc) — an Action Required card arriving while TTS plays waits for
// the current item, then activates. Consumer of A-2 #3e (TtsQueueStore.isPlaying() +
// store_tts_slot_released).
//
// Legacy, verified at 2847ea74 (Phase 2 A3 R3's `js:21636-21645` had drifted before io/phase2 landed):
//   - notifications.js:21777-21789  addActionRequiredNotification: activate only if
//                   `!this.activeTTSItem`, otherwise render minimized at position 1 and wait
//   - notifications.js:22781-22786  onTTSPlaybackComplete: a waiting card activates when the current item ends
//
// The store tests run against the REAL TtsQueueStore on one bus, so the release is the one the
// TTS queue actually emits. The last two enter where the incident would: the assembled
// createStores plus the boot-level TTS intent wire, where the prompt's own speech reaches the
// TTS queue before the Action Required store hears the frame.
//
// Run: npx tsx --test src/tests/unit/multiplexer/action_required_tts_deferral.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createActionRequiredStore,
  isAwaitingActivation,
  type ActionRequiredApiClient,
} from "../../../lupin_app/static/js/multiplexer/stores/ActionRequiredStore";
import { createTtsQueueStore } from "../../../lupin_app/static/js/multiplexer/stores/TtsQueueStore";
import { createStores } from "../../../lupin_app/static/js/multiplexer/stores";
import { createStorageServiceForTesting } from "../../../lupin_app/static/js/multiplexer/shared/StorageService";
import { wireNotificationTtsIntent } from "../../../lupin_app/static/js/multiplexer/wireTtsIntent";
import type {
  StoreActionRequiredChangedPayload,
  StoreAudioStateChangePayload,
  TtsQueueItem,
} from "../../../lupin_app/static/js/multiplexer/shared/types";

type Bus = ReturnType<typeof createEventBusForTesting>;

const NOW = 1_000_000;

function noTimers() {
  let next = 1;
  const intervals = new Set<number>();
  const timeouts  : Array<() => void> = [];
  return {
    intervals,
    /** Run every grace-period removal scheduled so far. */
    fireTimeouts(): void { for (const cb of timeouts.splice(0)) cb(); },
    setIntervalFn   : (() => { const id = next++; intervals.add(id); return id; }) as (cb: () => void, ms: number) => unknown,
    clearIntervalFn : ((id: unknown) => { intervals.delete(id as number); }) as (id: unknown) => void,
    setTimeoutFn    : ((cb: () => void) => { timeouts.push(cb); return next++; }) as (cb: () => void, ms: number) => unknown,
    clearTimeoutFn  : (() => {}) as (id: unknown) => void,
  };
}

const API: ActionRequiredApiClient = { post: async <T>() => ({}) as T };

function setup(opts: { wired?: boolean } = {}) {
  const bus     = createEventBusForTesting();
  const timers  = noTimers();
  const tts     = createTtsQueueStore({ bus, nowFn: () => NOW });
  const changes : string[] = [];
  bus.on<StoreActionRequiredChangedPayload>("store_action_required_changed", (e) => {
    if (e.payload.changeKind !== "tick") changes.push(`${e.payload.changeKind}:${e.payload.id_hash}`);
  });
  const ar = createActionRequiredStore({
    bus, api: API, nowFn: () => NOW, ...timers,
    ...(opts.wired === false ? {} : { ttsSlot: tts }),
  });
  return { bus, tts, ar, changes, timers };
}

function speech(idHash: string, actionRequired = false): TtsQueueItem {
  return { id_hash: idHash, ttsText: `say ${idHash}`, addedAt: 1, action_required: actionRequired };
}

function arrive(bus: Bus, idHash: string, priority = "low"): void {
  bus.emit({
    type    : "notification_queue_update",
    payload : { notification: {
      id_hash: idHash, message: `Proceed ${idHash}?`, sender_id: "alice@x", priority,
      timestamp: new Date(NOW).toISOString(), response_requested: true, response_type: "yes_no",
      timeout_seconds: 30,
    } },
    source  : "test",
    ts      : 0,
  });
}

function ended(bus: Bus): void {
  bus.emit({ type: "store_audio_ended", payload: {}, source: "test", ts: 0 });
}

function audio(bus: Bus, state: StoreAudioStateChangePayload["state"]): void {
  bus.emit<StoreAudioStateChangePayload>({
    type: "store_audio_state_change", payload: { state, prev: "playing" }, source: "test", ts: 0,
  });
}

// ---------------------------------------------------------------------------
// The predicate
// ---------------------------------------------------------------------------

test("isAwaitingActivation: only a pending card with no expiry is waiting", () => {
  assert.equal(isAwaitingActivation({ state: "pending",   expires_at: null }), true);
  assert.equal(isAwaitingActivation({ state: "pending",   expires_at: 5 }),    false);
  assert.equal(isAwaitingActivation({ state: "expired",   expires_at: null }), false);
  assert.equal(isAwaitingActivation({ state: "responded", expires_at: null }), false);
});

// ---------------------------------------------------------------------------
// Arrival (legacy :21772-21785)
// ---------------------------------------------------------------------------

test("a card arriving while another item speaks waits unstarted: no expiry, no countdown, only 'added'", () => {
  const { bus, tts, ar, changes, timers } = setup();
  tts.enqueue(speech("X"));
  arrive(bus, "AR");
  const card = ar.getById("AR")!;
  assert.equal(card.expires_at, null);
  assert.equal(isAwaitingActivation(card), true);
  assert.equal(timers.intervals.size, 0, "a waiting card has no countdown");
  assert.deepEqual(changes, ["added:AR"]);
});

test("a card arriving into silence activates at once", () => {
  const { bus, ar, changes, timers } = setup();
  arrive(bus, "AR");
  assert.equal(ar.getById("AR")!.expires_at, NOW + 30_000);
  assert.equal(timers.intervals.size, 1);
  assert.deepEqual(changes, ["added:AR"]);
});

test("a card whose OWN speech already holds the slot activates at once — no self-defer", () => {
  const { bus, tts, ar } = setup();
  tts.enqueue(speech("AR", true));   // the intent wire got there first, as it does in boot
  arrive(bus, "AR");
  assert.equal(tts.isPlaying(), true);
  assert.equal(ar.getById("AR")!.expires_at, NOW + 30_000);
});

test("its own speech queued BEHIND another item does not stop it waiting for that item", () => {
  const { bus, tts, ar } = setup();
  tts.enqueue(speech("X"));
  tts.enqueue(speech("AR", true));
  arrive(bus, "AR");
  assert.equal(ar.getById("AR")!.expires_at, null);
});

test("a manual pause still counts as playing: the card waits (legacy keeps activeTTSItem)", () => {
  const { bus, tts, ar } = setup();
  tts.enqueue(speech("X"));
  audio(bus, "paused");
  arrive(bus, "AR");
  assert.equal(ar.getById("AR")!.expires_at, null);
});

test("with no TTS slot wired, a card never waits", () => {
  const { bus, tts, ar } = setup({ wired: false });
  tts.enqueue(speech("X"));
  arrive(bus, "AR");
  assert.equal(ar.getById("AR")!.expires_at, NOW + 30_000);
});

// ---------------------------------------------------------------------------
// Release (legacy :22782-22786)
// ---------------------------------------------------------------------------

test("the waiting card activates when the current item ends, though the queue rolls straight on", () => {
  const { bus, tts, ar, changes, timers } = setup();
  tts.enqueue(speech("X"));
  tts.enqueue(speech("Y"));
  arrive(bus, "AR");
  ended(bus);
  assert.equal(tts.current(), "Y", "precondition: TTS never went quiet");
  assert.equal(ar.getById("AR")!.expires_at, NOW + 30_000);
  assert.equal(timers.intervals.size, 1);
  assert.deepEqual(changes, ["added:AR", "activated:AR"]);
});

test("a stop releases the waiting card too", () => {
  const { bus, tts, ar } = setup();
  tts.enqueue(speech("X"));
  arrive(bus, "AR");
  audio(bus, "idle");
  assert.equal(ar.getById("AR")!.expires_at, NOW + 30_000);
});

test("a second card arriving while the first waits also waits; the release activates the first only", () => {
  const { bus, tts, ar, changes } = setup();
  tts.enqueue(speech("X"));
  arrive(bus, "A1");
  arrive(bus, "A2");
  ended(bus);
  assert.equal(ar.getById("A1")!.expires_at, NOW + 30_000);
  assert.equal(ar.getById("A2")!.expires_at, null);
  assert.deepEqual(changes, ["added:A1", "added:A2", "activated:A1"]);
});

test("a release with no waiting card changes nothing", () => {
  const { bus, tts, ar, changes } = setup();
  arrive(bus, "AR");
  tts.enqueue(speech("X"));
  ended(bus);
  assert.equal(ar.getById("AR")!.expires_at, NOW + 30_000);
  assert.deepEqual(changes, ["added:AR"]);
});

test("only an arrival waits: a card promoted after the active one leaves starts even while TTS plays", () => {
  const { bus, tts, ar, timers } = setup();
  arrive(bus, "A1");
  arrive(bus, "A2");
  tts.enqueue(speech("X"));
  bus.emit({ type: "notification_expired", payload: { id_hash: "A1" }, source: "test", ts: 0 });
  assert.equal(ar.getById("A2")!.expires_at, null, "precondition: A2 queues behind A1's grace period");
  timers.fireTimeouts();
  assert.equal(ar.getById("A1"), undefined);
  assert.equal(tts.isPlaying(), true);
  assert.equal(ar.getById("A2")!.expires_at, NOW + 30_000, "legacy activateNextNotification does not ask TTS");
});

// ---------------------------------------------------------------------------
// Assembled — createStores + the boot TTS intent wire (the self-defer trap, live)
// ---------------------------------------------------------------------------

function assembled() {
  const bus    = createEventBusForTesting();
  const api    = { get: async () => ({}), post: async () => ({}), patch: async () => ({}) } as never;
  const stores = createStores({ eventBus: bus, storage: createStorageServiceForTesting(bus), api });
  wireNotificationTtsIntent(bus, stores.ttsQueue, () => NOW, () => ({ fraction: 1, enabled: false, minChars: 100 }));
  return { bus, stores };
}

test("assembled: a spoken prompt arriving into silence activates, though its own speech took the slot first", () => {
  const { bus, stores } = assembled();
  arrive(bus, "AR", "high");
  assert.equal(stores.ttsQueue.current(), "AR", "precondition: the prompt's own speech holds the slot");
  assert.notEqual(stores.actionRequired.getById("AR")!.expires_at, null);
});

test("assembled: a spoken prompt arriving behind another notification's speech waits, then activates on its end", () => {
  const { bus, stores } = assembled();
  bus.emit({
    type    : "notification_queue_update",
    payload : { notification: { id_hash: "N1", message: "Build done", sender_id: "bob@x", priority: "high",
                                timestamp: new Date(NOW).toISOString() } },
    source  : "test",
    ts      : 0,
  });
  arrive(bus, "AR", "high");
  assert.equal(stores.ttsQueue.current(), "N1");
  assert.equal(stores.actionRequired.getById("AR")!.expires_at, null);
  ended(bus);
  assert.equal(stores.ttsQueue.current(), "AR", "the queue rolled to the prompt's own speech");
  assert.notEqual(stores.actionRequired.getById("AR")!.expires_at, null);
});
