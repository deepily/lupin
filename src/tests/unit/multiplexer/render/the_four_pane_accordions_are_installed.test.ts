// 🔴 THE FOUR PANE ACCORDIONS ARE INSTALLED — a CALL-SITE guard, not a helper guard.
//
// WHY THIS FILE EXISTS. `wireSectionCollapse` was already covered: break the
// function itself and four named tests redden (measured — see the arm table
// below). What NOTHING watched was whether the four panes this row built ever
// CALL it. Deleting `this.collapseOff = wireSectionCollapse( root, header )`
// from FleetStatusRenderer, TaskListRenderer, HoldingAreaRenderer and
// EpicBoardRenderer — one at a time, anchor 1x, sha verified, restored
// byte-exact — left the suite at 2387 passed / 0 failed EVERY TIME.
//
//   arm                                        population        reds
//   P  break wireSectionCollapse itself        126 mux test.ts   4  <- the helper IS guarded
//   C1 delete FleetStatus  call site           126 mux test.ts   0  <- the call site is NOT
//   C2 delete TaskList     call site           render/*.test.ts  0
//   C3 delete HoldingArea  call site           render/*.test.ts  0
//   C4 delete EpicBoard    call site           render/*.test.ts  0
//
// That is § IMPLEMENTED BUT NOT INSTALLED: the helper at full coverage, the
// wiring invisible to the suite, so a revert of any one of those four lines
// ships silently. Arm P is also this file's positive control — a zero from an
// instrument nobody has watched return a one is worth nothing.
//
// ⚠️ THE CORPUS IS ASSERTED, NOT ASSUMED. A loop over an empty array passes
// every per-item assertion inside it. `test_the_corpus_is_the_whole_surface`
// pins the denominator at 4, so shrinking PANES reddens rather than quietly
// measuring less.
//
// ⚠️ AND EACH PANE CARRIES A NEGATIVE LEG. A wiring that collapsed on EVERY
// click would satisfy the toggle assertions and be wrong; clicking the pane's
// own refresh button must NOT collapse it. A guard satisfied by refusing
// everything is not a guard.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createFleetStatusRenderer } from "../../../../lupin_app/static/js/multiplexer/render/FleetStatusRenderer";
import { createTaskListRenderer } from "../../../../lupin_app/static/js/multiplexer/render/TaskListRenderer";
import { createHoldingAreaRenderer } from "../../../../lupin_app/static/js/multiplexer/render/HoldingAreaRenderer";
import { createEpicBoardRenderer } from "../../../../lupin_app/static/js/multiplexer/render/EpicBoardRenderer";
import type { TaskMutation } from "../../../../lupin_app/static/js/multiplexer/stores/TaskListStore";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

const FIXED_DATE = (): Date => new Date("2026-06-10T18:30:07Z");

// A mutation handle that never settles — nothing here drives a write, and an
// un-awaited promise is the honest shape for "this leg does not exercise it".
const inertMutation = (): TaskMutation => ({
  restoreState: () => {},
  done: new Promise<void>(() => {}),
});

// The panes mount BEFORE any data arrives, so every store answers `null`. That
// is deliberate: this file measures the CHROME's wiring, and a fixture carrying
// rows would let a row-level handler satisfy an assertion the header owns.
const emptyTaskStore = {
  composite: () => null,
  refresh: async (): Promise<void> => {},
  patchTask: (): TaskMutation => inertMutation(),
  transitionTask: (): TaskMutation => inertMutation(),
};

const emptyHoldingStore = {
  composite: () => null,
  refresh: async (): Promise<void> => {},
  refreshAfterWrite: async (): Promise<void> => {},
  transitionTask: async (): Promise<{ ok: boolean; message?: string }> => ({ ok: true }),
};

interface Pane {
  name   : string;
  /** Builds + mounts the renderer into `root`, and returns its unmount. */
  mount  : ( root: HTMLElement ) => () => void;
  /** The pane's own refresh control — the negative leg's subject. */
  refresh: string;
}

const PANES: readonly Pane[] = [
  {
    name    : "fleet-status",
    refresh : ".fleet-status-refresh",
    mount   : (root) => {
      const r = createFleetStatusRenderer({
        eventBus : createEventBusForTesting(),
        stores   : {
          fleet: {
            composite         : () => null,
            showOfflineFlag   : () => false,
            refresh           : async (): Promise<void> => {},
            toggleShowOffline : (): void => {},
          },
        },
        nowDateFn: FIXED_DATE,
      });
      r.mount(root);
      return () => r.unmount();
    },
  },
  {
    name    : "task-list",
    refresh : ".task-list-refresh",
    mount   : (root) => {
      const r = createTaskListRenderer({
        eventBus  : createEventBusForTesting(),
        stores    : { taskList: emptyTaskStore },
        nowDateFn : FIXED_DATE,
      });
      r.mount(root);
      return () => r.unmount();
    },
  },
  {
    name    : "holding-area",
    refresh : ".holding-area-refresh",
    mount   : (root) => {
      const r = createHoldingAreaRenderer({
        eventBus  : createEventBusForTesting(),
        store     : emptyHoldingStore,
        nowDateFn : FIXED_DATE,
      });
      r.mount(root);
      return () => r.unmount();
    },
  },
  {
    name    : "epic-board",
    refresh : ".epic-board-refresh",
    mount   : (root) => {
      const r = createEpicBoardRenderer({
        eventBus  : createEventBusForTesting(),
        store     : { composite: () => null, refresh: async (): Promise<void> => {} },
        nowDateFn : FIXED_DATE,
      });
      r.mount(root);
      return () => r.unmount();
    },
  },
];

// ---------------------------------------------------------------------------
// The denominator. A loop over nothing is green.
// ---------------------------------------------------------------------------

test("the corpus is the whole surface — all four accordions this row built", () => {
  assert.equal(PANES.length, 4);
  assert.deepEqual(
    PANES.map((p) => p.name).sort(),
    ["epic-board", "fleet-status", "holding-area", "task-list"],
  );
});

// ---------------------------------------------------------------------------
// One test per pane, named, so a failing SET says WHICH pane lost its wiring.
// ---------------------------------------------------------------------------

for (const pane of PANES) {
  test(`the ${pane.name} pane INSTALLS its accordion — a header click toggles data-collapsed`, () => {
    const root = document.createElement("div");
    const unmount = pane.mount(root);

    const header  = root.querySelector(".section-header") as HTMLElement;
    const chevron = header.querySelector(".toggle-button") as HTMLElement;
    assert.notEqual(header, null, `${pane.name}: no .section-header was built`);
    assert.notEqual(chevron, null, `${pane.name}: no .toggle-button chevron was built`);

    // Expanded is the mount-time state, and it is the reading a broken wiring
    // ALSO produces — so it is asserted as a precondition, never as evidence.
    assert.equal(chevron.textContent, "▼", `${pane.name}: did not mount expanded`);

    (header.querySelector("h3") as HTMLElement).dispatchEvent(new Event("click", { bubbles: true }));
    assert.equal(
      root.getAttribute("data-collapsed"), "true",
      `${pane.name}: a header click did not collapse the section — its wireSectionCollapse call site is gone`,
    );
    assert.equal(chevron.textContent, "▶", `${pane.name}: chevron did not flip on collapse`);

    chevron.dispatchEvent(new Event("click", { bubbles: true }));
    assert.equal(
      root.getAttribute("data-collapsed"), "false",
      `${pane.name}: a chevron click did not expand the section again`,
    );
    assert.equal(chevron.textContent, "▼", `${pane.name}: chevron did not flip back on expand`);

    unmount();
  });

  test(`the ${pane.name} accordion DISCRIMINATES — its own refresh control does not collapse it`, () => {
    const root = document.createElement("div");
    const unmount = pane.mount(root);

    const header  = root.querySelector(".section-header") as HTMLElement;
    const refresh = header.querySelector(pane.refresh) as HTMLElement;
    assert.notEqual(refresh, null, `${pane.name}: no ${pane.refresh} control in the header`);

    refresh.dispatchEvent(new Event("click", { bubbles: true }));
    assert.notEqual(
      root.getAttribute("data-collapsed"), "true",
      `${pane.name}: clicking a real control collapsed the section — a wiring that collapses on every click is not the wiring this asserts`,
    );

    unmount();
  });
}
