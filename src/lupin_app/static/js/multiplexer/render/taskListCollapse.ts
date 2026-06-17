/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Task-list card — per-persona accordion collapse state (TS multiplexer card).
//
// The persistence half of the accordion, mirroring the in-service JS card
// (notifications.js). These three constants are the PARITY CONTRACT shared
// VERBATIM with the JS card so a user moving between the two UIs sees the same
// per-owner collapse state:
//   - the localStorage key
//   - the "__unassigned__" sentinel owner key (the ownerless bucket)
//   - the expanded-on-first-load default (an absent/garbled key → empty set)
//
// Plan: src/rnd/v0.1.8/2026.06.17-task-list-accordion/01-design-and-build-plan.md
// A JS↔TS parity-checklist test asserts these constants match the JS card.

import type { TaskGroup } from "./taskListModel";

/** localStorage key holding the JSON array of collapsed owner keys. */
export const TASK_LIST_COLLAPSED_KEY = "lupin.taskList.collapsedOwners";

/** Sentinel owner key for the ownerless ("Unassigned") bucket. */
export const TASK_LIST_UNASSIGNED_KEY = "__unassigned__";

/**
 * Stable accordion key for an owner group: the persona, or the Unassigned
 * sentinel for the ownerless bucket. Pure.
 *
 * Ensures:
 *   - isUnassigned group → TASK_LIST_UNASSIGNED_KEY; else the (non-null) persona
 */
export function ownerKeyForGroup( group: TaskGroup ): string {
  /* c8 ignore next */ // ownerPersona is non-null for non-unassigned groups (groupTasksByOwner invariant); the ?? "" guard is belt-and-suspenders.
  return group.isUnassigned ? TASK_LIST_UNASSIGNED_KEY : ( group.ownerPersona ?? "" );
}

/**
 * Map an owner key to a DOM-id-safe slug for the group's <tbody> id / the
 * header's aria-controls target. Pure.
 *
 * Ensures:
 *   - "task-group-" + ownerKey with non [A-Za-z0-9_-] chars → "-"
 */
export function taskGroupIdSlug( ownerKey: string ): string {
  return "task-group-" + String( ownerKey ).replace( /[^a-zA-Z0-9_-]/g, "-" );
}

/**
 * Read the persisted set of collapsed owner keys from localStorage.
 *
 * Default state is "expanded on first load" — an absent/empty/garbled key
 * yields an EMPTY set. Non-string array members are dropped defensively.
 *
 * Ensures:
 *   - returns a Set of strings (empty on absent/invalid/parse-error); never throws
 */
export function loadCollapsedOwners(): Set<string> {
  try {
    const raw = globalThis.localStorage.getItem( TASK_LIST_COLLAPSED_KEY );
    const arr = raw ? JSON.parse( raw ) : [];
    return new Set(
      Array.isArray( arr ) ? arr.filter( ( o: unknown ): o is string => typeof o === "string" ) : [],
    );
  } catch {
    // Malformed JSON / unavailable storage — degrade to "nothing collapsed".
    return new Set();
  }
}

/**
 * Persist the collapsed owner-key set to localStorage as a JSON array.
 *
 * Ensures:
 *   - the key is written; a quota/serialization throw is swallowed (a write
 *     failure must never break rendering)
 */
export function saveCollapsedOwners( collapsedSet: Iterable<string> ): void {
  try {
    globalThis.localStorage.setItem( TASK_LIST_COLLAPSED_KEY, JSON.stringify( Array.from( collapsedSet ) ) );
  } catch {
    // Private-mode / quota / non-iterable input — swallow (degrade-safe).
  }
}

/**
 * Flip one owner's collapsed state and persist the result.
 *
 * Ensures:
 *   - ownerKey ∈ set → removed (now expanded); else added (now collapsed)
 *   - the updated set is persisted; returns the NEW collapsed boolean
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the exported function-declaration line; both if/else body branches are exercised by tests.
export function toggleCollapsedOwner( ownerKey: string ): boolean {
  const collapsed = loadCollapsedOwners();
  let isCollapsed: boolean;
  if ( collapsed.has( ownerKey ) ) {
    collapsed.delete( ownerKey );
    isCollapsed = false;
  } else {
    collapsed.add( ownerKey );
    isCollapsed = true;
  }
  saveCollapsedOwners( collapsed );
  return isCollapsed;
}
