// Multiplexer Phase 4 — NotificationStore unit tests.
// Run via `npx tsx --test src/tests/unit/multiplexer/notification_store.test.ts`.
// AC4 floor: ≥ 18 tests per design doc § Verification matrix per-store floor.

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createStorageServiceForTesting, InMemoryStorage } from "../../../lupin_app/static/js/multiplexer/shared/StorageService";
import { createNotificationStore } from "../../../lupin_app/static/js/multiplexer/stores/NotificationStore";
import type {
  LupinEvent,
  StoreNotificationsChangedPayload,
} from "../../../lupin_app/static/js/multiplexer/shared/types";

// ---------------------------------------------------------------------------
// Test utilities — manual timer + Date.now stubs so tests are fully deterministic.
// ---------------------------------------------------------------------------

interface TimerEntry {
  id : number;
  cb : () => void;
  ms : number;
}

function makeFakeTimers() {
  let nextId = 1;
  const queue: TimerEntry[] = [];
  return {
    setTimeoutFn: ((cb: () => void, ms: number): unknown => {
      const entry: TimerEntry = { id: nextId++, cb, ms };
      queue.push(entry);
      return entry.id;
    }) as (cb: () => void, ms: number) => unknown,
    clearTimeoutFn: ((id: unknown): void => {
      const idx = queue.findIndex(e => e.id === id);
      if (idx >= 0) queue.splice(idx, 1);
    }) as (id: unknown) => void,
    flushAll(): void {
      while (queue.length > 0) {
        const entry = queue.shift()!;
        entry.cb();
      }
    },
    pending(): number {
      return queue.length;
    },
  };
}

function setupStore(opts: {
  initialUnread?: number;
  now          ?: number;
} = {}) {
  const bus     = createEventBusForTesting();
  const backend = new InMemoryStorage();
  const storage = createStorageServiceForTesting(bus, backend);
  if (opts.initialUnread !== undefined) {
    storage.setJSON("notifications:unread-count", { count: opts.initialUnread, lastSeenTs: 1000 }, 1);
  }
  const timers = makeFakeTimers();
  let now      = opts.now ?? 1_700_000_000_000;
  const events: LupinEvent<unknown>[] = [];
  bus.on("store_notifications_changed", (e) => events.push(e));
  const store  = createNotificationStore({
    bus,
    storage,
    setTimeoutFn   : timers.setTimeoutFn,
    clearTimeoutFn : timers.clearTimeoutFn,
    nowFn          : () => now,
  });
  return {
    bus,
    storage,
    backend,
    store,
    events,
    timers,
    setNow(n: number) { now = n; },
    getNow() { return now; },
  };
}

function emitNotification(bus: ReturnType<typeof createEventBusForTesting>, fields: {
  id_hash             ?: string;
  message             ?: string;
  sender_id           ?: string;
  title               ?: string;
  timestamp           ?: string;
  response_requested  ?: boolean;
  response_type       ?: "yes_no" | "multiple_choice" | "open_ended" | "open_ended_batch";
  response_options    ?: ReadonlyArray<string>;
  response_default    ?: string;
  timeout_seconds     ?: number;
  // Phase 5 D-B (2026-05-05) — renderer-surfaced fields.
  voice_persona       ?: { name: string; voice_id: string; icon: string; color: string; borrowed: boolean };
  abstract            ?: string;
  progress_group_id   ?: string;
  was_expired         ?: boolean;
  time_display        ?: string;
  // WP14 (F8) — prediction-hint payload.
  prediction_hint     ?: { confidence: number; predicted_value: unknown; category: string };
}): void {
  bus.emit({
    type    : "notification_queue_update",
    payload : {
      queue_name   : "notification",
      value        : 1,
      notification : { ...fields },
    },
    source : "test",
    ts     : 0,
  });
}

// ===========================================================================
// 1-3 : Hydration
// ===========================================================================

test("hydrate: empty storage → unread=0; emits changeKind=hydrated on construct", () => {
  const { store, events } = setupStore();
  assert.equal(store.unreadCount(), 0);
  // First emission must be the hydrated signal.
  const hydrated = events.filter(e => (e.payload as StoreNotificationsChangedPayload).changeKind === "hydrated");
  assert.equal(hydrated.length, 1);
});

test("hydrate: pre-existing unread-count envelope restores unread", () => {
  const { store } = setupStore({ initialUnread: 7 });
  assert.equal(store.unreadCount(), 7);
});

test("hydrate: corrupt envelope (schemaVersion mismatch) leaves unread at 0", () => {
  const bus     = createEventBusForTesting();
  const storage = createStorageServiceForTesting(bus);
  // Write a v999 envelope — current schema is v1.
  storage.setJSON("notifications:unread-count", { count: 42, lastSeenTs: 1 }, 999);
  const store = createNotificationStore({ bus, storage });
  assert.equal(store.unreadCount(), 0);
});

// ===========================================================================
// 4-7 : Reducer for notification_queue_update — new arrivals
// ===========================================================================

test("notification_queue_update with notification field appends, bumps unread, emits added", () => {
  const { bus, store, events } = setupStore();
  const beforeLen = events.length;
  emitNotification(bus, {
    id_hash   : "n1",
    message   : "hello",
    sender_id : "user@example.com",
    timestamp : new Date(1_700_000_000_000).toISOString(),
  });
  assert.equal(store.list().length, 1);
  assert.equal(store.unreadCount(), 1);
  const added = events.slice(beforeLen).find(e =>
    (e.payload as StoreNotificationsChangedPayload).changeKind === "added"
  );
  assert.ok(added, "should emit changeKind=added");
  assert.equal((added!.payload as StoreNotificationsChangedPayload).id_hash, "n1");
});

test("notification_queue_update without notification field is a no-op (resync path)", () => {
  const { bus, store } = setupStore();
  bus.emit({
    type    : "notification_queue_update",
    payload : { queue_name: "notification", value: 5, unplayed_count: 3 },
    source  : "test",
    ts      : 0,
  });
  assert.equal(store.list().length, 0);
  assert.equal(store.unreadCount(), 0);
});

test("notification_queue_update dedups by id_hash on re-arrival; emits updated, no unread bump", () => {
  const { bus, store, events } = setupStore();
  emitNotification(bus, { id_hash: "n1", message: "first" });
  const beforeLen = events.length;
  emitNotification(bus, { id_hash: "n1", message: "first (updated)" });
  assert.equal(store.list().length, 1);
  assert.equal(store.unreadCount(), 1);
  const updated = events.slice(beforeLen).find(e =>
    (e.payload as StoreNotificationsChangedPayload).changeKind === "updated"
  );
  assert.ok(updated);
  // Updated message reflected in active list.
  assert.equal(store.list()[0]!.message, "first (updated)");
});

test("notification_queue_update rejects malformed payload (missing id_hash)", () => {
  const { bus, store } = setupStore();
  bus.emit({
    type    : "notification_queue_update",
    payload : { notification: { message: "no id_hash here" } },
    source  : "test",
    ts      : 0,
  });
  assert.equal(store.list().length, 0);
  assert.equal(store.unreadCount(), 0);
});

// ===========================================================================
// 8-9 : Field normalization
// ===========================================================================

test("normalization: timestamp ISO string → ts ms epoch", () => {
  const { bus, store } = setupStore();
  emitNotification(bus, {
    id_hash   : "n1",
    message   : "x",
    timestamp : "2026-05-04T12:00:00.000Z",
  });
  const n = store.list()[0]!;
  assert.equal(n.ts, Date.parse("2026-05-04T12:00:00.000Z"));
});

test("normalization: response_requested + timeout_seconds → action_required + expires_at", () => {
  const { bus, store } = setupStore();
  const isoTs = "2026-05-04T12:00:00.000Z";
  emitNotification(bus, {
    id_hash            : "ar1",
    message            : "do you confirm?",
    timestamp          : isoTs,
    response_requested : true,
    response_type      : "yes_no",
    response_options   : ["yes", "no"],
    response_default   : "no",
    timeout_seconds    : 30,
  });
  const n = store.list()[0]!;
  assert.equal(n.action_required, true);
  assert.equal(n.expires_at, Date.parse(isoTs) + 30_000);
  assert.equal(n.response_type, "yes_no");
  assert.deepEqual(n.options, ["yes", "no"]);
  assert.equal(n.default_value, "no");
});

// WP14 (F8): prediction_hint carries through normalize() onto the Notification.
test("normalization: prediction_hint copied through onto the notification (F8)", () => {
  const { bus, store } = setupStore();
  emitNotification(bus, {
    id_hash         : "pred1",
    message         : "Schedule the meeting?",
    response_type   : "yes_no",
    prediction_hint : { confidence: 0.9, predicted_value: "yes", category: "calendar" },
  });
  const n = store.list()[0]!;
  assert.deepEqual(n.prediction_hint, { confidence: 0.9, predicted_value: "yes", category: "calendar" });
});

// Absent prediction_hint stays undefined (the `!== undefined` copy-guard's false arm).
test("normalization: no prediction_hint → field stays undefined", () => {
  const { bus, store } = setupStore();
  emitNotification(bus, { id_hash: "plain1", message: "no hint here" });
  const n = store.list()[0]!;
  assert.equal(n.prediction_hint, undefined);
});

// ===========================================================================
// 10-11 : notification_responded
// ===========================================================================

test("notification_responded marks responded=true, emits updated, leaves unread alone", () => {
  const { bus, store, events } = setupStore();
  emitNotification(bus, { id_hash: "n1", message: "ar", response_requested: true });
  const beforeUnread = store.unreadCount();
  const beforeLen = events.length;
  bus.emit({ type: "notification_responded", payload: { id_hash: "n1", response: "yes" }, source: "test", ts: 0 });
  assert.equal(store.list()[0]!.responded, true);
  assert.equal(store.unreadCount(), beforeUnread);
  const updated = events.slice(beforeLen).find(e =>
    (e.payload as StoreNotificationsChangedPayload).changeKind === "updated"
  );
  assert.ok(updated);
});

test("notification_responded for unknown id_hash is a no-op", () => {
  const { bus, store, events } = setupStore();
  const beforeLen = events.length;
  bus.emit({ type: "notification_responded", payload: { id_hash: "ghost" }, source: "test", ts: 0 });
  assert.equal(events.length, beforeLen);
  assert.equal(store.list().length, 0);
});

// ===========================================================================
// 12-14 : notification_expired + sys_time_update sweep
// ===========================================================================

test("notification_expired moves item from active to history; emits expired", () => {
  const { bus, store, events } = setupStore();
  emitNotification(bus, { id_hash: "n1", message: "x" });
  const beforeLen = events.length;
  bus.emit({ type: "notification_expired", payload: { id_hash: "n1" }, source: "test", ts: 0 });
  assert.equal(store.list().length, 0);
  assert.equal(store.history().length, 1);
  const expired = events.slice(beforeLen).find(e =>
    (e.payload as StoreNotificationsChangedPayload).changeKind === "expired"
  );
  assert.ok(expired);
});

test("notification_expired is idempotent — repeated events are no-ops", () => {
  const { bus, store, events } = setupStore();
  emitNotification(bus, { id_hash: "n1", message: "x" });
  bus.emit({ type: "notification_expired", payload: { id_hash: "n1" }, source: "test", ts: 0 });
  const lenAfterFirst = events.length;
  bus.emit({ type: "notification_expired", payload: { id_hash: "n1" }, source: "test", ts: 0 });
  assert.equal(events.length, lenAfterFirst);
  assert.equal(store.history().length, 1);
});

test("sys_time_update local sweep: items past expires_at move to history with source=local-sweep", () => {
  const ctx = setupStore({ now: 1_000_000 });
  emitNotification(ctx.bus, {
    id_hash            : "ar1",
    message            : "fast prompt",
    response_requested : true,
    timestamp          : new Date(1_000_000).toISOString(),
    timeout_seconds    : 1,    // expires at 1_001_000
  });
  ctx.setNow(1_001_500);     // advance past expiry
  const beforeLen = ctx.events.length;
  ctx.bus.emit({ type: "sys_time_update", payload: { ts: ctx.getNow() }, source: "test", ts: 0 });
  assert.equal(ctx.store.list().length, 0);
  assert.equal(ctx.store.history().length, 1);
  const sweepEvent = ctx.events.slice(beforeLen).find(e =>
    (e.payload as StoreNotificationsChangedPayload).changeKind === "expired" &&
    (e.payload as StoreNotificationsChangedPayload).source === "local-sweep"
  );
  assert.ok(sweepEvent, "should emit local-sweep tagged expired event");
});

test("sys_time_update sweep does NOT touch items without expires_at", () => {
  const ctx = setupStore({ now: 1_000_000 });
  emitNotification(ctx.bus, { id_hash: "n1", message: "no timeout" });   // no timeout_seconds + no response_requested
  ctx.setNow(99_999_999_999);
  ctx.bus.emit({ type: "sys_time_update", payload: { ts: ctx.getNow() }, source: "test", ts: 0 });
  assert.equal(ctx.store.list().length, 1);
  assert.equal(ctx.store.history().length, 0);
});

test("double-expire race: local sweep + server notification_expired produces single history entry", () => {
  const ctx = setupStore({ now: 1_000_000 });
  emitNotification(ctx.bus, {
    id_hash            : "ar1",
    message            : "x",
    response_requested : true,
    timestamp          : new Date(1_000_000).toISOString(),
    timeout_seconds    : 1,
  });
  ctx.setNow(1_002_000);
  // Local sweep first…
  ctx.bus.emit({ type: "sys_time_update", payload: {}, source: "test", ts: 0 });
  // …then server tells us the same.
  ctx.bus.emit({ type: "notification_expired", payload: { id_hash: "ar1" }, source: "test", ts: 0 });
  assert.equal(ctx.store.history().length, 1);
  assert.equal(ctx.store.list().length, 0);
});

// ===========================================================================
// 15-17 : markRead / markAllRead
// ===========================================================================

test("markRead decrements unread; emits updated; idempotent on second call", () => {
  const { bus, store, events } = setupStore();
  emitNotification(bus, { id_hash: "n1", message: "x" });
  emitNotification(bus, { id_hash: "n2", message: "y" });
  assert.equal(store.unreadCount(), 2);
  const before = events.length;
  store.markRead("n1");
  assert.equal(store.unreadCount(), 1);
  const updated = events.slice(before).filter(e =>
    (e.payload as StoreNotificationsChangedPayload).changeKind === "updated"
  );
  assert.equal(updated.length, 1);
  // Second call is a no-op.
  store.markRead("n1");
  assert.equal(store.unreadCount(), 1);
});

test("markRead on unknown id_hash is a no-op", () => {
  const { store, events } = setupStore({ initialUnread: 3 });
  const before = events.length;
  store.markRead("ghost");
  assert.equal(store.unreadCount(), 3);
  assert.equal(events.length, before);
});

test("markAllRead zeros unread + emits a single bulk updated event; second call is a no-op", () => {
  const { bus, store, events } = setupStore();
  emitNotification(bus, { id_hash: "n1", message: "x" });
  emitNotification(bus, { id_hash: "n2", message: "y" });
  emitNotification(bus, { id_hash: "n3", message: "z" });
  const before = events.length;
  store.markAllRead();
  assert.equal(store.unreadCount(), 0);
  const updated = events.slice(before).filter(e =>
    (e.payload as StoreNotificationsChangedPayload).changeKind === "updated"
  );
  assert.equal(updated.length, 1, "single bulk emission");
  // Second call is a no-op (no further emission).
  const before2 = events.length;
  store.markAllRead();
  assert.equal(events.length, before2);
});

// ===========================================================================
// 18-20 : Persistence (debounced)
// ===========================================================================

test("persistence: setJSON not called immediately; only on debounce flush", () => {
  const { bus, store, backend, timers } = setupStore();
  emitNotification(bus, { id_hash: "n1", message: "x" });
  // No flush yet → no envelope written (other than the hydrated read,
  // which doesn't write).
  const rawBefore = backend.getItem("lupin:notifications:unread-count");
  assert.equal(rawBefore, null);
  // Pending timer scheduled.
  assert.equal(timers.pending() >= 1, true);
  store.flushPersistenceForTesting();
  const rawAfter = backend.getItem("lupin:notifications:unread-count");
  assert.ok(rawAfter !== null, "envelope should be persisted post-flush");
});

test("persistence: envelope carries schemaVersion=1 + count + lastSeenTs", () => {
  const { bus, store, backend } = setupStore();
  emitNotification(bus, { id_hash: "n1", message: "x" });
  emitNotification(bus, { id_hash: "n2", message: "y" });
  store.flushPersistenceForTesting();
  const raw = backend.getItem("lupin:notifications:unread-count");
  assert.ok(raw);
  const env = JSON.parse(raw!);
  assert.equal(env.schemaVersion, 1);
  assert.equal(env.payload.count, 2);
  assert.equal(typeof env.payload.lastSeenTs, "number");
});

test("persistence: rapid bursts coalesce — multiple changes → single timer firing → single write", () => {
  const { bus, backend, timers } = setupStore();
  // Three consecutive arrivals.
  emitNotification(bus, { id_hash: "n1", message: "a" });
  emitNotification(bus, { id_hash: "n2", message: "b" });
  emitNotification(bus, { id_hash: "n3", message: "c" });
  // Should be exactly one pending timer (rescheduled each time).
  assert.equal(timers.pending(), 1);
  timers.flushAll();
  const raw = backend.getItem("lupin:notifications:unread-count");
  const env = JSON.parse(raw!);
  assert.equal(env.payload.count, 3);
  // No lingering timers.
  assert.equal(timers.pending(), 0);
});

// ===========================================================================
// 21-22 : history bookkeeping + unread interaction
// ===========================================================================

test("expireToHistory: unread items moved to history decrement unread", () => {
  const { bus, store } = setupStore();
  emitNotification(bus, { id_hash: "n1", message: "x" });
  assert.equal(store.unreadCount(), 1);
  bus.emit({ type: "notification_expired", payload: { id_hash: "n1" }, source: "test", ts: 0 });
  assert.equal(store.history().length, 1);
  assert.equal(store.unreadCount(), 0);
});

test("expireToHistory: read items do NOT decrement unread again", () => {
  const { bus, store } = setupStore();
  emitNotification(bus, { id_hash: "n1", message: "x" });
  store.markRead("n1");                                                  // unread → 0
  assert.equal(store.unreadCount(), 0);
  bus.emit({ type: "notification_expired", payload: { id_hash: "n1" }, source: "test", ts: 0 });
  // Stays at 0, not -1.
  assert.equal(store.unreadCount(), 0);
});

// ===========================================================================
// 23-27 : Phase 5 D-B (2026-05-05) — renderer-surfaced fields round-trip
// ===========================================================================

test("D-B normalize: voice_persona round-trips through the store", () => {
  const { bus, store } = setupStore();
  const persona = { name: "Tiberius", voice_id: "vid_42", icon: "🦊", color: "#ab1234", borrowed: false };
  emitNotification(bus, { id_hash: "n1", message: "x", voice_persona: persona });
  const list = store.list();
  assert.equal(list.length, 1);
  assert.deepEqual(list[0]!.voice_persona, persona);
});

test("D-B normalize: abstract round-trips through the store", () => {
  const { bus, store } = setupStore();
  const text = "Long-form abstract describing background context for this notification.";
  emitNotification(bus, { id_hash: "n1", message: "x", abstract: text });
  assert.equal(store.list()[0]!.abstract, text);
});

test("D-B normalize: progress_group_id round-trips through the store", () => {
  const { bus, store } = setupStore();
  emitNotification(bus, { id_hash: "n1", message: "x", progress_group_id: "pg_research_001" });
  assert.equal(store.list()[0]!.progress_group_id, "pg_research_001");
});

test("D-B normalize: was_expired round-trips through the store", () => {
  const { bus, store } = setupStore();
  emitNotification(bus, { id_hash: "n1", message: "x", was_expired: true });
  assert.equal(store.list()[0]!.was_expired, true);
});

test("D-B normalize: time_display round-trips through the store", () => {
  const { bus, store } = setupStore();
  emitNotification(bus, { id_hash: "n1", message: "x", time_display: "23:10 EST" });
  assert.equal(store.list()[0]!.time_display, "23:10 EST");
});

// ---------------------------------------------------------------------------
// Coverage backfill — additional defensive branches
// ---------------------------------------------------------------------------

test("normalize: title field round-trips through the store", () => {
  // Exercises the truthy arm of `if (raw.title !== undefined)` in normalize().
  const { bus, store } = setupStore();
  emitNotification(bus, { id_hash: "n1", message: "x", title: "Hello there" });
  assert.equal(store.list()[0]!.title, "Hello there");
});

test("normalize: notification with non-string `message` is rejected", () => {
  // Exercises the `typeof raw.message !== \"string\"` arm in normalize().
  const { bus, store } = setupStore();
  bus.emit({
    type    : "notification_queue_update",
    payload : { notification: { id_hash: "n1", message: 42 as unknown as string } },
    source  : "test",
    ts      : 0,
  });
  assert.equal(store.list().length, 0);
});

test("normalize: invalid timestamp string yields null (notification dropped)", () => {
  // Exercises the `Number.isNaN(ts)` arm in normalize().
  const { bus, store } = setupStore();
  emitNotification(bus, { id_hash: "n1", message: "x", timestamp: "not-a-date" });
  assert.equal(store.list().length, 0);
});

test("notification_responded with only `notification_id` (no `id_hash`) — falls back via `??`", () => {
  // Exercises the second arm of `e.payload.id_hash ?? e.payload.notification_id`
  // in onResponded.
  const { bus, store } = setupStore();
  emitNotification(bus, { id_hash: "n1", message: "ping" });
  bus.emit({
    type    : "notification_responded",
    payload : { notification_id: "n1" },
    source  : "test",
    ts      : 0,
  });
  assert.equal(store.list()[0]!.responded, true);
});

test("notification_responded with neither id_hash nor notification_id is dropped silently", () => {
  // Exercises the truthy arm of `if (!id) return;` in onResponded.
  const { bus, store } = setupStore();
  emitNotification(bus, { id_hash: "n1", message: "ping" });
  bus.emit({
    type    : "notification_responded",
    payload : {},
    source  : "test",
    ts      : 0,
  });
  assert.equal(store.list()[0]!.responded, undefined, "no transition without an id");
});

test("notification_responded for an already-responded notification is a no-op", () => {
  // Exercises the truthy arm of `if (n.responded) return;` in onResponded.
  const { bus, store } = setupStore();
  emitNotification(bus, { id_hash: "n1", message: "ping" });
  bus.emit({ type: "notification_responded", payload: { id_hash: "n1" }, source: "test", ts: 0 });
  assert.equal(store.list()[0]!.responded, true);
  // Second response — should be a no-op (no extra emit, state unchanged).
  bus.emit({ type: "notification_responded", payload: { id_hash: "n1" }, source: "test", ts: 0 });
  assert.equal(store.list()[0]!.responded, true);
});

test("notification_expired with only `notification_id` — falls back via `??`", () => {
  // Exercises the `notification_id` arm of `e.payload.id_hash ?? e.payload.notification_id`
  // in onExpired.
  const { bus, store } = setupStore();
  emitNotification(bus, { id_hash: "n1", message: "ping" });
  bus.emit({
    type    : "notification_expired",
    payload : { notification_id: "n1" },
    source  : "test",
    ts      : 0,
  });
  assert.equal(store.list().length, 0, "n1 moved to history");
});

test("notification_expired with neither id is dropped silently", () => {
  const { bus, store } = setupStore();
  emitNotification(bus, { id_hash: "n1", message: "ping" });
  bus.emit({
    type    : "notification_expired",
    payload : {},
    source  : "test",
    ts      : 0,
  });
  assert.equal(store.list().length, 1, "no expiry without an id");
});

test("notification_expired for unknown id is silently dropped (idempotency guard)", () => {
  // Exercises the truthy arm of `if (!this.byId.has(idHash)) return;` in
  // expireToHistory().
  const { bus, store } = setupStore();
  emitNotification(bus, { id_hash: "n1", message: "ping" });
  bus.emit({
    type    : "notification_expired",
    payload : { id_hash: "unknown-id" },
    source  : "test",
    ts      : 0,
  });
  assert.equal(store.list().length, 1, "n1 untouched");
});
