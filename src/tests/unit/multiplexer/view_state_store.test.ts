// Multiplexer section-toolbar / accordion-collapse parity — ViewStateStore unit
// tests. Run via `npx tsx --test src/tests/unit/multiplexer/view_state_store.test.ts`.
//
// Target: 100% lines / branches / functions on ViewStateStore.ts per the
// project 100% COVERAGE MANDATE. No DOM (the store is pure state).

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createStorageServiceForTesting, InMemoryStorage } from "../../../lupin_app/static/js/multiplexer/shared/StorageService";
import type { StorageService } from "../../../lupin_app/static/js/multiplexer/shared/StorageService";
import { createViewStateStore } from "../../../lupin_app/static/js/multiplexer/stores/ViewStateStore";
import type { LupinEvent, StoreViewStateChangedPayload, ViewStateChangeKind } from "../../../lupin_app/static/js/multiplexer/shared/types";

// Persistence keys (mirror the store's private constants).
const SECTION_KEY   = "view_state_section_visibility";
const ACCORDION_KEY = "view_state_accordion_collapsed";
const SCHEMA        = 1;

function setup(seed?: (storage: StorageService) => void) {
  const bus     = createEventBusForTesting();
  const backend = new InMemoryStorage();
  const storage = createStorageServiceForTesting(bus, backend);
  if (seed) seed(storage);

  const changes: ViewStateChangeKind[] = [];
  bus.on<StoreViewStateChangedPayload>(
    "store_view_state_changed",
    (e: LupinEvent<StoreViewStateChangedPayload>) => changes.push(e.payload.changeKind),
  );

  const store = createViewStateStore({ bus, storage });
  return { bus, backend, storage, store, changes };
}

// ===========================================================================
// 1 — Defaults (no persisted state)
// ===========================================================================

test("defaults: all sections visible, all accordions expanded, no hidden ids", () => {
  const { store } = setup();
  assert.equal(store.isSectionVisible("notifications-pane"), true);
  assert.equal(store.isSectionVisible("anything-unknown"), true);
  assert.equal(store.isAccordionCollapsed("sender::x"), false);
  assert.deepEqual(store.getHiddenSectionIds(), []);
});

// ===========================================================================
// 2 — Section visibility: toggle + persist + getHiddenSectionIds
// ===========================================================================

test("setSectionVisible(false) hides + persists + lists; true restores", () => {
  const { store, backend } = setup();

  store.setSectionVisible("jobs-pane", false);
  assert.equal(store.isSectionVisible("jobs-pane"), false);
  assert.deepEqual(store.getHiddenSectionIds(), ["jobs-pane"]);

  // Persisted envelope present under the prefixed key.
  const raw = backend.getItem("lupin:" + SECTION_KEY);
  assert.ok(raw !== null);
  assert.equal(JSON.parse(raw).payload.sections["jobs-pane"], false);

  store.setSectionVisible("jobs-pane", true);
  assert.equal(store.isSectionVisible("jobs-pane"), true);
  assert.deepEqual(store.getHiddenSectionIds(), []);
});

test("getHiddenSectionIds returns only the explicitly-hidden ids", () => {
  const { store } = setup();
  store.setSectionVisible("a", false);
  store.setSectionVisible("b", true);
  store.setSectionVisible("c", false);
  assert.deepEqual(store.getHiddenSectionIds().sort(), ["a", "c"]);
});

test("hasSectionPreference: true only for an explicit preference (visible OR hidden), false otherwise", () => {
  const { store } = setup();
  assert.equal(store.hasSectionPreference("jobs-pane"), false);   // no preference → cold default applies
  store.setSectionVisible("jobs-pane", true);
  assert.equal(store.hasSectionPreference("jobs-pane"), true);    // explicit VISIBLE preference
  store.setSectionVisible("tts-pane", false);
  assert.equal(store.hasSectionPreference("tts-pane"), true);     // explicit HIDDEN preference
  assert.equal(store.hasSectionPreference("never-touched"), false);
});

// ===========================================================================
// 3 — Accordion collapse: toggle + persist
// ===========================================================================

test("setAccordionCollapsed(true) collapses + persists; false expands", () => {
  const { store, backend } = setup();

  store.setAccordionCollapsed("date::sess#ab::2026-06-23", true);
  assert.equal(store.isAccordionCollapsed("date::sess#ab::2026-06-23"), true);

  const raw = backend.getItem("lupin:" + ACCORDION_KEY);
  assert.ok(raw !== null);
  assert.equal(JSON.parse(raw).payload.accordions["date::sess#ab::2026-06-23"], true);

  store.setAccordionCollapsed("date::sess#ab::2026-06-23", false);
  assert.equal(store.isAccordionCollapsed("date::sess#ab::2026-06-23"), false);
});

// ===========================================================================
// 4 — Bulk intent emits (the ONLY emission)
// ===========================================================================

test("requestBulkAccordionCollapse(true) emits collapse-all; false emits expand-all", () => {
  const { store, changes } = setup();
  store.requestBulkAccordionCollapse(true);
  store.requestBulkAccordionCollapse(false);
  assert.deepEqual(changes, ["collapse-all", "expand-all"]);
});

test("per-section + per-accordion setters do NOT emit (silent persistence)", () => {
  const { store, changes } = setup();
  store.setSectionVisible("jobs-pane", false);
  store.setAccordionCollapsed("sender::x", true);
  assert.deepEqual(changes, []);
});

// ===========================================================================
// 5 — Hydration from persisted state
// ===========================================================================

test("hydrate replays persisted section-visibility + accordion-collapse maps", () => {
  const { store } = setup((storage) => {
    storage.setJSON(SECTION_KEY,   { sections:   { "jobs-pane": false, "tts-pane": true } }, SCHEMA);
    storage.setJSON(ACCORDION_KEY, { accordions: { "sender::x": true } },                    SCHEMA);
  });
  assert.equal(store.isSectionVisible("jobs-pane"), false);
  assert.equal(store.isSectionVisible("tts-pane"), true);
  assert.deepEqual(store.getHiddenSectionIds(), ["jobs-pane"]);
  assert.equal(store.isAccordionCollapsed("sender::x"), true);
});

test("hydrate coerces a corrupt map: non-boolean entries are dropped to default", () => {
  const { store } = setup((storage) => {
    // "b" is a string → dropped; only genuine booleans survive.
    storage.setJSON(SECTION_KEY, { sections: { a: true, b: "nope", c: false } }, SCHEMA);
  });
  assert.equal(store.isSectionVisible("a"), true);   // explicit true
  assert.equal(store.isSectionVisible("b"), true);   // dropped → default visible
  assert.equal(store.isSectionVisible("c"), false);  // explicit false survives
  assert.deepEqual(store.getHiddenSectionIds(), ["c"]);
});

test("hydrate degrades a non-object `sections` payload to empty (string)", () => {
  const { store } = setup((storage) => {
    storage.setJSON(SECTION_KEY, { sections: "garbage" }, SCHEMA);
  });
  assert.deepEqual(store.getHiddenSectionIds(), []);
  assert.equal(store.isSectionVisible("anything"), true);
});

test("hydrate degrades a null `accordions` payload to empty", () => {
  const { store } = setup((storage) => {
    storage.setJSON(ACCORDION_KEY, { accordions: null }, SCHEMA);
  });
  assert.equal(store.isAccordionCollapsed("anything"), false);
});
