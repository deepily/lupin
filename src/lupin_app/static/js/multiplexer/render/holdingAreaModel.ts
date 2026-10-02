/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Holding-area card — pure model helpers (TS multiplexer card).
//
// Reproduces the in-service JS card's holding-area grouping and sort
// (notifications.js:9540 _groupHeldRowsByFiler, :9889 _taskFilerLabel) as
// OBSERVATIONAL EQUIVALENCE, not shared code — Rick's ruling: the two clients
// share no code, so this is a specification-and-reproduction exercise.
//
// Spec: src/rnd/2026.09.05-fleet-accordions-current-state-inventory.md §5c

import { priorityRank, taskTitleLabel, type TaskItem, type TaskListComposite } from "./taskListModel";
import { personaLabel } from "../shared/personaLabel";
import { EPIC_UNASSIGNED_KEY } from "./epicBoardModel";

/** One filer's bucket of held rows. */
export interface HeldFilerGroup {
  filer : string;
  tasks : TaskItem[];
}

/**
 * The PERSON who filed this row, from `created_by`, display-cased. Pure.
 *
 * 🔴 DO NOT REACH FOR `created_by.split( " " )[ 0 ]`. The stored value is
 * `<persona> <8-hex session>`, and a persona can be TWO WORDS: "mr radio"
 * renders as "mr". Measured by María 2026-09-02: wrong on 6 of 13 live rows,
 * and those six are exactly the ones Rick asked about — the naive
 * implementation fails hardest precisely where the feature is for.
 *
 * ⇒ So this strips a TRAILING SESSION ID rather than keeping a leading word,
 * and on a non-match returns the WHOLE string untouched. A truncated name is a
 * WRONG name wearing a right one's clothes; an unexpected format shown in full
 * is visibly odd and sends the reader to the row.
 *
 * Case is display-only — the store holds "Krishna" and "mr radio" both, so
 * this normalises what the reader SEES without touching what is stored.
 *
 * Ensures:
 *   - "mr radio 0e61abe3"  → "Mr Radio"
 *   - "Krishna 420f5ec9"   → "Krishna"
 *   - no trailing session id → the whole string, display-cased
 *   - absent/blank → "—"
 *   - never throws
 */
export function taskFilerLabel( task: TaskItem | null | undefined ): string {
  // ONE rule, ONE place — the END-anchored strip now lives in shared/personaLabel.ts,
  // after being re-derived WRONGLY next door in finishedTasksModel (row 4a06ded1).
  // The docstring above is KEPT because it carries the measurement (6 of 13 live
  // rows); only the rule moved out.
  //
  // ⚠️ THE DISPLAY-CASING STAYS HERE AND IS NOT PART OF THE SHARED RULE. This pane
  // title-cases its filer labels; the Finished-Tasks WHO column does not. Folding the
  // casing into the shared helper would silently re-case a column that reads the
  // store's own spelling today.
  const stripped = personaLabel( task && task.created_by ? String( task.created_by ) : null, "—" );
  if ( stripped === "—" ) return stripped;
  return stripped.replace( /\b[a-z]/g, ( c ) => c.toUpperCase() );
}

/**
 * Group held rows BY FILER, which is what the triage session actually needs.
 *
 * ⭐ FILER, NOT OWNER — and the two genuinely differ. `created_by` names who
 * PUT the row in the holding area; `owner_persona` names who would do it if
 * approved. On the live board they disagree on 3 of 13 rows, which is why they
 * are two columns and never one merged "who". Triage asks "what did this
 * person file", so it groups on the filer. A port that groups by owner
 * produces a plausible, WRONG pane and nothing looks broken.
 *
 * ⚠️ STATUS IS DELIBERATELY NOT A SORT KEY. Status is uniform here — every row
 * is `not_approved` — so ranking by it would discriminate nothing. Adding it is
 * not so much wrong as inert, and it hides that the pane is single-status by
 * definition. (This is the one place the holding area's comparator diverges
 * from `groupTasksByOwner`, which DOES rank by status first.)
 *
 * Ensures:
 *   - returns [ { filer, tasks } ], filers sorted alphabetically
 *   - within a filer, rows sort by priority then title
 *   - a falsy / non-array tasks argument yields []
 *   - pure: no DOM, no side effects; never throws
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function groupHeldRowsByFiler( tasks: unknown ): HeldFilerGroup[] {
  const rows = Array.isArray( tasks ) ? tasks : [];

  const byFiler = new Map<string, TaskItem[]>();
  rows.forEach( ( raw ) => {
    const task   = ( raw ?? {} ) as TaskItem;
    const filer  = taskFilerLabel( task );
    const bucket = byFiler.get( filer );
    if ( bucket ) bucket.push( task );
    else byFiler.set( filer, [ task ] );
  } );

  return Array.from( byFiler.keys() )
    .sort( ( a, b ) => a.localeCompare( b ) )
    .map( ( filer ) => ( {
      filer,
      tasks : ( byFiler.get( filer ) as TaskItem[] ).slice().sort( ( a, b ) => {
        const pr = priorityRank( a.priority ) - priorityRank( b.priority );
        if ( pr !== 0 ) return pr;
        return taskTitleLabel( a ).localeCompare( taskTitleLabel( b ) );
      } ),
    } ) );
}

/** One story's held rows: the `correlation_key` they share and their full ids. */
export interface HeldStory {
  key : string;
  ids : string[];
}

/**
 * Group held rows by STORY — the `correlation_key` a plan import stamps on every
 * row it files — keeping only keys shared by two or more rows.
 *
 * 🔴 `epic:unassigned` IS NOT A STORY EITHER — it is the key a row carries when nobody chose one,
 * shared by unrelated rows, and a bar over it would approve strangers together.
 *
 * 🔴 ONE ROW IS NOT A STORY. A bar offering "approve all 1 in this story" is the
 * per-row control under a bigger label, and a pane of them would bury the real
 * stories. A row with no key is never grouped: an absent key is not a shared one.
 *
 * Reproduces notifications.js `_groupHeldRowsByStory` as observational
 * equivalence, not shared code.
 *
 * Ensures:
 *   - returns [ { key, ids } ], keys sorted alphabetically
 *   - ids are the full row ids in arrival order; a row with no id is dropped
 *   - a key with fewer than two ids is omitted, EXCEPT a key named in `keep` (a story
 *     whose last run left a report to show), which stays while it has one id left
 *   - a falsy / non-array tasks argument yields []
 *   - pure: no DOM, no side effects; never throws
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function groupHeldRowsByStory( tasks: unknown, keep: ReadonlySet<string> = new Set() ): HeldStory[] {
  const rows  = Array.isArray( tasks ) ? tasks : [];
  const byKey = new Map<string, string[]>();
  rows.forEach( ( raw ) => {
    const task = ( raw ?? {} ) as TaskItem;
    const key  = task.correlation_key ? String( task.correlation_key ) : "";
    const id   = task.id ? String( task.id ) : "";
    // "epic:unassigned" is the deliberate no-epic answer, a bucket and not a story: the same
    // treatment as no key at all.
    if ( key === "" || key === EPIC_UNASSIGNED_KEY || id === "" ) return;
    const bucket = byKey.get( key );
    if ( bucket ) bucket.push( id );
    else byKey.set( key, [ id ] );
  } );
  return Array.from( byKey.keys() )
    .filter( ( key ) => ( byKey.get( key ) as string[] ).length >= ( keep.has( key ) ? 1 : 2 ) )
    .sort( ( a, b ) => a.localeCompare( b ) )
    .map( ( key ) => ( { key, ids : byKey.get( key ) as string[] } ) );
}

/**
 * The number the Holding Area's header WOULD display for a composite, or null
 * when that pane would display no number at all.
 *
 * Parity A-2 #7. Legacy answers this by READING THE DOM
 * (`_holdingAreaHeaderCount`, notifications.js:12463) because the legacy page
 * has no store to ask. The multiplexer does, so it asks the store — María 🌸's
 * ruling, 2026-09-23.
 *
 * 🔴 IT MIRRORS THE PANE'S DECISION, NOT JUST ITS ARITHMETIC. Deriving a count
 * from any composite would produce a number for states in which the Holding
 * Area is deliberately showing "—" instead of one, and the caller would then
 * suppress a note on the strength of a figure nobody can see. The three
 * sentinel statuses and a malformed `tasks` all read null here for exactly the
 * reason `renderFromStore` paints a sentinel for them.
 *
 * ⚠️ It also removes a hazard legacy carries and documents: the legacy DOM read
 * can catch the header while it still holds its placeholder, because the task
 * list paints first. A store read has no such ordering.
 *
 * Requires:
 *   - composite is the Holding Area store's composite, or null before first poll
 *
 * Ensures:
 *   - null for a null composite (pre-first-poll — not "zero held rows")
 *   - null for a status the pane answers with a sentinel
 *   - null for a malformed `tasks` (an answer nobody understood is not a count)
 *   - otherwise the same total the pane's own header computes
 *   - Pure: no DOM, no side effects
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function heldHeaderCount( composite: TaskListComposite | null ): number | null {
  if ( composite === null ) return null;
  const status = composite.status ?? "";
  if ( status !== "" ) return null;
  if ( !Array.isArray( composite.tasks ) ) return null;
  return groupHeldRowsByFiler( composite.tasks ).reduce( ( n, g ) => n + g.tasks.length, 0 );
}
