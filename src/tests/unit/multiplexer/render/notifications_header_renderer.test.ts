// Multiplexer B3 (01-C) — NotificationsHeaderRenderer tests.
// Run via `npx tsx --test src/tests/unit/multiplexer/render/notifications_header_renderer.test.ts`.
// Coverage target: 100% lines/branches/functions on NotificationsHeaderRenderer.ts.

import { test, before, afterEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createNotificationsHeaderRenderer } from "../../../../lupin_app/static/js/multiplexer/render/NotificationsHeaderRenderer";
import type {
  NotificationsHeaderStoreLike,
  NotificationDeleteApiLike,
  SysTimeUpdatePayload,
} from "../../../../lupin_app/static/js/multiplexer/render/NotificationsHeaderRenderer";
import type { Notification, StoreNotificationsChangedPayload } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before(() => {
  if (typeof globalThis.document === "undefined") GlobalRegistrator.register();
});
afterEach(() => {
  if (globalThis.document !== undefined) document.body.replaceChildren();
});

function note(id: string, over: Partial<Notification> = {}): Notification {
  return { id_hash: id, ts: 1_700_000_000_000, sender_id: "s", message: "m-" + id, action_required: false, ...over };
}

// Mutable fake store implementing the narrowed surface.
function makeStore(init: { active?: Notification[]; visible?: Notification[]; history?: Notification[] } = {}) {
  let active  = init.active  ?? [];
  const hist  = init.history ?? [];
  let visible = init.visible ?? active;
  const removed: string[][] = [];
  const store: NotificationsHeaderStoreLike = {
    list           : () => active,
    history        : () => hist,
    visibleEntries : () => visible,
    removeByIdHashes: (ids) => {
      removed.push([...ids]);
      const set = new Set(ids);
      active  = active.filter(n => !set.has(n.id_hash));
      visible = visible.filter(n => !set.has(n.id_hash));
    },
  };
  return { store, removed, setActive(a: Notification[]) { active = a; visible = a; } };
}

function makeApi(failIds: Set<string> = new Set()): { api: NotificationDeleteApiLike; deleted: string[] } {
  const deleted: string[] = [];
  const api: NotificationDeleteApiLike = {
    delete<T>(path: string): Promise<T> {
      const id = decodeURIComponent(path.split("/").pop() ?? "");
      if (failIds.has(id)) return Promise.reject(new Error("boom " + id));
      deleted.push(id);
      return Promise.resolve(undefined as T);
    },
  };
  return { api, deleted };
}

function mountInto(opts: {
  store: NotificationsHeaderStoreLike;
  api: NotificationDeleteApiLike;
  confirmFn?: (m: string) => boolean;
}) {
  const bus = createEventBusForTesting();
  const renderer = createNotificationsHeaderRenderer({
    eventBus: bus, store: opts.store, api: opts.api, confirmFn: opts.confirmFn ?? (() => true),
  });
  const root = document.createElement("div");
  document.body.appendChild(root);
  renderer.mount(root);
  return { bus, renderer, root };
}

const $ = (root: HTMLElement, sel: string) => root.querySelector(sel) as HTMLElement;
const flush = () => new Promise<void>(r => setTimeout(r, 0));

// ---------------------------------------------------------------------------
// Construction + lifecycle
// ---------------------------------------------------------------------------

test("constructor throws without a store", () => {
  const bus = createEventBusForTesting();
  const { api } = makeApi();
  assert.throws(
    () => createNotificationsHeaderRenderer({ eventBus: bus, store: undefined as unknown as NotificationsHeaderStoreLike, api }),
    /requires a store/,
  );
});

test("mount builds the chrome; a 2nd mount throws", () => {
  const { store } = makeStore({ active: [note("a")] });
  const { api } = makeApi();
  const { renderer, root } = mountInto({ store, api });
  assert.notEqual(root.querySelector("#notifications-count"), null);
  assert.notEqual(root.querySelector("#clear-all-notifications"), null);
  assert.notEqual(root.querySelector("#history-dropdown-toggle"), null);
  assert.equal(($(root, "#history-dropdown-container") as HTMLElement).hidden, true);
  assert.throws(() => renderer.mount(root), /already mounted/);
});

test("unmount clears the root + is idempotent", () => {
  const { store } = makeStore();
  const { api } = makeApi();
  const { renderer, root } = mountInto({ store, api });
  renderer.unmount();
  assert.equal(root.querySelector("#notifications-count"), null);
  renderer.unmount();   // no-op
});

// ---------------------------------------------------------------------------
// Count + clear-all enablement
// ---------------------------------------------------------------------------

test("count reflects the active-list TOTAL (Lane 0a — RULED TOTAL, legacy parity) and updates on store change", () => {
  // The header count is the active-list TOTAL (list().length) — RULED 2026-07-02
  // from legacy ground truth (notifications.js:14417-14428 sums into
  // #notifications-count). NOT the unread tally.
  const { store, setActive } = makeStore({ active: [note("a"), note("b")] });
  const { api } = makeApi();
  const { bus, root } = mountInto({ store, api });
  assert.equal($(root, "#notifications-count").textContent, "2");
  setActive([note("a")]);
  bus.emit<StoreNotificationsChangedPayload>({ type: "store_notifications_changed", payload: { changeKind: "removed" }, source: "t", ts: 0 });
  assert.equal($(root, "#notifications-count").textContent, "1");
});

test("clear-all is disabled when nothing visible, enabled when visible", () => {
  const empty = makeStore({ active: [], visible: [] });
  const { api } = makeApi();
  const r1 = mountInto({ store: empty.store, api });
  assert.equal(($(r1.root, "#clear-all-notifications") as HTMLButtonElement).disabled, true);

  const full = makeStore({ active: [note("a")], visible: [note("a")] });
  const r2 = mountInto({ store: full.store, api });
  assert.equal(($(r2.root, "#clear-all-notifications") as HTMLButtonElement).disabled, false);
});

// ---------------------------------------------------------------------------
// H2 — env-label + live clock (sys_time_update)
// ---------------------------------------------------------------------------

test("mount builds empty env-label + clock spans", () => {
  const { store } = makeStore();
  const { api } = makeApi();
  const { root } = mountInto({ store, api });
  assert.notEqual(root.querySelector("#env-label"), null);
  assert.notEqual(root.querySelector("#clock"), null);
  assert.equal($(root, "#env-label").textContent, "");
  assert.equal($(root, "#clock").textContent, "");
});

test("sys_time_update with env_label + date populates env-label prefix + clock", () => {
  const { store } = makeStore();
  const { api } = makeApi();
  const { bus, root } = mountInto({ store, api });
  bus.emit<SysTimeUpdatePayload>({
    type: "sys_time_update",
    payload: { env_label: "DEVELOPMENT", date: "2026-07-01 @ 14:30" },
    source: "t", ts: 0,
  });
  assert.equal($(root, "#env-label").textContent, "[DEVELOPMENT]: ");
  assert.equal($(root, "#clock").textContent, "2026-07-01 @ 14:30");
});

test("sys_time_update with empty env_label + missing date clears both", () => {
  const { store } = makeStore();
  const { api } = makeApi();
  const { bus, root } = mountInto({ store, api });
  // First populate, then send a falsy/absent payload to exercise the "" branches.
  bus.emit<SysTimeUpdatePayload>({ type: "sys_time_update", payload: { env_label: "TEST", date: "d" }, source: "t", ts: 0 });
  bus.emit<SysTimeUpdatePayload>({ type: "sys_time_update", payload: {}, source: "t", ts: 0 });
  assert.equal($(root, "#env-label").textContent, "");
  assert.equal($(root, "#clock").textContent, "");
});

// ---------------------------------------------------------------------------
// History dropdown
// ---------------------------------------------------------------------------

test("history toggle opens the panel with rows, then closes", () => {
  const { store } = makeStore({ history: [note("h1", { message: "old one", time_display: "10:00 EDT" })] });
  const { api } = makeApi();
  const { root } = mountInto({ store, api });
  const panel = $(root, "#history-dropdown-container") as HTMLElement;
  $(root, "#history-dropdown-toggle").click();
  assert.equal(panel.hidden, false);
  assert.equal(panel.querySelectorAll(".notifications-history-row").length, 1);
  assert.match(panel.textContent ?? "", /old one/);
  assert.match(panel.textContent ?? "", /10:00 EDT/);
  $(root, "#history-dropdown-toggle").click();
  assert.equal(panel.hidden, true);
});

test("history panel shows an empty message when history is empty", () => {
  const { store } = makeStore({ history: [] });
  const { api } = makeApi();
  const { root } = mountInto({ store, api });
  $(root, "#history-dropdown-toggle").click();
  assert.match($(root, "#history-dropdown-container").textContent ?? "", /No history/);
});

test("history row falls back to ISO time when time_display absent", () => {
  const { store } = makeStore({ history: [note("h1")] });   // no time_display
  const { api } = makeApi();
  const { root } = mountInto({ store, api });
  $(root, "#history-dropdown-toggle").click();
  assert.match($(root, "#history-dropdown-container").textContent ?? "", /\d{4}-\d{2}-\d{2}T/);
});

test("an open history panel re-renders on a store change", () => {
  const s = makeStore({ active: [note("a")], history: [] });
  const { api } = makeApi();
  const { bus, root } = mountInto({ store: s.store, api });
  $(root, "#history-dropdown-toggle").click();   // open (empty)
  assert.match($(root, "#history-dropdown-container").textContent ?? "", /No history/);
  // Mutate history then emit — the open panel refreshes.
  (s.store.history as () => Notification[]) = () => [note("h9", { message: "fresh hist" })];
  bus.emit<StoreNotificationsChangedPayload>({ type: "store_notifications_changed", payload: { changeKind: "added" }, source: "t", ts: 0 });
  assert.match($(root, "#history-dropdown-container").textContent ?? "", /fresh hist/);
});

// ---------------------------------------------------------------------------
// Clear-all — confirm guard, all-success, partial-failure, empty
// ---------------------------------------------------------------------------

test("clear-all: confirm declined → no deletes, no removal", async () => {
  const s = makeStore({ active: [note("a")], visible: [note("a")] });
  const { api, deleted } = makeApi();
  const { root } = mountInto({ store: s.store, api, confirmFn: () => false });
  $(root, "#clear-all-notifications").click();
  await flush();
  assert.equal(deleted.length, 0);
  assert.equal(s.removed.length, 0);
});

test("clear-all: all succeed → every visible id deleted + removed; status reports", async () => {
  const s = makeStore({ active: [note("a"), note("b")], visible: [note("a"), note("b")] });
  const { api, deleted } = makeApi();
  const { root } = mountInto({ store: s.store, api });
  $(root, "#clear-all-notifications").click();
  await flush();
  assert.deepEqual(deleted.sort(), ["a", "b"]);
  assert.deepEqual(s.removed, [["a", "b"]]);
  assert.match($(root, '[data-testid="multiplexer-notifications-header-status"]').textContent ?? "", /Cleared 2\./);
});

test("clear-all: partial failure → only succeeded ids removed; failure surfaced", async () => {
  const s = makeStore({ active: [note("a"), note("b"), note("c")], visible: [note("a"), note("b"), note("c")] });
  const { api, deleted } = makeApi(new Set(["b"]));   // 'b' delete rejects
  const { root } = mountInto({ store: s.store, api });
  $(root, "#clear-all-notifications").click();
  await flush();
  assert.deepEqual(deleted.sort(), ["a", "c"]);       // b never recorded
  assert.deepEqual(s.removed, [["a", "c"]]);          // b NOT removed (stays in store)
  assert.match($(root, '[data-testid="multiplexer-notifications-header-status"]').textContent ?? "", /Cleared 2, 1 failed\./);
});

test("clear-all: empty visible scope → early return (no confirm, no delete)", async () => {
  const s = makeStore({ active: [], visible: [] });
  let confirmCalls = 0;
  const { api, deleted } = makeApi();
  const { root } = mountInto({ store: s.store, api, confirmFn: () => { confirmCalls++; return true; } });
  // Force a click even though the button is disabled (covers the guard directly).
  ($(root, "#clear-all-notifications") as HTMLButtonElement).disabled = false;
  $(root, "#clear-all-notifications").click();
  await flush();
  assert.equal(confirmCalls, 0);
  assert.equal(deleted.length, 0);
});

// ---------------------------------------------------------------------------
// Lane 0a — uniform section-header bar (🔔 + total count + env-label/clock in
// the h3) + session-only collapse of the sibling #notifications-pane
// ---------------------------------------------------------------------------

test("Lane 0a: 🔔 section-header bar with env-label/clock in the h3; chevron collapses the sibling #notifications-pane; control clicks do not", () => {
  const pane = document.createElement("section");
  pane.id = "notifications-pane";
  document.body.appendChild(pane);

  const { store } = makeStore({ active: [note("a")] });
  const { api } = makeApi();
  const { root, renderer } = mountInto({ store, api });

  const header = root.querySelector(".section-header") as HTMLElement;
  assert.ok(header, "section-header bar present");
  const h3 = header.querySelector("h3") as HTMLElement;
  assert.ok(h3.textContent!.includes("🔔 Notifications"), "🔔 Notifications title");
  assert.notEqual(h3.querySelector("#env-label"), null, "env-label injected into h3");
  assert.notEqual(h3.querySelector("#clock"), null, "clock injected into h3");
  assert.equal($(root, "#notifications-count").textContent, "1", "total count in header");

  const chevron = header.querySelector(".toggle-button") as HTMLElement;
  // Header-background click → collapse the sibling pane.
  h3.dispatchEvent(new Event("click", { bubbles: true }));
  assert.equal(pane.getAttribute("data-collapsed"), "true");
  assert.equal(chevron.textContent, "▶");
  // Chevron click → expand.
  chevron.dispatchEvent(new Event("click", { bubbles: true }));
  assert.equal(pane.getAttribute("data-collapsed"), "false");
  assert.equal(chevron.textContent, "▼");

  // A control click (history-toggle button) must NOT collapse.
  $(root, "#history-dropdown-toggle").dispatchEvent(new Event("click", { bubbles: true }));
  assert.equal(pane.getAttribute("data-collapsed"), "false", "control click does not collapse");

  renderer.unmount();
  pane.remove();
});

test("Lane 0a: a header click with NO #notifications-pane in the doc is a safe no-op", () => {
  const { store } = makeStore({ active: [] });
  const { api } = makeApi();
  const { root, renderer } = mountInto({ store, api });
  const header = root.querySelector(".section-header") as HTMLElement;
  // No sibling pane → the collapse handler returns early (no throw, chevron stays).
  (header.querySelector("h3") as HTMLElement).dispatchEvent(new Event("click", { bubbles: true }));
  assert.equal(header.querySelector(".toggle-button")!.textContent, "▼", "chevron unchanged");
  renderer.unmount();
});
