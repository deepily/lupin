/**
 * The ONE task-list query string, shared by both task-list consumers.
 *
 * Two panels poll the same endpoint from two different bundles — the TypeScript
 * multiplexer (`stores/TaskListStore.ts`, esbuild) and the classic-script
 * notifications page (`notifications.js`). They carried the URL as two separate
 * literals and had already drifted (`char_budget=0` in one, absent in the
 * other), so a fix applied to one silently left the bug live in the other.
 * This module is the single source both read.
 *
 * Param rationale
 * ---------------
 * unscoped_audit=true — a DELIBERATE full-board sweep (the human's dashboard),
 *   so it takes the repository unscoped-size guard's documented escape rather
 *   than 400ing once the store passes the threshold.
 *
 * NO include_terminal — the panel shows work that is still OWED. Pulling
 *   done/dropped history was the under-reporting bug (2026-07-22, Rick):
 *   `include_terminal=true` inflated the result to 1,171 rows against a
 *   server-side `limit` hard-capped at 500, so 671 rows were dropped with no
 *   indicator — and because ordering is newest-first, the rows evicted were
 *   OPEN ones the renderer then could not display. Both call sites carried a
 *   comment promising the human's view was "never silently truncated"; it was
 *   truncated by 57%. Non-terminal alone measures 139 rows — comfortably under
 *   the cap, with room to grow.
 *
 * hide_parked=false — a parked row is deliberately not-now, NOT invisible. The
 *   server hides parked by default; agents calling task_query(include_parked=
 *   True) saw 30 rows the dashboard could not, which is the asymmetry that
 *   started this investigation. The renderer marks them; it does not drop them.
 *
 * char_budget=0 — explicit opt-out from the server's response BYTE budget
 *   (default 100k chars). That budget protects an AGENT from pulling ~97k
 *   tokens into a context; this poll is the human's dashboard, where a
 *   truncated board is the defect the budget would cause.
 *
 * SINGLE-SOURCE HOLDS AT AUTHORING TIME, NOT AT RUNTIME — say so plainly so the
 *   next reader does not file it as a bug. esbuild INLINES this constant into
 *   the multiplexer bundle, and the notifications page ALSO loads this file as a
 *   module. Two copies of the string therefore exist in a live browser. They
 *   cannot drift, because both are generated from this one line; the duplication
 *   Rick's ruling removed was two hand-maintained literals, which is a different
 *   thing entirely.
 *
 * NOT INCLUDED, DELIBERATELY: no `offset`. This poll is a single-page sweep, and
 *   the row cap is now guarded by a VISIBLE banner rather than by hoping the
 *   board stays small (see _renderTaskListTruncationBanner in notifications.js).
 *   Pagination was ruled out; noticing was not.
 */
export const TASK_LIST_QUERY = "/api/tasks?limit=500&unscoped_audit=true&hide_parked=false&char_budget=0";

/**
 * The HOLDING-AREA query — rows filed but not yet cleared to start.
 *
 * WHY IT IS A SECOND QUERY AND NOT A FLAG ON THE FIRST. `not_approved` sits in
 * the repository's `BOARD_INVISIBLE_STATUSES` denylist alongside the terminal
 * statuses, so the board query above cannot see these rows and MUST NOT — the
 * whole point of the gate is that unapproved work does not appear as live work.
 * The two panes are showing deliberately disjoint sets, so they ask deliberately
 * different questions.
 *
 * ⭐ `status=not_approved` IS WHAT MAKES THIS WORK, and it is not obvious from
 * the parameter name. `_apply_owed_filter` applies the invisible-status denylist
 * only `if not include_terminal and status is None` (task_repository.py:1029-1032),
 * so naming a status explicitly TAKES THE ROW OUT of the denylist's reach. There
 * is no `include_not_approved` flag to add and none was needed — asking for the
 * status by name is the documented door.
 *
 * NO `hide_parked` — a held row has never been on the board, so it has never been
 *   parked. The parameter would be answering a question that cannot arise here.
 *
 * NO `include_terminal` — a row that was won't-fixed out of the holding area is
 *   closed, and the triage list is for rows still awaiting a decision. This is the
 *   same reasoning the board query uses, applied to a smaller set.
 *
 * char_budget=0 — same rationale as above: this is the human's dashboard, where a
 *   silently truncated list is the defect the byte budget would cause.
 */
export const HOLDING_AREA_QUERY = "/api/tasks?limit=500&unscoped_audit=true&status=not_approved&char_budget=0";

// Publish for the classic-script consumer (notifications.js is not a module and
// cannot import). Read at CALL time there, never at load time, so module
// execution order cannot matter.
if ( typeof window !== "undefined" ) {
    window.LUPIN_TASK_LIST_QUERY   = TASK_LIST_QUERY;
    window.LUPIN_HOLDING_AREA_QUERY = HOLDING_AREA_QUERY;
}
