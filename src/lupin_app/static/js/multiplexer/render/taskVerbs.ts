/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Task-list card — the verb table (row-control conversion, 2026.09.02).
//
// The multiplexer's Actions cell used to offer ONE verb, Drop, as a bare input
// plus a button. Rick ruled the one-select shape for the notifications board and
// then ruled it again for this surface: one select carrying all five verbs, one
// shared reason field, one Submit.
//
// This module is the pure half of that — no DOM, no store, no fetch. It answers
// three questions and nothing else: which verbs exist, what each one asks the
// operator for, and which of them a row in a given status may legally take. The
// cell renders what it says; the renderer posts what it says.
//
// Ported from notifications.js `_verbNeeds` / `_taskActionsCell` rather than
// re-derived. The payload shapes in particular are SETTLED — a second derivation
// is a second chance to get `park_reason` wrong.

import { isOpenStatus } from "./taskListModel";

/** The five verbs, in the fixed order they render in. */
export const TASK_VERBS: ReadonlyArray<string> = [ "park", "drop", "demote", "wont_fix", "approve" ];

/**
 * What one verb asks the operator for, and what it posts.
 *
 * 🔴 This table is the point of the redesign. On the notifications board five
 * verbs were five buttons because each carried a different obligation; the
 * obligations did not go away when the buttons did, they moved into a table like
 * this one. Here there was only ever one button, so the four other obligations
 * arrive for the first time — which is why this file is an addition and not a
 * merge, whatever the shape of the two surfaces looks like from outside.
 *
 * ⚠️ `dateLabel` answers a question Rick asked ("I really have no idea what the
 * date chooser is for") rather than naming the field the server stores it in. A
 * control whose purpose the operator cannot infer is a defect in the control.
 */
export interface VerbNeeds {
  /** The `to_status` the transition endpoint is asked for. */
  status      : string;
  /** True when a non-blank reason is required before the verb may be submitted. */
  reason      : boolean;
  /** True when a chase/triage date is required. */
  date        : boolean;
  /** The label the date input announces itself with; "" when there is no date. */
  dateLabel   : string;
  /** The reason field's placeholder while this verb is chosen. */
  placeholder : string;
  /** True when the verb closes the row for good and earns a confirm step. */
  terminal    : boolean;
}

const NEEDS: Readonly<Record<string, VerbNeeds>> = {
  park     : { status: "parked",       reason: true,  date: true,
               dateLabel: "Chase me again on",
               placeholder: "quote the sentence that decided this…", terminal: false },
  drop     : { status: "dropped",      reason: true,  date: false, dateLabel: "",
               placeholder: "why this is being dropped…", terminal: false },
  demote   : { status: "not_approved", reason: true,  date: true,
               dateLabel: "Triage this by",
               placeholder: "why this goes back to triage…", terminal: false },
  wont_fix : { status: "wont_fix",     reason: true,  date: false, dateLabel: "",
               placeholder: "why this will not be done…", terminal: true },
  approve  : { status: "queued",       reason: false, date: false, dateLabel: "",
               placeholder: "Approve needs no reason", terminal: false },
};

/**
 * Look up one verb's obligations.
 *
 * Ensures:
 *   - an unknown verb (including "") returns null — the caller's cue that the
 *     operator has not chosen anything yet
 *   - a known verb returns its full obligation record
 */
export function verbNeeds( verb: string | null | undefined ): VerbNeeds | null {
  if ( !verb ) return null;
  return NEEDS[ verb ] ?? null;
}

/**
 * The human name of a verb, for an option label or a refusal stripe.
 *
 * Ensures: returns the verb itself when unknown, never undefined.
 */
export function verbLabel( verb: string ): string {
  const LABELS: Readonly<Record<string, string>> = {
    park: "Park", drop: "Drop", demote: "Demote",
    wont_fix: "Won't fix", approve: "Approve",
  };
  return LABELS[ verb ] ?? verb;
}

/**
 * The refusal each verb earns when its reason is blank.
 *
 * ⚠️ Five verbs share one box and must NOT share one complaint. "A reason is
 * required" is true of four of them and teaches none of them: park needs a
 * QUOTE, demote must say why a row goes back to triage, and won't-fix is a
 * refusal whose justification is the only thing distinguishing it from work that
 * got forgotten. Merging the controls was the ask; merging what they mean was not.
 *
 * Ensures: returns a verb-specific sentence, never a generic one for a known verb.
 */
export function verbReasonComplaint( verb: string ): string {
  const COMPLAINTS: Readonly<Record<string, string>> = {
    drop     : "A drop reason is required.",
    park     : "A park reason is required — quote the row's own decisive sentence.",
    demote   : "A demote reason is required — say why this goes back to triage, or the next reader cannot tell it from a row that was never approved.",
    wont_fix : "A won't-fix reason is required — a refusal carries its justification, exactly as a drop does.",
  };
  return COMPLAINTS[ verb ] ?? "A reason is required.";
}

/**
 * The refusal a verb earns when its required date is blank. Park and Demote are
 * the only two that reach here, and they mean different things by a date, so
 * they say different things.
 */
export function verbDateComplaint( verb: string ): string {
  return verb === "park"
    ? "A chase date is required — a park is bounded, never indefinite."
    : "A triage-by date is required — a held row is bounded, never indefinite. Use won't-fix to kill it outright.";
}

/** One verb's standing on one row: may it be chosen, and if not, why not. */
export interface VerbLegality {
  verb    : string;
  label   : string;
  enabled : boolean;
  /** Empty when enabled; otherwise the sentence the greyed option carries. */
  why     : string;
}

/**
 * Which verbs a row in `status` may legally take.
 *
 * 🔴 A TERMINAL ROW OFFERS NOTHING. `done` / `dropped` / `wont_fix` are
 * append-only — the server's `validate_transition` refuses every edge out of
 * them. Every option is greyed and says so.
 *
 * ⚠️ Approve and Demote are opposite ends of one door, so exactly one of them is
 * ever live on a row. Approve is the holding area's exit (`not_approved →
 * queued`); Demote is its entrance. Offering both hands the operator a move that
 * is a no-op in one direction, which the store rejects as a failure rather than
 * as nothing happening.
 *
 * Requires:
 *   - status is the row's status string, or null/undefined
 * Ensures:
 *   - returns exactly TASK_VERBS.length entries, in TASK_VERBS order
 *   - a terminal row returns every entry disabled, each carrying the same
 *     append-only sentence naming the row's own status
 *   - Park is enabled ONLY from queued / in_progress
 *   - Approve is enabled ONLY on a not_approved row; Demote on every OTHER
 *     non-terminal row
 *   - Drop and Won't-fix are enabled on every non-terminal row
 */
export function verbLegality( status: string | null | undefined ): ReadonlyArray<VerbLegality> {
  const s          = ( status ?? "" ).toLowerCase();
  const isTerminal = !isOpenStatus( s );
  const isHeld     = s === "not_approved";
  const shown      = s || "unknown";
  const dead       = `this row is ${shown}; terminal rows are append-only and have no transitions out`;

  const parkLegal   = !isTerminal && ( s === "queued" || s === "in_progress" );
  const demoteLegal = !isTerminal && !isHeld;

  const entry = ( verb: string, enabled: boolean, why: string ): VerbLegality =>
    ( { verb, label: verbLabel( verb ), enabled, why: enabled ? "" : why } );

  return [
    entry( "park",     parkLegal,    isTerminal ? dead : "only from queued or in progress" ),
    entry( "drop",     !isTerminal,  dead ),
    entry( "demote",   demoteLegal,  isTerminal ? dead : "this row is already in the holding area" ),
    entry( "wont_fix", !isTerminal,  dead ),
    entry( "approve",  isHeld,       isTerminal ? dead : "only a row in the holding area can be approved" ),
  ];
}

/**
 * The extra body fields a verb's transition carries, beyond `to_status`.
 *
 * 🔴 PARK POSTS ITS REASON UNDER `park_reason`, NOT `reason`. The server keys
 * the two apart and a park filed under the generic key lands with no decisive
 * sentence attached — which is the whole thing the field exists to carry. This
 * mapping is copied from the notifications board rather than re-derived; a
 * second derivation is a second chance to get it wrong.
 *
 * Requires:
 *   - verb is a known verb (callers gate on verbNeeds first)
 *   - reason is the trimmed reason text; chaseIso is an ISO instant or null
 * Ensures:
 *   - a verb that takes no reason contributes no reason key at all
 *   - park's reason lands under `park_reason`; every other verb's under `reason`
 *   - a verb that takes a date contributes `next_chase_ts`
 */
export function transitionExtras(
  verb     : string,
  reason   : string,
  chaseIso : string | null,
): Record<string, string> {
  const needs = verbNeeds( verb );
  /* c8 ignore next */ // defensive: callers gate on verbNeeds before reaching here.
  if ( needs === null ) return {};
  const extras: Record<string, string> = {};
  if ( needs.reason ) extras[ verb === "park" ? "park_reason" : "reason" ] = reason;
  if ( needs.date && chaseIso !== null ) extras.next_chase_ts = chaseIso;
  return extras;
}
