/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Epic-board card — per-group accordion collapse state (TS multiplexer card).
//
// The persistence half of the epic board's axis-2 accordion, mirroring the
// in-service JS card (notifications.js:13316-13416). These constants and the
// default rule are the PARITY CONTRACT shared VERBATIM with the JS card so a
// user moving between the two UIs sees the same per-group open/closed state:
//   - the localStorage key
//   - the "__on_rick__" / "__drift__" sentinel group keys
//   - the first-load default (on-Rick expanded, everything else collapsed)
//
// 🔴 THIS FILE HAS THE OPPOSITE POLARITY TO taskListCollapse.ts, DELIBERATELY.
// The task list persists an ARRAY of COLLAPSED owner keys; the epic board
// persists a MAP of group key -> isEXPANDED. Porting one from the other
// INVERTS a viewer's saved state and fails INVISIBLY — the surface still
// renders correctly, so a CSSOM-level parity tier cannot see it. The two must
// not be unified, and the spec says so:
// src/rnd/2026.09.05-fleet-accordions-current-state-inventory.md §3.1
//
// ⚠️ It is not a two-state flag either. The map stores CHOICES, not state:
// a key the viewer has never toggled is ABSENT and falls through to
// epicDefaultExpanded(). That is what makes "collapsed by default" survive an
// epic being minted later — a brand-new epic takes the default rather than
// inheriting some stale set's membership.

/** localStorage key holding the JSON map of group key -> isExpanded choices. */
export const EPIC_BOARD_STATE_KEY = "lupin.epicBoard.groupState";

/** Sentinel group key: the waiting-on-Rick highlight. */
export const EPIC_ON_RICK_KEY = "__on_rick__";

/** Sentinel group key: rows carrying no epic at all. */
export const EPIC_DRIFT_KEY = "__drift__";

/** The persisted choice map: group key -> isExpanded. Absent key = no choice made. */
export type EpicGroupState = Record<string, boolean>;

/**
 * Map a group key to a DOM-id-safe slug for the group's <tbody> id / the
 * header's aria-controls target. Pure.
 *
 * Ensures:
 *   - "epic-group-" + epicKey with non [A-Za-z0-9_-] chars → "-"
 */
export function epicGroupIdSlug( epicKey: string ): string {
  return "epic-group-" + String( epicKey ).replace( /[^a-zA-Z0-9_-]/g, "-" );
}

/**
 * The FIRST-LOAD open/closed default for one group, before the viewer has
 * expressed any preference. Pure.
 *
 * Plan §6: "Default state: all epics collapsed. The macro view's value is the
 * list of epics and their counts; opening one is a deliberate act." The
 * ⏳ Waiting-on-Rick section is the documented exception — the plan calls it a
 * HIGHLIGHT, and a collapsed highlight highlights nothing.
 *
 * Ensures:
 *   - the on-Rick sentinel → true; every other key (epics, drift) → false
 */
export function epicDefaultExpanded( epicKey: string ): boolean {
  return epicKey === EPIC_ON_RICK_KEY;
}

/**
 * Read the persisted per-group open/closed CHOICES from localStorage.
 *
 * Ensures:
 *   - returns a plain object of key → boolean (empty on absent/invalid/
 *     parse-error); non-boolean values are dropped defensively
 *   - an array parses to {} — a JSON array is not a choice map
 *   - never throws
 */
export function loadEpicGroupState(): EpicGroupState {
  try {
    const raw    = globalThis.localStorage.getItem( EPIC_BOARD_STATE_KEY );
    const parsed = raw ? JSON.parse( raw ) : {};
    if ( !parsed || typeof parsed !== "object" || Array.isArray( parsed ) ) return {};
    const clean: EpicGroupState = {};
    Object.keys( parsed ).forEach( ( key ) => {
      if ( typeof parsed[ key ] === "boolean" ) clean[ key ] = parsed[ key ];
    } );
    return clean;
  } catch {
    // Malformed JSON / unavailable storage — degrade to "no choices recorded".
    return {};
  }
}

/**
 * Persist the per-group open/closed choice map to localStorage.
 *
 * Ensures:
 *   - the key is written; a quota/serialization throw is swallowed (a write
 *     failure must never break rendering)
 */
export function saveEpicGroupState( state: EpicGroupState ): void {
  try {
    globalThis.localStorage.setItem( EPIC_BOARD_STATE_KEY, JSON.stringify( state ) );
  } catch {
    // Private-mode / quota / non-serializable input — swallow (degrade-safe).
  }
}

/**
 * Resolve one group's expanded state: the viewer's recorded choice, else the
 * first-load default. Pure.
 *
 * Ensures:
 *   - a recorded boolean for epicKey → that boolean
 *   - no record → epicDefaultExpanded( epicKey )
 */
export function epicGroupIsExpanded( epicKey: string, state?: EpicGroupState ): boolean {
  const recorded = state ? state[ epicKey ] : undefined;
  return typeof recorded === "boolean" ? recorded : epicDefaultExpanded( epicKey );
}

/**
 * Flip one group's open/closed state and persist the choice.
 *
 * Ensures:
 *   - the flipped choice is recorded and persisted
 *   - returns the NEW COLLAPSED boolean for epicKey (note: collapsed, not
 *     expanded — this mirrors the JS card's return, and inverting it is the
 *     polarity trap this file exists to hold the line on)
 */
export function toggleEpicCollapsed( epicKey: string ): boolean {
  const state      = loadEpicGroupState();
  const isExpanded = !epicGroupIsExpanded( epicKey, state );
  state[ epicKey ] = isExpanded;
  saveEpicGroupState( state );
  return !isExpanded;
}
