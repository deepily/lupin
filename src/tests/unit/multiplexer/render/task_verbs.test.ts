// Guard — the multiplexer's verb table (row-control conversion, 2026.09.02).
//
// EVERY GUARD HERE STATES ITS DENOMINATOR. That is not decoration. The sweep
// written up in src/rnd/v0.2.1/2026.09.02-a-guard-that-declines-to-run-and-
// reports-success.md found guards that could not FAIL because they never
// located anything: a loop over an empty corpus passes every assertion inside
// it, and a substring check over a whole file cannot tell a live cell from a
// comment. So each sweep below asserts how many things it found, and asserts
// that count is at least N — with N measured off the tree, and its source named
// in the assertion message rather than chosen to make the number pass.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  TASK_VERBS,
  transitionExtras,
  verbDateComplaint,
  verbLabel,
  verbLegality,
  verbNeeds,
  verbReasonComplaint,
} from "../../../../lupin_app/static/js/multiplexer/render/taskVerbs";

// The denominator, measured off the tree: notifications.js `_verbNeeds` carries
// exactly five verbs (park, drop, demote, wont_fix, approve) and this table is
// its port. Five is the floor every sweep below is checked against.
const VERB_FLOOR = 5;

// The statuses a real row can be in, from taskListModel's STATUS_RANK plus the
// two the board adds (parked, not_approved) and the terminal wont_fix. Named
// here so a legality sweep has a stated corpus rather than an ad-hoc list.
const STATUS_CORPUS: ReadonlyArray<string> = [
  "queued", "in_progress", "claimed", "review", "blocked",
  "parked", "not_approved", "done", "dropped", "wont_fix",
];
const TERMINAL_IN_CORPUS: ReadonlyArray<string> = [ "done", "dropped", "wont_fix" ];

// ---------------------------------------------------------------------------
// The table itself
// ---------------------------------------------------------------------------

test("TASK_VERBS: five verbs, in the fixed render order the board uses", () => {
  assert.ok( TASK_VERBS.length >= VERB_FLOOR,
    `positive control: the port of notifications.js _verbNeeds carries ${VERB_FLOOR} verbs; found ${TASK_VERBS.length}` );
  assert.deepEqual( Array.from( TASK_VERBS ), [ "park", "drop", "demote", "wont_fix", "approve" ] );
});

test("verbNeeds: every verb in TASK_VERBS resolves, and the sweep says how many it resolved", () => {
  const resolved = TASK_VERBS.filter( ( v ) => verbNeeds( v ) !== null );
  assert.equal( resolved.length, TASK_VERBS.length,
    `every verb must resolve; ${resolved.length} of ${TASK_VERBS.length} did` );
  assert.ok( resolved.length >= VERB_FLOOR,
    `positive control: at least ${VERB_FLOOR} verbs must resolve, else this sweep asserted nothing` );
});

test("verbNeeds: an unknown verb and the empty choice both return null", () => {
  assert.equal( verbNeeds( "" ), null );
  assert.equal( verbNeeds( null ), null );
  assert.equal( verbNeeds( undefined ), null );
  assert.equal( verbNeeds( "delete" ), null );
});

test("verbNeeds: each verb's to_status is the one the server transition expects", () => {
  // Copied from notifications.js, not re-derived — a second derivation is a
  // second chance to get a status wrong.
  const EXPECTED: Readonly<Record<string, string>> = {
    park: "parked", drop: "dropped", demote: "not_approved",
    wont_fix: "wont_fix", approve: "queued",
  };
  const checked = TASK_VERBS.filter( ( v ) => EXPECTED[ v ] !== undefined );
  assert.equal( checked.length, TASK_VERBS.length, "every verb must have an expected status" );
  assert.ok( checked.length >= VERB_FLOOR, `positive control: ${VERB_FLOOR} statuses expected, ${checked.length} checked` );
  for ( const v of checked ) assert.equal( verbNeeds( v )!.status, EXPECTED[ v ], `${v} posts the wrong to_status` );
});

test("verbNeeds: exactly one verb is terminal, and it is won't-fix", () => {
  const terminal = TASK_VERBS.filter( ( v ) => verbNeeds( v )!.terminal );
  assert.deepEqual( terminal, [ "wont_fix" ] );
});

test("verbNeeds: exactly two verbs require a date, and each labels it for ITSELF", () => {
  const dated = TASK_VERBS.filter( ( v ) => verbNeeds( v )!.date );
  assert.deepEqual( dated, [ "park", "demote" ] );
  // The labels must DIFFER: a park's date and a demote's date are different
  // promises, and one shared caption is the defect Rick named ("I really have no
  // idea what the date chooser is for").
  assert.equal( verbNeeds( "park" )!.dateLabel, "Chase me again on" );
  assert.equal( verbNeeds( "demote" )!.dateLabel, "Triage this by" );
  assert.notEqual( verbNeeds( "park" )!.dateLabel, verbNeeds( "demote" )!.dateLabel );
});

test("verbNeeds: approve is the only verb that takes no reason", () => {
  const reasonless = TASK_VERBS.filter( ( v ) => !verbNeeds( v )!.reason );
  assert.deepEqual( reasonless, [ "approve" ] );
});

test("verbNeeds: no two verbs share a reason placeholder", () => {
  const placeholders = TASK_VERBS.map( ( v ) => verbNeeds( v )!.placeholder );
  assert.ok( placeholders.length >= VERB_FLOOR,
    `positive control: ${placeholders.length} placeholders collected, floor ${VERB_FLOOR}` );
  assert.equal( new Set( placeholders ).size, placeholders.length,
    "one shared box must not flatten five different obligations into one caption" );
});

// ---------------------------------------------------------------------------
// Complaints — five verbs share one box and must not share one complaint
// ---------------------------------------------------------------------------

test("verbReasonComplaint: each reason-taking verb earns its OWN sentence", () => {
  const needReason = TASK_VERBS.filter( ( v ) => verbNeeds( v )!.reason );
  assert.equal( needReason.length, 4, "four verbs take a reason; approve does not" );
  const complaints = needReason.map( verbReasonComplaint );
  assert.equal( new Set( complaints ).size, complaints.length,
    `four distinct complaints required; got ${new Set( complaints ).size}` );
  // A generic sentence would satisfy the uniqueness check above only if all four
  // differed, so pin the two that carry real instruction.
  assert.match( verbReasonComplaint( "park" ), /quote/i );
  assert.match( verbReasonComplaint( "demote" ), /triage/i );
});

test("verbReasonComplaint: an unknown verb falls back rather than returning undefined", () => {
  assert.equal( verbReasonComplaint( "nonsense" ), "A reason is required." );
});

test("verbDateComplaint: park and demote say different things about a date", () => {
  assert.match( verbDateComplaint( "park" ), /chase date/i );
  assert.match( verbDateComplaint( "demote" ), /triage-by date/i );
  assert.notEqual( verbDateComplaint( "park" ), verbDateComplaint( "demote" ) );
});

test("verbLabel: every verb has a human name; an unknown one returns itself", () => {
  const labelled = TASK_VERBS.filter( ( v ) => verbLabel( v ) !== v );
  assert.ok( labelled.length >= VERB_FLOOR - 1,
    `at least ${VERB_FLOOR - 1} verbs must be relabelled (drop/park are already words); ${labelled.length} were` );
  assert.equal( verbLabel( "wont_fix" ), "Won't fix" );
  assert.equal( verbLabel( "nonsense" ), "nonsense" );
});

// ---------------------------------------------------------------------------
// Legality — the sweep with the largest denominator, so it states it loudest
// ---------------------------------------------------------------------------

test("verbLegality: returns one entry per verb, in TASK_VERBS order, for EVERY status in the corpus", () => {
  assert.ok( STATUS_CORPUS.length >= 10,
    `positive control: the corpus is the 5 STATUS_RANK statuses + parked + not_approved + 3 terminal; found ${STATUS_CORPUS.length}` );
  let swept = 0;
  for ( const s of STATUS_CORPUS ) {
    const entries = verbLegality( s );
    assert.equal( entries.length, TASK_VERBS.length, `${s}: wrong number of options` );
    assert.deepEqual( entries.map( ( e ) => e.verb ), Array.from( TASK_VERBS ), `${s}: wrong option order` );
    swept += 1;
  }
  assert.equal( swept, STATUS_CORPUS.length, `swept ${swept} of ${STATUS_CORPUS.length} statuses` );
});

test("verbLegality: a terminal row offers NOTHING, and every option says why", () => {
  assert.ok( TERMINAL_IN_CORPUS.length === 3,
    "positive control: three terminal statuses — done, dropped, wont_fix" );
  let checked = 0;
  for ( const s of TERMINAL_IN_CORPUS ) {
    const entries = verbLegality( s );
    assert.equal( entries.filter( ( e ) => e.enabled ).length, 0, `${s}: a terminal row offered a live verb` );
    for ( const e of entries ) {
      assert.match( e.why, /append-only/, `${s}/${e.verb}: greyed without saying why` );
      assert.ok( e.why.includes( s ), `${s}/${e.verb}: the refusal must name the row's OWN status` );
    }
    checked += 1;
  }
  assert.equal( checked, 3, `checked ${checked} of 3 terminal statuses` );
});

test("verbLegality: wont_fix is terminal HERE — the multiplexer's model was missing it", () => {
  // Guard on the taskListModel fix that this conversion required. Before it,
  // TERMINAL_STATUSES was {done, dropped} and a won't-fixed row counted as work
  // still owed, so the cell would have offered five live transitions out of a
  // row the server refuses every edge out of.
  const enabled = verbLegality( "wont_fix" ).filter( ( e ) => e.enabled );
  assert.equal( enabled.length, 0,
    `a wont_fix row must offer nothing; it offered ${enabled.map( ( e ) => e.verb ).join( ", " )}` );
});

test("verbLegality: park is live ONLY from queued and in_progress", () => {
  const live = STATUS_CORPUS.filter( ( s ) => verbLegality( s ).find( ( e ) => e.verb === "park" )!.enabled );
  assert.deepEqual( live, [ "queued", "in_progress" ] );
  assert.match( verbLegality( "blocked" ).find( ( e ) => e.verb === "park" )!.why, /queued or in progress/ );
});

test("verbLegality: approve is live ONLY on a held row; demote on every OTHER open row", () => {
  const approveLive = STATUS_CORPUS.filter( ( s ) => verbLegality( s ).find( ( e ) => e.verb === "approve" )!.enabled );
  const demoteLive  = STATUS_CORPUS.filter( ( s ) => verbLegality( s ).find( ( e ) => e.verb === "demote" )!.enabled );
  assert.deepEqual( approveLive, [ "not_approved" ] );
  // Opposite ends of one door: the two sets must not intersect, and together
  // they must cover every open status exactly once.
  const open = STATUS_CORPUS.filter( ( s ) => !TERMINAL_IN_CORPUS.includes( s ) );
  assert.ok( open.length >= 7, `positive control: ${open.length} open statuses in a corpus of ${STATUS_CORPUS.length}` );
  assert.deepEqual( [ ...demoteLive, ...approveLive ].sort(), [ ...open ].sort(),
    "approve and demote must partition the open statuses — offering both is a no-op in one direction" );
  assert.equal( demoteLive.filter( ( s ) => approveLive.includes( s ) ).length, 0,
    "no row may offer both approve and demote" );
});

test("verbLegality: drop and wont_fix are live on EVERY open status", () => {
  const open = STATUS_CORPUS.filter( ( s ) => !TERMINAL_IN_CORPUS.includes( s ) );
  assert.ok( open.length >= 7, `positive control: ${open.length} open statuses swept` );
  for ( const s of open ) {
    for ( const v of [ "drop", "wont_fix" ] ) {
      assert.ok( verbLegality( s ).find( ( e ) => e.verb === v )!.enabled, `${v} must be live on ${s}` );
    }
  }
});

test("verbLegality: an enabled option carries NO explanation, a greyed one always does", () => {
  let enabledSeen = 0, greyedSeen = 0;
  for ( const s of STATUS_CORPUS ) {
    for ( const e of verbLegality( s ) ) {
      if ( e.enabled ) { assert.equal( e.why, "", `${s}/${e.verb}: a live option must not carry a refusal` ); enabledSeen += 1; }
      else             { assert.notEqual( e.why, "", `${s}/${e.verb}: a greyed option must say why` ); greyedSeen += 1; }
    }
  }
  // Both arms must have fired. Without this the test passes on a corpus that
  // happened to be all-enabled or all-greyed, asserting nothing about the other.
  assert.ok( enabledSeen > 0 && greyedSeen > 0,
    `both arms must fire: ${enabledSeen} enabled, ${greyedSeen} greyed, of ${STATUS_CORPUS.length * TASK_VERBS.length} pairs` );
  assert.equal( enabledSeen + greyedSeen, STATUS_CORPUS.length * TASK_VERBS.length,
    "the sweep must visit every status × verb pair" );
});

test("verbLegality: a missing or unknown status degrades to open, and names itself", () => {
  // A row with no status is never silently hidden (isOpenStatus is degrade-safe),
  // so it gets the ordinary open offering rather than a terminal one.
  assert.ok( verbLegality( undefined ).find( ( e ) => e.verb === "drop" )!.enabled );
  assert.ok( verbLegality( "" ).find( ( e ) => e.verb === "drop" )!.enabled );
  assert.match( verbLegality( "moon_phase" ).find( ( e ) => e.verb === "park" )!.why, /queued or in progress/ );
});

test("verbLegality: status matching is case-insensitive", () => {
  assert.ok( verbLegality( "QUEUED" ).find( ( e ) => e.verb === "park" )!.enabled );
  assert.ok( verbLegality( "Not_Approved" ).find( ( e ) => e.verb === "approve" )!.enabled );
});

// ---------------------------------------------------------------------------
// Payload shapes — settled, and the one place a re-derivation would cost a park
// ---------------------------------------------------------------------------

test("transitionExtras: park posts its reason under park_reason, never reason", () => {
  const body = transitionExtras( "park", "the row's own sentence", "2026-09-10T13:00:00.000Z" );
  assert.deepEqual( body, { park_reason: "the row's own sentence", next_chase_ts: "2026-09-10T13:00:00.000Z" } );
  assert.ok( !( "reason" in body ), "a park filed under the generic key lands with no decisive sentence" );
});

test("transitionExtras: every OTHER reason-taking verb posts under reason", () => {
  const others = TASK_VERBS.filter( ( v ) => verbNeeds( v )!.reason && v !== "park" );
  assert.equal( others.length, 3, `three non-park reason verbs expected; found ${others.length}` );
  for ( const v of others ) {
    const body = transitionExtras( v, "because", "2026-09-10T13:00:00.000Z" );
    assert.equal( body.reason, "because", `${v} must post under reason` );
    assert.ok( !( "park_reason" in body ), `${v} must not post under park_reason` );
  }
});

test("transitionExtras: only the dated verbs carry next_chase_ts", () => {
  let dated = 0, undated = 0;
  for ( const v of TASK_VERBS ) {
    const body = transitionExtras( v, "r", "2026-09-10T13:00:00.000Z" );
    if ( verbNeeds( v )!.date ) { assert.ok( "next_chase_ts" in body, `${v} must carry a chase instant` ); dated += 1; }
    else { assert.ok( !( "next_chase_ts" in body ), `${v} must not carry a chase instant` ); undated += 1; }
  }
  assert.equal( dated, 2, `two dated verbs expected; ${dated} found` );
  assert.equal( undated, TASK_VERBS.length - 2, `${TASK_VERBS.length - 2} undated verbs expected; ${undated} found` );
});

test("transitionExtras: approve posts an EMPTY body — no reason, no date", () => {
  assert.deepEqual( transitionExtras( "approve", "ignored text", "2026-09-10T13:00:00.000Z" ), {} );
});

test("transitionExtras: a dated verb with a null instant omits the key rather than sending null", () => {
  assert.deepEqual( transitionExtras( "park", "why", null ), { park_reason: "why" } );
});
