// Multiplexer WP4 — ReadingPaneStore unit tests.
// Run via `npx tsx --test src/tests/unit/multiplexer/reading_pane_store.test.ts`.
//
// Target: 100% lines / branches / functions on ReadingPaneStore.ts per the
// project 100% COVERAGE MANDATE. No DOM required (the store is pure state) —
// no happy-dom registration needed.

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createStorageServiceForTesting, InMemoryStorage } from "../../../lupin_app/static/js/multiplexer/shared/StorageService";
import type { StorageService } from "../../../lupin_app/static/js/multiplexer/shared/StorageService";
import { createReadingPaneStore } from "../../../lupin_app/static/js/multiplexer/stores/ReadingPaneStore";
import type {
  LupinEvent,
  ReadingPaneChangeKind,
  StoreReadingPaneChangedPayload,
} from "../../../lupin_app/static/js/multiplexer/shared/types";

// ---------------------------------------------------------------------------
// Setup helper — fresh bus + storage + store per test; captures emissions.
// ---------------------------------------------------------------------------

function setup(seed?: (storage: StorageService) => void) {
  const bus     = createEventBusForTesting();
  const backend = new InMemoryStorage();
  const storage = createStorageServiceForTesting(bus, backend);
  if (seed) seed(storage);

  const changes: ReadingPaneChangeKind[] = [];
  bus.on<StoreReadingPaneChangedPayload>(
    "store_reading_pane_changed",
    (e: LupinEvent<StoreReadingPaneChangedPayload>) => changes.push(e.payload.changeKind),
  );

  const store = createReadingPaneStore({ bus, storage });
  return { bus, backend, storage, store, changes };
}

// Persistence keys (mirror the store's private constants).
const LAYOUT_MODE_KEY = "reading_pane_layout_mode";
const SPLIT_RATIO_KEY = "reading_pane_split_ratio";

// ===========================================================================
// 1 — Defaults (no persisted state)
// ===========================================================================

test("defaults: vertical mode, 0.667 ratio, empty history, pane closed", () => {
  const { store } = setup();
  assert.equal(store.getLayoutMode(), "vertical");
  assert.equal(store.getSplitRatio(), 0.667);
  assert.deepEqual(store.getHistory(), []);
  assert.equal(store.currentEntry(), null);
  assert.equal(store.isPaneOpen(), false);
  assert.equal(store.isActionRequiredInPane(), false);
  assert.equal(store.canGoBack(), false);
});

// ===========================================================================
// 2 — Hydration branches
// ===========================================================================

test("hydrate: persisted horizontal mode is replayed", () => {
  const { store } = setup((s) => s.setJSON(LAYOUT_MODE_KEY, { mode: "horizontal" }, 1));
  assert.equal(store.getLayoutMode(), "horizontal");
});

test("hydrate: persisted vertical mode is replayed", () => {
  const { store } = setup((s) => s.setJSON(LAYOUT_MODE_KEY, { mode: "vertical" }, 1));
  assert.equal(store.getLayoutMode(), "vertical");
});

test("hydrate: invalid persisted mode falls back to vertical", () => {
  const { store } = setup((s) => s.setJSON(LAYOUT_MODE_KEY, { mode: "diagonal" as unknown as "vertical" }, 1));
  assert.equal(store.getLayoutMode(), "vertical");
});

test("hydrate: valid persisted ratio is replayed", () => {
  const { store } = setup((s) => s.setJSON(SPLIT_RATIO_KEY, { ratio: 0.5 }, 1));
  assert.equal(store.getSplitRatio(), 0.5);
});

test("hydrate: out-of-range ratio (too high) falls back to default", () => {
  const { store } = setup((s) => s.setJSON(SPLIT_RATIO_KEY, { ratio: 0.95 }, 1));
  assert.equal(store.getSplitRatio(), 0.667);
});

test("hydrate: out-of-range ratio (too low) falls back to default", () => {
  const { store } = setup((s) => s.setJSON(SPLIT_RATIO_KEY, { ratio: 0.1 }, 1));
  assert.equal(store.getSplitRatio(), 0.667);
});

test("hydrate: non-number ratio (typeof guard) falls back to default", () => {
  const { store } = setup((s) => s.setJSON(SPLIT_RATIO_KEY, { ratio: "wide" as unknown as number }, 1));
  assert.equal(store.getSplitRatio(), 0.667);
});

// ===========================================================================
// 3 — open()
// ===========================================================================

test("open: pushes an abstract entry, pane opens, emits 'opened'", () => {
  const { store, changes } = setup();
  const ok = store.open("abstract", "**hi**", "Greeting");
  assert.equal(ok, true);
  assert.equal(store.isPaneOpen(), true);
  assert.deepEqual(store.currentEntry(), { type: "abstract", payload: "**hi**", title: "Greeting" });
  assert.deepEqual(changes, ["opened"]);
});

test("open: empty title is coerced to empty string", () => {
  const { store } = setup();
  store.open("doc", "/app/docs?path=lupin/x.md", "");
  assert.equal(store.currentEntry()?.title, "");
});

test("open: depth-caps the history stack at 10 (oldest dropped)", () => {
  const { store } = setup();
  for (let i = 0; i < 12; i++) store.open("abstract", `a${i}`, `t${i}`);
  const hist = store.getHistory();
  assert.equal(hist.length, 10);
  // Oldest two (a0, a1) dropped; newest is a11.
  assert.equal(hist[0]?.payload, "a2");
  assert.equal(hist[hist.length - 1]?.payload, "a11");
});

test("open: suppressed (returns false, no push) while AR owns the pane", () => {
  const { store, changes } = setup((s) => s.setJSON(LAYOUT_MODE_KEY, { mode: "horizontal" }, 1));
  store.enterActionRequiredPane();
  changes.length = 0;
  const ok = store.open("abstract", "blocked", "x");
  assert.equal(ok, false);
  assert.equal(store.currentEntry(), null);
  assert.deepEqual(changes, []);
});

// ===========================================================================
// 4 — close()
// ===========================================================================

test("close: clears history, hides pane, emits 'closed'", () => {
  const { store, changes } = setup();
  store.open("abstract", "x", "t");
  changes.length = 0;
  store.close();
  assert.deepEqual(store.getHistory(), []);
  assert.equal(store.isPaneOpen(), false);
  assert.deepEqual(changes, ["closed"]);
});

// ===========================================================================
// 5 — back()
// ===========================================================================

test("back: at depth 1 is a no-op (returns false, no emit)", () => {
  const { store, changes } = setup();
  store.open("abstract", "only", "t");
  changes.length = 0;
  assert.equal(store.back(), false);
  assert.deepEqual(changes, []);
  assert.equal(store.currentEntry()?.payload, "only");
});

test("back: pops one entry and shows the prior one", () => {
  const { store, changes } = setup();
  store.open("abstract", "first", "t1");
  store.open("doc", "second", "t2");
  assert.equal(store.canGoBack(), true);
  changes.length = 0;
  assert.equal(store.back(), true);
  assert.equal(store.currentEntry()?.payload, "first");
  assert.equal(store.canGoBack(), false);
  assert.deepEqual(changes, ["back"]);
});

// ===========================================================================
// 6 — toggleLayoutMode()
// ===========================================================================

test("toggle: vertical → horizontal, persisted, emits 'layout-mode'", () => {
  const { store, storage, changes } = setup();
  const next = store.toggleLayoutMode();
  assert.equal(next, "horizontal");
  assert.equal(store.getLayoutMode(), "horizontal");
  assert.deepEqual(storage.getJSON(LAYOUT_MODE_KEY, 1), { mode: "horizontal" });
  assert.deepEqual(changes, ["layout-mode"]);
});

test("toggle: horizontal → vertical closes pane (clears history)", () => {
  const { store } = setup((s) => s.setJSON(LAYOUT_MODE_KEY, { mode: "horizontal" }, 1));
  store.open("abstract", "x", "t");
  assert.equal(store.isPaneOpen(), true);
  store.toggleLayoutMode();
  assert.equal(store.getLayoutMode(), "vertical");
  assert.equal(store.isPaneOpen(), false);
  assert.deepEqual(store.getHistory(), []);
});

test("toggle: horizontal → vertical while AR-in-pane exits AR + restores ratio", () => {
  const { store } = setup((s) => {
    s.setJSON(LAYOUT_MODE_KEY, { mode: "horizontal" }, 1);
    s.setJSON(SPLIT_RATIO_KEY, { ratio: 0.7 }, 1);
  });
  store.enterActionRequiredPane();
  assert.equal(store.getSplitRatio(), 0.5);     // forced 50/50
  assert.equal(store.isActionRequiredInPane(), true);
  store.toggleLayoutMode();                       // → vertical
  assert.equal(store.isActionRequiredInPane(), false);
  assert.equal(store.getSplitRatio(), 0.7);       // restored prior ratio
  assert.equal(store.isPaneOpen(), false);
});

// ===========================================================================
// 7 — setSplitRatio() clamping
// ===========================================================================

test("setSplitRatio: in-range value is stored, persisted, emits 'ratio'", () => {
  const { store, storage, changes } = setup();
  store.setSplitRatio(0.55);
  assert.equal(store.getSplitRatio(), 0.55);
  assert.deepEqual(storage.getJSON(SPLIT_RATIO_KEY, 1), { ratio: 0.55 });
  assert.deepEqual(changes, ["ratio"]);
});

test("setSplitRatio: below min clamps to 0.30", () => {
  const { store } = setup();
  store.setSplitRatio(0.05);
  assert.equal(store.getSplitRatio(), 0.30);
});

test("setSplitRatio: above max clamps to 0.85", () => {
  const { store } = setup();
  store.setSplitRatio(0.99);
  assert.equal(store.getSplitRatio(), 0.85);
});

// ===========================================================================
// 8 — enter/exitActionRequiredPane()
// ===========================================================================

test("enterAR: no-op in vertical mode (returns false)", () => {
  const { store, changes } = setup();   // default vertical
  assert.equal(store.enterActionRequiredPane(), false);
  assert.equal(store.isActionRequiredInPane(), false);
  assert.deepEqual(changes, []);
});

test("enterAR: lifts @50/50 in horizontal, stashes prior ratio, emits 'ar-enter'", () => {
  const { store, changes } = setup((s) => {
    s.setJSON(LAYOUT_MODE_KEY, { mode: "horizontal" }, 1);
    s.setJSON(SPLIT_RATIO_KEY, { ratio: 0.72 }, 1);
  });
  changes.length = 0;
  const ok = store.enterActionRequiredPane();
  assert.equal(ok, true);
  assert.equal(store.getSplitRatio(), 0.5);
  assert.equal(store.isActionRequiredInPane(), true);
  assert.equal(store.isPaneOpen(), true);     // AR owns pane even with empty history
  assert.deepEqual(changes, ["ar-enter"]);
});

test("enterAR: second call is a no-op (already lifted)", () => {
  const { store } = setup((s) => s.setJSON(LAYOUT_MODE_KEY, { mode: "horizontal" }, 1));
  assert.equal(store.enterActionRequiredPane(), true);
  assert.equal(store.enterActionRequiredPane(), false);
});

test("exitAR: restores stashed ratio, clears flag, emits 'ar-exit'", () => {
  const { store, changes } = setup((s) => {
    s.setJSON(LAYOUT_MODE_KEY, { mode: "horizontal" }, 1);
    s.setJSON(SPLIT_RATIO_KEY, { ratio: 0.72 }, 1);
  });
  store.enterActionRequiredPane();
  changes.length = 0;
  const ok = store.exitActionRequiredPane();
  assert.equal(ok, true);
  assert.equal(store.getSplitRatio(), 0.72);
  assert.equal(store.isActionRequiredInPane(), false);
  assert.deepEqual(changes, ["ar-exit"]);
});

test("exitAR: no-op when AR does not own the pane (returns false)", () => {
  const { store, changes } = setup();
  assert.equal(store.exitActionRequiredPane(), false);
  assert.deepEqual(changes, []);
});

// ===========================================================================
// 9 — isAbstractShown() toggle predicate
// ===========================================================================

test("isAbstractShown: true only for the exact abstract currently on top", () => {
  const { store } = setup();
  store.open("abstract", "ABSTRACT-A", "t");
  assert.equal(store.isAbstractShown("ABSTRACT-A"), true);
  assert.equal(store.isAbstractShown("ABSTRACT-B"), false);
});

test("isAbstractShown: false when the top entry is a doc", () => {
  const { store } = setup();
  store.open("doc", "/app/docs?path=lupin/x.md", "t");
  assert.equal(store.isAbstractShown("/app/docs?path=lupin/x.md"), false);
});

test("isAbstractShown: false when pane empty", () => {
  const { store } = setup();
  assert.equal(store.isAbstractShown("anything"), false);
});

test("isAbstractShown: false while AR owns the pane (falls through to open)", () => {
  const { store } = setup((s) => s.setJSON(LAYOUT_MODE_KEY, { mode: "horizontal" }, 1));
  store.open("abstract", "A", "t");
  store.exitActionRequiredPane();   // not in AR yet → no-op
  store.enterActionRequiredPane();
  assert.equal(store.isAbstractShown("A"), false);
});

// ===========================================================================
// 10 — getHistory()/currentEntry() return defensive copies
// ===========================================================================

test("getHistory + currentEntry return copies (no internal mutation leak)", () => {
  const { store } = setup();
  store.open("abstract", "x", "t");
  const hist = store.getHistory();
  (hist[0] as { payload: string }).payload = "MUTATED";
  const cur = store.currentEntry();
  (cur as { payload: string }).payload = "ALSO-MUTATED";
  assert.equal(store.currentEntry()?.payload, "x");
});
