// Finished Tasks — the pure model (row 470b7509).
//
// Every function here is pure, so every case is a fixture and a value. What is
// worth saying about the fixtures is that several of them are chosen so the
// RIGHT and WRONG implementations give DIFFERENT answers — a fixture where both
// agree measures nothing, whatever it asserts.
//
// Named examples, so a later reader does not "simplify" them back into silence:
//   · parseShownStatuses is fed an array whose ORDER differs from
//     FINISHED_STATUSES, because an implementation that returned the parsed
//     array verbatim and one that re-derived it from the canonical order agree
//     on every same-order fixture
//   · relativeAge is fed 60 and 61 minutes, because "1h" vs "1h1m" is the only
//     pair that separates a correct remainder from a dropped one
//   · clampWindowDays is fed 0 as well as -1, because 0 is the value a broken
//     read actually produces and it is the one that would render a window that
//     can never contain anything
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/finished_tasks_model.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  FINISHED_DEFAULT_SHOWN,
  FINISHED_STATUSES,
  FINISHED_UNMEASURED,
  FINISHED_WINDOW_DEFAULT_DAYS,
  FINISHED_WINDOW_MAX_DAYS,
  FINISHED_WINDOW_MIN_DAYS,
  actorPersona,
  clampWindowDays,
  finishedPaneState,
  mergeShownEvents,
  parseShownStatuses,
  relativeAge,
  transitionTarget,
  windowSinceIso,
  type FinishedTaskEvent,
} from "../../../../lupin_app/static/js/multiplexer/render/finishedTasksModel";

const NOW = Date.parse( "2026-09-07T20:00:00.000Z" );

function ev( over: Partial<FinishedTaskEvent> = {} ): FinishedTaskEvent {
  return {
    id         : 1,
    item_id    : "i1",
    ts         : "2026-09-07T19:00:00.000Z",
    actor      : "rio c079db30",
    transition : "in_progress->done",
    reason     : "shipped",
    title      : "a row",
    ...over,
  };
}

// ---------------------------------------------------------------------------
// The taxonomy — the denominator every other test in this file loops over
// ---------------------------------------------------------------------------

test( "the status taxonomy is the three TERMINAL statuses, in pill order, and NOT_APPROVED is not one", () => {
  assert.deepEqual( [ ...FINISHED_STATUSES ], [ "done", "dropped", "wont_fix" ] );
  // 🔴 `not_approved` is a held row that has not STARTED. The server's own
  // comment forbids adding it to TERMINAL_STATUSES, and a pane that showed it
  // as finished work would be reporting un-started rows as closed ones.
  assert.ok( !FINISHED_STATUSES.includes( "not_approved" ) );
  assert.ok( !FINISHED_STATUSES.includes( "parked" ) );
} );

test( "DONE is pre-lit ALONE — the ruled cold-start selection", () => {
  assert.deepEqual( [ ...FINISHED_DEFAULT_SHOWN ], [ "done" ] );
} );

// ---------------------------------------------------------------------------
// The window
// ---------------------------------------------------------------------------

test( "clampWindowDays holds the slider's declared range", () => {
  assert.equal( clampWindowDays( 1 ), 1 );
  assert.equal( clampWindowDays( 14 ), 14 );
  assert.equal( clampWindowDays( 7 ), 7 );
  assert.equal( clampWindowDays( "5" ), 5 );      // the DOM hands us strings
  assert.equal( clampWindowDays( 3.9 ), 3 );      // floored, never fractional days
  assert.equal( clampWindowDays( 99 ), FINISHED_WINDOW_MAX_DAYS );
  assert.equal( clampWindowDays( -1 ), FINISHED_WINDOW_MIN_DAYS );
} );

test( "🔴 AN UNUSABLE WINDOW FALLS BACK TO THE DEFAULT, NEVER TO ZERO", () => {
  // A zero-day window can never contain anything, so it would render as a
  // MEASURED "nothing finished" — the single reading this pane exists to
  // prevent. 0 is also the value `Number("")` and `Number(null)` produce, which
  // is exactly what a missing slider hands us.
  assert.equal( clampWindowDays( 0 ), FINISHED_WINDOW_MIN_DAYS );
  assert.equal( clampWindowDays( "" ), FINISHED_WINDOW_MIN_DAYS );
  assert.equal( clampWindowDays( NaN ), FINISHED_WINDOW_DEFAULT_DAYS );
  assert.equal( clampWindowDays( "abc" ), FINISHED_WINDOW_DEFAULT_DAYS );
  assert.equal( clampWindowDays( undefined ), FINISHED_WINDOW_DEFAULT_DAYS );
  // Infinity is NOT finite, so it lands with NaN on the DEFAULT rather than
  // being clamped to the maximum. That is the safer of the two: a garbage
  // read should not silently widen the window to a fortnight and fetch it.
  assert.equal( clampWindowDays( Infinity ), FINISHED_WINDOW_DEFAULT_DAYS );
  assert.equal( clampWindowDays( -Infinity ), FINISHED_WINDOW_DEFAULT_DAYS );
} );

test( "windowSinceIso converts DAYS to an instant — the x24 lives in exactly one place", () => {
  assert.equal( windowSinceIso( 1, NOW ), "2026-09-06T20:00:00.000Z" );
  assert.equal( windowSinceIso( 14, NOW ), "2026-08-24T20:00:00.000Z" );
  // and it clamps on the way through, so a bad slider cannot produce a bad wire
  assert.equal( windowSinceIso( 0, NOW ), windowSinceIso( 1, NOW ) );
} );

// ---------------------------------------------------------------------------
// Persistence polarity — the trap that fails invisibly
// ---------------------------------------------------------------------------

test( "🔴 THE PERSISTED VALUE IS THE SHOWN SET — POSITIVE POLARITY", () => {
  assert.deepEqual( [ ...parseShownStatuses( '["done"]' ) ], [ "done" ] );
  assert.deepEqual( [ ...parseShownStatuses( '["done","dropped"]' ) ], [ "done", "dropped" ] );
  assert.deepEqual( [ ...parseShownStatuses( '["wont_fix"]' ) ], [ "wont_fix" ] );

  // 🔴 THE DISCRIMINATING CASE. Under NEGATIVE polarity, `["dropped","wont_fix"]`
  // would mean "show done only". Under positive polarity it means "show dropped
  // and wont_fix". The two readings differ here and agree on `["done"]`, which
  // is why the single-element fixture above cannot carry this on its own.
  assert.deepEqual( [ ...parseShownStatuses( '["dropped","wont_fix"]' ) ], [ "dropped", "wont_fix" ] );
} );

test( "a persisted array is normalised to the canonical order, not echoed back", () => {
  // An implementation returning the parsed array verbatim passes every
  // same-order fixture. This one is deliberately out of order.
  assert.deepEqual( [ ...parseShownStatuses( '["wont_fix","done"]' ) ], [ "done", "wont_fix" ] );
} );

test( "a MISSING key means the spec default, never an empty selection", () => {
  assert.deepEqual( [ ...parseShownStatuses( null ) ], [ "done" ] );
} );

test( "a corrupt, wrong-typed or unusable value falls back the same way as a missing one", () => {
  for ( const raw of [ "not json", "{}", '"done"', "17", "null", "[]", '["nonsense"]' ] ) {
    assert.deepEqual( [ ...parseShownStatuses( raw ) ], [ "done" ],
      `${ raw } should fall back to the default rather than empty the pane` );
  }
} );

test( "an array from a FUTURE build naming an unknown status keeps its known members", () => {
  // Forward compatibility in the direction that matters: a newer client that
  // persisted a fourth status must not empty this client's pane, and must not
  // smuggle that status into a view this build cannot render a pill for.
  assert.deepEqual( [ ...parseShownStatuses( '["done","superseded"]' ) ], [ "done" ] );
} );

// ---------------------------------------------------------------------------
// The relative clock
// ---------------------------------------------------------------------------

test( "relativeAge renders minutes, hours, hours+minutes and days", () => {
  const at = ( ms: number ): string => relativeAge( new Date( NOW - ms ).toISOString(), NOW );
  assert.equal( at( 0 ), "0m" );
  assert.equal( at( 14 * 60_000 ), "14m" );
  assert.equal( at( 59 * 60_000 ), "59m" );
  // 60 vs 61 minutes is the ONLY pair that separates a correct remainder from a
  // dropped one — at 60 both implementations print "1h".
  assert.equal( at( 60 * 60_000 ), "1h" );
  assert.equal( at( 61 * 60_000 ), "1h1m" );
  assert.equal( at( 72 * 60_000 ), "1h12m" );
  assert.equal( at( 19 * 3600_000 ), "19h" );
  assert.equal( at( 3 * 24 * 3600_000 ), "3d" );
} );

test( "🔴 AN ABSENT OR UNPARSEABLE TIMESTAMP RENDERS THE EM DASH, NEVER 'NaNm'", () => {
  // A rendered NaN reads as a defect in the ROW, sending a reader after the
  // wrong thing. The em dash says the clock could not answer.
  assert.equal( relativeAge( null, NOW ), FINISHED_UNMEASURED );
  assert.equal( relativeAge( undefined, NOW ), FINISHED_UNMEASURED );
  assert.equal( relativeAge( "", NOW ), FINISHED_UNMEASURED );
  assert.equal( relativeAge( "not a date", NOW ), FINISHED_UNMEASURED );
} );

test( "a FUTURE timestamp clamps to 0m rather than printing a negative age", () => {
  // Browser/server clock skew is ordinary. "-3m" reads as a broken row.
  assert.equal( relativeAge( new Date( NOW + 5 * 60_000 ).toISOString(), NOW ), "0m" );
} );

// ---------------------------------------------------------------------------
// The two field readers
// ---------------------------------------------------------------------------

test( "WHO is the persona alone — the session id is noise at a glance", () => {
  assert.equal( actorPersona( "rio c079db30" ), "rio" );
  assert.equal( actorPersona( "mr" ), "mr" );
  assert.equal( actorPersona( "  maria  e2908f90 " ), "maria" );
} );

test( "an absent actor renders the em dash, not an empty cell", () => {
  // An empty cell is indistinguishable from a narrow column; the em dash says
  // "no actor was recorded", which is a fact about the row.
  assert.equal( actorPersona( null ), FINISHED_UNMEASURED );
  assert.equal( actorPersona( undefined ), FINISHED_UNMEASURED );
  assert.equal( actorPersona( "" ), FINISHED_UNMEASURED );
  assert.equal( actorPersona( "   " ), FINISHED_UNMEASURED );
} );

test( "transitionTarget takes the RIGHT-hand side — the status the row landed on", () => {
  assert.equal( transitionTarget( "in_progress->done" ), "done" );
  assert.equal( transitionTarget( "queued->wont_fix" ), "wont_fix" );
  // A malformed or absent transition renders untinted rather than throwing.
  assert.equal( transitionTarget( "done" ), "done" );
  assert.equal( transitionTarget( null ), "" );
  assert.equal( transitionTarget( undefined ), "" );
  assert.equal( transitionTarget( "" ), "" );
} );

// ---------------------------------------------------------------------------
// The merge
// ---------------------------------------------------------------------------

test( "only LIT statuses contribute rows, and the merge is newest-first", () => {
  const data = {
    done     : [ ev( { id: 1, ts: "2026-09-07T10:00:00Z", title: "d1" } ) ],
    dropped  : [ ev( { id: 2, ts: "2026-09-07T12:00:00Z", title: "x1" } ) ],
    wont_fix : [ ev( { id: 3, ts: "2026-09-07T11:00:00Z", title: "w1" } ) ],
  };
  assert.deepEqual( mergeShownEvents( data, [ "done" ] ).map( ( e ) => e.title ), [ "d1" ] );
  assert.deepEqual(
    mergeShownEvents( data, [ "done", "dropped", "wont_fix" ] ).map( ( e ) => e.title ),
    [ "x1", "w1", "d1" ],
    "rows must interleave by timestamp across statuses, not concatenate per status",
  );
} );

test( "an equal timestamp breaks on the event id, so repaints do not reshuffle rows", () => {
  const same = "2026-09-07T10:00:00Z";
  const data = { done: [ ev( { id: 7, ts: same, title: "older-id" } ), ev( { id: 9, ts: same, title: "newer-id" } ) ] };
  assert.deepEqual(
    mergeShownEvents( data, [ "done" ] ).map( ( e ) => e.title ),
    [ "newer-id", "older-id" ],
  );
} );

test( "an UNMEASURED status contributes nothing and does not throw", () => {
  assert.deepEqual( mergeShownEvents( {}, [ "done", "dropped" ] ), [] );
  assert.deepEqual( mergeShownEvents( { done: [] }, [ "done" ] ), [] );
} );

test( "a row with a null ts or a missing id sorts LAST rather than throwing", () => {
  // Both fields come off a database row. A torn one must degrade to the bottom
  // of the list, not take the sort down — and "" compares below every real ISO
  // instant, which is the property that puts it there.
  const good = ev( { id: 2, ts: "2026-09-07T10:00:00Z", title: "good" } );
  const torn = { ...ev( { title: "torn" } ), ts: null as unknown as string, id: undefined as unknown as number };
  assert.deepEqual( mergeShownEvents( { done: [ torn, good ] }, [ "done" ] ).map( ( e ) => e.title ),
    [ "good", "torn" ] );
  // Two torn rows must not throw on the id tiebreak either.
  const torn2 = { ...torn, title: "torn2" };
  assert.equal( mergeShownEvents( { done: [ torn, torn2 ] }, [ "done" ] ).length, 2 );
} );

test( "the merge does not mutate its input", () => {
  const rows = [ ev( { id: 1, ts: "2026-09-07T10:00:00Z" } ), ev( { id: 2, ts: "2026-09-07T12:00:00Z" } ) ];
  const before = rows.map( ( e ) => e.id );
  mergeShownEvents( { done: rows }, [ "done" ] );
  assert.deepEqual( rows.map( ( e ) => e.id ), before,
    "a sort in place would reorder the store's own cached array" );
} );

// ---------------------------------------------------------------------------
// The six states
// ---------------------------------------------------------------------------

test( "🔴 SIX STATES, AND EACH IS REACHABLE — the corpus, so a loop is not over nothing", () => {
  const cases: Array<[ string, Parameters<typeof finishedPaneState>[ 0 ] ]> = [
    [ "error",      { measuredStatuses: [],                 shown: [ "done" ], visibleCount: 0, error: "HTTP 500" } ],
    [ "unmeasured", { measuredStatuses: [],                 shown: [ "done" ], visibleCount: 0, error: null } ],
    [ "no_filter",  { measuredStatuses: [ "done" ],         shown: [],         visibleCount: 0, error: null } ],
    [ "empty",      { measuredStatuses: [ "done" ],         shown: [ "done" ], visibleCount: 0, error: null } ],
    [ "partial",    { measuredStatuses: [ "done" ],         shown: [ "done" ], visibleCount: 3, error: "HTTP 500 (dropped)" } ],
    [ "rows",       { measuredStatuses: [ ...FINISHED_STATUSES ], shown: [ "done" ], visibleCount: 3, error: null } ],
  ];
  assert.equal( cases.length, 6, "the pane has six states and this corpus must name all six" );
  for ( const [ expected, input ] of cases ) {
    assert.equal( finishedPaneState( input ), expected );
  }
} );

test( "🔴 A TOTAL FAILURE IS 'error', NOT A MEASURED ZERO — the ordering is load-bearing", () => {
  // This is the whole reason the pane exists. Reporting an unreachable stream as
  // "nothing finished" turns a broken fetch into an apparently quiet day, to the
  // person who asked for this pane BECAUSE work was going unfinished.
  assert.equal(
    finishedPaneState( { measuredStatuses: [], shown: [ "done" ], visibleCount: 0, error: "boom" } ),
    "error",
  );
  assert.notEqual(
    finishedPaneState( { measuredStatuses: [], shown: [ "done" ], visibleCount: 0, error: "boom" } ),
    "empty",
  );
} );

test( "a PARTIAL result is distinguishable from a complete one at the same row count", () => {
  // Same visible count, same shown set, same measured set — only the error
  // differs. An implementation that ignored `error` once rows exist would agree
  // with a correct one on every fixture where error is null.
  const base = { measuredStatuses: [ "done" ], shown: [ "done" ], visibleCount: 2 };
  assert.equal( finishedPaneState( { ...base, error: null } ), "rows" );
  assert.equal( finishedPaneState( { ...base, error: "HTTP 500 (dropped)" } ), "partial" );
} );
