// THE LOOKUP FILTERS THE LIST — the behaviour Rick asked for, and the one the
// first build did not deliver.
//
// 🔴 WHY THIS FILE EXISTS. The ticket lookup shipped as a box that CONFIRMED a
// ticket existed and printed a sentence about it. Rick rejected it on sight:
//
//     "Yes I can find a ticket by its first characters of the # but the problem
//      is it doesn't display it it only puts the title up in green text… what do
//      you think search does? Not confirm that it can find it but find it and
//      then display it. It's like a filter. So instead of displaying the title
//      in green text underneath of the search box you would hide all of the
//      other tickets in the task list and only display the 1 that was found."
//
// His ORIGINAL ask said the same thing and the first build still missed it: "I
// need the search capacity to FILTER OUT THE TASK LIST so I can find exactly
// what someone is talking about." The row even quoted that sentence.
//
// ⇒ Every assertion here is about the LIST, not about the box. A test that only
// checks the box got the row would go green on the build he rejected.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/task_list_renderer_lookup_filter.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createTaskListRenderer } from "../../../../lupin_app/static/js/multiplexer/render/TaskListRenderer";
import type { TaskListComposite, TaskItem } from "../../../../lupin_app/static/js/multiplexer/render/taskListModel";
import type { StoreTaskListChangedPayload } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );
beforeEach( () => { localStorage.clear(); } );

const FIXED_DATE = (): Date => new Date( "2026-09-09T16:00:00Z" );

const BOARD: TaskItem[] = [
  { id: "aaaaaaaa-0000-0000-0000-000000000001", title: "First board row",  status: "queued",      owner_persona: "maria",     priority: "P1" },
  { id: "bbbbbbbb-0000-0000-0000-000000000002", title: "Second board row", status: "in_progress", owner_persona: "mr radio",  priority: "P2" },
  { id: "cccccccc-0000-0000-0000-000000000003", title: "Third board row",  status: "queued",      owner_persona: "sam",       priority: "P0" },
];

// 🔴 NOT ON THE BOARD, ON PURPOSE. The row Rick pastes a hash for is usually a
// HELD row, which the board query cannot see — that is why the lookup uses the
// visibility-free single-row endpoint. A filter implemented as "hide rows whose
// id does not match" would show NOTHING for this case, which is worse than no
// search at all: an empty result reads as "does not exist".
const HELD_ROW: TaskItem = {
  id: "3fdf4fb4-2370-4117-9a02-c271fcecc331",
  title: "Main is RED: the prototype-chain sweep fails",
  status: "not_approved", owner_persona: "maria", priority: "P0",
};

function setup( lookupResult: TaskItem ) {
  const bus = createEventBusForTesting();
  let composite: TaskListComposite | null = null;
  const store = {
    composite : () => composite,
    refresh   : () => {},
    patch     : () => ( { restoreState: () => {}, done: Promise.resolve() } ),
    transition: () => ( { restoreState: () => {}, done: Promise.resolve() } ),
  } as never;

  const r = createTaskListRenderer( {
    eventBus: bus, stores: { taskList: store }, nowDateFn: FIXED_DATE,
    lookupFetch: () => Promise.resolve( lookupResult ),
  } );
  const root = document.createElement( "div" );
  r.mount( root );

  const publish = ( tasks: TaskItem[] ): void => {
    composite = { tasks, count: tasks.length };
    bus.emit<StoreTaskListChangedPayload>( {
      type: "store_task_list_changed", payload: { stampUpdated: false }, source: "test", ts: 0,
    } );
  };
  const titles = (): string[] =>
    Array.from( root.querySelectorAll( ".task-title" ) ).map( ( el ) => ( el.textContent ?? "" ).trim() );
  const box = {
    input : root.querySelector<HTMLInputElement>( "[data-testid='multiplexer-task-lookup-input']" )!,
    go    : root.querySelector<HTMLButtonElement>( "[data-testid='multiplexer-task-lookup-go']" )!,
    clear : root.querySelector<HTMLButtonElement>( "[data-testid='multiplexer-task-lookup-clear']" )!,
  };
  const count = (): string => root.querySelector( ".section-header-count" )?.textContent ?? "";
  const tick  = (): Promise<void> => new Promise( ( res ) => setTimeout( res, 0 ) );

  return { root, publish, titles, box, count, tick };
}

test( "positive control: the board really does render several rows first", () => {
  const { publish, titles } = setup( HELD_ROW );
  publish( BOARD );
  assert.equal( titles().length, 3, "without this, 'only one row shows' proves nothing" );
} );

test( "🔴 A FOUND ROW HIDES EVERY OTHER TICKET — the whole complaint", async () => {
  const { publish, titles, box, count, tick } = setup( BOARD[ 1 ]! );
  publish( BOARD );

  box.input.value = "bbbbbbbb";
  box.go.click();
  await tick();

  assert.deepEqual( titles(), [ "Second board row" ],
    "the other tickets are still on screen — this is the build Rick rejected" );
  assert.equal( count(), "1", "a count that disagrees with the visible rows reads as data loss" );
} );

test( "🔴 A HELD ROW THAT IS NOT ON THE BOARD IS STILL SHOWN", async () => {
  // The case the whole feature exists for. An id-filter over the board would
  // render an empty list here and read as "no such ticket".
  const { publish, titles, box, tick } = setup( HELD_ROW );
  publish( BOARD );

  box.input.value = "3fdf4fb4";
  box.go.click();
  await tick();

  assert.deepEqual( titles(), [ HELD_ROW.title ] );
  assert.match( ( document.body.textContent ?? "" ) + ( titles().join( "" ) ), /Main is RED/ );
} );

test( "the held row keeps its STATUS on screen, so it does not read as an ordinary live ticket", async () => {
  const { root, publish, box, tick } = setup( HELD_ROW );
  publish( BOARD );

  box.input.value = "3fdf4fb4";
  box.go.click();
  await tick();

  assert.match( root.textContent ?? "", /not_approved/,
    "which pile the row is in is usually the actual question" );
} );

test( "🔴 A POLL DOES NOT DROP THE FILTER", async () => {
  // The store re-renders on every fetch. Without the pin being honoured in the
  // render path the filtered view would evaporate a second or two after it was
  // applied, and read as a bug in the box rather than as a missing feature.
  const { publish, titles, box, tick } = setup( BOARD[ 1 ]! );
  publish( BOARD );

  box.input.value = "bbbbbbbb";
  box.go.click();
  await tick();
  assert.deepEqual( titles(), [ "Second board row" ] );

  publish( BOARD );                       // a poll lands
  assert.deepEqual( titles(), [ "Second board row" ], "the poll wiped the operator's filter" );
} );

test( "clearing puts the WHOLE list back — and at CURRENT data, not a snapshot", async () => {
  const { publish, titles, box, count, tick } = setup( BOARD[ 1 ]! );
  publish( BOARD );

  box.input.value = "bbbbbbbb";
  box.go.click();
  await tick();
  assert.equal( titles().length, 1 );

  // A row arrives while the filter is up. Clearing must show the NEW board, not
  // the one that was on screen when the filter was applied.
  const grown = [ ...BOARD, {
    id: "dddddddd-0000-0000-0000-000000000004", title: "Arrived while filtered",
    status: "queued", owner_persona: "sam", priority: "P2",
  } ];
  publish( grown );

  box.clear.click();
  assert.equal( titles().length, 4, "clearing replayed a stale snapshot instead of current rows" );
  assert.ok( titles().includes( "Arrived while filtered" ) );
  assert.equal( count(), "4" );
} );

test( "a MISS leaves the board alone", async () => {
  // A typo must not be destructive. The list the operator was reading is not the
  // thing that went wrong.
  const bus = createEventBusForTesting();
  let composite: TaskListComposite | null = { tasks: BOARD, count: BOARD.length };
  const store = { composite: () => composite, refresh: () => {} } as never;
  const r = createTaskListRenderer( {
    eventBus: bus, stores: { taskList: store }, nowDateFn: FIXED_DATE,
    lookupFetch: () => Promise.reject( { status: 404 } ),
  } );
  const root = document.createElement( "div" );
  r.mount( root );
  bus.emit<StoreTaskListChangedPayload>( {
    type: "store_task_list_changed", payload: { stampUpdated: false }, source: "test", ts: 0 } );

  const input = root.querySelector<HTMLInputElement>( "[data-testid='multiplexer-task-lookup-input']" )!;
  input.value = "deadbeef";
  root.querySelector<HTMLButtonElement>( "[data-testid='multiplexer-task-lookup-go']" )!.click();
  await new Promise( ( res ) => setTimeout( res, 0 ) );

  assert.equal( root.querySelectorAll( ".task-title" ).length, 3, "a miss wiped the board" );
} );

test( "no lookup fetcher ⇒ no box at all, and the list is unaffected", () => {
  const bus = createEventBusForTesting();
  const store = { composite: () => ( { tasks: BOARD, count: 3 } ), refresh: () => {} } as never;
  const r = createTaskListRenderer( { eventBus: bus, stores: { taskList: store }, nowDateFn: FIXED_DATE } );
  const root = document.createElement( "div" );
  r.mount( root );
  r.forceRenderForTesting();

  assert.equal( root.querySelector( "[data-testid='multiplexer-task-lookup-input']" ), null );
  assert.equal( root.querySelectorAll( ".task-title" ).length, 3 );
} );
