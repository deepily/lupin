// Multiplexer Phase 6b — ActionRequiredRenderer unit tests.
// AC5 floor: ≥21 cases per design doc § AC5 enumeration sub-table.

import { test, before } from "node:test";
import assert from "node:assert/strict";

import { parseResponseQuestions } from "../../../../lupin_app/static/js/multiplexer/stores/responseQuestions";
import { QUESTIONS_PAYLOAD } from "../fixtures/actionRequiredQuestionsPayload";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createActionRequiredRenderer,
  type ActionRequiredRenderer,
  type ActionRequiredStoreLike,
} from "../../../../lupin_app/static/js/multiplexer/render/ActionRequiredRenderer";
import type {
  ActionRequiredItem,
  ActionRequiredResponse,
  StoreActionRequiredChangedPayload,
} from "../../../../lupin_app/static/js/multiplexer/shared/types";

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

// 5ebd2aff step 2 — the real response_options payloads, never a hand-typed option list.
const MC_QUESTIONS    = parseResponseQuestions(QUESTIONS_PAYLOAD.multiple_choice.response_options);
const BATCH_QUESTIONS = parseResponseQuestions(QUESTIONS_PAYLOAD.open_ended_batch.response_options);

function makeItem(over: Partial<ActionRequiredItem> = {}): ActionRequiredItem {
  return {
    id_hash       : "ar1",
    prompt        : "Proceed?",
    response_type : "yes_no",
    questions     : [],
    expires_at    : Date.now() + 30_000,
    timeout_seconds : 30,
    state         : "pending",
    ...over,
  };
}

// 360de81b — the two halves of the section body.
function slotOf(root: HTMLElement): HTMLElement {
  return root.querySelector<HTMLElement>('[data-testid="multiplexer-action-required-active-slot"]')!;
}

function queueOf(root: HTMLElement): HTMLElement {
  return root.querySelector<HTMLElement>('[data-testid="multiplexer-action-required-pending-queue"]')!;
}

function rowsOf(root: HTMLElement): HTMLElement[] {
  return Array.from(queueOf(root).querySelectorAll<HTMLElement>(".action-required-minimized"));
}

// Walk the real multiple_choice stepper to the last question and tick the fixture's answer.
function answerMc(root: HTMLElement): void {
  root.querySelector<HTMLInputElement>('input[value="PostgreSQL"]')!.checked = true;
  root.querySelector<HTMLButtonElement>(".action-required-btn-next")!.click();
  root.querySelector<HTMLInputElement>('input[value="Search"]')!.checked = true;
  root.querySelector<HTMLInputElement>('input[value="Audit log"]')!.checked = true;
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

test("multiple_choice submit (real payload, walked with Next) → respondAndAwait(idHash, { answers } keyed by header)", async () => {
  const { renderer, root, state } = setupRenderer();
  state.items.set("ar1", makeItem({ response_type: "multiple_choice", questions: MC_QUESTIONS }));
  renderer.mount(root);
  answerMc(root);
  root.querySelector<HTMLButtonElement>(".action-required-btn-submit")!.click();
  await flush();
  assert.deepEqual(state.respondCalls, [{ idHash: "ar1", response: QUESTIONS_PAYLOAD.multiple_choice.answers }]);
  renderer.unmount();
});

test("multiple_choice submit with the last question unanswered → no respondAndAwait call", async () => {
  const { renderer, root, state } = setupRenderer();
  state.items.set("ar1", makeItem({ response_type: "multiple_choice", questions: MC_QUESTIONS }));
  renderer.mount(root);
  root.querySelector<HTMLInputElement>('input[value="PostgreSQL"]')!.checked = true;
  root.querySelector<HTMLButtonElement>(".action-required-btn-next")!.click();
  root.querySelector<HTMLButtonElement>(".action-required-btn-submit")!.click();
  await flush();
  assert.deepEqual(state.respondCalls, []);
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

test("open_ended_batch submit (real payload) → respondAndAwait(idHash, { answers } keyed by header)", async () => {
  const { renderer, root, state } = setupRenderer();
  state.items.set("ar1", makeItem({ response_type: "open_ended_batch", questions: BATCH_QUESTIONS }));
  renderer.mount(root);
  root.querySelectorAll<HTMLInputElement>(".action-required-batch-input")[0]!.value = "quantum computing";
  root.querySelector<HTMLButtonElement>(".action-required-btn-submit-all")!.click();
  await flush();
  assert.deepEqual(state.respondCalls, [{ idHash: "ar1", response: QUESTIONS_PAYLOAD.open_ended_batch.answers }]);
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
  assert.ok( root.querySelector(".action-required-btn-yes") !== null, "Yes button still present" );
  assert.ok( root.querySelector(".action-required-error-stripe") !== null, "error stripe rendered" );
  renderer.unmount();
});

test("360de81b: multiple_choice error-rollback reopens on the LAST question with its ticks kept, and Back still shows question 1's choice", async () => {
  const { renderer, root, bus, state } = setupRenderer();
  const item = makeItem({ response_type: "multiple_choice", questions: MC_QUESTIONS });
  state.items.set("ar1", item);
  state.respondMode = "reject";
  renderer.mount(root);
  answerMc(root);
  root.querySelector<HTMLButtonElement>(".action-required-btn-submit")!.click();
  await flush();
  assert.equal(state.respondCalls.length, 1, "the answer was submitted, then rejected");
  state.items.set("ar1", { ...item, state: "submitting" });
  emitChange(bus, { changeKind: "responded-pending", id_hash: "ar1", response: QUESTIONS_PAYLOAD.multiple_choice.answers });
  state.items.set("ar1", { ...item, state: "failed" });
  emitChange(bus, { changeKind: "failed", id_hash: "ar1", response: QUESTIONS_PAYLOAD.multiple_choice.answers });
  assert.ok( root.querySelector(".action-required-error-stripe") !== null );
  assert.equal(root.querySelector(".action-required-question-indicator")!.textContent, "Question 2 of 2", "not dropped back to question 1");
  assert.deepEqual(
    Array.from(root.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'), b => [b.value, b.checked]),
    [["Search", true], ["Export", false], ["Audit log", true]],
  );
  root.querySelector<HTMLButtonElement>(".action-required-btn-back")!.click();
  assert.equal(root.querySelector<HTMLInputElement>('input[value="PostgreSQL"]')!.checked, true);
  renderer.unmount();
});

test("360de81b: a card that leaves the store forgets its stepper position — the same id arriving again starts at question 1", () => {
  const { renderer, root, bus, state } = setupRenderer();
  const item = makeItem({ response_type: "multiple_choice", questions: MC_QUESTIONS });
  state.items.set("ar1", item);
  renderer.mount(root);
  root.querySelector<HTMLInputElement>('input[value="PostgreSQL"]')!.checked = true;
  root.querySelector<HTMLButtonElement>(".action-required-btn-next")!.click();
  state.items.delete("ar1");
  emitChange(bus, { changeKind: "removed", id_hash: "ar1" });
  state.items.set("ar1", item);
  emitChange(bus, { changeKind: "added", id_hash: "ar1" });
  assert.equal(root.querySelector(".action-required-question-indicator")!.textContent, "Question 1 of 2");
  assert.equal(root.querySelector<HTMLInputElement>('input[value="PostgreSQL"]')!.checked, false);
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
  assert.ok( root.querySelector(".action-required-input") !== null );
  assert.ok( root.querySelector(".action-required-error-stripe") !== null );
  renderer.unmount();
});

test("open_ended_batch error-rollback: failed event preserves batch inputs", async () => {
  const { renderer, root, bus, state } = setupRenderer();
  const item = makeItem({ response_type: "open_ended_batch", questions: BATCH_QUESTIONS });
  state.items.set("ar1", item);
  state.respondMode = "reject";
  renderer.mount(root);
  root.querySelector<HTMLButtonElement>(".action-required-btn-submit-all")!.click();
  await flush();
  state.items.set("ar1", { ...item, state: "failed" });
  emitChange(bus, { changeKind: "failed", id_hash: "ar1", response: QUESTIONS_PAYLOAD.open_ended_batch.answers });
  assert.equal(root.querySelectorAll(".action-required-batch-input").length, 2);
  assert.ok( root.querySelector(".action-required-error-stripe") !== null );
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
  assert.ok( widget!.querySelector(".action-required-submitting-msg") !== null );
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
  assert.ok( root.querySelector(".action-required-btn-yes") !== null );
  assert.ok( root.querySelector(".action-required-error-stripe") !== null );
  renderer.unmount();
});

test("transition: failed → submitting retry (responded-pending after failed re-enters submitting)", () => {
  const { renderer, root, bus, state } = setupRenderer();
  state.items.set("ar1", makeItem({ state: "failed" }));
  renderer.mount(root);
  // Verify failed state has error stripe.
  assert.ok( root.querySelector(".action-required-error-stripe") !== null );
  // Retry: store transitions back to submitting.
  state.items.set("ar1", makeItem({ state: "submitting" }));
  emitChange(bus, { changeKind: "responded-pending", id_hash: "ar1", response: "yes" });
  assert.equal(root.querySelector<HTMLElement>('[data-id-hash="ar1"]')!.dataset.state, "submitting");
  // Error stripe should be gone after retry transition.
  assert.ok( root.querySelector(".action-required-error-stripe") === null );
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
  assert.ok( root.querySelector('[data-id-hash="ar1"]') === null );
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

  // AC2c — atomicity under the Lane 0a structure. On mount the renderer now
  // scaffolds a persistent `.section-header` bar + a `.section-content` wrapper,
  // ABSORBING the pre-seeded read-only widget INTO content, then swaps it in
  // place via replaceWith. So the root observer sees a bounded set of mount
  // scaffolding records (remove ro from root → add header + content), NOT an
  // unbounded re-render loop; the actual read-only→interactive swap happens
  // in-place inside content (replaceWith) so the widget is never observed
  // missing. Cap generously to catch a runaway loop while allowing the scaffold.
  assert.ok(records.length >= 1 && records.length <= 4, `expected 1-4 childList records (mount scaffold + in-place swap), got ${records.length}`);

  // Lane 0a: widgets live inside the `.section-content` wrapper, under the header.
  const contentWrap = root.querySelector(".section-content");
  assert.notEqual(contentWrap, null, "Lane 0a section-content wrapper present");
  assert.ok( root.querySelector(".section-header") !== null, "Lane 0a section-header bar present" );

  // The swap MUST result in exactly one widget for ar1 in the final DOM (not 0, not 2),
  // and it must live inside the content wrapper (not orphaned at the root).
  assert.equal(root.querySelectorAll('[data-id-hash="ar1"]').length, 1, "exactly one widget after swap");
  assert.equal(contentWrap!.querySelectorAll('[data-id-hash="ar1"]').length, 1, "widget nested in section-content");

  // All 4 inertness markers gone from the new widget.
  const newWidget = root.querySelector<HTMLElement>('[data-id-hash="ar1"]');
  assert.equal(newWidget!.getAttribute("data-phase6-pending"), null, "marker 1 gone: data-phase6-pending");
  assert.equal(newWidget!.getAttribute("aria-disabled"),       null, "marker 2 gone: aria-disabled");
  assert.equal(newWidget!.style.cursor,                          "", "marker 3 gone: cursor:not-allowed");
  assert.ok( newWidget!.querySelector(".action-required-pending-notice") === null, "marker 4 gone: pending-notice microcopy" );

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

// ===========================================================================
// 360de81b — ONE CARD AT A TIME: one full card in the active slot, the rest as minimized rows
// with a #N badge (legacy renderActionRequiredNotification :22825, renderMinimizedNotificationDOM
// :21498, recalculateQueuePositions :22767).
// ===========================================================================

test("360de81b: three items → ONE full widget in the active slot (the first) and two minimized rows #1, #2 in the pending queue", () => {
  const { renderer, root, state } = setupRenderer();
  state.items.set("ar1", makeItem({ id_hash: "ar1", prompt: "First?" }));
  state.items.set("ar2", makeItem({ id_hash: "ar2", prompt: "Second?", response_type: "multiple_choice", questions: MC_QUESTIONS, expires_at: null }));
  state.items.set("ar3", makeItem({ id_hash: "ar3", prompt: "Third?", response_type: "open_ended", expires_at: null, timeout_seconds: 45 }));
  renderer.mount(root);
  assert.equal(root.querySelectorAll(".action-required-widget").length, 1, "one full card, not three");
  assert.deepEqual(Array.from(slotOf(root).querySelectorAll<HTMLElement>(".action-required-widget"), w => w.dataset.idHash), ["ar1"]);
  assert.equal(slotOf(root).querySelectorAll(".action-required-countdown").length, 1, "only the active card counts down");
  const rows = rowsOf(root);
  assert.deepEqual(rows.map(r => r.dataset.idHash), ["ar2", "ar3"]);
  assert.deepEqual(rows.map(r => r.querySelector(".action-required-minimized-position")!.textContent), ["#1", "#2"]);
  assert.deepEqual(rows.map(r => r.querySelector(".action-required-minimized-message")!.textContent), ["Second?", "Third?"]);
  assert.equal(rows[1]!.querySelector(".action-required-minimized-timeout")!.textContent, "45s");
  assert.equal(queueOf(root).querySelectorAll("button, input").length, 0, "a queued card cannot be answered out of turn");
  renderer.unmount();
});

test("360de81b: when the active card leaves, the next one fills the slot and the remaining rows renumber", () => {
  const { renderer, root, bus, state } = setupRenderer();
  state.items.set("ar1", makeItem({ id_hash: "ar1" }));
  state.items.set("ar2", makeItem({ id_hash: "ar2", expires_at: null }));
  state.items.set("ar3", makeItem({ id_hash: "ar3", expires_at: null }));
  renderer.mount(root);
  state.items.delete("ar1");
  emitChange(bus, { changeKind: "removed", id_hash: "ar1" });
  state.items.set("ar2", makeItem({ id_hash: "ar2" }));          // the store activated it
  emitChange(bus, { changeKind: "activated", id_hash: "ar2" });
  assert.deepEqual(Array.from(slotOf(root).children, c => (c as HTMLElement).dataset.idHash), ["ar2"]);
  assert.ok(slotOf(root).querySelector(".action-required-countdown") !== null, "the promoted card shows its countdown");
  assert.deepEqual(rowsOf(root).map(r => [r.dataset.idHash, r.querySelector(".action-required-minimized-position")!.textContent]), [["ar3", "#1"]]);
  assert.equal(root.querySelector(".section-header-count")!.textContent, "2");
  renderer.unmount();
});

test("360de81b: a queued card arriving or leaving does NOT rebuild the active card — a half-made choice survives", () => {
  const { renderer, root, bus, state } = setupRenderer();
  state.items.set("ar1", makeItem({ id_hash: "ar1", response_type: "multiple_choice", questions: MC_QUESTIONS }));
  renderer.mount(root);
  const widget = slotOf(root).firstElementChild;
  root.querySelector<HTMLInputElement>('input[value="SQLite"]')!.checked = true;
  state.items.set("ar2", makeItem({ id_hash: "ar2", expires_at: null }));
  emitChange(bus, { changeKind: "added", id_hash: "ar2" });
  state.items.delete("ar2");
  emitChange(bus, { changeKind: "removed", id_hash: "ar2" });
  assert.equal(slotOf(root).firstElementChild, widget, "same element, not a rebuild");
  assert.equal(root.querySelector<HTMLInputElement>('input[value="SQLite"]')!.checked, true);
  assert.equal(rowsOf(root).length, 0);
  renderer.unmount();
});

test("360de81b: a tick for a queued card is a silent no-op — only the active card has a countdown", () => {
  const { renderer, root, bus, state } = setupRenderer();
  state.items.set("ar1", makeItem({ id_hash: "ar1" }));
  state.items.set("ar2", makeItem({ id_hash: "ar2", expires_at: null }));
  renderer.mount(root);
  const before = queueOf(root).textContent;
  emitChange(bus, { changeKind: "tick", id_hash: "ar2", countdownMs: 1000 });
  assert.equal(queueOf(root).textContent, before);
  renderer.unmount();
});

test("360de81b: answered in another session, the card shows 'Responded in another session' for its grace period instead of vanishing", () => {
  const { renderer, root, bus, state } = setupRenderer();
  state.items.set("ar1", makeItem({ state: "pending" }));
  renderer.mount(root);
  state.items.set("ar1", makeItem({ state: "cancelled" }));
  emitChange(bus, { changeKind: "cancelled", id_hash: "ar1" });
  const widget = root.querySelector<HTMLElement>('[data-id-hash="ar1"]')!;
  assert.equal(widget.dataset.state, "cancelled");
  assert.equal(widget.hidden, false, "legacy shows it for 1.5 s (:24541-24560)");
  assert.match(widget.textContent ?? "", /✓ Responded in another session/);
  renderer.unmount();
});

test("forceRenderForTesting: re-renders all items synchronously after mutation", () => {
  const { renderer, root, state } = setupRenderer();
  renderer.mount(root);
  // Add an item AFTER mount without firing a store event.
  state.items.set("ar1", makeItem());
  assert.ok( root.querySelector('[data-id-hash="ar1"]') === null, "no widget yet (no event)" );
  renderer.forceRenderForTesting();
  assert.ok( root.querySelector('[data-id-hash="ar1"]') !== null, "widget appears after force render" );
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
  assert.ok( root.querySelector('[data-id-hash="ar1"]') !== null );
  emitChange(bus, { changeKind: "offline-resumed", id_hash: "ar1", countdownMs: 25_000 });
  assert.ok( root.querySelector('[data-id-hash="ar1"]') !== null );
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

test("cancelled item still in the store (its grace period) renders a visible cancelled card", () => {
  const { renderer, root, state } = setupRenderer();
  state.items.set("ar1", makeItem({ state: "cancelled" }));
  renderer.mount(root);
  const card = root.querySelector<HTMLElement>('[data-id-hash="ar1"]');
  assert.notEqual(card, null);
  assert.equal(card!.dataset.state, "cancelled");
  assert.equal(card!.querySelector(".action-required-prompt")!.textContent, "Proceed?");
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

test("formatResponse: an { answers } response renders as 'header: value; ...', a multi-select value comma-joined", () => {
  // One card at a time (360de81b): each responded card is rendered in the slot in turn.
  const cases: Array<[ActionRequiredItem, RegExp]> = [
    [makeItem({ id_hash: "ar1", state: "responded", response: QUESTIONS_PAYLOAD.multiple_choice.answers }), /Responded: Database: PostgreSQL; Features: Search, Audit log/],
    [makeItem({ id_hash: "ar2", state: "responded", response: QUESTIONS_PAYLOAD.open_ended_batch.answers }), /Responded: Topic: quantum computing; Budget: no limit/],
    [makeItem({ id_hash: "ar3", state: "responded" }), /Responded: \(no response recorded\)/],   // no response field
  ];
  const { renderer, root, state } = setupRenderer();
  renderer.mount(root);
  for (const [item, expected] of cases) {
    state.items.clear();
    state.items.set(item.id_hash, item);
    renderer.forceRenderForTesting();
    assert.match(slotOf(root).querySelector<HTMLElement>(`[data-id-hash="${item.id_hash}"]`)!.textContent ?? "", expected);
  }
  renderer.unmount();
});

test("forceRenderForTesting before mount is a no-op (no throw)", () => {
  const { renderer } = setupRenderer();
  // Not mounted → forceRenderForTesting bails.
  renderer.forceRenderForTesting();
});

// ===========================================================================
// L2 (mux MVP-finish): `✓ No pending actions` empty-state — Phase-6b branches
//   (renderAll count===0, first-widget clears empty, last-remove repaints,
//    unmount-at-0 edge + unmount-with-items blank)
// ===========================================================================

test("empty: mount with zero items paints #action-required-empty (renderAll count===0)", () => {
  const { renderer, root } = setupRenderer();   // store empty by default
  renderer.mount(root);
  const empty = root.querySelector("#action-required-empty");
  assert.notEqual(empty, null, "empty panel painted on mount-at-0");
  assert.ok(empty!.classList.contains("action-required-empty-state"));
  assert.match(empty!.textContent ?? "", /No pending actions/);
  assert.ok( root.querySelector(".action-required-widget") === null, "no widgets when empty" );
  renderer.unmount();
});

test("empty: first widget added clears the empty panel (clearEmpty removes it)", () => {
  const { renderer, root, bus, state } = setupRenderer();
  renderer.mount(root);
  assert.ok( root.querySelector("#action-required-empty") !== null, "empty present before first item" );
  // A new AR item arrives.
  state.items.set("ar1", makeItem({ id_hash: "ar1" }));
  emitChange(bus, { changeKind: "added", id_hash: "ar1" });
  assert.ok( root.querySelector("#action-required-empty") === null, "empty removed once a widget paints" );
  assert.notEqual(root.querySelector<HTMLElement>('[data-id-hash="ar1"]'), null, "widget painted");
  renderer.unmount();
});

test("empty: removing the last widget repaints the empty panel (onChange list→0)", () => {
  const { renderer, root, bus, state } = setupRenderer();
  state.items.set("ar1", makeItem({ id_hash: "ar1" }));
  renderer.mount(root);
  assert.notEqual(root.querySelector<HTMLElement>('[data-id-hash="ar1"]'), null, "widget present");
  assert.ok( root.querySelector("#action-required-empty") === null, "no empty while a widget exists" );
  // Item evicted from the store → onChange sees getById undefined.
  state.items.delete("ar1");
  emitChange(bus, { changeKind: "cancelled", id_hash: "ar1" });
  assert.equal(root.querySelector<HTMLElement>('[data-id-hash="ar1"]'), null, "widget removed");
  assert.ok( root.querySelector("#action-required-empty") !== null, "empty repainted after last removal" );
  renderer.unmount();
});

test("empty: removing one of two widgets does NOT paint empty (list still non-empty)", () => {
  const { renderer, root, bus, state } = setupRenderer();
  state.items.set("ar1", makeItem({ id_hash: "ar1" }));
  state.items.set("ar2", makeItem({ id_hash: "ar2" }));
  renderer.mount(root);
  state.items.delete("ar1");
  emitChange(bus, { changeKind: "cancelled", id_hash: "ar1" });
  assert.ok( root.querySelector("#action-required-empty") === null, "no empty while ar2 remains" );
  assert.notEqual(root.querySelector<HTMLElement>('[data-id-hash="ar2"]'), null, "ar2 still present");
  renderer.unmount();
});

test("empty: unmount-at-0 paints #action-required-empty (boundary owner edge)", () => {
  const { renderer, root } = setupRenderer();   // store empty
  renderer.mount(root);
  renderer.unmount();
  // Phase-6b owns painting the empty-state on teardown so the panel is not blank
  // until the next AR event reaches Phase-5.
  assert.ok( root.querySelector("#action-required-empty") !== null, "empty painted on unmount-at-0" );
  assert.equal(root.dataset.phase6bOwner, undefined, "ownership released");
});

test("empty: unmount WITH items leaves a blank panel, not the empty-state (unmount else branch)", () => {
  const { renderer, root, state } = setupRenderer();
  state.items.set("ar1", makeItem({ id_hash: "ar1" }));
  renderer.mount(root);
  renderer.unmount();
  assert.ok( root.querySelector("#action-required-empty") === null, "no empty-state when items remained" );
  assert.ok( root.querySelector(".action-required-widget") === null, "children cleared on unmount" );
});

test("empty: forceRenderForTesting with zero items paints the empty panel", () => {
  const { renderer, root, state } = setupRenderer();
  state.items.set("ar1", makeItem({ id_hash: "ar1" }));
  renderer.mount(root);
  assert.ok( root.querySelector("#action-required-empty") === null, "widget present after mount" );
  // Store drained, then a full re-render is forced.
  state.items.clear();
  renderer.forceRenderForTesting();
  assert.ok( root.querySelector("#action-required-empty") !== null, "empty painted on force-render at 0" );
  renderer.unmount();
});

// ===========================================================================
// Lane 0a — uniform section-header bar (icon + title + count + collapse chevron)
// ===========================================================================

test("Lane 0a: mount renders the .section-header bar (⚠️ Action Required) + a .section-content wrapper", () => {
  const { renderer, root, state } = setupRenderer();
  state.items.set("ar1", makeItem({ id_hash: "ar1" }));
  state.items.set("ar2", makeItem({ id_hash: "ar2", prompt: "Also?" }));
  renderer.mount(root);

  const header = root.querySelector(".section-header") as HTMLElement;
  assert.notEqual(header, null, "section-header bar present");
  const h3 = header.querySelector("h3") as HTMLElement;
  assert.ok(h3.textContent!.includes("⚠️ Action Required"), "legacy title");
  // The active card and the queued row live inside the content wrapper, below the header.
  const content = root.querySelector(".section-content") as HTMLElement;
  assert.notEqual(content, null, "section-content wrapper present");
  assert.equal(content.querySelectorAll(".action-required-widget").length, 1, "the active card is nested in content");
  assert.equal(content.querySelectorAll(".action-required-minimized").length, 1, "the queued row is nested in content");
  assert.ok( root.firstElementChild === header, "header is the first child (above the body)" );
  renderer.unmount();
});

test("Lane 0a: the header count chip tracks the number of action-required items", () => {
  const { renderer, root, state, bus } = setupRenderer();
  state.items.set("ar1", makeItem({ id_hash: "ar1" }));
  renderer.mount(root);
  const count = root.querySelector(".section-header-count") as HTMLElement;
  assert.equal(count.textContent, "1", "count = 1 after mount with one item");

  // Add a second item + emit a change → count reflects 2.
  state.items.set("ar2", makeItem({ id_hash: "ar2" }));
  emitChange(bus, { changeKind: "added", id_hash: "ar2" });
  assert.equal(count.textContent, "2", "count = 2 after add");

  // Remove one (store eviction) + emit → count reflects 1.
  state.items.delete("ar1");
  emitChange(bus, { changeKind: "cancelled", id_hash: "ar1" });
  assert.equal(count.textContent, "1", "count = 1 after removal");
  renderer.unmount();
});

test("Lane 0a: clicking the header toggles session-only collapse (data-collapsed on root + chevron glyph)", () => {
  const { renderer, root, state } = setupRenderer();
  state.items.set("ar1", makeItem({ id_hash: "ar1", state: "pending" }));
  renderer.mount(root);
  const header = root.querySelector(".section-header") as HTMLElement;
  const chevron = header.querySelector(".toggle-button") as HTMLElement;
  assert.equal(chevron.textContent, "▼", "expanded glyph initially");

  // Click the header background (h3) → collapse (data-collapsed flips on the root).
  (header.querySelector("h3") as HTMLElement).dispatchEvent(new Event("click", { bubbles: true }));
  assert.equal(root.getAttribute("data-collapsed"), "true");
  assert.equal(chevron.textContent, "▶");

  // Click the chevron span → expand.
  chevron.dispatchEvent(new Event("click", { bubbles: true }));
  assert.equal(root.getAttribute("data-collapsed"), "false");
  assert.equal(chevron.textContent, "▼");

  // After unmount the collapse listener is detached — a header click is inert.
  renderer.unmount();
});
