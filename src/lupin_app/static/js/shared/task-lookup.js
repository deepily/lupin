/**
 * Look up ONE ticket by the hash people actually paste — shared by both clients.
 *
 * WHY THIS EXISTS. Rick, 2026-09-09: *"Every time someone refers to a row for a
 * ticket by # I have no idea what they're talking about."* The fleet writes
 * 8-hex ids in every DM, every brief and every notification, and the only way
 * to turn one back into a ticket was to ask the person who sent it.
 *
 * 🟢 THE SERVER HALF ALREADY EXISTED AND NOBODY HAD TOLD HIM. `GET
 * /api/tasks/{ref}` (routers/tasks.py) has accepted a >= 4-hex prefix since row
 * f45b37a9, resolves it through `TaskRepository.find_by_id_prefix`, and — the
 * part that matters — applies NO board-visibility filter, so it finds
 * holding-area rows. Measured over HTTP 2026-09-09 by Mr. Radio 🦉: a prefix
 * resolved to a full row whose status is `not_approved`. This module is the
 * client half; no endpoint work was needed.
 *
 * ⚠️ DO NOT REBUILD THIS ON `GET /api/tasks?id_prefix=`. That is the BOARD
 * query and it chains `_apply_owed_filter` after the prefix match, so it hides
 * held rows. Measured against the holding area on 2026-09-09: of 23 rows, 15
 * carried no chase at all and 7 a future one, so exactly **1 of 23** was
 * findable that way. The two endpoints differ ON PURPOSE — one answers "show me
 * the board", this one answers "what is this hash" — and only the second is
 * right for a lookup.
 *
 * WHY A SHARED MODULE AND NOT TWO COPIES. `taskVerbs.ts` is the live receipt for
 * what one-sided delivery costs: the multiplexer's hand-written verb list is
 * missing `fixed` while the shared module ships it, so one client cannot offer a
 * verb the other can (row 507183ff). Rick's standing instruction is that every
 * facility lands on BOTH the notifications client and the multiplexer. This file
 * is the single source both read, in the same shape `task-list-query.js` and
 * `task-verbs.js` already use: an ES module for the esbuild bundle, published on
 * `window` for the classic-script page that cannot `import`.
 *
 * 🔴 THE CLASSIFIER IS A MIRROR OF A PYTHON FUNCTION, AND THAT IS A HAZARD.
 * `classifyTaskRef` below reimplements `task_store_rules.classify_task_ref` in a
 * second language. Two implementations of one matching rule with nothing
 * enforcing agreement is exactly the parallel-construction defect row f45b37a9
 * is itself about. The guard is
 * `src/tests/unit/shared/task_lookup.test.ts` — its first test reads
 * `MIN_TASK_REF_PREFIX_LEN` out of the Python source and reddens if the two
 * numbers drift. Named here so deleting the guard is a visible act.
 *
 * ⚠️ THIS POINTER WAS WRONG ON ARRIVAL and is the reason to distrust the genre.
 * It named `unit/multiplexer/task_lookup_matches_the_server_contract.test.ts`,
 * a file that has never existed — so the sentence promising that deleting the
 * guard would be VISIBLE was itself the thing hiding it. A cross-reference is
 * an assertion no test evaluates; the only fix that generalises is to keep them
 * few and check the ones you write.
 *
 * ⚠️ ONE KNOWN, DELIBERATE DIVERGENCE FROM THE SERVER, stated rather than left
 * to be discovered. Python's `uuid.UUID()` also accepts brace-wrapped
 * (`{...}`) and `urn:uuid:` spellings, which this module classifies INVALID.
 * Nobody pastes those out of a DM — the gesture this exists for is a copied
 * 8-hex token or a whole canonical UUID — and accepting a spelling the box will
 * never receive costs a branch that no test can honestly reach. If one ever
 * shows up, widen this and the guard together.
 */

export const MIN_TASK_REF_PREFIX_LEN = 4;

export const TASK_REF_FULL    = "full";
export const TASK_REF_PREFIX  = "prefix";
export const TASK_REF_INVALID = "invalid";

/** Canonical 8-4-4-4-12. */
const CANONICAL_UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
/** Exactly 32 hex, no hyphens — `uuid.UUID()` accepts this as a FULL id too. */
const COMPACT_UUID_LEN  = 32;
const HEX_ONLY_RE       = /^[0-9a-f]+$/;

/**
 * Classify a caller-supplied task reference. Pure — no fetch, no DOM.
 *
 * Mirrors `task_store_rules.classify_task_ref`, whose refusal is the one that
 * actually governs; this exists so the box can refuse junk WITHOUT a round trip
 * and tell the user why.
 *
 * 🔴 THE RETURN IS A DISCRIMINATED UNION ON PURPOSE. "`value` is null exactly
 * when `kind` is invalid" is an INVARIANT, and a comment saying so is a comment.
 * Spelling it as a union makes the checker narrow `value` to `string` the moment
 * a caller rules out the invalid arm — so `taskLookupPath` below needs no
 * defensive null check, and a future caller cannot forget one.
 *
 * @param {unknown} ref
 * @returns {{ kind: "full" | "prefix", value: string } | { kind: "invalid", value: null }}
 *
 * Requires:
 *   - `ref` is the raw user value. Any type: null, undefined and non-strings are
 *     classified INVALID rather than throwing — errors are data, not exceptions
 *
 * Ensures:
 *   - returns `{ kind, value }`, never null, never throws
 *   - a canonical UUID, or 32 bare hex chars -> `{ kind: "full", value: <lowercased, hyphens as typed> }`
 *   - >= MIN_TASK_REF_PREFIX_LEN hex chars, hyphens tolerated (that is what a
 *     partly-copied UUID looks like) -> `{ kind: "prefix", value: <lowercased, hyphens stripped> }`
 *   - anything else -> `{ kind: "invalid", value: null }`
 *   - lowercases, because the stored id renders lowercase and a match must not
 *     depend on how the caller happened to paste it
 *   - junk NEVER classifies as a prefix: a lookup built from arbitrary text is a
 *     search surface, which is a different feature with a different cost
 */
export function classifyTaskRef( ref ) {
    if ( typeof ref !== "string" ) return { kind: TASK_REF_INVALID, value: null };

    const candidate = ref.trim().toLowerCase();
    if ( !candidate ) return { kind: TASK_REF_INVALID, value: null };

    if ( CANONICAL_UUID_RE.test( candidate ) ) {
        return { kind: TASK_REF_FULL, value: candidate };
    }

    const compact = candidate.replace( /-/g, "" );
    if ( !HEX_ONLY_RE.test( compact ) ) {
        return { kind: TASK_REF_INVALID, value: null };
    }
    if ( compact.length === COMPACT_UUID_LEN ) {
        return { kind: TASK_REF_FULL, value: compact };
    }
    if ( compact.length >= MIN_TASK_REF_PREFIX_LEN ) {
        return { kind: TASK_REF_PREFIX, value: compact };
    }

    return { kind: TASK_REF_INVALID, value: null };
}

/**
 * Build the lookup URL for a reference, or null if it is not a reference.
 *
 * ⚠️ RETURNS null RATHER THAN A URL FOR JUNK, on purpose. The alternative is
 * letting the server 422 — which works, and spends a round trip plus a scary
 * error to say something the caller could have known before typing Enter.
 *
 * Requires:
 *   - `ref` is the raw user value (any type)
 *
 * Ensures:
 *   - a classifiable ref -> `"/api/tasks/<normalized>"`
 *   - anything else -> null
 *   - the path carries the NORMALIZED value, so two spellings of one id produce
 *     one URL and the server is never asked to re-derive what we already know
 *   - pure; never throws
 *
 * @param {unknown} ref
 * @returns {string | null}
 */
export function taskLookupPath( ref ) {
    const classified = classifyTaskRef( ref );
    // Narrowing, not defensiveness: ruling out the invalid arm is what makes
    // `value` a string below, so there is no null check to forget here.
    if ( classified.kind === TASK_REF_INVALID ) return null;
    return `/api/tasks/${ encodeURIComponent( classified.value ) }`;
}

/**
 * The sentence shown when a ref will not classify. One place, both clients.
 *
 * Ensures:
 *   - names the minimum length and that hyphens are fine, because "invalid" on
 *     its own leaves the user guessing which of the two rules they broke
 */
export function taskRefRefusalMessage() {
    return `Enter at least ${ MIN_TASK_REF_PREFIX_LEN } hex characters of a ticket id `
         + `(0-9, a-f). Hyphens are fine — paste as much of the id as you have.`;
}

/**
 * The sentence shown when the store answers 401. One place, both clients.
 *
 * 🔴 IT LIVES HERE BECAUSE IT ALREADY DRIFTED ONCE. The notifications client
 * shipped an `auth_required` arm and the multiplexer had none, so a signed-out
 * user was told "Lookup failed" on one client and "sign back in" on the other —
 * the same one-sided delivery `taskVerbs.ts` is the standing receipt for, found
 * in review 2026-09-09. Two clients agreeing that 401 is its own outcome is
 * only half the fix; if each composes its OWN wording they have merely drifted
 * more quietly.
 *
 * ⚠️ THE REMEDY IS THE USER'S, WHICH IS WHY THE WORDING MATTERS. A 401 is not a
 * fact about the ticket and not an outage. Say what happened and what to do.
 */
export const TASK_LOOKUP_AUTH_REQUIRED_MESSAGE = "Signed out — refresh the page to sign back in.";

/**
 * The sentence shown when the store did not answer at all. One place, both clients.
 *
 * 🔴 FOUND BY THE PARITY TEST ON ITS FIRST RUN, which is the argument for having
 * written it: on a 500 the notifications client said "The store did not answer.
 * Try again in a moment." and the multiplexer said "Lookup failed: HTTP 500".
 * Both had agreed the CONDITION was `unreachable` — they simply worded it
 * differently, so the old mention-test and even a state comparison would both
 * have passed. Nobody found this by reading the two files.
 *
 * ⚠️ THE SERVER'S OWN TEXT IS DELIBERATELY NOT PASSED THROUGH HERE, and this is
 * the one place that differs from the 422 arm. An ambiguous prefix's `detail`
 * NAMES the candidate ids and is the most useful thing on the screen; a 5xx's
 * message is "HTTP 500" or a stack fragment, which tells the reader nothing they
 * can act on and can leak internals onto a page. Say what to do instead.
 */
export const TASK_LOOKUP_UNREACHABLE_MESSAGE = "The store did not answer. Try again in a moment.";

// The classic-script bridge. notifications.js is not a module and cannot
// `import`, so publish on `window` and let it read at CALL time. Mirrors
// task-list-query.js and task-verbs.js exactly; see window-globals.d.ts for the
// declaration that keeps the .js typechecking under checkJs.
if ( typeof window !== "undefined" ) {
    window.LUPIN_CLASSIFY_TASK_REF        = classifyTaskRef;
    window.LUPIN_TASK_LOOKUP_PATH         = taskLookupPath;
    window.LUPIN_TASK_REF_REFUSAL_MESSAGE = taskRefRefusalMessage;
    window.LUPIN_MIN_TASK_REF_PREFIX_LEN  = MIN_TASK_REF_PREFIX_LEN;
    window.LUPIN_TASK_LOOKUP_AUTH_REQUIRED_MESSAGE = TASK_LOOKUP_AUTH_REQUIRED_MESSAGE;
    window.LUPIN_TASK_LOOKUP_UNREACHABLE_MESSAGE   = TASK_LOOKUP_UNREACHABLE_MESSAGE;
}
