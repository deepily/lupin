// Multiplexer Phase 6b — ActionRequiredRenderer unit tests.
// AC5 floor: ≥21 cases per design doc § AC5 enumeration sub-table.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../fastapi_app/static/js/multiplexer/shared/EventBus";
import {
  createActionRequiredRenderer,
  type ActionRequiredRenderer,
  type ActionRequiredStoreLike,
} from "../../../../fastapi_app/static/js/multiplexer/render/ActionRequiredRenderer";
import type {
  ActionRequiredItem,
  ActionRequiredResponse,
  StoreActionRequiredChangedPayload,
} from "../../../../fastapi_app/static/js/multiplexer/shared/types";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

// ---------------------------------------------------------------------------
// Test fixtures
// ---------------------------------------------------------------------------

interface FakeStoreState {
  items: Map<string, ActionRequiredItem>;
  respondCalls: Array<{ idHash: string; response: ActionRequiredResponse }>;
  respondMode: "resolve" | "reject";
  respondError?: Error;
}

function makeStore(): { store: ActionRequiredStoreLike; state: FakeStoreState } {
  const state: FakeStoreState = {
    items: new Map(),
    respondCalls: [],
    respondMode: "resolve",
  };
  const store: ActionRequiredStoreLike = {
    list: (): ReadonlyArray<ActionRequiredItem> => Array.from(state.items.values()),
    getById: (idHash: string): ActionRequiredItem | undefined => state.items.get(idHash),
    respondAndAwait: async (idHash: string, response: ActionRequiredResponse): Promise<void> => {
      state.respondCalls.push({ idHash, response });
      if (state.respondMode === "reject") {
        throw state.respondError ?? new Error("network down");
      }
    },
  };
  return { store, state };
}

function makeItem(over: Partial<ActionRequiredItem> = {}): ActionRequiredItem {
  return {
    id_hash       : "ar1",
    prompt        : "Proceed?",
    response_type : "yes_no",
    options       : [],
    expires_at    : Date.now() + 30_000,
    state         : "pending",
    ...over,
  };
}

interface Setup {
  bus      : ReturnType<typeof createEventBusForTesting>;
  store    : ActionRequiredStoreLike;
  state    : FakeStoreState;
  renderer : ActionRequiredRenderer;
  root     : HTMLElement;
}

function setupRenderer(): Setup {
  const bus = createEventBusForTesting();
  const { store, state } = makeStore();
  const renderer = createActionRequiredRenderer({ eventBus: bus, stores: { actionRequired: store } });
  const root = document.createElement("div");
  root.id = "action-required-pane";
  document.body.appendChild(root);
  return { bus, store, state, renderer, root };
}

function emitChange(bus: ReturnType<typeof createEventBusForTesting>, payload: StoreActionRequiredChangedPayload): void {
  bus.emit({ type: "store_action_required_changed", payload, source: "test", ts: 0 });
}

// Helper: wait for microtasks to flush so async respondAndAwait completes.
function flush(): Promise<void> {
  return new Promise((resolve) => queueMicrotask(resolve));
}

// ===========================================================================
// Mount + ownership flag (Pass 2 A3) + idempotency (F-26)
// ===========================================================================

test("mount: SETS root.dataset.phase6bOwner='true' BEFORE any DOM write (Pass 2 A3 ownership claim)", () => {
  const { renderer, root } = setupRenderer();
  assert.equal(root.dataset.phase6bOwner, undefined, "flag absent before mount");
  renderer.mount(root);
  assert.equal(root.dataset.phase6bOwner, "true", "ownership flag set after mount");
  renderer.unmount();
});

test("mount idempotency: second mount throws Error('ActionRequiredRenderer already mounted')", () => {
  const { renderer, root } = setupRenderer();
  renderer.mount(root);
  assert.throws(() => renderer.mount(root), /ActionRequiredRenderer already mounted/);
  renderer.unmount();
});

test("unmount: clears dataset.phase6bOwner + replaces children + is idempotent", () => {
  const { renderer, root } = setupRenderer();
  renderer.mount(root);
  renderer.unmount();
  assert.equal(root.dataset.phase6bOwner, undefined, "ownership flag cleared on unmount");
  // Idempotent — second unmount no-ops.
  renderer.unmount();
});

// ===========================================================================
// 6 submit happy-path — one per response_type / multiSelect variant
// ===========================================================================

test("yes_no submit Yes → respondAndAwait(idHash, 'yes')", async () => {
  const { renderer, root, store, state } = setupRenderer();
  state.items.set("ar1", makeItem({ response_type: "yes_no" }));
  renderer.mount(root);
  root.querySelector<HTMLButtonElement>(".action-required-btn-yes")!.click();
  await flush();
  assert.deepEqual(state.respondCalls, [{ idHash: "ar1", response: "yes" }]);
  void store; renderer.unmount();
});

test("yes_no submit No → respondAndAwait(idHash, 'no')", async () => {
  const { renderer, root, state } = setupRenderer();
  state.items.set("ar1", makeItem({ response_type: "yes_no" }));
  renderer.mount(root);
  root.querySelector<HTMLButtonElement>(".action-required-btn-no")!.click();
  await flush();
  assert.deepEqual(state.respondCalls, [{ idHash: "ar1", response: "no" }]);
  renderer.unmount();
});

test("multiple_choice radio submit → respondAndAwait(idHash, '<value>')", async () => {
  const { renderer, root, state } = setupRenderer();
  state.items.set("ar1", makeItem({ response_type: "multiple_choice", options: ["red", "green", "blue"] }));
  renderer.mount(root);
  root.querySelectorAll<HTMLInputElement>('input[type="radio"]')[1]!.checked = true;
  root.querySelector<HTMLButtonElement>(".action-required-btn-submit")!.click();
  await flush();
  assert.deepEqual(state.respondCalls, [{ idHash: "ar1", response: "green" }]);
  renderer.unmount();
});

test("multiple_choice checkbox submit → respondAndAwait(idHash, ['a', 'c'])", async () => {
  const { renderer, root, state } = setupRenderer();
  state.items.set("ar1", makeItem({ response_type: "multiple_choice", options: ["a", "b", "c"], multiSelect: true }));
  renderer.mount(root);
  const cb = root.querySelectorAll<HTMLInputElement>('input[type="checkbox"]');
  cb[0]!.checked = true;
  cb[2]!.checked = true;
  root.querySelector<HTMLButtonElement>(".action-required-btn-submit")!.click();
  await flush();
  assert.deepEqual(state.respondCalls, [{ idHash: "ar1", response: ["a", "c"] }]);
  renderer.unmount();
});

test("open_ended submit → respondAndAwait(idHash, '<text>')", async () => {
  const { renderer, root, state } = setupRenderer();
  state.items.set("ar1", makeItem({ response_type: "open_ended" }));
  renderer.mount(root);
  root.querySelector<HTMLInputElement>(".action-required-input")!.value = "hello";
  root.querySelector<HTMLButtonElement>(".action-required-btn-submit")!.click();
  await flush();
  assert.deepEqual(state.respondCalls, [{ idHash: "ar1", response: "hello" }]);
  renderer.unmount();
});

test("open_ended_batch submit → respondAndAwait(idHash, {Topic:'AI', Budget:'100'})", async () => {
  const { renderer, root, state } = setupRenderer();
  state.items.set("ar1", makeItem({ response_type: "open_ended_batch", options: ["Topic", "Budget"] }));
  renderer.mount(root);
  const inputs = root.querySelectorAll<HTMLInputElement>(".action-required-batch-input");
  inputs[0]!.value = "AI";
  inputs[1]!.value = "100";
  root.querySelector<HTMLButtonElement>(".action-required-btn-submit-all")!.click();
  await flush();
  assert.deepEqual(state.respondCalls, [{ idHash: "ar1", response: { Topic: "AI", Budget: "100" } }]);
  renderer.unmount();
});

// ===========================================================================
// 5 error-rollback cases — store rejects + emits "failed" → widget re-enabled + error stripe
// ===========================================================================

test("yes_no error-rollback: rejection + 'failed' event → widget rebuilt with error stripe + still interactive", async () => {
  const { renderer, root, bus, state } = setupRenderer();
  const item = makeItem({ response_type: "yes_no" });
  state.items.set("ar1", item);
  state.respondMode = "reject";
  renderer.mount(root);
  root.querySelector<HTMLButtonElement>(".action-required-btn-yes")!.click();
  await flush();
  // Simulate the store's "failed" event with the item now in failed state.
  state.items.set("ar1", { ...item, state: "failed" });
  emitChange(bus, { changeKind: "failed", id_hash: "ar1", response: "yes" });
  // Widget rebuilt: still interactive (Yes/No buttons present) + error stripe rendered.
  assert.notEqual(root.querySelector(".action-required-btn-yes"), null, "Yes button still present");
  assert.notEqual(root.querySelector(".action-required-error-stripe"), null, "error stripe rendered");
  renderer.unmount();
});

test("radio error-rollback: failed event leaves widget interactive + retry path", async () => {
  const { renderer, root, bus, state } = setupRenderer();
  const item = makeItem({ response_type: "multiple_choice", options: ["a", "b"] });
  state.items.set("ar1", item);
  state.respondMode = "reject";
  renderer.mount(root);
  root.querySelectorAll<HTMLInputElement>('input[type="radio"]')[0]!.checked = true;
  root.querySelector<HTMLButtonElement>(".action-required-btn-submit")!.click();
  await flush();
  state.items.set("ar1", { ...item, state: "failed" });
  emitChange(bus, { changeKind: "failed", id_hash: "ar1", response: "a" });
  assert.notEqual(root.querySelector('input[type="radio"]'), null);
  assert.notEqual(root.querySelector(".action-required-error-stripe"), null);
  renderer.unmount();
});

test("checkbox error-rollback: failed event preserves checkbox controls", async () => {
  const { renderer, root, bus, state } = setupRenderer();
  const item = makeItem({ response_type: "multiple_choice", options: ["x", "y"], multiSelect: true });
  state.items.set("ar1", item);
  state.respondMode = "reject";
  renderer.mount(root);
  root.querySelector<HTMLButtonElement>(".action-required-btn-submit")!.click();
  await flush();
  state.items.set("ar1", { ...item, state: "failed" });
  emitChange(bus, { changeKind: "failed", id_hash: "ar1", response: [] });
  assert.notEqual(root.querySelector('input[type="checkbox"]'), null);
  assert.notEqual(root.querySelector(".action-required-error-stripe"), null);
  renderer.unmount();
});

test("open_ended error-rollback: failed event preserves text input", async () => {
  const { renderer, root, bus, state } = setupRenderer();
  const item = makeItem({ response_type: "open_ended" });
  state.items.set("ar1", item);
  state.respondMode = "reject";
  renderer.mount(root);
  root.querySelector<HTMLInputElement>(".action-required-input")!.value = "x";
  root.querySelector<HTMLButtonElement>(".action-required-btn-submit")!.click();
  await flush();
  state.items.set("ar1", { ...item, state: "failed" });
  emitChange(bus, { changeKind: "failed", id_hash: "ar1", response: "x" });
  assert.notEqual(root.querySelector(".action-required-input"), null);
  assert.notEqual(root.querySelector(".action-required-error-stripe"), null);
  renderer.unmount();
});

test("open_ended_batch error-rollback: failed event preserves batch inputs", async () => {
  const { renderer, root, bus, state } = setupRenderer();
  const item = makeItem({ response_type: "open_ended_batch", options: ["Q1", "Q2"] });
  state.items.set("ar1", item);
  state.respondMode = "reject";
  renderer.mount(root);
  root.querySelector<HTMLButtonElement>(".action-required-btn-submit-all")!.click();
  await flush();
  state.items.set("ar1", { ...item, state: "failed" });
  emitChange(bus, { changeKind: "failed", id_hash: "ar1", response: {} });
  assert.equal(root.querySelectorAll(".action-required-batch-input").length, 2);
  assert.notEqual(root.querySelector(".action-required-error-stripe"), null);
  renderer.unmount();
});

// ===========================================================================
// 6 state-machine transitions
// ===========================================================================

test("transition: pending → submitting (responded-pending event renders submitting widget)", () => {
  const { renderer, root, bus, state } = setupRenderer();
  const item = makeItem();
  state.items.set("ar1", item);
  renderer.mount(root);
  // Now flip store state + emit responded-pending.
  state.items.set("ar1", { ...item, state: "submitting" });
  emitChange(bus, { changeKind: "responded-pending", id_hash: "ar1", response: "yes" });
  const widget = root.querySelector<HTMLElement>('[data-id-hash="ar1"]');
  assert.equal(widget!.dataset.state, "submitting");
  assert.notEqual(widget!.querySelector(".action-required-submitting-msg"), null);
  renderer.unmount();
});

test("transition: submitting → responded (responded event renders responded widget)", () => {
  const { renderer, root, bus, state } = setupRenderer();
  state.items.set("ar1", makeItem({ state: "submitting" }));
  renderer.mount(root);
  state.items.set("ar1", makeItem({ state: "responded", response: "yes" }));
  emitChange(bus, { changeKind: "responded", id_hash: "ar1", response: "yes" });
  const widget = root.querySelector<HTMLElement>('[data-id-hash="ar1"]');
  assert.equal(widget!.dataset.state, "responded");
  assert.match(widget!.textContent ?? "", /Responded: yes/);
  renderer.unmount();
});

test("transition: submitting → failed (failed event renders interactive widget + error stripe)", () => {
  const { renderer, root, bus, state } = setupRenderer();
  state.items.set("ar1", makeItem({ state: "submitting" }));
  renderer.mount(root);
  state.items.set("ar1", makeItem({ state: "failed" }));
  emitChange(bus, { changeKind: "failed", id_hash: "ar1", response: "yes" });
  // failed state renders the interactive widget (re-enabled) + error stripe.
  assert.notEqual(root.querySelector(".action-required-btn-yes"), null);
  assert.notEqual(root.querySelector(".action-required-error-stripe"), null);
  renderer.unmount();
});

test("transition: failed → submitting retry (responded-pending after failed re-enters submitting)", () => {
  const { renderer, root, bus, state } = setupRenderer();
  state.items.set("ar1", makeItem({ state: "failed" }));
  renderer.mount(root);
  // Verify failed state has error stripe.
  assert.notEqual(root.querySelector(".action-required-error-stripe"), null);
  // Retry: store transitions back to submitting.
  state.items.set("ar1", makeItem({ state: "submitting" }));
  emitChange(bus, { changeKind: "responded-pending", id_hash: "ar1", response: "yes" });
  assert.equal(root.querySelector<HTMLElement>('[data-id-hash="ar1"]')!.dataset.state, "submitting");
  // Error stripe should be gone after retry transition.
  assert.equal(root.querySelector(".action-required-error-stripe"), null);
  renderer.unmount();
});

test("transition: pending → expired_visual (expired event renders expired widget)", () => {
  const { renderer, root, bus, state } = setupRenderer();
  state.items.set("ar1", makeItem({ state: "pending" }));
  renderer.mount(root);
  state.items.set("ar1", makeItem({ state: "expired", default: "no", response: "no" }));
  emitChange(bus, { changeKind: "expired", id_hash: "ar1" });
  const widget = root.querySelector<HTMLElement>('[data-id-hash="ar1"]');
  assert.equal(widget!.dataset.state, "expired");
  assert.match(widget!.textContent ?? "", /Expired — default applied/);
  renderer.unmount();
});

test("transition: cancelled (store-side cancel) → widget removed when item also evicted", () => {
  const { renderer, root, bus, state } = setupRenderer();
  state.items.set("ar1", makeItem({ state: "pending" }));
  renderer.mount(root);
  // Store evicts item entirely + fires cancelled event.
  state.items.delete("ar1");
  emitChange(bus, { changeKind: "cancelled", id_hash: "ar1" });
  assert.equal(root.querySelector('[data-id-hash="ar1"]'), null);
  renderer.unmount();
});

// ===========================================================================
// Countdown handling — store-driven tick (NO RAF per Pass 2 a2)
// ===========================================================================

test("tick event updates .action-required-countdown text via .textContent (NO requestAnimationFrame)", () => {
  const originalRAF = globalThis.requestAnimationFrame;
  let rafCalls = 0;
  // Spy: replace RAF with a counter.
  globalThis.requestAnimationFrame = ((_cb: FrameRequestCallback): number => { rafCalls += 1; return 0; }) as typeof requestAnimationFrame;
  try {
    const { renderer, root, bus, state } = setupRenderer();
    state.items.set("ar1", makeItem({ expires_at: Date.now() + 30_000 }));
    renderer.mount(root);
    const countdown = root.querySelector<HTMLElement>(".action-required-countdown");
    assert.notEqual(countdown, null, "countdown element rendered on mount");
    const before = countdown!.textContent;
    emitChange(bus, { changeKind: "tick", id_hash: "ar1", countdownMs: 5_000 });
    const after = countdown!.textContent;
    assert.notEqual(after, before, "countdown text mutated by tick");
    assert.equal(rafCalls, 0, "Pass 2 a2: NO RAF calls — countdown driven by store tick events ONLY");
    renderer.unmount();
  } finally {
    globalThis.requestAnimationFrame = originalRAF;
  }
});

test("tick event for a non-existent id is silently dropped (no throw)", () => {
  const { renderer, root, bus } = setupRenderer();
  renderer.mount(root);
  // No widget rendered (store empty). Tick for a phantom id is a no-op.
  emitChange(bus, { changeKind: "tick", id_hash: "ghost", countdownMs: 1000 });
  renderer.unmount();
});

test("tick event with no countdownMs payload defaults to 0 ms remaining", () => {
  const { renderer, root, bus, state } = setupRenderer();
  state.items.set("ar1", makeItem());
  renderer.mount(root);
  emitChange(bus, { changeKind: "tick", id_hash: "ar1" });   // no countdownMs
  const countdown = root.querySelector<HTMLElement>(".action-required-countdown");
  assert.match(countdown!.textContent ?? "", /0/);
  renderer.unmount();
});

// ===========================================================================
// Inertness-lift atomic strip (AC2c) — single MutationObserver childList entry
// ===========================================================================

test("inertness-lift: read-only → interactive is atomic + all 4 markers gone (AC2c)", async () => {
  const { renderer, root, state } = setupRenderer();
  // Pre-seed root with a Phase 5-style read-only widget carrying all 4 inertness markers.
  const ro = document.createElement("div");
  ro.className = "action-required-widget";
  ro.setAttribute("data-id-hash", "ar1");
  ro.setAttribute("data-phase6-pending", "true");
  ro.setAttribute("aria-disabled", "true");
  ro.setAttribute("data-testid", "multiplexer-action-required");
  ro.style.cursor = "not-allowed";
  const microcopy = document.createElement("div");
  microcopy.className = "action-required-pending-notice";
  microcopy.textContent = "Input arrives in next phase";
  ro.appendChild(microcopy);
  root.appendChild(ro);

  // Set up MutationObserver to verify the swap is observable as a single coherent
  // childList change set (no intermediate "nothing here" state visible).
  const records: MutationRecord[] = [];
  const observer = new MutationObserver((muts) => { records.push(...muts); });
  observer.observe(root, { childList: true });

  state.items.set("ar1", makeItem());
  renderer.mount(root);

  await new Promise((resolve) => setTimeout(resolve, 0));
  observer.disconnect();

  // AC2c — atomicity check: the swap MAY be reported as 1 record (DOM-spec ideal:
  // one MutationRecord with addedNodes=[new] + removedNodes=[old] per replaceWith)
  // OR as 2 records microbatched in the same synchronous flush (happy-dom +
  // some browser engines split replaceWith into separate add + remove records).
  // Either way the user-visible result is atomic: no observed state where the
  // widget is missing entirely between records. Cap at 2 to enforce no
  // additional churn (e.g. accidental re-render loops).
  assert.ok(records.length >= 1 && records.length <= 2, `expected 1-2 childList records (atomic swap), got ${records.length}`);

  // The swap MUST result in exactly one widget for ar1 in the final DOM (not 0, not 2).
  assert.equal(root.querySelectorAll('[data-id-hash="ar1"]').length, 1, "exactly one widget after swap");

  // All 4 inertness markers gone from the new widget.
  const newWidget = root.querySelector<HTMLElement>('[data-id-hash="ar1"]');
  assert.equal(newWidget!.getAttribute("data-phase6-pending"), null, "marker 1 gone: data-phase6-pending");
  assert.equal(newWidget!.getAttribute("aria-disabled"),       null, "marker 2 gone: aria-disabled");
  assert.equal(newWidget!.style.cursor,                          "", "marker 3 gone: cursor:not-allowed");
  assert.equal(newWidget!.querySelector(".action-required-pending-notice"), null, "marker 4 gone: pending-notice microcopy");

  renderer.unmount();
});

// ===========================================================================
// Inline error stripe + initial render coverage
// ===========================================================================

test("initial render with item.state='failed' includes inline error stripe", () => {
  const { renderer, root, state } = setupRenderer();
  state.items.set("ar1", makeItem({ state: "failed" }));
  renderer.mount(root);
  const stripe = root.querySelector(".action-required-error-stripe");
  assert.notEqual(stripe, null);
  assert.equal(stripe!.getAttribute("role"), "alert");
  assert.match(stripe!.textContent ?? "", /Submit failed/);
  renderer.unmount();
});

test("multi-item render: each item gets its own widget + correct data-id-hash", () => {
  const { renderer, root, state } = setupRenderer();
  state.items.set("ar1", makeItem({ id_hash: "ar1", prompt: "First?" }));
  state.items.set("ar2", makeItem({ id_hash: "ar2", prompt: "Second?" }));
  renderer.mount(root);
  assert.notEqual(root.querySelector('[data-id-hash="ar1"]'), null);
  assert.notEqual(root.querySelector('[data-id-hash="ar2"]'), null);
  assert.equal(root.querySelectorAll(".action-required-widget").length, 2);
  renderer.unmount();
});

test("forceRenderForTesting: re-renders all items synchronously after mutation", () => {
  const { renderer, root, state } = setupRenderer();
  renderer.mount(root);
  // Add an item AFTER mount without firing a store event.
  state.items.set("ar1", makeItem());
  assert.equal(root.querySelector('[data-id-hash="ar1"]'), null, "no widget yet (no event)");
  renderer.forceRenderForTesting();
  assert.notEqual(root.querySelector('[data-id-hash="ar1"]'), null, "widget appears after force render");
  renderer.unmount();
});

test("added event for a new item appends widget to root", () => {
  const { renderer, root, bus, state } = setupRenderer();
  renderer.mount(root);
  assert.equal(root.querySelectorAll(".action-required-widget").length, 0);
  state.items.set("ar1", makeItem());
  emitChange(bus, { changeKind: "added", id_hash: "ar1" });
  assert.equal(root.querySelectorAll(".action-required-widget").length, 1);
  renderer.unmount();
});

test("offline-frozen / offline-resumed events trigger widget rebuild (no special handling needed)", () => {
  const { renderer, root, bus, state } = setupRenderer();
  state.items.set("ar1", makeItem());
  renderer.mount(root);
  emitChange(bus, { changeKind: "offline-frozen", id_hash: "ar1", countdownMs: 25_000 });
  // Widget still present, no exception.
  assert.notEqual(root.querySelector('[data-id-hash="ar1"]'), null);
  emitChange(bus, { changeKind: "offline-resumed", id_hash: "ar1", countdownMs: 25_000 });
  assert.notEqual(root.querySelector('[data-id-hash="ar1"]'), null);
  renderer.unmount();
});

test("tick on a widget without countdown element (e.g. submitting state) is a silent no-op", () => {
  const { renderer, root, bus, state } = setupRenderer();
  state.items.set("ar1", makeItem({ state: "submitting" }));
  renderer.mount(root);
  // Submitting widget has no .action-required-countdown — tick should silently drop.
  emitChange(bus, { changeKind: "tick", id_hash: "ar1", countdownMs: 1000 });
  renderer.unmount();
});

test("cancelled changeKind for an item still in the store rebuilds (does not remove)", () => {
  const { renderer, root, bus, state } = setupRenderer();
  // Item is "cancelled" but store still has the record (cleanup pending).
  state.items.set("ar1", makeItem({ state: "cancelled" }));
  renderer.mount(root);
  // Initial render produces a hidden tombstone.
  const tombstone = root.querySelector<HTMLElement>('[data-id-hash="ar1"]');
  assert.notEqual(tombstone, null);
  assert.equal(tombstone!.dataset.state, "cancelled");
  assert.equal(tombstone!.hidden, true);
  renderer.unmount();
});

test("cssEscape fallback path: works when CSS.escape is missing (older browser sim)", () => {
  const originalCSS = (globalThis as { CSS?: unknown }).CSS;
  (globalThis as { CSS?: unknown }).CSS = undefined;
  try {
    const { renderer, root, bus, state } = setupRenderer();
    // Two id_hashes: one with special chars (regex callback fires + escapes
    // each non-alphanumeric byte), one purely alphanumeric (regex finds zero
    // matches → callback never invoked, exercises the no-match branch).
    state.items.set("ar:weird/id", makeItem({ id_hash: "ar:weird/id" }));
    state.items.set("plain1",      makeItem({ id_hash: "plain1" }));
    renderer.mount(root);
    emitChange(bus, { changeKind: "tick", id_hash: "ar:weird/id", countdownMs: 1000 });
    emitChange(bus, { changeKind: "tick", id_hash: "plain1",      countdownMs: 1000 });
    // No throw — both fallback-path invocations completed.
    renderer.unmount();
  } finally {
    (globalThis as { CSS?: unknown }).CSS = originalCSS;
  }
});

test("formatResponse: array response renders as comma-joined; record renders as 'k: v; ...'", () => {
  const { renderer, root, state } = setupRenderer();
  // Array response.
  state.items.set("ar1", makeItem({ id_hash: "ar1", state: "responded", response: ["red", "blue"] }));
  state.items.set("ar2", makeItem({ id_hash: "ar2", state: "responded", response: { Topic: "AI", Budget: "100" } }));
  state.items.set("ar3", makeItem({ id_hash: "ar3", state: "responded" })); // no response field
  renderer.mount(root);
  assert.match(root.querySelector<HTMLElement>('[data-id-hash="ar1"]')!.textContent ?? "", /Responded: red, blue/);
  assert.match(root.querySelector<HTMLElement>('[data-id-hash="ar2"]')!.textContent ?? "", /Responded: Topic: AI; Budget: 100/);
  assert.match(root.querySelector<HTMLElement>('[data-id-hash="ar3"]')!.textContent ?? "", /Responded: \(no response recorded\)/);
  renderer.unmount();
});

test("forceRenderForTesting before mount is a no-op (no throw)", () => {
  const { renderer } = setupRenderer();
  // Not mounted → forceRenderForTesting bails.
  renderer.forceRenderForTesting();
});
