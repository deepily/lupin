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
    // Read-path tests never reach these; present only to satisfy the widened
    // TaskListApiClient surface (mutation behaviour is covered via makeMutateApi).
    patch: async <T,>(): Promise<T> => null as T,
    post:  async <T,>(): Promise<T> => null as T,
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
// Unscoped-query guard escape (design 2026.07.07) — the board card is a
// DELIBERATE full-board sweep, so its endpoint MUST carry the guard escape or
// it 400s once the store grows past the threshold. Pin the params + prove the
// page the server returns is cached WITHOUT client-side truncation (rider ii).
//
// ⚠️ SCOPE CORRECTION 2026-07-22. This block used to claim it proved "the
// human's view is never silently truncated". It never could: the store caches
// whatever ARRIVES, so it can only prove THIS LAYER drops nothing. The
// truncation that actually bit us happened UPSTREAM, at the server's 500-row
// cap, and no amount of faithful caching can see it. That gap is now covered
// where it belongs — by the has_more/total banner in the notifications panel.
// ---------------------------------------------------------------------------

test("endpoint carries the unscoped-guard escape params", () => {
  assert.ok(TASK_LIST_ENDPOINT.includes("unscoped_audit=true"), "must pass unscoped_audit=true");
  assert.ok(TASK_LIST_ENDPOINT.includes("limit=500"), "still caps at 500");
  // RE-CUT 2026-07-22 — this line used to assert include_terminal=true on the
  // stated ground that an all-status board kept the human's view "never
  // truncated". It did the opposite: terminal history inflated the result to
  // 1,171 rows against a server limit hard-capped at 500, silently dropping 671
  // — newest-first, so the evicted rows were the OPEN ones the card exists to
  // show. The panel now asks only for work that is still owed.
  assert.ok(!TASK_LIST_ENDPOINT.includes("include_terminal"), "must NOT request terminal rows");
  assert.ok(TASK_LIST_ENDPOINT.includes("hide_parked=false"), "must surface parked rows the server hides by default");
  // mini-plan 02 (2026-07-21): the server also enforces a response BYTE budget,
  // and under its 100k default this poll measured 30 of 1100 available rows. The
  // card's own invariant is that the human's view is never SILENTLY truncated,
  // so the deliberate sweep must name the escape — exactly as it names the
  // unscoped-size escape above.
  assert.ok(TASK_LIST_ENDPOINT.includes("char_budget=0"), "must opt out of the response byte budget");
});

test("refresh: a large board round-trips into the cache with nothing dropped", async () => {
  // What this DOES prove: the store is a faithful cache — a board larger than
  // the guard threshold, spanning many statuses, arrives and is kept entire.
  // What it does NOT prove (see the scope correction above): that the server
  // sent everything. Terminal rows still appear in this fixture on purpose —
  // the store must not editorialize by status even though the endpoint no
  // longer asks for them.
  const statuses = ["queued", "in_progress", "blocked", "done", "dropped"];
  const bigBoard: TaskListComposite = {
    tasks: Array.from({ length: 120 }, (_, i) => ({
      id: String(i), title: `t${i}`, status: statuses[i % statuses.length], owner_persona: "amy",
    })),
    count: 120,
  };
  const { bus } = makeBus();
  const getCalls: string[] = [];
  const api: TaskListApiClient = {
    get: async <T,>(path: string): Promise<T> => { getCalls.push(path); return bigBoard as T; },
    patch: async <T,>(): Promise<T> => null as T,
    post:  async <T,>(): Promise<T> => null as T,
  };
  const store = createTaskListStore({ bus, api, endpoint: ENDPOINT, nowFn });
  await store.refresh();
  assert.deepEqual(getCalls, [ENDPOINT]);                       // fetched via the escape endpoint
  assert.equal(store.composite()?.count, 120);                 // every row kept
  assert.equal(store.composite()?.tasks.length, 120);
  assert.ok(store.composite()?.tasks.some((t) => t.status === "done"));   // terminal rows preserved
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

// ---------------------------------------------------------------------------
// Phase 2 — patchTask / dropTask (optimistic + rollback)
// ---------------------------------------------------------------------------

interface Deferred { resolve: () => void; reject: (e: unknown) => void; }

interface MutCtx {
  api        : TaskListApiClient;
  patchCalls : Array<{ path: string; body: Record<string, unknown> }>;
  postCalls  : Array<{ path: string; body: Record<string, unknown> }>;
  settlePatch: ( ok: boolean, err?: unknown ) => void;
  settlePost : ( ok: boolean, err?: unknown ) => void;
}

// A mutate-api whose patch/post return promises the test settles explicitly, so
// the optimistic edit (synchronous) can be asserted BEFORE the server settles.
function makeMutateApi( seed: TaskListComposite ): MutCtx {
  const patchCalls: MutCtx["patchCalls"] = [];
  const postCalls:  MutCtx["postCalls"]  = [];
  let patchD: Deferred | null = null;
  let postD:  Deferred | null = null;
  const api: TaskListApiClient = {
    get:   async <T,>(): Promise<T> => seed as T,
    patch: <T,>( path: string, body: unknown ): Promise<T> => {
      patchCalls.push({ path, body: body as Record<string, unknown> });
      return new Promise<T>((res, rej) => { patchD = { resolve: () => res(null as T), reject: rej }; });
    },
    post:  <T,>( path: string, body: unknown ): Promise<T> => {
      postCalls.push({ path, body: body as Record<string, unknown> });
      return new Promise<T>((res, rej) => { postD = { resolve: () => res(null as T), reject: rej }; });
    },
  };
  return {
    api, patchCalls, postCalls,
    settlePatch: ( ok, err ) => { if (ok) patchD!.resolve(); else patchD!.reject(err); },
    settlePost:  ( ok, err ) => { if (ok) postD!.resolve();  else postD!.reject(err); },
  };
}

const seedComposite = (): TaskListComposite => ({
  tasks: [
    { id: "t1", title: "one", status: "in_progress", owner_persona: "amy",   priority: "P2" },
    { id: "t2", title: "two", status: "queued",      owner_persona: "bob",   priority: "P1" },
  ],
  count: 2,
});

async function primedStore( mut: MutCtx, actorProvider?: () => string | null ) {
  const { bus, events } = makeBus();
  const store = createTaskListStore({ bus, api: mut.api, endpoint: ENDPOINT, nowFn, actorProvider });
  await store.refresh();          // populate lastComposite from the seed
  events.length = 0;              // drop the refresh event; track mutation emits only
  return { store, events };
}

test("patchTask: optimistic priority edit mutates cache + emits (stampUpdated=false), api.patch body carries actor+authority", async () => {
  const mut = makeMutateApi(seedComposite());
  const { store, events } = await primedStore(mut, () => "rick@x.com");

  const { done } = store.patchTask("t1", { priority: "P0" });

  // Optimistic: cached row updated immediately; a non-stamping repaint emitted.
  assert.equal(store.composite()?.tasks?.[0]?.priority, "P0");
  assert.deepEqual(events, [{ stampUpdated: false }]);
  // Server call shape.
  assert.equal(mut.patchCalls.length, 1);
  assert.equal(mut.patchCalls[0]!.path, "/api/tasks/t1");
  assert.deepEqual(mut.patchCalls[0]!.body, { priority: "P0", actor: "rick@x.com (multiplexer)", authority: "user_direct" });

  mut.settlePatch(true);
  await done;
  // Success → optimistic state stands.
  assert.equal(store.composite()?.tasks?.[0]?.priority, "P0");
});

test("patchTask: owner reassignment edits owner_persona + sends owner body", async () => {
  const mut = makeMutateApi(seedComposite());
  const { store } = await primedStore(mut, () => "rick@x.com");

  store.patchTask("t1", { owner_persona: "carol" });
  assert.equal(store.composite()?.tasks?.[0]?.owner_persona, "carol");
  assert.deepEqual(mut.patchCalls[0]!.body, { owner_persona: "carol", actor: "rick@x.com (multiplexer)", authority: "user_direct" });
});

test("patchTask: default actorProvider → anonymous actor", async () => {
  const mut = makeMutateApi(seedComposite());
  const { store } = await primedStore(mut);   // no actorProvider
  store.patchTask("t1", { priority: "P3" });
  assert.equal(mut.patchCalls[0]!.body.actor, "anonymous (multiplexer)");
});

test("patchTask: restoreState reverts the optimistic edit + re-emits", async () => {
  const mut = makeMutateApi(seedComposite());
  const { store, events } = await primedStore(mut, () => "rick@x.com");

  const { restoreState, done } = store.patchTask("t1", { priority: "P0" });
  assert.equal(store.composite()?.tasks?.[0]?.priority, "P0");

  mut.settlePatch(false, new Error("boom"));
  await done.catch(() => { /* renderer would handle; here we drive rollback manually */ });
  restoreState();

  assert.equal(store.composite()?.tasks?.[0]?.priority, "P2", "reverted to original");
  assert.deepEqual(events, [{ stampUpdated: false }, { stampUpdated: false }]);
});

test("patchTask: unknown id → no-op (no api call, resolved done, inert restoreState)", async () => {
  const mut = makeMutateApi(seedComposite());
  const { store, events } = await primedStore(mut, () => "rick@x.com");

  const { restoreState, done } = store.patchTask("does-not-exist", { priority: "P0" });
  assert.equal(mut.patchCalls.length, 0, "no server call for a cache miss");
  assert.deepEqual(events, [], "no emit");
  assert.doesNotThrow(() => restoreState());
  await done;   // resolved
});

test("patchTask: no cached composite (pre-poll) → no-op", () => {
  const mut = makeMutateApi(seedComposite());
  const { bus } = makeBus();
  const store = createTaskListStore({ bus, api: mut.api, endpoint: ENDPOINT, nowFn, actorProvider: () => "rick@x.com" });
  // No refresh() → lastComposite is null.
  const { done } = store.patchTask("t1", { priority: "P0" });
  assert.equal(mut.patchCalls.length, 0);
  return done;  // resolved
});

test("dropTask: optimistic removal from open view + transition body (to_status/reason/actor/authority)", async () => {
  const mut = makeMutateApi(seedComposite());
  const { store, events } = await primedStore(mut, () => "rick@x.com");

  const { done } = store.dropTask("t1", "superseded");
  // Optimistic: t1 removed from the cached tasks; emit fired.
  assert.deepEqual(store.composite()?.tasks?.map(t => t.id), ["t2"]);
  assert.deepEqual(events, [{ stampUpdated: false }]);
  assert.equal(mut.postCalls.length, 1);
  assert.equal(mut.postCalls[0]!.path, "/api/tasks/t1/transition");
  assert.deepEqual(mut.postCalls[0]!.body, { to_status: "dropped", reason: "superseded", actor: "rick@x.com (multiplexer)", authority: "user_direct" });

  mut.settlePost(true);
  await done;
  assert.deepEqual(store.composite()?.tasks?.map(t => t.id), ["t2"]);
});

test("dropTask: restoreState re-inserts the removed task", async () => {
  const mut = makeMutateApi(seedComposite());
  const { store } = await primedStore(mut, () => "rick@x.com");

  const { restoreState, done } = store.dropTask("t1", "oops");
  assert.deepEqual(store.composite()?.tasks?.map(t => t.id), ["t2"]);

  mut.settlePost(false, new Error("500"));
  await done.catch(() => {});
  restoreState();
  assert.deepEqual(store.composite()?.tasks?.map(t => t.id), ["t1", "t2"]);
});

test("dropTask: unknown id → no-op (no api call)", async () => {
  const mut = makeMutateApi(seedComposite());
  const { store } = await primedStore(mut, () => "rick@x.com");
  const { restoreState, done } = store.dropTask("nope", "reason");
  assert.equal(mut.postCalls.length, 0);
  assert.doesNotThrow(() => restoreState());
  await done;
});

test("dropTask: no cached composite (pre-poll) → no-op", () => {
  const mut = makeMutateApi(seedComposite());
  const { bus } = makeBus();
  const store = createTaskListStore({ bus, api: mut.api, endpoint: ENDPOINT, nowFn, actorProvider: () => "rick@x.com" });
  // No refresh() → lastComposite is null.
  const { done } = store.dropTask("t1", "reason");
  assert.equal(mut.postCalls.length, 0);
  return done;   // resolved
});
