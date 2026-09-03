// Task-list card — TaskListRenderer unit tests.
// 100% lines/branches/functions per the multiplexer coverage mandate.

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createTaskListRenderer,
  type TaskListStoreLike,
  type TaskListFleetLike,
} from "../../../../lupin_app/static/js/multiplexer/render/TaskListRenderer";
import type { TaskListComposite } from "../../../../lupin_app/static/js/multiplexer/render/taskListModel";
import type { TaskMutation, TaskPatchFields } from "../../../../lupin_app/static/js/multiplexer/stores/TaskListStore";
import { ApiError } from "../../../../lupin_app/static/js/multiplexer/api/ApiClient";
import type { FleetComposite } from "../../../../lupin_app/static/js/multiplexer/render/fleetModel";
import type { StoreTaskListChangedPayload } from "../../../../lupin_app/static/js/multiplexer/shared/types";
import { TASK_LIST_COLLAPSED_KEY } from "../../../../lupin_app/static/js/multiplexer/render/taskListCollapse";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

// Accordion state lives in localStorage — isolate every test.
beforeEach(() => { localStorage.clear(); });

// Drain microtasks so a mutation's .then/.catch/.finally chain settles.
const tick = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));

interface FakeStore extends TaskListStoreLike {
  setComposite(c: TaskListComposite | null): void;
  refreshCalls: number;
  patchArgs: Array<{ id: string; fields: TaskPatchFields }>;
  transitionArgs: Array<{ id: string; toStatus: string; extras: Record<string, string> }>;
  /** Whether the most recent mutation's restoreState() was invoked. */
  lastRestoreCalled(): boolean;
  /** Settle the most recent mutation's `done` promise. */
  settleLast(ok: boolean, err?: unknown): void;
}

function makeStore(): FakeStore {
  let composite: TaskListComposite | null = null;
  const patchArgs: Array<{ id: string; fields: TaskPatchFields }> = [];
  const transitionArgs: Array<{ id: string; toStatus: string; extras: Record<string, string> }> = [];
  let lastRestore = { called: false };
  let lastDeferred: { resolve: () => void; reject: (e: unknown) => void } | null = null;

  const makeMutation = (): TaskMutation => {
    const restore = { called: false };
    lastRestore = restore;
    const done = new Promise<void>((res, rej) => {
      lastDeferred = { resolve: () => res(), reject: rej };
    });
    return { restoreState: () => { restore.called = true; }, done };
  };

  const store: FakeStore = {
    refreshCalls: 0,
    patchArgs,
    transitionArgs,
    composite: () => composite,
    refresh: async (): Promise<void> => { store.refreshCalls += 1; },
    setComposite: (c) => { composite = c; },
    patchTask: (id: string, fields: TaskPatchFields): TaskMutation => { patchArgs.push({ id, fields }); return makeMutation(); },
    transitionTask: (id: string, toStatus: string, extras: Record<string, string>): TaskMutation => { transitionArgs.push({ id, toStatus, extras }); return makeMutation(); },
    lastRestoreCalled: () => lastRestore.called,
    settleLast: (ok, err) => { if (ok) lastDeferred!.resolve(); else lastDeferred!.reject(err); },
  };
  return store;
}

// A fake fleet store whose composite() drives the owner-reassignment roster.
function makeFleet(composite: FleetComposite | null): TaskListFleetLike {
  return { composite: () => composite };
}

const FIXED_DATE = (): Date => new Date("2026-06-16T18:30:07Z");

function setup( fleet?: TaskListFleetLike ): {
  bus: ReturnType<typeof createEventBusForTesting>;
  store: FakeStore;
  root: HTMLElement;
  emit: (stampUpdated: boolean) => void;
} {
  const bus = createEventBusForTesting();
  const store = makeStore();
  const r = createTaskListRenderer({ eventBus: bus, stores: { taskList: store, fleet }, nowDateFn: FIXED_DATE });
  const root = document.createElement("div");
  r.mount(root);
  const emit = (stampUpdated: boolean): void => {
    bus.emit<StoreTaskListChangedPayload>({
      type: "store_task_list_changed", payload: { stampUpdated }, source: "test", ts: 0,
    });
  };
  return { bus, store, root, emit };
}

const okComposite = (tasks: TaskListComposite["tasks"]): TaskListComposite => ({ tasks, count: tasks?.length ?? 0 });

// ---------------------------------------------------------------------------
// Chrome + initial paint
// ---------------------------------------------------------------------------

test("mount builds chrome (Lane 0a section-header: title, count, refresh, updated, container)", () => {
  const { root } = setup();
  // Lane 0a — bespoke .task-list-header → uniform .section-header (📋 Task List
  // in the <h3>); count in the shared .section-header-count chip.
  const hdr = root.querySelector(".section-header") as HTMLElement;
  assert.ok(hdr, "section-header bar present");
  assert.ok(hdr.querySelector("h3")!.textContent!.includes("📋 Task List"), "title in h3");
  assert.ok(root.querySelector(".section-header-count"));
  assert.ok(root.querySelector(".task-list-refresh"));
  assert.ok(root.querySelector(".task-list-updated"));
  assert.ok(root.querySelector(".task-list-container"));
});

test("mount twice throws", () => {
  const bus = createEventBusForTesting();
  const store = makeStore();
  const r = createTaskListRenderer({ eventBus: bus, stores: { taskList: store }, nowDateFn: FIXED_DATE });
  r.mount(document.createElement("div"));
  assert.throws(() => r.mount(document.createElement("div")), /already mounted/);
});

test("initial paint with null composite → unreachable indicator + 'no tasks loaded yet', count 0, no stamp", () => {
  const { root } = setup();
  assert.ok(root.querySelector(".task-list-unreachable"));
  assert.ok(root.querySelector(".task-list-empty"));
  assert.equal(root.querySelector(".section-header-count")?.textContent, "0");
  assert.equal(root.querySelector(".task-list-updated")?.textContent, ""); // no stamp on initial (stampUpdated=false path)
});

// ---------------------------------------------------------------------------
// auth_required
// ---------------------------------------------------------------------------

test("auth_required → sign-in banner, count 0", () => {
  const { root, store, emit } = setup();
  store.setComposite({ status: "auth_required" });
  emit(true);
  assert.ok(root.querySelector(".task-list-signin"));
  assert.equal(root.querySelector(".section-header-count")?.textContent, "0");
});

// ---------------------------------------------------------------------------
// ok path — table + empty
// ---------------------------------------------------------------------------

test("ok with open tasks → table renders, count = open count, stamp set", () => {
  const { root, store, emit } = setup();
  store.setComposite(okComposite([
    { id: "1", title: "live", status: "in_progress", owner_persona: "amy" },
    { id: "2", title: "done-one", status: "done", owner_persona: "amy" }, // terminal → filtered out
    { id: "3", title: "blocked-one", status: "blocked", owner_persona: "amy", blocked_by: "x", next_chase_ts: "2026-06-16T14:30:00-04:00" },
  ]));
  emit(true);
  assert.ok(root.querySelector(".task-list-table"));
  assert.equal(root.querySelector(".section-header-count")?.textContent, "2"); // done excluded
  // The blocked row surfaces blocked_by + next_chase.
  const blockedRow = root.querySelector(".task-status-blocked");
  assert.ok(blockedRow);
  assert.match(blockedRow?.textContent ?? "", /x/);
  assert.match(root.querySelector(".task-list-updated")?.textContent ?? "", /^updated /);
});

test("ok but all terminal → filtered to empty → 'No open tasks.', count 0", () => {
  const { root, store, emit } = setup();
  store.setComposite(okComposite([{ id: "1", title: "d", status: "done", owner_persona: "amy" }]));
  emit(true);
  assert.ok(root.querySelector(".task-list-empty"));
  assert.equal(root.querySelector(".task-list-empty")?.textContent, "✅ No open tasks.");
  assert.equal(root.querySelector(".section-header-count")?.textContent, "0");
});

// ---------------------------------------------------------------------------
// unreachable guard legs + graceful degradation (last-known rows)
// ---------------------------------------------------------------------------

test("explicit unreachable (no prior good) → indicator + 'no tasks loaded yet'", () => {
  const { root, store, emit } = setup();
  store.setComposite({ status: "unreachable", tasks: null });
  emit(true);
  assert.ok(root.querySelector(".task-list-unreachable"));
  assert.ok(root.querySelector(".task-list-empty"));
  assert.equal(root.querySelector(".section-header-count")?.textContent, "0");
});

test("composite with non-array tasks → unreachable branch (3rd OR leg)", () => {
  const { root, store, emit } = setup();
  store.setComposite({ count: 0 }); // no status, tasks undefined → !Array.isArray
  emit(true);
  assert.ok(root.querySelector(".task-list-unreachable"));
});

test("graceful degradation: good fetch then unreachable → last-known rows replayed under indicator", () => {
  const { root, store, emit } = setup();
  // 1) good fetch caches open rows.
  store.setComposite(okComposite([{ id: "1", title: "live", status: "in_progress", owner_persona: "amy" }]));
  emit(true);
  assert.ok(root.querySelector(".task-list-table"));
  assert.equal(root.querySelector(".section-header-count")?.textContent, "1");

  // 2) store goes unreachable — indicator + LAST-KNOWN table (never blank).
  store.setComposite({ status: "unreachable", tasks: null });
  emit(true);
  assert.ok(root.querySelector(".task-list-unreachable"), "indicator shown");
  assert.ok(root.querySelector(".task-list-table"), "last-known rows still rendered");
  assert.equal(root.querySelector(".section-header-count")?.textContent, "1", "count holds at last-known");
});

// ---------------------------------------------------------------------------
// refresh wiring + force render + unmount
// ---------------------------------------------------------------------------

test("refresh button click → store.refresh()", () => {
  const { root, store } = setup();
  (root.querySelector(".task-list-refresh") as HTMLButtonElement).click();
  assert.equal(store.refreshCalls, 1);
});

test("forceRenderForTesting repaints when mounted", () => {
  const { root, store } = setup();
  store.setComposite(okComposite([{ id: "1", title: "live", status: "queued", owner_persona: "amy" }]));
  const bus = createEventBusForTesting();
  const r = createTaskListRenderer({ eventBus: bus, stores: { taskList: store }, nowDateFn: FIXED_DATE });
  const root2 = document.createElement("div");
  r.mount(root2);
  r.forceRenderForTesting();
  assert.ok(root2.querySelector(".task-list-table"));
  // The original setup() root is untouched by the second renderer.
  assert.ok(root.querySelector(".task-list-container"));
});

test("unmount clears the root subtree", () => {
  const bus = createEventBusForTesting();
  const store = makeStore();
  const r = createTaskListRenderer({ eventBus: bus, stores: { taskList: store }, nowDateFn: FIXED_DATE });
  const root = document.createElement("div");
  r.mount(root);
  assert.ok(root.querySelector(".section-header"));
  r.unmount();
  assert.equal(root.childNodes.length, 0);
  // After unmount the subscription is detached — a later emit is a no-op (no throw).
  bus.emit<StoreTaskListChangedPayload>({ type: "store_task_list_changed", payload: { stampUpdated: true }, source: "test", ts: 0 });
});

// ---------------------------------------------------------------------------
// Per-persona accordion
// ---------------------------------------------------------------------------

const TWO_OWNERS = (): TaskListComposite => okComposite([
  { id: "1", title: "a1", status: "queued", owner_persona: "amy" },
  { id: "2", title: "b1", status: "queued", owner_persona: "bob" },
]);

test("accordion: mount renders collapse-all / expand-all controls in the header", () => {
  const { root } = setup();
  assert.ok(root.querySelector('[data-testid="multiplexer-task-list-collapse-all"]'));
  assert.ok(root.querySelector('[data-testid="multiplexer-task-list-expand-all"]'));
});

test("accordion: a persisted-collapsed owner renders collapsed", () => {
  localStorage.setItem(TASK_LIST_COLLAPSED_KEY, JSON.stringify(["amy"]));
  const { store, emit, root } = setup();
  store.setComposite(TWO_OWNERS());
  emit(true);
  const amy = root.querySelector<HTMLElement>('tbody.task-group[data-owner="amy"]');
  const bob = root.querySelector<HTMLElement>('tbody.task-group[data-owner="bob"]');
  assert.ok(amy?.classList.contains("collapsed"), "amy persisted-collapsed");
  assert.ok(!bob?.classList.contains("collapsed"), "bob expanded");
});

test("accordion: clicking an owner header toggles + persists + repaints collapsed", () => {
  const { store, emit, root } = setup();
  store.setComposite(TWO_OWNERS());
  emit(true);
  const header = root.querySelector<HTMLElement>('tbody.task-group[data-owner="amy"] .task-group-header');
  header?.dispatchEvent(new Event("click", { bubbles: true }));

  assert.deepEqual(JSON.parse(localStorage.getItem(TASK_LIST_COLLAPSED_KEY) ?? "[]"), ["amy"]);
  const amy = root.querySelector<HTMLElement>('tbody.task-group[data-owner="amy"]');
  assert.ok(amy?.classList.contains("collapsed"), "amy collapsed after click");
  // a second click expands again
  root.querySelector<HTMLElement>('tbody.task-group[data-owner="amy"] .task-group-header')
    ?.dispatchEvent(new Event("click", { bubbles: true }));
  assert.deepEqual(JSON.parse(localStorage.getItem(TASK_LIST_COLLAPSED_KEY) ?? "[]"), []);
});

test("accordion: a click that is not on a header is a no-op", () => {
  const { store, emit, root } = setup();
  store.setComposite(TWO_OWNERS());
  emit(true);
  const container = root.querySelector<HTMLElement>(".task-list-container");
  container?.dispatchEvent(new Event("click", { bubbles: true }));   // target = container, no header
  assert.equal(localStorage.getItem(TASK_LIST_COLLAPSED_KEY), null, "no toggle persisted");
});

test("accordion: keyboard — Enter & Space toggle a header; other keys + non-header ignored", () => {
  const { store, emit, root } = setup();
  store.setComposite(TWO_OWNERS());
  emit(true);
  const headerSel = 'tbody.task-group[data-owner="amy"] .task-group-header';
  const fire = (key: string, sel: string): void => {
    root.querySelector<HTMLElement>(sel)?.dispatchEvent(
      new KeyboardEvent("keydown", { key, bubbles: true }),
    );
  };

  // a non-toggle key on a header → ignored
  fire("a", headerSel);
  assert.equal(localStorage.getItem(TASK_LIST_COLLAPSED_KEY), null);

  // Enter toggles (collapse)
  fire("Enter", headerSel);
  assert.deepEqual(JSON.parse(localStorage.getItem(TASK_LIST_COLLAPSED_KEY) ?? "[]"), ["amy"]);

  // Space toggles (expand)
  fire(" ", headerSel);
  assert.deepEqual(JSON.parse(localStorage.getItem(TASK_LIST_COLLAPSED_KEY) ?? "[]"), []);

  // legacy "Spacebar" toggles (collapse)
  fire("Spacebar", headerSel);
  assert.deepEqual(JSON.parse(localStorage.getItem(TASK_LIST_COLLAPSED_KEY) ?? "[]"), ["amy"]);

  // a toggle key NOT on a header → ignored (state unchanged)
  fire("Enter", ".task-list-container");
  assert.deepEqual(JSON.parse(localStorage.getItem(TASK_LIST_COLLAPSED_KEY) ?? "[]"), ["amy"]);
});

test("accordion: collapse-all persists every owner + repaints all collapsed", () => {
  const { store, emit, root } = setup();
  store.setComposite(TWO_OWNERS());
  emit(true);
  root.querySelector<HTMLElement>('[data-testid="multiplexer-task-list-collapse-all"]')
    ?.dispatchEvent(new Event("click", { bubbles: true }));

  assert.deepEqual(
    JSON.parse(localStorage.getItem(TASK_LIST_COLLAPSED_KEY) ?? "[]").sort(),
    ["amy", "bob"],
  );
  const collapsed = [...root.querySelectorAll("tbody.task-group")].every((e) => e.classList.contains("collapsed"));
  assert.ok(collapsed, "every group collapsed after collapse-all");
});

test("accordion: expand-all clears the set + repaints all expanded", () => {
  localStorage.setItem(TASK_LIST_COLLAPSED_KEY, JSON.stringify(["amy", "bob"]));
  const { store, emit, root } = setup();
  store.setComposite(TWO_OWNERS());
  emit(true);
  root.querySelector<HTMLElement>('[data-testid="multiplexer-task-list-expand-all"]')
    ?.dispatchEvent(new Event("click", { bubbles: true }));

  assert.deepEqual(JSON.parse(localStorage.getItem(TASK_LIST_COLLAPSED_KEY) ?? "[]"), []);
  const anyCollapsed = [...root.querySelectorAll("tbody.task-group")].some((e) => e.classList.contains("collapsed"));
  assert.ok(!anyCollapsed, "no group collapsed after expand-all");
});

// ---------------------------------------------------------------------------
// Phase 2 — per-row editing: delegated change/click → store mutation
// ---------------------------------------------------------------------------

const FLEET = (): FleetComposite => ({
  fleet_arbiter: { sessions: [
    { persona: "amy" },
    { persona: "bob" },
    { persona: "Sam" },   // overflow persona — INCLUDED in the roster (Q5)
  ] },
});

// Render a single open task (owner "amy", priority "P2") with an optional fleet.
function renderOne( fleet?: TaskListFleetLike ): ReturnType<typeof setup> {
  const ctx = setup(fleet);
  ctx.store.setComposite(okComposite([
    { id: "t1", title: "one", status: "in_progress", owner_persona: "amy", priority: "P2" },
  ]));
  ctx.emit(true);
  return ctx;
}

function changeSelect( root: HTMLElement, selector: string, value: string ): void {
  const sel = root.querySelector<HTMLSelectElement>(selector);
  sel!.value = value;
  sel!.dispatchEvent(new Event("change", { bubbles: true }));
}

// Choose a verb the way the operator does — a real bubbling change event, never
// the handler called by name — then type a reason and press Submit.
function submitVerb( root: HTMLElement, verb: string, reason: string | null ): void {
  changeSelect(root, ".task-verb-select", verb);
  if (reason !== null) {
    const input = root.querySelector<HTMLInputElement>(".task-reason-input");
    input!.value = reason;
  }
  const btn = root.querySelector<HTMLButtonElement>(".task-submit-button");
  btn!.dispatchEvent(new Event("click", { bubbles: true }));
}

test("priority select change → patchTask({priority})", () => {
  const { store, root } = renderOne(makeFleet(FLEET()));
  changeSelect(root, ".task-priority-select", "P0");
  assert.deepEqual(store.patchArgs, [{ id: "t1", fields: { priority: "P0" } }]);
});

test("owner select change → patchTask({owner_persona})", () => {
  const { store, root } = renderOne(makeFleet(FLEET()));
  changeSelect(root, ".task-owner-select", "bob");
  assert.deepEqual(store.patchArgs, [{ id: "t1", fields: { owner_persona: "bob" } }]);
});

test("owner roster comes from the fleet store, INCLUDES Sam, includes current owner", () => {
  const { root } = renderOne(makeFleet(FLEET()));
  const sel = root.querySelector<HTMLSelectElement>(".task-owner-select");
  // Current owner "amy" prepended; live roster amy/bob/Sam alpha-sorted, deduped (Q5: Sam included).
  assert.deepEqual(Array.from(sel!.options).map(o => o.value), ["amy", "bob", "Sam"]);
});

test("no fleet store → owner select shows only the current owner", () => {
  const { root } = renderOne(undefined);
  const sel = root.querySelector<HTMLSelectElement>(".task-owner-select");
  assert.deepEqual(Array.from(sel!.options).map(o => o.value), ["amy"]);
});

test("fleet store present but null composite → empty roster (only current owner)", () => {
  const { root } = renderOne(makeFleet(null));
  const sel = root.querySelector<HTMLSelectElement>(".task-owner-select");
  assert.deepEqual(Array.from(sel!.options).map(o => o.value), ["amy"]);
});

test("Drop chosen + a non-blank reason → transitionTask(id, 'dropped', {reason})", () => {
  const { store, root } = renderOne(makeFleet(FLEET()));
  submitVerb(root, "drop", "superseded");
  assert.deepEqual(store.transitionArgs, [{ id: "t1", toStatus: "dropped", extras: { reason: "superseded" } }]);
  assert.ok( root.querySelector(".task-row-error-stripe") === null, "no error on a valid drop" );
});

test("Drop chosen + a blank reason → NO transition + inline error stripe", () => {
  const { store, root } = renderOne(makeFleet(FLEET()));
  submitVerb(root, "drop", "   ");   // whitespace-only → blank after trim
  assert.equal(store.transitionArgs.length, 0);
  const stripe = root.querySelector(".task-row-error-stripe");
  assert.ok(stripe, "error stripe rendered");
  assert.match(stripe?.textContent ?? "", /reason is required/i);
});

test("blank-reason error stripe does not stack on repeat", () => {
  const { root } = renderOne(makeFleet(FLEET()));
  submitVerb(root, "drop", "");
  submitVerb(root, "drop", "");
  assert.equal(root.querySelectorAll(".task-row-error-stripe").length, 1);
});

test("change on a non-control element is ignored", () => {
  const { store, root } = renderOne(makeFleet(FLEET()));
  root.querySelector(".task-col-title")!.dispatchEvent(new Event("change", { bubbles: true }));
  assert.equal(store.patchArgs.length, 0);
});

test("idless row → priority change and a submitted verb are both no-ops", () => {
  const ctx = setup(makeFleet(FLEET()));
  ctx.store.setComposite(okComposite([{ title: "noid", status: "queued", owner_persona: "amy" }]));
  ctx.emit(true);
  changeSelect(ctx.root, ".task-priority-select", "P0");
  submitVerb(ctx.root, "drop", "reason");
  assert.equal(ctx.store.patchArgs.length, 0);
  assert.equal(ctx.store.transitionArgs.length, 0);
});

test("in-flight dedupe: a second same-control edit is a no-op until the first settles", async () => {
  const { store, root } = renderOne(makeFleet(FLEET()));
  changeSelect(root, ".task-priority-select", "P0");
  changeSelect(root, ".task-priority-select", "P1");   // same key → deduped while in flight
  assert.equal(store.patchArgs.length, 1);
  store.settleLast(true);
  await tick();
  changeSelect(root, ".task-priority-select", "P3");   // key cleared → allowed again
  assert.equal(store.patchArgs.length, 2);
});

test("mutation success (2xx) → no rollback, no error stripe", async () => {
  const { store, root } = renderOne(makeFleet(FLEET()));
  changeSelect(root, ".task-priority-select", "P0");
  store.settleLast(true);
  await tick();
  assert.equal(store.lastRestoreCalled(), false);
  assert.ok( root.querySelector(".task-row-error-stripe") === null );
});

test("mutation ApiError 404 → treated as success (no rollback, no stripe)", async () => {
  const { store, root } = renderOne(makeFleet(FLEET()));
  changeSelect(root, ".task-priority-select", "P0");
  store.settleLast(false, new ApiError(404, "/api/tasks/t1", "gone"));
  await tick();
  assert.equal(store.lastRestoreCalled(), false);
  assert.ok( root.querySelector(".task-row-error-stripe") === null );
});

test("mutation ApiError (non-404) → rollback + error stripe with HTTP code", async () => {
  const { store, root } = renderOne(makeFleet(FLEET()));
  changeSelect(root, ".task-priority-select", "P0");
  store.settleLast(false, new ApiError(500, "/api/tasks/t1", "boom"));
  await tick();
  assert.equal(store.lastRestoreCalled(), true);
  const stripe = root.querySelector(".task-row-error-stripe");
  assert.match(stripe?.textContent ?? "", /Edit failed \(HTTP 500\)/);
});

test("mutation non-Api Error → rollback + generic error stripe", async () => {
  const { store, root } = renderOne(makeFleet(FLEET()));
  changeSelect(root, ".task-owner-select", "bob");
  store.settleLast(false, new Error("network down"));
  await tick();
  assert.equal(store.lastRestoreCalled(), true);
  const stripe = root.querySelector(".task-row-error-stripe");
  assert.match(stripe?.textContent ?? "", /Edit failed: network down/);
});

// ---------------------------------------------------------------------------
// Row redesign 2026.06.29 — detail 📄 body overlay (D2: renders the task body)
// ---------------------------------------------------------------------------

const withBody = (): TaskListComposite =>
  okComposite([{ id: "abcd1234-ef", title: "has detail", status: "queued", owner_persona: "amy", body: "the full body" }]);

const liveEmoji = (root: HTMLElement): HTMLElement =>
  root.querySelector<HTMLElement>(".task-detail-emoji:not(.task-detail-empty)")!;

test("detail 📄: clicking a live emoji opens the body overlay (D2 body); Escape dismisses + detaches", () => {
  const { store, emit, root } = setup();
  store.setComposite(withBody());
  emit(true);
  liveEmoji(root).dispatchEvent(new Event("click", { bubbles: true }));
  const overlay = document.getElementById("task-body-overlay");
  assert.ok(overlay, "overlay opened");
  assert.equal(overlay!.querySelector(".task-body-overlay-body")?.textContent, "the full body");
  assert.match(overlay!.querySelector(".task-body-overlay-header")?.textContent ?? "", /abcd1234/);
  document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
  assert.ok( document.getElementById("task-body-overlay") === null, "Escape dismissed" );
});

test("detail 📄: a non-Escape key does NOT dismiss the overlay", () => {
  const { store, emit, root } = setup();
  store.setComposite(withBody());
  emit(true);
  liveEmoji(root).dispatchEvent(new Event("click", { bubbles: true }));
  document.dispatchEvent(new KeyboardEvent("keydown", { key: "x" }));
  assert.ok(document.getElementById("task-body-overlay"), "non-Esc keeps it open");
  document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));   // cleanup
});

test("detail 📄: backdrop click dismisses; inner panel click does NOT", () => {
  const { store, emit, root } = setup();
  store.setComposite(withBody());
  emit(true);
  liveEmoji(root).dispatchEvent(new Event("click", { bubbles: true }));
  const overlay = document.getElementById("task-body-overlay")!;
  overlay.querySelector<HTMLElement>(".task-body-overlay-content")!
    .dispatchEvent(new Event("click", { bubbles: true }));   // inner — stopPropagation
  assert.ok(document.getElementById("task-body-overlay"), "inner-panel click keeps it open");
  overlay.dispatchEvent(new Event("click", { bubbles: true }));   // backdrop
  assert.ok( document.getElementById("task-body-overlay") === null, "backdrop click dismissed" );
});

test("detail 📄: Enter on a focused live emoji opens the overlay (keyboard a11y)", () => {
  const { store, emit, root } = setup();
  store.setComposite(withBody());
  emit(true);
  liveEmoji(root).dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
  assert.ok(document.getElementById("task-body-overlay"), "Enter on emoji opened the overlay");
  document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));   // cleanup
});

test("detail 📄: a DIMMED (empty-body) emoji click is inert — no overlay", () => {
  const { store, emit, root } = setup();
  store.setComposite(okComposite([{ id: "x", title: "no body", status: "queued", owner_persona: "amy" }]));
  emit(true);
  const dimmed = root.querySelector<HTMLElement>(".task-detail-emoji.task-detail-empty");
  assert.ok(dimmed, "dimmed emoji rendered for the body-less row");
  dimmed!.dispatchEvent(new Event("click", { bubbles: true }));
  assert.ok( document.getElementById("task-body-overlay") === null, "dimmed emoji opens nothing" );
});

test("detail 📄: a live emoji with NO dataset opens overlay with empty body/id (?? '' fallback)", () => {
  const { root } = setup();
  const container = root.querySelector<HTMLElement>(".task-list-container")!;
  const emoji = document.createElement("span");
  emoji.className = "task-detail-emoji";   // live (not dimmed), carries no data-task-* attrs
  container.appendChild(emoji);
  emoji.dispatchEvent(new Event("click", { bubbles: true }));
  const overlay = document.getElementById("task-body-overlay")!;
  assert.equal(overlay.querySelector(".task-body-overlay-body")?.textContent, "");
  assert.match(overlay.querySelector(".task-body-overlay-header")?.textContent ?? "", /Task detail/);
  document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));   // cleanup
});

test("detail 📄: unmount dismisses an open overlay + detaches its Esc listener", () => {
  const bus = createEventBusForTesting();
  const store = makeStore();
  const r = createTaskListRenderer({ eventBus: bus, stores: { taskList: store }, nowDateFn: FIXED_DATE });
  const root = document.createElement("div");
  r.mount(root);
  store.setComposite(withBody());
  bus.emit<StoreTaskListChangedPayload>({ type: "store_task_list_changed", payload: { stampUpdated: true }, source: "test", ts: 0 });
  liveEmoji(root).dispatchEvent(new Event("click", { bubbles: true }));
  assert.ok(document.getElementById("task-body-overlay"), "overlay open before unmount");
  r.unmount();
  assert.ok( document.getElementById("task-body-overlay") === null, "unmount tore the overlay down" );
});

// ---------------------------------------------------------------------------
// F1 (2026.07.01) — ID cell click-to-copy the FULL uuid
// ---------------------------------------------------------------------------

// A full uuid whose 8-char DISPLAY prefix ("3b85863e") differs from the copy
// payload — proving the handler copies the FULL id, not the visible slice.
const FULL_ID = "3b85863e-ccb9-49af-9f3c-0011deadbeef";

// Swap navigator.clipboard for the duration of a test; returns a restore fn.
function stubClipboard( impl: { writeText: ( t: string ) => Promise<void> } | undefined ): () => void {
  const original = Object.getOwnPropertyDescriptor( navigator, "clipboard" );
  Object.defineProperty( navigator, "clipboard", { value: impl, configurable: true } );
  return () => {
    if ( original ) { Object.defineProperty( navigator, "clipboard", original ); }
    else { delete ( navigator as { clipboard?: unknown } ).clipboard; }
  };
}

// Mount a renderer with a captured flash-timer, render the given tasks, return
// the root + the list of scheduled timers (so a test can fire the flash timeout).
function renderCopyableWith( tasks: TaskListComposite["tasks"] ): {
  root: HTMLElement;
  timers: Array<{ cb: () => void; ms: number }>;
} {
  const bus = createEventBusForTesting();
  const store = makeStore();
  const timers: Array<{ cb: () => void; ms: number }> = [];
  const r = createTaskListRenderer({
    eventBus: bus,
    stores: { taskList: store },
    nowDateFn: FIXED_DATE,
    setTimeoutFn: ( cb, ms ) => { timers.push( { cb, ms } ); return 0; },
  });
  const root = document.createElement("div");
  r.mount(root);
  store.setComposite( okComposite( tasks ) );
  bus.emit<StoreTaskListChangedPayload>({ type: "store_task_list_changed", payload: { stampUpdated: true }, source: "test", ts: 0 });
  return { root, timers };
}

const renderCopyable = (): ReturnType<typeof renderCopyableWith> =>
  renderCopyableWith([{ id: FULL_ID, title: "one", status: "in_progress", owner_persona: "amy", priority: "P2" }]);

test("F1: clicking the ID cell copies the FULL uuid + flashes a no-reflow copied state that reverts on timeout", async () => {
  const writes: string[] = [];
  const restore = stubClipboard({ writeText: ( t ) => { writes.push( t ); return Promise.resolve(); } });
  const { root, timers } = renderCopyable();
  const cell = root.querySelector<HTMLElement>("td.task-col-id")!;
  assert.equal(cell.textContent, "3b85863e");                 // display is the 8-char PREFIX
  cell.dispatchEvent(new Event("click", { bubbles: true }));
  await tick();
  assert.deepEqual(writes, [FULL_ID]);                        // …but the FULL uuid was copied
  assert.ok(cell.classList.contains("task-id-copied"));       // transient flash ON
  assert.equal(timers.length, 1);
  assert.equal(timers[0].ms, 1200);
  timers[0].cb();                                             // fire the flash timeout
  assert.ok(!cell.classList.contains("task-id-copied"));      // …flash reverted (no reflow, class only)
  restore();
});

test("F1: Enter and Space on the focused ID cell copy the full uuid (keyboard a11y)", async () => {
  const writes: string[] = [];
  const restore = stubClipboard({ writeText: ( t ) => { writes.push( t ); return Promise.resolve(); } });
  const { root } = renderCopyable();
  const cell = root.querySelector<HTMLElement>("td.task-col-id")!;
  cell.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
  await tick();
  cell.dispatchEvent(new KeyboardEvent("keydown", { key: " ", bubbles: true }));
  await tick();
  assert.deepEqual(writes, [FULL_ID, FULL_ID]);
  restore();
});

test("F1: clicking an idless (em-dash) ID cell is a no-op — nothing copied", async () => {
  const writes: string[] = [];
  const restore = stubClipboard({ writeText: ( t ) => { writes.push( t ); return Promise.resolve(); } });
  const { root } = renderCopyableWith([{ title: "no-id", status: "queued" }]);
  const cell = root.querySelector<HTMLElement>("td.task-col-id")!;
  assert.equal(cell.textContent, "—");
  cell.dispatchEvent(new Event("click", { bubbles: true }));
  await tick();
  assert.deepEqual(writes, []);
  restore();
});

test("F1: clipboard unavailable → graceful no-op (no throw, no flash)", () => {
  const restore = stubClipboard(undefined);
  const { root } = renderCopyable();
  const cell = root.querySelector<HTMLElement>("td.task-col-id")!;
  assert.doesNotThrow(() => cell.dispatchEvent(new Event("click", { bubbles: true })));
  assert.ok(!cell.classList.contains("task-id-copied"));
  restore();
});

test("F1: writeText rejection (permission denied) is swallowed — no flash, no throw", async () => {
  const restore = stubClipboard({ writeText: () => Promise.reject(new Error("denied")) });
  const { root, timers } = renderCopyable();
  const cell = root.querySelector<HTMLElement>("td.task-col-id")!;
  cell.dispatchEvent(new Event("click", { bubbles: true }));
  await tick();
  assert.ok(!cell.classList.contains("task-id-copied"));
  assert.equal(timers.length, 0);
  restore();
});

// ---------------------------------------------------------------------------
// Row-control conversion 2026.09.02 — the four ADDED verbs.
//
// This card had ONE verb before tonight. Drop's path was already guarded, so the
// tests above re-point cleanly and prove almost nothing about the conversion:
// what is new is park, demote, won't-fix and approve, the legality that decides
// which of them a row may take, the date affordance two of them need, and the
// two-click confirm the terminal one earns. Every sweep below states how many
// verbs it drove, because a loop that drives none passes every assertion in it.
// ---------------------------------------------------------------------------

// Denominator, measured off the tree: taskVerbs.TASK_VERBS carries five.
const CONVERSION_VERB_FLOOR = 5;

// Render one row in a chosen status, so a test can reach a verb that is only
// legal from somewhere other than in_progress (approve needs not_approved).
function renderInStatus( status: string ): ReturnType<typeof setup> {
  const ctx = setup(makeFleet(FLEET()));
  ctx.store.setComposite(okComposite([
    { id: "t1", title: "one", status, owner_persona: "amy", priority: "P2" },
  ]));
  ctx.emit(true);
  return ctx;
}

function reasonBox( root: HTMLElement ): HTMLInputElement {
  return root.querySelector<HTMLInputElement>(".task-reason-input")!;
}
function submitBtn( root: HTMLElement ): HTMLButtonElement {
  return root.querySelector<HTMLButtonElement>(".task-submit-button")!;
}
function clickSubmit( root: HTMLElement ): void {
  submitBtn(root).dispatchEvent(new Event("click", { bubbles: true }));
}
function setDate( root: HTMLElement, day: string ): void {
  root.querySelector<HTMLInputElement>(".task-chase-input")!.value = day;
}

test("Submit with NO verb chosen → a stripe saying so, and no store call", () => {
  const { store, root } = renderOne(makeFleet(FLEET()));
  clickSubmit(root);
  assert.equal(store.transitionArgs.length, 0);
  assert.match(root.querySelector(".task-row-error-stripe")?.textContent ?? "",
    /choose an action first/i);
});

test("choosing a verb sets THAT verb's placeholder — five distinct captions, one box", () => {
  const { root } = renderInStatus("in_progress");
  const seen = new Set<string>();
  let driven = 0;
  for (const verb of ["park", "drop", "demote", "wont_fix", "approve"]) {
    changeSelect(root, ".task-verb-select", verb);
    seen.add(reasonBox(root).placeholder);
    driven += 1;
  }
  assert.equal(driven, CONVERSION_VERB_FLOOR, `drove ${driven} of ${CONVERSION_VERB_FLOOR} verbs`);
  assert.equal(seen.size, CONVERSION_VERB_FLOOR,
    `one shared box must not flatten ${CONVERSION_VERB_FLOOR} obligations into one caption; ${seen.size} distinct`);
});

test("un-choosing a verb returns the box to its resting caption", () => {
  const { root } = renderOne(makeFleet(FLEET()));
  changeSelect(root, ".task-verb-select", "drop");
  changeSelect(root, ".task-verb-select", "");
  assert.equal(reasonBox(root).placeholder, "reason…");
  assert.equal(reasonBox(root).disabled, false);
});

test("Approve DISABLES the shared reason field and clears whatever was typed", () => {
  // Rick's ruling. A live box beside a verb that discards its contents invites a
  // justification nothing will ever read.
  const { root } = renderInStatus("not_approved");
  changeSelect(root, ".task-verb-select", "drop");
  reasonBox(root).value = "typed before switching";
  changeSelect(root, ".task-verb-select", "approve");
  assert.equal(reasonBox(root).disabled, true);
  assert.equal(reasonBox(root).value, "", "text left in a disabled box would be posted by the next verb");
});

test("switching AWAY from approve re-enables the box", () => {
  const { root } = renderInStatus("not_approved");
  changeSelect(root, ".task-verb-select", "approve");
  changeSelect(root, ".task-verb-select", "drop");
  assert.equal(reasonBox(root).disabled, false);
});

test("a date input appears for EXACTLY the two verbs that need one, labelled for each", () => {
  const { root } = renderInStatus("in_progress");
  const EXPECT: ReadonlyArray<[string, string | null]> = [
    ["park", "Chase me again on"], ["drop", null], ["demote", "Triage this by"],
    ["wont_fix", null], ["approve", null],
  ];
  assert.equal(EXPECT.length, CONVERSION_VERB_FLOOR, "every verb must be driven");
  let withDate = 0, withoutDate = 0;
  for (const [verb, label] of EXPECT) {
    changeSelect(root, ".task-verb-select", verb);
    const date = root.querySelector<HTMLInputElement>(".task-chase-input");
    if (label === null) { assert.equal(date, null, `${verb}: an unwanted date box`); withoutDate += 1; }
    else {
      assert.ok(date, `${verb}: no date box`);
      assert.equal(date!.type, "date");
      assert.equal(date!.getAttribute("aria-label"), label, `${verb}: the caption must say what the date DOES`);
      withDate += 1;
    }
  }
  assert.equal(withDate, 2, `two dated verbs expected; ${withDate} seen`);
  assert.equal(withoutDate, 3, `three undated verbs expected; ${withoutDate} seen`);
});

test("the date box is REUSED across two dated verbs, not stacked", () => {
  const { root } = renderInStatus("in_progress");
  changeSelect(root, ".task-verb-select", "park");
  setDate(root, "2026-09-10");
  changeSelect(root, ".task-verb-select", "demote");
  assert.equal(root.querySelectorAll(".task-chase-input").length, 1, "one date box, relabelled");
  assert.equal(root.querySelector<HTMLInputElement>(".task-chase-input")!.getAttribute("aria-label"), "Triage this by");
});

test("the date box sits BEFORE Submit, so the row reads left to right", () => {
  const { root } = renderInStatus("in_progress");
  changeSelect(root, ".task-verb-select", "park");
  // Scope to the ROW. `.task-col-actions` is on the header <th> too, and it comes
  // first in document order — so a root-level query returns a cell with no
  // controls in it, and every "0 found" that follows reads like a broken render.
  const cell = root.querySelector<HTMLElement>(".task-row .task-col-actions")!;
  assert.ok(cell, "the row's own actions cell must be found, not the header's");
  // Walk the element chain rather than indexing a collection: a live
  // HTMLCollection hangs under happy-dom.
  const order: string[] = [];
  for (let el = cell.firstElementChild; el !== null; el = el.nextElementSibling) order.push(el.className);
  assert.ok(order.length >= 5,
    `positive control: priority, owner, verb, reason, date and Submit; ${order.length} children walked`);
  const dateAt   = order.findIndex(c => c.includes("task-chase-input"));
  const submitAt = order.findIndex(c => c.includes("task-submit-button"));
  assert.ok(dateAt >= 0 && submitAt >= 0, `both controls must be found: date=${dateAt} submit=${submitAt}`);
  assert.ok(dateAt < submitAt, `the date box must precede Submit; date=${dateAt} submit=${submitAt}`);
});

test("Park submits parked with park_reason AND a chase instant — never the generic key", () => {
  const { store, root } = renderInStatus("in_progress");
  changeSelect(root, ".task-verb-select", "park");
  reasonBox(root).value = "the sentence that decided it";
  setDate(root, "2026-09-10");
  clickSubmit(root);
  assert.equal(store.transitionArgs.length, 1);
  const [call] = store.transitionArgs;
  assert.equal(call!.toStatus, "parked");
  assert.equal(call!.extras.park_reason, "the sentence that decided it");
  assert.ok(!("reason" in call!.extras), "a park under the generic key carries no decisive sentence");
  assert.match(call!.extras.next_chase_ts!, /^2026-09-10T/, "the local calendar day became an instant");
});

test("Demote submits not_approved with reason AND a triage-by instant", () => {
  const { store, root } = renderInStatus("in_progress");
  changeSelect(root, ".task-verb-select", "demote");
  reasonBox(root).value = "back to triage";
  setDate(root, "2026-09-11");
  clickSubmit(root);
  assert.deepEqual(store.transitionArgs.map(c => c.toStatus), ["not_approved"]);
  assert.equal(store.transitionArgs[0]!.extras.reason, "back to triage");
  assert.ok("next_chase_ts" in store.transitionArgs[0]!.extras);
});

test("Approve submits queued with an EMPTY body — no reason, no date", () => {
  const { store, root } = renderInStatus("not_approved");
  changeSelect(root, ".task-verb-select", "approve");
  clickSubmit(root);
  assert.deepEqual(store.transitionArgs, [{ id: "t1", toStatus: "queued", extras: {} }]);
});

test("a dated verb with no date → that verb's OWN complaint, and no store call", () => {
  const CASES: ReadonlyArray<[string, RegExp]> = [
    ["park", /chase date is required/i], ["demote", /triage-by date is required/i],
  ];
  assert.equal(CASES.length, 2, "both dated verbs must be driven");
  let driven = 0;
  for (const [verb, pattern] of CASES) {
    const { store, root } = renderInStatus("in_progress");
    changeSelect(root, ".task-verb-select", verb);
    reasonBox(root).value = "a reason";
    clickSubmit(root);
    assert.equal(store.transitionArgs.length, 0, `${verb}: submitted without a date`);
    assert.match(root.querySelector(".task-row-error-stripe")?.textContent ?? "", pattern);
    driven += 1;
  }
  assert.equal(driven, 2, `drove ${driven} of 2 dated verbs`);
});

test("each reason-taking verb earns its OWN blank-reason complaint, not a shared one", () => {
  const CASES: ReadonlyArray<[string, string, RegExp]> = [
    ["in_progress", "park", /quote the row's own decisive sentence/i],
    ["in_progress", "drop", /a drop reason is required/i],
    ["in_progress", "demote", /why this goes back to triage/i],
    ["in_progress", "wont_fix", /a refusal carries its justification/i],
  ];
  assert.equal(CASES.length, 4, "four verbs take a reason; approve does not");
  const messages = new Set<string>();
  for (const [status, verb, pattern] of CASES) {
    const { store, root } = renderInStatus(status);
    changeSelect(root, ".task-verb-select", verb);
    clickSubmit(root);
    assert.equal(store.transitionArgs.length, 0, `${verb}: submitted with a blank reason`);
    const text = root.querySelector(".task-row-error-stripe")?.textContent ?? "";
    assert.match(text, pattern, `${verb}: wrong or generic complaint`);
    messages.add(text);
  }
  assert.equal(messages.size, 4, `four distinct complaints required; ${messages.size} seen`);
});

test("an unparseable date is refused BY NAME, and nothing is posted", () => {
  // A real `<input type="date">` refuses an invalid value outright — assigning
  // "not-a-day" leaves it empty, which is why the first draft of this test hit
  // the blank-date complaint instead. The bad string can only reach the handler
  // from a runtime that degraded the input to a plain text box, so that is the
  // condition driven here rather than one the widget makes impossible.
  const { store, root } = renderInStatus("in_progress");
  changeSelect(root, ".task-verb-select", "park");
  reasonBox(root).value = "why";
  const date = root.querySelector<HTMLInputElement>(".task-chase-input")!;
  date.type  = "text";                 // the degraded runtime
  date.value = "not-a-day";
  assert.equal(date.value, "not-a-day", "positive control: the bad string must actually be in the box");
  clickSubmit(root);
  assert.equal(store.transitionArgs.length, 0);
  assert.match(root.querySelector(".task-row-error-stripe")?.textContent ?? "", /date not understood: not-a-day/i);
});

// --- the two-click confirm, which only won't-fix earns ----------------------

test("Won't-fix takes TWO clicks: the first ARMS in the page, and posts nothing", () => {
  // Rick's ruling: the confirmation is on the button's own label, never a
  // browser confirm() — a modal blocks the extension's event loop, so the one
  // control that closes a row for good must not be the one that freezes the board.
  const { store, root } = renderInStatus("in_progress");
  changeSelect(root, ".task-verb-select", "wont_fix");
  reasonBox(root).value = "will not be done";
  clickSubmit(root);
  assert.equal(store.transitionArgs.length, 0, "the first click must not transition");
  assert.equal(submitBtn(root).dataset.armed, "1");
  assert.equal(submitBtn(root).textContent, "Confirm won't fix");
  assert.ok(submitBtn(root).classList.contains("task-submit-armed"));
  clickSubmit(root);
  assert.deepEqual(store.transitionArgs, [{ id: "t1", toStatus: "wont_fix", extras: { reason: "will not be done" } }]);
});

test("every NON-terminal verb submits on ONE click — the arming is won't-fix's alone", () => {
  const SINGLE: ReadonlyArray<[string, string, string]> = [
    ["in_progress", "park", "parked"], ["in_progress", "drop", "dropped"],
    ["in_progress", "demote", "not_approved"], ["not_approved", "approve", "queued"],
  ];
  assert.equal(SINGLE.length, CONVERSION_VERB_FLOOR - 1,
    `${CONVERSION_VERB_FLOOR - 1} single-click verbs expected; ${SINGLE.length} driven`);
  let driven = 0;
  for (const [status, verb, toStatus] of SINGLE) {
    const { store, root } = renderInStatus(status);
    changeSelect(root, ".task-verb-select", verb);
    reasonBox(root).value = "a reason";
    if (root.querySelector(".task-chase-input") !== null) setDate(root, "2026-09-10");
    clickSubmit(root);
    assert.deepEqual(store.transitionArgs.map(c => c.toStatus), [toStatus],
      `${verb}: did not transition on the first click`);
    driven += 1;
  }
  assert.equal(driven, SINGLE.length, `drove ${driven} of ${SINGLE.length}`);
});

test("changing the verb DISARMS Submit — an armed button must not outlive its verb", () => {
  // Otherwise the operator switches to Drop, clicks once expecting the usual
  // single click, and that click is swallowed by a confirmation for a verb they
  // have already left.
  const { store, root } = renderInStatus("in_progress");
  changeSelect(root, ".task-verb-select", "wont_fix");
  reasonBox(root).value = "will not be done";
  clickSubmit(root);
  assert.equal(submitBtn(root).dataset.armed, "1");

  changeSelect(root, ".task-verb-select", "drop");
  assert.equal(submitBtn(root).dataset.armed, undefined, "the arming survived a change of verb");
  assert.equal(submitBtn(root).textContent, "Submit");
  assert.equal(submitBtn(root).classList.contains("task-submit-armed"), false);

  reasonBox(root).value = "dropped instead";
  clickSubmit(root);
  assert.deepEqual(store.transitionArgs.map(c => c.toStatus), ["dropped"],
    "the click after a re-choice must act, not confirm");
});

test("a REFUSED confirm disarms — an arming must not survive a blanked reason", () => {
  // Arm won't-fix, clear the box, get refused. If the button stayed armed the
  // next click would close the row on a confirmation never successfully given.
  const { store, root } = renderInStatus("in_progress");
  changeSelect(root, ".task-verb-select", "wont_fix");
  reasonBox(root).value = "will not be done";
  clickSubmit(root);
  assert.equal(submitBtn(root).dataset.armed, "1");

  reasonBox(root).value = "";
  clickSubmit(root);
  assert.equal(store.transitionArgs.length, 0);
  assert.equal(submitBtn(root).dataset.armed, undefined, "a refusal left the button armed");
  assert.equal(submitBtn(root).textContent, "Submit");
});

test("a successful submit clears a stripe left by an earlier refusal", () => {
  const { root } = renderInStatus("in_progress");
  changeSelect(root, ".task-verb-select", "drop");
  clickSubmit(root);                                   // blank → stripe
  assert.ok(root.querySelector(".task-row-error-stripe"));
  reasonBox(root).value = "now with a reason";
  clickSubmit(root);
  assert.equal(root.querySelector(".task-row-error-stripe"), null,
    "an empty message must CLEAR the stripe, not paint a wordless one");
});

test("a terminal row never reaches the table at all — there is no control to click", () => {
  // The renderer shows OPEN work only, so done / dropped / wont_fix rows are
  // filtered before the cell is ever built. The cell's own terminal branch — the
  // greyed options and the disabled select — is therefore reachable from the
  // template and not from here, and it is guarded in task_row_control.test.ts.
  // Saying that plainly beats a renderer test that asserts a control it can
  // never obtain.
  const TERMINAL = ["done", "dropped", "wont_fix"];
  assert.equal(TERMINAL.length, 3, "positive control: three terminal statuses");
  let checked = 0;
  for (const status of TERMINAL) {
    const { store, root } = renderInStatus(status);
    assert.equal(root.querySelectorAll(".task-row").length, 0, `${status}: a terminal row was rendered`);
    assert.equal(root.querySelectorAll(".task-verb-select").length, 0, `${status}: a terminal row got controls`);
    assert.equal(store.transitionArgs.length, 0);
    checked += 1;
  }
  assert.equal(checked, 3, `checked ${checked} of 3`);
  // The other arm: an OPEN row in the same fixture DOES render, so the zero
  // above is the filter working and not the fixture rendering nothing at all.
  const { root } = renderInStatus("in_progress");
  assert.equal(root.querySelectorAll(".task-verb-select").length, 1,
    "positive control: an open row must render exactly one verb select");
});

test("two rows do not share a control — a verb chosen on one leaves the other at rest", () => {
  const ctx = setup(makeFleet(FLEET()));
  ctx.store.setComposite(okComposite([
    { id: "t1", title: "one", status: "in_progress", owner_persona: "amy" },
    { id: "t2", title: "two", status: "in_progress", owner_persona: "amy" },
  ]));
  ctx.emit(true);
  const rows = Array.from(ctx.root.querySelectorAll<HTMLElement>(".task-row"));
  assert.equal(rows.length, 2, `positive control: two rows rendered, ${rows.length} found`);

  const sel = rows[0]!.querySelector<HTMLSelectElement>(".task-verb-select")!;
  sel.value = "park";
  sel.dispatchEvent(new Event("change", { bubbles: true }));

  assert.equal(rows[0]!.querySelectorAll(".task-chase-input").length, 1, "row 1 got its date box");
  assert.equal(rows[1]!.querySelectorAll(".task-chase-input").length, 0, "row 2 grew a date box it never asked for");
  assert.equal(rows[1]!.querySelector<HTMLInputElement>(".task-reason-input")!.placeholder, "reason…");

  rows[0]!.querySelector<HTMLInputElement>(".task-reason-input")!.value = "why";
  rows[0]!.querySelector<HTMLInputElement>(".task-chase-input")!.value  = "2026-09-10";
  rows[0]!.querySelector<HTMLButtonElement>(".task-submit-button")!.dispatchEvent(new Event("click", { bubbles: true }));
  assert.deepEqual(ctx.store.transitionArgs.map(c => c.id), ["t1"], "the wrong row was transitioned");
});
