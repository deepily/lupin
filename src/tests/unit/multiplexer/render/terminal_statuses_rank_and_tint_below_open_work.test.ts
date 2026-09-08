// 🔴 THE ride-along FIX WAS LANDED AND NOTHING WATCHED IT — THE THIRD STATE.
//
// Row 470b7509 carries a ride-along describing a live bug: STATUS_RANK with no
// `wont_fix`, falling through to the unknown rank and sorting ABOVE done and
// dropped; `taskStatusClass` with no `wont_fix` / `not_approved` branch.
//
// 🔨 THE CODE FIX ALREADY LANDED, at b4cdf47e. Every factual claim in that
// ride-along block is now false — the entries are present, UNKNOWN_STATUS_RANK
// is 7 rather than 5, done is 8 rather than 6, dropped is 10 rather than 7.
// What was NOT true is that anything guarded it.
//
// POPULATION NAMED AND SWEPT (2026-09-07). `grep -rn 'wont_fix'
// src/tests/unit/multiplexer/` returns 7 files; every hit was OPENED, and every
// one is a holding-area batch verb, a task_verbs label, or a task_list_store
// CLOSING array. ZERO assert the rank ordering; ZERO assert the class mapping.
// Positive control: the same grep DOES return hits, so that zero is the tree's
// and not a broken search.
//
// ⇒ Delete `wont_fix : 9` today and nothing reddens. The fix ships and un-ships
// in silence. That is § UNGUARDED IS A THIRD STATE, and this file closes it.
//
// 🔴 IT ASSERTS THE ORDERING, NOT THE NUMBERS. `statusRank("wont_fix") === 9`
// would redden on a LEGITIMATE renumber — somebody inserting a status between
// queued and parked — and would say nothing about the property that matters.
// The property is that terminal work sorts BELOW open work and below the
// unknown fallback, and that survives any renumber which keeps it true.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/terminal_statuses_rank_and_tint_below_open_work.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  groupTasksByOwner,
  statusRank,
  taskStatusClass,
} from "../../../../lupin_app/static/js/multiplexer/render/taskListModel";

/** The three terminal statuses, per the server's TERMINAL_STATUSES. */
const TERMINAL = [ "done", "dropped", "wont_fix" ] as const;
/** Open statuses a row can actually carry, newest taxonomy included. */
const OPEN     = [ "blocked", "in_progress", "claimed", "review", "queued", "parked", "not_approved" ] as const;
/** A status nobody declared — the fallback's intended occupant. */
const TYPO     = "a-typo-nobody-declared";

test( "the corpus is the whole live taxonomy — a loop over a short list proves less than it looks", () => {
  assert.equal( TERMINAL.length, 3 );
  assert.equal( OPEN.length, 7 );
} );

test( "🔴 EVERY TERMINAL STATUS RANKS BELOW EVERY OPEN ONE — wont_fix included", () => {
  for ( const terminal of TERMINAL ) {
    for ( const open of OPEN ) {
      assert.ok( statusRank( terminal ) > statusRank( open ),
        `${ terminal } (rank ${ statusRank( terminal ) }) must rank below ${ open } (rank ${ statusRank( open ) })` );
    }
  }
} );

test( "🔴 AND BELOW THE UNKNOWN FALLBACK TOO — that is the exact rank wont_fix was reaching", () => {
  // This is the leg that separates "wont_fix has a rank" from "wont_fix has the
  // RIGHT one". A wrong-but-present rank of 5 passes the test above and fails
  // here, which is precisely the defect the ride-along describes.
  for ( const terminal of TERMINAL ) {
    assert.ok( statusRank( terminal ) > statusRank( TYPO ),
      `${ terminal } ranks at or above the unknown fallback — it is reaching the fallback itself` );
  }
} );

test( "the unknown fallback still sits BETWEEN open and terminal — it was not deleted or moved", () => {
  // Without this, "everything ranks below unknown" would be satisfiable by
  // making unknown rank 0, which would hide a typo'd row above blocked work.
  for ( const open of OPEN ) {
    assert.ok( statusRank( TYPO ) > statusRank( open ),
      `the unknown fallback ranks above ${ open } — a typo'd status would outrank real work` );
  }
} );

test( "an absent status takes the fallback rather than ranking first", () => {
  assert.equal( statusRank( null ), statusRank( TYPO ) );
  assert.equal( statusRank( undefined ), statusRank( TYPO ) );
  assert.equal( statusRank( "" ), statusRank( TYPO ) );
} );

test( "🔴 AND THE SORTER ACTUALLY USES IT — the rank is right AND it reaches the rendered order", () => {
  // A rank correct in the table and unused by the sorter is § IMPLEMENTED BUT
  // NOT INSTALLED. Fed in the WRONG order deliberately, so a sorter that
  // returned its input untouched fails rather than passing on a pre-sorted
  // fixture.
  const rows = [
    { id: "1", status: "wont_fix",    title: "closed",  priority: "P2", owner_persona: "rio" },
    { id: "2", status: "done",        title: "shipped", priority: "P2", owner_persona: "rio" },
    { id: "3", status: "in_progress", title: "live",    priority: "P2", owner_persona: "rio" },
  ];
  const model = groupTasksByOwner( rows );
  const order = model.groups.flatMap( ( g ) => g.tasks.map( ( t ) => t.status ) );
  assert.deepEqual( order, [ "in_progress", "done", "wont_fix" ],
    "open work must render above terminal work, and wont_fix below done" );
} );

test( "🔴 EVERY STATUS IN THE TAXONOMY HAS ITS OWN TINT — none falls through to unknown", () => {
  // The second half of the ride-along. A deliberately-closed row styled as a
  // typo is a row an operator reads as data corruption.
  const seen = new Map<string, string>();
  for ( const status of [ ...TERMINAL, ...OPEN ] ) {
    const cls = taskStatusClass( status );
    assert.notEqual( cls, "task-status-unknown",
      `${ status } falls through to the unknown tint — it is styled as a typo` );
    seen.set( status, cls );
  }
  // Named explicitly, because these three are the ones b4cdf47e added and the
  // ones a revert would take back out.
  assert.equal( seen.get( "wont_fix" ), "task-status-wont-fix" );
  assert.equal( seen.get( "parked" ), "task-status-parked" );
  assert.equal( seen.get( "not_approved" ), "task-status-not-approved" );
} );

test( "the unknown tint still EXISTS for a genuine typo — the fallback was not deleted", () => {
  // Without this leg, "nothing falls through to unknown" is satisfiable by
  // deleting the fallback, which would be a worse bug than the one being fixed.
  assert.equal( taskStatusClass( TYPO ), "task-status-unknown" );
  assert.equal( taskStatusClass( "" ), "task-status-unknown" );
  assert.equal( taskStatusClass( null ), "task-status-unknown" );
  assert.equal( taskStatusClass( undefined ), "task-status-unknown" );
} );
