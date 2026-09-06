// Row 87812328 — `TaskListRenderer.taskIdOf`'s last two lines, and why they get a
// TEST rather than a `c8 ignore`.
//
// 🔴 THE PRAGMA WAS THE RIGHT CALL AND I WAS WRONG TO CALL THESE "REACHABLE".
// Clayton 😎 enumerated the call sites and he is correct: every control the
// template renders lives either in the disclosed `.task-controls-row` — caught
// one branch earlier, at the `data-controls-for` lookup — or on the visible line
// inside `.task-row`. Through TODAY'S markup nothing reaches line 676. I had read
// the lines and called them reachable; reading a line tells you it exists, not
// that anything drives it, and his enumeration beat my reading.
//
// ⇒ SO WHY NOT PRAGMA IT. Because this is the ONE branch in this file with a
// receipt saying that argument fails. `taskIdOf`'s own header records defect D-A
// from `0fd99f96`: a guard annotated "defensive: every editable control is
// rendered inside a .task-row per the template invariant" became THE ONLY BRANCH
// the moment the controls moved out of the row, and every priority and owner edit
// silently posted nothing. Its words: "a defensive branch documented as
// unreachable is exactly the branch a re-shape makes reachable."
//
// Writing `/* c8 ignore */ // unreachable per the template invariant` here would
// reinstate, verbatim, the annotation that already failed once on this method.
//
// ⚠️ AND THE COVERAGE OUTCOME IS THE SAME EITHER WAY — that is the point. A
// pragma buys the gate; so does this. What a pragma does NOT buy is a red on the
// day the shape moves again, which is the only thing that would have caught D-A.
//
// ⚠️ WHAT THIS FILE DOES NOT CLAIM: that today's product reaches these lines. It
// does not, and this file's DOM says so out loud — it hand-builds a control
// outside both rows, which is the shape a re-shape PRODUCES, not one the template
// emits. Entry is through the real delegated `change` handler on the real
// renderer, so it is the path a drifted template would actually take.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createTaskListRenderer } from "../../../../lupin_app/static/js/multiplexer/render/TaskListRenderer";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

/** Records every patch the renderer attempts, so "nothing was posted" is checkable. */
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

/** A priority select — the control that carries NO `data-task-id` of its own. */
function prioritySelect(): HTMLSelectElement {
  const sel = document.createElement( "select" );
  sel.className = "task-priority-select";
  const opt = document.createElement( "option" );
  opt.value = "P1"; opt.textContent = "P1"; opt.selected = true;
  sel.appendChild( opt );
  return sel;
}

test( "POSITIVE CONTROL: the same control INSIDE the controls row does resolve and does post", () => {
  // Without this, every "nothing was posted" assertion below is satisfied by a
  // renderer that posts nothing ever — a harness that cannot act looks exactly
  // like a guard that correctly declined to.
  const { container, store } = mountRenderer();
  const row = document.createElement( "tr" );
  row.className = "task-controls-row";
  row.setAttribute( "data-controls-for", "aaaa1111-2222-3333-4444-555566667777" );
  const sel = prioritySelect();
  row.appendChild( sel );
  container.appendChild( row );

  sel.dispatchEvent( new globalThis.Event( "change", { bubbles: true } ) );

  assert.equal( store.patches.length, 1,
    "the delegated change handler did not reach the store even for a well-placed control — " +
    "this harness cannot demonstrate anything about the guards below" );
  assert.equal( store.patches[ 0 ].id, "aaaa1111-2222-3333-4444-555566667777" );
} );

test( "🔴 A CONTROL IN NEITHER ROW POSTS NOTHING AND SAYS SO — taskIdOf's null-scope return", () => {
  // The shape defect D-A produced: a control the template still renders and the
  // row lookup can no longer resolve. Before the reshape this was annotated
  // unreachable; the reshape made it the only branch.
  const { container, store } = mountRenderer();
  const sel = prioritySelect();
  container.appendChild( sel );          // in NEITHER .task-controls-row nor .task-row

  const errors: unknown[][] = [];
  const realError = console.error;
  console.error = ( ...args: unknown[] ): void => { errors.push( args ); };
  try {
    sel.dispatchEvent( new globalThis.Event( "change", { bubbles: true } ) );
  } finally {
    console.error = realError;
  }

  assert.equal( store.patches.length, 0,
    "a control that resolves no row scope still posted — it would be mutating a task it " +
    "cannot name" );

  // 🔴 THE LOUD HALF IS THE POINT, AND IT IS ASSERTED SEPARATELY. Returning ""
  // quietly is what every one of the four reshape defects did; María's condition
  // on centralising this lookup was that centralising it must not centralise the
  // silence. A no-op alone would satisfy the assertion above.
  assert.equal( errors.length, 1,
    "the control resolved no row scope and NOTHING was logged — the helper has gone quiet, " +
    "which is the exact failure mode the four reshape defects shared" );
  assert.match( String( errors[ 0 ][ 0 ] ), /resolved NO row scope/ );
} );

test( "🔴 A CONTROL BACK ON THE VISIBLE LINE RESOLVES VIA THE ROW — taskIdOf's rowId fallback", () => {
  // The other of the two lines. This is the LEGACY placement: before the
  // reshape every control sat inside `.task-row`, so a control that moves back
  // there — or one that never left — must still resolve. The fallback exists so
  // that a partial re-shape degrades to working rather than to silence.
  const { container, store } = mountRenderer();
  const row = document.createElement( "tr" );
  row.className = "task-row";
  row.setAttribute( "data-task-id", "bbbb2222-3333-4444-5555-666677778888" );
  const sel = prioritySelect();
  row.appendChild( sel );
  container.appendChild( row );

  sel.dispatchEvent( new globalThis.Event( "change", { bubbles: true } ) );

  assert.equal( store.patches.length, 1,
    "a control on the visible line resolved no id — the `.task-row` fallback is gone, and a " +
    "partial re-shape would now no-op silently instead of degrading to working" );
  assert.equal( store.patches[ 0 ].id, "bbbb2222-3333-4444-5555-666677778888" );
  assert.deepEqual( store.patches[ 0 ].fields, { priority: "P1" } );
} );
