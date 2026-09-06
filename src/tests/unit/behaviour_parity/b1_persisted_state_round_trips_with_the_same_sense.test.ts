// BEHAVIOUR TIER — B1: persisted state round-trips between the two clients with
// the same SENSE.
//
// Row 87812328 (P0). Plan §4.2/§4.3, src/rnd/2026.09.05-carbon-copy-accordions-
// into-multiplexer.md. Specification: Maya 🌻's inventory §3.1.
//
// ═══════════════════════════════════════════════════════════════════════════
// 🔴 WHAT THIS TIER IS, AND WHAT A GREEN RUN DOES NOT MEAN
// ═══════════════════════════════════════════════════════════════════════════
//
// THIS TIER PROVES THE TWO CLIENTS AGREE. IT DOES NOT PROVE THE BEHAVIOUR IS
// CORRECT. If the legacy behaviour is wrong, a perfect score reproduces the bug
// faithfully in both clients — now provably identically. A green run here is a
// PARITY signal and never a CORRECTNESS signal. That is part of the
// instrument's definition, at María 🌸's requirement, and it is stated here
// rather than in a footnote because this file will be cited for months.
//
// ═══════════════════════════════════════════════════════════════════════════
// WHY B1 EXISTS AT ALL — THE GAP NO OTHER TIER CAN SEE
// ═══════════════════════════════════════════════════════════════════════════
//
// Measured across all three layout-parity methodology documents: `behaviour` 0
// hits, `click` 0, `keyboard` 0, `persist`/`localStorage` 0. Their own scope
// line is "parity is equality of the CSSOM, measured." Rick asked for two axes
// — "look exactly" AND "behave exactly" — and the existing oracle answers one.
//
// 🔴 AND THE TWO PANES STORE THEIR STATE WITH OPPOSITE POLARITY, ON PURPOSE:
//
//     lupin.taskList.collapsedOwners  JSON ARRAY  membership => COLLAPSED
//     lupin.epicBoard.groupState      JSON MAP    value true => EXPANDED
//
// Porting one from the other INVERTS a real operator's saved state, and it fails
// INVISIBLY: the surface renders correctly, every CSSOM tier passes, and the
// only symptom is that everything the user collapsed comes back open. Plan §7.2.
//
// ⚠️ AND THIS IS NOT A TEST-ONLY CONCERN. Both clients read and write THE SAME
// TWO KEYS — verified below by extracting the legacy literals from
// notifications.js source rather than typing them. So a polarity divergence
// corrupts the saved state of any operator who uses both pages.
//
// ═══════════════════════════════════════════════════════════════════════════
// THE ONE DESIGN DECISION WORTH DEFENDING
// ═══════════════════════════════════════════════════════════════════════════
//
// 🔴 THE LEGACY KEY CONSTANTS ARE PARSED OUT OF notifications.js, NEVER TYPED
// HERE AND NEVER COPIED FROM THE MUX MODULE. The legacy class is loaded with the
// constructor SKIPPED (the established notifications_js harness), so its
// `this.TASK_LIST_COLLAPSED_KEY` fields have to be supplied. Supplying them from
// the mux's exported constant would make "both clients use the same key" true BY
// CONSTRUCTION — a comparison whose two sides come from one source, which is a
// tautology wearing an assertion. Parsing the legacy literal keeps the two sides
// independent, so the key-agreement assertion can actually fail.
//
// Run: npx tsx --test src/tests/unit/behaviour_parity/b1_persisted_state_round_trips_with_the_same_sense.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

// The MUX side, imported as the product exports it.
import {
  TASK_LIST_COLLAPSED_KEY,
  loadCollapsedOwners,
  saveCollapsedOwners,
  toggleCollapsedOwner,
} from "../../../lupin_app/static/js/multiplexer/render/taskListCollapse";
import {
  EPIC_BOARD_STATE_KEY,
  EPIC_ON_RICK_KEY,
  loadEpicGroupState,
  saveEpicGroupState,
  epicGroupIsExpanded,
  epicDefaultExpanded,
  toggleEpicCollapsed,
} from "../../../lupin_app/static/js/multiplexer/render/epicBoardCollapse";

const HERE            = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

/** The legacy key literals, read from the product's own source. */
function legacyConstantsFromSource(): Record<string, string> {
  const src = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const out: Record<string, string> = {};
  for ( const name of [
    "TASK_LIST_COLLAPSED_KEY", "EPIC_BOARD_STATE_KEY", "EPIC_ON_RICK_KEY", "EPIC_DRIFT_KEY",
  ] ) {
    const m = new RegExp( `this\\.${ name }\\s*=\\s*'([^']+)'` ).exec( src );
    assert.ok( m, `could not read this.${ name } out of notifications.js — the harness is ` +
                  `reading the wrong file, or the constructor moved` );
    out[ name ] = m![ 1 ];
  }
  return out;
}

/* eslint-disable @typescript-eslint/no-explicit-any */
let LEGACY_KEYS: Record<string, string>;
let legacy: any;

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();

  LEGACY_KEYS = legacyConstantsFromSource();

  const src     = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx = src.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext(
    src.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;",
    { filename: NOTIFICATIONS_JS },
  );

  // Constructor skipped (the established harness); the collapse methods read only
  // these four fields, supplied from the SOURCE parse above.
  legacy = Object.create( ( globalThis as any ).NotificationsUI.prototype );
  for ( const [ k, v ] of Object.entries( LEGACY_KEYS ) ) legacy[ k ] = v;
} );

beforeEach( () => { globalThis.localStorage.clear(); } );

// ---------------------------------------------------------------------------
// GATE — the harness reaches both clients before any parity claim is made
// ---------------------------------------------------------------------------

test( "GATE: both clients are really loaded and really share one localStorage", () => {
  // 🔴 Without this, every round-trip below is satisfied by a harness where one
  // side silently does nothing: writing and reading the same absent value agrees
  // perfectly. An empty result and a matching result print identically.
  assert.equal( typeof legacy.loadCollapsedTaskOwners, "function",
    "the legacy class did not load — vm.runInThisContext found no collapse methods" );
  assert.equal( typeof legacy.toggleEpicCollapsed, "function" );

  globalThis.localStorage.setItem( "__probe__", "1" );
  assert.equal( globalThis.localStorage.getItem( "__probe__" ), "1",
    "localStorage is not writable in this harness — every round-trip below is vacuous" );
  globalThis.localStorage.removeItem( "__probe__" );
} );

test( "🔴 THE TWO CLIENTS AGREE ON THE KEY NAMES — legacy literals parsed from source", () => {
  // If these ever diverge, nothing else in this file is meaningful: the two
  // clients would be reading different storage and would "agree" only because
  // they never see each other's writes.
  assert.equal( LEGACY_KEYS.TASK_LIST_COLLAPSED_KEY, TASK_LIST_COLLAPSED_KEY,
    "the task-list storage key has diverged between the clients — an operator's collapse " +
    "choices no longer follow them between the two pages" );
  assert.equal( LEGACY_KEYS.EPIC_BOARD_STATE_KEY, EPIC_BOARD_STATE_KEY,
    "the epic-board storage key has diverged between the clients" );
  assert.equal( LEGACY_KEYS.EPIC_ON_RICK_KEY, EPIC_ON_RICK_KEY,
    "the on-Rick sentinel has diverged — the two clients would default that group differently" );
} );

// ---------------------------------------------------------------------------
// B1a — TASK LIST: membership means COLLAPSED, both directions
// ---------------------------------------------------------------------------

test( "🔴 B1a LEGACY writes a collapsed owner -> THE MUX READS IT AS COLLAPSED", () => {
  legacy.toggleTaskOwnerCollapsed( "alice" );

  assert.ok( loadCollapsedOwners().has( "alice" ),
    "the operator collapsed alice's group on the legacy page and the multiplexer does not see " +
    "her as collapsed. If the mux read this array as EXPANDED owners, every group the user " +
    "closed would come back open and every tier that measures the CSSOM would still pass" );
} );

test( "🔴 B1a THE MUX writes a collapsed owner -> LEGACY READS IT AS COLLAPSED", () => {
  // The other direction, and it is not decorative: a reader and a writer can
  // agree in one direction while disagreeing in the other.
  saveCollapsedOwners( [ "bob" ] );

  const seen = legacy.loadCollapsedTaskOwners();
  assert.ok( seen.has( "bob" ),
    "the multiplexer collapsed bob's group and the legacy page does not see it as collapsed" );
} );

test( "🔴 B1a ABSENCE means EXPANDED in BOTH — the negative half of the polarity", () => {
  // The discriminating case. A client that treated the array as EXPANDED owners
  // would pass both tests above on the key it wrote and fail HERE, because the
  // sense of a name that is NOT in the list is the half that inverts.
  legacy.toggleTaskOwnerCollapsed( "alice" );

  assert.ok( !loadCollapsedOwners().has( "carol" ),
    "carol was never collapsed and the mux reports her as collapsed — the polarity is inverted" );
  assert.ok( !legacy.loadCollapsedTaskOwners().has( "carol" ),
    "carol was never collapsed and the legacy page reports her as collapsed" );
} );

test( "🔴 B1a A TOGGLE ROUND-TRIP RETURNS THE SAME BOOLEAN SENSE FROM BOTH", () => {
  // Both toggles return "is it NOW collapsed". A port that returned "is it now
  // expanded" would invert every caller's branch while the stored bytes stayed
  // identical — invisible to a byte-level comparison of localStorage.
  const legacyFirst = legacy.toggleTaskOwnerCollapsed( "dave" );
  assert.equal( legacyFirst, true,
    "legacy's first toggle of an expanded owner did not report COLLAPSED" );

  globalThis.localStorage.clear();
  const muxFirst = toggleCollapsedOwner( "dave" );
  assert.equal( muxFirst, true,
    "the mux's first toggle of an expanded owner did not report COLLAPSED — the two clients " +
    "return opposite booleans for the same gesture" );
  assert.equal( muxFirst, legacyFirst );
} );

// ⚠️ `epicGroupIsExpanded( key, state? )` IS PURE ON BOTH SIDES AND DOES NOT READ
// STORAGE. Called without `state` it always returns the DEFAULT, whatever is
// saved. My first draft of this file called it bare and two tests went red; the
// §4.3 hard gate says that when the tier fails on a known-good pair the TIER is
// wrong, not the port, and that is exactly what it was. The two implementations
// are line-for-line identical here —
//     const recorded = state ? state[ epicKey ] : undefined;
//     return typeof recorded === "boolean" ? recorded : <default>( epicKey );
// — so the callers below pass `loadEpicGroupState()` explicitly, which is what
// the real callers do. Recorded rather than quietly fixed: a reader who sees a
// bare call elsewhere should suspect the same mistake.
//
// ---------------------------------------------------------------------------
// B1b — EPIC BOARD: the map value means EXPANDED. Opposite polarity, on purpose.
// ---------------------------------------------------------------------------

test( "🔴 B1b LEGACY collapses an epic -> THE MUX READS IT AS COLLAPSED", () => {
  legacy.toggleEpicCollapsed( EPIC_ON_RICK_KEY );   // on-Rick defaults EXPANDED, so this collapses

  assert.equal( epicGroupIsExpanded( EPIC_ON_RICK_KEY, loadEpicGroupState() ), false,
    "the operator collapsed the on-Rick group on the legacy page and the multiplexer still " +
    "reads it as expanded — this is the §7.2 polarity trap, and the surface looks right in " +
    "both clients while the saved state means the opposite thing" );
} );

test( "🔴 B1b THE MUX collapses an epic -> LEGACY READS IT AS COLLAPSED", () => {
  toggleEpicCollapsed( EPIC_ON_RICK_KEY );

  const state = legacy.loadEpicGroupState();
  assert.equal( legacy._epicGroupIsExpanded( EPIC_ON_RICK_KEY, state ), false,
    "the multiplexer collapsed the on-Rick group and the legacy page still reads it expanded" );
} );

test( "🔴 B1b THE STORED VALUE MEANS EXPANDED, NOT COLLAPSED — asserted on the raw JSON", () => {
  // 🔴 The polarity itself, pinned against the bytes. This is the assertion that
  // fails if someone "harmonises" the two panes onto one convention: the epic
  // map stores isEXPANDED while the task-list array stores isCOLLAPSED, and that
  // asymmetry is deliberate rather than an accident to be tidied away.
  saveEpicGroupState( { "epic:alpha": true } );

  const raw = JSON.parse( globalThis.localStorage.getItem( EPIC_BOARD_STATE_KEY ) ?? "{}" );
  assert.equal( raw[ "epic:alpha" ], true, "the harness did not write what it thinks it wrote" );

  assert.equal( epicGroupIsExpanded( "epic:alpha", loadEpicGroupState() ), true,
    "a stored `true` no longer means EXPANDED in the mux — the map polarity has flipped" );
  assert.equal( legacy._epicGroupIsExpanded( "epic:alpha", legacy.loadEpicGroupState() ), true,
    "a stored `true` no longer means EXPANDED in the legacy client" );

  saveEpicGroupState( { "epic:alpha": false } );
  assert.equal( epicGroupIsExpanded( "epic:alpha", loadEpicGroupState() ), false );
  assert.equal( legacy._epicGroupIsExpanded( "epic:alpha", legacy.loadEpicGroupState() ), false );
} );

test( "🔴 B1b AN ABSENT KEY FALLS THROUGH TO THE SAME DEFAULT IN BOTH", () => {
  // "No choice recorded" is a third state, distinct from expanded and collapsed,
  // and the two clients must agree on what it means or a first-time viewer sees
  // a different board on each page.
  assert.equal( epicGroupIsExpanded( EPIC_ON_RICK_KEY, loadEpicGroupState() ),
                epicDefaultExpanded( EPIC_ON_RICK_KEY ) );
  assert.equal( epicGroupIsExpanded( EPIC_ON_RICK_KEY, loadEpicGroupState() ),
                legacy._epicDefaultExpanded( EPIC_ON_RICK_KEY ),
    "the two clients disagree about whether the on-Rick group starts open" );

  assert.equal( epicGroupIsExpanded( "epic:never-seen", loadEpicGroupState() ),
                legacy._epicDefaultExpanded( "epic:never-seen" ),
    "the two clients disagree about whether an ordinary epic starts open" );
} );

test( "🔴 B1b THE TWO PANES REALLY DO STORE OPPOSITE SENSES — the trap, stated as an assertion", () => {
  // If a future port harmonises them, this is what reddens. Collapse one group in
  // each pane through the REAL gestures, then read the raw storage: the task-list
  // key must CONTAIN the collapsed name, the epic key must map it to FALSE.
  legacy.toggleTaskOwnerCollapsed( "erin" );
  legacy.toggleEpicCollapsed( EPIC_ON_RICK_KEY );

  const owners = JSON.parse( globalThis.localStorage.getItem( TASK_LIST_COLLAPSED_KEY ) ?? "[]" );
  const epics  = JSON.parse( globalThis.localStorage.getItem( EPIC_BOARD_STATE_KEY ) ?? "{}" );

  assert.ok( Array.isArray( owners ), "the task-list key is no longer a JSON array" );
  assert.ok( owners.includes( "erin" ),
    "a COLLAPSED owner is absent from the task-list array — that array stores the collapsed " +
    "ones, so its polarity has flipped" );

  assert.equal( typeof epics, "object" );
  assert.equal( epics[ EPIC_ON_RICK_KEY ], false,
    "a COLLAPSED epic is not stored as false — that map stores isEXPANDED, so its polarity " +
    "has flipped. The two panes are deliberately opposite; making them agree silently " +
    "inverts one of them for every operator who already has state saved" );
} );
