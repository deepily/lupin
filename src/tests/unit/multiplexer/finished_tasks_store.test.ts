// FinishedTasksStore — fetch, window, cache and timer (row 470b7509).
//
// 🔴 THE FAKE API HONOURS ITS INPUT, AND THAT IS THE POINT OF THIS FILE. A
// `get: async () => page` fake returns the same body whatever URL it is handed,
// so every assertion written over it is satisfied identically by a store that
// sends the right query and one that sends nothing at all — the door, the
// window and the limit would all be unfalsifiable. This fake RECORDS every URL
// and answers PER STATUS, so a wrong request produces a different observation.
//
// Run: npx tsx --test src/tests/unit/multiplexer/finished_tasks_store.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createFinishedTasksStore,
  FINISHED_TASKS_ENDPOINT,
} from "../../../lupin_app/static/js/multiplexer/stores/FinishedTasksStore";
import {
  FINISHED_STATUSES,
  FINISHED_TASKS_POLL_INTERVAL_MS,
  type FinishedTaskEvent,
} from "../../../lupin_app/static/js/multiplexer/render/finishedTasksModel";

const NOW = Date.parse( "2026-09-07T20:00:00.000Z" );

function ev( id: number, status: string ): FinishedTaskEvent {
  return {
    id, item_id: `i${ id }`, ts: "2026-09-07T19:00:00.000Z",
    actor: "rio c079db30", transition: `in_progress->${ status }`,
    reason: "r", title: `t${ id }`,
  };
}

/** A recording fake that answers PER STATUS and can be told to fail one. */
function fakeApi( opts: {
  rows?  : Record<string, ReadonlyArray<FinishedTaskEvent>>;
  fail?  : Record<string, unknown>;
  body?  : Record<string, unknown>;
} = {} ) {
  const urls: string[] = [];
  return {
    urls,
    statusOf( url: string ): string {
      return /to_status=([a-z_]+)/.exec( url )?.[ 1 ] ?? "";
    },
    api: {
      async get<T>( path: string ): Promise<T> {
        urls.push( path );
        const status = /to_status=([a-z_]+)/.exec( path )?.[ 1 ] ?? "";
        if ( opts.fail !== undefined && status in opts.fail ) throw opts.fail[ status ];
        if ( opts.body !== undefined && status in opts.body ) return opts.body[ status ] as T;
        const rows = opts.rows?.[ status ] ?? [];
        return { events: rows, count: rows.length } as T;
      },
    },
  };
}

function storeWith( api: { get<T>( p: string ): Promise<T> } ) {
  return createFinishedTasksStore( {
    bus   : createEventBusForTesting(),
    api,
    nowFn : () => NOW,
  } );
}

// ---------------------------------------------------------------------------
// The door — ruling R5
// ---------------------------------------------------------------------------

test( "🔴 THE DOOR IS /api/tasks/events, NOT /api/tasks — ruling R5", () => {
  // Asserted on the CONSTANT as well as on the traffic below, because the
  // constant is what a careless edit changes and the traffic assertion alone
  // would still pass if somebody pointed it at /api/tasks/events/../tasks.
  assert.equal( FINISHED_TASKS_ENDPOINT, "/api/tasks/events" );
} );

test( "one call PER STATUS, all three every poll, each carrying to_status + since + limit", async () => {
  const f = fakeApi();
  await storeWith( f.api ).refresh();

  assert.equal( f.urls.length, 3, "all three statuses are fetched every poll — a pill toggle must not need a round trip" );
  assert.deepEqual( f.urls.map( f.statusOf ), [ ...FINISHED_STATUSES ] );
  for ( const url of f.urls ) {
    assert.ok( url.startsWith( `${ FINISHED_TASKS_ENDPOINT }?` ),
      `a call went somewhere other than the ruled door: ${ url }` );
    assert.ok( url.includes( "since=" ), `no window on the wire: ${ url }` );
    assert.ok( url.includes( "limit=500" ), `no page cap on the wire: ${ url }` );
    assert.ok( !/\/api\/tasks\?/.test( url ), `this is the /api/tasks door: ${ url }` );
  }
} );

test( "the WINDOW reaches the wire in HOURS-from-now, converted from the slider's days", async () => {
  const f     = fakeApi();
  const store = storeWith( f.api );

  await store.refresh();
  assert.ok( f.urls[ 0 ]!.includes( encodeURIComponent( "2026-09-06T20:00:00.000Z" ) ),
    "a 1-day window must ask for the instant 24h back" );

  store.setWindowDays( 14 );
  f.urls.length = 0;
  await store.refresh();
  assert.ok( f.urls[ 0 ]!.includes( encodeURIComponent( "2026-08-24T20:00:00.000Z" ) ),
    "a 14-day window must ask for the instant 14 days back — a x24 dropped anywhere gives 14 HOURS" );
} );

test( "setWindowDays clamps, so a broken slider cannot put a bad instant on the wire", async () => {
  const f     = fakeApi();
  const store = storeWith( f.api );
  store.setWindowDays( 0 );
  assert.equal( store.windowDays(), 1 );
  store.setWindowDays( 900 );
  assert.equal( store.windowDays(), 14 );
} );

// ---------------------------------------------------------------------------
// The cache — the absent/empty distinction the whole pane turns on
// ---------------------------------------------------------------------------

test( "a successful poll caches per status, and measuredStatuses names all three", async () => {
  const f = fakeApi( { rows: { done: [ ev( 1, "done" ) ], dropped: [], wont_fix: [ ev( 2, "wont_fix" ) ] } } );
  const store = storeWith( f.api );
  await store.refresh();

  assert.deepEqual( [ ...store.measuredStatuses() ], [ "done", "dropped", "wont_fix" ] );
  assert.equal( store.eventsByStatus().done?.length, 1 );
  assert.equal( store.eventsByStatus().dropped?.length, 0, "a MEASURED zero is an empty array, not an absent key" );
  assert.equal( store.error(), null );
} );

test( "🔴 A FAILED STATUS LEAVES ITS KEY ABSENT — NOT AN EMPTY ARRAY", async () => {
  // The distinction is the product. `[]` renders as "nothing reached dropped",
  // which is a CLAIM; a failed fetch has measured nothing and must say so.
  const f = fakeApi( { rows: { done: [ ev( 1, "done" ) ] }, fail: { dropped: Object.assign( new Error( "x" ), { status: 500 } ) } } );
  const store = storeWith( f.api );
  await store.refresh();

  assert.ok( "done" in store.eventsByStatus() );
  assert.ok( !( "dropped" in store.eventsByStatus() ),
    "a failed status must not be cached as an empty array — that is a measured zero it did not measure" );
  assert.deepEqual( [ ...store.measuredStatuses() ], [ "done", "wont_fix" ] );
} );

test( "🔴 ONE STATUS FAILING DOES NOT ABANDON THE OTHERS", async () => {
  // A throwing body that escaped the loop would leave every later status
  // unfetched, and the pane would report a total outage over one bad call.
  const f = fakeApi( { rows: { wont_fix: [ ev( 3, "wont_fix" ) ] }, fail: { done: new Error( "boom" ) } } );
  const store = storeWith( f.api );
  await store.refresh();

  assert.equal( f.urls.length, 3, "the loop must continue past a refusal" );
  assert.equal( store.eventsByStatus().wont_fix?.length, 1,
    "a status fetched AFTER the failing one must still land" );
} );

test( "a MALFORMED body leaves the key absent rather than defaulting to []", async () => {
  const f = fakeApi( { body: { done: { nonsense: true } } } );
  const store = storeWith( f.api );
  await store.refresh();
  assert.ok( !( "done" in store.eventsByStatus() ) );
  assert.match( String( store.error() ), /malformed/ );
} );

test( "the error message NAMES the status, so the partial sentinel can say what is missing", async () => {
  const cases: Array<[ unknown, RegExp ]> = [
    [ Object.assign( new Error( "u" ), { status: 401 } ), /sign-in required \(dropped\)/ ],
    [ Object.assign( new Error( "u" ), { status: 503 } ), /HTTP 503 \(dropped\)/ ],
    [ new Error( "socket hang up" ),                      /socket hang up \(dropped\)/ ],
  ];
  for ( const [ thrown, expected ] of cases ) {
    const store = storeWith( fakeApi( { fail: { dropped: thrown } } ).api );
    await store.refresh();
    assert.match( String( store.error() ), expected );
  }
} );

test( "a thrown NON-Error is still described — the message is not assumed to exist", async () => {
  // fetch layers throw strings and plain objects, not only Errors. A describer
  // that read `.message` unguarded would report "undefined (dropped)".
  const store = storeWith( fakeApi( { fail: { dropped: "connection reset" } } ).api );
  await store.refresh();
  assert.match( String( store.error() ), /connection reset \(dropped\)/ );
} );

test( "the FIRST failure is reported — a later success must not erase it", async () => {
  const f = fakeApi( { fail: { done: Object.assign( new Error( "u" ), { status: 500 } ) } } );
  const store = storeWith( f.api );
  await store.refresh();
  assert.match( String( store.error() ), /\(done\)/ );
} );

test( "a clean poll after a failed one CLEARS the error and refills the absent key", async () => {
  // The cache is swapped wholesale, so a recovered status must stop reading as
  // unmeasured — a stale absent key would keep the pane on "partial" forever.
  let broken = true;
  const store = storeWith( {
    async get<T>( path: string ): Promise<T> {
      const status = /to_status=([a-z_]+)/.exec( path )?.[ 1 ] ?? "";
      if ( broken && status === "dropped" ) throw new Error( "down" );
      return { events: [], count: 0 } as T;
    },
  } );
  await store.refresh();
  assert.notEqual( store.error(), null );
  assert.ok( !( "dropped" in store.eventsByStatus() ) );

  broken = false;
  await store.refresh();
  assert.equal( store.error(), null );
  assert.ok( "dropped" in store.eventsByStatus() );
} );

// ---------------------------------------------------------------------------
// Emission + timer
// ---------------------------------------------------------------------------

test( "a resolved poll emits store_finished_tasks_changed with stampUpdated true", async () => {
  const bus  = createEventBusForTesting();
  const seen : Array<{ stampUpdated: boolean }> = [];
  bus.on<{ stampUpdated: boolean }>( "store_finished_tasks_changed", ( e ) => seen.push( e.payload ) );

  const store = createFinishedTasksStore( { bus, api: fakeApi().api, nowFn: () => NOW } );
  await store.refresh();

  assert.equal( seen.length, 1 );
  assert.deepEqual( seen[ 0 ], { stampUpdated: true } );
} );

test( "🔴 IT EMITS ITS OWN EVENT, NOT THE TASK LIST'S", async () => {
  // A shared signal would re-stamp one pane's "updated" label on the other
  // pane's fetch — two panes claiming freshness neither of them measured.
  const bus = createEventBusForTesting();
  const other: string[] = [];
  for ( const t of [ "store_task_list_changed", "store_fleet_status_changed", "store_holding_area_changed" ] ) {
    bus.on( t as never, () => other.push( t ) );
  }
  await createFinishedTasksStore( { bus, api: fakeApi().api, nowFn: () => NOW } ).refresh();
  assert.deepEqual( other, [], "this store emitted another pane's event" );
} );

test( "an in-flight refresh is not re-entered — a manual click on a tick cannot double-fetch", async () => {
  let release: () => void = () => {};
  const gate = new Promise<void>( ( r ) => { release = r; } );
  const urls: string[] = [];
  const store = storeWith( {
    async get<T>( path: string ): Promise<T> {
      urls.push( path );
      await gate;
      return { events: [], count: 0 } as T;
    },
  } );

  const first  = store.refresh();
  const second = store.refresh();     // must be a no-op while the first is out
  release();
  await Promise.all( [ first, second ] );

  assert.equal( urls.length, 3, "the second refresh re-entered and doubled the traffic" );
} );

test( "startPolling fires ONE immediate refresh then schedules the 60s interval; stopPolling clears it", async () => {
  const f = fakeApi();
  const scheduled: Array<{ ms: number }> = [];
  const cleared  : number[] = [];
  const store = createFinishedTasksStore( {
    bus : createEventBusForTesting(),
    api : f.api,
    nowFn : () => NOW,
    setIntervalFn   : ( _cb, ms ) => { scheduled.push( { ms } ); return 42; },
    clearIntervalFn : ( h ) => { cleared.push( h ); },
  } );

  store.startPolling();
  await new Promise( ( r ) => setImmediate( r ) );
  assert.equal( f.urls.length, 3, "startPolling must fire an immediate refresh, not wait 60s for the first paint" );
  assert.deepEqual( scheduled, [ { ms: FINISHED_TASKS_POLL_INTERVAL_MS } ] );

  store.stopPolling();
  assert.deepEqual( cleared, [ 42 ] );
  store.stopPolling();
  assert.deepEqual( cleared, [ 42 ], "stopPolling must be idempotent" );
} );

test( "the scheduled tick actually refreshes — the callback is wired, not merely registered", async () => {
  const f = fakeApi();
  let tick: ( () => void ) | null = null;
  const store = createFinishedTasksStore( {
    bus : createEventBusForTesting(), api : f.api, nowFn : () => NOW,
    setIntervalFn   : ( cb ) => { tick = cb; return 1; },
    clearIntervalFn : () => {},
  } );
  store.startPolling();
  await new Promise( ( r ) => setImmediate( r ) );
  f.urls.length = 0;

  assert.notEqual( tick, null );
  ( tick as unknown as () => void )();
  await new Promise( ( r ) => setImmediate( r ) );
  assert.equal( f.urls.length, 3, "the interval callback does not reach refresh()" );
  store.stopPolling();
} );

test( "startPolling twice clears the first handle — no orphaned timer", async () => {
  const cleared: number[] = [];
  let next = 1;
  const store = createFinishedTasksStore( {
    bus : createEventBusForTesting(), api : fakeApi().api, nowFn : () => NOW,
    setIntervalFn   : () => next++,
    clearIntervalFn : ( h ) => { cleared.push( h ); },
  } );
  store.startPolling();
  store.startPolling();
  await new Promise( ( r ) => setImmediate( r ) );
  assert.deepEqual( cleared, [ 1 ], "a second startPolling left the first interval running" );
  store.stopPolling();
} );
