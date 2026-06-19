// Multiplexer WP2 (parity bridge) — SessionStripRenderer unit tests.
// Run via `npx tsx --test src/tests/unit/multiplexer/render/session_strip_renderer.test.ts`.
//
// Coverage target: 100% lines + branches + functions.

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createSessionStripRenderer } from "../../../../lupin_app/static/js/multiplexer/render/SessionStripRenderer";
import type {
  StoreSessionStripChangedPayload,
  StripSession,
  VoicePersona,
} from "../../../../lupin_app/static/js/multiplexer/shared/types";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

beforeEach(() => {
  if (globalThis.document !== undefined) document.body.replaceChildren();
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

interface MutableStore {
  list(): ReadonlyArray<StripSession>;
  setList(next: StripSession[]): void;
}

function makeStore(initial: StripSession[] = []): MutableStore {
  let backing = [...initial];
  return {
    list    : () => backing as ReadonlyArray<StripSession>,
    setList : (next) => { backing = [...next]; },
  };
}

function vp(over: Partial<VoicePersona> = {}): VoicePersona {
  return { name: "Krishna", voice_id: "v", icon: "🦚", color: "#1DE9B6", borrowed: false, ...over };
}

function session(over: Partial<StripSession> = {}): StripSession {
  return { sender_id: "s1", voice_persona: vp(), assigned_at: 1000, active: true, ...over };
}

interface Root {
  root         : HTMLElement;
  stripEl      : HTMLElement;
  iconsEl      : HTMLElement;
  focusToggle  : HTMLElement;
  hideToggle   : HTMLElement;
}

function makeRoot(opts: { strip?: boolean; icons?: boolean; focus?: boolean; hide?: boolean } = {}): Root {
  const inc = { strip: true, icons: true, focus: true, hide: true, ...opts };
  const root = document.createElement("main");
  root.className = "container";
  const strip = document.createElement("div");
  strip.id = "cc-session-strip";
  strip.setAttribute("data-phase6-pending", "true");
  if (inc.strip) root.appendChild(strip);
  const icons = document.createElement("div");
  icons.id = "cc-strip-icons";
  if (inc.icons) strip.appendChild(icons);
  const focus = document.createElement("button");
  focus.id = "cc-strip-toggle";
  focus.setAttribute("data-phase6-pending", "true");
  if (inc.focus) strip.appendChild(focus);
  const hide = document.createElement("button");
  hide.id = "cc-hide-inactive-toggle";
  hide.setAttribute("data-phase6-pending", "true");
  if (inc.hide) strip.appendChild(hide);
  document.body.appendChild(root);
  return { root, stripEl: strip, iconsEl: icons, focusToggle: focus, hideToggle: hide };
}

function makeCards(ids: string[]): void {
  const c = document.createElement("div");
  c.id = "sender-cards-container";
  for (const id of ids) {
    const card = document.createElement("div");
    card.className = "sender-card";
    card.setAttribute("data-sender-id", id);
    c.appendChild(card);
  }
  document.body.appendChild(c);
}

function emit(bus: ReturnType<typeof createEventBusForTesting>, p: StoreSessionStripChangedPayload): void {
  bus.emit<StoreSessionStripChangedPayload>({ type: "store_session_strip_changed", payload: p, source: "test", ts: 0 });
}

function clickIcon(iconsEl: HTMLElement, senderId: string): void {
  const icon = iconsEl.querySelector<HTMLElement>(`.cc-strip-icon[data-sender-id="${senderId}"]`);
  assert.ok(icon, `icon ${senderId} present`);
  icon!.dispatchEvent(new Event("click", { bubbles: true }));
}

// ===========================================================================
// mount / unmount lifecycle
// ===========================================================================

test("mount: lifts pending markers + renders existing sessions; double-mount throws", () => {
  const { root, stripEl, focusToggle, hideToggle, iconsEl } = makeRoot();
  const bus = createEventBusForTesting();
  const store = makeStore([session()]);
  const r = createSessionStripRenderer({ eventBus: bus, stores: { strip: store } });
  r.mount(root);
  assert.equal(stripEl.getAttribute("data-phase6-pending"), null);
  assert.equal(focusToggle.getAttribute("data-phase6-pending"), null);
  assert.equal(hideToggle.getAttribute("data-phase6-pending"), null);
  assert.equal(iconsEl.querySelectorAll(".cc-strip-icon").length, 1);
  assert.equal(stripEl.getAttribute("hidden"), null);
  assert.throws(() => r.mount(root), /already mounted/);
});

test("mount: throws when each required element is missing", () => {
  const bus = createEventBusForTesting();
  const store = makeStore();
  for (const [missing, re] of [
    ["strip", /#cc-session-strip not found/],
    ["icons", /#cc-strip-icons not found/],
    ["focus", /#cc-strip-toggle not found/],
    ["hide",  /#cc-hide-inactive-toggle not found/],
  ] as const) {
    document.body.replaceChildren();
    const { root } = makeRoot({ [missing]: false });
    const r = createSessionStripRenderer({ eventBus: bus, stores: { strip: store } });
    assert.throws(() => r.mount(root), re as RegExp);
  }
});

test("empty store → strip hidden", () => {
  const { root, stripEl } = makeRoot();
  const bus = createEventBusForTesting();
  const r = createSessionStripRenderer({ eventBus: bus, stores: { strip: makeStore() } });
  r.mount(root);
  assert.equal(stripEl.getAttribute("hidden"), "");
});

test("unmount: detaches listeners, clears icons + card focus, resets", () => {
  const { root, iconsEl, focusToggle } = makeRoot();
  makeCards(["s1", "s2"]);
  const bus = createEventBusForTesting();
  const store = makeStore([session({ sender_id: "s1" }), session({ sender_id: "s2", assigned_at: 2000 })]);
  const r = createSessionStripRenderer({ eventBus: bus, stores: { strip: store } });
  r.mount(root);
  clickIcon(iconsEl, "s1");   // focus → hides s2 card
  assert.equal(document.querySelector('.sender-card[data-sender-id="s2"]')!.getAttribute("data-focus-hidden"), "true");
  r.unmount();
  assert.equal(iconsEl.querySelectorAll(".cc-strip-icon").length, 0);
  assert.equal(document.querySelector('.sender-card[data-focus-hidden="true"]'), null);
  // listener detached: a store event after unmount does not repaint
  store.setList([session()]);
  emit(bus, { changeKind: "added", sender_id: "s1" });
  assert.equal(iconsEl.querySelectorAll(".cc-strip-icon").length, 0);
  // toggle click after unmount is a no-op (handler removed)
  focusToggle.dispatchEvent(new Event("click", { bubbles: true }));
});

test("unmount before mount: no-op, exercises null guards", () => {
  const bus = createEventBusForTesting();
  const r = createSessionStripRenderer({ eventBus: bus, stores: { strip: makeStore() } });
  assert.doesNotThrow(() => r.unmount());
});

// ===========================================================================
// live store events → icon add/remove/update
// ===========================================================================

test("store added/removed events drive icon add + removal; strip hides when empty", () => {
  const { root, stripEl, iconsEl } = makeRoot();
  const bus = createEventBusForTesting();
  const store = makeStore();
  const r = createSessionStripRenderer({ eventBus: bus, stores: { strip: store } });
  r.mount(root);
  store.setList([session({ sender_id: "s1" })]);
  emit(bus, { changeKind: "added", sender_id: "s1" });
  assert.equal(iconsEl.querySelectorAll(".cc-strip-icon").length, 1);
  assert.equal(stripEl.getAttribute("hidden"), null);
  store.setList([]);
  emit(bus, { changeKind: "removed", sender_id: "s1" });
  assert.equal(iconsEl.querySelectorAll(".cc-strip-icon").length, 0);
  assert.equal(stripEl.getAttribute("hidden"), "");
});

test("icons render in chronological assigned_at order (sender_id tiebreak)", () => {
  const { root, iconsEl } = makeRoot();
  const bus = createEventBusForTesting();
  const store = makeStore([
    session({ sender_id: "late",  assigned_at: 3000 }),
    session({ sender_id: "early", assigned_at: 1000 }),
    session({ sender_id: "tieB",  assigned_at: 2000 }),
    session({ sender_id: "tieA",  assigned_at: 2000 }),
  ]);
  const r = createSessionStripRenderer({ eventBus: bus, stores: { strip: store } });
  r.mount(root);
  const order = Array.from(iconsEl.querySelectorAll(".cc-strip-icon")).map(e => e.getAttribute("data-sender-id"));
  assert.deepEqual(order, ["early", "tieA", "tieB", "late"]);
});

test("re-render updates an existing icon in place (persona change)", () => {
  const { root, iconsEl } = makeRoot();
  const bus = createEventBusForTesting();
  const store = makeStore([session({ sender_id: "s1", voice_persona: vp({ name: "Krishna" }) })]);
  const r = createSessionStripRenderer({ eventBus: bus, stores: { strip: store } });
  r.mount(root);
  const before = iconsEl.querySelector(".cc-strip-icon");
  store.setList([session({ sender_id: "s1", voice_persona: vp({ name: "Rio" }) })]);
  emit(bus, { changeKind: "updated", sender_id: "s1" });
  const after = iconsEl.querySelector(".cc-strip-icon");
  assert.equal(before, after);   // DOM identity preserved
  assert.equal(after!.querySelector(".cc-strip-initial")!.textContent, "R");
});

// ===========================================================================
// WP8 — spin-up persona symmetry (idempotent strip icon on re-assign)
// ===========================================================================

test("WP8: re-assigning a session does not create a duplicate icon", () => {
  const { root, iconsEl } = makeRoot();
  const bus = createEventBusForTesting();
  const store = makeStore([session({ sender_id: "s1" })]);
  const r = createSessionStripRenderer({ eventBus: bus, stores: { strip: store } });
  r.mount(root);
  assert.equal(iconsEl.querySelectorAll('[data-sender-id="s1"]').length, 1);
  // a second voice_persona_assigned for the same sender (store emits "updated")
  emit(bus, { changeKind: "updated", sender_id: "s1" });
  assert.equal(iconsEl.querySelectorAll('[data-sender-id="s1"]').length, 1);
});

// ===========================================================================
// WP7 — reap → badge drop (icon removed from the strip)
// ===========================================================================

test("WP7: reaping a non-focused session drops its icon from the strip", () => {
  const { root, iconsEl } = makeRoot();
  const bus = createEventBusForTesting();
  const store = makeStore([session({ sender_id: "keep" }), session({ sender_id: "reap", assigned_at: 2000 })]);
  const r = createSessionStripRenderer({ eventBus: bus, stores: { strip: store } });
  r.mount(root);
  assert.equal(iconsEl.querySelectorAll(".cc-strip-icon").length, 2);
  store.setList([session({ sender_id: "keep" })]);
  emit(bus, { changeKind: "removed", sender_id: "reap" });
  assert.equal(iconsEl.querySelector('[data-sender-id="reap"]'), null);
  assert.equal(iconsEl.querySelectorAll(".cc-strip-icon").length, 1);
});

// ===========================================================================
// WP9 — manager-lineage badge (live add + clear through the store→renderer path)
// ===========================================================================

test("WP9: a session added with a manager renders the lineage badge on its icon", () => {
  const { root, iconsEl } = makeRoot();
  const bus = createEventBusForTesting();
  const store = makeStore();
  const r = createSessionStripRenderer({ eventBus: bus, stores: { strip: store } });
  r.mount(root);
  store.setList([session({ sender_id: "s1", manager_persona: { name: "Tiberius", icon: "👑", color: "#FFD700" } })]);
  emit(bus, { changeKind: "added", sender_id: "s1" });
  const icon = iconsEl.querySelector('[data-sender-id="s1"]')!;
  const badge = icon.querySelector(".cc-strip-manager-badge");
  assert.ok(badge);
  assert.equal(badge!.textContent, "T");
  assert.equal(icon.getAttribute("data-has-manager"), "true");
});

test("WP9: re-assign dropping the manager clears the lineage badge in place", () => {
  const { root, iconsEl } = makeRoot();
  const bus = createEventBusForTesting();
  const store = makeStore([session({ sender_id: "s1", manager_persona: { name: "Tiberius", icon: "👑", color: "#FFD700" } })]);
  const r = createSessionStripRenderer({ eventBus: bus, stores: { strip: store } });
  r.mount(root);
  assert.ok(iconsEl.querySelector(".cc-strip-manager-badge"));
  store.setList([session({ sender_id: "s1" })]);   // manager dropped
  emit(bus, { changeKind: "updated", sender_id: "s1" });
  assert.equal(iconsEl.querySelector(".cc-strip-manager-badge"), null);
  assert.equal(iconsEl.querySelector('[data-sender-id="s1"]')!.getAttribute("data-has-manager"), null);
});

// ===========================================================================
// focus model
// ===========================================================================

test("icon click enters focus: data-focused on icon, data-focus-active on toggle, cards hidden", () => {
  const { root, iconsEl, focusToggle } = makeRoot();
  makeCards(["s1", "s2"]);
  const bus = createEventBusForTesting();
  const store = makeStore([session({ sender_id: "s1" }), session({ sender_id: "s2", assigned_at: 2000 })]);
  const r = createSessionStripRenderer({ eventBus: bus, stores: { strip: store } });
  r.mount(root);
  clickIcon(iconsEl, "s1");
  assert.equal(iconsEl.querySelector('[data-sender-id="s1"]')!.getAttribute("data-focused"), "true");
  assert.equal(iconsEl.querySelector('[data-sender-id="s2"]')!.getAttribute("data-focused"), null);
  assert.equal(focusToggle.getAttribute("data-focus-active"), "true");
  assert.equal(focusToggle.textContent, "👁 Focus: ON");
  assert.equal(document.querySelector('[data-sender-id="s1"].sender-card')!.getAttribute("data-focus-hidden"), null);
  assert.equal(document.querySelector('[data-sender-id="s2"].sender-card')!.getAttribute("data-focus-hidden"), "true");
});

test("clicking the focused icon again exits focus (cards revealed, focus visuals cleared)", () => {
  const { root, iconsEl, focusToggle } = makeRoot();
  makeCards(["s1", "s2"]);
  const bus = createEventBusForTesting();
  const store = makeStore([session({ sender_id: "s1" }), session({ sender_id: "s2", assigned_at: 2000 })]);
  const r = createSessionStripRenderer({ eventBus: bus, stores: { strip: store } });
  r.mount(root);
  clickIcon(iconsEl, "s1");
  clickIcon(iconsEl, "s1");   // toggle off
  assert.equal(focusToggle.getAttribute("data-focus-active"), "false");
  assert.equal(focusToggle.textContent, "👁 Focus");
  assert.equal(iconsEl.querySelector('[data-sender-id="s1"]')!.getAttribute("data-focused"), null);
  assert.equal(document.querySelector('[data-sender-id="s2"].sender-card')!.getAttribute("data-focus-hidden"), null);
});

test("clicking a different icon while focused switches the focus anchor", () => {
  const { root, iconsEl } = makeRoot();
  makeCards(["s1", "s2"]);
  const bus = createEventBusForTesting();
  const store = makeStore([session({ sender_id: "s1" }), session({ sender_id: "s2", assigned_at: 2000 })]);
  const r = createSessionStripRenderer({ eventBus: bus, stores: { strip: store } });
  r.mount(root);
  clickIcon(iconsEl, "s1");
  clickIcon(iconsEl, "s2");
  assert.equal(iconsEl.querySelector('[data-sender-id="s2"]')!.getAttribute("data-focused"), "true");
  assert.equal(iconsEl.querySelector('[data-sender-id="s1"]')!.getAttribute("data-focused"), null);
  assert.equal(document.querySelector('[data-sender-id="s1"].sender-card')!.getAttribute("data-focus-hidden"), "true");
});

test("focus toggle button: enters on leftmost when nothing focused, exits when active", () => {
  const { root, focusToggle, iconsEl } = makeRoot();
  const bus = createEventBusForTesting();
  const store = makeStore([session({ sender_id: "b", assigned_at: 2000 }), session({ sender_id: "a", assigned_at: 1000 })]);
  const r = createSessionStripRenderer({ eventBus: bus, stores: { strip: store } });
  r.mount(root);
  focusToggle.dispatchEvent(new Event("click", { bubbles: true }));
  assert.equal(iconsEl.querySelector('[data-sender-id="a"]')!.getAttribute("data-focused"), "true");
  focusToggle.dispatchEvent(new Event("click", { bubbles: true }));
  assert.equal(focusToggle.getAttribute("data-focus-active"), "false");
});

test("focus toggle restores the last-focused session when it still exists", () => {
  const { root, iconsEl, focusToggle } = makeRoot();
  const bus = createEventBusForTesting();
  const store = makeStore([session({ sender_id: "a", assigned_at: 1000 }), session({ sender_id: "b", assigned_at: 2000 })]);
  const r = createSessionStripRenderer({ eventBus: bus, stores: { strip: store } });
  r.mount(root);
  clickIcon(iconsEl, "b");                                            // focus b
  focusToggle.dispatchEvent(new Event("click", { bubbles: true }));  // exit (retains b)
  focusToggle.dispatchEvent(new Event("click", { bubbles: true }));  // re-enter → restores b, not leftmost a
  assert.equal(iconsEl.querySelector('[data-sender-id="b"]')!.getAttribute("data-focused"), "true");
});

test("focus toggle falls back to leftmost when retained focus target is gone", () => {
  const { root, iconsEl, focusToggle } = makeRoot();
  const bus = createEventBusForTesting();
  const store = makeStore([session({ sender_id: "a", assigned_at: 1000 }), session({ sender_id: "b", assigned_at: 2000 })]);
  const r = createSessionStripRenderer({ eventBus: bus, stores: { strip: store } });
  r.mount(root);
  clickIcon(iconsEl, "b");                                            // focus b (retained on exit)
  focusToggle.dispatchEvent(new Event("click", { bubbles: true }));  // exit
  store.setList([session({ sender_id: "a", assigned_at: 1000 })]);   // b disappears (not via focused-reap path)
  emit(bus, { changeKind: "removed", sender_id: "b" });
  focusToggle.dispatchEvent(new Event("click", { bubbles: true }));  // re-enter → b gone → leftmost a
  assert.equal(iconsEl.querySelector('[data-sender-id="a"]')!.getAttribute("data-focused"), "true");
});

test("focus toggle is a no-op when there are no sessions", () => {
  const { root, focusToggle } = makeRoot();
  const bus = createEventBusForTesting();
  const r = createSessionStripRenderer({ eventBus: bus, stores: { strip: makeStore() } });
  r.mount(root);
  focusToggle.dispatchEvent(new Event("click", { bubbles: true }));
  assert.equal(focusToggle.getAttribute("data-focus-active"), "false");
});

test("reaping the focused session auto-exits focus mode", () => {
  const { root, iconsEl, focusToggle } = makeRoot();
  makeCards(["s1", "s2"]);
  const bus = createEventBusForTesting();
  const store = makeStore([session({ sender_id: "s1" }), session({ sender_id: "s2", assigned_at: 2000 })]);
  const r = createSessionStripRenderer({ eventBus: bus, stores: { strip: store } });
  r.mount(root);
  clickIcon(iconsEl, "s1");
  store.setList([session({ sender_id: "s2", assigned_at: 2000 })]);
  emit(bus, { changeKind: "removed", sender_id: "s1" });
  assert.equal(focusToggle.getAttribute("data-focus-active"), "false");
  assert.equal(document.querySelector('[data-sender-id="s2"].sender-card')!.getAttribute("data-focus-hidden"), null);
});

test("removing a NON-focused session does not exit focus", () => {
  const { root, iconsEl, focusToggle } = makeRoot();
  const bus = createEventBusForTesting();
  const store = makeStore([session({ sender_id: "s1" }), session({ sender_id: "s2", assigned_at: 2000 })]);
  const r = createSessionStripRenderer({ eventBus: bus, stores: { strip: store } });
  r.mount(root);
  clickIcon(iconsEl, "s1");
  store.setList([session({ sender_id: "s1" })]);
  emit(bus, { changeKind: "removed", sender_id: "s2" });
  assert.equal(focusToggle.getAttribute("data-focus-active"), "true");
});

// ===========================================================================
// click guards
// ===========================================================================

test("click outside any icon is a no-op", () => {
  const { root, iconsEl, focusToggle } = makeRoot();
  const bus = createEventBusForTesting();
  const r = createSessionStripRenderer({ eventBus: bus, stores: { strip: makeStore([session()]) } });
  r.mount(root);
  iconsEl.dispatchEvent(new Event("click", { bubbles: true }));   // click on the tray, not an icon
  assert.equal(focusToggle.getAttribute("data-focus-active"), "false");
});

test("click on an icon missing data-sender-id is a no-op", () => {
  const { root, iconsEl, focusToggle } = makeRoot();
  const bus = createEventBusForTesting();
  const r = createSessionStripRenderer({ eventBus: bus, stores: { strip: makeStore() } });
  r.mount(root);
  const orphan = document.createElement("button");
  orphan.className = "cc-strip-icon";   // no data-sender-id
  iconsEl.appendChild(orphan);
  orphan.dispatchEvent(new Event("click", { bubbles: true }));
  assert.equal(focusToggle.getAttribute("data-focus-active"), "false");
});

// ===========================================================================
// hide-inactive filter
// ===========================================================================

test("hide-inactive toggle hides inactive icons only; toggling off reveals them", () => {
  const { root, iconsEl, hideToggle } = makeRoot();
  const bus = createEventBusForTesting();
  const store = makeStore([
    session({ sender_id: "live", active: true }),
    session({ sender_id: "dead", active: false, assigned_at: 2000 }),
  ]);
  const r = createSessionStripRenderer({ eventBus: bus, stores: { strip: store } });
  r.mount(root);
  // default: nothing hidden
  assert.equal(iconsEl.querySelector('[data-sender-id="dead"]')!.getAttribute("data-inactive-hidden"), null);
  hideToggle.dispatchEvent(new Event("click", { bubbles: true }));
  assert.equal(hideToggle.getAttribute("data-hide-inactive"), "true");
  assert.equal(hideToggle.textContent, "👁 Active");
  assert.equal(iconsEl.querySelector('[data-sender-id="dead"]')!.getAttribute("data-inactive-hidden"), "true");
  assert.equal(iconsEl.querySelector('[data-sender-id="live"]')!.getAttribute("data-inactive-hidden"), null);
  hideToggle.dispatchEvent(new Event("click", { bubbles: true }));
  assert.equal(hideToggle.getAttribute("data-hide-inactive"), "false");
  assert.equal(hideToggle.textContent, "👁 All");
  assert.equal(iconsEl.querySelector('[data-sender-id="dead"]')!.getAttribute("data-inactive-hidden"), null);
});

test("WP9: a 'hydrated' store change reconciles the strip from store.list()", () => {
  const { root, iconsEl, stripEl } = makeRoot();
  const bus = createEventBusForTesting();
  const store = makeStore();
  const r = createSessionStripRenderer({ eventBus: bus, stores: { strip: store } });
  r.mount(root);
  assert.equal(stripEl.getAttribute("hidden"), "");           // empty at mount
  // Simulate the store having bulk-loaded a cold-reload snapshot, then emitting
  // the single id-less "hydrated" change.
  store.setList([session({ sender_id: "a" }), session({ sender_id: "b", assigned_at: 2000 })]);
  bus.emit<StoreSessionStripChangedPayload>({
    type: "store_session_strip_changed", payload: { changeKind: "hydrated" }, source: "test", ts: 0,
  });
  assert.equal(iconsEl.querySelectorAll(".cc-strip-icon").length, 2);
  assert.equal(stripEl.getAttribute("hidden"), null);
});

test("forceRenderForTesting reconciles from current store state", () => {
  const { root, iconsEl } = makeRoot();
  const bus = createEventBusForTesting();
  const store = makeStore();
  const r = createSessionStripRenderer({ eventBus: bus, stores: { strip: store } });
  r.mount(root);
  store.setList([session()]);
  r.forceRenderForTesting();
  assert.equal(iconsEl.querySelectorAll(".cc-strip-icon").length, 1);
});
