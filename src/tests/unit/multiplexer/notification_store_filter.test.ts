// Multiplexer — NotificationStore Mine switch mode (row 98305d96) + clear-all primitive.
// Run via `npx tsx --test src/tests/unit/multiplexer/notification_store_filter.test.ts`.
//
// Rick ruled ~15:57 EDT 2026-09-10 that the Mine switch ports legacy's USER filter. The SERVER
// applies it (coldHistoryHydration sends exclude_own_jobs for "others"); the store only holds the
// mode, under legacy's raw localStorage key. The 2026-06-29 message-DIRECTION predicate is gone:
// it hid every reply bubble under the default "own" (parity doc C2, second cause).

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createStorageServiceForTesting, InMemoryStorage } from "../../../lupin_app/static/js/multiplexer/shared/StorageService";
import * as notificationStoreModule from "../../../lupin_app/static/js/multiplexer/stores/NotificationStore";
import {
  createNotificationStore,
  FILTER_MODE_KEY,
} from "../../../lupin_app/static/js/multiplexer/stores/NotificationStore";
import type { NotificationHistoryApiClient } from "../../../lupin_app/static/js/multiplexer/stores/NotificationStore";
import type { ServerSenderHydrationRecord } from "../../../lupin_app/static/js/multiplexer/stores/SessionStripStore";
import type { LupinEvent, StoreNotificationsChangedPayload } from "../../../lupin_app/static/js/multiplexer/shared/types";

const NOW_MS = Date.parse("2026-06-11T22:00:00Z");

function fakeShared(seed: Record<string, string> = {}) {
  const map = new Map<string, string>(Object.entries(seed));
  return {
    map,
    storage : {
      getItem : (k: string): string | null => map.get(k) ?? null,
      setItem : (k: string, v: string): void => { map.set(k, v); },
    },
  };
}

function setup(opts: { shared?: ReturnType<typeof fakeShared> | null; oldEnvelope?: unknown } = {}) {
  const bus     = createEventBusForTesting();
  const storage = createStorageServiceForTesting(bus, new InMemoryStorage());
  if (opts.oldEnvelope !== undefined) storage.setJSON("notifications:filter-mode", opts.oldEnvelope, 1);
  const shared  = opts.shared === undefined ? fakeShared() : opts.shared;
  const events: LupinEvent<StoreNotificationsChangedPayload>[] = [];
  bus.on<StoreNotificationsChangedPayload>("store_notifications_changed", (e) => events.push(e));
  const store = createNotificationStore({
    bus, storage,
    sharedStorage  : shared === null ? null : shared.storage,
    setTimeoutFn   : (cb) => { cb(); return 0; },   // synchronous persist
    clearTimeoutFn : () => {},
    nowFn          : () => NOW_MS,
  });
  return { bus, store, events, shared };
}

// Push an inbound notification over the live queue path.
function pushIncoming(bus: ReturnType<typeof createEventBusForTesting>, id: string): void {
  bus.emit({
    type    : "notification_queue_update",
    payload : { notification: { id_hash: id, message: "m-" + id, sender_id: "s1", timestamp: "2026-06-29T12:00:00Z" } },
    source  : "test",
    ts      : 0,
  });
}

// ===========================================================================
// The direction predicate is gone
// ===========================================================================

test("the message-direction predicate no longer exists in the store module", () => {
  assert.equal("matchesNotificationFilter" in notificationStoreModule, false);
});

test("visibleEntries: a reply bubble from history is visible in every mode, the same rows as list()", async () => {
  const { store } = setup();
  const sender: ServerSenderHydrationRecord = { sender_id: "ext-sender", last_activity: "2026-06-11T21:05:00Z", count: 1, new_count: 0, voice_persona: null };
  const api: NotificationHistoryApiClient = {
    get: <T>(): Promise<T> => Promise.resolve({
      "2026-06-11": [ {
        id: "p1", sender_id: "ext-sender", message: "Promote it?", timestamp: "2026-06-11T21:00:00Z",
        response_value: { value: "Approved" }, responded_at: "2026-06-11T21:05:00Z",
      } ],
    } as T),
  };
  await store.hydrateHistory(api, { userEmail: "rick@example.com", effectiveHours: 48, senders: [ sender ] });
  assert.ok(store.list().some(n => n.id_hash === "p1-response" && n.direction === "outgoing"), "fixture must yield a reply bubble");

  for (const mode of [ "own", "others", "all" ] as const) {
    store.setFilterMode(mode);
    assert.ok(store.visibleEntries().some(n => n.id_hash === "p1-response"), `reply bubble hidden in mode ${mode}`);
    assert.equal(store.visibleEntries().length, store.list().length);
  }
});

// ===========================================================================
// The mode: default, legacy's key, and what "active" means
// ===========================================================================

test("filterMode defaults to own; isFilterActive is false", () => {
  const { store } = setup();
  assert.equal(store.filterMode(), "own");
  assert.equal(store.isFilterActive(), false);
});

test("setFilterMode stores the mode as a raw string under legacy's key and emits 'filtered'", () => {
  const { store, events, shared } = setup();
  assert.equal(FILTER_MODE_KEY, "notifications_filter_preference");
  const before = events.length;
  store.setFilterMode("others");
  assert.equal(store.filterMode(), "others");
  assert.equal(shared!.map.get(FILTER_MODE_KEY), "others");
  assert.ok(events.slice(before).map(e => e.payload.changeKind).includes("filtered"));
});

test("isFilterActive is true only for others: all sends the same request as own", () => {
  const { store } = setup();
  store.setFilterMode("all");
  assert.equal(store.isFilterActive(), false);
  store.setFilterMode("others");
  assert.equal(store.isFilterActive(), true);
});

test("hydrate: the mode legacy stored is the multiplexer's mode on construct", () => {
  // Legacy's literal key (notifications.js QUEUE_FILTER_PREF_KEY), not the constant.
  assert.equal(setup({ shared: fakeShared({ notifications_filter_preference: "others" }) }).store.filterMode(), "others");
  assert.equal(setup({ shared: fakeShared({ notifications_filter_preference: "all" }) }).store.filterMode(), "all");
});

test("hydrate: an invalid or absent stored value reads as own", () => {
  assert.equal(setup({ shared: fakeShared({ [FILTER_MODE_KEY]: "bogus" }) }).store.filterMode(), "own");
  assert.equal(setup({ shared: fakeShared() }).store.filterMode(), "own");
});

test("hydrate: the retired 'notifications:filter-mode' envelope is ignored", () => {
  assert.equal(setup({ oldEnvelope: { mode: "all" } }).store.filterMode(), "own");
});

test("no localStorage at all: the mode reads own and still changes in memory", () => {
  const { store } = setup({ shared: null });
  assert.equal(store.filterMode(), "own");
  store.setFilterMode("all");
  assert.equal(store.filterMode(), "all");
});

// ===========================================================================
// removeByIdHashes — the clear-all primitive
// ===========================================================================

test("removeByIdHashes removes the given ids, emits 'removed', drops unread", () => {
  const { store, bus, events } = setup();
  pushIncoming(bus, "n1");
  pushIncoming(bus, "n2");
  pushIncoming(bus, "n3");
  assert.equal(store.unreadCount(), 3);

  const before = events.length;
  store.removeByIdHashes(["n1", "n3"]);

  assert.deepEqual(store.list().map(n => n.id_hash), ["n2"]);
  assert.equal(store.unreadCount(), 1);
  const emitted = events.slice(before).map(e => e.payload.changeKind);
  assert.deepEqual(emitted, ["removed"]);   // exactly one bulk emit
});

test("removeByIdHashes skips unknown ids (partial-failure safe)", () => {
  const { store, bus } = setup();
  pushIncoming(bus, "n1");
  store.removeByIdHashes(["n1", "does-not-exist"]);
  assert.equal(store.list().length, 0);
});

test("removeByIdHashes with no matches is a no-op (no emit)", () => {
  const { store, bus, events } = setup();
  pushIncoming(bus, "n1");
  const before = events.length;
  store.removeByIdHashes(["ghost-a", "ghost-b"]);
  assert.equal(store.list().length, 1);
  assert.equal(events.slice(before).length, 0);
});

test("removeByIdHashes does not decrement unread below zero when item was read", () => {
  const { store, bus } = setup();
  pushIncoming(bus, "n1");
  store.markRead("n1");                 // unread → 0, n1 in readSet
  assert.equal(store.unreadCount(), 0);
  store.removeByIdHashes(["n1"]);       // read item removed; unread stays 0
  assert.equal(store.unreadCount(), 0);
  assert.equal(store.list().length, 0);
});
