// Multiplexer — AckStore unit tests (row 4f320c27 M1).
// Run via `npx tsx --test src/tests/unit/multiplexer/ack_store.test.ts`.
//
// Coverage target: 100% lines/branches/functions on AckStore.ts, per the Lupin-wide
// mandate. Uses the REAL EventBus rather than a stub — the store's whole live path
// is a bus subscription, and a stubbed bus would be a fixture that cannot
// discriminate a working subscription from a missing one.
//
// 🔴 THE ONE TEST THAT MATTERS MOST IS NOT IN THIS FILE'S SUBJECT AT ALL. Mr. Radio's
// condition 2 has TWO arms — an empty-message ack must LAND IN AckStore and must NEVER
// REACH NotificationStore — and a coverage number rewards writing only the first. Both
// live at the bottom, driven through the real NotificationStore on one real bus, which
// is the only altitude where "never reached" is a fact rather than an assumption.

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createStorageServiceForTesting, InMemoryStorage } from "../../../lupin_app/static/js/multiplexer/shared/StorageService";
import { createAckStore } from "../../../lupin_app/static/js/multiplexer/stores/AckStore";
import { createNotificationStore } from "../../../lupin_app/static/js/multiplexer/stores/NotificationStore";
import type {
  AckStore,
  BroadcastAcksApiClient,
} from "../../../lupin_app/static/js/multiplexer/stores/AckStore";
import {
  COMMONS_BROADCAST_ACK_TYPE,
  type BroadcastAckPayload,
  type StoreBroadcastAcksChangedPayload,
} from "../../../lupin_app/static/js/multiplexer/shared/types";

const BCAST = "22222222-bbbb-4ccc-8ddd-333333333333";
const OTHER = "99999999-cccc-4ddd-8eee-444444444444";

function freshStore(): {
  bus    : ReturnType<typeof createEventBusForTesting>;
  store  : AckStore;
  changes: StoreBroadcastAcksChangedPayload[];
} {
  const bus     = createEventBusForTesting();
  const store   = createAckStore( { bus } );
  const changes: StoreBroadcastAcksChangedPayload[] = [];
  bus.on<StoreBroadcastAcksChangedPayload>( "store_broadcast_acks_changed", ( e ) => changes.push( e.payload ) );
  return { bus, store, changes };
}

function emitAck( bus: ReturnType<typeof createEventBusForTesting>, payload: unknown ): void {
  bus.emit( { type: COMMONS_BROADCAST_ACK_TYPE, payload, source: "test", ts: 0 } );
}

// `result` may be a value (resolve) or an Error (reject), driving both paths.
function stubApi( result: unknown | Error ): BroadcastAcksApiClient {
  return {
    get<T>( _path: string ): Promise<T> {
      if ( result instanceof Error ) return Promise.reject( result );
      return Promise.resolve( result as T );
    },
  };
}

// ===========================================================================
// Empty state
// ===========================================================================

test( "an untouched store reports no acks and a zero count for any broadcast", () => {
  const { store } = freshStore();
  assert.deepEqual( store.acksFor( BCAST ), [] );
  assert.equal( store.countFor( BCAST ), 0 );
} );

// ===========================================================================
// The live fold
// ===========================================================================

test( "a live ack is folded and announced as `added`", () => {
  const { bus, store, changes } = freshStore();
  const stop = store.start();
  emitAck( bus, {
    broadcast_id: BCAST, session_id: "s1", persona_name: "Mr. Radio",
    persona_icon: "🦉", persona_color: "#FFA000", status: "completed",
    body_summary: "on it",
  } satisfies BroadcastAckPayload );

  assert.equal( store.countFor( BCAST ), 1 );
  assert.deepEqual( store.acksFor( BCAST ), [ {
    session_id: "s1", persona_name: "Mr. Radio", persona_icon: "🦉",
    persona_color: "#FFA000", status: "completed", body_summary: "on it",
  } ] );
  assert.deepEqual( changes, [ { changeKind: "added", broadcast_id: BCAST } ] );
  stop();
} );

test( "🔴 RE-ACKING A SESSION REPLACES IT — the tally counts SEATS, not messages", () => {
  // A seat acks `pending` then `completed`. Appending would count it twice and the
  // tally would read 2 of N for one seat, which is the defect the session_id fold key
  // exists to prevent. Server-side `get_latest_acks_for_broadcast` applies the same
  // rule; if the two ever disagree, a reload silently CHANGES the number.
  const { bus, store, changes } = freshStore();
  const stop = store.start();
  emitAck( bus, { broadcast_id: BCAST, session_id: "s1", status: "pending" } );
  emitAck( bus, { broadcast_id: BCAST, session_id: "s1", status: "completed" } );

  assert.equal( store.countFor( BCAST ), 1, "one seat, one tally entry" );
  assert.equal( store.acksFor( BCAST )[ 0 ]!.status, "completed", "the LATEST status wins" );
  assert.deepEqual( changes.map( c => c.changeKind ), [ "added", "updated" ] );
  stop();
} );

test( "two different sessions are two tally entries", () => {
  const { bus, store } = freshStore();
  const stop = store.start();
  emitAck( bus, { broadcast_id: BCAST, session_id: "s1" } );
  emitAck( bus, { broadcast_id: BCAST, session_id: "s2" } );
  assert.equal( store.countFor( BCAST ), 2 );
  stop();
} );

test( "🔴 TWO UNATTRIBUTED ACKS ARE TWO ACKS, NOT ONE", () => {
  // They are unattributable, not duplicates of each other. Collapsing them under a
  // shared placeholder key would silently under-count every seat whose bridge carried
  // no session_id. The server's fold makes the same choice.
  const { bus, store } = freshStore();
  const stop = store.start();
  emitAck( bus, { broadcast_id: BCAST, persona_name: "one" } );
  emitAck( bus, { broadcast_id: BCAST, persona_name: "two" } );
  assert.equal( store.countFor( BCAST ), 2 );
  assert.deepEqual( store.acksFor( BCAST ).map( a => a.persona_name ), [ "one", "two" ] );
  stop();
} );

test( "acks for different broadcasts do not mix", () => {
  const { bus, store } = freshStore();
  const stop = store.start();
  emitAck( bus, { broadcast_id: BCAST, session_id: "s1" } );
  emitAck( bus, { broadcast_id: OTHER, session_id: "s1" } );
  assert.equal( store.countFor( BCAST ), 1 );
  assert.equal( store.countFor( OTHER ), 1 );
  stop();
} );

test( "an ack with NO broadcast_id is dropped — there is no tally it belongs to", () => {
  const { bus, store, changes } = freshStore();
  const stop = store.start();
  emitAck( bus, { session_id: "s1" } );
  assert.equal( store.countFor( BCAST ), 0 );
  assert.deepEqual( changes, [], "a dropped ack announces nothing" );
  stop();
} );

test( "an ack with NO payload at all is dropped", () => {
  const { bus, store, changes } = freshStore();
  const stop = store.start();
  emitAck( bus, undefined );
  assert.deepEqual( changes, [] );
  stop();
} );

test( "non-string identity fields become null, and a missing summary becomes an empty string", () => {
  const { bus, store } = freshStore();
  const stop = store.start();
  emitAck( bus, {
    broadcast_id: BCAST, session_id: "s1",
    persona_name: 42, persona_icon: null, persona_color: undefined,
    status: { nope: true }, body_summary: 7,
  } );
  assert.deepEqual( store.acksFor( BCAST ), [ {
    session_id: "s1", persona_name: null, persona_icon: null,
    persona_color: null, status: null, body_summary: "",
  } ] );
  stop();
} );

test( "the returned array is a DEFENSIVE COPY — mutating it cannot corrupt the tally", () => {
  const { bus, store } = freshStore();
  const stop = store.start();
  emitAck( bus, { broadcast_id: BCAST, session_id: "s1" } );
  ( store.acksFor( BCAST ) as unknown as unknown[] ).length = 0;
  assert.equal( store.countFor( BCAST ), 1 );
  stop();
} );

test( "the unsubscribe returned by start() actually stops the fold", () => {
  const { bus, store } = freshStore();
  const stop = store.start();
  stop();
  emitAck( bus, { broadcast_id: BCAST, session_id: "s1" } );
  assert.equal( store.countFor( BCAST ), 0, "a stopped store must not keep folding" );
} );

// ===========================================================================
// Hydration — the half that makes a tally survive a reload
// ===========================================================================

test( "hydrate folds the persisted rows and announces `hydrated`", async () => {
  const { store, changes } = freshStore();
  await store.hydrate( stubApi( { acks: [
    { session_id: "s1", persona_name: "Mr. Radio", persona_icon: "🦉",
      persona_color: "#FFA000", ack_status: "completed", body_summary: "on it" },
    { session_id: "s2", persona_name: "María", ack_status: "pending" },
  ] } ), BCAST );

  assert.equal( store.countFor( BCAST ), 2 );
  assert.equal( store.acksFor( BCAST )[ 0 ]!.status, "completed",
    "the wire field is `ack_status`, not `status` — the server lifts it under a name that does not collide with the row's delivery `state`" );
  assert.equal( store.acksFor( BCAST )[ 1 ]!.body_summary, "", "a missing summary is an empty string" );
  assert.deepEqual( changes, [ { changeKind: "hydrated", broadcast_id: BCAST } ] );
} );

test( "🔴 HYDRATE REPLACES, IT DOES NOT MERGE", async () => {
  // A hydrate is the authoritative persisted answer. Merging would let a stale live
  // ack from a previous mount outlive the truth — and it would be invisible, because
  // a tally that is too HIGH looks exactly like a tally that is right.
  const { bus, store } = freshStore();
  const stop = store.start();
  emitAck( bus, { broadcast_id: BCAST, session_id: "ghost" } );
  assert.equal( store.countFor( BCAST ), 1 );

  await store.hydrate( stubApi( { acks: [ { session_id: "s1" } ] } ), BCAST );
  assert.deepEqual( store.acksFor( BCAST ).map( a => a.session_id ), [ "s1" ],
    "the stale live ack must not survive the authoritative answer" );
  stop();
} );

test( "hydrating an empty list empties the tally rather than leaving it stale", async () => {
  const { bus, store } = freshStore();
  const stop = store.start();
  emitAck( bus, { broadcast_id: BCAST, session_id: "s1" } );
  await store.hydrate( stubApi( { acks: [] } ), BCAST );
  assert.equal( store.countFor( BCAST ), 0 );
  stop();
} );

test( "a response with no `acks` key at all hydrates to empty rather than throwing", async () => {
  const { store } = freshStore();
  await store.hydrate( stubApi( {} ), BCAST );
  assert.equal( store.countFor( BCAST ), 0 );
} );

test( "a response whose `acks` is not an array hydrates to empty", async () => {
  const { store } = freshStore();
  await store.hydrate( stubApi( { acks: "not-an-array" } ), BCAST );
  assert.equal( store.countFor( BCAST ), 0 );
} );

test( "a null response body hydrates to empty rather than throwing", async () => {
  const { store } = freshStore();
  await store.hydrate( stubApi( null ), BCAST );
  assert.equal( store.countFor( BCAST ), 0 );
} );

test( "hydrated rows with no session_id each get their own entry", async () => {
  const { store } = freshStore();
  await store.hydrate( stubApi( { acks: [ { persona_name: "a" }, { persona_name: "b" } ] } ), BCAST );
  assert.equal( store.countFor( BCAST ), 2 );
} );

test( "a hydrate failure propagates rather than silently leaving a wrong tally", async () => {
  const { store } = freshStore();
  await assert.rejects( () => store.hydrate( stubApi( new Error( "boom" ) ), BCAST ), /boom/ );
  assert.equal( store.countFor( BCAST ), 0 );
} );

test( "the broadcast id is URL-ENCODED into the path", async () => {
  const { store } = freshStore();
  const seen: string[] = [];
  await store.hydrate( { get<T>( path: string ): Promise<T> {
    seen.push( path );
    return Promise.resolve( { acks: [] } as T );
  } }, "a b/c?d" );
  assert.deepEqual( seen, [ "/api/notifications/broadcast-acks/a%20b%2Fc%3Fd" ] );
} );

// ===========================================================================
// clear
// ===========================================================================

test( "clear drops one broadcast's tally and announces `cleared`", () => {
  const { bus, store, changes } = freshStore();
  const stop = store.start();
  emitAck( bus, { broadcast_id: BCAST, session_id: "s1" } );
  emitAck( bus, { broadcast_id: OTHER, session_id: "s1" } );
  changes.length = 0;

  store.clear( BCAST );
  assert.equal( store.countFor( BCAST ), 0 );
  assert.equal( store.countFor( OTHER ), 1, "clearing one card must not clear the others" );
  assert.deepEqual( changes, [ { changeKind: "cleared", broadcast_id: BCAST } ] );
  stop();
} );

test( "clearing a broadcast that was never acked announces NOTHING", () => {
  // An event for a no-op would make every renderer re-render on a clear that changed
  // nothing, and would make the event stream a poor signal of actual change.
  const { store, changes } = freshStore();
  store.clear( BCAST );
  assert.deepEqual( changes, [] );
} );

// ===========================================================================
// 🔴 MR. RADIO'S CONDITION 2 — BOTH ARMS, ON ONE REAL BUS
//
// Arm A alone is what a coverage number rewards: the ack reaches AckStore. Arm B is
// the one that would be skipped, and it is the one the defect lives in — an ack that
// ALSO carded would put a bodiless row in the user's notification history, which is
// precisely what intercepting before normalize() exists to prevent.
//
// These drive the REAL NotificationStore, not a re-implementation of the intercept.
// A test that re-emitted the bus event itself would pass with the intercept deleted.
// ===========================================================================

function wireBothStores() {
  const bus     = createEventBusForTesting();
  const storage = createStorageServiceForTesting( bus, new InMemoryStorage() );
  const notifications = createNotificationStore( {
    bus, storage,
    setTimeoutFn   : ( () => 0 ) as ( cb: () => void, ms: number ) => unknown,
    clearTimeoutFn : () => {},
    nowFn          : () => 1_700_000_000_000,
  } );
  const acks = createAckStore( { bus } );
  const stop = acks.start();
  return { bus, notifications, acks, stop };
}

// The frame exactly as the server sends it: `message: ""`, identity in `payload`.
function emitServerAckFrame( bus: ReturnType<typeof createEventBusForTesting>, payload: unknown, extra: Record<string, unknown> = {} ): void {
  bus.emit( {
    type   : "notification_queue_update",
    payload: { notification: {
      notification_type: COMMONS_BROADCAST_ACK_TYPE,
      id_hash          : "ack-1",
      message          : "",
      sender_id        : "claude.code@unknown.deepily.ai#f19a8996",
      payload,
      ...extra,
    } },
    source : "test",
    ts     : 0,
  } );
}

test( "ARM A — an EMPTY-MESSAGE ack lands in AckStore", () => {
  const { bus, acks, stop } = wireBothStores();
  emitServerAckFrame( bus, {
    broadcast_id: BCAST, session_id: "s1", persona_name: "Mr. Radio", status: "completed",
  } );
  assert.equal( acks.countFor( BCAST ), 1, "the ack must survive the intercept and fold" );
  assert.equal( acks.acksFor( BCAST )[ 0 ]!.persona_name, "Mr. Radio",
    "the identity travels in `payload`; normalize() would have dropped it" );
  stop();
} );

test( "🔴 ARM B — and it NEVER REACHES NotificationStore", () => {
  const { bus, notifications, acks, stop } = wireBothStores();
  emitServerAckFrame( bus, { broadcast_id: BCAST, session_id: "s1" } );
  assert.equal( acks.countFor( BCAST ), 1, "precondition — the ack did arrive" );
  assert.equal( notifications.list().length, 0,
    "a tally element is not a history entry: a carded ack is a bodiless row in the user's notification list" );
  stop();
} );

test( "ARM B holds for an ack carrying a NON-empty message too", () => {
  // The interception is by KIND, not by emptiness. If it keyed on the empty message,
  // a server that ever filled in a summary would start carding acks — and Arm A would
  // still pass, because the ack would reach AckStore either way.
  const { bus, notifications, acks, stop } = wireBothStores();
  emitServerAckFrame( bus, { broadcast_id: BCAST, session_id: "s1" }, { message: "Mr. Radio acked" } );
  assert.equal( acks.countFor( BCAST ), 1 );
  assert.equal( notifications.list().length, 0, "still not a card — the intercept is by kind" );
  stop();
} );

test( "an ack frame with a MALFORMED payload is still not carded", () => {
  // It cannot be folded (no broadcast_id), but it must not fall through to normalize()
  // either — that would card a bodiless row, the exact defect the intercept prevents.
  const { bus, notifications, acks, stop } = wireBothStores();
  emitServerAckFrame( bus, { session_id: "s1" } );
  assert.equal( acks.countFor( BCAST ), 0, "unfoldable" );
  assert.equal( notifications.list().length, 0, "and still not carded" );
  stop();
} );

test( "an ack frame with NO payload key is still not carded", () => {
  const { bus, notifications, stop } = wireBothStores();
  emitServerAckFrame( bus, undefined );
  assert.equal( notifications.list().length, 0 );
  stop();
} );

test( "🔴 CONTROL — an ORDINARY notification on the same wiring IS carded", () => {
  // Four "not carded" assertions above are also what a NotificationStore that cards
  // nothing returns. This is the arm that makes them mean something.
  const { bus, notifications, acks, stop } = wireBothStores();
  bus.emit( {
    type   : "notification_queue_update",
    payload: { notification: { id_hash: "n1", message: "an ordinary message", sender_id: "cc@x#a1" } },
    source : "test",
    ts     : 0,
  } );
  assert.equal( notifications.list().length, 1,
    "CONTROL FAILED — this wiring cards nothing at all, so every 'not carded' assertion above proved nothing" );
  assert.equal( acks.countFor( BCAST ), 0, "and an ordinary message is not an ack" );
  stop();
} );
