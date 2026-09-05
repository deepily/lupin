// The flow-ratio badge — three states: "Room for N more" | "FULL" | "CLOSE N".
//
// 🔴 WHAT THESE TESTS ARE ACTUALLY FOR, and it is not the string. The number must come
// from the SERVER payload, because the server derives it by asking the ratio gate
// itself. The moment the browser computes it there are two pieces of code answering one
// question in two languages, and the board can tell an operator the gate is open while
// the gate refuses. Mr. Radio's ruling 2026-09-05: the badge is a PROJECTION of the
// gate, never a second gate.
//
// ⇒ So the load-bearing test here is "the clause ignores created/closed and reads only
// the payload field" — it feeds counts under which every plausible local formula
// produces a DIFFERENT number, and asserts the render follows the field. A test that
// only checked "3 renders 3" would pass just as happily against a browser-side
// reimplementation that happened to agree today.
//
// 🔴 THE FIELD IS `room_for`, AND IT IS ONE LOWER THAN THE GATE WILL ACCEPT. Rick ruled
// this by keypress 2026-09-05 13:12 EDT on the option labelled, verbatim: "Keep your
// three states - badge under-reports by one." A real keypress, not a timeout default.
// The payload also carries `headroom` — the gate's exact number — and the badge
// deliberately does NOT render it. A test asserting the badge equals `headroom` would
// be asserting the ruling was not followed.
//
// ⇒ AND THAT IS WHY `FULL` IS BACK. It means N == 0, AT CAPACITY, STILL LEGAL. Under
// gate semantics it had no inputs at all; under the ruled loop semantics it is
// reachable, which is the whole substance of what Rick chose. Restoring the gate's
// exact number would delete it again — the two are one choice, not two.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/flow_ratio_room_clause.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE             = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext(
    fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;",
    { filename: NOTIFICATIONS_JS }
  );
} );

type RoomUI = Record<string, unknown> & {
  _flowRatioRoomText : ( payload: unknown ) => string;
  _formatFlowRatio   : ( payload: unknown, provisionalDays?: number ) => string;
};

function newUI(): RoomUI {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui = Object.create( Ctor.prototype ) as RoomUI;
  ui.debug = false;
  ui.log   = (): void => {};
  ui.error = (): void => {};
  return ui;
}

const DOT = "·";

// ---------------------------------------------------------------------------
// The structural test — the reason this file exists.
// ---------------------------------------------------------------------------

test( "the clause ignores created/closed and reads only room_for", () => {
  const ui = newUI();

  // Counts chosen so every plausible browser-side formula disagrees with the payload:
  //   the closed-form algebra  ceil( closed*1.0 - created ) - 1  ->   2
  //   created - closed                                          ->  -3
  //   closed - created                                          ->   3
  // The server says 7. Only a renderer that READS the field can produce 7.
  const clause = ui._flowRatioRoomText( { created: 10, closed: 13, ratio: 0.77, room_for: 7 } );

  assert.equal( clause, `  ${DOT} Room for 7 more`,
    "the rendered number must be the payload's room_for, not anything derived from the counts" );
} );

test( "a payload with counts but NO room_for renders no clause at all", () => {
  const ui = newUI();
  // The tempting failure: fall back to computing it locally when the field is absent.
  // A fallback is a second gate that only fires when nobody is looking.
  assert.equal( ui._flowRatioRoomText( { created: 10, closed: 13, ratio: 0.77 } ), "",
    "no room_for field must mean no clause — never a locally computed stand-in" );
} );

// ---------------------------------------------------------------------------
// The stated contract.
// ---------------------------------------------------------------------------

test( "a refusing gate renders CLOSE N, never a zero-room reading", () => {
  const ui = newUI();
  // The row is explicit: FULL means AT CAPACITY, STILL LEGAL; already-failing means
  // ILLEGAL NOW. Same number, different fact — they must not collapse.
  assert.equal( ui._flowRatioRoomText( { created: 14, closed: 3, ratio: 4.67,
                                         room_for: null, close_needed: 12 } ),
                `  ${DOT} CLOSE 12` );
} );

test( "CLOSE N is read from the payload too, not derived from the counts", () => {
  const ui = newUI();
  // Same structural point as the headroom test: counts under which no plausible local
  // formula yields 12.
  assert.equal( ui._flowRatioRoomText( { created: 3, closed: 99, ratio: 0.03,
                                         room_for: null, close_needed: 12 } ),
                `  ${DOT} CLOSE 12` );
} );

test( "a zero threshold no closure can open renders NO badge", () => {
  const ui = newUI();
  // close_needed null means there is no N. A badge naming an unreachable target is
  // worse than no badge.
  // 🔴 room_for is NULL here, not 0 — and the distinction is the whole point. The
  // server returns None whenever the gate already refuses, precisely so that 0 can mean
  // FULL (at capacity, still legal) and nothing else. A 0 here would render FULL on a
  // gate that is shut for everything.
  assert.equal( ui._flowRatioRoomText( { created: 10, closed: 13, ratio: 0.77,
                                         room_for: null, close_needed: null } ), "" );
} );

test( "CLOSE WINS over room when both are present — a breach never reads as capacity", () => {
  const ui = newUI();
  // The two partition in real payloads: the server returns room_for null whenever the
  // gate refuses. This pins the renderer's behaviour on a MALFORMED payload carrying
  // both, and the order is the control rather than the arithmetic — the row is explicit
  // that FULL means AT CAPACITY, STILL LEGAL while already-failing means ILLEGAL NOW,
  // so the failing reading must win any collision.
  assert.equal( ui._flowRatioRoomText( { room_for: 3, close_needed: 12 } ),
                `  ${DOT} CLOSE 12` );
} );

test( "one reads as 'Room for 1 more' with no special-casing", () => {
  const ui = newUI();
  assert.equal( ui._flowRatioRoomText( { created: 9, closed: 10, ratio: 0.9, room_for: 1 } ),
                `  ${DOT} Room for 1 more` );
} );

test( "a null room_for (no bound found) renders nothing", () => {
  const ui = newUI();
  // None over the wire means "effectively unbounded". A clause here would hand the
  // reader a target that does not exist.
  assert.equal( ui._flowRatioRoomText( { created: 0, closed: 10, ratio: 0, room_for: null } ), "" );
} );

test( "junk payloads are survived, not thrown on", () => {
  const ui = newUI();
  assert.equal( ui._flowRatioRoomText( null ),                   "" );
  assert.equal( ui._flowRatioRoomText( undefined ),              "" );
  assert.equal( ui._flowRatioRoomText( {} ),                     "" );
  assert.equal( ui._flowRatioRoomText( { room_for: "3" } ),      "" );
  assert.equal( ui._flowRatioRoomText( { room_for: NaN } ),      "" );
  assert.equal( ui._flowRatioRoomText( { room_for: Infinity } ), "" );
} );

// ---------------------------------------------------------------------------
// FULL — the state Rick's ruling brought back.
// ---------------------------------------------------------------------------

test( "room_for 0 renders FULL, in capitals, never 'Room for 0 more'", () => {
  const ui = newUI();
  // Ratified by keypress: "the edge display when n = 0 will be full in capital letters".
  // At created 9 / closed 10 / allow_below 1.00 the loop yields 0 while the gate would
  // still admit one more — which is exactly the divergence Rick chose.
  assert.equal( ui._flowRatioRoomText( { created: 9, closed: 10, ratio: 0.9, room_for: 0 } ),
                `  ${DOT} FULL` );
} );

test( "FULL is distinct from CLOSE — at capacity is not the same fact as illegal now", () => {
  const ui = newUI();
  const full  = ui._flowRatioRoomText( { room_for: 0 } );
  const close = ui._flowRatioRoomText( { room_for: null, close_needed: 1 } );
  assert.equal( full,  `  ${DOT} FULL` );
  assert.equal( close, `  ${DOT} CLOSE 1` );
  assert.notEqual( full, close,
    "collapsing these makes a healthy edge and a breach look identical" );
} );

test( "an idle board renders FULL — a consequence of the ruling, recorded not accidental", () => {
  const ui = newUI();
  // created 0 / closed 0: the gate admits exactly one create, so the loop yields 0.
  // Row f7c4f537 called this "surprising and probably wrong" while the question was
  // open; row ca08f05e was dropped as subsumed and Rick's keypress settled both. If
  // this ever reads wrong on screen it is a NEW decision, not a bug — which is why it
  // is pinned here rather than left to emerge.
  assert.equal( ui._flowRatioRoomText( { created: 0, closed: 0, ratio: null, room_for: 0 } ),
                `  ${DOT} FULL` );
} );

test( "🔴 THE BADGE IS NOT THE GATE'S NUMBER — headroom on the payload is ignored", () => {
  const ui = newUI();
  // The load-bearing guard for Rick's ruling. Both fields are present and they differ
  // by one, which is the normal case rather than a contrived one. A renderer that
  // "fixed" the off-by-one by reading `headroom` would pass every other test in this
  // file and fail this one.
  assert.equal( ui._flowRatioRoomText( { created: 10, closed: 13, ratio: 0.77,
                                         room_for: 2, headroom: 3 } ),
                `  ${DOT} Room for 2 more`,
    "the badge must render room_for (loop semantics, ruled) and never headroom (the gate's exact number)" );
} );

// ---------------------------------------------------------------------------
// Integration with the header line.
// ---------------------------------------------------------------------------

test( "the clause appears on the header line after the percent", () => {
  const ui = newUI();
  const text = ui._formatFlowRatio( { created: 10, closed: 13, ratio: 0.77,
                                      room_for: 3, close_needed: 0, window_hours: 24 } );
  assert.equal( text, `10 created / 13 closed  over 1d = 77%  ${DOT} Room for 3 more` );
} );

test( "POSITIVE CONTROL: the same header line without room_for is otherwise identical", () => {
  // Without this, the test above could pass because _formatFlowRatio returned "" for an
  // unrelated reason and the clause assertion would be checking nothing. This pins that
  // the ONLY difference between the two renders is the clause.
  const ui = newUI();
  const withNone = ui._formatFlowRatio( { created: 10, closed: 13, ratio: 0.77, window_hours: 24 } );
  assert.equal( withNone, "10 created / 13 closed  over 1d = 77%" );
  assert.ok( withNone.length > 0, "the control render must be non-empty, or it proves nothing" );
} );

test( "a DRAGGING window slider withholds the clause with everything else", () => {
  const ui = newUI();
  // The counts describe the COMMITTED window and room_for is derived from those same
  // counts, so quoting it beside a different interval is the same lie the percent and
  // the counts are already withheld to avoid.
  const text = ui._formatFlowRatio( { created: 10, closed: 13, ratio: 0.77,
                                      room_for: 3, window_hours: 24 }, 3 );
  assert.ok( !text.includes( "Room for" ),
    "a provisional window must not quote a room_for measured over a different one" );
} );
