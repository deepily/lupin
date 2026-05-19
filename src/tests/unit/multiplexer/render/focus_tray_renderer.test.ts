// Multiplexer Phase 6c Node B — FocusTrayRenderer unit tests.
// Run via `npx tsx --test src/tests/unit/multiplexer/render/focus_tray_renderer.test.ts`.
//
// AC-B4 target: ≥15 cases per execution plan §3.B.4 Step B6.

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { createEventBusForTesting } from "../../../../fastapi_app/static/js/multiplexer/shared/EventBus";
import { createFocusTrayRenderer } from "../../../../fastapi_app/static/js/multiplexer/render/FocusTrayRenderer";
import type { SenderRecord, StoreSendersChangedPayload } from "../../../../fastapi_app/static/js/multiplexer/shared/types";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

beforeEach(() => {
  // Clear document.body between tests — renderer queries .sender-card via
  // document.querySelectorAll so the global tree must be reset per test.
  if (globalThis.document !== undefined) {
    document.body.replaceChildren();
  }
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

interface MutableStore {
  list(): ReadonlyArray<SenderRecord>;
  setList(next: SenderRecord[]): void;
}

function makeStore( initial: SenderRecord[] = [] ): MutableStore {
  let backing = [...initial];
  return {
    list    : () => backing as ReadonlyArray<SenderRecord>,
    setList : (next) => { backing = [...next]; },
  };
}

function makeSender( over: Partial<SenderRecord> = {} ): SenderRecord {
  return {
    sender_id                : "s1",
    display_name             : "S1",
    last_active_ts           : 1_000_000,
    unread_count             : 0,
    conversation_mode_active : false,
    ...over,
  };
}

interface TestRoot {
  root     : HTMLElement;
  toggleEl : HTMLButtonElement;
  trayEl   : HTMLElement;
}

function makeRoot( opts: { includeToggle?: boolean; includeTray?: boolean } = {} ): TestRoot {
  const include = { includeToggle: true, includeTray: true, ...opts };
  const root = document.createElement("main");
  root.className = "container";
  if (include.includeToggle) {
    const toggle = document.createElement("button");
    toggle.id = "focus-mode-toggle";
    toggle.setAttribute("hidden", "");
    toggle.setAttribute("data-phase6-pending", "true");
    toggle.textContent = "Focus mode OFF";
    root.appendChild(toggle);
  }
  if (include.includeTray) {
    const tray = document.createElement("aside");
    tray.id = "focus-tray";
    tray.setAttribute("hidden", "");
    tray.setAttribute("data-phase6-pending", "true");
    root.appendChild(tray);
  }
  document.body.appendChild(root);
  return {
    root,
    toggleEl : root.querySelector("#focus-mode-toggle") as HTMLButtonElement,
    trayEl   : root.querySelector("#focus-tray")        as HTMLElement,
  };
}

function makeCardsInDocument( senderIds: string[] ): void {
  const container = document.createElement("div");
  container.id = "sender-cards-container";
  for (const id of senderIds) {
    const card = document.createElement("div");
    card.className = "sender-card";
    card.setAttribute("data-sender-id", id);
    container.appendChild(card);
  }
  document.body.appendChild(container);
}

function emit( bus: ReturnType<typeof createEventBusForTesting>, senderId: string ): void {
  bus.emit<StoreSendersChangedPayload>({
    type    : "store_senders_changed",
    payload : { changeKind: "updated", sender_id: senderId },
    source  : "test",
    ts      : 0,
  });
}

// ===========================================================================
// 1-2 : Mount guards
// ===========================================================================

test("mount throws when #focus-mode-toggle is missing in the root", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore();
  const { root } = makeRoot({ includeToggle: false });
  const r = createFocusTrayRenderer({ eventBus: bus, stores: { senders: store } });
  assert.throws(() => r.mount(root), /focus-mode-toggle/);
});

test("mount throws when #focus-tray is missing in the root", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore();
  const { root } = makeRoot({ includeTray: false });
  const r = createFocusTrayRenderer({ eventBus: bus, stores: { senders: store } });
  assert.throws(() => r.mount(root), /focus-tray/);
});

// ===========================================================================
// 3-4 : Marker lift on mount
// ===========================================================================

test("mount lifts `hidden` + `data-phase6-pending` from #focus-mode-toggle", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore();
  const { root, toggleEl } = makeRoot();
  const r = createFocusTrayRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);
  assert.equal(toggleEl.hasAttribute("hidden"), false);
  assert.equal(toggleEl.hasAttribute("data-phase6-pending"), false);
});

test("mount lifts `data-phase6-pending` from #focus-tray (tray's `hidden` is reconciler-managed)", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore();
  const { root, trayEl } = makeRoot();
  const r = createFocusTrayRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);
  assert.equal(trayEl.hasAttribute("data-phase6-pending"), false);
});

// ===========================================================================
// 5-6 : Toggle disabled-state per OSQ-B-3 (no pinned sender)
// ===========================================================================

test("mount with NO pinned sender disables the toggle and sets a tooltip", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore([ makeSender({ sender_id: "a", conversation_mode_active: false }) ]);
  const { root, toggleEl } = makeRoot();
  const r = createFocusTrayRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);
  assert.ok(toggleEl.hasAttribute("disabled"));
  assert.match(toggleEl.getAttribute("title") ?? "", /requires.*conversation/i);
});

test("mount with a pinned sender enables the toggle (no disabled / title)", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore([ makeSender({ sender_id: "a", conversation_mode_active: true }) ]);
  const { root, toggleEl } = makeRoot();
  const r = createFocusTrayRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);
  assert.equal(toggleEl.hasAttribute("disabled"), false);
  assert.equal(toggleEl.getAttribute("title"), null);
});

// ===========================================================================
// 7-8 : Toggle click semantics
// ===========================================================================

test("toggle click WITH a pinned sender flips focusModeActive ON", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore([ makeSender({ sender_id: "a", conversation_mode_active: true }) ]);
  const { root, toggleEl } = makeRoot();
  makeCardsInDocument([ "a" ]);
  const r = createFocusTrayRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);

  toggleEl.click();
  assert.equal(toggleEl.getAttribute("aria-pressed"), "true");
  assert.equal(toggleEl.textContent, "Focus mode ON");
});

test("toggle click WITHOUT a pinned sender is a no-op (state stays OFF)", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore([ makeSender({ sender_id: "a", conversation_mode_active: false }) ]);
  const { root, toggleEl } = makeRoot();
  const r = createFocusTrayRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);

  toggleEl.click();
  assert.equal(toggleEl.getAttribute("aria-pressed"), "false");
  assert.equal(toggleEl.textContent, "Focus mode OFF");
});

// ===========================================================================
// 9-10 : data-focus-hidden lifecycle
// ===========================================================================

test("focus mode ON applies data-focus-hidden=true to non-pinned sender cards", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore([
    makeSender({ sender_id: "pinned", conversation_mode_active: true }),
    makeSender({ sender_id: "other1" }),
    makeSender({ sender_id: "other2" }),
  ]);
  const { root, toggleEl } = makeRoot();
  makeCardsInDocument([ "pinned", "other1", "other2" ]);
  const r = createFocusTrayRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);

  toggleEl.click();

  assert.equal(document.querySelector('.sender-card[data-sender-id="pinned"]')!.getAttribute("data-focus-hidden"), null);
  assert.equal(document.querySelector('.sender-card[data-sender-id="other1"]')!.getAttribute("data-focus-hidden"), "true");
  assert.equal(document.querySelector('.sender-card[data-sender-id="other2"]')!.getAttribute("data-focus-hidden"), "true");
});

test("focus mode OFF clears data-focus-hidden from all sender cards", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore([
    makeSender({ sender_id: "pinned", conversation_mode_active: true }),
    makeSender({ sender_id: "other" }),
  ]);
  const { root, toggleEl } = makeRoot();
  makeCardsInDocument([ "pinned", "other" ]);
  const r = createFocusTrayRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);

  toggleEl.click();
  assert.equal(document.querySelector('.sender-card[data-sender-id="other"]')!.getAttribute("data-focus-hidden"), "true");

  toggleEl.click();
  assert.equal(document.querySelector('.sender-card[data-sender-id="other"]')!.getAttribute("data-focus-hidden"), null);
});

// ===========================================================================
// 11 : Tray content population
// ===========================================================================

test("focus mode ON populates #focus-tray with a focus-tray-row button per hidden sender", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore([
    makeSender({ sender_id: "pinned", display_name: "P", conversation_mode_active: true }),
    makeSender({ sender_id: "a",      display_name: "A" }),
    makeSender({ sender_id: "b",      display_name: "B" }),
  ]);
  const { root, toggleEl, trayEl } = makeRoot();
  makeCardsInDocument([ "pinned", "a", "b" ]);
  const r = createFocusTrayRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);

  toggleEl.click();
  const rows = trayEl.querySelectorAll<HTMLButtonElement>(".focus-tray-row");
  assert.equal(rows.length, 2);
  assert.equal(rows[0]!.getAttribute("data-sender-id"), "a");
  assert.equal(rows[1]!.getAttribute("data-sender-id"), "b");
  assert.equal(trayEl.hasAttribute("hidden"), false, "tray must be visible when focus mode is ON");
});

// ===========================================================================
// 12 : Tray-row click exits focus mode (per OSQ-B-2)
// ===========================================================================

test("clicking a tray row exits focus mode (focusModeActive flips OFF + tray cleared)", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore([
    makeSender({ sender_id: "pinned", conversation_mode_active: true }),
    makeSender({ sender_id: "a" }),
  ]);
  const { root, toggleEl, trayEl } = makeRoot();
  makeCardsInDocument([ "pinned", "a" ]);
  const r = createFocusTrayRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);

  toggleEl.click(); // turn focus mode ON
  const row = trayEl.querySelector<HTMLButtonElement>(".focus-tray-row")!;
  row.click();

  assert.equal(toggleEl.getAttribute("aria-pressed"), "false");
  assert.equal(document.querySelector('.sender-card[data-sender-id="a"]')!.getAttribute("data-focus-hidden"), null);
  assert.ok(trayEl.hasAttribute("hidden"), "tray hidden after exit");
});

// ===========================================================================
// 13 : Pin-moves-while-focus-on transfers data-focus-hidden to new non-pinned
// ===========================================================================

test("pin moves while focus-mode ON: data-focus-hidden re-applied to new non-pinned set (F-Arnold-B-Stage2-4)", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore([
    makeSender({ sender_id: "a", conversation_mode_active: true }),
    makeSender({ sender_id: "b" }),
  ]);
  const { root, toggleEl } = makeRoot();
  makeCardsInDocument([ "a", "b" ]);
  const r = createFocusTrayRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);
  toggleEl.click(); // focus mode ON

  // Pin moves A → B (single emission per store contract).
  store.setList([
    makeSender({ sender_id: "a", conversation_mode_active: false }),
    makeSender({ sender_id: "b", conversation_mode_active: true }),
  ]);
  emit(bus, "a");

  assert.equal(document.querySelector('.sender-card[data-sender-id="a"]')!.getAttribute("data-focus-hidden"), "true",
    "A is now hidden (it's no longer the pin)");
  assert.equal(document.querySelector('.sender-card[data-sender-id="b"]')!.getAttribute("data-focus-hidden"), null,
    "B is now exposed (it's the new pin)");
});

// ===========================================================================
// 14 : Pin disappears while focus-mode active → force-exit
// ===========================================================================

test("pin disappears while focus mode is active → toggle disabled but focus mode HELD (dual-emission transient guard)", () => {
  // NOTE: the renderer intentionally does NOT force-exit focus mode when
  // pinned becomes null. SenderStore's dual-emission single-pin invariant
  // produces a transient "no pin" state during every pin-MOVE; force-exiting
  // would lose the user's focus-mode state on every pin swap. The toggle
  // goes disabled (visual only); DOM state is held until either the next
  // emission restores a pin or the user manually toggles via deliberate
  // click. See FocusTrayRenderer.reconcile header comment.
  const bus   = createEventBusForTesting();
  const store = makeStore([
    makeSender({ sender_id: "a", conversation_mode_active: true }),
    makeSender({ sender_id: "b" }),
  ]);
  const { root, toggleEl } = makeRoot();
  makeCardsInDocument([ "a", "b" ]);
  const r = createFocusTrayRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);
  toggleEl.click(); // focus mode ON

  // Pin clears entirely.
  store.setList([
    makeSender({ sender_id: "a", conversation_mode_active: false }),
    makeSender({ sender_id: "b", conversation_mode_active: false }),
  ]);
  emit(bus, "a");

  assert.ok(toggleEl.hasAttribute("disabled"), "toggle disabled when no pin");
  assert.equal(toggleEl.getAttribute("aria-pressed"), "true", "focus mode HELD (not force-exited)");
  // data-focus-hidden state HELD per dual-emission transient guard — b stays hidden.
  assert.equal(document.querySelector('.sender-card[data-sender-id="b"]')!.getAttribute("data-focus-hidden"), "true",
    "data-focus-hidden state held during transient no-pin state");
});

// ===========================================================================
// 15-17 : Renderer lifecycle (unmount, double-mount, forceRenderForTesting)
// ===========================================================================

test("unmount() unsubscribes — subsequent store events do not trigger reconcile", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore([ makeSender({ sender_id: "a", conversation_mode_active: true }) ]);
  const { root, toggleEl } = makeRoot();
  makeCardsInDocument([ "a", "b" ]);
  const r = createFocusTrayRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);
  toggleEl.click(); // focus mode ON (so we can verify cleanup state)
  r.unmount();

  // After unmount, store changes must NOT cause reconcile (no DOM mutation).
  store.setList([ makeSender({ sender_id: "a", conversation_mode_active: false }) ]);
  emit(bus, "a");

  // Cards' data-focus-hidden cleared by unmount().
  for (const card of document.querySelectorAll(".sender-card")) {
    assert.equal(card.getAttribute("data-focus-hidden"), null,
      "unmount() clears data-focus-hidden");
  }
});

test("double mount() throws", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore();
  const { root } = makeRoot();
  const r = createFocusTrayRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);
  assert.throws(() => r.mount(root), /already mounted/);
});

test("forceRenderForTesting() triggers a sync reconcile based on current store state", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore([ makeSender({ sender_id: "a", conversation_mode_active: false }) ]);
  const { root, toggleEl } = makeRoot();
  const r = createFocusTrayRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);
  assert.ok(toggleEl.hasAttribute("disabled"), "no pin → disabled");

  // Mutate store WITHOUT emitting; forceRenderForTesting picks up the new state.
  store.setList([ makeSender({ sender_id: "a", conversation_mode_active: true }) ]);
  r.forceRenderForTesting();
  assert.equal(toggleEl.hasAttribute("disabled"), false, "pin appeared → enabled after forceRender");
});

// ===========================================================================
// 18-20 : Edge cases / coverage backfill
// ===========================================================================

test("tray click that hits something OTHER than a .focus-tray-row is a no-op", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore([
    makeSender({ sender_id: "pinned", conversation_mode_active: true }),
    makeSender({ sender_id: "a" }),
  ]);
  const { root, toggleEl, trayEl } = makeRoot();
  makeCardsInDocument([ "pinned", "a" ]);
  const r = createFocusTrayRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);
  toggleEl.click(); // focus mode ON

  // Dispatch a click whose target is the tray itself (not a row). Use
  // dispatchEvent to control target identity precisely.
  trayEl.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  assert.equal(toggleEl.getAttribute("aria-pressed"), "true",
    "click outside a tray row must not exit focus mode");
});

test("aria-pressed and textContent stay in sync with focusModeActive across multiple toggles", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore([ makeSender({ sender_id: "a", conversation_mode_active: true }) ]);
  const { root, toggleEl } = makeRoot();
  makeCardsInDocument([ "a" ]);
  const r = createFocusTrayRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);

  // 4-cycle: OFF → ON → OFF → ON.
  assert.equal(toggleEl.getAttribute("aria-pressed"), "false");
  toggleEl.click();
  assert.equal(toggleEl.getAttribute("aria-pressed"), "true");
  toggleEl.click();
  assert.equal(toggleEl.getAttribute("aria-pressed"), "false");
  toggleEl.click();
  assert.equal(toggleEl.getAttribute("aria-pressed"), "true");
  assert.equal(toggleEl.textContent, "Focus mode ON");
});

test("renderer remounts cleanly after unmount (round-trip lifecycle)", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore([ makeSender({ sender_id: "a", conversation_mode_active: true }) ]);
  const { root, toggleEl } = makeRoot();
  makeCardsInDocument([ "a" ]);
  const r = createFocusTrayRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);
  r.unmount();
  // Second mount on the same root should succeed (the `mounted` guard reset).
  r.mount(root);
  assert.equal(toggleEl.hasAttribute("disabled"), false);
});

// ===========================================================================
// Coverage backfill — exercise toggleFocusMode's `pinned === null` guard
//   (defense-in-depth race path; reachable when a synthetic event bypasses
//   the rendered `disabled` state)
// ===========================================================================

test("toggleFocusMode race guard: handler exits early when no pinned sender (force-enabled to bypass disabled gate)", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore([ makeSender({ sender_id: "a", conversation_mode_active: false }) ]);
  const { root, toggleEl } = makeRoot();
  const r = createFocusTrayRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);
  // Simulate a race: the rendered `disabled` state would normally suppress
  // the click in happy-dom, but in a real race the click event reaches the
  // handler before reconcile applies disabled. Force-removing disabled here
  // exercises the defense-in-depth `pinned === null` early-return guard
  // inside toggleFocusMode without depending on disabled-bypass behavior.
  toggleEl.removeAttribute("disabled");
  toggleEl.click();
  assert.equal(toggleEl.getAttribute("aria-pressed"), "false", "state unchanged after force-enabled click");
  assert.equal(toggleEl.textContent, "Focus mode OFF");
});
