// Multiplexer Lane D (WP3 + WP11) — CommonsActivityRenderer unit tests.
// Run via `npx tsx --test src/tests/unit/multiplexer/render/commons_activity_renderer.test.ts`.
//
// Coverage target: 100% lines/branches/functions. Uses the REAL CommonsStore +
// EventBus + in-memory StorageService (integration-faithful), a stub ApiClient,
// a synchronous rafFn, and a fake ResizeObserver so the WP11 overflow-measure
// paths are deterministic.

import { test, before, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createStorageServiceForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/StorageService";
import { createCommonsStore } from "../../../../lupin_app/static/js/multiplexer/stores/CommonsStore";
import { createCommonsActivityRenderer } from "../../../../lupin_app/static/js/multiplexer/render/CommonsActivityRenderer";
import type { CommonsActivityRenderer, CommonsActivityApiClient } from "../../../../lupin_app/static/js/multiplexer/render/CommonsActivityRenderer";
import type { CommonsStore } from "../../../../lupin_app/static/js/multiplexer/stores/CommonsStore";
import type { CommonsActivityEntry } from "../../../../lupin_app/static/js/multiplexer/shared/types";
import type { EventBus } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

const TZ = "America/New_York";
const FIXED_NOW = new Date(2026, 5, 10, 14, 0, 0).getTime();

// --- Fake ResizeObserver -----------------------------------------------------
class FakeResizeObserver {
  static instances: FakeResizeObserver[] = [];
  cb: () => void;
  observed: Element[] = [];
  disconnected = false;
  constructor(cb: () => void) { this.cb = cb; FakeResizeObserver.instances.push(this); }
  observe(t: Element): void { this.observed.push(t); }
  disconnect(): void { this.disconnected = true; }
  fire(): void { this.cb(); }
}

// --- marked / DOMPurify shims ------------------------------------------------
beforeEach(() => {
  const w = globalThis as unknown as {
    marked   ?: { parse: (s: string, opts?: unknown) => string };
    DOMPurify?: { sanitize: (s: string, cfg?: unknown) => string };
    ResizeObserver?: unknown;
  };
  w.marked    = { parse: (s: string): string => `<p>${s}</p>` };
  w.DOMPurify = { sanitize: (s: string): string => s };
  FakeResizeObserver.instances = [];
  w.ResizeObserver = FakeResizeObserver as unknown;
});

afterEach(() => {
  if (globalThis.document !== undefined) document.body.replaceChildren();
});

// --- DOM scaffold ------------------------------------------------------------
interface Scaffold {
  root        : HTMLElement;
  entriesEl   : HTMLElement;
  emptyEl     : HTMLElement;
  bodyEl      : HTMLElement;
  headerEl    : HTMLElement;
  windowSel   : HTMLSelectElement;
  directionSel: HTMLSelectElement;
  kindSel     : HTMLSelectElement;
  personaSel  : HTMLSelectElement;
  refreshBtn  : HTMLButtonElement;
}

function buildScaffold(): Scaffold {
  const root = document.createElement("section");
  root.id = "commons-activity-pane";
  root.innerHTML = `
    <div id="commons-activity-header">
      <h5>Recent Activity</h5>
      <div class="commons-activity-controls">
        <select id="commons-activity-window">
          <option value="today">Today</option>
          <option value="all">All</option>
          <option value="6">6h</option>
        </select>
        <select id="commons-activity-filter-direction">
          <option value="">Any direction</option>
          <option value="sender">Sender</option>
          <option value="recipient">Recipient</option>
        </select>
        <select id="commons-activity-filter-kind">
          <option value="all">All</option>
          <option value="heartbeats">Heartbeats</option>
          <option value="personas">Personas</option>
          <option value="broadcasts">Broadcasts</option>
        </select>
        <select id="commons-activity-filter-persona"></select>
        <button id="commons-activity-refresh" type="button">⟳</button>
      </div>
    </div>
    <div id="commons-activity-body">
      <div id="commons-activity-entries"></div>
      <div id="commons-activity-empty" hidden></div>
    </div>
  `;
  document.body.appendChild(root);
  return {
    root,
    entriesEl   : root.querySelector("#commons-activity-entries") as HTMLElement,
    emptyEl     : root.querySelector("#commons-activity-empty") as HTMLElement,
    bodyEl      : root.querySelector("#commons-activity-body") as HTMLElement,
    headerEl    : root.querySelector("#commons-activity-header") as HTMLElement,
    windowSel   : root.querySelector("#commons-activity-window") as HTMLSelectElement,
    directionSel: root.querySelector("#commons-activity-filter-direction") as HTMLSelectElement,
    kindSel     : root.querySelector("#commons-activity-filter-kind") as HTMLSelectElement,
    personaSel  : root.querySelector("#commons-activity-filter-persona") as HTMLSelectElement,
    refreshBtn  : root.querySelector("#commons-activity-refresh") as HTMLButtonElement,
  };
}

// --- stub api ----------------------------------------------------------------
interface ApiState {
  history     : unknown;
  pool        : unknown;
  historyErr  : Error | null;
  poolErr     : Error | null;
  paths       : string[];
}
function makeApi(): { api: CommonsActivityApiClient; state: ApiState } {
  const state: ApiState = {
    history    : { entries: [] },
    pool       : { pool: [], active_sessions: [] },
    historyErr : null,
    poolErr    : null,
    paths      : [],
  };
  const api: CommonsActivityApiClient = {
    get: async <T>(path: string): Promise<T> => {
      state.paths.push(path);
      if (path.includes("broadcast-history")) {
        if (state.historyErr) throw state.historyErr;
        return state.history as T;
      }
      // voice-persona/pool
      if (state.poolErr) throw state.poolErr;
      return state.pool as T;
    },
  };
  return { api, state };
}

function makeEntry(over: Partial<CommonsActivityEntry> = {}): CommonsActivityEntry {
  return {
    ts            : "2026-06-10T14:05:00+00:00",
    topic         : "build-status",
    topic_kind    : "free-form",
    persona_name  : "Tiberius",
    persona_icon  : "👑",
    persona_color : "#FFD600",
    body          : "shipped",
    metadata      : {},
    ...over,
  };
}

interface Harness {
  bus      : EventBus;
  store    : CommonsStore;
  renderer : CommonsActivityRenderer;
  api      : CommonsActivityApiClient;
  state    : ApiState;
  scaffold : Scaffold;
}

function makeHarness(opts: { mount?: boolean; appTimezone?: string | undefined; storage?: ReturnType<typeof createStorageServiceForTesting> } = {}): Harness {
  const bus      = createEventBusForTesting();
  const storage  = opts.storage ?? createStorageServiceForTesting(bus);
  const store    = createCommonsStore({ bus, storage, nowFn: () => FIXED_NOW });
  const { api, state } = makeApi();
  const scaffold = buildScaffold();
  const renderer = createCommonsActivityRenderer({
    eventBus     : bus,
    stores       : { commons: store },
    api,
    appTimezone  : "appTimezone" in opts ? opts.appTimezone : TZ,
    rafFn        : (cb) => cb(),   // synchronous
  });
  if (opts.mount !== false) renderer.mount(scaffold.root);
  return { bus, store, renderer, api, state, scaffold };
}

async function flush(): Promise<void> {
  for (let i = 0; i < 4; i++) await Promise.resolve();
}

function setDims(el: Element, client: number, scroll: number): void {
  Object.defineProperty(el, "clientHeight", { value: client, configurable: true });
  Object.defineProperty(el, "scrollHeight", { value: scroll, configurable: true });
}

// ===========================================================================
// Mount guards
// ===========================================================================

test("constructor throws when stores.commons is missing", () => {
  const bus = createEventBusForTesting();
  const { api } = makeApi();
  assert.throws(
    () => createCommonsActivityRenderer({ eventBus: bus, stores: {} as never, api }),
    /requires stores\.commons/,
  );
});

test("mount throws when #commons-activity-entries is missing", () => {
  const bus = createEventBusForTesting();
  const storage = createStorageServiceForTesting(bus);
  const store = createCommonsStore({ bus, storage, nowFn: () => FIXED_NOW });
  const { api } = makeApi();
  const r = createCommonsActivityRenderer({ eventBus: bus, stores: { commons: store }, api, rafFn: (cb) => cb() });
  const bare = document.createElement("div");
  document.body.appendChild(bare);
  assert.throws(() => r.mount(bare), /#commons-activity-entries not found/);
});

test("second mount without unmount throws", () => {
  const h = makeHarness();
  assert.throws(() => h.renderer.mount(h.scaffold.root), /already mounted/);
});

// ===========================================================================
// Initial render + eager hydrate
// ===========================================================================

test("initial mount renders empty state with the window-default copy", () => {
  const h = makeHarness();
  assert.equal(h.scaffold.entriesEl.children.length, 0);
  assert.equal(h.scaffold.emptyEl.hidden, false);
  assert.equal(h.scaffold.emptyEl.textContent, "No activity in window.");
});

test("eager hydrate on mount fills the entries list (then empty hides)", async () => {
  const h = makeHarness();
  h.state.history = { entries: [makeEntry({ body: "a" }), makeEntry({ body: "b" })] };
  // mount already floated hydrate against the default empty history; re-hydrate
  // is what the floated call resolves to. Drive a fresh hydrate to be explicit.
  await h.store.hydrate(h.api, "all");
  await flush();
  assert.equal(h.scaffold.entriesEl.children.length, 2);
  assert.equal(h.scaffold.emptyEl.hidden, true);
});

test("mount fires the floated hydrate + persona-pool fetch (paths recorded)", async () => {
  const h = makeHarness();
  await flush();
  assert.ok(h.state.paths.some(p => p.includes("broadcast-history")));
  assert.ok(h.state.paths.some(p => p.includes("voice-persona/pool")));
});

test("server disabled kill-switch hides the section", async () => {
  const h = makeHarness();
  h.state.history = { disabled: true };
  await h.store.hydrate(h.api, "all");
  await flush();
  assert.equal(h.scaffold.root.hidden, true);
});

test("hydrate rejection on mount is swallowed (no throw)", async () => {
  const bus = createEventBusForTesting();
  const storage = createStorageServiceForTesting(bus);
  const store = createCommonsStore({ bus, storage, nowFn: () => FIXED_NOW });
  const { api, state } = makeApi();
  state.historyErr = new Error("boom-history");
  state.poolErr = new Error("boom-pool");
  const scaffold = buildScaffold();
  const r = createCommonsActivityRenderer({ eventBus: bus, stores: { commons: store }, api, rafFn: (cb) => cb() });
  r.mount(scaffold.root);
  await flush();   // both floated promises reject + are caught
  assert.equal(scaffold.entriesEl.children.length, 0);
});

// ===========================================================================
// Filter-changed + live prepend
// ===========================================================================

test("filter-changed re-renders the filtered list", async () => {
  const h = makeHarness();
  h.state.history = { entries: [makeEntry({ topic: "broadcasts", topic_kind: "reserved", body: "b" }), makeEntry({ topic: "dm-x", body: "d" })] };
  await h.store.hydrate(h.api, "all");
  await flush();
  assert.equal(h.scaffold.entriesEl.children.length, 2);
  h.store.setKind("broadcasts");   // emits filter-changed → renderer repaints
  assert.equal(h.scaffold.entriesEl.children.length, 1);
});

test("live prepend (matchesFilter=true) inserts a row at the head + hides empty", () => {
  const h = makeHarness();
  h.bus.emit({ type: "notification_queue_update", payload: { notification: { type: "commons_activity", payload: makeEntry({ body: "live" }) } }, source: "t", ts: 0 } as never);
  assert.equal(h.scaffold.entriesEl.children.length, 1);
  assert.equal(h.scaffold.emptyEl.hidden, true);
});

test("live prepend keeps newest at the head", () => {
  const h = makeHarness();
  const send = (b: string): void => h.bus.emit({ type: "notification_queue_update", payload: { notification: { type: "commons_activity", payload: makeEntry({ body: b }) } }, source: "t", ts: 0 } as never);
  send("first");
  send("second");
  const first = h.scaffold.entriesEl.children[0] as HTMLElement;
  assert.ok(first.querySelector(".commons-activity-entry-body-content")?.textContent?.includes("second"));
});

test("live prepend (matchesFilter=false) leaves DOM empty + shows filter-active copy", () => {
  const h = makeHarness();
  h.store.setKind("heartbeats");          // active filter
  h.bus.emit({ type: "notification_queue_update", payload: { notification: { type: "commons_activity", payload: makeEntry({ metadata: {} }) } }, source: "t", ts: 0 } as never);
  assert.equal(h.scaffold.entriesEl.children.length, 0);
  assert.equal(h.scaffold.emptyEl.textContent, "No activity matches the current filter.");
});

// ===========================================================================
// Control wiring
// ===========================================================================

test("window select change re-hydrates with the chosen window", async () => {
  const h = makeHarness();
  h.scaffold.windowSel.value = "all";
  h.scaffold.windowSel.dispatchEvent(new Event("change", { bubbles: true }));
  await flush();
  assert.equal(h.store.getWindow(), "all");
  assert.ok(h.state.paths.some(p => p === "/api/commons/broadcast-history?limit=200"));
});

test("window-change hydrate rejection is swallowed", async () => {
  const h = makeHarness();
  h.state.historyErr = new Error("nope");
  h.scaffold.windowSel.value = "6";
  h.scaffold.windowSel.dispatchEvent(new Event("change", { bubbles: true }));
  await flush();
  assert.ok(true);   // no throw
});

test("direction / kind / persona select changes update the store filter", () => {
  const h = makeHarness();
  h.scaffold.directionSel.value = "sender";
  h.scaffold.directionSel.dispatchEvent(new Event("change", { bubbles: true }));
  h.scaffold.kindSel.value = "personas";
  h.scaffold.kindSel.dispatchEvent(new Event("change", { bubbles: true }));
  h.scaffold.personaSel.innerHTML = `<option value="">Any</option><option value="rachel">Rachel</option>`;
  h.scaffold.personaSel.value = "rachel";
  h.scaffold.personaSel.dispatchEvent(new Event("change", { bubbles: true }));
  assert.deepEqual(h.store.getFilter(), { direction: "sender", kind: "personas", persona: "rachel" });
});

test("setting direction/kind/persona back to defaults clears the filter", () => {
  const h = makeHarness();
  // Set then clear via empty-string select values.
  h.scaffold.directionSel.value = "";
  h.scaffold.directionSel.dispatchEvent(new Event("change", { bubbles: true }));
  h.scaffold.kindSel.value = "all";
  h.scaffold.kindSel.dispatchEvent(new Event("change", { bubbles: true }));
  h.scaffold.personaSel.value = "";
  h.scaffold.personaSel.dispatchEvent(new Event("change", { bubbles: true }));
  assert.equal(h.store.isFilterActive(), false);
});

test("kind select cleared to empty falls back to 'all'", () => {
  const h = makeHarness();
  h.store.setKind("personas");   // make it non-default first
  // Append an empty option so the select can hold "".
  const blank = document.createElement("option");
  blank.value = "";
  h.scaffold.kindSel.appendChild(blank);
  h.scaffold.kindSel.value = "";
  h.scaffold.kindSel.dispatchEvent(new Event("change", { bubbles: true }));
  assert.equal(h.store.getFilter().kind, "all");
});

test("change event on an unrelated select id is a no-op", () => {
  const h = makeHarness();
  const stray = document.createElement("select");
  stray.id = "unrelated";
  h.scaffold.root.appendChild(stray);
  stray.dispatchEvent(new Event("change", { bubbles: true }));
  assert.equal(h.store.isFilterActive(), false);
});

test("refresh button click re-hydrates + repopulates persona dropdown", async () => {
  const h = makeHarness();
  await flush();
  const before = h.state.paths.length;
  h.scaffold.refreshBtn.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  await flush();
  const after = h.state.paths.slice(before);
  assert.ok(after.some(p => p.includes("broadcast-history")));
  assert.ok(after.some(p => p.includes("voice-persona/pool")));
});

test("header click toggles the panel-collapse class", () => {
  const h = makeHarness();
  const title = h.scaffold.headerEl.querySelector("h5") as HTMLElement;
  title.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  assert.equal(h.scaffold.bodyEl.classList.contains("collapsed"), true);
  title.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  assert.equal(h.scaffold.bodyEl.classList.contains("collapsed"), false);
});

test("click on a control inside the header does NOT toggle collapse", () => {
  const h = makeHarness();
  h.scaffold.directionSel.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  assert.equal(h.scaffold.bodyEl.classList.contains("collapsed"), false);
});

test("click on neither toggle/refresh/header is a no-op", () => {
  const h = makeHarness();
  h.scaffold.entriesEl.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  assert.equal(h.scaffold.bodyEl.classList.contains("collapsed"), false);
});

// ===========================================================================
// Show-more toggle (per-entry) — click behavior
// ===========================================================================

test("toggle click expands then collapses the content + flips label", async () => {
  const h = makeHarness();
  h.state.history = { entries: [makeEntry({ body: "long body" })] };
  await h.store.hydrate(h.api, "all");
  await flush();
  const toggle = h.scaffold.entriesEl.querySelector(".commons-activity-entry-body-toggle") as HTMLButtonElement;
  const content = h.scaffold.entriesEl.querySelector(".commons-activity-entry-body-content") as HTMLElement;
  toggle.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  assert.equal(content.classList.contains("expanded"), true);
  assert.equal(toggle.textContent, "Show less ▴");
  toggle.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  assert.equal(content.classList.contains("expanded"), false);
  assert.equal(toggle.textContent, "Show more ▾");
});

// ===========================================================================
// WP11 — overflow measurement
// ===========================================================================

test("WP11: laid-out overflowing content reveals the toggle synchronously", () => {
  const h = makeHarness();
  // Live-prepend a row, but first arrange that the NEXT rendered content
  // measures as overflowing. We can't pre-size before render, so size after.
  h.bus.emit({ type: "notification_queue_update", payload: { notification: { type: "commons_activity", payload: makeEntry({ body: "x" }) } }, source: "t", ts: 0 } as never);
  // The synchronous rafFn already ran reveal() with clientHeight 0 → RO set up.
  // Simulate layout then fire the observer.
  const content = h.scaffold.entriesEl.querySelector(".commons-activity-entry-body-content") as HTMLElement;
  const toggle  = h.scaffold.entriesEl.querySelector(".commons-activity-entry-body-toggle") as HTMLButtonElement;
  setDims(content, 32, 80);   // scrollHeight >> clientHeight → overflow
  FakeResizeObserver.instances.at(-1)?.fire();
  assert.equal(toggle.hidden, false);
  assert.equal(FakeResizeObserver.instances.at(-1)?.disconnected, true);
});

test("WP11: laid-out non-overflowing content keeps the toggle hidden (no observer)", () => {
  const h = makeHarness();
  // Pre-size the content the FIRST measure will read by intercepting render:
  // render via forceRenderForTesting after seeding the store + sizing on next tick.
  // Simplest: prepend, then re-measure path. Instead assert the synchronous
  // reveal()==true short-circuit by sizing a freshly rendered row.
  h.bus.emit({ type: "notification_queue_update", payload: { notification: { type: "commons_activity", payload: makeEntry({ body: "y" }) } }, source: "t", ts: 0 } as never);
  const content = h.scaffold.entriesEl.querySelector(".commons-activity-entry-body-content") as HTMLElement;
  const toggle  = h.scaffold.entriesEl.querySelector(".commons-activity-entry-body-toggle") as HTMLButtonElement;
  // First rAF measured clientHeight=0 → observer created. Now lay out as
  // NON-overflowing and fire: reveal() returns true (measured) but toggle stays hidden.
  setDims(content, 40, 40);
  FakeResizeObserver.instances.at(-1)?.fire();
  assert.equal(toggle.hidden, true);
  assert.equal(FakeResizeObserver.instances.at(-1)?.disconnected, true);
});

test("WP11: content already laid out + overflowing on first measure needs no observer", async () => {
  // Render an entry, then re-render via forceRenderForTesting after pre-sizing
  // a content node is impossible (fresh nodes each render). Instead: drive the
  // synchronous reveal()=true-first-try path by stubbing clientHeight on the
  // prototype so the FIRST measure already sees layout.
  const proto = (globalThis as unknown as { HTMLElement: { prototype: HTMLElement } }).HTMLElement.prototype;
  const origClient = Object.getOwnPropertyDescriptor(proto, "clientHeight");
  const origScroll = Object.getOwnPropertyDescriptor(proto, "scrollHeight");
  Object.defineProperty(proto, "clientHeight", { configurable: true, get() { return 32; } });
  Object.defineProperty(proto, "scrollHeight", { configurable: true, get() { return 90; } });
  try {
    const h = makeHarness();
    h.bus.emit({ type: "notification_queue_update", payload: { notification: { type: "commons_activity", payload: makeEntry({ body: "z" }) } }, source: "t", ts: 0 } as never);
    const toggle = h.scaffold.entriesEl.querySelector(".commons-activity-entry-body-toggle") as HTMLButtonElement;
    assert.equal(toggle.hidden, false);
    // No observer should have been created for this row's measure (reveal()=true first try).
    assert.equal(FakeResizeObserver.instances.length, 0);
  } finally {
    if (origClient) Object.defineProperty(proto, "clientHeight", origClient); else delete (proto as unknown as Record<string, unknown>)["clientHeight"];
    if (origScroll) Object.defineProperty(proto, "scrollHeight", origScroll); else delete (proto as unknown as Record<string, unknown>)["scrollHeight"];
  }
});

test("WP11: missing ResizeObserver global degrades gracefully (no throw, toggle hidden)", () => {
  const h = makeHarness();
  delete (globalThis as unknown as Record<string, unknown>)["ResizeObserver"];
  h.bus.emit({ type: "notification_queue_update", payload: { notification: { type: "commons_activity", payload: makeEntry({ body: "q" }) } }, source: "t", ts: 0 } as never);
  const toggle = h.scaffold.entriesEl.querySelector(".commons-activity-entry-body-toggle") as HTMLButtonElement;
  assert.equal(toggle.hidden, true);   // never revealed, but no crash
});

// ===========================================================================
// Persona dropdown population
// ===========================================================================

test("persona dropdown is rebuilt from the pool with icon + display name", async () => {
  const h = makeHarness();
  h.state.pool = {
    pool            : [{ name: "Tiberius", icon: "👑", display_name: "Tiberius" }, { name: "Rachel", icon: "🕊️", display_name: "Rachel" }],
    active_sessions : [{ persona_name: "Tiberius" }, { persona_name: "Rachel" }],
  };
  // Re-trigger population via refresh (mount already ran one against empty pool).
  h.scaffold.refreshBtn.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  await flush();
  const opts = Array.from(h.scaffold.personaSel.options).map(o => o.textContent);
  assert.deepEqual(opts, ["Any persona", "👑 Tiberius", "🕊️ Rachel"]);
});

test("persona dropdown skips active sessions with no persona name", async () => {
  const h = makeHarness();
  h.state.pool = { pool: [], active_sessions: [{ persona_name: "" }, { persona_name: "Sam" }] };
  h.scaffold.refreshBtn.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  await flush();
  const vals = Array.from(h.scaffold.personaSel.options).map(o => o.value);
  assert.deepEqual(vals, ["", "sam"]);   // empty-name session skipped
});

test("persona dropdown handles a pool response missing pool + active_sessions keys", async () => {
  const h = makeHarness();
  h.state.pool = {};   // neither key present → both `?? []` fallbacks fire
  h.scaffold.refreshBtn.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  await flush();
  const opts = Array.from(h.scaffold.personaSel.options).map(o => o.textContent);
  assert.deepEqual(opts, ["Any persona"]);   // only the default
});

test("persona dropdown tolerates pool entries with no name + sessions with no persona_name", async () => {
  const h = makeHarness();
  h.state.pool = {
    pool            : [{ icon: "🪨" }],                       // no `name` → `p.name ?? ""`
    active_sessions : [{ /* no persona_name */ }, { persona_name: "Arnold" }],
  };
  h.scaffold.refreshBtn.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  await flush();
  const vals = Array.from(h.scaffold.personaSel.options).map(o => o.value);
  // nameless session skipped; Arnold present (no pool meta → display falls back to the session name)
  assert.deepEqual(vals, ["", "arnold"]);
  assert.equal(h.scaffold.personaSel.options[1]?.textContent, "Arnold");
});

test("persona dropdown restores a still-valid prior selection (sticky-when-valid)", async () => {
  const bus = createEventBusForTesting();
  const storage = createStorageServiceForTesting(bus);
  // Persist a persona filter that WILL be valid in the refreshed pool.
  const seed = createCommonsStore({ bus, storage, nowFn: () => FIXED_NOW });
  seed.setPersona("rachel");
  const h = makeHarness({ storage });
  h.state.pool = { pool: [{ name: "Rachel", icon: "🕊️" }], active_sessions: [{ persona_name: "Rachel" }] };
  h.scaffold.refreshBtn.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  await flush();
  assert.equal(h.scaffold.personaSel.value, "rachel");
});

test("persona dropdown clears a now-stale prior selection (write-through to store)", async () => {
  const bus = createEventBusForTesting();
  const storage = createStorageServiceForTesting(bus);
  const seed = createCommonsStore({ bus, storage, nowFn: () => FIXED_NOW });
  seed.setPersona("ghost");   // not in the refreshed pool
  const h = makeHarness({ storage });
  h.state.pool = { pool: [{ name: "Rachel", icon: "🕊️" }], active_sessions: [{ persona_name: "Rachel" }] };
  h.scaffold.refreshBtn.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  await flush();
  assert.equal(h.store.getFilter().persona, null);
});

test("persona-pool fetch rejection is swallowed", async () => {
  const h = makeHarness();
  h.state.poolErr = new Error("pool-down");
  h.scaffold.refreshBtn.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  await flush();
  assert.ok(true);   // no throw
});

test("refresh-hydrate rejection is swallowed", async () => {
  const h = makeHarness();
  await flush();
  h.state.historyErr = new Error("history-down");
  h.scaffold.refreshBtn.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  await flush();
  assert.ok(true);   // refresh hydrate rejected + caught, no throw
});

// ===========================================================================
// Control restoration from persisted state
// ===========================================================================

test("mount restores control values from the persisted store filter", () => {
  const bus = createEventBusForTesting();
  const storage = createStorageServiceForTesting(bus);
  const seed = createCommonsStore({ bus, storage, nowFn: () => FIXED_NOW });
  seed.setDirection("recipient");
  seed.setKind("personas");
  // persona option must exist for the select to take the value
  const h = makeHarness({ storage });
  // The persona select had no matching option at mount, so its value is "".
  assert.equal(h.scaffold.directionSel.value, "recipient");
  assert.equal(h.scaffold.kindSel.value, "personas");
  assert.equal(h.scaffold.windowSel.value, "today");
});

// ===========================================================================
// Lenient scaffold (optional elements absent)
// ===========================================================================

test("renders with a minimal scaffold (only the entries container present)", () => {
  const bus = createEventBusForTesting();
  const storage = createStorageServiceForTesting(bus);
  const store = createCommonsStore({ bus, storage, nowFn: () => FIXED_NOW });
  const { api } = makeApi();
  const root = document.createElement("section");
  root.innerHTML = `<div id="commons-activity-entries"></div>`;
  document.body.appendChild(root);
  const r = createCommonsActivityRenderer({ eventBus: bus, stores: { commons: store }, api, rafFn: (cb) => cb() });
  r.mount(root);
  // Live prepend works even without empty/header/body/selects.
  bus.emit({ type: "notification_queue_update", payload: { notification: { type: "commons_activity", payload: makeEntry({ body: "m" }) } }, source: "t", ts: 0 } as never);
  assert.equal(root.querySelector("#commons-activity-entries")?.children.length, 1);
  r.unmount();
});

test("default options (no appTimezone, no rafFn) construct + render without throwing", () => {
  const bus = createEventBusForTesting();
  const storage = createStorageServiceForTesting(bus);
  const store = createCommonsStore({ bus, storage, nowFn: () => FIXED_NOW });
  const { api } = makeApi();
  const root = document.createElement("section");
  root.innerHTML = `<div id="commons-activity-entries"></div>`;
  document.body.appendChild(root);
  // No appTimezone, default rafFn (real requestAnimationFrame in happy-dom).
  const r = createCommonsActivityRenderer({ eventBus: bus, stores: { commons: store }, api });
  r.mount(root);
  r.forceRenderForTesting();
  r.unmount();
  assert.ok(true);
});

// ===========================================================================
// Unmount
// ===========================================================================

test("unmount unsubscribes, disconnects observers, clears entries, and is idempotent", () => {
  const h = makeHarness();
  h.bus.emit({ type: "notification_queue_update", payload: { notification: { type: "commons_activity", payload: makeEntry({ body: "live" }) } }, source: "t", ts: 0 } as never);
  assert.equal(h.scaffold.entriesEl.children.length, 1);
  const ro = FakeResizeObserver.instances.at(-1);
  h.renderer.unmount();
  assert.equal(h.scaffold.entriesEl.children.length, 0);
  assert.equal(ro?.disconnected, true);
  // Post-unmount events do nothing.
  h.bus.emit({ type: "notification_queue_update", payload: { notification: { type: "commons_activity", payload: makeEntry() } }, source: "t", ts: 0 } as never);
  assert.equal(h.scaffold.entriesEl.children.length, 0);
  // Idempotent second unmount.
  h.renderer.unmount();
  assert.ok(true);
});

test("persona dropdown population that resolves AFTER unmount is a no-op", async () => {
  const h = makeHarness();
  h.state.pool = { pool: [{ name: "Rachel" }], active_sessions: [{ persona_name: "Rachel" }] };
  h.scaffold.refreshBtn.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  h.renderer.unmount();   // unmount before the pool fetch resolves
  await flush();
  assert.ok(true);   // late resolve hit the null-guard, no throw
});
