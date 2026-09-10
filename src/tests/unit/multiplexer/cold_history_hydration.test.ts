// P0 5ebd2aff (2026-09-10) — cold-load notification-history runner.
// Run via `npx tsx --test src/tests/unit/multiplexer/cold_history_hydration.test.ts`.
//
// The runner replaced boot.ts's inline senders-visible fetch, which used the
// 10 s ApiClient default and swallowed the abort. These pin: the long timeout
// reaches EVERY request, a failure is reported rather than swallowed, and the
// pane's Retry re-runs it.

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  COLD_HYDRATION_TIMEOUT_MS,
  HISTORY_RETRY_EVENT,
  createColdHistoryHydration,
  type ColdHydrationApiLike,
} from "../../../lupin_app/static/js/multiplexer/stores/coldHistoryHydration";
import type { ServerSenderHydrationRecord } from "../../../lupin_app/static/js/multiplexer/stores/SessionStripStore";
import type { HydrateHistoryOptions, NotificationHistoryApiClient } from "../../../lupin_app/static/js/multiplexer/stores/NotificationStore";

interface Call { path: string; timeoutMs: number | undefined }

function fakeApi(respond: (path: string) => Promise<unknown>): ColdHydrationApiLike & { calls: Call[] } {
  const calls: Call[] = [];
  return {
    calls,
    get<T>(path: string, opts?: { timeoutMs?: number }): Promise<T> {
      calls.push({ path, timeoutMs: opts?.timeoutMs });
      return respond(path) as Promise<T>;
    },
  };
}

function fakeStores(opts: { historyThrows?: boolean; hydrated?: boolean } = {}) {
  const log: string[] = [];
  let hydrated = opts.hydrated ?? false;
  let historyApi: NotificationHistoryApiClient | null = null;
  let historyOpts: HydrateHistoryOptions | null = null;
  const stores = {
    sessionStrip  : { hydrate: (r: ReadonlyArray<ServerSenderHydrationRecord>) => { log.push(`strip:${r.length}`); } },
    senders       : { hydrate: (r: ReadonlyArray<ServerSenderHydrationRecord>) => { log.push(`senders:${r.length}`); } },
    notifications : {
      hydrateHistory: async (api: NotificationHistoryApiClient, o: HydrateHistoryOptions) => {
        historyApi = api; historyOpts = o; log.push("history");
        if (opts.historyThrows) throw new Error("history exploded");
        hydrated = true;
      },
      isHistoryHydrated           : () => hydrated,
      markHistoryHydrationLoading : () => { log.push("loading"); },
      markHistoryHydrationFailed  : (reason: string) => { log.push(`failed:${reason}`); },
      resetHistoryHydration       : () => { log.push("reset"); hydrated = false; },
    },
  };
  return { stores, log, getHistoryApi: () => historyApi, getHistoryOpts: () => historyOpts };
}

const REC: ServerSenderHydrationRecord = { sender_id: "a", last_activity: "2026-09-10T14:00:00Z", count: 1, new_count: 0, voice_persona: null };

test("run: loading → senders-visible with the LONG timeout → strip, senders, history in order", async () => {
  const bus = createEventBusForTesting();
  const api = fakeApi(async () => [REC]);
  const f   = fakeStores();
  const r   = createColdHistoryHydration({ bus, api, stores: f.stores, getEmail: () => "rick@example.com", getEffectiveHours: () => 48 });
  await r.run();
  assert.deepEqual(f.log, ["loading", "strip:1", "senders:1", "history"]);
  assert.equal(api.calls.length, 1);
  assert.equal(api.calls[0]!.path, "/api/notifications/senders-visible/rick%40example.com");
  assert.equal(api.calls[0]!.timeoutMs, COLD_HYDRATION_TIMEOUT_MS);
  assert.ok(COLD_HYDRATION_TIMEOUT_MS > 52_800, "must outlast the measured 52.8 s senders-visible");
  assert.equal(f.getHistoryOpts()!.effectiveHours, 48);
  assert.equal(f.getHistoryOpts()!.userEmail, "rick@example.com");
});

test("run: the per-sender history requests ALSO carry the long timeout", async () => {
  const bus = createEventBusForTesting();
  const api = fakeApi(async () => [REC]);
  const f   = fakeStores();
  const r   = createColdHistoryHydration({ bus, api, stores: f.stores, getEmail: () => "rick@example.com", getEffectiveHours: () => 48, timeoutMs: 7_777 });
  await r.run();
  await f.getHistoryApi()!.get("/api/notifications/conversation-by-date/a/rick%40example.com?hours=48");
  assert.deepEqual(api.calls.map(c => c.timeoutMs), [7_777, 7_777]);
});

test("run: a rejected senders-visible is REPORTED as failed with its message, and run never rejects", async () => {
  const bus = createEventBusForTesting();
  const api = fakeApi(() => Promise.reject(new Error("request to /api/notifications/senders-visible timed out after 120000ms")));
  const f   = fakeStores();
  const r   = createColdHistoryHydration({ bus, api, stores: f.stores, getEmail: () => "rick@example.com", getEffectiveHours: () => 48 });
  await r.run();
  assert.deepEqual(f.log, ["loading", "failed:request to /api/notifications/senders-visible timed out after 120000ms"]);
});

test("run: a throw from hydrateHistory is also reported, not swallowed", async () => {
  const bus = createEventBusForTesting();
  const f   = fakeStores({ historyThrows: true });
  const r   = createColdHistoryHydration({ bus, api: fakeApi(async () => [REC]), stores: f.stores, getEmail: () => "rick@example.com", getEffectiveHours: () => 48 });
  await r.run();
  assert.equal(f.log.at(-1), "failed:history exploded");
});

test("run: no email yet → nothing fetched and the state stays idle (no loading claim)", async () => {
  const bus = createEventBusForTesting();
  const api = fakeApi(async () => [REC]);
  const f   = fakeStores();
  await createColdHistoryHydration({ bus, api, stores: f.stores, getEmail: () => null, getEffectiveHours: () => 48 }).run();
  await createColdHistoryHydration({ bus, api, stores: f.stores, getEmail: () => "", getEffectiveHours: () => 48 }).run();
  assert.equal(api.calls.length, 0);
  assert.deepEqual(f.log, []);
});

test("run: already hydrated → no-op", async () => {
  const bus = createEventBusForTesting();
  const api = fakeApi(async () => [REC]);
  const f   = fakeStores({ hydrated: true });
  await createColdHistoryHydration({ bus, api, stores: f.stores, getEmail: () => "rick@example.com", getEffectiveHours: () => 48 }).run();
  assert.equal(api.calls.length, 0);
});

test("run: a second run while the first is in flight does not fetch twice", async () => {
  const bus = createEventBusForTesting();
  let release: (v: unknown) => void = () => {};
  const api = fakeApi(() => new Promise(res => { release = res; }));
  const f   = fakeStores();
  const r   = createColdHistoryHydration({ bus, api, stores: f.stores, getEmail: () => "rick@example.com", getEffectiveHours: () => 48 });
  const first = r.run();
  await r.run();
  release([REC]);
  await first;
  assert.equal(api.calls.length, 1);
});

test("the pane's retry event re-runs after a failure; dispose detaches it", async () => {
  const bus = createEventBusForTesting();
  let fail = true;
  const api = fakeApi(() => fail ? Promise.reject(new Error("down")) : Promise.resolve([REC]));
  const f   = fakeStores();
  const r   = createColdHistoryHydration({ bus, api, stores: f.stores, getEmail: () => "rick@example.com", getEffectiveHours: () => 48 });
  await r.run();
  assert.equal(f.log.at(-1), "failed:down");

  fail = false;
  bus.emit({ type: HISTORY_RETRY_EVENT, payload: {}, source: "test", ts: 0 });
  await new Promise(res => setTimeout(res, 0));
  await new Promise(res => setTimeout(res, 0));
  assert.equal(f.log.at(-1), "history");
  assert.equal(api.calls.length, 2);

  r.dispose();
  bus.emit({ type: HISTORY_RETRY_EVENT, payload: {}, source: "test", ts: 0 });
  await new Promise(res => setTimeout(res, 0));
  assert.equal(api.calls.length, 2);
});

// Rick's ruling 1 (2026-09-10) — the history-window picker reloads, like legacy setHistoryWindow.

const flush = () => new Promise(res => setTimeout(res, 0));
const windowChanged = { type: "store_notifications_changed" as const, payload: { changeKind: "history_window" }, source: "test", ts: 0 };

test("a window change drops the loaded history and runs again with the NEW hours", async () => {
  const bus = createEventBusForTesting();
  const api = fakeApi(async () => [REC]);
  const f   = fakeStores();
  let hours: number | null = 48;
  const r   = createColdHistoryHydration({ bus, api, stores: f.stores, getEmail: () => "rick@example.com", getEffectiveHours: () => hours });
  await r.run();
  hours = null;
  bus.emit(windowChanged);
  await flush();
  await flush();
  assert.deepEqual(f.log, ["loading", "strip:1", "senders:1", "history", "reset", "loading", "strip:1", "senders:1", "history"]);
  assert.equal(f.getHistoryOpts()!.effectiveHours, null, "All time reaches hydrateHistory as null");
  assert.equal(api.calls.length, 2);

  r.dispose();
  bus.emit(windowChanged);
  await flush();
  assert.equal(api.calls.length, 2, "dispose detaches the window listener too");
});

test("other notification-store changes do not reload", async () => {
  const bus = createEventBusForTesting();
  const api = fakeApi(async () => [REC]);
  const f   = fakeStores();
  const r   = createColdHistoryHydration({ bus, api, stores: f.stores, getEmail: () => "rick@example.com", getEffectiveHours: () => 48 });
  await r.run();
  bus.emit({ type: "store_notifications_changed", payload: { changeKind: "hydrated" }, source: "test", ts: 0 });
  await flush();
  assert.equal(api.calls.length, 1);
  assert.ok(!f.log.includes("reset"));
  r.dispose();
});

test("a window change mid-run drops nothing now, then reloads exactly once after the run", async () => {
  const bus = createEventBusForTesting();
  const releases: Array<(v: unknown) => void> = [];
  const api = fakeApi(() => new Promise(res => { releases.push(res); }));
  const f   = fakeStores();
  const r   = createColdHistoryHydration({ bus, api, stores: f.stores, getEmail: () => "rick@example.com", getEffectiveHours: () => 48 });
  const first = r.run();
  await r.reload();
  await r.reload();
  assert.equal(api.calls.length, 1, "no second senders-visible while the first is in flight");
  assert.ok(!f.log.includes("reset"), "nothing dropped mid-run");

  releases[0]!([REC]);
  await first;
  await flush();
  assert.equal(api.calls.length, 2, "one reload after the run");
  assert.equal(f.log.filter(line => line === "reset").length, 1, "two requests, one reload");

  releases[1]!([REC]);
  await flush();
  assert.equal(f.log.at(-1), "history");
  r.dispose();
});
