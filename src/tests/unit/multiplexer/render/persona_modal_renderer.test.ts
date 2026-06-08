// Multiplexer Phase 6c Node A — PersonaModalRenderer unit tests.
// Run via `npx tsx --test src/tests/unit/multiplexer/render/persona_modal_renderer.test.ts`.
//
// AC-A4 target: ≥12 cases (incl #10 storm-safety persona-field-change subset).

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createPersonaModalRenderer } from "../../../../lupin_app/static/js/multiplexer/render/PersonaModalRenderer";
import type { SenderRecord, VoicePersona, StoreSendersChangedPayload } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

beforeEach(() => {
  if (globalThis.document !== undefined) {
    document.body.replaceChildren();
  }
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

interface MutableStore {
  get(senderId: string): SenderRecord | undefined;
  list(): ReadonlyArray<SenderRecord>;
  setList(next: SenderRecord[]): void;
}

function makeStore( initial: SenderRecord[] = [] ): MutableStore {
  let backing = [...initial];
  return {
    get     : (id) => backing.find(s => s.sender_id === id),
    list    : () => backing as ReadonlyArray<SenderRecord>,
    setList : (next) => { backing = [...next]; },
  };
}

function makePersona( over: Partial<VoicePersona> = {} ): VoicePersona {
  return {
    name     : "Tiberius",
    voice_id : "vid_42",
    icon     : "🌑",
    color    : "#3F51B5",
    borrowed : false,
    ...over,
  };
}

function makeSender( over: Partial<SenderRecord> = {} ): SenderRecord {
  return {
    sender_id                : "alice@x",
    display_name             : "Alice",
    last_active_ts           : 1_000_000,
    unread_count             : 0,
    conversation_mode_active : false,
    ...over,
  };
}

function makeRootWithPortal(): { root: HTMLElement; portal: HTMLElement } {
  const root = document.createElement("main");
  root.className = "container";
  const portal = document.createElement("div");
  portal.id = "persona-modal-portal";
  root.appendChild(portal);
  document.body.appendChild(root);
  return { root, portal };
}

function emit(
  bus      : ReturnType<typeof createEventBusForTesting>,
  senderId : string,
  kind     : "added" | "updated" | "removed" = "updated",
): void {
  bus.emit<StoreSendersChangedPayload>({
    type    : "store_senders_changed",
    payload : { changeKind: kind, sender_id: senderId },
    source  : "test",
    ts      : 0,
  });
}

// ===========================================================================
// 1-3 : Mount lifecycle
// ===========================================================================

test("mount throws when #persona-modal-portal is missing in the root", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore();
  const root  = document.createElement("main");
  document.body.appendChild(root);
  const r = createPersonaModalRenderer({ eventBus: bus, stores: { senders: store } });
  assert.throws(() => r.mount(root), /persona-modal-portal/);
});

test("mount with no senders: no popovers created in the portal", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore();
  const { root, portal } = makeRootWithPortal();
  const r = createPersonaModalRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);
  assert.equal(portal.children.length, 0);
});

test("mount creates a popover in the portal for every sender already carrying a voice_persona", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore([
    makeSender({ sender_id: "a", voice_persona: makePersona() }),
    makeSender({ sender_id: "b", voice_persona: makePersona({ name: "Maria", icon: "🌸" }) }),
    makeSender({ sender_id: "c" }), // no persona — NO popover
  ]);
  const { root, portal } = makeRootWithPortal();
  const r = createPersonaModalRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);
  assert.equal(portal.children.length, 2);
  assert.notEqual(portal.querySelector("#persona-popover-a"), null);
  assert.notEqual(portal.querySelector("#persona-popover-b"), null);
  assert.equal(portal.querySelector("#persona-popover-c"), null);
});

// ===========================================================================
// 4-5 : added / updated handling
// ===========================================================================

test("store_senders_changed('added') with persona creates a new popover", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore();
  const { root, portal } = makeRootWithPortal();
  const r = createPersonaModalRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);
  assert.equal(portal.children.length, 0);

  store.setList([ makeSender({ sender_id: "a", voice_persona: makePersona() }) ]);
  emit(bus, "a", "added");
  assert.equal(portal.children.length, 1);
  assert.notEqual(portal.querySelector("#persona-popover-a"), null);
});

test("store_senders_changed('updated') with persona change re-renders in place (preserves popover element identity)", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore([ makeSender({ sender_id: "a", voice_persona: makePersona({ name: "Tiberius" }) }) ]);
  const { root, portal } = makeRootWithPortal();
  const r = createPersonaModalRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);
  const original = portal.querySelector("#persona-popover-a")!;
  assert.match(original.textContent ?? "", /Tiberius/);

  store.setList([ makeSender({ sender_id: "a", voice_persona: makePersona({ name: "Tiberius v2" }) }) ]);
  emit(bus, "a", "updated");

  // Same element instance (F-Arnold-5 preserves open state).
  const after = portal.querySelector("#persona-popover-a")!;
  assert.strictEqual(after, original, "popover root element identity preserved across updates");
  assert.match(after.textContent ?? "", /Tiberius v2/);
});

// ===========================================================================
// 6 : persona release (updated with voice_persona undefined → removes popover)
// ===========================================================================

test("store_senders_changed('updated') with voice_persona undefined removes the popover", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore([ makeSender({ sender_id: "a", voice_persona: makePersona() }) ]);
  const { root, portal } = makeRootWithPortal();
  const r = createPersonaModalRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);
  assert.equal(portal.children.length, 1);

  store.setList([ makeSender({ sender_id: "a" }) ]); // persona released
  emit(bus, "a", "updated");
  assert.equal(portal.children.length, 0);
});

// ===========================================================================
// 7 : removed handling
// ===========================================================================

test("store_senders_changed('removed') removes the popover from the portal", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore([ makeSender({ sender_id: "a", voice_persona: makePersona() }) ]);
  const { root, portal } = makeRootWithPortal();
  const r = createPersonaModalRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);
  assert.equal(portal.children.length, 1);

  emit(bus, "a", "removed");
  assert.equal(portal.children.length, 0);
});

// ===========================================================================
// 8 : edge — updated for a sender that store.get returns undefined for
// ===========================================================================

test("store_senders_changed('updated') for unknown sender removes any existing popover (defensive)", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore([ makeSender({ sender_id: "a", voice_persona: makePersona() }) ]);
  const { root, portal } = makeRootWithPortal();
  const r = createPersonaModalRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);

  // Drop "a" from the store + emit an update for "a" (mimics a race).
  store.setList([]);
  emit(bus, "a", "updated");
  assert.equal(portal.children.length, 0);
});

// ===========================================================================
// 9 : added emission for a sender WITHOUT persona is a no-op
// ===========================================================================

test("store_senders_changed('added') for sender WITHOUT persona does not create a popover", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore();
  const { root, portal } = makeRootWithPortal();
  const r = createPersonaModalRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);

  store.setList([ makeSender({ sender_id: "a" }) ]); // no persona
  emit(bus, "a", "added");
  assert.equal(portal.children.length, 0);
});

// ===========================================================================
// 10 : storm-safety — multiple rapid emissions for the same sender remain idempotent
// ===========================================================================

test("storm of updated emissions on the same sender produces a single popover with the latest state", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore([ makeSender({ sender_id: "a", voice_persona: makePersona({ name: "v1" }) }) ]);
  const { root, portal } = makeRootWithPortal();
  const r = createPersonaModalRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);

  for (let i = 2; i <= 10; i++) {
    store.setList([ makeSender({ sender_id: "a", voice_persona: makePersona({ name: `v${i}` }) }) ]);
    emit(bus, "a", "updated");
  }
  // Single popover, latest content.
  assert.equal(portal.querySelectorAll("[id^='persona-popover-']").length, 1);
  assert.match(portal.querySelector("#persona-popover-a")!.textContent ?? "", /v10/);
});

// ===========================================================================
// 11 : F-Arnold-4 — no chip rendered for personaless senders means popover
//   also OMITTED (already covered by test #3 + #9 — explicit assertion here)
// ===========================================================================

test("F-Arnold-4: personaless sender never gets a popover (no stub/empty popover element)", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore([ makeSender({ sender_id: "a" }) ]); // no persona
  const { root, portal } = makeRootWithPortal();
  const r = createPersonaModalRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);
  assert.equal(portal.children.length, 0);
});

// ===========================================================================
// 12 : Renderer lifecycle (unmount, double-mount, forceRenderForTesting)
// ===========================================================================

test("unmount() removes all owned popovers and unsubscribes", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore([
    makeSender({ sender_id: "a", voice_persona: makePersona() }),
    makeSender({ sender_id: "b", voice_persona: makePersona() }),
  ]);
  const { root, portal } = makeRootWithPortal();
  const r = createPersonaModalRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);
  assert.equal(portal.children.length, 2);

  r.unmount();
  assert.equal(portal.children.length, 0, "unmount removes all owned popovers");

  // After unmount, store events do not re-create popovers.
  store.setList([ makeSender({ sender_id: "c", voice_persona: makePersona() }) ]);
  emit(bus, "c", "added");
  assert.equal(portal.children.length, 0);
});

test("double mount() throws", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore();
  const { root } = makeRootWithPortal();
  const r = createPersonaModalRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);
  assert.throws(() => r.mount(root), /already mounted/);
});

test("forceRenderForTesting() reconciles to current store state (adds + removes)", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore([ makeSender({ sender_id: "a", voice_persona: makePersona() }) ]);
  const { root, portal } = makeRootWithPortal();
  const r = createPersonaModalRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);
  assert.equal(portal.children.length, 1);

  // Mutate store WITHOUT emitting; force reconcile picks up the new state.
  store.setList([
    makeSender({ sender_id: "b", voice_persona: makePersona({ name: "Maria" }) }),
    makeSender({ sender_id: "c", voice_persona: makePersona({ name: "Tiffany" }) }),
  ]);
  r.forceRenderForTesting();
  assert.equal(portal.children.length, 2);
  assert.notEqual(portal.querySelector("#persona-popover-b"), null);
  assert.notEqual(portal.querySelector("#persona-popover-c"), null);
  assert.equal(portal.querySelector("#persona-popover-a"), null, "stale popover removed");
});

// ===========================================================================
// 13 : forceRenderForTesting before mount is a no-op (defense-in-depth)
// ===========================================================================

test("forceRenderForTesting before mount is a safe no-op (no crash)", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore([ makeSender({ sender_id: "a", voice_persona: makePersona() }) ]);
  const r = createPersonaModalRenderer({ eventBus: bus, stores: { senders: store } });
  assert.doesNotThrow(() => r.forceRenderForTesting());
});
