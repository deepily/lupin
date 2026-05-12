// Multiplexer Phase 6b — JobStore.delete() public API tests (AC2d).
// Run via `npx tsx --test src/tests/unit/multiplexer/jobstore_delete_api.test.ts`.
//
// Covers Phase 5A's 8-row DOD per
// `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/2026.05.11-phase6b-code-execution-plan.md`:
//
// | 5A-1 | Method exists on JobStore.prototype       |
// | 5A-2 | Method removes entry on hit              |
// | 5A-3 | Method emits store_jobs_changed removed  |
// | 5A-4 | restoreState() re-inserts identical state|
// | 5A-5 | restoreState() emits changeKind="added"  |
// | 5A-6 | Nonexistent idHash → no-op everywhere    |
// | 5A-7 | c8 100% on delete() + closure (run via c8)|
// | 5A-8 | This file exists + passes                 |

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../fastapi_app/static/js/multiplexer/shared/EventBus";
import { createJobStore } from "../../../fastapi_app/static/js/multiplexer/stores/JobStore";
import type {
  LupinEvent,
  StoreJobsChangedPayload,
} from "../../../fastapi_app/static/js/multiplexer/shared/types";

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

function seedRunningJob(
  bus: ReturnType<typeof createEventBusForTesting>,
  jobId: string,
  agentType: string = "math_agent",
): void {
  bus.emit({
    type    : "job_state_transition",
    payload : {
      job_id     : jobId,
      to_state   : "running",
      timestamp  : "2026-05-12T12:00:00Z",
      metadata   : { agent_type: agentType },
    },
    source  : "test",
    ts      : 0,
  });
}

function seedTodoJob(
  bus: ReturnType<typeof createEventBusForTesting>,
  jobId: string,
): void {
  bus.emit({
    type    : "job_state_transition",
    payload : {
      job_id    : jobId,
      to_state  : "queued",
      timestamp : "2026-05-12T11:00:00Z",
      metadata  : { agent_type: "calendar_agent" },
    },
    source  : "test",
    ts      : 0,
  });
}

// ---------------------------------------------------------------------------
// 5A-1 — Method exists on JobStore.prototype
// ---------------------------------------------------------------------------

test("delete() — method exists on JobStore instance (5A-1)", () => {
  const { store } = setup();
  assert.equal(typeof store.delete, "function");
});

// ---------------------------------------------------------------------------
// 5A-2 — Method removes entry on hit
// ---------------------------------------------------------------------------

test("delete() — removes entry on hit; getById returns undefined (5A-2)", () => {
  const { bus, store } = setup();
  seedRunningJob(bus, "job-a");
  assert.notEqual(store.getById("job-a"), undefined);
  assert.equal(store.bucket("running").length, 1);

  store.delete("job-a");

  assert.equal(store.getById("job-a"), undefined);
  assert.equal(store.bucket("running").length, 0);
});

// ---------------------------------------------------------------------------
// 5A-3 — Method emits store_jobs_changed with changeKind="removed"
// ---------------------------------------------------------------------------

test("delete() — emits store_jobs_changed{changeKind:'removed', id_hash} (5A-3)", () => {
  const { bus, store, events } = setup();
  seedRunningJob(bus, "job-b");
  const before = events.length;

  store.delete("job-b");

  const delta = events.slice(before);
  assert.equal(delta.length, 1);
  assert.equal(delta[0]!.type, "store_jobs_changed");
  assert.equal(delta[0]!.payload.changeKind, "removed");
  assert.equal(delta[0]!.payload.id_hash, "job-b");
  assert.equal(delta[0]!.source, "JobStore");
});

// ---------------------------------------------------------------------------
// 5A-4 — restoreState() re-inserts identical previous state
// ---------------------------------------------------------------------------

test("delete() — restoreState() re-inserts identical previous state (5A-4)", () => {
  const { bus, store } = setup();
  seedRunningJob(bus, "job-c", "math_agent");
  const before = store.getById("job-c");
  assert.notEqual(before, undefined);

  const { restoreState } = store.delete("job-c");
  assert.equal(store.getById("job-c"), undefined);

  restoreState();

  const after = store.getById("job-c");
  assert.deepEqual(after, before);
  assert.equal(store.bucket("running").length, 1);
});

test("delete() — restoreState() preserves original index within bucket (5A-4)", () => {
  const { bus, store } = setup();
  seedRunningJob(bus, "job-x");  // index 0
  seedRunningJob(bus, "job-y");  // index 1
  seedRunningJob(bus, "job-z");  // index 2

  const { restoreState } = store.delete("job-y");
  assert.deepEqual(
    store.bucket("running").map(j => j.id_hash),
    ["job-x", "job-z"],
  );

  restoreState();
  assert.deepEqual(
    store.bucket("running").map(j => j.id_hash),
    ["job-x", "job-y", "job-z"],
  );
});

// ---------------------------------------------------------------------------
// 5A-5 — restoreState() emits changeKind="added"
// ---------------------------------------------------------------------------

test("delete() — restoreState() emits store_jobs_changed{changeKind:'added', to: bucket} (5A-5)", () => {
  const { bus, store, events } = setup();
  seedRunningJob(bus, "job-d");
  const { restoreState } = store.delete("job-d");
  const before = events.length;

  restoreState();

  const delta = events.slice(before);
  assert.equal(delta.length, 1);
  assert.equal(delta[0]!.type, "store_jobs_changed");
  assert.equal(delta[0]!.payload.changeKind, "added");
  assert.equal(delta[0]!.payload.id_hash, "job-d");
  assert.equal(delta[0]!.payload.to, "running");
  assert.equal(delta[0]!.source, "JobStore");
});

test("delete() — restoreState() emits 'added' with bucket=todo for non-running jobs (5A-5)", () => {
  const { bus, store, events } = setup();
  seedTodoJob(bus, "job-e");
  const { restoreState } = store.delete("job-e");
  const before = events.length;

  restoreState();

  const delta = events.slice(before);
  assert.equal(delta.length, 1);
  assert.equal(delta[0]!.payload.changeKind, "added");
  assert.equal(delta[0]!.payload.to, "todo");
});

// ---------------------------------------------------------------------------
// 5A-6 — Nonexistent idHash → no-op + no-op restoreState
// ---------------------------------------------------------------------------

test("delete() — nonexistent idHash returns no-op closure; no exception (5A-6)", () => {
  const { store } = setup();
  const result = store.delete("does-not-exist");
  assert.equal(typeof result.restoreState, "function");
  // Calling no-op restoreState must not throw.
  assert.doesNotThrow(() => result.restoreState());
});

test("delete() — nonexistent idHash emits ZERO events (delete + restoreState) (5A-6)", () => {
  const { store, events } = setup();
  const before = events.length;

  const { restoreState } = store.delete("never-seen");
  restoreState();

  assert.equal(events.length, before);
});

// ---------------------------------------------------------------------------
// Cross-cutting / boundary cases
// ---------------------------------------------------------------------------

test("delete() — round-trip leaves indexById in consistent state (cross-cutting)", () => {
  const { bus, store } = setup();
  seedRunningJob(bus, "job-f");
  const { restoreState } = store.delete("job-f");
  restoreState();

  // After round-trip the job is back; a subsequent delete must still work
  // (i.e., indexById was correctly re-set).
  const second = store.delete("job-f");
  assert.equal(store.getById("job-f"), undefined);
  second.restoreState();
  assert.notEqual(store.getById("job-f"), undefined);
});

test("delete() — deleting from done bucket also routes restoreState back to done", () => {
  const { bus, store } = setup();
  seedRunningJob(bus, "job-g");
  // Move to done.
  bus.emit({
    type    : "job_state_transition",
    payload : {
      job_id    : "job-g",
      to_state  : "completed",
      timestamp : "2026-05-12T12:01:00Z",
    },
    source  : "test",
    ts      : 0,
  });
  assert.equal(store.bucket("done").length, 1);

  const { restoreState } = store.delete("job-g");
  assert.equal(store.bucket("done").length, 0);

  restoreState();
  assert.equal(store.bucket("done").length, 1);
  assert.equal(store.getById("job-g")!.status, "done");
});
