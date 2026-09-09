// THE HOLDING AREA GETS THE SEARCH TOO — and refuses rows that are not its own.
//
// 🔴 WHY THIS FILE EXISTS. Rick, 2026-09-09, after accepting the task list's
// filter: *"Now that you've proven how it works I want that extended and added
// to the holding area on both the multiplexer and the notifications client."*
//
// ⚠️ AND WHY IT IS NOT JUST THE SAME TESTS AGAIN. The lookup endpoint is
// visibility-free on purpose, so it returns queued, done and parked rows exactly
// as readily as held ones. The task list can show anything it is handed. This
// pane cannot: every row under a heading that reads "Holding Area" is claimed to
// be waiting on triage, so pinning a queued row here would be a false statement
// made by the LAYOUT — one no wording in the result line could take back.
//
// ⇒ The assertions that matter most here are the REFUSALS, not the hits.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/holding_area_lookup_filter.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createHoldingAreaRenderer,
  type HoldingAreaStoreLike,
} from "../../../../lupin_app/static/js/multiplexer/render/HoldingAreaRenderer";
import type { TaskListComposite, TaskItem } from "../../../../lupin_app/static/js/multiplexer/render/taskListModel";
import type { StoreHoldingAreaChangedPayload } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

const FIXED_DATE = (): Date => new Date( "2026-09-09T16:00:00Z" );

const HELD: TaskItem[] = [
  { id: "aaaaaaaa-0000-0000-0000-000000000001", title: "First held row",  status: "not_approved", owner_persona: "maria",    created_by: "maria 536c8ff7",    priority: "P1" },
  { id: "bbbbbbbb-0000-0000-0000-000000000002", title: "Second held row", status: "not_approved", owner_persona: "mr radio", created_by: "mr radio 81381447", priority: "P2" },
  { id: "cccccccc-0000-0000-0000-000000000003", title: "Third held row",  status: "not_approved", owner_persona: "sam",      created_by: "sam 684c7fdd",      priority: "P0" },
] as TaskItem[];

/** Held, and NOT in the pane's current payload — the case the feature is for. */
const HELD_OFF_PANE: TaskItem = {
  id: "3fdf4fb4-2370-4117-9a02-c271fcecc331",
  title: "A held row the current poll did not return",
  status: "not_approved", owner_persona: "maria", created_by: "maria 536c8ff7", priority: "P0",
} as TaskItem;

/** Found by the endpoint, and emphatically NOT held. */
const QUEUED_ROW: TaskItem = {
  id: "dddddddd-0000-0000-0000-000000000004",
  title: "A live queued ticket", status: "queued",
  owner_persona: "maria", created_by: "maria 536c8ff7", priority: "P1",
} as TaskItem;

function setup( lookup: TaskItem | ( () => Promise<TaskItem> ) ) {
  const bus = createEventBusForTesting();
  let composite: TaskListComposite | null = null;
  const transitioned: string[] = [];

  const store = {
    composite         : () => composite,
    refresh           : () => Promise.resolve(),
    refreshAfterWrite : () => Promise.resolve(),
    transitionTask    : ( id: string ) => { transitioned.push( id ); return Promise.resolve( { ok: true } ); },
  } as HoldingAreaStoreLike;

  const fetchTask = typeof lookup === "function"
    ? lookup
    : () => Promise.resolve( lookup );

  const r = createHoldingAreaRenderer( {
    eventBus: bus, store, nowDateFn: FIXED_DATE, lookupFetch: fetchTask,
  } );
  const root = document.createElement( "div" );
  r.mount( root );

  const publish = ( tasks: TaskItem[] | null, status?: string ): void => {
    composite = tasks === null
      ? ( { status, tasks: null } as unknown as TaskListComposite )
      : ( { status, tasks, count: tasks.length } as TaskListComposite );
    bus.emit<StoreHoldingAreaChangedPayload>( {
      type: "store_holding_area_changed", payload: { stampUpdated: false }, source: "test", ts: 0,
    } );
  };

  const titles = (): string[] =>
    Array.from( root.querySelectorAll( ".task-title" ) ).map( ( el ) => ( el.textContent ?? "" ).trim() );
  const box = {
    input : root.querySelector<HTMLInputElement>( "[data-testid='multiplexer-holding-area-lookup-input']" )!,
    go    : root.querySelector<HTMLButtonElement>( "[data-testid='multiplexer-holding-area-lookup-go']" )!,
    clear : root.querySelector<HTMLButtonElement>( "[data-testid='multiplexer-holding-area-lookup-clear']" )!,
    result: root.querySelector<HTMLElement>( "[data-testid='multiplexer-holding-area-lookup-result']" )!,
  };
  const count = (): string => root.querySelector( "[data-testid='multiplexer-holding-area-count']" )?.textContent ?? "";
  const tick  = (): Promise<void> => new Promise( ( res ) => setTimeout( res, 0 ) );

  return { root, renderer: r, publish, titles, box, count, tick, transitioned };
}

// ---------------------------------------------------------------------------
// Positive controls — without these, every "only one row" assertion is vacuous
// ---------------------------------------------------------------------------

test( "positive control: the pane really does render several held rows first", () => {
  const { publish, titles } = setup( HELD[ 0 ]! );
  publish( HELD );
  assert.equal( titles().length, 3, "without this, 'only one row shows' proves nothing" );
} );

test( "positive control: the box exists and carries ITS OWN test ids", () => {
  const { root, box } = setup( HELD[ 0 ]! );
  assert.ok( box.input, "no search input on the holding area" );
  // The task list's ids must NOT appear here, or a page-level query would cross
  // the two panes and a green assertion could be reading the wrong control.
  assert.equal( root.querySelectorAll( "[data-testid='multiplexer-task-lookup-input']" ).length, 0,
    "the holding area is emitting the TASK LIST's ids — two boxes, one id space" );
} );

// ---------------------------------------------------------------------------
// The behaviour Rick asked for
// ---------------------------------------------------------------------------

test( "🔴 A FOUND HELD ROW HIDES EVERY OTHER HELD TICKET", async () => {
  const { publish, titles, box, count, tick } = setup( HELD[ 1 ]! );
  publish( HELD );

  box.input.value = "bbbbbbbb";
  box.go.click();
  await tick();

  assert.deepEqual( titles(), [ "Second held row" ],
    "the other held tickets are still on screen — this is not a filter" );
  assert.equal( count(), "1", "a count that disagrees with the visible rows reads as data loss" );
  assert.equal( box.result.getAttribute( "data-state" ), "filtered" );
  assert.equal( box.clear.hidden, false, "the clear control must appear once a filter is live" );
} );

test( "🔴 A HELD ROW THE CURRENT POLL DID NOT RETURN IS STILL SHOWN", async () => {
  // The pinned row is the FETCHED row, not an id-filter over the pane's payload.
  // Filtering the payload would render an empty pane here, and empty reads as
  // "does not exist" — worse than no search.
  const { publish, titles, box, tick } = setup( HELD_OFF_PANE );
  publish( HELD );

  box.input.value = "3fdf4fb4";
  box.go.click();
  await tick();

  assert.deepEqual( titles(), [ "A held row the current poll did not return" ] );
} );

// ---------------------------------------------------------------------------
// The refusals — the half that distinguishes this pane from the task list
// ---------------------------------------------------------------------------

test( "🔴 A QUEUED ROW IS FOUND AND REFUSED — the pane is a claim, not a container", async () => {
  const { publish, titles, box, count, tick } = setup( QUEUED_ROW );
  publish( HELD );

  box.input.value = "dddddddd";
  box.go.click();
  await tick();

  assert.equal( box.result.getAttribute( "data-state" ), "out-of-scope",
    "reported as filtered — the pane would be claiming a queued row is awaiting triage" );
  assert.match( box.result.textContent ?? "", /not in the holding area/ );
  assert.match( box.result.textContent ?? "", /queued/,
    "the real status must be named, or the operator cannot tell where the row went" );
  assert.equal( titles().length, 3, "a refusal must leave the pane exactly as it was" );
  assert.equal( count(), "3", "the count moved on a refusal" );
  assert.equal( box.clear.hidden, true,
    "a clear control offered when nothing was hidden implies the row IS in this pane" );
} );

test( "a row with no status at all is refused, not silently pinned", async () => {
  const { publish, box, titles, tick } = setup( { id: "eeeeeeee", title: "Shapeless" } as TaskItem );
  publish( HELD );

  box.input.value = "eeeeeeee";
  box.go.click();
  await tick();

  assert.equal( box.result.getAttribute( "data-state" ), "out-of-scope" );
  assert.match( box.result.textContent ?? "", /unknown status/ );
  assert.equal( titles().length, 3 );
} );

test( "a FAILED lookup leaves the pane alone", async () => {
  const { publish, titles, box, tick } = setup(
    () => Promise.reject( Object.assign( new Error( "nope" ), { status: 404 } ) ) );
  publish( HELD );

  box.input.value = "99999999";
  box.go.click();
  await tick();

  assert.equal( box.result.getAttribute( "data-state" ), "missing" );
  assert.equal( titles().length, 3, "a failed search must not be destructive" );
} );

// ---------------------------------------------------------------------------
// Survival and teardown
// ---------------------------------------------------------------------------

test( "🔴 THE FILTER SURVIVES A POLL", async () => {
  const { publish, titles, box, tick } = setup( HELD[ 2 ]! );
  publish( HELD );

  box.input.value = "cccccccc";
  box.go.click();
  await tick();
  assert.deepEqual( titles(), [ "Third held row" ] );

  publish( HELD ); // the 60-second poll lands
  assert.deepEqual( titles(), [ "Third held row" ],
    "the poll dropped the filter — it would evaporate under the operator and read as a bug in the box" );
} );

test( "clearing restores CURRENT rows, not the snapshot from when the filter was applied", async () => {
  const { publish, titles, box, count, tick } = setup( HELD[ 0 ]! );
  publish( HELD );

  box.input.value = "aaaaaaaa";
  box.go.click();
  await tick();
  assert.deepEqual( titles(), [ "First held row" ] );

  // A row drains away while the filter is live.
  publish( [ HELD[ 1 ]!, HELD[ 2 ]! ] );
  box.clear.click();

  assert.deepEqual( titles(), [ "Third held row", "Second held row" ].sort(), titles().sort().join( " | " ) );
  assert.equal( count(), "2", "restored a stale snapshot instead of the current payload" );
} );

test( "🔴 AN UNREACHABLE STORE IS NEWS AND OUTRANKS A LIVE FILTER", async () => {
  const { publish, box, root, tick } = setup( HELD[ 0 ]! );
  publish( HELD );

  box.input.value = "aaaaaaaa";
  box.go.click();
  await tick();

  publish( null, "unreachable" );
  assert.match( root.textContent ?? "", /unreachable/i,
    "the pinned row was re-asserted over a sentinel — the operator would never learn the pane stopped answering" );
} );

test( "🔴 APPROVE-ALL WHILE FILTERED ACTS ON THE PINNED ROW ONLY", async () => {
  // Mr. Radio 🦉, review F3: "Approve-all over a filtered view is exactly what
  // Rick presses by reflex." The batch reads its ids off the RENDERED DOM, so a
  // live filter narrows it to one — which is the honest reading of the control,
  // but only if it is true. If the batch ever read from the store instead, this
  // press would silently approve every held row that filer has.
  const { publish, box, root, tick, transitioned } = setup( HELD[ 0 ]! );
  publish( HELD );

  box.input.value = "aaaaaaaa";
  box.go.click();
  await tick();

  const approve = root.querySelector<HTMLButtonElement>( ".holding-approve-all" );
  assert.ok( approve, "no batch control rendered on the pinned group — the row is not rendering as a normal held row" );

  const reason = root.querySelector<HTMLInputElement>( "input.holding-batch-reason, textarea.holding-batch-reason" );
  if ( reason ) reason.value = "approved during review";
  approve!.click();
  await tick();
  await tick();

  assert.deepEqual( transitioned, [ HELD[ 0 ]!.id ],
    `the batch reached ${ transitioned.length } rows while ONE was on screen — it is not reading the rendered DOM` );
} );

test( "no lookupFetch ⇒ no box, rather than a box that can only fail", () => {
  const bus = createEventBusForTesting();
  const store = {
    composite         : () => null,
    refresh           : () => Promise.resolve(),
    refreshAfterWrite : () => Promise.resolve(),
    transitionTask    : () => Promise.resolve( { ok: true } ),
  } as HoldingAreaStoreLike;
  const r = createHoldingAreaRenderer( { eventBus: bus, store, nowDateFn: FIXED_DATE } );
  const root = document.createElement( "div" );
  r.mount( root );

  assert.equal( root.querySelectorAll( "[data-testid='multiplexer-holding-area-lookup-input']" ).length, 0,
    "a box rendered with no fetcher behind it — a control that can only fail" );
} );

test( "unmount drops the pin, so a remount does not inherit a stale filter", async () => {
  const { renderer, publish, box, tick, root } = setup( HELD[ 0 ]! );
  publish( HELD );
  box.input.value = "aaaaaaaa";
  box.go.click();
  await tick();

  renderer.unmount();
  renderer.mount( root );
  publish( HELD );

  const titles = Array.from( root.querySelectorAll( ".task-title" ) ).map( ( el ) => ( el.textContent ?? "" ).trim() );
  assert.equal( titles.length, 3, "the remounted pane came back still filtered" );
} );
