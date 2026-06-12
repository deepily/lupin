// Multiplexer cold-load hydration (2026-06-11) — NotificationStore.hydrateHistory
// unit tests.
// Run via `npx tsx --test src/tests/unit/multiplexer/notification_store_hydrate_history.test.ts`.
//
// Design: src/rnd/v0.1.8/2026.06.11-mux-cold-load-notification-hydration-design.md
// (§2 store seeding, §3 emission contract, §4 dedupe contract, §6 test plan).

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createStorageServiceForTesting, InMemoryStorage } from "../../../lupin_app/static/js/multiplexer/shared/StorageService";
import {
  createNotificationStore,
  computeTodayAnchoredEffectiveHours,
} from "../../../lupin_app/static/js/multiplexer/stores/NotificationStore";
import type { NotificationHistoryApiClient } from "../../../lupin_app/static/js/multiplexer/stores/NotificationStore";
import type { ServerSenderHydrationRecord } from "../../../lupin_app/static/js/multiplexer/stores/SessionStripStore";
import type {
  LupinEvent,
  StoreNotificationsChangedPayload,
} from "../../../lupin_app/static/js/multiplexer/shared/types";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// Fixed "now": 2026-06-11T22:00:00Z (ms epoch). All last_activity fixtures are
// relative to this.
const NOW_MS = Date.parse("2026-06-11T22:00:00Z");

function setupStore() {
  const bus     = createEventBusForTesting();
  const backend = new InMemoryStorage();
  const storage = createStorageServiceForTesting(bus, backend);
  const events: LupinEvent<StoreNotificationsChangedPayload>[] = [];
  bus.on<StoreNotificationsChangedPayload>("store_notifications_changed", (e) => events.push(e));
  const store = createNotificationStore({
    bus,
    storage,
    nowFn          : () => NOW_MS,
    setTimeoutFn   : () => 0,
    clearTimeoutFn : () => {},
  });
  return { bus, store, events, backend };
}

// Programmable api.get stub: maps a sender_id (extracted from the path) to a
// conversation-by-date response or a rejection. Records every requested path.
function makeApiStub(bySender: Record<string, Record<string, unknown[]> | Error>): NotificationHistoryApiClient & { paths: string[] } {
  const paths: string[] = [];
  return {
    paths,
    get<T>(path: string): Promise<T> {
      paths.push(path);
      const m = /conversation-by-date\/([^/]+)\//.exec(path);
      const senderId = m ? decodeURIComponent(m[1] as string) : "";
      const resp = bySender[senderId];
      if (resp instanceof Error) return Promise.reject(resp);
      if (resp === undefined)    return Promise.reject(new Error(`unexpected sender ${senderId}`));
      return Promise.resolve(resp as T);
    },
  };
}

function makeRow(over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id                : "row-1",
    sender_id         : "ext-sender",
    message           : "hello from history",
    title             : null,
    abstract          : null,
    timestamp         : "2026-06-11T21:00:00Z",
    time_display      : null,
    progress_group_id : null,
    ...over,
  };
}

function makeSenderRec(over: Partial<ServerSenderHydrationRecord> = {}): ServerSenderHydrationRecord {
  return {
    sender_id     : "ext-sender",
    last_activity : "2026-06-11T21:00:00Z",
    count         : 1,
    new_count     : 1,
    voice_persona : null,
    ...over,
  };
}

function emitLive(bus: ReturnType<typeof createEventBusForTesting>, fields: Record<string, unknown>): void {
  bus.emit({
    type    : "notification_queue_update",
    payload : { notification: fields },
    source  : "test",
    ts      : 0,
  });
}

const OPTS_BASE = { userEmail: "rick@example.com", effectiveHours: 22 };

// ===========================================================================
// Seeding basics
// ===========================================================================

test("hydrateHistory seeds active list from multi-sender, multi-date responses + emits exactly one hydrated", async () => {
  const { store, events } = setupStore();
  const api = makeApiStub({
    "ext-sender" : {
      "2026-06-11" : [makeRow({ id: "a1", timestamp: "2026-06-11T21:00:00Z" })],
      "2026-06-10" : [makeRow({ id: "a0", timestamp: "2026-06-10T23:30:00Z", message: "older" })],
    },
    "cc-sender"  : {
      "2026-06-11" : [makeRow({ id: "b1", sender_id: "cc-sender", message: "cc msg", timestamp: "2026-06-11T20:00:00Z" })],
    },
  });
  const preEvents = events.length;   // constructor "hydrated" (unread envelope) already fired
  await store.hydrateHistory(api, {
    ...OPTS_BASE,
    senders : [makeSenderRec(), makeSenderRec({ sender_id: "cc-sender", last_activity: "2026-06-11T20:00:00Z" })],
  });

  assert.equal(store.list().length, 3);
  const hydratedAfter = events.slice(preEvents).filter(e => e.payload.changeKind === "hydrated");
  assert.equal(hydratedAfter.length, 1);
  assert.equal(hydratedAfter[0]!.payload.id_hash, undefined);
  // Ascending-ts seed order.
  const tss = store.list().map(n => n.ts);
  assert.deepEqual([...tss].sort((a, b) => a - b), tss);
  assert.ok(store.isHistoryHydrated());
});

test("seeded rows force action_required=false, never set expires_at, survive a sys_time_update sweep", async () => {
  const { bus, store } = setupStore();
  const api = makeApiStub({
    "ext-sender" : { "2026-06-11" : [makeRow({ response_requested: true, response_type: "yes_no" })] },
  });
  await store.hydrateHistory(api, { ...OPTS_BASE, senders: [makeSenderRec()] });
  const n = store.list()[0]!;
  assert.equal(n.action_required, false);
  assert.equal(n.expires_at, undefined);
  // Local expiry sweep must not archive hydrated history.
  bus.emit({ type: "sys_time_update", payload: {}, source: "test", ts: NOW_MS });
  assert.equal(store.list().length, 1);
  assert.equal(store.history().length, 0);
});

test("hydration never bumps unread and never schedules persistence", async () => {
  const { store, backend } = setupStore();
  const api = makeApiStub({
    "ext-sender" : { "2026-06-11" : [makeRow()] },
  });
  await store.hydrateHistory(api, { ...OPTS_BASE, senders: [makeSenderRec()] });
  assert.equal(store.unreadCount(), 0);
  store.flushPersistenceForTesting();   // no pending timer → no write
  assert.equal(backend.getItem("lupin:notifications:unread-count"), null);
});

test("string optionals copy through; DB-null optionals are dropped", async () => {
  const { store } = setupStore();
  const api = makeApiStub({
    "ext-sender" : {
      "2026-06-11" : [
        makeRow({ id: "full", title: "T", abstract: "A", progress_group_id: "pg-1", time_display: "21:00 EDT" }),
        makeRow({ id: "nulls", timestamp: "2026-06-11T21:01:00Z" }),
      ],
    },
  });
  await store.hydrateHistory(api, { ...OPTS_BASE, senders: [makeSenderRec()] });
  const full  = store.list().find(n => n.id_hash === "full")!;
  const nulls = store.list().find(n => n.id_hash === "nulls")!;
  assert.equal(full.title, "T");
  assert.equal(full.abstract, "A");
  assert.equal(full.progress_group_id, "pg-1");
  assert.equal(full.time_display, "21:00 EDT");
  assert.equal(nulls.title, undefined);
  assert.equal(nulls.abstract, undefined);
  assert.equal(nulls.progress_group_id, undefined);
  assert.equal(nulls.time_display, undefined);
});

test("malformed rows are skipped: missing id, missing message, missing/bad timestamp, non-string sender_id falls back to empty", async () => {
  const { store } = setupStore();
  const api = makeApiStub({
    "ext-sender" : {
      "2026-06-11" : [
        makeRow({ id: undefined }),
        makeRow({ id: "no-msg", message: undefined }),
        makeRow({ id: "no-ts", timestamp: undefined }),
        makeRow({ id: "bad-ts", timestamp: "not-a-date" }),
        makeRow({ id: "ok", sender_id: 42 }),
      ],
    },
  });
  await store.hydrateHistory(api, { ...OPTS_BASE, senders: [makeSenderRec()] });
  assert.equal(store.list().length, 1);
  assert.equal(store.list()[0]!.id_hash, "ok");
  assert.equal(store.list()[0]!.sender_id, "");
});

// ===========================================================================
// Window filter + fetch params
// ===========================================================================

test("window filter: stale, missing-last_activity, unparseable-last_activity, and missing-sender_id senders are not fetched", async () => {
  const { store } = setupStore();
  const api = makeApiStub({
    "fresh" : { "2026-06-11" : [makeRow({ id: "f1", sender_id: "fresh" })] },
  });
  await store.hydrateHistory(api, {
    ...OPTS_BASE,
    senders : [
      makeSenderRec({ sender_id: "fresh" }),
      makeSenderRec({ sender_id: "stale", last_activity: "2026-06-09T00:00:00Z" }),
      makeSenderRec({ sender_id: "no-activity", last_activity: undefined }),
      makeSenderRec({ sender_id: "bad-activity", last_activity: "garbage" }),
      makeSenderRec({ sender_id: undefined }),
    ],
  });
  assert.equal(api.paths.length, 1);
  assert.match(api.paths[0]!, /conversation-by-date\/fresh\//);
  assert.equal(store.list().length, 1);
});

test("fetch params mirror classic: hours + anchor=last_activity, URL-encoded sender + email", async () => {
  const { store } = setupStore();
  const api = makeApiStub({
    "claude.code@lupin.deepily.ai#abc" : { "2026-06-11" : [] },
  });
  await store.hydrateHistory(api, {
    ...OPTS_BASE,
    senders : [makeSenderRec({ sender_id: "claude.code@lupin.deepily.ai#abc" })],
  });
  assert.equal(api.paths.length, 1);
  const path = api.paths[0]!;
  assert.ok(path.startsWith("/api/notifications/conversation-by-date/claude.code%40lupin.deepily.ai%23abc/rick%40example.com?"));
  assert.match(path, /hours=22/);
  assert.match(path, /anchor=2026-06-11T21%3A00%3A00Z/);
});

// ===========================================================================
// Dedupe contract — both arrival orders (design §4)
// ===========================================================================

test("live-first wins: a hydrated row whose id already arrived live is skipped", async () => {
  const { bus, store } = setupStore();
  emitLive(bus, { id_hash: "dup-1", message: "live version", sender_id: "ext-sender", timestamp: "2026-06-11T21:00:00Z" });
  assert.equal(store.list().length, 1);
  const api = makeApiStub({
    "ext-sender" : { "2026-06-11" : [makeRow({ id: "dup-1", message: "hydrated version" }), makeRow({ id: "uniq-2", timestamp: "2026-06-11T21:02:00Z" })] },
  });
  await store.hydrateHistory(api, { ...OPTS_BASE, senders: [makeSenderRec()] });
  assert.equal(store.list().length, 2);
  assert.equal(store.list().find(n => n.id_hash === "dup-1")!.message, "live version");
});

test("hydrate-first: a live re-arrival with the same id updates in place — no dupe, no unread bump", async () => {
  const { bus, store, events } = setupStore();
  const api = makeApiStub({
    "ext-sender" : { "2026-06-11" : [makeRow({ id: "dup-2", message: "hydrated version" })] },
  });
  await store.hydrateHistory(api, { ...OPTS_BASE, senders: [makeSenderRec()] });
  const pre = events.length;
  emitLive(bus, { id_hash: "dup-2", message: "live re-arrival", sender_id: "ext-sender", timestamp: "2026-06-11T21:00:05Z" });
  assert.equal(store.list().length, 1);
  assert.equal(store.list()[0]!.message, "live re-arrival");
  assert.equal(store.unreadCount(), 0);
  const updated = events.slice(pre).filter(e => e.payload.changeKind === "updated");
  assert.equal(updated.length, 1);
  assert.equal(updated[0]!.payload.id_hash, "dup-2");
});

// ===========================================================================
// Best-effort batch + idempotency
// ===========================================================================

test("a rejected per-sender fetch is skipped; the rest seed and the single hydrated emission still fires", async () => {
  const { store, events } = setupStore();
  const api = makeApiStub({
    "boom"       : new Error("503"),
    "ext-sender" : { "2026-06-11" : [makeRow()] },
  });
  const pre = events.length;
  await store.hydrateHistory(api, {
    ...OPTS_BASE,
    senders : [makeSenderRec({ sender_id: "boom" }), makeSenderRec()],
  });
  assert.equal(store.list().length, 1);
  assert.equal(events.slice(pre).filter(e => e.payload.changeKind === "hydrated").length, 1);
});

test("second hydrateHistory call is a no-op: no fetches, no emission", async () => {
  const { store, events } = setupStore();
  const api = makeApiStub({
    "ext-sender" : { "2026-06-11" : [makeRow()] },
  });
  await store.hydrateHistory(api, { ...OPTS_BASE, senders: [makeSenderRec()] });
  assert.ok(store.isHistoryHydrated());
  const pre      = events.length;
  const prePaths = api.paths.length;
  await store.hydrateHistory(api, { ...OPTS_BASE, senders: [makeSenderRec()] });
  assert.equal(api.paths.length, prePaths);
  assert.equal(events.length, pre);
});

test("isHistoryHydrated is false before the first hydrateHistory", () => {
  const { store } = setupStore();
  assert.equal(store.isHistoryHydrated(), false);
});

// ===========================================================================
// computeTodayAnchoredEffectiveHours — classic-verbatim 'today' branch
// ===========================================================================

test("computeTodayAnchoredEffectiveHours: floors at 1 at/just-after local midnight, ceils mid-day", () => {
  const atMidnight = new Date(2026, 5, 11, 0, 0, 0).getTime();
  assert.equal(computeTodayAnchoredEffectiveHours(atMidnight), 1);
  const halfPast = new Date(2026, 5, 11, 0, 30, 0).getTime();
  assert.equal(computeTodayAnchoredEffectiveHours(halfPast), 1);
  const midDay = new Date(2026, 5, 11, 13, 30, 0).getTime();
  assert.equal(computeTodayAnchoredEffectiveHours(midDay), 14);
  const exactHour = new Date(2026, 5, 11, 9, 0, 0).getTime();
  assert.equal(computeTodayAnchoredEffectiveHours(exactHour), 9);
});
