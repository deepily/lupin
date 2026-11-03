// The task-list status filter: its table and three pure functions.
//
// The invariant under test: All is the default; the four chips are additive; all four
// selected is All; clearing the last chip is All, never an empty list. The statuses each
// chip stands for are pinned to literals below, so a silent edit to the table fails here.
// The claimed and review mapping is Rick's ruling; two tests name it.
//
// Coverage: this module is under shared/*.js, which the c8 denominator in
// run-typescript-tests.sh does not include. Its 100% lines, branches and functions were
// measured by running c8 with --include on this one file (see the row's receipt).
//
// Run: npx tsx --test src/tests/unit/shared/task_status_filter.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  TASK_STATUS_CHIPS,
  activeChips,
  toggleChip,
  filterTasksByChips,
  publishOnWindow,
} from "../../../lupin_app/static/js/shared/task-status-filter.js";

const ROWS = [
  { id: "p",  status: "parked" },
  { id: "b",  status: "blocked" },
  { id: "i",  status: "in_progress" },
  { id: "q",  status: "queued" },
  { id: "c",  status: "claimed" },
  { id: "r",  status: "review" },
  { id: "x",  status: "something_new" },
  { id: "nx" },
];

const ids = ( rows: { id: string }[] ) => rows.map( ( r ) => r.id );

test( "the table has exactly the four chips, in Rick's order, with these labels", () => {
  assert.deepEqual( TASK_STATUS_CHIPS.map( ( c ) => [ c.key, c.label ] ), [
    [ "parked", "Parked" ], [ "blocked", "Blocked" ], [ "in_progress", "In progress" ], [ "queued", "Queued" ],
  ] );
} );

test( "each of the four named statuses belongs to exactly one chip", () => {
  const owners = ( status: string ) => TASK_STATUS_CHIPS.filter( ( c ) => c.statuses.includes( status ) ).map( ( c ) => c.key );
  assert.deepEqual( owners( "parked" ),      [ "parked" ] );
  assert.deepEqual( owners( "blocked" ),     [ "blocked" ] );
  assert.deepEqual( owners( "in_progress" ), [ "in_progress" ] );
  assert.deepEqual( owners( "queued" ),      [ "queued" ] );
} );

test( "claimed and review count as In progress, by Rick's ruling", () => {
  const owners = ( status: string ) => TASK_STATUS_CHIPS.filter( ( c ) => c.statuses.includes( status ) ).map( ( c ) => c.key );
  assert.deepEqual( owners( "claimed" ), [ "in_progress" ] );
  assert.deepEqual( owners( "review" ),  [ "in_progress" ] );
} );

test( "activeChips: nothing selected is All", () => {
  assert.deepEqual( activeChips( [] ), [] );
} );

test( "activeChips: a selection comes back in table order, unknown keys dropped", () => {
  assert.deepEqual( activeChips( [ "queued", "nope", "parked" ] ), [ "parked", "queued" ] );
} );

test( "activeChips: all four selected is All", () => {
  assert.deepEqual( activeChips( [ "queued", "in_progress", "blocked", "parked" ] ), [] );
} );

test( "toggleChip: adds an unselected chip and removes a selected one", () => {
  assert.deepEqual( toggleChip( [], "blocked" ), [ "blocked" ] );
  assert.deepEqual( toggleChip( [ "blocked" ], "queued" ), [ "blocked", "queued" ] );
  assert.deepEqual( toggleChip( [ "blocked", "queued" ], "blocked" ), [ "queued" ] );
} );

test( "toggleChip: clearing the last chip returns All, never an empty view", () => {
  assert.deepEqual( toggleChip( [ "parked" ], "parked" ), [] );
} );

test( "toggleChip: selecting the fourth chip collapses to All", () => {
  assert.deepEqual( toggleChip( [ "parked", "blocked", "in_progress" ], "queued" ), [] );
} );

test( "toggleChip: from All, one click selects only that chip", () => {
  assert.deepEqual( toggleChip( [], "in_progress" ), [ "in_progress" ] );
} );

test( "toggleChip: an unknown key leaves the selection as it was, and the input is not changed", () => {
  const before = [ "parked" ];
  assert.deepEqual( toggleChip( before, "bogus" ), [ "parked" ] );
  toggleChip( before, "queued" );
  assert.deepEqual( before, [ "parked" ] );
} );

test( "filterTasksByChips: All returns every row in order, including statuses no chip names", () => {
  assert.deepEqual( ids( filterTasksByChips( ROWS, [] ) ), ids( ROWS ) );
} );

test( "filterTasksByChips: each chip alone shows only its own statuses", () => {
  assert.deepEqual( ids( filterTasksByChips( ROWS, [ "parked" ] ) ),  [ "p" ] );
  assert.deepEqual( ids( filterTasksByChips( ROWS, [ "blocked" ] ) ), [ "b" ] );
  assert.deepEqual( ids( filterTasksByChips( ROWS, [ "queued" ] ) ),  [ "q" ] );
  // Claimed and review ride with In progress.
  assert.deepEqual( ids( filterTasksByChips( ROWS, [ "in_progress" ] ) ), [ "i", "c", "r" ] );
} );

test( "filterTasksByChips: a union shows both chips' rows in the list's own order", () => {
  assert.deepEqual( ids( filterTasksByChips( ROWS, [ "queued", "parked" ] ) ), [ "p", "q" ] );
} );

test( "filterTasksByChips: all four selected is exactly the All view", () => {
  const all = [ "parked", "blocked", "in_progress", "queued" ];
  assert.deepEqual( filterTasksByChips( ROWS, all ), filterTasksByChips( ROWS, [] ) );
} );

test( "filterTasksByChips: a null row is skipped, not a throw", () => {
  assert.deepEqual( filterTasksByChips( [ null as never, { status: "queued" } ], [ "queued" ] ), [ { status: "queued" } ] );
} );

test( "publishOnWindow puts the table and the three functions on the object it is given", () => {
  const win: Record<string, unknown> = {};
  publishOnWindow( win );
  const published = win.LUPIN_TASK_STATUS_FILTER as Record<string, unknown>;
  assert.deepEqual( Object.keys( published ).sort(), [ "TASK_STATUS_CHIPS", "activeChips", "filterTasksByChips", "toggleChip" ] );
  assert.equal( published.toggleChip, toggleChip );
  assert.equal( published.TASK_STATUS_CHIPS, TASK_STATUS_CHIPS );
} );

test( "importing the module publishes it on the global object, which is the window in a browser", () => {
  const published = ( globalThis as never as { LUPIN_TASK_STATUS_FILTER?: { toggleChip: unknown } } ).LUPIN_TASK_STATUS_FILTER;
  assert.ok( published );
  assert.equal( published.toggleChip, toggleChip );
} );
