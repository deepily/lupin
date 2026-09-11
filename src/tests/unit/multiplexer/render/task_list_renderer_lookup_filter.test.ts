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
import { ApiError } from "../../../../lupin_app/static/js/multiplexer/api/ApiClient";

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

  assert.equal( root.querySelectorAll( "[data-testid='multiplexer-task-lookup-input']" ).length, 0,
    "a box rendered with no fetcher behind it — a control that can only fail" );
  assert.equal( root.querySelectorAll( ".task-title" ).length, 3 );
} );

// ---------------------------------------------------------------------------
// THE NULL-PAYLOAD ARM — the eleventh uncovered branch, and it is REACHABLE
//
// 🔴 WHY THIS TEST EXISTS RATHER THAN A PRAGMA. Row a881b8a3 records the rule:
// a pragma asserts a claim about the PRODUCER, so you read the producers before
// choosing test-or-pragma. `renderPinned()` is private, so its producers are
// exactly two and both are in this file:
//
//   :225  onFound: ( task ) => { this.pinnedTask = task; this.renderPinned(); }
//         UNGUARDED — whatever fetchTask resolves to becomes the pin.
//   :335  if ( this.pinnedTask !== null ) { this.renderPinned(); return; }
//         guarded, cannot deliver null.
//
// ⇒ So `task === null` at :371 is reachable through :225 whenever the endpoint
//   answers 200 with a null body. That is a TEST, not an unreachable branch.

test( "🔴 A NULL PAYLOAD MUST NOT BLANK THE BOARD", async () => {
  // The endpoint answering 200 with no row. The pin is set to null, renderPinned
  // takes its early return, and the operator's list must survive untouched — a
  // blank board would read as "every ticket is gone", which is the worst possible
  // reading of a search that found nothing.
  const { publish, titles, box, count, tick } = setup( null as unknown as TaskItem );
  publish( BOARD );

  box.input.value = "aaaaaaaa";
  box.go.click();
  await tick();

  assert.equal( titles().length, 3, "a null payload emptied the board" );
  assert.equal( count(), "3", "the count moved on a payload that carried no row" );
} );

// ---------------------------------------------------------------------------
// AFTER A VERB ON THE FILTERED ROW — Rick, row 700f0e1d, 2026-09-11:
// "whenever delete from a row filtered by the search box takes place, the search
// card results should be cleared so that the whole task list is displayed again."
//
// Keyed on where the row GOES: a verb that takes it off the task list clears the
// filter; a verb that leaves it on (approve, un-park → queued) re-fetches the pin,
// because the pin is a fetched snapshot and would otherwise show the old status.
// ---------------------------------------------------------------------------

interface Deferred { resolve: () => void; reject: ( e: unknown ) => void; promise: Promise<void> }
function deferred(): Deferred {
  let resolve!: () => void; let reject!: ( e: unknown ) => void;
  const promise = new Promise<void>( ( res, rej ) => { resolve = res; reject = rej; } );
  return { resolve, reject, promise };
}

function setupWithVerbs( lookups: TaskItem[] ) {
  const bus = createEventBusForTesting();
  let composite: TaskListComposite | null = null;
  const transitions: Array<{ id: string; toStatus: string; settle: Deferred }> = [];
  const patches: string[] = [];
  let fetches = 0;
  const store = {
    composite     : () => composite,
    refresh       : () => {},
    patchTask     : ( id: string ) => { patches.push( id ); return { restoreState: () => {}, done: Promise.resolve() }; },
    transitionTask: ( id: string, toStatus: string ) => {
      const settle = deferred();
      transitions.push( { id, toStatus, settle } );
      return { restoreState: () => {}, done: settle.promise };
    },
  } as never;

  const r = createTaskListRenderer( {
    eventBus: bus, stores: { taskList: store }, nowDateFn: FIXED_DATE,
    lookupFetch: () => { const row = lookups[ Math.min( fetches, lookups.length - 1 ) ]!; fetches += 1; return Promise.resolve( row ); },
  } );
  const root = document.createElement( "div" );
  r.mount( root );

  const publish = ( tasks: TaskItem[] ): void => {
    composite = { tasks, count: tasks.length };
    bus.emit<StoreTaskListChangedPayload>( { type: "store_task_list_changed", payload: { stampUpdated: false }, source: "test", ts: 0 } );
  };
  const titles = (): string[] => Array.from( root.querySelectorAll( ".task-title" ) ).map( ( el ) => ( el.textContent ?? "" ).trim() );
  const box = {
    input : root.querySelector<HTMLInputElement>( "[data-testid='multiplexer-task-lookup-input']" )!,
    go    : root.querySelector<HTMLButtonElement>( "[data-testid='multiplexer-task-lookup-go']" )!,
    clear : root.querySelector<HTMLButtonElement>( "[data-testid='multiplexer-task-lookup-clear']" )!,
  };
  const tick = (): Promise<void> => new Promise( ( res ) => setTimeout( res, 0 ) );
  const find = async ( typed: string ): Promise<void> => { box.input.value = typed; box.go.click(); await tick(); };
  const submitVerb = ( verb: string, reason: string | null, rowId?: string ): void => {
    // Controls carry `data-task-id`; compare the attribute rather than interpolating a selector.
    const pick = <T extends HTMLElement>( cls: string ): T =>
      Array.from( root.querySelectorAll<T>( cls ) ).find( ( el ) => rowId === undefined || el.dataset.taskId === rowId )!;
    const sel = pick<HTMLSelectElement>( ".task-verb-select" );
    sel.value = verb;
    sel.dispatchEvent( new Event( "change", { bubbles: true } ) );
    if ( reason !== null ) pick<HTMLInputElement>( ".task-reason-input" ).value = reason;
    pick<HTMLButtonElement>( ".task-submit-button" ).dispatchEvent( new Event( "click", { bubbles: true } ) );
  };
  return { root, publish, titles, box, tick, find, submitVerb, transitions, patches, fetchCount: () => fetches };
}

test( "🔴 A DROP ON THE FILTERED ROW CLEARS THE SEARCH AND SHOWS THE WHOLE LIST", async () => {
  const t = setupWithVerbs( [ BOARD[ 1 ]! ] );
  t.publish( BOARD );
  await t.find( "bbbbbbbb" );
  assert.deepEqual( t.titles(), [ "Second board row" ], "positive control: the filter is up before the drop" );

  t.submitVerb( "drop", "superseded" );
  assert.equal( t.transitions.length, 1 );
  assert.equal( t.titles().length, 1, "the filter must hold until the drop actually lands" );
  t.transitions[ 0 ]!.settle.resolve();
  await t.tick();

  assert.equal( t.titles().length, 3, "the filter survived the drop — Rick's complaint" );
  assert.equal( t.box.input.value, "", "the search box still holds the dropped row's id" );
  assert.equal( t.box.clear.hidden, true, "the clear control is still offered on an unfiltered list" );
} );

test( "a 404 on the drop (row already gone) clears the search too", async () => {
  const t = setupWithVerbs( [ BOARD[ 1 ]! ] );
  t.publish( BOARD );
  await t.find( "bbbbbbbb" );
  t.submitVerb( "drop", "superseded" );
  t.transitions[ 0 ]!.settle.reject( new ApiError( 404, "/api/tasks/bbbbbbbb", "gone" ) );
  await t.tick();
  assert.equal( t.titles().length, 3, "a row that is already gone left the operator filtered to it" );
} );

test( "a REFUSED drop keeps the filter — nothing left the list", async () => {
  const t = setupWithVerbs( [ BOARD[ 1 ]! ] );
  t.publish( BOARD );
  await t.find( "bbbbbbbb" );
  t.submitVerb( "drop", "superseded" );
  t.transitions[ 0 ]!.settle.reject( new ApiError( 403, "/api/tasks/bbbbbbbb", "no" ) );
  await t.tick();
  assert.deepEqual( t.titles(), [ "Second board row" ], "a refusal cleared the operator's filter" );
  assert.equal( t.box.input.value, "bbbbbbbb" );
} );

test( "🔴 APPROVE ON A FILTERED HELD ROW RE-FETCHES THE PIN AND KEEPS THE FILTER", async () => {
  const approved: TaskItem = { ...HELD_ROW, status: "queued" };
  const t = setupWithVerbs( [ HELD_ROW, approved ] );
  t.publish( BOARD );
  await t.find( "3fdf4fb4" );
  assert.equal( t.fetchCount(), 1 );

  t.submitVerb( "approve", null );
  assert.equal( t.transitions[ 0 ]!.toStatus, "queued" );
  t.transitions[ 0 ]!.settle.resolve();
  await t.tick();
  await t.tick();

  assert.equal( t.fetchCount(), 2, "the pin was not re-fetched, so it still shows the old status" );
  assert.deepEqual( t.titles(), [ HELD_ROW.title ], "approve cleared the filter, but the row is still on the list" );
  assert.doesNotMatch( t.root.querySelector( ".task-row" )!.textContent ?? "", /not_approved/,
    "the pinned row still shows the pre-approval status" );
} );

test( "an APPROVE that answers 404 (row gone) CLEARS instead of re-fetching a row that is not there", async () => {
  const t = setupWithVerbs( [ HELD_ROW, HELD_ROW ] );
  t.publish( BOARD );
  await t.find( "3fdf4fb4" );
  t.submitVerb( "approve", null );
  t.transitions[ 0 ]!.settle.reject( new ApiError( 404, "/api/tasks/3fdf4fb4", "gone" ) );
  await t.tick();
  await t.tick();
  assert.equal( t.fetchCount(), 1, "a 404 re-fetched a row the server just said is gone" );
  assert.equal( t.titles().length, 3, "the operator was left filtered to a row that no longer exists" );
} );

test( "a priority edit on the filtered row keeps the filter", async () => {
  const t = setupWithVerbs( [ BOARD[ 1 ]! ] );
  t.publish( BOARD );
  await t.find( "bbbbbbbb" );
  const sel = t.root.querySelector<HTMLSelectElement>( ".task-priority-select" )!;
  sel.value = "P0";
  sel.dispatchEvent( new Event( "change", { bubbles: true } ) );
  await t.tick();
  assert.deepEqual( t.patches, [ "bbbbbbbb-0000-0000-0000-000000000002" ], "positive control: the edit was sent" );
  assert.deepEqual( t.titles(), [ "Second board row" ], "a field edit dropped the filter" );
} );

test( "a verb that lands AFTER the operator filtered to a DIFFERENT row leaves that filter alone", async () => {
  // Drop row A while unfiltered, then search for row B before the drop settles.
  const t = setupWithVerbs( [ BOARD[ 2 ]! ] );
  t.publish( BOARD );
  t.submitVerb( "drop", "superseded", "aaaaaaaa-0000-0000-0000-000000000001" );
  assert.equal( t.transitions[ 0 ]!.id, "aaaaaaaa-0000-0000-0000-000000000001" );
  await t.find( "cccccccc" );
  assert.deepEqual( t.titles(), [ "Third board row" ] );

  t.transitions[ 0 ]!.settle.resolve();
  await t.tick();
  assert.deepEqual( t.titles(), [ "Third board row" ], "another row's drop cleared this filter" );
} );
