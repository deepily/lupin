// "Room for N more" — María's clause on the flow-ratio bar.
//
// 🔴 WHAT THESE TESTS ARE ACTUALLY FOR, and it is not the string. The number must come
// from the SERVER payload, because the server derives it by asking the ratio gate
// itself. The moment the browser computes it there are two pieces of code answering one
// question in two languages, and the board can tell an operator the gate is open while
// the gate refuses. Mr. Radio's ruling 2026-09-05: headroom is a PROJECTION of the gate,
// never a second gate.
//
// ⇒ So the load-bearing test here is "the clause ignores created/closed and reads only
// headroom" — it feeds counts under which every plausible local formula produces a
// DIFFERENT number, and asserts the render follows the payload field. A test that only
// checked "headroom 3 renders 3" would pass just as happily against a browser-side
// reimplementation that happened to agree today.
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

test( "the clause ignores created/closed and reads only headroom", () => {
  const ui = newUI();

  // Counts chosen so every plausible browser-side formula disagrees with the payload:
  //   the closed-form algebra  ceil( closed*1.0 - created ) - 1  ->   2
  //   created - closed                                          ->  -3
  //   closed - created                                          ->   3
  // The server says 7. Only a renderer that READS the field can produce 7.
  const clause = ui._flowRatioRoomText( { created: 10, closed: 13, ratio: 0.77, headroom: 7 } );

  assert.equal( clause, `  ${DOT} Room for 7 more`,
    "the rendered number must be the payload's headroom, not anything derived from the counts" );
} );

test( "a payload with counts but NO headroom renders no clause at all", () => {
  const ui = newUI();
  // The tempting failure: fall back to computing it locally when the field is absent.
  // A fallback is a second gate that only fires when nobody is looking.
  assert.equal( ui._flowRatioRoomText( { created: 10, closed: 13, ratio: 0.77 } ), "",
    "no headroom field must mean no clause — never a locally computed stand-in" );
} );

// ---------------------------------------------------------------------------
// The stated contract.
// ---------------------------------------------------------------------------

test( "zero headroom is SAID, not suppressed", () => {
  const ui = newUI();
  // A shut gate is exactly when the reader needs the number.
  assert.equal( ui._flowRatioRoomText( { created: 14, closed: 3, ratio: 4.67, headroom: 0 } ),
                `  ${DOT} Room for 0 more` );
} );

test( "one reads as 'Room for 1 more' with no special-casing", () => {
  const ui = newUI();
  assert.equal( ui._flowRatioRoomText( { created: 9, closed: 10, ratio: 0.9, headroom: 1 } ),
                `  ${DOT} Room for 1 more` );
} );

test( "a null headroom (no bound found) renders nothing", () => {
  const ui = newUI();
  // None over the wire means "effectively unbounded". A clause here would hand the
  // reader a target that does not exist.
  assert.equal( ui._flowRatioRoomText( { created: 0, closed: 10, ratio: 0, headroom: null } ), "" );
} );

test( "junk payloads are survived, not thrown on", () => {
  const ui = newUI();
  assert.equal( ui._flowRatioRoomText( null ),                   "" );
  assert.equal( ui._flowRatioRoomText( undefined ),              "" );
  assert.equal( ui._flowRatioRoomText( {} ),                     "" );
  assert.equal( ui._flowRatioRoomText( { headroom: "3" } ),      "" );
  assert.equal( ui._flowRatioRoomText( { headroom: NaN } ),      "" );
  assert.equal( ui._flowRatioRoomText( { headroom: Infinity } ), "" );
} );

// ---------------------------------------------------------------------------
// Integration with the header line.
// ---------------------------------------------------------------------------

test( "the clause appears on the header line after the percent", () => {
  const ui = newUI();
  const text = ui._formatFlowRatio( { created: 10, closed: 13, ratio: 0.77,
                                      headroom: 3, window_hours: 24 } );
  assert.equal( text, `10 created / 13 closed  over 1d = 77%  ${DOT} Room for 3 more` );
} );

test( "POSITIVE CONTROL: the same header line without headroom is otherwise identical", () => {
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
  // The counts describe the COMMITTED window and headroom is derived from those same
  // counts, so quoting it beside a different interval is the same lie the percent and
  // the counts are already withheld to avoid.
  const text = ui._formatFlowRatio( { created: 10, closed: 13, ratio: 0.77,
                                      headroom: 3, window_hours: 24 }, 3 );
  assert.ok( !text.includes( "Room for" ),
    "a provisional window must not quote a headroom measured over a different one" );
} );
