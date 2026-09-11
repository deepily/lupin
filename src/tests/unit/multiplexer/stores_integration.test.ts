// Multiplexer Phase 4 — cross-store integration tests.
// Run via `npx tsx --test src/tests/unit/multiplexer/stores_integration.test.ts`.
// AC8 + AC4 floor: ≥ 6 tests per design doc § Verification matrix.

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createStorageServiceForTesting } from "../../../lupin_app/static/js/multiplexer/shared/StorageService";
import { createStores } from "../../../lupin_app/static/js/multiplexer/stores";
import { deriveTaskActor } from "../../../lupin_app/static/js/multiplexer/render/taskListModel";
import { TASK_LIST_QUERY, HOLDING_AREA_QUERY } from "../../../lupin_app/static/js/shared/task-list-query.js";
import { ApiError } from "../../../lupin_app/static/js/multiplexer/api/ApiClient";
import type { ActionRequiredApiClient } from "../../../lupin_app/static/js/multiplexer/stores";
import type {
  AudioContextLike,
  AudioBufferLike,
} from "../../../lupin_app/static/js/multiplexer/audio/pcm-decoder";
import type {
  LupinEvent,
  LupinEventType,
} from "../../../lupin_app/static/js/multiplexer/shared/types";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeApiStub(): ActionRequiredApiClient & { get: <T>(path: string) => Promise<T> } {
  // post (ActionRequired/Missed/PredictionVote) + get (FleetStatus) — the
  // widened createStores api contract (Lane E quartet wiring).
  return {
    post: async () => ({ ok: true }),
    get : async <T,>(): Promise<T> => ({} as T),
  };
}

class StubAudioContext implements AudioContextLike {
  createBuffer(channels: number, length: number, sampleRate: number): AudioBufferLike {
    return {
      numberOfChannels : channels,
      length,
      sampleRate,
      duration         : length / sampleRate,
      copyToChannel    : () => {},
    };
  }
}

function setupAll() {
  const bus     = createEventBusForTesting();
  const storage = createStorageServiceForTesting(bus);
  const order   : LupinEventType[] = [];
  // Tap to record EVERY emission in arrival order, regardless of type.
  // We use specific types so we can assert ordering across stores.
  const watch = ["store_notifications_changed", "store_senders_changed", "store_action_required_changed", "store_audio_state_change", "store_jobs_changed"] as const;
  for (const t of watch) {
    bus.on(t, (e) => order.push(e.type));
  }
  const stores = createStores({
    eventBus            : bus,
    storage,
    api                 : makeApiStub(),
    audioContextFactory : () => new StubAudioContext(),
  });
  return { bus, storage, stores, order };
}

// ===========================================================================
// 1 — Subscription order: action-required notification → 3 stores fire in canonical order
// ===========================================================================

test("notification with response_requested=true fans out: NotificationStore (filtered out — empty msg=>no), SenderStore + ActionRequiredStore in order", () => {
  const ctx = setupAll();
  // Fire a single notification_queue_update with response_requested=true.
  // Per pinned order: NotificationStore (1st), SenderStore (2nd),
  // ActionRequiredStore (3rd), AudioStore (4th — no subscription on this
  // event), JobStore (5th — no subscription on this event).
  ctx.bus.emit({
    type    : "notification_queue_update",
    payload : {
      notification: {
        id_hash            : "ar1",
        message            : "Proceed?",
        sender_id          : "alice@x",
        timestamp          : new Date(1_000_000).toISOString(),
        response_requested : true,
        response_type      : "yes_no",
        response_options   : ["yes", "no"],
        timeout_seconds    : 30,
      },
    },
    source : "test",
    ts     : 0,
  });
  // Filter to only the cross-store-relevant emissions in arrival order.
  // Expected sequence: store_notifications_changed (added) →
  //                    store_senders_changed (added) →
  //                    store_action_required_changed (added).
  // Hydration emissions from NotificationStore construct happened earlier.
  const arrivalOrder = ctx.order.filter(t => t !== "store_notifications_changed" || ctx.order.indexOf(t) === ctx.order.lastIndexOf(t));
  // Simpler: look at the last 3 entries — those are this notification's fanout.
  const lastThree = ctx.order.slice(-3);
  assert.deepEqual(lastThree, [
    "store_notifications_changed",
    "store_senders_changed",
    "store_action_required_changed",
  ]);
});

// ===========================================================================
// 2 — Plain notification (no action required): NotificationStore + SenderStore (no ActionRequired)
// ===========================================================================

test("notification without response_requested fans out: NotificationStore + SenderStore only", () => {
  const ctx = setupAll();
  ctx.bus.emit({
    type    : "notification_queue_update",
    payload : {
      notification: {
        id_hash    : "n1",
        message    : "Hello",
        sender_id  : "alice@x",
        timestamp  : new Date(1_000_000).toISOString(),
      },
    },
    source : "test",
    ts     : 0,
  });
  const lastTwo = ctx.order.slice(-2);
  assert.deepEqual(lastTwo, ["store_notifications_changed", "store_senders_changed"]);
});

// ===========================================================================
// 3 — Job event isolation: only JobStore reacts
// ===========================================================================

test("job_state_transition only triggers JobStore emission", () => {
  const ctx = setupAll();
  const before = ctx.order.length;
  ctx.bus.emit({
    type    : "job_state_transition",
    payload : { job_id: "j1", to_state: "queued", timestamp: "2026-05-04T12:00:00Z" },
    source  : "test",
    ts      : 0,
  });
  const after = ctx.order.slice(before);
  assert.deepEqual(after, ["store_jobs_changed"]);
});

// ===========================================================================
// 4 — sys_time_update is "broad signal" — no store_changed events emitted unless prompts pending
// ===========================================================================

test("sys_time_update with no pending prompts: no store_changed emissions", () => {
  const ctx = setupAll();
  const before = ctx.order.length;
  ctx.bus.emit({ type: "sys_time_update", payload: {}, source: "test", ts: 0 });
  // NotificationStore sweeps active list (no items expired) → no emit.
  // ActionRequiredStore sees event but updates clockOffset only → no emit.
  assert.equal(ctx.order.length, before);
});

// ===========================================================================
// 5 — store getById propagates correctly across instances
// ===========================================================================

test("cross-store data access: notification + sender + ar prompt all queryable post-fanout", () => {
  const ctx = setupAll();
  ctx.bus.emit({
    type    : "notification_queue_update",
    payload : {
      notification: {
        id_hash            : "ar1",
        message            : "?",
        sender_id          : "bob@x",
        timestamp          : new Date(1_000_000).toISOString(),
        response_requested : true,
        timeout_seconds    : 30,
      },
    },
    source : "test",
    ts     : 0,
  });
  const n = ctx.stores.notifications.list().find(x => x.id_hash === "ar1");
  const s = ctx.stores.senders.get("bob@x");
  const ar = ctx.stores.actionRequired.getById("ar1");
  assert.ok(n,  "NotificationStore registers the prompt");
  assert.ok(s,  "SenderStore registers the sender");
  assert.ok(ar, "ActionRequiredStore registers the prompt");
});

// ===========================================================================
// 6 — Audio binary frame: only AudioStore reacts (transport-level callback, not bus)
// ===========================================================================

test("AudioStore.binaryHandler invocation does NOT emit any bus event from other stores", () => {
  const ctx = setupAll();
  const before = ctx.order.length;
  // Direct call to binary handler — bypasses the bus entirely.
  const buf = new Int16Array([0, 100, -100, 200, -200]).buffer;
  ctx.stores.audio.binaryHandler(buf);
  const after = ctx.order.slice(before);
  // Only AudioStore should emit (state transitions). No notification/job/sender events.
  for (const t of after) {
    assert.ok(
      t === "store_audio_state_change",
      `unexpected non-audio event during binaryHandler: ${t}`,
    );
  }
});

// ===========================================================================
// 7 — Pinned order under microtask boundary: emissions from a single dispatch are deterministic
// ===========================================================================

test("microtask determinism: emissions from a single notification dispatch are in pinned order, no interleaving", () => {
  const ctx = setupAll();
  const before = ctx.order.length;
  ctx.bus.emit({
    type    : "notification_queue_update",
    payload : {
      notification: {
        id_hash            : "ar2",
        message            : "?",
        sender_id          : "carol@x",
        timestamp          : new Date(1_000_000).toISOString(),
        response_requested : true,
        timeout_seconds    : 30,
      },
    },
    source : "test",
    ts     : 0,
  });
  // emit() is synchronous (CustomEvent dispatch) — all listeners fire before
  // emit() returns. So `ctx.order` already has the full fanout in registration
  // order, no microtask boundary needed.
  const fanout = ctx.order.slice(before);
  // Exactly 3 emissions (NotificationStore + SenderStore + ActionRequiredStore).
  assert.equal(fanout.length, 3);
  assert.deepEqual(fanout, [
    "store_notifications_changed",
    "store_senders_changed",
    "store_action_required_changed",
  ]);
});

// ---------------------------------------------------------------------------
// THE INSTALL QUESTION FOR THE HOLDING AREA'S WRITE SURFACE (row 87812328).
//
// 🔴 A STORE BUILT WITHOUT AN `actorProvider` FAILS SILENTLY AND CORRECTLY.
// The holding area now WRITES — the batch verbs post a transition per row — and
// `createHoldingAreaStore` defaults a missing provider to `() => null`, which
// `deriveTaskActor` renders as "anonymous (multiplexer)". Nothing throws, no
// request is refused, and the store's audit trail fills with correctly-shaped
// rows naming NOBODY. That is the one property an audit trail exists for.
//
// The factory line is a single argument. Dropping it is a one-character edit
// that no test of the STORE can see, because a store constructed directly in its
// own test is handed a provider by that test. Only a test that asks the ASSEMBLED
// FACTORY can catch it — the same shape as the mount guard on this branch, which
// exists because two panes reached 100% coverage while the app mounted neither.
// ---------------------------------------------------------------------------

test( "createStores hands the holding-area store the operator, so a batch is attributable", async () => {
  const posts: Array<{ path: string; body: unknown }> = [];
  const api = {
    get   : async () => ( {} ),
    patch : async () => ( {} ),
    post  : async ( path: string, body: unknown ) => { posts.push( { path, body } ); return {}; },
  } as never;

  const stores = createStores( {
    eventBus      : createEventBusForTesting(),
    storage       : createStorageServiceForTesting(),
    api,
    actorProvider : () => "rick@example.com",
  } );

  await stores.holdingArea.transitionTask( "row-1", "queued", {} );

  assert.equal( posts.length, 1, "the assembled holding-area store did not reach the api at all" );
  assert.equal( ( posts[ 0 ]?.body as { actor: string } ).actor, "rick@example.com (multiplexer)",
    "the factory built the holding-area store without an actorProvider — every batch transition would be filed as anonymous" );
} );

test( "the guard's negative control — an omitted provider really does read as anonymous", () => {
  // Without this, the test above passes for a factory that hardcodes the actor,
  // and it also passes if `deriveTaskActor` were to return the same string for
  // every input. It pins that the two cases are actually DISTINGUISHABLE.
  assert.equal( deriveTaskActor( null ), "anonymous (multiplexer)" );
  assert.notEqual( deriveTaskActor( "rick@example.com" ), deriveTaskActor( null ) );
} );

// ---------------------------------------------------------------------------
// Row c9fafb9d — createStores re-reads BOTH boards after a landed verdict (Tiffany F1, W4).
//
// The re-read is one closure in the factory. The store's own test hands it a fake
// `afterVerdict`, so replacing the factory's closure with `async () => {}` survived every test
// that builds the store directly: a landed approval would leave the moved row on its old board
// until the next 60s poll. Only the ASSEMBLED factory can say which queries follow the POST.
// ---------------------------------------------------------------------------


function verdictStores( refuse: boolean ) {
  const log: string[] = [];
  const api = {
    get   : async ( path: string ) => { log.push( `GET ${ path }` ); return { tasks: [], count: 0 }; },
    patch : async () => ( {} ),
    post  : async ( path: string ) => {
      log.push( `POST ${ path }` );
      if ( refuse ) throw new ApiError( 403, path, JSON.stringify( { detail: "only Rick" } ) );
      return {};
    },
  } as never;
  const stores = createStores( { eventBus: createEventBusForTesting(), storage: createStorageServiceForTesting(), api } );
  return { stores, log };
}

test( "a landed verdict from the assembled stores re-reads the task list AND the holding area, after the POST", async () => {
  const { stores, log } = verdictStores( false );
  assert.deepEqual( await stores.taskRequests.submitVerdict( "row-1", { verdict: "approved" } ), { ok: true } );
  const post = log.indexOf( "POST /api/tasks/row-1/request-verdict" );
  assert.ok( post >= 0, "the verdict never reached the api" );
  const after = log.slice( post + 1 );
  assert.ok( after.includes( `GET ${ TASK_LIST_QUERY }` ),    "the task list was not re-read after the verdict" );
  assert.ok( after.includes( `GET ${ HOLDING_AREA_QUERY }` ), "the holding area was not re-read after the verdict" );
  assert.ok( after.includes( "GET /api/tasks/request-badges" ), "the badges were not re-read after the verdict" );
} );

test( "a refused verdict from the assembled stores re-reads neither board", async () => {
  const { stores, log } = verdictStores( true );
  const result = await stores.taskRequests.submitVerdict( "row-1", { verdict: "approved" } );
  assert.deepEqual( result, { ok: false, message: "only Rick" } );
  assert.deepEqual( log, [ "POST /api/tasks/row-1/request-verdict" ] );
} );

test( "a verdict landing while a task-list poll is in flight waits it out and THEN reads the list (Tiffany L1)", async () => {
  // `taskList.refresh()` skips a collision, so the factory used to get no task-list read at all
  // when a poll was mid-flight. This gates the poll's list read and lets the verdict land inside it.
  let release!: () => void;
  const gate = new Promise<void>( ( r ) => { release = r; } );
  const log: string[] = [];
  let listGets = 0;
  const api = {
    get   : async ( path: string ) => {
      log.push( `GET ${ path }` );
      if ( path === TASK_LIST_QUERY ) { listGets += 1; if ( listGets === 1 ) await gate; }
      return { tasks: [], count: 0 };
    },
    patch : async () => ( {} ),
    post  : async ( path: string ) => { log.push( `POST ${ path }` ); return {}; },
  } as never;
  const stores = createStores( { eventBus: createEventBusForTesting(), storage: createStorageServiceForTesting(), api } );
  const poll    = stores.taskList.refresh();
  await new Promise( ( r ) => setTimeout( r, 0 ) );
  const verdict = stores.taskRequests.submitVerdict( "row-1", { verdict: "approved" } );
  await new Promise( ( r ) => setTimeout( r, 0 ) );
  release();
  await poll;
  assert.deepEqual( await verdict, { ok: true } );
  const after = log.slice( log.indexOf( "POST /api/tasks/row-1/request-verdict" ) + 1 );
  assert.equal( after.filter( ( l ) => l === `GET ${ TASK_LIST_QUERY }` ).length, 1,
                `no task-list read began after the verdict POST: ${ JSON.stringify( after ) }` );
} );
