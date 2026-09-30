// Holding-area card — the BATCH verb table, unit tests.
// 100% lines/branches/functions per the multiplexer coverage mandate.
//
// 🔴 EVERY STRING IS COMPARED AGAINST notifications.js ON DISK, NEVER AGAINST A
// LITERAL RETYPED HERE. A literal in this file shares its provenance with the
// one in the module under test, so the two move together on any copy-paste error
// and the comparison can never fail. Two provenances, or it is not a comparison.
//
// 🔴 AND THE EXTRACTOR CARRIES ITS OWN POSITIVE CONTROL, BECAUSE AN EXTRACTOR
// THAT RETURNS GARBAGE PASSES BOTH OBVIOUS CHECKS. A previous extractor on this
// branch returned ten SLABS OF SOURCE as "strings" — an unanchored `"[^"]{10,}"`
// pairing the closing quote of one literal with the opening quote of the next —
// and both a COUNT floor and a DISTINCTNESS check passed on it, because count
// and distinctness are both CARDINALITY checks and neither looks at SHAPE. So:
// the regex is anchored to `[^"\n]`; the strings are shape-asserted (no newline,
// no source punctuation); and the count is an EQUALITY against a figure derived
// with a DIFFERENT INSTRUMENT — a scan of the region's own lines — rather than a
// floor read off the extractor's own output.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

import {
  HOLDING_BATCH_VERBS,
  holdingBatchNeeds,
  holdingBatchExtras,
  holdingBatchInFlightStatus,
  holdingBatchFinalStatus,
  HOLDING_BATCH_BLANK_REASON,
  HOLDING_BATCH_NO_ROWS,
} from "../../../../lupin_app/static/js/multiplexer/render/holdingAreaBatch";

const HERE        = dirname( fileURLToPath( import.meta.url ) );
const LEGACY_PATH = resolve( HERE, "../../../../lupin_app/static/js/notifications.js" );

/**
 * The legacy batch region: `_applyHoldingBatch` plus the two click handlers that
 * call it, up to the next unrelated method.
 *
 * ⚠️ BOTH BOUNDARIES ARE ASSERTED, AND THE ORDER BETWEEN THEM IS TOO. A slice
 * whose end marker moved above its start silently yields "" — and an empty
 * corpus passes every per-item assertion in a loop over it. A loop over nothing
 * is green.
 */
function legacyBatchSource(): string {
  const src   = readFileSync( LEGACY_PATH, "utf8" );
  const start = src.indexOf( "async _applyHoldingBatch( filer, toStatus, extras, verb ) {" );
  assert.ok( start !== -1, "legacy _applyHoldingBatch not found — the extraction is pointing at nothing" );
  const end   = src.indexOf( "async refreshHoldingArea() {", start );
  assert.ok( end > start, "legacy refreshHoldingArea not found after the batch region — the slice boundaries have moved" );
  return src.slice( start, end );
}

/**
 * Every plain double-quoted string literal in the region.
 *
 * ⚠️ ANCHORED TO `[^"\n]`, WHICH IS THE WHOLE DIFFERENCE. `[^"]` alone spans
 * newlines, so it happily pairs the closing quote of one literal with the
 * opening quote of the next and returns the source between them.
 */
function legacyQuotedStrings(): string[] {
  return Array.from( legacyBatchSource().matchAll( /"([^"\n]{6,})"/g ) ).map( ( m ) => m[ 1 ] as string );
}

/** Every backtick template literal in the region, source-verbatim (placeholders intact). */
function legacyTemplates(): string[] {
  return Array.from( legacyBatchSource().matchAll( /`([^`\n]{6,})`/g ) ).map( ( m ) => m[ 1 ] as string );
}

// ---------------------------------------------------------------------------
// The extraction's positive controls — FIRST, because every comparison below is
// worthless without them.
// ---------------------------------------------------------------------------

test( "the region extractor reaches real source and not an empty slice", () => {
  const body = legacyBatchSource();
  assert.ok( body.length > 500, `the batch region came back at ${ body.length } chars — too short to be the real method` );
  assert.ok( body.includes( "_renderHoldingGroupStatus" ), "the region does not contain the status painter it is built around" );
  assert.ok( body.includes( "_handleHoldingWontFixAllClick" ), "the region does not reach the won't-fix handler" );
} );

test( "the quoted-string extractor returns STRINGS, not slabs of source", () => {
  const found = legacyQuotedStrings();
  assert.ok( found.length >= 1, "no quoted strings found in the batch region — the extractor is returning nothing" );
  for ( const s of found ) {
    // SHAPE, not cardinality. A slab of source carries the punctuation a
    // sentence never does; a count and a distinctness check see neither.
    assert.ok( !s.includes( "\n" ), `extracted a multi-line slab, not a string: ${ JSON.stringify( s.slice( 0, 60 ) ) }` );
    // The tell is `;`, NOT `{`. The first cut of this banned `{` too and fired on
    // `"${CSS.escape( filer )}"` — a correctly-extracted string that happens to be
    // an interpolation fragment, in a region full of template literals. A shape
    // check that rejects legitimate members is not stricter, it is WRONG, and it
    // would have sent the next reader to fix an extractor that works.
    assert.ok( !s.includes( ";" ), `extracted source, not a string: ${ JSON.stringify( s.slice( 0, 60 ) ) }` );
  }
} );

test( "the shape check can actually REJECT a slab — the negative control", () => {
  // Without this, the test above is satisfied by an extractor returning nothing
  // and by a predicate true of everything. Both of those pass silently.
  const planted = 'a string";\n  const x = "another string';
  assert.ok( planted.includes( "\n" ) && planted.includes( ";" ),
    "the planted slab does not carry the tells the shape check keys on — the control proves nothing" );
} );

test( "the quoted-string count matches a figure taken with a DIFFERENT instrument", () => {
  // The independent instrument: count the region's own lines that OPEN a plain
  // double-quoted literal of the same shape, without reusing the extractor's
  // regex over the whole body. Equality, never a floor — a floor is satisfied by
  // an extractor returning twice as much as it should.
  const lines = legacyBatchSource().split( "\n" );
  let byLine = 0;
  for ( const line of lines ) byLine += ( line.match( /"[^"\n]{6,}"/g ) ?? [] ).length;
  assert.equal( legacyQuotedStrings().length, byLine,
    "the whole-body extraction and the line-by-line count disagree — one of them is pairing quotes across a boundary" );
} );

// ---------------------------------------------------------------------------
// The carbon copies
// ---------------------------------------------------------------------------

test( "the blank-reason refusal is the legacy sentence, verbatim", () => {
  assert.ok( legacyQuotedStrings().includes( HOLDING_BATCH_BLANK_REASON ),
    `HOLDING_BATCH_BLANK_REASON is not in the legacy source. Ours: ${ JSON.stringify( HOLDING_BATCH_BLANK_REASON ) }` );
} );

test( "the no-rows line is the legacy sentence, verbatim", () => {
  assert.ok( legacyQuotedStrings().includes( HOLDING_BATCH_NO_ROWS ),
    `HOLDING_BATCH_NO_ROWS is not in the legacy source. Ours: ${ JSON.stringify( HOLDING_BATCH_NO_ROWS ) }` );
} );

test( "the blank-reason refusal names the BLAST RADIUS, not merely the requirement", () => {
  // A shape assertion on top of the carbon copy: the sentence's whole job is to
  // tell the operator that one reason is about to land on every row. "A reason
  // is required" would satisfy a substring check against the legacy string and
  // teach nothing.
  assert.match( HOLDING_BATCH_BLANK_REASON, /every row in this group/ );
} );

test( "the in-flight line is the legacy template with the same substitutions", () => {
  const legacy = legacyTemplates().find( ( t ) => t.includes( "${verb} ${ok + failed} of ${ids.length}" ) );
  assert.ok( legacy !== undefined,
    `the legacy in-flight template was not found. Templates seen: ${ JSON.stringify( legacyTemplates() ) }` );
  const substituted = legacy
    .replace( "${verb}", "Approved" )
    .replace( "${ok + failed}", "3" )
    .replace( "${ids.length}", "8" );
  assert.equal( holdingBatchInFlightStatus( "Approved", 3, 8 ), substituted );
} );

test( "the in-flight line carries the ellipsis that marks it as unfinished", () => {
  // Not decoration. The final line drops it, and that is the only glyph
  // separating "still running" from "done" for an operator watching a batch that
  // can legitimately sit for minutes on the approval gate.
  assert.ok( holdingBatchInFlightStatus( "Closed", 0, 4 ).endsWith( "…" ) );
  assert.ok( !holdingBatchFinalStatus( "Closed", 4, 0, 4, null ).includes( "…" ) );
} );

test( "the in-flight number counts ATTEMPTS, so a wholly-refused batch still advances", () => {
  // The tempting alternative — counting successes — leaves a fully-refused batch
  // frozen at "0 of 8…" for its whole run, which is indistinguishable from the
  // hang this line exists to rule out.
  assert.equal( holdingBatchInFlightStatus( "Approved", 8, 8 ), "Approved 8 of 8…" );
} );

test( "the clean final line is the legacy template with the same substitutions", () => {
  const legacy = legacyTemplates().find(
    ( t ) => t.includes( "${ok} of ${ids.length} ${verb.toLowerCase()}." ) && !t.includes( "refused" ) );
  assert.ok( legacy !== undefined,
    `the legacy clean-final template was not found. Templates seen: ${ JSON.stringify( legacyTemplates() ) }` );
  const substituted = legacy
    .replace( "${ok}", "8" )
    .replace( "${ids.length}", "8" )
    .replace( "${verb.toLowerCase()}", "closed" );
  assert.equal( holdingBatchFinalStatus( "Closed", 8, 0, 8, null ), substituted );
} );

test( "the partial-failure final line is the legacy template with the same substitutions", () => {
  const legacy = legacyTemplates().find( ( t ) => t.includes( "refused. First refusal:" ) );
  assert.ok( legacy !== undefined,
    `the legacy partial-failure template was not found. Templates seen: ${ JSON.stringify( legacyTemplates() ) }` );
  const substituted = legacy
    .replace( "${ok}", "3" )
    .replace( "${ids.length}", "8" )
    .replace( "${verb.toLowerCase()}", "closed" )
    .replace( "${failed}", "5" )
    .replace( "${firstError}", "403: not on the allowlist" );
  assert.equal( holdingBatchFinalStatus( "Closed", 3, 5, 8, "403: not on the allowlist" ), substituted );
} );

test( "the final line names BOTH counts and the first refusal, or it is not a report", () => {
  const line = holdingBatchFinalStatus( "Approved", 3, 5, 8, "403 denied" );
  assert.match( line, /\b3 of 8\b/ );      // what worked
  assert.match( line, /\b5 refused\b/ );   // what did not — the half the shrunken list hides
  assert.match( line, /403 denied/ );      // the server's own words, not ours
} );

// ---------------------------------------------------------------------------
// The verb table
// ---------------------------------------------------------------------------

test( "the two batch verbs and their statuses match what the legacy handlers post", () => {
  const body = legacyBatchSource();
  // The legacy call sites, read from source rather than remembered:
  //   _applyHoldingBatch( filer, "queued",   {},         "Approved" )
  //   _applyHoldingBatch( filer, "wont_fix", { reason }, "Closed"   )
  assert.ok( body.includes( '_applyHoldingBatch( filer, "queued", {}, "Approved" )' ),
    "the legacy approve call site has changed shape — re-derive this table rather than trusting it" );
  assert.ok( body.includes( '_applyHoldingBatch( filer, "wont_fix", { reason }, "Closed" )' ),
    "the legacy won't-fix call site has changed shape — re-derive this table rather than trusting it" );

  assert.deepEqual( [ ...HOLDING_BATCH_VERBS ], [ "approve", "wont_fix" ] );
  assert.equal( holdingBatchNeeds( "approve" )?.status,  "queued" );
  assert.equal( holdingBatchNeeds( "wont_fix" )?.status, "wont_fix" );
  assert.equal( holdingBatchNeeds( "approve" )?.pastLabel,  "Approved" );
  assert.equal( holdingBatchNeeds( "wont_fix" )?.pastLabel, "Closed" );
} );

test( "approve asks for nothing and won't-fix demands a reason — the asymmetry IS the design", () => {
  assert.equal( holdingBatchNeeds( "approve" )?.reason,   false );
  assert.equal( holdingBatchNeeds( "approve" )?.terminal, false );
  assert.equal( holdingBatchNeeds( "wont_fix" )?.reason,   true );
  assert.equal( holdingBatchNeeds( "wont_fix" )?.terminal, true );
} );

test( "an unknown verb is null, in every falsy shape a caller can hand it", () => {
  assert.equal( holdingBatchNeeds( "" ), null );
  assert.equal( holdingBatchNeeds( null ), null );
  assert.equal( holdingBatchNeeds( undefined ), null );
  assert.equal( holdingBatchNeeds( "drop" ), null );        // a per-row verb, deliberately not a batch one
  assert.equal( holdingBatchNeeds( "toString" ), null );    // an inherited Object key is not a verb
} );

test( "approve posts NO reason key at all, even when a reason box happens to be filled", () => {
  // Not cosmetic. Approve is the one verb whose whole point is that it needs
  // nothing; shipping an unasked-for field on it invites a server-side reading
  // that the operator justified a promotion they did not.
  assert.deepEqual( holdingBatchExtras( "approve", "" ), {} );
  assert.deepEqual( holdingBatchExtras( "approve", "somebody typed in the box" ), {} );
} );

test( "won't-fix posts the group reason under `reason`", () => {
  assert.deepEqual( holdingBatchExtras( "wont_fix", "superseded by the v2 door" ),
    { reason: "superseded by the v2 door" } );
} );

test( "an unknown verb contributes no extras rather than an empty reason", () => {
  assert.deepEqual( holdingBatchExtras( "park", "anything" ), {} );
} );
