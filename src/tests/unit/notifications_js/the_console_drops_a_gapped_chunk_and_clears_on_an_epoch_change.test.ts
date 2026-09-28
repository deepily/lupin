// Legacy notifications.js — the LEGACY TWINS of B4.1 (gap -> REST repair), B4.2 (epoch
// clear, including `epoch_mismatch`) and B4.4 (unwatch before watch, whole lifecycle).
//
// Row 27760534, phase 2, slice 8. Plan §3, §4.
//
// §4 rules the legacy client ships the FULL feature, and states the two clients SHARE NO
// CODE — the multiplexer is a TS bundle with a `stores/` layer, this is plain script with
// module-level state (Mr. Radio's ruling). So these tests are not evidence of parity, they
// are its only MECHANISM. Written as twins of the multiplexer's on purpose.
//
// ─────────────────────── WHY A GAPPED CHUNK IS DROPPED ───────────────────────
//
// Not deferred, not buffered — dropped, with a REST repair from `last_next_offset`.
// Rendering a chunk that does not abut what we already hold would SPLICE the transcript:
// the reader gets a continuous-looking narrative with a hole in the middle of it. A hole
// you can see is recoverable. One you cannot is not, and a console exists to be trusted
// about what happened.
//
// ─────────────────── WHY AN EPOCH CHANGE CLEARS RATHER THAN REPAIRS ───────────────────
//
// A gap is a hole in a file. An epoch change means the FILE IS GONE — a `/clear` or a
// rotation. Every offset we hold indexes into something that no longer exists, so there is
// nothing to repair and nothing to reconcile; there is only a buffer to discard. Repairing
// instead would fetch from an offset that means something different now.
//
// `epoch_mismatch` is the same situation arriving by a different door: the first frame a
// reconnecting client gets after a `/clear` it did not see. §3/T15 is explicit that the
// server must not silently rebase, and the client must not read the reply as a
// continuation — a silent rebase hands the client a whole new file labelled as its own.

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE             = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

type Outcome  = { action: string; repairFrom: number | null; blocksAdded?: number };
type Envelope = { type: string; cc_session_id: string; from_offset?: number; file_epoch?: unknown };

let beginWatch : ( id: string | null ) => Envelope[];
let endWatch   : ( ) => Envelope[];
let applyChunk : ( chunk: unknown ) => Outcome;
let applyState : ( frame: unknown ) => Outcome;
let state      : Record<string, unknown>;

const SEAT  = "4cecf18a-66f7-442f-98f3-98d61d680654";
const OTHER = "449359bc-c735-4970-8fc0-e83b635c8548";
const EPOCH = "57238c9d-c227-469e-b707-13b7752a7399";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );

  vm.runInThisContext(
    fullSource.slice( 0, initIdx ) +
    "\n;globalThis.__ccBeginWatch = ccConsoleBeginWatch;" +
    "\n;globalThis.__ccEndWatch   = ccConsoleEndWatch;" +
    "\n;globalThis.__ccApplyChunk = ccConsoleApplyChunk;" +
    "\n;globalThis.__ccApplyState = ccConsoleApplyState;" +
    "\n;globalThis.__ccState      = ccConsoleState;"
  );
  const g    = globalThis as Record<string, unknown>;
  beginWatch = g.__ccBeginWatch as typeof beginWatch;
  endWatch   = g.__ccEndWatch   as typeof endWatch;
  applyChunk = g.__ccApplyChunk as typeof applyChunk;
  applyState = g.__ccApplyState as typeof applyState;
  state      = g.__ccState      as Record<string, unknown>;

  for ( const [ name, fn ] of Object.entries( { beginWatch, endWatch, applyChunk, applyState } ) ) {
    assert.equal( typeof fn, "function", `${name} loaded` );
  }
} );

// The state is module-level by ruling, so it persists between tests — reset it explicitly
// rather than letting one test's residue become another's precondition.
beforeEach( () => { endWatch(); } );

function chunk( over: Partial<Record<string, unknown>> = { } ) {
  return {
    cc_session_id : SEAT, file_epoch : EPOCH, offset : 0, next_offset : 100,
    blocks : [ { kind : "text", text : "hello" } ], ts : "2026-09-27T00:00:00Z", ...over,
  };
}


// ── the watch lifecycle: B4.4, over the WHOLE lifecycle ──────────────────────

test( "opening a console on a seat sends exactly one watch and no unwatch", () => {
  const out = beginWatch( SEAT );
  assert.deepEqual( out.map( e => e.type ), [ "cc_transcript_watch" ] );
  assert.equal( out[ 0 ].cc_session_id, SEAT );
  assert.equal( out[ 0 ].from_offset, 0, "a watch must name where it starts" );
  assert.equal( out[ 0 ].file_epoch, null, "a first watch sends a null epoch and learns it" );
} );

test( "switching seats UNWATCHES the old one BEFORE watching the new one", () => {
  beginWatch( SEAT );
  const out = beginWatch( OTHER );

  assert.deepEqual(
    out.map( e => e.type ), [ "cc_transcript_unwatch", "cc_transcript_watch" ],
    "the unwatch must come FIRST. If it trailed the watch, a seat switch would hold two " +
    "live subscriptions for a moment and the pane would interleave two transcripts."
  );
  assert.equal( out[ 0 ].cc_session_id, SEAT,  "the unwatch names the OLD seat" );
  assert.equal( out[ 1 ].cc_session_id, OTHER, "the watch names the NEW seat" );
} );

test( "re-opening the SAME seat is a no-op, not an unwatch-rewatch churn", () => {
  beginWatch( SEAT );
  assert.deepEqual( beginWatch( SEAT ), [ ], "a healthy subscription was dropped and rebuilt" );
} );

test( "closing the console leaves ZERO live watches", () => {
  beginWatch( SEAT );
  const out = endWatch();
  assert.deepEqual( out.map( e => e.type ), [ "cc_transcript_unwatch" ] );
  assert.equal( state.watchedCcSessionId, null );
  assert.deepEqual( endWatch(), [ ], "closing an already-closed console must send nothing" );
} );

test( "switching seats clears the previous seat's buffer", () => {
  beginWatch( SEAT );
  applyChunk( chunk() );
  assert.equal( ( state.blocks as unknown[] ).length, 1 );

  beginWatch( OTHER );
  assert.equal(
    ( state.blocks as unknown[] ).length, 0,
    "the old seat's blocks survived a seat switch — the pane would show one seat's output " +
    "under another seat's name"
  );
  assert.equal( state.lastNextOffset, null );
} );


// ── B4.1's twin: the gap rule ────────────────────────────────────────────────

test( "a contiguous chunk is appended", () => {
  beginWatch( SEAT );
  const out = applyChunk( chunk( { offset : 0, next_offset : 100 } ) );
  assert.equal( out.action, "appended" );
  assert.equal( out.blocksAdded, 1 );
  assert.equal( state.lastNextOffset, 100 );
} );

test( "chunks that abut keep appending", () => {
  beginWatch( SEAT );
  applyChunk( chunk( { offset : 0,   next_offset : 100 } ) );
  const out = applyChunk( chunk( { offset : 100, next_offset : 250 } ) );
  assert.equal( out.action, "appended" );
  assert.equal( state.lastNextOffset, 250 );
} );

test( "a GAPPED chunk is dropped and repaired from last_next_offset", () => {
  beginWatch( SEAT );
  applyChunk( chunk( { offset : 0, next_offset : 100 } ) );

  const out = applyChunk( chunk( { offset : 900, next_offset : 1000 } ) );
  assert.equal( out.action, "gap" );
  assert.equal(
    out.repairFrom, 100,
    "the repair must start at last_next_offset — where our record actually ends — not at " +
    "the gapped chunk's own offset, which would leave the hole in place"
  );
} );

test( "the dropped chunk's blocks are NOT rendered", () => {
  beginWatch( SEAT );
  applyChunk( chunk( { offset : 0, next_offset : 100 } ) );
  const before = ( state.blocks as unknown[] ).length;

  applyChunk( chunk( { offset : 900, next_offset : 1000,
                       blocks : [ { kind : "text", text : "SPLICED" } ] } ) );

  assert.equal(
    ( state.blocks as unknown[] ).length, before,
    "a gapped chunk's blocks were appended. That splices the transcript: the reader sees a " +
    "continuous narrative with a hole in it and nothing to indicate the hole."
  );
  assert.equal( state.lastNextOffset, 100, "a dropped chunk must not advance the offset" );
} );

test( "a gap does not clear what was already received", () => {
  // Dropping the CHUNK is not discarding the RECORD. Clearing here would turn a repairable
  // hole into a full re-fetch, and would look identical to an epoch change.
  beginWatch( SEAT );
  applyChunk( chunk( { offset : 0, next_offset : 100 } ) );
  applyChunk( chunk( { offset : 900, next_offset : 1000 } ) );
  assert.equal( ( state.blocks as unknown[] ).length, 1 );
} );


// ── B4.2's twin: epoch change and epoch_mismatch ─────────────────────────────

test( "an epoch change CLEARS the buffer and the offset", () => {
  beginWatch( SEAT );
  applyChunk( chunk( { offset : 0, next_offset : 100 } ) );

  const out = applyChunk( chunk( { file_epoch : "a-different-file", offset : 0, next_offset : 50 } ) );
  assert.equal( out.action, "epoch-changed" );
  assert.equal( ( state.blocks as unknown[] ).length, 0, "pre-change blocks survived the epoch change" );
  assert.equal( state.lastNextOffset, null );
} );

test( "an epoch change REPAIRS FROM ZERO, not from the old offset", () => {
  beginWatch( SEAT );
  applyChunk( chunk( { offset : 0, next_offset : 100 } ) );
  const out = applyChunk( chunk( { file_epoch : "a-different-file", offset : 0, next_offset : 50 } ) );

  assert.equal(
    out.repairFrom, 0,
    "an epoch change must re-fetch the backlog from the start of the NEW file. Repairing " +
    "from the old last_next_offset indexes into a file that no longer exists, so the " +
    "number means something different now."
  );
} );

test( "epoch_mismatch clears and re-fetches — it is never a continuation", () => {
  beginWatch( SEAT );
  applyChunk( chunk( { offset : 0, next_offset : 100 } ) );

  const out = applyState( { cc_session_id : SEAT, state : "epoch_mismatch", file_epoch : "new-file" } );
  assert.equal( out.action, "cleared" );
  assert.equal( out.repairFrom, 0 );
  assert.equal(
    ( state.blocks as unknown[] ).length, 0,
    "blocks from the stale epoch survived an epoch_mismatch. Treating that reply as a " +
    "continuation hands the client a whole new file labelled as its own (§3, T15)."
  );
  assert.equal( state.fileEpoch, "new-file", "the client must adopt the epoch the server named" );
} );

test( "a rotation behaves like an epoch mismatch, for the same reason", () => {
  beginWatch( SEAT );
  applyChunk( chunk( { offset : 0, next_offset : 100 } ) );
  const out = applyState( { cc_session_id : SEAT, state : "rotated", file_epoch : "rotated-file" } );
  assert.equal( out.action, "cleared" );
  assert.equal( out.repairFrom, 0 );
} );

test( "`ended` leaves the received record on screen", () => {
  // The seat is gone; what it printed is not. Clearing here would delete the transcript at
  // the exact moment it became the only remaining record of the session.
  beginWatch( SEAT );
  applyChunk( chunk( { offset : 0, next_offset : 100 } ) );
  const out = applyState( { cc_session_id : SEAT, state : "ended" } );
  assert.equal( out.action, "ended" );
  assert.equal( ( state.blocks as unknown[] ).length, 1 );
} );

test( "`live` does not disturb the buffer", () => {
  beginWatch( SEAT );
  applyChunk( chunk( { offset : 0, next_offset : 100 } ) );
  assert.equal( applyState( { cc_session_id : SEAT, state : "live" } ).action, "live" );
  assert.equal( ( state.blocks as unknown[] ).length, 1 );
} );

test( "an unknown state is reported rather than guessed at", () => {
  beginWatch( SEAT );
  const out = applyState( { cc_session_id : SEAT, state : "a_state_invented_by_this_test" } );
  assert.equal( out.action, "unknown-state" );
  assert.equal( out.repairFrom, null, "an unrecognised state must not trigger a re-fetch" );
} );


// ── frames for other seats, and malformed frames ─────────────────────────────

test( "a chunk for a seat we are NOT watching is ignored, never rendered", () => {
  beginWatch( SEAT );
  const out = applyChunk( chunk( { cc_session_id : OTHER } ) );
  assert.equal( out.action, "not-watched" );
  assert.equal( ( state.blocks as unknown[] ).length, 0 );
} );

test( "a chunk arriving with no console open is ignored", () => {
  const out = applyChunk( chunk() );
  assert.equal( out.action, "not-watched" );
} );

test( "a state frame for another seat is ignored", () => {
  beginWatch( SEAT );
  assert.equal(
    applyState( { cc_session_id : OTHER, state : "epoch_mismatch" } ).action, "not-watched"
  );
} );

test( "malformed frames are tolerated, not thrown on", () => {
  beginWatch( SEAT );
  for ( const junk of [ null, undefined, 42, "a string", [ ] ] ) {
    assert.equal( applyChunk( junk ).action, "malformed" );
    assert.equal( applyState( junk ).action, "malformed" );
  }
} );

test( "an ARRAY is malformed, not mistaken for another seat's traffic", () => {
  // 🔴 THIS ARM FOUND A REAL DEFECT IN THE FIRST CUT OF THIS FILE'S IMPLEMENTATION.
  // `typeof [] === "object"` and `[]` is truthy, so a bare typeof guard accepted an array
  // as a well-formed frame. It then fell through to the seat comparison, where
  // `undefined !== SEAT` reported it as "not-watched" — traffic for a different seat.
  //
  // That is the worse of the two wrong answers: "not-watched" is the REASSURING
  // diagnosis. It says the frame was fine and simply not ours, so nobody investigates,
  // while "malformed" says the wire produced something impossible. Fixed by
  // `ccConsoleIsFrame`, which is a named predicate precisely so all three call sites
  // share one definition of "is a frame".
  beginWatch( SEAT );
  assert.equal( applyChunk( [ ] ).action, "malformed" );
  assert.equal( applyState( [ ] ).action, "malformed" );
  assert.equal( applyChunk( [ { cc_session_id : SEAT } ] ).action, "malformed" );
} );

test( "a chunk with no blocks array advances the offset without rendering", () => {
  beginWatch( SEAT );
  const out = applyChunk( chunk( { blocks : undefined, offset : 0, next_offset : 100 } ) );
  assert.equal( out.action, "appended" );
  assert.equal( out.blocksAdded, 0 );
  assert.equal( state.lastNextOffset, 100 );
} );

test( "an EMPTY block in a chunk is still appended", () => {
  // The same rule as ccConsoleShouldRender, asserted at the chunk layer too — a filter
  // added here would bypass that function entirely and its own test would stay green.
  beginWatch( SEAT );
  const out = applyChunk( chunk( { blocks : [ { kind : "thinking", text : "" } ] } ) );
  assert.equal( out.blocksAdded, 1, "an empty thinking block was dropped at the chunk layer" );
} );
