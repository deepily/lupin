# TODO

## 📋 MORATORIUM BOOK 2026-08-30 (Mr. Radio 🦉 `93a8751c`, crew of five) — findings held OUT of the store per Rick's no-new-tickets order, and the 96% ratchet

**Rick's order, 10:12 EDT**: *"We're declaring a no new tickets moratorium for the entire day or until I lift the moratorium… workers, if you've got issues you're discovering along the way, you're going to have to surface that to your managers who will then track everything in the local to-do files, not the task list."* Everything below arrived by DM and is deliberately NOT a row.

**Rick's coverage ratchet, same sitting**: *"We are going to work towards 96% coverage, and every time we attain the new coverage level we're going to bump it up 1%."* Baseline **95.14%** at `f857bcbe`, measured by Tiberius 👑 against `fail_under = 92`, frame verified complete.

⚠️ **TWO THINGS THAT MOVE THE NUMBER THE WRONG WAY, both caught before anyone reported false progress:**
- **The approved rename ADDS 143 uncovered statements to the frame.** `probe-cc-bounded-billing-2026.05.12.py` → `probe_cc_bounded_billing.py` (Rick ruled yes, 10:11) makes a currently-invisible file visible **at 0%**. The denominator grows with no numerator. Krishna 🦚 is measuring the exact delta before we touch `fail_under`. **Do not bump the gate until the tier is genuinely above the new line** — ratcheting a gate we just made harder to pass is how a green becomes a lie.
- **`src/tests` is NOT in the coverage `source` list** (Rachel 🕊️). Test-file work is correctness, not coverage. Three rows closed this morning moved the percentage by exactly zero, and that is fine — but nobody should report a guard fix as progress toward 96.

### Findings banked, not filed

#### A documented rollback whose automated half NEVER WORKED (Chloé 🗼, banked by Mr Radio 🦉, 2026-08-30)

- [ ] 🔴 **`src/docs/auth/migration-guide.md` documents an auth-migration rollback, and the automated half of it has never once run.** `rollback_migration.py` imported `delete_user_by_email` from `cosa.rest.user_service`; `git log -S "def delete_user_by_email"` is **EMPTY repo-wide across all history**, so the function never existed and the script raised `ImportError` on load from the day it was written. Verified independently three times — Chloé, Tiberius, and me.
  **The script is deleted** (`c93785fb`, recovery command in the commit message). ⚠️ **That closed the smaller half.** Chloé's framing, kept verbatim because it is the right one: *deleting the script stopped it lying; it did not close the gap.* The guide still describes a rollback nobody can perform.
  **Two options were refused, and the refusals carry the decision content**: repointing it at `deactivate_user` would make a script named *rollback* silently soft-deactivate, which is worse than broken; and **adding a real hard-delete to `user_service` is NEW destructive capability against user records — Rick's call, not this crew's.**
  ⇒ **What needs ruling**: does the guide get its automated rollback built, or get rewritten to describe the manual procedure that actually exists?
  ⚠️ She asked me this twice before I answered. The delay was mine, and it was not a signal that the finding was minor.

#### A mutant can HANG instead of failing, and the fake that makes a loop testable is what causes it (Pocholo 📣, 2026-08-30)

- [ ] **The mutation section of CLAUDE.md lists three ways a harness lies. There is a fourth, measured today at `dcc503a8`: a mutant that produces neither a pass nor a fail.** Removing the `not batch` arm from `scan-prose-task-refs.py`'s paging loop made it spin forever; my fake served its last page indefinitely, so the suite ran until the OOM killer took it — **rc = −9**. Scored naively that is a non-zero exit, i.e. a KILL, which is exactly the over-report the existing rule warns about; scored honestly it is no verdict at all, and in a real tier it is worse than either because **a hang blocks the box while a red just reports.**
  ⚠️ **The cause is the fixture, not the code and not the assertions** — the same shape as the fourth reading already in CLAUDE.md. A fake that repeats its last response is what makes `has_more: true` with an empty page testable in the first place; it is also precisely what converts a broken loop guard into an infinite loop. **The property that makes the test possible is the property that makes it hang.**
  **Remedy, and it is one line**: cap the fake and raise. `if len( calls ) > MAX_PAGES: raise RanAway(...)` turns the runaway into a red, after which that mutation is KILLED by the test named for it (18/18 on these three files, verified applied by sha and accepting only `rc == 1`).
  ⇒ **Worth generalising**: any fake that serves a paging, polling or retry loop should cap itself. Not filed as a row per the moratorium — and it is a doctrine amendment to CLAUDE.md § mutation, not a bug, so it wants Rick's eye rather than a ticket.

#### Post-game open threads (Rachel 🕊️, 2026-08-30 — held per the moratorium, NOT rows)

Retro: `src/rnd/v0.2.1/2026.08.30-crew-day-post-game.md` §5. **These are owed as store rows the moment
Rick lifts the moratorium; nothing else about them changes.**

- [ ] 🔴 **Rio ⚡'s voided run has no receipt and nobody has re-run it.** 20 failures + 96% coverage were declared void after a raw purge. **There is no test-run id, Rio filed no deposit, and the claim exists only in a manager's memento.** Marked UNVERIFIED in the retro rather than repeated as fact. ⇒ Someone must re-run it; until then neither the 20 nor the 96% is a number anyone may quote.
- [ ] **Krishna 🦚 owes receipts** — asked WHICH race makes the e2e red a test race; unanswered. He also claims the idle-box refusal is already fixed and the venv path is fixture data. No deposit, no memento, so there is no written record of his reasoning at all.
- [x] ✅ **ANSWERED: it PREVENTS, it does not HEAL — and the remedy is a `/clear`, not a re-spin** (Pocholo 📣 measured 2026-08-30 ~21:30 EDT; **corrected by Mr Radio 🦉 within ten minutes**). `51950988`'s own message already said it prevents rather than heals — *"the eight erased seats stay erased until each restarts"* — so that half existed and had merely never been carried back to this list. **Measured: 9 of 11 live bridges carry `manager_figure_implicit`; 2 do not — María 🌸 and Tiffany 💍.**
  🔴 **MY FIRST WRITE-UP GOT THE REMEDY AND THE REASONING BOTH WRONG, AND MR RADIO'S OWN BRIDGE IS THE RECEIPT THAT KILLS THEM.** I wrote that the population "healed by RE-SPINS" and that the two stragglers "have not restarted since", inferring the second from bridge **mtime**:
  · **A `/clear` is enough.** Phase 4.6 stamps the field at every **SessionStart**, and `/clear` fires SessionStart. His persona was assigned **13:41 — before the 15:21 fix — and his bridge carries the field**, because he cleared at 17:39. No re-spin involved. Prescribing a re-spin for something a `/clear` fixes is an expensive remedy for a cheap problem.
  · **mtime cannot answer this question at all.** Re-read one minute later, **all three bridges showed mtime 17:41** — his stamped, the other two not. Their bridges are written continuously and an ordinary write does not add the field, so mtime is not the discriminator and the conclusion it supported was right for the wrong reason. **The discriminator is whether SessionStart has RE-RUN since 15:21.**
  ⇒ Nothing to build; the fix is correct and its scope was stated honestly in its own commit. **The last two close when María and Tiffany each `/clear`** — theirs to fire, not the manager's.
- [ ] **Maya 🌻 owes** — live-vs-dead per credential on `baac2474`. The Postgres password is the one that matters and it is still live.
- [ ] **Row `5246bb67` has `next_chase_ts: null`** — *"Epic keys rot because nothing enforces them at creation"*. Every other open row under this manager carries a chase. **A row with no chase is invisible to the chase loop** and survives only if a human happens to re-read the board.
- [ ] **Checked-hash drift is CONTINUOUS, not one-shot** (measured twice, minutes apart: **57** non-checked-hash at `25b4b36c`, **26** at `625665bb`, HEAD moving under the reading; top offenders in `lupin_mcp`). The conversion plus "remember to re-run it" is a rule, not a control. **This is the measurement open decision `f313fc2d` was waiting for.** I did NOT convert the tree — doing so while seats are mid-work is already in the manager's own error list.
- [ ] **Zero rolling deposits, second consecutive crew run** (0 of 6; mementos 4 of 4). Doctrine ranks the deposit ABOVE the memento and the fleet does the opposite, consistently. Two runs is a second data point, **not yet a pattern** — recorded rather than proposed as a doctrine change. A different crew deposited seven times the same calendar day, so the mechanism works and this crew did not use it.
- [x] ✅ **CLOSED, and my framing of it was wrong** — `post-game.md` §5.6's doc-viewer claim is **PER-REPO, not absent**. The `io/post-games/` prefix **EXISTS in planning-is-prompting** (`.docview.yml:26`, commented with a pointer back to §5.6); it does **not** exist in Lupin, whose manifest allows only `src/` plus named root files. I measured Lupin correctly and then reported it as a universal fact about the doc — the same error the crew-day retro catalogues, one frame out. Fixed at the source: §5.6 now states it per-repo, explains that a Lupin-filed retro is therefore terminal-read only, and gives the one-line check `grep -n 'io/post-games/' "$REPO/.docview.yml"`. Corrections also landed in the retro, the derivation doc and the corpus pointer.



- [ ] 🔴 **A COMMIT MESSAGE DESCRIBED THE BEHAVIOUR THE AUTHOR MEANT, NOT THE ONE HE SHIPPED** (Tiberius 👑, self-caught, 2026-08-30). `7ba8d630`'s message states *"a live pid whose comm cannot be read stays an offender, so unknown is not cleared."* **The code did the opposite.** The merge with Krishna's independent fix did not create the contradiction — it **exposed one already in the tree**. ⇒ The message is what a reviewer trusts, and one describing the INTENDED behaviour is **indistinguishable from one describing the SHIPPED behaviour** until somebody runs it. Worth more than the fail-open itself: the fail-open was findable, and this is the thing that would have stopped anyone looking.
- [ ] **My own coordination failure: two seats fixed one guard** (Mr Radio 🦉, 2026-08-30). Krishna `929b36f8` and Tiberius `7ba8d630`, independently, both correct. I assigned `17486970` to Tiberius and never told Krishna it was taken when he raised it. Cost: a merge conflict, a red tip, and a lost fail-closed property. ⇒ **The moratorium moved where visibility lives and I did not adjust.** A store row used to be what made a claim visible; with rows frozen, findings travel by DM and the manager becomes the only index. **Under a no-new-tickets rule the manager must BROADCAST an assignment, not merely record it.**
- [ ] **The contention guard's shape test can safely widen, once one predicate exists** (Tiberius 👑). `looks_like_pytest` requires an ABSOLUTE path, so real script-form (`.venv/bin/python3 .venv/bin/pytest`) and bare-console-script invocations read `shape=False` and go **unflagged**. **The gap does not reach production** — `resolve_venv_pytest` always yields an absolute path, so every sanctioned runner is caught; the failing fixtures were hand-typed relative forms, which he named as his own rather than banking the receipt. ⇒ The absolute-path rule existed only to stop a quoted command line matching, and the **comm gate now kills that class outright** (measured: a seat briefing quoting an absolute path reads `flagged=False` on comm alone). Shape test can widen to any path containing a slash. **Approved as the follow-on — after reconciliation, not on top of an unreconciled merge.**

- [ ] 🔴 **THE COVERAGE GATE CANNOT FAIL ON A RED TIER** (Tiberius 👑, found in the no-escape-hatch re-run; verified independently by Mr Radio 🦉, 2026-08-30). `src/tests/run-coverage-gate.sh --run-tiers` invokes both tiers with a bare `bash …` at lines 64 and 66 and captures **neither exit status**; line 25 sets `-o pipefail` but **not** `-e`, so a non-zero walks straight on to the report step. ⇒ **Every green this gate has reported since it landed means "coverage rendered above `fail_under`", NOT "the tests passed"** — and nothing in the output distinguishes the two. This is the gate the PR merge ritual stands on. Fix assigned to Tiberius: capture each status, fail and NAME the failing tier, and prove it with a positive control (force a tier non-zero, show the gate goes red) — because a gate that cannot fail is precisely the thing you cannot prove by watching it pass. ⚠️ It landed as a **post-terminal addendum on the already-closed `e2099400`**, which is not where anyone will look; that is why it is here.
- [ ] **A second file in the same directory did real work at module level** (Rachel 🕊️). `report.py` could not be imported either, for the same reason `loc_rollup.py` could not. **Two of three files in one directory** turns "a quirk of `loc_rollup`" into a question about `src/scripts` generally: what else runs `git log`, renders images, or writes into `io/` the moment it is imported? Nobody has swept for it.
- [ ] **The Stop hook's broad `except` is LOAD-BEARING, and nobody chose that deliberately** (Maya 🌻, surfaced as a deviation from Mr Radio's instruction; verified by Mr Radio 🦉, 2026-08-30). Told to *narrow the catch* on `e3dd1df2`, she narrowed its **meaning** — naming the failing phase — rather than restricting the `except`, and said so instead of quietly doing it. **Verified:** at `stop.py:~2524` the only `try`/`except` in that region wraps the settings parse and catches `ValueError`; `_arm_idle_waiter`, `_ask_anything_else` and `_announce_idle` all sit **outside** it. A raise from any of them escapes before `emit_json` ever runs ⇒ **the session's Stop goes unanswered and the seat hangs.** Narrowing the except would have converted a logged oddity into a dead session. ⇒ The structural fact worth acting on: **the broad `except` is the only thing standing between an unexpected exception and a hung session, because the call site has no guard of its own.** Adding guards there is a change to the liveness path — **Rick's call, not a drive-by**. Held for him.

- [ ] **The parity tool compares half of each file and reports PARITY OK on the rest** (Rio ⚡, measured). `MIN_BLOCK_CHARS = 120` skips **13 of 24** blocks in `plan-push.md` and **12 of 26** in `plan-loc-delta-global.md`. A one-line drift in any of those 25 blocks is invisible in both directions. Two further limits: run `doc_deploy_parity.py` **as it ships** and both pairs are red before *and* after his fix — the masking that produces a green is his, in a throwaway driver, and is exactly the extension María declined to build; and the pairs are not in `DEFAULT_PAIRS` with no `--pairs` flag, so **nobody can reproduce his receipt by running the tool**. ⇒ He demoted the parity run to *corroboration* and made a byte-level diff the load-bearing evidence. Sent to María 🌸 directly — the tool is hers, and Rick ruled 10:00 that planning-is-prompting owns the parity question. **A green under a masking the tool does not have is not the tool's green.**
- [ ] **Merge claims in mementos and amendments are wrong roughly half the time** (Krishna 🦚 offered the write-up; Mr Radio caught three instances before breakfast). `b12425ba` said "unmerged, awaiting cherry-pick" — already an ancestor. `ea53d354` said "not merged, not pushed" — already an ancestor. Last night's harvest found two more, in **both** directions. Every one was caught only by `git merge-base --is-ancestor`, which is one command. Write-up owed to Mr Radio, not to the store.
- [ ] **`test_manager_figure` finding** (Rachel 🕊️) — arrived by DM, held here.
- [ ] **A recheck step in the reap process** (Rachel 🕊️, found while fixing `48b5f19e`) — surfaced by DM, held here under the moratorium rather than filed. **Detail, now owed no longer**: a memento write verifies placement *within* a slot and cannot know **which door is about to arrive**. A REAP reads `io`; a SELF-RESPIN reads root. I read a context tick offering self-respin as the door, wrote `--slot root`, and **the write reported complete success** — record, mirror, pointer, sha verified, `resolve` exit 0. Every one of those checks was true and about the wrong door; Mr Radio was reaping me, and the reap would have seeded my successor from a 90-minute-old file while reporting success. ⇒ **The write side cannot know which reader is coming — the reaper can.** The recheck belongs at the reap, not in `memento_slot.py`. Caught by a human, not by any instrument.
- [ ] 🔴 **`memento_io.py verify` cannot answer "is this seat safe to reap"** (Rachel 🕊️, 2026-08-30, at Mr Radio's request). Write-up: `src/rnd/v0.2.1/2026.08.30-verify-exit-code-cannot-answer-the-reap-question.md` — **analysis + proposal, NOTHING BUILT.** ⚠️ **Opens by retracting the banked finding's stated cause**: the exit 1 is **not** the 71 orphan mirrors — `cmd_verify` never appends orphans to `findings` and its docstring argues correctly that it must not. Implementing the finding as banked would have shipped a no-op reported as a fix. **Measured 17:08:37 EDT**: exit 1 comes from **7 real findings** (6 `DRIFTED`, 1 `BARE-SLOT`) out of 529 records, 523 clean. **The defect is that a repo-wide verdict is the only verdict** — `verify` has no `--persona`, so a reaper must grep their own name out of a 547-file scan. **Receipt: 4 of the 7 findings are Mr Radio's own, one of them session `93a8751c`, live now** — he read that exit 1 three times today as somebody else's untidy archive. Proposal: `--persona` scoping findings + exit code, **exit 4 when the seat is not found** (the script's own precedent; a typo'd persona returning 0 is worse than the bug). Orphans stay non-fatal, gain **attribution** instead of a remedy. ⚠️ §4 argues against it: one afternoon, one reader, and a cheaper per-seat summary line may lose nothing.
- [ ] **A Lupin post-game with no reachable copy** (Rachel 🕊️, found while measuring both corpora, 2026-08-30 17:07:07 EDT). Lupin's `io/post-games/` holds 4 retros; three carry a `src/rnd` pointer and **`2026.07.27-crew-day-silence-post-game.md` (119 lines) does not.** With Lupin's `.docview.yml` correctly lacking the `io/post-games/` prefix (Mr Radio's ruling 17:05 — it stays out), that document is readable by nobody but a person standing on this machine: gitignored, unserved, unpointed. ⇒ Either land a `src/rnd` copy or a pointer. Flagged to Chloé 🗼, who owns the corpus doctrine.
- [ ] **The gate that was never written** (Pocholo 📣, on `54589356`) — he inherited a DM saying *"the queue is gated at :307 and :1846"*, grepped before building on it, and found every `answer_is_correct` reference in that file was a write, a report or a docstring. **Not one was a gate.** His count: *"the sixth of these on this epic, and the same cheap habit caught it each time."* ⇒ The habit — verify the premise before building on it — is the durable item, not the six instances.
- [ ] **A fixture cannot tell two calls apart when they are one object** (Rio ⚡, found by his own new tests on `debug_crud_llm_call.py`, 2026-08-30). The script builds ONE payload dict and **mutates it between its two calls**, so a mock recording arguments **by reference** made both recorded calls read `stream=True`. An assertion that the two calls DIFFER then failed **against correct code**. ⇒ Fixed by SNAPSHOTTING the payload at record time, never by weakening the assertion. **This is the fourth explanation from the mutation doctrine found in the wild** — the assertions were present, correct, and named for exactly the thing under test, and the fixture still could not discriminate. Generalises past his file: any mock that records mutable arguments by reference is asserting on the LAST state of the object, whatever its name says.
- [ ] **A file whose IMPORT was `:8000`-class work** (Rachel 🕊️, found on `src/scripts/loc-analysis/loc_rollup.py`, 2026-08-30). Everything from "View A" down was **module-level**: importing the file ran `git log` across every branch, rendered two PNGs, and wrote three files into `io/git-delta-analysis`. A persistent-state mutation **fired by an import** — so an import-and-smoke test was not available at any price, and the file could not be covered without a code change. Fixed by moving the block into `main()` behind a `__main__` guard and returning its two series so tests assert on the numbers. Verified after merge: import from a clean interpreter, `io/git-delta-analysis` 5 entries before and 5 after. ⇒ **The blast radius was zero only because nothing imported it.** Any tier that ever touched that file would have run it, on whatever box happened to be running. Worth a sweep: what else in `src/scripts` does real work at module level? Nobody has asked.
- [ ] **Three more `debug/` one-shots still at flat 0%**, surfaced while verifying Rio's merge: `debug_queue_endpoint.py` (32 stmt / 4 br), `debug_queue_state_monitoring.py` (84 / 16), `debug_websocket_connection.py` (36 / 4) — ~176 statements. Assigned to Rio, same pattern and harness. Not a row; tracked here.
- [ ] **`src/lib` is untracked but NOT ignore-matched** (Pocholo 📣, correcting Mr Radio). `git check-ignore src/lib` → false; `git status --ignored` prints `!!` only because every file beneath it is a `.pyc`. A directory-level rollup, not a rule match. ⇒ A "disk minus ignored paths" fix would **not** have excluded it, which is why the collision guard's pool is now `git ls-files`. Recorded because the wrong reading is the natural one.

### Closed with receipts this morning (4)

| row | receipt | verified how |
|---|---|---|
| `f2f7b0cd` lupin-mobile is a sibling now | `b0548518` | 200 + 13,971 bytes of the real README through the doc viewer; container resolves the new path |
| `c89cec9b` shadowing guard reads git, not the checkout | `17d5bae2` | re-ran in the MAIN tree, 9 passed, `lib` **not** added to the declared list |
| `a8222a71` canary stops taking a filename hostage | `9af5ac03` | merged `--no-ff`, 15 passed in the main tree |
| `8593bf65` six passages, not two | `d6910d27` | byte-level diff against canonical |

**Rulings obtained from Rick this morning**, all genuine keypresses, none defaults: Option B on `src/scripts` (`c89cec9b`) · edit the live global config + keep both copies in sync (`3a6d9505`) · build the parity check, **p-is-p owns it** (`dacac717`) · checked-hash `.pyc` invalidation repo-wide (`866f43ce`) · rename the dated probe with no date at all (`9078a035`).

⚠️ **`866f43ce` carried a `[default used] no` from an earlier timed-out ask.** Rick's keypress is the opposite answer. Both are on the row and labelled — a row with two contradictory answers and no provenance is worse than a row with none.

## 📨 FINDING 2026-08-30 (Clayton 😎 `1bfda44e`, with Chloé 🗼) — THE CONDENSER FIX **IS** LANDED, AND IT CANNOT SEE ANY OF TONIGHT'S FOUR INVERSIONS

**Verified, because a DM said the opposite.** A condensed DM reported *"the condenser fix is not
committed anywhere and needs to be landed."* It is committed: `_retracted_assertions` lives at
`src/cosa/rest/routers/dm.py:1554`, is **wired into the guard chain at line 2015**, landed at
`349aa8ba`, working tree clean, and `src/tests/unit/test_dm_tutor_send_path.py` is **111 passed**.
The message claiming the condenser fix was missing was itself produced by the condenser.

**What is NOT landed is a guard for the class that is actually firing.** §4's guard keys on
**retraction markers**, and per Chloé's §7 at `bef61718` **not one of tonight's four inversions is
a retraction** — they are a recommendation, a state report, a measurement, and a merge note. The
guard is correct and it is aimed at a case that did not recur.

⚠️ **The dangerous direction is the one that produces a green build.** Inversion #1 told a seat to
**delete** the `site-packages` clause — a live guard over the ~29,000 vendored files in
`src/cosa/.venv` — because doing so *"keeps all tests green."* It does keep them green; that is
exactly why the mutation survived. A seat that complied would have shipped a passing suite, a
removed guard, and **no artifact anywhere recording that a guard was removed.** An inverted
retraction reads as odd; an inverted **recommendation** reads as ordinary technical advice.

🔴 **The only remedy currently proposed is a HABIT — "open the path before acting on the DM" — and
this fleet'"'"'s own doctrine is that a habit is not a control.** §4 makes that point about itself.
Four inversions in one evening, three of them mine, and what caught every one was a human opening
the artifact. That worked tonight and is not a mechanism.

⇒ **Open question for Rick / Mr. Radio, deliberately NOT a store row under the moratorium**: does
the non-retraction inversion class get a detector, or do we accept the habit and say so plainly?
A third option is cheaper than either: **put the verdict in the path, not the prose** — the prose
is the part that gets rewritten, and every one of the four had its corrective evidence one file
open away.

**Receipts**: guard `349aa8ba` · four inversions and the `262fc37cb0ae` measurement in
`src/rnd/v0.2.1/2026.08.30-dm-condenser-inverts-retractions.md` §7 · mutation run
`src/rnd/v0.2.1/2026.08.30-independent-mutation-run-chloe-four.md`.

⚠️ **One correction that cannot be made where it belongs**: merge subject `199d9aca` says the
sixth finding was *"refuted with a fixture."* It was not — `limit=1` → `limit=2` (`262fc37cb0ae`)
is an equivalent mutant with deliberately no test, and it **survives deterministically at that
very tip**, measured twice by me and once by Chloé. A merge subject cannot be rewritten once in
history, so the correction lives here and in §7.

## 🌿 TONIGHT 2026-08-21 (Cheech 🌿 `5c04b97c`, nine re-spins; crew Krishna · Rachel · Pocholo · maya) — brain integration BUILT: `/api/v2 ask|submit`, ten doors retired, three tiers green at `8657cfa9`

**Landed** on `wt-brain-integration-10ef4b64` (tip `7c00c787`, pushed): steps 1–9b, all ten doors (each deletes its own accordion card — Rick 20:44; Re-render button stays), door 8 voice→ask, step 12, class delete 7a20a09d, Mr Radio's B/C/D. Gate ts-6eaebff8 @888754f1 = no code regression; final tiers @8657cfa9 unit 16,876/0 · cosa 8,622/0 · guard 2/0 (María reproduced). Plan: `src/rnd/v0.2.0/2026.08.20-brain-integration-cascade-review-plan.md` § "Manager rulings after the 11:43 re-spin" (end-of-night fold).

**Pending decision (Rick) — `83fe98aa`, chase 10:00 EDT**: (1) merge integration → wip now (recommended); (2) close B0(iii) window + Rachel reverts the UNCOMMITTED probe patch on the main checkout (`running_fifo_queue.py`, `todo_fifo_queue.py`, `_unreachability_probe.py`) — REQUIRED before the wip merge because 7c deleted `push_job`'s body. Four asks 20:52–21:29 timed out. Bounce `:7999` + push remain his word.

**Tomorrow's order**: re-ask → revert + 0d4bc1ff closes → merge into wip → next `:8000` gate at that head (everything since 888754f1 rides it; maya rig, idle check §1a, E2E + integration, diff vs ts-6eaebff8) → bounce + push on Rick's word → step 13 (1e597a65, maya dry-run, Cheech GO) → María d212f54b eval → Mr Radio cdfedc41 (1447261b) → María's rename branch.

**Follow-ups — ✅ ALL SIX DISPOSED OF, Rick's sprint-close walkthrough with María 🌸, 2026-08-22 ~11:40 EDT.** Every ruling below is a genuine keypress, not a timeout default. The no-new-bug-rows order of 08-21 was lifted for these specifically.

- [x] **Order-effect unit reds** → **PROMOTED, row `ece4d86a`** (P2, Cheech). One row for all four, his choice over splitting or dropping. Carries the two-line fix for the diagnosed one *and* the finding that generalises: the arbiter-loop file does real bridge IO and carries **zero** `serial_bridge_guard` markers.
- [x] **`self_respin` lost its wake** → **PROMOTED, row `b0570b67`** (P1, Cheech) — but **reframed on his ruling**: *add a wake check*, do NOT chase the root cause. The row says so in its first line so nobody spends a day reproducing an intermittent spawn-path drop. It fails in the worst direction — the seat looks idle, not broken.
- [x] **Gate rig / gitignored state** → **DONE, no row.** Was already half-written: §0b of `RIG-PROCEDURE.md` covered `src/conf/keys` with its evidence (17 of 25 integration failures). Topped up with the terraform provider cache, `cloud-run.env`, the eleven failing test names, and the checkable-name rule. ⚠️ **`io/brain-integration-gate/` is git-ignored, so that procedure is not in version control** — flagged, not fixed.
- [x] **The three-part bundle** → **SPLIT.** (a) Pocholo's sweep → **row `e3f59977`** (P2, Cheech), with an explicit warning not to close it by deleting tests to move a number. (b) Mock-job door → **DROPPED as already-decided** — held deliberately with the two resume-from doors; `mock_job.py:170` constructs directly with no registry command. (c) `test_data_types_and_exceptions.py` self-skip → **noted in the file itself**, not tracked: 7 tests have never run, and "skipped" reads as deliberate when it is not.
- [x] **cosa collected 8,647 vs ran 8,648** → **DROPPED UNCHASED, and recorded as unchased** rather than left to fade. One test in eight and a half thousand, never produced a wrong verdict, and re-measuring needs a fresh collect *and* a fresh run on a box that is contended today.
- [x] **Three concurrent tiers contend** → **COALESCED into `ece4d86a`** — same defect as item 1 seen from the other end. The marker already exists (`pytest.ini:60`), is already deselected by default (`pytest.ini:82`), and five files already carry it. The work is applying it, not inventing it.

## ☕ TONIGHT 2026-08-21 (Mr. Radio 🦉 `e9a672a2`, crew of six) — four branches landed, board to zero; follow-ups kept OUT of the store per Rick's no-new-BUG-rows order

**Landed**: A router-label-fix → wip `decae6c7` (0 corpus lines move; rule doc + `router_label_audit.py` + lint test) · B claude-code v2 submit → integration `1c319db0` · C expeditor per-call state → `24c3b3ba` · D xfail-blanket strip → `af9f557d` (and fixed dead Replay on done jobs). Rows 0795b5d8 · 14172091 · 10c60712 · 82fb9fcb · 25ff8360 closed with receipts.

**Follow-ups (backlog, not rows — promote when Rick lifts the ban)**:
- [ ] Regenerate FastAPI docs (`generate-api-docs.sh` → `api.json`/`api.md`) after the next `:7999` bounce picks up B's 410 doors — needs a live server (Rio's doc `src/rnd/v0.2.0/2026.08.21-claude-code-doors-external-callers.md`).
- [ ] lupin-mobile's one claude-code submit call site now answers 410 — owed in the mobile repo (same doc).
- [ ] `NotificationsHeaderRenderer.ts` TS coverage 99.31 stmts / 92.94 branch (lines 394, 424-425) fails the enforced 100% gate; pre-existing, proven by Chloé's c8 baseline at f4a8bee4 — owner of the renderer.
- [ ] Pre-existing reds at the integration head: `test_no_router_in_the_tree_is_unmatched` (Rachel, door 10) + two podcast dry-run tests; maya's full unit at `1c319db0` is the count of record (Cheech).
- [ ] `notifications.js:6187-6193` inert bare `${queueName}_jobs` fallback — two-line deletion for whoever is next in that region (Sam).
- [ ] Two order-effect reds in whole-run unit tiers (presentation dry-run banner, v2 cache lancedb closure) pass alone — worth a fixture look (Tiberius).
- [ ] Tooling: `git merge-tree --write-tree` is NOT in this git — use `git merge-tree $(git merge-base A B) A B | grep -c '^<<<<<<<'` for conflict checks (cost one false "both conflict" ruling tonight).

**Mine, still open in the store**: 1e597a65 (step-13 dump, Cheech's GO after 9a/9b) · cdfedc41 (brake-flag protocol member, 1447261b, Cheech's 10:00 EDT window, María PASS). Memento: `src/rnd/v0.2.0/_archive/D/2026.08.21-mr-radio-cascade-resume-memento.md`.

## ⚖️ RULED 2026-08-21 morning (Rick, to María 🌸 `e5933e98`) — brain integration: three questions closed, one scope added

Plan `src/rnd/v0.2.0/2026.08.20-brain-integration-cascade-review-plan.md`, folded at `16c6dc2b`. **Nothing built.**

1. **User mode STAYS; the queue resolves it first.** *"Per your recommendation we're going to keep it because the queue resolves mode first."* `push_job` keeps `get_user_mode` and both maps and hands `AskFlow` a resolved command — **the flow never learns about modes.** Ruled after two facts read from source: the mode state is a per-user dict keyed on `current_user["uid"]` at **both** ends (`todo_fifo_queue.py:230`, `queues.py:241`/`:1606`), so it is **not** a global flag; and every one of the 15 mode targets is already `speakable`, so mode adds **stickiness, not reach**.
2. **Guard BOTH cache ends** — *"the read at the head end of the process, and the write after the agent executes."* ⚠️ The correctness prompt he named (`running_fifo_queue.py:1751`) is **asynchronous and times out to unverified**, so the row is written before the answer arrives: `answer_is_correct` is the **read** guard's field (fails CLOSED); the **write** guard keys on whether the **router chose** the agent.
3. **The whole snapshot cache is DUMPED after the refactor** — *"we don't need to deal with any old bullshit that we have to try to figure out why."* ⇒ the 28-row question **dissolves**, and the measurements owed against it are **no longer owed**. The guards are **not** optional because of it — a fresh cache re-poisons itself without them, and refills ownerless unless the `user_id` fix is scheduled.
4. **NEW SCOPE — one canonical entry point, the v2 one.** *"I don't want a Q&A entry point along with an ask entry point along with a specific kind of task queuing mechanism."* **Seven HTTP doors exist today across three mechanisms**; **two bypass `push_job` entirely** (`queues.py:1829`, `:1932`), so the read guard ruled above **does not reach them**. No step written yet.

**Corrected in my own text, twice**: the 27 bad rows were **not** written by mode — they came from v2's `_maybe_write_back` (`flow.py:291`), which has **no CRUD exclusion**.

**And my correction itself needed correcting** (Krishna, reconciled): `TodoCrudAgent`/`CalendarCrudAgent` **are** subclasses, so `isinstance` catches *them* — but the 28 rows carry **`TodoListAgent` (27) and `CalendaringAgent` (1)**, which are **siblings** and sail straight through that check. ⇒ **v1 is protected by ROUTING, not by the class test**: the CRUD fork means a todo question builds a CRUD subclass in the first place. Both statements were true about different classes, and only the reconciled one is useful.

**Still unruled**: does dead `_process_fast_lane` go with its seven tests · what becomes of the other six doors.

**Own rows, found while checking and not folded into this plan**: `dead_queue_watchdog.py:396` re-pushes with `getattr( failed_job, "user_id", "" )` — an empty-key fallback shared by every job that lost its user · `speech.py:338` calls `push_job` with **one of four required arguments**, so that path is dead or raises every time; undetermined which.

---
## 🕳️ PATTERN 2026-08-20 (Tiberius 👑, recorded by Mr. Radio 🦉 `f60b686e`) — AN INSTRUMENT THAT ERASES ITS OWN WITNESS: three sightings in one night, so design against it rather than fix it three times

**The general form**: *a measurement whose population excludes failures cannot report failure.* Each sighting below looked healthy — that is the whole problem. None of the three announced anything; a person noticed the number was wrong.

### The three, tonight

| # | instrument | how it erased its witness |
|---|---|---|
| 1 | the v1/v2 scorer | booked correct v1 behaviour as failure — same 20 utterances scored **20/20 for v2, 0/20 for v1**, both arms behaving correctly |
| 2 | `render_paired_report` | emitted provenance and a **bare delta** — a median over whichever utterances survived would have read as a verdict on the whole corpus (`5dfe0d43` ruled otherwise; never implemented until `0b3a08f2`) |
| 3 | the four route-error rates | computed over the **`ok` set**, and `is_completed_ok` moved errored records *out* of `ok` — so all four went **structurally zero at the exact moment they mattered**. `replay_failure_rate` read `0.0` while 42% of warm responses were failing |

Adjacent sightings from the same week, same shape: a websocket suite reporting green over **4 of ~50** tests; `/health` answering 200 while every embed returned nothing; `n=49` from a pairing that compared nothing.

### The design rule this argues for

**Before trusting a rate, ask what its denominator excludes.** If the excluded set is where the failures go, the rate is structurally incapable of reporting them — and it will report `0.0`, which reads as good news. A zero from a healthy system and a zero from an erased denominator are indistinguishable at the point of reading.

⇒ Concretely: **an error rate must be computed over every ANSWERED request, never over the successful subset.** That is the fix Tiberius applied — with the control that proves it (dirty case red on the old code and `0.42` on the new; clean case denominators coincide exactly, so nothing that reported correctly changes).

⚠️ **Demanding the receipt is what found the second layer.** He had a working fix for the one metric and would have shipped it; being asked to *prove* "nothing that reported correctly changes" surfaced that the cache views legitimately want the ok-gated denominator and the error views do not. **The proof was not a formality — it was the thing that found the rest of the defect.**

### Not yet owed
No row, per the standing no-new-rows order. The candidate work is a sweep for other rates computed over a success-filtered population, and a test convention that pins each rate's denominator explicitly.


## 🔁 BACKLOG 2026-08-20 (Chloé 🗼, handed back to Mr. Radio 🦉 `f60b686e`) — six hand-rolled retry loops now have a shared helper to move onto, and two of them must not be moved blind

**Not owed yet — no row, per Rick's no-new-rows order. This is the hand-back so it does not evaporate with the seat.**

The shared helper exists and is in use: `src/cosa/utils/bounded_retry.py` (sync `retry_call` + async `retry_call_async`, attempt count, wall-clock deadline, exponential backoff, exception filtering, optional predicate, `on_retry` hook, retry-on-returned-value). Landed at **`8fab39fe`** with 100% lines AND branches, first caller `search_kagi.py:search_fastgpt()`. Full unit sweep after it: **16,065 passed, 0 failed**.

**Why the helper was worth building at all**: there was no shared retry helper and no retry library in the tree — no `tenacity`, no `backoff` in any requirements file — and six independent loops had each solved it again.

### The six candidates, per-loop risk in the writeup
`src/rnd/v0.2.0/2026.08.20-bounded-retry-helper-and-migration-candidates.md`

⚠️ **Two must be read before they are touched** — Chloé's call, and it is the reason this is a backlog note rather than a mechanical sweep:

| loop | why it is not mechanical |
|---|---|
| `agents/dm_quality_judge/` (`judge.py`, `judge_v2.py`) | the prompt **changes between attempts** to break a degenerate mode — a generic retry that replays the same call defeats the point of retrying |
| `memory/embedding_provider.py` | the exception **types** drive whether the caller retries by shrinking the batch (bug `13b35b37`) — a helper that normalises or swallows the type breaks the caller's decision |

The other four (`podcast_generator/tts_client.py`, `notification_proxy/verification.py`, `memory/speech_to_text_provider.py`, `rest/db/auto_migrate.py`) look closer to mechanical, but `auto_migrate` is deadline-shaped and was the model the helper was built from, so it may be better left as the reference.

**Anyone taking this**: migrate one loop per commit with its own tests, never a sweep. The fence on the original row existed because a P3 that grows into a six-file refactor stops being reviewable.


## 🐢 FINDING 2026-08-20 (Mr. Radio 🦉 `f60b686e`, at Rick's request) — v2's CACHE NEVER HITS: the synonym row points at a snapshot id that does not exist

**Rick asked where v2's latency lives, and guessed a blocking embed plus a slow DB write. Both measured, both cheap.** Analysis only — **nothing was changed.**

### Where the time actually goes (median per phase, 191 traces)

| Phase | todo | math | calculator |
|---|---:|---:|---:|
| router | 22 ms | 23 ms | 22 ms |
| agent invoked | 831 ms | 901 ms | 807 ms |
| **first useful output** | **62,217 ms** | **9,222 ms** | **3,126 ms** |
| writeback complete | 62,930 ms | 9,435 ms | 3,235 ms |

**Embedding 1.6 ms · ANN 1.7 ms · exact lookup 11.9 ms · DB write-back 110–710 ms.** ⇒ **~100% of the time is agent execution**, before anything is written anywhere.

### The reason the agent runs at all: the cache never hits

**0 cache hits in 193 requests, including 93 warm-pass repeats.** Cold median 8,520 ms, warm median 8,473 ms — **the warm pass buys nothing**. 59 of 74 ANN lookups scored **exactly 100.0** and none replayed (by design, `flow.py:95` — only a tier-1 exact match replays). Tier 1b `exact_normalized`, the *designated* warm-pass replay signal, fired **0** times.

### 🔴 THE MECHANISM — GHOST POINTERS (Tiberius's diagnosis; mine below was WRONG)

**The clean step truncates `solution_snapshots` and leaves `canonical_synonyms` standing.** So every run begins holding *prior runs'* synonym rows pointing at snapshot rows that no longer exist. Tier 1 matches a ghost by verbatim text, dereferences it to nothing, and reports a **miss**.

⇒ **That explains both halves of the signature at once**: a **0% hit rate** against a **65% candidate rate** is what a lookup looks like when it *finds* something and then dereferences to nothing. Receipt from `lupin_db_test` after `ts-23613e7d`: **124 snapshots, 1,021 v2-written synonyms, 897 dangling**, and every synonym matching a live question resolved to a ghost.

**Fix**: both clean steps now empty the two tables in one statement, with tests that go red on the old code.

**⚠️ MY DIAGNOSIS BELOW WAS WRONG AND THE ERROR IS INSTRUCTIVE.** I compared a synonym row against a snapshot for the same question *text* and concluded write-back computed two different ids. **They came from different GENERATIONS** — the synonym survived an earlier run, the snapshot was written by this one. Same question, different run, different row; the ids disagree for a reason that has nothing to do with the write path. **I asserted a mechanism from two values without checking they were contemporaries.** An id bug explains neither half of the signature; ghost pointers explain both. Kept below as the record of a tested-and-failed hypothesis, not deleted.

### ~~The mechanism — two different ids for the same question~~ (WITHDRAWN, see above)

Queried `lupin_db_test` (the isolated store the run actually writes; **my first query hit `lupin_db_dev` and returned a misleading 0/25 — the wrong-database mistake, caught before it was claimed**):

| Check | Result |
|---|---|
| Tonight's repeated questions with a `canonical_synonyms` row | **23 / 25** |
| Same questions present in `solution_snapshots` (by text) | **23 / 25** |
| Same questions whose synonym `snapshot_id` **resolves** to a snapshot | **0 / 25** |
| Synonym rows store-wide whose `snapshot_id` does not resolve | **924 / 1,048** |

For `'update the priority of paint bedroom on my task list'`:
- `canonical_synonyms.snapshot_id` = `44933b7331defafcb145f6f61e7907d38b666b40da67a4bd47ddea25f2cbd4a2`
- `solution_snapshots.id_hash` for that same question = `0958b48a7435b70834def2de787ca0ce93aae95f8ed2c795c83d40ad9502…`

⇒ **Write-back stores the snapshot under one id and the synonym under a different one.** The exact tier finds the synonym, follows the pointer, finds nothing, falls through to ANN — which by design never replays — so **the full agent runs on every repeat**, and a duplicate snapshot is written (57 of 59 perfect-similarity records did exactly that).

### ⚠️ THIS PARTLY REVERSES TONIGHT'S HEADLINE

If v1's warm pass replays from a working cache (~3.5 s) while v2 re-runs the full agent every time, then the measured **"v1 is 3.9× faster" is largely cached-vs-uncached, not architecture** — the benchmark compared **v1-with-a-working-cache against v2-with-a-broken-one**. The comparison may be **understating** v2 substantially.

### ✅ FIXED AND PROVEN LIVE — then Rick ordered the cache fixed BEFORE the rerun

**Rick's ruling ~21:12** (four-option ask, answered, not a default): *"Fix the cache first, then rerun."* He had ordered the rerun an hour earlier, before either of us knew the cache was dead; shown the new evidence, he changed the order. The submit was held ~10 minutes while he decided.

**Live two-call proof on `:8000`, after running the real guarded clean step** — not a unit test:

| | |
|---|---|
| Call 1 — agent path, no hit | **11,148 ms** |
| Call 2 — replay path, `cache_hit` true, similarity 100.0 | **24.6 ms** |
| Ratio | **~450×** |

Store finished with 1 snapshot, 1 synonym, **0 dangling**; the clean step cleared all 1,048 real synonyms including the 924 ghosts. ⚠️ **Held loosely: one utterance, one pair — a mechanism demonstration, not a distribution.**

**Blast-radius check before commit** (asked, because a helper that empties a table gets reused somewhere it shouldn't six months later): both truncate functions live in `src/scripts`, no application module imports them, and each **refuses unless the EXECUTING connection's own database name** is exactly `lupin_db_test` or `lupin_db_v1baseline` — frozenset equality, not substring, read off the live connection so a passed argument cannot lie about the target. Only the table list inside that already-guarded statement was widened.

### 🔄 AND THIS REVERSES THE STANDING HEADLINE

**"v1 is 3.9× faster" was measured against a v2 whose cache could not hit once** — it was never a comparison of the two designs. With v1 replaying warm in ~3,500 ms and v2 in tens of milliseconds, the aligned rerun may land the opposite way. **Nobody should quote the old number as though it still stands.**

**In flight**: `ts-e0311090`, n=20, submitted 21:26 — the first run tonight with **aligned scorers AND a working cache**. Gate cleared properly: unit suite **16,003 passed / 0 failed, exit code 0 read directly rather than through a pipe**; six fixes at `4ec69f42`; `:8000` verified idle; n=20 confirmed in compose *and* the container's own env. Rick confirmed he is keeping the box up past the ~23:00 landing.


## ⚖️ RULED 2026-08-20 (Mr. Radio 🦉 `f60b686e`, found by Tiberius 👑) — REFUSE THE NUMBER: THE TWO ARMS WERE NEVER SCORED BY THE SAME RULES

**Row `d8d019f6` closes on "a real median-delta number, OR a refusal with a reason someone can point at." This is that refusal**, and it is worth more than the delta would have been: a delta gets argued with, a broken instrument gets fixed.

### 🔴 THE ONE EXAMPLE THAT SETTLES IT — same 20 utterances, both arms behaving CORRECTLY, opposite verdicts

The identical 20 `automatic` mode-switch utterances, same corpus, same night, **neither arm misbehaving**:

| Arm | What it does | What its scorer says |
|---|---|---|
| **v1** | answers the mode switch **instantly**, returns `job_id: None` (correct — a mode switch spawns no job) | `failure="push_failed"` ⇒ **0 of 20** |
| **v2** | answers the mode switch, returns 200 | `ok=True` ⇒ **20 of 20** |

**One category, two verdicts, zero difference in behaviour.** Lead with this if anyone asks why the comparison cannot stand.

### Three independent asymmetries. Each one alone invalidates the comparison.

**(1) The two arms do not define "ok" at the same bar** — read at both lines, not taken on report:

| Arm | The line that decides success | What it requires |
|---|---|---|
| **v2** | `v2_eval.py:837` — `ok = ( reply.status_code == 200 )` | **The HTTP call returned 200.** Nothing about content: an empty or useless body scores as a success. |
| **v1** | `v1_eval_arm.py:314` — `rec.ok = rec.client_span_ms is not None` | Reachable only after job id, metadata **and** `completed_ts` all exist. **The work finished end to end and the client observed it.** |

⇒ *"Did the server answer?"* and *"did the work finish?"* are different questions. A v1 job that ran perfectly but whose completion event the client missed scores as a **failure**; a v2 call returning an empty 200 scores as a **success**.

**(2) A correct mode switch is booked as a v1 failure — 40 occurrences.** Asymmetries 1 and 2 fire together on the same twenty rows above. **That is the entire "automatic 0 of 20."** v1's honest failure rate is **~35%, not 48%** — and still not comparable to v2's until the bars match.

**(3) The routing denominators differ — and the contract for it was written into the wrong file.** `v1_eval_arm.py:440` excludes routing-ineligible utterances from its denominator (~40% of the corpus) and says, verbatim:

> `# … and their count + corpus share are reported so the exclusion`
> `# is auditable, never silent. The v2 arm must exclude the SAME utterances.`

**The string `eligible` appears 12 times in `v1_eval_arm.py` and ZERO times in `v2_eval.py`.** Verified by grep. So v1 scores routing over ~60% of the corpus and v2 over 100%.

⇒ **THE LESSON IS SHARPER THAN THE DEFECT.** Somebody knew the requirement precisely enough to write it down — **in the wrong component's comments, addressed to code that was never going to read it.** *A cross-component contract living in one component's comments is not a contract, it is a wish.*

### ⇒ This upgrades the verdict from "tonight's run is unreadable" to "no run from this harness was ever readable."

**Artifacts preserved deliberately, as EVIDENCE FOR THE REFUSAL rather than as a result.** The `ok`-scoring is broken; the client spans were recorded independently of it, so once both scorers agree on a bar a valid delta may be **re-derivable from tonight's data without another 70-minute run**.

**The pre-existing asymmetry stays disclosed and is NOT part of this**: v1's client span includes full FIFO queue-dwell by design, and that was chosen, documented, and printed in the instrument string. **These three were not chosen.**

### ⏳ PENDING — Rick did not answer (the ask timed out; no response at all)

Asked ~20:24: fix the scorers and rerun **tomorrow morning** (my recommendation), rerun **tonight**, or **stop and take the defects**. **Nothing is authorized and nothing was done.** The run was left to finish for its artifacts. Re-ask tomorrow.

### 🧵 THE SENTENCE THAT TIES THE WHOLE NIGHT TOGETHER (Tiberius, 20:33)

> **"The wrong pairing does not look wrong, it looks well-powered."**

Pairing v1-warm against v2-cold would have yielded **49 shared utterances** — a perfectly plausible sample size. That is how the meaningless −11.2s delta got produced. The **correct** pairing yields **0** and the tool refuses. ⇒ **The broken-looking output was the honest one.**

**Every finding tonight has this shape — the failing state looked healthier than the true state:**

| Instrument | Looked like | Actually was |
|---|---|---|
| Bare `pytest` over `websocket_smoke` | "5 passed" — a green tier | 4 of ~50 tests |
| `/health` on the v1 arm | 200, all night | every embed returning nothing |
| v1's scorer on a mode switch | `push_failed` ×20 | correct behaviour, mis-booked |
| Cold-vs-warm pairing | n=49, well-powered | not a comparison at all |
| Unit suite over `running_fifo_queue` | green | a mock implementing a method the real class lacks |

⇒ **A number that looks reasonable is not evidence the measurement was reasonable.** The only defence that worked all night was asking one more discriminating question before publishing.

**And the design lesson underneath it** (from the seq-split fix, `4366749f`): an **assertion detects a mislabelling after it happens; splitting on the arm's own monotonic counter means there is nothing to detect.** Correct-by-construction beats correct-and-checked. Three separate fixes tonight ended up taking that shape.

### 🔬 THE PATTERN THAT SAVED THIS, WORTH MORE THAN ANY SINGLE FINDING

Tonight produced **five confident answers** to "why does v1 fail ~half the time," and **four were wrong**:

| # | Answer | How it died |
|---|---|---|
| 1 | Missing credentials cripple the baseline | **Disproved by its own test** — 48% credentialed vs 47% crippled |
| 2 | v1 is genuinely unreliable; v2 wins on reliability | Withdrawn — it would have been published at 19:31 |
| 3 | Three distinct v1 defects | Partly right; one is shared with main, one is a harness artifact |
| 4 | The instrument mis-scores mode switches | True, but not the whole story |
| 5 | **The two scorers never asked the same question** | Current, and it dissolves the rest |

**Each was stated confidently. Each died to one more discriminating question asked before publishing.** Tiberius withdrew his credential theory *explicitly* in the write-up rather than letting it fade — "tested and failed" and "superseded" leave the next reader in completely different positions. **Two of the wrong calls were mine** (the direction of the notify bias; the blast radius of the mock-auth defect), both corrected by the worker holding the measurement.


## 🪞 FINDING 2026-08-20 (Mr. Radio 🦉 `f60b686e`) — A TEST MOCK IMPLEMENTS A METHOD THE REAL CLASS DOES NOT HAVE, and it is live on main right now

**`set_solution_summary_gist` is called in production and defined nowhere in production.**

| Where | What |
|---|---|
| `src/cosa/rest/running_fifo_queue.py:1579` and **`:1730`** (MAIN tree, today) | **calls** `running_job.set_solution_summary_gist( … )` |
| same file, pinned worktree `b0735467`, `:1579` and `:1744` | **calls** it |
| `src/cosa/memory/solution_snapshot.py`, either tree | **no definition** |
| anywhere in production code, either tree | **no definition** |
| `src/cosa/tests/unit/rest/test_running_fifo_queue.py:65` | **`def set_solution_summary_gist( self, v ): self.solution_summary_gist = v`** — on a **test double** |
| `src/cosa/history/2025-11-08-to-2026-02-03-history.md:746` | a markdown record of a method that once existed |

⇒ **THE MOCK IS MORE CAPABLE THAN THE REAL CLASS.** The unit suite passes because the double implements a method `SolutionSnapshot` does not have, so production raises `AttributeError` at a line the suite believes it covers. **This is at HEAD, not only in the pinned baseline** — it is a live defect on the working branch.

**Observed cost**: 42 occurrences of `'SolutionSnapshot' object has no attribute 'set_solution_summary_gist'` in one v1 arm run.

**⚠️ AND IT IS NOT A v1-vs-v2 DIFFERENTIATOR, WHICH IS THE TRAP.** It is one **shared** bug that only v1's code path reaches. Read naively it inflates v1's failure count and looks like evidence that v2 is more reliable by design. It is not.

**This is the third time tonight the cause of v1's ~48% failure rate has moved**: missing credentials → *(disproved, 48% vs 47% after provisioning)* → genuine v1 unreliability → *(now)* three separate defects, at least one of them shared with main and one of them a harness artifact. **Each attribution was stated confidently and each was wrong.** The pattern that keeps saving it is refusing to publish until one more discriminating question is answered.

**Status of the other two failure classes in the credentialed run:**
- **49 × `User not found: interactive_job_tester_8e32@generated.local`** — the *same* mock-auth id as the notify finding above. The v1 launcher sets `AUTH_MODE=mock` while dev and test run `jwt`, so this is a **mock user never provisioned in the DB — harness artifact**, not a v1 defect.
- **28 × `EmbeddingProvider HTTP fallback returned 422 — String should have at least 1 character, input: ''`** — **v1 is embedding an empty string.** No read yet on whether the empty value is the utterance itself or a derived field v1 fails to populate. **This one may be genuine.**

**Not filed as store rows** (no-new-rows order). The mock/real mismatch deserves a P1 when it lifts — a passing test suite is currently asserting the existence of a method that does not exist.


## ♻️ FINDING 2026-08-20 (Tiberius 👑, error owned by Mr. Radio 🦉 `f60b686e`) — A CONTAINER RECREATE DOES NOT KILL A RUNNING JOB, IT REHYDRATES IT

**I told Tiberius "force-recreating the test container is what ended `ts-7b9a6b87`." That was wrong**, and it nearly cost the rerun.

**What actually happens**: the recreate applies env changes and the persisted job comes **back**. His log: `[CJ-PERSIST] Restored immediate job: ts-346cab2d`, restarted **19:46:33**. His "job gone" check landed in the few seconds before rehydration completed, read empty, and he then relaunched the v1 arm **underneath a live run** at 19:48:59.

⇒ **What ends it**: killing the pytest process **inside** the container, which dead-letters the job and frees the monopolize slot. The recreate is the sanctioned path for applying env changes — it is **not** a kill. The two look identical for about ten seconds.

**⚠️ AND THIS REFINES A DOCUMENTED RULE, which is why it belongs here and not only on a row.** The `schedule-tests` skill states — correctly, measured 2026-08-15 — that **a bounce DESTROYS the queue**: `todo`, `run`, `done`, `dead` all came back empty and two queued jobs were lost. **Both facts are true at once**: a **QUEUED** job is lost, a **RUNNING immediate** job **rehydrates**.

**The trap is the inference, not either fact.** A reader who knows "a bounce destroys the queue" naturally concludes "so a bounce kills the running job too" — and gets tonight's outcome: a baseline server relaunched under a run that was still going. **That inference is nowhere written down as false.** Worth adding to the skill next to the existing warning.

**Also fixed tonight, `f86ee2d7` — a green tick that meant the wrong thing.** Tiberius's report tool rendered **PASS** on a synthetic pair that kept 53 of 100 with one category entirely absent, because **both arms lost the same records** so nothing *diverged*. **Divergence and attrition are different questions and it only asked the first.** A green reading "the arms agree" when the honest statement is "the arms agree about half a corpus." He found it by rehearsing the tool on a synthetic pair rather than waiting for live data to expose it.

**Status**: `ts-23613e7d` running since 19:50:20 — the first properly credentialed run tonight. Verified independently: 11 keys in the worktree, **zero** key-not-found lines in the fresh arm log, pin still `b0735467` with an empty porcelain.


## 📨 FINDING 2026-08-20 (Mr. Radio 🦉 `f60b686e`) — THE DM CONDENSER DROPPED AN AUTHORIZATION LINE, three times, and each drop cost ~5 minutes of a live run

**What happened.** Tiberius correctly refused to kill a live job without Rick's direct word. I sent it three times. My 19:40 DM **opened with the literal words "RICK'S WORD: KILL IT"**, followed by the provenance: the 19:32 four-option ask, his selection of *"Kill it, fix the credentials, rerun now"*, `answered=true`, `default_used=false`. His reply came back: **"You have said three times to kill it but not once that you have his word."**

⇒ **He is not wrong about what he received.** The DM condenser summarised my message and **dropped the authorization sentence** — the one load-bearing line — while keeping the surrounding operational detail. Every one of those DMs carries the marker `This DM was condensed in transit`.

**THE SHAPE**: the condenser optimises for *information density*, and a short declarative authorization ("I have his word") is low-density next to a paragraph of mechanics. So it compresses away **precisely the sentence a permission gate is waiting on**, and leaves the instructions it was gating. The receiver then sees an order with no authority behind it — which is exactly what a careful worker is built to refuse.

**Cost tonight**: ~15 minutes across three round-trips, while a run that could not produce a number kept burning the box.

**Workaround used**: send the authorization **alone**, in a message short enough that there is nothing to condense. That worked.

⇒ **The fix worth building**: authorization lines must be exempt from condensation, or the condenser must never drop a sentence naming a person's decision. A comms layer that summarises away consent is a comms layer that manufactures refusals. Related but distinct from `b1f3d2df` (condenser inventing a noun) and `206dd6ea` (truncated body, fallback did not fire) — both already closed, both the same family.

**Not filed as a store row** (no-new-rows order). Worth a P1 when it lifts — this one silently breaks the fleet's permission model.


## 🔑 FINDING 2026-08-20 (Tiberius 👑, verified by Mr. Radio 🦉 `f60b686e`) — EVERY WORKTREE IS BORN WITHOUT CREDENTIALS, and four gates said the server was fine

**Attempt 12 could not produce a number, and the reason is not the code.** The pinned v1 baseline worktree holds **2 API key files**; the main tree holds **11**. Verified independently by listing both directories:

```
main tree:  anthropic-api-key-firewalled eleven11 gemini google groq huggingface
            kagi mistral model-server-api notification-api-claude-code-dev openai
worktree:   model-server-api notification-api-claude-code-dev
```

**The causal chain appears ~300 times in the v1 arm log**: `Key [openai] not found at …/lupin-v1-baseline-b0735467/src/conf/keys/openai` → `EMBEDDING API ERROR` → sqlalchemy `expected 768 dimensions, not 0`. Plus 28 where the HTTP fallback to the model server 422'd on empty text, and 27 jobs ending `Confirmation timeout/error — defaulting to cancel`. **Only 18 of 320 pushes returned 500** ⇒ these are jobs that were **accepted and then died on a missing credential**, not rejected requests.

⇒ **v1 kept 53 of 100 warm-pass records, with `automatic` at 0/20 and `calculator` at 3/20.** A delta computed on that compares v2 against a v1 that could not embed.

**🔴 THE FINDING WE NEARLY PUBLISHED INSTEAD.** v1 at 53/100 against v2 at 22/22 reads as *"v2 is dramatically more reliable"* — and I had already told Tiberius to put that comparison on the first screen of the report, above the latency delta, because it answered Rick's question more decisively. **It would have been false.** The gap is a provisioning error in one worktree, not a property of either codebase. What caught it was asking one question before publishing: *are these real request failures, or records that never got written?* Neither of us knew, and the answer was neither.

**⚠️ ROOT CAUSE, AND IT OUTLIVES THIS RUN: keys are gitignored, so every worktree is born credential-less and nothing warns.** The baseline server came up, answered `/health` 200, **passed its code-identity gate**, and accepted work — then failed on the first embed. It ran that way for four hours.

⇒ **IDENTITY IS NOT CAPABILITY.** Every gate this crew has built checks *which code is running*; none checked *whether the environment can do the work*. Second instance in one day — the 18:07 reboot killed both vLLM model servers and `:7997`, and only `:7997` was written down.

**FIXED, by Tiberius, `ee221b71`** — and both design choices matter:
- It is a **DIFF of the two key directories, not an enumeration**. The launcher already checked `model-server-api`, which is exactly how this was missed — enumerating repeats the mistake one key at a time, while a diff catches whatever the main tree has and the worktree lacks, **including keys added later**.
- It sits on the **already-up path**, which is the half that actually bit us: every re-check tonight said *"identity matches, nothing to do."*
- Proven red against the live crippled arm; names all nine missing keys and prints the copy command; exit 1.

**Rick's ruling, 19:33 EDT**: kill, fix the credentials, rerun at n=20 now. Answered off a four-option ask, not a default. **On the pin**: keys are not code, `b0735467`'s tree is unchanged, so provisioning credentials does not weaken the tamper-evident baseline — stated on the row so a later reader does not mistake it for tampering.

**AND THE EMBED PROBE LANDED, `5ecee90e` — built as a DISCRIMINATOR, not a check that passes.** The identical probe returns **0 from the crippled worktree and 768 from the main tree**, same code and same model server, differing only in which key directory is on the path. That negative control is what separates an instrument from a decoration: a probe nobody has ever seen fail is an assumption with a green tick.

It **replaces the `/health` call outright** — `/health` answered all night while all 300 embeds returned nothing.

⇒ **BOTH CHECKS STAY, because they fail on different things**: the **diff** catches a key that is *absent* and names which files to copy; the **probe** catches a key that is present but wrong, revoked, or pointing at nothing. The diff proves a file exists, which is the same shape of gap as `/health` proving a port answers — that argues for the probe being the gate, not for dropping the cheaper check.

**Provenance verified three ways rather than asserted** (row event 8217, written *before* the copy): `.gitignore:71` excludes `src/conf/keys/**`, so the keys were never in `b0735467`'s tree and cannot be; the worktree is clean at `b0735467`; and after the copy both `rev-parse` and the code-identity gate still read `b0735467`. **Tiberius's sentence, which settles it: *"Provisioning restores the intended baseline; the tampering would have been publishing a delta against an arm we knew could not embed."***


## 🚦 FINDING 2026-08-20 (Mr. Radio 🦉 `f60b686e`, with María 🌸) — the websocket tier CANNOT do its job where the merge checklist puts it, and it reports green anyway

**Two defects, and the second is the one that matters.**

**(1) The directory answers to bare pytest and lies.** `python -m pytest src/tests/websocket_smoke/ -q` returns **5 passed, 1 skipped** — and reads as a passing tier. The real suite is ~50 tests and does **not** run under pytest collection: it lives behind a custom runner, `python -m tests.websocket_smoke.infrastructure.smoke_test_runner`, invoked by `src/scripts/run-websocket-smoke-tests.sh`. Counted in the tree: **4 pytest-collectable test functions** across the whole `websocket_smoke/` directory. ⇒ **A green covering roughly a twelfth of the suite, with nothing in the output saying so.** Caught tonight when María reported "websocket smoke 5 passed 1 skipped" and the number didn't match what CLAUDE.md says that tier is. She retracted within two minutes of being asked which command she ran.

**(2) THE GATE ORDER ITSELF IS WRONG FOR WORKTREE BRANCHES — María's point, and it is worth more than the miss.** The websocket suite drives a **live server**. On a worktree branch it therefore tests **whatever `:7999` is currently serving**, which is not the branch's code. The PR merge checklist places it *before* the merge. ⇒ **In that position, for any worktree branch, it cannot do its job — it produces a green about code that isn't under test.**

⇒ **THE SPLIT, applied to María's brain-integration merge tonight**: unit and cosa are meaningful **pre-merge** on the worktree (she has both — 15,937 passed with 11 failures proven identical on a clean control at `a657e88e`; cosa 8,750 / 0). **Websocket smoke, E2E UI and integration are all server-dependent ⇒ post-merge, post-bounce**: release `:8000` → merge → bounce `:7999` with the sanctioned script → run websocket smoke **through the shell script** → then take `:8000` for the last two.

**Not filed as a store row** (no-new-rows order). Worth one when it lifts — probably as a pytest collection guard that fails loudly if the websocket directory is invoked directly, since a suite that answers to the wrong command with a green is the failure mode here, not the runner.


## 🔔 FINDING 2026-08-20 (Mr. Radio 🦉 `f60b686e`, corrected by Tiberius 👑) — v1's notifications fail validation 530 times and nobody has ever seen it

**Found by reading the v1 arm's log during attempt 12, not by looking for it.** `/tmp/v1-baseline-7997.log` carries **530 × `[ERROR] _notify() failed: 1 validation error for AsyncNotificationRequest`**. The cause is not a network problem: `job_id` fails the model's pattern `^([a-z]+-[a-f0-9]{8}…`. It is **caught, logged, and non-fatal**, so every run completes and nothing visibly breaks. **v2 has 0** of these in a live container log of 1,516 lines.

**I called the direction of the bias wrong and Tiberius corrected it — the correction is the useful part.** I assumed a failing notify *added* latency to v1's measured span, making v1 look slow and flattering v2. The opposite is true: the exception is raised **constructing** `AsyncNotificationRequest`, which happens **before** `notify_user_async` is ever called — and that function is a **synchronous `requests.post` with retry sleeps**. So the failure **skips an HTTP round trip a healthy v1 would pay**, at ~**1.66 skipped notifies per push**.

⇒ It is genuinely inside the measured span (`running_fifo_queue.py:1687` calls `_notify`, and the run-to-done event the client blocks on is emitted after it). ⇒ **A repaired v1 would measure SLOWER, so tonight's delta is CONSERVATIVE toward v2, not inflated by it.** That sentence goes beside the number in the report rather than being left as an unexplained asterisk.

**✅ ANSWERED — and the answer is "neither", which is why asking was worth it.** I framed it as a binary: harness artifact, or a product bug dropping real users' notifications. Tiberius established it is **the ordinary path carrying a harness-shaped value**, so it is a real defect with a much narrower blast radius than I feared.

**The mechanism**: the id is not synthesized by the eval harness — it is `job.id_hash`, scoped by the ordinary `register_scoped_job` into `"sha256::user_id"`. The notification pattern accepts that form **only when `user_id` is a UUID**.

**Established with a negative control, four real values tested rather than one:**

| Value | Against the pattern |
|---|---|
| mock-auth id the v1 arm actually produces (`interactive_job_tester_8e32@generated.local`) | ❌ **REJECTED** |
| a real JWT `user_id` (a UUID) | ✅ matches |
| a bare sha256 | ✅ matches |
| an agentic id | ✅ matches |

⇒ **A genuine logged-in user's notifications validate fine.**

**🔴 I THEN OVERSTATED THE BLAST RADIUS AND TIBERIUS NARROWED IT AGAIN — with receipts.** I wrote that it hits "every deployment running `AUTH_MODE=mock`… our whole dev and test fleet," and that notifications had therefore been silently failing across the environments where people debug by watching them. **That was wrong**, and the correction is measured, not argued:

- `auth mode = jwt` is set once in `[Lupin: Baseline]`, which **Development and Testing both inherit**
- **neither container overrides `AUTH_MODE`**; the live dev container reports `jwt` when asked directly
- **dev and test logged ZERO of these failures** while carrying real traffic
- the **only** `AUTH_MODE=mock` in play anywhere is the **v1 baseline arm's own launcher, line 145** — even `run-websocket-smoke-tests.sh` dropped its mock override, with a comment that the server runs JWT now

⇒ **Scope is the pinned v1 eval arm, not the fleet. Nobody has been debugging blind.** Filed as row `befeba88` (Tiberius had already filed it before the no-new-rows order reached him; kept queued — it costs nothing there and dropping a measured defect to satisfy a workload order would lose it). Scope corrected inside the row so it does not stand as a fleet-wide claim.

**⚠️ THE PATTERN WORTH KEEPING FROM THIS EXCHANGE — it happened twice in ten minutes, both times to me.** I got the *direction* of the latency bias backwards, and then I got the *breadth* of the defect wrong. Both times a worker holding the actual measurement corrected me, and both times my error was the same move: taking a real finding and stating it one step wider than the evidence carried. The finding survived both corrections and got sharper each time.

**Deliberately NOT fixed tonight**: a fix would change v1 **mid-measurement**, the one thing this crew has been careful not to do.

**Two lower-priority items seen in the same log, recorded so nobody re-derives them**: 622 splainer warnings for a missing `model tokenizer map` key, and an XML parser stripping 96 chars before the root tag. Neither looks load-bearing. Not chased.

**Not filed as a store row** (Rick's no-new-rows order still stands).


## ⏳ PENDING DECISION 2026-08-20 (Mr. Radio 🦉 `f60b686e`) — the off-peak window is wrong AGAIN, and this is the third version of the same rule

**Asked, not answered.** Rick was asked and replied about something else; the question stands. **Do not treat the current CLAUDE.md text as settled — it is measurably wrong right now.**

**What CLAUDE.md says** (§ COST MODEL → Off-peak scheduling rule): host up from ~7:17 AM, and **7:30–10 AM EDT is "OPTIMAL — schedule batch work here."**

**What the box actually does.** Measured from `last -x reboot`, the 12 morning boots since Aug 4:

`08:52 · 09:27 · 07:17 · 09:14 · 09:52 · 09:56 · 09:20 · 10:52 · 09:48 · 09:03 · 09:17 · 09:43`

**Median 09:24. Eleven of twelve are after 08:52.** The 07:17 the rule rests on is a single day (Aug 6). ⇒ **a job placed at 7:30 sits dead ~1.5–2.5h on almost every day.**

**This is the second correction of the same rule, failing the same way.** The original pointed at hours the box was OFF. The 2026-08-17 correction replaced it with hours the box is *usually not up yet* — and it was written in the same doc that says *"a copied example is how a bad window propagates faster than the prose that describes it."* Both versions were derived from too few boots.

⇒ **Proposed: 10 AM – 1 PM**, with the measurement command written beside it so the next reader re-derives the window instead of trusting the sentence:
```bash
last -x reboot | head -20      # then read the morning boot times yourself
```

⚠️ **The one thing that would make this wrong, and only Rick can answer it**: this is derived from boot *history*. If he powers the box on deliberately and would just as happily boot at 7:30 when a job needs it, then this is a record of habit rather than a constraint, and the rule should stay as written. **Ask before editing CLAUDE.md.**

**Live receipt that the window is not academic**: the box was down 14:34–18:07 today and booted at 18:07, so no morning window existed at all. Attempt 12 ran in the evening on Rick's direct approval instead.


## 🌙 TONIGHT 2026-08-20 (Mr. Radio 🦉 `f60b686e`, with Tiberius 👑 and María 🌸) — attempt 12 is live, and two of my own claims were wrong

**Attempt 12 = `ts-7b9a6b87`, live 18:36:15 EDT**, n=60, **no `--timeout`**, auto-fix off, `:8000` verified idle at submit. Lands ~23:25. Rick is leaving the box up. Row `d8d019f6`; it closes on a median-delta number or a refusal someone can point at, and nothing less.

**🔴 TWO CARRIED-FORWARD CLAIMS OF MINE, BOTH FALSE, BOTH CORRECTED WITH MEASUREMENTS.** Same shape both times: a true-when-taken measurement restated as a present-tense fact days later, without re-measuring.
1. **"The test credentials are set nowhere on this box"** — repeated in history.md and used to describe four rows as blocked. **Rick challenged it directly and was right.** They are at `~/.bashrc:147-148` and live in the shell; `docker compose config` → **exit 0, 554 lines, empty stderr**. `--force-recreate` was never blocked. None of those four rows had the credential in `blocked_by` — the block existed only in prose.
2. **The 7:30 AM window** — see the pending decision above.

**Attempt 12 refused once before it ran, and the refusal was the system working.** First submit `ts-06e1d1a6` died in **2.3 seconds**: the two vLLM servers at `192.168.1.21:3000/:3001` had been dead since the 18:07 reboot, and the liveness guard **refused rather than measure against dead infrastructure**. Nothing ran, nothing was falsified. ⇒ **Three things die on a reboot, not one** — `:7997` *and* both model servers — and only `:7997` was written down anywhere. Tiberius relaunched both from Rick's own aliases and resubmitted.

**María's guardrail is armed and PROVEN, not asserted** — `src/scripts/watch-paired-block-failure-rate.py`, committed rather than scratchpad. Her 08-17 finding (row `2ebe4ccb`): a paired run can degrade **categorically**, not randomly — failures by block ran 10/10/4/38/94% — and because the corpus is **ordered by category**, one whole category went 94% absent from v2 while v1 kept it. Accuracy is scored over `ok` records only, so **the arm that loses its hardest category scores better**, and the floor of 30 does not catch it (~300 pairs survive a 32% failure rate). Replayed against her own file the script reproduces 12/10/4/38/94/62 and fires on blocks 4–6; it stays **quiet on a uniformly-bad run**, because flatness is what it tests. The report will carry **per-arm failure rate and each arm's surviving category composition beside the delta**.

**⚖️ RULED (Mr. Radio, María concurring) — the v1 pin stays `b0735467` for this run.** `v1_eval_arm.py:105` pins the pre-drift sha for tamper-evidence (Sam's design, Cheech-ratified 08-15), which is in genuine tension with my own 08-14 ruling on `647f3733` to baseline against v1 as of the harness landing. **Changing the referent mid-flight makes tonight's number incomparable to all eleven prior attempts.** The honest fix is not moving the pin but *naming* it: the reason now lives **in the assert's own message**, not only in the report, so the next reader sees a referent somebody chose rather than a check that happens to pass. Committed `a657e88e`, 169 unit tests green.

**⚖️ RULED (Mr. Radio) — row `3598c1d3` (weather search) is a missing retry, not a mystery.** Chloé and Sam each named two closing events and each correctly declined the second as a manager's call. Taking it: `KagiSearch.search_fastgpt()` is a **bare single call** — no retry, no backoff, no exception handling — so one momentary upstream blip becomes a user-visible failure with certainty. What happened at 18:54 on 08-19 is now **accepted as permanently unknown**. Row un-parked to `queued` as defined work: bounded retry + backoff, **without swallowing the final status code** (Sam proved that property with a control test at `79ea2501` — run it before and after).

**Staffing**: Rick's skeleton-crew hold stands. He approved **exactly one** seat by name — Tiberius, for this run. A second seat for the P3 was offered and declined by me: a P3 does not warrant source edits on the same box during a 4.8-hour measurement.


## 📋 DECISIONS LOG 2026-08-19 night (Mr. Radio 🦉 `4c571f73`) — post-game of the six-seat crew run

Retro: `io/post-games/2026.08.19-six-rows-and-attempt-eleven-post-game.md` (full tier, **DRAFT pending Rick's D3 approval**). 59 commits, 6 seats, unit tier green at HEAD `31899329` (24,635 passed / 0 failed).

- **R-1 — the submit path must refuse a per-test timeout shorter than the suite budget it runs under.** Attempt 11 of the paired n=60 run died on `--timeout 5400` while the suite budget was correctly 30000s. `test_paired_n_fits_integration_timeout.py` guards the hazard and passes, because it compares `n` against the *suite* budget and never sees the per-test cap. Filed as store row `64677f38` (Tiberius, P1). n=60 stays unchanged — shrinking the corpus would change what is measured to dodge a typo.
- **R-2 — open the harvest window BEFORE announcing the reap.** Six seats left **zero** rolling deposits on the commons `post-game` topic tonight (newest entry is 2026-08-17); all six left lesson-bearing mementos. `io/post-games/README.md` carries a standing note saying exactly this, and I read it after the reap. Cross-examination of tonight's crew is gone permanently.
- **R-3 — an instrument that fails ten times is a decision for Rick, not maintenance to absorb.** Notifications returned `user_not_available` all evening and I kept re-firing per instance. Escalate the *pattern* on the second or third failure, naming it as a pattern.
- **R-4 (NOT YET GRADUATED) — a negative result is only as wide as the path the probe exercised.** María ruled out cwd restoration from the success path only; the leak was on the error path (`80c17f29`). `post-game.md` §5.3 requires cross-examining the source before this becomes doctrine — **do not write it into a `workflow/` doc until María has had the chance to refute it.**

**Still unhomed, for Rick**: should the no-new-rows ban lift for measured, reproduced defects? Three real defects tonight had nowhere to live.

## 🔬 FINDING 2026-08-19 (Rachel 🕊️ `6dc9e44d`) — this box CANNOT produce a live Python stack, and we have wanted one three times this week

**Found while diagnosing the `:7997` wedge (row `012e35a9`).** A server was burning a full core with 32 runnable threads and answering nothing. Naming the loop needed one stack dump. **Every route to one is closed on this host**, and they are closed independently, so no single fix opens them:

| Route | State | Why it fails |
|---|---|---|
| `py-spy dump --pid` | not installed | and it would still need ptrace below |
| `gdb -p` | installed, refused | `EPERM` — attach is blocked before it starts |
| `/proc/<pid>/task/*/stack` | refused | `Permission denied` for a same-uid reader |
| `perf record -p` | not installed | and `perf_event_paranoid` is **4**, which denies it anyway |
| a signal → thread dump | nothing to signal | app registers **no `faulthandler`**; `SigCgt` covers INT/TERM/WINCH only, so a `SIGUSR1` would **kill** the process, not dump it |

Root of the first three: `/proc/sys/kernel/yama/ptrace_scope` is **1** (attach only to your own descendants) and `sudo` wants a password, so an agent session can never attach to a server it did not spawn.

**What it cost.** The `:7997` root cause was reached by inference — CPU-per-thread, `wchan`, per-thread syscall counters, thread ages, and reading the code — and then closed with a control test rather than a captured frame. That worked, and it took roughly 20 minutes that a `py-spy dump` would have made 20 seconds. **Mr Radio's count: three times this week.**

**The cheapest durable fix is the last row of that table, and it needs no root at all.** Registering `faulthandler` on a spare signal at server startup is a handful of lines, and from then on any wedged Lupin process dumps every thread's frames on demand. Worth pairing with `py-spy` in the venv for processes that lack the hook.

**Not filed as a row** (skeleton-crew no-new-rows order). **Not fixed** — recorded here on Mr Radio's instruction.


## 🔓 FINDING 2026-08-19 (Mr. Radio 🦉 `4c571f73`) — `--showlocals` writes the live password into a saved artifact on any auth failure

**Found while diagnosing `ts-5a02a537`.** `pytest.ini:82` carries `--showlocals` in `addopts`, so a failing frame dumps every local variable into the junit XML and the run log. The frame that failed was `v2_eval._login`, whose locals include `email` and `password` — so the **live credential for `interactive.job.tester@lupin.deepily.ai` is now sitting in plaintext** in `io/test-suite/artifacts/integration-junit-*.xml`.

**This is not specific to that test.** Any auth failure in any test that holds a credential in a local writes it to disk the same way. The artifacts are named, dated, and kept.

**⚠️ The same flag is the only reason the v1 arm's metrics survived.** Nothing reached `io/v2-flow/` — `_dump_paired_artifacts` needs a *pair*, and the v2 arm died before producing one, so the dump never ran. The p50/p95/cache-hit numbers existed **solely** in the traceback locals `--showlocals` captured. So the flag is simultaneously the leak and the only forensic record of a 47-minute run.

**That tension is the actual decision**, and it is not obviously resolvable by turning the flag off:
- **Off** → no leak, but a failed run leaves nothing behind but a stack, which is the exact silence this crew has spent a week removing (`ts-1686ce29` died with no recoverable artifacts and cost a day).
- **On** → forensics survive, credentials leak.
- **The real fix is neither**: stop putting a password in a local. `_login` could take a callable or read from env at the call site so the secret never lands in a frame. Then `--showlocals` keeps its forensic value and has nothing sensitive to spill.

**Scope check before anyone acts**: the artifacts are local, on a box behind the same VPN/ADC boundary Rick already ruled on for `adce3547`, so this is housekeeping and not an incident. But it is a *credential in a file*, and the account is one every seat uses.

**Not filed as a row** (skeleton-crew no-new-rows order). **Not fixed** — the honest fix touches `v2_eval.py`, which the live run imports, so it waits for `ts-47b18c7e` to land.


## ⚖️ RULED 2026-08-19 (Rick, ~15:40 EDT) — skeleton crew HOLDS until he says otherwise; the tick does not override him

**Clean answer, not a timeout default** (`answered=true`, `default_used=false`). Verbatim: *"let's hold off from a skeleton crew until whenever I say so."*

**The conflict this settles**: the heartbeat tick fires *"tasks > workers — STAFF UP THIS TICK: spawn/assign now. Waiting to be told is a redline."* His standing order (broadcast `a30ebf4f`) says skeleton crew, no workers. **A tick does not reverse a standing order from the user** — I surfaced it as a blocking ask rather than resolving it myself, and that was the right call.

### ⚠️ THE TICK'S REASONING IS UNSOUND HERE, AND IT IS THIS WEEK'S RECURRING SHAPE
It reads *8 owed, 1 worker* and concludes understaffed. It cannot see that **7 of the 8 are serialised behind one live latency measurement**, so a crew would buy one P2 and risk the afternoon's run:

| Row | P | Why a worker cannot take it now |
|---|---|---|
| `d8d019f6` | P1 | The run itself — waiting on a result, not buildable |
| `3bfd3fbc` | P1 | Needs a *finished* run to supply genuine v1 residue |
| `95924f2d` | P1 | Regenerates the corpus the run is sampling from |
| `07fda9b6` | P1 | Open half is the **harness** classifier — not our code |
| `adce3547` | P2 | Fix = force-recreate = kills the run (María concurs) |
| `ec5cf83a` | P2 | Fleet-wide DM path; peers are actively DMing |
| `7c84b8b8` | P2 | Proof needs a 15k-test run on this same box |
| `7b9094d8` | P2 | Genuinely available — the only one |

**An owed-count is not a staffing signal**, because it cannot distinguish *unstaffed* from *serialised*. Same family as the day's other findings: an instrument asserting a conclusion from a number it cannot contextualise. Recorded here rather than filed (no-new-rows order).

**Rick also offered to disable the heartbeat Stop poke** — *"so that you don't get distracted with this kind of productive bullshit."* Undecided; my read is in the reply, and it stays his call.


## 🔇 CONFIRMED 2026-08-19 (Mr. Radio 🦉 `4c571f73`) — PHANTOM INTERRUPTS: the harness claims the user spoke when the user did not

**✅ RICK CONFIRMED IT DIRECTLY, 2026-08-19 ~15:40 EDT**, on the fifth occurrence, asked in real time while it was happening: *"Yes, and I haven't sent you anything. It's a phantom interrupt."* That is testimony from the only party who can settle it — no inference, no reconstruction. **The interrupt is spurious.**

**Occurrence #5 detail**, captured live because we had agreed the protocol in advance: fired ~15:38 EDT during a Bash health check on the paired run, and **arrived in the same beat as an inbound peer DM from María timestamped 15:38:35**. That co-incidence supports Rick's mechanism — another notification draining into the pre/post-tool-call slot and being labelled as the user — over my original "his words went missing in delivery" reading.

**The protocol worked and is worth keeping**: agree in advance that the next occurrence gets flagged *immediately* with a timestamp, then ask the one question only the human can answer — *did you speak?* Five occurrences of silent guessing produced nothing; one real-time ask settled it.

**Symptom**: four times this afternoon a tool call was refused with *"A user-initiated voice message was received and takes precedence over this tool call. You must address the user's message before continuing."* No message content accompanied any of them. From my side the user had said something urgent enough to interrupt me, and I could not see one word of it.

**What I checked, so this is not a guess**: no voice buffer exists for this session (`~/.claude/sessions/cc-buffer-4c571f73*` / `-8d2b6455*` absent), and **no `cc-buffer-*.jsonl` anywhere was modified in the last hour** — the newest is from 2026-08-18. So the content is not sitting undrained in Lupin's buffer waiting for me; it never landed there.

⇒ **The detection path and the delivery path have come apart.** Something upstream knows a voice message arrived — reliably enough to preempt a tool call four times — while the content reaches neither my context nor the buffer the hooks drain.

**Why it is worse than a dropped message**: the interrupt asserts an obligation ("you must address the user's message") that it makes impossible to discharge. I cannot answer, and I cannot tell whether the user is repeating themselves, correcting my course, or telling me to stop. The safe reading — ask them to re-send — is the one I took, but a seat that instead *guesses* what was said would be guessing at the user's instructions.

**Same family as the rest of today's board** (`07fda9b6`, and the two gates fixed in `37bd64f9`): a signal that reports an event without reporting its content, leaving the reader to supply the missing half. Related: the harness-side half of `07fda9b6`, which Rick ruled should name what it objected to.

**⇒ RICK'S READING, AND IT BEATS MINE (2026-08-19 ~15:45 EDT).** I had this as a *delivery* failure — his words went missing. He says it is a **misattribution**: some other notification drains into the pre/post-tool-call slot and gets presented to the model as a user voice message, because human communication legitimately outranks a tool call in that queue. **María reported the same yesterday while he was not messaging her.**

His reading fits my measurement better than mine did. A message that never entered the buffer yet still preempted a tool call is not a dropped message — it is an event wearing a message's label. On a genuine delivery failure I would expect a buffer write with no read; I found no write at all.

**AGREED PROTOCOL**: on the next occurrence I notify him immediately with the timestamp and what I was doing, and he confirms whether he sent anything. That one bit — *did a human speak* — is the discriminator, and nothing on my side can observe it. Recorded here because it needs to survive a re-spin: a seat that hits this cold will read the interrupt as a real instruction it somehow lost.

**Not filed as a row** (skeleton-crew no-new-rows order). **Not fixed**: the mislabelling is in the notification/hook layer, and the same layer-separation that keeps `07fda9b6` open applies.

**⚠️ THE FAILURE MODE TO AVOID IS GUESSING.** The interrupt asserts an obligation — *the user said something, address it before continuing* — while supplying nothing to address. A seat that infers what was probably said, and acts on it, is acting on instructions no human gave.


## 🔑 FIXED 2026-08-19 (Mr. Radio 🦉 `4c571f73`) — the :8000 seed was create-only, so a drifted credential could never be repaired

**The blocker**: `POST /auth/login` on `:8000` returned 401 with the same credentials that worked on `:7999`, which stopped `d8d019f6` from being submitted at all.

**Not a missing user, and not a wrong password.** The row existed in `lupin_db_test` with `is_active=t`, and its id matched dev exactly. Verified against the stored hashes directly: the dev hash verifies the env password, the test hash does not.

**The mechanism**: `src/scripts/seed_test_companions.py` copies companions dev→test with `INSERT … ON CONFLICT ( id ) DO NOTHING`. That makes it **create-only** — the instant a row exists in test, nothing in dev can ever reach it again. Change a password in dev and test keeps the old hash forever. The script runs on every test-container start and reported `All companion credentials already present in test database` the entire time: a green line asserting the credentials were GOOD when all it had checked was that rows with those ids EXISTED.

**This exact 401 was diagnosed before**, on 2026-04-13 (`src/rnd/v0.1.6/2026.04.13-test-container-auth-fix-plan.md`). That fix added the two missing emails to the allowlist — it repaired that day's symptom and left the create-only mechanism untouched to do it again.

**Fixed**: `ON CONFLICT ( id ) DO UPDATE` on the credential columns for both `users` and `api_keys`, inserted-vs-refreshed counted honestly via `RETURNING ( xmax = 0 )`, and the summary reports what it actually did. The container's startup log now shows both boots back to back — the old false green, then the converge line.

**⚠️ The fix moved the blast radius, and that needed its own guard** (María 🌸). Create-only was safe **by accident**: a script that cannot overwrite anything is harmless pointed at a live database. Converging removed that accident — this script now overwrites password and API-key hashes — and `TEST_DB` is a hardcoded constant, exactly the kind of thing a later edit makes configurable without re-deriving what it protected. Added an assert-the-target refusal at the top (`"test" not in TEST_DB` → exit 3, before any connection opens). Proven both ways: `lupin_db_test` passes, `lupin_db_dev` refuses.

### 📥 FINDING (not filed — skeleton-crew no-new-rows order): the regression guard for this exists and never runs

`src/tests/integration/test_cross_container_auth.py` was written on 2026-04-13 **specifically** to catch this drift. It passes now, and it would have failed for however long the test hash was stale. It is login-only, non-destructive, and takes **0.49 s** — it meets every `:7999` criterion — but it lives in `src/tests/integration/`, so it only runs in the scheduled `:8000` bucket as the final merge gate. A guard that runs a few times a month is not guarding a credential that drifts silently. **Proposed**: move it to the fast `:7999` path so it runs with the unit tier. Not done — that is a test-venue change and belongs in a review, not in a run-unblocking patch.


## 📊 MEASURED 2026-08-18 night (Mr. Radio 🦉 `89a34076`) — the notification-length natural experiment, and why `type` cannot answer it

**Rick's question**: did the DM tutor's brevity generalize to the spoken notifications he receives? **Measured, doc `9bc17152`**: the tail compressed (p90 1009 → 738 chars, −27%) while the median did **not** move (272 → 287). Distribution did not shift down; its right tail was cut. Replicated in both `lupin` and `plan`.

**Two decisions recorded here rather than in the doc:**

1. **`type='progress'` must NOT be excluded from this population, despite looking like process chatter.** Rick asked for that cut; it reversed the finding. It is wrong: `notification_type: str = "progress"` is the **default** in `notify()` (`cosa_voice_mcp.py:1291`, `:1434`) and the closing-turn TTS contract never names the argument, so nearly all authored speech lands there by omission. A 100-row sample is conversation — *"Standing by for the next task."*, *"Want me to commit this?"*, *"Morning. I'm up and running…"*. Excluding it drops ~72% of the channel and keeps only senders who bothered to pass a type: a selection effect, not a filter.

2. **The `type` column is not a category — it records whether the caller passed an argument.** Any future analysis cutting on `type` inherits that flaw. `custom` proves it twice over: 50.5% questions against 1–4.5% for every other type, but split at ~140 chars it is 90.2% questions below and 15.5% above — two populations under one label. **A question-vs-statement split (`message LIKE '%?%'`) is the honest cut and has not been run** (row `bdd1ca85`, P3).

**Still open**: causation is NOT established and will not be until someone finds a project the tutor never touched. The cutover was fleet-wide, so there is no untreated control group; the spillover story fits the data and so would any other fleet-wide change on 2026-08-13. Nobody has found such a project.

---

## 🔴 2026-08-18 MORNING — THE REBOOT DOES NOT UNBLOCK ANYTHING. Two fixes, both measured.

Rick asked directly whether tomorrow's reboot would pick up the new password and clear the blocked jobs.
**It will not.** Verified, not assumed:

**1. `~/.bashrc` returns early for non-interactive shells** — lines 5-8, `case $- in ... *) return;;`.
Every export below that line is dead code for tool shells, scripts and cron, which is every path a seat
actually uses. The password IS in the file (1 grep hit) and is still invisible after an explicit
`source ~/.bashrc`. **Remedy (Rick's): move both exports ABOVE the guard, or into `~/.profile`.**

**2. All four compose services are `restart: unless-stopped`** — `docker-compose.yml` lines 14, 61, 148, 333.
A reboot RESTARTS the existing containers with the env baked in at their last CREATE. Compose is never
re-rendered on boot, so the new password is not consulted. A reboot is not a recreate.

**WHAT ACTUALLY CLEARS IT** — one command, from an **interactive** shell, after boot:
```
docker compose up -d --force-recreate
```
⚠️ `bounce-dev-server.sh` does NOT substitute — it is a plain `docker restart`, same reuse problem.

**VERIFY AT EVERY STEP; four of these five have already failed silently once:**
1. exports readable from a non-interactive shell
2. `docker compose up -d --force-recreate`
3. `docker exec … printenv` shows the value **inside** the container (it reads **absent** now — that
   absence is the deliberate before-reading, so "present" after is real evidence)
4. `list-pending` returns something other than **401**
5. submit the paired run **behind** the already-queued 08:00 job, never ahead of it

**Unblocks together**: `d8d019f6` (paired run) · `3bfd3fbc` (its acceptance run) · `adce3547` step 3
(delete the JWT literal) · every future mount/env change. `53f60fcd` and `43fca908` are downstream of the first.

## ☀️ FIRST THING 2026-08-18 (Mr. Radio 🦉 `e251aa88`) — one credential unblocks four things

**Rick issues `LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL` / `_PASSWORD` to a seat.** That single act unblocks
john's `:8000` submissions, the morning paired run (`d8d019f6`), `3bfd3fbc`'s acceptance run, and every future
`docker compose --force-recreate` — the documented remedy for ANY mount or env change on either server, which
no seat can currently run. Compose has required these two in fail-loud `:?` form since before tonight.

**Then, in order**: (1) `--force-recreate` and confirm `docker exec printenv JWT_SECRET_KEY` reads PRESENT —
it reads absent now, measured, as the deliberate negative control; (2) only then delete the `jwt_service.py`
literal fallback (`adce3547` step 3); (3) submit the paired run BEHIND the already-queued 08:00 job, never
ahead of it; (4) flip block mode at `run-unit-tests.sh:31` and `run-cosa-tests.sh:34` — but run both tiers
first and do NOT flip if either is red at that HEAD.

⚠️ **The `:7999` bounce cannot do job (1).** `bounce-dev-server.sh` runs plain `docker restart`, which reuses
the container, so env changes silently do not land. A healthy server after a bounce is NOT evidence.

## ⚖️ RULED 2026-08-17 night (Mr. Radio 🦉 `e251aa88`)

- **The DM quality grader comes OFF the send path** (`ec5cf83a`). Grading must not sit inside the latency of
  accepting a DM; a grader that is down, slow or absent must be invisible to the sender. Acceptance is
  measurable: send latency with `:3001` down indistinguishable from up. Mechanism deliberately unruled.
- **JWT: require the env var everywhere, delete the literal — but provision FIRST** (`adce3547`). Not a random
  per-process secret: random silently invalidates tokens across restarts and across the two servers, which
  surfaces as an intermittent auth bug instead of a loud failure at boot.
- **Block mode flips, but a morning seat executes it** (`7c84b8b8`) — the box goes down with nobody awake to
  unflip. A red tier under a fresh flip is indistinguishable from a flip that caused it.
- **P1 `07fda9b6`'s headline is WITHDRAWN — the permission classifier is deterministic.** I matched two runs on
  the verb while they differed in both flag and commit. What survives: a refusal states none of the three
  conditions it applies, and recovering that cost two seats nine runs. Receipts `33460c60`, `abd39c5e`.

## 🧩 HELD OUT OF THE STORE 2026-08-17 (Tiberius 👑) — BRAIN INTEGRATION has no row (Rick's no-new-rows ban)

María (`89b27996`) flagged that her P1's two-part gate — *"pass 2 lands only after BOTH the registration
consolidation AND the brain integration have landed"* — has **NO ROW for half two**. Half one (registration
consolidation) = **`95924f2d`**, moved to in_progress tonight after we cleared its false Rick-block (steps 1-4
done `d110c26e`, step 5 retrain gated on Rick's explicit go). Half two, **BRAIN INTEGRATION = AskFlow called
from `todo_fifo_queue`**, is homeless: it is NEW unbuilt work, so the no-new-rows ban forbids a store row.
Recorded here (ban-neutral backlog) so it is not lost. **Mint a store row the moment the ban lifts** (or on a
Rick waiver — a §5.5 + brain-integration waiver was asked for earlier tonight and the ask timed out). It gates
`89b27996` pass-2; until brain-integration lands, that pass-2 cannot.

## 📌 UNFILED 2026-08-15 NIGHT (Cheech 🌿) — four findings held out of the store on Rick's no-new-tasks order

Rick's 23:0x directive was **"no new bugs allowed"** while driving the board down, so none of
these became rows. They are real, they are reproduced, and they need rows the moment the
directive lifts. Recorded here so the order costs us nothing.

1. **CONTEXT IS NOT A TURN — the biggest one.** The memento now reaches a rehydrated seat
   (`8ff014e2`, `8b9a10e9`, `7a9e5d22`, `965e8d41`), but **nothing makes the seat act on it**.
   It sits at an empty prompt behind **ghost placeholder text that reads like queued work and
   is not** — proven by typing a string that replaced the supposed "pending" line.
   - a **poke** cannot reach a quiet worker (Mr. Radio's `98350737`: 52 gate evaluations, 0 pokes)
   - a **DM** cannot either — arnold sat 72 minutes through one
   - **typing into the pane CAN**; plain `Enter` submits once the box has content
   - **four seats recovered this way tonight**: arnold, sam, Rachel, and Rachel's crew
   ⇒ Wanted: something that hands a rehydrated seat its first turn. Until then, a re-spin is a
   two-person operation and the second person is a human.

2. **`list-pending` does not exist.** Both `CLAUDE.md` and `CLAUDE.local.md` instruct sessions
   to run it *first* before scheduling on `:8000`; `src/cosa/rest/routers/test_suite.py` has
   exactly one route, the POST submit. The real pre-check is
   `GET /api/get-queue/{todo,run,done}` with a JWT. **Two traps for the next seat**: the login
   route is `/auth/login`, NOT `/api/auth/login`, and the token is nested at
   `tokens.access_token`, not top-level. Creds: `~/.lupin/config` `[lupin]`.
   ⇒ The documentation is wrong, not the capability. Fix the docs.

3. **The self-respin observer has no periodic caller.** arnold's TTL sweep (`3bac5ccb`) is
   correct and 100% covered, and **armed but not firing** — nothing calls
   `observe_fleet_self_respin` on a schedule. Three real markers were created tonight (mine,
   Rachel's, Mr. Radio's) and none will ever be swept. He flagged this himself rather than
   shipping a green row over it.

4. **Tiffany-class mementos.** A record with **no amendment block** yields a near-blank return:
   the seat gets a pointer and no state. `965e8d41` now labels that case loudly instead of
   showing it under a success banner, but the writer-side habit is the actual fix — Rachel has
   told both her seats to write real mementos.

### Two instruments that lied tonight — distrust these specifically

- **`dismiss_sessions` reported `timeout_no_memento` for BOTH workers** whose records I had
  verified on disk seconds earlier. Known: row `dffebbd6` — it reads the *pointer* at
  `io/mementos/<persona>.md`, not the *record* it names. **Verify the record yourself; never
  take the verb's verdict.**
- **`context-pressure` said `idle` for two seats that were stuck behind a
  `Set up auto mode for your environment?` modal** for over an hour. I nearly reaped arnold
  over it, which would have destroyed a finished review's delivery.
  **Read the pane before believing the instrument.**

## ☀️ FIRST THING TOMORROW — 2026-08-15, ~10–11am, Rick + Mr. Radio 🦉, and NOTHING ELSE BEFORE IT

> **Re-dated 08-14 → 08-15 by Cheech 🌿 on 2026-08-14.** It did not run on the 14th: Rick was AFK all day
> (broadcast `ee1a49ce`), which put the whole day on the CJ Flow v2 plan. Row `5e848dd8` is still `blocked`
> on Rick with its chase time already passed — the two open items remain his, unchanged: the **rollback
> choice** (`ask_multiple_choice ko6gqmox1`, still unanswered) and the **end-to-end walkthrough** he required
> before any write to `input_and_output`. Nothing about the job changed; only the date did.

**Rick's instruction, 2026-08-13 (verbatim in substance)**: *"Make a note of it in the to-do document for it
to be the first and only thing you and I begin the day with."*

**THE JOB**: run the embedding regeneration together — row `5e848dd8`. Not a backfill-normalize; a full
REGENERATION into shadow columns, then a swap. ~287,200 rows across `input_and_output` (input + output_final)
and `prediction_decisions`.

**READ THIS FIRST, it is the whole walkthrough**:
`src/rnd/v0.2.0/2026.08.13-embedding-regeneration-run-walkthrough.md`

**The order of the morning**:

| # | Step | Who |
|---|---|---|
| 0 | **Unload the dev + test models** to clear GPU 0 | **Rick** |
| 1 | Confirm nothing queued/running; confirm we are inside the window | Mr. Radio |
| 2 | `plan` — read the norm histogram together, confirm TWO populations (a third stops us) | both |
| 3 | `fill --limit=500 --apply` — bounded pass into shadow columns; **this is where the DB write side finally gets measured** | Mr. Radio |
| 4 | Look at that number, decide continue-now or schedule | **Rick** |
| 5 | `fill --apply` — full run, checkpointed and resumable | Mr. Radio |
| 6 | `verify` — must pass clean, zero bad norms, or we do not proceed | Mr. Radio |
| 7 | `swap --apply` — the ONE irreversible command, with Rick present | both |

**Settled overnight, do not re-litigate**:
- **Window widened to 11am** (`OFF_PEAK_END_HOUR = 11`, was 9) so a post-breakfast start is not refused.
  Code + 4 new tests + doc; suite green 122 passing, 100% lines/branches. The clock was always the courtesy
  check — the busy probe is the real gate, and `--force` still cannot override it.
- **Rollback RULED — shadow columns only, no `pg_dump`.** Rick: *"Either we successfully write all of the
  shadow columns with the new embeddings or we don't… If it fails we drop the shadow column."* Failure mode
  is a wasted GPU hour, not lost data.
- **The GPU is NOT the constraint the old write-up implied.** `AdaptiveBudget` grows the batch empirically
  (×1.5 per success, halve on refusal, floor 5k / ceiling 2M chars), so on an emptied card it climbs on its
  own — 40,000 is a starting point, not a ceiling. Watch the "final char budget" the fill prints; that number
  is the empirical ceiling of the real hardware and it is the measurement we still lack.

**The one honest unknown**: the DB write side (~289,000 UPDATEs) is unmeasured. The oft-quoted ~16 minutes
is EMBEDDING TIME ONLY. Step 3 exists to replace that guess with a number before anything large runs.

---

## 📉 TO QUANTIFY 2026-08-14+ (Rick's observation, recorded by Cheech 🌿) — the token-burn drop

**Rick, 2026-08-13 end of day, explicitly flagged as ANECDOTAL and to be revisited "after a couple full days
of hard burn."** Recording the numbers now so tomorrow's quantification has a baseline to argue with, not a
memory to reconstruct.

**What he observed** — two independent readings, same direction:

| Reading | Before | After |
|---|---|---|
| Share of all tokens burned via the cosa-voice MCP server | **80+%** pre-KISS-protocol → **50+%** post-KISS | **~30-some %** today, first partial day of the DM tutor |
| Fleet-wide burn rate (third-party aggregator, all Claude Code calls) | **14,000–22,000 tok/min** | **~7,000 tok/min** today, with **11 agents** running simultaneously |

**Before anyone converts this into a claim, the confounds have to be named.** I ran the DM verbosity pilot
that got fooled by exactly this shape of before/after comparison — it published p=0.047 at 14:00Z and the
final pull retracted it (no effect at this dose, A 0.051 / B 0.058, and **+7.3% tokens all-in** once the
75,506 burned on 272 refused drafts were counted). The failure was never bad arithmetic; it was comparing
periods that differed in more than one thing. Today differs in at least five:

1. **Three interventions landed together** — the KISS/brevity mandate, the DM tutor (live 14:14 UTC, boot
   #56), and the tutor's own same-day fixes (dropped agency, dropped paths `06c3eb29`, invented-person
   refusal `a28c24b6`). A single before/after cannot apportion credit among them.
2. **"Share of tokens via MCP" has a denominator.** A drop in the share is equally consistent with MCP
   traffic falling *or* with non-MCP work rising. Both numbers have to be reported, never the ratio alone.
3. **Tokens per minute is not tokens per unit of work.** 11 agents at 7,000 tok/min is a rate, not an
   efficiency — the same figure results from agents thinking harder about less, or from a quiet evening.
4. **A partial day is not a day**, and today's shape was unusual: a fleet-wide wind-down from ~23:30.
5. **The tutor clips the tail by construction** — measured on the pilot corpus (`6bfd4223`): rejecting at
   p99 = 149 and max = 150, the threshold itself visible in the data, while sentence count barely moved
   (8 → 7). María's corollary stands: a delivered tail under a gate is the gate's configuration, so
   delivered tails must never be compared across a gated and an ungated period.

**What would actually settle it**: tokens per delivered unit of work (per DM, per row closed, per commit),
segmented by MCP vs non-MCP, over two full comparable days — the "couple full days of hard burn" Rick
already named. The corpus for the DM half exists at `<projects-data>/lupin/dm-corpus/` with every row
provenance-stamped, and `analyze_arms.py` raises `FileNotFoundError` rather than silently reading the
retired file, so the measurement is reproducible.

**Sequencing**: this is explicitly AFTER the embedding regeneration above — that is the first and only thing
tomorrow starts with.

## 🦚 FINDING 2026-08-13 (Krishna `d901908f`, row e0bb5a94) — orchestrator.py pre-existing coverage gap

While adding the defect-B assertion tests I found `orchestrator.py` sits at **99% branch coverage**, not the
mandated 100%: three lines are uncovered — **85** (`timeout_seconds must be a positive int` raise), **114**
(a `return (` continuation), **1164** (the `**Approval**: {auto_notice}` abstract line). All three blame to
`414009c3c`, i.e. **pre-existing debt** unrelated to defect A/B — my two new tests only ADDED coverage (they
closed the previously-uncovered stop_reason branches at 1343/1430). Left out of the A/B scope on purpose;
recorded here per today's no-new-rows order.

## 🚚 LIVE 2026-08-13 (Mr. Radio 🦉 `a31a20c5`) — the tutor is in use; two questions land here

**Commit `b8d10bd3`, force-recreated onto `:7999` at 14:14:10 UTC (boot #56).** Rick's order:
*"implement it fully and make sure it's actually in use."* Trigger lowered to **>4 claims**, two-arm pilot
**suspended**, every corpus row **provenance-stamped**, corpus **moved out of the repo** to
`<projects-data>/lupin/dm-corpus/`. Unit suite 13,562 + 386 deploy green.

**Proven live, not asserted** — first real DM after the recreate (row 1 of the new corpus):
`tutor_fired=True · outcome=rewritten · claims 5→3 · words 93→26 · git_sha=b8d10bd3 · port=7999`,
and `effective_arm=None` confirming the pilot no longer assigns arms.

Both items below are **for Rick's word, not owed work** — his 2026-08-13 broadcast prohibits adding board
items today, so they are recorded here rather than minted as rows.

### 📥 TAKEN 2026-08-13 (from María 🌸, diagnosis complete) — a no-git-ancestor cwd should say so ONCE

María closed the "eight tmp MCP failures" investigation with a root cause rather than a question, and the
finding worth remembering is that **our own documentation caused it**: the old `cd /tmp && claude mcp get …`
line told people to do the thing that breaks project detection. Last incident is 2026-07-13, the day that
line was removed; nothing in the month since. The worktree variant was closed by worktree-aware detection,
and the remainder was one night of repros from a scratchpad.

**What is left is mine and it is small**: a cwd with **no git ancestor** is a *knowable, permanent*
condition, so firing `CRITICAL: COSA-VOICE MCP VALIDATION FAILED` on **every connection** is the wrong
shape — it floods the operator with an urgent alarm that repetition cannot help. It should say it once.

Diagnosis: `planning-is-prompting/src/rnd/2026.08.13-defaulted-cwd-tmp-sessions-diagnosis.md` (her `5ef637e`)

### 🔬 OWED 2026-08-13 (Cheech 🌿) — the tutor loses AGENCY and TENSE, and there is a test set for it

Not a threshold problem — a **prompt** problem, so raising the trigger would not touch it. Cheech's
exhibit, from the live corpus: I wrote *"Force-recreated from committed code at b8d10bd3… I carried the
real interactive-test credentials forward"*; what he received was *"Deployed from commit b8d10bd3…
interactive-test credentials transferred."* Three losses in one sentence — active to passive, my agency
erased, and **`force-recreated` flattened to `deployed`**, which destroys the exact
restart-versus-recreate distinction that was load-bearing all morning.

**Method, his and accepted verbatim**: the corpus holds **12 `tutor_fired` rows**, each carrying the
original and the rewrite side by side. Build the regression from those real pairs and **require it to FAIL
on them BEFORE touching the prompt** — otherwise a prompt edit cannot be shown to have fixed anything.

**NOT STARTED.** Recorded so it is not assumed done.

**Already shipped in response** (`a1df14f0`): the recipient now sees `DM_TUTOR_NOTICE` on any rewritten DM,
so a reader knows the wording is not the sender's before quoting it back at them. That closes the
*provenance* gap, not the *fidelity* one above.

### 📏 PRACTICE NOTE 2026-08-13 — a HELD row must be PARKED, not left queued

Found while handing my board over: `5bc22180` carried **"HELD by Rick 2026-08-05"** in its own
title and was still sitting in the **queued** count. So it read, every time anyone looked, as
available work nobody was picking up — when the human had already ruled it not-now.

**Why it matters beyond one row**: today's directive was to run the board down from 70, and a
burn-down number that includes rows nobody is allowed to work is a fiction. The store already has
the right shape for this — `parked` requires a `park_reason` quoting the row's own decisive
sentence plus a `next_chase_ts`, so the hold is bounded and self-expiring rather than silent.

**Scope, measured rather than assumed**: I checked the queued lupin board and found **this one
row**, not a pattern. Recording it as practice, not as a systemic finding — the honest version is
"one row was mis-statused", and it is now parked with a chase at 2026-08-20.

**The rule**: when a human holds a row, park it that day. Leaving it queued costs nothing visible
and quietly corrupts every count taken afterwards.

### 🪵 FOUND 2026-08-13 (Cheech 🌿 + Sam 🎙️) — a log line that says "fault" during normal operation

`queue_consumer.py:123` prints **"Monopoly hold active — deferring FOREIGN intake (lineage children
pass)"** — and it fires whenever there is *no admissible child in the queue this tick*. Read the loop:
`pop_next_eligible(predicate=_is_admissible_child)` returns None and the line prints. That happens in
the completely healthy case where children were **already admitted and are currently running**, so
nothing is left to admit.

**It cost three people about three hours today.** A gapless 17-minute run of that line was read as
"children are stuck behind the monopoly hold", and the true reading was "the children are running fine
and nothing new is waiting". It produced an escalation to me that a green test was lying, a wrong
reopening of `0c4e8cfa` by me, and a retraction of both. Resolved only when Sam ran `ts-c81091ff` and
watched both children get **admitted** — render-only rendered phases 6→8.5.

**Fix**: say what is true — something like *"monopoly hold active; no admissible lineage child this
tick"* — and distinguish "a foreign job is being held back" from "nothing is waiting". They are
different facts and the line currently prints the alarming one for both.

**The real gain from the whole exercise** was Sam's, and it stands: `test_presentation_render_only_smoke`
carried no `parent_id_hash` while its two siblings did, so its child genuinely was foreign by
construction. Fixed. There is **no consumer bug** — do not let anyone edit Gate B on the strength of
this log.

### 🧵 THE DAY'S THROUGH-LINE (2026-08-13) — five instruments, all aimed slightly off

Worth reading together, because the same defect wore five costumes in one day and each was found by a
different person:

| Instrument | Said | Meant |
|---|---|---|
| Presentation E2E harness | PASS | never looked at the pptx |
| Gate-reachability allowlist | covered | catches *new* files, not existing ones that **grow** |
| Quality judge length detail | a grade | also handed the sender the target |
| `deferring FOREIGN intake` | a fault | the queue is idle and healthy |
| My own tutor probe | "works" | worked on a *synthetic* doc, not the real input |

**The shape**: each was a check whose output did not mean what its name implied, and every one survived
because reading the name was cheaper than reading the mechanism. **The counter that worked, every
time, was going to the primary artifact** — the served schema, the gated collection, the corpus row,
the actual log loop, the tree.

### ❓ OPEN FOR RICK — the spoken TTS rider still names a word count

His DM instruction was *"three sentences and a path with no word counts to be found anywhere."* The DM
composition contract now matches that verbatim. **The spoken TTS rider still says "≤3 sentences AND ≤60
words", and I deliberately did not strip it.**

That number is not a style rule — it is derived from the server's hard ~500-character spoken cap
(`spoken_word_budget()` in `hook_common.py`, at a deliberately pessimistic 8.3 chars/word). Overshooting
the cap **rejects the whole call silently**, which reads as the assistant going mute. Removing the only
countable form of it trades a visible instruction for an invisible failure, on a different channel from
the one his instruction was about.

María agrees and is saying the same in her note, so he gets one story from both of us. **His call.**

### 🧭 FOUND 2026-08-13 (Cheech 🌿 `6794a377`) — the fleet can MAKE a manager, and it took all day to notice

**By ~13:30 all three managers were over budget** — María 63%, Mr Radio 75%, me 83% — while both
workers sat at 21% and 28%. Workers are restorable by re-spin; **managers are not**, so capacity drains
from the supervising layer while the layer that has a mechanism stays healthy.

**Five people spent four hours optimising inside a frame nobody questioned.** We built: a transfer rule
(rows move, seats do not), a precommitted trigger, an orphan-recovery note, staged respawn briefs, a
reap-then-respawn-under-new-lineage move, and a placeholder rule for stale seed paths. Every one is
correct and now in `4c`. **Not one of them asked whether the set of possible receivers was fixed.**

⇒ **`spawn_sessions` takes `role="manager"`.** A fresh manager seat starts near zero. Handing an
exhausted manager's seats to another exhausted manager relocates the wall; spawning a new one
**restores capacity**. María fired it immediately on hearing the phrasing, and did it EARLY rather than
at her trigger, because a new seat only helps if it is warm before the deadline.

**Why this is a doctrine finding and not a tip**: the question "who can receive?" has a fixed-set
shape, and a fixed set is exactly what a tired reader stops re-examining. The whole day's escalation
ladder — precommit, stage, transfer, recover — is the shape of good work inside an unexamined
constraint. **It was equally true at 09:00 and nobody said it.**

**Suggested for `manager-context-monitoring.md`**: make "spawn a fresh manager" the FIRST option at the
ceiling, ahead of transfer, and make it fire early enough that the new seat is warm. Transfer is the
fallback when a fresh seat cannot be had, not the default.

### 🔴 FOUND 2026-08-13 (Cheech 🌿 `6794a377`) — `dismiss_sessions(write_memento=True)` REPORTED SUCCESS AND WROTE NOTHING

Found by executing the first two re-spins under the new manager-context policy, roughly ninety minutes
after it went live. **This is the policy's own machinery failing silently in the step the policy exists
to protect.**

**What happened.** Krishna was reaped with `write_memento=True` and `respin_personas=["krishna"]`. The
call returned clean — `dismissed: killed`, `retained_owner_personas: ["krishna"]`,
`retained_unmatched: []`. The ownership half worked exactly as documented. **No memento was written.**
The newest `krishna-*.md` on disk is `krishna-fc56ee39.md` dated **2026-08-05**, eight days stale, and
`io/mementos/krishna.md` still points at it. Nothing in the return value distinguishes this from success.

**Why it did not cost anything.** Because his predecessor had been told to write the state into the ROW
(`e0bb5a94`), not only into a memento. His successor's first message back was *"Continuity was in the
row (memento was lost as warned)."* Had we relied on the flag, a P1 mid-investigation would have come
back with a root-cause finding, a captured evidence body, an approved-but-unimplemented fix design, and
five remaining steps — all gone.

**The trap for the next reader**: seeding the stale file would have been WORSE than seeding nothing. An
eight-day-old memento from unrelated work reads as current context. I spawned with no seed and an
explicit "do not read any krishna-*.md" in the brief.

**What worked instead, and should become the rule.** For Sam's re-spin I had him write the memento
himself through `memento_io.py write` BEFORE the reap, then **verified the file on disk** — record,
mirror, pointer, sha `16da46f2` — and only then dismissed. That is two extra steps and it is the
difference between a handoff and a hope.

**Proposed**:
1. **Do not trust `write_memento=True`.** Have the worker run `memento_io.py write` at checkpoint, as
   part of "prepare for re-spin", and have the manager `ls` the record before reaping.
2. Fix the verb so a failed memento leg is LOUD — the same `write` script already fails non-zero when
   any leg fails, so the reap path is not using it, or is swallowing its result.
3. Standing regardless of the fix: **worker state belongs in the ROW.** A memento is a convenience; the
   row is the record. That is what actually carried this handoff.

### 🔴🔴 FOUND 2026-08-13 (Cheech 🌿 `6794a377`, confirmed by Mr. Radio 🦉) — the tutor INVENTED A PERSON WHO DOES NOT EXIST

**This is a different severity class from everything else on this page.** The earlier findings are
*losses* — agency, tense, paths. This is a *fabrication*: the rewrite added an actor to a technical
report who was never in the original and does not exist.

**What Mr Radio actually wrote** (his words, after I asked him to restate): he is at 52%, his memento
is written, and he would not rule on row `e0bb5a94` from my relay of Krishna's finding — *because it
agreed with his own earlier result, and that is when he trusts a relay least*. He asked that Krishna
put it on the row directly instead.

**What reached me**: three sentences about *"the reviewer"* — that "the reviewer is asking for
additional documentation before they can approve the changes", that "the reviewer has confirmed the
changes are correct and the commit hash matches", and that "the reviewer is asking for the specific
details of the test that was run." Plus his memento path, dangling.

**There is no reviewer.** Not on that row, not in that exchange, not anywhere in the thread. The tutor
manufactured a third party, gave them opinions, and attributed an approval state to them.

**Why this outranks the other findings.** A dropped path is *visibly* missing — I noticed instantly and
asked. A dropped agency is recoverable by checking the artifact. But an invented actor **reads as
signal**: a manager told there is a reviewer awaiting documentation has every reason to go produce it,
chase a person who does not exist, or — worst — record "reviewed and approved" in a row. Nothing in the
message looks wrong. It cost nothing here only because the message was *also* incoherent enough that I
refused to act on it and asked for a restatement.

⚠️ **The near-miss is the whole point**: my instinct on receiving it was to work out *which* reviewer
and *which* change. Had the fabrication been cleaner, I would have.

**What this bears on**: Rick's still-open teaching question. The word saving is real and measured. This
is the other side of the ledger, and it is not a tuning problem — a rewriter that can add a fact can
add any fact, and no threshold setting bounds that.

**Suggested, in order of cost**:
1. Treat any invented ENTITY as a hard failure in the prompt regression, not a quality score. The 12
   real original/rewrite pairs already in the corpus are the test set; add this exchange as pair 13.
2. Consider a structural check — an entity/noun-phrase diff between original and rewrite, flagging any
   actor present in the output and absent from the input. Deterministic, like the pointer fix.
3. Until then, the standing rule that saved this one: **when a DM's subject is unclear, ask for a
   restatement rather than reconstructing it.** Do not infer the missing half.

### 🩺 FOUND 2026-08-13 (Cheech 🌿 `6794a377`) — the tutor drops PROVENANCE, and that is a different cost from brevity

Not an objection to shipping it. A measured side effect from the first hour of live use, recorded so the
teaching question gets decided on the whole ledger rather than the word saving alone.

**The near-miss.** Krishna reported the outcome of row `0c4e8cfa`. What reached me read as *"the routing
problem has been identified and fixed, commit `587e399a`, Gate B now admits."* I was one step from calling
it a scope violation — the row's own text says **DO NOT fix the consumer's intake logic** and I had
repeated that in his brief. One `git log` stopped it: **`587e399a` is dated 2026-08-04**, authored nine
days ago by someone else. Krishna had changed nothing. He had *proved the inference and found it already
fixed* — which is a completely different report, and the correct one.

**What the compression removed was not words, it was agency and tense**: who did it, and when. A rewrite
that keeps every claim can still convert *"I found that someone already did X"* into *"X has been done"*,
and the passive voice is exactly where a compressor lands when it is squeezing.

**Why this is worth Rick's attention and not just a caveat**: the failure mode is a manager acting on a
worker's report. It is silent — both parties believe the message was faithful — and it is *biased toward
the reader blaming the sender*, because the sender's carefulness is what gets compressed away.

**Cheap mitigations, none of them "turn it off"**, in rising cost:
1. Have the tutor preserve **dates, commit shas and actor names** verbatim, as it already preserves paths.
   These are the provenance-bearing tokens and they are cheap to whitelist.
2. Surface `tutor_fired` **to the recipient**, not only in the corpus, so a reader knows the prose is not
   the sender's and can ask before acting on it.
3. Standing rule for the fleet, free and already in force on my crew: **when a hedge or an attribution is
   load-bearing, verify against the artifact, not the message.** That is what caught this one.

⚠️ **Also stale, and I am not fixing it because I should not restate the number**: the ruling section
further down this file still describes the trigger with the pre-2026-08-13 value, which the top of this
same file has already superseded. Mr Radio owns that line. Two different numbers for one threshold in one
document is the condition the `NEVER DISCLOSE` comment in `lupin-app.ini` exists to prevent — a reader who
believes the stale one writes to the wrong shape.

### 🔧 FOUND 2026-08-13 (Mr. Radio 🦉, flagged by Cheech 🌿) — `--force` bundles three unrelated guards

`bounce-dev-server.sh --force` waives **three** independent things at once: the unwarned-fleet pause, the
running-job refusal, and the **dirty-tree confirmation**. I wanted the first and silently got the third,
so boot #57 deployed five uncommitted `deep_research_to_presentation` files of Krishna's. No harm — the
app booted clean and the added field is optional and additive — but it went out **ungated**, and Cheech
proved it by diffing the *served* schema against committed HEAD rather than taking anyone's word.

**The defect is not "somebody used `--force`"** — it is that one flag waives guards that protect against
unrelated failures. A caller who wants to skip a five-second pause should not thereby stop checking whose
uncommitted work they are about to serve. **Proposed**: split into `--no-pause` / `--allow-dirty` /
`--kill-running-job`, keeping `--force` as all three for compatibility. Not done today — it is a change to
the bounce path while the fleet is bouncing, which is the wrong hour for it.

### 🗃️ DONE 2026-08-13 — the accumulating corpus was still inside the repo

Caught while answering María's read-out. This morning's move relocated the six **tracked** run files but
missed `src/tmp/dm_traffic.jsonl` — the live 4.5 MB sink, gitignored but still in the tree and therefore
on `git clean -xdf`'s list. All **3,242** historical rows are now merged ahead of the post-recreate rows
in `<projects-data>/lupin/dm-corpus/dm_traffic.jsonl`, verified chronological and line-for-line before the
in-repo copy was retired (kept on disk as `.retired-2026.08.13`, delete on Rick's word).

**Also answered**: the `blind`/`rejecting` split is NOT missing from the corpus. It lives in
`effective_arm` (1,178 / 841 over 2,019 rows); `arm` and `effective_arm` are disjoint by María's own
2026-08-03 design, so `arm` reading only `signal_only` is the design working. Zero rows carry both.

### 🔎 FOUND 2026-08-13 (Mr. Radio + Cheech 🌿) — two thresholds collide at 150 words

`dm qualitative word limit = 150` (above it the judge skips directness+tone) and `dm experiment reject
threshold words = 150` (the rejecting arm refuses over it) are **the same number**. So the rejecting arm
only ever admitted rows guaranteed to get a qualitative grade, while blind let longer ones through and
their `overall` fell back to length-alone.

**Measured by Cheech**: split on 150 words, both arms populate directness at *exactly* 96.5% under the
ceiling; at or over it blind is 1.4% and rejecting has 5 such rows total. So there is **no arm effect on
the judge** — the gate selects the population and the ceiling does the rest. Not a defect: it is behaving
as designed. What survives is that **`overall` is not comparable across arms** (rejecting's set is 99.4%
under the ceiling, blind's 55.5% — different formulas on different populations).

`judge.py:179` already states that two related numbers must not coincide, for the same class of reason.
Moot while the pilot is suspended, but it must be settled before any arm comparison is published or the
pilot is ever resumed.

---

## ⚖️ RULED 2026-08-12 (Rick) — ship the tutor FLEET-WIDE; the teaching question stays OPEN

**The ruling**: *"Let's ship the tutor fleet-wide and leave teaching open."* Take the word saving now
— it is certain and needs no experiment — and stop trying to buy the teaching answer in the same move.

> ⚠️ **SUPERSEDED 2026-08-13** — this block records the 08-12 ruling **as it was made**, and its trigger
> value is no longer in force: Rick lowered it to **>4 claims** on 08-13. Left standing rather than edited
> because a decisions log that quietly rewrites itself cannot be audited; the live value is at the top of
> this file and in `dm tutor trigger claims`. Flagged by Cheech 🌿, who correctly did not restate either number.

**What ships**: the tutor on every DM at the then-ruled trigger of **>6 claims** (now >4), runtime-configurable, **no
output gate** (also runtime-configurable, default off). Expected: the average DM goes from ~8 sentences
/ 123 words to **4 sentences / 62 words — half of every word the fleet sends**, on ~1,634 calls per
2,951 DMs.

**What is NOT built**: no third arm, no recipient randomization, no assigner, no ledger. The two-arm
`blind`-vs-`rejecting` block is set aside as its **own finished question** — analyse and report it
standalone (does refusing an over-long DM make senders write shorter), never folded into the tutor's.

### 🔓 OPEN — does reading short DMs teach you to write them?

Unanswered, deliberately. **Every cheap route to it is closed**, and that is why it is parked rather
than queued:

- **Before/after against the existing corpus is dead.** María's phase 1 (the sentence rule in global
  `CLAUDE.md` + the spawn rider) shipped 2026-08-12, so any post-tutor comparison confounds the doc
  rewrite with the tutor, inseparably. The baseline is also not untaught — 1,136 of 1,945
  in-experiment rows were sent under the `rejecting` arm, which is itself a treatment.
- **Day-level noise is large** even on the clean slice (blind + legacy `signal_only`, 2,001 rows):
  SD of daily medians **31.6 words**, and only 7 usable baseline days — capping a pre-post design at
  roughly a 40-word MDE no matter how long the "after" side runs.
- **The design that would work** is recipient-randomized, costs ~5 weeks at MDE ~17 words, halves the
  word saving while it runs, and needs `in_reply_to` + `context_epoch` + a disclosure change.
  → `src/rnd/v0.2.0/2026.08.04-dm-verbosity-reduction/2026.08.12-recipient-randomized-teaching-experiment.md`

**If it is ever reopened**: run it against a **post-doc-change** baseline so the instruction lever is
already pulled on both sides. And note the ceiling — the tutor cannot teach across a re-spin, so
anything durable has to ride the memento or the spawn brief, not the tutor.

### Implementation order when the fleet-wide ship is picked up

1. Wire `rewrite_dm()` into `execute_dm_send` (`dm.py:1008`) — it exists and is fail-closed; nothing calls it.
2. Record **submitted** and **delivered** on the corpus row (`_persist_dm_row` takes one `body_text`, two call sites) plus `tutor_fired` / `tutor_outcome`, recorded not re-derived.
3. Tests to the 100% gate at every tier.

---

## 📥 FINDING 2026-08-13 (Krishna 🦚 `effddeae`) — dr2p slide-count plumbed backend-only; the research→slides form has NO duration UI to mirror (row 880d2801)

`target_slide_count` is now plumbed through the deep_research_to_presentation chain (factory → job →
agent → inner PresentationConfig override), the dr2p REST request model, and the CLI (`--slide-count`),
mirroring `target_duration_minutes` exactly. Landed in the same commit as this note; agent/job/router
100% covered.

**The frontend piece is a real scope fork, not a skip.** The row asked to "surface it in the frontend
job-submit form," but the research→presentation path in `notifications.js:3124` **hardcodes**
`body.target_duration_minutes = 15` with **no UI input** — there is no duration control to mirror for
slide count on that panel. The only duration input (`#presentation-duration`, notifications.html:418)
belongs to the DIRECT presentation panel (`/api/presentation-generator/submit`, notifications.js:3391),
a different path. Options for a follow-up: (a) add a slide-count numeric input to the research panel
(new UI — duration itself isn't exposed there either), (b) add it to the DIRECT presentation panel for
parity, (c) leave the UI as-is since slide count is now controllable via API + CLI. Deferred to Rick's
UI call per today's no-new-store-rows order.

---

## 📥 FOLLOW-UP 2026-08-13 (Krishna 🦚 `effddeae`) — the CBR store is 100% poison for batches; cleanup deferred (NOT a store row per today's order)

**Parent**: bug cdb5a76f (expeditor CBR returned a different question set's answers). Fix landed in
`src/cosa/agents/prediction_engine/prediction_engine.py` — batches now key on their per-question
content, not the count preamble.

**The poison count (read-only, live Postgres store, 2026-08-13)**: of 46 `open_ended_batch` rows in
`prediction_decisions`, **all 46** are keyed on the content-free preamble. **32 share the exact string
`"I have 3 questions for you."`** with conflicting answers in one bucket — Vertex/judge/push, a podcast
`query`, and podcast `languages/audience` all collide there. (8× "5 questions", 5× "4 questions", 1× "6
questions".)

**Why cleanup is not urgent — MEASURED, not inferred**: (1) the auto-submit hazard is closed by
construction and tested — confidence 1.0 came only from the exact-match string compare, and a content
key never equals a legacy preamble. (2) Read-only real-embedding probe: cos(content key, legacy
preamble) = **0.43** for both podcast and vertex batches, far below the **0.85** open_ended_cbr
retrieval floor, so a poison row is not even retrieved for a content-key query; the two live batches
sit at 0.53 to each other (also below floor). These rows are **inert by measurement**, not actively
harmful. Cleanup removes the last theoretical wrong-suggestion path — hygiene, not a live-hazard fix.

**Deferred to Rick**: deleting/re-keying 46 live rows is destructive; Cheech's call was "get the number
first, don't delete." The number is above. Options when ready: (a) leave inert, (b) hard-delete the 46,
(c) re-key by re-deriving content from each row's `decision_value` answers keys. Recommend (b) — the
answers keys don't reconstruct the original question texts reliably.
Read-only counter: `scratchpad/count_poison.py` (session effddeae).

---

## ✅ CLOSED 2026-08-13 (Sam 🎙️ `94f3bfed`) — row 89bfcc8f done on harness scope; two residual lessons kept here

Row 89bfcc8f closed `done` on harness scope. All six harness defects are fixed and proven
live end-to-end on :8000 run `ts-c81091ff`: the classification reads honest **NOT EXECUTED**,
never a false `FAILED 0/0/0/0` and never a false green. Commits (held for Rick, NOT pushed):
`b9450146 99fbca8d f136f965 5c59d144 79fcf083 c37443f5 df866b60 7b630a42`.

**Not the harness's fault (out of scope, unreproducible):** the real-generation Sonnet child
`pr-aeeaef3c` died — *"Elaboration returned no usable slides"* after ~10.5 min (~$0.46 lost, no
deck). It got a well-formed 15-slide outline; the elaboration LLM response simply lacked the
top-level `slides` key and the strict parser refused to fail-open. The code that produced it was
Rick's reverted-uncommitted deploy, so there is no repo copy to fix — belongs in front of
whoever next stands in the elaboration path.

**Two residual lessons (no owner, no row):**
1. **A deferred job lives only in memory — capture evidence at submit time, not by polling.** A
   16:10 `docker restart lupin-rest-test` (to serve a fix) erased the in-memory deferred children
   from an earlier run, making their lineage unrecoverable. The submit-time lineage probe
   (`7b630a42`) is the durable fix: log `{harness, env token, stamp}` at submit, restart-proof.
2. **`test_presentation_dry_run_smoke.py` still lacks the `parent_id_hash` stamp** (Mr Radio noted).
   Latent, low priority — it is NOT in the regression runner, so it can't cause a deferral there.
   Cheech's call: do not sweep it now.

## 📥 FINDING 2026-08-13 (Sam 🎙️ `00aa8745`) — presentation regression fix #2: the internal jobs still can't run headless (row 89bfcc8f, fix #1 landed)

Row 89bfcc8f had two fixes. **Fix #1 is landed** (commit `b9450146`): a 0/0/0/0 tier
now reports **NOT EXECUTED**, never the false-red FAILED — honest labeling across the
per-suite notify, overall banner, report table, and abstract.

**Fix #2 is NOT done** and is a larger, separate effort (kept here, not a new board row,
per Rick's 2026-08-13 no-new-rows order). Make the regression's internal presentation
jobs runnable headless on :8000:

- **Submit 404 — NOT REPRODUCIBLE TODAY (presumed stale container; NOT "fixed").** 2026-08-13:
  `preflight-test-container.sh` is green (mounts applied) and an OpenAPI read of both servers shows
  `/api/presentation-generator/submit` **is served on :8000 and :7999** (153 routes each). Presumed cause of
  the 08-05 404: a stale/unmounted container serving code without the route. A mount that went stale once can
  go stale again — this is not a code fix, it is "cannot reproduce now". No code change owed unless it recurs.
- **The other two are reachable by TARGETED tests, not a money run** (Cheech, 2026-08-13): the offline-gate
  fail-open default is a unit test around the gate/proxy default; the junit shape is a unit test around
  `_parse_non_pytest_stdout` / the `SUITES_SUPPORTING_JUNIT_XML` decision. Exhaust these cheap instruments
  before buying a real-money :8000 regression run.
- **Junit shape — FIXED, commit `99fbca8d`.** Dropped `presentation` from `SUITES_SUPPORTING_JUNIT_XML`
  (so no `--junit-xml` is injected into the multi-tier orchestrator that ignores it → no more phantom-file
  FileNotFoundError) and taught `_parse_non_pytest_stdout` the presentation tier summary
  (`Total: N tiers / Passed: N / Failed: N`), same treatment as the websocket runner. 5 new unit tests;
  144 test_suite job tests pass. A successful run now parses as tier counts instead of 0/0/0/0.
- **Offline gate — the fail-open default ALREADY EXISTS (no code owed for the primary gate).** The
  presentation orchestrator's review gate sets `response_default` so a 503/undeliverable ask resolves to
  the continue value instead of raising `VoiceGateNoDefaultError` (orchestrator.py ~1844-1847, from the
  dead-letter fix for job `pr-b1ea3708`), and the notifications gate endpoint honors defaults
  (`notifications.py:1227` returns the default on the offline path). So the row's "fail-open gate default"
  is implemented. The 2026-08-05 503 was either pre-that-fix or a residual ungated ask on a path only a
  LIVE run would surface — and that repro is **entangled with open P1 `0c4e8cfa`** (a monopolize test job
  suspected of deferring its own presentation child as foreign intake, so no scheduled presentation test
  may complete on :8000). Cannot pinpoint or verify without a run that is itself blocked.

⇒ **Fix #2 status**: junit reporting FIXED (99fbca8d); fail-open gate already in place; submit-404
~~not-reproducible~~ **IS reproducible — double-root path bug, see RUN COLLECTED below**. `0c4e8cfa` is NOT
a blocker (fixed 08-04 by 587e399a, per Cheech). Cheech authorized a minimal live verification.

⭐ **LIVE :8000 VERIFICATION RUN SUBMITTED — RESULT TO COLLECT.** job_id
`ts-3caa2ce9::50c73ba7-36dd-4eaf-a7e2-63256252c84f` (test_types=presentation, render+Sonnet only,
auto_fix_on_failure=False, scheduled 2026-08-13T11:08:05-04:00, ~8min ~$0.46). Verifies the headless
scheduled path completes with real tier counts and NO residual 503. **Collect it**: poll
`/api/get-queue/done` on :8000 + read container logs for a "User is offline and no default response
provided" 503; RECORD THE OUTCOME EITHER WAY (a clean no-503 run is the proof as much as a 503). Submitted
under a re-spin checkpoint; Sam re-spun right after. Row 89bfcc8f amended with the same job_id.

⭐ **RUN COLLECTED (Sam 🎙️ `5252b3a0`, 2026-08-13).** Job `ts-3caa2ce9` completed on :8000 (status
completed, 7.5s): "presentation: 0 passed, **2 failed**, 0 errors, 0 skipped" — REAL tier counts, not
0/0/0/0. Report: `io/test-suite/2026.08.13-at-11:08-EDT-presentation-results.md`.
- **THREE HARNESS FIXES PROVEN GREEN in the live headless path**: (1) **NO 503** — zero "User is offline
  and no default response provided" in the run window (`docker logs -t`, 15:08:05→15:08:14 UTC); fail-open
  holds. (2) **junit clean** — no in-window junit exception (the log's FileNotFoundError is dated 20260805,
  the OLD run). (3) **0/0/0/0 fixed** — honest "2 failed" reported.
- **CORRECTION: submit-404 IS reproducible** (I had it wrong as "not reproducible"). Root cause reproduced:
  the render-only smoke test (`src/tests/smoke/test_presentation_render_only_smoke.py`) sends `source_path`
  = the ABSOLUTE fixture path (`_resolve_fixture_yaml` → `{LUPIN_ROOT}/src/tests/fixtures/presentations/
  render-only-example.yaml`, passed verbatim). The submit handler (`presentation_generator.py:162-171`)
  treats a leading-`/` path as REPO-RELATIVE and prepends project_root again → `/var/lupin/var/lupin/...`
  → double-root → 404 "Source file not found". Live :8000 repro: absolute → 404; same file sent
  repo-relative → 200 queued. **Fix (mine): send `os.path.relpath(self._yaml_path, LUPIN_ROOT)` with a
  leading slash from `get_submit_payload`** (or a general relativizer). Control-prove before/after.
- **Failure #2 (Sonnet tier) NOT yet isolated** — only one submit/404 in-window; 7.5s total means tier 2
  never reached real generation; no second 404/error logged. Needs its own diagnosis.
- **Row status**: fix #2's HARNESS scope (0/0/0/0 + junit + 503 fail-open) is DONE and proven. Remaining to
  green-headless: the render-only double-root fix + tier-2 diagnosis. Row stays OPEN on those.

⭐ **FIX #2 REMAINING WORK LANDED (Sam 🎙️ `5252b3a0`, 2026-08-13)** — all offline-proven, 5 commits (not pushed):
- **Tier-2 diagnosed from the run's OWN stdout — no 2nd :8000 spend for diagnosis**:
  `/tmp/presentation-regression-latest.log` showed `unrecognized arguments: --content-model` → pytest
  rejected the flag pre-collection → tier failed in 5s (non-execution). Both failures were harness bugs.
- `f136f965` (A): register `--content-model`/`--lead-model`/`--yaml-path` in `smoke/conftest.py` (--timeout
  belongs to pytest-timeout). Control-proven: flags collect; unregistered still rejects.
- `5c59d144` (B+C): render-only `get_submit_payload` sends repo-relative path; handler 400-guards an
  absolute/==root path (Cheech both-ends ruling). Unit-proven (4).
- `79fcf083` (D1): `run_tier` classifies by exit code — 0→PASSED, 1→FAILED, else→NOT EXECUTED (code named,
  never green); summary emits Not-executed; script green only if FAILED==0 AND NOT_EXECUTED==0. `PYTEST_CMD`
  seam; 5 control cases (Cheech's three incl. mixed + unmapped-never-green).
- `c37443f5` (D2): `job.py` threads `not_executed` through `_classify_outcome` (5th arg), parser, notify,
  report, abstract, totals, cost_summary. A tier that never ran now reads NOT EXECUTED, not FAILED — closing
  the gap where the multi-tier script slipped a non-collected tier past fix #1. +9 tests; 108 green.
- **Final :8000 run AUTHORIZED by Cheech** (2026-08-13): a lying-harness row needs a real scheduled run to
  prove it now tells the truth; offline controls prove the classifier maps exit codes but NOT the composition
  (runner actually passes the flags conftest registers) — only the deployed invocation exercises that. Green
  will prove the HAPPY PATH only; the NOT-EXECUTED classification rests on the three offline controls (not one
  green run). Submitting after a bind-mount freshness check + list-pending.

⭐ **:8000 RUN ts-0ae6e18f RESULT (Sam 🎙️ `5252b3a0`, 2026-08-13) — NOT green, but the fix is PROVEN LIVE + a
new deeper defect surfaced.** Ran 1021s (~17min), so BOTH tiers reached real execution (the flags fix worked
— Sonnet no longer fast-fails at 5s).
- ✅ **Composition proven**: render-only submit returned **200** (repo-relative path fix live) → child job
  `pr-9eafa885` enqueued. The Sonnet tier COLLECTED and ran (flags registered live via bind mount).
- ✅ **D1 classifier proven LIVE on a GENUINE non-execution**: the script reported `⊘ NOT EXECUTED:
  sonnet-full (exit code 124 — tier did not run, 900s)` and summary `Not executed: 2` — a real timeout,
  correctly NOT EXECUTED (never a false FAILED). Stronger evidence than a happy path would have given.
- ✅ **D2 proven on THIS run's real output, offline + free**: feeding the run's actual summary
  ("Total: 2 tiers / Passed: 0 / Failed: 0 / Not executed: 2") through the NEW parser → `not_executed:2` →
  `NOT EXECUTED`. Closes the loop without a re-run.
- 🪞 **Irony (job-level 0/0/0/0)**: the :8000 server runs a BOOT-STALE parser (booted 13:21 UTC, predates D2),
  so the job-level result read `0/0/0/0 NOT EXECUTED` + a "STARTUP CRASH" mislabel — the very fix that stops
  0/0/0/0 is not being served yet. A `docker restart lupin-rest-test` (src/ is bind-mounted) serves D2 for
  future runs; it will NOT re-parse this frozen job.
- 🔴 **NEW DEFECT (goes here, not a row): the monopolize test-suite job defers its OWN presentation child as
  FOREIGN intake, so no presentation tier can complete headless.** Run-window log: after `pr-9eafa885` was
  enqueued (200), `[CONSUMER] Monopoly hold active — deferring FOREIGN intake (lineage children pass)` repeats
  every second for the whole run. The child is NOT recognized as a lineage child of monopolizer `ts-0ae6e18f`
  (the render-only/live smoke tests submit via `/api/presentation-generator/submit` with NO parent_id_hash
  linking them to the test-suite job), so the monopoly hold defers it forever → render-only times out at 120s,
  sonnet-full at 900s = ~1020s total (both exit 124). **This is the `0c4e8cfa` mechanism** the earlier TODO
  believed fixed by 587e399a on 08-04 — it is NOT fixed for the presentation-regression path. Fix direction:
  the smoke tests must stamp the child submit with the monopolizer's id as parent_id_hash (lineage), OR the
  monopoly hold must recognize the test-user's presentation children as lineage. Needs an owner — beyond this
  row's harness scope.
- **Row 89bfcc8f scope**: fix #2's HARNESS bugs (0/0/0/0, junit, 503 fail-open, submit-404, flag-drift, tier
  mislabel) are DONE + proven. The presentation regression still can't go GREEN headless because of the
  monopoly-child-deferral defect above — a SEPARATE issue, correctly surfaced (not masked) by the now-honest
  harness. Recommend the row close on harness scope with the monopoly defect tracked here.

**Shuffle sweep FINAL (3 seeds, both roots):** seed 1337 (clean) = 6 reds; seed 202 (clean, box quiet —
only DMs + the urllib submit ran, no concurrent pytest) = **3 reds = exactly the 3 genuine isolation-reds**;
seed 101 = DISCARDED (contaminated — I ran concurrent pytest during it; its ~126 extra lancedb/normalizer/
solution_snapshot reds appear in NO other seed). Cross-seed: the 3 isolation-reds are consistent (live
branch reds); polluter #4 (bfe TestResubmit ×2 + config canary) is order-dependent (in 1337, absent in
202) — confirmed live, correctly filed above. Polluters #2/#3 are GONE from every seed (fixes hold).

**Why parked, not attempted now**: reproduction requires a live `:8000` run that spends real
LLM money (~$0.46 Sonnet tier) and takes ~8 min, plus a scope call on the offline-gate default
that touches the proxy path. Verify container freshness first, then decide.

---

## 📥 FINDING 2026-08-13 (Sam 🎙️ `00aa8745`) — unit-suite polluters #2 AND #3 FIXED (row 69fb89cd closed on those); polluter #4 (config-singleton canary) LIVE + separately filed; 3 unrelated live branch reds filed

**Polluter #2 root cause + fix — commit `12e062f0`.** The two
`test_progress_group_passthrough.py::TestPodcastGeneratorVoiceIoPassthrough` victims were
**order-dependent by construction**, not the downstream of a dirty teardown. `voice_io.notify`'s
dispatch gate is `_force_cli_mode or _cosa_interface is None` — it does **not** read
`_voice_available` (which the tests patched). The core `_cosa_interface` global is `None` by default
and is set to the podcast interface **only as a side-effect of the first import** of
`podcast_generator.voice_io`. Once any earlier test imports that module, the victim's own import is a
no-op, the gate sees `None`, and notify prints instead of dispatching. Proven with a `sys.modules`
probe (failing order: `podcast_preloaded=True`, `_cosa_interface=None`; passing order: the import
re-configures). Every test that touches the global restores it faithfully — there was no polluter to
fix. **Fix**: pin both gate inputs as auto-restored `patch()` context managers. **Control-proven**
(Cheech's condition): breaking notify's real dispatch turns BOTH pinned tests red — not a false green.

**Baseline both-roots run at HEAD+fix**: 4 failed / 22441 passed — and `progress_group` is GONE, so
polluter #2 is confirmed fixed in a FULL run. The 4 split cleanly:

- **`test_terraform_invariants` — polluter #3, FIXED — commit `f505c9f8`.** Mechanism:
  `test_envs_test_passes_terraform_validate` ran `terraform init` with `TF_PLUGIN_CACHE_DIR=PROVIDER_CACHE`,
  which DOWNLOADED the providers into `src/terraform/envs/test/.terraform/providers` on a cold cache — a
  shared-state WRITE that populated the very dir `test_terraform_provider_cache_is_present` asserts, so
  whichever ran first decided the other's result; the gitignored cache then persisted, self-healing the red
  ("moves between runs"). **Fix (Cheech ruling 2026-08-13): validate SKIPS loudly on a cold cache** (never
  runs init, never downloads, never populates; remedy in the skip reason), while **presence STAYS a hard
  RED** watchdog (honoring the author's "do not skip" for presence). Not a fixture that inits — that would
  MANUFACTURE the invariant under test and defeat the watchdog. **Delete-the-step verified both directions**
  in a fresh cold worktree: cold → presence RED + validate SKIPPED, identical in both orders, cache stays
  absent (neither repopulates); provisioned → both pass, full file 17 passed.

- **THREE LIVE REDS ON THIS BRANCH — not pollution, not order-dependent, not row 69fb.** These FAIL in
  ISOLATION at branch HEAD `3fc21826`, so the branch is genuinely red on them independent of anyone's
  collection order:
  - `test_gate_reachability_census::test_allowlist_has_no_stale_entries` — `find_stale_allowlist_entries`
    returns non-empty; the gate allowlist ledger has stale entries needing an update.
  - `test_gate_reachability_census::test_detector_reports_the_witness_when_not_allowlisted`
  - `presentation_generator/prompts/test_narrative_outline_elaboration::TestElaborationParser::test_parse_full_validation`
    — a real parser output mismatch on `out[1]["presenter_notes"]`.
  These deserve their own owner; they are pre-existing branch failures surfaced by this sweep, filed
  here per the no-new-rows order.

**Shuffle sweep — seed 1337 (both roots, file-order shuffle):** 6 failed / 22439 passed. `progress_group`
and `terraform` are GONE (polluters #2 and #3 confirmed fixed under a shuffled order). The 6 split into
the 3 live isolation-reds above (census x2, narrative) PLUS a NEW order-dependent set below.

### 🔴 POLLUTER #4 — LIVE, a DETECTOR FIRING (config-singleton pollution) — separately filed, NOT part of the 69fb close

Under the seed-1337 shuffle these three FAIL, and all three PASS in isolation (so: order-dependent, real
pollution — the same class 69fb was about, but a different, still-live polluter):

- `test_hermetic_config_fixture_b::TestHermeticModuleBoundary::test_config_singleton_is_virgin_at_module_boundary`
- `bug_fix_expediter/test_job::TestResubmit::test_success_debug_off_skips_final_print`
- `bug_fix_expediter/test_job::TestResubmit::test_success_pushes_and_returns_id`

⚠️ **The first one is a CANARY, not a flaky test — it exists to catch `ConfigurationManager` singleton
pollution.** Its red under shuffle means it is DOING ITS JOB: something really dirties the config singleton
before it. **DO NOT "fix" it by making it pass** — that disables the detector, exactly as making the
terraform presence watchdog green would have. The fix belongs in the POLLUTER (whoever leaves the
`ConfigurationManager` singleton dirty without restoring it), not in the canary. The bfe `TestResubmit`
pair are downstream victims of the same singleton pollution.

**Bounded repro / handoff**: seed-1337 file order at `/tmp/claude-1001/sweep_order_1337.txt`, full log at
`/tmp/claude-1001/sweep_seed_1337.log`. First step: bisect which earlier module leaves the
`ConfigurationManager` singleton (`_instances` / cached config) mutated; the canary names the seam, the bfe
victims are downstream. Needs its own owner — Sam handed off after closing 69fb on #2/#3 per Cheech's
"a half-done row you can finish today beats an open-ended hunt."

---

## ☀️ FIRST THING 2026-08-12 — resume the DM tutor (Rick's word, 2026-08-11 ~23:15)

**Rick read the implementation record and greenlit continuing.** His words: *"this is insanely
good news… let's return to this tomorrow first thing."* **This is the queued first item; start here
before anything else on the board.**

He also confirmed the short-band result reads as expected, not as a defect: *"obvious that DMs
shorter than 80 words compress the least — no surprise there."* So **the `<80` band's 76% is
understood behaviour**, and the open question below is about whether the tutor should *run* there
at all, not about why it compresses poorly.

**Pick up with the two rulings still owed** (below), then the small open items.

---

## 🌙 EOD 2026-08-11 (Mr. Radio 🦉 `c74141d6`, with María 🌸) — DM tutor agent built, two rulings owed by Rick

### FIRST THING — two things wait on Rick, neither is code

1. **Keep or veto the CDATA prompt line.** The plan said no prompt rewording; I added one requirement line to `dm-tutor.txt`, copied from `dm-compression.txt:34`. **Without it the agent cannot parse any DM whose prose contains an angle bracket** — that killed the first live call (`git show HEAD:<file>`). My argument: it is format plumbing for the standard path, the same category as the `{{PYDANTIC_XML_EXAMPLE}}` marker, not a change to what the model is asked to say. If vetoed, the prompt cannot ride `AgentBase` and that becomes the finding.
2. **His read of the 40 sample pairs** — still owed from earlier, and now the 200-run adds more. Every check we own is structural: slots present, pointer verbatim, word counts. **Whether a rewrite quietly reverses a meaning is the one question no harness answers.** Stamped doc: `/tmp/dm-tutor-samples-2026.08.11-1945.md` (⚠️ `/tmp` is swept nightly; regenerate with `tutor_sample_run.py`).

### What landed

`dm.txt` → `DmTutorAgent` on `AgentBase`, with `rewrite_dm()` as the fail-closed seam Rick asked for
(*"a DMTutor agent object that can be used within the DM send calls"*). 99 unit tests, 100% lines and
branches, full gate 13,529 green, 200-run 387/400 delivered, 250+ band compresses to **17%**.

→ `src/rnd/v0.2.0/2026.08.04-dm-verbosity-reduction/2026.08.11-dm-tutor-agent-implementation-record.md`

### Open, and small

- **The path checker is too strict.** `pointer in body` fails a value the model legitimately composed from several real paths. Should test each comma/semicolon-separated element and strip a leading label word. Until fixed its `NOT IN DM` count reads as a hallucination rate and **is not one** — all 9 were verified as real literals.
- **The prompt never says "exactly one" pointer.** "The most relevant" gets read as "the relevant ones" on long messages. One-word fix, but item 1 above should rule first.
- **The `<80` band barely compresses** (76% delivered). Worth asking whether the tutor should run on short messages at all — 3.1s to remove a quarter of a 60-word message may not pay.
- **Send-path integration is NOT done.** `rewrite_dm()` exists; nothing calls it. That is the "greater experiment" and was not in this cut.

### Carried, not mine

María 🌸 retracted her own headline on the stop sentinel after seeing n=200 (195 vs 192, floor of 4).
Her probe was not confounded — it varied the sentinel cleanly — but the sentinel and CDATA guard the
same failure, so once CDATA is in place the sentinel has nothing left to catch. **One message cannot
tell you which of two overlapping guards did the work.**

---

## 🌙 EOD 2026-08-10 (Mr. Radio 🦉 `df4207f2`) — pick up here tomorrow

**Two commits, both pushed**: `481f6a8d` (arbiter fleet-loop fix + deploy gate + loop liveness) and `af406cc9` (arbiter venv out of the deploy tree). 121 tests green.

### FIRST THING — one unverified claim

**The VM was powered down mid-check**, so the restart onto the new light venv at `$HOME/.venvs/lupin-arbiter` was never confirmed. Everything up to it passed: provisioning ran clean and its own import gate approved that venv (12 modules, DB closure correctly not required). The unit is enabled, so it should come up on boot.

```
gcloud compute ssh lupin-host-test --zone=us-central1-a --project=hello-world-foo-423219 --tunnel-through-iap \
  --command='systemctl --user is-active lupin-arbiter-app.service;
             journalctl --user -u lupin-arbiter-app.service --since "5 min ago" --no-pager | grep -o "interpreter .*" | tail -1;
             curl -s http://127.0.0.1:8001/health'
```

Expect: `active` · interpreter `/home/admin_rickruiz_altostrat_com/.venvs/lupin-arbiter/bin/python` · `degraded: false` with all four loops `alive`. **That last check is the light-venv proof** — the new venv has never had SQLAlchemy, so a live fleet loop on it proves the gate works in production, not just in a control.

If it comes up on the OLD interpreter, the legacy symlink is winning — remove `/mnt/lupin-data/lupin/.venv` and `/mnt/lupin-data/lupin/.venv-arbiter` (provisioning prints both commands rather than deleting them for you).

### Still open from tonight

- **`live_notify_disabled` at every arbiter boot** — `Environment 'development' not found in ~/.lupin/config`. The VM arbiter cannot send live notifications. Found, not scoped.
- **8 provider keys still absent from the VM** (`openai`, `gemini`, `groq`, `huggingface`, `kagi`, `mistral`, `google`, `anthropic-api-key-firewalled`). Each will fail exactly like `eleven11` did, and only in a log. Worth a preflight check that names them.
- **The deploy still chowns the tree to uid 1001**, a user that does not exist on that box. The arbiter venv is out of the way now; anything else living in that tree is not.
- Row `970002f1` stays open until the pickup check above passes.

---

## ⚖️ RULED 2026-08-07 (Mr. Radio 🦉 `61c3d613`, with María 🌸) — Arm 4 compression: FAILED EXPERIMENT, closed

**Rick's ruling**: *"Let's mark this down to a failed experiment. Even the larger models are unable to compress these messages…"*

**Measured**: 600 live compressions, three runs of 200. **3.0% of DM tokens saved where the economics needed 38%** — ~2,537 tokens/day against the plan's 32,028 (7.9%) — at 49 min/day of added delivery latency, which is a **floor** because recipient fan-out is uncounted.

**What is now excluded as the cause**:
- ~~the model~~ — larger models tried by hand against the committed prompt samples, no material improvement
- ~~the prompt's ratio instruction~~ — arm B named each message's exact target; 3.0% → 3.1%, and mildly counterproductive
- ~~placeholders as *the* cause~~ — density hurts (delivery 28% → 18%) but near-placeholder-free messages still fail 72% of the time

**Still open, and the one experiment that would settle it**: are these DMs compressible *at all* by a free-rewriting model? Most carry code, logs, citations and enumerated findings — material with little redundancy to remove. **The test**: run the compressor on *unfrozen* bodies, compare compression on the same messages, ignore the fidelity loss. Compression jumps → placeholders were the ceiling. Compression flat → the ceiling is the material. **Not run** — ruled closed. → `src/rnd/v0.2.0/2026.08.04-dm-verbosity-reduction/2026.08.07-arm-4-phase-2-findings-and-recommendation.md` §7

**NOT reverted, and should not be**: Phase 1's freeze protocol. Zero corrupted messages across all 600, and fail-closed is why these numbers can be trusted. Two verify-tier classes caught corruptions a single-tier design would have shipped.

**Prompt samples committed for anyone re-testing**: `src/rnd/v0.2.0/2026.08.04-dm-verbosity-reduction/prompt-samples/` — four real DMs, one per band, verbatim prompts plus answer keys for scoring.

---

## 🌙 EOD 2026-08-06 (Cheech 🌿 `72343afa`) — crew harvested, two lanes landed, one design awaiting Rick

**Committed tonight**: Rio ⚡'s two lanes (`9c5dccd4` spawn-failure reason + dry-run tmux probe; `d5ecb753` presentation timing clamp now disclosed rather than reported as a measurement) and Tiberius 👑's `69fb89cd` polluter #1 fix. 365 targeted unit tests green; both worker lanes reviewed before staging. Crew reaped, memento verified on disk.

**Awaiting Rick's word** — the Mon–Sat three-arm week design (`2026.08.06-three-arm-week-design-for-ratification.md`). Nothing starts on it until he rules.

**New row** `0ab3c0cd` (P2) — the brief-length probe's bash half is `skipif`-gated on tmux, so it ships green and unverified on a box without tmux; and the probe's session name is shorter than the real spawn's, so the assembled command it measures is not the one that runs.

**Still open from tonight**: `69fb89cd` polluter #2 · `c9d3ddcb` ungated in-tree CoSA suite · `35d0a451` est_tokens omits refused drafts (bites Saturday's cost line).

**Left dirty, not mine**: María 🌸's arm-4 compression plan docs; `notifications.html`/`.js` (owner unknown, already dirty at 14:48).

## ⏳ SATURDAY 2026-08-08, after 19:00 EDT (Cheech 🌿 `72343afa`) — DM pilot final pull: report POOLED **and** Tue/Wed-only, side by side

**Rick's instruction, 2026-08-06 evening**: capture this before the tokens run out. 🤣

### The task

When the last extension slot closes **Sat 2026-08-08 19:00 EDT**, run `analyze_arms.py` on the
complete corpus and publish **two** sets of numbers, not one:

| Report | Days | Answers |
|---|---|---|
| **Pooled** | 08-04 → 08-08 (all five) | the best-powered estimate available |
| **Tue/Wed only** | 08-04, 08-05 | what the pilot said *before* it was extended |

### Why both — this is the point, not a formality

**The extension was authorized after the interim result was seen** (Rick, 2026-08-06 ~18:10).
That makes the stopping rule data-dependent, which is the classic way to manufacture
significance by accident. Publishing both is the defense:

- **They agree** → the extension tightened a result already pointing the same way. It sharpened
  the finding rather than creating it.
- **They disagree** → *that disagreement is the finding*, and the pooled number must be read
  with real suspicion.

Say plainly, in the report itself, that the extension was added mid-flight. Do not bury it.

### Contents

1. Both co-primaries (all attempts · first attempts only), exact p-values, ±46-word null band —
   pooled and standalone. **The estimator does not change**; nothing was re-specified after looking.
2. **Usable clock-hour pairs, pooled vs standalone.** This is where the extension earns its
   keep: it was **5 of 14** at extension time, with nine buckets one-armed or empty. The
   analyzer pools all days into 14 clock-hour buckets, so extra days fill gaps rather than
   raising the ceiling.
3. Cost / break-even recomputation against the Wednesday midpoint (46.4k est-token rewrite
   spend, 30.8% required vs 23.8% observed — **losing at both bounds**).
4. Row `35d0a451` still open: `est_tokens` omits refused drafts, so rewrite spend is
   understated — which pushes the loss further, not back. Quote it as a floor.

### ⚠️ Separate the blocks BY DATE, not by a field

`slot_id` carries the date: `2026-08-04*`/`08-05*` = original, `08-06*`/`07*`/`08*` = extension.
**The `block` field is `null` on every row** — it lives in the schedule JSON but
`dm_experiment._parse_slots` drops it (builds the slot dict from `slot_id`/`arm`/`local_hour`/
`start_utc` only). Deliberately not fixed mid-run: it would need a bounce inside a live slot and
would split the extension into rows-with and rows-without.

### ⚠️ Volume is the risk, not the schedule

The pilot measures DMs between **working** sessions. Volume tracks headcount: 13 senders → 962
rows Tuesday; 8 senders → 71 rows Thursday after the crew was reaped. The 19:00 slot Thursday
produced **one** row in its first 16 minutes, and that row was mine. **If Fri/Sat are quiet,
say so plainly** — "the extension was armed correctly and the fleet was idle" is a coverage
result, not a null result, and the two must not be reported as the same thing.

**Docs**: `src/rnd/v0.2.0/2026.08.04-dm-verbosity-reduction/2026.08.06-dm-pilot-schedule-extension.md`
(extension + caveat + §6a first-row confirmation) ·
`…/2026.08.06-three-arm-week-design-for-ratification.md` (Monday, awaiting Rick's ruling)

---

## ✅ RESOLVED 2026-08-06 (Cheech 🌿 `72343afa`) — the 08-05 "not diagnosed" quiet-corpus question, answered

The MIDPOINT entry below asked whether the stalled corpus was a **quiet fleet** or a **stopped
writer**, noting the two *"look identical from inside the corpus."*

**Answer: neither — the SCHEDULE EXPIRED.** It declared 28 slots covering Tue 08-04 and Wed
08-05 only, ending 2026-08-06T03:00Z. Outside a slot, `assignment_at()` returns `None` **by
design** and the row is written untagged. The pilot stopped accruing while traffic kept
flowing; the fail-safe worked exactly as specified.

⇒ **The distinguishing check is one line**: group the corpus by day **and by experiment tag**,
not by day alone. A coverage report that cannot say "zero tagged today" is not a liveness check.
Extended through Sat 19:00 EDT and confirmed producing (first tagged row 19:16, arm `blind`,
slot `2026-08-06T19`).

## ✅ SUPERSEDED 2026-08-05 morning (Mr. Radio 🦉 `2c3c8645`) — the crash was diagnosed and fixed the same night; this block was written before that and never updated

**What this block said**: *"Status at hand-off: NOT DIAGNOSED."* **That was true when written (~23:1x EDT) and false 15 minutes later.**

**The crash** (`pr-62254a7f`, 03:08:31 UTC — *"Outline generation returned no usable entries"*) was the plan-mode twin: `PRESENTATION_PERMISSION_MODE` was still `"plan"`. Fixed in `f67189c3` (committed 03:15:41 UTC), deployed at the 03:14:57 UTC bounce. **Proven fixed**: `pr-c07dbd3d` ran 03:20–03:30 UTC — 15 slides, PPTX 4844KB, `pres-56183c6e`.

⚠️ **But the proof came through the CARD path only.** The Q&A-card path failed 7 minutes *before* the fix deployed and has never been retried on fixed code — the two paths were never compared on the same code. **That gap is the live P0**, not the crash.

**Today's two P0s (Rick, 2026-08-05)** — SWE crew live: Tiffany 💍 Tester · Clayton 😎 Implementer · Rachel 🕊️ Reviewer.

1. **Q&A-card → presentation runs end to end** — Rick: *"I have to have it working for me today so I can hammer out various iterations of the presentation I'm giving tomorrow at noon."* Row `ffd46737` (P1). Spec: `src/rnd/v0.2.0/2026.08.05-qa-card-presentation-path-podcast-only-fences.md`. Three `fuzzy_file_match` features in `expeditor.py` are fenced to podcast only (L388–392 auto-resolve, L388–392 choice card, L422 present-but-unresolvable rescue), leaving presentation's `source` degraded.
2. **User-specified duration + slide count** — Rick: *"It's a 60-minute presentation and there's no way in hell I can cram all of that into 12 slides."* **María owns the architecture**; the crew builds after she and Rick agree. Clayton is on recon only until then.

### 🗳️ RULING 2026-08-05 ~11:37 EDT (Rick, on a 4-option menu with pros/cons) — build the two content fixes, hold the third

**His words**: *"Let's do both context fixes per your recommendation and hold the third for now. I'd love to have this working but I don't think I'm going to demo file matching for presentation jobs. I definitely want to implement it though, so perhaps later make note of it — but not now."*

| Item | Ruling | State |
|---|---|---|
| **Raise the 30,000-char source clip** → one shared INI ceiling, all 3 sites in one commit (`narrative.py:178`, `elaboration.py:171`, podcast `script_generation.py:262`) | ✅ **GO** | Clayton building |
| **Land the dropped `audience_context`** (`job.py:249-256` copies 4 args and skips it; `config.py` has no field) | ✅ **GO** | Clayton building |
| Generalize the expeditor podcast-only fences | ⏸️ **HELD — not dropped** | Row `5bc22180`; proposal written + Rachel-passed, needs only a GO |
| María's T1/T2 (explicit slide count; the *"close to 12"* vs *"exactly 15"* prompt contradiction) + T2b drift warning + Gate-1 `human_feedback` | ✅ **GO** — Rick ruled directly to María at 11:38, **Scope B: soft target with a drift warning, not hard exactly-N** | **Cheech 🌿** owns the build (spun up by Rick, outside Mr. Radio's crew). Doc: `src/rnd/v0.2.0/2026.08.05-presentation-slide-count-control.md` |

**⚠️ Two crews, one file — ordering ruled 2026-08-05 ~11:43 (Mr. Radio).** Clayton and Cheech both change the **signature of `get_narrative_analysis_prompt`** (his configured source-ceiling param; her `human_feedback` + budget param). A genuine conflict, not line-proximity: git merges lines 153-156 and 178 quietly and leaves callers half-updated, so **it fails at call time, not at merge time.** **Clayton lands first; Cheech rebases**, doing all of T1's plumbing outside `narrative.py` first and touching that file last. Rachel gates both and re-derives the complete call-site set at HEAD each time.

**Scope grew to FOUR clip sites, ruled on evidence.** Clayton flagged a 50k twin at podcast `script_generation.py:198` rather than silently widening; Rachel pre-read it independently and reached the same verdict — an arbitrary literal with only boilerplate justification, same shape as `:262`. Folded in, because leaving a known 50k clip two functions above the 30k one we were fixing would have been *us* creating the fix-one-twin pattern, knowingly, in the same commit. Final: **2 presentation (30k) + 2 podcast (50k analysis, 30k script) → one neutral key `agent source content max chars`, `[Lupin: Baseline]`, default 200000.** The commit must state that both podcast clips **changed number** — a silent unification is a behaviour change wearing a refactor's clothes.

### ✅ LANDED 2026-08-05 12:40–12:44 — both authorized fixes, verified before announcing

| Sha | What | Verification |
|---|---|---|
| **`934b364b`** (Clayton 😎) | Shared ceiling `agent source content max chars = 200000` replacing bare literals at **all 4 clip sites** (`narrative.py`, `elaboration.py`, podcast `script_generation.py` ×2) + `audience_context` onto `PresentationConfig` + all 4 `getattr` defaults → explicit access | 15 files, 215/37. Zero `target_slide_count`/`_slide_budget` additions. Isolated-worktree touched-tests **247/247**. Rachel PASS 6/6 at the committed bytes |
| **`f41aa1fe`** (Mr. Radio 🦉) | `d55f2f87` — **24 disambiguation tests were gate-reachable by nobody**, and the gated suite had *zero* choice-card coverage. Moved into the gated suite, not allowlisted | 24 pass in new location; census **31 passed** (was 1 failed). Pure rename, no production code |

| **`8de931f8`** (Cheech 🌿 / María 🌸 spec) | T1/T2/T2b — author-set `target_slide_count` overriding the duration formula, across INI/CLI/REST/voice; `_slide_budget()` collapsing three duplicated sites; drift warning gated on an explicit count; Gate-1 `human_feedback` param | 14 files, +352/−9, **zero** foreign content, index empty. 696 passed on the committed sha |
| **`54421d01`** (Mr. Radio 🦉) | **Seven R&D docs were untracked** while the code they specified was landing — including María's spec, the governing document for `8de931f8`. Caught by Cheech verifying her own commit | Docs only. Index verified empty before staging, contents after |
| **`c6f7b45f`** (Clayton 😎) | The two podcast clip-pins in the **ungated** `src/cosa/tests/` tree still asserted the old 50k/30k literals against his intended change. Now parametric on the **configured** ceiling + a `None`-no-clip companion each | 1 file, 26/5. File 46/46. Whole-tree sweep for old clip literals across **both** test trees: clean |

⇒ **Rick's 77,621-char source now reaches the model in full**, dictated `audience_context` lands, and slide count is author-settable instead of inferred from duration.

**⚠️ The regression that only the full run could find.** `934b364b` shipped red on two tests nobody's gate collected: they live in `src/cosa/tests/`, which **no gate-invocable runner reaches**. Clayton's touched-tests run missed them; Rachel's gate missed them; **only Tiffany's 9,000-test both-roots pass found them.** Second time in one day that tree hid something — the first was the 24 doc-choice tests. ⇒ **`src/cosa/tests/` is a standing blind spot and deserves its own row after the demo.**

**HEAD is now the composed tree** — `c6f7b45f → 54421d01 → 8de931f8 → f41aa1fe → 934b364b → 9b7abc98`, both crews plus both manager commits. Clayton's background both-roots run off `c6f7b45f` therefore **is** the composed-tree unit verification (row `ee679014`), by accident of ordering; Tiffany owns the live end-to-end half.

### 🔴 THE COST OF TWO CREWS ON ONE TREE — worth more than the code

**`git commit --only -- <paths>` commits the WORKING-TREE version of the named paths and IGNORES a clean index.** Clayton's index was verifiably clean (215/37, zero T1 by grep); `--only` bypassed it and re-bundled the other crew's work as `0d390b11`. He caught it himself from a 291-vs-215 file-stat mismatch, `reset --soft`, re-committed as `934b364b`. **The flag that sounds exactly like "commit only my paths" is the one that silently takes the working tree** — and this fleet's parallel-session doctrine actively points people at it.

**`git diff -U0` cannot split two crews' CONTIGUOUS new lines** — hunk boundaries come from the pre-image, so a 61-line pure insertion authored by two people is one hunk with nothing to cut on. The INI split cleanly (13 lines apart, separated by originals); one test file took three rounds. **Class membership is not hunk separability.**

**The rule neither manager had**: *"stage nothing" governs the index; **don't edit inside another crew's unlanded structure** governs the edit.* Perfect staging discipline does not save you from nested authorship.

**Partial staging buys correct authorship at the cost of an untested artifact** — every test ran against a working tree holding both crews' code, while the commit held one crew's. Gate the committed artifact (`git show <sha>:<file>`, read whole), never the dirty tree.

**`LUPIN_ROOT` must point at the worktree for isolated runs** — subprocess tests resolve `__main__.py` and config through it and will false-red off the dirty main tree. Cost Clayton one false red; not discoverable from the failure text.

### 🪞 FOUR FACES OF ONE PATTERN — wrong instrument, not wrong thinking

Recorded for the post-game; **graduation to `workflow/` deliberately withheld** (María's boundary — four faces in one morning from seats all in this room is one day of evidence; the qualifying instance must come from outside).

| Face | What it produced |
|---|---|
| A grep count answering "what matches", not "what breaks if it's gone" | A 16-line delete list that was really 13 — three sat in a method whose removal breaks two live callers |
| `git log --since="2026-08-05 15:00:00"` in EDT | A **future** window that cannot contain anything, returning a confident zero indistinguishable from a quiet branch |
| A grep of `src/cosa/tests/` for tests living in `src/tests/` | An **empty result from the wrong tree**, which reads as "the tests don't assert this" |
| A correct read of a method body, then a cited symbol that doesn't exist | *"The read was real, the citation was invented"* — a fabricated receipt passes every reader who trusts it and fails only the one who greps |

**And the manager's own**: two correct observations of the same repo contradicted each other because a branch pointer moved between them — `0d390b11` went dangling, so `git log` showed one seat nothing while another had read the commit directly.

### 🛟 DEMO-EVE SAFETY — row `ee679014` (P1), raised unprompted 2026-08-05 ~11:47

**KNOWN-GOOD SHA: `9b7abc98`** — recorded **before** the tree moves. It is the last commit proven to produce a deck end to end, twice: `pr-a10a55aa` (Q&A path, PPTX 5,462 KB) and `pr-c07dbd3d` (card path, 4,844 KB). **If 2026-08-06 morning is broken, this is the number to go back to.** Reconstructing "what was good" from a git log at 9am on demo day is not a plan.

**The gap nobody owned**: two crews land 4+ commits into the presentation path today. Each verifies its own diff; Rachel gates each. **Nobody measures the tree they jointly produce** — the same shape that has burned this fleet all week, a green measured somewhere other than where it has to hold.

**Countermeasure**: after BOTH crews' commits are in and both passed, Tiffany runs **one live end-to-end pass on the composed tree** — freshly bounced, served bytes verified, whole user-observable chain (submit → expeditor → arc → outline → elaborate → render → PPTX). Acceptance: a finished PPTX **plus** the tail-reached probe green, which is what proves the ceiling took effect end to end rather than only in a unit test. It belongs to neither crew; it belongs to the manager.

**Verification trap recorded (Rachel → María, step 6): the slide-count run must be LIVE, never `--dry-run`.** Dry run mocks every LLM call (`job.py:_execute_dry_run`, mock outline at `orchestrator.py:804-830`), so it returns the *mock's* count and measures the harness instead of the model — a green that proves nothing about the thing under test.

**The reasoning that split them**: fixes 1-2 change what the **model** sees — a better deck, with no change to the flow Rick rehearses tonight. Fix 3 changes what **Rick** sees, the day before he presents. Same low risk, different exposure.

### ✅ P0-1 CLOSED — the Q&A-card path runs end to end

`pr-a10a55aa` (Tiffany 💍, `:7999`, current code, test user): **PPTX 5,462 KB, 15 slides**, full chain expeditor → outline → elaborate → YAML → Marp → 14 visuals → export. **Phase 3 — the step that killed `pr-62254a7f` last night — cleared in 22 seconds.** Writeup: `src/rnd/v0.2.0/2026.08.05-qa-presentation-path-e2e-verification.md`.

### 🔍 What the morning found that nobody was looking for

- **61% of Rick's source never reached the model.** His outline is 77,621 chars; the clip is 30,000, in *both* the arc and content phases. Every deck he has generated from it was built from the first 39%.
- **`audience_context` is silently discarded.** He dictated *"presenting to forward deployed engineers at Google"*; it was stored on the job and never copied to the config the orchestrator reads.
- **The same clip exists in podcast** (Rachel found it) — so the fix uses a shared key and podcast becomes a one-line follow-up instead of next month's twin-miss.
- **The two prompts contradict each other**: narrative says *"close to 12"*, outline says *"exactly 15"*. No test covers the formula at all.
- **Gate 1's "Revise" is a no-op** — feedback is stored but the prompt builder has no parameter to receive it, so it re-rolls the identical call and burns a revision.
- **Two same-named files** — `src/rnd/…` at 48,473 and `io/deep-research/…` at 77,621. That collision produced a real disagreement between two seats' measurements; cite the full path or measure the wrong document.

**The lesson this block earned**: a status line records what was true when written. This one sat at the top of TODO.md all night asserting "NOT DIAGNOSED" about a bug that was fixed, committed and verified before midnight — the same defect `history.md`'s own header names about its health stamp. **Nothing re-derives a stamp.**

---

## 📋 DECISIONS LOG 2026-08-04 evening (Mr. Radio 🦉 `7802a03f`) — the demo works; scope for the last two days

**D6 — Verify only before Thursday; change no code.** *Ruled by Rick, 20:5x EDT, on a menu with pros/cons.*
Rick's podcast ran end to end and he listened to it — the demo path is proven once, by hand. Remaining work is split into *verify* and *fix*, and only verify is authorized. Two runs go ahead: `3171c9dd` (the demo path through the automated harness — repeatable proof, not one good run) and `68198c9f` (a **vague** file description, the closest thing to how Rick will actually speak on stage). **The error-string fix `e0bb5a94` is explicitly NOT taken**, though it is small and genuinely valuable — it edits the demo path two days out, unreviewed, and today already showed what that costs. **Why**: today's failures all shared one shape — a green measured somewhere other than where it had to hold. More measurement helps; more change does not.

**D7 — Spawn one fresh reviewer for the adversarial read.** *Ruled by Rick, same sitting.*
`a4521768` has sat untouched all day; its owner Rio was reaped and nobody has ever read the demo path hostilely. Rick chose a **fresh** worker over me doing it — correctly: I got the routing safety-net wrong, reported audio rendering after the job had died, and had Spanish backwards an hour earlier. **Scope**: demo path only, findings and evidence, **no fix proposals** — which keeps it inside D6. Anything it finds is Rick's call, not an automatic change.

**D8 — Spanish stays off, and the reason on record was wrong.** *Correction, Rick 2026-08-04.*
I wrote in `lupin-app.ini` that English-only was about "doubling the work and adding a failure surface", and told Rick restoring Spanish was one config line. **Both were wrong.** The real reason is bug `0913bb90`: the translation step intermittently returns the **English** text unchanged, and two masking layers shipped it as a fake `es-MX` podcast — Rick got two English podcasts. Krishna's fix makes that **fail loud**; it does **not** make translation succeed, and the distinguishing run that would size how often it fires was deferred and never executed. So the odds are unmeasured. The config comment has been rewritten to say so. **Gates on Spanish**: fix `0913bb90`'s root cause, then run the N=5 distinguishing run.

**D9 — The disambiguation card ships, and D6's "change no code" is superseded for it.** *Ruled by Rick, ~21:33 EDT, after a traced walkthrough.* Watching the path where two files both match "the KISS protocol", Rick asked what happens — the answer was a blank *"Which document should I use?"* with the candidates known and thrown away, because auto-resolve accepts only an exactly-one result. His words: *"if that works, it would be a very compelling demo of disambiguation"*, with the binding constraint *"a standard multiple choice UI that is used for all other lists of options. We want maximum reuse of code."* Shipped as `2d6de739`. **D6 still governs everything else** — this is one named exception granted explicitly, not a general re-opening. **Why it was safe to take two days out**: it was reviewed before a line was written (which caught a real defect in my plan), gated behind a caller-passed flag so the presentation path is untouched by construction, and proven by a live run that captured the card off the WebSocket rather than by unit tests alone.

**D10 — English-only is FINAL for Thursday.** *Ruled by Rick, 22:2x EDT, on a menu with the measurement option offered and declined.* Ratifies D8 with one thing D8 did not say: there are **three** outcomes, not two. Beyond real Spanish and a visible "Translation Failed", a valid parse whose segments are still English **ships silently as a normally-titled es-MX script**, because nothing compares the translation to its source. Rick declined the N=5 distinguishing run rather than spend the night sizing a risk he had already decided not to take. **Gates on Spanish unchanged**: fix `0913bb90`'s root cause, then measure.

---

## 📋 DECISIONS LOG 2026-08-04 (Mr. Radio 🦉 `7802a03f`, five-worker crew) — Thursday demo: the line was refuted, replaced, and the root cause found

**D1 — Chase a wording fix AND a code fix in parallel.** *Ruled by Rick, 12:43 EDT, on a menu with pros/cons.*
The demo line `"make me a podcast on KISS"` routed correctly and then **crashed** — `FileNotFoundError: Research document not found: KISS`. Rick declined to bet on either fix alone. Rachel took the wording lane, Clayton the code lane. Both landed. **The wording fix won the race**, so the code fix stopped being the critical path and became durability.

**D2 — Prosody: file it, do not touch the audio path before Thursday.** *Ruled by Rick, 12:04 EDT.*
Rick asked for the translation to preserve prosody cues. Investigation showed the request pointed at the wrong layer: translation **already** preserves them (148 verified in the Spanish text), and the **text-to-speech engine strips every marker before synthesis, for every language including English**. So the cues have never been audible. Making translation "keep" them changes nothing. Real work is a TTS change; deferred rather than touching the one component whose failure means no podcast at all.

**D3 — HOLD the `topic → research` alias drop until after Thursday.** *Ruled by me; raised to Rick to overrule.*
⚠️ **My first justification was wrong and is recorded as such on row `bd0ce120`.** I called it "a behaviour change of unknown risk." Rachel's contrast then showed the presentation pair already does it the correct way — so it is *"match a proven-correct sibling"*, not a novel design. **The hold stands on redundancy** (Clayton's fix already covers Thursday), **not on risk.**

**D4 — Split a landed fix from its unbounded follow-up.** *Ruled by me, on Krishna's question.*
Closed the proxy-port fix on its receipts; minted the back-contamination audit as its own row. An open row hides that the fix landed, and unbounded forensics does not belong bundled with a one-line change.

**D5 — Closing a latent gap does not outrank the demo.** *Ruled by me, on Tiffany's `:8000` fix.*
Her diff touched the **podcast submit endpoints** — Rick's demo path, two days out, on a row that is not demo-blocking. Ruling: prove a normal submit is identical before and after, or drop those endpoints. She proved it with a **differential** (disable the stamps → only the 2 lineage tests red, all 48 normal-submit paths identical either way). Kept in the pass.

### 🔎 THE ROOT CAUSE, and it traces to a bug we fixed the same morning

The podcast command's **1200 training rows all emit a topic; zero emit file paths.** The registry then aliases that topic into `research`, **a file-path argument**. So the extractor did exactly what it was taught, and the registry put the answer in the wrong slot.

It was **trained as "podcast from a topic" — the old, inverted label — and implemented as a file reader.** The label inversion fixed at 10:58 was never cosmetic; it had already propagated into the training data. The crash was that same mistake surfacing at runtime, hours after we thought we'd fixed it.

**Scope checked, not assumed** (Rachel): the presentation pair is clean — 879/1200 real paths, no topic alias. **Isolated, not systemic.** A negative result worth as much as a positive.

### 🪞 THE PATTERN THE DAY KEPT REPEATING — worth reusing

**Five separate claims today were measured somewhere other than where the thing has to work**, and every one read as green:

| Claim | Measured where | Where it had to hold |
|---|---|---|
| "Resolves to Rick's file 3/3" | The matcher, fed directly | The live flow — where the matcher is never called |
| "473 tests pass" | A subset | The merge |
| "21,562 passed" | An earlier run | The committed code |
| "Prompt auto-submits after 5s" | A config field | An observed submission — there was none |
| "Spanish loses its cues" | A metadata list | The translated text — the cues were there |

Three of those were mine. The countermeasure that actually worked, every time, was **someone re-deriving the claim from the other end** — Rio refusing a subset, Clayton reading the consumer, Tiffany finding her own harness in the logs, Krishna retracting his own report.

**Standing rule adopted from this**: a receipt must name **which run produced it**, and a "probably fine" gets answered with a differential, not a paragraph.

---

## 📊 MIDPOINT 2026-08-05 evening (Cheech 🌿 `f8754825`) — DM pilot: the break-even moved, and the bounds stopped bracketing zero

Doc: `src/rnd/v0.2.0/2026.08.04-dm-verbosity-reduction/2026.08.05-dm-two-arm-pilot-midpoint-status.md` (sequel to the 08-04 break-even doc, now a sibling in the same subdir).

| | Tuesday | Tue + Wed (partial) |
|---|---|---|
| required first-try reduction | 22.4% | **30.8%** |
| observed | 26.8% | 23.8% |
| full-credit bound | −3,147 tok (saving) | **+10,558 tok (loss)** |
| no-credit bound | +16,115 tok | **+46,421 tok** |

The observed gap barely moved; the **requirement** rose, because rewrites nearly tripled while first tries not quite doubled. Behaviour still moves and reads as restraint (157.4 → 126.3 words/attempt; co-primary B answerable at last, n=5, same direction as A) but nothing is significant — p = 0.375 / 0.438 on a ±46-word null band.

**Two things a later seat should not have to rediscover**: the effect is in **words**, every cost figure is in **chars÷4 est-tokens** (never a tokenizer), and they are not interchangeable. And bunching in \[140,149\] went 4.4% → 11.1% — senders steering *to* the threshold, not away.

### ⏳ Still open on this row

- ~~**Wednesday is 7 of 14 slots**, and no rows have landed since 16:10 EDT. **Not diagnosed** — quiet fleet and stopped writer look identical from inside the corpus.~~ ✅ **ANSWERED 2026-08-06 — the schedule expired** (28 slots, Tue/Wed only). Neither candidate was right; see the RESOLVED entry at the top of this file.
- Row `35d0a451` (published metric omits refused drafts) is still queued — today's data widens the gap it describes (published −33.2% vs all-in +7.4%), so quoting either figure alone is now more misleading than it was Tuesday.

## 📋 DECISIONS LOG 2026-08-03 (Cheech 🌿 `2c73cb48`) — DM verbosity pilot, live-gate verification

**D1 — Prove the reject path with a real schedule slot, not the arm override.** *Ruled by me on Tiffany 💍's refutation, 2026-08-03.*

I planned to pin `dm experiment arm override = rejecting` and bounce. Tiffany refused to run it and cited `dm.py:1037`: the gate executes only when `assignment_at` returns a slot, and `override_arm` **re-labels a matched slot — it cannot create one**. Outside the Tue/Wed window `assignment_at` returns `None`, so the smoke would have returned an ordinary 201 and I would have called the gate proven.

Chosen instead: a temporary `rejecting` slot dated **2026-08-03** (outside the pilot window, so its rows can never enter the Tue/Wed analysis), live for the smoke, then removed and the mirror re-verified from the live policy. Rejected: forcing the override active in code (a code change to prove a code path), and shipping on the in-process tier alone (no live proof before go-live).

**Why it matters beyond this row**: an override that only re-labels looks identical, from the caller's side, to one that arms. The distinguishing evidence was in the source, not in the response.

**D2 — Exclude `TEMP-` slots in code, not by remembering to delete them.** *Ruled by María 🌸, adopted 2026-08-03.*

María did not object to the temp slot; she objected to its containment being **deletion-dependent**. Landed at `analyze_arms.eligible_rows()` — the single chokepoint feeding co-primaries, secondaries and counts — with two unit tests, so co-primaries, secondaries and counts all drop `TEMP-` rows whether or not the slot was ever removed. Same reasoning that put a janitor on the scratch project instead of a "delete when done" rule.

**D3 — Wait out a running job rather than force the bounce.** *Ruled by Rick, 2026-08-03.* `bounce-dev-server.sh` exited 4 on `inflight_agentic_jobs=1` (his podcast job). Options were wait, `--force` (destroys the job), or skip live verification. He chose wait; there were ~11 hours of margin against a ten-minute remainder. The guard's refusal was the correct behaviour and is worth keeping in mind as *the* precedent: a dirty tree is recoverable, an in-flight job is not.

### ⏳ Still open on this row

- **The pilot has not RUN yet.** Build is complete and committed; Tuesday 09:00 ET opens the window. Store row `a3666252` (P1) carries items 7 (in-window audit of both arms) and 8 (23:00 counts) so they survive the tester's seat.
- **Not pushed.** `2c73cb48` and everything before it sit on `wip-v0.2.0-2026.08.03-present-and-demo` with no upstream. Rick's call.
- **`history.md` at 16.0k tokens** — past the 17k warning on the next entry. Next seat should archive.

## 📋 DECISIONS LOG 2026-08-02 (Cheech 🌿 `13459df0`) — embedding regeneration scope + venue

**D1 — Regenerate EVERY row, not the subset that looks wrong.** *Ruled by Rick, 2026-08-02.*

I proposed regenerating only the 79,318 rows whose vectors read norm 1.0, treating the other 209,468 as already correct. Rick's ruling: *"We are replacing all of those values not a segment because they represent the results of embeddings created by two different embedding spaces, two different training sets, two different services."*

**Why my version was wrong, in one line**: a norm measures whether a vector was *normalized*, not which model produced it. It separates OpenAI from local only because those two happen to differ in normalization, and it cannot see any boundary *inside* the local era — a model version, training set, service endpoint, or prose/code engine choice could all change without moving the norm. "Already correct" asserted a provenance nothing had measured.

The invariant is one space, one model, one pass. Partial regeneration leaves a mixed space **and leaves it undetectable**, which is how the original defect survived two and a half months. Scope: 158,666 → **578,364** calls. Selection predicate is now "has source text".

**D2 — The fill runs against `:7999` off-peak.** *Ruled by Rick, 2026-08-02.* Rejected `:8000` (monopolize-mode; a multi-hour fill would block every scheduled test suite, and this is not a test suite) and in-process (conflicts with the standing never-grab-a-GPU rule + GPU-0 pinning). Rick added: measure one batch of 256 first and extrapolate, rather than scheduling against a guess.

**D3 — Unload the other GPU models before the run.** *Rick, 2026-08-02.* GPU 0 is a 24,564 MiB card with **23 MiB free**: 7,416 MiB is the embedding model server itself (must stay) and 16,754 MiB is a vLLM instance (pid 9710) that can be unloaded, taking free memory to ~17 GiB. This invalidated the hardcoded batch budget. Resolved by making the budget adaptive (grows on success, halves on refusal) rather than scaling a constant by a chars-per-MiB rate I have no data for. ⚠️ Open question for the walkthrough: unloading that vLLM may interact with row `357c283f` (router-model 404), which is also a vLLM question.

### ⏳ Still open on this row — nothing is blocked, but nothing writes until these are settled

- **Runtime is HALF measured.** Embedding: 0.41s per 256-batch, ~16 min for all 578,364 — and that measurement found a CUDA OOM on long-text batches that would have killed the run (fixed, `0310aa05` + `d7e02562`). The **DB write side remains unmeasured** — 288,932 UPDATEs plus reads, very likely the dominant term. Measuring it needs the clone rehearsal or a bounded shadow-column fill, both behind the walkthrough.
- **Rollback undecided.** Once swapped, the old vectors are gone unless the shadow columns are kept or a `pg_dump` of the two tables is taken first. Real disk. Needs a ruling before step 5.
- **Full walkthrough not yet held.** Rick's standing constraint: no writes to `input_and_output` "until you and I discuss the entire process from beginning to end." D1 and D2 settled scope and venue; the end-to-end walkthrough has not.

## 🗳️ RULING 2026-08-02 (Rick, via Mr. Radio 🦉 `4829ab05`) — a closed row may now be amended

**Decision**: allow `task_amend` on a terminal row, flagged as a post-terminal addendum. Chosen over adding a `ready-for-gate` status (too much surgery for a P3) and over writing down the process rule (rules get forgotten — this fleet chose a janitor over a "delete when done" instruction for exactly that reason).

**Why it was asked**: a worker self-closes, then the manager runs the gate — and the store refused every write verb on a closed row, so the verdict had nowhere to go. Maria hit it twice in one hour; on row `700a6330` her gate **failed the first pass** and none of that reached the row.

**Landed**: row `3c569786`, commit `310aa290`. The block names the status at write and says it is not a reopening; the event is `amended_post_terminal`. `transition` / `edit` / `correlate` stay refused — a closed row stays closed.

**Not recovered**: the verdicts already lost on `ddcc40c2` / `700a6330` / `49a76406`. The capability now exists to write them late, but they are Maria's to write — reconstructing them from her DMs would put words in her mouth on a durable record.

## ✅ CLOSED 2026-08-02 (Mr. Radio 🦉 `1bf47c18`) — Krishna's managed-bounce lane: all three items done, and the answer moved the target

*(The "FOR TOMORROW" version of this entry is kept below for the record — it was accurate when written and one of its own claims turned out to be wrong.)*

**All three landed** in `70a27d02` (item 1) and `066f04f8` (items 2–3), on Rick's ruling. Doc: `src/rnd/v0.1.9/2026.08.02-settle-deadline-arithmetic-30-vs-40.md`.

1. **`main.py` fallback** — was still 15 while the key read 30; now tracks the key, with a **call-site pin test** that reads the `default=` the code was actually called with rather than grepping the source. (Note: TODO line 171 in the entry below claimed this was "also fixed". It was not — it was still 15 this morning. A claim about a fix is a claim like any other.)
2. **The arithmetic is settled, and Krishna was right.** `self._attempt += 1` runs **before** the `min()`, so the first delay is `2^1` not `2^0` — wakes at **2/6/14/30/60**, his series, not my 1/3/7/15/31. Confirmed against ~63k printed reconnect delays, not just derived. Both live samples fall out **exactly** at a ~40s restart catching the t=60 wake (+18.6s, +20.4s).
3. **Jitter is ON — pointing DOWN**, and the cap came to 10, deadline to 15.

**🔴 The finding that outlives the three items — arrival is a SAWTOOTH in restart downtime.** A restart 11 seconds *faster* arrives 11 seconds *later* relative to gate start (D=30.1 → +29.9; D=41.4 → +18.6). Rachel's ~8s-downtime bounce would have arrived at +6s and 15 would have been fine — **the two nights' numbers never conflicted, they were different points on a sawtooth.** So the deadline can never be tuned by averaging observations, and 30 was not "measurement-backed" in any sense that survives: two samples cannot bound a sawtooth.

**What replaced measurement**: the deadline is now **derived**, not chosen. `SettleDeadlinePinTests` computes the requirement as `RECONNECT_MAX_DELAY + margin` and reds if the cap and the deadline drift apart **in either direction**. The 15→30→15 churn happened because the two values lived in different files and were picked independently by different people; that coupling is now a test.

**On jitter, and Rick was right to push back.** He asked *"jitter always helps smooth out the thundering herd, does it not?"* — yes, and that was never disputed. The narrower claim was that it helps the *herd* (load) and not the *gate* (last-arrival), since a coverage gate waits for the slowest session. Simulated over 20k bounces: symmetric ±50% jitter at the old cap takes the typical wait from 8.1s to 27.7s. **His pushback produced the better fix**: jitter has a *direction*, and applying it **downward only** spreads the fleet just as well while leaving the cap a real ceiling — which the deadline's derivation depends on.

**The instrument that was missing**, and the honest reason two competent readings stood unreconciled for a day: the reconnect line had **no timestamp** and sat outside the timestamped log path — zero timestamped reconnect lines in the entire 118 MB centralized log. The downtime had to be *inferred* from arrival times. Now routed through an overridable `_log`; gated by driving the real `run()` loop against a real file and asserting on **what landed on disk**, not by reading the chain.

### ⚠️ TRANSITION HAZARD — the next bounce is the lossy one, and it is unavoidable

The two halves of this fix land on **different processes at different times**:

- the **deadline (15s)** is server-side — live the moment `:7999` is bounced;
- the **cap (10s) + jitter** is in the **listener**, a long-lived host-side process that keeps its old code until it respawns.

So the **first** bounce after this commit runs a 15s deadline against listeners still on the 30s cap — the one combination that is worse than either state. Sessions alive right now will not have the new backoff until their listeners restart.

**Not a reason to revert, and not a reason to rush a bounce.** Options, for whoever takes it: accept one lossy all-clear (the warning still lands, and the warning text is self-limiting), or let the fleet turn over naturally first. **Flagged rather than decided — Mr. Radio did not bounce `:7999` on this.**

---

## 🗄️ FOR THE RECORD — the "FOR TOMORROW" entry as written 2026-08-02 00:12 (superseded by the entry above)

**Rick asked for a note that Krishna has work "still in flight and uncommitted." I checked the tree before writing it, and the second half is not true — so here is the accurate version, because a wrong note tomorrow costs more than no note.**

**NOTHING of Krishna's is uncommitted.** His tree work — deadline 15 → 30, the splainer rewrite, and the pin test — shipped in `416940e4`. `git status` shows no managed-bounce file dirty. He explicitly reverted a half-finished edit rather than leave the tree inconsistent under a deadline, and said so.

**What IS unfinished is work he never built.** Three items, in priority order:

1. **`main.py:472` still falls back to `15`.** The key is now 30, so if that config key ever goes missing the server silently reverts to the value we just measured as wrong. One line. This is the only *code* item.
2. **The deadline may need to be 40, not 30 — and the arithmetic to decide it is UNRECONCILED.** I ordered 40, then withdrew the order when I noticed my own objection cut both ways. The dispute: Krishna reads the listener backoff wake series as **2/6/14/30** from disconnect; I read `min(1.0·2^attempt, 30)` as **1/3/7/15/31**. Neither of us settled **the offset between the disconnect clock and the gate-start clock**, which is precisely what makes "+20.4s from gate start" and "a 30s wake from disconnect" non-comparable. 30 clears both *observed* samples by ~10s, so what shipped is defensible on measurement — but if the boundary reading is right, 30 races the wake it is waiting for.
3. **🔴 THE REAL FIX, and it needs Rick, not a worker.** The listener backoff in `src/cosa/agents/utils/proxy_agents/base_config.py` has **no jitter** and a 30s cap. Nine sessions waking within 8 milliseconds of each other is a thundering herd by construction. Jitter would make *any* deadline choice robust instead of boundary-sensitive, and a lower cap would stop pushing reconnection past every sane window. **Fleet-wide blast radius — deliberately not taken by the bounce-arc crew.**

**Where the context lives**: Krishna's memento (`.claude-memento-krishna-50c3680b.md`) carries all three plus the backoff finding; store row `251a42d0` (done) carries the full arc; his session was reaped clean on Rick's word.

---

## 🅿️ PARKED 2026-08-02 (María 🌸 + Mr. Radio 🦉) — the mirroring test: is odd phrasing TRANSMITTED between seats, or does each seat drift alone?

**⛔ NOT BEFORE THURSDAY'S DEMO — Rick, 2026-08-02: actionable bug fixes only.** Nothing here is a bug and nothing blocks the demo. Parked deliberately so it is not lost, not because it is next.

**The claim under test.** Drift says each seat degrades on its own. **Mirroring** says each seat learns the register from the last one — which is what would explain a house style that is consistent *across* seats rather than personal to each, and how DMs creep past 1000 words.

**María's test** (she proposes ~1 hour; the corpus is already on disk, nothing to build): pull the coined terms from one week of DMs, count how many appear in more than one seat, and check whether B's first use postdates A's. Shared **and** sequential ⇒ mirroring. Personal **and** simultaneous ⇒ the word dies.

**🔴 ONE CONTROL IS REQUIRED FIRST, or the test cannot fail.** *Shared-and-sequential* is also exactly what you get when both seats read the same source. Our own `CLAUDE.md` coins **WaHH · MoPEP · NoJP · TLH · NoDrama · 3LoL · NoMC C2C · NoAA** — every one appears in multiple seats' DMs, and every one is sequential by construction, because somebody had to type it first. **The test as written scores all of them as mirroring when they are plain instruction-following.**

**The fix is cheap**: exclude any term that appears in a committed instruction file, doc, or broadcast **before** its first DM use. What survives that filter is genuinely transmitted seat to seat — which is the claim. Without it, every result confirms the hypothesis and the run proves nothing.

**Status of the exchange**: María accepted the walkthrough offer and quoted the coherency-drift line into the KISS explainer (Act 13). My reply naming the control is **drafted but UNSENT** — cosa-voice lost its tool bindings in session `1bf47c18` and there is no CLI for `dm_send`. Draft + the walkthrough DM are held in that session's scratchpad; whoever has a live binding can send them, or they go out after a re-spin.

---

## 📥 FINDING 2026-08-02 (Mr. Radio 🦉 `1bf47c18`) — a listener loads the WORKING TREE at spawn, so it can pick up HALF an edit

**Status**: measured on boot #8, **no store row** (Rick's no-new-rows order stands). Sharper than the transition hazard filed above, and it partly replaces it.

**How it surfaced**: boot #8's reconnect lines were inconsistent with each other. Four listeners printed the old bare format; one printed **timestamped** lines — my instrument, committed at 13:43 — while *also* showing a **16.0s** delay at attempt 4, which the new 10s cap forbids. Timestamp present, cap absent. That combination exists in no commit.

**Cause**: listeners run `python -m lupin_cli...` straight out of `/src` (verified: the module resolves to the working tree, not site-packages). They import **whatever is on disk at the moment they spawn**. My two edits were saved ~15 minutes apart; a session that started between them loaded one and not the other.

```
3e328792  12:51   no timestamped lines
1bf47c18  12:53   no
b07d59ac  13:04   no
9fec7c53  13:20   FOUR  <- spawned between the _log edit and the cap edit
55eae7a8  14:06   (not yet reconnected)
```
A clean split at exactly the edit boundary — this is the mechanism, not a coincidence.

**🔴 Why it matters beyond this change.** `:7999` has the rule "a saved file is not a served file — you must bounce." **For listeners the inverse holds: a saved file IS served, to the next listener that spawns, with no bounce and no announcement.** An editing session therefore deploys *intermediate* states to the fleet without anyone acting. The fleet can hold several code versions at once, and none of them need correspond to a commit.

**Not proposing a fix here** — the options (spawn from an installed copy, stamp each listener with a git sha at spawn, or accept it and make the version legible in the log) have real trade-offs and this is fleet-shaped. Naming the mechanism so the next confusing log is diagnosed in a minute rather than an hour.

**Refines the transition-hazard entry above**: it is not "old code vs new code" — there is no single old version. Any listener alive across an editing session may hold a mix.

---

## 📥 FINDING 2026-08-02 (Mr. Radio 🦉 `1bf47c18`) — session gists have been degraded fleet-wide since the Mistral cutover

**Status**: found incidentally while reading listener logs, **not fixed** — a model-server bounce and GPU work are outside what I take unilaterally. No store row (Rick's no-new-rows order stands).

**What the server serves** (`GET :3001/v1/models`): `kaitchup/Phi-4-AutoRound-GPTQ-4bit`.
**What the config asks for** (since the 07-31 cutover `5499fdbf`, 29 references renamed): `ConfidentialMind/Mistral-Small-3.2-24B-Instruct-2506-GPTQ-AutoRound-TextOnly`.

Every Gister call 404s. **102 degraded gists today**, most recent 17:14. The listener is honest in the log — *"DEGRADED: gist unavailable — emitting 5-word prefix fallback … This is NOT a model-generated gist"* — but a 5-word prefix still *looks* like a gist in the UI, which is why nobody filed it.

**Same shape as "a saved file is not a served file."** The 07-31 session verified Mistral with a real inference call on its own dedicated venv/port. What was never verified is that **`:3001` — the port the Gister actually calls — was moved to it.**

**Two ways out**: bring `:3001` up on Mistral (what the cutover intended; venv + `svllmm` alias already exist), or revert the 29 config references to Phi-4. Rick's call.

---


Last updated: 2026-08-02 (Rachel 🕊️ `0d6df7b6` — bounce-button: served ≠ saved, and a whole press pressed)

---

## 📥 FINDING 2026-08-02 (Rachel 🕊️ `0d6df7b6`) — the bounce button was 404 on the running server; auth-401 + whole-press now proven; the endpoint tests were ungated

**No store row** — Rick's no-new-rows order tonight. Three jobs for María 🌸 (`2b9feb77`) on commit `5f40de15` (Managed bounce R2). Same shape three times: a saved file that was not a served/gated file.

**Job 2 finding (biggest) — committed ≠ deployed.** `POST /api/system/bounce` returned **404 on the live :7999**: the endpoint committed at 20:52 but the container last started 20:25 and reload is OFF, so the button was DEAD on the running server. María's own rule — "a saved file is not a served file" — broken within the hour of R2 being called done. Fixed by driving the sanctioned sequence: `bounce-dev-server.sh` (load the endpoint; 404→401 confirmed live) → `install-bounce-watcher.sh` (the watcher was NOT running — no `io/bounce` heartbeat → a press would 503; now a systemd --user unit, heartbeat fresh at 1s) → **the real authenticated press**.

**Whole press proven end-to-end (first time):** click → `202 triggered` at t=0 → watcher claimed the trigger + set `bounce.inprogress` at t=2s → :7999 DOWN at t=20s → HEALTHY at t=28s (all-clear). Observe loop only accepts "healthy" AFTER first seeing "down", so a pre-restart 200 cannot false-green it. Corroborated independently by María: container `StartedAt` moved 21:16:45 → 21:20:51.

**Job 1 — the auth-401 branch was untested.** `test_system_bounce.py` proved 409/503/202 but called the endpoint with a **fake `current_user`**, bypassing the auth dependency, so the 401 the commit names never ran. Closed by new `test_system_bounce_auth.py` (2 passed): drives the REAL chain (`HTTPBearerWith401` → `get_current_user`); unauth AND malformed-Bearer both 401 (a custom 401 subclass, not FastAPI's default 403 — the commit's "401" claim verified). Red-proof (documented): removing `Depends(get_current_user)` → unauth reaches the body → 503/202, not 401.

**Job 3 — those tests were invisible to the gate.** Both files lived in `src/cosa/tests/unit/rest/`, but the unit gate runs `pytest src/tests/unit/` only (`src/tests/run-unit-tests.sh`), so **0 were collected** — green locally, never in CI. Relocated both into `src/tests/unit/` (where sibling `test_bounce_watcher*.py` already live); verified by RUNNING the gate: `run-unit-tests.sh -k system_bounce` → **13 passed, 12142 deselected**. Chose relocate over allowlist deliberately.
- **SYSTEMIC (worth a real look):** no runner I could find collects `src/cosa/tests/` at all — `pyproject.toml` references it only to EXCLUDE it from coverage — yet it holds **~415 test files**. A whole tree of unit tests may be green-locally / ungated. Same failure shape as the 404, at scale.

**Uncommitted for the crew (Sam gates, María/Cheech commit):** `src/tests/unit/test_system_bounce_auth.py` (new), the `git mv` of `test_system_bounce.py` into `src/tests/unit/`, and the D2/D3 test files from the prior legs.

---

## 📥 STASHED 2026-08-02 (Cheech 🌿 `7edf6e5e`) — a review that stops at the process boundary passes an inert fix

**Not filed as a row, per Rick's board-to-zero directive tonight.** Recorded here because it is the second instance in one day, in different code, by different people.

**What happened.** Bug `f433fbae` D1 committed as `fd11cd30`: `ask_multiple_choice` now passes `response_default`, so an offline read should return the default instead of a 503. Sam reviewed it and PASSED it — he confirmed the 503 had drifted to `notifications.py:1068-1069`, reverted the plumb himself, and got the exact predicted failure text. A careful review by any normal standard.

Then Clayton, chasing an unrelated ruling about marking defaults, found the fix **delivers nothing**:

- the server's offline branch returns a plain `JSONResponse`, not a `data:` SSE frame the client parses;
- `OfflineEvent` requires a `response` field the server never sends — the default goes into `default_used` instead;
- so client validation fails and drops to an error dict. Honest, not forged. But the default never lands.

Sam retracted his own pass unprompted and named the miss himself: *"I gated the server emit and the plumb, never traced the client consume — the exact different-process seam."*

**Why it matters.** This is the same shape the late-answer-handback cascade caught four hours earlier: a dedupe ledger whose writer lived in a different process from its reader, whose test would have gone green while production failed. Different file, different people, same seam. A unit-level negative control proves the **plumb**, not the **delivery** — and the control is what makes the review feel finished.

**The rule that came out of it, now binding on this crew:** do not gate a cross-process fix by reading the chain. Reading is how it passed the first time. Execute it — drive a real call against a server forced into the failing state and assert on **what the caller actually receives**, provenance intact.

---

## 📥 SCOPED 2026-08-02 (Clayton 😎 `99913b08`) — bug f433fbae D2 does NOT fix the symptom Rick reported

**No store row** — Rick's no-new-rows order tonight. Two caveats, so D2 is never read as closing a complaint it doesn't touch.

**What D2 landed.** The blocking-ask verbs (`ask_yes_no` / `ask_multiple_choice` / `converse` / `ask_open_ended_batch`) now stamp an `idempotency_key`, and the server's response-required path re-attaches to the original notification on a repeat key instead of minting a second card. This closes the **in-process same-key re-POST** duplicate — `notify_user_sync`'s `retry_on_timeout` loop and any durable resend.

**Caveat 1 — a bounce still duplicates.** `_ask_idempotency_index` is an in-memory `OrderedDict`; a :7999 bounce wipes it, so the same key re-POSTed *after* a bounce misses and mints a new card. The existing fire-and-forget idempotency cache has the identical limitation. **Fix (deferred):** add an `idempotency_key` column to the `notifications` table (a migration on the hot table — none exists today, and the row has no spare metadata field) and look up by key so the dedup survives a process restart.

**Caveat 2 (the bigger finding, stated bluntly) — D2 does NOT fix the symptom Rick reported.** Rick's "re-answer the same question" came from **three separate ask INVOCATIONS**, each minting a *fresh* idempotency_key. No idempotency key — in-memory or DB-backed — dedups distinct invocations; only content-hashing the ask would, and nobody has ratified that. D2 fixes the retry-loop case, not the re-invocation case. The reload-OFF policy change (2026-08-01) plus D1's marked-default are what actually reduce the reported storm; D2 is defense-in-depth on top.

**Follow-up (D1 offline test) — pre-existing failure, must move to the SSE contract when fixed.** `src/tests/unit/test_notifications_api.py::TestNotifyResponseRequired::test_notify_response_required_offline_with_default` **already fails at the pre-tonight base** (`fd11cd30^`) — an empty-body test-harness issue, independent of D1. It is NOT a D1 regression. BUT: D1 changed the response-required offline path from a `JSONResponse` to an SSE `StreamingResponse` (ack + OfflineEvent frame). So whoever fixes that test's harness must **also** update it to assert the SSE contract (`response.status_code == 200`, `text/event-stream`, parse `data:` frames → `status: offline` / `response` / `default_used: true`) — a `response.json()` assertion on that path is now wrong by design. Same applies to `test_notify_response_required_open_ended_batch_accepted` if it exercises the offline path.

---

## 📥 FINDING 2026-08-02 (Tiberius 👑 `f63d0e28`) — the handback bounce-e2e can't be a :8000-scheduled job

**Status**: measured, resolved for THIS test, worth a venue-rule note. **No store row** — Rick's no-new-rows order tonight.

**The finding**: the two execution rules in my brief can't both hold for the late-answer handback e2e.
- **A :8000-scheduled test cannot bounce :8000.** The test-suite runner `Popen`s pytest as a *child of the :8000 server process* (`src/cosa/agents/test_suite/job.py`). A test that restarts :8000 to wipe the in-memory `pending_responses` waiters kills its own runner mid-run → deadlock, no results.
- **Bouncing the real :7999 is worse**, not a fallback: it's the live fleet server, and seeding+answering notification rows there writes to `lupin_db_dev` — the "no test touches a live dev data store" mandate.

**Resolution (Cheech green-lit 2026-08-01 20:32)**: the handback e2e stands up its **own uvicorn on a throwaway migrated DB** and bounces *that* via a genuine kill+restart. Real process-lifetime seam (in-memory waiters wiped, durable PG row survives), isolated, reproducible, no fleet disruption, no live-DB write. No manual :7999 bounce tonight.

**Also measured**: `lupin_db_dev` is already migrated — `answer_delivered_at` column + `idx_notifications_answer_owed` index present, `alembic_version = 3da5c0d1eee6`. So Rachel's deferred "live round-trip" precondition (deferred until the shared DB carries `3da5c0d1eee6`) is satisfied for the dev DB.

**LANDED 2026-08-02**: `src/tests/e2e/test_ask_answer_handback.py` (+ `_handback_e2e_server.py`) — THREE scenarios GREEN, 57s.
- (a) stream-death, server alive → answer reaches the asker via the re-attach poll → `responded`, no re-ask.
- (b) orphaned waiter (stream death) → answer OWED → travels via `answer_catchup.surface_owed_answers`; ack empties owed → surfaces once. Proves the catch-up path only.
- (c) **LIVE waiter wiped by a real restart** — hold the stream OPEN (waiter live), assert in-flight, restart (process death), then answer → travels via catch-up. Rick's mid-question-bounce case.
- **Sam's catch (2026-08-02)**: (b) alone oversold — closing the client stream makes uvicorn cancel the generator, whose `finally` DELETES the waiter, so the restart wiped nothing live (deleting it stayed green). Fixed: (b) renamed + descoped to orphaned-answer travel; (c) added for the live-waiter case.
- Falsifications EXECUTED (predicted text confirmed, restored): (1) inverted the owed predicate → catch-up empties → red; (2) neutralized (c)'s restart → the live waiter is woken (delivered), owed stays 0 → red. (2) proves (c)'s restart is load-bearing.
- Venue: own uvicorn (real notifications+websocket routers) on a throwaway migrated DB, bounced by kill+restart. Never touched :7999/:8000/`lupin_db_dev`.

**Finding worth the design owners' eyes (stale-PID bridge → NULL persona)**: `_voice_persona_for_sender_id` resolves the bridge via `find_session_by_id`, which **skips any bridge file whose filename PID is not a live process** (stale-session guard). So a session whose bridge is stale/dead at answer-persist time stamps `sender_persona = NULL` on the ask row — and that late answer becomes **unretrievable by persona**, the same §4.4 accepted gap as a persona-less session, but reached by a *different* door (a dead-PID bridge, not a failed allocation). Bounded + already-audible (the `[NOTIFY] ⚠️ … NO voice persona` warning fires), but the runbook gap is currently framed as "allocation failed" only; a dead bridge at persist time hits it too. Not a blocker; noting so the gap's framing is complete.

---

## 📥 FINDING 2026-08-02 (Tiffany 💍 `0768c103`) — two notification tests assert the pre-SSE offline contract; NOT "pre-existing", 40 minutes old

**Status**: reproduced and root-caused by me, **not fixed** — it is the f433fbae campaign's lane, not mine. **No store row** per Rick's no-new-rows order.

```
FAILED test_notifications_api.py::TestNotifyResponseRequired::test_notify_response_required_offline_with_default
FAILED test_notifications_api.py::TestNotifyResponseRequired::test_notify_response_required_open_ended_batch_accepted
        json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)
```

**Cause**: `1cd795c7` ("Bug f433fbae D1 (server half)") deliberately changed the offline branch from a plain `JSONResponse` to a `StreamingResponse` emitting two SSE frames. That is the correct fix and the commit is sound — it updated *its own* test. It did not update these two **twins in a different file**, which still call `.json()` on a response that is now an SSE stream.

**🔴 THE LABEL MATTERS.** These were reported to me as "pre-existing failures, not in my diff." The first half is right, the second is misleading: **I ran this exact class at 00:38 tonight and all five passed.** They broke at ~00:55. "Pre-existing" invites everyone to route around them; "someone changed the contract 40 minutes ago and two twins were missed" tells the owner it is theirs and still warm.

**Fix direction — assert the NEW contract, do NOT restore the JSON blob.** Drain the generator and assert both frames, `response=<default>`, `default_used=True`, exactly as `1cd795c7` did for its own test. This is the third instance tonight of the same shape (podcast tests `20c70793`, DM-judge `60bbb6ce`): a campaign moves a contract, a twin in another file keeps asserting the old one, and the cheapest green is the wrong one.

**Verified not caused by the bridge-guard work**: both still fail with `-o addopts=""`, so the `pytest.ini` marker change is exonerated.

---

## 📥 BACKLOG 2026-08-02 (Tiffany 💍 `0768c103`) — the all-clear's real blocker is the reconnect WINDOW, not the predicate

**Status**: measured tonight, NOT built, NOT ruled. **No store row** — Rick's broadcast ordered no new task items tonight, so this is stashed here deliberately.

**Context**: bug `784d4a2e` replaced the all-clear settle gate's plateau predicate with roster-coverage (Rick's direct ruling, 2026-08-02 ~00:20). The predicate change is right and is committed work. This entry is about what the fix EXPOSED rather than solved.

**The measurement** — a real `:7999` bounce at 00:25 ran the new gate:
```
all-clear FIRED on DEADLINE EXPIRY (boot #3): reached 10 recipient(s) after 15.3s;
reconnect curve 0→0→1→1→1→1→…→1   [29 polls flat at ONE]
10 session(s) had NOT rejoined and got NO all-clear (accepted loss, no re-fire): [10 ids]
```

**🔴 CORRECTED TWICE. Read both corrections — the second one partly restores the first, and that is the lesson.**

*First version*: "reconnection is slower than the 15-second window" (1 of 11 sockets back at fire time). *Correction 1*: I called that wrong and replaced it — the roster and the live-socket set were **never the same id space** (roster holds `0768c103-eb8d-…`, the socket registry holds `cc-listener-0768c103`), so the comparison could not match at all and the gate was **blind, not coarse**. Fixed under `784d4a2e`.

*Correction 2, measured on boot #4 with the fix live*: **both defects were real and stacked.** The id-space bug was masking a genuine timing problem, and now that the gate can actually see returning sessions, the timing problem is exposed and finally has a number under it. My first explanation was not wrong — it was **incomplete, and I called it wrong**. Over-correcting is its own error: a second story that fits the evidence does not automatically retire the first.

**🎯 THE NUMBER, measured on boot #4 (2026-08-02 01:17, `d96f59ce` live):**
```
01:17:08.404  all-clear FIRED on DEADLINE EXPIRY — 15.5s, curve 0→0→0→1→1→…→1
              9 session(s) named as missed
01:17:11.506  cc-listener-0768c103   ┐
01:17:11.511  cc-listener-7edf6e5e   │  ALL NINE of the "missed"
01:17:11.511  cc-listener-9056b85b   │  reconnect 3.1s LATER,
01:17:11.512  cc-listener-0d6df7b6   │  within 8 MILLISECONDS
01:17:11.513  cc-listener-f63d0e28   │  of each other
01:17:11.513  cc-listener-8a09f41c   │
01:17:11.513  cc-listener-5b2b4545   ┘  (+ 2 more)
```

**What this establishes, and it is the first hard evidence in this whole arc:**
- The fleet does **not** trickle back — it returns in one synchronized burst at **~18.6s after the gate starts**, roughly 3 seconds past a 15-second deadline. That looks like a fixed reconnect/backoff interval, not load-dependent scatter.
- **The deadline is the lever now, and it is short by about 3 seconds.** Every one of the 9 sessions named as an accepted loss was actually back moments later — and got nothing, because re-fire is barred.
- The gate itself is behaving correctly: it named exactly the sessions that genuinely had no socket at fire time. The instrument is sound; the window is wrong.

**✅ SECOND SAMPLE ARRIVED — boot #5, a peer's bounce minutes later. It CONFIRMS the burst and widens the spread:**
```
boot #4   fire 01:17:08.404 (15.5s)  →  9 listeners at 01:17:11.506   = +3.1s   (within 8ms)
boot #5   fire 01:21:14.801 (15.4s)  →  9 listeners at 01:21:19.813   = +5.0s   (within ~70ms)
```
Reconnection completes **~18.6s and ~20.4s** after the gate starts. **The 15s deadline misses it both times.** Two independent bounces, both a synchronized burst, both a total delivery loss.

**Worth noting how the second sample was obtained**: I asked Rick whether to fire two controlled bounces for measurement — a deliberate fleet disruption at 1am — and the ask timed out because a peer's bounce dropped it. That bounce *was* the sample. The question answered itself at zero cost to the fleet.

**Next, in order:**
1. **DELEGATED (Krishna, spawned 01:22)** — raise the deadline 15 → **30**, not 25: two samples at 18.6 and 20.4 are 1.8s apart at n=2, so leave real headroom rather than hugging the larger one. Splainer twin must state the measurements *and* that n=2 — it currently admits "15 is a GUESS", and the replacement must not read as more certain than two samples support. Plus a test that goes red if anyone tidies it back to 15.
2. **✅ ANSWERED — and it makes 30 the wrong number.** Krishna traced the burst to the listener's exponential backoff in `src/cosa/agents/utils/proxy_agents/base_config.py`: `RECONNECT_INITIAL_DELAY=1.0`, `BACKOFF_FACTOR=2.0`, `MAX_DELAY=30.0`, **no jitter** — which is exactly why all nine wake within 8ms of each other. The fleet lands on the **30-second cap wake**. So a 30s deadline *races the wake it is waiting for* — a coin flip, and the same "don't hug the sample" error I gave him, reappearing one level up. **Corrected to 40**, clear of the boundary. (Arithmetic being reconciled first: his series is 2/6/14/30, mine is 1/3/7/15/31 from `min(1.0·2^attempt, 30)`; we are choosing a config value against those boundaries, so the exact series and the offset between the disconnect clock and the gate clock have to be settled, not assumed.)

3. **🔴 THE REAL FIX IS JITTER, and it is Rick's call — fleet-wide blast radius.** Nine sessions waking within 8 milliseconds is a textbook thundering herd; the lockstep is a property of the backoff having no randomization. Adding jitter would spread the reconnects and make *any* deadline choice robust instead of boundary-sensitive. Also worth pricing: a 30s cap means a listener that misses early attempts waits half a minute, which is what pushes reconnection past any sane all-clear window in the first place. **Not touched** — a launch-wide backoff change is not something a bounce-arc worker should land unilaterally.

4. **Also fixed**: `main.py:472`'s fallback default was still 15. A fallback that disagrees with the key silently reverts to the known-wrong value if the key ever goes missing.
3. Only then consider the warning-phase ack list as a tighter roster — it may be unnecessary if the window is simply correct.

⚠️ **The roster over-count is real and still costs us**, independent of the id bug: the 00:25 warning was acked by only 2 distinct sessions while the roster listed 10. Krishna was **reaped at ~15:50** and his bridge file is still on the roster nine hours later — a session that will never reconnect, holding the gate to the deadline on every bounce.

⚠️ **A second, upstream collision** (Arnold, not fixable in the gate): the two id spaces meet at `session_id[:8]`, because the socket key carries only 8 characters. Two sessions sharing 8 leading characters would mark a real straggler as covered. That lives in how listeners are named, not in the gate.

---

## 📥 STASHED 2026-08-01 night (Mr. Radio 🦉 `9056b85b`) — two findings NOT filed as rows, per Rick's board-to-zero directive

Rick's broadcast `0152e7b0`: *"stop posting new task list items. NONE… stash it in the to-do file and we'll come back to it on another day."* Both of these would otherwise be store rows. Neither blocks anything.

**1. Tone's evidence sometimes hands back the whole message instead of the phrase it judged.**
Measured properly in commit `a09a2327` (probe + 31 tests). On the four probe bodies the behaviour is clean and defensible: the two *plainly-written* bodies (tone +2) get the whole body quoted — when prose is uniformly plain there is no offending phrase to point at, so "all of it" is a fair answer — while the two *jargon* bodies (tone −2/−1) get aimed quotes, 6/6. **The anomaly is on live DMs, not probe bodies**: two of mine scored tone **−1** and still echoed whole. On a negative grade there *is* something specific to point at, so the probe's pattern does not predict it. n=2. Not a grading defect — the weights are right — an evidence-quality one. Next step if picked up: run the tone grader against bodies that are plain-but-flawed, which is the cell the 2×2 does not contain.

**2. `io/mementos/tiberius.md` is a bare slot that nobody can clear.**
The last surviving `memento_io verify` finding on this repo. Its content is **byte-identical** to `tiberius-legacy-2026.07.14-193034.md`, so the data-loss window is already closed — what remains is a label, not a risk. Clearing a bare slot needs `write --persona <p> --session-id <sid>`, and Tiberius's seat is gone, so the session id would have to be invented. That is exactly what `BARE_SLOT_EXEMPTIONS` in `memento_io.py` exists for, and three slots already sit in it for this reason. **It is a planning-is-prompting change, not a Lupin one**, and adding a fifth entry deliberately reds `test_exemptions_are_exactly_the_ruled_set` so a human has to notice — which is the design, not an obstacle. Deliberately not done from this repo tonight.

---

## 📥 BACKLOG 2026-08-01 evening (Rick's idea, captured by Mr. Radio 🦉 `9056b85b`) — reject over-long DMs at a hidden, randomized word limit

**Status**: idea captured, NOT built, NOT ruled. No store row yet — this is a design Rick floated, not owed work.

**Rick's proposal, in his framing**: tell everyone up front that exceeding the word limit produces an **error and the DM is not sent**. Do **not** tell them what the limit is, and draw it **randomly between 150 and 250** so it cannot be gamed. The published advice is simply to stay within the recommended limits.

**Why the lever is right.** A grade is advisory. The judge published 👎s all evening and nobody was blocked by one, which is exactly how a ~1000-word DM still went out (Rick's broadcast `d8099c6c`). A rejection forces the rewrite — a different instrument, not a louder version of the same one.

**Why the randomization is smarter than it first reads.** A known limit of 200 puts everyone at 199 — compliance, but it parks all traffic at the ceiling. A threshold drawn from 150–250 turns the cliff into a **slope of rejection probability**: ~10% at 160 words, ~90% at 240. The risk-averse response is to go well under 150 rather than hug the edge, and that behaviour falls out of the mechanism instead of out of asking nicely.

**🔴 THE ONE CHANGE I'd insist on — seed the threshold on a HASH OF THE BODY, not a fresh random per call.** As drafted, a rejected DM retried *unchanged* succeeds about half the time, which teaches **"retry beats editing"** — the one gaming vector the randomization itself introduces. Hashing keeps every property wanted (unknowable in advance, unguessable, spread over 150–250) and adds the one needed: the same text always gets the same verdict, so a rejection sticks until the words actually change. It also keeps the send path reproducible for debugging and tests.

**Two things to settle before it ships**
1. **What counts as a word.** A pasted stack trace, code block, JSON blob or long URL blows any limit — and those are sometimes what a DM legitimately carries. Strip fenced blocks from the count, or the rule punishes the wrong messages.
2. **What the error says.** That message is the *entire* teaching surface. It should name the ~60-word target, say the limit is variable so nobody burns a cycle reverse-engineering it, and point at the doc-link pattern for anything genuinely long. "Too long" alone produces guessing.

**Interaction with the open bug rows**: this largely retires `0fc5b8f0` (the −2 length grade saturating at 250) for *enforcement* — nothing that long gets sent at all — but the saturation still distorts the audit history, so that row stays open rather than closing on this.

---

## 📋 DECISIONS LOG 2026-08-01 (Cheech 🌿 `7edf6e5e` + María 🌸 `2b9feb77`) — late-answer-handback cascade post-game

**Retro**: `io/post-games/2026.08.01-late-answer-handback-cascade-post-game.md` (local corpus, gitignored). Cascade telemetry: 15 stage-reviews, 5 sections, 43 min, 51 findings, 0 rejected, 0 escalations, no code under Rick's gate. Cast reaped 16:54; post-game opened 16:58.

**R-1 — the deposits carried the harvest through a reap-before-harvest, and that is a receipt, not a mechanism claim.** 18 rolling deposits from 4 of 4 cascade seats, every one carrying provenance; the reap cost the retro almost nothing. **María, cross-examined, refused the causal version**: *"with one run I cannot separate 'a mechanism made it hold' from 'four diligent seats made it hold.' Diligence is the confound and we did not control for it."* Accepted verbatim — headline the receipt, drop the causation.

**R-1b — two runs now point the same way, on different tiers.** 2026-07-27 measured the *teardown-time* deposit (memento element 9) → 1 of 6. 2026-08-01 measured the *during-run* deposit → 4 of 4. Consistent with `post-game.md` §3.4 ranking tier 2 above tier 3, and the first positive control that ranking has. Still not a controlled comparison — the seats differ.

**R-1c — PENDING RICK.** The 2026-07-27 ruling R1 (*"every stand-down instruction must name element 9"*) is a *"remember to do this"* rule — the anti-pattern `post-game.md` §7 names by name. Proposal: demote it to a backstop under a headline of *rely on the during-run deposit*, the same demotion §3.3 applied to the reap gate. **Not applied — and the decision row was RETIRED the same evening** (`20efd445`, dropped). Rick: *"explain or retire."* The honest explanation is that it should not have been minted. The post-game workflow says open threads become store items rather than sitting in prose; I applied that to an *observation*, which already lived in two better places (the retro and the corpus README standing note). The result was a row that **read** as owed work while nothing was blocked on it and nobody was doing the wrong thing.

It also failed the bar I had just set for everything else in the same retro: both pattern candidates stay candidates until **cross-day** recurrence, yet I routed this one — two runs, different tiers, diligence uncontrolled by María's own refutation — to the operator queue anyway. Applying my own bar retires it. The July rule stands as a belt beside today's suspenders; keeping both costs nothing, and a third run re-surfaces it with evidence attached.

**R-2 — Candidate 1 (an artifact belonging to no section goes un-updated) stays a CANDIDATE at four instances.** Tiberius 👑 refuted the promotion *from his own deposit, before anyone asked*: "count causes, not symptoms before you let evidence promote a rule." María: "Nothing moves it. Four instances, one cause, one run." A reaped seat winning an argument with a live manager is what the provenance field is for.

**R-3 — Candidate 2 (a close check scoped to its author's own conditions) stays a CANDIDATE, and María's self-contradicting crew brief is NOT folded in to reach two.** Her ruling: same *family*, different *mechanism*; folding it in inflates the evidence. What it adds is a second author and a different engagement. **Promotion bar: cross-DAY recurrence.**

**R-4 — on "0 rejected across 51 findings": the asymmetry is the finding, not the zero — now supported by a sample of two.** Tension was real on the manager axis (reviewers refuted the manager 4×; two reviewers disagreed substantively; one retired her own concern on evidence) and absent on the author axis (51 for 51 conceded, never once defended). María supplied the discriminator — *"was any ACCEPTED finding wrong? Nobody re-derived one"* — and it was run rather than argued: two accepted findings re-derived cold, both hold at the exact cited lines (`emit_to_session` has no `return` statement at all; the ORM partial-index prior art sits at `postgres_models.py:227-231`). **2 of 51 is a spot check.** Hypothesis → supported, not proven.

**The day's through-line, from the design under review straight into the review of it**: *a value that cannot distinguish "I know" from "I don't know" was used as a gate.* A send read as a receipt · a stored default read as a given answer · "returns nothing" read as a proof · "the same ledger" read as one process · a headline count read as its own tables. **The manager reported ~70 findings upward all afternoon against a true 51 — and the moderator of this very post-game announced 20 deposits against a true 18, one hour after reading a memento whose headline finding is that exact defect.** Both corrected in flight and left visible rather than scrubbed.

---

## ⏳ PENDING — 2026-08-01 (Cheech 🌿 `070d88a5`) — podcast E2E blocked on container Claude Code re-auth

**Status**: OPEN, needs Rick first thing in the morning. Store row `bff6bc6c` (bug, owner `rick`, next_chase 2026-08-01 06:45 UTC).

**What shipped tonight (done, no action needed)**: podcast generator hosts renamed Nora→Maria, Quentin→"Mr. Radio" across config/code (commit `1935089d`, reviewed, 337/337 green), plus a fix so a failed AI call now fails loudly instead of faking an empty script (commit `419174ed`, reviewed, 30/30 green).

**What's still blocked**: the `lupin-rest-dev` container's Claude Code login is revoked (401 "OAuth access token has been revoked"). Rick ran `claude auth login` once tonight — `claude auth status` reported success, but a real call still 401'd immediately after, so the login didn't actually take. **`claude auth status` is unreliable in this container — verify with a live call** (`docker exec lupin-rest-dev claude -p "reply PONG"` and confirm it actually returns PONG), not just the status field. Until this is genuinely fixed, no bounded-CC job (podcast, BFE, TFE, deep research, presentation) can run in that container.

**Next step**: Rick re-authenticates, verifies with the live-probe method above, then re-run the real podcast job against `src/rnd/v0.1.9/2026.07.19-brevity-mandate-injection-riders.md` to get the actual rendered episode with Maria/Mr. Radio dialogue.

---

## ⏳ PENDING DECISION 2026-07-26 (Mr. Radio 🦉 `9a63d597`) — `7ee5b646`: the HWM janitor switch

**Status**: OPEN, awaiting Rick. Store row `7ee5b646` (decision, `gate_class=operator`).

**The situation**: the DM-inbox bookmark janitor shipped with `arbiter enable hwm deletion = False`, which **diverges from his "let the janitor drain them" ruling**. I flipped it to OFF after measuring that the plan's safety claim was inverted — reaping a live session's bookmark does not duplicate its DMs, it **silently swallows the un-surfaced ones** (a missing file reads as never-seeded, so the reconcile records the inbox as already-seen and surfaces nothing). That re-creates bug `59f355e0`.

**What Rick decides**: whether to turn it on. The 7-day window is already his ruling and needs no change. Nothing drains until the INI key flips.

---

## ⏳ ~~PENDING DECISION~~ ✅ RULED 2026-07-27 — `2b20a6d6`: backend-blind test isolation (kept for the record)

**Status**: ✅ **CLOSED 2026-07-27** — both arms ruled by Rick; see the Decisions Log entry immediately above. Store row `2b20a6d6` carries both rulings as amendments. Original framing retained below.

**The situation**: nine `cosa/memory/*` classes route on the ambient `vector store backend` flag and silently discard any `db_path` handed to them. `postgres` has been live since 2026-07-07 with no per-block override, so a test that constructs one believing it is isolated is reading and writing the shared store. One module (`test_answer_is_correct`) is fixed — commit `e4113d64`. Six more in `src/tests/integration/` are not.

**What Rick decides**: which remedy, and what happens to the six.

**My recommendation, revised after measuring**: fix the three production call sites first, THEN raise at the source, then add the guard test. The original recommendation said "raise" outright; checking its stated risk showed **three live sites pass `db_path` under postgres** (`main.py:512`, `responder.py:260`, `prediction_engine.py:165`), so a raise breaks them today. `routers/system.py:272` is the one good citizen — it asks the flag before building a path, and is the shape the others should take.

**Why I did not just do it**: the six live on the gated `:8000` suite; a change there cannot be verified without monopolizing the test server, which is the second half of what this decision decides. Also worth naming — `main.py` gates on `solution snapshots manager type`, a **second authority for the same fact** with nothing comparing the two. Reconciling that belongs to whichever remedy wins.

**Related**: `d621b111` (the bug + full sweep) · `d6f11dfd` (closed) · `cfcbb703` Family B (the allowlist that missed this) · `d8a23fca`

---

## 📥 BACKLOG 2026-07-25 (Rick's idea, captured by Mr. Radio 🦉 `43ff094e`) — ASR warm-up endpoint to pre-heat Cloud Run

**Status**: possible FUTURE performance improvement. Not owed work, no store row, not scheduled. Rick's framing: *"I want to be able to warm up cloud run before I actually use the app. And a voice to text warm up endpoint would be great."*

**The problem**: `lupin-model-server` is a scale-to-zero L4 Cloud Run service (`minScale=0`, deliberate — Rick 2026-07-25: *"cloud run should not be warm during the day… I don't want to pay for it sitting there doing nothing"*). So the FIRST voice interaction of a session eats the cold start. Measured today: **32.0s** wall clock for the first authenticated call, versus **4.1s** for a transcribe against an already-warm instance. That ~28s is paid by whoever speaks first.

**Design note that makes this cheap — measured, not assumed.** The warm-up does NOT need to send audio. The model server eager-loads its pipelines at startup (`_load_whisper()`, "Eager-load distil-whisper pipeline to GPU 0"), so ANY request that causes an instance to start also loads the models. Receipt from today's cold start:
```
GET /health  →  HTTP 200 in 32.0s
{"status":"ready","models_loaded":["whisper","code_rank_embed","nomic_embed_text_v1_5"],
 "vram_used_mb":2496,"uptime_seconds":25,"load_errors":[]}
```
`uptime_seconds: 25` on a 32s call ⇒ that call STARTED the instance, and by the time it answered the models were already resident. **An authenticated `GET /health` is a complete warm-up.** No audio round-trip, no `/transcribe`, no upload — which also means the warm-up costs nothing beyond the instance-start it is deliberately buying.

**Sketch** (whoever picks this up should re-derive, not trust this):
- A Lupin endpoint (e.g. `POST /api/asr/warm`) that fires the authenticated `GET {LUPIN_MODEL_SERVER_URL}/health` and returns promptly — the caller wants "I started it", not "I waited for it".
- Fire-and-forget / non-blocking, so the UI can trigger it on page load or on mic-button focus without stalling.
- Idempotent + cheap to call repeatedly; a warm instance answers in ms.
- Honest reporting: return whether the instance was already warm (`uptime_seconds`) vs just started, so the UI can say "ready" vs "warming, ~30s".
- ⚠️ **Cost coupling** — this is the one thing to think hard about. A warm-up trigger wired to something automatic (page load, a poll, a heartbeat) re-creates by the back door exactly the always-warm billing Rick just rejected. It should be USER-INTENT-driven (mic focus, an explicit button) or explicitly rate-limited, and that constraint belongs in the design, not in a comment.

**Related**: today's STT 401 (row `30198303`, closed) and `src/cosa/utils/secret_drift.py`. The warm-up path would exercise the same auth chain, so it doubles as an early-warning probe for key drift — but see the `unknown`-is-not-a-pass rule in that module before treating a warm-up failure as a health signal.

---

## 🔴 P0 FOR TOMORROW (2026-07-25) — VM persona-404: APPLY the code-route fix on the VM

**Repo side is DONE + green** (session b46c77e3, `wip-v0.1.9`): `atomic_write_json` fchmod-0660-before-replace, `register_session.py` explicit `chmod 2770` (setgid) sessions dir, 3 new mode tests, 252 unit tests pass. Design in `src/rnd/v0.1.9/2026.07.24-vm-persona-bridge-mount-uid-divergence.md` **FINAL PLAN v3** (approved by two independent reviewers — Sam 🎙️ + local LLM expert — GO-WITH-CHANGES, all folded).

**Morning steps (VM only, NOT yet applied):**
1. `cloud-gpu.env`: add `LUPIN_HOST_SESSIONS_DIR=/home/admin_rickruiz_altostrat_com/.claude/sessions` + `LUPIN_BRIDGE_GID=1721846087`.
2. `docker-compose.cloud-gpu.yml` `rest` service: long-form bind (`create_host_path: false`) of sessions dir + `group_add: ["${LUPIN_BRIDGE_GID:?...}"]` — verify via `compose … config | grep sessions` (never `sudo`).
3. VM: `chmod 2770 ~/.claude/sessions`; backfill `chgrp 1721846087 + chmod 660 ~/.claude/sessions/cc-*.json`.
4. Push repo change to VM (`./src` bind covers container + host hook); recreate `--env-file cloud-gpu.env --no-deps --force-recreate lupin-rest`.
5. **Bidirectional runtime test** (the crux): host writes bridge → container `set_voice_persona()` → assert numeric owner 1001 / group 1721846087 / mode 0660 → host rewrites → container reads again. Then fresh session `request_persona()` → allocated (not 404); confirm `notify()`/OAuth/health survive; `docker inspect` both mounts.
6. VM `lupin-host-test` is currently STARTED (running); `acl` pkg was installed during diagnosis (now moot — code route chosen).

---

## 🔴 P0 FOR TOMORROW (2026-07-17) — Task-board state classification: finish the analysis

**Priority: 0 (HIGHEST). Assignee: Mr. Radio 🦉. Filed: 2026-07-16 (session 1a52ceb2, Rick's session-end directive).**

- **[LUPIN] Task-board state classification for workflow analysis — the doc + its amendment.**
  - **Document**: `src/rnd/v0.1.9/2026.07.16-task-board-state-classification-for-workflow-analysis.md` (commits `78854959` report + `5e8373c1` amendment)
  - **⛔ READ THE AMENDMENT FIRST — the report's central causal claim is REFUTED by my own measurement.** The amendment outranks the report. Do not re-ship the retracted claims:
    - ⛔ *"the board grows BY CONSTRUCTION (receipts gate on exit, none on entrance)"* — mechanism real, **effect ABSENT**.
    - ⛔ *"the board only grows"* — **FALSE as a steady state** (07-13 closed 46/46).
  - **Measured truth** (store Postgres direct, read-only — `task_items` + `task_events`): **all-time closure 861/925 = 93.1%** · **oldest OPEN item = 4 days, ZERO older than a week** · **40 of 64 open rows are <1 day old** · 3-day burst **158 arrived / 101 (64%) closed** · **52% of the open board belongs to the crew reaped at 22:11** ⇒ **the board didn't rot, it was DECAPITATED MID-SPRINT** · **I am the single largest minter of the burst I catalogued** (35 rows / 3 sessions).
  - **Findings that SURVIVE the refutation** (these are the real work): **C1** zombie items N≥4 (owner already reaped at mint time) · **C3** chase-expired ≥7 · **C4/C5** · **C7: 41 P1 / 65% — priority carries no information** · **the Stop-hook owed-work oracle LIES** (told me "2 in-progress" when the store said 0; told María "10" when the store said 2 — N=2, two seats, one hour) · **THE FILTER DEFECT: §6 mandates scoped queries, and a scoped query CANNOT show you that half the board is someone else's. I declared "board clean" 3× — each TRUE OF MY FILTER.** (María owns the §6 fix; finding is mine.)
  - **The meta-lesson, banked**: *a finding that CONFIRMS the boss's suspicion passes a checkpoint that a contradicting one never would.* Rick was angry; my catalog agreed; I never ran the one number my own report called "the number that actually proves it." María sent it back. **Agreement is not a checkpoint — it is the absence of one.**
  - **Next actions**: (1) drive the surviving findings (C1/C3/C7 + the Stop-hook oracle + the filter defect) to filed, owned store items; (2) reconcile with María's workflow analysis — this doc was written *for* her lane; (3) decide whether the retracted framing needs a correction anywhere it was already relayed.

---

## 📋 DECISIONS LOG 2026-07-15 (Mr. Radio 🦉, session bf549da1) — tmux fleet-killer cascade close-out

- **Cascade `cascade-tmux-fleet-killer` COMPLETE** (the P0 below, EXECUTED): 3 sections × 3 stages, 34 findings (0 foundational, 0 votes, 0 user escalations), ~55 min. Plan final-current on disk; Step-9 revision-handoff doc: `src/rnd/v0.1.9/2026.07.15-cascade-tmux-fleet-killer-revision-handoff.md`.
- **OSQ-1 CONFIRMED (Rick, /plan-decide one-touch, 03:26Z)**: execve kill-tracer ships, ordered LAST in §10 — install-only-on-request preserves the sudo gate.
- **Implementation = FULL SWE-team workflow (Rick, voice, via María relay 03:27Z)**: `/spin-up-swe-team` crew (Implementer + Reviewer + Tester), implementer seat cold-context-briefed on the handoff doc + plan ONLY.
- **OSQ-4 ruled by concurrence**: env-strip sufficient, `-S`/`-L` NOT adopted; AC5 = standing precedence canary. **OSQ-5**: vertex WIP lane orphaned (creator c8a18353 died 9 s after launching its own killer pytest) — cleared for edit+restore; vertex-lane continuity store task `bd0b728b` minted.
- [ ] **v1.N candidate: cascade-tmux-fleet-killer workflow-guidance batch (19 items)** (cascade cascade-tmux-fleet-killer, Manager Mr. Radio 🦉, filed 2026-07-15). Five manager moves ran ahead of the codified playbook (forward cross-section folds under a ratified ownership map · ownership-map-at-ratification · conditional ratify-by-concurrence · carried-items handoff field · probe-before-declare with delivery-clock); full 19-item all-seats index in handoff doc §6. Proposed fold targets: plan-review-cascaded.md §Step 5/§decomposition, common.md §Step 5/§Heartbeat Handling, defaults.md §Severity-tag metadata schema. Source: kind: manager_self_audit_sweep post on cascade-tmux-fleet-killer at 2026-07-15T03:33:43Z.

## 📥 BACKLOG 2026-07-07 PM (Tiberius 👑, session 4e12c586) — post-switchover live-voice E2E pulled off the board (Rick voice order)

**Rick (voice, 2026-07-07 ~22:35 EDT): "push this task item into the to-do queue — it does not belong on the board: ee23fca8."** Store item `ee23fca8` DROPPED with this backlog entry as its durable landing pad. Context: the item was the post-switchover live-voice E2E for `766bb609` (persona voice_id honored per session), blocked on the lane-1 flip; Rick killed the flip the same evening with a global multiplexer-parity verdict ("still ugly, still incomplete for the MVP" — logged HIGH in intake `603d9275`), so the E2E has no near-term trigger.

**Resume-when**: the multiplexer reaches Rick's MVP layout/functionality-parity bar AND the lane-1 flip (multiplexer = live TTS client) actually lands.

**Scope at resume (verbatim from the store item)**: E2E driving ≥2 sessions with distinct voice personas; assert each `/api/get-speech-elevenlabs` POST carries that session's `voice_id` (present→honored) and a persona-less notification omits the key → server default voice, consuming server seam `speech.py:558`. Cite reviewed commit `76946d9a` + merge `a9dd6f41`. Prereq receipt: playback consumer `4f14d38f` is DONE. Also-owed cosmetic sweep bundled in the old item body: `wireTtsPlayback` comment names default voice "(Sam)" but the real default is config key `elevenlabs tts default voice id` — comment-only.

---

## 🔝 #1 PRIORITY for the `wip-v0.1.9` bug-fix branch (Rick, 2026-06-26) — Multiplexer → notifications-client LAYOUT-LEVEL parity

**Directive**: get the multiplexer's CC-notifications surface to *real layout-level parity* with the legacy notifications client. This is the **#1 priority for the current bug-fix development branch** (Rick, voice, 2026-06-26).

**Holder (all discrepancies live here)**: `src/rnd/v0.1.9/2026.06.25-notifications-to-multiplexer-migration-discrepancies/` — index `00-index.md`; the section-layout gap analysis is `01-mux-vs-legacy-notifications-section-gap-analysis.md`. New discrepancy docs (CSS/visual, behavior, event-wiring) land in this folder as found.

**Substrate — verified gap analysis** (doc 01 in the holder). Confirmed section-level reorder:
- **Intended (legacy)**: broadcast card *(with nested Recent-Activity history)* → focus bar *(TTS preview above it)* → sessions container.
- **Mux actual**: focus bar hoisted to top → TTS preview orphaned as a sibling below it → sessions → jobs → **broadcast exiled to the bottom** → Recent-Activity **de-nested** as a separate pane.
- Plus per-message regressions: pause/stop/proxy-ratify dropped.

**Remediation buckets (gap doc §6)**: B1 restore section order (broadcast **+ re-nested Recent-Activity** → focus-bar → sessions); B2 relocate TTS preview into/above the focus bar; B3 restore section-header controls (count/filter/history/clear-all); B4 restore per-message pause/stop; B5 CSS pass LAST.

**Design calls — ✅ ALL RESOLVED** (Rick `/plan-decide`, 2026-06-26; §Decisions Log): a/b/c (broadcast-at-top + re-nest Recent-Activity inside broadcast + restore per-message pause/stop) **plus** the audit-surfaced d/e/f/g — Action-Required **full-funnel restore** (+ rich responder), TTS-Queue **full 1:1 restore** (chrome + per-item queue), Task-List **kept as a documented superset**, and **port ALL 7 absent accordions → total 13/13 parity**.

**Build-plan corpus — ✅ DRAFTED & COMMITTED** (`995dc952`, NOT pushed): 11 plans in `…/05-build-plans/` (00-index + shared template; 01 CC-session B1–B5 keystone; 02–04 the 3 partials; 05–11 the 7 absent), plus the **F0 shared-`AudioStore` foundation** finding (gates plans 01/02/03/05) and the consolidated cascaded-review agenda (questions e′–m).

### 🟥 #1 ACTION — Saturday 2026-06-27: run the 11 build-plan drafts through CASCADED REVIEW
**#1 priority for Sat 2026-06-27 (Rick).** Run ALL 11 drafts in `src/rnd/v0.1.9/2026.06.25-notifications-to-multiplexer-migration-discrepancies/05-build-plans/` through the **cascaded plan-review** process (`/plan-review-cascaded`) on the **dev server** (not the laptop). Start with **F0 (AudioStore shared foundation)** + **plan 01 (CC-session keystone)**; settle the **e′–m** review agenda (esp. e′ TTS reorder = FIFO vs drag · j/k dev-pane gating · i WS-scope filtering · m the jobs-pane delete-routing bug). Implementation begins ONLY after review ratifies each plan (manage-don't-build · 100% L/B/F · visual rebaseline).

### ✅ STATUS 2026-06-29 (Mr. Radio 🦉, session 2f4feb0a) — Plan-01 keystone chain BUILT + PUSHED
The ratified **Plan 01 (CC-session B1–B5)** keystone chain is largely landed + **pushed** (`wip-v0.1.9` → origin, HEAD `f333b6c2`, green-gated tsc 0 + TS suite 1993/1993):
- **B1** section reorder + commons re-nest — `5906508f` ✅ · **B2** slider → header region — `f86efef3` ✅ · **B3** own-only filter + section-header controls — `0f6d9ba0` ✅ · **B4** keystone per-message ⏸/⏹ + proxy-ratify — `24298595` (merged `d89e3e20`) ✅ · **F0** AudioStore/TtsQueueStore foundation (00b a/b/c/e/f, gates 01/02/03/05) — `f2204db1` (merged `c2cfa731`) ✅ · **2 reds** (governance hermeticity, C2-b premise) — `e0b3be32`/`d3b668d3` ✅

**Remaining on the mux-parity arc**:
- [ ] **B5** — CSS single-source into the shared sheet + Layout-Parity Oracle T2/T3 + golden snapshot rebaseline (gated LAST; pins against B3's finalized selectors).
- [ ] **F0-d call-site** — DEFERRED on **decision `d1bdb7ca`** (mux TTS architecture: server-push vs client-initiate). The mux has NO client-initiate TTS path today; building one is Rick's architecture call, to pair with the 00c / Plan-01 speak-gesture lane. F0 foundation ships complete without it; B4's identity half is mock-verified until F0-d wires the real boot.
- [ ] **Plans 02–04** (Action-Required, TTS-Queue, Task-List partials) + **05–11** (the 7 absent accordions) — still pending build/review.

### ✅ STATUS 2026-06-30 (Mr. Radio 🦉, session ef70b5f4) — Mux MVP-FINISH remediation BUILT + INTEGRATED (push authorized; flip gated on Rick's visual sign-off)

The ratified **mux MVP-finish remediation** (6 items; plan `src/rnd/v0.1.9/2026.06.30-mux-mvp-finish-remediation-plan.md`) is **BUILT, reviewed, committed-held, and integrated** on `wip-v0.1.9` (HEAD `1351976f`). Execution log: `src/rnd/v0.1.9/2026.06.30-mux-mvp-finish-build-execution-log.md`.
- **L1** bugs `d9d8d651` · **L2** AR+PLY `f48b0bf0` · **L3** VIS `ce164056` · **L4** NAV `6c20b7c3` · **AudioRecorder c8** `8a2c421a` — all reviewed-green, merged clean (3 shared-file carve-outs composed).
- **Gates GREEN**: V-P6 3/3 · gate E4 · directory-wide c8 100% · merged suite 2051/2051 · WS smoke 50/50. Dist builds.
- **:8000**: E2E (`ts-55f92b50`) + integration (`ts-13e9fc86`) submitted — **results for AM review** (Rick: rerun in the morning is fine).

**☀️ 2026-07-01 AM — Rick action items:**
- [ ] **GCP: `terraform apply` the model-server → Cloud Run split** (Tiberius 👑 session eb4b105f). Committed-held `c89c31ea`, pushed in `df0c1edf`; reviewed GREEN (Tiberius adversarial + María #1-#4 SOURCE + Arnold dry-side; **F-T1 caught+fixed** — scale-schedule jobs `oidc_token`→`oauth_token` for the Cloud Run Admin API, else the min-toggle 403s and the warm window silently never activates). **Rick's go + `gcloud` login — real money.** ⚠️ Apply DURING 09:00-23:00 EDT (finding #8 first-apply overnight warm-leak) → then ping **Arnold 🪨** for the WITH-CREDS green-bar (embedding+STT 200 vs the live `…run.app`; #6 the true-green gate). Cross-repo: VM-side PGA + `*.run.app` DNS + suspend/resume IAM grant live in the `terraforming-vms` handoff (02-vm-downgrade-handoff.md). **Runbook: store task `c3fafac5`.** **DECISION (ratified 2026-06-30, Rick): BUY the split — ≈$527/mo, ~$96/mo (~15%) cheaper than always-on; weekday-only Mon-Fri 09:00-23:00 + VM SUSPEND-not-stop + monthly-only (CUD dropped).** Design: `src/rnd/v0.1.9/2026.06.30-gpu-model-server-cloud-run-split/` (01-design + 03-cost-reprice).
- [ ] **`a5559b49` — visual-regression rebaseline**: env-drift (host↔container libfreetype AA), NOT code. `ce216d11` held (fonts-dejavu-core + fingerprint guard). Landing to true 37/37 via Cheech's treadmill-immune run (`auto_fix_on_failure=false`); 30+ rebaseline PNGs commit local-held. **If it didn't land tonight**: resume runbook in `src/rnd/v0.1.9/2026.06.30-visual-regression-env-drift-root-cause.md` §Phase-2 (pause completion-watchdog OR per-run `auto_fix_on_failure=false` → clear 4 persisted RED jobs → cold `--update`+compare all 36). Blocks nothing downstream. Follow-on: arbiter dual-false-positive bug `262c59f6` (RED-first).
- [ ] **Visual sign-off** on the :8000 E2E **visual-regression diffs** — they WILL diff on the INTENDED UI (new AR/PLY panels, nav bar, header polish, V9 strip-icon). The one EXECUTOR:HUMAN tier → then **golden rebaseline**.
- [ ] **The FLIP** (`lupin-app.ini:883` `legacy notifications redirect enabled=True`) — Rick's word, AFTER visual sign-off. Push landed the mux code DORMANT behind the un-flipped flag.
- [ ] **Oracle-held rows** — if the E2E Oracle geometry surfaces a target: V13 (stale-check), V6/V7 inline, V10a spacing, L2 Playing-N-vs-Queued-N redundancy + AR widget tint. Crew (Krishna 🦚 / Sam 🎙️ / Clayton 😎) held ALIVE on standby to fix fast.
- [ ] **6 admin NAV items** DEFERRED (L4 `TODO(post-MVP)` in `NavBarRenderer.ts`) — roles-claim shape unverified vs `jwt_service`; verify before porting admin-gating.

### Possible future enhancement (NOT a priority — Rick de-prioritized 2026-06-26; store task `69edd619` dropped)
- [ ] **[LUPIN] `reason` discriminator on `voice_persona_released`** — add `reason={exit|reassigned|borrowed_return|clear}` to the WS payload (emit `voice_persona.py:~570`; catalog passthrough `notifications.py:~609`; consumers: web notifications.js + mux + mobile). Retires the client-side debounce-guess for true-exit vs benign-release. Mobile ships fine on its 3-5s debounce without it. Revisit only when convenient.
- [ ] **[LUPIN] Fleet-status board: give the heartbeat-arbiter its own "infra" lane** — the board truncates session `lupin-arbiter-app-8001` → `lupin-ar` and files it under `(Unmanaged) … worker / unknown`, so the standing heartbeat/owed-work arbiter reads like a mystery idle worker. Give it a dedicated infra row (or show its full name + an "infra" tag) so it's not confused with crew workers. Cosmetic only — arbiter is healthy/alive, this is a renderer change. DEFERRED under the mux↔legacy-notifications UI parity freeze (Rick, 2026-06-26 — no changes to either UI until parity lands). Filed by María 🌸 (session `ae92e658`, 2026-06-26).

---

## ▶ DECISION (2026-06-26, Rick voice ruling) — ABANDON LanceDB → PostgreSQL + pgvector (v0.2.0)

**Ruling**: Move off LanceDB entirely. Adopt **PostgreSQL + an embeddings / similarity-search extension (pgvector)** as the vector store. **No nightly/standing compaction** — the whole incident class that drove Bucket 3 disappears with LanceDB. Rick: "I don't want to put any more effort into it." The 88GB-incident remediation items (`5daf94a0` + Phase B compaction) are **CLOSED as superseded** — Phase A rebuild already reclaimed ~89GB (commit `63bfb1b4`, 90.46GB→1.07GB), more than enough runway to coast until the migration lands.

### v0.2.0 backlog (new dev branch)
- [ ] **[LUPIN] v0.2.0: LanceDB → PostgreSQL + pgvector migration** — stand up a Postgres-backed vector store (pgvector embeddings + similarity search) replacing LanceDB for `input_and_output_tbl` (and any other LanceDB-backed tables). Encompasses: schema design, embedding column + index strategy (HNSW vs IVFFlat), data backfill from the current LanceDB store, repo/DAO swap, config keys + splainer, 100% line/branch/function tests, and a cutover + rollback plan. Targets the **v0.2.0 dev branch**. Supersedes ALL LanceDB compaction/rebuild work (Bucket 3, TODO 461/462/1668/1745).

### 🗄️ LONG-TERM (deferred, NOT scheduled) — LanceDB source-code teardown (Phase 2)
**Context (2026-07-08, Mr. Radio 🦉, session 98a1c238 — Rick voice ruling):** the LanceDB **on-disk store** was removed today — DATA01 working-tree copy deleted (30G reclaimed); DATA02 backup-drive mirror FROZEN as a rollback snapshot via a `rsync-exclude.txt` entry. The daily Postgres backup was verified to capture all tables (whole-DB `pg_dump`, 25/25 tables incl. every pgvector table). Store task `4955d0b9` CLOSED. **Rick's instruction: leave the LanceDB source code intact for now — defer removal to a future endeavor, not today.**
- [ ] **[LUPIN] LanceDB source-code teardown (rollback-killing full teardown)** — the Phase-2 deliverable set from `src/rnd/v0.2.0/2026.07.07-lancedb-teardown-prep-scoping.md §4`: (1) remove the `lancedb` dependency (`pyproject.toml:43` + `src/cosa/requirements.txt:105`) + all 8 top-level `import lancedb`; (2) strip both dispatch layers — Layer A `vector_store_backend.py` + `vector store backend` INI flag (the live rollback switch), Layer B `solution_manager_factory.py` `ManagerType.LANCEDB` + lancedb factory keys; (3) remove all `if not self._use_postgres` branches across the 8 memory modules + update ~12 test files; (4) rename module file `lancedb_solution_manager.py` → `solution_snapshot_manager.py` (class symbol already renamed in Phase 1); (5) retire the `engine.lancedb_table` PredictionEngine family (`DEFAULT_LANCEDB_TABLE`, decision_proxy `proxy_lancedb_table`, INI `prediction engine lancedb table` + `swe team trust proxy lancedb table`, `main.py:480`); (6) disposition the backfill utility + 6 lancedb scripts (§7 table). Large blast radius on the CBR core — 100% L/B/F gate, full test layers, DO NOT rush. **NOTE:** with the on-disk store now gone, flipping `vector store backend` back to `lancedb` would find no local data — code-level rollback is already effectively spent (DATA02 mirror + GCS + off-tree backfill tooling are the only nets), which lowers the risk of this teardown.

---

## Decisions Log

> ⚠️ **Re-seeded 2026-08-26.** This section was carried out of the live file by TODO archival and never re-created — **67 entries, newest 2026-07-07, now live only in `todo-history/2026-04-15-to-2026-06-16-todo.md`**. Every ruling between then and today went unlogged here. Look there for anything older than this heading.

- 2026-08-30 — **Post-game R1: where a fact is stated twice on one path, what discharges it?** → **RULED AND SPLIT (Mr Radio 🦉).** *Where two sites agree, no return-value test can pin either — so drop the second statement, or keep it and defend it by annotation and review, never by the harness. The flag is discharged by SHOWING each site pinned, never by arguing the path-level test is good enough.* **(a) ADOPTED for the crew now**: a masked line at a fail-closed boundary is KEPT, annotated, and never deleted to quiet a harness. **(b) ESCALATED to Rick** for fleet doctrine — *"a rule about how everyone writes and reviews is not mine to install."* 🔴 **The wording is Tiberius 👑's, not the author's, and it survived because he refuted his own first fix**: "pin each site directly" failed his own reproduction — measured at `a35ce8ef`, mutating the outer site leaves **127 passing**, including the unit test written against that exact function, because it resolves through the inner site. Landed as an annotation in the file it came from: `03b90812`. Derivation `src/rnd/v0.2.1/2026.08.30-never-let-an-instrument-certify-itself.md` §5 (`1d6857fe`).
- 2026-08-30 — **What is the organizing frame for the day's recurring defect?** → **NEVER LET AN INSTRUMENT CERTIFY ITSELF** (frame: Maya 🌻; adopted by Mr Radio 🦉). Beats *"an instrument that cannot tell a good state from a bad one"* because it **names the remedy rather than the symptom**: in every instance the fix is *a second reading that does not come from the thing under test*. **Eleven instances in six hours**, count went 5 → 6 → 9 → 10 → 11, each step because someone looked again with a different instrument. ⚠️ **One near-instance deliberately EXCLUDED** — the verifier whose failure sentence named the wrong mode certified nothing; forcing it in would be the move the principle exists to catch. Doc: `src/rnd/v0.2.1/2026.08.30-crew-day-post-game.md` §3.1.
- 2026-08-30 — **What discharges that principle in code?** → **GRADUATE the two-independent-readings pattern** (Maya 🌻, forced by Tiberius 👑 reviewing `177c3542`; in the tree at `aab06b9c`). Read the live record DIRECTLY · cross-check the helper against it · **assert the record is NON-EMPTY**. 🔴 **The third move is load-bearing and is the one people skip**: moves 1–2 build a control, and **on an empty record two readings agree perfectly**, so a cross-check without it is itself an instrument that cannot fail — the control you built to escape the rule walks straight back into it. Generalised: **a comparison is not a measurement until you know both sides are non-empty.** Fourth move for cross-reader writes (`heartbeat_hold_io.py:472`): read back through the reader the CONSUMER uses, and roll back on failure. ⚠️ **BOUNDARY, load-bearing not decorative**: applies ONLY where an independent second reading exists — otherwise the rule is satisfied by MANUFACTURING one, and **a fake second reading is worse than none because it also reports success.**
- 2026-08-30 — **Where does a post-game's full text live, given the corpus is local-only?** → **TRACKED HOME IN `src/rnd/`; the corpus keeps its index entry and a POINTER** (Mr Radio 🦉, 16:48, superseding his own 15:24 ruling — taken before either of us had measured). Why: `io/post-games/` is gitignored at `.gitignore:104` **and** returns BLOCKED from the doc viewer's own whitelist gate, so a retro filed there is readable by nobody but the person at this machine. **Rick's 2026-06-30 local-only ruling is NOT overturned** — only the readable text moved. A second full copy was refused deliberately: two copies of one document is the `masked-invariant` shape in prose. ⚠️ **`post-game.md` §5.6 asserts the corpus "stays doc-viewable via the `io/post-games/` prefix in `.docview.yml`". There is no such prefix** — a doctrine doc claiming an untested capability, which is why the retro was invisible for an afternoon.
- 2026-08-30 — **Memento slots: is `slot=root` a misfiling?** → **NO — two doors, two slots** (Chloé 🗼's finding, on `memento_slot.py` `320733a1`). A **reap** reads `io` (a manager reads the seats it SPAWNED); a **self-respin** reads `root` (a seat clears its OWN pane). The defect was never a slot nobody reads — it is that **nothing checked the slot matched the door**; `self_respin_core` had no concept of a slot at all, so doctrine named a location and the code checked none. 🔴 **This retracts an earlier finding of mine that reached this row and a manager**: I read a 2-2 split in `slot=` as the finding without asking what `root` was FOR. Both "misses" had also self-repaired within the hour (15:13:53, 15:40:12) before I published. Corrections on row `8068c65e`, events 10269/10270. Workflow fix landed by Chloé at `5f28ada` (planning-is-prompting).

- 2026-08-26 — **Does María's approval discharge Rick's gate on the excision plan?** → **YES — GO, incorporating her four fixes.** Rick's words: *"Maria has approval discharges the gate I want you to incorporate the changes and then Implement the plan."* Executed in the ratified order, fixes first: `71d5efaa` (§3a stdlib out of the denominator) → `d466a9b9` (§3b `src/lib` deleted) → `1dd574d5` (§6.1 routing denominator frozen + fatal) → `22ad69b3` (Step 2 relocations) → `75ad1bd8` (Steps 3–4, the excision + the pinned worktree) → `e9ade94f` (execution record). 🔴 **The finding to carry forward: the plan's blast radius was short by two.** It named ONE edge from v2 into the delete list; there were THREE — one module-level (v2 would have died at *import*, not degraded) and one inside a *keeper*, both invisible to a grep of `v2_eval.py`. **A delete list built by naming files is not the same as one built by following imports.** Now pinned by `src/tests/unit/test_v2_survives_v1_excision.py`, which blocks the deleted module names in a child process and imports v2 anyway — with its own negative control. Record: plan §7.
- 2026-08-26 — **What lands next, now the plan is approved?** → **RESUME THE PLAN'S ORDER (stdlib fix → delete `src/lib` → V1 excision) — BUT GATED ON MARÍA'S REVIEW.** Rick's words: *"I'm going to go with your recommendation to resume the plan's order but I want Maria to review this before you implement it"*, plus *"Maria is going to sanity check your plan"*. Why the order: the stdlib fix and the `src/lib` delete are cheap, unambiguous, and both change the DENOMINATOR, so doing them before more test-writing stops me producing numbers that get re-based. ⚠️ **NOTHING IN THE PLAN IS EXECUTED UNTIL MARÍA'S REVIEW LANDS** — the three denominator/structural moves are held; §3d test-writing continues under its own separate authorisation from this morning. Named hard prerequisite for the excision, held with it: `v2_eval.py` imports `make_ws_recv_events` FROM `v1_eval_arm`, so that listener must be relocated into a v2-owned module and green BEFORE any delete.
- 2026-08-26 — **Contended coverage runs: guard mechanically, warn, or leave as a written rule?** → **REFUSE the run, with an env-var escape hatch**. Why: measured today, a `--cov` tier run sharing the box read **82% / 1320 missing** where the identical tree run alone read **89% / 853** — same command, same isolated COVERAGE_FILE, same pass counts, no warning. The error is directionally hostile (coverage looks WORSE, so the reflex is to write tests for a hole that is not there), and it now has teeth: with `fail_under` rising per milestone, a floor set off a contended run lands ~7 points too low and nothing ever goes red to say so. Same shape as the misplaced heartbeat holds — the doc was already correct and half the fleet broke it anyway; the detector is what fixed it. Doc: `src/rnd/v0.2.0/2026.08.26-contended-tier-run-fabricates-a-coverage-regression.md`.
- 2026-08-26 — **`fail_under`: raise per milestone, or hold at 96 until 100?** → **RAISE PER MILESTONE**. Why: a floor that never moves is not a ramp — it is a number someone eventually notices. Raising as ground is taken is the only version where the gate does work *during* the climb rather than after it, and it locks each gain against silent slip-back. Context: the floor is 96 while the measured frame is 89, so the gate is currently red. Tiffany's line, quoted in the plan: *the ramp's teeth are this row's chase* — and a chase date is not a control. Plan §5.4.
- 2026-08-26 — **`lupin_app`: fold the :8000 tiers into the coverage frame, or scope the mandate?** → **FOLD THEM IN, and extract the pure helpers**. Why: 367 statements sit at ~28% because `main.py` is lifespan/background-loops/middleware exercised only by the integration and e2e tiers, which the baseline does not run — so it is not a test-writing debt but code the fast tiers structurally cannot reach. Scoping the mandate instead would leave those statements unreachable by construction and stop the ramp short with no way to say why. Cost accepted: the full-frame number becomes a deliberate, slower measurement. Plan §3c.
- 2026-08-26 — **`src/lib`: delete, revive, or leave?** → **DELETE**. Why: 524 statements at 0% because the package cannot be imported (`pyaudio` absent; bare `import lupin_client`), untouched since 2026-01-28, every in-tree reference commented out except a launcher invoking python3.10 in a 3.13 repo. Deleting removes the lines rather than hiding them (+0.84 pts); leaving carries a permanent zero that makes 100% unreachable by construction. Plan §3b.

## Pending Decisions

> Queue for `/plan-decide` (the **guided-decision-walkthrough** skill). One-line topics; the skill frames each live with pros/cons + a recommendation, descending priority. Detail lives in the linked design docs.

---

### 🔴 OPEN FOR RICK (2026-08-30, raised by Mr Radio 🦉, written up by Rachel 🕊️) — **a standing order that lives only in a TODO file is one re-spin from being broken**

**The decision**: where does a standing fleet-wide order live so that a re-spun seat inherits it?

**The evidence is this session, and it is a near miss rather than a theory.** Rick's no-new-tickets
moratorium was issued 10:12 EDT. Mr Radio self-respun at 16:28 and **his own memento did not carry
it** — he learned it back from the post-game an hour later. His words: *"I have created no rows this
session, only amended two that already existed, so I am clean — but that is luck, not care."*

⇒ **A manager who does not know a moratorium exists cannot comply with it, and nothing in the write
path would have stopped him.** `task_create` has no knowledge of the order; the order lives in
prose, in a file a rehydrating seat is not obliged to read before its first write.

**Why it is worth Rick's time rather than a habit fix**: this is the fleet's own
`rule-instead-of-mechanism` shape, on the surface where it costs most. Three instances the same day
(misplaced mementos after the row was filed; checked-hash drift after the migration; zero rolling
deposits after two runs of doctrine) all share it — **the instruction was correct, present, and
changed nothing.**

**Options, with the trade named:**

| | Option | Cost | What it buys |
|---|---|---|---|
| **(a)** | **A store-side gate** — `task_create` refuses (or warns) while a moratorium flag is set | needs a flag with an owner and an off-switch; a wrong-on flag blocks legitimate work | the only option that reaches a seat which never read the order |
| **(b)** | **Carry it in the memento contract** — a standing-orders element every re-spin inherits | free; it is a doc change | depends on the writer remembering, which is the failure being fixed |
| **(c)** | **Leave it in TODO.md** — status quo | free | works for anyone who reads it; failed once today, silently |

**Recommendation: (a), with (b) as the cheap companion.** (b) alone repeats the defect one layer
over — it is still a rule that must be remembered, by the seat least able to know what it forgot.
(a) is the only one that acts at the moment of the write, where the actor is present, which is the
same argument that decided the memento-slot fork this afternoon.

⚠️ **NOT ACTIONED, AND DELIBERATELY SO**: minting a store row to track a decision about not minting
store rows would break the order it is about. **This entry is the surface the moratorium itself
prescribes — findings to the local TODO** — which is also, precisely, the weakness being reported.
It is filed in the place the item argues is not durable enough, because that is the only place
currently permitted.

**Receipts**: post-game `src/rnd/v0.2.1/2026.08.30-crew-day-post-game.md` (`d9e1193c`) · moratorium
book above · Mr Radio's DM 16:51 EDT.

---


**Messaging-coordination plane (P0)** — ✅ **ALL 7 RESOLVED 2026-06-02 via `/plan-decide`** (Rick ratified every recommendation). Source `src/rnd/v0.1.8/2026.06.02-messaging-coordination-plane-design.md` (§ Ratified Decisions). Rulings in the Decisions Log below.
- **Implementation queue — ✅ ALL 5 LEVERS COMPLETE:** A durable outbox · D pull-able inbox · B loop de-block · C express lane · E backpressure. In-process, no broker. **A ✅ · D ✅ (committed `722e624`, :8000 integration 2/2) · B ✅ · C ✅ · E ✅** — 990 unit tests green, no regressions. B/C/E committed in the wrap-up checkpoint.

**GCP test-VM operability — follow-on (opened 2026-07-22, session 2c24d27b):** source `src/rnd/v0.1.9/2026.07.22-vm-git-sync-strategy-decision.md` §6.
- [ ] **[LUPIN] Add SSH agent-forwarding to `lupin-vm.sh shell`** (`--ssh-flag="-A"`) — interactive git-as-you on the VM, all repos, zero creds at rest. Recommended next step; trivial.
- [ ] **[LUPIN] Unattended VM self-update?** — if near-term, start GitHub App setup (short-lived per-repo tokens); machine-user is the lighter interim. Skip deploy key (single-repo ceiling).
- [ ] **[LUPIN] `push-bundle` default** — keep fetch-only (current, safer) or default `--checkout` (deploy semantic)?
- [ ] **[LUPIN] Optional: fold `--actuate` into `provision-arbiter-on-vm.sh`** — one-shot arbiter bring-up (linger + enable) behind an explicit opt-in flag.
- [ ] **[LUPIN] Unify the notification API key across deployments — or ratify that they diverge** (opened 2026-07-25, session b38f09bb). The VM's `:7999` container accepts `ccfc494d` and rejects `26e3c096`, which the 07-25 entry records as the re-minted app key for the **Secret Manager / Cloud Run STT** path. Provisioning had rsync'd the dev box's key onto the VM, where it read fine and authenticated nowhere. Decide whether the VM container's registry should be re-minted to match, or whether per-deployment keys are the intended design and the provisioning copy is the only thing to fix. Detail: `src/rnd/v0.1.9/2026.07.25-vm-dm-outbound-key-two-stacked-defects.md`.
- [ ] **[LUPIN] Provisioning should not copy `src/conf/keys/` wholesale to a remote host** (opened 2026-07-25, session b38f09bb). The VM held 10 dev credentials it never needed; removed on Rick's instruction. Whatever placed them there will do it again on the next provision — fix at the source.

**Task-store identity (opened 2026-07-25, session b38f09bb):**
- [ ] **[LUPIN] Store attributes items to the wrong persona** — a row created from session `b38f09bb` (Cheech 🌿) was stamped `owner_persona: "rachel"` / `created_by: "Rachel f3d7df6c"`, where `f3d7df6c` is the **background-job id**, not the MCP session id. The store resolves identity from a different source than the session bridge, so owed work can land under the wrong owner. Row `641942c0` is the live example.

**Messaging plane — follow-on (deferred design decision):**
- [ ] **[LUPIN] Lever B comprehensive sweep** — revisit moving ALL remaining sync DB/file I/O off the event loop (beyond the surgical hot-handler fix), after measuring whether colder paths still stall under load. Deferred per Rick 2026-06-02; surgical fix lands first.
- [ ] **[LUPIN] Full-REMOVAL of the legacy commons-DM path (revisit-later)** — note-to-revisit per Rick's 2026-06-15 ruling (comment-out now, full-delete deferred). After the dm_send cutover has soaked and telemetry shows zero legacy-path hits, DELETE the commented-out machinery: `commons_send_to`, `ask_async`/`ask_sync` DM-mode, `register-question` + `CommonsQuestionWatcher` + main.py lifespan, the 2 legacy listener handlers. KEEP polling-mode + broadcasts + presence + `_handle_broadcast_received`. Prereq already handled at comment-out time: arbiter `make_dm_push_fn` migrated to `/api/notify-peer`. Design: `src/rnd/v0.1.8/2026.06.13-cosa-voice-token-reduction/03-phase4-legacy-commons-dm-retirement-proposal.md`.

## Pending

### 🔎 Sweep finding, NOT filed as a row (Rick's 2026-08-19 no-new-bugs-until-zero order)

**`matplotlib_renderer.py:235` executes model-generated Python with no sandbox.** Found during
row `60f04102`'s sweep (2026-08-19, Mr. Radio). It writes generated `code` to a temp file and runs
`python3 <temp_path>` as the server's OS user — arbitrary code execution by construction, no import
allowlist, a 30s timeout the only control.

- **Same family as `7b9094d8`, different site.** Better in one respect: `NamedTemporaryFile` gives
  each run a unique path, so it has none of `util_code_runner`'s shared-path race.
- **Not caller-supplied directly** — the code is model-generated. But a caller who controls the
  presentation prompt influences what gets generated, so the trust boundary is the model's output,
  not the user's input.
- **Deliberately not fixed.** Rick scoped `7b9094d8` to "the race only" and explicitly excluded the
  sandbox half. Fixing the sandbox here would override that ruling at a site he had not seen.
- **Promote to a row when the board reaches zero**, or fold into `7b9094d8` if its scope is ever
  widened to the sandbox.

### 🌅 MORNING AFTER THE REBOOT — two gates left open on purpose (store row `19a417fa`)

Rick's call at session-end 2026-08-17: pick these up in the morning, after the reboot.

**1. WebSocket smoke cannot run from any agent seat.** `run-websocket-smoke-tests.sh` aborts at
pre-flight on unset `LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL` / `_PASSWORD`. Measured: the
credentials **are** in `~/.bashrc` (1 grep hit), `source ~/.bashrc` leaves them **empty**, and
`~/.profile` has 0 hits. That is the `case $- in … *) return;;` early-return at lines 5-8 documented
at the top of this file — every export below it is dead code for tool shells.
**Remedy is Rick's, already recorded**: move both exports above the guard, or into `~/.profile`.
⚠️ **The reboot alone does not fix it** — see the entry above; it needs
`docker compose up -d --force-recreate` from an *interactive* shell, and `bounce-dev-server.sh`
does not substitute.

**2. Six pre-existing unit failures, none from tonight's work.** Proven by stashing every file
touched and re-running against clean HEAD — identical list both ways.

| test | count |
|---|---|
| `test_compose_env_contract_coverage.py` | 2 |
| `test_compose_service_parity.py::test_env_key_parity` | 1 |
| `test_env_contract_citations.py` (`GH_TOKEN@docker-compose.yml:266`, `:442`) | 2 |
| `test_pytest_collection_diagnosis.py::test_shape_a_is_diagnosed_as_a_collection_error` | 1 |

Five of six are the **docker-compose env contract** — the same surface as the `JWT_SECRET_KEY` /
`.env` provisioning in `b6b012a6` and `cba7b4a6`. They look like compose changes that landed without
the contract file following. **Whoever owns that lane should confirm before anyone edits.**

**Green and needing no redo**: unit 15,639 passed · cosa 8,696 passed / 26 skipped · training 111
passed / 7 skipped. **Still unrun**: serial bridge guard, E2E UI + visual, integration (final gate).

### 🔬 FIRST LoRA RETRAIN — tomorrow evening, 2026-08-18 (store row `c4837011`)

The registry → XML → PeftTrainer seam has **never run end to end**. Until 2026-08-17 the trainer
had only ever consumed the April 2026-04-05 corpus, which predated the registry by four months.
The live corpus was regenerated tonight through the sanctioned path
(`XmlCoordinator.write_ttv_split_to_jsonl`), so tomorrow is the first run against generated data.

**Corpus now on disk** (`sample_size_per_command=1500`): 47,336 rows — 37,868 train / 4,734 test /
4,734 validate, 40 commands, worst class ratio **9.9×** (April was 56.3×).
April preserved beside it as `voice-commands-xml-{train,test,validate}.april-2026.04.05.jsonl`
(gitignored, same directory) — the swap is reversible with three `mv` commands.

**Three defects the new corpus fixes vs April:**

| # | defect | April | now |
|---|---|---|---|
| 1 | two contradicting router instructions for the same 17 commands | 16,585 rows `<agent-routing-commands>` + 7,371 rows `<browser-commands>` | one template, 0 browser-wrapper router rows |
| 2 | `agent router go to test fix expediter resume` absent entirely | 0 | 1,500 |
| 3 | starved classes | test suite 85, tfe resume 0 | 1,465 / 1,500 |

Defect 1 was fixed in *code* on 2026-08-16 (`dfc9eb47`, row `14ba1437`) and guarded by a test —
but the guard covers the generator, not the file, so the artifact carried it for two more days.

**Watch during the run:** every row's `instruction` carries the full command menu inline, so the
LoRA learns the **menu** — any registry change obliges a corpus regeneration before a retrain
(row `95924f2d`). `test suite` and `tfe resume` went from starved to full, so they are the classes
most likely to move.

**Still open — the remaining floor:** the ten "using clipboard" variants are pinned at 200 rows each
by their 200-line seed files, and they alone set the 9.9× ratio. Untouched tonight.

⚠️ **The host is powered off ~22:53–07:17 EDT.** "Tomorrow evening" must start before ~22:53 or the
job does not run late — it does not run at all until boot.

### History Archive (Session 280)

### SWE Team Proxy: Workload Generator + Shadow-Mode Capture

### SWE Team Proxy Agent (HIGH PRIORITY)

### Disambiguate Database Names (Session 343-344)

### Before Branch Merge

### TTS Focus Mode Race Condition (Sessions 346-347)

### Future Considerations

- [ ] **[LUPIN] Add 60s safety timeout to TTS focus mode** - Prevent permanent stuck state when TTS queue items fail to play. **Partially addressed** (Session 164): Added staleness check on restore + exit in moveToRegularNotifications. Still need: runtime 60s timeout for cases where notification exists but user never responds and timeout doesn't fire. **File**: `src/lupin_app/static/js/notifications.js:9374-9393`
- [ ] **Silent flag for notifications**: Consider adding a `silent` parameter to the cosa-voice notification system to suppress TTS during automated testing. Would require changes to: router request models, job classes, voice_io wrappers, and core notification functions.
---


---

## 📦 Archived

- [`todo-history/2026-04-10-to-2026-05-01-todo.md`](todo-history/2026-04-10-to-2026-05-01-todo.md) — 21 CLOSED + 10 MIXED-excerpt sections, 198 closed bullets, archived 2026-05-01 (Session 92ece47c)
- [`todo-history/2026-04-14-to-2026-05-28-todo.md`](todo-history/2026-04-14-to-2026-05-28-todo.md) — 27 CLOSED sections (2026-04-14 → 2026-05-28), archived 2026-06-18 (Session 3364493b, Tiffany 💍; task 02f1e0d5)
- [`todo-history/2026-04-15-to-2026-06-16-todo.md`](todo-history/2026-04-15-to-2026-06-16-todo.md) — 98 sections (2026-04-15 → 2026-06-16 arcs + undated legacy queues), HORIZON sweep at the 2026-06-25 boundary, archived 2026-07-11 (Session 372f9dc9, Mr. Radio 🦉; task 2a190fa2). ⚠️ Contains 359 still-open [ ] bullets swept by age, NOT by disposition — stale-pending review open.
- [`todo-history/2026-06-25-to-2026-07-31-todo.md`](todo-history/2026-06-25-to-2026-07-31-todo.md) — 21 sections (2026-06-25 → 2026-07-31), cut at the 2026-08-01 boundary, archived 2026-08-06 (Session 72343afa, Cheech 🌿). Reclaimed ~11.2k tokens. Sections carrying an open-work marker (⏳ 🅿️ PENDING BACKLOG 🔴 P0, or any open `[ ]` bullet) were KEPT in TODO.md regardless of age — this sweep archived by disposition, not by age alone.

⚠️ **TODO.md is still ~27.9k chars-over-4 after this cut, above the 25k limit.** The remaining bulk is this week's decision and finding blocks, which are too live to sweep by date. Closing it further is a disposition question, not an age question — someone has to rule which of the 08-01→08-06 blocks are settled.
