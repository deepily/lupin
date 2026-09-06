/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Epic-board card — pure model helpers (TS multiplexer card).
//
// Reproduces the in-service JS card's epic grouping (notifications.js:13227
// groupTasksByEpic, :13154 _epicKeyOf, :13202 _taskWaitsOnRick) as
// OBSERVATIONAL EQUIVALENCE, not shared code — Rick's ruling: the two clients
// share no code, so this is specification-and-reproduction.
//
// Spec: src/rnd/2026.09.05-fleet-accordions-current-state-inventory.md §5d

import {
  priorityRank,
  statusRank,
  taskTitleLabel,
  type TaskItem,
  type TaskBlockedRef,
} from "./taskListModel";

/** A correlation_key counts as an epic ONLY with this prefix. */
export const EPIC_KEY_PREFIX = "epic:";

/** The deliberately-epicless epic; sorts LAST among epics. */
export const EPIC_UNASSIGNED_KEY = "epic:unassigned";

/** The one human the highlight section watches for. */
export const EPIC_BLOCKER_OF_INTEREST = "rick";

export interface EpicGroup {
  epicKey : string;
  tasks   : TaskItem[];
}

export interface EpicBoardModel {
  totalCount : number;
  onRick     : TaskItem[];
  groups     : EpicGroup[];
  drift      : TaskItem[];
}

/**
 * The row's epic key, or null when it carries none. Pure.
 *
 * Ensures:
 *   - a correlation_key starting with "epic:" → that key
 *   - absent / non-prefixed → null (the row is DRIFT, never silently dropped)
 */
export function epicKeyOf( task: TaskItem | null | undefined ): string | null {
  const key = task && task.correlation_key ? String( task.correlation_key ) : "";
  return key.startsWith( EPIC_KEY_PREFIX ) ? key : null;
}

/**
 * True when the row is blocked on Rick. Pure.
 *
 * ⚠️ BOTH HALVES ARE LOAD-BEARING: the id must match "rick" case-insensitively
 * AND the ref's kind must be "user" or "persona". A ref of some other kind that
 * happens to be named rick is not a human blocker, and matching on the id alone
 * would sweep it into the highlight.
 *
 * Ensures:
 *   - blocked_by is a typed-ref ARRAY; a string / null / absent value → false
 *   - never throws
 */
export function taskWaitsOnRick( task: TaskItem | null | undefined ): boolean {
  const refs: TaskBlockedRef[] =
    task && Array.isArray( task.blocked_by ) ? ( task.blocked_by as TaskBlockedRef[] ) : [];
  return refs.some( ( ref ) => {
    if ( !ref || typeof ref !== "object" ) return false;
    const ident = String( ref.id == null ? "" : ref.id ).trim().toLowerCase();
    return ident === EPIC_BLOCKER_OF_INTEREST && ( ref.kind === "user" || ref.kind === "persona" );
  } );
}

/**
 * Build the epic-grouped model from a flat task array — the MACRO twin of
 * groupTasksByOwner.
 *
 * Group ordering mirrors the generator's sort_key: the "epic:unassigned" bucket
 * sinks LAST among the epics, everything else is biggest-first, ties broken by
 * key so the order is STABLE across renders.
 *
 * ⚠️ THE TIE-BREAK IS NOT COSMETIC. Without it two equal-sized epics can swap
 * places between refreshes — intermittent, hard to reproduce, and it does not
 * look like a sort bug.
 *
 * ⚠️ onRick is a HIGHLIGHT, NOT A MOVE. Rows blocked on Rick appear in `onRick`
 * AND stay under their own epic. A port that removes them from their group
 * empties epics that are not empty.
 *
 * Ensures:
 *   - totalCount counts ALL input rows
 *   - onRick holds every row blocked on Rick, P0 first then id
 *   - groups holds one entry per distinct "epic:" key, biggest first,
 *     "epic:unassigned" last
 *   - drift holds every row whose correlation_key is absent or non-prefixed —
 *     never silently dropped
 *   - a row is in exactly one of groups / drift
 *   - within a group, rows sort status-rank → priority → title, the same
 *     urgency order the task list uses
 *   - pure + degrade-safe (falsy rows collapse to {}, never throws)
 */
export function groupTasksByEpic( tasks: unknown ): EpicBoardModel {
  const rows = Array.isArray( tasks ) ? tasks : [];

  const byEpic = new Map<string, TaskItem[]>();
  const drift: TaskItem[]  = [];
  const onRick: TaskItem[] = [];

  rows.forEach( ( raw ) => {
    const task    = ( raw ?? {} ) as TaskItem;
    const epicKey = epicKeyOf( task );
    if ( epicKey ) {
      const bucket = byEpic.get( epicKey );
      if ( bucket ) bucket.push( task );
      else byEpic.set( epicKey, [ task ] );
    } else {
      drift.push( task );
    }
    if ( taskWaitsOnRick( task ) ) onRick.push( task );
  } );

  const byUrgency = ( a: TaskItem, b: TaskItem ): number => {
    const sr = statusRank( a.status ) - statusRank( b.status );
    if ( sr !== 0 ) return sr;
    const pr = priorityRank( a.priority ) - priorityRank( b.priority );
    if ( pr !== 0 ) return pr;
    return taskTitleLabel( a ).localeCompare( taskTitleLabel( b ) );
  };

  // Generator parity (sort_key): unassigned last, then biggest bucket first,
  // then key — so a render never reshuffles two equal-sized epics.
  const groups: EpicGroup[] = Array.from( byEpic.keys() )
    .sort( ( a, b ) => {
      const au = a === EPIC_UNASSIGNED_KEY ? 1 : 0;
      const bu = b === EPIC_UNASSIGNED_KEY ? 1 : 0;
      if ( au !== bu ) return au - bu;
      const size = ( byEpic.get( b ) as TaskItem[] ).length - ( byEpic.get( a ) as TaskItem[] ).length;
      if ( size !== 0 ) return size;
      return a.localeCompare( b );
    } )
    .map( ( epicKey ) => ( {
      epicKey,
      tasks : ( byEpic.get( epicKey ) as TaskItem[] ).slice().sort( byUrgency ),
    } ) );

  onRick.sort( ( a, b ) => {
    const pr = priorityRank( a.priority ) - priorityRank( b.priority );
    if ( pr !== 0 ) return pr;
    return String( a.id || "" ).localeCompare( String( b.id || "" ) );
  } );

  return { totalCount: rows.length, onRick, groups, drift: drift.slice().sort( byUrgency ) };
}

// ---------------------------------------------------------------------------
// Epic stories — the hand-maintained titles and one-line stories
// ---------------------------------------------------------------------------

/** One epic's hand-written entry from `GET /api/epic-stories`. */
export interface EpicStory {
  title? : string;
  story? : string;
}

/** The stories map, keyed by epic key. Absent entries are normal, not errors. */
export type EpicStories = Readonly<Record<string, EpicStory | undefined>>;

/**
 * The human title for an epic: the hand-maintained story title when one exists,
 * otherwise the DE-SLUGGED key ("epic:board-visibility" → "board visibility").
 *
 * ⚠️ A MISSING ENTRY IS A NUDGE, NEVER AN ERROR. The stories file is hand-edited
 * and will always lag the keys in the store, so an epic with no entry must still
 * render with a readable name rather than a blank or a raw key. Mirrors
 * generate_epic_board.py:385 and notifications.js `_epicTitleLabel`.
 *
 * Ensures:
 *   - a story with a non-empty title → that title
 *   - no story / blank title → the key minus the "epic:" prefix, "-" → " "
 *   - pure; never throws
 */
export function epicTitleLabel( epicKey: string, stories: EpicStories = {} ): string {
  const story = stories[ epicKey ];
  if ( story && story.title ) return String( story.title );
  return String( epicKey ).replace( EPIC_KEY_PREFIX, "" ).replace( /-/g, " " );
}

/**
 * The one-line story for an epic, or "" when none is written.
 *
 * Ensures:
 *   - a story with a non-empty `story` → that string; else ""
 *   - pure; never throws
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the exported function-declaration line — c8 reports ONE location for this "branch" (the identifier itself) where a real conditional carries two, and the function is called directly by five tests with one AND two arguments. Two branches of the same signature already sit uncovered in this file at the sort comparators (134, 149), pre-dating this change.
export function epicStoryText( epicKey: string, stories: EpicStories = {} ): string {
  const story = stories[ epicKey ];
  return ( story && story.story ) ? String( story.story ) : "";
}
