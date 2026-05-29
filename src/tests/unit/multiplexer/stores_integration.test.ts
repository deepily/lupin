// Multiplexer Phase 4 — cross-store integration tests.
// Run via `npx tsx --test src/tests/unit/multiplexer/stores_integration.test.ts`.
// AC8 + AC4 floor: ≥ 6 tests per design doc § Verification matrix.

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../fastapi_app/static/js/multiplexer/shared/EventBus";
import { createStorageServiceForTesting } from "../../../fastapi_app/static/js/multiplexer/shared/StorageService";
import { createStores } from "../../../fastapi_app/static/js/multiplexer/stores";
import type { ActionRequiredApiClient } from "../../../fastapi_app/static/js/multiplexer/stores";
import type {
  AudioContextLike,
  AudioBufferLike,
} from "../../../fastapi_app/static/js/multiplexer/audio/pcm-decoder";
import type {
  LupinEvent,
  LupinEventType,
} from "../../../fastapi_app/static/js/multiplexer/shared/types";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeApiStub(): ActionRequiredApiClient {
  return { post: async () => ({ ok: true }) };
}

class StubAudioContext implements AudioContextLike {
  createBuffer(channels: number, length: number, sampleRate: number): AudioBufferLike {
    return {
      numberOfChannels : channels,
      length,
      sampleRate,
      duration         : length / sampleRate,
      copyToChannel    : () => {},
    };
  }
}

function setupAll() {
  const bus     = createEventBusForTesting();
  const storage = createStorageServiceForTesting(bus);
  const order   : LupinEventType[] = [];
  // Tap to record EVERY emission in arrival order, regardless of type.
  // We use specific types so we can assert ordering across stores.
  const watch = ["store_notifications_changed", "store_senders_changed", "store_action_required_changed", "store_audio_state_change", "store_jobs_changed"] as const;
  for (const t of watch) {
    bus.on(t, (e) => order.push(e.type));
  }
  const stores = createStores({
    eventBus            : bus,
    storage,
    api                 : makeApiStub(),
    audioContextFactory : () => new StubAudioContext(),
  });
  return { bus, storage, stores, order };
}

// ===========================================================================
// 1 — Subscription order: action-required notification → 3 stores fire in canonical order
// ===========================================================================

test("notification with response_requested=true fans out: NotificationStore (filtered out — empty msg=>no), SenderStore + ActionRequiredStore in order", () => {
  const ctx = setupAll();
  // Fire a single notification_queue_update with response_requested=true.
  // Per pinned order: NotificationStore (1st), SenderStore (2nd),
  // ActionRequiredStore (3rd), AudioStore (4th — no subscription on this
  // event), JobStore (5th — no subscription on this event).
  ctx.bus.emit({
    type    : "notification_queue_update",
    payload : {
      notification: {
        id_hash            : "ar1",
        message            : "Proceed?",
        sender_id          : "alice@x",
        timestamp          : new Date(1_000_000).toISOString(),
        response_requested : true,
        response_type      : "yes_no",
        response_options   : ["yes", "no"],
        timeout_seconds    : 30,
      },
    },
    source : "test",
    ts     : 0,
  });
  // Filter to only the cross-store-relevant emissions in arrival order.
  // Expected sequence: store_notifications_changed (added) →
  //                    store_senders_changed (added) →
  //                    store_action_required_changed (added).
  // Hydration emissions from NotificationStore construct happened earlier.
  const arrivalOrder = ctx.order.filter(t => t !== "store_notifications_changed" || ctx.order.indexOf(t) === ctx.order.lastIndexOf(t));
  // Simpler: look at the last 3 entries — those are this notification's fanout.
  const lastThree = ctx.order.slice(-3);
  assert.deepEqual(lastThree, [
    "store_notifications_changed",
    "store_senders_changed",
    "store_action_required_changed",
  ]);
});

// ===========================================================================
// 2 — Plain notification (no action required): NotificationStore + SenderStore (no ActionRequired)
// ===========================================================================

test("notification without response_requested fans out: NotificationStore + SenderStore only", () => {
  const ctx = setupAll();
  ctx.bus.emit({
    type    : "notification_queue_update",
    payload : {
      notification: {
        id_hash    : "n1",
        message    : "Hello",
        sender_id  : "alice@x",
        timestamp  : new Date(1_000_000).toISOString(),
      },
    },
    source : "test",
    ts     : 0,
  });
  const lastTwo = ctx.order.slice(-2);
  assert.deepEqual(lastTwo, ["store_notifications_changed", "store_senders_changed"]);
});

// ===========================================================================
// 3 — Job event isolation: only JobStore reacts
// ===========================================================================

test("job_state_transition only triggers JobStore emission", () => {
  const ctx = setupAll();
  const before = ctx.order.length;
  ctx.bus.emit({
    type    : "job_state_transition",
    payload : { job_id: "j1", to_state: "queued", timestamp: "2026-05-04T12:00:00Z" },
    source  : "test",
    ts      : 0,
  });
  const after = ctx.order.slice(before);
  assert.deepEqual(after, ["store_jobs_changed"]);
});

// ===========================================================================
// 4 — sys_time_update is "broad signal" — no store_changed events emitted unless prompts pending
// ===========================================================================

test("sys_time_update with no pending prompts: no store_changed emissions", () => {
  const ctx = setupAll();
  const before = ctx.order.length;
  ctx.bus.emit({ type: "sys_time_update", payload: {}, source: "test", ts: 0 });
  // NotificationStore sweeps active list (no items expired) → no emit.
  // ActionRequiredStore sees event but updates clockOffset only → no emit.
  assert.equal(ctx.order.length, before);
});

// ===========================================================================
// 5 — store getById propagates correctly across instances
// ===========================================================================

test("cross-store data access: notification + sender + ar prompt all queryable post-fanout", () => {
  const ctx = setupAll();
  ctx.bus.emit({
    type    : "notification_queue_update",
    payload : {
      notification: {
        id_hash            : "ar1",
        message            : "?",
        sender_id          : "bob@x",
        timestamp          : new Date(1_000_000).toISOString(),
        response_requested : true,
        timeout_seconds    : 30,
      },
    },
    source : "test",
    ts     : 0,
  });
  const n = ctx.stores.notifications.list().find(x => x.id_hash === "ar1");
  const s = ctx.stores.senders.get("bob@x");
  const ar = ctx.stores.actionRequired.getById("ar1");
  assert.ok(n,  "NotificationStore registers the prompt");
  assert.ok(s,  "SenderStore registers the sender");
  assert.ok(ar, "ActionRequiredStore registers the prompt");
});

// ===========================================================================
// 6 — Audio binary frame: only AudioStore reacts (transport-level callback, not bus)
// ===========================================================================

test("AudioStore.binaryHandler invocation does NOT emit any bus event from other stores", () => {
  const ctx = setupAll();
  const before = ctx.order.length;
  // Direct call to binary handler — bypasses the bus entirely.
  const buf = new Int16Array([0, 100, -100, 200, -200]).buffer;
  ctx.stores.audio.binaryHandler(buf);
  const after = ctx.order.slice(before);
  // Only AudioStore should emit (state transitions). No notification/job/sender events.
  for (const t of after) {
    assert.ok(
      t === "store_audio_state_change",
      `unexpected non-audio event during binaryHandler: ${t}`,
    );
  }
});

// ===========================================================================
// 7 — Pinned order under microtask boundary: emissions from a single dispatch are deterministic
// ===========================================================================

test("microtask determinism: emissions from a single notification dispatch are in pinned order, no interleaving", () => {
  const ctx = setupAll();
  const before = ctx.order.length;
  ctx.bus.emit({
    type    : "notification_queue_update",
    payload : {
      notification: {
        id_hash            : "ar2",
        message            : "?",
        sender_id          : "carol@x",
        timestamp          : new Date(1_000_000).toISOString(),
        response_requested : true,
        timeout_seconds    : 30,
      },
    },
    source : "test",
    ts     : 0,
  });
  // emit() is synchronous (CustomEvent dispatch) — all listeners fire before
  // emit() returns. So `ctx.order` already has the full fanout in registration
  // order, no microtask boundary needed.
  const fanout = ctx.order.slice(before);
  // Exactly 3 emissions (NotificationStore + SenderStore + ActionRequiredStore).
  assert.equal(fanout.length, 3);
  assert.deepEqual(fanout, [
    "store_notifications_changed",
    "store_senders_changed",
    "store_action_required_changed",
  ]);
});
