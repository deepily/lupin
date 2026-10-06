// Legacy notifications.js — row 8796333b, slice 3: a `task_store_changed` frame on the queue
// socket re-reads the legacy task list and the legacy finished-tasks pane.
//
// What is real here: the class loaded from notifications.js, `handleQueueMessage` (the frame
// goes in as the JSON text a socket delivers), `_handleTaskStoreChanged`, `refreshTaskList`,
// `_refreshTaskListAfterWrite` and `refreshFinishedTasks`. What is stubbed: the two fetches
// (they count their calls and can be held open) and the renderers, which are not under test.
//
// The server half (a commit emits the frame) and the multiplexer half are tested elsewhere:
// src/tests/unit/test_task_store_change_notifier.py and
// src/tests/unit/multiplexer/task_store_changed_through_queue_transport.test.ts.
//
// Coverage note: notifications.js cannot be instrumented by c8 (it is loaded by slicing the
// source through `vm.runInThisContext`), so this tier is its behavioural gate. See the
// exemption block in src/tests/run-typescript-tests.sh.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/a_task_store_push_rereads_the_legacy_task_panes.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE             = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

const PUSH_EVENT = "task_store_changed";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext(
    fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;",
    { filename: NOTIFICATIONS_JS }
  );
} );

beforeEach( () => {
  // The finished-tasks refresh returns early when its section is absent, so the section is
  // present in every test and its absence is never the reason a count reads zero.
  document.body.innerHTML = `<div id="section-finished-tasks"><input id="finished-tasks-window" value="1"></div>`;
} );

type UI = Record<string, unknown> & {
  handleQueueMessage: ( event: { data: string } ) => void;
  refreshTaskList: () => Promise<void>;
  refreshFinishedTasks: () => Promise<void>;
  _buildQueueAuthMessage: () => { subscribed_events: string[] };
  _buildAudioAuthMessage: () => { subscribed_events: string[] };
};

const tick      = (): Promise<void> => new Promise( ( r ) => setTimeout( r, 0 ) );
const settleAll = async (): Promise<void> => { for ( let i = 0; i < 10; i++ ) await tick(); };

// The frame as the server sends it: an invalidation with no delta. The payload fields are
// the ones task_store_change_notifier.py builds; the handler reads none of them.
function pushFrame(): { data: string } {
  return { data: JSON.stringify( {
    type: PUSH_EVENT, event_id: 18211, item_id: "aaaaaaaa-1111-2222-3333-444444444444",
    transition: "amended", to_status: "queued", ts: "2026-10-06T13:00:00+00:00", count: 1,
  } ) };
}

interface Harness {
  ui: UI;
  counts: { list: number; finished: number };
  errors: unknown[][];
  listGates: Array<() => void>;
  finishedGates: Array<() => void>;
}

/**
 * A constructor-bypassed instance with both polls "running" unless told otherwise.
 *
 * `holdList` / `holdFinished` make each fetch wait until its gate is called, so a test can
 * land a push while a read is in flight.
 */
function makeUI( opts: { listPolling?: boolean; finishedPolling?: boolean; holdList?: boolean; holdFinished?: boolean } = {} ): Harness {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui   = Object.create( Ctor.prototype ) as UI;
  const h: Harness = { ui, counts: { list: 0, finished: 0 }, errors: [], listGates: [], finishedGates: [] };

  ui.debug = false;
  ui.log   = (): void => {};
  ui.error = ( ...args: unknown[] ): void => { h.errors.push( args ); };
  ui.authToken      = "<test-double-token-placeholder>";
  ui.queueSessionId = "calm dolphin";
  ui.audioSessionId = "wise owl";

  // A truthy handle is what "the poll is running" means to the handler. No real interval is
  // started, so nothing is left ticking after the test.
  ui.taskListPollIntervalHandle = opts.listPolling === false ? null : 1;
  ui._finishedTasksTimer        = opts.finishedPolling === false ? null : 1;
  ui._taskListFetchInFlight     = false;
  ui._finishedTasksFetchInFlight = false;

  ui.fetchTaskList = async () => {
    h.counts.list += 1;
    if ( opts.holdList ) await new Promise<void>( ( r ) => { h.listGates.push( r ); } );
    return { tasks: [], count: 0 };
  };
  ui.fetchFinishedTasks = async () => {
    h.counts.finished += 1;
    if ( opts.holdFinished ) await new Promise<void>( ( r ) => { h.finishedGates.push( r ); } );
    return { eventsByStatus: {}, error: null };
  };

  ui.renderTaskList        = (): void => {};
  ui.fetchEpicStories      = async (): Promise<void> => {};
  ui.renderEpicBoard       = (): void => {};
  ui.fetchFlowRatio        = async () => ( {} );
  ui._renderFlowRatio      = (): void => {};
  ui.initFlowRatioControls = (): void => {};
  ui.refreshHoldingArea    = async (): Promise<void> => {};
  ui.refreshRequestBadges  = async (): Promise<void> => {};
  ui.renderFinishedTasks   = (): void => {};
  return h;
}


// ── the subscription ──────────────────────────────────────────────────────────

test( "the QUEUE socket subscribes task_store_changed", () => {
  const queue = makeUI().ui._buildQueueAuthMessage().subscribed_events;
  assert.ok(
    queue.includes( PUSH_EVENT ),
    "task_store_changed is missing from _buildQueueAuthMessage's subscribed_events, so the server never sends it to this page"
  );
} );

test( "the AUDIO socket does not subscribe task_store_changed, and still carries its own events", () => {
  const audio = makeUI().ui._buildAudioAuthMessage().subscribed_events;
  assert.ok( audio.includes( "audio_streaming_chunk" ), "control: the audio list no longer carries its own event, so the zero below means nothing" );
  assert.ok( !audio.includes( PUSH_EVENT ), "task_store_changed is in the AUDIO list; /ws/audio is a different socket" );
} );


// ── a frame causes a read ─────────────────────────────────────────────────────

test( "a task_store_changed frame re-reads the task list once and the finished tasks once", async () => {
  const { ui, counts, errors } = makeUI();
  ui.handleQueueMessage( pushFrame() );
  await settleAll();
  assert.equal( counts.list, 1, "the task list was not re-read exactly once on the push" );
  assert.equal( counts.finished, 1, "the finished-tasks pane was not re-read exactly once on the push" );
  assert.deepEqual( errors, [] );
} );

test( "a frame of another type reads neither pane", async () => {
  const { ui, counts } = makeUI();
  ui.handleQueueMessage( { data: JSON.stringify( { type: "sys_ping" } ) } );
  ui.handleQueueMessage( { data: JSON.stringify( { type: "notification_play_sound" } ) } );
  await settleAll();
  assert.deepEqual( counts, { list: 0, finished: 0 } );
} );


// ── a pane that is not polling is left alone ──────────────────────────────────

test( "with the task-list poll stopped, a push reads the finished tasks and not the task list", async () => {
  const { ui, counts } = makeUI( { listPolling: false } );
  ui.handleQueueMessage( pushFrame() );
  await settleAll();
  assert.deepEqual( counts, { list: 0, finished: 1 } );
} );

test( "with the finished-tasks poll stopped, a push reads the task list and not the finished tasks", async () => {
  const { ui, counts } = makeUI( { finishedPolling: false } );
  ui.handleQueueMessage( pushFrame() );
  await settleAll();
  assert.deepEqual( counts, { list: 1, finished: 0 } );
} );


// ── a push during a read in flight is not dropped ─────────────────────────────

test( "a push that lands during a task-list tick in flight gets a fresh read after the tick ends", async () => {
  const { ui, counts, listGates } = makeUI( { holdList: true, finishedPolling: false } );
  const tickRun = ui.refreshTaskList();
  await settleAll();
  assert.equal( counts.list, 1, "setup: the tick's read is in flight" );
  assert.equal( ui._taskListFetchInFlight, true, "setup: the in-flight guard is set" );

  ui.handleQueueMessage( pushFrame() );
  await settleAll();
  assert.equal( counts.list, 1, "a second read began while the tick was still in flight" );

  listGates[ 0 ]!();
  await tickRun;
  await settleAll();
  assert.equal( counts.list, 2, "the push was dropped: no read began after the tick ended" );
  listGates[ 1 ]!();
  await settleAll();
  assert.equal( ui._taskListFetchInFlight, false );
} );

test( "three pushes during a finished-tasks read in flight cause exactly one more read", async () => {
  const { ui, counts, finishedGates } = makeUI( { holdFinished: true, listPolling: false } );
  const firstRead = ui.refreshFinishedTasks();
  await settleAll();
  assert.equal( counts.finished, 1, "setup: the first read is in flight" );

  ui.handleQueueMessage( pushFrame() );
  ui.handleQueueMessage( pushFrame() );
  ui.handleQueueMessage( pushFrame() );
  await settleAll();
  assert.equal( counts.finished, 1, "a second read began while the first was still in flight" );

  finishedGates[ 0 ]!();
  await settleAll();
  assert.equal( counts.finished, 2, "the pushes were dropped: no read began after the first one ended" );
  finishedGates[ 1 ]!();
  await firstRead;
  await settleAll();
  assert.equal( counts.finished, 2, "more than one extra read ran for one burst of pushes" );
  assert.equal( ui._finishedTasksPushPending, false );
} );

test( "a finished-tasks read with no push during it is not followed by another", async () => {
  const { ui, counts } = makeUI( { listPolling: false } );
  await ui.refreshFinishedTasks();
  await settleAll();
  assert.equal( counts.finished, 1 );
} );


// ── a failed read is logged and stays out of the socket handler ───────────────

test( "a task-list read that fails on a push is logged and does not throw into the socket handler", async () => {
  const { ui, errors } = makeUI( { finishedPolling: false } );
  ui.fetchTaskList = async () => { throw new Error( "boom from the list" ); };
  assert.doesNotThrow( () => ui.handleQueueMessage( pushFrame() ) );
  await settleAll();
  assert.equal( errors.length, 1, "the failed read was not logged exactly once" );
  assert.equal( errors[ 0 ]![ 0 ], "task_store_changed: task list refresh failed:" );
  assert.equal( ( errors[ 0 ]![ 1 ] as Error ).message, "boom from the list" );
  assert.equal( ui._taskListFetchInFlight, false, "the in-flight guard was left set after the failure" );
} );

test( "a finished-tasks read that fails on a push is logged and does not throw into the socket handler", async () => {
  const { ui, errors } = makeUI( { listPolling: false } );
  ui.fetchFinishedTasks = async () => { throw new Error( "boom from finished" ); };
  assert.doesNotThrow( () => ui.handleQueueMessage( pushFrame() ) );
  await settleAll();
  assert.equal( errors.length, 1, "the failed read was not logged exactly once" );
  assert.equal( errors[ 0 ]![ 0 ], "task_store_changed: finished tasks refresh failed:" );
  assert.equal( ( errors[ 0 ]![ 1 ] as Error ).message, "boom from finished" );
  assert.equal( ui._finishedTasksFetchInFlight, false, "the in-flight guard was left set after the failure" );
} );
