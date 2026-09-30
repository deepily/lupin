// notifications.js `_transitionTask` must not read a 202 as an approval (row 8ed76594).
//
// 🔴 THE SECOND CLIENT, AND IT IS THE ONE THE TYPE ARGUMENT NEVER COVERED.
// The defence usually cited for the async opt-in is that `transitionTask`'s extras are
// typed `Record<string, string>`, so a browser cannot send a real boolean. That is a
// TypeScript claim, it erases at runtime, and THIS file has no type system at all —
// `notifications.js` is a classic script. Whatever is true of the multiplexer's types is
// simply not true here, so this surface needs its own guard rather than inheriting one.
//
// The defect: `_transitionTask` does `if ( response.ok ) return { ok: true }`, and
// `response.ok` is true for ANY 2xx. A 202 means "Rick has not been asked yet, here is a
// ticket" and comes back as "Rick approved it".
//
// ⚠️ THIS CLIENT DISCRIMINATES ON THE STATUS CODE, NOT THE BODY MARKER, AND THE
// DIFFERENCE FROM THE MULTIPLEXER GUARD IS FORCED BY THE LAYER. Here the raw `Response`
// is in hand, so `response.status` is available and unambiguous — and the defect is
// literally "any 2xx reads as success", so the fix belongs on the code. The multiplexer
// store cannot do this: `ApiClient` returns the parsed body and never surfaces the
// status, so it reads the server's body marker instead. Two layers, two available
// signals, one behaviour.
//
// Harness is the established one (holding_area_panel / task_list_panel): load the class
// via vm.runInThisContext sliced before the DOM-ready init, Object.create the prototype
// to skip the constructor, stub `authedFetch`, drive the REAL method.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/the_202_is_not_a_success.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE            = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

before( () => {
  if ( typeof globalThis.document === "undefined" ) {
    GlobalRegistrator.register();
  }
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext(
    fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;",
    { filename: NOTIFICATIONS_JS }
  );
} );

type TransitionResult = { ok: boolean; message?: string; pending?: boolean; ticketId?: string };

type TransitionUI = Record<string, unknown> & {
  _transitionTask : ( id: string, to: string, extras?: unknown ) => Promise<TransitionResult>;
  authedFetch     : ( url: string, init: Record<string, unknown> ) => Promise<unknown>;
};

/** The server's 202 body, verbatim in shape from routers/tasks.py:1348-1356. */
const AWAITING_BODY = {
  status      : "awaiting_human_approval",
  ticket_id   : "11111111-2222-3333-4444-555555555555",
  task_id     : "abc-123",
  to_status   : "queued",
  resolves_by : "2026-09-08T23:59:00+00:00",
  check_with  : "task_promotion_status",
};

const ROW_ID = "aaaaaaaa-1111-2222-3333-444444444444";

/**
 * A UI whose `authedFetch` answers with one canned response.
 *
 * The response is a real-shaped `Response` stand-in: `ok` is derived from the status the
 * way the browser derives it, never hand-set, so a test cannot accidentally describe a
 * combination the platform never produces.
 */
function newUI( status: number, body: unknown ): TransitionUI {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui   = Object.create( Ctor.prototype ) as TransitionUI;
  ui.debug            = false;
  ui.log              = (): void => {};
  ui.error            = (): void => {};
  ui.queueSessionId   = "wise penguin";
  ui.authedFetch = async () => ( {
    ok     : status >= 200 && status < 300,
    status,
    json   : async () => body,
    text   : async () => JSON.stringify( body ),
  } );
  return ui;
}

// ---------------------------------------------------------------------------
// The guard
// ---------------------------------------------------------------------------

test( "a 202 awaiting-approval is NOT reported as a successful approval", async () => {
  const ui     = newUI( 202, AWAITING_BODY );
  const result = await ui._transitionTask( ROW_ID, "queued", {} );

  // The whole defect in one assertion: today this reads `{ ok: true }`, because
  // `response.ok` is true for any 2xx.
  assert.equal(
    result.ok, false,
    "a 202 awaiting_human_approval was reported as a successful approval — the operator would be told Rick approved a promotion he has not been asked about",
  );
} );

test( "the awaiting-approval result is distinguishable from a refusal, and carries the ticket", async () => {
  const ui     = newUI( 202, AWAITING_BODY );
  const result = await ui._transitionTask( ROW_ID, "queued", {} );

  assert.equal( result.pending, true, "awaiting approval must be distinguishable from a refusal" );
  assert.equal( result.ticketId, AWAITING_BODY.ticket_id, "the ticket id must survive to the caller" );
} );

// ---------------------------------------------------------------------------
// The controls. Without these the guard is satisfied by a client that calls
// EVERYTHING pending, or that reports every 2xx as a failure — both worse than
// the defect.
// ---------------------------------------------------------------------------

test( "CONTROL — a 200 is still a plain success, with no pending flag", async () => {
  const ui     = newUI( 200, { status: "queued" } );
  const result = await ui._transitionTask( ROW_ID, "queued", {} );
  assert.equal( result.ok, true, "a synchronous approval must still report success" );
  assert.notEqual( result.pending, true, "a synchronous approval must not be marked pending" );
} );

test( "CONTROL — a 403 refusal still reports the server's own words, and is not pending", async () => {
  const ui     = newUI( 403, { detail: "promotion out of the holding area is manager-only" } );
  const result = await ui._transitionTask( ROW_ID, "queued", {} );
  assert.equal( result.ok, false );
  assert.notEqual( result.pending, true, "a refusal must not be dressed up as awaiting approval" );
  assert.match( String( result.message ), /manager-only/, "the server's own words must survive" );
} );

test( "CONTROL — a 204 with no body is a success, and the marker read does not crash on it", async () => {
  const ui     = newUI( 204, null );
  const result = await ui._transitionTask( ROW_ID, "queued", {} );
  assert.equal( result.ok, true );
} );

// ---------------------------------------------------------------------------
// The degenerate 202s. Its sibling guard's coverage run found the matching gap in
// HoldingAreaStore; these are the same two shapes on this client.
//
// 🔴 THE VERDICT MUST NOT DEPEND ON THE BODY. `_transitionTask` decides pending on the
// STATUS CODE and only then tries to read a ticket out of the body. If an unreadable or
// ticketless body could flip the verdict back to success, the fix would evaporate on
// exactly the malformed responses it most needs to survive.
// ---------------------------------------------------------------------------

test( "a 202 whose body will not parse is STILL pending — the verdict does not depend on the parse", async () => {
  const ui = newUI( 202, null );
  // A body that throws on read, which is what a truncated or non-JSON 202 does.
  ui.authedFetch = async () => ( {
    ok     : true,
    status : 202,
    json   : async () => { throw new SyntaxError( "Unexpected end of JSON input" ); },
    text   : async () => "",
  } );

  const result = await ui._transitionTask( ROW_ID, "queued", {} );

  assert.equal( result.ok, false, "an unreadable 202 body flipped the verdict back to success" );
  assert.equal( result.pending, true );
  assert.equal( result.ticketId, "", "no ticket could be read, so it must be empty" );
} );

test( "a 202 carrying NO ticket_id is still pending, with an empty ticket rather than \"undefined\"", async () => {
  const ui     = newUI( 202, { status: "awaiting_human_approval" } );
  const result = await ui._transitionTask( ROW_ID, "queued", {} );

  assert.equal( result.ok, false );
  assert.equal( result.pending, true );
  assert.equal( result.ticketId, "", "a missing ticket must be empty, never the text \"undefined\"" );
} );
