# R1 index check — yesterday's twelve commits vs the document at c3191337

**Reviewer 1 (Tiberius 👑), 2026-08-21.** Read-only.
**Document**: `src/rnd/v0.2.0/2026.08.20-brain-integration-cascade-review-plan.md`, worktree
`lupin-wt-brain-integration`, branch `wt-brain-integration-10ef4b64`, frozen at `c3191337`.

**Method**: pulled every added line of each commit, tested survival verbatim at HEAD, then read each
survivor in its current context. A line that vanished is not automatically drift — most were
superseded on purpose by a later split. Drift is where a point's *conclusion* is no longer correctly
represented somewhere in the document.

**Headline: 5 drifted, 7 held.** All twelve touch only the plan file; no code was written.

| # | commit | subject | verdict | why | plan ref |
|---|---|---|---|---|---|
| 1 | `c2e70ccb` | the reporting pin comes out, finding 2 closes by deletion | **DRIFTED** | Step 2b carries the ruling, but the "Reuse, do not rebuild" line still names `resolve_voice()` — the function this very ruling deletes. (R1 finding 1) | plan:172 vs step 2b |
| 2 | `717e11a6` | step 5 would have broken the live path; 6/7 were the wrong way round | HELD | The `:541` catch and the wire-first-remove-second order both survive; its old step 6/7 wording was superseded cleanly by the later split. | step 5, step 7 order note |
| 3 | `3d16f82d` | Rick's gist-tier ruling | HELD | Now step 6a; the ruling section is intact and correctly reordered behind 6-pre. | step 6a, gist ruling §  |
| 4 | `f014dd40` | the two cache stages are coupled | **DRIFTED** | The coupling point survives in step 7b, but its Files-table row still reads "in scope, not conditional" for `:953`, which `95792e74` later downgraded to open question 4. (R1 finding 6) | plan:169 vs step 7a |
| 5 | `95792e74` | split 6 and 7, name all eight parity values, the fast lane is dead | **DRIFTED ON ARRIVAL** | The split and the eight-value table hold. The same commit introduced the wrong observability tally ("three observable commits out of ten") and left standing the Files-table row it had just contradicted. (R1 findings 2, 6) | plan:272-274 |
| 6 | `9b0d9f4e` | Rick rules route-first | HELD | Its own flagged-open `router_error` question was correctly closed by `48c28a09`; the superseded caveat is gone on purpose. | route-first ruling § |
| 7 | `48c28a09` | router failure fails loudly, and the legacy-row count is 28 | **DRIFTED ON THE NUMBER** | The ruling holds and its "scope I am NOT assuming" caveat was correctly retired by `6897fe46` — but it measured **28** CRUD-backed snapshots and `c3191337` restates the same owed measurement as **27**. | plan:584, :599 vs :37-38 |
| 8 | `9eefec71` | the receptionist is the default, the fault that reached it is never spoken | HELD | Both gaps still stated; its "still not assumed" caveat correctly retired by `6897fe46`. | receptionist refinement § |
| 9 | `6897fe46` | Rick closes the open reading: the receptionist stays | HELD | Nothing of it was removed or contradicted. | CLOSED subsection |
| 10 | `47dc1ab4` | step 6 silently deletes user mode | HELD | Fully intact; it is open question 1 and correctly ranked above the cache guard. | plan:~420-470 |
| 11 | `b536973d` | mode routing is also the pump, and one part is unverified | HELD | Fully intact; it is the owed `created_date`/`run_date` measurement. | plan:~465-475 |
| 12 | `c3191337` | STOP — state recorded at 23:00 | **DRIFTED** | It is the authoritative STATE AT STOP and it uses three populations interchangeably, none reconciled: **28** CRUD-backed snapshots, **"the 27 rows"**, and **"27 blank-owner rows"**. | plan:29, :37-38, :599 |

## Live consequence of the 27/28 drift

The two owed measurements were dispatched this morning against **different-sized populations** —
reviewer 2 measuring 28 CRUD-backed snapshots, reviewer 3 measuring 27 `TodoListAgent` rows — because
the document states the same owed measurement twice with two different counts. Whether these are one
population (27 `TodoListAgent` + 1 other CRUD-backed) or two is never said. It needs one sentence in
STATE AT STOP naming the populations and their relationship, before either number is quoted again.

## New finding 13 — severity_proposed: inconsistency

**"No snapshot written without a valid `user_id`" is a settled ruling with no implementation home.**
It is listed twice in STATE AT STOP — at plan:46 as SETTLED, and at plan:50 as cleared-to-build —
and appears in **no step of the Sequence, no row of the Files table, and no line of Verification**.
Same family as the orphaned `snapshotable=False` fix (R1 finding 4). **Step 0** (the deprecated
snapshot-manager trap removal) is likewise absent from both the Sequence and the cleared list, though
the document argues at length that it must come first.

## What this pass did NOT check

Only the twelve commit subjects against the document. No code was read for this pass beyond what the
earlier lane work already covered, and no measurements were run.
