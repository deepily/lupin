// Holding-area card — HoldingAreaStore's WRITE surface (row 87812328).
// 100% lines/branches/functions per the multiplexer coverage mandate.
//
// 🔴 THE ONE PROPERTY EVERY TEST HERE IS REALLY ABOUT: `transitionTask` NEVER
// REJECTS. A batch is a loop over it, and a loop whose body can throw stops on
// its first refusal — so the rows after a 403 are never attempted and the
// operator is told nothing about them. Every "returns a result" assertion below
// is that invariant wearing a different hat.
//
// ⚠️ THE ERRORS ARE REAL `ApiError` INSTANCES, NOT HAND-BUILT OBJECTS. A
// hand-written fixture is not merely simpler than reality, it is systematically
// BETTER-FORMED than it — and the whole hazard in `holdingRefusalMessage` lives
// in the exact shape of `ApiError.message`, which is assembled by a constructor
// this test would otherwise be free to misremember.

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { ApiError } from "../../../lupin_app/static/js/multiplexer/api/ApiClient";
import {
  createHoldingAreaStore,
  holdingRefusalMessage,
  type HoldingAreaApiClient,
} from "../../../lupin_app/static/js/multiplexer/stores/HoldingAreaStore";

interface Recorded { path: string; body: unknown }

function storeWith(
  postImpl: ( path: string, body: unknown ) => Promise<unknown>,
  actor: string | null = "rick@example.com",
) {
  const posts: Recorded[] = [];
  const api: HoldingAreaApiClient = {
    get: async () => ( { status: "", tasks: [] } ) as never,
    post: async ( path, body ) => { posts.push( { path, body } ); return postImpl( path, body ) as never; },
  };
  const store = createHoldingAreaStore( {
    bus: createEventBusForTesting(), api,
    actorProvider: () => actor,
    setIntervalFn: () => 1, clearIntervalFn: () => { /* no timer in these tests */ },
  } );
  return { store, posts };
}

// ---------------------------------------------------------------------------
// The happy path and the shape of what is posted
// ---------------------------------------------------------------------------

test( "a 2xx resolves ok, and posts to the row's own transition door", async () => {
  const { store, posts } = storeWith( async () => ( {} ) );
  const result = await store.transitionTask( "abc-123", "queued", {} );
  assert.deepEqual( result, { ok: true } );
  assert.equal( posts.length, 1 );
  assert.equal( posts[ 0 ]?.path, "/api/tasks/abc-123/transition" );
} );

test( "the posted body carries to_status, the verb's extras, the actor and the authority", async () => {
  const { store, posts } = storeWith( async () => ( {} ) );
  await store.transitionTask( "abc-123", "wont_fix", { reason: "superseded by the v2 door" } );
  assert.deepEqual( posts[ 0 ]?.body, {
    to_status : "wont_fix",
    reason    : "superseded by the v2 door",
    actor     : "rick@example.com (multiplexer)",
    authority : "user_direct",
  } );
} );

test( "`authority: user_direct` is posted — a batch is still a human pressing a button", async () => {
  // Not decoration. The store's audit trail keys provenance off this field, and
  // recording an operator's decision as anything weaker makes it read as
  // automation on a surface whose whole subject is who decided what.
  const { store, posts } = storeWith( async () => ( {} ) );
  await store.transitionTask( "x", "queued", {} );
  assert.equal( ( posts[ 0 ]?.body as { authority: string } ).authority, "user_direct" );
} );

test( "an unauthenticated construction records `anonymous`, never a blank actor", async () => {
  const { store, posts } = storeWith( async () => ( {} ), null );
  await store.transitionTask( "x", "queued", {} );
  assert.equal( ( posts[ 0 ]?.body as { actor: string } ).actor, "anonymous (multiplexer)" );
} );

test( "a row id is URL-encoded rather than pasted into the path", async () => {
  const { store, posts } = storeWith( async () => ( {} ) );
  await store.transitionTask( "a/b?c#d", "queued", {} );
  assert.equal( posts[ 0 ]?.path, "/api/tasks/a%2Fb%3Fc%23d/transition" );
} );

// ---------------------------------------------------------------------------
// The refusals — the half the batch report is built out of
// ---------------------------------------------------------------------------

test( "a refusal is a VALUE, not a throw — the loop-body invariant", async () => {
  const { store } = storeWith( async () => {
    throw new ApiError( 403, "/api/tasks/x/transition", '{"detail":"actor not on the allowlist"}' );
  } );
  // If this rejected, the await itself would throw and the test would error out
  // rather than fail an assertion — which is exactly what a batch loop would do.
  const result = await store.transitionTask( "x", "queued", {} );
  assert.equal( result.ok, false );
} );

test( "a refusal carries the SERVER'S OWN WORDS, not a client-authored sentence", async () => {
  const { store } = storeWith( async () => {
    throw new ApiError( 403, "/api/tasks/x/transition",
      '{"detail":"actor rick@example.com (multiplexer) is not on the promotion allowlist"}' );
  } );
  const result = await store.transitionTask( "x", "queued", {} );
  assert.deepEqual( result, {
    ok: false,
    message: "actor rick@example.com (multiplexer) is not on the promotion allowlist",
  } );
} );

// ---------------------------------------------------------------------------
// holdingRefusalMessage, driven directly
// ---------------------------------------------------------------------------

test( "a JSON `detail` string comes back verbatim", () => {
  assert.equal(
    holdingRefusalMessage( new ApiError( 422, "/api/tasks/x/transition", '{"detail":"reason must be non-blank"}' ) ),
    "reason must be non-blank" );
} );

test( "a NON-STRING `detail` is stringified rather than dropped", () => {
  // FastAPI's validation errors arrive as a LIST of objects. Dropping them would
  // turn the most informative refusal the server sends into a bare "422".
  const detail = [ { loc: [ "body", "reason" ], msg: "field required" } ];
  assert.equal(
    holdingRefusalMessage( new ApiError( 422, "/api/tasks/x/transition", JSON.stringify( { detail } ) ) ),
    JSON.stringify( detail ) );
} );

test( "a NON-JSON error body collapses to the bare status — the legacy behaviour, kept", () => {
  // An HTML error page is not a message to an operator, and the two clients
  // reporting the same 502 differently is worse than either wording.
  assert.equal(
    holdingRefusalMessage( new ApiError( 502, "/api/tasks/x/transition", "<html>Bad Gateway</html>" ) ),
    "502" );
} );

test( "a JSON body with no `detail` key also collapses to the bare status", () => {
  assert.equal(
    holdingRefusalMessage( new ApiError( 500, "/api/tasks/x/transition", '{"error":"boom"}' ) ),
    "500" );
} );

test( "a transport throw reads as UNREACHABLE, so an outage never masquerades as a refusal", () => {
  // The distinction is the point: a refusal means the server considered this and
  // said no, and an operator responds to those two facts differently. A network
  // error carries no `status`, which is the discriminator.
  assert.equal(
    holdingRefusalMessage( new TypeError( "Failed to fetch" ) ),
    "unreachable: Failed to fetch" );
} );

test( "a thrown non-Error is still turned into a sentence rather than crashing the loop", () => {
  assert.equal( holdingRefusalMessage( "just a string" ), "unreachable: just a string" );
  assert.equal( holdingRefusalMessage( null ), "unreachable: null" );
  assert.equal( holdingRefusalMessage( undefined ), "unreachable: undefined" );
} );

test( "an error whose message does NOT carry the expected prefix is still read, not discarded", () => {
  // Defensive against the ApiError message format changing under us: the prefix
  // is RECONSTRUCTED from `.status` and `.url`, and when it does not match, the
  // whole message is tried as the body rather than the function giving up.
  const odd = { status: 409, url: "/x", message: '{"detail":"a conflicting transition is in flight"}' };
  assert.equal( holdingRefusalMessage( odd ), "a conflicting transition is in flight" );
} );

test( "the prefix is stripped by RECONSTRUCTION, not by splitting on the first colon", () => {
  // A URL contains colons. Splitting on the first one would return
  // "//localhost:7999/api/..." as the message body on any absolute URL.
  const err = new ApiError( 403, "http://localhost:7999/api/tasks/x/transition", '{"detail":"denied"}' );
  assert.ok( err.message.includes( "http://localhost:7999" ), "the fixture does not exercise the colon case" );
  assert.equal( holdingRefusalMessage( err ), "denied" );
} );

// ---------------------------------------------------------------------------
// What transitionTask deliberately does NOT do
// ---------------------------------------------------------------------------

test( "the cached composite is NOT edited and no change event fires — the batch refreshes once, at the end", async () => {
  // A DIVERGENCE FROM TaskListStore, and a deliberate one. That store makes an
  // optimistic edit so a single row repaints instantly. A batch cannot: the
  // renderer reads its id list off the RENDERED DOM, so an optimistic removal per
  // row would repaint the pane mid-loop and pull the remaining rows out from
  // under the walk.
  const bus    = createEventBusForTesting();
  const events: string[] = [];
  bus.on( "store_holding_area_changed", () => { events.push( "changed" ); } );
  const api: HoldingAreaApiClient = { get: async () => ( {} ) as never, post: async () => ( {} ) as never };
  const store = createHoldingAreaStore( {
    bus, api, actorProvider: () => "x@y.z",
    setIntervalFn: () => 1, clearIntervalFn: () => { /* no timer */ },
  } );

  const before = store.composite();
  await store.transitionTask( "a", "queued", {} );
  await store.transitionTask( "b", "wont_fix", { reason: "r" } );

  assert.equal( store.composite(), before, "transitionTask edited the cached composite" );
  assert.deepEqual( events, [], "transitionTask emitted a change event — the pane would repaint mid-batch" );
} );

test( "an error carrying a status but NO url is still read — the prefix reconstruction degrades", () => {
  // The prefix is built from `.status` and `.url`. A thrown object with a numeric
  // status and no url is not something ApiClient produces today; it is what a
  // second api implementation, or a future ApiError shape, could hand this.
  // Reconstructing `HTTP 403 : ` then failing to match must fall through to
  // trying the WHOLE message as the body, never to discarding it.
  assert.equal(
    holdingRefusalMessage( { status: 403, message: '{"detail":"denied by the gate"}' } ),
    "denied by the gate" );
} );
