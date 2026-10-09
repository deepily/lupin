// Row 71a11ed7 — "Approve refused: no-op transition 'queued'->'queued'" for an approve that took effect.
//
// A second approve reached the server after the first had committed. The server wrote nothing and said
// so (422), and both multiplexer stores reported that as a refusal. They now re-read the row and treat a
// 422 on a row ALREADY at the target status as a success. The server's message is unchanged.
//
// ⚠️ THE ARMS ARE NOT INTERCHANGEABLE. "Success when the row is there" alone is satisfied by a store that
// calls everything a success; "refusal when it is not" alone by one that never re-reads. The pair, plus
// "a 403 is never re-read" (a real refusal must not be rescued by a lucky status), is what pins the rule.

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { alreadyAtTarget } from "../../../lupin_app/static/js/multiplexer/stores/alreadyAtTarget";
import { createHoldingAreaStore } from "../../../lupin_app/static/js/multiplexer/stores/HoldingAreaStore";
import { createTaskListStore } from "../../../lupin_app/static/js/multiplexer/stores/TaskListStore";

class Rejected extends Error {
  constructor( public readonly status: number, message = "x", public readonly url = "u" ) { super( message ); }
}

/** An api whose POST rejects with `postErr` and whose GET of the one row answers `rowAnswer`. */
function fakeApi( postErr: unknown, rowAnswer: () => Promise<unknown>, listing: unknown = { tasks: [ { id: "t1", status: "queued", title: "t" } ], count: 1 } ) {
  const gets: string[] = [];
  const api = {
    get   : async ( path: string ) => { gets.push( path ); return path === "/api/tasks/t1" ? rowAnswer() : listing; },
    post  : async () => { throw postErr; },
    patch : async () => undefined,
  };
  return { api: api as never, gets };
}

const NOOP_422 = new Rejected( 422, "HTTP 422 u: {\"detail\":\"no-op transition 'queued'->'queued'\"}" );

// ---------------------------------------------------------------------------
// alreadyAtTarget — every branch
// ---------------------------------------------------------------------------

test( "alreadyAtTarget: a 422 on a row already at the target is true, and the read names the encoded id", async () => {
  const gets: string[] = [];
  const api = { get: async ( path: string ) => { gets.push( path ); return { status: "queued" }; } };
  assert.equal( await alreadyAtTarget( api as never, "a/b?c", "queued", NOOP_422 ), true );
  assert.deepEqual( gets, [ "/api/tasks/a%2Fb%3Fc" ] );
} );

test( "alreadyAtTarget: a 422 on a row at a DIFFERENT status is false", async () => {
  const { api } = fakeApi( null, async () => ( { status: "not_approved" } ) );
  assert.equal( await alreadyAtTarget( api, "t1", "queued", NOOP_422 ), false );
} );

test( "alreadyAtTarget: a non-422 is false and NO read is made", async () => {
  const { api, gets } = fakeApi( null, async () => ( { status: "queued" } ) );
  assert.equal( await alreadyAtTarget( api, "t1", "queued", new Rejected( 403 ) ), false );
  assert.equal( await alreadyAtTarget( api, "t1", "queued", null ), false );
  assert.equal( await alreadyAtTarget( api, "t1", "queued", undefined ), false );
  assert.deepEqual( gets, [], "a real refusal was re-read and could have been rescued by a lucky status" );
} );

test( "alreadyAtTarget: a failed or empty read leaves the original refusal standing", async () => {
  const failing = fakeApi( null, async () => { throw new Rejected( 500 ); } );
  assert.equal( await alreadyAtTarget( failing.api, "t1", "queued", NOOP_422 ), false );
  const empty = fakeApi( null, async () => null );
  assert.equal( await alreadyAtTarget( empty.api, "t1", "queued", NOOP_422 ), false );
} );

// ---------------------------------------------------------------------------
// HoldingAreaStore.transitionTask
// ---------------------------------------------------------------------------

function holdingStore( api: never ) {
  return createHoldingAreaStore( {
    bus: createEventBusForTesting(), api, actorProvider: () => "rick@example.com",
    setIntervalFn: () => 1, clearIntervalFn: () => { /* no timer */ },
  } );
}

test( "HoldingAreaStore: a 422 no-op on a row already queued is { ok: true }", async () => {
  const { api } = fakeApi( NOOP_422, async () => ( { status: "queued" } ) );
  assert.deepEqual( await holdingStore( api ).transitionTask( "t1", "queued", {} ), { ok: true } );
} );

test( "HoldingAreaStore: a 422 on a row NOT at the target is still a refusal carrying the server's words", async () => {
  const { api } = fakeApi( NOOP_422, async () => ( { status: "not_approved" } ) );
  const result = await holdingStore( api ).transitionTask( "t1", "queued", {} );
  assert.equal( result.ok, false );
  assert.match( result.message ?? "", /no-op transition/ );
} );

test( "HoldingAreaStore: a 403 stays a refusal and the row is never re-read", async () => {
  const { api, gets } = fakeApi( new Rejected( 403, "HTTP 403 /x: {\"detail\":\"not an approver\"}" ), async () => ( { status: "queued" } ) );
  const result = await holdingStore( api ).transitionTask( "t1", "queued", {} );
  assert.equal( result.ok, false );
  assert.deepEqual( gets, [] );
} );

// ---------------------------------------------------------------------------
// TaskListStore.transitionTask
// ---------------------------------------------------------------------------

async function listStore( api: never ) {
  const store = createTaskListStore( {
    bus: createEventBusForTesting(), api, endpoint: "/api/tasks?x", nowFn: () => 1,
  } as never );
  await store.refresh();
  return store;
}

test( "TaskListStore: a 422 no-op on a row already at the target resolves done and keeps the optimistic row", async () => {
  const { api } = fakeApi( NOOP_422, async () => ( { status: "queued" } ) );
  const store = await listStore( api );
  const { done } = store.transitionTask( "t1", "queued", {} );
  await done;   // rejects today
  assert.equal( store.composite()?.tasks?.[ 0 ]?.status, "queued" );
} );

test( "TaskListStore: a 422 on a row NOT at the target still rejects, so the renderer rolls back", async () => {
  const { api } = fakeApi( NOOP_422, async () => ( { status: "not_approved" } ) );
  const store = await listStore( api );
  const { done } = store.transitionTask( "t1", "queued", {} );
  await assert.rejects( done, ( e: unknown ) => e === NOOP_422 );
} );

test( "TaskListStore: a 403 rejects and the row is never re-read", async () => {
  const forbidden = new Rejected( 403 );
  const { api, gets } = fakeApi( forbidden, async () => ( { status: "queued" } ) );
  const store = await listStore( api );
  const { done } = store.transitionTask( "t1", "queued", {} );
  await assert.rejects( done, ( e: unknown ) => e === forbidden );
  assert.ok( !gets.includes( "/api/tasks/t1" ), "a real refusal was re-read" );
} );
