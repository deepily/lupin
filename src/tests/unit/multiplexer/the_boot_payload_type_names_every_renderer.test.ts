// 🔴 THE FIFTH REGISTRATION EDIT — THE ONE NOTHING WATCHED, AND THE FILE KNEW.
//
// Inserting a pane into the multiplexer is documented as FOUR edits: the HTML
// section, SECTION_TOGGLES, the boot.ts mount block, and the
// bootCompletePayload.handlers LITERAL. It is FIVE. The fifth is the
// `BootCompletePayload.handlers` INTERFACE in shared/types.ts, which declares
// one optional `<name>Renderer?: string` key per mounted renderer.
//
// MEASURED, 2026-09-07, row 470b7509. I made all four documented edits for the
// finished-tasks pane. BOTH existing guards stayed GREEN —
// the_hand_lists_are_checked_against_what_boot_reaches (7 passed) and
// boot_mounts_every_pane_the_page_declares (10 passed). `tsc --noEmit` is what
// failed:
//     boot.ts(723,7): error TS2353: Object literal may only specify known
//     properties, and 'finishedTasksRenderer' does not exist in type '{ … }'
//
// ⚠️ AND THE FILE HAD ALREADY PREDICTED IT. shared/types.ts:782-788, written by
// whoever landed the holding-area and epic-board panes: "THIS TYPE IS A THIRD
// HAND-LIST OF THE SAME POPULATION, and it is the one nothing in the test tier
// watches … `tsc` caught it, which is luck of the type system rather than a
// check somebody designed. Adding a renderer means editing THREE places, and
// only two of them redden."
//
// ⇒ It was written down and it was not a control. This file is the control.
//
// 🔴 WHY tsc IS NOT ENOUGH, AND THIS IS THE WHOLE ARGUMENT FOR THE SECOND TEST
// BELOW. The compiler fires only on ADDING a key the interface lacks. It says
// NOTHING in the other direction: delete a renderer from boot and its interface
// key survives, compiling cleanly and claiming a mount the app no longer has —
// exactly the staleness the sibling guard already polices on the literal. One
// direction is half a guard.
//
// ⚠️ SCOPE: this is a WIRING guard. It establishes that three declarations of
// one population agree. It says NOTHING about whether any renderer works.
//
// Run: npx tsx --test src/tests/unit/multiplexer/the_boot_payload_type_names_every_renderer.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const HERE       = dirname( fileURLToPath( import.meta.url ) );
const BOOT_PATH  = resolve( HERE, "../../../lupin_app/static/js/multiplexer/boot.ts" );
const TYPES_PATH = resolve( HERE, "../../../lupin_app/static/js/multiplexer/shared/types.ts" );

/** One reader for boot.ts, so the two sweeps below cannot disagree about what it says. */
const bootSource = (): string => readFileSync( BOOT_PATH, "utf8" );

/**
 * The keys the PAYLOAD LITERAL sets, from boot.ts's handlers block.
 *
 * Deliberately the same extraction the sibling guard uses, so the two files
 * cannot disagree about what the literal says while disagreeing about what it
 * should contain.
 */
function literalKeys(): Set<string> {
  const block = /handlers\s*:\s*\{([\s\S]*?)\n\s*\},/.exec( bootSource() );
  assert.ok( block, "the bootCompletePayload.handlers block is no longer findable in boot.ts" );
  return new Set( ( block![ 1 ]!.match( /^\s*([a-zA-Z]+)\s*:/gm ) ?? [] )
    .map( ( m ) => /([a-zA-Z]+)/.exec( m )![ 1 ]! )
    .filter( ( k ) => k.endsWith( "Renderer" ) ) );
}

/**
 * The keys the INTERFACE declares, from BootCompletePayload's handlers member.
 *
 * ⚠️ THE TWO SIDES ARE READ FROM DIFFERENT FILES, which is what keeps this a
 * comparison rather than a tautology. A guard deriving one from the other would
 * agree with itself and report nothing — this branch's § A COMPARISON WHOSE TWO
 * SIDES COME FROM ONE SOURCE.
 */
function interfaceKeys(): Set<string> {
  const src   = readFileSync( TYPES_PATH, "utf8" );
  const iface = /interface\s+BootCompletePayload\s*\{([\s\S]*?)\n\}/.exec( src );
  assert.ok( iface, "the BootCompletePayload interface is no longer findable in shared/types.ts" );
  const block = /handlers\s*:\s*\{([\s\S]*?)\n\s{2}\};/.exec( iface![ 1 ]! );
  assert.ok( block, "the handlers member of BootCompletePayload is no longer findable" );
  return new Set( ( block![ 1 ]!.match( /^\s*([a-zA-Z]+)\??\s*:/gm ) ?? [] )
    .map( ( m ) => /([a-zA-Z]+)/.exec( m )![ 1 ]! )
    .filter( ( k ) => k.endsWith( "Renderer" ) ) );
}

/**
 * The renderers boot actually CONSTRUCTS — a THIRD source, and the one that
 * supplies this file's denominator.
 *
 * 🔴 IT EXISTS BECAUSE A FLOOR IS NOT A POPULATION (Mr. Radio 🦉's review of
 * 162be6c2, 2026-09-07). The first cut of this file asserted `size >= 10` as its
 * positive control. That proves the regex is not returning EMPTY and nothing
 * more: a sweep degraded to finding 11 of 18 passes it, and then both
 * directional comparisons below run over a silently truncated population and
 * agree perfectly. `>= 10` catches the loud failure and waves through the quiet
 * one, which is the wrong way round.
 *
 * ⚠️ THE CONSTRUCTION SWEEP IS NOT A FOURTH HAND-LIST. It reads `create…Renderer(`
 * calls out of boot.ts, so it moves on its own when a renderer is added or
 * deleted — a derived denominator rather than a number somebody maintains.
 */
function renderersBootConstructs(): Set<string> {
  return new Set( bootSource()
    .split( "\n" )
    .filter( ( line ) => !line.trimStart().startsWith( "//" ) )
    .flatMap( ( line ) => line.match( /\bcreate([A-Z][A-Za-z]*)Renderer\s*\(/g ) ?? [] )
    .map( ( m ) => /create([A-Z][A-Za-z]*)Renderer/.exec( m )![ 1 ]! )
    .map( ( name ) => `${ name.charAt( 0 ).toLowerCase() }${ name.slice( 1 ) }Renderer` ) );
}

// Declared exceptions, copied in shape from the sibling guard rather than
// re-derived: a renderer whose payload key differs from its factory name, and
// the two sub-renderers deliberately absent from the payload. Both lists are
// themselves checked below — an exception for something that no longer exists
// quietly widens the frame.
const KEY_ALIASES: Readonly<Record<string, string>> = {
  notificationsListRenderer : "notificationsRenderer",
  jobsPaneRenderer          : "jobsRenderer",
};
const NOT_IN_PAYLOAD: ReadonlySet<string> = new Set( [
  "broadcastCardRenderer",
  "notificationsHeaderRenderer",
] );

/** What the payload and the interface SHOULD each contain, derived from boot. */
function expectedKeys(): Set<string> {
  return new Set( [ ...renderersBootConstructs() ]
    .map( ( n ) => KEY_ALIASES[ n ] ?? n )
    .filter( ( k ) => !NOT_IN_PAYLOAD.has( k ) ) );
}

test( "🔴 THE DENOMINATOR IS DERIVED FROM BOOT, NOT A FLOOR — a truncated sweep reddens", () => {
  // Mr. Radio's finding, closed. Both sweeps must find EXACTLY the population
  // boot constructs; a regex that degrades to a subset now fails here instead of
  // sailing past a `>= 10`.
  const expected = expectedKeys();
  const lit      = literalKeys();
  const iface    = interfaceKeys();

  // The anchors that keep this from being a tautology: three named renderers
  // that must appear in ALL THREE sources. If the construction sweep itself
  // broke, `expected` would shrink and the equalities would still hold — these
  // are what makes that visible.
  for ( const named of [ "taskListRenderer", "fleetStatusRenderer", "finishedTasksRenderer" ] ) {
    assert.ok( expected.has( named ), `the CONSTRUCTION sweep no longer finds ${ named } — its regex is not reaching boot.ts` );
    assert.ok( lit.has( named ),      `the payload literal no longer names ${ named }` );
    assert.ok( iface.has( named ),    `the interface no longer declares ${ named }` );
  }

  assert.equal( lit.size, expected.size,
    `the payload literal names ${ lit.size } renderers and boot constructs ${ expected.size }` );
  assert.equal( iface.size, expected.size,
    `the interface declares ${ iface.size } renderers and boot constructs ${ expected.size }` );
} );

test( "the declared exceptions are still REAL, not leftovers nobody rechecked", () => {
  // ⚠️ The exception lists are themselves hand-maintained, so they get the same
  // treatment as everything else here: an entry naming a renderer boot no longer
  // constructs silently widens the frame for whatever takes that name next.
  const built = renderersBootConstructs();
  for ( const name of NOT_IN_PAYLOAD ) {
    assert.ok( built.has( name ), `NOT_IN_PAYLOAD still excuses ${ name }, which boot no longer constructs` );
  }
  for ( const from of Object.keys( KEY_ALIASES ) ) {
    assert.ok( built.has( from ), `KEY_ALIASES still maps ${ from }, which boot no longer constructs` );
  }
} );

test( "🔴 EVERY RENDERER THE PAYLOAD SETS IS DECLARED BY THE INTERFACE", () => {
  // The direction `tsc` already covers — kept because a compiler error is a
  // build-time accident of the type system, and this file is the place a reader
  // looks to find out that the fifth edit exists at all.
  const iface   = interfaceKeys();
  const missing = [ ...literalKeys() ].filter( ( k ) => !iface.has( k ) ).sort();

  assert.deepEqual( missing, [],
    `boot's payload sets these renderer keys and BootCompletePayload does not declare them: ` +
    `${ missing.join( ", " ) }. Add each to the handlers member in shared/types.ts. Inserting a ` +
    `pane is FIVE edits, not four: HTML section, SECTION_TOGGLES, the boot mount block, the ` +
    `payload literal, and this interface` );
} );

test( "🔴 AND EVERY KEY THE INTERFACE DECLARES IS ONE THE PAYLOAD ACTUALLY SETS", () => {
  // 🔴 THE DIRECTION tsc CANNOT SEE, and the reason this file is not redundant
  // with the compiler. Delete a renderer from boot and its interface key
  // compiles cleanly forever, declaring a mount the app no longer performs.
  const lit   = literalKeys();
  const stale = [ ...interfaceKeys() ].filter( ( k ) => !lit.has( k ) ).sort();

  assert.deepEqual( stale, [],
    `BootCompletePayload declares these renderer keys and boot's payload sets none of them: ` +
    `${ stale.join( ", " ) }. The interface is a claim about what the app mounts; a key ` +
    `outliving its renderer makes that claim false, and the compiler is silent about it` );
} );

test( "the finished-tasks pane is named on BOTH sides — the row that found this gap", () => {
  // Named explicitly rather than left to the set comparisons, so a reader
  // arriving from row 470b7509 can see the specific claim it landed.
  assert.ok( literalKeys().has( "finishedTasksRenderer" ) );
  assert.ok( interfaceKeys().has( "finishedTasksRenderer" ) );
} );
