// Ticket lookup by hash — the classifier both clients share, and the guard that
// keeps it agreeing with the Python that actually governs.
//
// WHAT THIS FILE IS FOR. `shared/task-lookup.js` reimplements
// `task_store_rules.classify_task_ref` in a second language so the search box
// can refuse junk without a round trip. Two implementations of one matching rule
// is the parallel-construction hazard row f45b37a9 is itself about — the server
// is the one that governs, and this file is what stops the client drifting away
// from it silently.
//
// ⚠️ THIS MODULE IS NOT IN THE c8 DENOMINATOR, AND THAT IS NOT AN OVERSIGHT.
// `run-typescript-tests.sh` includes only `multiplexer/**`, `nav/**` and
// `diagnostic/**` `.ts`. `shared/*.js` matches none of them, exactly like its two
// siblings `task-list-query.js` and `task-verbs.js`. So these assertions RUN and
// FAIL loudly, and they emit no coverage number. Said plainly because a silence
// that looks like coverage is the defect this repo keeps finding — do NOT read a
// green TypeScript gate as evidence about this file; read THIS file.
//
// Run: npx tsx --test src/tests/unit/shared/task_lookup.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import {
  MIN_TASK_REF_PREFIX_LEN,
  TASK_REF_FULL,
  TASK_REF_PREFIX,
  TASK_REF_INVALID,
  classifyTaskRef,
  taskLookupPath,
  taskRefRefusalMessage,
} from "../../../lupin_app/static/js/shared/task-lookup.js";

const HERE      = path.dirname( fileURLToPath( import.meta.url ) );
const REPO_ROOT = path.resolve( HERE, "../../../.." );
const RULES_PY  = path.join( REPO_ROOT, "src/cosa/rest/task_store_rules.py" );

// ---------------------------------------------------------------------------
// THE CROSS-LANGUAGE GUARD — the reason this file exists at all
// ---------------------------------------------------------------------------

test( "the minimum prefix length matches the Python that actually governs", () => {
  const source = readFileSync( RULES_PY, "utf8" );
  const match  = source.match( /^MIN_TASK_REF_PREFIX_LEN\s*=\s*(\d+)\s*$/m );

  // POSITIVE CONTROL ON THE READER ITSELF. If the constant is renamed or moved,
  // `match` is null and a bare `Number(null)` would read as 0 — which would then
  // "agree" with nothing and fail confusingly, or worse, pass if the JS were
  // also 0. Assert we FOUND it before comparing, so a broken reader is a
  // distinct, named failure rather than a mysterious numeric one.
  assert.ok(
    match,
    `could not find MIN_TASK_REF_PREFIX_LEN in ${ RULES_PY } — the reader is broken, `
    + `which is a DIFFERENT failure from the two values disagreeing`,
  );

  assert.equal(
    MIN_TASK_REF_PREFIX_LEN,
    Number( match![ 1 ] ),
    "the client classifier and the server rule disagree about the minimum prefix "
    + "length; the server is the one that governs, so change the JS",
  );
} );

// ---------------------------------------------------------------------------
// CLASSIFICATION — one assertion per branch of the contract
// ---------------------------------------------------------------------------

test( "a canonical UUID classifies as a full id", () => {
  const id = "49e52a90-d08c-4085-a172-780b19b6451a";
  assert.deepEqual( classifyTaskRef( id ), { kind: TASK_REF_FULL, value: id } );
} );

test( "32 bare hex chars classify as a full id, matching uuid.UUID()", () => {
  // Python's uuid.UUID() accepts the compact spelling as a FULL id. If this
  // classified as a prefix the two sides would name the same row by different
  // kinds — benign for the lookup, and exactly the drift the guard above exists
  // to keep visible.
  const compact = "49e52a90d08c4085a172780b19b6451a";
  assert.equal( compact.length, 32 );
  assert.deepEqual( classifyTaskRef( compact ), { kind: TASK_REF_FULL, value: compact } );
} );

test( "the 8-hex token the fleet actually pastes classifies as a prefix", () => {
  // The whole point of the row: this is what arrives in a DM.
  assert.deepEqual(
    classifyTaskRef( "49e52a90" ),
    { kind: TASK_REF_PREFIX, value: "49e52a90" },
  );
} );

test( "a partly-copied UUID keeps its hyphens on the way in and loses them on the way out", () => {
  assert.deepEqual(
    classifyTaskRef( "49e52a90-d08c" ),
    { kind: TASK_REF_PREFIX, value: "49e52a90d08c" },
  );
} );

test( "case and surrounding whitespace do not change the answer", () => {
  // A paste out of a chat client routinely carries both.
  assert.deepEqual(
    classifyTaskRef( "  49E52A90  " ),
    { kind: TASK_REF_PREFIX, value: "49e52a90" },
  );
} );

test( "exactly the minimum length is accepted and one short is refused", () => {
  const atMin   = "a".repeat( MIN_TASK_REF_PREFIX_LEN );
  const oneShort = "a".repeat( MIN_TASK_REF_PREFIX_LEN - 1 );

  assert.equal( classifyTaskRef( atMin ).kind,    TASK_REF_PREFIX,
    "the boundary itself must be INSIDE the accepted set" );
  assert.equal( classifyTaskRef( oneShort ).kind, TASK_REF_INVALID,
    "one character below the boundary must be refused" );
} );

test( "non-hex text is refused rather than becoming a search surface", () => {
  // 🔴 THE LOAD-BEARING REFUSAL. If arbitrary text classified as a prefix, an id
  // lookup would quietly become a LIKE-based search — a different feature with a
  // different cost, arrived at by accident. Every one of these is >= the minimum
  // length, so LENGTH is not what refuses them.
  for ( const junk of [ "hello", "select *", "ghijkl", "49e52a90z", "not-a-hash" ] ) {
    assert.deepEqual(
      classifyTaskRef( junk ),
      { kind: TASK_REF_INVALID, value: null },
      `"${ junk }" must not classify as a reference`,
    );
  }
} );

test( "non-strings are data, not exceptions", () => {
  for ( const bad of [ null, undefined, 42, {}, [], true ] ) {
    assert.deepEqual(
      classifyTaskRef( bad as unknown as string ),
      { kind: TASK_REF_INVALID, value: null },
      `${ String( bad ) } must classify INVALID rather than throw`,
    );
  }
} );

test( "an empty or whitespace-only ref is refused", () => {
  for ( const blank of [ "", "   ", "\t\n" ] ) {
    assert.equal( classifyTaskRef( blank ).kind, TASK_REF_INVALID );
  }
} );

// ---------------------------------------------------------------------------
// THE URL — what the box will actually request
// ---------------------------------------------------------------------------

test( "the lookup path targets the visibility-free single-row endpoint", () => {
  // 🔴 /api/tasks/<ref>, NOT /api/tasks?id_prefix=<ref>. The query form chains
  // the board-visibility filter after the prefix match, so it hides holding-area
  // rows — measured 2026-09-09: 1 of 23 held rows findable. This assertion is
  // what stops someone "simplifying" the box onto the board query later.
  assert.equal( taskLookupPath( "49e52a90" ), "/api/tasks/49e52a90" );
  assert.ok( !taskLookupPath( "49e52a90" )!.includes( "id_prefix" ),
    "the lookup must not be rebuilt on the board query — it cannot see held rows" );
} );

test( "the path carries the normalized value, so two spellings produce one URL", () => {
  assert.equal( taskLookupPath( " 49E5-2A90 " ), taskLookupPath( "49e52a90" ) );
} );

test( "a full UUID keeps its canonical spelling in the path", () => {
  const id = "49e52a90-d08c-4085-a172-780b19b6451a";
  assert.equal( taskLookupPath( id ), `/api/tasks/${ id }` );
} );

test( "junk yields no URL at all rather than a request the server will refuse", () => {
  for ( const junk of [ "hello", "", null, 42 ] ) {
    assert.equal( taskLookupPath( junk as unknown as string ), null );
  }
} );

// ---------------------------------------------------------------------------
// THE REFUSAL SENTENCE
// ---------------------------------------------------------------------------

test( "the refusal names BOTH rules a user can break", () => {
  const message = taskRefRefusalMessage();

  // Asserting the SUBSTANCE the sentence must carry, never its wording — a test
  // pinning the prose fails open the day someone rewrites it, which is the
  // negative-assertion defect row 456f694c is about.
  assert.match( message, new RegExp( String( MIN_TASK_REF_PREFIX_LEN ) ),
    "must name the minimum length, or the user cannot tell which rule they broke" );
  assert.match( message, /hyphen/i,
    "must say hyphens are fine — a partly-pasted UUID carries them" );
} );
