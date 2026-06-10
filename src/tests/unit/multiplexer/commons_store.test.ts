// Multiplexer Lane D (WP3) — CommonsStore unit tests.
// Run via `npx tsx --test src/tests/unit/multiplexer/commons_store.test.ts`.
//
// Coverage target: 100% lines/branches/functions per the Lupin-wide mandate.

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createStorageServiceForTesting } from "../../../lupin_app/static/js/multiplexer/shared/StorageService";
import { createCommonsStore } from "../../../lupin_app/static/js/multiplexer/stores/CommonsStore";
import type { CommonsStore, CommonsHistoryApiClient } from "../../../lupin_app/static/js/multiplexer/stores/CommonsStore";
import type {
  CommonsActivityEntry,
  LupinEvent,
  StoreCommonsChangedPayload,
} from "../../../lupin_app/static/js/multiplexer/shared/types";
import type { EventBus } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import type { StorageService } from "../../../lupin_app/static/js/multiplexer/shared/StorageService";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeEntry(over: Partial<CommonsActivityEntry> = {}): CommonsActivityEntry {
  return {
    ts                : "2026-06-10T14:00:00+00:00",
    topic             : "broadcasts",
    topic_kind        : "reserved",
    sender_session_id : "abc123",
    persona_name      : "Tiberius",
    persona_icon      : "👑",
    persona_color     : "#FFD600",
    body              : "hello commons",
    metadata          : {},
    ...over,
  };
}

interface Harness {
  bus     : EventBus;
  storage : StorageService;
  store   : CommonsStore;
  events  : Array<StoreCommonsChangedPayload>;
  nowFn   : () => number;
}

// Fixed clock: 2026-06-10T14:00:00 LOCAL (the Date ctor below is local-time).
const FIXED_NOW = new Date(2026, 5, 10, 14, 0, 0).getTime();

function makeHarness(opts: { storage?: StorageService; nowFn?: () => number } = {}): Harness {
  const bus     = createEventBusForTesting();
  const storage = opts.storage ?? createStorageServiceForTesting(bus);
  const nowFn   = opts.nowFn ?? (() => FIXED_NOW);
  const events: Array<StoreCommonsChangedPayload> = [];
  bus.on<StoreCommonsChangedPayload>("store_commons_changed", (e) => events.push(e.payload));
  const store = createCommonsStore({ bus, storage, nowFn });
  return { bus, storage, store, events, nowFn };
}

// Stub ApiClient — records the path it was called with + returns a canned body.
function makeApi(body: unknown, capture?: { path?: string }): CommonsHistoryApiClient {
  return {
    get: async <T>(path: string): Promise<T> => {
      if (capture) capture.path = path;
      return body as T;
    },
  };
}

function emitQueueUpdate(bus: EventBus, notification: unknown): void {
  bus.emit<unknown>({
    type    : "notification_queue_update",
    payload : { queue_name: "notification", value: 1, notification },
    source  : "test",
    ts      : 0,
  } as LupinEvent<unknown>);
}

// ===========================================================================
// 1 : Construction + defaults
// ===========================================================================

test("fresh store has empty cache, default filter, default window, not disabled", () => {
  const { store } = makeHarness();
  assert.deepEqual(store.entries(), []);
  assert.deepEqual(store.getFilter(), { direction: null, kind: "all", persona: null });
  assert.equal(store.getWindow(), "today");
  assert.equal(store.isFilterActive(), false);
  assert.equal(store.isDisabled(), false);
});

test("getFilter returns a defensive copy (mutating it does not affect the store)", () => {
  const { store } = makeHarness();
  const f = store.getFilter();
  f.kind = "broadcasts";
  assert.equal(store.getFilter().kind, "all");
});

// ===========================================================================
// 2 : hydrate() — REST load
// ===========================================================================

test("hydrate replaces cache, sets window, emits hydrated", async () => {
  const { store, events } = makeHarness();
  const cap: { path?: string } = {};
  const api = makeApi({ entries: [makeEntry(), makeEntry({ body: "second" })] }, cap);
  await store.hydrate(api, "all");
  assert.equal(store.entries().length, 2);
  assert.equal(store.getWindow(), "all");
  assert.equal(store.isDisabled(), false);
  assert.deepEqual(events.at(-1), { changeKind: "hydrated" });
  // "all" window → no hours param, limit only
  assert.equal(cap.path, "/api/commons/broadcast-history?limit=200");
});

test("hydrate without a window arg keeps the current window", async () => {
  const { store } = makeHarness();
  const cap: { path?: string } = {};
  const api = makeApi({ entries: [] }, cap);
  await store.hydrate(api);   // no window → uses default "today"
  // "today" at FIXED_NOW (14:00 local) → 14 hours since midnight
  assert.equal(cap.path, "/api/commons/broadcast-history?hours=14&limit=200");
});

test("hydrate with numeric window passes hours through", async () => {
  const { store } = makeHarness();
  const cap: { path?: string } = {};
  await store.hydrate(makeApi({ entries: [] }, cap), "6");
  assert.equal(cap.path, "/api/commons/broadcast-history?hours=6&limit=200");
});

test("hydrate 'today' rounds up and floors at 1 hour just after midnight", async () => {
  // 00:10 local → ceil(10min/60min)=1
  const justAfterMidnight = new Date(2026, 5, 10, 0, 10, 0).getTime();
  const { store } = makeHarness({ nowFn: () => justAfterMidnight });
  const cap: { path?: string } = {};
  await store.hydrate(makeApi({ entries: [] }, cap), "today");
  assert.equal(cap.path, "/api/commons/broadcast-history?hours=1&limit=200");
});

test("hydrate honors the server disabled kill-switch: clears cache, flips isDisabled", async () => {
  const { store, events } = makeHarness();
  // Seed a non-empty cache first.
  await store.hydrate(makeApi({ entries: [makeEntry()] }), "all");
  assert.equal(store.entries().length, 1);
  // Now the flag flips off server-side.
  await store.hydrate(makeApi({ disabled: true }), "all");
  assert.equal(store.isDisabled(), true);
  assert.deepEqual(store.entries(), []);
  assert.deepEqual(events.at(-1), { changeKind: "hydrated" });
});

test("hydrate tolerates a response missing the entries field", async () => {
  const { store } = makeHarness();
  await store.hydrate(makeApi({}), "all");
  assert.deepEqual(store.entries(), []);
  assert.equal(store.isDisabled(), false);
});

test("hydrate re-enables after a prior disabled response", async () => {
  const { store } = makeHarness();
  await store.hydrate(makeApi({ disabled: true }), "all");
  assert.equal(store.isDisabled(), true);
  await store.hydrate(makeApi({ entries: [makeEntry()] }), "all");
  assert.equal(store.isDisabled(), false);
  assert.equal(store.entries().length, 1);
});

test("hydrate rejection propagates to the caller", async () => {
  const { store } = makeHarness();
  const api: CommonsHistoryApiClient = {
    get: async <T>(_path: string): Promise<T> => { throw new Error("network"); },
  };
  await assert.rejects(() => store.hydrate(api, "all"), /network/);
});

// ===========================================================================
// 3 : live WS ingest via notification_queue_update
// ===========================================================================

test("commons_activity notification prepends to cache and emits prepended(matches=true)", () => {
  const { store, bus, events } = makeHarness();
  emitQueueUpdate(bus, { type: "commons_activity", payload: makeEntry({ body: "live" }) });
  assert.equal(store.entries().length, 1);
  assert.equal(store.entries()[0]?.body, "live");
  assert.deepEqual(events.at(-1), { changeKind: "prepended", matchesFilter: true });
});

test("live entries land at the head (newest-first)", () => {
  const { store, bus } = makeHarness();
  emitQueueUpdate(bus, { type: "commons_activity", payload: makeEntry({ body: "first" }) });
  emitQueueUpdate(bus, { type: "commons_activity", payload: makeEntry({ body: "second" }) });
  assert.equal(store.entries()[0]?.body, "second");
  assert.equal(store.entries()[1]?.body, "first");
});

test("non-commons notification_queue_update frames are ignored", () => {
  const { store, bus, events } = makeHarness();
  emitQueueUpdate(bus, { type: "notification_arrived", payload: { id_hash: "x" } });
  assert.equal(store.entries().length, 0);
  assert.equal(events.length, 0);
});

test("queue update with no notification field is ignored", () => {
  const { store, bus, events } = makeHarness();
  bus.emit<unknown>({
    type    : "notification_queue_update",
    payload : { queue_name: "notification", value: 0 },
    source  : "test",
    ts      : 0,
  } as LupinEvent<unknown>);
  assert.equal(store.entries().length, 0);
  assert.equal(events.length, 0);
});

test("commons_activity notification missing its payload is ignored", () => {
  const { store, bus, events } = makeHarness();
  emitQueueUpdate(bus, { type: "commons_activity" });   // no payload
  assert.equal(store.entries().length, 0);
  assert.equal(events.length, 0);
});

test("prepended emits matchesFilter=false when the live entry fails the active filter", () => {
  const { store, bus, events } = makeHarness();
  store.setKind("heartbeats");   // entry below is not a heartbeat
  emitQueueUpdate(bus, { type: "commons_activity", payload: makeEntry({ metadata: {} }) });
  assert.equal(store.entries().length, 1);          // still cached
  assert.deepEqual(events.at(-1), { changeKind: "prepended", matchesFilter: false });
});

// ===========================================================================
// 4 : filter mutators + persistence
// ===========================================================================

test("setDirection / setKind / setPersona mutate filter, emit filter-changed, mark active", () => {
  const { store, events } = makeHarness();
  store.setKind("broadcasts");
  assert.deepEqual(events.at(-1), { changeKind: "filter-changed" });
  store.setDirection("sender");
  store.setPersona("Tiberius");
  assert.deepEqual(store.getFilter(), { direction: "sender", kind: "broadcasts", persona: "tiberius" });
  assert.equal(store.isFilterActive(), true);
});

test("setPersona(null) and setPersona('') both clear the persona axis", () => {
  const { store } = makeHarness();
  store.setPersona("Rachel");
  assert.equal(store.getFilter().persona, "rachel");
  store.setPersona("");
  assert.equal(store.getFilter().persona, null);
  store.setPersona("Rachel");
  store.setPersona(null);
  assert.equal(store.getFilter().persona, null);
});

test("setKind('all') + setDirection(null) return isFilterActive to false", () => {
  const { store } = makeHarness();
  store.setKind("personas");
  store.setDirection("recipient");
  assert.equal(store.isFilterActive(), true);
  store.setKind("all");
  store.setDirection(null);
  assert.equal(store.isFilterActive(), false);
});

test("filter persists across store instances via StorageService", () => {
  const bus     = createEventBusForTesting();
  const storage = createStorageServiceForTesting(bus);
  const first   = createCommonsStore({ bus, storage, nowFn: () => FIXED_NOW });
  first.setKind("personas");
  first.setDirection("recipient");
  first.setPersona("Maria");
  // A fresh store over the same storage re-hydrates the persisted filter.
  const second = createCommonsStore({ bus, storage, nowFn: () => FIXED_NOW });
  assert.deepEqual(second.getFilter(), { direction: "recipient", kind: "personas", persona: "maria" });
  assert.equal(second.isFilterActive(), true);
});

test("a corrupt/partial persisted filter coerces each axis to its default", () => {
  const bus     = createEventBusForTesting();
  const storage = createStorageServiceForTesting(bus);
  // Write a deliberately bogus envelope under the store's key.
  storage.setJSON("commons:activity-filter", { direction: "sideways", kind: "garbage", persona: 42 }, 1);
  const store = createCommonsStore({ bus, storage, nowFn: () => FIXED_NOW });
  assert.deepEqual(store.getFilter(), { direction: null, kind: "all", persona: null });
});

test("a persisted filter with an empty-string persona coerces persona to null", () => {
  const bus     = createEventBusForTesting();
  const storage = createStorageServiceForTesting(bus);
  storage.setJSON("commons:activity-filter", { direction: "sender", kind: "all", persona: "" }, 1);
  const store = createCommonsStore({ bus, storage, nowFn: () => FIXED_NOW });
  assert.deepEqual(store.getFilter(), { direction: "sender", kind: "all", persona: null });
});

// ===========================================================================
// 5 : matchesFilter predicate + visibleEntries
// ===========================================================================

test("kind=heartbeats matches only heartbeat-metadata entries", () => {
  const { store } = makeHarness();
  store.setKind("heartbeats");
  assert.equal(store.matchesFilter(makeEntry({ metadata: { kind: "heartbeat" } })), true);
  assert.equal(store.matchesFilter(makeEntry({ metadata: { kind: "status" } })), false);
  assert.equal(store.matchesFilter(makeEntry({ metadata: {} })), false);
});

test("kind=personas matches dm- topics that are not heartbeats", () => {
  const { store } = makeHarness();
  store.setKind("personas");
  assert.equal(store.matchesFilter(makeEntry({ topic: "dm-tiberius", metadata: {} })), true);
  assert.equal(store.matchesFilter(makeEntry({ topic: "broadcasts" })), false);
  assert.equal(store.matchesFilter(makeEntry({ topic: "dm-tiberius", metadata: { kind: "heartbeat" } })), false);
});

test("kind=broadcasts matches broadcasts + broadcast-acks topics only", () => {
  const { store } = makeHarness();
  store.setKind("broadcasts");
  assert.equal(store.matchesFilter(makeEntry({ topic: "broadcasts" })), true);
  assert.equal(store.matchesFilter(makeEntry({ topic: "broadcast-acks" })), true);
  assert.equal(store.matchesFilter(makeEntry({ topic: "dm-x" })), false);
});

test("direction=sender matches on lowercased persona name", () => {
  const { store } = makeHarness();
  store.setDirection("sender");
  store.setPersona("Tiberius");
  assert.equal(store.matchesFilter(makeEntry({ persona_name: "Tiberius" })), true);
  assert.equal(store.matchesFilter(makeEntry({ persona_name: "Rachel" })), false);
  assert.equal(store.matchesFilter(makeEntry({ persona_name: null })), false);
});

test("direction=recipient matches the dm-<sanitized-persona> topic", () => {
  const { store } = makeHarness();
  store.setDirection("recipient");
  store.setPersona("Mr. Radio");   // lowercased → "mr. radio" → sanitized → dm-mr_radio
  assert.equal(store.matchesFilter(makeEntry({ topic: "dm-mr_radio" })), true);
  assert.equal(store.matchesFilter(makeEntry({ topic: "dm-tiberius" })), false);
});

test("direction=recipient is a silent no-op when kind=broadcasts (broadcasts fan out)", () => {
  const { store } = makeHarness();
  store.setKind("broadcasts");
  store.setDirection("recipient");
  store.setPersona("tiberius");
  // A broadcast row matches despite the recipient axis being set.
  assert.equal(store.matchesFilter(makeEntry({ topic: "broadcasts" })), true);
});

test("direction set without a persona target applies no direction constraint", () => {
  const { store } = makeHarness();
  store.setDirection("sender");   // persona stays null
  assert.equal(store.matchesFilter(makeEntry({ persona_name: "anyone" })), true);
});

test("entry with no topic / no metadata / no persona is handled by the predicate", () => {
  const { store } = makeHarness();
  // kind=all, no direction → everything matches even with missing fields.
  const bare = { topic_kind: "free-form" } as unknown as CommonsActivityEntry;
  assert.equal(store.matchesFilter(bare), true);
});

test("visibleEntries returns only entries passing the active filter, newest-first", () => {
  const { store, bus } = makeHarness();
  emitQueueUpdate(bus, { type: "commons_activity", payload: makeEntry({ topic: "broadcasts", body: "b1" }) });
  emitQueueUpdate(bus, { type: "commons_activity", payload: makeEntry({ topic: "dm-x", body: "d1" }) });
  store.setKind("broadcasts");
  const vis = store.visibleEntries();
  assert.equal(vis.length, 1);
  assert.equal(vis[0]?.body, "b1");
  // entries() still returns the full cache
  assert.equal(store.entries().length, 2);
});

// ===========================================================================
// 6 : cleanup
// ===========================================================================

test("disposeForTesting detaches the queue-update listener", () => {
  const { store, bus } = makeHarness();
  store.disposeForTesting();
  emitQueueUpdate(bus, { type: "commons_activity", payload: makeEntry() });
  assert.equal(store.entries().length, 0);
});
