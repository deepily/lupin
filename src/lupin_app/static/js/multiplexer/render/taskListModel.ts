/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Task-list card — pure model + formatters (Step 4, store-canonical task mgmt).
//
// The PURE (no-DOM) half of the task-list card, mirroring fleetModel.ts. Owns
// the wire shape of a `/api/tasks` row, the owner-grouping hierarchy, the
// open/terminal status partition, and the status / priority / next-chase
// formatters. Kept DOM-free so the table template + store consume one source
// of truth and every branch is unit-testable in isolation.
//
// Read-contract (LOCKED, cascade §F): read-only consumer of the EXISTING
// `GET /api/tasks` endpoint (routers/tasks.py:419-477) which returns FULL rows.
// This card does NOT touch tasks.py.

// ---------------------------------------------------------------------------
// Wire shapes (all fields optional — rendered defensively)
// ---------------------------------------------------------------------------

/** One `/api/tasks` row (server `_serialize_item`, tasks.py:131-160). */
export interface TaskItem {
  id?                  : string;
  item_class?          : string;
  title?               : string;
  body?                : string | null;
  project?             : string | null;
  owner_persona?       : string | null;
  accountable_manager? : string | null;
  created_by?          : string | null;
  status?              : string;
  blocked_by?          : string | null;
  next_chase_ts?       : string | null;
  gate_class?          : string | null;
  priority?            : string | null;
  source_qid?          : string | null;
  correlation_key?     : string | null;
  created_ts?          : string;
  updated_ts?          : string;
}

/**
 * The store's cached view. On a 200 the store wraps the endpoint body
 * (`{ tasks, count }`); on 401 / unreachable it caches a status sentinel so the
 * renderer degrades gracefully (last-known rows + indicator, never blank).
 */
export interface TaskListComposite {
  status? : string;             // "auth_required" | "unreachable" | undefined (ok)
  tasks?  : TaskItem[] | null;
  count?  : number;
}

export interface TaskGroup {
  ownerPersona : string | null;   // null → the "Unassigned" bucket
  isUnassigned : boolean;
  tasks        : TaskItem[];
}

export interface TaskListModel {
  totalCount : number;
  groups     : TaskGroup[];
}

// ---------------------------------------------------------------------------
// Status taxonomy (mirrors task_store_rules.VALID_STATUSES)
// ---------------------------------------------------------------------------

// Terminal statuses — work no longer owed. Everything else is "open".
const TERMINAL_STATUSES: ReadonlySet<string> = new Set( [ "done", "dropped" ] );

// Sort rank: most-urgent / most-active first, terminal last. Unknown → between
// open and terminal so a typo'd status never hides above blocked work.
const STATUS_RANK: Readonly<Record<string, number>> = {
  blocked     : 0,
  in_progress : 1,
  claimed     : 2,
  review      : 3,
  queued      : 4,
  done        : 6,
  dropped     : 7,
};
const UNKNOWN_STATUS_RANK = 5;

/** True when the status is non-terminal (work still owed). Pure. */
export function isOpenStatus( status: string | null | undefined ): boolean {
  if ( !status ) return true;   // missing status defaults to "open" (degrade-safe)
  return !TERMINAL_STATUSES.has( status );
}

function statusRank( status: string | null | undefined ): number {
  if ( !status ) return UNKNOWN_STATUS_RANK;
  const rank = STATUS_RANK[ status ];
  return rank === undefined ? UNKNOWN_STATUS_RANK : rank;
}

// Priority rank for the secondary sort: P0 highest. Unknown sorts last.
function priorityRank( priority: string | null | undefined ): number {
  if ( !priority ) return 99;
  const m = /^P(\d+)$/.exec( priority );
  return m ? Number( m[ 1 ] ) : 99;
}

// ---------------------------------------------------------------------------
// Labels
// ---------------------------------------------------------------------------

/**
 * Resolve a task's owner label: `owner_persona` preferred, "Unassigned" when
 * absent/empty. Pure.
 */
export function taskOwnerLabel( task: TaskItem | null | undefined ): string {
  if ( task && task.owner_persona ) return task.owner_persona;
  return "Unassigned";
}

/** Title fallback so a row never renders an empty primary cell. Pure. */
export function taskTitleLabel( task: TaskItem | null | undefined ): string {
  if ( task && task.title ) return task.title;
  return "(untitled)";
}

// ---------------------------------------------------------------------------
// Grouping
// ---------------------------------------------------------------------------

function asRows( tasks: unknown ): Array<TaskItem | null | undefined> {
  return Array.isArray( tasks ) ? ( tasks as Array<TaskItem | null | undefined> ) : [];
}

/**
 * Build the owner-grouped model: each distinct `owner_persona` is a group
 * (persona-sorted), tasks with no owner collapse into a single trailing
 * "Unassigned" bucket. Within a group, tasks sort by status-rank (blocked
 * first), then priority (P0 first), then title. Pure + degrade-safe (falsy
 * rows collapse to an empty Unassigned row, never throw).
 *
 * Requires:
 *   - tasks is an array of TaskItem (or non-array → treated as empty)
 * Ensures:
 *   - returns { totalCount, groups }; totalCount counts ALL input rows
 *   - groups are owner-sorted alpha; the Unassigned bucket (if any) is LAST
 *   - never throws
 */
export function groupTasksByOwner( tasks: unknown ): TaskListModel {
  const rows = asRows( tasks );

  const byOwner = new Map<string, TaskItem[]>();
  const unassigned: TaskItem[] = [];

  rows.forEach( ( raw ) => {
    const task = ( raw ?? {} ) as TaskItem;
    const owner = task.owner_persona;
    if ( owner ) {
      const bucket = byOwner.get( owner );
      if ( bucket ) bucket.push( task );
      else byOwner.set( owner, [ task ] );
    } else {
      unassigned.push( task );
    }
  } );

  const byUrgency = ( a: TaskItem, b: TaskItem ): number => {
    const sr = statusRank( a.status ) - statusRank( b.status );
    if ( sr !== 0 ) return sr;
    const pr = priorityRank( a.priority ) - priorityRank( b.priority );
    if ( pr !== 0 ) return pr;
    return taskTitleLabel( a ).localeCompare( taskTitleLabel( b ) );
  };

  const groups: TaskGroup[] = Array.from( byOwner.keys() )
    .sort( ( a, b ) => a.localeCompare( b ) )
    .map( ( owner ) => ( {
      ownerPersona : owner,
      isUnassigned : false,
      tasks        : byOwner.get( owner )!.slice().sort( byUrgency ),
    } ) );

  if ( unassigned.length > 0 ) {
    groups.push( {
      ownerPersona : null,
      isUnassigned : true,
      tasks        : unassigned.slice().sort( byUrgency ),
    } );
  }

  return { totalCount: rows.length, groups };
}

// ---------------------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------------------

/** Empty-cell guard: falsy / "none" → em-dash, else the trimmed value. Pure. */
export function taskCellOrDash( value: string | null | undefined ): string {
  if ( !value || value === "none" ) return "—";
  return value;
}

/**
 * Map a status word to its row-accent + badge color class. Pure.
 *
 * Ensures:
 *   - keys on the trimmed lowercase status:
 *     blocked→task-status-blocked, in_progress→…-active, claimed→…-active,
 *     review→…-review, queued→…-queued, done→…-done, dropped→…-dropped
 *   - anything else (empty / unrecognized) → task-status-unknown
 *   - never throws
 */
export function taskStatusClass( status: string | null | undefined ): string {
  const word = typeof status === "string" ? status.trim().toLowerCase() : "";
  if ( word === "blocked" )                          return "task-status-blocked";
  if ( word === "in_progress" || word === "claimed" ) return "task-status-active";
  if ( word === "review" )                           return "task-status-review";
  if ( word === "queued" )                           return "task-status-queued";
  if ( word === "done" )                             return "task-status-done";
  if ( word === "dropped" )                          return "task-status-dropped";
  return "task-status-unknown";
}

/**
 * Map a `P<n>` priority to its heat class. Pure.
 *
 * Ensures:
 *   - P0/P1 → "task-prio-high", P2 → "task-prio-mid", P3+ → "task-prio-low"
 *   - null/undefined/non-`P<n>` → "" (untinted)
 *   - never throws
 */
export function taskPriorityClass( priority: string | null | undefined ): string {
  if ( typeof priority !== "string" ) return "";
  const m = /^P(\d+)$/.exec( priority.trim() );
  if ( !m ) return "";
  const n = Number( m[ 1 ] );
  if ( n <= 1 ) return "task-prio-high";
  if ( n === 2 ) return "task-prio-mid";
  return "task-prio-low";
}

/**
 * Format an ISO-8601 next-chase timestamp as "MM-DD HH:MM" in the given IANA
 * zone (DST-aware via Intl). Null/absent → "—"; unparseable → "—"; invalid
 * zone → browser-local. Pure (never throws).
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line (try/catch default-param interplay).
export function formatChaseTime( iso: string | null | undefined, ianaZone: string | null | undefined ): string {
  if ( !iso ) return "—";
  const date = new Date( iso );
  if ( Number.isNaN( date.getTime() ) ) return "—";
  const opts: Intl.DateTimeFormatOptions = {
    hour12 : false,
    month  : "2-digit",
    day    : "2-digit",
    hour   : "2-digit",
    minute : "2-digit",
  };
  if ( ianaZone ) {
    try {
      return new Intl.DateTimeFormat( undefined, { ...opts, timeZone: ianaZone } ).format( date );
    } catch {
      // Invalid IANA zone — degrade to browser-local (never throw).
    }
  }
  return new Intl.DateTimeFormat( undefined, opts ).format( date );
}
