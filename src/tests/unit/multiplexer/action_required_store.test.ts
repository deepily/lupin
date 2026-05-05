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
