// Multiplexer Lane E WP12 — FleetStatusStore unit tests.
// 100% lines/branches/functions per the multiplexer coverage mandate.

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createFleetStatusStore,
  FLEET_STATE_ENDPOINT,
  FLEET_STATUS_POLL_INTERVAL_MS,
  type FleetApiClient,
} from "../../../lupin_app/static/js/multiplexer/stores/FleetStatusStore";
import type { FleetComposite } from "../../../lupin_app/static/js/multiplexer/render/fleetModel";
import type { StoreFleetStatusChangedPayload } from "../../../lupin_app/static/js/multiplexer/shared/types";

let nowSeq = 3000;
const nowFn = (): number => nowSeq++;

// Drain microtasks + one macrotask so an async refresh fully settles (its
// in-flight guard resets in `finally`) before the next assertion.
const tick = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));

const GOOD: FleetComposite = {
  app_timezone  : "America/New_York",
  fleet_arbiter : { sessions: [{ persona: "A", role: "manager" }] },
};

interface ApiCtx {
  api      : FleetApiClient;
  getCalls : string[];
  setMode  : (m: "good" | "throw401" | "throw500" | "network") => void;
}

function makeApi(): ApiCtx {
  const getCalls: string[] = [];
  let mode: "good" | "throw401" | "throw500" | "network" = "good";
  const api: FleetApiClient = {
    get: async <T,>(path: string): Promise<T> => {
      getCalls.push(path);
      if (mode === "throw401") { const e = new Error("401") as Error & { status: number }; e.status = 401; throw e; }
      if (mode === "throw500") { const e = new Error("500") as Error & { status: number }; e.status = 500; throw e; }
      if (mode === "network") throw new Error("network down"); // no .status
      return GOOD as T;
    },
  };
  return { api, getCalls, setMode: (m) => { mode = m; } };
}

function makeBus(): { bus: ReturnType<typeof createEventBusForTesting>; events: StoreFleetStatusChangedPayload[] } {
  const bus = createEventBusForTesting();
  const events: StoreFleetStatusChangedPayload[] = [];
  bus.on<StoreFleetStatusChangedPayload>("store_fleet_status_changed", (e) => events.push(e.payload));
  return { bus, events };
}

interface TimerCtx {
  setIntervalFn   : (cb: () => void, ms: number) => number;
  clearIntervalFn : (h: number) => void;
  scheduled       : Array<{ cb: () => void; ms: number; handle: number }>;
  cleared         : number[];
  fire            : (handle: number) => void;
}

function makeTimers(): TimerCtx {
  let nextHandle = 1;
  const scheduled: Array<{ cb: () => void; ms: number; handle: number }> = [];
  const cleared: number[] = [];
  return {
    scheduled,
    cleared,
    setIntervalFn: (cb, ms): number => {
      const handle = nextHandle++;
      scheduled.push({ cb, ms, handle });
      return handle;
    },
    clearIntervalFn: (h): void => { cleared.push(h); },
    fire: (handle): void => {
      const entry = scheduled.find((s) => s.handle === handle);
      if (entry) entry.cb();
    },
  };
}

// ---------------------------------------------------------------------------
// Initial state
// ---------------------------------------------------------------------------

test("initial composite is null; showOffline is false", () => {
  const { bus } = makeBus();
  const { api } = makeApi();
  const store = createFleetStatusStore({ bus, api, nowFn });
  assert.equal(store.composite(), null);
  assert.equal(store.showOfflineFlag(), false);
});

// ---------------------------------------------------------------------------
// fetch sentinel mapping via refresh()
// ---------------------------------------------------------------------------

test("refresh: 200 caches the composite + emits stampUpdated=true", async () => {
  const { bus, events } = makeBus();
  const ctx = makeApi();
  const store = createFleetStatusStore({ bus, api: ctx.api, nowFn });
  await store.refresh();
  assert.deepEqual(ctx.getCalls, [FLEET_STATE_ENDPOINT]);
  assert.equal(store.composite(), GOOD);
  assert.deepEqual(events, [{ stampUpdated: true }]);
});

test("refresh: 401 maps to {status:'auth_required'}", async () => {
  const { bus } = makeBus();
  const ctx = makeApi();
  ctx.setMode("throw401");
  const store = createFleetStatusStore({ bus, api: ctx.api, nowFn });
  await store.refresh();
  assert.deepEqual(store.composite(), { status: "auth_required" });
});

test("refresh: non-401 HTTP error maps to {status:'unreachable', fleet_arbiter:null}", async () => {
  const { bus } = makeBus();
  const ctx = makeApi();
  ctx.setMode("throw500");
  const store = createFleetStatusStore({ bus, api: ctx.api, nowFn });
  await store.refresh();
  assert.deepEqual(store.composite(), { status: "unreachable", fleet_arbiter: null });
});

test("refresh: network throw (no .status) maps to unreachable", async () => {
  const { bus } = makeBus();
  const ctx = makeApi();
  ctx.setMode("network");
  const store = createFleetStatusStore({ bus, api: ctx.api, nowFn });
  await store.refresh();
  assert.deepEqual(store.composite(), { status: "unreachable", fleet_arbiter: null });
});

// ---------------------------------------------------------------------------
// debounce
// ---------------------------------------------------------------------------

test("refresh: in-flight guard prevents a concurrent double-fetch", async () => {
  const { bus } = makeBus();
  const getCalls: string[] = [];
  let release!: (v: FleetComposite) => void;
  const api: FleetApiClient = {
    get: <T,>(path: string): Promise<T> => {
      getCalls.push(path);
      return new Promise<T>((resolve) => { release = resolve as unknown as (v: FleetComposite) => void; });
    },
  };
  const store = createFleetStatusStore({ bus, api, nowFn });

  const first  = store.refresh();
  const second = store.refresh(); // should early-return (guard)
  await second;                   // resolves immediately (no fetch)
  assert.equal(getCalls.length, 1, "second refresh must not fetch while first is in flight");

  release(GOOD);
  await first;
  assert.equal(getCalls.length, 1);

  // After settle, a new refresh fetches again (guard reset in finally). Don't
  // await it — the fake `get` stays pending until released; just confirm the
  // guard let it through, then release so no promise dangles.
  const third = store.refresh();
  assert.equal(getCalls.length, 2);
  release(GOOD);
  await third;
});

// ---------------------------------------------------------------------------
// toggleShowOffline
// ---------------------------------------------------------------------------

test("toggleShowOffline: flips the flag + emits stampUpdated=false", () => {
  const { bus, events } = makeBus();
  const { api } = makeApi();
  const store = createFleetStatusStore({ bus, api, nowFn });
  store.toggleShowOffline();
  assert.equal(store.showOfflineFlag(), true);
  assert.deepEqual(events, [{ stampUpdated: false }]);
  store.toggleShowOffline();
  assert.equal(store.showOfflineFlag(), false);
  assert.deepEqual(events, [{ stampUpdated: false }, { stampUpdated: false }]);
});

// ---------------------------------------------------------------------------
// polling
// ---------------------------------------------------------------------------

test("startPolling: immediate refresh + schedules the 60s interval", async () => {
  const { bus } = makeBus();
  const ctx = makeApi();
  const timers = makeTimers();
  const store = createFleetStatusStore({
    bus, api: ctx.api, nowFn,
    setIntervalFn: timers.setIntervalFn, clearIntervalFn: timers.clearIntervalFn,
  });
  store.startPolling();
  await tick(); // let the immediate refresh settle (in-flight guard resets)
  assert.equal(ctx.getCalls.length, 1, "immediate refresh fires");
  assert.equal(timers.scheduled.length, 1);
  assert.equal(timers.scheduled[0]!.ms, FLEET_STATUS_POLL_INTERVAL_MS);

  // Firing the interval triggers another refresh.
  timers.fire(timers.scheduled[0]!.handle);
  await tick();
  assert.equal(ctx.getCalls.length, 2);
});

test("startPolling: idempotent — clears the previous interval before re-scheduling", () => {
  const { bus } = makeBus();
  const ctx = makeApi();
  const timers = makeTimers();
  const store = createFleetStatusStore({
    bus, api: ctx.api, nowFn,
    setIntervalFn: timers.setIntervalFn, clearIntervalFn: timers.clearIntervalFn,
  });
  store.startPolling();
  store.startPolling();
  assert.equal(timers.scheduled.length, 2);
  assert.deepEqual(timers.cleared, [timers.scheduled[0]!.handle]);
});

test("stopPolling: clears an active interval; no-op when inactive", () => {
  const { bus } = makeBus();
  const ctx = makeApi();
  const timers = makeTimers();
  const store = createFleetStatusStore({
    bus, api: ctx.api, nowFn,
    setIntervalFn: timers.setIntervalFn, clearIntervalFn: timers.clearIntervalFn,
  });
  // No-op when nothing scheduled.
  store.stopPolling();
  assert.deepEqual(timers.cleared, []);

  store.startPolling();
  const handle = timers.scheduled[0]!.handle;
  store.stopPolling();
  assert.deepEqual(timers.cleared, [handle]);
  // Second stop is a no-op (handle nulled).
  store.stopPolling();
  assert.deepEqual(timers.cleared, [handle]);
});
