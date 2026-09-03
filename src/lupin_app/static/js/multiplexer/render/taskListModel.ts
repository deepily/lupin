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
// Phase 2 (per-worker task editing) adds the PATCH/transition WRITE consumers in
// TaskListStore — the card stays a pure consumer; it still does NOT touch tasks.py.

import { splitFleetByLiveness, type FleetComposite } from "./fleetModel";

// ---------------------------------------------------------------------------
// Wire shapes (all fields optional — rendered defensively)
// ---------------------------------------------------------------------------

/**
 * One blocked-by dependency: a TYPED ref. Real `/api/tasks` rows return
 * `blocked_by` as an ARRAY of these (postgres_models.TaskItem.blocked_by is a
 * JSONB list [{kind: item|persona|user, id}]). Both fields are optional so a
 * malformed ref never throws the render (mirrors the JS card's 2724b80d fix).
 */
export interface TaskBlockedRef {
  kind? : string;
  id?   : string;
}

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
  // Real rows return a typed-ref ARRAY; string|null kept for defensive back-compat.
  blocked_by?          : string | TaskBlockedRef[] | null;
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
const TERMINAL_STATUSES: ReadonlySet<string> = new Set( [ "done", "dropped", "wont_fix" ] );

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
// Exported (Phase 2) — the editable priority control reuses the same ranking
// vocabulary the model sorts by, so the dropdown order matches row order.
export function priorityRank( priority: string | null | undefined ): number {
  if ( !priority ) return 99;
  const m = /^P(\d+)$/.exec( priority );
  return m ? Number( m[ 1 ] ) : 99;
}

// ---------------------------------------------------------------------------
// Phase 2 — per-worker task editing helpers (pure; no DOM)
// ---------------------------------------------------------------------------

// The editable priority buckets (D2 — P0–P3 now; intra-bucket drag-reorder is
// the deferred Phase 2b). Ordered most-urgent first so the dropdown reads
// top-to-bottom in the same urgency order the rows sort by (priorityRank).
export const EDITABLE_PRIORITIES: ReadonlyArray<string> = [ "P0", "P1", "P2", "P3" ];

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
// Row redesign 2026.06.29 — id column + title truncation + body-overlay helpers
// (pure; MIRRORS the in-service JS card's notifications.js helpers VERBATIM so
// the two cards render the row identically. Drift accepted per D5/throwaway.)
// ---------------------------------------------------------------------------

// Client title-truncation cap. It USED to be identical to the server-side store
// cap (task_store_rules.TITLE_SOFT_CAP, handoff #5 / D4), and that comment stayed
// here asserting the identity after it stopped being true — which is the exact
// failure the row that moved the cap was about.
//
// 🔴 THEY DIVERGED DELIBERATELY ON 2026-09-01. Rick raised the STORE cap 60 -> 120
// (bug 6ce252e7). This number stayed at 60 because the two caps answer different
// questions and always did: the store cap decides what is KEPT, and losing a tail
// there destroys a qualifier permanently. This one decides how much fits in a
// fixed-width column, and what it cuts is recoverable in place — the row renders
// an ellipsis and the full title rides the cell's hover tooltip.
//
// ⚠️ SO: DO NOT "RESYNC" THIS TO 120 to restore the old identity. A 120-char cell
// changes the row layout, and nothing is lost at 60. Whether the column should get
// wider now that titles may legitimately run to 120 is a UI question for Rick, and
// it is banked rather than decided here.
export const TASK_TITLE_TRUNCATE_LEN = 60;

/**
 * The compact row identifier: the first 8 chars of the item's id (the store
 * serializes its UUID as `id`; first-8 is the "id_hash" the design 2026.06.29
 * row redesign places in the new leftmost column). Pure.
 *
 * Ensures:
 *   - non-empty id → its first 8 chars; absent/empty → "—"
 *   - never throws
 */
export function taskIdLabel( task: TaskItem | null | undefined ): string {
  const id = ( task && task.id != null ) ? String( task.id ) : "";
  return id ? id.slice( 0, 8 ) : "—";
}

/**
 * Client title-truncation backstop (design 2026.06.29 §4.4 / D1): trim a
 * wall-of-text title to TASK_TITLE_TRUNCATE_LEN chars + an ellipsis. The full
 * title rides the cell's hover-tooltip so nothing is hidden. Pure.
 *
 * Ensures:
 *   - label.length > cap → label.slice( 0, cap ) + "…"; else label verbatim
 *   - never throws
 */
export function truncateTaskTitle( label: string ): string {
  const s = String( label );
  return s.length > TASK_TITLE_TRUNCATE_LEN ? s.slice( 0, TASK_TITLE_TRUNCATE_LEN ) + "…" : s;
}

/**
 * Whether the task has no detail `body` to show in the overlay — drives the
 * dim-in-place 📄 (handoff ruling #3): an empty body keeps the emoji in its
 * column but disabled / non-clickable. Pure.
 *
 * Ensures:
 *   - body null / undefined / whitespace-only → true; else false
 *   - never throws
 */
export function taskBodyIsEmpty( task: TaskItem | null | undefined ): boolean {
  const body = task ? task.body : null;
  return body == null || String( body ).trim() === "";
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
 * Stringify a `blocked_by` value to a single cell string. Real `/api/tasks` rows
 * return a typed-ref ARRAY [{kind, id}]; each ref renders "kind:id" (or just the
 * id when kind is absent), joined with ", ". A plain string / null passes through
 * unchanged (defensive back-compat). MIRRORS the in-service JS card's _renderTaskRow
 * (2724b80d) VERBATIM so the two cards render blocked_by identically. Pure.
 *
 * Ensures:
 *   - array → each ref "kind:id" (or "id" when kind falsy; String(ref) when not an
 *     object), joined ", "; an empty array → "" (caller's taskCellOrDash → "—")
 *   - string|null|undefined → returned unchanged
 *   - never throws (the latent array-crash the JS card hit pre-2724b80d)
 */
export function formatTaskBlockedBy(
  blockedBy: string | TaskBlockedRef[] | null | undefined,
): string | null | undefined {
  if ( !Array.isArray( blockedBy ) ) return blockedBy;
  return blockedBy
    .map( ( ref ) => ( ref && typeof ref === "object" ) ? ( ref.kind ? `${ref.kind}:${ref.id}` : `${ref.id}` ) : String( ref ) )
    .join( ", " );
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

// ---------------------------------------------------------------------------
// Phase 2 — actor derivation + reassign roster (pure)
// ---------------------------------------------------------------------------

/**
 * Derive the audit `actor` string for a UI-originated edit from the
 * authenticated user's identity (Rick's Q1 ruling 2026-06-23: DERIVE from the
 * AUTHENTICATED user — email/display identity — NOT a fixed literal). The
 * "(multiplexer)" surface tag records WHICH client made the edit (the audit
 * trail already distinguishes provenance via `authority='user_direct'`, but the
 * surface tag disambiguates two edits by the same human from different clients).
 * Pure.
 *
 * Ensures:
 *   - a non-blank email → "<trimmed-email> (multiplexer)"
 *   - null / undefined / blank email → "anonymous (multiplexer)" (defensive —
 *     an authenticated card always carries an email claim; this is the
 *     pre-hydration / malformed-token safety net, never a fixed business literal)
 *   - never throws
 */
export function deriveTaskActor( email: string | null | undefined ): string {
  const id = typeof email === "string" ? email.trim() : "";
  return id ? `${id} (multiplexer)` : "anonymous (multiplexer)";
}

/**
 * Build the reassignment-target roster from the SAME source the fleet-status
 * card consumes (`FleetStatusStore` → `fleet_arbiter.sessions`), filtered to
 * ACTIVE (non-offline) personas — INCLUDING the 'Sam' overflow persona (Rick's
 * Q5 ruling 2026-06-23: the roster is the same one the fleet-status card shows,
 * which carries Sam as a live persona; no reassign-only exclusion). Distinct,
 * alpha-sorted. Pure + degrade-safe.
 *
 * Requires:
 *   - fleet is the FleetComposite the fleet card caches, or null (pre-first-poll
 *     / auth / unreachable sentinels all collapse to an empty roster)
 * Ensures:
 *   - null / missing fleet_arbiter / missing sessions → []
 *   - only LIVE sessions contribute (splitFleetByLiveness — same "live" rule the
 *     fleet card shows by default); offline personas never become targets
 *   - blank personas dropped; duplicates collapsed; Sam (when live) is a target
 *   - returned alpha-sorted
 *   - never throws
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the function-declaration line (union-typed param + array return-type interplay); all internal branches are exercised by tests.
export function activeReassignTargets( fleet: FleetComposite | null | undefined ): string[] {
  if ( !fleet || !fleet.fleet_arbiter ) return [];
  const sessions = fleet.fleet_arbiter.sessions;
  if ( !Array.isArray( sessions ) ) return [];
  const { live } = splitFleetByLiveness( sessions );
  const seen = new Set<string>();
  for ( const s of live ) {
    const persona = s.persona;
    if ( !persona ) continue;
    seen.add( persona );
  }
  return Array.from( seen ).sort( ( a, b ) => a.localeCompare( b ) );
}
