// A WRITE THE SERVER KEPT SURVIVES A FAILED READ-BACK — row 93ca4268.
//
// 🔴 READ THIS BEFORE CITING ANY ARM BELOW: THESE ARE LATENT-PATH GUARDS, NOT
// REPRODUCTIONS. As of 2026-09-26 no read in this codebase can reject — Rachel 🕊️ and
// Sam 🎙️ measured the closure independently, and `a_store_refresh_cannot_reject_today.
// test.ts` pins it. So not one arm here reproduces a symptom an operator has seen, and
// none of them would have gone red before the fix ran through a real store. Every one
// drives a STUB that rejects on purpose. Mr. Radio reclassified the row as hardening on
// that evidence (2026-09-26 14:46 EDT); a claim of a live rollback would be false.
//
// WHAT IS BEING GUARDED. All three panes that write a row wrapped the write in
// `rowWrite`, one line in each file:
//
//     const done = mutation.done.then( () => this.store.refreshAfterWrite() );
//
// `.then` ADOPTS the read's promise, so `done` stops reporting the write and starts
// reporting the read. The shared `TaskRowController.commitMutation` treats a rejected
// `done` as a refused write — `restoreState()` plus a refusal stripe — so a read that
// rejected after a write the server had stored would take the operator's edit back off
// the screen, with nothing saying the write had succeeded. These arms hold the decoupled
// chain to that contract: the read's rejection never reaches `done`, and never vanishes.
//
// ⚠️ WHY GUARD A PATH NOTHING CAN TAKE. Because the closure is not local. The stores are
// closed at their own seam; the join in `refreshAfterWrite` is closed only DOWNSTREAM,
// for as long as they stay closed. Narrowing one `fetchState` catch reopens the whole
// chain silently — 138976e2 is that narrowing having happened once already.
//
// ⚠️ THREE PANES, THREE DIFFERENT SYMPTOMS, AND ONLY ONE IS A REVERT. This is the whole
// design of this file, and an arm copied between panes proves nothing:
//   · Task List and Epic Board pass the store's REAL restorer → the edit would REVERT.
//   · Holding Area's restorer is `() => {}` (its store takes no optimistic edit) → nothing
//     reverts, so its exposure is a FALSE REFUSAL STRIPE over a write that landed. An arm
//     asserting "the value survived" passes here against the UNFIXED build, because that
//     value was never going to change.
//   · Holding Area's BATCH trailer and `TaskRequestStore.submitVerdict` `await` their read
//     mid-sequence, so a rejection abandons the statements after it: the batch would never
//     paint its tally, and a verdict chip would sit on "Sending…" over a recorded verdict.
//
// ⚠️ WHY THE SEAM IS THE RENDERER AND NOT THE STORE. The read cannot be made to reject
// through a real store, so an arm that tried would be measuring the store's catch. All
// three wrappers take a store INTERFACE, so a double whose `refreshAfterWrite` rejects is
// trivial, and that is also where the fix belongs. Test and fix meet at one seam.
//
// ⚠️ AND NO ARM HERE CALLS `startPolling()`. Sam's harness trap: if a run ever does
// reject, `void this.refresh()` becomes an unhandled rejection, and Node reports the
// whole FILE as failed while every named subtest still shows `ok`. A file-level red with
// no named subtest red is a fixture defect, not the code under test.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/a_write_the_server_kept_survives_a_failed_read_back.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting, type EventBus } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createTaskListRenderer } from "../../../../lupin_app/static/js/multiplexer/render/TaskListRenderer";
import { createEpicBoardRenderer } from "../../../../lupin_app/static/js/multiplexer/render/EpicBoardRenderer";
import { createHoldingAreaRenderer } from "../../../../lupin_app/static/js/multiplexer/render/HoldingAreaRenderer";
import { READ_BACK_FAILED_CLASS, READ_BACK_FAILED_STAMP }
  from "../../../../lupin_app/static/js/multiplexer/shared/afterWriteRead";
import type { TaskItem, TaskListComposite }
  from "../../../../lupin_app/static/js/multiplexer/render/taskListModel";
import type { TaskMutation }
  from "../../../../lupin_app/static/js/multiplexer/stores/TaskListStore";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );
beforeEach( () => {
  localStorage.clear();
  document.body.replaceChildren();
} );

const ROW_ID     = "aaaa1111-2222-3333-4444-555566667777";
const FIXED_DATE = (): Date => new Date( "2026-09-26T16:00:00Z" );

/** The rejection every read-failure arm uses: a REAL Error, per the row's item 3. */
const READ_BLEW_UP = (): Error => new Error( "the read after the write blew up" );

function task( over: Partial<TaskItem> = {} ): TaskItem {
  return { id: ROW_ID, title: "a row", status: "queued", owner_persona: "amy", priority: "P2",
           created_by: "maya", project: "lupin", ...over } as TaskItem;
}

// ---------------------------------------------------------------------------
// The store double. `refreshAfterWrite` is the ONE thing under test here, so it
// is the one thing the double gets to decide.
// ---------------------------------------------------------------------------

interface StoreDouble {
  composite() : TaskListComposite | null;
  refresh()   : Promise<void>;
  refreshAfterWrite() : Promise<void>;
  patchTask( id: string, fields: Record<string, unknown> ): TaskMutation;
  transitionTask( id: string, toStatus: string, extras: Record<string, unknown> ): TaskMutation;
}

interface Recorded {
  /** Every optimistic edit the double was asked to make, in order. */
  patches       : Array<Record<string, unknown>>;
  /** How many times the after-write read was asked for. */
  reads         : number;
  /** How many times the controller asked to ROLL BACK. This is the defect, counted. */
  restores      : number;
}

/**
 * A task-list-shaped store whose WRITE always succeeds and whose after-write READ
 * rejects when `failRead` is on.
 *
 * ⚠️ `restoreState` IS A REAL COUNTER, not a no-op. A double that ignored it could
 * not tell a build that rolled back from one that did not — which is the entire
 * question for two of the three panes.
 */
function taskListDouble( bus: EventBus, rows: TaskItem[], failRead: () => boolean ): { store: StoreDouble; calls: Recorded } {
  const calls: Recorded = { patches: [], reads: 0, restores: 0 };
  const composite = { status: "ok", tasks: rows } as unknown as TaskListComposite;
  const mutation = ( fields: Record<string, unknown> ): TaskMutation => {
    calls.patches.push( fields );
    return { restoreState: () => { calls.restores += 1; }, done: Promise.resolve() };
  };
  return {
    calls,
    store : {
      composite : () => composite,
      refresh   : async () => {},
      refreshAfterWrite : async () => {
        calls.reads += 1;
        if ( failRead() ) throw READ_BLEW_UP();
        // ⚠️ A SUCCESSFUL READ EMITS, because the real stores do — `refresh()` sets the
        // composite then calls `emitChanged()`, and the panes repaint and re-stamp off
        // that event. A double that read without emitting would leave every pane frozen
        // on its first paint, and the "a good read clears the warning" arm below would
        // be measuring the double's silence rather than the pane's behaviour.
        bus.emit( { type: "store_task_list_changed", payload: { stampUpdated: true },
                    source: "taskListDouble", ts: 0 } );
      },
      patchTask      : ( _id, fields ) => mutation( fields ),
      transitionTask : ( _id, toStatus, extras ) => mutation( { toStatus, ...extras } ),
    },
  };
}

function q<T extends Element>( root: ParentNode, sel: string ): T {
  const el = root.querySelector<T>( sel );
  assert.ok( el, `not rendered: ${ sel }` );
  return el;
}

/** Several microtask turns — the write, the read and the controller's settle are all async. */
const settle = async (): Promise<void> => {
  for ( let i = 0; i < 8; i += 1 ) await new Promise( ( r ) => setTimeout( r, 0 ) );
};

/** The refusal stripe's text for this row, or "" when no refusal is being shown. */
function stripeText( root: ParentNode ): string {
  const stripe = root.querySelector<HTMLElement>( ".task-row-error-stripe" );
  if ( stripe === null || stripe.hidden ) return "";
  return ( stripe.textContent ?? "" ).trim();
}

/** The pane's updated-stamp element, found by the data-testid the pane publishes. */
function stamp( root: ParentNode, testid: string ): HTMLElement {
  return q<HTMLElement>( root, `[data-testid="${ testid }"]` );
}

/** Stage a new priority and press Update — the operator's real path through the shared row. */
function editPriority( root: ParentNode, value: string, id: string = ROW_ID ): void {
  const select = q<HTMLSelectElement>( root, `select.task-priority-select[data-task-id="${ id }"]` );
  select.value = value;
  select.dispatchEvent( new Event( "change", { bubbles: true } ) );
  const update = q<HTMLButtonElement>( root, `button.task-priority-update[data-task-id="${ id }"]` );
  assert.equal( update.disabled, false, "Update stayed disabled — the staged edit never registered" );
  update.dispatchEvent( new Event( "click", { bubbles: true } ) );
}

// ===========================================================================
// SITES 1 AND 3 — the two panes with a REAL restorer. The edit must SURVIVE.
// ===========================================================================

type RealRestorerPane = {
  name   : string;
  testid : string;
  mount  : ( bus: EventBus, store: StoreDouble ) => { root: HTMLElement; unmount: () => void };
};

const REAL_RESTORER_PANES: readonly RealRestorerPane[] = [
  {
    name   : "Task List (TaskListRenderer.rowWrite)",
    testid : "multiplexer-task-list-updated",
    mount  : ( bus, store ) => {
      const root = document.createElement( "div" );
      document.body.appendChild( root );
      const r = createTaskListRenderer( {
        eventBus : bus, nowDateFn : FIXED_DATE,
        stores   : { taskList : store },
      } as never );
      r.mount( root );
      return { root, unmount: () => r.unmount() };
    },
  },
  {
    name   : "Epic Board (EpicBoardRenderer.rowWrite)",
    testid : "multiplexer-epic-board-updated",
    mount  : ( bus, store ) => {
      const root = document.createElement( "div" );
      document.body.appendChild( root );
      const r = createEpicBoardRenderer( {
        eventBus : bus, nowDateFn : FIXED_DATE, store,
      } as never );
      r.mount( root );
      r.forceRenderForTesting();
      return { root, unmount: () => r.unmount() };
    },
  },
];

for ( const pane of REAL_RESTORER_PANES ) {

  test( `positive control — ${ pane.name }: the write reaches the store and the read is taken`, async () => {
    const bus = createEventBusForTesting();
    const { store, calls } = taskListDouble( bus, [ task() ], () => false );
    const m = pane.mount( bus, store );
    editPriority( m.root, "P0" );
    await settle();

    assert.equal( calls.patches.length, 1,
      "Update sent no write — the driver is broken, and nothing below would mean anything" );
    assert.equal( calls.reads, 1, "no after-write read was taken — this pane is not the one under test" );
    assert.equal( calls.restores, 0, "a successful write and read rolled something back" );
    m.unmount();
  } );

  test( `🔴 ${ pane.name }: a read that rejects after an ACCEPTED write never rolls it back`, async () => {
    const bus = createEventBusForTesting();
    const { store, calls } = taskListDouble( bus, [ task() ], () => true );
    const m = pane.mount( bus, store );

    editPriority( m.root, "P0" );
    await settle();

    assert.equal( calls.patches.length, 1, "the write was not sent — the driver is broken, not the code" );
    assert.equal( calls.reads, 1, "the after-write read was never attempted" );
    // 🔴 THE ASSERTION THE ROW EXISTS FOR. `restoreState` is the controller's rollback;
    // calling it is the client deciding a stored write did not happen.
    assert.equal( calls.restores, 0,
      "a read rejected after a write the server ACCEPTED and the client rolled the write "
      + "back: the operator's edit would come off the screen while the server holds the new value" );
    assert.equal( stripeText( m.root ), "",
      `a write the server stored was painted as refused: "${ stripeText( m.root ) }"` );
    m.unmount();
  } );

  test( `${ pane.name }: the failed read is SURFACED on the updated-stamp, not swallowed`, async () => {
    const bus = createEventBusForTesting();
    const { store } = taskListDouble( bus, [ task() ], () => true );
    const m = pane.mount( bus, store );
    const before = stamp( m.root, pane.testid ).textContent ?? "";
    assert.equal( stamp( m.root, pane.testid ).classList.contains( READ_BACK_FAILED_CLASS ), false,
      "the pane was already marked stale before the read failed — nothing below would mean anything" );

    editPriority( m.root, "P0" );
    await settle();

    const el = stamp( m.root, pane.testid );
    assert.equal( el.textContent, READ_BACK_FAILED_STAMP,
      `the failed read left the stamp reading "${ el.textContent }" (was "${ before }") — a caught-and-`
      + "dropped read trades a visibly wrong value for an invisibly stale one, which is worse" );
    assert.ok( el.classList.contains( READ_BACK_FAILED_CLASS ), "the stamp carries no stale marking to style" );
    m.unmount();
  } );

  test( `${ pane.name }: a later SUCCESSFUL read clears the stale marking`, async () => {
    // The staleness is a fact with an end. A marking that outlived its fact would
    // train the operator to ignore it, which costs the next real one.
    let fail = true;
    const bus = createEventBusForTesting();
    const { store } = taskListDouble( bus, [ task() ], () => fail );
    const m = pane.mount( bus, store );

    editPriority( m.root, "P0" );
    await settle();
    assert.ok( stamp( m.root, pane.testid ).classList.contains( READ_BACK_FAILED_CLASS ),
      "the first arm did not mark the pane stale — the second arm proves nothing" );

    fail = false;
    editPriority( m.root, "P1" );
    await settle();

    const el = stamp( m.root, pane.testid );
    assert.equal( el.classList.contains( READ_BACK_FAILED_CLASS ), false,
      "the board was re-read successfully and the stale warning is still up" );
    assert.notEqual( el.textContent, READ_BACK_FAILED_STAMP, "the stamp still reads stale after a good read" );
    m.unmount();
  } );

  test( `🔴 ${ pane.name }: a read rejecting for a poll THIS writer never started still spares the edit`, async () => {
    // PATH (b), and Mr. Radio flagged it as the important one. `refreshAfterWrite()`
    // AWAITS `inFlightRun` — a poll that started BEFORE this write — precisely so the
    // read it then takes can see the write. Joining that poll also inherits its
    // rejection, so the failure reaching `done` is not this writer's read at all, and
    // no per-shape patch at the read can reach it. The double reproduces the SHAPE:
    // one rejected promise, created before the write, handed to every joiner.
    //
    // ⚠️ AND IT IS CLOSED TODAY, WHICH IS WHY THIS ARM IS LABELLED LATENT. Rachel and
    // Sam both measured it: `inFlightRun` rejects only if `run` rejects, `run`'s two
    // exits are `fetchState()` (total catch) and `emitChanged()` (the bus converts a
    // throwing listener to `listener_error`), so nothing upstream can produce a
    // rejection to inherit. ⚠️ Rachel's precision, worth keeping: (b) is closed
    // DOWNSTREAM, not at its own seam — `refreshAfterWrite` still faithfully propagates
    // whatever `inFlightRun` does. That is a weaker closure than (a)'s, and the kind
    // that reopens silently the day a store is made to reject on purpose.
    const priorPollFailure = Promise.reject( READ_BLEW_UP() );
    priorPollFailure.catch( () => {} );   // the poll's own rejection is handled; this is the JOIN

    const calls = { patches: 0, restores: 0, joins: 0 };
    const composite = { status: "ok", tasks: [ task() ] } as unknown as TaskListComposite;
    const store: StoreDouble = {
      composite : () => composite,
      refresh   : async () => {},
      // The writer never started this read; it is waiting out someone else's.
      refreshAfterWrite : async () => { calls.joins += 1; await priorPollFailure; },
      patchTask : ( _id, fields ) => {
        calls.patches += 1;
        void fields;
        return { restoreState: () => { calls.restores += 1; }, done: Promise.resolve() };
      },
      transitionTask : () => ( { restoreState: () => { calls.restores += 1; }, done: Promise.resolve() } ),
    };

    const m = pane.mount( createEventBusForTesting(), store );
    editPriority( m.root, "P0" );
    await settle();

    assert.equal( calls.patches, 1, "the write was not sent — the driver is broken, not the code" );
    assert.equal( calls.joins, 1, "the writer took no after-write read at all" );
    assert.equal( calls.restores, 0,
      "a poll that failed BEFORE this write, and which this writer only joined, rolled this "
      + "writer's stored edit back. Someone else's failed read must not undo my write." );
    assert.equal( stripeText( m.root ), "", "a stored write was painted as refused" );
    assert.ok( stamp( m.root, pane.testid ).classList.contains( READ_BACK_FAILED_CLASS ),
      "the joined failure was swallowed — the operator is shown a stale board with no warning" );
    m.unmount();
  } );
}

// ===========================================================================
// SITE 2 — the Holding Area's `rowWrite`. Its restorer is `() => {}`, so the
// damage was never a revert. Watch the STRIPE.
// ===========================================================================

const HELD = "bbbb1111-2222-3333-4444-555566667777";

function heldRow(): TaskItem {
  return task( { id: HELD, status: "not_approved", created_by: "krishna", owner_persona: "amy" } );
}

interface HoldingHarness {
  root      : HTMLElement;
  writes    : () => number;
  reads     : () => number;
  statusOf  : ( filer: string ) => string;
  clickApproveAll : ( filer: string ) => void;
  unmount   : () => void;
}

/**
 * Mount the real Holding Area over a store whose writes SUCCEED and whose
 * after-write read rejects when `failRead` says so.
 *
 * ⚠️ `transitionTask` RESOLVES `{ ok: true }` — it never rejects, which is the real
 * store's contract (a batch is a loop, and a throwing body abandons every row after
 * the first refusal). So every rejection this harness can produce comes from the
 * READ, which is what the file is about.
 */
function mountHolding( rows: TaskItem[], failRead: () => boolean ): HoldingHarness {
  let writes = 0;
  let reads  = 0;
  const composite = { status: "", tasks: rows } as unknown as TaskListComposite;
  const bus  = createEventBusForTesting();
  const root = document.createElement( "div" );
  document.body.appendChild( root );

  const renderer = createHoldingAreaRenderer( {
    eventBus : bus, nowDateFn : FIXED_DATE,
    store    : {
      composite : () => composite,
      refresh   : async () => {},
      refreshAfterWrite : async () => {
        reads += 1;
        if ( failRead() ) throw READ_BLEW_UP();
        bus.emit( { type: "store_holding_area_changed", payload: { stampUpdated: true },
                    source: "holdingDouble", ts: 0 } );
      },
      transitionTask : async () => { writes += 1; return { ok: true }; },
      patchTask      : async () => { writes += 1; return { ok: true }; },
    },
  } as never );
  renderer.mount( root );

  const groupOf = ( filer: string ): HTMLElement => {
    const g = Array.from( root.querySelectorAll<HTMLElement>( ".holding-area-group" ) )
      .find( ( el ) => el.dataset.filer === filer );
    assert.ok( g, `no rendered group for filer ${ JSON.stringify( filer ) }` );
    return g;
  };

  return {
    root,
    writes : () => writes,
    reads  : () => reads,
    statusOf : ( filer ) => q<HTMLElement>( groupOf( filer ), ".holding-area-group-status" ).textContent ?? "",
    // Two clicks: the first ARMS the button, the second CONFIRMS (row 376dd4cb).
    clickApproveAll : ( filer ) => {
      const button = q<HTMLButtonElement>( groupOf( filer ), ".holding-approve-all" );
      button.dispatchEvent( new globalThis.MouseEvent( "click", { bubbles: true } ) );
      button.dispatchEvent( new globalThis.MouseEvent( "click", { bubbles: true } ) );
    },
    unmount : () => renderer.unmount(),
  };
}

test( "positive control — Holding Area: the row write lands and its read is taken", async () => {
  const h = mountHolding( [ heldRow() ], () => false );
  editPriority( h.root, "P0", HELD );
  await settle();
  assert.equal( h.writes(), 1, "Update sent no write — the driver is broken" );
  assert.equal( h.reads(), 1, "no after-write read was taken" );
  assert.equal( stripeText( h.root ), "", "a successful write and read painted a refusal" );
  h.unmount();
} );

test( "🔴 Holding Area: a failed read paints NO refusal stripe over a write the server kept", async () => {
  // ⚠️ THE ASSERTION THAT WOULD PASS VACUOUSLY HERE is "the edited value survived":
  // this store takes no optimistic edit, so `restoreState` is `() => {}` and the value
  // was never going to change whatever the build does. The stripe is the discriminator.
  const h = mountHolding( [ heldRow() ], () => true );

  editPriority( h.root, "P0", HELD );
  await settle();

  assert.equal( h.writes(), 1, "the write was not sent — the driver is broken, not the code" );
  assert.equal( h.reads(), 1, "the after-write read was never attempted" );
  assert.equal( stripeText( h.root ), "",
    "a read rejected after a write the server ACCEPTED and the pane painted the read's error "
    + `into the row's refusal stripe: "${ stripeText( h.root ) }". A false refusal over a stored `
    + "write is this pane's whole exposure — it has no revert to show." );
  h.unmount();
} );

test( "Holding Area: the failed read is SURFACED on the updated-stamp", async () => {
  const h = mountHolding( [ heldRow() ], () => true );
  editPriority( h.root, "P0", HELD );
  await settle();

  const el = stamp( h.root, "multiplexer-holding-area-updated" );
  assert.equal( el.textContent, READ_BACK_FAILED_STAMP,
    "the failed read was swallowed — the pane silently shows a board it could not re-read" );
  assert.ok( el.classList.contains( READ_BACK_FAILED_CLASS ), "the stamp carries no stale marking" );
  h.unmount();
} );

// ===========================================================================
// SITE 4 — the batch loop's TRAILING read. A bare `await` here abandoned the
// statement after it, which is the line that reports the batch.
// ===========================================================================

test( "positive control — the batch reports its tally when the trailing read succeeds", async () => {
  const h = mountHolding( [ heldRow() ], () => false );
  h.clickApproveAll( "Krishna" );
  await settle();
  assert.equal( h.writes(), 1, "Approve all transitioned nothing — the driver is broken" );
  assert.equal( h.statusOf( "Krishna" ), "1 of 1 approved.",
    "the batch does not report its tally even on the happy path — nothing below would mean anything" );
  h.unmount();
} );

test( "🔴 the batch still reports its tally when the trailing read fails", async () => {
  // Every transition had already been attempted and counted by the time the trailer
  // runs. A rejection there threw that tally away: the group froze on the in-flight
  // line — "Approved 1 of 1…" — over a batch that had FINISHED and landed, and since
  // `runBatch` is driven through `void`, the rejection went nowhere anyone could see.
  const h = mountHolding( [ heldRow() ], () => true );

  h.clickApproveAll( "Krishna" );
  await settle();

  assert.equal( h.writes(), 1, "Approve all transitioned nothing — the driver is broken, not the code" );
  assert.equal( h.reads(), 1, "the batch took no trailing read at all" );
  assert.equal( h.statusOf( "Krishna" ), "1 of 1 approved.",
    `the batch's tally was abandoned by the rejecting read; the group still reads `
    + `"${ h.statusOf( "Krishna" ) }" over transitions the server accepted` );
  assert.ok( stamp( h.root, "multiplexer-holding-area-updated" ).classList.contains( READ_BACK_FAILED_CLASS ),
    "the batch's failed read was swallowed — the tally is shown over a board nobody could re-read" );
  h.unmount();
} );

// ===========================================================================
// SITE 5 — `showCreatedTicket`'s FIRE-AND-FORGET read. It cannot roll anything
// back, which is exactly why it went unnoticed: it surfaced nothing at all.
// ===========================================================================

const NEW_ROW = { id: "cccc1111-2222-3333-4444-555566667777", title: "Rick's own ticket", status: "queued" };

/** Mount the Task List with a working New-ticket transport, over a read that can fail. */
function mountNewTicket( failRead: () => boolean ): { root: HTMLElement; reads: () => number; unmount: () => void } {
  let reads = 0;
  const bus  = createEventBusForTesting();
  const root = document.createElement( "div" );
  document.body.appendChild( root );
  const r = createTaskListRenderer( {
    eventBus : bus, nowDateFn : FIXED_DATE,
    stores   : { taskList : {
      composite : () => ( { status: "ok", tasks: [] } as unknown as TaskListComposite ),
      refresh   : async () => {},
      refreshAfterWrite : async () => {
        reads += 1;
        if ( failRead() ) throw READ_BLEW_UP();
      },
      patchTask      : () => ( { restoreState: () => {}, done: Promise.resolve() } ),
      transitionTask : () => ( { restoreState: () => {}, done: Promise.resolve() } ),
    } },
    postTicket : () => Promise.resolve( { status: 201, body: NEW_ROW } ),
  } as never );
  r.mount( root );
  return { root, reads: () => reads, unmount: () => r.unmount() };
}

/** File a ticket through the real New card — the operator's path. */
function fileTicket(): void {
  q<HTMLButtonElement>( document, "[data-testid='multiplexer-task-list-new-ticket']" )
    .dispatchEvent( new Event( "click", { bubbles: true } ) );
  q<HTMLInputElement>( document, "[data-testid='multiplexer-new-ticket-title']" ).value = "T";
  q<HTMLButtonElement>( document, "[data-testid='multiplexer-new-ticket-create']" )
    .dispatchEvent( new Event( "click", { bubbles: true } ) );
}

test( "positive control — filing a ticket takes the after-write read", async () => {
  const h = mountNewTicket( () => false );
  fileTicket();
  await settle();
  assert.equal( h.reads(), 1, "the New card took no read — the driver is broken" );
  assert.equal( stamp( h.root, "multiplexer-task-list-updated" ).classList.contains( READ_BACK_FAILED_CLASS ), false,
    "a successful read marked the pane stale" );
  h.unmount();
} );

test( "🔴 a ticket filed against a board that cannot be re-read says so", async () => {
  // This one cannot roll anything back — `void` discards the promise — so its exposure
  // is pure SILENCE: the ticket is created, the board cannot be re-read, the new row is
  // not on screen, and the only trace is an unhandled rejection in the console. "Nothing
  // appeared" is indistinguishable from "the ticket was not created".
  const h = mountNewTicket( () => true );

  fileTicket();
  await settle();

  assert.equal( h.reads(), 1, "the New card took no read — the driver is broken, not the code" );
  const el = stamp( h.root, "multiplexer-task-list-updated" );
  assert.equal( el.textContent, READ_BACK_FAILED_STAMP,
    "the ticket was filed and the board could not be re-read, and the pane said nothing" );
  assert.ok( el.classList.contains( READ_BACK_FAILED_CLASS ), "the stamp carries no stale marking" );
  h.unmount();
} );

// ===========================================================================
// THE PANE CAN BE GONE BY THE TIME THE READ FAILS.
// ===========================================================================

test( "a read that fails AFTER the pane unmounts is a no-op, not a throw", async () => {
  // ⚠️ THIS IS NOT A DEFENSIVE-BRANCH FORMALITY — it is the one ordering nothing else
  // here covers. `readBackAfterWrite` runs after an `await`, so the operator can close
  // the pane, or a repaint can null the stamp, between the write settling and the read
  // rejecting. `onStale` then paints into nothing. Throwing there would surface as an
  // unhandled rejection with no named test red — Sam's harness-trap signature.
  let release!: () => void;
  const held = new Promise<void>( ( r ) => { release = r; } );

  const bus  = createEventBusForTesting();
  const root = document.createElement( "div" );
  document.body.appendChild( root );
  const r = createTaskListRenderer( {
    eventBus : bus, nowDateFn : FIXED_DATE,
    stores   : { taskList : {
      composite : () => ( { status: "ok", tasks: [ task() ] } as unknown as TaskListComposite ),
      refresh   : async () => {},
      refreshAfterWrite : async () => { await held; throw READ_BLEW_UP(); },
      patchTask      : () => ( { restoreState: () => {}, done: Promise.resolve() } ),
      transitionTask : () => ( { restoreState: () => {}, done: Promise.resolve() } ),
    } },
  } as never );
  r.mount( root );

  editPriority( root, "P0" );
  await settle();
  r.unmount();          // the stamp is gone; the read is still in flight
  release();

  await assert.doesNotReject( async () => { await settle(); },
    "the read rejected after unmount and the pane threw while trying to say so" );
} );
