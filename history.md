# Lupin Project History

**Archives**: [history/README.md](history/README.md) is the index.

**Last archived**: 2026-11-04, entries 10-14 to 10-23, by Cheech.

> ⚠️ **This line records PROVENANCE, not health — do not read it as a status.** It says when the file was last archived, not how big it is now. The previous header asserted *"✅ HEALTHY at ~7.9k tokens (31% of 25k)"*; six days later the file was **21.0k — past the 19k CRITICAL threshold** — and the header still said 31%, because nothing re-derives a stamp. **On 2026-07-27 that stale figure was quoted into a commit message as a health claim in the same command that measured the real number.** Same defect as a calibration stamp standing in for its instrument.
>
> **Measure it, never quote this line**: `python3 -c "import io;n=len(io.open('history.md',encoding='utf-8').read());print(f'{n/4/1000:.1f}k tokens')"` · thresholds **17k WARNING · 19k CRITICAL · 25k limit**.

## 2026.11.04 - Session ebd974b4 (Cheech 🌿, manager; crew Rio, Rachel, Pocholo, Krishna, Sam, all reaped) | v0.2.2 merged into main and released; wip-v0.2.3 cut; wiki lint 204 to 0

- **Evening, after the first ritual**:
  - **The release.** PR #23 was squash-merged into main as `d0180365c`, and release v0.2.2 is published there with the source zip.
  - **Who ran what.** Auto mode refused the merge call, and the branch guard refused branch creation. Rick ran both scripts himself, with `BRANCH_GUARD_ALLOW=rick` for the branch.
  - **The new branch** is `wip-v0.2.3-2026.11.04-online-preference-learning`. María's parked fixes are cherry-picked onto it as `aee873d2b` and `1b21c4413`, so the old line stays out of its history. Her 165 tests pass, and so do the 1,594 census guards. Local wip-v0.2.1 and wip-v0.2.2 are deleted after content checks.
  - **The squash stranded three gate settings.** The doclint push epoch and the reuse gate's `since` were no longer ancestors. The gate's `base` named the deleted branch. Pre-push doclint skipped everything, and the reuse gate exited 3. `fb62363bc` re-points them at `d0180365c` and main. María owes its review and 3 reuse outcome lines (row e69ab353).

- **The three smoke reds are fixed and merged.** The compose-drift probe counts compose secrets as mounts (`69dcf6bb0`). Presentation and chain jobs send their asks to the right user (`131116482`). The SWE-team proxy test and the two live presentation smokes skip without a running proxy (`acefc4184`, `401135a53`).
- **Rick's voice reports, fixed**: a relative markdown link in the doc viewer opens the file it names (`f66c5b4f5`). The approve landing page reads an escaped P0 link (`dfaf35e75`). The README marks the Bayesian trust proxy as deprecated, with Rick's Coming Soon text, and its figures are re-derived (`401135a53`, `f1307a14a`, `a03a28525`).
- **Speech** says a link's label and "URL omitted", never the address (`e2780ddc3`).
- **Wiki lint went from 204 findings to 0** in three slices: lupin_mcp (Rachel, `316b036a8`), reuse_needset (Pocholo, `1c279c3e1`), and cosa plus the app (Rio, `6a7739d19`). 20 new pages, 696 in all. Krishna reviewed each slice. One duplicate line in the wiki index was fixed in `38eb5ac3e`.
- **Gates.** At `38eb5ac3e`, Rio ran 1–7 and 9–12 and all passed: unit 43,785, cosa 10,109, coverage 100.00%, docker_smoke 48, census guards 1,593. Gates 8 and 13–15 passed on :8000 at `f66c5b4f5`. Mr. Radio's live checks `ts-15a0638f` and `ts-49bf0c5f` passed.
- **Parked for wip-v0.2.3**, per Rick's broadcast `87304695`:
  - María's duplicate-check fixes, at `refs/parked/v0.2.3-maria-dupcheck-fixes`.
  - Rows 10691b4f and 77718bf0.
  - Rio's two P3 rows.
- **History archived**: entries 10-14 to 10-23 moved to `history/2026-10-14-to-23-history.md` (19.0k to 5.7k tokens).
- **Memento sweep**: 126 old mementos were trashed (80 digested from 2 to 4 Nov) and 15 kept for live seats. Lessons from them:
  - A sed by line number after an earlier edit can delete a function and still pass py_compile. After a scripted edit, run `pytest --collect-only` and read the diff (Rio).
  - A worktree added from inside a seat tree nests under it. Give an absolute path under the main repo's `.claude/worktrees/` (Krishna).
  - The decision proxy's trust gate runs only the `count` model. Beta, BLR, Thompson, conformal and ICRL are reached only from tests (Pocholo, measured 4 Nov 01:51 UTC, read-only).
- **Owed**:
  - María's review of `fb62363bc` and her outcome lines (row e69ab353, held for Rick).
  - Mr. Radio's test VM deploy at `d0180365c` (row a7177417).
  - The parked v0.2.3 rows.

## 2026.11.03 - Session d5ed7a66 (Cheech 🌿, manager; crew Sam) | What's new for v0.2.2 rewritten, the PR's merge gates run at d8747550c, three smoke rows filed

- **What's new.** `WHATS-NEW.md` now holds only v0.2.2, rewritten for the strategic picture (about 690 words, `210e13d00`). The older sections moved into `VERSION-HISTORY.md`, reworded to pass doclint (`09b8de142`). The README's what's-new paragraph names v0.2.2 (`d87173ae1`).
- **Merges this evening** (Mr. Radio's crew): the e2e tooltip race fix (`dd2f102bb`), the v2_ask hang-guard fix (`189018592`) and the decision-proxy explainer (`d8747550c`, the pushed head).
- **Gates at d8747550c**: typecheck 3/3, stylelint 42/42, doclint 1,026/1,026 and reuse all pass. Unit and cosa pass (Sam). Coverage exit 2: it needs the :8000 server's coverage of `main.py`, from one run with `LUPIN_SERVER_COVERAGE=1`.
- **Smoke at 210e13d00**: 5 failed, 559 passed.
  - The phase6b gate passes when run alone.
  - The two compose-drift reds are a probe bug (row 21b96c4f, Rio). The secret mounts and `GH_TOKEN` are present.
  - The research-to-presentation test sends its asks to Rick's account, then loses the job (row 61c7123f, Chloé).
  - The SWE team proxy test gets no answer to its notification (row 72d25810, Chloé).
  - All three rows are held for Rick.
- **PR body draft** (strategic style, gate table empty): `/tmp/claude-1001/-mnt-DATA01-include-www-deepily-ai-projects-lupin/daeedcae-ec34-4635-b1f9-09eb30025393/scratchpad/pr-body-v0.2.2-draft.md`, copied to `io/mementos/cheech-pr-body-v0.2.2-draft.md`.
- **Owed next session**: the :8000 coverage run with e2e_a and integration in the same pass, the three smoke rows, then the PR on Rick's word.

## 2026.11.03 - Session b7d7515e (Mr. Radio 🦉, manager; crew Clayton, Rio, Krishna, Pocholo, Rachel, Sam, Maya, Chloé) | 1.1.7 rolled out; approve links gained a status filter, a P0 promote and a gc-proof test; the decision-proxy explainer; the PR's flake fixes merged

### Checkpoint | 2026.11.03 23:35 | 📷 for Rick's end-of-session ritual

- **1.1.7 rollout (row 3e906d57, done)**: claude-agent-sdk 0.2.177 merged as 1113d2e06. Smoke ts-96471716 was green with 496 passed. Clayton ran the runbook through to Cloud Run at 0 and the VM stopped.
- **No GPU in unit tests**: Rick ruled that no unit test may need a free GPU. The peft quantize tests now mock CUDA (row 14cd7040, merged 8ecbc6e6b).
- **Merged today**:
  - Duplicate check table on the weekly fleet page: f32f645b, 4f6612e6e.
  - Duplicate check verdict lines: 63c83b3c, 3fcca7a2f, follow-up acd44f007.
  - Keep place toggle styling: c278c339, 0328f99e6.
  - Task list status filter: 8eb71f8e, 49184cc09, baselines f25a14c1a.
  - One-click P0 promote link: 54d62c0e, fa1abf79b.
  - Approve-page test: 5007e43e, 46a25f848.
  - Approve-link GC flake: 93ecdd14, ac1f8c86b.
  - Nine PR-gate unit reds: 2ae9a5f4, 3a2ffcbc6.
- **For Cheech's v0.2.2 PR**: the e2e tooltip race fix (496cfcff) merged as dd2f102bb. The v2_ask replay now waits on the 180 s hang guard, per Rick (3b78303b, 189018592). Before the fix, the solo :8000 run at 210e13d00 failed 1 of 2.
- **Decision-proxy explainer (row 55e451bf, done)**: Pocholo wrote 756 lines, merged as d8747550c. It lives in `src/rnd/v0.2.2/2026.11.03-online-preference-learning/`, the folder Rick named. Its section 8 lists 18 defects, gathered in held row 10691b4f.
- **The presentation job Rick saw**: a $0 dry run on the test account, from `test_presentation_dry_run_smoke.py` in Sam's smoke tier.
- **Owed next session**:
  - Run the 496cfcff and 3b78303b files on :8000 after Cheech's coverage run.
  - e8b9b428, speech says "URL omitted": Krishna approved 713daa6c1; unit, census and merge remain.
  - 526bfd86: reproduce on the legacy page.
  - 21b96c4f, compose drift probe: Rio's draft is 16e46365e on a hold tag. A fixture briefly held the .env postgres password; it was redacted before any commit.
  - Cheech's held smoke rows 61c7123f and 72d25810, for Chloé.
  - The crew post-game, still owed.

## 2026.11.02 - Session ade365b2 (Mr. Radio 🦉, manager; crew Clayton, Rio, Maya, all reaped) | One 1.1.6 image on :7999, :8000 and the test VM; Keep place fixed in both clients; the SDK bump reviewed

### Checkpoint | 2026.11.02 22:45 | 📷 for Rick's 22:45 ritual

- **Image 1.1.6 (row eded549d, done)**: a full Dockerfile rebuild, `lupin:1.1.6-candidate`, carrying both the Google libraries and python-pptx. Both :7999 and :8000 were recreated on it while idle (commit 74ce6b5c2). It was pushed to Artifact Registry `lupin-images` (digest 99f002c5). The VM's cloud-gpu.env now names it as `LUPIN_IMAGE` (backup `.bak-2026.11.02-pre-1.1.6`). Deployed the branch: VM HEAD matched local, post-preflight 74 passed and 0 blocking. The first build stalled for two hours on a model download and was restarted.
- **:8000 Claude login (row b75c084a, done)**: Rick ran `/login`, and `check-claude-login.sh` exits 0.
- **Keep place (row 492b8ecc, done) and the toggles row (row 532225c1, merged)**: Rio built both; Maya reviewed them over four rounds. Cause: Keep place guarded only the page scroll. A legacy card moved by insertBefore, or a multiplexer card replaced by a progress-group arrival, reset its history pane to 0. Tests-only commit 28a60b89f: run ts-bc1532eb gave 7 failed and 3 passed (every pinned case 100 → 0; the controls passed). After merge d92b42d89 and a bundle rebuild, run ts-04450565 gave 10 of 10.
- **SDK bump (row 3e906d57, open, mine)**: Clayton moved claude-agent-sdk from 0.2.88 to 0.2.177, so the bundled CLI is 2.1.317, the host's version (it was 2.1.161). He also added a parity check. Maya approved 59d3c1d5a; it is held at tag `hold/3e906d57-clayton-sdk-bump`, not merged.
- **Owed next session**:
  - Read the full TypeScript and E2E run ts-68194a6f. It was still running at 22:45; it is the snapshot check that closes 532225c1.
  - For 3e906d57, first: uv-synced unit, cosa and coverage tiers, because Clayton's ran on a PYTHONPATH overlay.
  - Then: the 1.1.7 rebuild, one live bounded job, the :8000 pyramid, the merge and the deploy.
  - VM items found before the deploy: an empty CLAUDE_CODE_OAUTH_TOKEN, and a 336h flow-ratio window where the ruling is 24h.
- Mementos: `io/mementos/clayton-8ec6a36c.md`, `rio-565a1f75.md`, `maya-61e5c423.md`.

## 2026.11.02 afternoon to night - Session 7e4810a2 (Cheech 🌿, manager; crew John, Pocholo, Sam, Rachel, Chloé) | Plan 3's rollout ruled, reviewed and mostly built; the daily duplicate check's first timed pass

- **Rulings.** Rick ruled Plan 3's rollout section by card, fifteen rulings from 17:26 to 19:30, and question 3 at 21:49. The cascaded review closed at revision 8 (`095d2d2a6`). The reviewed plan merged as `0f179c8aa`.
- **Built and merged, all reviewed.** Track A, María's workflow. Track B, the outcome checker. Track C, the gate and its weekly report. Track D, the run names, the token ceiling and the install script. Track E, the daily duplicate job and its filing. Track F, the tie and both parts. The closing merges were `621639bf5`, `18b032d81`, `8b4aa8838`, `c7c456cb6`, `b1fe08aa0`, `ae3047506`, `b365b9240` and `ff3f3875f`. Census guards passed 1,579 at `ff3f3875f`.
- **Two standing rules** went into the root CLAUDE.md: the config file is always committed (`e1395a64d`), and token spend is the manager's call (`8e08fa499`).
- **The daily check's first timed pass.** The first pass failed on GPU refusals and was fixed (`9016c6a24`). The second embedded 12,834 texts in about 32 minutes from a cold start, then stopped while judging. One definition naming the reuse tools tripped the judge's leak check (row `9311c904`).
- **The unit tier needs 12 GB.** It cannot fit a seat's 8 GiB, so it gets its own 16 GB scope (row `d0b369af`).
- **Files**: history.md, TODO.md, the remediation plan, and the root CLAUDE.md.

## 2026.11.01 to 11.02 - Sessions b3670c7d and 7e4810a2 (Cheech 🌿, manager; crew John, Pocholo, Rachel, Chloé, still seated) | First-thousand trial Parts 1 and 2; the plants reached the judge without their purpose line; an explainer for program managers

- **Part 1, 1 Nov by day.** Rick ruled that a seed can be its own test item. The method change landed in seven reviewed merges, `f01a270ae` to `b6d5a5cb2`. The first control run found 5 of 17 planted rewrites.
- **Part 2, 1 Nov at night.** Expert 1 traced the miss to the plants' missing purpose lines, and the plants got lines (`81fa95da0`). The rerun put 12 of 13 plants in the 128, against 5 of 13 bare. The pass mark held with a = 1 and b = 4. The yield trace found 58 of 70. Merges `865c63cd0`, `823526117` and `83c88f6f6`.
- **2 Nov, morning.** Rick closed Part 2 and opened Part 3. Expert 2's response joined expert 1's in one review document. Part 3 was designed with the crew. The post-game is `db66a1756`.
- **The gap.** The plants reached the judge as an opaque id and a signature, with no purpose line. The judge figures on the plants are suspended. The fix is merged at `e607c9040`, with 3,831 unit tests and 1,567 census guards passing.
- **Explainer** for program managers, with four Mermaid charts: `src/rnd/v0.2.2/2026.09.30-wiki-and-jev-for-code-reuse-review/2026.11.02-reuse-search-measurement-explainer.md`. Pushed at 10:46 as `c7e8f6564`.
- **Files**: history.md, TODO.md, the plan, the explainer, the review document, the R&D index, the post-game and its index.

## 2026.11.01 - Session ade365b2 (Mr. Radio 🦉, manager; crew Tiberius, Clayton, Rio, all reaped) | Drive podcast publishing proven end to end, row d0361881 closed

### Checkpoint | 2026.11.02 00:10 | Drive proof run done; d0361881, 7826d34b closed

- **Landed on the working branch, not pushed**:
  - `bf7307966`: research skips a failed topic (row `9f726f77`), and the setting `podcast drive upload users` (row `273c731a`).
  - `64961152c`: the 📋 view link (row `c65e449a`).
  - `1eb7c6d0b`: four unit reds (row `6717ff87`).
  - e2e_a `ts-22756399`: 491 passed, 0 failed.
- **Proof**: job `rp-f4e44cc2` uploaded its mp3 (20 MB) and the source document to Rick's Drive, checked with the publisher token. The test user was added for that run only; the setting is back to `owner` and :7999 was bounced.
- **Owed by Rick**: renew the Claude login in lupin-rest-test (expired 2026-11-01 04:35 UTC). The 10-26 post-game row `320e0229` still waits in holding.
- **Files**: history.md
- **Commit**: [pending]

## 2026.10.30 - Session d4efa51c (Cheech 🌿, manager; crew Rio and Rachel, reaped) | Opus work-alikes regraded, all 222 pairs labelled, trial runs 2 and 3, a JSON handoff for the second reviewer

- **Landed and pushed** (`9508dfa42..16df2ee4c`):
  - `c86427d5a` third-rater loader, and `2dae0d3f0` unofficial Set A run.
  - `6f5cc04ca` podcast doc pins.
  - `c8b3fdc6d`: an unofficial proof run refuses a judge ledger outside proof-unofficial (Rio, row `193952e1`).
  - `16df2ee4c` six semdup wiki pages (Rachel, row `677eaa4c`).
- **Labels**: Rick regraded the 20 Opus work-alikes blind, and 15 are now same job, against 11 before. He agreed with his first answers on 12 of 20. He then labelled the 97 new flags, so all 222 are labelled, 8 of them unsure.
- **Trial runs** (`io/semdup/proof-unofficial/2.json`, `3.json`): run 3 uses all 222 labels.
  - Agreement 95.3% and found 64/74 = 86.5% pass.
  - Correct 128/171 = 74.9% fails the 0.80 bar. The 97 flags outside the built pairs were 66% real.
- **Second reviewer handoff**: `io/semdup-labelling/2026.10.25-run5/handoff/reviewer-2-labelling.json` and its instructions; import is row `894bf578`.
- **Board**: the archived reviewer branch was dropped as already landed (row `ef49e95e`). The rename to duplicate-check waits on the proof (row `78755a78`).
- **Memento sweep**: 20 from 10-30 digested, all already covered by this entry and Mr. Radio's. 141 were trashed and 13 kept for live seats.
- **Files**: history.md, TODO.md, and the labelling and run data under `io/` (not tracked).

## 2026.10.30 day to night - Session 9193d2a3 (Mr. Radio 📻, manager; crew John, Krishna, Sam, Pocholo, all reaped) | Time zone only from configuration, model server redeployed, first VM vector build

- **Landed on the working branch, not pushed.** Tip `2e131d30a`, 46 commits after `9508dfa42`.
  - Row `43286adc` (done): the time zone comes only from configuration. `cosa/config/app_timezone.py` reads it with no default, and every code fallback is removed. Web pages show the server zone or a labelled UTC time. Two census guards were added.
  - Row `d3550878` (parked to 11:15Z 10-31): the first VM vector build finished (9581 rows). The model server image is updated to `20261030-role-document`, image only. The `"purpose-lines"` literal is fixed and `candidate_build.py` is at 100% coverage.
  - Rows `5a8ab11c`, `2f4fd59e` and `5c3bf58e` are done: a librarian test pin, terraform matched to the live service, and the Testing-GCS LAN-model guard.
- **Gates at the tip**: full unit 41718 passed, 0 failed. TypeScript `ts-387b7bc9` 6360 passed. Census 1549 passed. Doclint clean.
- **Servers**: :7999 and :8001 restarted on the new code. The test VM is still at `9508dfa42`.
- **Open for Rick**: push, the VM deploy, dropping duplicate row `f1700a8d`, and deciding row `320e0229`.
- **Files**: history.md.

## 2026.10.29 evening to night - Session 2b284afe (Cheech 🌿, manager; crew Tiffany, reaped) | Rick's 125 labels in, every open decision ruled, explainer for the expert, podcast parse fix landed

- **Labels**: Rick labelled all 125 Set A pairs (70 same job, 55 not). Of the 20 Opus work-alikes, 9 were ruled not the same job.
- **Rulings** (decision walkthrough; recorded in the explainer's section 9 and on rows `f029b4b5` and `46105b99`):
  - The second reviewer labels all 125 Set A pairs blind.
  - A third rater breaks ties on the disputed pairs only.
  - No comment cleanup until the proof passes (`3ef167df`).
  - Set B keeps confirm mode.
  - Future pairs show doc comments on both sides, and reject banned names built from joined strings.
  - Set B's work-alikes are a mix: about 90 mined from TypeScript and about 60 synthetic Python, each synthetic one checked by a person. This one is flagged for the resident expert.
  - The run count for the experiment is withheld, to be fixed before the experiment runs.
- **Landed on the working branch, not pushed**: podcast parse failure handling, by Tiffany (`c2bae7056`, `008fd2030`, row `0a5db694` done). An unreadable script now saves the full reply under `io/json-recovery-failures/` and retries once. Cheech's re-run: 600 unit tests and 1,535 census guards passed. It is live on :7999 after the 03:04Z bounce, and the podcast of the explainer was restarted.
- **Docs**: `src/rnd/v0.2.2/2026.09.30-wiki-and-jev-for-code-reuse-review/2026.10.29-proof-pairs-and-needset-labelling-explainer.md` is new, with a README link. The scratch notes in `io/tmp/` are the same-job guide and the power table for the run count.
- **Open**: rows `e2121bc4` (the early, unofficial proof run) and `fc1658f2` (third-rater loader), approved and parked to 10:00 EDT 10-30. The blocked Plan 3 chain is re-chased to 11-02. Rick is still to name the second reviewer and the third rater.
- **Files**: the explainer, src/rnd/README.md, history.md.

## 2026.10.28 day to night - Session a61ed994 (Mr. Radio 🦉, manager; crew Krishna, John, Tiffany, Maya) | Test VM on Vertex Model Garden, gist fixed live, podcast cause found

- **Landed on the working branch.** Each passed review and the gates; nothing pushed. Tip `80325bcf0`.
  - Model Garden chain `be077aa77`. Rick's shadow-audit switch-on `06f6c3b77`, and its test `34756e619`.
  - 78 R&D files deleted `0bace4db6`. Lint-count ceiling `1c95a0846`, `cfbcbd9ad`. Move-probe README deleted `8b5a499da`.
  - Row `d3550878`: a command-only submit no longer waits on the gist (`bb60e8559`, `bbb9c873e`). The VM preflight readings are fixed (`e0d7621d3`, `fe2834ad0`). The VM gist uses Gemini Flash-Lite on Vertex, by Rick's ruling (`68b966e29`).
  - P0 `3ed25e12`: the container pins Vertex-served model ids (`db347f3be`). The podcast prompt example escapes its break-tag quotes, and recovery repairs them (`e580eb1f4`, `80325bcf0`).
- **VM** deployed at `34756e61` at 01:29Z. The post-deploy preflight had 0 blocking items, `claude -p` in the container answers, and the Flash-Lite gist works live.
- **Open**:
  - Podcast fix: not yet deployed or rerun.
  - The first vector build was still running at 22:20.
  - Typed asks on the VM hang on the home-LAN router LoRA. The ruling is asked of Rick on `d3550878`, re-asked at 10:32.
  - Row `281f5223` is folded into `d3550878`; Rick can drop it.
  - Cost note: the haiku slot uses claude-sonnet-5-5, because Vertex serves no haiku.
- **Files**: history.md. Code arrived by the reviewed fast-forwards above.

## 2026.10.28 day to night - Session bf84de97 (Cheech 🌿, manager; crew Rachel, Chloé, Krishna, all reaped) | Proof driver landed, check passes on run5, waiting on labels

- **Landed on the working branch.** Each passed Chloé's review and the gates. Pushed at tonight's closing time.
  - Proof driver `proof_cli.py` with 31 tests at 100% (`a44119e6c`, row `e8967ff9`). A real `--check` on run5 passes: pool 12,204, 65 planted, 60 monolith pairs, 1,146 structural pairs.
  - The label-prep repeated-name fix (`7cff5b3dd`, row `1520163f`) and the regenerated API docs for the pair-labelling routes (`fee404196`, row `ae815ee2`). The 10-24 decisions log is in `472f1339f`.
- **Rulings**: structural pairs are staged as one tree. The pilot (the remediation plan's sixth phase) waits for the proof. Rick is recruiting the second reviewer. Seats are staffed without asking.
- **Open**: gate `f029b4b5`. Rick is at 63 of 125 labels and no second reviewer file exists yet. After that comes the proof run (row `6e821290`), and then Rick names the passing record (row `35914482`).
- **Files**: history.md. Code arrived by the reviewed fast-forwards above.

## 2026.10.26 day to night - Session 4dc30fb3 (Cheech 🌿, manager; crew Rachel, Chloé) | Labelling page live, Rick at 27 of 125, P6 ruled, endpoint note

- **Landed on the working branch** (each passed Chloé's review and the merge gate; not pushed until tonight's session-end):
  - Labelling page `/app/pair-labelling` (`225ea66f4`, `6ba5a520b`), with no auto-advance, Go to pair N and a saved-answer marker (`78ddf860f`, `45d41ce9c`, bug `ff1ad13a`). Rows `ea45cf15` and `ff1ad13a` are done.
  - Proof loader `label_load.py` (`f90d4a987`), wiki pins for 23 orphans (`f954844c2`, `afcff8da7`), and the endpoint reuse note (`dbb180de7`, `ddff8842e`, row `f48c7689`).
  - Earlier today: `4c9f940a3` (row `792509e3`) and `54f6ea8a5` (census race, row `ee912ca1`).
- **Rulings**: P6 split 150/150/0 (row `b5955633`). The work-alike source is decided after Rick's labels (Python 0 in 563 calls, TypeScript 5 in 500; row `46105b99`). Pilot window lifted tonight. Rows `9e2d7c1d` closed and `0d675ad6` parked.
- **Rick's labelling**: 27 of 125 saved in `io/semdup-labelling/2026.10.25-run5/packets/labels-rick.jsonl`, about 2.5 minutes a pair. Guide: `io/tmp/2026.10.26-same-job-labelling-guide.md`.
- **Lesson**: my merge gate skipped `symindex lint` and left 23 orphans, which Mr. Radio caught. The memory `feedback_landing_gates_include_symindex_lint.md` already said to run it.
- **Files**: history.md, TODO.md. Code arrived by the reviewed fast-forwards above.

## 2026.10.26 day to night - Session c3f1bdfe (Mr. Radio 📻, manager; crew Maya, John, Clayton, Tiberius, Tiffany) | Coverage at 100%, :8000 smoke green, R&D frontmatter, two work-alike pilots

- **Landed on the working branch.** All green and reviewed, not pushed; tip `7d69b61a8`.
  - Coverage row `e1a36bb4` closed at 100.00% over 102,293 statements.
    - Maya's `main.py` lifespan extraction: `60d7841d9..7df094b07`.
    - The gate refuses when an xdist worker's data is lost: `114b7c2c0`.
    - Two xdist workers under coverage: `7889c1444`.
    - The cosa_voice_mcp SIGTERM handler moves into `__main__`: `a2190e2b1`, `6cbb5a9aa`, `2a073442b`.
  - Smoke row `4ad9c156` is green: run `ts-fbbe1e47` had 496 passed and 0 failed, against 474/7/15 before.
    - The :8000 container forwards the smoke admin login: `5e8440a33`, `c6d9d6656`, `3288b898c`, `45852fa5d`.
    - deep-research.json gains a podcast-wording entry for research_to_podcast: `4a1fbf71e`.
    - Rick confirmed the model host at 192.168.1.21 did not change.
  - R&D row `3a2f726b`: the groups 12 and 13 files gain requested_by, ratified_by and provenance. The original grants stay. Commits `6c6ded0a3`, `d8c74452a`.
  - Row `95622992`: the unread running_job stores leave `_process_job`, with an exact-hit delivery test. Commits `ffac90117`, `7d69b61a8`.
  - Row `c586af0f`: the timing-test control, `a6b092b3f`.
- **Closed without code**: `c37c3c07a` had already fixed `39c69b0b`. The 1.2M reap result came from this seat's own MCP subprocess. That process predates the fix, so it happened again at 22:32.
- **Measured** on row `46105b99`, under Rick's window lift:
  - Work-alike in Python: 0 keys in 500 calls, and 0 in 563 with earlier draws.
  - Work-alike in TypeScript: 5 keys in 500 calls.
  - 150 TypeScript keys would cost about 15,000 calls, and up to about 46,000 at the 95% edge.
  - Rick picks the work-alike source after his labels.
- **Open**:
  - `3a2f726b`: Rick ruled to delete groups 1 to 11, 78 files. The permission classifier refused the `git rm`. Prep is in `io/mementos/maya-3a2f726b-prep/`. Chase 10-27 10:30.
  - `d3550878`: Tiberius's Model Garden chain sits on `45852fa5d`, tip `22d37a7e7`, six commits.
    - Claude Code in lupin-rest-cloud-gpu calls Vertex.
    - Deploy writes LUPIN_GCP_PROJECT_ID, and the preflight reads it.
    - All four of Tiffany's tests now exist. Her re-review is owed, then the landing and the VM deploy.
    - The VM service account has cloud-platform scope and aiplatform.user.
  - `527fec6e`: the podcast button on the VM waits on Rick.
- **Files**: history.md. Code arrived by the reviewed fast-forwards above.
