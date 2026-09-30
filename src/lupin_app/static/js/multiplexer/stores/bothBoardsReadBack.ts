/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// The post-verdict read-back of BOTH boards.
//
// 🔴 IT LIVES IN ITS OWN FILE BECAUSE `index.ts` IS NOT MEASURED. The TypeScript
// coverage gate excludes `**/index.ts` — correctly, since a barrel is re-exports — so
// logic written there carries no coverage obligation and no coverage report. This
// function started life inside `createStores`, where it was tested and still invisible
// to the 100% gate. Sam 🎙️ caught it (row 93ca4268). A barrel exclusion is the right
// rule; putting behaviour behind it is what makes the rule wrong.
//
// ⚠️ AND THE TEST WOULD NOT HAVE TOLD ANYONE. It passed either way. What the exclusion
// hides is not a red, it is the DENOMINATOR: a file absent from a scoped report reads
// exactly like a file at 100%.

/**
 * Re-read both boards after a verdict, awaiting BOTH to the end.
 *
 * ⚠️ NOT `Promise.all` (row 93ca4268, HARDENING — no read can reject today). `all`
 * settles on the FIRST rejection while the other board's read is still running — it is
 * never cancelled, its outcome is simply discarded — so one failed read would hide
 * whether the other board had caught up. The caller still needs to know something
 * failed, so the first rejection is re-raised once both are done;
 * `TaskRequestStore.submitVerdict` catches it and reports staleness rather than letting
 * it look like a verdict that did not land.
 *
 * Requires:
 *   - both arguments expose `refreshAfterWrite()` — the read that is guaranteed to have
 *     STARTED after the write, not merely to have finished after it
 *
 * Ensures:
 *   - both `refreshAfterWrite()` calls are awaited to completion, whatever either does
 *   - resolves when both succeeded; otherwise rejects with the FIRST rejection's reason
 */
/* c8 ignore next */ // tsx phantom-branch artifact on the exported function-declaration line. EVIDENCE, measured at b6008ed84 — the sha on this branch where this pragma does NOT yet exist, so the figures are reproducible there: branch 0 spans line 34 cols 22-41, the declaration IDENTIFIER, with hits [0], while the body below it ran 7 times. A branch guarding anything would have to have been taken for that to happen. HOW TO RE-DERIVE, because THIS PRAGMA HIDES ITS OWN EVIDENCE: with the ignore in place c8 omits the branch entirely, so the entry cited here is NOT in coverage-final.json and cannot be checked as the file stands. Delete this one line, re-run the tier under `c8 --reporter=json`, and read the branch entry at the declaration line. Restore the line afterwards. (The location COUNT discriminates nothing: all 640 branch entries under stores/ have exactly one, measured 2026-09-26 — Rachel's catch.) The one real conditional, line 39, is covered both ways at counts [12] and [3].
export async function bothBoardsReadBack(
  taskList    : { refreshAfterWrite(): Promise<void> },
  holdingArea : { refreshAfterWrite(): Promise<void> }
): Promise<void> {
  const settled = await Promise.allSettled( [ taskList.refreshAfterWrite(), holdingArea.refreshAfterWrite() ] );
  for ( const r of settled ) if ( r.status === "rejected" ) throw r.reason;
}
