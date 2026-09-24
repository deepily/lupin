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
import type { Notification, NotificationFilterMode, StoreNotificationsChangedPayload } from "../../../../lupin_app/static/js/multiplexer/shared/types";
import type { HistoryWindow } from "../../../../lupin_app/static/js/multiplexer/stores/historyWindow";

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
function makeStore(init: { active?: Notification[]; visible?: Notification[]; history?: Notification[]; mode?: NotificationFilterMode } = {}) {
  let active  = init.active  ?? [];
  const hist  = init.history ?? [];
  let visible = init.visible ?? active;
  let win: HistoryWindow = 48;
  let mode: NotificationFilterMode = init.mode ?? "own";
  const modeCalls: NotificationFilterMode[] = [];
  const removed: string[][] = [];
  const store: NotificationsHeaderStoreLike = {
    list           : () => active,
    history        : () => hist,
    visibleEntries : () => visible,
    historyWindow    : () => win,
    setHistoryWindow : (w) => { win = w; },
    filterMode       : () => mode,
    setFilterMode    : (m) => { modeCalls.push(m); mode = m; },
    removeByIdHashes: (ids) => {
      removed.push([...ids]);
      const set = new Set(ids);
      active  = active.filter(n => !set.has(n.id_hash));
      visible = visible.filter(n => !set.has(n.id_hash));
    },
  };
  return { store, removed, modeCalls, setMode(m: NotificationFilterMode) { mode = m; }, setActive(a: Notification[]) { active = a; visible = a; } };
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
  isAdmin?: () => boolean;
  revealFilterSettings?: () => void;
}) {
  const bus = createEventBusForTesting();
  const renderer = createNotificationsHeaderRenderer({
    eventBus: bus, store: opts.store, api: opts.api, confirmFn: opts.confirmFn ?? (() => true), isAdmin: opts.isAdmin,
    revealFilterSettings: opts.revealFilterSettings,
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
  assert.ok( root.querySelector("#notifications-count") !== null );
  assert.ok( root.querySelector("#clear-all-notifications") !== null );
  assert.ok( root.querySelector("#history-dropdown-toggle") !== null );
  // Rick's ruling (2026-09-10, row 98305d96): the expired-notifications button is renamed so it no
  // longer reads as a second history control beside the history-window picker.
  assert.equal($(root, "#history-dropdown-toggle").textContent, "Expired ▾");
  assert.equal(($(root, "#history-dropdown-container") as HTMLElement).hidden, true);
  assert.throws(() => renderer.mount(root), /already mounted/);
});

test("H6: the clear-all button carries the legacy label 🗑️ Clear All", () => {
  const { store } = makeStore({ active: [note("a")] });
  const { api } = makeApi();
  const { renderer, root } = mountInto({ store, api });
  assert.equal($(root, "#clear-all-notifications").textContent, "🗑️ Clear All");
  renderer.unmount();
});

test("unmount clears the root + is idempotent", () => {
  const { store } = makeStore();
  const { api } = makeApi();
  const { renderer, root } = mountInto({ store, api });
  renderer.unmount();
  assert.ok( root.querySelector("#notifications-count") === null );
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
  assert.ok( root.querySelector("#env-label") !== null );
  assert.ok( root.querySelector("#clock") !== null );
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

// A-2 #4 — the confirm names the COUNT and the WINDOW (legacy notifications.js:20952).
//
// 🔴 NOTHING ASSERTED THE MESSAGE TEXT BEFORE THESE. Every clear-all test above counted
// confirm CALLS or returned false from the stub; the sentence itself could have said
// anything, and this button deletes on the server, durably. The two facts an operator
// needs before pressing it — how many, and over what window — were the two it omitted.

test("clear-all confirm: names the count and the window, and pluralises (A-2 #4)", async () => {
  const s = makeStore( { active: [ note( "a" ), note( "b" ) ], visible: [ note( "a" ), note( "b" ) ] } );
  const { api } = makeApi();
  const seen: string[] = [];
  const { root } = mountInto( { store: s.store, api, confirmFn: ( m ) => { seen.push( m ); return false; } } );
  $( root, "#clear-all-notifications" ).click();
  await flush();
  // The store's default window is 48h, whose label is legacy's "Last 2 days".
  assert.deepEqual( seen, [ "Clear all 2 notifications (Last 2 days)? This cannot be undone." ] );
} );

test("clear-all confirm: ONE notification reads \"1 notification\", not \"1 notifications\"", async () => {
  const s = makeStore( { active: [ note( "a" ) ], visible: [ note( "a" ) ] } );
  const { api } = makeApi();
  const seen: string[] = [];
  const { root } = mountInto( { store: s.store, api, confirmFn: ( m ) => { seen.push( m ); return false; } } );
  $( root, "#clear-all-notifications" ).click();
  await flush();
  assert.deepEqual( seen, [ "Clear all 1 notification (Last 2 days)? This cannot be undone." ] );
} );

test("clear-all confirm: the window it names FOLLOWS the picker, it is not hardcoded", async () => {
  // The whole point of naming the window is that it distinguishes a small "Today" clear
  // from an "All time" one. A message that always said the same window would satisfy both
  // tests above and be worse than useless — it would state a scope the click does not have.
  const s = makeStore( { active: [ note( "a" ) ], visible: [ note( "a" ) ] } );
  s.store.setHistoryWindow( null );   // "All time"
  const { api } = makeApi();
  const seen: string[] = [];
  const { root } = mountInto( { store: s.store, api, confirmFn: ( m ) => { seen.push( m ); return false; } } );
  $( root, "#clear-all-notifications" ).click();
  await flush();
  assert.deepEqual( seen, [ "Clear all 1 notification (All time)? This cannot be undone." ] );
} );

test("clear-all confirm: the count is the FILTER-SCOPED count, not the whole list", async () => {
  // Legacy counts what the filter admits and deletes what the filter admits. If the
  // message counted `list()` while the loop walked `visibleEntries()`, it would promise
  // a deletion larger than the one it performs — and every assertion above would pass.
  const s = makeStore( { active: [ note( "a" ), note( "b" ), note( "c" ) ], visible: [ note( "a" ) ] } );
  const { api } = makeApi();
  const seen: string[] = [];
  const { root } = mountInto( { store: s.store, api, confirmFn: ( m ) => { seen.push( m ); return false; } } );
  $( root, "#clear-all-notifications" ).click();
  await flush();
  assert.deepEqual( seen, [ "Clear all 1 notification (Last 2 days)? This cannot be undone." ],
    "the confirm counted the unfiltered list, promising more than the click deletes" );
} );

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
// Lane 0a — uniform section-header bar (title + total count + env-label/clock in
// the h3) + session-only collapse of the sibling #notifications-pane. The title
// became legacy's "Claude Code Notifications:" under Rick's 2026-09-10 ruling 3.
// ---------------------------------------------------------------------------

test("Lane 0a: section-header bar with env-label/clock in the h3; chevron collapses the sibling #notifications-pane; control clicks do not", () => {
  const pane = document.createElement("section");
  pane.id = "notifications-pane";
  document.body.appendChild(pane);

  const { store } = makeStore({ active: [note("a")] });
  const { api } = makeApi();
  const { root, renderer } = mountInto({ store, api });

  const header = root.querySelector(".section-header") as HTMLElement;
  assert.ok(header, "section-header bar present");
  const h3 = header.querySelector("h3") as HTMLElement;
  assert.ok(h3.textContent!.includes("Claude Code Notifications:"), "legacy title (ruling 3)");
  assert.ok( h3.querySelector("#env-label") !== null, "env-label injected into h3" );
  assert.ok( h3.querySelector("#clock") !== null, "clock injected into h3" );
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

// ---------------------------------------------------------------------------
// Rick's 2026-09-10 ruling 3 (P0 5ebd2aff) — legacy title, TTS slider inside the bar
// ---------------------------------------------------------------------------

test("ruling 3: the h3 reads env-label, 'Claude Code Notifications:', the count, then the clock — no 🔔", () => {
  const { store } = makeStore({ active: [note("a"), note("b")] });
  const { api } = makeApi();
  const { root, renderer } = mountInto({ store, api });
  const h3 = root.querySelector(".section-header h3") as HTMLElement;
  assert.ok(!h3.textContent!.includes("🔔"), "no bell glyph");
  const kids = Array.from(h3.childNodes);
  assert.equal((kids[0] as HTMLElement).id, "env-label");
  assert.equal(kids[1]!.textContent, "Claude Code Notifications: ");
  assert.equal((kids[2] as HTMLElement).id, "notifications-count");
  assert.equal(kids[2]!.textContent, "2");
  assert.equal((kids[3] as HTMLElement).id, "clock", "the clock follows the count");
  renderer.unmount();
});

test("ruling 3: the TTS slider slot is the FIRST header action, inside the bar", () => {
  const { store } = makeStore({ active: [] });
  const { api } = makeApi();
  const { root, renderer } = mountInto({ store, api });
  const actions = root.querySelector(".section-header .section-header-actions") as HTMLElement;
  const slot = actions.firstElementChild as HTMLElement;
  assert.equal(slot.id, "tts-preview-slider-mount");
  assert.equal(slot.getAttribute("data-testid"), "multiplexer-tts-preview-slider-mount");
  renderer.unmount();
});

test("ruling 3: a slider mounted into the slot survives a store refresh", () => {
  const { store, setActive } = makeStore({ active: [note("a")] });
  const { api } = makeApi();
  const { bus, root, renderer } = mountInto({ store, api });
  const slot = $(root, "#tts-preview-slider-mount");
  const slider = document.createElement("input");
  slot.appendChild(slider);

  setActive([note("a"), note("b")]);
  bus.emit<StoreNotificationsChangedPayload>({ type: "store_notifications_changed", payload: { changeKind: "added", id_hash: "b" }, source: "test", ts: 0 });

  assert.equal($(root, "#notifications-count").textContent, "2", "the refresh ran");
  assert.ok(slider.isConnected, "the slider is still in the page");
  assert.ok($(root, "#tts-preview-slider-mount") === slot, "the same slot element");
  renderer.unmount();
});

test("ruling 3: a click inside the TTS slot does not collapse the section", () => {
  const pane = document.createElement("section");
  pane.id = "notifications-pane";
  document.body.appendChild(pane);
  const { store } = makeStore({ active: [] });
  const { api } = makeApi();
  const { root, renderer } = mountInto({ store, api });

  const label = document.createElement("label");
  $(root, "#tts-preview-slider-mount").appendChild(label);
  label.dispatchEvent(new Event("click", { bubbles: true }));
  assert.equal(pane.getAttribute("data-collapsed"), null, "a click on the slider's label must not collapse");

  renderer.unmount();
  pane.remove();
});

// ---------------------------------------------------------------------------
// Rick's 2026-09-10 ruling 1 (P0 5ebd2aff) — the history-window picker in the bar
// ---------------------------------------------------------------------------

test("ruling 1: the history-window picker sits right after the TTS slot and shows the store's window", () => {
  const { store } = makeStore({ active: [] });
  const { api } = makeApi();
  const { root, renderer } = mountInto({ store, api });
  const actions = root.querySelector(".section-header .section-header-actions") as HTMLElement;
  assert.equal((actions.children[1] as HTMLElement).id, "history-window-dropdown");
  assert.equal($(root, ".dropdown-display-label").textContent, "Last 2 days");
  renderer.unmount();
});

test("ruling 1: picking a window sets it on the store without collapsing; a store change repaints the label", () => {
  const pane = document.createElement("section");
  pane.id = "notifications-pane";
  document.body.appendChild(pane);
  const { store } = makeStore({ active: [] });
  const { api } = makeApi();
  const { bus, root, renderer } = mountInto({ store, api });

  $(root, "button.dropdown-display").dispatchEvent(new Event("click", { bubbles: true }));
  const allTime = Array.from(root.querySelectorAll(".dropdown-item")).find(i => i.textContent === "All time") as HTMLElement;
  allTime.dispatchEvent(new Event("click", { bubbles: true }));
  assert.equal(store.historyWindow(), null);
  assert.equal($(root, ".dropdown-display-label").textContent, "All time");
  assert.equal(pane.getAttribute("data-collapsed"), null, "picking never collapses the section");

  store.setHistoryWindow("today");
  bus.emit<StoreNotificationsChangedPayload>({ type: "store_notifications_changed", payload: { changeKind: "history_window" }, source: "test", ts: 0 });
  assert.equal($(root, ".dropdown-display-label").textContent, "Today");

  renderer.unmount();
  pane.remove();
});

test("ruling 1: unmount detaches the picker's outside-click listener", () => {
  const { store } = makeStore({ active: [] });
  const { api } = makeApi();
  const { root, renderer } = mountInto({ store, api });
  const menu = $(root, "#history-dropdown-menu");
  $(root, "button.dropdown-display").dispatchEvent(new Event("click", { bubbles: true }));
  renderer.unmount();
  document.body.dispatchEvent(new Event("click", { bubbles: true }));
  assert.ok(menu.classList.contains("show"), "a detached picker no longer hears document clicks");
});

// ---------------------------------------------------------------------------
// Row 98305d96 — the admin Mine switch (legacy's user filter)
// ---------------------------------------------------------------------------

const changed = (bus: ReturnType<typeof createEventBusForTesting>, changeKind: StoreNotificationsChangedPayload["changeKind"]) =>
  bus.emit<StoreNotificationsChangedPayload>({ type: "store_notifications_changed", payload: { changeKind }, source: "test", ts: 0 });

test("Mine switch: hidden for a non-admin, and for a renderer built without isAdmin", () => {
  for (const isAdmin of [() => false, undefined]) {
    const { store } = makeStore();
    const { root, renderer } = mountInto({ store, api: makeApi().api, isAdmin });
    assert.equal($(root, "[data-testid='multiplexer-notifications-filter-badge']").hidden, true);
    assert.equal($(root, "[data-testid='multiplexer-notifications-filter-switch']").hidden, true);
    renderer.unmount();
  }
});

test("Mine switch: an admin sees legacy's badge and three buttons, with the stored mode pressed", () => {
  const { store } = makeStore({ mode: "others" });
  const { root } = mountInto({ store, api: makeApi().api, isAdmin: () => true });
  const badge = $(root, "#notifications-filter-badge");
  assert.equal(badge.hidden, false);
  assert.equal(badge.textContent, "🚫 Not Mine");
  assert.equal(badge.getAttribute("data-mode"), "others");
  const labels = [...root.querySelectorAll(".notifications-filter-btn")].map(b => b.textContent);
  assert.deepEqual(labels, ["👤 Mine", "🚫 Not Mine", "👥 All Users"]);
  assert.equal($(root, "[data-testid='multiplexer-notifications-filter-others-btn']").getAttribute("aria-pressed"), "true");
  assert.equal($(root, "[data-testid='multiplexer-notifications-filter-own-btn']").getAttribute("aria-pressed"), "false");
});

test("Mine switch: the badge sits right after the title, as in legacy — not inside the h3, not in the actions", () => {
  const { store } = makeStore();
  const { root } = mountInto({ store, api: makeApi().api, isAdmin: () => true });
  // Strings and booleans only: a failing assert on a DOM node prints the whole tree and
  // trips the jstest lane's RSS ceiling (measured 2270MB), so a regression would read as
  // a killed tier instead of this test's name.
  const h3 = root.querySelector(".section-header h3") as HTMLElement;
  const badge = $(root, "#notifications-filter-badge");
  assert.equal((h3.nextElementSibling as HTMLElement | null)?.id, "notifications-filter-badge", "legacy notifications.html:481-483 — h3, then the badge");
  assert.equal(badge.closest(".section-header-actions") === null, true, "not an action");
  assert.equal(h3.contains(badge), false, "not part of the title");
});

test("Mine switch: mounting only reads the mode, so a page load does not trigger a history reload", () => {
  const { store, modeCalls } = makeStore({ mode: "all" });
  mountInto({ store, api: makeApi().api, isAdmin: () => true });
  assert.deepEqual(modeCalls, []);
});

test("Mine switch: clicking another mode sets it once; clicking the current mode does nothing", () => {
  const { store, modeCalls } = makeStore();
  const { root } = mountInto({ store, api: makeApi().api, isAdmin: () => true });
  $(root, "[data-testid='multiplexer-notifications-filter-own-btn']").click();
  assert.deepEqual(modeCalls, [], "own is already current");
  $(root, "[data-testid='multiplexer-notifications-filter-others-btn']").click();
  assert.deepEqual(modeCalls, ["others"]);
});

test("Mine switch: the badge and pressed button follow the store on the next change event", () => {
  const f = makeStore();
  const { root, bus } = mountInto({ store: f.store, api: makeApi().api, isAdmin: () => true });
  f.setMode("all");
  changed(bus, "filtered");
  assert.equal($(root, "#notifications-filter-badge").textContent, "👥 All Users");
  assert.equal($(root, "[data-testid='multiplexer-notifications-filter-all-btn']").classList.contains("active"), true);
  assert.equal($(root, "[data-testid='multiplexer-notifications-filter-own-btn']").classList.contains("active"), false);
});

// ---------------------------------------------------------------------------
// Parity A-2 #11 — the filter badge reveals Queue Filter Settings.
//
// Legacy: notifications.js:1834-1839 — stopPropagation(), then
// showAndScrollToFilterPanel(). Both halves are asserted, and the
// stopPropagation half is asserted THROUGH ITS CONSEQUENCE (the section does not
// collapse) rather than by spying on the event: a spy would pass against a
// handler that called stopPropagation on the wrong event.
// ---------------------------------------------------------------------------

test("A-2 #11: clicking the filter badge calls the reveal", () => {
  const { store } = makeStore({ active: [note("a")] });
  const { api } = makeApi();
  let calls = 0;
  const { root, renderer } = mountInto({
    store, api, isAdmin: () => true, revealFilterSettings: () => { calls += 1; },
  });
  const badge = $(root, "#notifications-filter-badge");
  assert.ok(!badge.hidden, "precondition: the badge is shown to an admin, or the click below proves nothing");
  badge.dispatchEvent(new Event("click", { bubbles: true }));
  assert.equal(calls, 1);
  renderer.unmount();
});

test("🔴 A-2 #11: the badge click does NOT collapse the notifications section", () => {
  // The stopPropagation() half, and the reason it is not defensive copying. This badge
  // is a <span>, and `headerClickShouldCollapse` returns TRUE for every target that is
  // not inside a `button, a, input, select` — so without stopPropagation the operator
  // asking to see the filters would lose the notification list on the way there.
  const pane = document.createElement("section");
  pane.id = "notifications-pane";
  document.body.appendChild(pane);

  const { store } = makeStore({ active: [note("a")] });
  const { api } = makeApi();
  let calls = 0;
  const { root, renderer } = mountInto({
    store, api, isAdmin: () => true, revealFilterSettings: () => { calls += 1; },
  });

  // Control arm: a bare header click DOES collapse, so the assertion below is
  // discriminating rather than a pane that simply never collapses in this harness.
  const h3 = root.querySelector(".section-header h3") as HTMLElement;
  h3.dispatchEvent(new Event("click", { bubbles: true }));
  assert.equal(pane.getAttribute("data-collapsed"), "true", "harness check: a header click must collapse");
  ($(root, ".toggle-button")).dispatchEvent(new Event("click", { bubbles: true }));
  assert.equal(pane.getAttribute("data-collapsed"), "false", "harness check: re-expanded before the real arm");

  $(root, "#notifications-filter-badge").dispatchEvent(new Event("click", { bubbles: true }));
  assert.equal(calls, 1, "the reveal still fired");
  assert.equal(pane.getAttribute("data-collapsed"), "false",
    "the badge click collapsed the section — stopPropagation is missing or on the wrong event");

  renderer.unmount();
  pane.remove();
});

test("A-2 #11: a badge click with NO reveal wired is a safe no-op", () => {
  // Production always passes the thunk; a harness that does not care omits it, and the
  // optional-call must not throw. This is the `?.()` branch.
  const { store } = makeStore({ active: [note("a")] });
  const { api } = makeApi();
  const { root, renderer } = mountInto({ store, api, isAdmin: () => true });
  $(root, "#notifications-filter-badge").dispatchEvent(new Event("click", { bubbles: true }));
  renderer.unmount();
});
