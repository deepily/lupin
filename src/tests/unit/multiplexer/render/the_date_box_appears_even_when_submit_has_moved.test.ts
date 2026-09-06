// Row 87812328 — three more branches the coverage gate named at 99.74%, all in
// TaskListRenderer, all REACHABLE, all about a row shape that has drifted.
//
// THE GATE'S RECEIPT, taken BEFORE this file existed, from lcov BRDA records on
// the whole-tier run at de5166b7 (3184 pass / 0 fail, branches 5857/5872):
//     TaskListRenderer.ts  BRDA line=454 block=96  branch=0 taken=0
//     TaskListRenderer.ts  BRDA line=455 block=97  branch=0 taken=0
//     TaskListRenderer.ts  BRDA line=670 block=148 branch=0 taken=0
//
// 🔴 WHY THESE ARE NOT DEFENSIVE BRANCHES. Every one is the FALLBACK half of an
// operator the author reached for on purpose — `btn?.parentNode ?? cell`,
// `btn ?? null`, `getAttribute(...) ?? ""`. Writing `?.` and `??` IS the
// statement that the left side can be absent. A branch that exists only because
// its author expected the absence is a case nobody exercised, not a guard.
//
// AND THE ABSENCE IS THE DOCUMENTED DEFECT ON THIS VERY METHOD. The comment
// above line 454 records why the anchor moved to Submit's own parent: after the
// reshape `.task-col-actions` became the disclosed FIELD WRAPPER and Submit
// dropped one level into a `.task-disclosed-value` span, so inserting against
// the wrapper failed and THE DATE BOX NEVER APPEARED — the verb was chosen, no
// date was asked for, and Submit then refused the row for a missing date the
// operator was never offered. This file pins the next step of that same drift:
// a cell where Submit is not there at all.
//
// ⚠️ WHAT THIS FILE DOES NOT CLAIM: that today's template renders an actions
// cell without a Submit button. It does not. The DOM here is hand-built, which
// is the shape a re-shape PRODUCES rather than one the template emits — the same
// method a_control_outside_both_rows_no_ops_loudly.test.ts uses, and for the
// same reason. Entry is through the real delegated `change` listener on the real
// renderer, so it is the path a drifted template would actually take.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createTaskListRenderer } from "../../../../lupin_app/static/js/multiplexer/render/TaskListRenderer";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

function makeStore() {
  const patches: Array<{ id: string; fields: Record<string, unknown> }> = [];
  return {
    patches,
    composite: () => null,
    refresh  : async (): Promise<void> => {},
    patchTask( id: string, fields: Record<string, unknown> ) {
      patches.push( { id, fields } );
      return { done: Promise.resolve() };
    },
  };
}

function mountRenderer() {
  const bus   = createEventBusForTesting();
  const store = makeStore();
  const r = createTaskListRenderer( {
    eventBus: bus, stores: { taskList: store as never },
    nowDateFn: () => new Date( "2026-09-06T04:00:00Z" ),
  } as never );
  const root = document.createElement( "div" );
  r.mount( root );
  return { root, store, container: root.querySelector( ".task-list-container" ) as HTMLElement };
}

/** A verb select set to `park` — the verb that requires a date. */
function verbSelect( verb = "park" ): HTMLSelectElement {
  const sel = document.createElement( "select" );
  sel.className = "task-verb-select";
  const opt = document.createElement( "option" );
  opt.value = verb; opt.textContent = verb; opt.selected = true;
  sel.appendChild( opt );
  return sel;
}

function submitButton(): HTMLButtonElement {
  const b = document.createElement( "button" );
  b.className = "task-submit-button";
  b.type = "button";
  return b;
}

/**
 * Build a `.task-controls-row` holding an actions cell, optionally with Submit.
 * `withAnchor` controls whether the row carries `data-controls-for`.
 */
function mountActionsCell(
  opts: { withSubmit: boolean; withAnchor: boolean },
): { cell: HTMLElement; sel: HTMLSelectElement; store: ReturnType<typeof makeStore> } {
  const { container, store } = mountRenderer();
  const row = document.createElement( "tr" );
  row.className = "task-controls-row";
  if ( opts.withAnchor ) row.setAttribute( "data-controls-for", "aaaa1111-2222-3333-4444-555566667777" );

  const cell = document.createElement( "td" );
  cell.className = "task-col-actions";
  const sel = verbSelect();
  cell.appendChild( sel );
  if ( opts.withSubmit ) cell.appendChild( submitButton() );

  row.appendChild( cell );
  container.appendChild( row );
  return { cell, sel, store };
}

// ------------------------------------------- TaskListRenderer.ts:454 / :455

test( "POSITIVE CONTROL: with Submit present the date box is inserted BESIDE it", () => {
  // Without this the assertion below is satisfied by a renderer that appends the
  // date box anywhere at all — "a date box exists" cannot distinguish the
  // anchored path from the fallback unless the anchored path is pinned too.
  const { cell, sel } = mountActionsCell( { withSubmit: true, withAnchor: true } );
  sel.dispatchEvent( new globalThis.Event( "change", { bubbles: true } ) );

  const date = cell.querySelector( ".task-chase-input" );
  assert.notEqual( date, null, "no date box appeared for `park`, which requires one" );
  assert.equal( date?.nextElementSibling?.className, "task-submit-button",
    "the date box is not immediately before Submit — the insertion is no longer anchored on the " +
    "button, which is the defect the comment above line 454 records" );
} );

test( "🔴 WITH SUBMIT GONE the date box still appears, appended to the cell", () => {
  // The `?? cell` and `?? null` fallbacks. An operator who picks `park` must be
  // OFFERED a date; if the box never renders, Submit refuses the row for a
  // missing date the operator was never asked for — a dead end with no message.
  const { cell, sel } = mountActionsCell( { withSubmit: false, withAnchor: true } );
  sel.dispatchEvent( new globalThis.Event( "change", { bubbles: true } ) );

  const date = cell.querySelector( ".task-chase-input" ) as HTMLInputElement | null;
  assert.notEqual( date, null,
    "Submit was absent and the date box was NOT rendered — the operator picks `park`, is never " +
    "offered a date, and the row cannot be submitted" );
  assert.equal( date?.type, "date" );
  assert.equal( date?.parentElement, cell,
    "the date box did not fall back to the actions cell as its parent" );
  assert.equal( date?.getAttribute( "aria-label" ), "Chase me again on",
    "the fallback path dropped the label — a bare date box does not say what it is for" );
} );

test( "POSITIVE CONTROL: a verb needing NO date inserts nothing, Submit or not", () => {
  // Proves the assertions above are about the date-requiring branch and not
  // about the renderer inserting a date box unconditionally.
  const { cell, sel } = mountActionsCell( { withSubmit: false, withAnchor: true } );
  ( sel.options[ 0 ] as HTMLOptionElement ).value = "drop";   // reason: yes, date: no
  sel.dispatchEvent( new globalThis.Event( "change", { bubbles: true } ) );

  assert.equal( cell.querySelector( ".task-chase-input" ), null,
    "a date box appeared for `drop`, which requires no date" );
} );

// ------------------------------------------------- TaskListRenderer.ts:670

test( "🔴 A CONTROLS ROW WITH NO data-controls-for RESOLVES TO \"\" AND POSTS NOTHING", () => {
  // `getAttribute( "data-controls-for" ) ?? ""`. `getAttribute` returns null for
  // a missing attribute, and null is not a task id. Coercing it to "" is what
  // lets the caller's `id === ""` refusal fire; without the coalesce the id is
  // null, `null === ""` is false, and the renderer posts a mutation against a
  // row it cannot name.
  const { container, store } = mountRenderer();
  const row = document.createElement( "tr" );
  row.className = "task-controls-row";       // deliberately NO data-controls-for
  const sel = document.createElement( "select" );
  sel.className = "task-priority-select";
  const opt = document.createElement( "option" );
  opt.value = "P1"; opt.selected = true;
  sel.appendChild( opt );
  row.appendChild( sel );
  container.appendChild( row );

  sel.dispatchEvent( new globalThis.Event( "change", { bubbles: true } ) );

  assert.equal( store.patches.length, 0,
    "an anchorless controls row still posted — the id resolved to something truthy, so the " +
    "renderer mutated a task it cannot name" );
} );

test( "POSITIVE CONTROL: the same row WITH the anchor does post", () => {
  // Without this, "nothing was posted" is satisfied by a harness that can never
  // post at all.
  const { container, store } = mountRenderer();
  const row = document.createElement( "tr" );
  row.className = "task-controls-row";
  row.setAttribute( "data-controls-for", "bbbb2222-3333-4444-5555-666677778888" );
  const sel = document.createElement( "select" );
  sel.className = "task-priority-select";
  const opt = document.createElement( "option" );
  opt.value = "P1"; opt.selected = true;
  sel.appendChild( opt );
  row.appendChild( sel );
  container.appendChild( row );

  sel.dispatchEvent( new globalThis.Event( "change", { bubbles: true } ) );

  assert.equal( store.patches.length, 1,
    "a well-anchored controls row did not reach the store — this harness cannot demonstrate " +
    "anything about the anchorless case above" );
  assert.equal( store.patches[ 0 ].id, "bbbb2222-3333-4444-5555-666677778888" );
} );
