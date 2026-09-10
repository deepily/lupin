// Row 98305d96 — the Mine switch loads history ONCE per mode.
// Run via `npx tsx --test src/tests/unit/multiplexer/the_mine_switch_loads_history_once_per_mode.test.ts`.
//
// Mr. Radio's condition on the design (DM 17:06): a page load runs exactly ONE history hydration.
// Legacy's admin page loaded history twice on every start (row b670b76c), because initializing
// its filter UI called setFilterMode, and setFilterMode reloads. Here the REAL store, the REAL
// cold-load runner and the REAL header renderer are put together the way boot.ts wires them.
//
// One deliberate difference from boot: the header mounts WHILE the first load is in flight.
// boot.ts mounts the header before it even creates the runner, so a mode write during mount
// would slip past the reload listener and be caught by nothing. Measured by revert arm
// 2026-09-10: with the runner created first but the header mounted before run(), a mount-time
// write replaced the run instead of doubling it, and this test stayed green. Mounting during
// the run is the ordering in which such a write DOES produce a second load.

import { test, before, afterEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createStorageServiceForTesting, InMemoryStorage } from "../../../lupin_app/static/js/multiplexer/shared/StorageService";
import { createNotificationStore, FILTER_MODE_KEY } from "../../../lupin_app/static/js/multiplexer/stores/NotificationStore";
import { createColdHistoryHydration } from "../../../lupin_app/static/js/multiplexer/stores/coldHistoryHydration";
import { createNotificationsHeaderRenderer } from "../../../lupin_app/static/js/multiplexer/render/NotificationsHeaderRenderer";
import type { ServerSenderHydrationRecord } from "../../../lupin_app/static/js/multiplexer/stores/SessionStripStore";

before(() => {
  if (typeof globalThis.document === "undefined") GlobalRegistrator.register();
});
afterEach(() => {
  document.body.replaceChildren();
});

const settle = (): Promise<void> => new Promise(r => setTimeout(r, 30));

function bootLike(storedMode: string | null, admin: boolean) {
  const bus     = createEventBusForTesting();
  const storage = createStorageServiceForTesting(bus, new InMemoryStorage());
  const map     = new Map<string, string>();
  if (storedMode !== null) map.set(FILTER_MODE_KEY, storedMode);
  const store = createNotificationStore({
    bus, storage,
    sharedStorage : { getItem: (k) => map.get(k) ?? null, setItem: (k, v) => { map.set(k, v); } },
  });

  const sender: ServerSenderHydrationRecord = {
    sender_id: "claude.code@lupin.deepily.ai#abc12345", last_activity: new Date().toISOString(), count: 1, new_count: 0, voice_persona: null,
  };
  const sendersVisible: string[] = [];
  const api = {
    get: <T>(path: string): Promise<T> => {
      if (path.includes("/senders-visible/")) {
        sendersVisible.push(path);
        return Promise.resolve([ sender ] as T);
      }
      return Promise.resolve({} as T);   // conversation-by-date: no rows needed here
    },
  };
  const ignore = { hydrate: (): void => {} };

  // The same expression boot.ts passes.
  const hydration = createColdHistoryHydration({
    bus, api,
    stores            : { sessionStrip: ignore, senders: ignore, notifications: store },
    getEmail          : () => "rick@example.com",
    getEffectiveHours : () => 48,
    getExcludeOwnJobs : () => admin && store.filterMode() === "others",
  });

  const mountHeader = (): void => {
  const header = createNotificationsHeaderRenderer({
    eventBus  : bus,
    store,
    api       : {
      delete          : <T>(): Promise<T> => Promise.resolve(undefined as T),
      bounceDevServer : () => Promise.resolve({ status: "accepted", timestamp: "" }),
    },
    confirmFn : () => true,
    isAdmin   : () => admin,
  });
  header.mount(root);
  };
  const root = document.createElement("div");
  document.body.appendChild(root);

  return { store, root, hydration, sendersVisible, map, mountHeader };
}

test("an admin page load in Not Mine runs ONE history hydration, and it asks for exclude_own_jobs", async () => {
  const b = bootLike("others", true);
  const firstLoad = b.hydration.run();
  b.mountHeader();                      // the header arrives while the history is loading
  await firstLoad;
  await settle();
  assert.equal(b.sendersVisible.length, 1, `senders-visible fetched ${b.sendersVisible.length} times on one page load`);
  assert.match(b.sendersVisible[ 0 ]!, /exclude_own_jobs=true/);
});

test("switching to Mine reloads once, without exclude_own_jobs, and legacy's key follows", async () => {
  const b = bootLike("others", true);
  b.mountHeader();
  await b.hydration.run();
  (b.root.querySelector("[data-testid='multiplexer-notifications-filter-own-btn']") as HTMLElement).click();
  await settle();
  assert.equal(b.sendersVisible.length, 2);
  assert.doesNotMatch(b.sendersVisible[ 1 ]!, /exclude_own_jobs/);
  assert.equal(b.map.get(FILTER_MODE_KEY), "own");
});

test("a non-admin never excludes, even when legacy left Not Mine stored, and sees no switch", async () => {
  const b = bootLike("others", false);
  b.mountHeader();
  await b.hydration.run();
  await settle();
  assert.equal(b.sendersVisible.length, 1);
  assert.doesNotMatch(b.sendersVisible[ 0 ]!, /exclude_own_jobs/);
  assert.equal((b.root.querySelector("[data-testid='multiplexer-notifications-filter-switch']") as HTMLElement).hidden, true);
});
