// Task-list card — TaskListRenderer unit tests.
// 100% lines/branches/functions per the multiplexer coverage mandate.

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createTaskListRenderer,
  type TaskListStoreLike,
} from "../../../../lupin_app/static/js/multiplexer/render/TaskListRenderer";
import type { TaskListComposite } from "../../../../lupin_app/static/js/multiplexer/render/taskListModel";
import type { StoreTaskListChangedPayload } from "../../../../lupin_app/static/js/multiplexer/shared/types";
import { TASK_LIST_COLLAPSED_KEY } from "../../../../lupin_app/static/js/multiplexer/render/taskListCollapse";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

// Accordion state lives in localStorage — isolate every test.
beforeEach(() => { localStorage.clear(); });

interface FakeStore extends TaskListStoreLike {
  setComposite(c: TaskListComposite | null): void;
  refreshCalls: number;
}

function makeStore(): FakeStore {
  let composite: TaskListComposite | null = null;
  const store: FakeStore = {
    refreshCalls: 0,
    composite: () => composite,
    refresh: async (): Promise<void> => { store.refreshCalls += 1; },
    setComposite: (c) => { composite = c; },
  };
  return store;
}

const FIXED_DATE = (): Date => new Date("2026-06-16T18:30:07Z");

function setup(): {
  bus: ReturnType<typeof createEventBusForTesting>;
  store: FakeStore;
  root: HTMLElement;
  emit: (stampUpdated: boolean) => void;
} {
  const bus = createEventBusForTesting();
  const store = makeStore();
  const r = createTaskListRenderer({ eventBus: bus, stores: { taskList: store }, nowDateFn: FIXED_DATE });
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

test("mount builds chrome (title, count, refresh, updated, container)", () => {
  const { root } = setup();
  assert.ok(root.querySelector(".task-list-title"));
  assert.ok(root.querySelector(".task-list-count"));
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
  assert.equal(root.querySelector(".task-list-count")?.textContent, "0");
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
  assert.equal(root.querySelector(".task-list-count")?.textContent, "0");
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
  assert.equal(root.querySelector(".task-list-count")?.textContent, "2"); // done excluded
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
  assert.equal(root.querySelector(".task-list-count")?.textContent, "0");
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
  assert.equal(root.querySelector(".task-list-count")?.textContent, "0");
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
  assert.equal(root.querySelector(".task-list-count")?.textContent, "1");

  // 2) store goes unreachable — indicator + LAST-KNOWN table (never blank).
  store.setComposite({ status: "unreachable", tasks: null });
  emit(true);
  assert.ok(root.querySelector(".task-list-unreachable"), "indicator shown");
  assert.ok(root.querySelector(".task-list-table"), "last-known rows still rendered");
  assert.equal(root.querySelector(".task-list-count")?.textContent, "1", "count holds at last-known");
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
  assert.ok(root.querySelector(".task-list-header"));
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
