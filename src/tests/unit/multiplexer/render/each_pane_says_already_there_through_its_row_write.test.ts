// Row 71a11ed7 — the "already there" note must survive each pane's `rowWrite` wrapper.
//
// Three renderers (Task List, Epic Board, Holding Area) wrap their store's write in a `rowWrite` that
// waits for the read-back and then hands `done` on. A wrapper that forgets to pass the store's outcome
// along turns "Drop: this row is already dropped" into silence in that one pane, and every test that
// stops at the controller or the store stays green. These drive the ASSEMBLED renderer: a store that
// resolves { alreadyAt }, a click on the real Submit, and the stripe the operator would read.
//
// ⚠️ EACH PANE ALSO GETS A CONTROL THAT MUST NOT SAY IT: a row that is gone (404) is a quiet success, and
// a refusal is a refusal. Without these a pane that always printed the note would pass.

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createTaskListRenderer } from "../../../../lupin_app/static/js/multiplexer/render/TaskListRenderer";
import { createEpicBoardRenderer } from "../../../../lupin_app/static/js/multiplexer/render/EpicBoardRenderer";
import { createHoldingAreaRenderer } from "../../../../lupin_app/static/js/multiplexer/render/HoldingAreaRenderer";
import { ApiError } from "../../../../lupin_app/static/js/multiplexer/api/ApiClient";
import type { TaskMutation } from "../../../../lupin_app/static/js/multiplexer/stores/TaskListStore";
import type { TaskItem, TaskListComposite } from "../../../../lupin_app/static/js/multiplexer/render/taskListModel";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );
beforeEach( () => {
  localStorage.clear();
  document.body.replaceChildren();
} );

const ID   = "aaaa1111-2222-3333-4444-555566667777";
const tick = (): Promise<void> => new Promise( ( r ) => setTimeout( r, 0 ) );

type Outcome = "already" | "gone" | "plain";

const DONE: Record<Outcome, () => Promise<{ alreadyAt?: string } | void>> = {
  already : () => Promise.resolve( { alreadyAt: "dropped" } ),
  gone    : () => Promise.reject( new ApiError( 404, "/api/tasks/x/transition", "gone" ) ),
  plain   : () => Promise.resolve(),
};

function mutation( outcome: Outcome ): TaskMutation {
  return { restoreState: () => {}, done: DONE[ outcome ]() };
}

function openRow(): TaskItem {
  return { id: ID, title: "a row", status: "in_progress", priority: "P2", owner_persona: "amy",
           correlation_key: "epic:alpha", blocked_by: [], created_by: "maya", project: "lupin" } as unknown as TaskItem;
}

function taskStore( outcome: Outcome ) {
  const composite = { status: "ok", tasks: [ openRow() ] } as unknown as TaskListComposite;
  return {
    composite         : () => composite,
    refresh           : async () => {},
    refreshAfterWrite : async () => {},
    patchTask         : () => mutation( "plain" ),
    transitionTask    : () => mutation( outcome ),
  };
}

function drive( root: HTMLElement, verb: string, reason: string ): void {
  const select = root.querySelector<HTMLSelectElement>( ".task-verb-select" )!;
  assert.ok( select, "the pane painted no verb select" );
  select.value = verb;
  select.dispatchEvent( new Event( "change", { bubbles: true } ) );
  const input = root.querySelector<HTMLInputElement>( ".task-reason-input" );
  if ( input !== null ) input.value = reason;
  root.querySelector( ".task-submit-button" )!.dispatchEvent( new Event( "click", { bubbles: true } ) );
}

function stripe( root: ParentNode ): { hidden: boolean; text: string } {
  const el = root.querySelector<HTMLElement>( ".task-row-error-stripe" )!;
  assert.ok( el, "the pane painted no refusal stripe" );
  return { hidden: el.hidden, text: el.textContent ?? "" };
}

const NOTE = "Drop: this row is already dropped — this click changed nothing.";

for ( const pane of [ "task list", "epic board" ] as const ) {
  const mount = ( outcome: Outcome ): HTMLElement => {
    const root = document.createElement( "div" );
    document.body.appendChild( root );
    const eventBus = createEventBusForTesting();
    if ( pane === "task list" ) createTaskListRenderer( { eventBus, stores: { taskList: taskStore( outcome ) } as never, nowDateFn: () => new Date( 0 ) } ).mount( root );
    else createEpicBoardRenderer( { eventBus, store: taskStore( outcome ), nowDateFn: () => new Date( 0 ) } ).mount( root );
    return root;
  };

  test( `${ pane }: a store that says the row was already there reaches the stripe as the note`, async () => {
    const root = mount( "already" );
    drive( root, "drop", "why" );
    await tick(); await tick();
    assert.deepEqual( stripe( root ), { hidden: false, text: NOTE } );
  } );

  test( `${ pane }: a row that is gone (404) shows no already-there note`, async () => {
    const root = mount( "gone" );
    drive( root, "drop", "why" );
    await tick(); await tick();
    assert.equal( stripe( root ).text.includes( "already" ), false );
  } );

  test( `${ pane }: a plain success shows nothing`, async () => {
    const root = mount( "plain" );
    drive( root, "drop", "why" );
    await tick(); await tick();
    assert.equal( stripe( root ).hidden, true );
  } );
}

// ── Holding Area: its store answers a result, not a mutation ────────────────

function mountHolding( answer: { ok: boolean; message?: string; alreadyAt?: string } ): HTMLElement {
  const root = document.createElement( "div" );
  document.body.appendChild( root );
  const held = { ...openRow(), status: "not_approved" } as unknown as TaskItem;
  const composite = { status: "ok", tasks: [ held ] } as unknown as TaskListComposite;
  createHoldingAreaRenderer( {
    eventBus : createEventBusForTesting(),
    store    : {
      composite: () => composite, refresh: async () => {}, refreshAfterWrite: async () => {},
      transitionTask: async () => answer, patchTask: async () => ( { ok: true } ),
    } as never,
  } ).mount( root );
  return root;
}

test( "holding area: a store that says the row was already queued reaches the stripe as the note", async () => {
  const root = mountHolding( { ok: true, alreadyAt: "queued" } );
  drive( root, "approve", "" );
  await tick(); await tick();
  assert.deepEqual( stripe( root ), { hidden: false, text: "Approve: this row is already queued — this click changed nothing." } );
} );

test( "holding area: a plain success shows nothing", async () => {
  const root = mountHolding( { ok: true } );
  drive( root, "approve", "" );
  await tick(); await tick();
  assert.equal( stripe( root ).hidden, true );
} );

test( "holding area: a refusal shows the refusal and never the already-there note", async () => {
  const root = mountHolding( { ok: false, message: "not an approver" } );
  drive( root, "approve", "" );
  await tick(); await tick();
  const s = stripe( root );
  assert.equal( s.hidden, false );
  assert.match( s.text, /not an approver/ );
  assert.equal( s.text.includes( "already" ), false );
} );
