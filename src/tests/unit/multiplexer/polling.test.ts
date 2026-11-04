// polling — createPushPoller and resolveRuntimeDefaults, the helpers the stores share.
//
// Run: npx tsx --test src/tests/unit/multiplexer/polling.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createPushPoller, resolveRuntimeDefaults } from "../../../lupin_app/static/js/multiplexer/stores/polling";

/** A poller wired to recording fakes; `calls` is the ordered log of everything it did. */
function rig() {
  const bus   = createEventBusForTesting();
  const calls : string[] = [];
  const timers = new Map<number, { cb: () => void; ms: number }>();
  let nextHandle = 1;
  const poller = createPushPoller( {
    bus,
    intervalMs     : 4321,
    setIntervalFn  : ( cb, ms ) => { const h = nextHandle++; timers.set( h, { cb, ms } ); calls.push( `set:${ h }:${ ms }` ); return h; },
    clearIntervalFn: ( h ) => { timers.delete( h ); calls.push( `clear:${ h }` ); },
    refresh          : async () => { calls.push( "refresh" ); },
    refreshAfterWrite: async () => { calls.push( "after-write" ); },
  } );
  const push = (): void => bus.emit( { type: "task_store_changed", payload: { count: 1 } } as never );
  return { poller, calls, timers, push };
}

test( "start refreshes once now, arms the interval at intervalMs, and nothing else", () => {
  const { poller, calls } = rig();
  poller.start();
  assert.deepEqual( calls, [ "refresh", "set:1:4321" ] );
});

test( "the timer calls refresh, never refreshAfterWrite", () => {
  const { poller, calls, timers } = rig();
  poller.start();
  calls.length = 0;
  timers.get( 1 )!.cb();
  assert.deepEqual( calls, [ "refresh" ] );
});

test( "a task_store_changed push calls refreshAfterWrite, never refresh", () => {
  const { poller, calls, push } = rig();
  poller.start();
  calls.length = 0;
  push();
  assert.deepEqual( calls, [ "after-write" ] );
});

test( "stop clears the interval and silences the push", () => {
  const { poller, calls, push } = rig();
  poller.start();
  calls.length = 0;
  poller.stop();
  push();
  assert.deepEqual( calls, [ "clear:1" ] );
});

test( "stop before start, and a second stop, do nothing", () => {
  const { poller, calls } = rig();
  poller.stop();
  poller.start();
  poller.stop();
  poller.stop();
  assert.deepEqual( calls, [ "refresh", "set:1:4321", "clear:1" ] );
});

test( "start twice restarts cleanly: one timer, one subscription", () => {
  const { poller, calls, timers, push } = rig();
  poller.start();
  poller.start();
  assert.deepEqual( calls, [ "refresh", "set:1:4321", "clear:1", "refresh", "set:2:4321" ] );
  assert.deepEqual( [ ...timers.keys() ], [ 2 ] );
  calls.length = 0;
  push();
  assert.deepEqual( calls, [ "after-write" ] );
});

test( "resolveRuntimeDefaults hands back each injected hook untouched", () => {
  const nowFn = () => 7, setIntervalFn = () => 1, clearIntervalFn = () => {};
  const out = resolveRuntimeDefaults( { nowFn, setIntervalFn, clearIntervalFn } );
  assert.equal( out.nowFn, nowFn );
  assert.equal( out.setIntervalFn, setIntervalFn );
  assert.equal( out.clearIntervalFn, clearIntervalFn );
});

test( "resolveRuntimeDefaults fills the runtime clock and timers when none are given", () => {
  const out = resolveRuntimeDefaults( {} );
  const before = Date.now();
  const now    = out.nowFn();
  assert.ok( now >= before && now <= Date.now() );
  let fired = 0;
  const handle = out.setIntervalFn( () => { fired++; }, 1_000_000 );
  assert.ok( handle !== undefined && handle !== null );
  out.clearIntervalFn( handle );
  assert.equal( fired, 0 );
});
