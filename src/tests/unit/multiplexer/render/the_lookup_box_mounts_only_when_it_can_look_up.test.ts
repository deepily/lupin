// The task-list header offers a ticket-lookup box IF AND ONLY IF it was given
// something that can perform the lookup.
//
// WHY BOTH ARMS ARE ASSERTED. `lookupFetch` is optional on
// `TaskListRendererOptions`, and the tempting shape was a production-default
// fallback like the clock and the timer beside it. There is no sane default for
// a network call, so absence means NO BOX rather than a box that can only fail —
// and an input that is always wrong is worse than one that is not offered.
//
// ⚠️ THE ABSENT ARM IS THE ONE THAT WOULD ROT. Every real construction passes
// `lookupFetch`, so nothing else in the tree exercises the null branch; without
// this file it is a live branch with no test, which under a 100% gate shows up
// as a coverage number rather than as the missing guard it is.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/the_lookup_box_mounts_only_when_it_can_look_up.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createTaskListRenderer } from "../../../../lupin_app/static/js/multiplexer/render/TaskListRenderer";
import type { TaskItem } from "../../../../lupin_app/static/js/multiplexer/render/taskListModel";

before( () => {
  if ( !( globalThis as { document?: unknown } ).document ) {
    GlobalRegistrator.register();
  }
} );

/** The narrowest stores object `mount()` will accept. */
function stubStores() {
  return {
    taskList : {
      composite    : () => null,
      refresh      : () => Promise.resolve(),
      startPolling : () => {},
      stopPolling  : () => {},
    },
  } as never;
}

/** A minimal event bus — mount subscribes, and never fires in these tests. */
function stubBus() {
  return {
    on   : () => () => {},
    emit : () => {},
  } as never;
}

const LOOKUP_TESTID = '[data-testid="multiplexer-task-lookup"]';

test( "with a fetcher, the header carries the lookup box", () => {
  const renderer = createTaskListRenderer( {
    eventBus    : stubBus(),
    stores      : stubStores(),
    lookupFetch : () => Promise.resolve( {} as TaskItem ),
  } );

  const root = document.createElement( "div" );
  renderer.mount( root );

  assert.ok( root.querySelector( LOOKUP_TESTID ),
    "a construction that CAN look tickets up must offer the box" );
  renderer.unmount();
} );

test( "without a fetcher, no box is mounted at all", () => {
  const renderer = createTaskListRenderer( {
    eventBus : stubBus(),
    stores   : stubStores(),
    // lookupFetch deliberately omitted
  } );

  const root = document.createElement( "div" );
  renderer.mount( root );

  assert.equal( root.querySelectorAll( LOOKUP_TESTID ).length, 0,
    "an input that could only ever fail must not be offered" );
  renderer.unmount();
} );

test( "the box does not displace the controls that were already there", () => {
  // A regression guard on the ORDER change: the lookup was prepended to the
  // header's action slot, and the cheapest way to break refresh is to replace
  // the actions array rather than extend it.
  const renderer = createTaskListRenderer( {
    eventBus    : stubBus(),
    stores      : stubStores(),
    lookupFetch : () => Promise.resolve( {} as TaskItem ),
  } );

  const root = document.createElement( "div" );
  renderer.mount( root );

  for ( const testid of [
    "multiplexer-task-list-refresh",
    "multiplexer-task-list-collapse-all",
    "multiplexer-task-list-expand-all",
    "multiplexer-task-list-updated",
    "multiplexer-task-list-count",
  ] ) {
    assert.ok( root.querySelector( `[data-testid="${ testid }"]` ),
      `${ testid } must survive the header gaining a lookup box` );
  }
  renderer.unmount();
} );
