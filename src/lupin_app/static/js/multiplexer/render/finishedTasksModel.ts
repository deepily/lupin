/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Finished Tasks — the pure half (row 470b7509, the MULTIPLEXER port of the
// legacy pane shipped at ba4bb92c).
//
// 🔴 NO CODE REUSE, AND THAT IS A RULING (Rick, row 87812328). Legacy is JS in
// one file; this is TS across a store / model / template / renderer split. The
// target is OBSERVATIONAL EQUIVALENCE — the same statuses, the same six empty
// states, the same em-dash-before-first-poll — reached independently. Nothing
// here imports from `static/js/notifications.js`, and the server's
// `VALID_STATUSES` is the authority both copies answer to.
//
// 🔴 THE SOURCE IS THE EVENT STREAM, WHICH IS RULING R5 AND NOT A PREFERENCE.
// `/api/tasks` cannot answer "which rows became terminal in the last 24 hours":
// there is no terminal-timestamp column in the schema, so its `updated_ts`
// moves on EVERY write and an amended three-day-old row reads as freshly
// finished; and it orders by `created_ts`, so a row finished ten minutes ago
// sorts below every row created today. `task_events` is append-only, one row
// per state change, already ordered ts DESC.
//
// This file holds only decisions that need no DOM: the status taxonomy, the
// persisted-filter polarity, the relative clock, the merge/sort, and the
// empty-state dispatch. The DOM lives in templates/finishedTasksTable.ts and
// FinishedTasksRenderer.ts; fetch/poll lives in stores/FinishedTasksStore.ts.

// The ONE import this pure model takes: the shared prototype-chain refusal.
// See mergeShownEvents — a persisted status name must not reach an inherited member.
import { ownLookup } from "../shared/ownLookup";

/** One `task_events` row as `_serialize_event` puts it on the wire. */
import { personaLabel } from "../shared/personaLabel";

export interface FinishedTaskEvent {
  id            : number;
  item_id       : string;
  ts            : string;
  actor         : string | null;
  transition    : string | null;
  reason        : string | null;
  title         : string | null;
  authority?    : string | null;
  receipt_refs? : unknown;
}

/**
 * Events keyed by the status they landed on.
 *
 * 🔴 AN ABSENT KEY AND AN EMPTY ARRAY ARE DIFFERENT FACTS, AND THE WHOLE PANE
 * TURNS ON THE DIFFERENCE. Absent means that status was never successfully
 * measured; empty means it was measured and nothing reached it. Rendering the
 * first as the second turns a broken fetch into an apparently quiet day, which
 * is the exact failure this pane exists to prevent.
 */
export type FinishedEventsByStatus = Readonly<Partial<Record<string, ReadonlyArray<FinishedTaskEvent>>>>;

/**
 * The three terminal statuses, in the order the pills render.
 *
 * This client's OWN copy of the server's TERMINAL_STATUSES, per the
 * no-code-reuse ruling. `not_approved` is deliberately absent: the server's own
 * comment forbids adding it to TERMINAL_STATUSES — a held row has not started,
 * it has not finished.
 */
export const FINISHED_STATUSES: ReadonlyArray<string> = Object.freeze( [ "done", "dropped", "wont_fix" ] );

/** DONE pre-lit ALONE (design §1.2) — the cold-start selection, and the
 *  fallback whenever the persisted value is missing or unusable. */
export const FINISHED_DEFAULT_SHOWN: ReadonlyArray<string> = Object.freeze( [ "done" ] );

/**
 * localStorage key holding the JSON array of SHOWN statuses.
 *
 * 🔴 POSITIVE POLARITY, DECLARED AT THE POINT OF DEFINITION (design §9.4), and
 * the key name says so — it holds what IS shown. This is not a style choice:
 * a NEGATIVE array spells the required `DONE ONLY` default as
 * `["dropped","wont_fix"]`, and the day a FOURTH terminal status is added it is
 * not in that list, so it appears in a pane whose entire specification is that
 * it defaults to done. `["done"]` keeps meaning exactly done, forever.
 *
 * ⚠️ AND THIS FILE SITS BESIDE TWO KEYS THAT DISAGREE WITH EACH OTHER —
 * `lupin.taskList.collapsedOwners` is an ARRAY of COLLAPSED keys and
 * `lupin.epicBoard.groupState` is a MAP of key -> isEXPANDED. Same feature,
 * inverted sense, different container. Copying either one inverts a user's
 * saved state and FAILS INVISIBLY, which is why the polarity is written here
 * rather than left to be inferred from a neighbour.
 */
export const FINISHED_SHOWN_KEY = "lupin.finishedTasks.shownStatuses";

/** The window slider's range, in DAYS. Days on screen, hours on the wire. */
export const FINISHED_WINDOW_MIN_DAYS = 1;
export const FINISHED_WINDOW_MAX_DAYS = 14;
/** Rick's ruling, 2026-09-07 ~20:55 EDT by keypress: the day control is a
 *  WIDTH slider — you widen how far back the pane looks. It is NOT an offset
 *  stepper, and there is not one alongside it. */
export const FINISHED_WINDOW_DEFAULT_DAYS = 1;

/** The count chip / pill badge before anything has been measured. NEVER "0" —
 *  a 0 claims something was counted, and nothing has been. */
export const FINISHED_UNMEASURED = "—";

/** Poll cadence, matching every other autonomous pane on this page. */
export const FINISHED_TASKS_POLL_INTERVAL_MS = 60000;

/** Rows fetched per status per poll. The whole population is ~47/day, so one
 *  page is the whole window and there is no pagination to get wrong. */
export const FINISHED_TASKS_PAGE_LIMIT = 500;

/**
 * Clamp a slider value to the declared range, rejecting anything unusable.
 *
 * Requires:
 *   - value is whatever the DOM or a persisted read produced (string, number,
 *     NaN, null, …)
 *
 * Ensures:
 *   - returns an integer in [FINISHED_WINDOW_MIN_DAYS, FINISHED_WINDOW_MAX_DAYS]
 *   - anything non-finite falls back to the default rather than to 0 — a
 *     zero-day window is a window that can never contain anything, and it would
 *     render as a measured "nothing finished"
 *   - never throws
 */
export function clampWindowDays( value: unknown ): number {
  const n = Math.floor( Number( value ) );
  if ( !Number.isFinite( n ) ) return FINISHED_WINDOW_DEFAULT_DAYS;
  if ( n < FINISHED_WINDOW_MIN_DAYS ) return FINISHED_WINDOW_MIN_DAYS;
  if ( n > FINISHED_WINDOW_MAX_DAYS ) return FINISHED_WINDOW_MAX_DAYS;
  return n;
}

/**
 * The `since` instant for a window, as the API's ISO-8601 parameter.
 *
 * 🔴 THE ×24 LIVES HERE AND NOWHERE ELSE. The slider is the only thing in this
 * feature that speaks days; the wire keeps taking the instant it always took.
 * Two places doing this conversion is how a 14-day window becomes a 14-hour one
 * in exactly one of them.
 */
export function windowSinceIso( days: number, nowMs: number ): string {
  return new Date( nowMs - clampWindowDays( days ) * 24 * 60 * 60 * 1000 ).toISOString();
}

/**
 * Read the persisted SHOWN statuses.
 *
 * Requires:
 *   - raw is the localStorage value, or null when the key is absent
 *
 * Ensures:
 *   - a missing key returns the HTML/spec default (done only), NEVER an empty
 *     selection — matching the section-axis convention's "missing key = use the
 *     default", and because an empty selection is a pane deliberately showing
 *     nothing, which is never a useful state
 *   - a corrupt or unparseable value falls back the same way
 *   - values not in FINISHED_STATUSES are dropped; if that leaves nothing, the
 *     default is used. A persisted array from a future build naming a status
 *     this one does not know must not empty the pane
 *   - the returned order follows FINISHED_STATUSES, so the set round-trips
 *     stably rather than reordering on every write
 *   - never throws
 */
export function parseShownStatuses( raw: string | null ): ReadonlyArray<string> {
  if ( raw === null ) return FINISHED_DEFAULT_SHOWN;
  let parsed: unknown;
  try {
    parsed = JSON.parse( raw );
  } catch {
    return FINISHED_DEFAULT_SHOWN;
  }
  if ( !Array.isArray( parsed ) ) return FINISHED_DEFAULT_SHOWN;
  const kept = FINISHED_STATUSES.filter( ( s ) => parsed.includes( s ) );
  return kept.length === 0 ? FINISHED_DEFAULT_SHOWN : kept;
}

/**
 * "14m" / "1h12m" / "19h" / "3d". Pure; never throws.
 *
 * Ensures:
 *   - an absent or unparseable timestamp renders the em dash rather than
 *     "NaNm", because a rendered NaN reads as a defect in the ROW when it is a
 *     defect in the clock
 *   - a future timestamp clamps to "0m" rather than going negative — clock skew
 *     between the browser and the server is ordinary and must not print "-3m"
 */
export function relativeAge( iso: string | null | undefined, nowMs: number ): string {
  if ( iso === null || iso === undefined || iso === "" ) return FINISHED_UNMEASURED;
  const then = new Date( iso ).getTime();
  if ( Number.isNaN( then ) ) return FINISHED_UNMEASURED;
  const mins = Math.max( 0, Math.floor( ( nowMs - then ) / 60000 ) );
  if ( mins < 60 ) return `${ mins }m`;
  const hours = Math.floor( mins / 60 );
  if ( hours < 24 ) return mins % 60 === 0 ? `${ hours }h` : `${ hours }h${ mins % 60 }m`;
  return `${ Math.floor( hours / 24 ) }d`;
}

/**
 * The persona alone, from an actor field shaped "persona sessionid".
 *
 * Ensures:
 *   - the session id is dropped — it is noise at a glance, and this column is a
 *     glance
 *   - an absent actor renders the em dash rather than an empty cell, so a row
 *     with no recorded actor is visibly different from a narrow column
 */
export function actorPersona( actor: string | null | undefined ): string {
  // ONE rule, ONE place — see shared/personaLabel.ts. The naive leading-word split
  // shipped to this very column, in a file next door to one whose docstring warned
  // against it, which is why the rule is a function now rather than a comment.
  return personaLabel( actor, FINISHED_UNMEASURED );
}

/**
 * The status a transition landed on — the right-hand side of "queued->done".
 *
 * Ensures:
 *   - returns "" for an absent or malformed transition rather than throwing, so
 *     a torn row renders untinted instead of taking the pane down
 */
export function transitionTarget( transition: string | null | undefined ): string {
  if ( typeof transition !== "string" ) return "";
  const parts = transition.split( "->" );
  /* c8 ignore next */ // `?? ""` is unreachable: String.split always yields >=1 element, so the last index always exists. Present only because noUncheckedIndexedAccess types it as possibly-undefined.
  return parts[ parts.length - 1 ] ?? "";
}

/**
 * Merge the LIT statuses' events into one newest-first list.
 *
 * Requires:
 *   - shown is the currently-lit status list (positive polarity)
 *
 * Ensures:
 *   - only lit statuses contribute — an unlit status's rows are withheld from
 *     the table while its pill still shows its own count, because a pill's
 *     number must not depend on whether it happens to be lit
 *   - sorted by ts DESCENDING, with the event id as a stable tiebreak so two
 *     events sharing a timestamp do not swap places between repaints
 *   - never mutates its input
 */
export function mergeShownEvents(
  eventsByStatus: FinishedEventsByStatus,
  shown         : ReadonlyArray<string>,
): ReadonlyArray<FinishedTaskEvent> {
  const merged: FinishedTaskEvent[] = [];
  for ( const status of shown ) {
    // Read through the shared refusal, NOT `eventsByStatus[ status ]`. `shown` is the
    // LIT set and is PERSISTED, so a stored "toString" makes a bare index return the
    // inherited Function — which IS `!== undefined`, so the guard below passes and the
    // spread throws, taking the pane down. Measured, not argued: spreading it raises
    // "Spread syntax requires ...iterable[Symbol.iterator] to be a function".
    // The guard test could not see this line — its regex keys on a trailing `??`/`||`
    // and this coalesces with an `if`. Same hazard, different syntax.
    const rows = ownLookup< ReadonlyArray<FinishedTaskEvent> | undefined >(
      eventsByStatus as Readonly<Record<string, ReadonlyArray<FinishedTaskEvent> | undefined>>,
      status,
      undefined,
    );
    if ( rows !== undefined ) merged.push( ...rows );
  }
  return merged.sort( ( a, b ) => {
    const byTs = String( b.ts ?? "" ).localeCompare( String( a.ts ?? "" ) );
    return byTs !== 0 ? byTs : ( b.id ?? 0 ) - ( a.id ?? 0 );
  } );
}

/**
 * Which of the six pane states to paint.
 *
 * 🔴 SIX, AND THEY ARE SIX BECAUSE THEY MEAN SIX DIFFERENT THINGS. Collapsing
 * them into one "no results" is exactly what turns a broken fetch into an
 * apparently quiet day — and this pane exists because work was going
 * unfinished, so the difference between "nothing finished" and "I could not
 * find out" is the whole product.
 *
 *   error       nothing measured at all, and a failure explains why
 *   unmeasured  nothing measured yet, and no failure — the first poll is out
 *   no_filter   every pill is off (reachable only transiently; a click that
 *               would empty the selection re-lights DONE)
 *   empty       measured, and a real zero
 *   partial     some statuses answered and some did not — rows shown, and SAID
 *               to be incomplete
 *   rows        measured, complete, non-empty
 *
 * Requires:
 *   - measuredStatuses is the set of statuses whose fetch SUCCEEDED
 *
 * Ensures:
 *   - the order of the checks is the order above and it is load-bearing: a
 *     total failure must not be reported as a measured zero
 */
export type FinishedPaneState = "error" | "unmeasured" | "no_filter" | "empty" | "partial" | "rows";

/* c8 ignore next */ // tsx phantom-branch artifact on the function declaration line (object-literal param type erasure).
export function finishedPaneState( opts: {
  measuredStatuses : ReadonlyArray<string>;
  shown            : ReadonlyArray<string>;
  visibleCount     : number;
  error            : string | null;
} ): FinishedPaneState {
  const measured = opts.measuredStatuses.length > 0;
  if ( !measured ) return opts.error !== null ? "error" : "unmeasured";
  if ( opts.shown.length === 0 ) return "no_filter";
  if ( opts.visibleCount === 0 ) return "empty";
  return opts.error !== null ? "partial" : "rows";
}
