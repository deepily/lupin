// Multiplexer Phase 4 — JobStore unit tests.
// Run via `npx tsx --test src/tests/unit/multiplexer/job_store.test.ts`.
// AC4 floor: ≥ 12 tests per design doc § Verification matrix per-store floor.

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createJobStore,
  type JobHistoryApiClient,
} from "../../../lupin_app/static/js/multiplexer/stores/JobStore";
import type {
  LupinEvent,
  StoreJobsChangedPayload,
} from "../../../lupin_app/static/js/multiplexer/shared/types";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function setup() {
  const bus    = createEventBusForTesting();
  const events: LupinEvent<StoreJobsChangedPayload>[] = [];
  bus.on<StoreJobsChangedPayload>("store_jobs_changed", (e) => events.push(e));
  const store  = createJobStore({ bus, nowFn: () => 1_000_000 });
  return { bus, store, events };
}

function emitTransition(bus: ReturnType<typeof createEventBusForTesting>, fields: {
  job_id     : string;
  from_state ?: string;
  to_state   : string;
  timestamp  ?: string;
  metadata   ?: Record<string, unknown>;
}): void {
  bus.emit({
    type    : "job_state_transition",
    payload : fields,
    source  : "test",
    ts      : 0,
  });
}

function emitRemoved(bus: ReturnType<typeof createEventBusForTesting>, jobId: string): void {
  bus.emit({
    type    : "job_removed",
    payload : { job_id: jobId, queue: "running", timestamp: "2026-05-04T12:00:00Z" },
    source  : "test",
    ts      : 0,
  });
}

// ===========================================================================
// 1-3 : Initial state + basic add path
// ===========================================================================

test("empty store: all 5 buckets empty; getById returns undefined", () => {
  const { store } = setup();
  for (const b of ["todo", "running", "done", "dead", "history"] as const) {
    assert.equal(store.bucket(b).length, 0);
  }
  assert.equal(store.getById("ghost"), undefined);
  assert.equal(store.isHistoryHydrated(), false);
});

test("first-seen job_state_transition: adds to bucket per to_state mapping; emits added", () => {
  const { bus, store, events } = setup();
  emitTransition(bus, { job_id: "j1", to_state: "queued", metadata: { agent_type: "DeepResearchJob" } });
  assert.equal(store.bucket("todo").length, 1);
  assert.equal(store.bucket("todo")[0]!.id_hash, "j1");
  assert.equal(store.bucket("todo")[0]!.status, "todo");
  assert.equal(store.bucket("todo")[0]!.job_type, "DeepResearchJob");
  const added = events.find(e => e.payload.changeKind === "added");
  assert.ok(added);
  assert.equal(added!.payload.id_hash, "j1");
  assert.equal(added!.payload.to, "todo");
});

test("getById finds jobs in any bucket", () => {
  const { bus, store } = setup();
  emitTransition(bus, { job_id: "j-todo", to_state: "queued" });
  emitTransition(bus, { job_id: "j-run", to_state: "running" });
  emitTransition(bus, { job_id: "j-done", to_state: "completed" });
  assert.equal(store.getById("j-todo")?.status, "todo");
  assert.equal(store.getById("j-run")?.status, "running");
  assert.equal(store.getById("j-done")?.status, "done");
});

// ===========================================================================
// 4-7 : Status mapping (server → UI)
// ===========================================================================

test("status mapping: pending/queued/scheduled/paused/stalled all map to todo", () => {
  const states = ["pending", "queued", "scheduled", "paused", "stalled"];
  for (const state of states) {
    const { bus, store } = setup();
    emitTransition(bus, { job_id: `j-${state}`, to_state: state });
    assert.equal(store.bucket("todo").length, 1, `${state} should land in todo`);
    assert.equal(store.bucket("todo")[0]!.status, "todo");
  }
});

test("status mapping: failed/cancelled/interrupted all map to dead", () => {
  const states = ["failed", "cancelled", "interrupted"];
  for (const state of states) {
    const { bus, store } = setup();
    emitTransition(bus, { job_id: `j-${state}`, to_state: state });
    assert.equal(store.bucket("dead").length, 1, `${state} should land in dead`);
    assert.equal(store.bucket("dead")[0]!.status, "dead");
  }
});

test("status mapping: completed → done; running → running", () => {
  const { bus, store } = setup();
  emitTransition(bus, { job_id: "ja", to_state: "completed" });
  emitTransition(bus, { job_id: "jb", to_state: "running" });
  assert.equal(store.bucket("done").length, 1);
  assert.equal(store.bucket("running").length, 1);
});

test("status mapping: unknown server state is dropped silently", () => {
  const { bus, store, events } = setup();
  const before = events.length;
  emitTransition(bus, { job_id: "weird", to_state: "intergalactic" });
  assert.equal(store.bucket("todo").length, 0);
  assert.equal(store.bucket("running").length, 0);
  assert.equal(events.length, before);
});

// ===========================================================================
// 8-9 : Cross-bucket transitions
// ===========================================================================

test("cross-bucket transition: queued → running moves job + emits transitioned with from/to", () => {
  const { bus, store, events } = setup();
  emitTransition(bus, { job_id: "j1", to_state: "queued" });
  const before = events.length;
  emitTransition(bus, { job_id: "j1", from_state: "queued", to_state: "running" });
  assert.equal(store.bucket("todo").length, 0);
  assert.equal(store.bucket("running").length, 1);
  const transitioned = events.slice(before).find(e => e.payload.changeKind === "transitioned");
  assert.ok(transitioned);
  assert.equal(transitioned!.payload.from, "todo");
  assert.equal(transitioned!.payload.to, "running");
});

test("same-bucket transition (pending → queued, both → todo): does NOT move the job", () => {
  const { bus, store, events } = setup();
  emitTransition(bus, { job_id: "j1", to_state: "pending" });
  emitTransition(bus, { job_id: "j1", from_state: "pending", to_state: "queued", metadata: { worker_id: "w7" } });
  // Still in todo; meta updated.
  assert.equal(store.bucket("todo").length, 1);
  const job = store.bucket("todo")[0]!;
  assert.equal(job.meta["worker_id"], "w7");
  // Two events: added + transitioned (same-bucket still emits transitioned).
  const transitioned = events.filter(e => e.payload.changeKind === "transitioned");
  assert.equal(transitioned.length, 1);
});

// ===========================================================================
// 10-12 : job_removed semantics
// ===========================================================================

test("job_removed for done job: removes from done; appends to history", () => {
  const { bus, store, events } = setup();
  emitTransition(bus, { job_id: "j1", to_state: "completed" });
  const before = events.length;
  emitRemoved(bus, "j1");
  assert.equal(store.bucket("done").length, 0);
  assert.equal(store.bucket("history").length, 1);
  assert.equal(store.bucket("history")[0]!.id_hash, "j1");
  assert.equal(store.getById("j1")?.id_hash, "j1");
  const removed = events.slice(before).find(e => e.payload.changeKind === "removed");
  assert.ok(removed);
});

test("job_removed for dead job: also appends to history", () => {
  const { bus, store } = setup();
  emitTransition(bus, { job_id: "jd", to_state: "failed" });
  emitRemoved(bus, "jd");
  assert.equal(store.bucket("dead").length, 0);
  assert.equal(store.bucket("history").length, 1);
});

test("job_removed for todo/running job: removes entirely; does NOT append to history", () => {
  const { bus, store } = setup();
  emitTransition(bus, { job_id: "jt", to_state: "queued" });
  emitTransition(bus, { job_id: "jr", to_state: "running" });
  emitRemoved(bus, "jt");
  emitRemoved(bus, "jr");
  assert.equal(store.bucket("todo").length, 0);
  assert.equal(store.bucket("running").length, 0);
  assert.equal(store.bucket("history").length, 0);
  assert.equal(store.getById("jt"), undefined);
  assert.equal(store.getById("jr"), undefined);
});

test("job_removed for unknown id: silent no-op", () => {
  const { bus, store, events } = setup();
  const before = events.length;
  emitRemoved(bus, "ghost");
  assert.equal(store.bucket("history").length, 0);
  assert.equal(events.length, before);
});

// ===========================================================================
// 13-15 : hydrateHistory (Q7 Option B)
// ===========================================================================

test("hydrateHistory: populates history bucket from API response; emits hydrated", async () => {
  const { bus, store, events } = setup();
  const api: JobHistoryApiClient = {
    get: async (_path: string) => ({
      jobs: [
        { id_hash: "h1", job_type: "DeepResearchJob", status: "completed", created_at: "2026-05-01T10:00:00Z", completed_at: "2026-05-01T10:30:00Z" },
        { id_hash: "h2", job_type: "PodcastGeneratorJob", status: "failed", created_at: "2026-05-02T11:00:00Z" },
      ],
      total: 2,
    }),
  };
  await store.hydrateHistory(api);
  assert.equal(store.bucket("history").length, 2);
  assert.equal(store.isHistoryHydrated(), true);
  const hydrated = events.find(e => e.payload.changeKind === "hydrated");
  assert.ok(hydrated);
  assert.equal(hydrated!.payload.bucket, "history");
});

test("hydrateHistory dedups against in-session history entries", async () => {
  const { bus, store } = setup();
  // In-session: a done job that gets removed → history.
  emitTransition(bus, { job_id: "h1", to_state: "completed" });
  emitRemoved(bus, "h1");
  assert.equal(store.bucket("history").length, 1);

  const api: JobHistoryApiClient = {
    get: async () => ({
      jobs: [
        // Same id_hash as in-session entry — must NOT duplicate.
        { id_hash: "h1", job_type: "X", status: "completed", created_at: "2026-05-01T10:00:00Z" },
        // New entry from server.
        { id_hash: "h2", job_type: "Y", status: "failed", created_at: "2026-05-02T11:00:00Z" },
      ],
    }),
  };
  await store.hydrateHistory(api);
  assert.equal(store.bucket("history").length, 2, "should NOT double-count h1");
});

// W3 — the old once-guard is GONE: a REPLACE (append=false) must refetch on
// every call so window-change + retry actually re-hit the server.
test("hydrateHistory REPLACE refetches on every call (no once-guard) — W3", async () => {
  const { store, events } = setup();
  let callCount = 0;
  const api: JobHistoryApiClient = {
    get: async () => {
      callCount++;
      return { jobs: [] };
    },
  };
  await store.hydrateHistory(api);
  await store.hydrateHistory(api);
  assert.equal(callCount, 2, "REPLACE refetches every call");
  const hydrated = events.filter(e => e.payload.changeKind === "hydrated");
  assert.equal(hydrated.length, 2, "each REPLACE emits a hydrated event");
  // isHistoryHydrated stays a "≥1 hydrate completed" latch.
  assert.equal(store.isHistoryHydrated(), true);
});

test("hydrateHistory default (no opts) calls /api/job-history?days=30&limit=20&offset=0 (NOT /api/queue/...) — W3", async () => {
  // Regression guard for the migration 404 bug: the queues router mounts
  // job-history under the `/api` prefix (matches the legacy client). A call to
  // `/api/queue/job-history` 404s and is silently swallowed by the renderer's
  // .catch(), so nothing else here would surface a wrong URL. Assert it explicitly.
  // W3: the virgin default is the 30-day window, page size 20 (NOT the old 100).
  const { store } = setup();
  const calledPaths: string[] = [];
  const api: JobHistoryApiClient = {
    get: async (path: string) => {
      calledPaths.push(path);
      return { jobs: [] };
    },
  };
  await store.hydrateHistory(api);
  assert.deepEqual(calledPaths, ["/api/job-history?days=30&limit=20&offset=0"]);
  assert.ok(!calledPaths[0].startsWith("/api/queue/"), "must NOT use the /api/queue/ per-item prefix");
});

// ===========================================================================
// W3 — parametrized hydrateHistory: window / pagination / load-more
// ===========================================================================

test("hydrateHistory with explicit days builds days={N}&limit=20&offset=0 — W3", async () => {
  const { store } = setup();
  const calledPaths: string[] = [];
  const api: JobHistoryApiClient = {
    get: async (path: string) => { calledPaths.push(path); return { jobs: [] }; },
  };
  await store.hydrateHistory(api, { days: 7 });
  assert.deepEqual(calledPaths, ["/api/job-history?days=7&limit=20&offset=0"]);
});

test("hydrateHistory with days present-but-undefined ('all') OMITS the days param — W3", async () => {
  const { store } = setup();
  const calledPaths: string[] = [];
  const api: JobHistoryApiClient = {
    get: async (path: string) => { calledPaths.push(path); return { jobs: [] }; },
  };
  // The renderer maps the "all" select option to days:undefined (key present).
  await store.hydrateHistory(api, { days: undefined });
  assert.deepEqual(calledPaths, ["/api/job-history?limit=20&offset=0"]);
});

test("hydrateHistory honors custom limit + offset on a REPLACE — W3", async () => {
  const { store } = setup();
  const calledPaths: string[] = [];
  const api: JobHistoryApiClient = {
    get: async (path: string) => { calledPaths.push(path); return { jobs: [], total: 0 }; },
  };
  await store.hydrateHistory(api, { days: 14, limit: 5, offset: 10 });
  assert.deepEqual(calledPaths, ["/api/job-history?days=14&limit=5&offset=10"]);
});

test("hydrateHistory tracks historyLoadedCount + historyTotalCount from the response — W3", async () => {
  const { store } = setup();
  const api: JobHistoryApiClient = {
    get: async () => ({
      jobs: [
        { id_hash: "p1", status: "completed", created_at: "2026-05-01T10:00:00Z" },
        { id_hash: "p2", status: "failed",    created_at: "2026-05-02T10:00:00Z" },
      ],
      total: 5,
    }),
  };
  await store.hydrateHistory(api, { days: 30, limit: 2 });
  assert.equal(store.historyLoadedCount(), 2, "cursor = offset(0) + fetched(2)");
  assert.equal(store.historyTotalCount(), 5, "total from server");
  assert.equal(store.bucket("history").length, 2);
});

test("hydrateHistory total falls back to the cursor when the server omits total — W3", async () => {
  const { store } = setup();
  const api: JobHistoryApiClient = {
    get: async () => ({ jobs: [ { id_hash: "z1", status: "completed", created_at: "2026-05-01T10:00:00Z" } ] }),
  };
  await store.hydrateHistory(api);
  assert.equal(store.historyLoadedCount(), 1);
  assert.equal(store.historyTotalCount(), 1, "no server total → gate stays closed (loaded === total)");
});

test("hydrateHistory APPEND (load-more) fetches at the tracked cursor + same window, dedups + appends — W3", async () => {
  const { store } = setup();
  const calledPaths: string[] = [];
  const pages: Record<number, ReadonlyArray<Record<string, unknown>>> = {
    0: [ { id_hash: "a1", status: "completed", created_at: "2026-05-01T10:00:00Z" },
         { id_hash: "a2", status: "failed",    created_at: "2026-05-02T10:00:00Z" } ],
    2: [ // page 2 re-includes a2 (overlap) + a new a3 — a2 must NOT double-count
         { id_hash: "a2", status: "failed",    created_at: "2026-05-02T10:00:00Z" },
         { id_hash: "a3", status: "completed", created_at: "2026-05-03T10:00:00Z" } ],
  };
  const api: JobHistoryApiClient = {
    get: async (path: string) => {
      calledPaths.push(path);
      const offset = Number(new URL(path, "http://x").searchParams.get("offset"));
      return { jobs: pages[offset] ?? [], total: 3 };
    },
  };
  // Initial REPLACE with a specific window.
  await store.hydrateHistory(api, { days: 7, limit: 2 });
  assert.equal(store.historyLoadedCount(), 2);
  // Load-more: append the next page at the cursor, staying in the days=7 window.
  await store.hydrateHistory(api, { append: true, limit: 2 });
  assert.deepEqual(calledPaths, [
    "/api/job-history?days=7&limit=2&offset=0",
    "/api/job-history?days=7&limit=2&offset=2",   // same window, cursor offset
  ]);
  // a2 deduped; a3 appended → 3 unique rows.
  assert.deepEqual(store.bucket("history").map(j => j.id_hash), ["a1", "a2", "a3"]);
  // Cursor advances by the RAW page size (2), not the deduped count (1).
  assert.equal(store.historyLoadedCount(), 4);
  assert.equal(store.historyTotalCount(), 3);
});

test("hydrateHistory REPLACE clears the prior window before refetching — W3", async () => {
  const { store } = setup();
  const responses: ReadonlyArray<Record<string, unknown>>[] = [
    [ { id_hash: "old1", status: "completed", created_at: "2026-04-01T10:00:00Z" },
      { id_hash: "old2", status: "failed",    created_at: "2026-04-02T10:00:00Z" } ],
    [ { id_hash: "new1", status: "completed", created_at: "2026-05-01T10:00:00Z" } ],
  ];
  let call = 0;
  const api: JobHistoryApiClient = {
    get: async () => ({ jobs: responses[call++]!, total: responses[call - 1]!.length }),
  };
  await store.hydrateHistory(api, { days: 30 });
  assert.deepEqual(store.bucket("history").map(j => j.id_hash), ["old1", "old2"]);
  // Window-change REPLACE: old rows cleared (+ index entries), new window populated.
  await store.hydrateHistory(api, { days: 1 });
  assert.deepEqual(store.bucket("history").map(j => j.id_hash), ["new1"]);
  assert.equal(store.getById("old1"), undefined, "cleared rows leave indexById too");
  assert.equal(store.historyLoadedCount(), 1);
});

test("hydrateHistory REPLACE does NOT overwrite a still-live done job's bucket mapping — W3", async () => {
  const { bus, store } = setup();
  // A done job is live in the done bucket (not yet removed to history).
  emitTransition(bus, { job_id: "live1", to_state: "completed" });
  assert.equal(store.getById("live1")?.status, "done");
  // Server history returns the SAME id — dedup by indexById.has() must skip it
  // so its done-bucket mapping is preserved (never clobbered to "history").
  const api: JobHistoryApiClient = {
    get: async () => ({ jobs: [ { id_hash: "live1", status: "completed", created_at: "2026-05-01T10:00:00Z" } ], total: 1 }),
  };
  await store.hydrateHistory(api);
  assert.equal(store.bucket("history").length, 0, "live done job not duplicated into history");
  assert.equal(store.getById("live1")?.status, "done");
});

// ===========================================================================
// 16 : Field bookkeeping (started_at on running, completed_at on terminal)
// ===========================================================================

test("transition into running sets started_at; transition into done/dead sets completed_at", () => {
  const { bus, store } = setup();
  emitTransition(bus, { job_id: "j1", to_state: "queued", timestamp: "2026-05-04T12:00:00Z" });
  emitTransition(bus, { job_id: "j1", from_state: "queued", to_state: "running" });
  assert.ok(store.getById("j1")?.started_at !== undefined);

  emitTransition(bus, { job_id: "j1", from_state: "running", to_state: "completed", timestamp: "2026-05-04T12:10:00Z" });
  const j = store.getById("j1")!;
  assert.ok(j.completed_at !== undefined);
  // completed_at populated from transition timestamp.
  assert.equal(j.completed_at, Date.parse("2026-05-04T12:10:00Z"));
});

test("transition without to_state or job_id is silently dropped", () => {
  const { bus, store, events } = setup();
  const before = events.length;
  bus.emit({ type: "job_state_transition", payload: { from_state: "queued" }, source: "test", ts: 0 });
  bus.emit({ type: "job_state_transition", payload: { job_id: "j1" }, source: "test", ts: 0 });
  assert.equal(store.bucket("todo").length, 0);
  assert.equal(events.length, before);
});

// ===========================================================================
// W2 — clearBucket (bulk delete-all local clear) + historyWindowDays getter
// ===========================================================================

test("clearBucket: empties the bucket + clears indexById + emits removed{bucket}; other buckets untouched", () => {
  const { bus, store, events } = setup();
  emitTransition(bus, { job_id: "a", to_state: "running" });
  emitTransition(bus, { job_id: "b", to_state: "running" });
  emitTransition(bus, { job_id: "c", to_state: "pending" });   // todo — must survive
  assert.equal(store.bucket("running").length, 2);

  events.length = 0;
  store.clearBucket("running");

  assert.equal(store.bucket("running").length, 0, "running bucket emptied");
  assert.equal(store.getById("a"), undefined, "indexById entry a cleared");
  assert.equal(store.getById("b"), undefined, "indexById entry b cleared");
  assert.equal(store.bucket("todo").length, 1, "unrelated bucket untouched");
  assert.equal(events.length, 1, "exactly one change event");
  assert.equal(events[0]!.payload.changeKind, "removed");
  assert.equal(events[0]!.payload.bucket, "running");
});

test("clearBucket: on an already-empty bucket still emits removed{bucket} (unconditional re-render contract)", () => {
  const { store, events } = setup();
  events.length = 0;
  store.clearBucket("dead");
  assert.equal(store.bucket("dead").length, 0);
  assert.equal(events.length, 1);
  assert.equal(events[0]!.payload.changeKind, "removed");
  assert.equal(events[0]!.payload.bucket, "dead");
});

test("historyWindowDays: defaults to 30 (legacy virgin window) before any hydrate", () => {
  const { store } = setup();
  assert.equal(store.historyWindowDays(), 30);
});

test("historyWindowDays: reflects a custom hydrated window; undefined after an all-time hydrate", async () => {
  const { store } = setup();
  const api: JobHistoryApiClient = {
    get: async <T>(): Promise<T> => ({ jobs: [], total: 0 } as unknown as T),
  };
  await store.hydrateHistory(api, { days: 7, append: false });
  assert.equal(store.historyWindowDays(), 7);
  await store.hydrateHistory(api, { days: undefined, append: false });   // all-time → omit days
  assert.equal(store.historyWindowDays(), undefined);
});
