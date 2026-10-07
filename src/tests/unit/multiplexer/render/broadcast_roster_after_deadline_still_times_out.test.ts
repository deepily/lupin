// Multiplexer — a roster that lands AFTER the tally's deadline must still end in a timed-out tally (Tiberius, 2026-10-07).
// Run via `npx tsx --test src/tests/unit/multiplexer/render/broadcast_roster_after_deadline_still_times_out.test.ts`.
//
// Real BroadcastCardRenderer + BroadcastStore + AckStore + BroadcastAckTallyRenderer; only api.get is held open,
// and the tally's timer is captured so the test fires the deadline by hand.

import { test, before, afterEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createStorageServiceForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/StorageService";
import { createAckStore } from "../../../../lupin_app/static/js/multiplexer/stores/AckStore";
import { createBroadcastStore } from "../../../../lupin_app/static/js/multiplexer/stores/BroadcastStore";
import { createBroadcastCardRenderer } from "../../../../lupin_app/static/js/multiplexer/render/BroadcastCardRenderer";
import { createBroadcastAckTallyRenderer } from "../../../../lupin_app/static/js/multiplexer/render/BroadcastAckTallyRenderer";
import type { BroadcastAckTallyRenderer } from "../../../../lupin_app/static/js/multiplexer/render/BroadcastAckTallyRenderer";
import type { BroadcastCardRenderer, BroadcastCardApiClient } from "../../../../lupin_app/static/js/multiplexer/render/BroadcastCardRenderer";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

const BCAST = "22222222-bbbb-4ccc-8ddd-333333333333";

let card  : BroadcastCardRenderer | null     = null;
let tally : BroadcastAckTallyRenderer | null = null;

afterEach( () => {
  if ( card !== null )  { card.unmount();  card = null; }
  if ( tally !== null ) { tally.unmount(); tally = null; }
  document.body.replaceChildren();
} );

function build( rosterReady: boolean ) {
  const bus      = createEventBusForTesting();
  const storage  = createStorageServiceForTesting();
  const ackStore = createAckStore( { bus } );
  const store    = createBroadcastStore( { storage } );
  const deadlines: ( () => void )[] = [];
  tally = createBroadcastAckTallyRenderer( {
    eventBus: bus, ackStore, broadcastStore: store,
    setTimeoutFn: ( cb: () => void ) => { deadlines.push( cb ); return deadlines.length; },
    clearTimeoutFn: () => {},
  } );
  let release: () => void = () => {};
  const gate = new Promise<void>( ( r ) => { release = r; } );
  const api = {
    get   : async <T>( _p: string ): Promise<T> => {
      if ( !rosterReady ) await gate;
      return { sessions: [ { session_id: "s1" }, { session_id: "s2" } ] } as unknown as T;
    },
    broadcastToCcSessions: () => Promise.reject( new Error( "not used" ) ),
  } as unknown as BroadcastCardApiClient;
  card = createBroadcastCardRenderer( {
    eventBus: bus, store, api, getAuthToken: () => "tok",
    recorder: { startRecording: () => Promise.resolve(), stopRecording: () => Promise.resolve() },
    recipientsRefreshDebounceMs: 0, ackTally: tally,
  } );
  const root = document.createElement( "div" );
  document.body.appendChild( root );
  card.mount( root );
  return { tally, deadlines, release };
}

const panelAttr = ( name: string ) => document.querySelector( '[data-testid="broadcast-ack-tally"]' )?.getAttribute( name ) ?? null;

test( "control: a roster that is already known when the deadline fires times out", async () => {
  const { tally, deadlines } = build( true );
  await new Promise( ( r ) => setTimeout( r, 0 ) );
  tally.track( BCAST );
  assert.equal( deadlines.length, 1, "track armed one deadline" );
  deadlines[ 0 ]!();
  assert.equal( panelAttr( "data-timed-out" ), "true", "0 of 2 acknowledged at the deadline must be timed out" );
} );

test( "a roster that lands after the deadline still ends in a timed-out tally", async () => {
  const { tally, deadlines, release } = build( false );
  await new Promise( ( r ) => setTimeout( r, 0 ) );          // the fetch is still pending: roster unknown
  tally.track( BCAST );
  deadlines[ 0 ]!();                                          // the 5-minute deadline fires with the roster unknown
  release();                                                  // the roster lands late
  await new Promise( ( r ) => setTimeout( r, 10 ) );
  assert.equal( panelAttr( "data-expected" ), "2", "precondition: the late roster painted" );
  assert.equal( panelAttr( "data-timed-out" ), "true", "the deadline has passed with 0 of 2 acknowledged, so the tally must be timed out; nothing re-arms or re-checks it when the roster lands" );
} );
