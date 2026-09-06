// Epic-board card — epicBoardCollapse unit tests.
// 100% lines/branches/functions per the multiplexer coverage mandate.
//
// THESE TESTS EXIST TO CATCH ONE DEFECT ABOVE ALL OTHERS: the persistence
// polarity trap (spec §3.1). The task list persists an ARRAY of COLLAPSED
// owner keys; the epic board persists a MAP of group key -> isEXPANDED.
// A port that carries one polarity into the other inverts a viewer's saved
// state and renders perfectly while doing it, so no CSSOM-level parity tier
// can see it. Every assertion below that names "polarity" is written so that
// swapping the sense FAILS BY NAME rather than merely reddening something.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  EPIC_BOARD_STATE_KEY,
  EPIC_ON_RICK_KEY,
  EPIC_DRIFT_KEY,
  epicGroupIdSlug,
  epicDefaultExpanded,
  loadEpicGroupState,
  saveEpicGroupState,
  epicGroupIsExpanded,
  toggleEpicCollapsed,
  type EpicGroupState,
} from "../../../lupin_app/static/js/multiplexer/render/epicBoardCollapse";

import {
  TASK_LIST_COLLAPSED_KEY,
} from "../../../lupin_app/static/js/multiplexer/render/taskListCollapse";

// ---------------------------------------------------------------- fake storage

interface FakeStorage {
  store      : Map<string, string>;
  failOnSet  : boolean;
  failOnGet  : boolean;
  getItem    : ( k: string ) => string | null;
  setItem    : ( k: string, v: string ) => void;
}

function installStorage(): FakeStorage {
  const fake: FakeStorage = {
    store     : new Map<string, string>(),
    failOnSet : false,
    failOnGet : false,
    getItem( k: string ): string | null {
      if ( this.failOnGet ) throw new Error( "storage unavailable" );
      return this.store.has( k ) ? ( this.store.get( k ) as string ) : null;
    },
    setItem( k: string, v: string ): void {
      if ( this.failOnSet ) throw new Error( "quota exceeded" );
      this.store.set( k, v );
    },
  };
  ( globalThis as unknown as { localStorage: unknown } ).localStorage = fake;
  return fake;
}

// ---------------------------------------------------------------- constants

test( "the localStorage key matches the JS card verbatim", () => {
  assert.equal( EPIC_BOARD_STATE_KEY, "lupin.epicBoard.groupState" );
} );

test( "the sentinel group keys match the JS card verbatim", () => {
  assert.equal( EPIC_ON_RICK_KEY, "__on_rick__" );
  assert.equal( EPIC_DRIFT_KEY,   "__drift__" );
} );

test( "POLARITY: the epic board does not share the task list's storage key", () => {
  // Unifying the two modules would collapse these onto one key and one shape.
  assert.notEqual( EPIC_BOARD_STATE_KEY, TASK_LIST_COLLAPSED_KEY );
} );

// ---------------------------------------------------------------- slug

test( "epicGroupIdSlug prefixes and sanitises non-id characters", () => {
  assert.equal( epicGroupIdSlug( "abc" ),            "epic-group-abc" );
  assert.equal( epicGroupIdSlug( "a b/c.d" ),        "epic-group-a-b-c-d" );
  assert.equal( epicGroupIdSlug( EPIC_ON_RICK_KEY ), "epic-group-__on_rick__" );
  assert.equal( epicGroupIdSlug( "keep-_09" ),       "epic-group-keep-_09" );
} );

// ---------------------------------------------------------------- defaults

test( "epicDefaultExpanded: on-Rick expands, every other group collapses", () => {
  assert.equal( epicDefaultExpanded( EPIC_ON_RICK_KEY ), true  );
  assert.equal( epicDefaultExpanded( EPIC_DRIFT_KEY ),   false );
  assert.equal( epicDefaultExpanded( "epic-42" ),        false );
} );

// ---------------------------------------------------------------- load

test( "loadEpicGroupState returns {} when the key is absent", () => {
  installStorage();
  assert.deepEqual( loadEpicGroupState(), {} );
} );

test( "loadEpicGroupState returns {} on malformed JSON", () => {
  const fake = installStorage();
  fake.store.set( EPIC_BOARD_STATE_KEY, "{not json" );
  assert.deepEqual( loadEpicGroupState(), {} );
} );

test( "loadEpicGroupState returns {} when storage itself throws", () => {
  const fake = installStorage();
  fake.failOnGet = true;
  assert.deepEqual( loadEpicGroupState(), {} );
} );

test( "a task-list-shaped array yields no choices", () => {
  // The polarity trap in its most literal form: the task list's persisted
  // shape IS a JSON array of owner-key STRINGS. Handed one, the epic board
  // must produce no choices at all.
  //
  // ⚠️ THIS TEST DOES NOT PIN THE Array.isArray GUARD, and saying so is the
  // point. Measured: deleting that guard leaves this test GREEN, because the
  // array's members are strings and the boolean value-filter drops them
  // anyway. It pins the OUTCOME for a realistic payload; the guard itself is
  // pinned by the next test, which is the only one that can see it.
  const fake = installStorage();
  fake.store.set( EPIC_BOARD_STATE_KEY, JSON.stringify( [ "epic-1", "epic-2" ] ) );
  assert.deepEqual( loadEpicGroupState(), {} );
} );

test( "loadEpicGroupState rejects a JSON ARRAY categorically, even one of booleans", () => {
  // The discriminating case. An array of BOOLEANS survives the value-filter:
  // Object.keys gives "0"/"1" and the values are real booleans, so without the
  // Array.isArray guard this returns { "0": true, "1": false } — indices
  // masquerading as group keys. This is the ONLY fixture in the file that can
  // tell the guard is present.
  const fake = installStorage();
  fake.store.set( EPIC_BOARD_STATE_KEY, JSON.stringify( [ true, false ] ) );
  assert.deepEqual( loadEpicGroupState(), {} );
} );

test( "loadEpicGroupState returns {} for JSON null", () => {
  const fake = installStorage();
  fake.store.set( EPIC_BOARD_STATE_KEY, "null" );
  assert.deepEqual( loadEpicGroupState(), {} );
} );

test( "loadEpicGroupState returns {} for a JSON scalar", () => {
  const fake = installStorage();
  fake.store.set( EPIC_BOARD_STATE_KEY, "7" );
  assert.deepEqual( loadEpicGroupState(), {} );
} );

test( "loadEpicGroupState drops non-boolean values and keeps boolean ones", () => {
  const fake = installStorage();
  fake.store.set( EPIC_BOARD_STATE_KEY, JSON.stringify( {
    kept_true  : true,
    kept_false : false,
    dropped_s  : "true",
    dropped_n  : 1,
    dropped_z  : null,
  } ) );
  assert.deepEqual( loadEpicGroupState(), { kept_true: true, kept_false: false } );
} );

// ---------------------------------------------------------------- save

test( "saveEpicGroupState writes the map as JSON under the epic key", () => {
  const fake  = installStorage();
  const state = { "epic-1": true, "epic-2": false };
  saveEpicGroupState( state );
  assert.deepEqual( JSON.parse( fake.store.get( EPIC_BOARD_STATE_KEY ) as string ), state );
} );

test( "saveEpicGroupState swallows a write failure — rendering must not break", () => {
  const fake = installStorage();
  fake.failOnSet = true;
  assert.doesNotThrow( () => saveEpicGroupState( { "epic-1": true } ) );
  assert.equal( fake.store.has( EPIC_BOARD_STATE_KEY ), false );
} );

// ---------------------------------------------------------------- resolve

test( "POLARITY: a stored TRUE means EXPANDED, not collapsed", () => {
  installStorage();
  // If the sense were inverted, this group would resolve to collapsed.
  assert.equal( epicGroupIsExpanded( "epic-1", { "epic-1": true } ), true );
} );

test( "POLARITY: a stored FALSE means COLLAPSED, and overrides nothing else", () => {
  installStorage();
  assert.equal( epicGroupIsExpanded( "epic-1", { "epic-1": false } ), false );
} );

test( "POLARITY: a stored FALSE on the on-Rick sentinel BEATS its expanded default", () => {
  // The sharpest discriminator in this file: default says expand, the viewer
  // said collapse. Only a correct recorded-choice-wins resolver returns false.
  installStorage();
  assert.equal( epicGroupIsExpanded( EPIC_ON_RICK_KEY, { [ EPIC_ON_RICK_KEY ]: false } ), false );
} );

test( "TRI-STATE: an ABSENT key falls through to the default, it is not 'collapsed'", () => {
  installStorage();
  const state: EpicGroupState = { other: false };
  // Absent + on-Rick → expanded. A two-state (present/absent) port returns false here.
  assert.equal( epicGroupIsExpanded( EPIC_ON_RICK_KEY, state ), true  );
  assert.equal( epicGroupIsExpanded( "epic-new",       state ), false );
} );

test( "epicGroupIsExpanded with NO state argument uses the default", () => {
  installStorage();
  assert.equal( epicGroupIsExpanded( EPIC_ON_RICK_KEY ), true  );
  assert.equal( epicGroupIsExpanded( "epic-1" ),         false );
} );

// ---------------------------------------------------------------- toggle

test( "toggleEpicCollapsed returns the NEW COLLAPSED boolean, not the expanded one", () => {
  installStorage();
  // "epic-1" defaults to collapsed → first toggle EXPANDS it → returns false.
  assert.equal( toggleEpicCollapsed( "epic-1" ), false );
} );

test( "toggleEpicCollapsed persists the flipped choice as isEXPANDED", () => {
  const fake = installStorage();
  toggleEpicCollapsed( "epic-1" );
  const written = JSON.parse( fake.store.get( EPIC_BOARD_STATE_KEY ) as string );
  // Stored TRUE = expanded. Stored FALSE here would be the inverted polarity.
  assert.deepEqual( written, { "epic-1": true } );
} );

test( "toggleEpicCollapsed on the on-Rick sentinel COLLAPSES it first", () => {
  const fake = installStorage();
  assert.equal( toggleEpicCollapsed( EPIC_ON_RICK_KEY ), true );
  assert.deepEqual(
    JSON.parse( fake.store.get( EPIC_BOARD_STATE_KEY ) as string ),
    { [ EPIC_ON_RICK_KEY ]: false },
  );
} );

test( "toggleEpicCollapsed round-trips: two flips restore the starting state", () => {
  const fake = installStorage();
  const first  = toggleEpicCollapsed( "epic-1" );
  const second = toggleEpicCollapsed( "epic-1" );
  assert.equal( first,  false );
  assert.equal( second, true  );
  assert.deepEqual(
    JSON.parse( fake.store.get( EPIC_BOARD_STATE_KEY ) as string ),
    { "epic-1": false },
  );
} );

test( "toggleEpicCollapsed preserves the choices of other groups", () => {
  const fake = installStorage();
  fake.store.set( EPIC_BOARD_STATE_KEY, JSON.stringify( { keep: true } ) );
  toggleEpicCollapsed( "epic-1" );
  assert.deepEqual(
    JSON.parse( fake.store.get( EPIC_BOARD_STATE_KEY ) as string ),
    { keep: true, "epic-1": true },
  );
} );
