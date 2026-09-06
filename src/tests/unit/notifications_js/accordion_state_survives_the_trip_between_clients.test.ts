// The persistence polarity trap, tested where it actually bites: BETWEEN the
// two clients, through one shared localStorage value.
//
// THE CONTRACT. Both cards claim, in their own file headers, that a user moving
// between the legacy card and the multiplexer sees the same collapse state.
// That contract is a ROUND TRIP through localStorage, and until this file
// nothing exercised it: one client writes, the OTHER reads, and the viewer's
// intent must survive.
//
// 🔴 WHY THE EXISTING PARITY CHECK CANNOT SEE THIS. `task_list_collapse.test.ts`
// asserts parity by reading notifications.js AS TEXT and checking the key
// literal appears in it. That catches a renamed key. It cannot catch an
// INVERTED one — flip which membership means "collapsed" inside the JS card and
// the key literal is untouched, so the text check still passes while a viewer's
// saved state silently means the opposite. Measured: the two single-module
// suites kill every in-module inversion (5 arms, all killed), and neither can
// see a cross-client disagreement, because neither loads the other client.
//
// 🔴 THE TWO PANES HAVE OPPOSITE POLARITY ON PURPOSE, AND THAT IS THE TRAP.
//     lupin.taskList.collapsedOwners  ARRAY of COLLAPSED keys   (member = closed)
//     lupin.epicBoard.groupState      MAP  key -> isEXPANDED    (true  = open)
// Porting one from the other inverts a viewer's saved state and fails
// INVISIBLY — the surface still renders correctly, so a CSSOM-level parity tier
// cannot see it. Spec: src/rnd/2026.09.05-fleet-accordions-current-state-inventory.md §3.1
//
// ⚠️ AND THE EPIC MAP IS THREE-STATE, NOT TWO. An ABSENT key is "no choice
// made" and falls through to the default (on-Rick open, everything else shut).
// A port that normalises absent to `false` looks tidy and quietly closes the
// one group the plan calls a highlight.
//
// 🔴 PROOF THAT THIS DISCRIMINATES — five arms, measured, not argued. A guard
// that has never been watched to FAIL is not a guard (§ UNGUARDED IS A THIRD
// STATE). Green baseline 10/0 taken FIRST; every arm restored and re-verified.
//
//   arm on the LEGACY card                    this file   old-task   old-epic
//   invert task-list membership               1 FAIL      12 pass    25 pass
//   invert epic stored polarity               2 FAIL      12 pass    25 pass
//   absent epic key normalised to false       1 FAIL      12 pass    25 pass
//   rename the task-list key literal          4 FAIL      —          —
//   invert BOTH clients symmetrically         1 FAIL      —          —
//
// ⇒ The first three are the reason this file exists: the two single-module
// suites are BLIND to all of them, because neither loads the other client.
//
// 🔴 THE FOURTH ARM ANSWERS THE TAUTOLOGY CHALLENGE. `Object.create` skips the
// constructor that assigns the key constants, so the obvious harness hand-sets
// them FROM the TS module — and then asserting they match the TS module
// compares a value against itself (§ A COMPARISON WHOSE TWO SIDES COME FROM ONE
// SOURCE CANNOT DISAGREE). This harness instead extracts the literals from
// notifications.js AS TEXT. Renaming the literal in the JS card ALONE reddens
// the control plus three round trips — which is the measurement showing the two
// sides have genuinely different provenances.
//
// 🔴 THE FIFTH ARM IS THE ONE THAT COULD HAVE EXPOSED A TAUTOLOGY AND DID NOT.
// A pure "do the two clients agree?" check passes when BOTH are inverted
// together — consistent, and consistently wrong. Inverting both still reddens
// here, because the expectations are LITERALS ("collapsing must return true"),
// not values read back from the other client. Agreement is necessary and this
// file does not treat it as sufficient.
//
// ⚠️ WHAT IT STILL DOES NOT COVER, said plainly: this round-trips the STORE, not
// the RENDERED surface. A client could read the value correctly and paint it
// backwards, and nothing here would notice. That is a different arm and it has
// not been run.
//
// :7999-eligible in spirit — pure, no server, no network. Runs in the
// TypeScript tier (:8000 scheduled) because that is where .test.ts lives.

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

import {
  TASK_LIST_COLLAPSED_KEY,
  TASK_LIST_UNASSIGNED_KEY,
  loadCollapsedOwners,
  saveCollapsedOwners,
  toggleCollapsedOwner,
} from "../../../lupin_app/static/js/multiplexer/render/taskListCollapse";

import {
  EPIC_BOARD_STATE_KEY,
  EPIC_ON_RICK_KEY,
  epicDefaultExpanded,
  epicGroupIsExpanded,
  loadEpicGroupState,
  saveEpicGroupState,
  toggleEpicCollapsed,
} from "../../../lupin_app/static/js/multiplexer/render/epicBoardCollapse";

const HERE             = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

type LegacyCard = Record<string, unknown> & {
  TASK_LIST_COLLAPSED_KEY : string;
  TASK_LIST_UNASSIGNED_KEY: string;
  error                   : ( ...a: unknown[] ) => void;
  EPIC_BOARD_STATE_KEY    : string;
  EPIC_ON_RICK_KEY        : string;
  loadCollapsedTaskOwners : () => Set<string>;
  saveCollapsedTaskOwners : ( s: Iterable<string> ) => void;
  toggleTaskOwnerCollapsed: ( ownerKey: string ) => boolean;
  loadEpicGroupState      : () => Record<string, boolean>;
  saveEpicGroupState      : ( s: Record<string, boolean> ) => void;
  _epicGroupIsExpanded    : ( epicKey: string, state?: Record<string, boolean> ) => boolean;
  _epicDefaultExpanded    : ( epicKey: string ) => boolean;
};

let legacy: LegacyCard;

/**
 * Pull a constructor-assigned string constant out of notifications.js AS TEXT.
 *
 * 🔴 THIS IS WHY THE PARITY ASSERTION IS NOT A TAUTOLOGY. The real constructor
 * cannot run here (it builds a TTSAudioCache and friends), so the established
 * harness pattern is Object.create(prototype) — which skips the `this.KEY = ...`
 * assignments. Hand-setting those keys FROM the TS module and then asserting
 * they match the TS module would compare a value against itself
 * (§ A COMPARISON WHOSE TWO SIDES COME FROM ONE SOURCE CANNOT DISAGREE).
 * Reading the literal out of the JS source keeps the two provenances genuinely
 * separate: the TS constant on one side, the JS card's own text on the other.
 */
function legacyConstant( source: string, name: string ): string {
  const m = new RegExp( `this\\.${name}\\s*=\\s*['"]([^'"]+)['"]` ).exec( source );
  assert.ok( m, `notifications.js must assign this.${name} — the extractor, not the card, is broken` );
  return ( m as RegExpExecArray )[ 1 ];
}

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext(
    fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;",
    { filename: NOTIFICATIONS_JS },
  );
  const Ctor = ( globalThis as unknown as { NotificationsUI: new () => unknown } ).NotificationsUI;
  legacy = Object.create( ( Ctor as unknown as { prototype: object } ).prototype ) as LegacyCard;

  // The constants the skipped constructor would have set — taken from the card's
  // own source text, never from the TS module under comparison.
  legacy.TASK_LIST_COLLAPSED_KEY  = legacyConstant( fullSource, "TASK_LIST_COLLAPSED_KEY" );
  legacy.TASK_LIST_UNASSIGNED_KEY = legacyConstant( fullSource, "TASK_LIST_UNASSIGNED_KEY" );
  legacy.EPIC_BOARD_STATE_KEY     = legacyConstant( fullSource, "EPIC_BOARD_STATE_KEY" );
  legacy.EPIC_ON_RICK_KEY         = legacyConstant( fullSource, "EPIC_ON_RICK_KEY" );
  legacy.error                    = () => {};
} );

beforeEach( () => { localStorage.clear(); } );

// ---------------------------------------------------------------------------
// POSITIVE CONTROL. Without this, a harness that failed to construct the legacy
// card would make every round-trip assertion below vacuous — the classic
// "a loop over nothing is green".
// ---------------------------------------------------------------------------
test( "CONTROL: the legacy card is really loaded and exposes both stores", () => {
  assert.equal( typeof legacy.loadCollapsedTaskOwners, "function" );
  assert.equal( typeof legacy.loadEpicGroupState, "function" );
  assert.equal( legacy.TASK_LIST_COLLAPSED_KEY, TASK_LIST_COLLAPSED_KEY );
  assert.equal( legacy.EPIC_BOARD_STATE_KEY, EPIC_BOARD_STATE_KEY );
  assert.notEqual( TASK_LIST_COLLAPSED_KEY, EPIC_BOARD_STATE_KEY );
} );

// ---------------------------------------------------------------------------
// TASK LIST — membership means COLLAPSED, in both directions.
// ---------------------------------------------------------------------------
test( "TASK LIST · multiplexer writes, legacy reads: a collapsed owner is still COLLAPSED", () => {
  saveCollapsedOwners( [ "maria", TASK_LIST_UNASSIGNED_KEY ] );
  const seenByLegacy = legacy.loadCollapsedTaskOwners();
  assert.ok( seenByLegacy.has( "maria" ), "legacy must read 'maria' as collapsed" );
  assert.ok( seenByLegacy.has( TASK_LIST_UNASSIGNED_KEY ), "the unassigned sentinel must survive the trip" );
  assert.ok( !seenByLegacy.has( "krishna" ), "an owner never collapsed must NOT come back collapsed" );
} );

test( "TASK LIST · legacy writes, multiplexer reads: a collapsed owner is still COLLAPSED", () => {
  legacy.saveCollapsedTaskOwners( new Set( [ "john", TASK_LIST_UNASSIGNED_KEY ] ) );
  const seenByMux = loadCollapsedOwners();
  assert.ok( seenByMux.has( "john" ), "the multiplexer must read 'john' as collapsed" );
  assert.ok( seenByMux.has( TASK_LIST_UNASSIGNED_KEY ) );
  assert.ok( !seenByMux.has( "maria" ) );
} );

test( "TASK LIST · a toggle in one client is read as the SAME state by the other", () => {
  const nowCollapsed = toggleCollapsedOwner( "rachel" );          // mux collapses
  assert.equal( nowCollapsed, true, "toggle must report the NEW collapsed state" );
  assert.ok( legacy.loadCollapsedTaskOwners().has( "rachel" ) );

  const nowCollapsedAgain = legacy.toggleTaskOwnerCollapsed( "rachel" ); // legacy expands
  assert.equal( nowCollapsedAgain, false );
  assert.ok( !loadCollapsedOwners().has( "rachel" ), "the multiplexer must see it EXPANDED again" );
} );

test( "TASK LIST · an absent key means EVERYTHING EXPANDED in both clients", () => {
  assert.equal( localStorage.getItem( TASK_LIST_COLLAPSED_KEY ), null );
  assert.equal( loadCollapsedOwners().size, 0 );
  assert.equal( legacy.loadCollapsedTaskOwners().size, 0 );
} );

// ---------------------------------------------------------------------------
// EPIC BOARD — the stored boolean means EXPANDED, in both directions.
// ---------------------------------------------------------------------------
test( "EPIC BOARD · multiplexer writes, legacy reads: stored TRUE still means EXPANDED", () => {
  saveEpicGroupState( { "epic-alpha": true, "epic-beta": false } );
  const state = legacy.loadEpicGroupState();
  assert.equal( legacy._epicGroupIsExpanded( "epic-alpha", state ), true,
    "stored true must read as EXPANDED in the legacy card — false here is the inverted polarity" );
  assert.equal( legacy._epicGroupIsExpanded( "epic-beta", state ), false );
} );

test( "EPIC BOARD · legacy writes, multiplexer reads: stored TRUE still means EXPANDED", () => {
  legacy.saveEpicGroupState( { "epic-gamma": true, "epic-delta": false } );
  const state = loadEpicGroupState();
  assert.equal( epicGroupIsExpanded( "epic-gamma", state ), true,
    "stored true must read as EXPANDED in the multiplexer — false here is the inverted polarity" );
  assert.equal( epicGroupIsExpanded( "epic-delta", state ), false );
} );

test( "EPIC BOARD · a toggle in one client is read as the SAME state by the other", () => {
  // on-Rick starts EXPANDED by default, so the first toggle closes it.
  const nowCollapsed = toggleEpicCollapsed( EPIC_ON_RICK_KEY );
  assert.equal( nowCollapsed, true, "toggle must report the NEW COLLAPSED state, not the stored expanded one" );
  assert.equal( legacy._epicGroupIsExpanded( EPIC_ON_RICK_KEY, legacy.loadEpicGroupState() ), false );
} );

// ---------------------------------------------------------------------------
// 🔴 THE THREE-STATE RULE. An ABSENT key is not `false` — it is "no choice
// made", and both clients must fall through to the same default.
// ---------------------------------------------------------------------------
test( "EPIC BOARD · an ABSENT key falls to the DEFAULT in both clients, not to false", () => {
  saveEpicGroupState( { "epic-alpha": false } );            // one unrelated choice
  const muxState    = loadEpicGroupState();
  const legacyState = legacy.loadEpicGroupState();

  // on-Rick is the documented exception: a collapsed highlight highlights nothing.
  assert.equal( epicDefaultExpanded( EPIC_ON_RICK_KEY ), true );
  assert.equal( legacy._epicDefaultExpanded( EPIC_ON_RICK_KEY ), true );
  assert.equal( epicGroupIsExpanded( EPIC_ON_RICK_KEY, muxState ), true,
    "an untouched on-Rick must be EXPANDED — normalising absent to false closes the highlight" );
  assert.equal( legacy._epicGroupIsExpanded( EPIC_ON_RICK_KEY, legacyState ), true );

  // a brand-new epic minted later takes the default too, rather than inheriting
  // membership from some stale set.
  assert.equal( epicGroupIsExpanded( "epic-minted-yesterday", muxState ), false );
  assert.equal( legacy._epicGroupIsExpanded( "epic-minted-yesterday", legacyState ), false );
} );

// ---------------------------------------------------------------------------
// 🔴 THE TWO STORES MUST NOT BLEED. This is the port-one-from-the-other failure
// in its most literal form: one pane's write must not change the other's reading.
// ---------------------------------------------------------------------------
test( "the two stores are independent — writing one does not move the other", () => {
  saveCollapsedOwners( [ "maria" ] );
  saveEpicGroupState( { "epic-alpha": true } );

  assert.ok( loadCollapsedOwners().has( "maria" ) );
  assert.equal( epicGroupIsExpanded( "epic-alpha", loadEpicGroupState() ), true );

  // The shapes are genuinely different — an array in one, an object in the other.
  const rawTask = JSON.parse( localStorage.getItem( TASK_LIST_COLLAPSED_KEY ) as string );
  const rawEpic = JSON.parse( localStorage.getItem( EPIC_BOARD_STATE_KEY ) as string );
  assert.ok( Array.isArray( rawTask ), "task list persists an ARRAY of collapsed keys" );
  assert.ok( !Array.isArray( rawEpic ) && typeof rawEpic === "object",
    "epic board persists a MAP of key -> isExpanded" );

  // 🔴 And the polarity is genuinely opposite: for the SAME viewer intent
  // ("this group is shut"), one store RECORDS the key and the other stores false.
  assert.ok( rawTask.includes( "maria" ), "shut => PRESENT in the task-list array" );
  saveEpicGroupState( { "epic-alpha": false } );
  assert.equal( JSON.parse( localStorage.getItem( EPIC_BOARD_STATE_KEY ) as string )[ "epic-alpha" ], false,
    "shut => stored FALSE in the epic map. If these two ever agree in sign, one was ported from the other." );
} );
