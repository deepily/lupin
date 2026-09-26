// Row 93ca4268 — THE PIN. Mr. Radio's ruling, 2026-09-26: test the reachable
// symptoms for real, and pin the UNREACHABLE one so it announces itself the day
// it becomes reachable. Written by Sam 🎙️.
//
// WHAT IS BEING PINNED. `refreshAfterWrite()` inherits a prior poll's rejection
// through `await this.inFlightRun` (TaskListStore) / `await this.inFlight`
// (HoldingAreaStore). That is a real mechanism: if a poll's run rejects, a LATER
// writer's `done` rejects, and taskRowController rolls back an edit the server
// already accepted — someone else's failed read destroying my write.
//
// It cannot happen today, and the reason is worth stating because it is the
// whole value of this file. A run's body is `try { fetchState(); emitChanged(); }
// finally {}` — no catch — so there are exactly TWO exits:
//   1. `fetchState()` rejecting. Closed: both stores catch every shape and return
//      an `unreachable` / `auth_required` sentinel instead of throwing.
//   2. `emitChanged()` throwing. Closed one layer down: it is `bus.emit(...)`, and
//      EventBus wraps every listener in try/catch and converts a throw into a
//      `listener_error` event rather than letting it out.
// Both exits closed ⇒ the run always fulfils ⇒ `await inFlightRun` never
// re-throws ⇒ path (b) is dead code today.
//
// 🔴 WHY A PIN AND NOT A COMMENT. "Currently unreachable" is exactly the kind of
// claim that rots silently: one `catch` narrowed, one store added, one emit moved
// off the bus, and path (b) goes live with nothing to announce it. These tests
// FAIL when that happens. A comment would not.
//
// 🔴 AND THEY ARE BEHAVIOURAL, NOT TEXTUAL. A pin that greps the source for
// `catch` would pass on a catch that rethrows and fail on a refactor that changed
// nothing. These drive the real store through the real bus and assert the one
// thing that matters: the returned promise FULFILS.
//
// HOW TO READ A FAILURE HERE. It does not mean this file is wrong. It means a
// store gained a rejecting path, so the poll-in-flight rollback described in row
// 93ca4268 has become LIVE and needs a real test plus, if the wrapper decoupling
// ever regressed, a real fix.

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createTaskListStore } from "../../../lupin_app/static/js/multiplexer/stores/TaskListStore";
import { createHoldingAreaStore } from "../../../lupin_app/static/js/multiplexer/stores/HoldingAreaStore";
import type { TaskListApiClient } from "../../../lupin_app/static/js/multiplexer/stores/TaskListStore";
import type { HoldingAreaApiClient } from "../../../lupin_app/static/js/multiplexer/stores/HoldingAreaStore";
import type { ListenerErrorPayload } from "../../../lupin_app/static/js/multiplexer/shared/types";

/** Every shape a read can fail in. `network` carries no `.status`, which is the
 *  one that used to slip past a status-keyed catch. */
type FailMode = "http500" | "http401" | "network" | "nonError";

function failingGet( mode: FailMode ): <T>( path: string ) => Promise<T> {
  return async <T,>(): Promise<T> => {
    if ( mode === "http500" )  { const e = new Error( "500" ) as Error & { status: number }; e.status = 500; throw e; }
    if ( mode === "http401" )  { const e = new Error( "401" ) as Error & { status: number }; e.status = 401; throw e; }
    if ( mode === "network" )  { throw new Error( "network down" ); }
    throw "a bare string, not an Error";   // eslint-disable-line no-throw-literal -- the shape a `instanceof Error` guard misses
  };
}

const MODES: FailMode[] = [ "http500", "http401", "network", "nonError" ];

// ---------------------------------------------------------------------------
// Exit 1 — fetchState. Both stores, every shape.
// ---------------------------------------------------------------------------

test( "PIN: TaskListStore.refresh() fulfils however the read fails", async () => {
  assert.ok( MODES.length > 0, "the mode list must be non-empty — a loop over nothing passes every assertion in it" );
  for ( const mode of MODES ) {
    const bus = createEventBusForTesting();
    const api = { get: failingGet( mode ), patch: async <T,>(): Promise<T> => null as T, post: async <T,>(): Promise<T> => null as T } as TaskListApiClient;
    const store = createTaskListStore( { bus, api } );

    await assert.doesNotReject(
      () => store.refresh(),
      `TaskListStore.refresh() REJECTED on a '${ mode }' read. Path (b) of row 93ca4268 is now LIVE: ` +
      `a poll failing this way will roll back a later writer's accepted edit.`,
    );
  }
} );

test( "PIN: HoldingAreaStore.refresh() fulfils however the read fails", async () => {
  assert.ok( MODES.length > 0, "the mode list must be non-empty" );
  for ( const mode of MODES ) {
    const bus = createEventBusForTesting();
    const api = { get: failingGet( mode ), post: async <T,>(): Promise<T> => null as T, patch: async <T,>(): Promise<T> => null as T } as HoldingAreaApiClient;
    const store = createHoldingAreaStore( { bus, api } );

    await assert.doesNotReject(
      () => store.refresh(),
      `HoldingAreaStore.refresh() REJECTED on a '${ mode }' read. Path (b) of row 93ca4268 is now LIVE.`,
    );
  }
} );

// ---------------------------------------------------------------------------
// Exit 2 — emitChanged. A subscriber that throws must not escape the bus.
// ---------------------------------------------------------------------------

// 🔴 WHAT THIS PIN ASSERTS, AND WHY IT IS NOT "refresh() does not reject".
// I wrote it that way first and the positive control refuted it. Removing
// EventBus's listener try/catch does NOT make `refresh()` reject: the listener
// runs under `EventTarget.dispatchEvent`, and per the DOM event model an
// exception thrown by a listener is reported as an uncaught error rather than
// propagated to the dispatcher. So exit 2 is closed TWICE — once by EventBus's
// catch, and again, underneath it, by the platform. A `doesNotReject` here can
// never go red, and a pin that cannot fail pins nothing.
//
// So this asserts the thing that CAN move: that the bus still CONVERTS the throw
// into an observable `listener_error`. Remove EventBus's catch and this reddens
// BY NAME, which is what a pin owes its reader.
test( "PIN: a throwing subscriber is converted to listener_error, not lost", async () => {
  const bus = createEventBusForTesting();

  const seen: string[] = [];
  bus.on<ListenerErrorPayload>( "listener_error", ( e ) => { seen.push( e.payload.error ); } );

  let sawEmit = false;
  bus.on( "store_task_list_changed", () => {
    sawEmit = true;
    throw new Error( "subscriber exploded during repaint" );
  } );

  const api = {
    get: async <T,>(): Promise<T> => ( { status: "ok", tasks: [], count: 0 } as unknown as T ),
    patch: async <T,>(): Promise<T> => null as T,
    post:  async <T,>(): Promise<T> => null as T,
  } as TaskListApiClient;

  await assert.doesNotReject(
    () => createTaskListStore( { bus, api } ).refresh(),
    "refresh() REJECTED because a subscriber threw — exit 2 of row 93ca4268's path (b) is open.",
  );

  // Without this the assertion below is satisfiable by a read that never emitted
  // at all, which would pin nothing.
  assert.equal( sawEmit, true, "the throwing subscriber must actually have been invoked" );

  assert.deepEqual(
    seen, [ "subscriber exploded during repaint" ],
    "EventBus no longer converts a listener throw into `listener_error`. The throw is now escaping " +
    "the wrapper, which is the isolation row 8033756c's subscriber depends on.",
  );
} );

// ---------------------------------------------------------------------------
// The consequence, stated as its own assertion so a failure names the harm.
// ---------------------------------------------------------------------------

// Rachel 🕊️ reviewed the pin at e22cac92d and named this test's ceiling: asserting
// only that it FULFILS cannot notice the join being deleted, because a
// `refreshAfterWrite` that never joins also fulfils. Closed below by asserting the
// join's observable consequence — a SECOND read — rather than its source text.
test( "PIN: refreshAfterWrite() joining a failed prior poll still fulfils, and still re-reads", async () => {
  const bus = createEventBusForTesting();
  const getCalls: string[] = [];
  const failing = failingGet( "network" );
  const api = {
    get: async <T,>( path: string ): Promise<T> => { getCalls.push( path ); return failing<T>( path ); },
    patch: async <T,>(): Promise<T> => null as T,
    post:  async <T,>(): Promise<T> => null as T,
  } as TaskListApiClient;
  const store = createTaskListStore( { bus, api } );

  // Start a poll and do NOT await it — this is the in-flight run a writer joins.
  const poll = store.refresh();
  assert.equal( getCalls.length, 1, "the poll must have issued its read before we join it" );

  await assert.doesNotReject(
    () => store.refreshAfterWrite(),
    "refreshAfterWrite() inherited a prior poll's rejection. This is the exact rollback row 93ca4268 " +
    "describes: the write succeeded, someone else's read failed, and the operator's edit is about to revert.",
  );

  await assert.doesNotReject( () => poll, "and the poll itself must not reject either" );

  // 🔴 THE JOIN, ASSERTED BY ITS CONSEQUENCE. `refreshAfterWrite` waits out the
  // in-flight poll and THEN takes a fresh read, because a read that began before
  // the write cannot see it however patiently you wait. Delete the
  // `await this.inFlightRun` and `refresh()`'s own `if (this.inFlight) return`
  // debounce swallows the call: one read, not two, and a writer that never
  // re-read. This count is what notices.
  assert.equal(
    getCalls.length, 2,
    "refreshAfterWrite() did not issue a read of its own. It either skipped the join and was " +
    "swallowed by refresh()'s in-flight debounce, or it resolved on the poll's read — which began " +
    "BEFORE the write and therefore cannot see it.",
  );
} );
