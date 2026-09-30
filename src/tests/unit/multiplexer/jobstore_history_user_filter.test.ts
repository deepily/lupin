// Row 83c3ff74 — JobStore carries the Mine / Not Mine / All Users filter to /api/job-history.
// Run via `npx tsx --test src/tests/unit/multiplexer/jobstore_history_user_filter.test.ts`.
//
// The filter is chosen by whoever asks for a REPLACE (the jobs pane). The store's job is to send
// it, and to keep sending the SAME one on a load-more — a second page in a different filter
// would stitch two users' histories into one list.

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createJobStore, type JobHistoryApiClient } from "../../../lupin_app/static/js/multiplexer/stores/JobStore";

function row(id: string) {
  return { id_hash: id, job_type: "claude_code", status: "completed", created_at: "2026-09-10T20:00:00Z" };
}

function setup() {
  const bus   = createEventBusForTesting();
  const store = createJobStore({ bus, nowFn: () => 1_000_000 });
  const paths : string[] = [];
  const api   : JobHistoryApiClient = {
    get: async <T>(path: string): Promise<T> => {
      paths.push(path);
      const offset = Number(new URL(path, "http://x").searchParams.get("offset"));
      return { jobs: offset === 0 ? [ row("a"), row("b") ] : [ row("c") ], total: 3 } as T;
    },
  };
  const param = (i: number): string | null => new URL(paths[ i ]!, "http://x").searchParams.get("user_filter");
  return { store, api, paths, param };
}

test("a REPLACE sends the filter it was given, decoded exactly", async () => {
  for (const filter of [ "rick_6bdc", "!self", "*" ]) {
    const s = setup();
    await s.store.hydrateHistory(s.api, { userFilter: filter });
    assert.equal(s.param(0), filter);
  }
});

test("no filter means no user_filter param, and the request is byte-identical to before", async () => {
  const s = setup();
  await s.store.hydrateHistory(s.api);
  await s.store.hydrateHistory(s.api, { days: 7, userFilter: undefined });
  assert.equal(s.paths[ 0 ], "/api/job-history?days=30&limit=20&offset=0");
  assert.equal(s.paths[ 1 ], "/api/job-history?days=7&limit=20&offset=0");
});

test("a load-more keeps the filter of the page before it, even when the caller passes another", async () => {
  const s = setup();
  await s.store.hydrateHistory(s.api, { userFilter: "!self", limit: 2 });
  await s.store.hydrateHistory(s.api, { append: true, limit: 2, userFilter: "*" });
  assert.equal(s.param(1), "!self");
  assert.equal(s.store.bucket("history").length, 3);
});

test("a new REPLACE replaces the recorded filter, so the next load-more follows it", async () => {
  const s = setup();
  await s.store.hydrateHistory(s.api, { userFilter: "!self", limit: 2 });
  await s.store.hydrateHistory(s.api, { userFilter: "rick_6bdc", limit: 2 });
  await s.store.hydrateHistory(s.api, { append: true, limit: 2 });
  assert.equal(s.param(2), "rick_6bdc");
});
