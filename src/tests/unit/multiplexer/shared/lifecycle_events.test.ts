// emitLifecycleEvent and attachLifecycleEvents build each page lifecycle event.
//
// Run: npx tsx --test src/tests/unit/multiplexer/shared/lifecycle_events.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";

import { attachLifecycleEvents, emitLifecycleEvent } from "../../../../lupin_app/static/js/multiplexer/shared/lifecycleEvents";
import type { EventBus } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";

function busDouble() {
  const events: Array<{ type: string; payload: unknown; source: string; ts: number }> = [];
  return { events, bus: { emit: ( e: { type: string; payload: unknown; source: string; ts: number } ) => { events.push( e ); } } as unknown as EventBus };
}

test( "an event carries the type, the caller's source and a payload holding the same time", () => {
  const { events, bus } = busDouble();
  emitLifecycleEvent( bus, "page_hidden", "boot" );
  assert.equal( events.length, 1 );
  assert.equal( events[ 0 ]!.type, "page_hidden" );
  assert.equal( events[ 0 ]!.source, "boot" );
  assert.deepEqual( events[ 0 ]!.payload, { ts: events[ 0 ]!.ts } );
} );

test( "bfcache: true adds the flag to the payload, and no extra leaves it out", () => {
  const { events, bus } = busDouble();
  emitLifecycleEvent( bus, "page_visible", "boot", { bfcache: true } );
  emitLifecycleEvent( bus, "page_visible", "boot", {} );
  assert.deepEqual( events[ 0 ]!.payload, { ts: events[ 0 ]!.ts, bfcache: true } );
  assert.deepEqual( events[ 1 ]!.payload, { ts: events[ 1 ]!.ts } );
} );

test( "attachLifecycleEvents turns visibility, online and offline into events", () => {
  const { events, bus } = busDouble();
  const handlers: Record<string, () => void> = {};
  const doc = { visibilityState: "hidden", addEventListener: ( t: string, h: () => void ) => { handlers[ t ] = h; } } as unknown as Document;
  const win = { addEventListener: ( t: string, h: () => void ) => { handlers[ t ] = h; } };
  attachLifecycleEvents( bus, doc, win, "consolePage" );
  handlers[ "visibilitychange" ]!();
  ( doc as { visibilityState: string } ).visibilityState = "visible";
  handlers[ "visibilitychange" ]!();
  handlers[ "online" ]!();
  handlers[ "offline" ]!();
  assert.deepEqual( events.map( ( e ) => e.type ), [ "page_hidden", "page_visible", "network_online", "network_offline" ] );
  assert.ok( events.every( ( e ) => e.source === "consolePage" ) );
} );
