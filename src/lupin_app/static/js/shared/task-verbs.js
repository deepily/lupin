/**
 * The ONE task-verb vocabulary, shared by every consumer that speaks it.
 *
 * WHY THIS MODULE EXISTS. The row's action control speaks FIVE verbs, and before
 * this file the vocabulary lived in FOUR separate tables inside notifications.js,
 * each keyed by the same five strings and each maintained by hand:
 *
 *     _verbNeeds            :10308   status / reason / date / placeholder / terminal
 *     _verbReasonComplaint  :12154   the per-verb blank-reason message (four entries)
 *     _verbLabel            :12169   the display label
 *     _taskActionsCell      :10105   the <option> list and its legality predicates
 *
 * They agreed. They agreed by COINCIDENCE, not by construction — the same shape
 * this repo has been bitten by repeatedly (`manager_refusal`'s own comment names
 * it; `authenticated_user_id` and `_resolve_project_from_bridge_cwd` are the same
 * disease). Four hand-kept copies of one list is four chances for a sixth verb to
 * land in three of them.
 *
 * 🔴 THIS IS THE ORACLE, AND IT IS DELIBERATELY NOT THE DOM. A test that reads the
 * expected verb set off the rendered page cannot notice a pane that STOPS rendering
 * a verb — it simply stops expecting it, and goes green on the exact defect it was
 * written to catch. The guard reads its EXPECTATION here and its OBSERVATION from
 * the DOM, and asserts observed ⊇ oracle per pane. Adding a verb below is therefore
 * what makes every pane get asked about it.
 *
 * ⚠️ THE STATUS VOCABULARY IS THE STORE'S, NOT THIS FILE'S. Every `status` and every
 * `legalFrom` entry here must exist in `task_store_rules.py`, and `park.legalFrom`
 * must equal its `PARK_LEGAL_FROM_STATUSES`. That is not left to care: a Python
 * guard reads this module and asserts it, so the two sides agree by construction.
 *
 * A module so the same file can be `import`ed by the TypeScript tier; it publishes
 * `window.LUPIN_TASK_VERB_SPECS` for the classic script, read at CALL time so module
 * execution order cannot matter. Same pattern as `task-list-query.js`.
 */

/**
 * One entry per verb the row control offers, in the order they are offered.
 *
 * Fields
 * ------
 * status      the store status this verb transitions the row TO
 * label       the display name, and the word a refusal is reported under
 * reason      whether a non-blank reason is required before any request is sent
 * date        whether a date input is required (injected by the verb-change handler)
 * dateLabel   the caption for that date input, "" when the verb takes no date
 * placeholder the reason box's placeholder — each verb states its OWN obligation
 * complaint   the blank-reason refusal message, null for a verb needing no reason
 * armsTwice   whether Submit ARMS on the first click and commits on the second
 *
 *             🔴 IT IS NOT "IS THE TARGET STATUS TERMINAL", THOUGH IT WAS CALLED
 *             `terminal` UNTIL 2026-09-04 AND THE TWO ARE NOT THE SAME SET. `drop`
 *             posts `dropped`, which the store lists as TERMINAL, and it commits on
 *             ONE click. Only `wont_fix` arms. So the old name asserted a store fact
 *             the field does not carry — and it fooled the first guard written
 *             against it into asserting the equivalence and going red on correct
 *             code. Named for the behaviour it drives.
 *
 *             ⚠️ WHETHER `drop` SHOULD ALSO ARM IS AN OPEN PRODUCT QUESTION, not an
 *             oversight to be quietly closed here. It is irreversible in the store
 *             exactly as won't-fix is. Rick's call; pinned as-is by
 *             `test_the_ui_verb_vocabulary_matches_the_store.py` so a change to the
 *             policy is visible rather than silent.
 * legalFrom   statuses this verb is offered FROM, or null for "any non-terminal"
 * illegalFrom statuses to subtract when legalFrom is null, or null for none
 * disabledWhy the greyed <option>'s own label suffix — an <option> has nowhere to
 *             hang a tooltip, so the explanation rides in the label itself
 */
export const TASK_VERB_SPECS = {
    park     : { status: "parked",       label: "Park",      reason: true,  date: true,
                 dateLabel  : "Chase me again on",
                 placeholder: "quote the sentence that decided this…",
                 complaint  : "A park reason is required — quote the row's own decisive sentence.",
                 armsTwice  : false,
                 legalFrom  : [ "queued", "in_progress" ], illegalFrom: null,
                 disabledWhy: "only from queued or in progress" },

    drop     : { status: "dropped",      label: "Drop",      reason: true,  date: false,
                 dateLabel  : "",
                 placeholder: "why this is being dropped…",
                 complaint  : "A drop reason is required.",
                 armsTwice  : false,
                 legalFrom  : null, illegalFrom: null,
                 disabledWhy: "" },

    demote   : { status: "not_approved", label: "Demote",    reason: true,  date: true,
                 dateLabel  : "Triage this by",
                 placeholder: "why this goes back to triage…",
                 complaint  : "A demote reason is required — say why this goes back to triage, or the next reader cannot tell it from a row that was never approved.",
                 armsTwice  : false,
                 legalFrom  : null, illegalFrom: [ "not_approved" ],
                 disabledWhy: "this row is already in the holding area" },

    wont_fix : { status: "wont_fix",     label: "Won't-fix", reason: true,  date: false,
                 dateLabel  : "",
                 placeholder: "why this will not be done…",
                 complaint  : "A won't-fix reason is required — a refusal carries its justification, exactly as a drop does.",
                 armsTwice  : true,
                 legalFrom  : null, illegalFrom: null,
                 disabledWhy: "" },

    // ⚠️ ADDED AT THE REBASE ONTO dcb8daa3, AND IT IS THE HALF THE MERGE WOULD HAVE
    // DROPPED SILENTLY. John landed `fixed` as a SIXTH verb in the inline TABLE this
    // module replaces; my side deletes that table and reads here instead. Take either
    // side of that conflict verbatim and you lose something: his, and the four hand-kept
    // copies come back; mine, and Rick's mark-as-fixed becomes a live <option> whose
    // lookup returns null — the row answers "Choose an action first" and the button
    // reads as dead. Both sides were right; neither was complete.
    //
    // 🔴 `reason: false` IS RICK'S RULING, NOT AN OVERSIGHT, and it is carried across
    // verbatim from john's table: he ruled his click IS the receipt — "I'm not waiting
    // around for you guys to do proper task list hygiene." Making him supply a sha or a
    // note was put to him and REJECTED as friction on the exact path he called too slow.
    // The attestation the server records is built in `_handleTaskSubmitClick`.
    //
    // `armsTwice: true` is his `terminal: true`, renamed to the field this module uses
    // for the behaviour rather than for a store fact: `done` is append-only, so a
    // misclick is not undoable, and it earns the same two-click arm won't-fix has.
    fixed    : { status: "done",         label: "Fixed",     reason: false, date: false,
                 dateLabel  : "",
                 placeholder: "Marking fixed needs no reason",
                 complaint  : null,
                 armsTwice  : true,
                 legalFrom  : null, illegalFrom: null,
                 disabledWhy: "" },

    approve  : { status: "queued",       label: "Approve",   reason: false, date: false,
                 dateLabel  : "",
                 placeholder: "Approve needs no reason",
                 complaint  : null,
                 armsTwice  : false,
                 legalFrom  : [ "not_approved" ], illegalFrom: null,
                 disabledWhy: "only a row in the holding area can be approved" }
};

/**
 * The verb names, in offer order.
 *
 * 🔴 DERIVED, NEVER RE-TYPED. A hand-written second list beside the table above is
 * the very defect this module exists to remove, one file lower down.
 */
export const TASK_VERBS = Object.keys( TASK_VERB_SPECS );

// Publish for the classic-script consumer (notifications.js is not a module and
// cannot import). Read at CALL time there, never at load time, so module
// execution order cannot matter.
if ( typeof window !== "undefined" ) {
    window.LUPIN_TASK_VERB_SPECS = TASK_VERB_SPECS;
    window.LUPIN_TASK_VERBS      = TASK_VERBS;
}
