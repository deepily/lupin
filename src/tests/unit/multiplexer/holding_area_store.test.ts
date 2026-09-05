// Holding-area card — HoldingAreaStore unit tests.
// 100% lines/branches/functions per the multiplexer coverage mandate.
//
// THE DEFECT THIS FILE EXISTS TO CATCH: the holding area reading the TASK
// LIST's query. Both are /api/tasks; only `status=not_approved` separates
// them, and that parameter is what takes held rows out of the server's
// invisible-status denylist. A store pointed at the wrong one renders a
// plausible, wrong pane — every row on the board instead of the held ones.

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createHoldingAreaStore,
  HOLDING_AREA_ENDPOINT,
  HOLDING_AREA_POLL_INTERVAL_MS,
  type HoldingAreaApiClient,
} from "../../../lupin_app/static/js/multiplexer/stores/HoldingAreaStore";
import { TASK_LIST_ENDPOINT } from "../../../lupin_app/static/js/multiplexer/stores/TaskListStore";
import type { TaskListComposite } from "../../../lupin_app/static/js/multiplexer/render/taskListModel";

const tick = (): Promise<void> => new Promise( ( r ) => setTimeout( r, 0 ) );

const GOOD: TaskListComposite = {
  tasks : [ { id: "1", title: "held", status: "not_approved", created_by: "amy 11111111" } ],
  count : 1,
};

interface Ctx {
  api   : HoldingAreaApiClient;
  calls : string[];
  mode  : { v: "good" | "throw401" | "throw500" };
}

function makeApi(): Ctx {
  const calls: string[] = [];
  const mode: Ctx[ "mode" ] = { v: "good" };
  const api: HoldingAreaApiClient = {
    get: async <T,>( path: string ): Promise<T> => {
      calls.push( path );
      if ( mode.v === "throw401" ) {
        const e = new Error( "401" ) as Error & { status: number }; e.status = 401; throw e;
      }
      if ( mode.v === "throw500" ) {
        const e = new Error( "500" ) as Error & { status: number }; e.status = 500; throw e;
      }
      return GOOD as unknown as T;
    },
  };
  return { api, calls, mode };
}

// ---------------------------------------------------------------- endpoint

test( "🔴 the endpoint is the HOLDING-AREA query, NOT the task list's", () => {
  assert.notEqual( HOLDING_AREA_ENDPOINT, TASK_LIST_ENDPOINT );
} );

test( "the endpoint names status=not_approved — the parameter that makes it work", () => {
  // Per the shared module's own docstring: naming a status explicitly takes the
  // row OUT of the server's invisible-status denylist. Drop it and the pane
  // silently shows nothing, because held rows are denied by default.
  assert.ok( HOLDING_AREA_ENDPOINT.includes( "status=not_approved" ) );
} );

test( "the endpoint carries NO hide_parked — a held row was never on the board", () => {
  assert.ok( !HOLDING_AREA_ENDPOINT.includes( "hide_parked" ) );
  // Positive control: the TASK LIST query DOES carry it, so this probe can see
  // the parameter when it is present.
  assert.ok( TASK_LIST_ENDPOINT.includes( "hide_parked" ) );
} );

test( "the poll interval matches fleet parity", () => {
  assert.equal( HOLDING_AREA_POLL_INTERVAL_MS, 60000 );
} );

// ---------------------------------------------------------------- refresh

test( "composite() is null before the first refresh", () => {
  const { api } = makeApi();
  const store = createHoldingAreaStore( { bus: createEventBusForTesting(), api } );
  assert.equal( store.composite(), null );
} );

test( "refresh caches the composite and hits the holding-area endpoint", async () => {
  const { api, calls } = makeApi();
  const store = createHoldingAreaStore( { bus: createEventBusForTesting(), api } );
  await store.refresh();
  assert.deepEqual( calls, [ HOLDING_AREA_ENDPOINT ] );
  assert.deepEqual( store.composite(), GOOD );
} );

test( "an injected endpoint overrides the default", async () => {
  const { api, calls } = makeApi();
  const store = createHoldingAreaStore( { bus: createEventBusForTesting(), api, endpoint: "/custom" } );
  await store.refresh();
  assert.deepEqual( calls, [ "/custom" ] );
} );

test( "a 401 caches the auth_required sentinel, never a throw", async () => {
  const { api, mode } = makeApi();
  mode.v = "throw401";
  const store = createHoldingAreaStore( { bus: createEventBusForTesting(), api } );
  await store.refresh();
  assert.deepEqual( store.composite(), { status: "auth_required" } );
} );

test( "a non-401 failure caches the unreachable sentinel with tasks null", async () => {
  const { api, mode } = makeApi();
  mode.v = "throw500";
  const store = createHoldingAreaStore( { bus: createEventBusForTesting(), api } );
  await store.refresh();
  assert.deepEqual( store.composite(), { status: "unreachable", tasks: null } );
} );

test( "an error with NO status field still degrades to unreachable", async () => {
  const api: HoldingAreaApiClient = { get: async () => { throw new Error( "network" ); } };
  const store = createHoldingAreaStore( { bus: createEventBusForTesting(), api } );
  await store.refresh();
  assert.deepEqual( store.composite(), { status: "unreachable", tasks: null } );
} );

// ---------------------------------------------------------------- events

test( "refresh emits store_holding_area_changed, NOT the task list's event", async () => {
  const bus = createEventBusForTesting();
  const seen: string[] = [];
  bus.on( "store_holding_area_changed", () => seen.push( "holding" ) );
  bus.on( "store_task_list_changed",    () => seen.push( "tasklist" ) );
  const { api } = makeApi();
  await createHoldingAreaStore( { bus, api } ).refresh();
  // A shared signal would repaint the task list on every holding-area poll and
  // re-stamp its "updated" time from a fetch that was not its own.
  assert.deepEqual( seen, [ "holding" ] );
} );

test( "the emitted payload stamps updated and names the store as source", async () => {
  const bus = createEventBusForTesting();
  let ev: { payload: { stampUpdated: boolean }; source: string; ts: number } | null = null;
  bus.on( "store_holding_area_changed", ( e ) => { ev = e as never; } );
  const { api } = makeApi();
  await createHoldingAreaStore( { bus, api, nowFn: () => 4242 } ).refresh();
  assert.deepEqual( ev!.payload, { stampUpdated: true } );
  assert.equal( ev!.source, "HoldingAreaStore" );
  assert.equal( ev!.ts, 4242 );
} );

// ---------------------------------------------------------------- debounce

test( "an in-flight refresh debounces a second call — ONE fetch, not two", async () => {
  // ⚠️ THE FIXTURE MUST ALWAYS SETTLE. An earlier version held the first fetch
  // on a promise released by hand. With the guard removed the second call
  // awaited that same promise, the test HUNG, and node reported "cancelled 5"
  // with rc=1 — which reads exactly like a kill and is a COULD-NOT-RUN. A
  // mutation that hangs the suite proves nothing in either direction, and node
  // prints `not ok` for cancelled tests too, so the usual grep over-reports.
  //
  // This version resolves on its own timer, so removing the guard produces a
  // real ASSERTION FAILURE (2 calls, not 1) rather than a hang.
  const calls: string[] = [];
  const api: HoldingAreaApiClient = {
    get: async <T,>( p: string ): Promise<T> => {
      calls.push( p );
      await new Promise<void>( ( r ) => setTimeout( r, 5 ) );
      return GOOD as unknown as T;
    },
  };
  const store = createHoldingAreaStore( { bus: createEventBusForTesting(), api } );
  const first  = store.refresh();
  const second = store.refresh();      // lands mid-flight — must do nothing
  await Promise.all( [ first, second ] );
  assert.equal( calls.length, 1, "a second refresh landing mid-flight must not re-fetch" );
} );

// ---------------------------------------------------------------- polling

test( "startPolling refreshes ONCE immediately, then arms the interval", async () => {
  const { api, calls } = makeApi();
  let armed: { cb: () => void; ms: number } | null = null;
  const store = createHoldingAreaStore( {
    bus: createEventBusForTesting(), api,
    setIntervalFn: ( cb, ms ) => { armed = { cb, ms }; return 7; },
    clearIntervalFn: () => { /* noop */ },
  } );
  store.startPolling();
  await tick();
  assert.equal( calls.length, 1 );
  assert.equal( armed!.ms, HOLDING_AREA_POLL_INTERVAL_MS );
  armed!.cb();                       // the interval firing
  await tick();
  assert.equal( calls.length, 2 );
} );

test( "startPolling is IDEMPOTENT — it clears the prior handle before arming", () => {
  const { api } = makeApi();
  const cleared: number[] = [];
  let next = 100;
  const store = createHoldingAreaStore( {
    bus: createEventBusForTesting(), api,
    setIntervalFn: () => next++,
    clearIntervalFn: ( h ) => cleared.push( h ),
  } );
  store.startPolling();
  store.startPolling();
  // The second start must clear the first handle, or the pane double-polls
  // forever and nothing visible says so.
  assert.deepEqual( cleared, [ 100 ] );
} );

test( "stopPolling clears the handle and is idempotent", () => {
  const { api } = makeApi();
  const cleared: number[] = [];
  const store = createHoldingAreaStore( {
    bus: createEventBusForTesting(), api,
    setIntervalFn: () => 55,
    clearIntervalFn: ( h ) => cleared.push( h ),
  } );
  store.startPolling();
  store.stopPolling();
  store.stopPolling();               // second call must be a no-op
  assert.deepEqual( cleared, [ 55 ] );
} );

test( "stopPolling before any start is a no-op", () => {
  const { api } = makeApi();
  const cleared: number[] = [];
  const store = createHoldingAreaStore( {
    bus: createEventBusForTesting(), api,
    setIntervalFn: () => 1,
    clearIntervalFn: ( h ) => cleared.push( h ),
  } );
  store.stopPolling();
  assert.deepEqual( cleared, [] );
} );
