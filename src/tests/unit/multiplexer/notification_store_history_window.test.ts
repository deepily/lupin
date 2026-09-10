// P0 5ebd2aff (2026-09-10) — Rick's ruling 1: NotificationStore owns the history window.
// Run via `npx tsx --test src/tests/unit/multiplexer/notification_store_history_window.test.ts`.
//
// These pin: the window lives under the legacy client's RAW key (so both
// clients agree), an unchanged pick does nothing (legacy skips the reload), a
// reset lets history hydrate again, and "All time" sends no hours and applies
// no cutoff.

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createStorageServiceForTesting, InMemoryStorage } from "../../../lupin_app/static/js/multiplexer/shared/StorageService";
import { createNotificationStore } from "../../../lupin_app/static/js/multiplexer/stores/NotificationStore";
import type { NotificationHistoryApiClient } from "../../../lupin_app/static/js/multiplexer/stores/NotificationStore";
import { HISTORY_WINDOW_KEY } from "../../../lupin_app/static/js/multiplexer/stores/historyWindow";
import type { ServerSenderHydrationRecord } from "../../../lupin_app/static/js/multiplexer/stores/SessionStripStore";
import type { LupinEvent, StoreNotificationsChangedPayload } from "../../../lupin_app/static/js/multiplexer/shared/types";

const NOW_MS = Date.parse("2026-09-10T15:00:00Z");

// The raw storage the legacy client writes, with every write recorded.
class FakeShared {
  readonly values = new Map<string, string>();
  readonly writes : Array<[string, string]> = [];
  getItem(key: string): string | null { return this.values.get(key) ?? null; }
  setItem(key: string, value: string): void { this.writes.push([key, value]); this.values.set(key, value); }
}

function setupStore(shared: FakeShared | null = new FakeShared()) {
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
    sharedStorage  : shared,
  });
  events.length = 0;   // drop the construction-time `hydrated`
  return { store, events };
}

function sender(id: string, lastActivity?: string): ServerSenderHydrationRecord {
  return { sender_id: id, last_activity: lastActivity, count: 1, new_count: 0, voice_persona: null };
}

function row(id: string, senderId: string): Record<string, unknown> {
  return { id, sender_id: senderId, message: `m ${id}`, title: null, abstract: null, timestamp: "2026-09-10T14:00:00Z", time_display: null, progress_group_id: null };
}

// Records every requested path; each sender returns one row.
function recordingApi(): NotificationHistoryApiClient & { paths: string[] } {
  const paths: string[] = [];
  return {
    paths,
    get<T>(path: string): Promise<T> {
      paths.push(path);
      const senderId = decodeURIComponent(/conversation-by-date\/([^/]+)\//.exec(path)?.[1] ?? "");
      return Promise.resolve({ "2026-09-10": [row(`r-${senderId}`, senderId)] } as T);
    },
  };
}

test("a browser with no stored pick starts on 48 hours, with or without storage", () => {
  assert.equal(setupStore().store.historyWindow(), 48);
  assert.equal(setupStore(null).store.historyWindow(), 48);
});

test("the window is read from the legacy client's raw key at construction", () => {
  for (const [raw, expected] of [["today", "today"], ["all", null], ["168", 168]] as const) {
    const shared = new FakeShared();
    shared.values.set(HISTORY_WINDOW_KEY, raw);
    assert.equal(setupStore(shared).store.historyWindow(), expected, raw);
  }
});

test("setHistoryWindow writes the legacy raw value and emits history_window", () => {
  const shared = new FakeShared();
  const { store, events } = setupStore(shared);
  store.setHistoryWindow(null);
  assert.equal(store.historyWindow(), null);
  assert.deepEqual(shared.writes, [["notifications_history_window", "all"]]);
  assert.deepEqual(events.map(e => e.payload.changeKind), ["history_window"]);
});

test("picking the window already in force writes nothing and emits nothing", () => {
  const shared = new FakeShared();
  const { store, events } = setupStore(shared);
  store.setHistoryWindow(48);
  assert.deepEqual(shared.writes, []);
  assert.deepEqual(events, []);
});

test("resetHistoryHydration drops loaded history, returns to idle, and lets it hydrate again", async () => {
  const { store, events } = setupStore();
  const opts = { userEmail: "rick@example.com", effectiveHours: 48, senders: [sender("a", "2026-09-10T14:00:00Z")] };
  await store.hydrateHistory(recordingApi(), opts);
  assert.equal(store.list().length, 1);
  assert.equal(store.isHistoryHydrated(), true);

  events.length = 0;
  store.resetHistoryHydration();
  assert.equal(store.list().length, 0);
  assert.equal(store.isHistoryHydrated(), false);
  assert.equal(store.historyHydrationState(), "idle");
  assert.deepEqual(events.map(e => e.payload.changeKind), ["history_reset"]);

  await store.hydrateHistory(recordingApi(), opts);
  assert.equal(store.list().length, 1, "the same row seeds again — it is not treated as already present");
});

test("All time: every sender loads, with no hours param", async () => {
  const { store } = setupStore();
  const api = recordingApi();
  await store.hydrateHistory(api, {
    userEmail      : "rick@example.com",
    effectiveHours : null,
    senders        : [sender("recent", "2026-09-10T14:00:00Z"), sender("old", "2020-01-01T00:00:00Z")],
  });
  assert.equal(api.paths.length, 2, "no cutoff drops the old sender");
  for (const path of api.paths) {
    assert.ok(!path.includes("hours="), path);
    assert.ok(path.includes("anchor="), path);
  }
});

test("control: a numbered window still sends hours and skips senders older than it", async () => {
  const { store } = setupStore();
  const api = recordingApi();
  await store.hydrateHistory(api, {
    userEmail      : "rick@example.com",
    effectiveHours : 48,
    senders        : [sender("recent", "2026-09-10T14:00:00Z"), sender("old", "2020-01-01T00:00:00Z")],
  });
  assert.equal(api.paths.length, 1);
  assert.ok(api.paths[0]!.includes("hours=48"), api.paths[0]);
});

test("All time with no last_activity requests the bare URL, never anchor=undefined", async () => {
  const { store } = setupStore();
  const api = recordingApi();
  await store.hydrateHistory(api, { userEmail: "rick@example.com", effectiveHours: null, senders: [sender("quiet")] });
  assert.deepEqual(api.paths, ["/api/notifications/conversation-by-date/quiet/rick%40example.com"]);
});
