// Multiplexer Phase 4 — ActionRequiredStore unit tests.
// Run via `npx tsx --test src/tests/unit/multiplexer/action_required_store.test.ts`.
// AC4 floor: ≥ 22 tests (D-F bumped from 18 to 22 for the hybrid timer +
// sys_time_update + connection_state_change cases).

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../fastapi_app/static/js/multiplexer/shared/EventBus";
import {
  createActionRequiredStore,
  type ActionRequiredApiClient,
} from "../../../fastapi_app/static/js/multiplexer/stores/ActionRequiredStore";
import type {
  LupinEvent,
  StoreActionRequiredChangedPayload,
} from "../../../fastapi_app/static/js/multiplexer/shared/types";

// ---------------------------------------------------------------------------
// Manual timer harness (separate from NotificationStore's setTimeout one —
// this is for setInterval, which fires repeatedly).
// ---------------------------------------------------------------------------

interface IntervalEntry {
  id : number;
  cb : () => void;
  ms : number;
}

function makeFakeIntervals() {
  let nextId = 1;
  const map = new Map<number, IntervalEntry>();
  return {
    setIntervalFn: ((cb: () => void, ms: number): unknown => {
      const id = nextId++;
      map.set(id, { id, cb, ms });
      return id;
    }) as (cb: () => void, ms: number) => unknown,
    clearIntervalFn: ((id: unknown): void => {
      map.delete(id as number);
    }) as (id: unknown) => void,
    /** Fire all currently-scheduled intervals exactly once. */
    fireAll(): void {
      // Snapshot first because tick callbacks may mutate the map (e.g. expire
      // calls clearInterval).
      const snapshot = Array.from(map.values());
      for (const entry of snapshot) {
        if (map.has(entry.id)) entry.cb();
      }
    },
    pending(): number {
      return map.size;
    },
    has(id: unknown): boolean {
      return map.has(id as number);
    },
  };
}

// ---------------------------------------------------------------------------
// Test setup helpers
// ---------------------------------------------------------------------------

function setup(opts: { now?: number } = {}) {
  const bus    = createEventBusForTesting();
  const events: LupinEvent<StoreActionRequiredChangedPayload>[] = [];
  bus.on<StoreActionRequiredChangedPayload>("store_action_required_changed", (e) => events.push(e));
  let now      = opts.now ?? 1_700_000_000_000;
  const timers = makeFakeIntervals();
  let postCalls: Array<{ path: string; body: unknown }> = [];
  let postRejects = false;
  const api: ActionRequiredApiClient = {
    post: async (path, body) => {
      postCalls.push({ path, body });
      if (postRejects) throw new Error("network down");
      return { ok: true };
    },
  };
  const store = createActionRequiredStore({
    bus,
    api,
    setIntervalFn   : timers.setIntervalFn,
    clearIntervalFn : timers.clearIntervalFn,
    nowFn           : () => now,
  });
  return {
    bus,
    store,
    events,
    timers,
    postCalls,
    setNow: (n: number) => { now = n; },
    getNow: () => now,
    setPostRejects: (b: boolean) => { postRejects = b; },
  };
}

function emitArPrompt(bus: ReturnType<typeof createEventBusForTesting>, fields: {
  id_hash             ?: string;
  message             ?: string;
  timestamp           ?: string;
  response_requested  ?: boolean;
  response_type       ?: "yes_no" | "multiple_choice" | "open_ended" | "open_ended_batch";
  response_options    ?: ReadonlyArray<string>;
  response_default    ?: string;
  timeout_seconds     ?: number;
}): void {
  bus.emit({
    type    : "notification_queue_update",
    payload : { notification: { ...fields } },
    source  : "test",
    ts      : 0,
  });
}

// ===========================================================================
// 1-3 : Spawn / dedup / non-action notifications ignored
// ===========================================================================

test("notification_queue_update with response_requested=true spawns a prompt; emits added", () => {
  const ctx = setup({ now: 1_000_000 });
  emitArPrompt(ctx.bus, {
    id_hash            : "ar1",
    message            : "Proceed?",
    response_requested : true,
    response_type      : "yes_no",
    response_options   : ["yes", "no"],
    response_default   : "no",
    timeout_seconds    : 30,
    timestamp          : new Date(1_000_000).toISOString(),
  });
  const item = ctx.store.getById("ar1");
  assert.ok(item);
  assert.equal(item!.state, "pending");
  assert.equal(item!.prompt, "Proceed?");
  assert.equal(item!.response_type, "yes_no");
  assert.deepEqual(item!.options, ["yes", "no"]);
  assert.equal(item!.default, "no");
  assert.equal(item!.expires_at, 1_000_000 + 30_000);
  const added = ctx.events.find(e => e.payload.changeKind === "added");
  assert.ok(added);
});

test("notification_queue_update without response_requested does NOT spawn a prompt", () => {
  const ctx = setup();
  emitArPrompt(ctx.bus, { id_hash: "n1", message: "x", response_requested: false });
  emitArPrompt(ctx.bus, { id_hash: "n2", message: "y" });          // omitted (=false)
  assert.equal(ctx.store.list().length, 0);
});

test("duplicate notification_queue_update for same id_hash: dedup, no second spawn", () => {
  const ctx = setup();
  emitArPrompt(ctx.bus, { id_hash: "ar1", message: "x", response_requested: true, timeout_seconds: 30 });
  const before = ctx.events.length;
  emitArPrompt(ctx.bus, { id_hash: "ar1", message: "x (dup)", response_requested: true, timeout_seconds: 30 });
  assert.equal(ctx.store.list().length, 1);
  assert.equal(ctx.events.length, before, "no extra emission for dedup");
});

// ===========================================================================
// 4-6 : Interval ticking
// ===========================================================================

test("setInterval(1000) is scheduled on prompt spawn; cleared on terminal state", () => {
  const ctx = setup({ now: 1_000_000 });
  emitArPrompt(ctx.bus, { id_hash: "ar1", message: "x", response_requested: true, timeout_seconds: 30, timestamp: new Date(1_000_000).toISOString() });
  assert.equal(ctx.timers.pending(), 1);
  ctx.store.respond("ar1", "yes");                                 // → responded (terminal)
  assert.equal(ctx.timers.pending(), 0);
});

test("interval tick emits store_action_required_changed with changeKind=tick + countdownMs", () => {
  const ctx = setup({ now: 1_000_000 });
  emitArPrompt(ctx.bus, { id_hash: "ar1", message: "x", response_requested: true, timeout_seconds: 30, timestamp: new Date(1_000_000).toISOString() });
  ctx.setNow(1_005_000);                                           // 5s later
  const before = ctx.events.length;
  ctx.timers.fireAll();
  const tick = ctx.events.slice(before).find(e => e.payload.changeKind === "tick");
  assert.ok(tick);
  // Remaining = 30000 - 5000 = 25000.
  assert.equal(tick!.payload.countdownMs, 25_000);
});

test("countdown reaching zero auto-expires locally + does NOT POST", () => {
  const ctx = setup({ now: 1_000_000 });
  emitArPrompt(ctx.bus, { id_hash: "ar1", message: "x", response_requested: true, timeout_seconds: 5, response_default: "no", timestamp: new Date(1_000_000).toISOString() });
  ctx.setNow(1_010_000);                                           // way past expiry
  ctx.timers.fireAll();
  const item = ctx.store.getById("ar1")!;
  assert.equal(item.state, "expired");
  assert.equal(item.response, "no", "default applied as response on local expire");
  assert.equal(ctx.postCalls.length, 0, "must NOT POST default to server (Q3)");
  assert.equal(ctx.timers.pending(), 0, "interval cleared");
  const expired = ctx.events.find(e => e.payload.changeKind === "expired");
  assert.ok(expired);
});

// ===========================================================================
// 7-10 : respond() flow
// ===========================================================================

test("respond() flips state to responded optimistically + emits responded", async () => {
  const ctx = setup();
  emitArPrompt(ctx.bus, { id_hash: "ar1", message: "x", response_requested: true, timeout_seconds: 30 });
  await ctx.store.respond("ar1", "yes");
  assert.equal(ctx.store.getById("ar1")!.state, "responded");
  assert.equal(ctx.store.getById("ar1")!.response, "yes");
  const responded = ctx.events.find(e => e.payload.changeKind === "responded");
  assert.ok(responded);
});

test("respond() POSTs to /api/notify/response with notification_id + response_value", async () => {
  const ctx = setup();
  emitArPrompt(ctx.bus, { id_hash: "ar1", message: "x", response_requested: true, timeout_seconds: 30 });
  await ctx.store.respond("ar1", "yes");
  assert.equal(ctx.postCalls.length, 1);
  assert.equal(ctx.postCalls[0]!.path, "/api/notify/response");
  const body = ctx.postCalls[0]!.body as { notification_id: string; response_value: { response: string } };
  assert.equal(body.notification_id, "ar1");
  assert.equal(body.response_value.response, "yes");
});

test("respond() on already-responded prompt is a no-op", async () => {
  const ctx = setup();
  emitArPrompt(ctx.bus, { id_hash: "ar1", message: "x", response_requested: true, timeout_seconds: 30 });
  await ctx.store.respond("ar1", "yes");
  const before = ctx.events.length;
  await ctx.store.respond("ar1", "no");
  assert.equal(ctx.events.length, before, "second respond does not emit");
  assert.equal(ctx.postCalls.length, 1, "second respond does not POST");
  // Original response retained.
  assert.equal(ctx.store.getById("ar1")!.response, "yes");
});

test("respond() network failure leaves local state at responded (UI feedback already delivered)", async () => {
  const ctx = setup();
  emitArPrompt(ctx.bus, { id_hash: "ar1", message: "x", response_requested: true, timeout_seconds: 30 });
  ctx.setPostRejects(true);
  await ctx.store.respond("ar1", "yes");
  assert.equal(ctx.store.getById("ar1")!.state, "responded");
});

test("respond() on unknown id_hash is a no-op", async () => {
  const ctx = setup();
  await ctx.store.respond("ghost", "yes");
  assert.equal(ctx.postCalls.length, 0);
  assert.equal(ctx.events.length, 0);
});

// ===========================================================================
// 11-13 : notification_responded (server fanout) cancellation
// ===========================================================================

test("notification_responded from server cancels pending prompt → cancelled state", () => {
  const ctx = setup();
  emitArPrompt(ctx.bus, { id_hash: "ar1", message: "x", response_requested: true, timeout_seconds: 30 });
  ctx.bus.emit({ type: "notification_responded", payload: { id_hash: "ar1" }, source: "test", ts: 0 });
  assert.equal(ctx.store.getById("ar1")!.state, "cancelled");
  const cancelled = ctx.events.find(e => e.payload.changeKind === "cancelled");
  assert.ok(cancelled);
});

test("notification_responded on already-responded local prompt is a no-op (server confirming)", async () => {
  const ctx = setup();
  emitArPrompt(ctx.bus, { id_hash: "ar1", message: "x", response_requested: true, timeout_seconds: 30 });
  await ctx.store.respond("ar1", "yes");
  const before = ctx.events.length;
  ctx.bus.emit({ type: "notification_responded", payload: { id_hash: "ar1" }, source: "test", ts: 0 });
  assert.equal(ctx.events.length, before);
  assert.equal(ctx.store.getById("ar1")!.state, "responded");          // not flipped to cancelled
});

test("notification_responded for unknown id_hash is a no-op", () => {
  const ctx = setup();
  ctx.bus.emit({ type: "notification_responded", payload: { id_hash: "ghost" }, source: "test", ts: 0 });
  assert.equal(ctx.events.length, 0);
});

// ===========================================================================
// 14-15 : sys_time_update → clockOffset reconciliation
// ===========================================================================

test("sys_time_update positive drift: ticks compute remaining using server clock", () => {
  const ctx = setup({ now: 1_000_000 });
  emitArPrompt(ctx.bus, { id_hash: "ar1", message: "x", response_requested: true, timeout_seconds: 30, timestamp: new Date(1_000_000).toISOString() });
  // Server clock ahead by 2 seconds.
  ctx.bus.emit({ type: "sys_time_update", payload: { serverTime: 1_002_000 }, source: "test", ts: 0 });
  // Local now = 1_000_000; clockOffset = +2000.
  ctx.setNow(1_005_000);                                           // local clock advances 5s
  const before = ctx.events.length;
  ctx.timers.fireAll();
  const tick = ctx.events.slice(before).find(e => e.payload.changeKind === "tick");
  assert.ok(tick);
  // expires_at = 1_030_000; effective now = 1_005_000 + 2000 = 1_007_000.
  // Remaining = 1_030_000 - 1_007_000 = 23_000.
  assert.equal(tick!.payload.countdownMs, 23_000);
});

test("sys_time_update negative drift: ticks compute remaining correctly with negative offset", () => {
  const ctx = setup({ now: 1_000_000 });
  emitArPrompt(ctx.bus, { id_hash: "ar1", message: "x", response_requested: true, timeout_seconds: 30, timestamp: new Date(1_000_000).toISOString() });
  // Server clock behind by 3 seconds.
  ctx.bus.emit({ type: "sys_time_update", payload: { serverTime: 997_000 }, source: "test", ts: 0 });
  ctx.setNow(1_005_000);
  ctx.timers.fireAll();
  const tick = ctx.events.find(e => e.payload.changeKind === "tick");
  assert.ok(tick);
  // expires_at = 1_030_000; effective now = 1_005_000 - 3000 = 1_002_000.
  // Remaining = 1_030_000 - 1_002_000 = 28_000.
  assert.equal(tick!.payload.countdownMs, 28_000);
});

// ===========================================================================
// 16-19 : connection state freeze / thaw
// ===========================================================================

test("connection_state_change → backoff: freezes interval + emits offline-frozen", () => {
  const ctx = setup({ now: 1_000_000 });
  emitArPrompt(ctx.bus, { id_hash: "ar1", message: "x", response_requested: true, timeout_seconds: 30, timestamp: new Date(1_000_000).toISOString() });
  ctx.timers.fireAll();                                            // get one tick to populate lastCountdown
  const before = ctx.events.length;
  ctx.bus.emit({ type: "connection_state_change", payload: { state: "backoff", prev: "connected", attempts: 1, transport: "QueueTransport" }, source: "test", ts: 0 });
  assert.equal(ctx.timers.pending(), 0);
  const frozen = ctx.events.slice(before).find(e => e.payload.changeKind === "offline-frozen");
  assert.ok(frozen);
  assert.equal(frozen!.payload.id_hash, "ar1");
  assert.ok(frozen!.payload.countdownMs !== undefined);
});

test("connection_state_change → offline: also freezes (alternative state)", () => {
  const ctx = setup({ now: 1_000_000 });
  emitArPrompt(ctx.bus, { id_hash: "ar1", message: "x", response_requested: true, timeout_seconds: 30, timestamp: new Date(1_000_000).toISOString() });
  ctx.bus.emit({ type: "connection_state_change", payload: { state: "offline", prev: "connected", attempts: 5, transport: "QueueTransport" }, source: "test", ts: 0 });
  assert.equal(ctx.timers.pending(), 0);
});

test("connection_state_change → connected after backoff: thaws + emits offline-resumed", () => {
  const ctx = setup({ now: 1_000_000 });
  emitArPrompt(ctx.bus, { id_hash: "ar1", message: "x", response_requested: true, timeout_seconds: 30, timestamp: new Date(1_000_000).toISOString() });
  ctx.bus.emit({ type: "connection_state_change", payload: { state: "backoff", prev: "connected", attempts: 1, transport: "QueueTransport" }, source: "test", ts: 0 });
  const before = ctx.events.length;
  ctx.bus.emit({ type: "connection_state_change", payload: { state: "connected", prev: "reconnecting", attempts: 0, transport: "QueueTransport" }, source: "test", ts: 0 });
  assert.equal(ctx.timers.pending(), 1, "interval restarted");
  const resumed = ctx.events.slice(before).find(e => e.payload.changeKind === "offline-resumed");
  assert.ok(resumed);
});

test("freeze does not affect already-terminal prompts", async () => {
  const ctx = setup({ now: 1_000_000 });
  emitArPrompt(ctx.bus, { id_hash: "ar1", message: "x", response_requested: true, timeout_seconds: 30 });
  await ctx.store.respond("ar1", "yes");
  const before = ctx.events.length;
  ctx.bus.emit({ type: "connection_state_change", payload: { state: "offline", prev: "connected", attempts: 1, transport: "QueueTransport" }, source: "test", ts: 0 });
  // No offline-frozen for the responded prompt.
  const frozen = ctx.events.slice(before).find(e => e.payload.changeKind === "offline-frozen");
  assert.equal(frozen, undefined);
});

// ===========================================================================
// 20-22 : Multi-prompt independence + edge cases
// ===========================================================================

test("multi-prompt independence: two prompts have separate timers + separate state", () => {
  const ctx = setup({ now: 1_000_000 });
  emitArPrompt(ctx.bus, { id_hash: "ar1", message: "p1", response_requested: true, timeout_seconds: 30, timestamp: new Date(1_000_000).toISOString() });
  emitArPrompt(ctx.bus, { id_hash: "ar2", message: "p2", response_requested: true, timeout_seconds: 60, timestamp: new Date(1_000_000).toISOString() });
  assert.equal(ctx.timers.pending(), 2);
  // Respond ar1 → its interval cleared; ar2's interval untouched.
  ctx.store.respond("ar1", "yes");
  assert.equal(ctx.timers.pending(), 1);
  assert.equal(ctx.store.getById("ar1")!.state, "responded");
  assert.equal(ctx.store.getById("ar2")!.state, "pending");
});

test("malformed timestamp drops the prompt silently (no spawn, no emission)", () => {
  const ctx = setup();
  const before = ctx.events.length;
  emitArPrompt(ctx.bus, { id_hash: "ar1", message: "x", response_requested: true, timeout_seconds: 30, timestamp: "garbage-not-a-date" });
  assert.equal(ctx.store.list().length, 0);
  assert.equal(ctx.events.length, before);
});

test("notification without id_hash + without id is dropped silently", () => {
  const ctx = setup();
  ctx.bus.emit({
    type    : "notification_queue_update",
    payload : { notification: { message: "no id", response_requested: true, timeout_seconds: 10 } },
    source  : "test",
    ts      : 0,
  });
  assert.equal(ctx.store.list().length, 0);
});

test("default response_type=open_ended when not specified", () => {
  const ctx = setup();
  emitArPrompt(ctx.bus, { id_hash: "ar1", message: "x", response_requested: true, timeout_seconds: 30 });
  assert.equal(ctx.store.getById("ar1")!.response_type, "open_ended");
});

test("default timeout_seconds=30 when not specified", () => {
  const ctx = setup({ now: 1_000_000 });
  emitArPrompt(ctx.bus, { id_hash: "ar1", message: "x", response_requested: true, timestamp: new Date(1_000_000).toISOString() });
  assert.equal(ctx.store.getById("ar1")!.expires_at, 1_000_000 + 30_000);
});

// ===========================================================================
// Coverage backfill — defensive guard branches
// ===========================================================================

test("queue_update with no `notification` field is ignored (covers `if (!n) return`)", () => {
  const ctx = setup();
  ctx.bus.emit({
    type    : "notification_queue_update",
    payload : {}, // no `notification` field
    source  : "test",
    ts      : 0,
  });
  assert.equal(ctx.store.list().length, 0);
});

test("notification with no `message` falls back to empty prompt (covers `n.message ?? \"\"`)", () => {
  const ctx = setup();
  emitArPrompt(ctx.bus, { id_hash: "ar1", response_requested: true, timeout_seconds: 30 });
  // No message field → prompt should be "".
  assert.equal(ctx.store.getById("ar1")!.prompt, "");
});

test("notification_responded with only `notification_id` (no `id_hash`) — falls back via `??`", () => {
  const ctx = setup();
  emitArPrompt(ctx.bus, { id_hash: "ar1", message: "q", response_requested: true, timeout_seconds: 30 });
  ctx.bus.emit({
    type    : "notification_responded",
    payload : { notification_id: "ar1" },
    source  : "test",
    ts      : 0,
  });
  assert.equal(ctx.store.getById("ar1")!.state, "cancelled");
});

test("notification_responded with neither id_hash nor notification_id is dropped silently", () => {
  const ctx = setup();
  emitArPrompt(ctx.bus, { id_hash: "ar1", message: "q", response_requested: true, timeout_seconds: 30 });
  ctx.bus.emit({
    type    : "notification_responded",
    payload : {}, // no id_hash, no notification_id
    source  : "test",
    ts      : 0,
  });
  assert.equal(ctx.store.getById("ar1")!.state, "pending", "no transition without an id");
});

test("notification_responded for an entry already in non-pending non-responded state is a no-op", () => {
  const ctx = setup({ now: 1_000_000 });
  emitArPrompt(ctx.bus, {
    id_hash: "ar1", message: "q", response_requested: true,
    timeout_seconds: 1, timestamp: new Date(1_000_000).toISOString(),
  });
  // Auto-expire by advancing the clock past expiry and firing the timer.
  ctx.setNow(1_002_000);
  ctx.timers.fireAll();
  assert.equal(ctx.store.getById("ar1")!.state, "expired");

  // Now the server fanout arrives — should be a no-op (state stays expired).
  ctx.bus.emit({
    type    : "notification_responded",
    payload : { id_hash: "ar1" },
    source  : "test",
    ts      : 0,
  });
  assert.equal(ctx.store.getById("ar1")!.state, "expired");
});

test("sys_time_update with `ts` only (no serverTime) — falls back via `??`", () => {
  const ctx = setup({ now: 1_000_000 });
  emitArPrompt(ctx.bus, {
    id_hash: "ar1", message: "q", response_requested: true,
    timeout_seconds: 60, timestamp: new Date(1_000_000).toISOString(),
  });
  ctx.bus.emit({
    type    : "sys_time_update",
    payload : { ts: 1_010_000 }, // no serverTime
    source  : "test",
    ts      : 0,
  });
  // clockOffset becomes 1_010_000 - 1_000_000 = 10_000. Fire a tick at the
  // same now=1_000_000 — countdown should reflect the offset.
  ctx.timers.fireAll();
  // The countdown emission should be present in events.
  const tickEvents = ctx.events.filter((e) => e.payload.changeKind === "tick");
  assert.ok(tickEvents.length >= 1);
});

test("sys_time_update with non-number serverTime is ignored", () => {
  const ctx = setup();
  emitArPrompt(ctx.bus, { id_hash: "ar1", message: "q", response_requested: true, timeout_seconds: 30 });
  // Emit with a non-number serverTime — should be ignored.
  ctx.bus.emit({
    type    : "sys_time_update",
    payload : { serverTime: "not-a-number" as unknown as number },
    source  : "test",
    ts      : 0,
  });
  // No throw, store unchanged.
  assert.equal(ctx.store.getById("ar1")!.state, "pending");
});

test("freezeAll is idempotent — already-frozen entries are not re-emitted on a second freeze", () => {
  const ctx = setup({ now: 1_000_000 });
  emitArPrompt(ctx.bus, { id_hash: "ar1", message: "q", response_requested: true, timeout_seconds: 30 });

  // First freeze — emits offline-frozen for ar1.
  ctx.bus.emit({ type: "connection_offline", payload: {}, source: "test", ts: 0 });
  const eventsAfterFirst = ctx.events.length;

  // Second freeze (no thaw between) — already frozen, should NOT re-emit.
  ctx.bus.emit({ type: "connection_offline", payload: {}, source: "test", ts: 0 });

  const newOfflineFrozen = ctx.events
    .slice(eventsAfterFirst)
    .filter((e) => e.payload.changeKind === "offline-frozen");
  assert.equal(newOfflineFrozen.length, 0, "second freeze is a no-op for already-frozen entries");
});

test("freezeAll skips terminal entries (responded prompt is not re-emitted as offline-frozen)", () => {
  const ctx = setup({ now: 1_000_000 });
  // Spawn two prompts — pending one + one we'll respond to.
  emitArPrompt(ctx.bus, { id_hash: "ar1", message: "q1", response_requested: true, timeout_seconds: 30 });
  emitArPrompt(ctx.bus, { id_hash: "ar2", message: "q2", response_requested: true, timeout_seconds: 30 });
  // Respond to ar2 → terminal state, but entry stays in entries map until cleanup.
  void ctx.store.respond("ar2", "ok");

  // Capture events from this point only.
  const eventsBefore = ctx.events.length;
  // Trigger freezeAll via connection_offline.
  ctx.bus.emit({ type: "connection_offline", payload: {}, source: "test", ts: 0 });

  // Only ar1 should produce an offline-frozen emission; ar2 is terminal → skipped.
  const newEvents = ctx.events.slice(eventsBefore).filter((e) => e.payload.changeKind === "offline-frozen");
  assert.equal(newEvents.length, 1, "only the pending prompt is frozen");
  assert.equal(newEvents[0]?.payload.id_hash, "ar1");
});

test("thawAll skips terminal entries AND skips already-non-frozen pending entries", () => {
  const ctx = setup({ now: 1_000_000 });
  // ar1: pending + frozen (will be thawed)
  // ar2: pending + NOT frozen (manually unfrozen — covers !entry.frozen continue)
  // ar3: terminal (responded — covers state !== pending continue)
  emitArPrompt(ctx.bus, { id_hash: "ar1", message: "q1", response_requested: true, timeout_seconds: 30 });
  emitArPrompt(ctx.bus, { id_hash: "ar2", message: "q2", response_requested: true, timeout_seconds: 30 });
  emitArPrompt(ctx.bus, { id_hash: "ar3", message: "q3", response_requested: true, timeout_seconds: 30 });
  void ctx.store.respond("ar3", "ok"); // terminal

  // Freeze all (only ar1 + ar2 are pending and will be frozen; ar3 is terminal).
  ctx.bus.emit({ type: "connection_offline", payload: {}, source: "test", ts: 0 });

  // Thaw only ar1: emit "connection_online" then immediately re-freeze ar2 by
  // calling connection_offline again? That doesn't work — events are global.
  // Instead, simulate a partial thaw by responding to ar2 BEFORE thaw, so it
  // becomes terminal — then thaw skips it via the state check, NOT the frozen
  // check. To exercise the !entry.frozen continue branch we need a pending
  // entry that wasn't frozen during freezeAll. The simplest path: spawn a new
  // prompt AFTER freezeAll fired (its frozen=false and pending), then thaw.
  emitArPrompt(ctx.bus, { id_hash: "ar4", message: "q4", response_requested: true, timeout_seconds: 30 });
  // ar4 is now pending + NOT frozen. (freezeAll already fired before it spawned.)

  const eventsBefore = ctx.events.length;
  // Trigger thawAll via connection_online.
  ctx.bus.emit({ type: "connection_online", payload: {}, source: "test", ts: 0 });

  // Resumed events should include ar1 + ar2 (frozen pending), but NOT ar3
  // (terminal — state-check continue) and NOT ar4 (already non-frozen — !frozen continue).
  const resumed = ctx.events.slice(eventsBefore).filter((e) => e.payload.changeKind === "offline-resumed");
  const idsResumed = resumed.map((e) => e.payload.id_hash).sort();
  assert.deepEqual(idsResumed, ["ar1", "ar2"], "only frozen pending entries resume");
});

// ===========================================================================
// Phase 6b — respondAndAwait() (Pass 2 A1) + widened respond() (Pass 2 A2)
// ===========================================================================

test("respondAndAwait() success: emits responded-pending then responded; final state=responded", async () => {
  const ctx = setup();
  emitArPrompt(ctx.bus, { id_hash: "ar1", message: "q", response_requested: true, timeout_seconds: 30 });
  const before = ctx.events.length;
  await ctx.store.respondAndAwait("ar1", "yes");
  const after = ctx.events.slice(before);
  const pending = after.find(e => e.payload.changeKind === "responded-pending");
  const ok      = after.find(e => e.payload.changeKind === "responded");
  assert.ok(pending, "responded-pending emitted");
  assert.ok(ok,      "responded emitted");
  // responded-pending must precede responded.
  assert.ok(after.indexOf(pending!) < after.indexOf(ok!), "responded-pending precedes responded");
  assert.equal(pending!.payload.response, "yes", "pending event carries response payload");
  assert.equal(ok!.payload.response,      "yes", "responded event carries response payload");
  assert.equal(ctx.store.getById("ar1")!.state,    "responded");
  assert.equal(ctx.store.getById("ar1")!.response, "yes");
  assert.equal(ctx.timers.pending(), 0, "interval cleared on submitting transition");
});

test("respondAndAwait() rejection: emits responded-pending then failed; final state=failed; re-throws", async () => {
  const ctx = setup();
  emitArPrompt(ctx.bus, { id_hash: "ar1", message: "q", response_requested: true, timeout_seconds: 30 });
  ctx.setPostRejects(true);
  const before = ctx.events.length;
  let thrown: unknown = null;
  try { await ctx.store.respondAndAwait("ar1", "yes"); } catch (err) { thrown = err; }
  assert.ok(thrown instanceof Error, "respondAndAwait re-throws on POST failure");
  assert.equal((thrown as Error).message, "network down");
  const after = ctx.events.slice(before);
  const pending = after.find(e => e.payload.changeKind === "responded-pending");
  const failed  = after.find(e => e.payload.changeKind === "failed");
  assert.ok(pending, "responded-pending emitted");
  assert.ok(failed,  "failed emitted");
  assert.ok(after.indexOf(pending!) < after.indexOf(failed!), "responded-pending precedes failed");
  assert.equal(failed!.payload.response, "yes",  "failed event carries response payload");
  assert.ok(failed!.payload.error instanceof Error, "failed event carries error");
  assert.equal(ctx.store.getById("ar1")!.state, "failed");
  assert.equal(ctx.store.getById("ar1")!.response, undefined, "response NOT stored on failure");
  assert.equal(ctx.timers.pending(), 0, "interval not restarted after failure");
});

test("respondAndAwait() unknown idHash throws Error", async () => {
  const ctx = setup();
  let thrown: unknown = null;
  try { await ctx.store.respondAndAwait("ghost", "yes"); } catch (err) { thrown = err; }
  assert.ok(thrown instanceof Error);
  assert.match((thrown as Error).message, /Unknown action_required id: ghost/);
  assert.equal(ctx.postCalls.length, 0);
});

test("respondAndAwait() retry after failure: failed → submitting → responded", async () => {
  const ctx = setup();
  emitArPrompt(ctx.bus, { id_hash: "ar1", message: "q", response_requested: true, timeout_seconds: 30 });
  ctx.setPostRejects(true);
  await ctx.store.respondAndAwait("ar1", "yes").catch(() => {});
  assert.equal(ctx.store.getById("ar1")!.state, "failed");
  // Retry — server back online.
  ctx.setPostRejects(false);
  await ctx.store.respondAndAwait("ar1", "yes");
  assert.equal(ctx.store.getById("ar1")!.state, "responded");
  assert.equal(ctx.postCalls.length, 2, "second attempt POSTed");
});

test("respondAndAwait() on already-responded entry throws (cannot re-submit terminal state)", async () => {
  const ctx = setup();
  emitArPrompt(ctx.bus, { id_hash: "ar1", message: "q", response_requested: true, timeout_seconds: 30 });
  await ctx.store.respondAndAwait("ar1", "yes");
  let thrown: unknown = null;
  try { await ctx.store.respondAndAwait("ar1", "no"); } catch (err) { thrown = err; }
  assert.ok(thrown instanceof Error);
  assert.match((thrown as Error).message, /Cannot respondAndAwait in state responded/);
});

test("respondAndAwait() POSTs structured wire shape: notification_id + response_value: { response }", async () => {
  const ctx = setup();
  emitArPrompt(ctx.bus, { id_hash: "ar1", message: "q", response_requested: true, timeout_seconds: 30 });
  await ctx.store.respondAndAwait("ar1", "yes");
  assert.equal(ctx.postCalls.length, 1);
  assert.equal(ctx.postCalls[0]!.path, "/api/notify/response");
  const body = ctx.postCalls[0]!.body as { notification_id: string; response_value: { response: unknown } };
  assert.equal(body.notification_id, "ar1");
  assert.equal(body.response_value.response, "yes");
});

// ---------------------------------------------------------------------------
// Phase 6b A2 — widened response shape (string | array | record)
// ---------------------------------------------------------------------------

test("respond() accepts ReadonlyArray<string> for multi-select response", async () => {
  const ctx = setup();
  emitArPrompt(ctx.bus, { id_hash: "ar1", message: "q", response_requested: true, timeout_seconds: 30 });
  await ctx.store.respond("ar1", ["red", "blue"]);
  assert.deepEqual(ctx.store.getById("ar1")!.response, ["red", "blue"]);
  const body = ctx.postCalls[0]!.body as { response_value: { response: unknown } };
  assert.deepEqual(body.response_value.response, ["red", "blue"]);
});

test("respond() accepts Record<string, string> for open_ended_batch response", async () => {
  const ctx = setup();
  emitArPrompt(ctx.bus, { id_hash: "ar1", message: "q", response_requested: true, timeout_seconds: 30 });
  await ctx.store.respond("ar1", { Topic: "AI", Budget: "100" });
  assert.deepEqual(ctx.store.getById("ar1")!.response, { Topic: "AI", Budget: "100" });
  const body = ctx.postCalls[0]!.body as { response_value: { response: unknown } };
  assert.deepEqual(body.response_value.response, { Topic: "AI", Budget: "100" });
});

test("respond() back-compat: still accepts a plain string response", async () => {
  const ctx = setup();
  emitArPrompt(ctx.bus, { id_hash: "ar1", message: "q", response_requested: true, timeout_seconds: 30 });
  await ctx.store.respond("ar1", "yes");
  assert.equal(ctx.store.getById("ar1")!.response, "yes");
});

test("respondAndAwait() accepts ReadonlyArray<string> + emits payload with array response", async () => {
  const ctx = setup();
  emitArPrompt(ctx.bus, { id_hash: "ar1", message: "q", response_requested: true, timeout_seconds: 30 });
  const before = ctx.events.length;
  await ctx.store.respondAndAwait("ar1", ["A", "B", "C"]);
  const responded = ctx.events.slice(before).find(e => e.payload.changeKind === "responded");
  assert.deepEqual(responded!.payload.response, ["A", "B", "C"]);
  assert.deepEqual(ctx.store.getById("ar1")!.response, ["A", "B", "C"]);
});

test("respondAndAwait() accepts Record<string, string> + emits payload with object response", async () => {
  const ctx = setup();
  emitArPrompt(ctx.bus, { id_hash: "ar1", message: "q", response_requested: true, timeout_seconds: 30 });
  await ctx.store.respondAndAwait("ar1", { q1: "yes", q2: "no" });
  assert.deepEqual(ctx.store.getById("ar1")!.response, { q1: "yes", q2: "no" });
});
