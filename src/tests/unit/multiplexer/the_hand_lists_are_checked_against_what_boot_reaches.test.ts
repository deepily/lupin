// Row 87812328 — Clayton 😎's F2 and F3, which are ONE defect on TWO surfaces.
//
// 🔴 A HAND-MAINTAINED LIST WITH NOTHING CHECKING IT DRIFTS SILENTLY, AND BOTH
// OF THESE HAD. `SECTION_TOGGLES` names the panes a viewer can hide and was
// missing the two newest panes, so an operator on the multiplexer could not hide
// either while on legacy they could — and one of the two missing buttons is a
// Rick voice ruling (2026-09-02, notifications.html:51-62). `bootCompletePayload
// .handlers` names every mounted renderer for AC9's Playwright contract and
// omitted the same two, so unmounting them left that assertion green.
//
// ═══════════════════════════════════════════════════════════════════════════
// WHY THE OBVIOUS FIX IS WRONG, MEASURED — AND IT WAS PROPOSED TWICE
// ═══════════════════════════════════════════════════════════════════════════
//
// The review's prescription was "DERIVE the population, do not extend the list".
// Right about the FAILURE, wrong about the remedy — and the two wrong remedies
// fail in opposite directions:
//
//   1. DERIVE FROM THE PAGE → deletes a working toggle. `commons-activity-pane`
//      is NOT declared in multiplexer.html at all; it is declared at
//      `render/templates/broadcastCard.ts:94`, rendered into the notifications
//      subtree, and querySelected at `boot.ts:551`. A guard asserting
//      SECTION_TOGGLES equals the page's panes demands DELETING it.
//
//      ⇒ It also reconciles the review's own 7 / 6 / 5 arithmetic, which does
//        not otherwise add up: six toggles of which five match seven panes
//        leaves ONE unmatched, and that one is commons — unmatched because it
//        lives in the other source, not because it is wrong. Reported there as
//        a positive control; it was a finding.
//
//   2. DERIVE FROM WHAT BOOT MOUNTS → a comparison that cannot disagree. Delete
//      a mount and it also leaves the list it is checked against, so the guard
//      agrees with itself and reports nothing. This one was MY proposal and
//      María 🌸 killed it at design: it is this repo's § A COMPARISON WHOSE TWO
//      SIDES COME FROM ONE SOURCE, i.e. a tautology wearing an assertion.
//
// 🔨 MARÍA'S RULING (2026-09-05 23:47 EDT): the hand-maintained list IS the
// right shape — as the INDEPENDENT side. Nobody generates it, so the guard can
// assert BOTH directions against it without either side supplying its own
// denominator. What was wrong was a hand list with no guard in either direction.
//
// ⇒ So this file does NOT replace either list. It pins them:
//     · every pane the product actually declares must have a toggle
//     · every toggle must name a pane that actually exists
//   One direction alone is half a guard — the first catches a pane nobody can
//   hide, the second catches a toggle pointing at nothing.
//
// ⚠️ `commons-activity-pane` is the live witness that the registry is not a
// page-scrape. It is in SECTION_TOGGLES and NOT in multiplexer.html, so a future
// "simplification" of this guard to the page alone reddens here rather than
// silently deleting a ratified button.
//
// ⚠️ SCOPE, so nobody reads this wider than it is: these are WIRING guards. They
// establish that a toggle exists for every pane and that the payload names every
// mount. They say NOTHING about whether pressing a toggle works — that is a
// different question, on a different surface, and it is not answered here.
//
// Run: npx tsx --test src/tests/unit/multiplexer/the_hand_lists_are_checked_against_what_boot_reaches.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve, join } from "node:path";

import { SECTION_TOGGLES } from "../../../lupin_app/static/js/multiplexer/render/templates/sectionToolbar";

const HERE      = dirname( fileURLToPath( import.meta.url ) );
const MUX       = resolve( HERE, "../../../lupin_app/static/js/multiplexer" );
const TEMPLATES = join( MUX, "render/templates" );
const BOOT_PATH = join( MUX, "boot.ts" );
const HTML_PATH = resolve( HERE, "../../../lupin_app/static/html/multiplexer.html" );

const bootSource = (): string => readFileSync( BOOT_PATH, "utf8" );

// ---------------------------------------------------------------------------
// The OBSERVED side for the toggles: every pane the product declares, from BOTH
// of the two sources that declare one.
// ---------------------------------------------------------------------------

/** Panes declared as static markup in the page. */
function panesInPage(): Set<string> {
  const html = readFileSync( HTML_PATH, "utf8" );
  return new Set( ( html.match( /<section\s+id="([a-zA-Z-]+-pane)"/g ) ?? [] )
    .map( ( m ) => /"([^"]+)"/.exec( m )![ 1 ] ) );
}

/**
 * Panes declared inside a RENDER TEMPLATE and injected at runtime.
 *
 * 🔴 THIS SOURCE IS THE WHOLE POINT OF THE FILE. Leave it out and the guard
 * reports `commons-activity-pane` as a toggle with no pane — a false positive
 * that reads as a finding, and whose "fix" is deleting a working button.
 */
function panesInTemplates(): Set<string> {
  const found = new Set<string>();
  for ( const entry of readdirSync( TEMPLATES ) ) {
    if ( !entry.endsWith( ".ts" ) || entry.endsWith( ".test.ts" ) ) continue;
    const src = readFileSync( join( TEMPLATES, entry ), "utf8" );
    for ( const m of src.match( /<section\s+id="([a-zA-Z-]+-pane)"/g ) ?? [] ) {
      found.add( /"([^"]+)"/.exec( m )![ 1 ] );
    }
  }
  return found;
}

function declaredPanes(): Set<string> {
  return new Set( [ ...panesInPage(), ...panesInTemplates() ] );
}

test( "the pane sweeps reach real populations, from BOTH sources, before anything is concluded", () => {
  // 🔴 POSITIVE CONTROLS FIRST. A sweep that matched nothing would make every
  // set-difference below pass over an empty set, and an absence would print
  // exactly like a clean bill of health.
  const page      = panesInPage();
  const templates = panesInTemplates();

  assert.ok( page.size >= 5,
    `the page sweep found only ${ page.size } panes — the regex is not reaching the markup` );
  assert.ok( page.has( "task-list-pane" ),
    "the page no longer declares the task-list pane — or this sweep is reading the wrong file" );

  // And the template source specifically, because it is the one a naive
  // implementation drops and its absence is silent.
  assert.ok( templates.has( "commons-activity-pane" ),
    "the TEMPLATE sweep found no commons pane. Either it moved into the page — in which " +
    "case say so and simplify this file deliberately — or this sweep has stopped reaching " +
    "render/templates, and the guard below is now one source short without saying so" );
  assert.ok( !page.has( "commons-activity-pane" ),
    "the commons pane is now declared in the page too. That is a real change and may be " +
    "right, but it removes this file's only witness that the two-source union is load-bearing" );
} );

test( "🔴 EVERY PANE THE PRODUCT DECLARES HAS A VISIBILITY TOGGLE", () => {
  // Clayton 😎's F2. Catches a pane an operator cannot hide — the direction that
  // fires when a NEW pane ships, which is how both of the newest ones shipped.
  const registry = new Set( SECTION_TOGGLES.map( ( s ) => s.sectionId ) );
  const missing  = [ ...declaredPanes() ].filter( ( id ) => !registry.has( id ) ).sort();

  assert.deepEqual( missing, [],
    `these panes ship with no way to hide them: ${ missing.join( ", " ) }. Add each to ` +
    `SECTION_TOGGLES in render/templates/sectionToolbar.ts. Do NOT make that list derive ` +
    `itself from the panes — a list generated from what it checks cannot disagree with it, ` +
    `which is the defect this guard exists to prevent rather than a shortcut past it` );
} );

test( "🔴 AND EVERY TOGGLE NAMES A PANE THAT ACTUALLY EXISTS", () => {
  // The other direction, and it is not decorative: without it a toggle left
  // behind by a deleted pane paints a button that hides nothing, and the test
  // above would stay green forever.
  const declared = declaredPanes();
  const orphans  = SECTION_TOGGLES.map( ( s ) => s.sectionId )
    .filter( ( id ) => !declared.has( id ) ).sort();

  assert.deepEqual( orphans, [],
    `these toggles name panes nothing declares: ${ orphans.join( ", " ) }. Either the pane ` +
    `was deleted and its toggle should go with it, or the pane is declared somewhere ` +
    `neither sweep reads — in which case ADD THAT SOURCE here rather than deleting the toggle` );
} );

// ---------------------------------------------------------------------------
// F3 — the same shape on the boot-complete payload
// ---------------------------------------------------------------------------

/**
 * Every renderer boot actually constructs, as the payload spells its key.
 *
 * ⚠️ THE TWO SIDES ARE DIFFERENT STATEMENTS, NOT ONE DERIVED FROM THE OTHER.
 * They share a FILE, which is not the same as sharing a source: deleting a mount
 * removes its `create…Renderer(` call and leaves the payload entry, so this
 * comparison can still fail. That is the property María's ruling asks for.
 */
function renderersBootConstructs(): Set<string> {
  const calls = bootSource()
    .split( "\n" )
    .filter( ( line ) => !line.trimStart().startsWith( "//" ) )
    .flatMap( ( line ) => line.match( /\bcreate([A-Z][A-Za-z]*)Renderer\s*\(/g ) ?? [] )
    .map( ( m ) => /create([A-Z][A-Za-z]*)Renderer/.exec( m )![ 1 ] )
    .map( ( name ) => `${ name.charAt( 0 ).toLowerCase() }${ name.slice( 1 ) }Renderer` );
  return new Set( calls );
}

/** The payload's own keys, read from boot.ts's handlers block. */
function payloadHandlerKeys(): Set<string> {
  const block = /handlers\s*:\s*\{([\s\S]*?)\n\s*\},/.exec( bootSource() );
  assert.ok( block, "the bootCompletePayload.handlers block is no longer findable in boot.ts" );
  return new Set( ( block![ 1 ].match( /^\s*([a-zA-Z]+)\s*:/gm ) ?? [] )
    .map( ( m ) => /([a-zA-Z]+)/.exec( m )![ 1 ] )
    .filter( ( k ) => k.endsWith( "Renderer" ) ) );
}

// 🔴 DECLARED, NOT DERIVED — the same treatment the sibling boot guard gives its
// two non-conforming mount ids. A renderer whose payload key differs from its
// factory name is an EXCEPTION somebody made on purpose, so it is written down
// and a NEW divergence reddens on the day it lands. Widening the derivation to
// swallow these would fix today and be wrong at the next rename, which is the
// enumeration defect wearing a regex.
const KEY_ALIASES: Readonly<Record<string, string>> = {
  notificationsListRenderer : "notificationsRenderer",   // the payload names the pane, not the list
  jobsPaneRenderer          : "jobsRenderer",            // likewise
};

// Renderers deliberately absent from the payload: both are sub-renderers mounted
// INSIDE another pane's subtree rather than top-level surfaces AC9 asserts on.
const NOT_IN_PAYLOAD: ReadonlySet<string> = new Set( [
  "broadcastCardRenderer",
  "notificationsHeaderRenderer",
] );

test( "the boot-payload sweeps reach real populations before anything is concluded", () => {
  const built = renderersBootConstructs();
  const keys  = payloadHandlerKeys();
  assert.ok( built.size >= 10, `the construction sweep found only ${ built.size } renderers` );
  assert.ok( keys.size  >= 10, `the payload sweep found only ${ keys.size } handler keys` );
  assert.ok( built.has( "taskListRenderer" ), "boot no longer constructs the task-list renderer" );
  assert.ok( keys.has( "taskListRenderer" ),  "the payload no longer names the task-list renderer" );
} );

test( "🔴 EVERY RENDERER BOOT MOUNTS IS NAMED IN THE BOOT-COMPLETE PAYLOAD", () => {
  // Clayton 😎's F3. No runtime behaviour — this is AC9's wiring contract, and a
  // renderer missing from it can be unmounted with the assertion staying green.
  // It is in scope because that is this branch's whole method: a component can
  // be complete and absent from the product, and the check for that is the one
  // people skip as ceremony.
  const keys    = payloadHandlerKeys();
  const missing = [ ...renderersBootConstructs() ]
    .map( ( name ) => KEY_ALIASES[ name ] ?? name )
    .filter( ( key ) => !keys.has( key ) && !NOT_IN_PAYLOAD.has( key ) )
    .sort();

  assert.deepEqual( missing, [],
    `boot mounts these renderers and the boot-complete payload does not name them: ` +
    `${ missing.join( ", " ) }. Add each to bootCompletePayload.handlers as ` +
    `\`<name> : "mounted"\`, per the convention boot.ts:272 already documents. If one is ` +
    `deliberately absent, add it to NOT_IN_PAYLOAD here WITH ITS REASON — a declared ` +
    `exception is checkable and an undeclared one is invisible` );
} );

test( "🔴 AND EVERY PAYLOAD KEY NAMES A RENDERER BOOT ACTUALLY CONSTRUCTS", () => {
  // The direction that catches a stale entry: a renderer deleted from boot whose
  // payload key survives claims a mount the app no longer has, and AC9 then
  // asserts on a surface nobody builds.
  const built = new Set( [ ...renderersBootConstructs() ].map( ( n ) => KEY_ALIASES[ n ] ?? n ) );
  const stale = [ ...payloadHandlerKeys() ].filter( ( k ) => !built.has( k ) ).sort();

  assert.deepEqual( stale, [],
    `the boot-complete payload names these renderers and boot constructs none of them: ` +
    `${ stale.join( ", " ) }. The payload is a claim about what the app mounted; a key ` +
    `outliving its renderer makes that claim false while every test stays green` );
} );

test( "the declared exceptions are still REAL, not leftovers nobody rechecked", () => {
  // ⚠️ A declared-exception list is itself a hand-maintained list, so it gets the
  // same treatment as the two above: an entry naming a renderer that no longer
  // exists is a silent widening of the frame. This is the guard on the guard.
  const built = renderersBootConstructs();
  for ( const name of NOT_IN_PAYLOAD ) {
    assert.ok( built.has( name ),
      `NOT_IN_PAYLOAD still excuses ${ name }, which boot no longer constructs. Remove it — ` +
      `an exception for something absent quietly excuses whatever takes its name next` );
  }
  for ( const from of Object.keys( KEY_ALIASES ) ) {
    assert.ok( built.has( from ),
      `KEY_ALIASES still maps ${ from }, which boot no longer constructs. Remove it.` );
  }
} );
