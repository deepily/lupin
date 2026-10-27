# TODO

## 🔀 BRANCH HANDOFF — Mr. Radio 🦉 (`9d720da8`), v0.2.1 → `wip-v0.2.2-2026.09.30-code-wiki-and-jev-for-reuse-planning-review`

Written 2026-09-30 for Rick's PR broadcast `0375db54`. At the time of writing, `wip-v0.2.1-2026.08.29-cjflow-v2-followup` is **0 ahead / 0 behind origin**. Do not create the new branch until Rick's merge lands and main is pulled.

**Pick up first on the new branch (P0, Rick bumped both 09-30):**
- `31344c5f`: fold today's four hand-applied lupin-host-test fixes into the VM push script's preflight checks: the `heartbeat` + `task_store` settings blocks, `~/.claude/fleet-roster.env` manager lines, the flow-ratio override file, and container `safe.directory` for every `/var/external-projects/*` mount. The last one does **not** survive a container recreate, so make it durable in the compose env.
- `08691779`: the test-server port bug; every finding is on the row. Still open there:
  - The receipt validator reports a git failure ("dubious ownership") as "commit not on any branch". File it as its own bug.
  - Cheech's unverified lead that validation-rejected creates count toward the ratio gate.
  - Rick's call on whether holding-area (`not_approved`) creates should count toward the gate at all.

**In progress, carried over:** `8c3628a4` (rebaseline 5 multiplexer visual snapshots) · `4f5301ad` (pixel comparator threshold; reverted 09-29 after a new 9-px phase6a red, repeat run owed) · `97c5bd94` (stale-MCP check in the arbiter: re-landed and verified live; the INI key is still owed).
**Blocked on Rick:** `a3c59f2d` (retiring queue doors), `80513825` (approval-settings DB move; test-DB check waits on the :8000 refresh).
**Timers from the 09-30 skeleton crew** (these clean themselves up; nothing to fold in): `stop-poke-restore-20260930` (dev and test, 17:00 EDT) and `ratio-gate-reenable-20260930` (test, 12:46 EDT).
**Not mine and uncommitted in the main tree** (left alone): the phase6b `action_required` PNG baseline (dirty since 09-22) and María's three `src/rnd/v0.2.1/` docs (kill-switch design, console-tee plan, cascade handoff).

## 📚 Decisions log 2026-10-26 evening (Cheech 🌿 `4dc30fb3`, crew Rachel and Chloé)

- **P6 kind split** (row `b5955633`): 150 near-copies, 150 work-alikes and 0 cross-language. The report states that cross-language is not measured, and the 0.85 work-alike floor is withdrawn.
- **Endpoint reuse** gets its own design (row `f48c7689`). The note is `src/rnd/v0.2.2/2026.10.26-endpoint-reuse-design-note.md`, and it is not part of Plan 3's 300 needs.
- **Work-alike source** (row `46105b99`): the pilots found 0 keys in 563 Python calls and 5 in 500 TypeScript calls. Rick decides the source after his labels, and no full draw runs before then.
- **Pilot window**: Rick lifted the 10:00 to 13:00 live-call window for tonight's two pilots only.
- **Same job** means a caller that wanted A's result is served by B, perhaps after a small change. Opposites such as open and close are not the same job, and names and language never count (guide `io/tmp/2026.10.26-same-job-labelling-guide.md`).
- **Backlog**: archive the TODO.md horizon, which is 1,234 lines and was deferred at session-end.

## 📚 Decisions log 2026-10-23 evening (Cheech 🌿 `21aa6e8a`, skeleton crew, no seats)

### Rick's rulings
- ~17:30: write the team's response to the two expert critiques of the reuse checker, checked against the code. Done: `src/rnd/v0.2.2/2026.09.30-wiki-and-jev-for-code-reuse-review/2026.10.23-reuse-detection-response-to-expert-critiques.md` (row `6a259ea2`, still held).
- Evening, by voice: answer his six follow-up points in the same document. They cover unindexed files, private methods, language filtering, the missing baseline, first-pass coverage and the judge's inputs. Done as its section 7.
- Rick will run the same cascaded review with and without the reuse index and compare the code produced. That experiment is the go/no-go test for the checker.
- ~23:20: run session end with push and backup; **pick the decisions up tomorrow morning**.

### ⏰ Pick up first, morning of 2026-10-24: nine decisions waiting on Rick
Sections 5 and 7.3 of the response document. Each has our recommendation there.
1. Retire the "write new" verdict now (recommend yes) · 2. Test set of 80 to 120 needs · 3. Two people settle disputed labels · 4. Stop rule (first expert's thresholds) · 5. Two engineer-week ceiling
6. Search only the target language by default · 7. Add private and protected methods · 8. Index tests as a separate scope · 9. The with-and-without cascaded review as the go/no-go test

Rows re-chased to 2026-10-24 10:30 EDT: `b7fc7240` (spot-check, now waits on these decisions; old blocker `a9c46718` is done), `874dff1a` (waits on gate `f21c6315`).

### Not mine, flagged by the orphan check
- `d6846ef5` (María, blocked on Rick) and `d3550878` (Mr. Radio, blocked on me, the VM nightly refresh) are past their chase dates.
- TODO.md is 1,174 lines, well past the ~200-line signal; no horizon tags. Archiving it is Rick's call.

## 📚 Decisions log 2026-10-21 day to night (Cheech 🌿 `e448d721`)

### Rick's rulings
- ~19:35: band off in the shipped verdict policy, fix later. He asked for, and read, an explainer of the band results first.
- ~18:40: write a problem statement for an outside expert. A false "write new" is the error to minimize; "not sure, read the source" does not count against the checker. The expert may scrap the design, drop Jev, or say the similarity search is at its ceiling, and compare it with Claude Code's plain grep.
- Include the shadow audit and the "more code in the embeddings" idea in it. Move it to `src/rnd/` without "-draft", with front matter naming him as requester.
- Podcast script review timeout 600 → 60 seconds. He presses Config reload himself.
- Once both expert responses are in: one synthesis document, then a podcast of it. A podcast of response 1 alone was started tonight (`pg-3ecf731e`).

### Not ruled, waiting on Rick
- Row `a9c46718`, the final call: rely on the reuse checker, or keep it advisory. I recommend advisory.
- Expert response 2: still uploading at session end.

## 📚 Decisions log 2026-10-20 evening (Mr. Radio 🦉 `e8e1c10f`)

### Rick's rulings
- ~19:15: drop the Dart claim-check row (`3740dd5b`). It tested the old "keep every claim" standard, and Dart is not in the reuse index.
- ~19:32: spawn a worker for the VM refresh (`d3550878`). ~19:35: Plan 1's ratchet-and-handover phase now, the VM podcast bug later.
- ~19:50: re-park P0 `3a2f726b` until Plans 1 and 2 finish.
- ~21:35, on Cheech's card: fix the VM compose safe.directory line, and do not override the preflight.
- ~22:41: delete the four test-written files in the repo root.

### Not ruled, waiting on Rick
- Admit bugs `419a6b2e` (test litter, P3) and `8b306654` (reuse data dir resolved to "Using", P2).

## 📚 Decisions log 2026-10-18 evening to 2026-10-19 night (Cheech 🌿 `88ab1868`)

### Rick's rulings
- 10-18 ~21:15, decision `19aea5ba`: freshen on demand. The lookup refreshes stale vectors under the build lock and answers from the fresh set.
- 10-19 ~15:15, decision `2e2324dd`: the refresh job's login comes from Secret Manager. Rick created both secrets in one command.
- 10-19 ~21:07, by voice: Cheech runs VM deploys, "not my job". This is saved as a memory.
- 10-19 ~21:42, bug `d3550878`: fix the VM refresh install properly tomorrow, with one command for any host.
- 10-19 ~22:20, by voice: every open plan row carries the plan's name ("Plan 2: …"), and status reports are written for a program manager.
- 10-19 ~22:45, by voice: push and back up at session end.

### Not ruled, waiting on Rick
- Set the "good enough" accuracy bar (`84c3f892`) before the final test (`a9c46718`) reports.
- Admit or hold the held rows: `a9c46718`, `fcbc72d3`, `b7fc7240`, `09ef7938`, `5c1413eb`, `9e2d7c1d`.
- TODO.md is 1,134 lines, well past the ~200-line horizon signal. Archive at the next session with `/plan-todo archive`.

## 📚 Decisions log 2026-10-18 evening to 2026-10-19 noon (Mr. Radio 🦉 `f29ced56`)

### Rick's rulings
- 10-19 morning, by voice: skip the legacy `notifications.js` twins (decision `999e405d`, closed).
- 10-19, broadcast `90cccaf9`: cut manager rosters by 50%. Mr. Radio went from 9 seats to 0.
- 10-19, by voice: a status turn that holds a gate must ask directly, never list it as "waiting on you".

### Not ruled, waiting on Rick
- Admit or hold the three held rows. They are `cbeb4336` (P2, docs router test red on the base), `6b74a018` (P3, partial twins) and `e674fe42` (P3, bridge JSON).
- Push the working branch; the branch head is `553ab781c` plus later commits by peers.

## 📚 Decisions log 2026-10-15 day (Cheech 🌿 `a5779b32`)

### Rick's rulings
- 12:24, gate `32b71742`: yes to unfreezing the model server for the embeddings role field. It runs image 0.1.2, built from main `4e6e9a11b`.
- 15:29 and 15:50, by voice: slim the crew and finish the work in progress (row `e02f05bc`). Then release the seats and run the session end with a push and a backup.

### Not ruled, waiting on Rick
- Row `78ec2079`: may the daily vector refresh be switched on? Two asks timed out, and a timeout is not a ruling. The switch stays off.
- Row `19aea5ba`: should lookup refuse, or skip and count, when vectors name symbols deleted after the build? My recommendation is skip and count.
- Held rows to admit: `3790cd32` (a crash in util_code_runner), `75c1524b` (the float16 setting is ignored), `cde008ce` (a flaky test fix), `25f53d5e` (the band fit). Drop `a45ccc1a`, a duplicate.

### My rulings, which Rick may overturn
- The vectors do not depend on batch size, and Sam measured cosine 1.0 for every text, so a copy before landing was allowed.
- The band fit needs a new driver and two live runs. That is new work, so it moved to row `25f53d5e` instead of the close-out.
- No folder is exempt from wiki pins; whether the three dead or experimental folders should be deleted is Rick's question.

### Backlog from this session (no row)
- Archive the TODO.md horizon with `/plan-todo archive`; the file is 5,193 lines against a signal near 200.
- Rachel's seat tree keeps one untracked draft, `2026.10.14-reuse-lookup-candidate-stage-measured-inputs.md`, with no authorization; it dies with the tree.

## 📚 DECISIONS LOG 2026-10-14 night to 2026-10-15 noon (Mr. Radio 🦉 `5890f1ba`)

- **Split seed 20261014** for the verdict-layer fit (row `8a8bca62`) (Rick, ask_yes_no, clean yes, about 09:25 EDT; row `27ae353d`). The shipped verdict threshold is now the fitted 0.3.
- **Promote the ten recommended rows** (Rick, yes, about 09:40). Of row `62777c82`, only the parallel-only test fixes were authorized; wiring a parallel lane into the gates is held as decision row `c8d4b539`.
- **Dart gate parked until next week** (Rick, ask_multiple_choice, answered, about 09:59; row `3740dd5b`, chase 2026-10-20 10:30).
- **Mine, reversible**:
  - Kill-guard wrappers: refuse any wrapper whose literal argument text names kill, pkill or killall; no shell parser; variable, alias and quote-split verbs are documented gaps.
  - The own-children exception is exactly `pgrep|ps -P $$ | xargs [-r] kill [-SIGNAL]`.
  - Installer: an explicitly set server URL that cannot be reached fails the install; only the default may report SKIPPED.
- **Unanswered, not rulings** (both timed out to their defaults): strong cut-off `4dc2c93e` and VM folder mode `867ab3a3`. Re-ask 2026-10-16 10:30.
- **Practice adopted after my regression**: land a range only after a full unit tier on identical patches (range-diff "="), not after the changed files' tests alone.

## 📚 DECISIONS LOG 2026-10-13 day (Mr. Radio 🦉 `44c062fb`, skeleton crew, no seats)

- **Finish the browser utterance id work** (Rick, voice card, "yes"; he then admitted row `281a7608`). Done and closed at `fe0a806a8`.
- **Mine, reversible**: the legacy page keeps a list of live ids and holds one ending frame per id, in place of the reviewer's "restore the previous id" fix, which two overlapping failures broke.

### Waiting on Rick

- [ ] Row `3a2f726b` (R&D cleanup, P0): the one-week park ended 2026-10-13 10:15 EDT. His condition for picking it up, the branch committed, pushed and merged, has not happened. Park again or start.
- [ ] Row `b6f7f302` (Tiffany, held): the phone side of the utterance id.
- [ ] The test container login: `docker exec -it lupin-rest-test claude /login`.
- [ ] Ten held rows on my board; the P3 ones are `a798d296`, `cc86889e`, `6afda7d8`.

### Backlog from this session (no row)

- [ ] Archive `history.md`: past the 17k warning line again with this entry; measure before quoting.
- [ ] Legacy page nits, on row `281a7608`: a stop between two waiting requests can leave a held frame unacted; an ending frame with no id forgets a running stream (the current server sends none); the multiplexer passes on an item id that is already ill-formed.

## 📚 DECISIONS LOG 2026-10-12 evening (Cheech 🌿 `db0f87c2`, skeleton crew, no seats, bounded jobs only)

- **The Phase 5 gate is lint** (Rick, card "Cheech: Phase 5 gate", a keypress, recorded on row `8fac4769` at 20:25 EDT by the store stamp): "Lint only, fix on contact". I had recommended checking each page against the code. The claim harness on whole pages (row `694849ee`) is dropped; the stale pins and the blind sample on row `4bbeeb39` no longer gate.
- **The ledger rule changes** (Rick, card on the ledger rule, a keypress, row `752cb59d`): "Yes, change the rule". A document cited only by a new R&D document no longer counts as held. I had recommended reading a sample first. The ledger moved 134 documents to history; nobody has read them.
- **No lint finding is waived because a test pins the text** (Rick, card "Cheech: Phase 5 gate, CLAUDE.md", typed, recorded on row `9827dda3` at 22:10:59 EDT). I had recommended fixing 67 of the 131 findings in `CLAUDE.md` and waiving the 64 in the merge section. His answer: "In your recommendation that we fix 67 and waive the merge section are you proposing that we let Lint findings pass because it breaks a test? Did I understand that correctly? Because that sure as fuck should not be happening anywhere The test gets updated to reflect the reality of better code actually passes its lint tests!" All 133 are fixed in `d295ec37e`, which is not landed.
- **A gate is a direct ask** (Rick, by voice, time not read off a clock): he asked what I am supposed to do when my last words are "I still need your 2 rulings". I then sent the two cards above.
- **Last call** (Rick, broadcast `67300d33`, row `effd93ec`): last call 22:35, the session-end ritual at 22:45, lights out 23:00, for Mr. Radio and me. No push and no backup were named.
- **Mine, Rick may overturn**: an R&D document not yet swept still holds what it cites. Six dated explainers and post-games stay out of the Phase 5 population (336 findings), as ruled on 10-10. The row id `2f18ad99` leaves the merge section of `CLAUDE.md`, because the linter flags a bare id even in backticks. `src/tests/data/docstring_census_v022.json` keeps its line about the old heading; it is a dated record and nothing reads it.
- **Open, not decided**: whether a decision record counts as a live citer that holds an R&D document out of history. Eleven ledger rows are held only that way.

### Backlog from this session (Cheech; new rows were refused by the ticket gate at ratio 1.32)

- Land `d295ec37e` first: rebase onto the branch head, run unit and cosa, fast-forward.
- Archive `history.md`: 17.1k tokens with tonight's entry (measured 22:33 EDT), past the 17k warning line. Deferred at closing because lights out was 23:00.
- The lupin-mobile half of both exit gates: lint over its instruction file, README and 32 commands (Phase 5), and a ledger for its R&D folder (Phase 6, row `ff6a6af6`). No mobile seat was live.
- Five findings held on row `ca204c66` because the gate refused new rows: three transcript-server defects, the commons log switch that any non-empty value turns on, and the queue caching a submit past the flow's write guard.
- `test_typescript_suite_gate.py` checks suite names by substring, so "smoke" is satisfied by "docker_smoke" (second reader's finding, not fixed).
- The worktree `cheech-records-1012b` gained a `node_modules` link at 20:48:09 EDT during a unit run; I did not make it and did not find what did.

## 📚 DECISIONS LOG 2026-10-12 evening (Mr. Radio 🦉 `14f0a33b`, skeleton crew, no seats)

- **Audio chunks stay bare** (Rick, card answered about 22:02 EDT, row `87d19d27`): "Leave chunks bare (Recommended)". A client ties audio to an utterance by the `utterance_id` on the status frame before it. Cancelling the older stream and framing each chunk are not being built.
- **The guards stay as they are** (Rick, yes/no card at about 22:12 EDT, row `2f5c2b80`): the blank-line fix stays; the "prefix stops at a newline" change is dropped. His question, "Did that really happen?", was answered by the hook logs: no logged text since 2026-06-06 has 20 or more setting-only lines in a row.
- **Both browser clients use the id, and Tiffany is told** (Rick, card comment then yes at about 22:13 EDT, row `281a7608`, held): "both browser clients along with let Tiffany know". The note is in lupin-mobile `TODO.md`; the browser change is commit `48913c4b7`, unmerged.
- **Mine, reversible**: the API docs were regenerated from the live `:7999` server (`ff1416bbf`) after checking each changed entry against `src/cosa/rest/routers/arbiter.py`. The TS/JS count table stamp was refreshed (`23e72b6aa`) because every staged TypeScript or JavaScript file was being refused; no entry moved.

### Backlog from this session (no row; new rows were gated at 20:25 EDT, ratio 1.33)

- [ ] Archive `history.md`: 17.7k tokens projected at 22:36 EDT on 2026-10-12 with this session's entry (warning line 17k, critical 19k). The archive card timed out, so the workflow's default, next session, applies.
- [x] (done 2026-10-13) Row `281a7608` is in the holding area and I could not request its admit: an admit must name a live ticket of mine to drop, and I had none.
- [x] (done 2026-10-13) After `48913c4b7` merges, the multiplexer bundle in the main tree's `src/lupin_app/static/dist/` must be rebuilt (`src/scripts/build-multiplexer.sh`) before `:7999` or `:8000` serves the change; then the TypeScript and E2E tiers on `:8000`.
- [ ] The stash, commit and config guard regexes are still quadratic on hundreds of assignment-only lines (552 ms per regex at 2,000 lines). Accepted by Rick's ruling above; recorded so nobody re-finds it as new.

## 📚 DECISIONS LOG 2026-10-04 (Mr. Radio 🦉 `93ec0919`, then `acd9cc5f` after a self re-spin at 14:52 EDT; crew Tiberius · Sam · Rio) — pilot finished, fast-check trial, Gemini comparison plan

**Rick ruled** (each by keypress or spoken order, 2026-10-04):

- **Finish the pilot so he can decide go or no-go** (voice, about 12:52 EDT; confirmed yes). The summary is done. **The verdict itself is not given**: six cards between 13:45 and 17:10 EDT timed out. The three pilot commits stay on `refs/keep/` (`7f5c619de`, `3da2dd2ec`, `ab56f9029`). Row `0066a201`.
- **"Build 3 and run 120 today"** (card, about 19:00 EDT): build the thinking-off judge, one claims list and 8 at once, and run a trial. Row `6df3455e`, closed.
- **Gemini comparison, planning only tonight; he runs it at work** (voice about 19:15, then four cards): the harness calls AGY once per prompt, with agent instructions as the fallback · accuracy scored on tonight's 130 only · data in a bundle outside git · he pushes. Row `68221701`, closed.
- **"Let's shut it down for the night, give me a push and a backup"** (voice, about 21:50 EDT).

**Not ruled, asked and timed out**: whether the AGY command door is built here (two cards). It is not built; the plan says building it is the first job at work.

**Measured tonight, and what follows from it**:

- A judge with thinking off is fast and unreliable. It missed every known real loss in single runs (pilot 0 of 2, trial 0 of 2) and caught the pilot's two in 1 of 10 repeated verdicts, against 8 of 10 with thinking on. **Keep thinking on.** The earlier rig result "both losses found" was one lucky run; both pages that said so now carry a dated correction (`818ef01c4`).
- One claims list and 8 at once held: every known loss was still extracted (4 of 4); 7.0 to 7.8 times throughput over about 1,140 calls with no failed or retried call.
- With thinking on, three judge runs, one list, 8 at once: about 42 minutes of checking for a daily train of about 354 docstrings, about 4.9 hours for the whole job. As the pilot ran it: 11 to 21 hours a train.
- The labelled set's planted removals (28 of 28 caught by the fast judge) are too blunt to show the weakness that real losses show.

**Backlog, not yet owed** (no row; raise with Rick):

- [ ] Restore the 2 real losses in tonight's trial rewrite (`541b72c40`, `refs/keep/tiberius-trial-rewrite`): the types of `branch`, `wip_committed`, `wip_sha` in `drain_then_remove`'s return description. Then ask Rick whether the 130 merge.
- [ ] Untested ways to win back judge speed: a capped thinking budget; thinking off with a mandatory quote of the new text for every "present", checked by script; one thinking-on run in place of three (missed each known loss 1 time in 5).
- [ ] The harness records calls and seconds, not tokens. A cost comparison needs token counts in the ledger.
- [ ] The pilot card's option "Go, and build the fast judge" is withdrawn; re-ask as plain go or no-go.
- [ ] Post-game for 2026-10-04 (a crew ran: Tiberius, Sam, Rio). Waived at the 14:52 re-spin as owed at session end; not written tonight.

## 📦 Archived 2026-10-26

→ archived to `todo-history/2026-08-26-to-2026-10-10-todo.md`: 15 dated sections from 2026-09-30 to 10-10 and 72 Decisions Log entries from 2026-08-26 to 10-09, moved verbatim. The 2026-10-04 section stays here (open items).

## 📦 Archived 2026-10-15

→ archived to `todo-history/2026-06-26-to-2026-09-26-todo.md`: 86 dated sections from 2026-06-26 to 09-26, moved verbatim. Open decisions stay here.

## 📌 ASSIGNMENTS — one line per defect that has an owner (live index; grep before you start work)

**WHY THIS EXISTS**: it is the missing half of the one-owner rule recorded in the moratorium book under *"THE SAME
COORDINATION FAILURE FIRED A SECOND TIME THE SAME NIGHT"*. That rule said a sweep surfacing an already-assigned
defect is the signal — and named no reader and no artifact, so the only thing that could notice was a manager
remembering to. Caught by Rachel 🕊️; ruled required by Mr Radio 🦉, 2026-08-30 ~20:22 EDT. **Naming an existing
owner is now a grep, not a memory.**

**WHO WRITES IT**: **Mr Radio 🦉, by name.** The manager confers ownership, so the manager writes the line at the moment he assigns — one line, while he is already acting.
🔴 **AND A FILE HANDED OVER IN A DM NEEDS ITS ROW MORE THAN ONE PICKED OFF A LIST, BECAUSE THE RECIPIENT HAS LESS REASON TO CHECK.** Chloé 🗼's ruling, 2026-08-31 ~00:41, and she is the seat it cost. **A VERBAL ASSIGNMENT BYPASSES THE TABLE, WHICH IS THE ONE PATH THE TABLE CANNOT COVER** — she was handed `seed_test_companions.py` directly at 00:35, had no reason to grep a list she had just been told the answer to, and Clayton 😎 was already on it. Two suites for one file, 387 lines and 312, both of which would collect and both of which would run. **The cause was placement, not either of them working badly**, and it is the same shape as the collision this table was built to stop — arriving through the one door the table has no reader on.

**WHO READS IT**: every seat, twice — before starting reported work, and whenever a sweep surfaces something. A hit means **decline and tell the manager** (never seat-to-seat). **A miss means ASK, not proceed quietly** — see the scoped caveat below. This table is not yet complete enough for silence to mean
"nobody owns it".

🔴 **FORMAT INVARIANT — EVERY NORMATIVE SENTENCE AND EVERY TABLE ROW IN THIS SECTION SITS ON ONE UNWRAPPED PHYSICAL LINE, AND A REWRAP IS A DEFECT.** Rachel 🕊️'s ruling on the form, 2026-08-30 ~20:31 EDT, and it is written here rather than left to taste because the instances were fixed once and the property was not, which is how they get re-wrapped by the next editor tidying the file.
⚠️ **The receipt**: an hour after this section shipped, `grep "A miss means ASK, not proceed quietly"` returned **0** — the one rule telling a reader what to do when the list is silent could not be found by searching for it, inside a section whose whole argument is that naming an owner should be a grep rather than a memory. The assignee's rule was broken the same way.
✅ **How to check before you commit an edit here** — `grep -c` counts matching LINES, so an unwrapped sentence returns NON-ZERO and a wrapped one returns exactly **0**; the test is therefore **"must not return 0"**, never "must return 1". ⚠️ **The first cut of this line said "must return exactly 1" and was wrong the moment it was written**, because this very line quotes the phrases it counts and so adds to their own totals — an instruction that fails on the file containing it. Check these three: `A miss means ASK, not proceed quietly` · `missing line, which is the signal` · `decline and tell the manager`
🔎 **AND THE ROW HALF IS MECHANICAL — Rachel 🕊️'s detector, pasted verbatim; it prints every physically-wrapped row in the table and stays silent when there are none.** She tested it on a scratch copy with a row deliberately hard-wrapped; I re-ran it here both ways rather than take that on report.
```bash
awk '/^\| defect \| owner/{t=1} t && NF==0{t=0} t && !/^\|.*\|$/{print FILENAME":"NR": BROKEN ROW"}' TODO.md
```

| defect | owner | assigned | state |
|---|---|---|---|
| Speech-act guard for the DM condenser | Clayton 😎 | 2026-08-30 ~19:33 | ✅ merged `4d4eb954` |
| Hold-notice dangling reference — every red that withholds the recipe carries the notice | Clayton 😎 | 2026-08-30 ~20:09 | ✅ merged `39343c24` |
| Sweep for surfaces still printing the remedy the rotation hold refuses | Maya 🌻 | 2026-08-30 | ✅ merged `2b2b0980` |
| Citations by SYMBOL go advisory (Option B) | Krishna 🦚 recommended; Mr Radio 🦉 ruled | 2026-09-19 22:41 | ✅ **ruled and implemented** `0ac74aa8`. A line number is a fact about a file at one moment, not about code. Option A repairs coordinates and buys one quiet interval until the next insertion. Matches standing doctrine — *name the content, not the coordinate*. Proof it mattered: his 43 inserted lines pushed A-0's `notifications.js:25530-25552` outside `scrollIntoViewIfNeeded` by exactly 43, with no citation edited and no behaviour changed |
| 🔴 The SYMBOL check can be defeated by prose — REMEDY UNRULED | Krishna 🦚 found it; **Maya 🌻 to rule the shape** | 2026-09-19 22:45 | 🔁 **open, no row yet** (minting refused). He replaced `reinitializeConfig` with `reinitializeConfigThatDoesNotExist` in B-5L's header and the guard **stayed green** — `init`, tokenised out of `/api/init` in the same sentence, is a real legacy method and satisfied it. With the range check advisory this is the only thing between a wrong symbol and a green guard. **Predicate I ruled** (not the spelling): a citation must name a symbol as a *delimited identifier*, never a word that happens to appear in a sentence. Backticks are one spelling — write the predicate, not the enumeration. Found by him trying to break his own change |
| Population pin "is not a control" — **WITHDRAWN, I was wrong** | Mr Radio 🦉 claimed; Maya 🌻 refuted | 2026-09-19 22:40 | ✅ **no defect.** I recorded Rio's own framing that nothing holds the literal. She measured: the set-point test computes `DECLARED_POPULATION - live` AND `live - DECLARED_POPULATION`, unconditionally, in the plain unit tier — a careless edit IS caught. **No mechanisation**, her ruling as given. Rio's reviewer-recipe at `2a05cd29` stands as a documented limit, and his reason is right: a second derivation of the same rule agrees with the first until it does not, and then neither side can arbitrate |
| Build UNROWED when minting is refused | Mr Radio 🦉 | 2026-09-19 22:38 | ✅ **ruled.** B-5/B-5L had no rows and the ratio gate refuses to mint. A row is *bookkeeping of authorised work, not the authorisation*; a gate that cannot mint is not withholding permission, it has run out of paper. Authorisation is P0 epic `645a7da5`. Substitutes for the row: anchor named in the commit message AND the header marker, one line to the manager per landing with the sha, every judgement call a row would have captured escalated rather than absorbed |
| `/api/init` unauthenticated — severity | **Rick** ruled; Mr Radio 🦉 recommended P1 | 2026-09-19 22:45 | ✅ **P5, Rick's keypress** (`default_used=false`), filed `f9e71d8e`. `system.py:275`, bare GET, hot-swaps config block AND DB connection per its own docstring. Recorded as his call — **do not silently re-rate upward**. Unmeasured and named rather than bridged: who can actually reach `:7999`. Also unchecked: middleware, router-level deps, proxy rules — an unauthenticated route *definition* is not proof of an unauthenticated *path* |
| B-5/B-5L closed by DIVERGING from legacy | Krishna 🦚 built; Mr Radio 🦉 + Maya 🌻 measured independently | 2026-09-19 22:46 | 🔁 **row was wrong, verdict pending.** He gated `reinitializeConfig` to admins and hid the button. Legacy does NOT gate it (`notifications.html:1366`, plain button, no gate) and the endpoint is open regardless — so the change is a parity *divergence* that is also cosmetic. Maya reached both findings independently of me. Asked her for **reject-and-refile**, not approval. `eadcf5ba` unreviewed, ahead=2 behind=5 |
| Rotation-hold dangling reference | Maya 🌻 | 2026-08-30 ~20:09 | ⛔ **stood down** — Clayton reached it independently; this row IS the collision that produced this table |
| planning-is-prompting cross-session doc, §1.5.1b | Maya 🌻 measured it; Mr Radio 🦉 wrote it up | 2026-08-30 | ✅ **landed** `d3b0d20` in planning-is-prompting; that file has since moved on to §1.5.1c. Seeded here as Krishna 🦚's and in flight — wrong on owner **and** on state, corrected by Mr Radio 🦉 on rehydrate. If Krishna holds a residual amendment, the assignee's rule applies to him. |
| Build this ASSIGNMENTS list | Tiberius 👑 | 2026-08-30 ~20:22 | ✅ this section |
| `src/scripts/seed_test_companions.py` → 100% | Clayton 😎 | 2026-08-31 ~00:35 | 🔴 **COLLISION, ruled** — Clayton `c7ce493c` (00:38:00, `src/tests/unit/scripts/`) STANDS on PLACEMENT, mirroring `src/scripts/`; Chloé `2e1ae708` (00:39:49, `src/tests/unit/`) stands down and hands over any case his suite lacks. **Cause was mine: I DM-assigned it to Chloé at 00:35 and never wrote this row while Clayton was already on it.** |
| `src/scripts/reset_user_password.py` → 100% | Chloé 🗼 | 2026-08-31 ~00:20 | ✅ `61251144` / `1afb7b7c`, 14 tests, 69 stmts 16 branches, 0 missing — with the CLI block (141–172) EXCLUDED by `pyproject.toml:335` policy and untested, disclosed by her and verified by Tiberius 👑 |
| `src/scripts/probe_cc_bounded_billing.py` — cover or exempt (row `2b2f426e`) | Clayton 😎 | 2026-08-31 ~00:27 | ✅ **DELETED** `c3626795` — self-declared throwaway, no caller, answer preserved in the 05-12 R&D doc. Recovery by blob `ffc5db07`, then `ddeae7f6`, then `e2b56bf0` |
| Coverage-guard false alarm on the tiers' own flags (row `da5868df`) | Tiberius 👑 authored; Chloé 🗼 reviews | 2026-08-31 ~00:29 | 🔁 in review — branch `wt-tiberius-covblind` is TWO commits, `54bea5bf` + `0258f415`; she found the fix asserting "measurement still happened" by inferring it from a flag, he re-took the reading (249,856 bytes / 704 files) |
| Memento write/amend/adopt deadlock (row `dbca4ba8`) | maya 🌻 | 2026-08-31 ~00:29 | 🔁 in progress — she replaced my option (b) hint with the root cause: `amend` compared SESSION IDS alone, which cannot separate a re-spun seat from a foreign-persona pointer. New `persona_of_record`, reusing `HEX8_SUFFIX_RE` |
| D10 conformance sweep of the Decisions Log | Clayton 😎 | 2026-08-31 ~00:21 | 🔁 `0dee28bb` with Tiberius — he judges, Tiberius writes the remedies; deliberately two seats |
| Print real remedies under the retro's rulings | Tiberius 👑 | 2026-08-31 ~00:24 | 🔁 in progress — against Clayton's CORRECTED test: name the COMMAND, the COMPARISON, or the ARTIFACT a reader would produce |
| The one-owner rule + this list | Tiberius 👑 | 2026-08-30 ~20:19 | 🔄 in flight |
| Reviewing the one-owner rule | Rachel 🕊️ | 2026-08-30 ~20:22 | ✅ **done ~20:33** — changes requested and accepted; she also handed Tiberius a both-directions check for hard-wrapped rows, which is the grep-breaking property |
| `test_secret_scan.py` follow-on — **exclusively hers** | Maya 🌻 | 2026-08-30 ~20:27 | 🔄 in flight |
| Mutation pass over the three merged tips | Clayton 😎 | 2026-08-30 ~20:27 | 🔄 in flight |
| Reviewing Maya's follow-on | Krishna 🦚 | 2026-08-30 ~20:27 | 🔄 in flight |
| Blocked row `298af249` | Rio ⚡ | 2026-08-30 ~20:27 | 🅿️ parked — blocked |
| §1.5.1b's RANKING of distortion — marker-stripping has addition's undetectability | Krishna 🦚 | 2026-08-30 | ✅ **landed** planning-is-prompting `2391801` (branch `wt-krishna-1.5.1c`, reviewed by Rachel 🕊️, ancestor of `7479d2c`). **Missing until Tiberius 👑 caught it at 20:31** — Mr Radio 🦉 had closed the §1.5.1b row above as landed, which was the section EXISTING, a different thing from this amendment to it. |
| Coverage ratchet toward 96% — derive the gap at HEAD, take the largest single-file win | Chloé 🗼 | 2026-08-30 ~20:36 | 🔄 in flight — reviewer Rachel 🕊️. Barred from `test_secret_scan.py` (Maya's) and from greening the two deliberate rotation reds |
| Surviving mutant in `dm.py` found by his own pass | Clayton 😎 | 2026-08-30 ~20:36 | 🔄 in flight — his own work, his to fix |
| Two surviving mutants in `test_secret_scan.py` (Clayton's pass, reported not fixed) | Maya 🌻 | 2026-08-30 ~20:36 | ✅ **written into the book** — moratorium book, *THE TWO SURVIVORS I CALLED "DELIBERATE"*: both re-measured at `8278a379`, verbatim mutation + line + mutated sha + a positive control that kills. Maya's call on Survivor 2; Survivor 1 is covered by design |
| Reviewing Chloé's coverage work | Rachel 🕊️ | 2026-08-30 ~20:36 | 🔄 in flight |
| P1 `0e7c9214` — a repeat question announces "New math job" and the answer never arrives | Pocholo 📣 | 2026-08-30 ~21:42 | 🔄 **CHANGES** from **Rachel 🕊️** on `ed243b36`. Root cause: `_queue_best_snapshot` passed the requester's EMAIL but not their USER ID, so a replayed snapshot kept the original creator's stored id and the frame went to a key with no session behind it. She verified it complete not partial — one non-test caller of `get_copy`, six mutations killed on a green baseline. 🔴 **Hold is three TEXT narrowings**: his retraction claims the withdrawn causal claim lived only in a DM; it is in the commit subject, `solution_snapshot.py:686` and the test module line 7. **A retraction that does not reach the artifact is not a retraction — the docstring outlives the DM** |
| `e9b78e51` option (d) — the one-line rebind at `register_session.py:2061` | Chloé 🗼 | 2026-08-30 ~21:53 | 🔄 **DONE, awaiting a non-author verdict.** Two arms from one tree: fix ON 5 passed, fix OFF 2 failed / 3 passed, and **the two that redden are exactly the two that name the behaviour.** 🔴 **The pin fired as designed** — `test_an_on_disk_only_key_survives_the_next_session_start` was `xfail(strict=True)` precisely so landing this would XPASS into a FAILURE and drag the lander back to the file. **Reviewer Clayton 😎** |
| Coverage: `src/cosa/rest/routers/notifications.py` — largest single gap, 45.13% | Krishna 🦚 | 2026-08-30 ~21:36 | 🔄 measuring first in `wt-krishna-notifcov` off `9baa617f`; will report the real number and which parts are dark BEFORE writing a test, and pose a mutation against each test added. **Reviewer Clayton 😎** |
| Coverage: `src/scripts/probe_cc_bounded_billing.py` | Clayton 😎 | 2026-08-30 ~21:41 | 🔄 **SWAPPED** — Pocholo 📣 claimed it seconds before Clayton named it and Clayton yielded rather than contest; they then traded. **Reviewer Rachel 🕊️** |
| Coverage: `src/scripts/bounce_dev_warn.py` | Pocholo 📣 | 2026-08-30 ~21:41 | 🔄 **SWAPPED to him**, and it is a genuine zero the census method HID. 134 lines, `_ack_timing()` and `main()` over three real collaborators. Measures at HEAD to confirm the zero rather than inherit it from the `cc336880` census. **Reviewer Rachel 🕊️** |
| The hook-payload cut: hard byte cap, and our banner is bigger than the whole preview | Rio ⚡ | 2026-08-30 ~21:34 | 🔄 `2eb3650c` on `wt-rio-298af249`. **Reviewer Tiberius 👑** |
| `7bc011b9` — the hazard is a marker TRIVIALLY SATISFIED, not one unchecked | Maya 🌻 | 2026-08-30 ~21:38 | 🔄 **NOT merged; she caught that I said it was.** Clayton 😎's correction to her REASONING on `0ad6d5ae`, kept as a separate commit so his sha would not move under him. What is on the branch now carries a **correct assert with a comment that misexplains it**. **Reviewer Clayton 😎** |
| Coverage census — **DELIVERED, frame stated** | Chloé 🗼 | 2026-08-30 ~21:10 | ✅ **sha `5506e9a4`, bare `--cov` only, pyproject's 13-entry `source` list governed, frame = 703 files.** 73.14%, 20,919 passed / 3 failed / 42 skipped; largest single gap `notifications.py` at 45.13%; 46 files at zero. 🔴 **73.14% IS NOT A DROP FROM 95.14%** — hers is the UNIT tier alone; the branch figure is unit AND cosa appended to one data file, and cosa carries most of `src/cosa`. **That sentence leads the report or the number gets quoted without it.** Rachel 🕊️ approves |
| `report-orphaned-dm-buffers.py:39` resolves the sessions dir OUTSIDE the seam | Rio ⚡ | 2026-08-30 ~21:10 | 🔄 **the branch's only GENUINE red** — the other two failures are the deliberate rotation reds. `DEFAULT_SESSION_DIR = Path.home() / ".claude" / "sessions"`, failing `test_sessions_dir_seam.py::TestNoNewHardcodedResolution`. His by authorship: added at `250baf4b`, verified by Mr Radio 🦉. Reviewer Tiberius 👑 |
| Contention guard, shape clause 2 (`006e83f7` on `wt-tiberius-shape-clause2`) | Tiberius 👑 | 2026-08-30 ~21:08 | 🔄 mutation-proven 6/6, **reviewer Rachel 🕊️** (he authored it). ⚠️ He deliberately did NOT run the full unit tier — Chloé's census was live at pid 3537855 — which **is his own module working**; that run is the reviewer's to discharge now the census has finished |
| The INVERTED REFUSAL — the notice's first line can be flipped and the file stays green | Maya 🌻 | 2026-08-30 ~21:08 | 🔄 **ruled IN scope by Mr Radio 🦉.** Her earlier declination covered a POINTER (*"below"*): **a pointer being wrong misleads about LOCATION, a refusal being wrong misleads about PERMISSION** (Clayton 😎's sharpening of the ruling). Assert the ACT, not the wording. **Maya raised it; Clayton 😎 measured it** — not an independent sighting, a check of her claim — at `81253062` — the flip to *"It is fine to clear this red by recording a scan"* stays green at 2 failed / 73 — then **DECLINED the fix on the one-owner rule** and handed her the sha |
| Re-posed window test — pins the VALUE, not a range (`b03045e4` on `wt-clayton-windowfix`) | Clayton 😎 | 2026-08-30 ~20:51 | 🔄 **reviewer: Krishna 🦚** — Tiberius 👑 authored the test so cannot review it, and stays reviewer of the original three at `cd74c38f` |
| Survivor 2 — the dropped *"below"*, a real gap in `test_secret_scan.py` | Maya 🌻 | 2026-08-30 ~20:52 | 🔄 `wt-maya-survivor2` off `285b373d`, **reviewer Krishna 🦚**. Clayton 😎 found and reported it (`1b49fbfe`); survivor 1 is covered by `_hold` and needs nothing. 🔴 **SHE DECLINED HALF OF IT DELIBERATELY, recorded here rather than left in a commit body**: she pins the BLOCK's *"below"* and NOT the lead sentence's. Her reasoning — the block's copy is load-bearing because **the block is what sends the reader down**; the lead sentence's is decoration that reads well. ⚠️ **A deliberate scope decision that lives only in a commit message reads later as an oversight.** |
| Amendment: a code handoff needs an ABSOLUTE path or a tracked location | Mr Radio 🦉 | 2026-08-30 ~20:51 | 🔄 **reviewer: Rachel 🕊️** — neither the rule's author (me) nor its finder (Tiberius 👑) can review it |
| `.index( refusal )` asymmetry on the position assertion's LEFT operand — merged unfixed at `8278a379`, **already fixed at `aa35c075`** | Maya 🌻 | 2026-08-30 ~20:47 | ✅ fixed on `wt-maya-render-guard` before I could assign it; three arms killed by a new test pinning Krishna 🦚's five orderings as constructed strings. **Awaiting his verdict, then I merge — on HIS message, not on a report of it.** ⚠️ **This is the measured cost of my early merge**: his non-blocking note had no pre-merge moment left to land in |
| Fold the baseline-red instrument finding into CLAUDE.md's mutation section — `rc == 1` is not a kill on a branch carrying intentional reds | Clayton 😎 | 2026-08-30 ~20:40 | 🔄 in flight — his own measurement; it sharpens a rule already in the file |
| `src/tests/run-unit-tests.sh` line 10 teaches the anti-pattern — its usage example is `run-unit-tests.sh -v --cov=cosa` | Pocholo 📣 | 2026-08-30 ~20:44 | 🔄 in flight — **Rachel 🕊️'s finding, Pocholo 📣's to fix** (moved off her: she is already reviewing Chloé and ran the archaeology above). **Rachel reviews.** Verified verbatim by Mr Radio 🦉 at line 10. **Worse than the CLAUDE.md drift**: this is the line people COPY, and a scoped `--cov` silently overrides the config's `source`, so a census run this way reports a frame it never measured. Line 2's *"~915 tests"* is adjacent and likely stale — check it while you are in there |
| CLAUDE.md's *"seven-entry `source` list"* — **an AMBIGUITY, not an error** | Chloé 🗼 | 2026-08-30 ~20:41 | 🔄 in flight — **SETTLED, after three wrong theories in ten minutes.** Measured at HEAD and verified by Mr Radio 🦉: the list is **7 top-level roots + 6 `src/scripts` subdirectories = 13 entries**. *"Seven"* is **correct about roots**. ⇒ **Fix by DISAMBIGUATING — "seven top-level roots, thirteen entries, six of them subdirectories of `src/scripts`" — NOT by correcting a number.** The passage's lesson survives intact and the change is smaller than anyone claimed. 🔴 **The receipt is the process, not the fix**: Mr Radio 🦉 said it went stale; Rachel 🕊️ said no committed state ever held seven (true, and verified); Chloé 🗼 said a seven-entry state sat uncommitted in the author's tree (also true, and verified — `b12425ba` adds `src/scripts` plus six subdirs in one commit). **All three explained a discrepancy that did not exist.** Rachel found it and retracted her own retraction. **Nobody checked the COUNTING RULE before theorising about the number.** Finding is Rachel's; the fix sits in Chloé's census, so it stays hers, Rachel reviews. |
| *(unassigned — free seats)* | *(none — Pocholo 📣 staffed 20:44)* | — | 🔴 Rio ⚡ is parked on `298af249`, which is a **block**, not a free seat |
| Flip-day: the hold tests stop measuring the flag | Maya 🌻 | 2026-08-30 ~19:0x | ✅ merged `39d912ec` — reviewer Rachel 🕊️, not Tiberius (the gate was his) |
| Probe-recall caveat — docstring only, row `40f8e3cc` | Tiberius 👑 | 2026-08-30 | ✅ merged `a91f2ad1` — reviewer Chloé 🗼, after two refusals |
| Roster lookup-miss reads as a missing seat | Pocholo 📣 | 2026-08-30 | ✅ merged `eac4fb9c` |
| Completing this table from the manager's own view | Mr Radio 🦉 | 2026-08-30 ~20:27 | ✅ **done 2026-08-30 ~20:40** — the three rows above plus the §1.5.1b correction. Every sha `git merge-base --is-ancestor`-checked against tip `0f3e75b8`. |
| Four PROSE readers of the moved root-pointer name, left behind by `73caf656` | maria 🌸 | 2026-09-02 ~17:30 | 🔴 **found by Mr Radio 🦉 reviewing her fix at her request.** The code fix is complete — `slot_pointer_path` was the only executing reader. What was missed is the prose that ARGUES from the old layout: `memento_slot.py:33` justifies leg 2 by the shared pointer, and `:47`'s LAYOUT table still reads `slot=root POINTER .claude-memento.md`, **contradicting line 175 of its own file**; `reap_memento.py:49` and `:134` argue "never the root pointer" from persona-lessness, and CLAUDE.md cites that docstring as the authority on which door owns which slot. ⇒ **Her own rule one level down — a reader is any sentence the next person reasons from, not only a line that executes.** CLAUDE.md:2037/2053 and `lupin-app-splainer.ini:416` were the same staleness and are **already fixed by Mr Radio 🦉** (his file, his adjacent clause). ⚠️ Leg 2 still earns its place, for a DIFFERENT reason than it was built for: a persona outlives its sessions, so a stale same-persona pointer still names a foreign `session_id`. **Fix the premise, keep the leg.** |
| A worker spawned into the MAIN checkout is announced only as a venv script's no-op | Mr Radio 🦉 | 2026-09-02 ~17:35 | 🔴 **maria 🌸's disclosure; the diagnosis is hers, the row is mine because I offered to take it so she could stay on the prose.** She read `REFUSING: <target> is the MAIN repo, which owns the real .venv` as a venv message. **SHE WAS RIGHT — IT IS ONE**, and my first framing to her ("a location refusal worded like an environment complaint") was wrong: `link-worktree-venv.sh:91` is correctly refusing to symlink the main repo's venv to itself, and its subject is the venv. ⇒ **The defect is a MISSING signal, not a badly-worded one.** `worktree_venv.py:111` maps that exit to `status: "main_repo"` under the comment *"is the main checkout - nothing to do"* — true of PROVISIONING, and the only place the LOCATION fact ever surfaces. It prints under `if debug:` and is not even a warning, so by default a spawn into the shared tree is **silent**. ⚠️ Same family as this file's *empty result is two failures wearing one face*, mirrored: **a benign no-op and an operationally significant placement print the same thing**, and here the code's own comment endorses the benign reading. Cost tonight: two workers in the main tree, one of which wrote to it during a live tier. **Fix names the placement at spawn time; do NOT touch the script — it is correct.** |
| **H6 — the worktree tax is provisioned by nothing** (`node_modules`, root `.env` carrying `JWT_SECRET_KEY`, `src/scripts/cloud-run.env`) | 🔴 **UNASSIGNED — needs an owner** | 2026-09-03 ~23:05 | Named by Tiberius 👑 when closing `9d654899` as *"the largest thing this row leaves open"*; he correctly did not absorb it. **Three registers, no single guard**: a missing package that reads as a broken test, an import that refuses outright, nine unit failures naming an unset variable. ⚠️ **The unit tier is IMMUNE to the JWT one** — `src/cosa/tests/conftest.py` does an `os.environ.setdefault` at collection time — so 21,800 passing tests never notice and only something importing the assembled app refuses; **say that caveat wherever this is quoted**. Fix has a shape already: provision at spawn in the Python creators, same as `link-worktree-venv.sh`. 🔴 **Do NOT symlink anything under `src/conf/keys/`** — a venv is a build artifact, a key is a secret. Detail: TODO.md § HELD OUT OF THE STORE, H6. **The ticket-ratio gate refused the row; this line IS the assignment surface until it opens.** |
| Row `5f982bbd` — line 3 stops short of the right edge in all three panes (P1, Rick's own report) | Pocholo 📣 implements; Rachel 🕊️ reviews | 2026-09-04 ~11:36 | 🔄 in flight — un-parked when its chase expired. ⚠️ **The row's own colspan hypothesis is REFUTED**: Rachel measured at `b78c7651` that line 3 has no colspan of its own, the containing `<td>` already spans all six columns, and the stop is INSIDE the cell — a flex row of two `inline-flex` fields. Go at the flex layer. **Venue correction, mine**: the line-3 arms live in `src/tests/e2e_ui/`, a Playwright :8000 suite — my brief pinned both seats to `src/tests/unit/`, which cannot see the new arm |
| Row `dbb4c187` — click the ID cell, get the full id on the clipboard, all three panes (P2, Rick by voice) | Pocholo 📣 | 2026-09-04 ~11:40 | ⏸️ **QUEUED BEHIND `5f982bbd`, deliberately.** Same file, same emitter, same panes — a second seat in `notifications.js` in parallel is the two-suites-one-file collision this table exists to stop, so it is sequenced to one owner rather than staffed to two |
| Row `331c8852` — fleet-cap slider, the one outstanding piece of Rick's cap order (P1) | Krishna 🦚 implements; Tiberius 👑 reviews | 2026-09-04 ~11:36 | 🔄 in flight — unblocked on **Rick's ruling by ask at ~11:35**, discharging María 🌸's hold by its own stated condition. 🔴 **Branch from `9c3c7cb3` on `wt-pocholo-fleet18`, NOT the working branch** — verified by me at 11:36, still NOT an ancestor of HEAD, so three built-and-green parts live there and nowhere else. Scope is the slider ONLY; "pool to 18" is dead scope |
| The 19.5px — epic board's grid off by 1.5px from a layout-participating border (`epic-board.css:168`), conditional on the data; fix by box-shadow + a CROSS-PANE arm whose fixture carries the triggering classes | Rachel 🕊️ | 2026-09-04 ~14:31 | 🔄 in flight — she LOCATED it, mechanism named, not just measured. Lives on row `5f982bbd` (its guard); do NOT mint a new row, the ticket gate is refusing at ratio 1.14 |
| False toggle claim — `046d9f52`'s message AND `_handleTaskIdCopyClick`'s docstring both state as fact that a row click toggles disclosure; measured false, only `.task-disclose-button` does | Rachel 🕊️ | 2026-09-04 ~14:47 | 🔄 in flight — reassigned off Cheech at his re-spin; durable text deserves a seat with headroom. The commit message cannot be rewritten, so the docstring is the artifact that reaches future readers |
| Five stale text assertions in `test_task_row_state_controls.py` pinning `task-col-actions` / `colspan="5"` against `d6b3d819`'s deliberate removal | Cheech 🌿 (successor `8047f2a2`) | 2026-09-04 ~14:47 | 🔄 in flight — John `950b26f1` baselined them as PRE-EXISTING via `git show HEAD:` restore, byte-identical logs, and routed them here. ⚠️ Do NOT just make them pass: an assertion re-pointed at whatever the file now says is a tautology |
| `test_task_body_overlay_cache_bust` — `/static/css/notifications.css` token did not follow its last change — **DONE** | Cheech 🌿 (successor `8047f2a2`) → Maya 🌻 | 2026-09-04 ~14:47 → closed 2026-09-15 ~20:45 | ✅ It was a one-line bump after all, and by 09-15 the JS had drifted too: `notifications.css` `20260905a` and `notifications.js` `20260911d` both moved to `20260915a`. The guard named the culprits itself — `c4f8e39c` (css) and `5a3e57f0` (js), today's toolbar work. Red before, 4 failed / 24 passed / 15 skipped; green after, 26 passed / 16 skipped. On Cheech's skip-count warning, which was right: the counts are NOT comparable across the fix, because the two violation cases collapse into one `[NOTSET]` placeholder when the corpus empties (43 → 42 collected). I settled it by diffing the COLLECTED CASE SETS rather than the totals, and `test_the_unbumped_census_can_find_a_positive` still passes, so the empty corpus is a real zero and not a broken instrument |
| Reap resolves the io memento slot to the WORKTREE, reports a live memento as `timeout_no_memento` | Mr. Radio 🦉 | 2026-09-04 ~14:50 | ⛔ **HELD OUT OF THE STORE** — ticket gate refused at 422 (ratio 1.14, opens below 1.10, close 7 more). Not a P0 and I will not inflate one to clear a gate. Full finding below under 🔴 FINDING 2026-09-04 |
| epic-board.css `?v=` stamp not bumped with Rachel's `6cbcbdb9` — the bump MUST descend from her commit or the guard still fails | Cheech 🌿 | 2026-09-04 ~15:04 | ⏳ waiting on `6cbcbdb9` to merge. **Row text supplied by Cheech, written here by me — the mandate says the MANAGER writes the line, and I had asked him to draft it, which handed my own obligation back to him. He declined and grepped first.** The debt is MINE: Rachel did not bump it because I told her not to, to avoid a collision that then did not materialise |
| Cache-bust guard does not report its own denominator — a raw skip count from `test_task_body_overlay_cache_bust.py` is uninterpretable | Cheech 🌿 | 2026-09-04 ~15:09 | 🔄 in flight — **gate-refused at ratio 1.14, not inflated to P0.** The file has SIX parametrized functions each with its own skip conditions, so a ONE-FILE run is already a sum ACROSS FUNCTIONS. I told him to "confirm you ran one file" citing the multi-FILE trap; right in general, wrong for this file. A guard that prints how many assets it discovered can be caught being wrong; one printing only pass/fail cannot |
| Review all six held commits — Rachel's `b0fb7668` `2a3e88a0` `6cbcbdb9` and Cheech's tip `6f6e42ef` | Rachel 🕊️ (successor `0228ce36`) | 2026-09-04 ~15:06 | 🔄 in flight — **none of the six is independently reviewed and the predecessor is author-AND-reviewer of her own GCP fix.** That is the gate short by one, so I spawned rather than merge on my own say-so. Seat freed by her own reap; cap untouched |
| The 19.5px epic-board grid — **DONE** | Rachel 🕊️ (`aee594c8`) | 2026-09-04 ~14:31 | ✅ `6cbcbdb9` — *"One 3px border on one group-header cell made every epic column narrower than its twin"*, +37 CSS and a **110-line guard**. ⚠️ **She built the cross-pane guard I told her to SKIP and she was right to** — I read 47.4% as too tight; she knew her own window better than my sensor did |
| False toggle claim in `_handleTaskIdCopyClick` — **DONE** | Rachel 🕊️ (`aee594c8`) | 2026-09-04 ~14:47 | ✅ `2a3e88a0` — and it **exceeded the brief**: I asked her to correct a false claim, she found the handler stops the click for a GOOD reason and the stated reason was simply the wrong one |
| GCP comment fix on sam's orphaned H6 branch — **DONE** | Rachel 🕊️ (`aee594c8`) | 2026-09-04 ~14:39 | ✅ `b0fb7668` — *"A comment naming the variable is a reference to it, and the scan does not read comments differently"*. 🔴 **I blocked `dde8b87a` on Rick as "orphaned, no author" SEVEN MINUTES AFTER she fixed it** — I checked whether sam was alive and concluded the work was abandoned. A missing author is not a missing fix |
| Five stale row-control assertions + cache-bust stamp — **DONE** | Cheech 🌿 (`8047f2a2`) | 2026-09-04 ~14:47 | ✅ `2391b602` `d5066a54` `6f6e42ef` — **zero new failures, six fixed**, and the two-tree reconciliation closes exactly: 8−6=2, 2+10=12, all ten worktree artifacts named and both missing inputs verified absent-here/present-in-main |

🔴 **THE ASSIGNEE'S RULE — AND IT HAS NO CAVEAT.** If you HOLD an assignment and find no line for it here, you have found a **missing line, which is the signal**, and the fix is to tell Mr Radio 🦉 so he writes it. You know your own assignment; incompleteness of this table is never a reason to leave your own row unwritten. **Work that turns up with no entry here was either never assigned or assigned without being recorded, and both are worth
stopping for.** (Rachel 🕊️,
second review: the caveat below was unscoped, which let the one person who cannot honestly appeal to it do exactly
that.)

⚠️ **THE CAVEAT, AND IT IS SCOPED TO ONE READER ONLY — the seat asking "does somebody ELSE already own this?"**
For that query, and that query alone, a miss is weak evidence rather than a clear road. **NARROWED 2026-08-30
~20:27**: the rows below the seed are Mr Radio 🦉's own dictation of the live set, given as he re-spun, so this is
no longer one seat's DM record — but it is still a snapshot he owned rather than a read of any system, and he
named completing it as the first act after his re-spin. ✅ **RESOLVED 2026-08-30 ~20:40 by Mr Radio 🦉 on rehydrate**: the one item
Tiberius 👑 could not verify — §1.5.1b, seeded as Krishna 🦚's and in flight — is **landed** at
planning-is-prompting `d3b0d20`, and that file has since moved on to §1.5.1c. The seed had it wrong on owner and on
state; the row now says so. Three merges from before the seed were added at the same time, each sha
`git merge-base --is-ancestor`-checked against tip `0f3e75b8`. **The table is now the manager's full live set, not
one seat's DM record** — still a snapshot of what he holds rather than a read of any system, so the caveat stands. The caveat does NOT reach the
assignee's rule above, and it is not a licence to skip the check — a miss means *ask*, not *proceed quietly*. Verify anything here that a decision rests on — the merge shas are
`git merge-base --is-ancestor`-checkable and were checked; the assignment times are from DM timestamps.

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


## 🅿️ PARKED 2026-08-02 (María 🌸 + Mr. Radio 🦉) — the mirroring test: is odd phrasing TRANSMITTED between seats, or does each seat drift alone?

**⛔ NOT BEFORE THURSDAY'S DEMO — Rick, 2026-08-02: actionable bug fixes only.** Nothing here is a bug and nothing blocks the demo. Parked deliberately so it is not lost, not because it is next.

**The claim under test.** Drift says each seat degrades on its own. **Mirroring** says each seat learns the register from the last one — which is what would explain a house style that is consistent *across* seats rather than personal to each, and how DMs creep past 1000 words.

**María's test** (she proposes ~1 hour; the corpus is already on disk, nothing to build): pull the coined terms from one week of DMs, count how many appear in more than one seat, and check whether B's first use postdates A's. Shared **and** sequential ⇒ mirroring. Personal **and** simultaneous ⇒ the word dies.

**🔴 ONE CONTROL IS REQUIRED FIRST, or the test cannot fail.** *Shared-and-sequential* is also exactly what you get when both seats read the same source. Our own `CLAUDE.md` coins **WaHH · MoPEP · NoJP · TLH · NoDrama · 3LoL · NoMC C2C · NoAA** — every one appears in multiple seats' DMs, and every one is sequential by construction, because somebody had to type it first. **The test as written scores all of them as mirroring when they are plain instruction-following.**

**The fix is cheap**: exclude any term that appears in a committed instruction file, doc, or broadcast **before** its first DM use. What survives that filter is genuinely transmitted seat to seat — which is the claim. Without it, every result confirms the hypothesis and the run proves nothing.

**Status of the exchange**: María accepted the walkthrough offer and quoted the coherency-drift line into the KISS explainer (Act 13). My reply naming the control is **drafted but UNSENT** — cosa-voice lost its tool bindings in session `1bf47c18` and there is no CLI for `dm_send`. Draft + the walkthrough DM are held in that session's scratchpad; whoever has a live binding can send them, or they go out after a re-spin.

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

## Decisions Log

> ⚠️ **Re-seeded 2026-08-26.** This section was carried out of the live file by TODO archival and never re-created — **67 entries, newest 2026-07-07, now live only in `todo-history/2026-04-15-to-2026-06-16-todo.md`**. Every ruling between then and today went unlogged here. Look there for anything older than this heading.

- 2026-10-15 — **Push the working branch, which holds the whole fleet's commits (row `b1a56152`)?** → **Push the whole branch** (Rick, about 12:20 EDT, card). Pushed `d300a0c33..958bca47e`.
- 2026-10-15 — **How is the strong cut-off set (row `4dc2c93e`)?** → **A precision rule, with the confidence bar near 0.7** (Rick, about 12:22 EDT, card). Refit row `25e5e51a`.
- 2026-10-15 — **The twins?** → **Refactor them under a P1** (Rick, about 12:22 EDT, card). His words: "Create a P1, pick it for me". Row `83fd572c` is mine.
- 2026-10-15 — **Parallel unit lane (row `c8d4b539`)?** → **Measure, then wire** (Rick, about 12:25 EDT, card). The coverage gate and the bridge guard get measured first.
- 2026-10-15 — **VM sessions folder mode (row `867ab3a3`)?** → **Start the VM and fix it now** (Rick, about 12:26 EDT, card). The mode was already 2770, so no change was made.

→ entries dated 2026-08-26 to 2026-10-09 archived to `todo-history/2026-08-26-to-2026-10-10-todo.md`.

## Pending Decisions

> Queue for `/plan-decide` (the **guided-decision-walkthrough** skill). One-line topics; the skill frames each live with pros/cons + a recommendation, descending priority. Detail lives in the linked design docs.

---

- **Borrowed-identity refusal on ten tools (row `0c21fc5d`, `not_approved`)**: the guard marks ten tools RULING OWED (`set_session_topic`, `dm_list`, `enable_speakerphone`, `disable_speakerphone`, `request_persona`, `spawn_sessions`, `commons_post`, `commons_ask_async`, `commons_ask_sync`, `dm_respond`; counted at `eca5c09a0`). The row itself names three that write under a resolved session id and persona with no `_refuse_borrowed_identity` call: `dm_respond`, `commons_post`, `set_session_topic`. John called `set_session_topic` under a borrowed-identity setting against a throwaway bridge file at about 15:35, and the tool wrote it with no refusal. Wanted from Rick: wire the refusal per tool, or write an exemption with a reason.
- **Env keys run (row `80513825`)**: Rick runs the one command himself after a quiet window, adds an allow rule for the script, or holds.

### 🔴 OPEN FOR RICK — holding-area triage: sacrifice 12, promote 6 (2026-09-27, consensus María 🌸 + Mr. Radio 🦉)

The rule: features and bugs are promoted first, and tooling, test, stale and duplicate rows are sacrificed. All 18 ids were checked present in `not_approved` at 2026-09-27 ~16:15 EDT (lupin 49 rows, lupin-mobile 4).

**✅ FILED 2026-09-27 16:07 EDT — six sword-of-Damocles admit requests, all `request_state: pending` on your board.** Approving one admits the promote row and drops its paired ticket in the same step.

| promote | pays with |
|---|---|
| `aa13fdd7` mux TTS when off | `47b99296` duplicate cron row |
| `b6526c47` decision-proxy batch | `991d6a3a` cron guard day |
| `f9e71d8e` `/api/init` no auth | `ea690e92` coverage backfill |
| `f27a61f4` mobile stop-list | `80dfb7db` stale tester baseline |
| `4e936916` mobile Submit clipped | `3369be06` stale crew review |
| `c59457f0` mobile focus drawer | `97ef4b64` c8 pragma wording |

**🗑️ YOURS TO DELETE BY HAND (not in any request):** `e814d74a` · `b504f50c` · `5eeb0fbe` · `b3785c88` · `18ec288d` · `7c4cfd4d`

**PROMOTE 6**

| row | project | what |
|---|---|---|
| `aa13fdd7` | lupin | Multiplexer must never play TTS when TTS is off — verify, then fix |
| `b6526c47` | lupin | Decision-proxy acknowledge: any credentialed caller can retire another user's batch |
| `f9e71d8e` | lupin | `/api/init` has no auth and hot-swaps config + DB connection on a bare GET |
| `f27a61f4` | lupin-mobile | Stop-list: visible delete button and tap-to-edit |
| `4e936916` | lupin-mobile | Focus-mode multiple-choice ask clips its own Submit at phone width |
| `c59457f0` | lupin-mobile | Focus drawer: hide Queue/Trust/Inbox, list Home surfaces, rename "Legacy" |

**SACRIFICE 12**

| row | why |
|---|---|
| `47b99296` | duplicate of `991d6a3a` |
| `991d6a3a` | cron guard ignores the day — tooling |
| `ea690e92` | coverage backfill for one script — tooling |
| `80dfb7db` | tester baseline at an old sha — stale |
| `3369be06` | a past crew's review of a 6-row queue — stale |
| `97ef4b64` | c8 pragma reason wording — tooling |
| `e814d74a` | two stale comments |
| `b504f50c` | two stale comments |
| `5eeb0fbe` | compose bind wrong-host guard — tooling |
| `b3785c88` | test-host settings.json missing task_store block — tooling |
| `18ec288d` | orphan-branch tick not installed — tooling |
| `7c4cfd4d` | Vertex region scrub; the same red is also carried by `542b2fc2` |

### ✅ CLOSED — stop-poke silence (2026-09-27, Mr. Radio 🦉 `eafd1241`, broadcast d2d092f5)

**Superseded by broadcast cec4dc67 (Rick, ~16:20 EDT): "enable the heartbeat stop poke".** `heartbeat.poke_output_enabled` is back to `true`; re-read and parsed at the time of the change. The earlier record is kept below.

Your order was "disable the heartbeat stop poke". I set `~/.claude/settings.json` → `heartbeat.poke_disabled_message` to `""`, which is the code's full-silence path; the 2026-09-26 mute text was still delivered as a poke (the stop is blocked and the text is typed into the seat). **I have not confirmed it loads**: the loader check was denied as "Logging/Audit Tampering" (silence also drops your alert card), then a read-only search was denied as "Self-Modification". The direct ask timed out at 600s. A store row was refused by the fleet ticket gate (41 created vs 31 closed, ratio 1.32), so it is recorded here instead. **Pick one**: keep it (recommended; add a permission rule so I can verify it) · revert to the old message · `heartbeat.enabled = false`. My §4 (HTML clients) of `src/rnd/v0.2.1/2026.09.27-console-tee-live-stream-plan.md` waits on this.

### 🔴 OPEN FOR RICK — five gates carried out of session d1e0fd28 / 0dc1ec5c (2026-09-17 evening, Mr. Radio 🦉)

⚠️ **READ THIS FIRST — the last ask on these came back `answered=true` carrying "This is a test, as requested."** That is a real keypress (`default_used=false`) with a non-answer body, and it answers none of the four questions it was attached to. **It is NOT approval of anything**, and nothing below was actioned on it. Recorded because an `answered` flag with unrelated content is the same trap as row `e5f21fff` wearing the opposite coat: there, a timeout looked like a ruling; here, a ruling-shaped receipt carries no ruling. Re-ask; do not read the flag.

1. **P0 `80f10bdd` — type ONE message from the rebuilt phone.** Four asks tonight, four timeouts. Both code halves shipped (server needs nothing per Rick's own no-guard ruling; phone moved to `POST /api/notify` in `cfb8285`). Close condition: a `:7999` log line showing `POST /api/notify` and a row with `type=user_initiated_message`, `direction=human_to_ai`, carrying his typed text. **Ten seconds of his thumb is the only thing left in the only open P0.**
2. **`1e25955c` — mint and admit A-2 #3a–3e + #9.** SEVEN asks, seven timeouts. Blocks `dcaeb0fc` (#2d), `3dc5d3a0` (A-1c3) and A-1a's Epic Board half. Specs already exist in `src/rnd/v0.2.1/2026.09.16-parity-build-row-manifest.md`.
3. **The six snapshot calls on `f0e00f01`** — the only reds left on that row. ⚠️ The churn precondition is now SATISFIED: the timezone fix landed (`4f445965`), so a rebaseline pass would cover his six **plus** the harness pin move **plus** the ~9 clock-bearing baselines in one go. Chloé measured that item 7 adds **no** visual churn, so nothing else needs to wait.
4. **Two holding-area rows need his admit** — both invisible to every query while held: `6e2b1f7e` (the timezone rebaseline half I deliberately did not ship, P1) and `d3d4a18c` (32 unowned stylelint errors, P3). An admit costs one of my live tickets under the sword of Damocles, which is why I did not pay for the first one.
5. **Push.** The branch is **39 ahead of origin and has never been pushed**. `ts-31fe4355` (typescript + both e2e halves at the merged tip) was in flight at session end, so **no e2e receipt exists for tonight's nine merges** — my recommendation is push after it reports, not before.

**Also awaiting his word, lower stakes**: whether the four full-panel notice states and the multiplexer get the same toolbar move as row `8b1b1e79` (a scope widening María priced with the empty-panel cost); whether the clipped server warning earns a tooltip; and whether to raise the fleet cap, which refused a fourth seat at 8 running and left row `8b1b1e79` assigned rather than staffed.

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
- [`todo-history/2026-08-26-to-2026-10-10-todo.md`](todo-history/2026-08-26-to-2026-10-10-todo.md) — 15 dated sections (2026-09-30 → 2026-10-10) + 72 Decisions Log entries (2026-08-26 → 2026-10-09), cut at the 14-day window, archived 2026-10-26 (Rick's request)

⚠️ **TODO.md is still ~27.9k chars-over-4 after this cut, above the 25k limit.** The remaining bulk is this week's decision and finding blocks, which are too live to sweep by date. Closing it further is a disposition question, not an age question — someone has to rule which of the 08-01→08-06 blocks are settled.
