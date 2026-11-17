// Task List pane: status chips and the query_unavailable message.
//
// Both were ported from notifications.js renderTaskList.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/task_list_renderer_status_chips.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createTaskListRenderer, TASK_LIST_QUERY_UNAVAILABLE_MESSAGE } from "../../../../lupin_app/static/js/multiplexer/render/TaskListRenderer";
import type { TaskListComposite, TaskItem } from "../../../../lupin_app/static/js/multiplexer/render/taskListModel";
import type { StoreTaskListChangedPayload } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );
beforeEach( () => { localStorage.clear(); } );

const BOARD: TaskItem[] = [
  { id: "aaaaaaaa-0000-0000-0000-000000000001", title: "Queued row",   status: "queued",      owner_persona: "maria", priority: "P1" },
  { id: "bbbbbbbb-0000-0000-0000-000000000002", title: "Running row",  status: "in_progress", owner_persona: "maria", priority: "P2" },
  { id: "cccccccc-0000-0000-0000-000000000003", title: "Reviewing row", status: "review",     owner_persona: "sam",   priority: "P0" },
  { id: "dddddddd-0000-0000-0000-000000000004", title: "Blocked row",  status: "blocked",     owner_persona: "sam",   priority: "P3" },
];

function setup() {
  const bus = createEventBusForTesting();
  let composite: TaskListComposite | null = null;
  const store = {
    composite : () => composite,
    refresh   : () => {},
    refreshAfterWrite : () => Promise.resolve(),
    patch     : () => ( { restoreState: () => {}, done: Promise.resolve() } ),
    transition: () => ( { restoreState: () => {}, done: Promise.resolve() } ),
  } as never;
  const r = createTaskListRenderer( { eventBus: bus, stores: { taskList: store }, nowDateFn: () => new Date( "2026-11-07T16:00:00Z" ) } );
  const root = document.createElement( "div" );
  r.mount( root );
  const publish = ( next: TaskListComposite ): void => {
    composite = next;
    bus.emit<StoreTaskListChangedPayload>( { type: "store_task_list_changed", payload: { stampUpdated: false }, source: "test", ts: 0 } );
  };
  const titles  = (): string[] => Array.from( root.querySelectorAll( ".task-title" ) ).map( ( el ) => ( el.textContent ?? "" ).trim() );
  const chip    = ( key: string ): HTMLButtonElement => root.querySelector<HTMLButtonElement>( `[data-testid='task-status-chip-${ key }']` )!;
  const pressed = (): string[] => Array.from( root.querySelectorAll( ".task-status-chip" ) ).filter( ( b ) => b.getAttribute( "aria-pressed" ) === "true" ).map( ( b ) => b.getAttribute( "data-chip" )! );
  const count   = (): string => root.querySelector( ".section-header-count" )?.textContent ?? "";
  return { r, root, publish, titles, chip, pressed, count };
}

test( "five buttons are drawn, and All is pressed at the start", () => {
  const { root, pressed } = setup();
  const keys = Array.from( root.querySelectorAll( ".task-status-chip" ) ).map( ( b ) => b.getAttribute( "data-chip" ) );
  assert.deepEqual( keys, [ "all", "parked", "blocked", "in_progress", "queued" ] );
  assert.deepEqual( pressed(), [ "all" ] );
} );

test( "a chip narrows the rows and the count; In progress also shows review", () => {
  const { publish, titles, chip, pressed, count } = setup();
  publish( { tasks: BOARD, count: 4 } );
  assert.equal( titles().length, 4 );
  chip( "in_progress" ).click();
  assert.deepEqual( titles().sort(), [ "Reviewing row", "Running row" ] );
  assert.deepEqual( pressed(), [ "in_progress" ] );
  assert.equal( count(), "Live: 2" );
  chip( "queued" ).click();
  assert.equal( titles().length, 3 );
  chip( "in_progress" ).click();
  assert.deepEqual( titles(), [ "Queued row" ] );
} );

test( "All clears the selection and shows every row", () => {
  const { publish, titles, chip, pressed } = setup();
  publish( { tasks: BOARD, count: 4 } );
  chip( "blocked" ).click();
  assert.deepEqual( titles(), [ "Blocked row" ] );
  chip( "all" ).click();
  assert.equal( titles().length, 4 );
  assert.deepEqual( pressed(), [ "all" ] );
} );

test( "a chip that matches nothing says so, and a new poll keeps the filter", () => {
  const { publish, root, chip, titles } = setup();
  publish( { tasks: BOARD, count: 4 } );
  chip( "parked" ).click();
  assert.match( root.querySelector( ".task-list-container" )!.textContent ?? "", /No tasks match the selected statuses/ );
  publish( { tasks: BOARD, count: 4 } );
  assert.match( root.querySelector( ".task-list-container" )!.textContent ?? "", /No tasks match the selected statuses/ );
  chip( "all" ).click();
  assert.equal( titles().length, 4 );
} );

test( "an empty board still says No open tasks, whatever the chip", () => {
  const { publish, root, chip } = setup();
  publish( { tasks: [], count: 0 } );
  chip( "queued" ).click();
  assert.match( root.querySelector( ".task-list-container" )!.textContent ?? "", /No open tasks/ );
} );

test( "query_unavailable names the missing file and zeroes the count", () => {
  const { publish, root, count } = setup();
  publish( { status: "query_unavailable" } );
  const text = root.querySelector( ".task-list-query-unavailable" )!.textContent ?? "";
  assert.equal( text, TASK_LIST_QUERY_UNAVAILABLE_MESSAGE );
  assert.match( text, /task-list-query\.js is missing or failed to parse/ );
  assert.equal( count(), "Live: 0" );
} );

test( "unmount then mount again draws fresh chips", () => {
  const { r, root } = setup();
  r.unmount();
  r.mount( root );
  assert.equal( root.querySelectorAll( ".task-status-chip" ).length, 5 );
} );
