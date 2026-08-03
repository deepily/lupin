// Multiplexer B3 (01-C) — NotificationStore own-only filter + clear-all primitive.
// Run via `npx tsx --test src/tests/unit/multiplexer/notification_store_filter.test.ts`.
// Coverage target: 100% lines/branches/functions on the B3 net-new store logic
// (matchesNotificationFilter all 3 branches + visibleEntries + filterMode +
// setFilterMode + isFilterActive + removeByIdHashes + hydrate/persist).

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createStorageServiceForTesting, InMemoryStorage } from "../../../lupin_app/static/js/multiplexer/shared/StorageService";
import {
  createNotificationStore,
  matchesNotificationFilter,
} from "../../../lupin_app/static/js/multiplexer/stores/NotificationStore";
import type { LupinEvent, Notification, StoreNotificationsChangedPayload } from "../../../lupin_app/static/js/multiplexer/shared/types";

const FILTER_KEY = "notifications:filter-mode";

function setup(seedFilter?: { mode: unknown } | "corrupt") {
  const bus     = createEventBusForTesting();
  const backend = new InMemoryStorage();
  const storage = createStorageServiceForTesting(bus, backend);
  if (seedFilter === "corrupt") {
    backend.setItem("lupin:" + FILTER_KEY, "not json {{{");
  } else if (seedFilter !== undefined) {
    storage.setJSON(FILTER_KEY, seedFilter, 1);
  }
  const events: LupinEvent<StoreNotificationsChangedPayload>[] = [];
  bus.on<StoreNotificationsChangedPayload>("store_notifications_changed", (e) => events.push(e));
  let now = 1_700_000_000_000;
  const store = createNotificationStore({
    bus, storage,
    setTimeoutFn   : (cb) => { cb(); return 0; },   // synchronous persist
    clearTimeoutFn : () => {},
    nowFn          : () => now,
  });
  return { bus, storage, backend, store, events };
}

// Push an inbound notification (no `direction` ⇒ "own"/inbound).
function pushIncoming(bus: ReturnType<typeof createEventBusForTesting>, id: string): void {
  bus.emit({
    type    : "notification_queue_update",
    payload : { notification: { id_hash: id, message: "m-" + id, sender_id: "s1", timestamp: "2026-06-29T12:00:00Z" } },
    source  : "test",
    ts      : 0,
  });
}

// A hand-built Notification (lets us set `direction` directly for the predicate).
function mkNote(id: string, direction?: "incoming" | "outgoing"): Notification {
  const n: Notification = { id_hash: id, ts: 1, sender_id: "s", message: "m", action_required: false };
  if (direction !== undefined) n.direction = direction;
  return n;
}

// ===========================================================================
// matchesNotificationFilter — all three mode branches, direct + pure
// ===========================================================================

test("matchesNotificationFilter own: inbound (no direction) and incoming pass; outgoing fails", () => {
  assert.equal(matchesNotificationFilter(mkNote("a"), "own"), true);              // direction absent
  assert.equal(matchesNotificationFilter(mkNote("a", "incoming"), "own"), true);
  assert.equal(matchesNotificationFilter(mkNote("a", "outgoing"), "own"), false);
});

test("matchesNotificationFilter others: only outgoing passes", () => {
  assert.equal(matchesNotificationFilter(mkNote("a", "outgoing"), "others"), true);
  assert.equal(matchesNotificationFilter(mkNote("a", "incoming"), "others"), false);
  assert.equal(matchesNotificationFilter(mkNote("a"), "others"), false);
});

test("matchesNotificationFilter all: everything passes", () => {
  assert.equal(matchesNotificationFilter(mkNote("a"), "all"), true);
  assert.equal(matchesNotificationFilter(mkNote("a", "incoming"), "all"), true);
  assert.equal(matchesNotificationFilter(mkNote("a", "outgoing"), "all"), true);
});

// ===========================================================================
// filterMode default + hydrate + persist
// ===========================================================================

test("filterMode defaults to own; isFilterActive false at default", () => {
  const { store } = setup();
  assert.equal(store.filterMode(), "own");
  assert.equal(store.isFilterActive(), false);
});

test("setFilterMode persists + emits a 'filtered' changeKind", () => {
  const { store, events, storage } = setup();
  const before = events.length;
  store.setFilterMode("all");
  assert.equal(store.filterMode(), "all");
  assert.equal(store.isFilterActive(), true);
  const emitted = events.slice(before).map(e => e.payload.changeKind);
  assert.ok(emitted.includes("filtered"));
  // Persisted through the real read path: the envelope round-trips to "all".
  assert.equal(storage.getJSON<{ mode: string }>(FILTER_KEY, 1)!.mode, "all");
});

test("setFilterMode others → isFilterActive true", () => {
  const { store } = setup();
  store.setFilterMode("others");
  assert.equal(store.isFilterActive(), true);
});

test("hydrate: a persisted mode is restored on construct", () => {
  const { store } = setup({ mode: "all" });
  assert.equal(store.filterMode(), "all");
});

test("hydrate: an invalid persisted mode degrades to own", () => {
  const { store } = setup({ mode: "bogus" });
  assert.equal(store.filterMode(), "own");
});

test("hydrate: a corrupt envelope degrades to own (no throw)", () => {
  const { store } = setup("corrupt");
  assert.equal(store.filterMode(), "own");
});

// ===========================================================================
// visibleEntries — reflects the active mode over the live list
// ===========================================================================

test("visibleEntries: own (default) shows inbound; others hides them; all shows all", () => {
  const { store, bus } = setup();
  pushIncoming(bus, "n1");
  pushIncoming(bus, "n2");
  assert.equal(store.list().length, 2);

  // own (default): both inbound are visible.
  assert.equal(store.visibleEntries().length, 2);

  // others: no outgoing present → none visible (raw list unchanged).
  store.setFilterMode("others");
  assert.equal(store.visibleEntries().length, 0);
  assert.equal(store.list().length, 2);

  // all: everything visible again.
  store.setFilterMode("all");
  assert.equal(store.visibleEntries().length, 2);
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
