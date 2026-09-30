// FlowRatioStore (row c1bb2be7, build item A-2 #8) — the Holding Area's flow-ratio gate:
// the tick's reads and retries, and every outcome of the three writes. The five legacy
// defects this store fixes each have a test here that names its number.

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createFlowRatioStore,
  FLOW_RATIO_ENDPOINT,
  FLOW_RATIO_POLL_INTERVAL_MS,
  FLOW_RATIO_SETTINGS_ENDPOINT,
  MANAGER_PULL_ENDPOINT,
  type FlowRatioApiClient,
} from "../../../lupin_app/static/js/multiplexer/stores/FlowRatioStore";

const RATIO    = { created: 5, closed: 4, ratio: 1.25, window_hours: 24, allow_below: 1 };
const SETTINGS = { allow_below: 1, window_hours: 24, window_source: "config", threshold_source: "config" };
const PULL     = { disabled: true, source: "config" };

function httpError( status: number ): Error & { status: number } {
  const e = new Error( `HTTP ${status}` ) as Error & { status: number };
  e.status = status;
  return e;
}

type Answer = unknown | ( () => unknown );

/** A fake api whose answers are set per endpoint and method; a thrown Error is a rejection. */
function makeApi( answers: Record<string, Answer> = {} ) {
  const calls: string[] = [];
  const table: Record<string, Answer> = {
    [ `GET ${FLOW_RATIO_ENDPOINT}` ]          : RATIO,
    [ `GET ${FLOW_RATIO_SETTINGS_ENDPOINT}` ] : SETTINGS,
    [ `GET ${MANAGER_PULL_ENDPOINT}` ]        : PULL,
    ...answers,
  };
  const answer = async ( key: string ): Promise<never> => {
    calls.push( key );
    let a = table[ key ];
    if ( typeof a === "function" ) a = ( a as () => unknown )();
    if ( a instanceof Error ) throw a;
    return a as never;
  };
  const api: FlowRatioApiClient = {
    get    : ( path ) => answer( `GET ${path}` ),
    patch  : ( path, body ) => answer( `PATCH ${path} ${JSON.stringify( body )}` ),
    delete : ( path ) => answer( `DELETE ${path}` ),
  };
  return { api, calls, table };
}

function makeStore( api: FlowRatioApiClient ) {
  const bus    = createEventBusForTesting();
  const errors : string[] = [];
  let emits = 0;
  bus.on( "store_flow_ratio_changed", () => { emits += 1; } );
  const store = createFlowRatioStore( { bus, api, nowFn: () => 0, errorFn: ( m ) => errors.push( m ) } );
  return { store, errors, emits: () => emits };
}

test( "a tick reads the ratio, then the settings and the manager-pull state, and emits once", async () => {
  const ctx = makeApi();
  const { store, emits } = makeStore( ctx.api );
  assert.equal( store.ratio(), null );
  await store.refresh();
  assert.deepEqual( ctx.calls, [ `GET ${FLOW_RATIO_ENDPOINT}`, `GET ${FLOW_RATIO_SETTINGS_ENDPOINT}`, `GET ${MANAGER_PULL_ENDPOINT}` ] );
  assert.deepEqual( store.ratio(), RATIO );
  assert.deepEqual( store.settings(), SETTINGS );
  assert.deepEqual( store.managerPull(), PULL );
  assert.equal( emits(), 1 );
} );

test( "once usable, the settings and the pull are NOT re-read by the tick, so no slider moves under a finger", async () => {
  const ctx = makeApi();
  const { store } = makeStore( ctx.api );
  await store.refresh();
  ctx.calls.length = 0;
  await store.refresh();
  assert.deepEqual( ctx.calls, [ `GET ${FLOW_RATIO_ENDPOINT}` ] );
} );

test( "defects 4 and 6 fixed: an unusable read is retried on the next tick", async () => {
  const ctx = makeApi( {
    [ `GET ${FLOW_RATIO_SETTINGS_ENDPOINT}` ] : httpError( 503 ),
    [ `GET ${MANAGER_PULL_ENDPOINT}` ]        : new Error( "offline" ),
    [ `GET ${FLOW_RATIO_ENDPOINT}` ]          : httpError( 500 ),
  } );
  const { store, errors } = makeStore( ctx.api );
  await store.refresh();
  assert.equal( store.ratio(), null );
  assert.equal( store.settings(), null );
  assert.equal( store.managerPull(), null );
  assert.deepEqual( errors, [
    "Flow ratio unavailable: Error: HTTP 500",
    "Flow ratio settings unavailable: Error: HTTP 503",
    "Manager-pull read failed: Error: offline",
  ] );

  ctx.table[ `GET ${FLOW_RATIO_SETTINGS_ENDPOINT}` ] = { allow_below: 1 };   // readable but unusable
  ctx.table[ `GET ${MANAGER_PULL_ENDPOINT}` ]        = PULL;
  ctx.calls.length = 0;
  await store.refresh();
  assert.equal( ctx.calls.length, 3, "both retried" );
  assert.deepEqual( store.managerPull(), PULL );

  ctx.calls.length = 0;
  await store.refresh();
  assert.ok( ctx.calls.includes( `GET ${FLOW_RATIO_SETTINGS_ENDPOINT}` ), "unusable settings are retried too" );
  assert.ok( !ctx.calls.includes( `GET ${MANAGER_PULL_ENDPOINT}` ), "a read pull is not" );
} );

test( "a refresh landing on a refresh in flight does not double-fetch", async () => {
  let release!: ( v: unknown ) => void;
  const ctx = makeApi( { [ `GET ${FLOW_RATIO_ENDPOINT}` ]: () => new Promise( ( r ) => { release = r; } ) } );
  const { store } = makeStore( ctx.api );
  const first = store.refresh();
  await store.refresh();
  assert.equal( ctx.calls.length, 1 );
  release( RATIO );
  await first;
  assert.equal( ctx.calls.length, 3 );
} );

test( "a settings save PATCHes the body, keeps the server's answer, then re-reads the ratio", async () => {
  const answer = { ...SETTINGS, allow_below: 0.7, threshold_source: "override" };
  const ctx = makeApi( { [ `PATCH ${FLOW_RATIO_SETTINGS_ENDPOINT} {"allow_below":0.7}` ]: answer } );
  const { store, emits } = makeStore( ctx.api );
  await store.saveSettings( { allow_below: 0.7 } );
  assert.deepEqual( ctx.calls, [ `PATCH ${FLOW_RATIO_SETTINGS_ENDPOINT} {"allow_below":0.7}`, `GET ${FLOW_RATIO_ENDPOINT}` ] );
  assert.deepEqual( store.settings(), answer );
  assert.equal( store.controlsMessage(), null, "a success leaves the source line to speak" );
  assert.equal( emits(), 1 );
} );

test( "defects 1, 2 and 3 fixed: a refused or failed save keeps its message, re-reads the settings AND the ratio", async () => {
  for ( const [ err, message ] of [
    [ httpError( 403 ), "not saved — admin only" ],
    [ httpError( 422 ), "not saved (HTTP 422)" ],
    [ new Error( "offline" ), "not saved (network)" ],   // legacy repainted nothing here (defect 2)
  ] as const ) {
    const ctx = makeApi( { [ `PATCH ${FLOW_RATIO_SETTINGS_ENDPOINT} {"window_hours":168}` ]: err } );
    const { store } = makeStore( ctx.api );
    await store.saveSettings( { window_hours: 168 } );
    assert.deepEqual( ctx.calls.slice( 1 ), [ `GET ${FLOW_RATIO_SETTINGS_ENDPOINT}`, `GET ${FLOW_RATIO_ENDPOINT}` ], message );
    assert.equal( store.controlsMessage(), message, "the refusal is not overwritten by the re-read (defect 1)" );
    assert.deepEqual( store.settings(), SETTINGS );
  }
} );

test( "the next write clears the previous write's message", async () => {
  const ctx = makeApi( { [ `PATCH ${FLOW_RATIO_SETTINGS_ENDPOINT} {"allow_below":2}` ]: httpError( 403 ) } );
  const { store } = makeStore( ctx.api );
  await store.saveSettings( { allow_below: 2 } );
  assert.equal( store.controlsMessage(), "not saved — admin only" );
  ctx.table[ `PATCH ${FLOW_RATIO_SETTINGS_ENDPOINT} {"allow_below":1}` ] = SETTINGS;
  await store.saveSettings( { allow_below: 1 } );
  assert.equal( store.controlsMessage(), null );
} );

test( "the manager-pull save reports FROZEN / allowed, and a refusal re-reads the state", async () => {
  const ctx = makeApi( {
    [ `PATCH ${MANAGER_PULL_ENDPOINT} {"disabled":true}` ]  : { disabled: true, source: "override" },
    [ `PATCH ${MANAGER_PULL_ENDPOINT} {"disabled":false}` ] : { disabled: false, source: "override" },
  } );
  const { store } = makeStore( ctx.api );
  await store.saveManagerPull( true );
  assert.equal( store.controlsMessage(), "manager pull FROZEN" );
  await store.saveManagerPull( false );
  assert.equal( store.controlsMessage(), "manager pull allowed" );
  assert.deepEqual( store.managerPull(), { disabled: false, source: "override" } );

  ctx.table[ `PATCH ${MANAGER_PULL_ENDPOINT} {"disabled":true}` ] = httpError( 403 );
  ctx.calls.length = 0;
  await store.saveManagerPull( true );
  assert.equal( store.controlsMessage(), "not saved — admin only" );
  assert.deepEqual( ctx.calls, [ `PATCH ${MANAGER_PULL_ENDPOINT} {"disabled":true}`, `GET ${MANAGER_PULL_ENDPOINT}` ] );
  assert.deepEqual( store.managerPull(), PULL, "the box goes back to what the server holds" );
} );

test( "Reset DELETEs, keeps the answer and re-reads the ratio; a refusal says so; a network failure is logged", async () => {
  const ctx = makeApi( { [ `DELETE ${FLOW_RATIO_SETTINGS_ENDPOINT}` ]: SETTINGS } );
  const { store, errors } = makeStore( ctx.api );
  await store.resetSettings();
  assert.deepEqual( ctx.calls, [ `DELETE ${FLOW_RATIO_SETTINGS_ENDPOINT}`, `GET ${FLOW_RATIO_ENDPOINT}` ] );
  assert.deepEqual( store.settings(), SETTINGS );
  assert.equal( store.controlsMessage(), null );

  ctx.table[ `DELETE ${FLOW_RATIO_SETTINGS_ENDPOINT}` ] = httpError( 403 );
  await store.resetSettings();
  assert.equal( store.controlsMessage(), "not reset — admin only" );
  ctx.table[ `DELETE ${FLOW_RATIO_SETTINGS_ENDPOINT}` ] = httpError( 500 );
  await store.resetSettings();
  assert.equal( store.controlsMessage(), "not reset (HTTP 500)" );

  ctx.table[ `DELETE ${FLOW_RATIO_SETTINGS_ENDPOINT}` ] = new Error( "offline" );
  await store.resetSettings();
  assert.equal( store.controlsMessage(), null, "legacy's reset only logs a network failure" );
  assert.deepEqual( errors, [ "Flow ratio settings reset failed: Error: offline" ] );
} );

test( "polling: one immediate tick, then every 60 s; stopping clears it; starting again replaces it", async () => {
  const ctx = makeApi();
  const scheduled: Array<{ cb: () => void; ms: number }> = [];
  const cleared: number[] = [];
  const bus = createEventBusForTesting();
  const store = createFlowRatioStore( {
    bus, api: ctx.api, nowFn: () => 0, errorFn: () => {},
    setIntervalFn   : ( cb, ms ) => scheduled.push( { cb, ms } ),
    clearIntervalFn : ( h ) => { cleared.push( h ); },
  } );
  store.startPolling();
  await new Promise( ( r ) => setTimeout( r, 0 ) );
  assert.equal( ctx.calls[ 0 ], `GET ${FLOW_RATIO_ENDPOINT}` );
  assert.equal( scheduled[ 0 ]!.ms, FLOW_RATIO_POLL_INTERVAL_MS );
  ctx.calls.length = 0;
  scheduled[ 0 ]!.cb();
  await new Promise( ( r ) => setTimeout( r, 0 ) );
  assert.deepEqual( ctx.calls, [ `GET ${FLOW_RATIO_ENDPOINT}` ] );
  store.startPolling();
  assert.deepEqual( cleared, [ 1 ], "the first interval is cleared before the second" );
  store.stopPolling();
  store.stopPolling();
  assert.deepEqual( cleared, [ 1, 2 ], "stopping twice clears once" );
} );

// The four constants every other assertion in this file is written over, pinned to
// literals. Without this, both sides of those assertions derive from the same import:
// the fake api is KEYED by `GET ${FLOW_RATIO_ENDPOINT}` and then ASSERTED against
// `GET ${FLOW_RATIO_ENDPOINT}`, so retargeting the constant to
// "/api/COMPLETELY-WRONG-PATH" leaves every one of them green. A tautology wearing an
// assertion's clothes; pinning one side is what makes the rest of the file discriminate.
// Legacy's own paths and tick, from notifications.js: the ratio read at
// fetchFlowRatio (notifications.js:11443), the settings read and write at
// fetchFlowRatioSettings (:11563) and saveFlowRatioSettings (:11649), manager-pull at
// fetchManagerPullDisabled (:11693), and the shared 60 s task-list tick.
// Found by Maya 🌻 in review, 2026-09-19.
test( "the endpoints and the poll interval are legacy's, not whatever the module says", () => {
  assert.equal( FLOW_RATIO_ENDPOINT,          "/api/tasks/flow-ratio" );
  assert.equal( FLOW_RATIO_SETTINGS_ENDPOINT, "/api/tasks/flow-ratio/settings" );
  assert.equal( MANAGER_PULL_ENDPOINT,        "/api/tasks/manager-pull" );
  assert.equal( FLOW_RATIO_POLL_INTERVAL_MS,  60000 );
} );
