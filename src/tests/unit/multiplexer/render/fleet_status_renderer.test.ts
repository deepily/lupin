// Multiplexer Lane E WP12 — FleetStatusRenderer unit tests.
// 100% lines/branches/functions per the multiplexer coverage mandate.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createFleetStatusRenderer,
  type FleetStoreLike,
} from "../../../../lupin_app/static/js/multiplexer/render/FleetStatusRenderer";
import type { FleetComposite } from "../../../../lupin_app/static/js/multiplexer/render/fleetModel";
import type { StoreFleetStatusChangedPayload } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

interface FakeStore extends FleetStoreLike {
  setComposite(c: FleetComposite | null): void;
  setShowOffline(b: boolean): void;
  refreshCalls: number;
  toggleCalls: number;
}

function makeStore(): FakeStore {
  let composite: FleetComposite | null = null;
  let showOffline = false;
  const store: FakeStore = {
    refreshCalls: 0,
    toggleCalls: 0,
    composite: () => composite,
    showOfflineFlag: () => showOffline,
    refresh: async (): Promise<void> => { store.refreshCalls += 1; },
    toggleShowOffline: (): void => { store.toggleCalls += 1; showOffline = !showOffline; },
    setComposite: (c) => { composite = c; },
    setShowOffline: (b) => { showOffline = b; },
  };
  return store;
}

const FIXED_DATE = (): Date => new Date("2026-06-10T18:30:07Z");

function setup(): {
  bus: ReturnType<typeof createEventBusForTesting>;
  store: FakeStore;
  root: HTMLElement;
  emit: (stampUpdated: boolean) => void;
} {
  const bus = createEventBusForTesting();
  const store = makeStore();
  const r = createFleetStatusRenderer({ eventBus: bus, stores: { fleet: store }, nowDateFn: FIXED_DATE });
  const root = document.createElement("div");
  r.mount(root);
  const emit = (stampUpdated: boolean): void => {
    bus.emit<StoreFleetStatusChangedPayload>({
      type: "store_fleet_status_changed", payload: { stampUpdated }, source: "test", ts: 0,
    });
  };
  return { bus, store, root, emit };
}

const goodSessions = (sessions: FleetComposite["fleet_arbiter"]): FleetComposite => ({
  app_timezone: "America/New_York",
  fleet_arbiter: sessions,
});

// ---------------------------------------------------------------------------
// Chrome + initial paint
// ---------------------------------------------------------------------------

test("mount builds chrome (Lane 0a section-header: title, count, refresh, updated, container)", () => {
  const { root } = setup();
  // Lane 0a — the bespoke .fleet-status-header is now the uniform .section-header
  // bar; the title lives in its <h3> (🛰️ Fleet Status), count in the shared
  // .section-header-count chip. Refresh/updated/container classes are preserved.
  const header = root.querySelector(".section-header") as HTMLElement;
  assert.ok(header, "section-header bar present");
  assert.ok(header.querySelector("h3")!.textContent!.includes("🛰️ Fleet Status"), "title in h3");
  assert.ok(root.querySelector(".section-header-count"));
  assert.ok(root.querySelector(".fleet-status-refresh"));
  assert.ok(root.querySelector(".fleet-status-updated"));
  assert.ok(root.querySelector(".fleet-status-container"));
  // The container is the collapsible body (carries .section-content).
  assert.ok(root.querySelector(".section-content.fleet-status-container"), "container is the section-content body");
});

test("initial paint with null composite → arbiter-offline banner, count 0", () => {
  const { root } = setup();
  assert.ok(root.querySelector(".fleet-status-offline"));
  assert.equal(root.querySelector(".section-header-count")?.textContent, "0");
  assert.equal(root.querySelector(".fleet-status-updated")?.textContent, ""); // no stamp on initial
});

// ---------------------------------------------------------------------------
// The four §6.4 states
// ---------------------------------------------------------------------------

test("auth_required → sign-in message; count 0; no stamp", () => {
  const { store, root, emit } = setup();
  store.setComposite({ status: "auth_required" });
  emit(true);
  assert.ok(root.querySelector(".fleet-status-signin"));
  assert.equal(root.querySelector(".section-header-count")?.textContent, "0");
  assert.equal(root.querySelector(".fleet-status-updated")?.textContent, "");
});

test("unreachable status → arbiter-offline banner", () => {
  const { store, root, emit } = setup();
  store.setComposite({ status: "unreachable", fleet_arbiter: null });
  emit(true);
  assert.ok(root.querySelector(".fleet-status-offline"));
});

test("good composite with no fleet_arbiter → offline banner", () => {
  const { store, root, emit } = setup();
  store.setComposite({ app_timezone: "UTC" }); // fleet_arbiter undefined
  emit(true);
  assert.ok(root.querySelector(".fleet-status-offline"));
});

test("empty sessions → 'No active sessions', no toggle, stamp set", () => {
  const { store, root, emit } = setup();
  store.setComposite(goodSessions({ sessions: [] }));
  emit(true);
  const msg = root.querySelector(".fleet-status-empty");
  assert.equal(msg?.textContent, "No active sessions.");
  assert.ok( root.querySelector(".fleet-offline-toggle") === null );
  assert.match(root.querySelector(".fleet-status-updated")!.textContent!, /^updated \d{2}:\d{2}:\d{2}/);
});

test("fleet_arbiter present but sessions undefined → 'No active sessions' (|| [] fallback)", () => {
  const { store, root, emit } = setup();
  store.setComposite({ app_timezone: "UTC", fleet_arbiter: {} }); // sessions undefined
  emit(true);
  assert.equal(root.querySelector(".fleet-status-empty")?.textContent, "No active sessions.");
});

test("context_pressure.personas joins % Window + Window into the table", () => {
  const { store, root, emit } = setup();
  const composite: FleetComposite = {
    app_timezone : "UTC",
    fleet_arbiter: { sessions: [{ persona: "Tiberius", role: "manager", liveness: { verdict: "live" } }] },
    context_pressure: { personas: { Tiberius: { consumption_pct_of_window: 33.3, window_size: 200000 } } },
  };
  store.setComposite(composite);
  emit(true);
  // Scope to tbody — the thead <th> shares the .fleet-col-window-pct class.
  assert.equal(root.querySelector("tbody .fleet-col-window-pct")?.textContent, "33.3%");
  assert.equal(root.querySelector("tbody .fleet-col-window")?.textContent, "200K");
});

test("populated live sessions → table; count reflects visible; stamp set", () => {
  const { store, root, emit } = setup();
  store.setComposite(goodSessions({ sessions: [
    { persona: "Tiberius", role: "manager", liveness: { verdict: "live" } },
    { persona: "Rachel", role: "worker", manager: "Tiberius", liveness: { verdict: "live" } },
  ] }));
  emit(true);
  assert.ok(root.querySelector(".fleet-status-table"));
  assert.equal(root.querySelector(".section-header-count")?.textContent, "2");
});

test("all sessions offline + hidden → toggle + 'No live sessions'; count 0", () => {
  const { store, root, emit } = setup();
  store.setComposite(goodSessions({ sessions: [
    { persona: "Dead1", role: "worker", liveness: { verdict: "offline" } },
    { persona: "Dead2", role: "worker", liveness: { verdict: "offline" } },
  ] }));
  emit(true);
  assert.ok(root.querySelector(".fleet-offline-toggle"));
  assert.equal(root.querySelector(".fleet-status-empty")?.textContent, "No live sessions.");
  assert.equal(root.querySelector(".section-header-count")?.textContent, "0");
});

test("showOffline=true reveals offline rows in the table + 'Hide offline' label", () => {
  const { store, root, emit } = setup();
  store.setShowOffline(true);
  store.setComposite(goodSessions({ sessions: [
    { persona: "Live1", role: "manager", liveness: { verdict: "live" } },
    { persona: "Dead1", role: "worker", liveness: { verdict: "offline" } },
  ] }));
  emit(true);
  assert.ok(root.querySelector(".fleet-status-table"));
  assert.equal(root.querySelector(".section-header-count")?.textContent, "2"); // both visible
  assert.match(root.querySelector(".fleet-offline-toggle-btn")!.textContent!, /Hide offline \(1\)/);
});

// ---------------------------------------------------------------------------
// Wiring
// ---------------------------------------------------------------------------

test("refresh button click invokes store.refresh()", () => {
  const { store, root } = setup();
  root.querySelector<HTMLButtonElement>(".fleet-status-refresh")!.click();
  assert.equal(store.refreshCalls, 1);
});

test("offline-toggle button click invokes store.toggleShowOffline()", () => {
  const { store, root, emit } = setup();
  store.setComposite(goodSessions({ sessions: [
    { persona: "Live1", role: "manager", liveness: { verdict: "live" } },
    { persona: "Dead1", role: "worker", liveness: { verdict: "offline" } },
  ] }));
  emit(true);
  root.querySelector<HTMLButtonElement>(".fleet-offline-toggle-btn")!.click();
  assert.equal(store.toggleCalls, 1);
});

test("stampUpdated=false does NOT re-stamp the updated label", () => {
  const { store, root, emit } = setup();
  store.setComposite(goodSessions({ sessions: [{ persona: "A", role: "manager", liveness: { verdict: "live" } }] }));
  emit(true);
  const stamped = root.querySelector(".fleet-status-updated")!.textContent;
  assert.match(stamped!, /^updated /);
  // A view toggle re-render (stampUpdated=false) keeps the old stamp.
  emit(false);
  assert.equal(root.querySelector(".fleet-status-updated")!.textContent, stamped);
});

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

test("second mount without unmount throws", () => {
  const bus = createEventBusForTesting();
  const store = makeStore();
  const r = createFleetStatusRenderer({ eventBus: bus, stores: { fleet: store } });
  r.mount(document.createElement("div"));
  assert.throws(() => r.mount(document.createElement("div")), /already mounted/);
});

test("unmount unsubscribes + clears; later events do not repaint; re-mount OK", () => {
  const bus = createEventBusForTesting();
  const store = makeStore();
  const r = createFleetStatusRenderer({ eventBus: bus, stores: { fleet: store }, nowDateFn: FIXED_DATE });
  const root = document.createElement("div");
  r.mount(root);
  assert.ok(root.querySelector(".fleet-status-container"));
  r.unmount();
  assert.ok( root.querySelector(".fleet-status-container") === null );

  store.setComposite(goodSessions({ sessions: [{ persona: "A", role: "manager" }] }));
  bus.emit<StoreFleetStatusChangedPayload>({ type: "store_fleet_status_changed", payload: { stampUpdated: true }, source: "t", ts: 0 });
  assert.ok( root.querySelector(".fleet-status-table") === null ); // no repaint after unmount

  assert.doesNotThrow(() => r.mount(root));
});

test("unmount before mount is a no-op (idempotent)", () => {
  const bus = createEventBusForTesting();
  const store = makeStore();
  const r = createFleetStatusRenderer({ eventBus: bus, stores: { fleet: store } });
  assert.doesNotThrow(() => r.unmount());
  assert.doesNotThrow(() => r.unmount());
});

test("forceRenderForTesting before mount is a no-op; after mount stamps", () => {
  const bus = createEventBusForTesting();
  const store = makeStore();
  const r = createFleetStatusRenderer({ eventBus: bus, stores: { fleet: store }, nowDateFn: FIXED_DATE });
  assert.doesNotThrow(() => r.forceRenderForTesting());
  const root = document.createElement("div");
  r.mount(root);
  store.setComposite(goodSessions({ sessions: [{ persona: "A", role: "manager", liveness: { verdict: "live" } }] }));
  r.forceRenderForTesting();
  assert.match(root.querySelector(".fleet-status-updated")!.textContent!, /^updated /);
});
