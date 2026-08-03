// Multiplexer v0.1.9 — StripReconnectRehydrator unit tests.
// 100% lines/branches/functions per the Lupin-wide coverage mandate.
// Run via `npx tsx --test src/tests/unit/multiplexer/strip_reconnect_rehydrator.test.ts`.

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createStripReconnectRehydrator,
  STRIP_REHYDRATE_TRANSPORT,
  type StripRehydrateApiClient,
  type StripRehydrateStores,
} from "../../../lupin_app/static/js/multiplexer/stores/StripReconnectRehydrator";
import type {
  ConnectionState,
  ConnectionStateChangePayload,
} from "../../../lupin_app/static/js/multiplexer/shared/types";
import type { ServerSenderHydrationRecord } from "../../../lupin_app/static/js/multiplexer/stores/SessionStripStore";

// Drain microtasks + one macrotask so an async rehydrate fully settles (its
// in-flight guard resets in `finally`) before the next assertion.
const tick = (): Promise<void> => new Promise( ( resolve ) => setTimeout( resolve, 0 ) );

const RECORDS: ServerSenderHydrationRecord[] = [
  { sender_id: "s1", voice_persona: { name: "Tiffany", icon: "💍", color: "#FFD600", assigned_at: "2026-07-07T16:00:00+00:00" } },
];

// ---------------------------------------------------------------------------
// Fakes
// ---------------------------------------------------------------------------

interface ApiCtx {
  api      : StripRehydrateApiClient;
  getCalls : string[];
  setMode  : ( m: "good" | "throw" | "defer" ) => void;
  resolveDeferred: () => void;
}

function makeApi(): ApiCtx {
  const getCalls: string[] = [];
  let mode: "good" | "throw" | "defer" = "good";
  let releaseDeferred: () => void = () => {};
  const api: StripRehydrateApiClient = {
    get: async <T,>( path: string ): Promise<T> => {
      getCalls.push( path );
      if ( mode === "throw" ) throw new Error( "senders-visible fetch failed" );
      if ( mode === "defer" ) {
        await new Promise<void>( ( resolve ) => { releaseDeferred = resolve; } );
      }
      return RECORDS as T;
    },
  };
  return {
    api,
    getCalls,
    setMode          : ( m ) => { mode = m; },
    resolveDeferred  : () => releaseDeferred(),
  };
}

interface StoreCtx {
  stores      : StripRehydrateStores;
  stripReconcile: ServerSenderHydrationRecord[][];
  sendHydrate : ServerSenderHydrationRecord[][];
}

function makeStores(): StoreCtx {
  const stripReconcile: ServerSenderHydrationRecord[][] = [];
  const sendHydrate : ServerSenderHydrationRecord[][] = [];
  const stores: StripRehydrateStores = {
    sessionStrip : { reconcile: ( r ) => { stripReconcile.push( r as ServerSenderHydrationRecord[] ); } },
    senders      : { hydrate: ( r ) => { sendHydrate.push( r as ServerSenderHydrationRecord[] ); } },
  };
  return { stores, stripReconcile, sendHydrate };
}

function emitConn(
  bus: ReturnType<typeof createEventBusForTesting>,
  fields: { state: ConnectionState; prev: ConnectionState; transport?: string },
): void {
  const payload: ConnectionStateChangePayload = {
    state     : fields.state,
    prev      : fields.prev,
    attempts  : 0,
    transport : fields.transport ?? STRIP_REHYDRATE_TRANSPORT,
  };
  bus.emit<ConnectionStateChangePayload>( { type: "connection_state_change", payload, source: "test", ts: 0 } );
}

function setup( opts: { email?: string | null } = {} ) {
  const bus       = createEventBusForTesting();
  const apiCtx    = makeApi();
  const storeCtx  = makeStores();
  let email: string | null = opts.email === undefined ? "a+b@x.com" : opts.email;
  const rehydrator = createStripReconnectRehydrator( {
    bus,
    api      : apiCtx.api,
    stores   : storeCtx.stores,
    getEmail : () => email,
  } );
  return { bus, apiCtx, storeCtx, rehydrator, setEmail: ( e: string | null ) => { email = e; } };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test( "reconnect edge (queue, reconnecting->connected) re-hydrates both stores with the encoded path", async () => {
  const { bus, apiCtx, storeCtx } = setup( { email: "a+b@x.com" } );
  emitConn( bus, { state: "connected", prev: "reconnecting" } );
  await tick();
  assert.deepEqual( apiCtx.getCalls, [ "/api/notifications/senders-visible/a%2Bb%40x.com" ] );
  assert.equal( storeCtx.stripReconcile.length, 1 );
  assert.equal( storeCtx.sendHydrate.length, 1 );
  assert.deepEqual( storeCtx.stripReconcile[ 0 ], RECORDS );
  assert.deepEqual( storeCtx.sendHydrate[ 0 ], RECORDS );
} );

test( "ignores a non-queue transport reconnect (audio socket)", async () => {
  const { bus, apiCtx, storeCtx } = setup();
  emitConn( bus, { state: "connected", prev: "reconnecting", transport: "AudioTransport" } );
  await tick();
  assert.deepEqual( apiCtx.getCalls, [] );
  assert.equal( storeCtx.stripReconcile.length, 0 );
} );

test( "ignores a transition that is not INTO connected", async () => {
  const { bus, apiCtx } = setup();
  emitConn( bus, { state: "offline", prev: "connected" } );
  await tick();
  assert.deepEqual( apiCtx.getCalls, [] );
} );

test( "ignores the initial connect (connecting->connected, boot already hydrated)", async () => {
  const { bus, apiCtx } = setup();
  emitConn( bus, { state: "connected", prev: "connecting" } );
  await tick();
  assert.deepEqual( apiCtx.getCalls, [] );
} );

test( "skips when email is null", async () => {
  const { bus, apiCtx } = setup( { email: null } );
  emitConn( bus, { state: "connected", prev: "reconnecting" } );
  await tick();
  assert.deepEqual( apiCtx.getCalls, [] );
} );

test( "skips when email is empty string", async () => {
  const { bus, apiCtx } = setup( { email: "" } );
  emitConn( bus, { state: "connected", prev: "reconnecting" } );
  await tick();
  assert.deepEqual( apiCtx.getCalls, [] );
} );

test( "a failed fetch does not throw, does not hydrate, and resets in-flight for the next edge", async () => {
  const { bus, apiCtx, storeCtx } = setup();
  apiCtx.setMode( "throw" );
  emitConn( bus, { state: "connected", prev: "reconnecting" } );
  await tick();
  assert.equal( apiCtx.getCalls.length, 1 );
  assert.equal( storeCtx.stripReconcile.length, 0 );
  assert.equal( storeCtx.sendHydrate.length, 0 );

  // in-flight reset in finally → a subsequent good edge fetches + hydrates.
  apiCtx.setMode( "good" );
  emitConn( bus, { state: "connected", prev: "reconnecting" } );
  await tick();
  assert.equal( apiCtx.getCalls.length, 2 );
  assert.equal( storeCtx.stripReconcile.length, 1 );
} );

test( "debounces overlapping reconnect edges — only one fetch while a fetch is in flight", async () => {
  const { bus, apiCtx, storeCtx } = setup();
  apiCtx.setMode( "defer" );
  emitConn( bus, { state: "connected", prev: "reconnecting" } );  // starts the deferred fetch
  await tick();
  emitConn( bus, { state: "connected", prev: "reconnecting" } );  // dropped — in flight
  await tick();
  assert.equal( apiCtx.getCalls.length, 1 );

  apiCtx.resolveDeferred();
  await tick();
  assert.equal( storeCtx.stripReconcile.length, 1 );
  assert.equal( storeCtx.sendHydrate.length, 1 );

  // After settle, a fresh edge fetches again (guard released).
  apiCtx.setMode( "good" );
  emitConn( bus, { state: "connected", prev: "reconnecting" } );
  await tick();
  assert.equal( apiCtx.getCalls.length, 2 );
} );

test( "disposeForTesting detaches the listener — later edges are ignored", async () => {
  const { bus, apiCtx, rehydrator } = setup();
  rehydrator.disposeForTesting();
  emitConn( bus, { state: "connected", prev: "reconnecting" } );
  await tick();
  assert.deepEqual( apiCtx.getCalls, [] );
} );
