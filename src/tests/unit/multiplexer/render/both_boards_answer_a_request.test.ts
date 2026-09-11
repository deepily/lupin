// Promote/demote requests — driven through the REAL panes (row c9fafb9d, design §6).
// 100% lines/branches/functions per the multiplexer coverage mandate.
//
// 🔴 WHY THIS FILE EXISTS BESIDE request_chips.test.ts. That file proves the chip and the
// controller are right; it cannot prove either pane mounts a badge, routes a chip click to
// the verdict door instead of its own verbs, or fills a chip after a paint. A component can
// be complete and fully covered and never reach the page — so here the holding area and the
// task list are mounted for real, painted through their real templates and the shared row,
// and clicked. Only the stores are fakes.

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createHoldingAreaRenderer,
  type HoldingAreaStoreLike,
} from "../../../../lupin_app/static/js/multiplexer/render/HoldingAreaRenderer";
import {
  createTaskListRenderer,
  type TaskListStoreLike,
} from "../../../../lupin_app/static/js/multiplexer/render/TaskListRenderer";
import { renderDisclosedRow } from "../../../../lupin_app/static/js/multiplexer/render/templates/taskRowDisclosed";
import type { RequestBoardStoreLike } from "../../../../lupin_app/static/js/multiplexer/render/requestChips";
import type { RequestFiledDetail } from "../../../../lupin_app/static/js/multiplexer/stores/TaskRequestStore";
import type { TaskItem, TaskListComposite } from "../../../../lupin_app/static/js/multiplexer/render/taskListModel";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );
beforeEach( () => { localStorage.clear(); } );

const tick = (): Promise<void> => new Promise( ( r ) => setTimeout( r, 0 ) );

const FILED = "2026-09-10T09:00:00Z";

function row( id: string, status: string, move: string | null ): TaskItem {
  return {
    id, title: `row ${ id }`, status, priority: "P2", owner_persona: "chloe", created_by: "mr radio 52f3fe21",
    request_state: move === null ? null : "pending", request_move: move, request_ts: move === null ? null : FILED,
  };
}

interface Requests extends RequestBoardStoreLike {
  verdicts : Array<{ id: string; body: Record<string, unknown> }>;
  countsValue : Record<string, unknown> | null;
}

function requestStore(): Requests {
  const details = new Map<string, RequestFiledDetail>( [
    [ `h1@${ FILED }`, { filer: "mr radio 52f3fe21", reason: "ready to start" } ],
    [ `t1@${ FILED }`, { filer: "cheech 1a2b3c4d",   reason: "blocked a week" } ],
  ] );
  const s: Requests = {
    verdicts: [], countsValue: { holding_area: 1, task_area: 1 },
    counts: () => s.countsValue,
    async submitVerdict( id, body ) { s.verdicts.push( { id, body } ); return { ok: true }; },
    cachedDetail: ( id, ts ) => details.get( `${ id }@${ ts }` ),
    async loadDetail() { /* everything these tests need is cached */ },
  };
  return s;
}

function holdingStore( tasks: TaskItem[] ): HoldingAreaStoreLike & { transitions: string[] } {
  const composite = { status: "", tasks } as TaskListComposite;
  const s = {
    transitions: [] as string[],
    composite: () => composite,
    async refresh() { /* repaint driven by the bus below */ },
    async refreshAfterWrite() { /* as above */ },
    async transitionTask( id: string ) { s.transitions.push( id ); return { ok: true }; },
  };
  return s;
}

function taskListStore( tasks: TaskItem[] ): TaskListStoreLike & { transitions: string[] } {
  const composite: TaskListComposite = { tasks, count: tasks.length };
  const s = {
    transitions: [] as string[],
    composite: () => composite,
    refresh: async () => { /* none */ },
    patchTask: () => ( { restoreState: () => { /* none */ }, done: Promise.resolve() } ),
    transitionTask: ( id: string ) => { s.transitions.push( id ); return { restoreState: () => { /* none */ }, done: Promise.resolve() }; },
  };
  return s;
}

const badgeText = ( root: HTMLElement, testid: string ): [ string, boolean ] => {
  const b = root.querySelector<HTMLElement>( `[data-testid="${ testid }"]` )!;
  return [ b.textContent ?? "", b.hidden ];
};

// ---------------------------------------------------------------------------
// The holding area
// ---------------------------------------------------------------------------

test( "the holding area shows the PROMOTE count beside its count chip, and repaints it on a badge poll", () => {
  const bus = createEventBusForTesting();
  const requests = requestStore();
  const root = document.createElement( "div" );
  createHoldingAreaRenderer( { eventBus: bus, store: holdingStore( [ row( "h1", "not_approved", "admit" ) ] ), requestStore: requests } ).mount( root );

  const count = root.querySelector( '[data-testid="multiplexer-holding-area-count"]' )!;
  assert.equal( ( count.nextElementSibling as HTMLElement ).getAttribute( "data-testid" ), "multiplexer-holding-area-request-badge" );
  assert.deepEqual( badgeText( root, "multiplexer-holding-area-request-badge" ), [ "1 request", false ] );

  requests.countsValue = { holding_area: 0, task_area: 5 };
  bus.emit( { type: "store_request_badges_changed", payload: { known: true }, source: "t", ts: 0 } );
  assert.deepEqual( badgeText( root, "multiplexer-holding-area-request-badge" ), [ "", true ],
                    "the task list's five demotes are not this pane's count" );
} );

test( "a held row's chip shows who asked and why, and its Approve reaches the VERDICT door, not a batch", async () => {
  const bus = createEventBusForTesting();
  const requests = requestStore();
  const store = holdingStore( [ row( "h1", "not_approved", "admit" ), row( "h2", "not_approved", null ) ] );
  const root = document.createElement( "div" );
  createHoldingAreaRenderer( { eventBus: bus, store, requestStore: requests } ).mount( root );

  const chips = root.querySelectorAll<HTMLElement>( ".task-request-chip" );
  assert.equal( chips.length, 1, "only the row with a pending request carries a chip" );
  const chip = chips[ 0 ]!;
  assert.ok( chip.closest( ".task-col-title" ), "the chip is on the VISIBLE row's title cell" );
  assert.equal( chip.querySelector( ".task-request-detail" )!.textContent, "by mr radio 52f3fe21 — ready to start" );

  chip.querySelector<HTMLButtonElement>( ".task-request-approve" )!.click();
  await tick();
  assert.deepEqual( requests.verdicts, [ { id: "h1", body: { verdict: "approved" } } ] );
  assert.deepEqual( store.transitions, [], "a chip click never runs the pane's own verbs" );

  // The pane's own batch buttons still work alongside the chip.
  root.querySelector<HTMLButtonElement>( ".holding-approve-all" )!.click();
  await tick();
  assert.equal( store.transitions.length, 2 );
} );

test( "a holding area filtered to one pinned row still fills that row's chip", async () => {
  const bus = createEventBusForTesting();
  const requests = requestStore();
  const root = document.createElement( "div" );
  const pinned = row( "h1", "not_approved", "admit" );
  createHoldingAreaRenderer( {
    eventBus: bus, store: holdingStore( [] ), requestStore: requests, lookupFetch: async () => pinned,
  } ).mount( root );
  assert.equal( root.querySelectorAll( ".task-request-chip" ).length, 0, "positive control: nothing on the pane before the lookup" );
  const input = root.querySelector<HTMLInputElement>( '[data-testid="multiplexer-holding-area-lookup-input"]' )!;
  input.value = "3fdf4fb4";
  root.querySelector<HTMLButtonElement>( '[data-testid="multiplexer-holding-area-lookup-go"]' )!.click();
  await tick();
  await tick();
  assert.equal( root.querySelector( ".task-request-detail" )?.textContent, "by mr radio 52f3fe21 — ready to start" );
} );

test( "a holding area built WITHOUT a request store mounts no badge, and its batch clicks still work", async () => {
  const bus = createEventBusForTesting();
  const store = holdingStore( [ row( "h2", "not_approved", null ) ] );
  const root = document.createElement( "div" );
  const r = createHoldingAreaRenderer( { eventBus: bus, store } );
  r.mount( root );
  assert.equal( root.querySelectorAll( '[data-testid="multiplexer-holding-area-request-badge"]' ).length, 0 );
  root.querySelector<HTMLButtonElement>( ".holding-approve-all" )!.click();
  await tick();
  assert.deepEqual( store.transitions, [ "h2" ] );
  r.unmount();
} );

test( "unmounting the holding area stops its badge listening", () => {
  const bus = createEventBusForTesting();
  const requests = requestStore();
  const root = document.createElement( "div" );
  const r = createHoldingAreaRenderer( { eventBus: bus, store: holdingStore( [] ), requestStore: requests } );
  r.mount( root );
  const badge = root.querySelector<HTMLElement>( '[data-testid="multiplexer-holding-area-request-badge"]' )!;
  r.unmount();
  requests.countsValue = { holding_area: 9, task_area: 0 };
  bus.emit( { type: "store_request_badges_changed", payload: { known: true }, source: "t", ts: 0 } );
  assert.equal( badge.textContent, "1 request" );
} );

// ---------------------------------------------------------------------------
// The task list
// ---------------------------------------------------------------------------

test( "the task list shows the DEMOTE count, fills the chip, and routes Approve with its triage date", async () => {
  const bus = createEventBusForTesting();
  const requests = requestStore();
  requests.countsValue = { holding_area: 4, task_area: 2 };
  const store = taskListStore( [ row( "t1", "queued", "demote" ) ] );
  const root = document.createElement( "div" );
  createTaskListRenderer( { eventBus: bus, stores: { taskList: store }, requestStore: requests } ).mount( root );
  bus.emit( { type: "store_task_list_changed", payload: { stampUpdated: true }, source: "t", ts: 0 } );

  const count = root.querySelector( '[data-testid="multiplexer-task-list-count"]' )!;
  assert.equal( ( count.nextElementSibling as HTMLElement ).getAttribute( "data-testid" ), "multiplexer-task-list-request-badge" );
  assert.deepEqual( badgeText( root, "multiplexer-task-list-request-badge" ), [ "2 requests", false ] );

  const chip = root.querySelector<HTMLElement>( ".task-request-chip" )!;
  assert.equal( chip.querySelector( ".task-request-detail" )!.textContent, "by cheech 1a2b3c4d — blocked a week" );
  chip.querySelector<HTMLInputElement>( ".task-request-triage" )!.value = "2026-09-17";
  chip.querySelector<HTMLButtonElement>( ".task-request-approve" )!.click();
  await tick();
  assert.deepEqual( requests.verdicts, [ { id: "t1", body: {
    verdict: "approved", next_chase_ts: new Date( "2026-09-17T09:00:00" ).toISOString() } } ] );
  assert.deepEqual( store.transitions, [] );

  // A click that is not a chip button still reaches the pane's own handler.
  root.querySelector<HTMLButtonElement>( ".task-disclose-button" )!.click();
  assert.equal( root.querySelector<HTMLElement>( ".task-controls-row" )!.hidden, false );
} );

test( "the task list fills chips on its unreachable replay and on a pinned row too", async () => {
  const bus = createEventBusForTesting();
  const requests = requestStore();
  let composite: TaskListComposite = { tasks: [ row( "t1", "queued", "demote" ) ], count: 1 };
  const store = { ...taskListStore( [] ), composite: () => composite };
  const pinned = row( "t1", "queued", "demote" );
  const root = document.createElement( "div" );
  createTaskListRenderer( {
    eventBus: bus, stores: { taskList: store }, requestStore: requests, lookupFetch: async () => pinned,
  } ).mount( root );
  const emit = (): void => bus.emit( { type: "store_task_list_changed", payload: { stampUpdated: false }, source: "t", ts: 0 } );
  emit();

  composite = { status: "unreachable", tasks: null };
  emit();
  assert.ok( root.querySelector( ".task-list-unreachable" ) );
  assert.equal( root.querySelector( ".task-request-detail" )?.textContent, "by cheech 1a2b3c4d — blocked a week" );

  composite = { tasks: [], count: 0 };
  emit();
  assert.equal( root.querySelectorAll( ".task-request-chip" ).length, 0, "positive control: the replayed chip is gone before the lookup" );
  const input = root.querySelector<HTMLInputElement>( '[data-testid="multiplexer-task-lookup-input"]' )!;
  input.value = "3fdf4fb4";
  root.querySelector<HTMLButtonElement>( '[data-testid="multiplexer-task-lookup-go"]' )!.click();
  await tick();
  await tick();
  assert.equal( root.querySelector( ".task-request-detail" )?.textContent, "by cheech 1a2b3c4d — blocked a week" );
} );

test( "a task list built WITHOUT a request store mounts no badge", () => {
  const bus = createEventBusForTesting();
  const root = document.createElement( "div" );
  const r = createTaskListRenderer( { eventBus: bus, stores: { taskList: taskListStore( [ row( "t1", "queued", null ) ] ) } } );
  r.mount( root );
  bus.emit( { type: "store_task_list_changed", payload: { stampUpdated: false }, source: "t", ts: 0 } );
  assert.equal( root.querySelectorAll( '[data-testid="multiplexer-task-list-request-badge"]' ).length, 0 );
  r.unmount();
} );

// ---------------------------------------------------------------------------
// The shared row
// ---------------------------------------------------------------------------

test( "the shared row carries the chip on the task list and holding area, never on the epic board", () => {
  const t = row( "e1", "queued", "demote" );
  const chipIn = ( pane: "task-list" | "holding-area" | "epic-board" ): boolean => {
    const table = document.createElement( "tbody" );
    table.appendChild( renderDisclosedRow( t, pane, null, [], Date.parse( "2026-09-10T12:00:00Z" ) ) );
    return table.querySelector( ".task-request-chip" ) !== null;
  };
  assert.deepEqual( [ chipIn( "task-list" ), chipIn( "holding-area" ), chipIn( "epic-board" ) ], [ true, true, false ] );
} );
