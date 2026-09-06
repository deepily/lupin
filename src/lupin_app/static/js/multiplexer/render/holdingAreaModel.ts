/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Holding-area card — pure model helpers (TS multiplexer card).
//
// Reproduces the in-service JS card's holding-area grouping and sort
// (notifications.js:9540 _groupHeldRowsByFiler, :9889 _taskFilerLabel) as
// OBSERVATIONAL EQUIVALENCE, not shared code — Rick's ruling: the two clients
// share no code, so this is a specification-and-reproduction exercise.
//
// Spec: src/rnd/2026.09.05-fleet-accordions-current-state-inventory.md §5c

import { priorityRank, taskTitleLabel, type TaskItem } from "./taskListModel";

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
  const raw = task && task.created_by ? String( task.created_by ).trim() : "";
  if ( !raw ) return "—";

  // Anchored at the END. A leading-word rule cannot express a two-word persona.
  const stripped = raw.replace( /\s+[0-9a-f]{8}$/i, "" ).trim();

  // A non-match leaves `stripped === raw`, which is the deliberate fall-through:
  // render it whole rather than guess where the name stops.
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
