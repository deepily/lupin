// Task-list card — TaskListStore unit tests.
// 100% lines/branches/functions per the multiplexer coverage mandate.

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createTaskListStore,
  TASK_LIST_ENDPOINT,
  TASK_LIST_POLL_INTERVAL_MS,
  type TaskListApiClient,
} from "../../../lupin_app/static/js/multiplexer/stores/TaskListStore";
import type { TaskListComposite } from "../../../lupin_app/static/js/multiplexer/render/taskListModel";
import type { StoreTaskListChangedPayload } from "../../../lupin_app/static/js/multiplexer/shared/types";

let nowSeq = 5000;
const nowFn = (): number => nowSeq++;

// Drain microtasks + one macrotask so an async refresh fully settles.
const tick = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));

const GOOD: TaskListComposite = {
  tasks : [{ id: "1", title: "t", status: "in_progress", owner_persona: "amy" }],
  count : 1,
};

interface ApiCtx {
  api      : TaskListApiClient;
  getCalls : string[];
  setMode  : (m: "good" | "throw401" | "throw500" | "network") => void;
}

function makeApi(): ApiCtx {
  const getCalls: string[] = [];
  let mode: "good" | "throw401" | "throw500" | "network" = "good";
  const api: TaskListApiClient = {
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

function makeBus(): { bus: ReturnType<typeof createEventBusForTesting>; events: StoreTaskListChangedPayload[] } {
  const bus = createEventBusForTesting();
  const events: StoreTaskListChangedPayload[] = [];
  bus.on<StoreTaskListChangedPayload>("store_task_list_changed", (e) => events.push(e.payload));
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

// Inject an explicit endpoint so the production-default fallback stays an
// ignored production branch and getCalls is deterministic.
const ENDPOINT = TASK_LIST_ENDPOINT;

// ---------------------------------------------------------------------------
// Initial state
// ---------------------------------------------------------------------------

test("initial composite is null", () => {
  const { bus } = makeBus();
  const { api } = makeApi();
  const store = createTaskListStore({ bus, api, endpoint: ENDPOINT, nowFn });
  assert.equal(store.composite(), null);
});

// ---------------------------------------------------------------------------
// fetch sentinel mapping via refresh()
// ---------------------------------------------------------------------------

test("refresh: 200 caches the composite + emits stampUpdated=true", async () => {
  const { bus, events } = makeBus();
  const ctx = makeApi();
  const store = createTaskListStore({ bus, api: ctx.api, endpoint: ENDPOINT, nowFn });
  await store.refresh();
  assert.deepEqual(ctx.getCalls, [ENDPOINT]);
  assert.equal(store.composite(), GOOD);
  assert.deepEqual(events, [{ stampUpdated: true }]);
});

test("refresh: 401 maps to {status:'auth_required'}", async () => {
  const { bus } = makeBus();
  const ctx = makeApi();
  ctx.setMode("throw401");
  const store = createTaskListStore({ bus, api: ctx.api, endpoint: ENDPOINT, nowFn });
  await store.refresh();
  assert.deepEqual(store.composite(), { status: "auth_required" });
});

test("refresh: non-401 HTTP error maps to {status:'unreachable', tasks:null}", async () => {
  const { bus } = makeBus();
  const ctx = makeApi();
  ctx.setMode("throw500");
  const store = createTaskListStore({ bus, api: ctx.api, endpoint: ENDPOINT, nowFn });
  await store.refresh();
  assert.deepEqual(store.composite(), { status: "unreachable", tasks: null });
});

test("refresh: network throw (no .status) maps to unreachable", async () => {
  const { bus } = makeBus();
  const ctx = makeApi();
  ctx.setMode("network");
  const store = createTaskListStore({ bus, api: ctx.api, endpoint: ENDPOINT, nowFn });
  await store.refresh();
  assert.deepEqual(store.composite(), { status: "unreachable", tasks: null });
});

// ---------------------------------------------------------------------------
// debounce
// ---------------------------------------------------------------------------

test("refresh: in-flight guard prevents a concurrent double-fetch", async () => {
  const { bus } = makeBus();
  const getCalls: string[] = [];
  let release!: (v: TaskListComposite) => void;
  const api: TaskListApiClient = {
    get: <T,>(path: string): Promise<T> => {
      getCalls.push(path);
      return new Promise<T>((resolve) => { release = resolve as unknown as (v: TaskListComposite) => void; });
    },
  };
  const store = createTaskListStore({ bus, api, endpoint: ENDPOINT, nowFn });

  const first  = store.refresh();
  const second = store.refresh(); // should early-return (guard)
  await second;
  assert.equal(getCalls.length, 1, "second refresh must not fetch while first is in flight");

  release(GOOD);
  await first;
  assert.equal(getCalls.length, 1);

  // After settle, a new refresh fetches again (guard reset in finally).
  const third = store.refresh();
  assert.equal(getCalls.length, 2);
  release(GOOD);
  await third;
});

// ---------------------------------------------------------------------------
// polling
// ---------------------------------------------------------------------------

test("startPolling: immediate refresh + schedules the 60s interval", async () => {
  const { bus } = makeBus();
  const ctx = makeApi();
  const timers = makeTimers();
  const store = createTaskListStore({
    bus, api: ctx.api, endpoint: ENDPOINT, nowFn,
    setIntervalFn: timers.setIntervalFn, clearIntervalFn: timers.clearIntervalFn,
  });
  store.startPolling();
  await tick();
  assert.equal(ctx.getCalls.length, 1, "immediate refresh fires");
  assert.equal(timers.scheduled.length, 1);
  assert.equal(timers.scheduled[0]!.ms, TASK_LIST_POLL_INTERVAL_MS);

  timers.fire(timers.scheduled[0]!.handle);
  await tick();
  assert.equal(ctx.getCalls.length, 2);
});

test("startPolling: idempotent — clears the previous interval before re-scheduling", () => {
  const { bus } = makeBus();
  const ctx = makeApi();
  const timers = makeTimers();
  const store = createTaskListStore({
    bus, api: ctx.api, endpoint: ENDPOINT, nowFn,
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
  const store = createTaskListStore({
    bus, api: ctx.api, endpoint: ENDPOINT, nowFn,
    setIntervalFn: timers.setIntervalFn, clearIntervalFn: timers.clearIntervalFn,
  });
  store.stopPolling();
  assert.deepEqual(timers.cleared, []);

  store.startPolling();
  const handle = timers.scheduled[0]!.handle;
  store.stopPolling();
  assert.deepEqual(timers.cleared, [handle]);
  store.stopPolling();
  assert.deepEqual(timers.cleared, [handle]);
});
