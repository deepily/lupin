// Multiplexer Phase 6c Node D — ConversationModePinRenderer unit tests.
// Run via `npx tsx --test src/tests/unit/multiplexer/render/conversation_mode_pin_renderer.test.ts`.
//
// AC-D4 target: ≥15 cases per execution plan §3.D.4 + Path δ scope reduction
// (Rick 2026-05-19): mic-monopoly attribute-writing tests are NOT in this
// file. See TODO.md "Phase 6c follow-on: mic-monopoly indicator" for when
// they land back.
//
// Coverage shape: 6 attribute-lifecycle + 3 pin-move + 2 single-pin-invariant
// + 3 lifecycle + 1 perf-gate-adjacent + 1 defensive idempotency = 16 cases.

import { test, before } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { createEventBusForTesting } from "../../../../fastapi_app/static/js/multiplexer/shared/EventBus";
import { createConversationModePinRenderer } from "../../../../fastapi_app/static/js/multiplexer/render/ConversationModePinRenderer";
import type { SenderRecord, StoreSendersChangedPayload } from "../../../../fastapi_app/static/js/multiplexer/shared/types";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

interface MutableStore {
  list(): ReadonlyArray<SenderRecord>;
  setList(next: SenderRecord[]): void;
}

function makeStore(initial: SenderRecord[] = []): MutableStore {
  let backing = [...initial];
  return {
    list    : () => backing as ReadonlyArray<SenderRecord>,
    setList : (next) => { backing = [...next]; },
  };
}

function makeSender(over: Partial<SenderRecord> = {}): SenderRecord {
  return {
    sender_id                : "s1",
    display_name             : "S1",
    last_active_ts           : 1_000_000,
    unread_count             : 0,
    conversation_mode_active : false,
    ...over,
  };
}

interface ManualTimer {
  id    : number;
  cb    : () => void;
  fired : boolean;
}

function makeManualTimers() {
  const pending : ManualTimer[] = [];
  let nextId = 1;
  return {
    setTimeoutFn   : (cb: () => void) => {
      const id = nextId++;
      pending.push({ id, cb, fired: false });
      return id;
    },
    clearTimeoutFn : (id: unknown) => {
      const idx = pending.findIndex(p => p.id === id);
      if (idx >= 0) pending.splice(idx, 1);
    },
    fireAll       : () => {
      const live = pending.filter(p => !p.fired);
      for (const p of live) {
        p.fired = true;
        p.cb();
      }
    },
    pendingCount  : () => pending.filter(p => !p.fired).length,
  };
}

function makeCard(senderId: string): HTMLElement {
  const card = document.createElement("div");
  card.className = "sender-card";
  card.setAttribute("data-sender-id", senderId);
  return card;
}

function makeRoot(senderIds: string[]): HTMLElement {
  const root = document.createElement("div");
  for (const id of senderIds) {
    root.appendChild(makeCard(id));
  }
  return root;
}

function emitStoreChange(
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
// 1-6 : Attribute lifecycle
// ===========================================================================

test("mount with a pre-pinned sender writes data-pinned-conv-mode on that card (initial paint)", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore([
    makeSender({ sender_id: "a", conversation_mode_active: true }),
    makeSender({ sender_id: "b", conversation_mode_active: false }),
  ]);
  const root  = makeRoot(["a", "b"]);
  const r     = createConversationModePinRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);

  assert.equal(root.querySelector('[data-sender-id="a"]')!.getAttribute("data-pinned-conv-mode"), "true");
  assert.equal(root.querySelector('[data-sender-id="b"]')!.getAttribute("data-pinned-conv-mode"), null);
});

test("mount with empty store is a no-op (no attributes written)", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore([]);
  const root  = makeRoot(["a"]);
  const r     = createConversationModePinRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);

  assert.equal(root.querySelector('[data-sender-id="a"]')!.getAttribute("data-pinned-conv-mode"), null);
});

test("mount with no pinned senders is a no-op (no attribute written even though store has senders)", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore([makeSender({ sender_id: "a", conversation_mode_active: false })]);
  const root  = makeRoot(["a"]);
  const r     = createConversationModePinRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);

  assert.equal(root.querySelector('[data-sender-id="a"]')!.getAttribute("data-pinned-conv-mode"), null);
});

test("store_senders_changed → flipping a sender to pinned writes the attribute on the matching card", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore([makeSender({ sender_id: "a", conversation_mode_active: false })]);
  const root  = makeRoot(["a"]);
  const r     = createConversationModePinRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);

  store.setList([makeSender({ sender_id: "a", conversation_mode_active: true })]);
  emitStoreChange(bus, "a");

  assert.equal(root.querySelector('[data-sender-id="a"]')!.getAttribute("data-pinned-conv-mode"), "true");
});

test("store_senders_changed → flipping a sender to unpinned clears the attribute", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore([makeSender({ sender_id: "a", conversation_mode_active: true })]);
  const root  = makeRoot(["a"]);
  const r     = createConversationModePinRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);
  assert.equal(root.querySelector('[data-sender-id="a"]')!.getAttribute("data-pinned-conv-mode"), "true");

  store.setList([makeSender({ sender_id: "a", conversation_mode_active: false })]);
  emitStoreChange(bus, "a");

  assert.equal(root.querySelector('[data-sender-id="a"]')!.getAttribute("data-pinned-conv-mode"), null);
});

test("sender_id with special chars resolves via cssEscape and the attribute is set on the right card", () => {
  const bus   = createEventBusForTesting();
  const specialId = "claude.code@lupin.deepily.ai#c7333045";
  const store = makeStore([makeSender({ sender_id: specialId, conversation_mode_active: true })]);
  const root  = makeRoot([specialId]);
  const r     = createConversationModePinRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);

  // querySelector with the raw sender_id only works because the renderer
  // CSS-escapes the value internally before building the selector.
  const card = root.querySelector<HTMLElement>(`[data-sender-id="${specialId}"]`)!;
  assert.equal(card.getAttribute("data-pinned-conv-mode"), "true");
});

// ===========================================================================
// 7-9 : Pin-move + focus-flash
// ===========================================================================

test("pin MOVE A → B: A's attribute cleared, B's attribute set, B gets data-focus-flash", () => {
  const bus    = createEventBusForTesting();
  const timers = makeManualTimers();
  const store  = makeStore([
    makeSender({ sender_id: "a", conversation_mode_active: true }),
    makeSender({ sender_id: "b", conversation_mode_active: false }),
  ]);
  const root   = makeRoot(["a", "b"]);
  const r      = createConversationModePinRenderer({
    eventBus       : bus,
    stores         : { senders: store },
    setTimeoutFn   : timers.setTimeoutFn,
    clearTimeoutFn : timers.clearTimeoutFn,
  });
  r.mount(root);

  // Dual-emission swap: clear A first (intermediate unpinned state), set B second.
  store.setList([
    makeSender({ sender_id: "a", conversation_mode_active: false }),
    makeSender({ sender_id: "b", conversation_mode_active: false }),
  ]);
  emitStoreChange(bus, "a");

  store.setList([
    makeSender({ sender_id: "a", conversation_mode_active: false }),
    makeSender({ sender_id: "b", conversation_mode_active: true }),
  ]);
  emitStoreChange(bus, "b");

  const cardA = root.querySelector('[data-sender-id="a"]')!;
  const cardB = root.querySelector('[data-sender-id="b"]')!;
  assert.equal(cardA.getAttribute("data-pinned-conv-mode"), null);
  assert.equal(cardB.getAttribute("data-pinned-conv-mode"), "true");
  assert.equal(cardB.getAttribute("data-focus-flash"), "true", "focus-flash fires on pin-move");
});

test("first-time activation does NOT trigger focus-flash (lastPinned starts null)", () => {
  const bus    = createEventBusForTesting();
  const timers = makeManualTimers();
  const store  = makeStore([makeSender({ sender_id: "a", conversation_mode_active: false })]);
  const root   = makeRoot(["a"]);
  const r      = createConversationModePinRenderer({
    eventBus       : bus,
    stores         : { senders: store },
    setTimeoutFn   : timers.setTimeoutFn,
    clearTimeoutFn : timers.clearTimeoutFn,
  });
  r.mount(root);

  store.setList([makeSender({ sender_id: "a", conversation_mode_active: true })]);
  emitStoreChange(bus, "a");

  const card = root.querySelector('[data-sender-id="a"]')!;
  assert.equal(card.getAttribute("data-pinned-conv-mode"), "true");
  assert.equal(card.getAttribute("data-focus-flash"), null, "no flash on first-time activation");
  assert.equal(timers.pendingCount(), 0, "no flash timer scheduled");
});

test("focus-flash auto-removes after flashDurationMs (manual timer fires)", () => {
  const bus    = createEventBusForTesting();
  const timers = makeManualTimers();
  const store  = makeStore([
    makeSender({ sender_id: "a", conversation_mode_active: true }),
    makeSender({ sender_id: "b", conversation_mode_active: false }),
  ]);
  const root   = makeRoot(["a", "b"]);
  const r      = createConversationModePinRenderer({
    eventBus       : bus,
    stores         : { senders: store },
    flashDurationMs: 50,
    setTimeoutFn   : timers.setTimeoutFn,
    clearTimeoutFn : timers.clearTimeoutFn,
  });
  r.mount(root);

  // Trigger a pin-move so focus-flash gets written.
  store.setList([
    makeSender({ sender_id: "a", conversation_mode_active: false }),
    makeSender({ sender_id: "b", conversation_mode_active: true }),
  ]);
  emitStoreChange(bus, "a");
  emitStoreChange(bus, "b");

  const cardB = root.querySelector('[data-sender-id="b"]')!;
  assert.equal(cardB.getAttribute("data-focus-flash"), "true");
  assert.equal(timers.pendingCount(), 1, "exactly one flash timer pending");

  // Fire the timer; flash attribute clears.
  timers.fireAll();
  assert.equal(cardB.getAttribute("data-focus-flash"), null, "flash cleared after timer fires");
  assert.equal(timers.pendingCount(), 0);
});

// ===========================================================================
// 10-11 : Single-pin invariant — consumer-side reconciliation
// ===========================================================================

test("re-activating the SAME sender does NOT re-flash (lastPinned === currentPinned)", () => {
  const bus    = createEventBusForTesting();
  const timers = makeManualTimers();
  const store  = makeStore([
    makeSender({ sender_id: "a", conversation_mode_active: true }),
    makeSender({ sender_id: "b", conversation_mode_active: false }),
  ]);
  const root   = makeRoot(["a", "b"]);
  const r      = createConversationModePinRenderer({
    eventBus       : bus,
    stores         : { senders: store },
    setTimeoutFn   : timers.setTimeoutFn,
    clearTimeoutFn : timers.clearTimeoutFn,
  });
  r.mount(root); // initial paint sets lastPinned = a
  const cardA = root.querySelector('[data-sender-id="a"]')!;
  assert.equal(cardA.getAttribute("data-focus-flash"), null, "no flash on initial paint");

  // A deactivates then re-activates — lastPinned stays "a" across the unpinned interval.
  store.setList([makeSender({ sender_id: "a", conversation_mode_active: false })]);
  emitStoreChange(bus, "a");
  store.setList([makeSender({ sender_id: "a", conversation_mode_active: true })]);
  emitStoreChange(bus, "a");

  assert.equal(cardA.getAttribute("data-pinned-conv-mode"), "true");
  assert.equal(cardA.getAttribute("data-focus-flash"), null, "re-activation of same sender does not flash");
});

test("if multiple records have conversation_mode_active=true (transient race), first match wins this pass", () => {
  // The store reducer's single-pin invariant should prevent this in steady state,
  // but the renderer reads list() defensively. The first match in Array.find is
  // canonical for this pass; the next emission reconciles.
  const bus   = createEventBusForTesting();
  const store = makeStore([
    makeSender({ sender_id: "a", conversation_mode_active: true }),
    makeSender({ sender_id: "b", conversation_mode_active: true }),
  ]);
  const root  = makeRoot(["a", "b"]);
  const r     = createConversationModePinRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);

  // "a" comes first in list order so it wins this pass.
  assert.equal(root.querySelector('[data-sender-id="a"]')!.getAttribute("data-pinned-conv-mode"), "true");
  assert.equal(root.querySelector('[data-sender-id="b"]')!.getAttribute("data-pinned-conv-mode"), null);
});

// ===========================================================================
// 12-14 : Renderer lifecycle
// ===========================================================================

test("unmount() unsubscribes from the bus — subsequent store events do NOT trigger reconcile", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore([makeSender({ sender_id: "a", conversation_mode_active: false })]);
  const root  = makeRoot(["a"]);
  const r     = createConversationModePinRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);
  r.unmount();

  // Flip state + emit; the unmounted renderer must NOT respond.
  store.setList([makeSender({ sender_id: "a", conversation_mode_active: true })]);
  emitStoreChange(bus, "a");

  assert.equal(root.querySelector('[data-sender-id="a"]')!.getAttribute("data-pinned-conv-mode"), null);
});

test("unmount() clears in-flight flash timers", () => {
  const bus    = createEventBusForTesting();
  const timers = makeManualTimers();
  const store  = makeStore([
    makeSender({ sender_id: "a", conversation_mode_active: true }),
    makeSender({ sender_id: "b", conversation_mode_active: false }),
  ]);
  const root   = makeRoot(["a", "b"]);
  const r      = createConversationModePinRenderer({
    eventBus       : bus,
    stores         : { senders: store },
    setTimeoutFn   : timers.setTimeoutFn,
    clearTimeoutFn : timers.clearTimeoutFn,
  });
  r.mount(root);

  // Trigger pin-move so a flash timer is queued.
  store.setList([
    makeSender({ sender_id: "a", conversation_mode_active: false }),
    makeSender({ sender_id: "b", conversation_mode_active: true }),
  ]);
  emitStoreChange(bus, "a");
  emitStoreChange(bus, "b");
  assert.equal(timers.pendingCount(), 1, "flash timer queued");

  r.unmount();
  assert.equal(timers.pendingCount(), 0, "unmount drained the timer queue");
});

test("double mount throws (idempotency guard)", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore([]);
  const root  = makeRoot([]);
  const r     = createConversationModePinRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);
  assert.throws(() => r.mount(root), /already mounted/);
});

// ===========================================================================
// 15-16 : Edge / robustness
// ===========================================================================

test("pinned sender's card not yet in DOM → no-op for this pass; subsequent paint sets attribute when card arrives", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore([makeSender({ sender_id: "a", conversation_mode_active: true })]);
  // Root has NO "a" card yet (simulates notification arriving before
  // NotificationsListRenderer painted the sender card).
  const root  = makeRoot([]);
  const r     = createConversationModePinRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);

  // No card to write to — nothing written, no crash.
  assert.equal(root.children.length, 0);

  // Card arrives later (NotificationsListRenderer painted it). Re-render via
  // forceRenderForTesting picks it up.
  root.appendChild(makeCard("a"));
  r.forceRenderForTesting();
  assert.equal(root.querySelector('[data-sender-id="a"]')!.getAttribute("data-pinned-conv-mode"), "true");
});

test("forceRenderForTesting() triggers reconciliation synchronously", () => {
  const bus   = createEventBusForTesting();
  const store = makeStore([makeSender({ sender_id: "a", conversation_mode_active: false })]);
  const root  = makeRoot(["a"]);
  const r     = createConversationModePinRenderer({ eventBus: bus, stores: { senders: store } });
  r.mount(root);

  // Mutate store WITHOUT emitting; force a sync paint.
  store.setList([makeSender({ sender_id: "a", conversation_mode_active: true })]);
  r.forceRenderForTesting();
  assert.equal(root.querySelector('[data-sender-id="a"]')!.getAttribute("data-pinned-conv-mode"), "true");
});

// ===========================================================================
// 17-18 : c8 coverage backfill — branches the AC-D4 happy-path tests miss
// ===========================================================================

test("re-flashing the same sender within the flash window cancels its prior timer", () => {
  // Exercise startFocusFlash's `if (existing !== undefined) clearTimeoutFn(existing)`
  // branch (lines 191-193 in ConversationModePinRenderer.ts at write time).
  // Trigger sequence A→B (flashes B, timer for B queued), B→A (flashes A,
  // timer for A queued), A→B again (B's prior timer still in flashTimers
  // because we never fired manual timers; new flash for B clears the stale
  // entry).
  const bus    = createEventBusForTesting();
  const timers = makeManualTimers();
  const store  = makeStore([
    makeSender({ sender_id: "a", conversation_mode_active: true }),
    makeSender({ sender_id: "b", conversation_mode_active: false }),
  ]);
  const root   = makeRoot(["a", "b"]);
  const r      = createConversationModePinRenderer({
    eventBus       : bus,
    stores         : { senders: store },
    setTimeoutFn   : timers.setTimeoutFn,
    clearTimeoutFn : timers.clearTimeoutFn,
  });
  r.mount(root);

  // Move 1: A → B (flash B, timer queued)
  store.setList([
    makeSender({ sender_id: "a", conversation_mode_active: false }),
    makeSender({ sender_id: "b", conversation_mode_active: true }),
  ]);
  emitStoreChange(bus, "a");
  emitStoreChange(bus, "b");
  assert.equal(timers.pendingCount(), 1, "after Move 1: one pending flash timer");

  // Move 2: B → A (flash A, timer queued; B's timer stays in the map)
  store.setList([
    makeSender({ sender_id: "a", conversation_mode_active: true }),
    makeSender({ sender_id: "b", conversation_mode_active: false }),
  ]);
  emitStoreChange(bus, "b");
  emitStoreChange(bus, "a");
  assert.equal(timers.pendingCount(), 2, "after Move 2: two pending flash timers (B's and A's)");

  // Move 3: A → B again. B's OLD timer entry is still in flashTimers; the
  // new flash must clearTimeoutFn the stale entry FIRST then queue a fresh one.
  store.setList([
    makeSender({ sender_id: "a", conversation_mode_active: false }),
    makeSender({ sender_id: "b", conversation_mode_active: true }),
  ]);
  emitStoreChange(bus, "a");
  emitStoreChange(bus, "b");
  // Net pending: A's timer (from Move 2) + B's FRESH timer (Move 3 replaced Move 1's).
  assert.equal(timers.pendingCount(), 2, "after Move 3: B's stale timer cleared, fresh B timer + A's timer remain");
  // Confirm B still has the flash attribute (renderer re-set it via the reflow pattern).
  assert.equal(root.querySelector('[data-sender-id="b"]')!.getAttribute("data-focus-flash"), "true");
});

test("renderer constructed with no setTimeoutFn / clearTimeoutFn override uses globalThis timer functions", () => {
  // Coverage backfill for the inline default arrow functions:
  //   `opts.setTimeoutFn ?? ((cb, ms) => globalThis.setTimeout(cb, ms))`
  //   `opts.clearTimeoutFn ?? ((id) => globalThis.clearTimeout(id as ...))`
  // Both arrow functions execute when production callers omit the test-only
  // injection opts. Real timer is queued + flash-cleared via unmount; the
  // long flashDurationMs guarantees the real setTimeout doesn't fire
  // during the test.
  const bus   = createEventBusForTesting();
  const store = makeStore([
    makeSender({ sender_id: "a", conversation_mode_active: true }),
    makeSender({ sender_id: "b", conversation_mode_active: false }),
  ]);
  const root  = makeRoot(["a", "b"]);
  const r     = createConversationModePinRenderer({
    eventBus        : bus,
    stores          : { senders: store },
    flashDurationMs : 60_000,    // 60s — real timer never fires within test runtime
  });
  r.mount(root);

  // Trigger a pin-move so default setTimeoutFn arrow executes.
  store.setList([
    makeSender({ sender_id: "a", conversation_mode_active: false }),
    makeSender({ sender_id: "b", conversation_mode_active: true }),
  ]);
  emitStoreChange(bus, "a");
  emitStoreChange(bus, "b");

  const cardB = root.querySelector('[data-sender-id="b"]')!;
  assert.equal(cardB.getAttribute("data-focus-flash"), "true",
    "default setTimeoutFn wired the real-timer flash");

  // unmount runs the default clearTimeoutFn arrow on the queued real timer.
  // No leak: test process exits cleanly after this completes synchronously.
  r.unmount();
});
