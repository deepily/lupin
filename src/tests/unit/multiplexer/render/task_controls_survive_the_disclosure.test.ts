// Guard — the row reshape moved every control OUT of `.task-row` into the
// SIBLING `.task-controls-row`, and three handlers were still resolving their
// scope with `closest( ".task-row" )`.
//
// 🔴 ALL THREE FAILED BY EARLY RETURN. No throw, no console error, no red test:
// `closest` returned null, the guard beneath it returned, and the control simply
// did nothing. Nine controls present, none functional, nothing to investigate.
// That is the class that ships — and the reason Rick's ruling to re-shape the
// row BEFORE building the two new panes was the right order: wiring the disclosed
// row on top of the old seam would have produced exactly that task list.
//
// ⚠️ EVERY TEST HERE DRIVES THE ASSEMBLED RENDERER, NOT A TEMPLATE. A
// template-level check cannot see any of these: the markup was always correct.
// What broke was the handler's route to it. So each test asserts BOTH halves —
// the control is present, AND activating it reaches the store — because a test
// that only asserts presence passes with the handler returning early, which is
// the exact shape being guarded against.
//
// The three sites, measured at 2026-09-05:
//   D-A  taskIdOf            → id resolved "", every priority/owner edit posted nothing
//   D-B  handleSubmitClick   → verb select resolved null, ALL FIVE verbs dead
//   D-C  renderRowError      → grew a second stripe beside the template's own

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
import type { FleetComposite } from "../../../../lupin_app/static/js/multiplexer/render/fleetModel";
import type { StoreTaskListChangedPayload } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before(() => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );
beforeEach( () => { localStorage.clear(); } );

// ---------------------------------------------------------------------------
// Harness — the smallest thing that mounts the real renderer over a real store.
// ---------------------------------------------------------------------------

interface Recorded {
  patches     : Array<{ id: string; fields: TaskPatchFields }>;
  transitions : Array<{ id: string; toStatus: string; extras: Record<string, string> }>;
}

function mountOne( status = "in_progress" ): { root: HTMLElement; rec: Recorded } {
  const rec: Recorded = { patches : [], transitions : [] };
  const composite: TaskListComposite = {
    status : "ok",
    tasks  : [ { id : "t1", title : "one", status, owner_persona : "amy", priority : "P2", project : "lupin" } ],
  } as unknown as TaskListComposite;

  const store: TaskListStoreLike = {
    composite       : () => composite,
    refresh         : async () => {},
    patchTask       : ( id, fields ) => {
      rec.patches.push( { id, fields } );
      return { restoreState : () => {}, done : Promise.resolve() } as unknown as TaskMutation;
    },
    transitionTask  : ( id, toStatus, extras ) => {
      rec.transitions.push( { id, toStatus, extras } );
      return { restoreState : () => {}, done : Promise.resolve() } as unknown as TaskMutation;
    },
  };
  const fleet: TaskListFleetLike = {
    composite : () => ( {
      fleet_arbiter : { sessions : [ { persona : "amy" }, { persona : "bob" } ] },
    } as unknown as FleetComposite ),
  };

  const bus  = createEventBusForTesting();
  const root = document.createElement( "div" );
  document.body.appendChild( root );
  createTaskListRenderer( { eventBus : bus, stores : { taskList : store, fleet } } ).mount( root );
  bus.emit<StoreTaskListChangedPayload>( { type : "store_task_list_changed", payload : { stampUpdated : true }, source : "test", ts : 0 } );
  return { root, rec };
}

function q<T extends HTMLElement>( root: HTMLElement, sel: string ): T {
  const el = root.querySelector<T>( sel );
  assert.ok( el, `the control is not even rendered: ${ sel } — this guard is about the ROUTE to a control, so a missing control means the test is measuring the wrong thing` );
  return el;
}

function change( el: HTMLSelectElement | HTMLInputElement, value: string ): void {
  el.value = value;
  el.dispatchEvent( new Event( "change", { bubbles : true } ) );
}

// ---------------------------------------------------------------------------
// D-A — the id must resolve from a control that is NOT inside `.task-row`
// ---------------------------------------------------------------------------

test( "D-A: the priority select is OUTSIDE .task-row, and changing it still posts", () => {
  const { root, rec } = mountOne();
  const sel = q<HTMLSelectElement>( root, ".task-priority-select" );

  // The premise, asserted rather than assumed — if this ever becomes false the
  // test below stops being a guard and starts being a coincidence.
  assert.equal( sel.closest( ".task-row" ), null,
    "the premise of this guard is gone: the control is back inside .task-row" );
  assert.ok( sel.closest( ".task-controls-row" ), "the control must live in the disclosed controls row" );

  change( sel, "P0" );
  assert.deepEqual( rec.patches, [ { id : "t1", fields : { priority : "P0" } } ],
    "the id resolved empty and the edit posted nothing — closest( '.task-row' ) walked past the control" );
} );

test( "D-A: the owner select posts too — it carries NO data-task-id of its own", () => {
  const { root, rec } = mountOne();
  const sel = q<HTMLSelectElement>( root, ".task-owner-select" );
  // ⚠️ MEASURED, AND IT IS WHY THE FIX CANNOT REST ON THE CONTROL'S OWN STAMP.
  // The verb select, the reason box and Submit carry `data-task-id`; these two
  // selects never have. So the id must come from the ROW, which owns it.
  assert.equal( sel.dataset.taskId, undefined,
    "if this select now carries its own id, the row-keyed resolution is no longer what this test proves" );
  change( sel, "bob" );
  assert.deepEqual( rec.patches, [ { id : "t1", fields : { owner_persona : "bob" } } ] );
} );

// ---------------------------------------------------------------------------
// D-B — Submit reads the verb, the reason and the date from the controls row
// ---------------------------------------------------------------------------

test( "D-B: Submit reaches the verb select across the row boundary, and posts", () => {
  const { root, rec } = mountOne();
  const verb = q<HTMLSelectElement>( root, ".task-verb-select" );
  const btn  = q<HTMLButtonElement>( root, ".task-submit-button" );
  assert.equal( btn.closest( ".task-row" ), null, "the premise is gone: Submit is back inside .task-row" );

  change( verb, "drop" );
  change( q<HTMLInputElement>( root, ".task-reason-input" ), "superseded" );
  btn.dispatchEvent( new Event( "click", { bubbles : true } ) );

  assert.deepEqual( rec.transitions, [ { id : "t1", toStatus : "dropped", extras : { reason : "superseded" } } ],
    "Submit found no verb select and returned early — all five verbs were dead" );
} );

test( "D-B: a dated verb GETS its date box, beside Submit rather than inside the field", () => {
  // The same boundary one level down: `insertBefore` needs a DIRECT child, and
  // Submit now sits inside the field's value span rather than in the field. A
  // date box that never appears means Submit then refuses the row for a date the
  // operator was never offered — a refusal for a control that is not there.
  const { root, rec } = mountOne();
  change( q<HTMLSelectElement>( root, ".task-verb-select" ), "park" );
  const date = q<HTMLInputElement>( root, ".task-chase-input" );
  assert.equal( date.type, "date" );
  assert.equal( date.parentNode, q<HTMLButtonElement>( root, ".task-submit-button" ).parentNode,
    "the date box must land in Submit's own parent, whatever the nesting depth" );

  change( q<HTMLInputElement>( root, ".task-reason-input" ), "later" );
  change( date, "2026-09-10" );
  q<HTMLButtonElement>( root, ".task-submit-button" ).dispatchEvent( new Event( "click", { bubbles : true } ) );
  assert.equal( rec.transitions.length, 1, "a park with both fields filled must post" );
  assert.equal( rec.transitions[ 0 ]!.toStatus, "parked" );
} );

// ---------------------------------------------------------------------------
// D-C — ONE stripe per row, the template's, filled rather than grown
// ---------------------------------------------------------------------------

test( "D-C: exactly ONE stripe per row, and it is the template's <tr> — not a grown <td>", () => {
  const { root } = mountOne();
  const stripes = Array.from( root.querySelectorAll<HTMLElement>( ".task-row-error-stripe" ) );
  assert.equal( stripes.length, 1, `two mechanisms wearing one class name; ${ stripes.length } stripes found` );
  assert.equal( stripes[ 0 ]!.tagName, "TR", "the renderer grew its own <td> stripe beside the template's row" );
  assert.equal( stripes[ 0 ]!.getAttribute( "data-error-for" ), "t1" );
  assert.equal( stripes[ 0 ]!.hidden, true, "a clean row's stripe must be HIDDEN, not absent" );
} );

test( "D-C: a refusal REVEALS the one stripe; a later success hides it again", () => {
  const { root, rec } = mountOne();
  const stripe = q<HTMLElement>( root, ".task-row-error-stripe" );

  change( q<HTMLSelectElement>( root, ".task-verb-select" ), "drop" );
  change( q<HTMLInputElement>( root, ".task-reason-input" ), "   " );   // blank after trim
  q<HTMLButtonElement>( root, ".task-submit-button" ).dispatchEvent( new Event( "click", { bubbles : true } ) );

  assert.equal( rec.transitions.length, 0, "a blank reason must not post" );
  assert.equal( stripe.hidden, false, "the refusal was never shown to the operator" );
  assert.match( stripe.textContent ?? "", /reason is required/i );
  assert.equal( root.querySelectorAll( ".task-row-error-stripe" ).length, 1, "the stripe must not stack" );

  change( q<HTMLInputElement>( root, ".task-reason-input" ), "superseded" );
  q<HTMLButtonElement>( root, ".task-submit-button" ).dispatchEvent( new Event( "click", { bubbles : true } ) );
  assert.equal( rec.transitions.length, 1 );
  assert.equal( stripe.hidden, true, "a success must CLEAR the previous refusal, not leave an empty stripe showing" );
  assert.equal( stripe.textContent, "" );
} );

// ---------------------------------------------------------------------------
// The disclosure itself — the toggle the three defects arrived with
// ---------------------------------------------------------------------------

test( "the ⋯ toggle flips its own row's controls, and only its own", () => {
  const { root } = mountOne();
  const btn    = q<HTMLButtonElement>( root, ".task-disclose-button" );
  const hidden = q<HTMLElement>( root, ".task-controls-row" );

  assert.equal( hidden.hidden, true, "the controls row is hidden at rest — Rick's ruling" );
  assert.equal( btn.getAttribute( "aria-expanded" ), "false" );

  btn.dispatchEvent( new Event( "click", { bubbles : true } ) );
  assert.equal( hidden.hidden, false );
  assert.equal( btn.getAttribute( "aria-expanded" ), "true", "the accessible half must move WITH the visual one" );

  btn.dispatchEvent( new Event( "click", { bubbles : true } ) );
  assert.equal( hidden.hidden, true );
  assert.equal( btn.getAttribute( "aria-expanded" ), "false" );
} );

// ---------------------------------------------------------------------------
// The helper's own obligation — centralising the lookup must not centralise the
// silence (María's condition on approving `controlScope`, 2026-09-05).
// ---------------------------------------------------------------------------

test( "a control in NEITHER row SHOUTS — one helper must not become one quiet no-op", () => {
  const { root } = mountOne();

  // Take a real control out of both rows, exactly as a future re-shape would,
  // and press it. The handler will no-op — that part is unavoidable — but it
  // must not do so in silence, because silence is what cost four defects.
  // ⚠️ It must stay INSIDE the container — that is where the delegated listener
  // lives. Moving it to `root` puts it outside the listener's subtree, the
  // handler never runs at all, and the test then passes or fails for a reason
  // that has nothing to do with the alarm.
  const container = q<HTMLElement>( root, ".task-list-container" );
  const btn = q<HTMLButtonElement>( root, ".task-submit-button" );
  container.appendChild( btn );
  assert.equal( btn.closest( ".task-controls-row" ), null );
  assert.equal( btn.closest( ".task-row" ), null, "the control must be outside BOTH rows for this test to mean anything" );

  const said: string[] = [];
  const real = console.error;
  console.error = ( ...args: unknown[] ) => { said.push( args.map( String ).join( " " ) ); };
  try {
    btn.dispatchEvent( new Event( "click", { bubbles : true } ) );
  } finally {
    console.error = real;
  }

  assert.equal( said.length, 1, `the orphaned control must be reported exactly once; ${ said.length } messages` );
  assert.match( said[ 0 ]!, /no row scope/i );
  assert.match( said[ 0 ]!, /task-submit-button/, "the message must name the control, or it cannot be chased" );
} );

test( "a control that IS in a row says nothing — the alarm must discriminate", () => {
  // Positive control for the test above. An alarm that fires on every click is
  // an alarm nobody reads, and it would pass the previous test just as well.
  const { root } = mountOne();
  const said: string[] = [];
  const real = console.error;
  console.error = ( ...args: unknown[] ) => { said.push( args.map( String ).join( " " ) ); };
  try {
    change( q<HTMLSelectElement>( root, ".task-priority-select" ), "P0" );
    change( q<HTMLSelectElement>( root, ".task-verb-select" ), "drop" );
    change( q<HTMLInputElement>( root, ".task-reason-input" ), "why" );
    q<HTMLButtonElement>( root, ".task-submit-button" ).dispatchEvent( new Event( "click", { bubbles : true } ) );
  } finally {
    console.error = real;
  }
  assert.deepEqual( said, [], "the ordinary path must be silent" );
} );
