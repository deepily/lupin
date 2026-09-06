/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Holding-area card — the BATCH verb table (row 87812328).
//
// The pure half of approve-all / won't-fix-all: no DOM, no fetch, no store. It
// answers what the two batch verbs post, what the operator is refused for, and
// what every line of the group's status text reads — and nothing else. The
// sequential loop, the id lookup and the control disabling live in the renderer,
// which is the layer the operator's click actually enters at.
//
// Ported from notifications.js `_handleHoldingApproveAllClick` /
// `_handleHoldingWontFixAllClick` / `_applyHoldingBatch` rather than
// re-derived. Every string below is a CARBON COPY and is pinned against that
// file on disk, not against a literal retyped here — two provenances, so the
// comparison can actually fail.
//
// 🔴 THE TWO VERBS ARE NOT SYMMETRIC AND THE ASYMMETRY IS THE WHOLE DESIGN.
// Approve is `not_approved → queued`, the non-destructive direction: no reason,
// no confirm, and a row approved by mistake is demoted straight back. Won't-fix
// is TERMINAL and applies ONE reason to EVERY row under a filer — honest for the
// case the batch exists to serve, dishonest for a mixed group, which is why the
// per-row control stays the right tool whenever the reasons differ.
//
// ⚠️ THE FRICTION ON WON'T-FIX-ALL IS THE REQUIRED REASON BOX, NOT A DIALOG.
// A browser `confirm()` blocks the extension's event loop, so the one control
// that closes a whole group for good must not be the one that freezes the board.
// The per-row Submit arms-then-confirms on its own label for the same reason;
// here the box is already the second deliberate act.

/** The two batch verbs, in the fixed order they render in. */
export const HOLDING_BATCH_VERBS: ReadonlyArray<string> = [ "approve", "wont_fix" ];

/**
 * What one batch verb posts, and what it asks the operator for first.
 *
 * `pastLabel` is the word the status line is built from ("Approved" / "Closed")
 * — it reads as a participle in flight (`Approved 3 of 8…`) and lower-cased in
 * the final line (`3 of 8 closed.`), which is why it is stored capitalised and
 * lowered at the point of use rather than carried twice.
 */
export interface HoldingBatchNeeds {
  /** The `to_status` every row in the group is transitioned to. */
  status    : string;
  /** True when a non-blank group reason is required before anything is posted. */
  reason    : boolean;
  /** True when the verb closes every row for good. */
  terminal  : boolean;
  /** The participle the status line is built from. */
  pastLabel : string;
}

const BATCH_NEEDS: Readonly<Record<string, HoldingBatchNeeds>> = {
  approve  : { status: "queued",   reason: false, terminal: false, pastLabel: "Approved" },
  wont_fix : { status: "wont_fix", reason: true,  terminal: true,  pastLabel: "Closed"   },
};

/**
 * Look up one batch verb's obligations.
 *
 * Ensures:
 *   - an unknown verb (including "" / null / undefined) returns null
 *   - a known verb returns its full obligation record
 */
export function holdingBatchNeeds( verb: string | null | undefined ): HoldingBatchNeeds | null {
  if ( !verb ) return null;
  // 🔴 `Object.hasOwn`, NOT a bare index-and-coalesce. `BATCH_NEEDS[ verb ] ?? null`
  // walks the PROTOTYPE CHAIN, so `holdingBatchNeeds( "toString" )` returns
  // `Object.prototype.toString` — a truthy value that then reads as a legal batch
  // verb, and whose `.status` is `undefined`. It would POST a transition with no
  // target status rather than refusing. Not reachable from the two buttons this
  // module serves today; reachable from any other caller, which is what an
  // exported function has to survive. Caught by a test asking for "toString"
  // BECAUSE it asked — the four ordinary unknown-verb cases all passed.
  return Object.hasOwn( BATCH_NEEDS, verb ) ? BATCH_NEEDS[ verb ] as HoldingBatchNeeds : null;
}

/**
 * The refusal a blank batch reason earns. Carbon copy of
 * notifications.js `_handleHoldingWontFixAllClick`.
 *
 * ⚠️ IT NAMES THE BLAST RADIUS, NOT JUST THE REQUIREMENT. "A reason is
 * required" is true and teaches nothing here: the operator is one press from
 * closing every row under a filer under a single justification, and the
 * sentence they are refused with is the last place that can say so.
 *
 * 🔴 THE CHECK IS CLIENT-SIDE BECAUSE THE SERVER'S IS PER ROW. The store
 * requires a non-blank reason on every `->wont_fix`, so posting a blank one
 * returns N identical 422s the operator must read one at a time to learn a
 * single fact. This is the one thing the client can say FASTER, which is the
 * only licence it has to pre-check anything.
 */
export const HOLDING_BATCH_BLANK_REASON =
  "A reason is required — it will be applied to every row in this group.";

/**
 * What a group with no eligible rows reports. Carbon copy of
 * notifications.js `_applyHoldingBatch`.
 *
 * ⚠️ IT IS NOT AN ERROR AND IT IS NOT SILENCE. A press that reaches zero rows
 * has to say so: silence reads as "it worked" on a pane whose whole job is rows
 * awaiting a decision, and an empty result and a broken one wearing one face is
 * the failure this pane's sentinels already exist to prevent one level up.
 */
export const HOLDING_BATCH_NO_ROWS = "No rows in this group.";

/**
 * The group status line WHILE a batch is running.
 *
 * 🔴 THE NUMBER COUNTS ATTEMPTS, NOT SUCCESSES, AND THE OPPOSITE CHOICE IS THE
 * TEMPTING ONE. Counting successes in flight leaves a wholly-refused batch
 * sitting at `Approved 0 of 8…` for the entire run — frozen, and frozen in a way
 * that looks exactly like the hang this line exists to rule out. The `…` marks
 * the line as in-flight; the final line drops it and resolves the two numbers
 * apart.
 *
 * ⚠️ A BATCH APPROVE IS UNBOUNDED IN TIME, WHICH IS WHY THIS LINE EXISTS AT ALL.
 * `not_approved → queued` IS the promotion, so with the approval gate enforcing,
 * every row of a batch approve asks Rick and waits out its own timeout. Eight
 * held rows can hold the pane for eight timeouts, and one static line painted
 * before that wait is indistinguishable from a dead pane.
 *
 * Ensures: returns `"<Past> <attempted> of <total>…"`, never a bare count.
 */
export function holdingBatchInFlightStatus( pastLabel: string, attempted: number, total: number ): string {
  return `${ pastLabel } ${ attempted } of ${ total }…`;
}

/**
 * The group status line AFTER every row has been attempted.
 *
 * 🔴 A PARTIAL FAILURE IS REPORTED AS A PARTIAL FAILURE. The obvious
 * implementation fires N requests, refreshes, and renders a shorter list — which
 * LOOKS like success. If two of eight were refused, those two are still on
 * screen and nothing says why, and the operator reads the shrunken list as "it
 * worked". So both counts are named, and the FIRST server message is kept
 * because that is the one carrying the actor and the allowlist on a 403.
 *
 * Requires:
 *   - ok + failed === total is the caller's invariant, not enforced here
 * Ensures:
 *   - no failures → `"<ok> of <total> <past-lowered>."` and nothing more
 *   - any failure → the same, plus the refused count and the first refusal
 */
export function holdingBatchFinalStatus(
  pastLabel  : string,
  ok         : number,
  failed     : number,
  total      : number,
  firstError : string | null,
): string {
  const head = `${ ok } of ${ total } ${ pastLabel.toLowerCase() }`;
  if ( failed === 0 ) return `${ head }.`;
  return `${ head } — ${ failed } refused. First refusal: ${ firstError }`;
}

/**
 * The extra body fields a batch verb's transition carries beyond `to_status`.
 *
 * ⚠️ ONE REASON, EVERY ROW — that is not a shortcut, it is the verb's meaning,
 * and the tooltip on the button says so to the operator before they press it.
 *
 * Ensures:
 *   - a verb that takes no reason contributes NO reason key at all (an empty
 *     `reason` posted alongside an approve is a field the server did not ask
 *     for, on the one verb whose whole point is that it needs nothing)
 *   - an unknown verb contributes nothing
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the exported function-declaration line — c8 reports ONE location for this "branch" where a real conditional carries two (verified against coverage-final.json: type=branch, counts=[0], single entry). Every internal branch IS exercised: `needs === null` both ways, and `needs.reason` both ways.
export function holdingBatchExtras( verb: string, reason: string ): Record<string, string> {
  const needs = holdingBatchNeeds( verb );
  if ( needs === null ) return {};
  return needs.reason ? { reason } : {};
}
