// The holding-area WRITE surface must not read a 202 as an approval (row 8ed76594).
//
// 🔴 THE DEFECT THIS GUARDS, AND WHY IT IS NOT A FALSE RED BUT A FALSE FACT.
// `HoldingAreaStore.transitionTask` awaits `api.post` and returns `{ ok: true }` on
// anything that did not throw. `ApiClient` throws only on `!response.ok`, and a 202 is
// `ok` — so an asynchronous promotion, which means "Rick has not been asked yet, here is
// a ticket", comes back indistinguishable from "Rick approved it". The pane then paints
// the row as approved. Tiffany measured the same shape in TaskListStore on 2026-09-06;
// this is the batch surface's arm of it.
//
// ⚠️ THE DISCRIMINATOR IS THE SERVER'S BODY MARKER, NOT THE STATUS CODE, AND THAT IS
// FORCED BY THE LAYER RATHER THAN CHOSEN. `ApiClient.request` returns the parsed BODY and
// never surfaces `response.status` (ApiClient.ts:227-232) — a 200 and a 202 are literally
// the same value there. Widening that shared helper's contract would touch every caller
// of it, so the server puts a marker in the 202 body on purpose and `task_store_tools.py`
// already pins to it for exactly this reason. Three clients, one rule.
//
// The marker string is duplicated from the server rather than imported — the browser
// cannot import `cosa.rest.routers.tasks` — so it is pinned by the parity test in
// `src/tests/unit/test_the_browser_202_marker_matches_the_server.py`, the same way the
// MCP client's copy is pinned by `test_the_promotion_poll_answers_like_a_synchronous_call.py`.
//
// ⚠️ NOTE WHAT THAT MEANS FOR THIS FILE: the guard below hands the store the marker it
// expects, so it cannot by itself catch a server respelling. The parity test is the arm
// that can. Neither alone is sufficient and they are not redundant.

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createHoldingAreaStore,
  type HoldingAreaApiClient,
} from "../../../lupin_app/static/js/multiplexer/stores/HoldingAreaStore";

/** The server's 202 body, verbatim in shape from routers/tasks.py:1348-1356. */
const AWAITING_BODY = {
  status      : "awaiting_human_approval",
  ticket_id   : "11111111-2222-3333-4444-555555555555",
  task_id     : "abc-123",
  to_status   : "queued",
  resolves_by : "2026-09-08T23:59:00+00:00",
  check_with  : "task_promotion_status",
};

function storeWith( postImpl: ( path: string, body: unknown ) => Promise<unknown> ) {
  const posts: Array<{ path: string; body: unknown }> = [];
  const api: HoldingAreaApiClient = {
    get  : async () => ( { status: "", tasks: [] } ) as never,
    post : async ( path, body ) => { posts.push( { path, body } ); return postImpl( path, body ) as never; },
  };
  const store = createHoldingAreaStore( {
    bus             : createEventBusForTesting(),
    api,
    actorProvider   : () => "rick@example.com",
    setIntervalFn   : () => 1,
    clearIntervalFn : () => { /* no timer in these tests */ },
  } );
  return { store, posts };
}

// ---------------------------------------------------------------------------
// The guard
// ---------------------------------------------------------------------------

test( "an awaiting-approval body is NOT reported as a successful approval", async () => {
  const { store } = storeWith( async () => AWAITING_BODY );
  const result = await store.transitionTask( "abc-123", "queued", {} );

  // The whole defect in one assertion: today this reads `{ ok: true }`.
  assert.equal(
    result.ok, false,
    "a 202 awaiting_human_approval was reported as a successful approval — the row would paint as approved for a promotion Rick has not been asked about",
  );
} );

test( "the awaiting-approval result is distinguishable from a refusal, and carries the ticket", async () => {
  const { store } = storeWith( async () => AWAITING_BODY );
  const result = await store.transitionTask( "abc-123", "queued", {} );

  // `ok: false` alone would make "Rick has not answered yet" read as "the server said
  // no", which is a different wrong answer rather than a fix. The pending flag is what
  // lets the operator be told the true thing.
  assert.equal( result.pending, true, "awaiting approval must be distinguishable from a refusal" );
  assert.equal( result.ticketId, AWAITING_BODY.ticket_id, "the ticket id must survive to the caller" );
} );

// ---------------------------------------------------------------------------
// The controls. Without these the guard above is satisfied by a store that calls
// EVERYTHING pending, which would be strictly worse than the defect.
// ---------------------------------------------------------------------------

test( "CONTROL — an ordinary 200 is still a plain success, with no pending flag", async () => {
  const { store } = storeWith( async () => ( {} ) );
  const result = await store.transitionTask( "abc-123", "queued", {} );
  assert.equal( result.ok, true, "a synchronous approval must still report success" );
  assert.notEqual( result.pending, true, "a synchronous approval must not be marked pending" );
} );

test( "CONTROL — a 200 whose body merely MENTIONS the marker elsewhere is still a success", async () => {
  // The discriminator is the `status` FIELD, not the marker appearing anywhere in the
  // payload. A substring test would pass this and be wrong.
  const { store } = storeWith( async () => ( { status: "queued", reason: "awaiting_human_approval was not the outcome" } ) );
  const result = await store.transitionTask( "abc-123", "queued", {} );
  assert.equal( result.ok, true, "only the status field opts a response into the pending branch" );
} );

test( "CONTROL — a non-object body does not crash the marker read", async () => {
  const { store } = storeWith( async () => null );
  const result = await store.transitionTask( "abc-123", "queued", {} );
  assert.equal( result.ok, true );
} );

// ---------------------------------------------------------------------------
// The degenerate 202. Found by coverage, not by imagination: the `?? ""` on
// ticket_id was the store's last uncovered branch (98.43% → this arm).
//
// 🔴 AND IT IS A REAL SHAPE, NOT A NUMBER-CHASING ARM. The pending VERDICT must not
// depend on the ticket being present — a 202 that arrives without one is still "Rick
// has not been asked yet", and reporting it as an approval because a field was missing
// would be the original defect wearing a different hat.
// ---------------------------------------------------------------------------

test( "a 202 carrying NO ticket_id is still pending, with an empty ticket rather than \"undefined\"", async () => {
  const { store } = storeWith( async () => ( { status: "awaiting_human_approval" } ) );
  const result = await store.transitionTask( "abc-123", "queued", {} );

  assert.equal( result.ok, false, "a ticketless 202 must still not read as an approval" );
  assert.equal( result.pending, true );
  // `String( undefined )` is "undefined" — a string the operator would be shown verbatim.
  assert.equal( result.ticketId, "", "a missing ticket must be empty, never the text \"undefined\"" );
} );
