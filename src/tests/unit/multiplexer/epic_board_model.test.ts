// Epic-board card — epicBoardModel unit tests.
// 100% lines/branches/functions per the multiplexer coverage mandate.
//
// FOUR DEFECTS THESE PIN, each of which renders a plausible pane (spec §5d):
//   1. onRick treated as a MOVE rather than a HIGHLIGHT — empties epics that
//      are not empty
//   2. "epic:unassigned" not sunk last — looks right until an unowned row appears
//   3. no key tie-break — two equal-sized epics swap between refreshes, which
//      does not look like a sort bug
//   4. drift silently dropped — rows vanish with no error

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  EPIC_KEY_PREFIX,
  EPIC_UNASSIGNED_KEY,
  EPIC_BLOCKER_OF_INTEREST,
  epicKeyOf,
  taskWaitsOnRick,
  groupTasksByEpic,
} from "../../../lupin_app/static/js/multiplexer/render/epicBoardModel";
import type { TaskItem } from "../../../lupin_app/static/js/multiplexer/render/taskListModel";

const rick = ( kind: string ) => ( { blocked_by: [ { kind, id: "rick" } ] } as TaskItem );

// ---------------------------------------------------------------- constants

test( "constants match the JS card verbatim", () => {
  assert.equal( EPIC_KEY_PREFIX,           "epic:" );
  assert.equal( EPIC_UNASSIGNED_KEY,       "epic:unassigned" );
  assert.equal( EPIC_BLOCKER_OF_INTEREST,  "rick" );
} );

// ---------------------------------------------------------------- epicKeyOf

test( "epicKeyOf requires the prefix — a bare correlation_key is DRIFT", () => {
  assert.equal( epicKeyOf( { correlation_key: "epic:alpha" } ), "epic:alpha" );
  assert.equal( epicKeyOf( { correlation_key: "alpha" } ),      null );
  assert.equal( epicKeyOf( { correlation_key: "" } ),           null );
  assert.equal( epicKeyOf( { correlation_key: null } ),         null );
  assert.equal( epicKeyOf( {} ),                                null );
  assert.equal( epicKeyOf( null ),                              null );
  assert.equal( epicKeyOf( undefined ),                         null );
} );

test( "epicKeyOf anchors the prefix at the START, not anywhere", () => {
  assert.equal( epicKeyOf( { correlation_key: "not-epic:alpha" } ), null );
} );

// ---------------------------------------------------------------- waitsOnRick

test( "taskWaitsOnRick matches a user OR persona ref named rick", () => {
  assert.equal( taskWaitsOnRick( rick( "user" ) ),    true );
  assert.equal( taskWaitsOnRick( rick( "persona" ) ), true );
} );

test( "BOTH HALVES LOAD-BEARING: the right name with the WRONG KIND does not match", () => {
  // Matching on the id alone would sweep a non-human ref into the highlight.
  assert.equal( taskWaitsOnRick( rick( "item" ) ), false );
} );

test( "the id match is trimmed and case-insensitive", () => {
  assert.equal( taskWaitsOnRick( { blocked_by: [ { kind: "user", id: "  RICK " } ] } ), true );
} );

test( "a non-rick blocker does not match", () => {
  assert.equal( taskWaitsOnRick( { blocked_by: [ { kind: "user", id: "maria" } ] } ), false );
} );

test( "a non-array / absent / malformed blocked_by yields false, never throws", () => {
  assert.equal( taskWaitsOnRick( { blocked_by: "rick" } ),          false );
  assert.equal( taskWaitsOnRick( { blocked_by: null } ),            false );
  assert.equal( taskWaitsOnRick( {} ),                              false );
  assert.equal( taskWaitsOnRick( null ),                            false );
  assert.equal( taskWaitsOnRick( { blocked_by: [ null ] } as unknown as TaskItem ),   false );
  assert.equal( taskWaitsOnRick( { blocked_by: [ "rick" ] } as unknown as TaskItem ), false );
  assert.equal( taskWaitsOnRick( { blocked_by: [ { kind: "user" } ] } ),              false );
  assert.equal( taskWaitsOnRick( { blocked_by: [ { kind: "user", id: null } ] } ),    false );
} );

// ---------------------------------------------------------------- grouping

test( "a non-array argument yields an empty model, not a throw", () => {
  const m = groupTasksByEpic( null );
  assert.deepEqual( m, { totalCount: 0, onRick: [], groups: [], drift: [] } );
} );

test( "totalCount counts ALL input rows, grouped and drift alike", () => {
  const m = groupTasksByEpic( [
    { correlation_key: "epic:a" }, { correlation_key: "nope" }, {},
  ] );
  assert.equal( m.totalCount, 3 );
} );

test( "DRIFT IS NEVER SILENTLY DROPPED — a row is in exactly one of groups/drift", () => {
  const m = groupTasksByEpic( [
    { title: "in",  correlation_key: "epic:a" },
    { title: "out", correlation_key: "loose" },
    { title: "bare" },
  ] );
  assert.deepEqual( m.groups.map( ( g ) => g.epicKey ), [ "epic:a" ] );
  assert.deepEqual( m.drift.map( ( t ) => t.title ), [ "bare", "out" ] );
  assert.equal( m.groups[ 0 ].tasks.length + m.drift.length, 3 );
} );

test( "epic:unassigned SINKS LAST even when it is the biggest bucket", () => {
  // Biggest-first would put unassigned first. Only the explicit sink is correct.
  const m = groupTasksByEpic( [
    { correlation_key: EPIC_UNASSIGNED_KEY }, { correlation_key: EPIC_UNASSIGNED_KEY },
    { correlation_key: EPIC_UNASSIGNED_KEY }, { correlation_key: "epic:small" },
  ] );
  assert.deepEqual( m.groups.map( ( g ) => g.epicKey ), [ "epic:small", EPIC_UNASSIGNED_KEY ] );
} );

test( "groups order BIGGEST FIRST", () => {
  const m = groupTasksByEpic( [
    { correlation_key: "epic:small" },
    { correlation_key: "epic:big" }, { correlation_key: "epic:big" },
  ] );
  assert.deepEqual( m.groups.map( ( g ) => g.epicKey ), [ "epic:big", "epic:small" ] );
} );

test( "STABILITY: equal-sized epics tie-break on KEY, so renders do not reshuffle", () => {
  // Without the key tie-break the order depends on Map insertion, which flips
  // when the server returns rows in a different order. Same set, two orders,
  // one expected output.
  const forward = groupTasksByEpic( [ { correlation_key: "epic:b" }, { correlation_key: "epic:a" } ] );
  const reverse = groupTasksByEpic( [ { correlation_key: "epic:a" }, { correlation_key: "epic:b" } ] );
  assert.deepEqual( forward.groups.map( ( g ) => g.epicKey ), [ "epic:a", "epic:b" ] );
  assert.deepEqual( reverse.groups.map( ( g ) => g.epicKey ), [ "epic:a", "epic:b" ] );
} );

test( "within a group rows sort status-rank → priority → title", () => {
  const m = groupTasksByEpic( [
    { correlation_key: "epic:a", title: "z", status: "queued",  priority: "P0" },
    { correlation_key: "epic:a", title: "a", status: "blocked", priority: "P3" },
    { correlation_key: "epic:a", title: "b", status: "queued",  priority: "P0" },
  ] );
  // blocked outranks queued despite P3 vs P0 — status first, then priority, then title.
  assert.deepEqual( m.groups[ 0 ].tasks.map( ( t ) => t.title ), [ "a", "b", "z" ] );
} );

test( "drift is sorted by the same urgency comparator", () => {
  const m = groupTasksByEpic( [
    { title: "q", status: "queued" },
    { title: "b", status: "blocked" },
  ] );
  assert.deepEqual( m.drift.map( ( t ) => t.title ), [ "b", "q" ] );
} );

// ---------------------------------------------------------------- onRick

test( "onRick is a HIGHLIGHT, NOT A MOVE — the row stays under its epic too", () => {
  // The defect this pins empties epics that are not empty.
  const m = groupTasksByEpic( [
    { title: "held", correlation_key: "epic:a", blocked_by: [ { kind: "user", id: "rick" } ] },
  ] );
  assert.deepEqual( m.onRick.map( ( t ) => t.title ), [ "held" ] );
  assert.deepEqual( m.groups[ 0 ].tasks.map( ( t ) => t.title ), [ "held" ] );
} );

test( "a drift row blocked on Rick appears in BOTH onRick and drift", () => {
  const m = groupTasksByEpic( [
    { title: "loose", blocked_by: [ { kind: "persona", id: "rick" } ] },
  ] );
  assert.equal( m.onRick.length, 1 );
  assert.equal( m.drift.length,  1 );
} );

test( "onRick sorts P0 FIRST, then id — NOT by status", () => {
  const m = groupTasksByEpic( [
    { id: "b", priority: "P1", status: "blocked", blocked_by: [ { kind: "user", id: "rick" } ] },
    { id: "a", priority: "P0", status: "queued",  blocked_by: [ { kind: "user", id: "rick" } ] },
  ] );
  assert.deepEqual( m.onRick.map( ( t ) => t.id ), [ "a", "b" ] );
} );

test( "onRick ties on priority break on id", () => {
  const m = groupTasksByEpic( [
    { id: "z", priority: "P1", blocked_by: [ { kind: "user", id: "rick" } ] },
    { id: "a", priority: "P1", blocked_by: [ { kind: "user", id: "rick" } ] },
  ] );
  assert.deepEqual( m.onRick.map( ( t ) => t.id ), [ "a", "z" ] );
} );

test( "onRick tolerates a missing id", () => {
  const m = groupTasksByEpic( [
    { priority: "P1", blocked_by: [ { kind: "user", id: "rick" } ] },
    { id: "a", priority: "P1", blocked_by: [ { kind: "user", id: "rick" } ] },
  ] );
  assert.equal( m.onRick.length, 2 );
  assert.equal( m.onRick[ 0 ].id, undefined );
} );

test( "falsy rows collapse to {} rather than throwing", () => {
  const m = groupTasksByEpic( [ null, undefined, { correlation_key: "epic:a" } ] );
  assert.equal( m.totalCount, 3 );
  assert.equal( m.drift.length, 2 );
} );

test( "the input array is not mutated", () => {
  const rows: TaskItem[] = [
    { correlation_key: "epic:a", title: "b", priority: "P2" },
    { correlation_key: "epic:a", title: "a", priority: "P0" },
  ];
  const snapshot = rows.map( ( t ) => t.title );
  groupTasksByEpic( rows );
  assert.deepEqual( rows.map( ( t ) => t.title ), snapshot );
} );
