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
// 🔨 6 as of 2026-09-08: `unpark` joins for Rick's P0 row 03d3bf78. Still a FLOOR
// and not an equality — the assertions below name the members, and membership is
// what a rename defeats while arithmetic stays undisturbed.
const VERB_FLOOR = 6;

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

test("TASK_VERBS: the fixed render order the board uses", () => {
  assert.ok( TASK_VERBS.length >= VERB_FLOOR,
    `positive control: the port of notifications.js _verbNeeds carries ${VERB_FLOOR} verbs; found ${TASK_VERBS.length}` );
  // `fixed` sits between wont_fix and unpark because that is where the SHARED module
  // puts it (row 507183ff). The two lists agreeing is guarded separately, and against
  // the module rather than against this literal, by
  // the_multiplexer_offers_every_shared_verb.test.ts — this line pins the order the
  // board renders; that file pins WHERE the order comes from.
  assert.deepEqual( Array.from( TASK_VERBS ), [ "park", "drop", "demote", "wont_fix", "fixed", "unpark", "approve" ] );
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
    // `unpark` -> "queued" is RICK'S OWN RULING, verbatim 2026-09-08: "the proper
    // state is to go from parked to queued." It is also the only reachable answer —
    // `parked_from_status` was rejected as a column, so where a row was before it
    // parked is not remembered, and `is_park_legal_from` guarantees it was `queued`
    // or `in_progress`. Same target as `approve`, arrived at from the other side.
    // `fixed` -> "done" is Rick's missing positive terminal verb (row 507183ff):
    // "I see something's fixed, I'm going to mark it as fixed." Its absence left the
    // board with only a NEGATIVE human-driven terminal verb.
    wont_fix: "wont_fix", fixed: "done", unpark: "queued", approve: "queued",
  };
  const checked = TASK_VERBS.filter( ( v ) => EXPECTED[ v ] !== undefined );
  assert.equal( checked.length, TASK_VERBS.length, "every verb must have an expected status" );
  assert.ok( checked.length >= VERB_FLOOR, `positive control: ${VERB_FLOOR} statuses expected, ${checked.length} checked` );
  for ( const v of checked ) assert.equal( verbNeeds( v )!.status, EXPECTED[ v ], `${v} posts the wrong to_status` );
});

test("verbNeeds: TWO verbs are terminal — won't-fix and fixed, the negative and the positive", () => {
  // 🔴 THIS TEST'S PREMISE CHANGED, and the change is the point of row 507183ff.
  // It used to read "exactly one verb is terminal, and it is won't-fix" — which was
  // an accurate description of a board Rick complained about: the only human-driven
  // way to close a row was to say it would NOT be done. `wont_fix` counts toward the
  // create/close ratio gate and `dropped` does not, so a missing positive terminal
  // verb inflates the open count the gate reads.
  //
  // Both arm twice: `done` and `wont_fix` are append-only, so a misclick on either is
  // not undoable.
  const terminal = TASK_VERBS.filter( ( v ) => verbNeeds( v )!.terminal );
  assert.deepEqual( terminal, [ "wont_fix", "fixed" ] );
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

test("verbNeeds: fixed, unpark and approve are the verbs that take no reason", () => {
  // 🔨 WAS "approve is the only verb". `unpark` joined 2026-09-08 (row 03d3bf78),
  // and for the same shape of reason: un-parking DISCARDS the park's justification
  // rather than answering it — the server clears `park_reason` on leaving `parked` —
  // so demanding a second reason to explain dropping the first records nothing.
  //
  // 🔨 `fixed` joins 2026-09-09 (row 507183ff) for a DIFFERENT reason, worth keeping
  // distinct: a fix explains itself. A mandatory note was put to Rick and REJECTED as
  // friction on the exact path he called too slow. Note the asymmetry with its sibling
  // — won't-fix DOES require a reason, because a refusal carries its justification the
  // way a drop does, and "why not" is not inferable from the row the way "done" is.
  const reasonless = TASK_VERBS.filter( ( v ) => !verbNeeds( v )!.reason );
  assert.deepEqual( reasonless, [ "fixed", "unpark", "approve" ] );
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

test("transitionExtras: the dated verbs carry an instant, un-park carries an explicit null, the rest carry nothing", () => {
  // 🔨 REAIMED 2026-09-08 (row 03d3bf78). The old rule was a clean binary — a verb
  // either carries `next_chase_ts` or it does not. `unpark` is a THIRD case and the
  // distinction is load-bearing: it carries the key with a null VALUE, because Rick
  // ruled the old chase must be CLEARED and an omitted key leaves the stored value
  // untouched. "Send nothing" and "send null" are different requests.
  let dated = 0, clearing = 0, undated = 0;
  for ( const v of TASK_VERBS ) {
    const body = transitionExtras( v, "r", "2026-09-10T13:00:00.000Z" );
    if ( v === "unpark" ) {
      assert.ok( "next_chase_ts" in body, "un-park must SEND the key, or nothing is cleared" );
      assert.equal( body.next_chase_ts, null, "un-park must send null, not an instant" );
      clearing += 1;
    }
    else if ( verbNeeds( v )!.date ) { assert.ok( "next_chase_ts" in body, `${v} must carry a chase instant` ); dated += 1; }
    else { assert.ok( !( "next_chase_ts" in body ), `${v} must not carry a chase instant` ); undated += 1; }
  }
  assert.equal( dated, 2, `two dated verbs expected; ${dated} found` );
  assert.equal( clearing, 1, `exactly one clearing verb expected; ${clearing} found` );
  assert.equal( undated, TASK_VERBS.length - 3, `${TASK_VERBS.length - 3} undated verbs expected; ${undated} found` );
});

test("transitionExtras: un-park posts ONLY the null chase — no reason, no instant", () => {
  // The positive control for the clause above: a body carrying anything else would
  // mean un-park had picked up a reason field it does not ask the operator for.
  assert.deepEqual( transitionExtras( "unpark", "ignored text", "2026-09-10T13:00:00.000Z" ),
                    { next_chase_ts: null } );
});

test("transitionExtras: approve posts an EMPTY body — no reason, no date", () => {
  assert.deepEqual( transitionExtras( "approve", "ignored text", "2026-09-10T13:00:00.000Z" ), {} );
});

test("transitionExtras: a dated verb with a null instant omits the key rather than sending null", () => {
  assert.deepEqual( transitionExtras( "park", "why", null ), { park_reason: "why" } );
});

// ---------------------------------------------------------------------------
// The prototype-chain guard (added 2026-09-05, at María's instruction).
//
// 🔴 THESE ARE UNREACHABLE FROM THE UI TODAY AND ARE GUARDED ANYWAY. Every
// caller reads `select.value` off a select THIS FILE'S OWN table rendered, so
// only the five real verbs can arrive. That is a property of today's CALL GRAPH,
// not of this code — these are exported functions, the next call site is one
// afternoon's work, and it will not arrive with a note saying which strings it
// may pass.
//
// The defect was found in the SIBLING module (holdingAreaBatch.ts) by a test
// that asked for "toString" because it asked; the four ordinary unknown-verb
// cases all passed there. Fixed in both, because leaving one of two identical
// defects standing is how it comes back wearing a different call site.
//
// ⚠️ WHAT MAKES IT DANGEROUS IS THAT THE WRONG ANSWER IS TRUTHY.
// `NEEDS[ "toString" ]` is `Object.prototype.toString` — a function, so every
// `if ( needs === null )` guard downstream lets it through, and its `.status` is
// `undefined`, so the caller POSTs a transition with NO TARGET STATUS rather
// than refusing to post at all. A falsy wrong answer would have been caught by
// the guards that already exist.
// ---------------------------------------------------------------------------

test( "verbNeeds refuses an inherited Object key rather than returning a function", () => {
  for ( const key of [ "toString", "constructor", "valueOf", "hasOwnProperty", "__proto__" ] ) {
    assert.equal( verbNeeds( key ), null, `verbNeeds( ${ JSON.stringify( key ) } ) leaked a prototype member` );
  }
} );

test( "verbLabel falls back to the verb itself for an inherited key, not to a function", () => {
  for ( const key of [ "toString", "constructor", "valueOf" ] ) {
    assert.equal( verbLabel( key ), key, `verbLabel( ${ JSON.stringify( key ) } ) leaked a prototype member` );
  }
} );

test( "verbReasonComplaint falls back to the generic sentence for an inherited key", () => {
  for ( const key of [ "toString", "constructor", "valueOf" ] ) {
    assert.equal( verbReasonComplaint( key ), "A reason is required.",
      `verbReasonComplaint( ${ JSON.stringify( key ) } ) leaked a prototype member` );
  }
} );

test( "the guard's positive control — the five REAL verbs still resolve", () => {
  // Without this, `Object.hasOwn` guards that always returned null/fallback would
  // satisfy every assertion above. A guard is not proven by what it rejects.
  for ( const verb of TASK_VERBS ) {
    assert.notEqual( verbNeeds( verb ), null, `${ verb } stopped resolving — the guard is rejecting real verbs` );
    assert.equal( typeof verbLabel( verb ), "string" );
  }
  assert.equal( verbNeeds( "park" )?.status, "parked" );
  assert.equal( verbLabel( "wont_fix" ), "Won't fix" );
  assert.match( verbReasonComplaint( "park" ), /quote the row's own decisive sentence/ );
} );

// ---------------------------------------------------------------------------
// UN-PARK IS OFFERED WHERE IT SHOULD BE — Rick's P0, row 03d3bf78
//
// 🔴 THESE EXIST BECAUSE A MUTATION ARM FOUND NOTHING. Forcing `isParked` to false
// in `verbLegality` — so un-park is offered on NO row, ever — left all 46 tests in
// this directory green. The sweeps above count verbs and check ordering; not one of
// them asserted that THIS verb is enabled on the status it exists for. The whole
// point of the card was untested and the suite was confident about it.
// ---------------------------------------------------------------------------

test("verbLegality: un-park is ENABLED on a parked row", () => {
  const unpark = verbLegality( "parked" ).find( ( e ) => e.verb === "unpark" );
  assert.ok( unpark, "un-park must be among the offered verbs at all" );
  assert.equal( unpark!.enabled, true, "un-park must be live on a parked row — this is the verb's whole purpose" );
  assert.equal( unpark!.why, "", "an enabled verb carries no refusal text" );
});

test("verbLegality: un-park is GREYED on every status that is not parked", () => {
  // 🔴 THE POSITIVE CONTROL, in the other direction. Without it, a verb enabled on
  // EVERY row would pass the test above — and un-park is approver-gated precisely
  // because it decides what the fleet works on.
  const others = [ "queued", "in_progress", "blocked", "not_approved", "review", "claimed", "done", "dropped", "wont_fix" ];
  for ( const status of others ) {
    const unpark = verbLegality( status ).find( ( e ) => e.verb === "unpark" );
    assert.ok( unpark, `un-park must still be RENDERED on a ${status} row, greyed rather than absent` );
    assert.equal( unpark!.enabled, false, `un-park must be greyed on a ${status} row` );
    assert.ok( unpark!.why.length > 0, `a greyed verb must say why: ${status}` );
  }
});

test("verbLegality: an EXPIRED park is still offered un-park", () => {
  // Rick's own example, row 49b87212: its chase time had passed, so the store counts
  // it as owed — but expiry is computed at READ time and never rewrites the row, so
  // its stored status is still "parked". The UI is handed that stored value.
  // ⇒ Keying on the stored status is what makes the expired case work, and this test
  // is what stops someone "fixing" it to consult a chase date.
  const unpark = verbLegality( "parked" ).find( ( e ) => e.verb === "unpark" );
  assert.equal( unpark!.enabled, true );
});
