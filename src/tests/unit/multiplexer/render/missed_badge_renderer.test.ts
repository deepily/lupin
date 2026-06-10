// Multiplexer Lane E WP15 — MissedBadgeRenderer unit tests.
// 100% lines/branches/functions per the multiplexer coverage mandate.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createMissedBadgeRenderer,
  type MissedStoreLike,
} from "../../../../lupin_app/static/js/multiplexer/render/MissedBadgeRenderer";
import type { StoreMissedChangedPayload } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

interface FakeStore extends MissedStoreLike {
  setCount(n: number): void;
  resetCalls: number;
}

function makeStore(initial = 0, opts: { reject?: boolean; resolvesTo?: number } = {}): FakeStore {
  let count = initial;
  const store: FakeStore = {
    resetCalls: 0,
    count: () => count,
    setCount: (n: number) => { count = n; },
    reset: async (): Promise<number> => {
      store.resetCalls += 1;
      if (opts.reject) throw new Error("reset failed");
      count = opts.resolvesTo ?? 0;
      return count;
    },
  };
  return store;
}

function emitChanged(bus: ReturnType<typeof createEventBusForTesting>, count: number): void {
  bus.emit<StoreMissedChangedPayload>({
    type    : "store_missed_changed",
    payload : { count },
    source  : "test",
    ts      : 0,
  });
}

// ---------------------------------------------------------------------------
// Visibility
// ---------------------------------------------------------------------------

test("mount with zero count paints an empty root (hidden)", () => {
  const bus = createEventBusForTesting();
  const store = makeStore(0);
  const r = createMissedBadgeRenderer({ eventBus: bus, stores: { missed: store } });
  const root = document.createElement("div");
  r.mount(root);
  assert.equal(root.querySelector(".missed-badge"), null);
});

test("mount with non-zero count paints the badge + Reset button", () => {
  const bus = createEventBusForTesting();
  const store = makeStore(5);
  const r = createMissedBadgeRenderer({ eventBus: bus, stores: { missed: store } });
  const root = document.createElement("div");
  r.mount(root);
  assert.ok(root.querySelector(".missed-badge"));
  assert.equal(root.querySelector(".missed-status")?.textContent, "5 missed while away");
  assert.ok(root.querySelector(".missed-reset-button"));
});

test("store_missed_changed repaints: 0 → N shows badge, N → 0 hides it", () => {
  const bus = createEventBusForTesting();
  const store = makeStore(0);
  const r = createMissedBadgeRenderer({ eventBus: bus, stores: { missed: store } });
  const root = document.createElement("div");
  r.mount(root);
  assert.equal(root.querySelector(".missed-badge"), null);

  store.setCount(3);
  emitChanged(bus, 3);
  assert.ok(root.querySelector(".missed-badge"));

  store.setCount(0);
  emitChanged(bus, 0);
  assert.equal(root.querySelector(".missed-badge"), null);
});

// ---------------------------------------------------------------------------
// Reset wiring
// ---------------------------------------------------------------------------

test("Reset button click invokes store.reset()", async () => {
  const bus = createEventBusForTesting();
  const store = makeStore(4, { resolvesTo: 0 });
  const r = createMissedBadgeRenderer({ eventBus: bus, stores: { missed: store } });
  const root = document.createElement("div");
  r.mount(root);
  const btn = root.querySelector<HTMLButtonElement>(".missed-reset-button");
  assert.ok(btn);
  btn.click();
  await Promise.resolve();
  assert.equal(store.resetCalls, 1);
});

test("Reset rejection is swallowed (no unhandled rejection); badge stays", async () => {
  const bus = createEventBusForTesting();
  const store = makeStore(4, { reject: true });
  const r = createMissedBadgeRenderer({ eventBus: bus, stores: { missed: store } });
  const root = document.createElement("div");
  r.mount(root);
  const btn = root.querySelector<HTMLButtonElement>(".missed-reset-button");
  assert.ok(btn);
  assert.doesNotThrow(() => btn.click());
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(store.resetCalls, 1);
  // Count unchanged (store left it); the badge is still present.
  assert.ok(root.querySelector(".missed-badge"));
});

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

test("second mount without unmount throws", () => {
  const bus = createEventBusForTesting();
  const store = makeStore(0);
  const r = createMissedBadgeRenderer({ eventBus: bus, stores: { missed: store } });
  r.mount(document.createElement("div"));
  assert.throws(() => r.mount(document.createElement("div")), /already mounted/);
});

test("unmount unsubscribes (no repaint after) and clears the root; re-mount OK", () => {
  const bus = createEventBusForTesting();
  const store = makeStore(2);
  const r = createMissedBadgeRenderer({ eventBus: bus, stores: { missed: store } });
  const root = document.createElement("div");
  r.mount(root);
  assert.ok(root.querySelector(".missed-badge"));

  r.unmount();
  assert.equal(root.querySelector(".missed-badge"), null);

  // After unmount, a changed event must NOT repaint into the old root.
  store.setCount(9);
  emitChanged(bus, 9);
  assert.equal(root.querySelector(".missed-badge"), null);

  assert.doesNotThrow(() => r.mount(root));
  assert.ok(root.querySelector(".missed-badge"));
});

test("unmount before mount is a no-op (idempotent)", () => {
  const bus = createEventBusForTesting();
  const store = makeStore(0);
  const r = createMissedBadgeRenderer({ eventBus: bus, stores: { missed: store } });
  assert.doesNotThrow(() => r.unmount());
  assert.doesNotThrow(() => r.unmount());
});

test("forceRenderForTesting before mount is a no-op", () => {
  const bus = createEventBusForTesting();
  const store = makeStore(3);
  const r = createMissedBadgeRenderer({ eventBus: bus, stores: { missed: store } });
  assert.doesNotThrow(() => r.forceRenderForTesting());
});

test("forceRenderForTesting after mount repaints from current store count", () => {
  const bus = createEventBusForTesting();
  const store = makeStore(0);
  const r = createMissedBadgeRenderer({ eventBus: bus, stores: { missed: store } });
  const root = document.createElement("div");
  r.mount(root);
  store.setCount(8);
  r.forceRenderForTesting();
  assert.equal(root.querySelector(".missed-status")?.textContent, "8 missed while away");
});
