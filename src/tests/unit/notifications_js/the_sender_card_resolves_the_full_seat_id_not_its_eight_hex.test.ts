// Legacy notifications.js — B4.4c: the sender card's 8-hex resolves to the FULL
// `cc_session_id` through the roster, and never gets sent as-is.
//
// Row 27760534, phase 2, slice 8. Plan §4.
//
// ─────────────────────── THE FIXTURE IS THE WHOLE MEASUREMENT ───────────────────────
//
// 🔴 EVERY ROSTER BELOW CONTAINS TWO SEATS WHOSE ids SHARE THEIR FIRST 8 CHARACTERS, AND
// THAT IS NOT DECORATION. The sender card carries only 8 hex characters (`parseSenderId`
// keeps the `#` suffix of `claude.code@lupin.deepily.ai#4cecf18a`), while the stream is
// keyed on the seat's FULL `stable_session_id`. With ONE seat in the fixture, or with
// seats whose prefixes differ, a client that resolves properly through the roster and a
// client that just sends the 8-hex return THE SAME ANSWER, and the test cannot tell them
// apart.
//
// That is the lesson the parity oracle records in its own header
// (`both_clients_issue_the_same_request_for_every_control.test.ts`): asserting a URL with
// the id `t1` made an encoded and an unencoded client byte-identical, so the test measured
// nothing in EITHER direction, and nobody noticed for as long as it stayed green.
//
// ───────────────────────── WHY "AMBIGUOUS" IS A REAL ARM ─────────────────────────
//
// A prefix is not a unique key. Once the fixture admits that two seats can share 8
// characters, "resolve by prefix" has a third outcome besides found and not-found, and the
// tempting implementation — take the first match — silently attaches the console to the
// WRONG seat's output. A console showing another seat's transcript, confidently, is worse
// than a console that does not open.
//
// CLAUDE.md § "Pointing at something": make the pointer self-checking, say it must match
// exactly once, and say what to do when it matches zero or twice — come back, never guess.
//
// Coverage (B4.10b): notifications.js cannot be instrumented by c8 — these tests load it
// by slicing the source through `vm.runInThisContext`, outside c8's import graph. Its real
// gate is behavioural: this tier plus E2E rows B4.7/B4.8. A named exclusion, not silence.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE             = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

type Resolution = { ccSessionId: string | null; reason: string };
type Seat       = { session_id: string; project?: string; transcript_watchable?: boolean };

let resolveSessionId : ( cardId: string | null, roster: Seat[] ) => Resolution;
let canWatch         : ( cardId: string | null, roster: Seat[] ) => boolean;
let newestAt         : string;

before( () => {
  if ( typeof globalThis.document === "undefined" ) {
    GlobalRegistrator.register();
  }
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  const classOnly  = fullSource.slice( 0, initIdx );

  vm.runInThisContext(
    classOnly +
    "\n;globalThis.__ccConsoleResolveSessionId = ccConsoleResolveSessionId;" +
    "\n;globalThis.__ccConsoleCanWatch         = ccConsoleCanWatch;" +
    "\n;globalThis.__CC_CONSOLE_NEWEST_AT      = CC_CONSOLE_NEWEST_AT;"
  );

  const g = globalThis as Record<string, unknown>;
  resolveSessionId = g.__ccConsoleResolveSessionId as typeof resolveSessionId;
  canWatch         = g.__ccConsoleCanWatch         as typeof canWatch;
  newestAt         = g.__CC_CONSOLE_NEWEST_AT      as string;

  assert.equal( typeof resolveSessionId, "function", "ccConsoleResolveSessionId loaded" );
  assert.equal( typeof canWatch,         "function", "ccConsoleCanWatch loaded" );
} );


// ── the fixture, built so it can discriminate ────────────────────────────────

// Two live seats sharing "4cecf18a" — the case a prefix match cannot decide.
const TWIN_A = "4cecf18a-66f7-442f-98f3-98d61d680654";
const TWIN_B = "4cecf18a-0000-4b1c-9d2e-111111111111";
// A seat with a prefix all its own.
const LONER  = "449359bc-c735-4970-8fc0-e83b635c8548";

function seat( id: string, watchable = true ): Seat {
  return { session_id : id, project : "lupin", transcript_watchable : watchable };
}

// THE CONTROL FOR THE FIXTURE ITSELF. If these two ever stop sharing a prefix, every
// ambiguity assertion below silently becomes a test of nothing.
test( "the fixture's twin seats really do share their first eight characters", () => {
  assert.equal(
    TWIN_A.slice( 0, 8 ), TWIN_B.slice( 0, 8 ),
    "the twin seats no longer share an 8-character prefix, so the ambiguity arms below " +
    "are no longer testing ambiguity"
  );
  assert.notEqual( TWIN_A, TWIN_B, "the twins must be DIFFERENT seats sharing a prefix" );
  assert.notEqual(
    LONER.slice( 0, 8 ), TWIN_A.slice( 0, 8 ),
    "the loner must not collide with the twins"
  );
} );


// ── the happy path sends the FULL id ─────────────────────────────────────────

test( "an unambiguous card id resolves to the seat's FULL stable id", () => {
  const roster = [ seat( LONER ), seat( TWIN_A ) ];
  const out    = resolveSessionId( LONER.slice( 0, 8 ), roster );

  assert.equal( out.reason, "ok" );
  assert.equal( out.ccSessionId, LONER, "the FULL stable id must be what gets watched" );
} );

test( "the resolved id is never the card's 8-hex", () => {
  const roster = [ seat( LONER ), seat( TWIN_A ) ];
  const cardId = LONER.slice( 0, 8 );
  const out    = resolveSessionId( cardId, roster );

  assert.notEqual(
    out.ccSessionId, cardId,
    "the 8-hex from the card was sent as the cc_session_id. The stream is keyed on the " +
    "FULL stable_session_id (§3); an 8-character key matches no seat server-side and the " +
    "pane opens to nothing while auth reports success."
  );
  assert.ok( ( out.ccSessionId as string ).length > 8 );
} );


// ── the arm the shared-prefix fixture exists for ─────────────────────────────

test( "a card id matching TWO seats resolves to nothing, rather than guessing", () => {
  const roster = [ seat( TWIN_A ), seat( TWIN_B ), seat( LONER ) ];
  const out    = resolveSessionId( "4cecf18a", roster );

  assert.equal(
    out.reason, "ambiguous-prefix",
    "an 8-character prefix shared by two live seats must be reported as ambiguous"
  );
  assert.equal(
    out.ccSessionId, null,
    "a seat was CHOSEN from an ambiguous prefix. Taking the first match attaches the " +
    "console to whichever seat happened to sort first and shows another seat's " +
    "transcript under this card's name — confidently, with nothing to notice it by."
  );
} );

test( "the ambiguous case does not silently pick either twin", () => {
  const roster = [ seat( TWIN_A ), seat( TWIN_B ) ];
  const out    = resolveSessionId( "4cecf18a", roster );

  assert.notEqual( out.ccSessionId, TWIN_A );
  assert.notEqual( out.ccSessionId, TWIN_B );
} );

test( "ordering the roster the other way gives the SAME refusal", () => {
  // A first-match implementation is order-dependent; a correct one is not. Two orders,
  // one answer — otherwise the assertion above passes for whichever order was written.
  const forward = resolveSessionId( "4cecf18a", [ seat( TWIN_A ), seat( TWIN_B ) ] );
  const reverse = resolveSessionId( "4cecf18a", [ seat( TWIN_B ), seat( TWIN_A ) ] );

  assert.deepEqual(
    forward, reverse,
    "the resolution changed when the roster order changed, which is the signature of a " +
    "first-match implementation"
  );
} );


// ── a chip with no roster row offers no watch ────────────────────────────────

test( "a card whose seat is absent from the roster resolves to nothing", () => {
  // The chip list and the fleet roster are DIFFERENT POPULATIONS (§4): `senders-visible`
  // is a per-user notification-sender list, so a chip can outlive its seat.
  const out = resolveSessionId( "deadbeef", [ seat( LONER ), seat( TWIN_A ) ] );
  assert.equal( out.reason, "not-in-roster" );
  assert.equal( out.ccSessionId, null );
} );

test( "a seat with no live transcript is not watchable", () => {
  const out = resolveSessionId( LONER.slice( 0, 8 ), [ seat( LONER, false ) ] );
  assert.equal( out.reason, "not-watchable" );
  assert.equal( out.ccSessionId, null );
} );

test( "a card with no session id at all resolves to nothing", () => {
  for ( const empty of [ null, "" ] ) {
    const out = resolveSessionId( empty, [ seat( LONER ) ] );
    assert.equal( out.reason, "no-card-id" );
    assert.equal( out.ccSessionId, null );
  }
} );

test( "an empty roster is handled, not thrown on", () => {
  assert.equal( resolveSessionId( "4cecf18a", [ ] ).reason, "not-in-roster" );
} );

test( "malformed roster rows are skipped rather than crashing the pane", () => {
  const roster = [
    null, undefined, { }, { session_id : 42 }, seat( LONER ),
  ] as unknown as Seat[];
  const out = resolveSessionId( LONER.slice( 0, 8 ), roster );
  assert.equal( out.reason, "ok" );
  assert.equal( out.ccSessionId, LONER );
} );


// ── the affordance follows the resolution, in all four refusing cases ────────

test( "the watch affordance is offered only when resolution succeeds", () => {
  const good = [ seat( LONER ) ];
  assert.equal( canWatch( LONER.slice( 0, 8 ), good ), true );

  assert.equal( canWatch( "4cecf18a", [ seat( TWIN_A ), seat( TWIN_B ) ] ), false, "ambiguous" );
  assert.equal( canWatch( "deadbeef", good ),                               false, "not in roster" );
  assert.equal( canWatch( LONER.slice( 0, 8 ), [ seat( LONER, false ) ] ),  false, "not watchable" );
  assert.equal( canWatch( null, good ),                                     false, "no card id" );
} );


// ── OSQ-9 is one constant, so a flip is one line ─────────────────────────────

test( "the newest-block edge is a single named constant", () => {
  // Mr. Radio's approval 2026-09-27: newest at the BOTTOM. Rick may still flip it, and the
  // multiplexer holds the same decision the same way — so this asserts the CONSTANT
  // exists and is one of the two legal values, not that it is forever "bottom".
  assert.ok(
    [ "top", "bottom" ].includes( newestAt ),
    `CC_CONSOLE_NEWEST_AT is "${newestAt}", which is neither "top" nor "bottom"`
  );
  assert.equal( newestAt, "bottom", "OSQ-9 as approved 2026-09-27: newest at the bottom" );
} );
