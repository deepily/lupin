// Holding-area card — holdingAreaModel unit tests.
// 100% lines/branches/functions per the multiplexer coverage mandate.
//
// TWO DEFECTS THESE TESTS EXIST TO CATCH, both of which render a plausible,
// wrong pane rather than an obviously broken one:
//   1. grouping by OWNER instead of FILER (spec §5c.1)
//   2. taking the LEADING word of created_by instead of stripping a TRAILING
//      session id — which truncates every two-word persona (notifications.js:9889)
// Both are pinned by fixtures where the two rules give DIFFERENT answers. A
// fixture whose owner and filer agree cannot see defect 1 at all.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  taskFilerLabel,
  groupHeldRowsByFiler,
} from "../../../lupin_app/static/js/multiplexer/render/holdingAreaModel";
import type { TaskItem } from "../../../lupin_app/static/js/multiplexer/render/taskListModel";

// ---------------------------------------------------------------- filer label

test( "taskFilerLabel strips a trailing 8-hex session id and display-cases", () => {
  assert.equal( taskFilerLabel( { created_by: "Krishna 420f5ec9" } ), "Krishna" );
} );

test( "TWO-WORD PERSONA: 'mr radio 0e61abe3' keeps BOTH words", () => {
  // The whole reason the rule is anchored at the END. A leading-word rule
  // returns "Mr" here, which is a wrong name wearing a right one's clothes.
  assert.equal( taskFilerLabel( { created_by: "mr radio 0e61abe3" } ), "Mr Radio" );
} );

test( "a string with NO trailing session id is returned WHOLE, not truncated", () => {
  assert.equal( taskFilerLabel( { created_by: "mr radio" } ), "Mr Radio" );
  assert.equal( taskFilerLabel( { created_by: "some unexpected format here" } ),
                "Some Unexpected Format Here" );
} );

test( "the session-id match is case-insensitive and anchored", () => {
  assert.equal( taskFilerLabel( { created_by: "Rio 0E61ABE3" } ), "Rio" );
  // Not 8 hex → no strip. Shown whole rather than guessed at.
  //
  // ⚠️ Note the casing: \b[a-z] finds no word boundary between "0" and "e",
  // so a token STARTING with a digit is never display-cased. Verified against
  // the legacy JS rather than predicted — I predicted "0E61Abe" and was wrong.
  assert.equal( taskFilerLabel( { created_by: "Rio 0e61abe" } ),  "Rio 0e61abe" );
  // Leading, not trailing → not stripped.
  assert.equal( taskFilerLabel( { created_by: "0e61abe3 Rio" } ), "0e61abe3 Rio" );
} );

test( "absent / blank / whitespace created_by → em-dash", () => {
  assert.equal( taskFilerLabel( { created_by: null } ),      "—" );
  assert.equal( taskFilerLabel( { created_by: "" } ),        "—" );
  assert.equal( taskFilerLabel( { created_by: "   " } ),     "—" );
  assert.equal( taskFilerLabel( {} ),                        "—" );
  assert.equal( taskFilerLabel( null ),                      "—" );
  assert.equal( taskFilerLabel( undefined ),                 "—" );
} );

test( "a bare session id with no name is shown WHOLE — visibly odd, by design", () => {
  // The rule requires leading whitespace, so a lone id does not match and is
  // rendered untouched. An unexpected format shown in full sends the reader to
  // the row; a truncated one would look like a name.
  assert.equal( taskFilerLabel( { created_by: "0e61abe3" } ), "0e61abe3" );
} );

// ---------------------------------------------------------------- grouping

test( "a non-array argument yields []", () => {
  assert.deepEqual( groupHeldRowsByFiler( null ),      [] );
  assert.deepEqual( groupHeldRowsByFiler( undefined ), [] );
  assert.deepEqual( groupHeldRowsByFiler( "nope" ),    [] );
  assert.deepEqual( groupHeldRowsByFiler( {} ),        [] );
  assert.deepEqual( groupHeldRowsByFiler( [] ),        [] );
} );

test( "FILER NOT OWNER: rows are bucketed by created_by, never owner_persona", () => {
  // The discriminating fixture: filer and owner DISAGREE on every row, and
  // they disagree in a way that produces a different NUMBER of groups.
  // Group-by-owner gives three groups of one; group-by-filer gives one of three.
  const rows: TaskItem[] = [
    { title: "a", created_by: "maria b9c93948", owner_persona: "john"    },
    { title: "b", created_by: "maria b9c93948", owner_persona: "rachel"  },
    { title: "c", created_by: "maria b9c93948", owner_persona: "krishna" },
  ];
  const groups = groupHeldRowsByFiler( rows );
  assert.equal( groups.length, 1 );
  assert.equal( groups[ 0 ].filer, "Maria" );
  assert.deepEqual( groups[ 0 ].tasks.map( ( t ) => t.title ), [ "a", "b", "c" ] );
} );

test( "groups sort by filer name ascending", () => {
  const rows: TaskItem[] = [
    { title: "z", created_by: "zoe 11111111" },
    { title: "a", created_by: "adam 22222222" },
    { title: "m", created_by: "mia 33333333" },
  ];
  assert.deepEqual(
    groupHeldRowsByFiler( rows ).map( ( g ) => g.filer ),
    [ "Adam", "Mia", "Zoe" ],
  );
} );

test( "rows within a filer sort by PRIORITY first", () => {
  const rows: TaskItem[] = [
    { title: "low",  created_by: "amy 11111111", priority: "P3" },
    { title: "high", created_by: "amy 11111111", priority: "P0" },
    { title: "mid",  created_by: "amy 11111111", priority: "P1" },
  ];
  assert.deepEqual(
    groupHeldRowsByFiler( rows )[ 0 ].tasks.map( ( t ) => t.title ),
    [ "high", "mid", "low" ],
  );
} );

test( "rows tied on priority sort by TITLE", () => {
  const rows: TaskItem[] = [
    { title: "charlie", created_by: "amy 11111111", priority: "P1" },
    { title: "alpha",   created_by: "amy 11111111", priority: "P1" },
    { title: "bravo",   created_by: "amy 11111111", priority: "P1" },
  ];
  assert.deepEqual(
    groupHeldRowsByFiler( rows )[ 0 ].tasks.map( ( t ) => t.title ),
    [ "alpha", "bravo", "charlie" ],
  );
} );

test( "a missing priority sorts LAST, not first", () => {
  const rows: TaskItem[] = [
    { title: "none", created_by: "amy 11111111" },
    { title: "p2",   created_by: "amy 11111111", priority: "P2" },
  ];
  assert.deepEqual(
    groupHeldRowsByFiler( rows )[ 0 ].tasks.map( ( t ) => t.title ),
    [ "p2", "none" ],
  );
} );

test( "STATUS IS NOT A SORT KEY — it must not reorder rows", () => {
  // Every row in this pane is not_approved, so status can discriminate nothing.
  // If a port adds statusRank ahead of priority (as groupTasksByOwner does),
  // "blocked" would sort ahead of "not_approved" and this order would invert.
  const rows: TaskItem[] = [
    { title: "first",  created_by: "amy 11111111", priority: "P0", status: "not_approved" },
    { title: "second", created_by: "amy 11111111", priority: "P1", status: "blocked"      },
  ];
  assert.deepEqual(
    groupHeldRowsByFiler( rows )[ 0 ].tasks.map( ( t ) => t.title ),
    [ "first", "second" ],
  );
} );

test( "an untitled row still sorts deterministically", () => {
  const rows: TaskItem[] = [
    { created_by: "amy 11111111", priority: "P1" },
    { title: "aaa", created_by: "amy 11111111", priority: "P1" },
  ];
  // "(untitled)" sorts BEFORE "aaa" — localeCompare puts the parenthesis
  // first. Measured, not predicted; the point of the test is determinism.
  assert.deepEqual(
    groupHeldRowsByFiler( rows )[ 0 ].tasks.map( ( t ) => t.title ?? "(untitled)" ),
    [ "(untitled)", "aaa" ],
  );
} );

test( "null / undefined members are tolerated and bucket under the em-dash", () => {
  const groups = groupHeldRowsByFiler( [ null, undefined, { created_by: "amy 11111111" } ] );
  // The em-dash sorts BEFORE "Amy" under localeCompare. Measured.
  assert.deepEqual( groups.map( ( g ) => g.filer ), [ "—", "Amy" ] );
  assert.equal( groups[ 0 ].tasks.length, 2 );
  assert.equal( groups[ 1 ].tasks.length, 1 );
} );

test( "the input array is not mutated", () => {
  const rows: TaskItem[] = [
    { title: "b", created_by: "amy 11111111", priority: "P2" },
    { title: "a", created_by: "amy 11111111", priority: "P0" },
  ];
  const snapshot = rows.map( ( t ) => t.title );
  groupHeldRowsByFiler( rows );
  assert.deepEqual( rows.map( ( t ) => t.title ), snapshot );
} );

// ---------------------------------------------------------------- JS parity

// OBSERVATIONAL-EQUIVALENCE CORPUS.
//
// The expected column is not predicted and not derived from this port. Each
// value was produced by executing the legacy JS body transcribed VERBATIM from
// notifications.js:9922-9930 over the same input, then written here as a
// LITERAL — so the two sides of every assertion below have DIFFERENT
// PROVENANCE and the comparison cannot be satisfied by construction.
//
// Rick's ruling is no shared code between the clients, so equivalence is the
// only thing that can be asserted. This is where it is asserted.
//
// ⚠️ SCOPE: this pins taskFilerLabel only, and it pins the port against the JS
// SOURCE TEXT as transcribed on 2026-09-05 — not against the running JS card.
// A change to notifications.js will not redden it.
const FILER_PARITY: ReadonlyArray<readonly [ string, string ]> = [
  [ "Krishna 420f5ec9",            "Krishna" ],
  [ "mr radio 0e61abe3",           "Mr Radio" ],
  [ "mr radio",                    "Mr Radio" ],
  [ "Rio 0E61ABE3",                "Rio" ],
  [ "Rio 0e61abe",                 "Rio 0e61abe" ],
  [ "0e61abe3 Rio",                "0e61abe3 Rio" ],
  [ "0e61abe3",                    "0e61abe3" ],
  [ "some unexpected format here", "Some Unexpected Format Here" ],
  [ "  padded  11111111  ",        "Padded" ],
  [ "maria b9c93948",              "Maria" ],
  [ "a 12345678",                  "A" ],
  [ "",                            "—" ],
  [ "   ",                         "—" ],
  [ "MR RADIO 0e61abe3",           "MR RADIO" ],
  [ "x9 abcdef01",                 "X9" ],
  [ "tiberius-👑 deadbeef",        "Tiberius-👑" ],
];

test( "JS PARITY: taskFilerLabel matches the legacy card across the corpus", () => {
  // Positive control: a corpus that silently emptied would pass every
  // per-item assertion in the loop, so assert it is populated first.
  assert.ok( FILER_PARITY.length >= 16, "parity corpus is populated" );
  for ( const [ input, expected ] of FILER_PARITY ) {
    assert.equal(
      taskFilerLabel( { created_by: input } ),
      expected,
      `filer label diverged from the legacy card for ${ JSON.stringify( input ) }`,
    );
  }
} );
