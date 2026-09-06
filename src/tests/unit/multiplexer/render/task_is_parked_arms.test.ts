// Row 87812328 — `taskIsParked` (render/taskListModel.ts), the TS twin of the
// store predicate `park_is_active()` and of the JS `_taskIsParked`.
//
// 🔴 THE TS TWIN HAD ZERO TESTS. The JS twin is well covered in
// `src/tests/unit/notifications_js/task_list_panel.test.ts` (`_taskIsParked`,
// underscore-prefixed) — a search for the bare name finds those and reads like
// coverage this function does not have. Two names, two functions, one contract.
//
// 🔴 EVERY ARM IS DRIVEN BOTH WAYS. A predicate that returned `false`
// unconditionally would satisfy every "→ false" assertion in this file, so each
// group carries its opposite and the file ends with a positive control that the
// function answers both ways at all.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/task_is_parked_arms.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";

import { taskIsParked } from "../../../../lupin_app/static/js/multiplexer/render/taskListModel";
import type { TaskItem } from "../../../../lupin_app/static/js/multiplexer/render/taskListModel";

const AT = ( y: number, mo: number, d: number, h: number, mi: number ): number =>
  Date.UTC( y, mo - 1, d, h, mi, 0 );

function parked( next_chase_ts: unknown ): TaskItem {
  return { id: "t1", status: "parked", next_chase_ts } as unknown as TaskItem;
}

// ---------------------------------------------------------------------------
// 1. KEYED ON `status`, NOT on park_reason.
// ---------------------------------------------------------------------------

test( "a non-parked status is never park-active, however future its chase", () => {
  const future = "2099-01-01T00:00:00Z";
  for ( const status of [ "queued", "in_progress", "blocked", "done", "dropped" ] ) {
    const row = { id: "t1", status, next_chase_ts: future } as unknown as TaskItem;
    assert.equal( taskIsParked( row, AT( 2026, 1, 1, 0, 0 ) ), false, `${ status } must not read as parked` );
  }
} );

test( "the SAME future chase on a parked row IS park-active — the control on the arm above", () => {
  // Without this the block above is satisfied by a function that always says false.
  assert.equal( taskIsParked( parked( "2099-01-01T00:00:00Z" ), AT( 2026, 1, 1, 0, 0 ) ), true );
} );

test( "a null/undefined row is false rather than a throw", () => {
  assert.equal( taskIsParked( null, AT( 2026, 1, 1, 0, 0 ) ), false );
  assert.equal( taskIsParked( undefined, AT( 2026, 1, 1, 0, 0 ) ), false );
} );

// ---------------------------------------------------------------------------
// 2. THE CHASE COMPARISON, INCLUDING ITS BOUNDARY.
// ---------------------------------------------------------------------------

test( "future chase → parked; past chase → NOT parked (expired, rejoined owed)", () => {
  const now = AT( 2026, 7, 22, 12, 0 );
  assert.equal( taskIsParked( parked( "2026-07-22T13:00:00Z" ), now ), true,  "future chase is park-active" );
  assert.equal( taskIsParked( parked( "2026-07-22T11:00:00Z" ), now ), false, "past chase has rejoined owed" );
} );

test( "chase EXACTLY now is NOT parked — the boundary is strict `>`", () => {
  const now = AT( 2026, 7, 22, 12, 0 );
  assert.equal( taskIsParked( parked( "2026-07-22T12:00:00Z" ), now ), false, "come due is owed, not parked" );
  // One millisecond later it flips — without this the assertion above is also
  // satisfied by a comparison that is broken in the other direction.
  assert.equal( taskIsParked( parked( "2026-07-22T12:00:00.001Z" ), now ), true );
} );

// ---------------------------------------------------------------------------
// 3. FAIL-LOUD-TOWARD-OWED — a malformed park is VISIBLE work, not a dimmed row.
// ---------------------------------------------------------------------------

test( "null, non-string, blank and unparseable chases are all NOT parked", () => {
  const now = AT( 2026, 7, 22, 12, 0 );
  for ( const bad of [ null, undefined, 12345, {}, "", "   ", "not-a-date", "2026-13-45T99:99:99Z" ] ) {
    assert.equal( taskIsParked( parked( bad ), now ), false, `${ JSON.stringify( bad ) } must fail toward owed` );
  }
} );

// ---------------------------------------------------------------------------
// 4. ZONE-LESS ⇒ UTC. The cross-language trap: Python replaces tzinfo with UTC,
//    `Date.parse( "…T12:00:00" )` resolves as LOCAL. Left alone the twins
//    disagree by the operator's UTC offset, silently, only for zone-less rows.
//
// ⚠️ BOTH SIDES ARE DRIVEN ON PURPOSE AND NEITHER ALONE IS ENOUGH. Dropping the
//    normalization shifts the parse by the runner's offset: WEST of UTC it moves
//    later (only the "now is after" case flips), EAST it moves earlier (only the
//    "now is before" case flips). The pair discriminates in either hemisphere.
//
// ⚠️ STATED LIMITATION: on a runner at UTC+0 the bare and Z forms parse
//    identically, so this arm is VACUOUS there — it cannot fail, and a green from
//    a UTC box is not evidence the normalization exists. The margins are 30
//    minutes, under any non-zero offset, so any offset at all makes it bite.
// ---------------------------------------------------------------------------

test( "a zone-less chase is read as UTC, not as local time", () => {
  const bare = "2030-06-01T12:00:00";
  assert.equal( taskIsParked( parked( bare ), AT( 2030, 6, 1, 12, 30 ) ), false, "12:00Z is behind 12:30Z" );
  assert.equal( taskIsParked( parked( bare ), AT( 2030, 6, 1, 11, 30 ) ), true,  "12:00Z is ahead of 11:30Z" );
} );

test( "a zone-less chase behaves IDENTICALLY to the same instant written with Z", () => {
  // The timezone-independent statement of the same rule: whatever the runner's
  // offset, these two spellings name one instant and must never disagree.
  for ( const now of [ AT( 2030, 6, 1, 11, 30 ), AT( 2030, 6, 1, 12, 30 ) ] ) {
    assert.equal(
      taskIsParked( parked( "2030-06-01T12:00:00" ), now ),
      taskIsParked( parked( "2030-06-01T12:00:00Z" ), now ),
      `bare and Z must agree at now=${ new Date( now ).toISOString() } ` +
      `(runner offset ${ new Date().getTimezoneOffset() } min)`,
    );
  }
} );

test( "an EXPLICIT offset is honoured rather than overwritten with Z", () => {
  // "12:00:00+02:00" is 10:00Z. A normalizer that appended Z blindly would read
  // it as 12:00Z and both assertions below would flip.
  const zoned = "2030-06-01T12:00:00+02:00";
  assert.equal( taskIsParked( parked( zoned ), AT( 2030, 6, 1, 10, 30 ) ), false, "10:00Z is behind 10:30Z" );
  assert.equal( taskIsParked( parked( zoned ), AT( 2030, 6, 1,  9, 30 ) ), true,  "10:00Z is ahead of 09:30Z" );
} );

test( "the compact +HHMM offset spelling is recognised too", () => {
  const zoned = "2030-06-01T12:00:00+0200";
  assert.equal( taskIsParked( parked( zoned ), AT( 2030, 6, 1, 10, 30 ) ), false );
  assert.equal( taskIsParked( parked( zoned ), AT( 2030, 6, 1,  9, 30 ) ), true  );
} );

// ---------------------------------------------------------------------------
// 5. THE CLOCK ARM — `now` omitted reads Date.now() at call time.
// ---------------------------------------------------------------------------

test( "with no `now` the real clock decides, both ways", () => {
  assert.equal( taskIsParked( parked( "2099-01-01T00:00:00Z" ) ), true,  "far future is parked" );
  assert.equal( taskIsParked( parked( "2000-01-01T00:00:00Z" ) ), false, "far past is not" );
} );

test( "a NaN `now` falls through to the real clock instead of being trusted", () => {
  // 🔴 THE QUIET FAILURE THIS GUARDS: every comparison against NaN is false, so a
  // trusted NaN would answer "not parked" for EVERY row — no throw, no warning,
  // the whole pane silently un-dimmed. The far-future row proves the fallback ran.
  assert.equal( taskIsParked( parked( "2099-01-01T00:00:00Z" ), Number.NaN ), true );
  assert.equal( taskIsParked( parked( "2000-01-01T00:00:00Z" ), Number.NaN ), false );
} );

test( "a non-finite `now` (Infinity) also falls through to the clock", () => {
  assert.equal( taskIsParked( parked( "2099-01-01T00:00:00Z" ), Number.POSITIVE_INFINITY ), true );
} );

// ---------------------------------------------------------------------------
// 6. POSITIVE CONTROL ON THE WHOLE FILE.
// ---------------------------------------------------------------------------

test( "POSITIVE CONTROL — the predicate answers both true and false", () => {
  const now = AT( 2026, 7, 22, 12, 0 );
  const answers = new Set( [
    taskIsParked( parked( "2026-07-22T13:00:00Z" ), now ),
    taskIsParked( parked( "2026-07-22T11:00:00Z" ), now ),
  ] );
  assert.equal( answers.size, 2, "a predicate stuck on one answer would satisfy half this file" );
} );
