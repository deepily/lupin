// Parity row A-1b — the press-hold repaint guard, on all three panes.
// 100% lines/branches/functions per the multiplexer coverage mandate.
//
// 🔴 EVERY PANE TEST PUTS A REAL POLL TICK BETWEEN THE PRESS AND THE CLICK. The
// stores are the REAL TaskListStore / HoldingAreaStore, driven through their
// injected `setIntervalFn`, over a fake API. Legacy's own post-mortem is why:
// "every test called the handler by name so no poll could run between them."
// A test that emits the bus event by hand, or calls the render by name, is
// testing the function, not the property.
//
// The property (spec §7 surface 8): a click whose press and release straddle a
// poll still reaches its handler, and the held repaint lands exactly once, with
// the LATEST composite, after the release.

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { wirePressHoldGuard } from "../../../../lupin_app/static/js/multiplexer/render/pressHoldGuard";
import { createTaskListRenderer } from "../../../../lupin_app/static/js/multiplexer/render/TaskListRenderer";
import { createHoldingAreaRenderer } from "../../../../lupin_app/static/js/multiplexer/render/HoldingAreaRenderer";
import { createEpicBoardRenderer } from "../../../../lupin_app/static/js/multiplexer/render/EpicBoardRenderer";
import { createTaskListStore, type TaskListApiClient } from "../../../../lupin_app/static/js/multiplexer/stores/TaskListStore";
import { createHoldingAreaStore, type HoldingAreaApiClient } from "../../../../lupin_app/static/js/multiplexer/stores/HoldingAreaStore";
import { loadEpicGroupState, epicGroupIsExpanded } from "../../../../lupin_app/static/js/multiplexer/render/epicBoardCollapse";
import type { TaskItem, TaskListComposite } from "../../../../lupin_app/static/js/multiplexer/render/taskListModel";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

beforeEach( () => { localStorage.clear(); } );

const settle = (): Promise<void> => new Promise( ( r ) => setTimeout( r, 0 ) );

// ---------------------------------------------------------------------------
// Harness: fake timers, a fake API serving a mutable composite, a repaint counter
// ---------------------------------------------------------------------------

interface Timers {
  setIntervalFn   : ( cb: () => void, ms: number ) => number;
  clearIntervalFn : ( h: number ) => void;
  setTimeoutFn    : ( cb: () => void, ms: number ) => unknown;
  /** Fire every interval — one poll tick for every store on the page. */
  poll(): Promise<void>;
  /** Run every pending timeout (the deferred mouseup release among them). */
  flushTimeouts(): void;
}

function makeTimers(): Timers {
  const intervals: Array<() => void> = [];
  let timeouts: Array<() => void> = [];
  return {
    setIntervalFn   : ( cb ) => intervals.push( cb ),
    clearIntervalFn : () => undefined,
    setTimeoutFn    : ( cb ) => { timeouts.push( cb ); return timeouts.length; },
    async poll() { for ( const cb of intervals ) cb(); await settle(); },
    flushTimeouts() { const due = timeouts; timeouts = []; for ( const cb of due ) cb(); },
  };
}

/** Count `replaceChildren` on a container — one call is one repaint. */
function countRepaints( container: HTMLElement ): { readonly n: number } {
  const counter = { n: 0 };
  const original = container.replaceChildren.bind( container );
  container.replaceChildren = ( ...nodes: Array<Node | string> ): void => { counter.n += 1; original( ...nodes ); };
  return counter;
}

function press( el: Element, type: string ): void {
  el.dispatchEvent( new MouseEvent( type, { bubbles: true } ) );
}

function openRow( id: string, title: string, owner = "amy" ): TaskItem {
  return { id, title, status: "in_progress", priority: "P2", owner_persona: owner, correlation_key: "epic:alpha", blocked_by: [] } as unknown as TaskItem;
}

function heldRow( id: string, title: string ): TaskItem {
  return { id, title, status: "not_approved", priority: "P2", created_by: "krishna 0e61abe3" } as unknown as TaskItem;
}

// ---------------------------------------------------------------------------
// Task List + Epic Board — one real TaskListStore feeds both, as boot wires it
// ---------------------------------------------------------------------------

function mountTaskPanes( tasks: TaskItem[] ) {
  const timers = makeTimers();
  const bus    = createEventBusForTesting();
  let composite: TaskListComposite = { tasks, count: tasks.length };
  const api: TaskListApiClient = {
    get   : async <T,>(): Promise<T> => composite as T,
    patch : async <T,>(): Promise<T> => null as T,
    post  : async <T,>(): Promise<T> => null as T,
  };
  const store = createTaskListStore( {
    bus, api, nowFn: () => 0, setIntervalFn: timers.setIntervalFn, clearIntervalFn: timers.clearIntervalFn,
  } );

  const taskRoot = document.createElement( "div" );
  const epicRoot = document.createElement( "div" );
  document.body.append( taskRoot, epicRoot );
  const taskList = createTaskListRenderer( {
    eventBus: bus, stores: { taskList: store }, nowDateFn: () => new Date( 0 ), setTimeoutFn: timers.setTimeoutFn,
  } );
  const epic = createEpicBoardRenderer( {
    eventBus: bus, store, nowDateFn: () => new Date( 0 ), setTimeoutFn: timers.setTimeoutFn,
  } );
  taskList.mount( taskRoot );
  epic.mount( epicRoot );

  return {
    timers, store, taskList, epic,
    taskContainer : taskRoot.querySelector( ".task-list-container" ) as HTMLElement,
    epicContainer : epicRoot.querySelector( ".epic-board-container" ) as HTMLElement,
    setTasks( next: TaskItem[] ) { composite = { tasks: next, count: next.length }; },
    unmount() { taskList.unmount(); epic.unmount(); taskRoot.remove(); epicRoot.remove(); },
  };
}

test( "Task List: a poll landing mid-press does not replace the pressed node, and the click still reaches its handler", async () => {
  const h = mountTaskPanes( [ openRow( "t1", "first" ) ] );
  h.store.startPolling();
  await h.timers.poll();
  const repaints = countRepaints( h.taskContainer );

  const disclose = h.taskContainer.querySelector( ".task-disclose-button" ) as HTMLElement;
  assert.ok( disclose, "positive control: the row's ⋯ button is painted" );

  press( disclose, "mousedown" );
  h.setTasks( [ openRow( "t1", "second" ) ] );
  await h.timers.poll();

  assert.equal( repaints.n, 0, "the poll repainted during the press" );
  assert.ok( disclose.isConnected, "the pressed node was replaced mid-press" );

  press( disclose, "mouseup" );
  disclose.click();
  const controls = h.taskContainer.querySelector( ".task-controls-row" ) as HTMLElement;
  assert.equal( controls.hidden, false, "the click did not reach the disclosure handler" );

  h.timers.flushTimeouts();
  assert.equal( repaints.n, 1, "the held repaint must land exactly once" );
  assert.match( h.taskContainer.textContent ?? "", /second/, "the replayed repaint is not the latest composite" );
  h.unmount();
} );

test( "Task List: two polls held behind one press replay ONE repaint, carrying the latest composite", async () => {
  const h = mountTaskPanes( [ openRow( "t1", "first" ) ] );
  h.store.startPolling();
  await h.timers.poll();
  const repaints = countRepaints( h.taskContainer );

  press( h.taskContainer.querySelector( ".task-disclose-button" )!, "mousedown" );
  h.setTasks( [ openRow( "t1", "second" ) ] );
  await h.timers.poll();
  h.setTasks( [ openRow( "t1", "third" ) ] );
  await h.timers.poll();
  assert.equal( repaints.n, 0 );

  press( h.taskContainer, "mouseleave" );   // leaving the pane releases at once
  assert.equal( repaints.n, 1 );
  assert.match( h.taskContainer.textContent ?? "", /third/ );
  assert.doesNotMatch( h.taskContainer.textContent ?? "", /second/ );
  h.unmount();
} );

test( "Task List control arm: with no press in flight a poll repaints at once", async () => {
  const h = mountTaskPanes( [ openRow( "t1", "first" ) ] );
  h.store.startPolling();
  await h.timers.poll();
  const repaints = countRepaints( h.taskContainer );
  h.setTasks( [ openRow( "t1", "second" ) ] );
  await h.timers.poll();
  assert.equal( repaints.n, 1 );
  assert.match( h.taskContainer.textContent ?? "", /second/ );
  h.unmount();
} );

test( "Epic Board: a poll landing mid-press is held, the header click still toggles, and the release repaints once", async () => {
  const h = mountTaskPanes( [ openRow( "t1", "first" ) ] );
  h.store.startPolling();
  await h.timers.poll();
  const repaints = countRepaints( h.epicContainer );

  const header = h.epicContainer.querySelector( "tr.epic-group-header" ) as HTMLElement;
  assert.ok( header, "positive control: the epic group header is painted" );

  press( header, "mousedown" );
  h.setTasks( [ openRow( "t1", "second" ) ] );
  await h.timers.poll();
  assert.equal( repaints.n, 0, "the poll repainted the epic board during the press" );
  assert.ok( header.isConnected );

  press( header, "mouseup" );
  header.click();
  assert.equal( epicGroupIsExpanded( "epic:alpha", loadEpicGroupState() ), true, "the header click was lost" );

  h.timers.flushTimeouts();
  assert.equal( repaints.n, 1 );
  h.unmount();
} );

// ---------------------------------------------------------------------------
// Holding Area — its own real store and its own poll
// ---------------------------------------------------------------------------

function mountHoldingArea( rows: TaskItem[] ) {
  const timers = makeTimers();
  const bus    = createEventBusForTesting();
  let composite: TaskListComposite = { tasks: rows, count: rows.length };
  const posts: string[] = [];
  const api: HoldingAreaApiClient = {
    get  : async <T,>(): Promise<T> => composite as T,
    post : async <T,>( path: string ): Promise<T> => { posts.push( path ); return {} as T; },
  };
  const store = createHoldingAreaStore( {
    bus, api, nowFn: () => 0, setIntervalFn: timers.setIntervalFn, clearIntervalFn: timers.clearIntervalFn,
  } );
  const root = document.createElement( "div" );
  document.body.append( root );
  const renderer = createHoldingAreaRenderer( {
    eventBus: bus, store, nowDateFn: () => new Date( 0 ), setTimeoutFn: timers.setTimeoutFn,
  } );
  renderer.mount( root );
  return {
    timers, store, renderer, posts,
    container : root.querySelector( ".holding-area-container" ) as HTMLElement,
    setRows( next: TaskItem[] ) { composite = { tasks: next, count: next.length }; },
    unmount() { renderer.unmount(); root.remove(); },
  };
}

test( "Holding Area: Approve all pressed across a poll still posts, and the held repaint lands once on release", async () => {
  const h = mountHoldingArea( [ heldRow( "a", "first" ) ] );
  h.store.startPolling();
  await h.timers.poll();
  const repaints = countRepaints( h.container );

  const approve = h.container.querySelector( ".holding-approve-all" ) as HTMLButtonElement;
  assert.ok( approve, "positive control: the batch button is painted" );

  press( approve, "mousedown" );
  h.setRows( [ heldRow( "a", "second" ) ] );
  await h.timers.poll();
  assert.equal( repaints.n, 0, "the poll repainted the holding area during the press" );
  assert.ok( approve.isConnected );

  press( approve, "mouseup" );
  approve.click();
  await settle();
  assert.deepEqual( h.posts, [ "/api/tasks/a/transition" ], "the click never reached the batch" );

  h.timers.flushTimeouts();
  await settle();
  assert.match( h.container.textContent ?? "", /second/ );
  h.unmount();
} );

test( "Holding Area: a window blur mid-press releases the held repaint at once", async () => {
  const h = mountHoldingArea( [ heldRow( "a", "first" ) ] );
  h.store.startPolling();
  await h.timers.poll();
  const repaints = countRepaints( h.container );

  press( h.container.querySelector( ".holding-approve-all" )!, "mousedown" );
  h.setRows( [ heldRow( "a", "second" ) ] );
  await h.timers.poll();
  assert.equal( repaints.n, 0 );

  window.dispatchEvent( new Event( "blur" ) );
  assert.equal( repaints.n, 1 );
  assert.match( h.container.textContent ?? "", /second/ );
  h.unmount();
} );

// ---------------------------------------------------------------------------
// The guard alone — the edges a pane test would reach only by accident
// ---------------------------------------------------------------------------

function guardHarness() {
  const container = document.createElement( "div" );
  document.body.append( container );
  const timers = makeTimers();
  const guard  = wirePressHoldGuard( container, { setTimeoutFn: timers.setTimeoutFn } );
  const paints: string[] = [];
  return { container, timers, guard, paints };
}

test( "guard: no press means hold() declines and remembers nothing", () => {
  const g = guardHarness();
  assert.equal( g.guard.hold( () => g.paints.push( "x" ) ), false );
  press( g.container, "mouseleave" );
  assert.deepEqual( g.paints, [], "a release with nothing held must be a no-op" );
  g.guard.dispose();
} );

test( "guard: a second press before the first release's timer runs is NOT released by that stale timer", () => {
  const g = guardHarness();
  press( g.container, "mousedown" );
  press( g.container, "mouseup" );        // schedules release for press #1
  press( g.container, "mousedown" );      // press #2 — a double-click
  assert.equal( g.guard.hold( () => g.paints.push( "held" ) ), true );

  g.timers.flushTimeouts();               // press #1's timer — stale
  assert.deepEqual( g.paints, [], "a stale release painted during the second press" );

  press( g.container, "mouseup" );
  g.timers.flushTimeouts();
  assert.deepEqual( g.paints, [ "held" ] );
  g.guard.dispose();
} );

test( "guard: dispose detaches every listener, forgets the held paint, and voids a scheduled release", () => {
  const g = guardHarness();
  press( g.container, "mousedown" );
  g.guard.hold( () => g.paints.push( "held" ) );
  press( g.container, "mouseup" );
  g.guard.dispose();

  g.timers.flushTimeouts();
  press( g.container, "mouseleave" );
  window.dispatchEvent( new Event( "blur" ) );
  press( g.container, "mousedown" );
  assert.deepEqual( g.paints, [] );
  assert.equal( g.guard.hold( () => g.paints.push( "late" ) ), false, "a mousedown after dispose still started a press" );
  g.guard.dispose();                      // idempotent
} );
