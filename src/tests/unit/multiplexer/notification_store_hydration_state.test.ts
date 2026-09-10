// P0 5ebd2aff (2026-09-10) — NotificationStore cold-load hydration STATE.
// Run via `npx tsx --test src/tests/unit/multiplexer/notification_store_hydration_state.test.ts`.
//
// Why these exist: senders-visible measured 52.8 s for Rick against a 10 s
// client timeout, and the multiplexer painted "No notifications yet." over a
// fetch it had abandoned. The store now says loading / done / failed so the
// pane can tell the difference between an empty inbox and nothing measured.

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createStorageServiceForTesting, InMemoryStorage } from "../../../lupin_app/static/js/multiplexer/shared/StorageService";
import { createNotificationStore } from "../../../lupin_app/static/js/multiplexer/stores/NotificationStore";
import type { NotificationHistoryApiClient } from "../../../lupin_app/static/js/multiplexer/stores/NotificationStore";
import type { ServerSenderHydrationRecord } from "../../../lupin_app/static/js/multiplexer/stores/SessionStripStore";
import type { LupinEvent, StoreNotificationsChangedPayload } from "../../../lupin_app/static/js/multiplexer/shared/types";

const NOW_MS = Date.parse("2026-09-10T15:00:00Z");

function setupStore() {
  const bus     = createEventBusForTesting();
  const storage = createStorageServiceForTesting(bus, new InMemoryStorage());
  const events: LupinEvent<StoreNotificationsChangedPayload>[] = [];
  bus.on<StoreNotificationsChangedPayload>("store_notifications_changed", (e) => events.push(e));
  const store = createNotificationStore({
    bus,
    storage,
    nowFn          : () => NOW_MS,
    setTimeoutFn   : () => 0,
    clearTimeoutFn : () => {},
  });
  // The store emits one `hydrated` while constructing (its persisted-state load);
  // drop it so every assertion below sees only what the test itself caused.
  events.length = 0;
  return { store, events };
}

function sender(id: string): ServerSenderHydrationRecord {
  return { sender_id: id, last_activity: "2026-09-10T14:00:00Z", count: 1, new_count: 0, voice_persona: null };
}

function row(id: string, senderId: string): Record<string, unknown> {
  return { id, sender_id: senderId, message: `m ${id}`, title: null, abstract: null, timestamp: "2026-09-10T14:00:00Z", time_display: null, progress_group_id: null };
}

// api.get stub keyed by sender id; an Error value rejects that sender's fetch.
function apiStub(bySender: Record<string, Record<string, unknown[]> | Error>): NotificationHistoryApiClient {
  return {
    get<T>(path: string): Promise<T> {
      const m = /conversation-by-date\/([^/]+)\//.exec(path);
      const resp = bySender[decodeURIComponent((m?.[1] ?? "") as string)];
      if (resp instanceof Error || resp === undefined) return Promise.reject(resp ?? new Error("unexpected"));
      return Promise.resolve(resp as T);
    },
  };
}

const OPTS = { userEmail: "rick@example.com", effectiveHours: 48 };

test("a fresh store is idle with no error", () => {
  const { store } = setupStore();
  assert.equal(store.historyHydrationState(), "idle");
  assert.equal(store.historyHydrationError(), null);
});

test("markHistoryHydrationLoading → loading, clears any error, emits hydration_state", () => {
  const { store, events } = setupStore();
  store.markHistoryHydrationFailed("earlier");
  events.length = 0;
  store.markHistoryHydrationLoading();
  assert.equal(store.historyHydrationState(), "loading");
  assert.equal(store.historyHydrationError(), null);
  assert.deepEqual(events.map(e => e.payload.changeKind), ["hydration_state"]);
});

test("markHistoryHydrationFailed → failed with the reason, emits hydration_state", () => {
  const { store, events } = setupStore();
  store.markHistoryHydrationFailed("request timed out after 10000ms");
  assert.equal(store.historyHydrationState(), "failed");
  assert.equal(store.historyHydrationError(), "request timed out after 10000ms");
  assert.deepEqual(events.map(e => e.payload.changeKind), ["hydration_state"]);
});

test("a successful hydrateHistory ends in done with no error", async () => {
  const { store } = setupStore();
  store.markHistoryHydrationLoading();
  await store.hydrateHistory(apiStub({ a: { "2026-09-10": [row("r1", "a")] } }), { ...OPTS, senders: [sender("a")] });
  assert.equal(store.historyHydrationState(), "done");
  assert.equal(store.historyHydrationError(), null);
  assert.equal(store.list().length, 1);
});

test("EVERY in-window sender fetch rejected → failed, NOT hydrated, and nothing seeded", async () => {
  const { store, events } = setupStore();
  await store.hydrateHistory(
    apiStub({ a: new Error("request timed out after 10000ms"), b: new Error("boom") }),
    { ...OPTS, senders: [sender("a"), sender("b")] },
  );
  assert.equal(store.historyHydrationState(), "failed");
  assert.match(store.historyHydrationError() ?? "", /all 2 sender history requests failed/);
  assert.match(store.historyHydrationError() ?? "", /timed out after 10000ms/);
  assert.equal(store.isHistoryHydrated(), false);
  assert.equal(store.list().length, 0);
  assert.equal(events.some(e => e.payload.changeKind === "hydrated"), false);
});

test("after an all-rejected failure a retry can still hydrate", async () => {
  const { store } = setupStore();
  await store.hydrateHistory(apiStub({ a: new Error("down") }), { ...OPTS, senders: [sender("a")] });
  assert.equal(store.historyHydrationState(), "failed");
  await store.hydrateHistory(apiStub({ a: { "2026-09-10": [row("r1", "a")] } }), { ...OPTS, senders: [sender("a")] });
  assert.equal(store.historyHydrationState(), "done");
  assert.equal(store.list().length, 1);
});

test("a PARTIAL rejection still seeds the rest and ends in done (existing best-effort contract)", async () => {
  const { store } = setupStore();
  await store.hydrateHistory(
    apiStub({ a: new Error("one bad sender"), b: { "2026-09-10": [row("r2", "b")] } }),
    { ...OPTS, senders: [sender("a"), sender("b")] },
  );
  assert.equal(store.historyHydrationState(), "done");
  assert.equal(store.list().length, 1);
});

test("zero in-window senders is a real empty result → done, not failed", async () => {
  const { store } = setupStore();
  await store.hydrateHistory(apiStub({}), { ...OPTS, senders: [] });
  assert.equal(store.historyHydrationState(), "done");
  assert.equal(store.isHistoryHydrated(), true);
});
