// Multiplexer — a FAILED active-sessions fetch must not read as an empty roster (Krishna, 2026-10-07).
// Run via `npx tsx --test src/tests/unit/multiplexer/render/broadcast_failed_roster_is_not_an_empty_roster.test.ts`.
//
// Enters at the layer the incident enters: the REAL BroadcastCardRenderer, the REAL BroadcastStore, the
// REAL AckStore and the REAL BroadcastAckTallyRenderer, with only the HTTP edge (api.get) failing.
// The card's catch path signals the tally; the tally must then say the roster is unknown, never
// "All 0 sessions acknowledged".

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

test( "a failed active-sessions fetch leaves the tally saying the roster is unknown, not 'All 0 sessions acknowledged'", async () => {
  const bus      = createEventBusForTesting();
  const storage  = createStorageServiceForTesting();
  const ackStore = createAckStore( { bus } );
  const store    = createBroadcastStore( { storage } );
  tally = createBroadcastAckTallyRenderer( { eventBus: bus, ackStore, broadcastStore: store } );
  const api = {
    get   : <T>( _p: string ): Promise<T> => Promise.reject( new Error( "network down" ) ),
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
  await new Promise( ( r ) => setTimeout( r, 0 ) );          // the initial fetch has rejected and the card's catch has run

  tally.track( BCAST );                                       // a broadcast is being counted (sent, or restored after a reload)
  const summary = document.querySelector( '[data-testid="broadcast-ack-summary"]' )?.textContent ?? "";
  assert.ok( summary !== "", "the tally rendered a summary line" );
  assert.doesNotMatch( summary, /All 0 session/, `a failed roster read must not print a complete tally; got: ${ summary }` );
  assert.match( summary, /recipient list|unknown|could not/i, `the summary must say the roster is not known; got: ${ summary }` );
} );
