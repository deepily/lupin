// Promote/demote requests — TaskRequestStore (row c9fafb9d).
// 100% lines/branches/functions per the multiplexer coverage mandate.
//
// 🔴 THE PROPERTY THAT MATTERS MOST: A VERDICT RE-READS THE BOARDS ONLY WHEN IT LANDED. An
// approval moved a row between panes, so a re-read after a refusal would repaint nothing
// new and hide that nothing happened; a missing re-read after success leaves the row on the
// pane it left. Both directions are pinned below.
//
// ⚠️ The refusals are real `ApiError` instances, for the reason the holding-area store's
// tests give: the message's exact shape is what `holdingRefusalMessage` strips.

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { ApiError } from "../../../lupin_app/static/js/multiplexer/api/ApiClient";
import {
  createTaskRequestStore,
  TASK_REQUEST_POLL_INTERVAL_MS,
  type TaskRequestApiClient,
} from "../../../lupin_app/static/js/multiplexer/stores/TaskRequestStore";
import type { StoreRequestBadgesChangedPayload } from "../../../lupin_app/static/js/multiplexer/shared/types";

interface Harness {
  gets     : string[];
  posts    : Array<{ path: string; body: unknown }>;
  emitted  : StoreRequestBadgesChangedPayload[];
  after    : { calls: number };
  store    : ReturnType<typeof createTaskRequestStore>;
  interval : { cb: ( () => void ) | null; ms: number; cleared: number[] };
}

function harness(
  getImpl  : ( path: string ) => Promise<unknown>,
  postImpl : ( path: string, body: unknown ) => Promise<unknown> = async () => ( {} ),
  withAfter = true,
): Harness {
  const gets: string[] = [];
  const posts: Array<{ path: string; body: unknown }> = [];
  const emitted: StoreRequestBadgesChangedPayload[] = [];
  const after = { calls: 0 };
  const interval = { cb: null as ( () => void ) | null, ms: 0, cleared: [] as number[] };
  const bus = createEventBusForTesting();
  bus.on<StoreRequestBadgesChangedPayload>( "store_request_badges_changed", ( e ) => emitted.push( e.payload ) );
  const api: TaskRequestApiClient = {
    get  : async ( path ) => { gets.push( path ); return getImpl( path ) as never; },
    post : async ( path, body ) => { posts.push( { path, body } ); return postImpl( path, body ) as never; },
  };
  const store = createTaskRequestStore( {
    bus, api,
    afterVerdict    : withAfter ? async () => { after.calls += 1; } : undefined,
    nowFn           : () => 42,
    setIntervalFn   : ( cb, ms ) => { interval.cb = cb; interval.ms = ms; return 7; },
    clearIntervalFn : ( h ) => { interval.cleared.push( h ); },
  } );
  return { gets, posts, emitted, after, store, interval };
}

test( "counts are null before the first poll, then the endpoint's body, and each poll emits known", async () => {
  const h = harness( async () => ( { task_area: 1, holding_area: 2 } ) );
  assert.equal( h.store.counts(), null );
  await h.store.refresh();
  assert.deepEqual( h.gets, [ "/api/tasks/request-badges" ] );
  assert.deepEqual( h.store.counts(), { task_area: 1, holding_area: 2 } );
  assert.deepEqual( h.emitted, [ { known: true } ] );
} );

test( "a failed poll CLEARS the counts and says unknown — a stale badge would claim waiting work", async () => {
  let fail = false;
  const h = harness( async () => { if ( fail ) throw new ApiError( 500, "/api/tasks/request-badges", "boom" ); return { task_area: 3, holding_area: 0 }; } );
  await h.store.refresh();
  fail = true;
  await h.store.refresh();
  assert.equal( h.store.counts(), null );
  assert.deepEqual( h.emitted, [ { known: true }, { known: false } ] );
} );

test( "a colliding refresh JOINS the fetch in flight rather than starting a second", async () => {
  let release!: () => void;
  const gate = new Promise<void>( ( r ) => { release = r; } );
  const h = harness( async () => { await gate; return { task_area: 0, holding_area: 0 }; } );
  const first  = h.store.refresh();
  const second = h.store.refresh();
  release();
  await Promise.all( [ first, second ] );
  assert.equal( h.gets.length, 1 );
  assert.equal( h.emitted.length, 1 );
} );

test( "polling refreshes at once, then on the boards' 60s cadence; stopping clears it and is idempotent", async () => {
  const h = harness( async () => ( { task_area: 0, holding_area: 0 } ) );
  h.store.startPolling();
  assert.equal( h.interval.ms, TASK_REQUEST_POLL_INTERVAL_MS );
  assert.equal( TASK_REQUEST_POLL_INTERVAL_MS, 60000 );
  await new Promise( ( r ) => setTimeout( r, 0 ) );
  h.interval.cb!();
  await new Promise( ( r ) => setTimeout( r, 0 ) );
  assert.equal( h.gets.length, 2 );
  h.store.stopPolling();
  h.store.stopPolling();
  assert.deepEqual( h.interval.cleared, [ 7 ] );
} );

test( "a landed verdict posts to the row's verdict door, then re-reads the badges and BOTH boards", async () => {
  const h = harness( async () => ( { task_area: 0, holding_area: 0 } ) );
  const result = await h.store.submitVerdict( "abc/1", { verdict: "approved" } );
  assert.deepEqual( result, { ok: true } );
  assert.deepEqual( h.posts, [ { path: "/api/tasks/abc%2F1/request-verdict", body: { verdict: "approved" } } ] );
  assert.deepEqual( h.gets, [ "/api/tasks/request-badges" ] );
  assert.equal( h.after.calls, 1 );
} );

test( "a refused verdict resolves with the server's own sentence and re-reads NOTHING", async () => {
  const h = harness(
    async () => ( {} ),
    async ( path ) => { throw new ApiError( 403, path, JSON.stringify( { detail: "only Rick answers a request" } ) ); },
  );
  const result = await h.store.submitVerdict( "abc", { verdict: "denied" } );
  assert.deepEqual( result, { ok: false, message: "only Rick answers a request" } );
  assert.deepEqual( h.gets, [] );
  assert.equal( h.after.calls, 0 );
} );

test( "a store built without afterVerdict still resolves a landed verdict", async () => {
  const h = harness( async () => ( {} ), async () => ( {} ), false );
  assert.deepEqual( await h.store.submitVerdict( "abc", { verdict: "denied" } ), { ok: true } );
} );

test( "the filing detail is read once per request, keyed by id AND request_ts", async () => {
  const h = harness( async () => ( { events: [
    { transition: "request_filed", actor: "mr radio 52f3fe21", reason: "move: 'demote' (prior request: None) | reason: stale" },
  ] } ) );
  assert.equal( h.store.cachedDetail( "abc", "t1" ), undefined );
  await h.store.loadDetail( "abc", "t1" );
  assert.deepEqual( h.gets, [ "/api/tasks/abc/events" ] );
  assert.deepEqual( h.store.cachedDetail( "abc", "t1" ), { filer: "mr radio 52f3fe21", reason: "stale" } );
  assert.equal( h.store.cachedDetail( "abc", "t2" ), undefined, "a re-filed request is read afresh" );
} );

test( "a trail with no filing caches null; a FAILED read caches nothing, so the next paint asks again", async () => {
  let fail = false;
  const h = harness( async ( path ) => { if ( fail ) throw new ApiError( 502, path, "down" ); return { events: [] }; } );
  await h.store.loadDetail( "a", "t" );
  assert.equal( h.store.cachedDetail( "a", "t" ), null );
  fail = true;
  await h.store.loadDetail( "b", "t" );
  assert.equal( h.store.cachedDetail( "b", "t" ), undefined );
} );

// ---------------------------------------------------------------------------
// §6 item 18 — THE VERDICT'S RE-READ MUST HAVE STARTED AFTER THE VERDICT.
//
// 🔴 `refresh()` JOINS a read already in flight. That is right for the poll —
// one fetch, never two — and WRONG for a caller that just wrote, because a fetch
// that STARTED before the POST landed cannot see it however patiently you wait.
// `submitVerdict` awaited `refresh()`, so a verdict answered while the 60s poll
// happened to be mid-fetch settled on counts taken BEFORE it, and the badge sat
// one behind until the next tick.
//
// ⚠️ THE COLLISION IS THE WHOLE TEST. With no poll in flight the two verbs are
// indistinguishable — `refresh()` finds nothing to join and fetches. A test that
// does not arm the collision passes against either build.
// ---------------------------------------------------------------------------

/** A GET that hands back its resolver, so a poll can be held mid-fetch. */
function heldGets() {
  const pending: Array<( body: unknown ) => void> = [];
  return {
    pending,
    get : ( _path: string ) => new Promise<unknown>( ( res ) => { pending.push( res ); } ),
  };
}

test( "🔴 A VERDICT LANDING ON AN IN-FLIGHT POLL STILL READS THE COUNTS THE VERDICT MADE", async () => {
  const held = heldGets();
  const h    = harness( held.get );

  // The poll's fetch is in flight, holding counts taken BEFORE the verdict.
  const poll = h.store.refresh();
  assert.equal( held.pending.length, 1, "positive control: the poll really is mid-fetch" );

  const verdict = h.store.submitVerdict( "abc", { verdict: "approved" } );
  await Promise.resolve();
  held.pending[ 0 ]!( { task_area: 9, holding_area: 9 } );   // the PRE-verdict counts land
  await poll;

  // The verdict must not settle on those. It joins the poll, then takes its own read.
  await Promise.resolve(); await Promise.resolve();
  assert.equal( held.pending.length, 2,
    "the verdict settled on the poll's read — those counts predate its own POST (§6 item 18)" );
  held.pending[ 1 ]!( { task_area: 8, holding_area: 9 } );

  assert.deepEqual( await verdict, { ok: true } );
  assert.deepEqual( h.store.counts(), { task_area: 8, holding_area: 9 },
    "the badge is one behind: it shows the count taken before the verdict landed" );
  assert.equal( h.after.calls, 1, "the other boards are still told, exactly once" );
} );

test( "refreshAfterWrite with NO poll in flight simply reads — the uncontended arm", async () => {
  const h = harness( async () => ( { task_area: 1, holding_area: 0 } ) );
  await h.store.refreshAfterWrite();
  assert.deepEqual( h.gets, [ "/api/tasks/request-badges" ] );
  assert.deepEqual( h.store.counts(), { task_area: 1, holding_area: 0 } );
} );
