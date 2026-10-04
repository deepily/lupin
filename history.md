# Lupin Project History

> **Archives**: See [history/README.md](history/README.md) for the full chronological index. Most recent: [2026-09-06 to 09-19](history/2026-09-06-to-19-history.md).
>
> **Last archived**: 2026-10-03 by Mr. Radio 🦉 (session 6d9a5ad1), on Rick's choice of option A — one cut (09-06 to 09-19), 13 entries, 54,537 chars moved verbatim; character accounting balanced (26,635 kept + 54,537 cut = 81,172 before). Cut by DATE, not position: one 09-19 entry sat at the bottom of the file below 09-06. Prior: 2026-09-16 by Mr. Radio 🦉 (session e58aaec3) — one cut (08-30 to 09-05), 9 entries, 50,584 chars moved verbatim; character accounting balanced (33,890 kept + 50,584 cut = 84,474 before). Cut by DATE, verified contiguous at the bottom. Prior: 2026-09-06 by Sam 🎙️ (session 07554529) — one cut (08-21 to 08-29), 8 entries, 39,857 chars moved verbatim; character accounting balanced (43,128 kept + 39,857 cut + 2 newlines — one separator, one file-terminating — = 82,987 before). Cut by DATE, and the positional cut was VERIFIED to coincide with it in both directions rather than assumed — this time they did. Prior: 2026-08-30 by Mr. Radio 🦉 (session 93a8751c) — one cut (08-14 to 08-20), seven entries, 25,267 chars moved verbatim; character accounting balanced (46,822 kept + 25,267 cut = 72,089 before). Cut by DATE, not position — the 08-19 entry sits at the BOTTOM of the file below 08-14, so a tail cut would have archived a newer entry than it kept. Prior: 2026-08-25 by Krishna 🦚 (one cut, 08-10 to 08-12). Prior: 2026-08-21 by Cheech 🌿 (one cut, 08-04 to 08-07).
>
> ⚠️ **This line records PROVENANCE, not health — do not read it as a status.** It says when the file was last archived, not how big it is now. The previous header asserted *"✅ HEALTHY at ~7.9k tokens (31% of 25k)"*; six days later the file was **21.0k — past the 19k CRITICAL threshold** — and the header still said 31%, because nothing re-derives a stamp. **On 2026-07-27 that stale figure was quoted into a commit message as a health claim in the same command that measured the real number.** Same defect as a calibration stamp standing in for its instrument.
>
> **Measure it, never quote this line**: `python3 -c "import io;n=len(io.open('history.md',encoding='utf-8').read());print(f'{n/4/1000:.1f}k tokens')"` · thresholds **17k WARNING · 19k CRITICAL · 25k limit**.

### 2026.10.03 - Session 6d9a5ad1 (Mr. Radio 🦉, manager; crew Chloé 🗼, Krishna 🦚 from about 16:25 EDT) | Integration 34 → 3 reds; three console-stream server defects fixed; DB login built and waiting on sudo

- **Integration on :8000, four runs**: `ts-11c25f8a` 417 passed / 34 failed · `ts-8584a00b` 445 / 6 · `ts-332ebcf6` 446 / 5 · `ts-3c700544` (head `77f5e626d`) 448 / 3. Causes and fixes are on row `d849a6d9`.
- **Landed on the working branch (not pushed)**: `5e8537ba5` ratio gate off for `[Lupin: Testing]` · seeder and task-store test fixes (`033da9aba`, `da4dd78e5`, `89989afb4`, `3795b1feb`, `f572b5c28`, `978967905`, `497059313`) · console stream server fixes, María reviewed: `f60627d28` (offset kept across a quiet poll), `91574fce7` (frames chain across unseen records, a /clear is announced, non-admin watch refused in the contract's frame), `42961911a` (a backlog page always returns one whole record) · `034955047` + `642633cf5` suite-lineage CRUD jobs skip the confirmation (`4cbd4858`) · `28aa569ff` worktree guard covers lupin-mobile's scripts (`5aedbad2`) · `2cf2be63d` notify-door tests send a Bearer JWT (`c46ba7c0`, green live in `ts-3c700544`) · `8bf4377fc` Decisions Log.
- **Built, reviewed, not on main at 19:10 EDT**: `78145754d` (task-store tests meet the pull switch; Krishna PASS) and `18b28b44e` (a recast job keeps its suite lineage, no 60 s correctness wait; Krishna PASS). The auto-mode permission check refused the cherry-pick three times, once after Rick's yes. They address the 3 remaining reds. Not run live.
- **DB login (`80513825`)**: Rick ruled "extra group on the two app services". Compose commit `e74f798d1` built and reviewed, held until `/etc/lupin/secrets/db_app_password` exists (his sudo steps, not run at 19:09).
- **Rows filed or scoped**: `8d4a5a59` (a request body can claim suite lineage; Krishna's code read) · `8796333b` scoped (one invalidation event for the task panes; Chloé). `c9252819` still waits on `gcloud auth login`.
- **Seat re-spun itself at 16:40 EDT** (session id 6d9a5ad1 → 6809e0d5, same seat).
- **Files**: history.md, TODO.md, src/docs/post-games/README.md; code via reviewed merges only.

### 2026.10.02 - Session bf81cf59 (Cheech 🌿, manager; crew Maya 🌻, Tiberius 👑, Rio) | Harness fix, Do not rule, Fable call cap and labelled-set seeder merged; pilot held for claim loss

- **Merged on the working branch (head `57a0a35e7`, pushed on Rick's broadcast `ae5e1f8c`)**: `4592dc181` harness quote-floor fix + stub manifests + Dart pair builder · `3aa15187f` Do not / Don't injection rule + Fable per-model call cap · `96ddb2ed6` cap test timeout · `394f6c9e9` Rio's seeding script (row `13878d1c`, 96 tests, Tiberius PASS after four rounds). All with Tiberius PASS.
- **Pilot rewrite held**: the claim check found claims missing in 53 of 78 docstrings; Tiberius's sample of 48 read 37 as real loss. Rick ruled history may go and reasons stay (`b3086a20`); the restored rewrite `refs/keep/maya-pilot-restore` (`7f5c619de`) waits on a judge history class (`9d40b2af`).
- **Rick ruled** (Decisions Log 2026-10-02 in TODO.md): 190 gate pairs, Fable writes only with a cap of 500, the Fable test call was covered by the plan, held rows admitted except `9641c0e8`.
- **Owed Monday**: coverage gate on a quiet box first (tonight's run refused, exit 2 from contention) · judge history class · pilot claim check · first Fable writer run · post-game for 10-01 and 10-02 (row `ca204c66`). Crew down; mementos in `io/mementos/{maya,rio,tiberius}-*.md`.
- **Files**: history.md, TODO.md; code via reviewed merges only.

### 2026.10.02 - Session 76f0cdab (Mr. Radio 🦉, manager; crew Chloé 🗼, Krishna 🦚, John 🏄🏽) | Poke toggle and worktree janitor landed; VM spawns default to Sonnet; Rick's 7 blockers ruled and worked; integration 66 → 50 reds

- **Landed on the working branch (not pushed)**: `49f987d75` poke toggle + janitor (evacuate, archive, 14-day sweep) · `b098aa6f5` VM model pin · `3a6d805ec`/`92e0185e9`/`222ba140c` eval lineage fix, 15-minute per-file cap, Krishna's integration fixes, two-click approve · `f7e8890e1` DB-login guard rail, repo side (`80513825`) · `9718cf97c` section D rebaseline (`aee3ab5b`) · `38dd62dc4` task_create description (`a8a2651d`, María reviewed) · `06dfba7e6` suite-lineage jobs skip the correctness ask (`4cbd4858`), manager-seat callers, guarded `lupin_db_test` seeder, :8000 gets its own sessions folder, holding-area label never shows a raw key (`0d6d4387`) · `6e160dcb8` edit-parity probe gets an epic key.
- **Rick's rulings at 21:00 (all 7 blockers, direct asks)**: VM config (he added the header, I did the rest) · seed fixture, test DB only · rebaseline section D · VM roster persona Cheech · separate :8000 sessions folder · skip the eval wait for suite jobs · sudo steps tomorrow 10 to 1.
- **VM (`c9252819` P0)**: `~/.lupin/config` `[local]` filled, cosa-voice re-registered with the config args; all 4 spawn roles resolve to Sonnet 5.5. Owed: one real spawn after a VM session restarts. `72781b05` closed (roster line, preflight C11 OK).
- **Integration on `06dfba7e6` (`ts-38f000d5`)**: 401 passed, 34 failed, 16 errors in 27 min (was 50/16, and hours long). Causes grouped on `d849a6d9`. The next one is the ratio gate in the test DB; the fix is one `[Lupin: Testing]` INI line, which waits on Rick's uncommitted fleet-cap edit in `lupin-app.ini`.
- **Rows closed**: `72781b05`, `0d6d4387`, `a8a2651d`, `20e26936`, `a3c59f2d`, `376dd4cb`, `3526fb95`. Workers reaped with mementos in `io/mementos/`. Sudo runbook: `io/findings-80513825-sudo-runbook.md`.
- **Files**: history.md; code via reviewed merges only.

### 2026.10.01 - Session 37cbc13d (Cheech 🌿, manager; crew Sam 🎙️, Maya 🌻, Tiberius 👑, John 🏄🏽, Chloé 🗼) | v0.2.2 judge harness, doc tools and Jev adapter merged; gate run finished; e2e slowdown diagnosed; pushed on Rick's word

- **Merged, each with Tiberius PASS (head `06503a6f1`)**: `c8b4818cc` claim harness + prose judge · `c770d3e90` between-suites reset fix (`07dde530`) · `26ff4b99f` precision/recall report (`f5482b4b`) · `0c617d906` Jev adapter · `1953cd470` Maya's doc tools + `judge_comparison.py` + hermetic harness (`46309646`) · `06503a6f1` dotted dates + MCP-tool exemption. Plan 1 Rulings R.9, R.10, B4 written.
- **Gate run (row `0fc47c13`) finished 23:10**, Maya's report: Haiku, Sonnet, Jev legs all rc=0, 150 pairs; copies in `projects-data/lupin/gate-run-2026.10.01/`. The comparison report and Tiberius's review (`e982851a`) are not done; D3 (which judge) waits on them.
- **NOT merged, pinned under `refs/keep/`**: `maya-d23063c0f` (script delta; whole-tree tier 28,481 passed, 1 failed: a 5.0 s timing cap missed by 0.07 s under load, bug `797a2dc3`) · `chloe-f28b78a21` (census fix, Tiberius PASS twice, no whole-tree tier).
- **e2e gate NOT green (bug `ff85f78f`)**: both halves cut at the 2,500 s limit twice with 0 failures. Tiberius measured the cause: 689 dead session files from the first harness run make the fleet-size-cap census take 9 s per page load on both servers. They age out of the 12 h window about 04:20 to 05:35 EDT; Rick's answer on quarantining them timed out, nothing was moved.
- **Still owed on `ca204c66`**: unit tier on a merged head with the two pinned commits, e2e re-run, integration (105 known reds with Mr. Radio), coverage gate, post-game for both days. Mementos: `.claude-memento-cheech-37cbc13d.md` (Rick's return list), `io/mementos/{maya,tiberius,chloe}.md`.
- **Files**: history.md, TODO.md; code via reviewed merges only.

### 2026.10.01 - Session cf6ff92a (Mr. Radio 🦉, manager; no crew, Rick ruled "no workers yet") | Test-VM fixes proven on a recreate and documented

- **Proven on lupin-host-test (row `72781b05`)**: resumed the suspended VM, deployed `a7f2af593` with a recreate; preflight pre 51 passed / 0 blocking, post 64 / 0. The 3 Google repos answer "dubious ownership" with the compose `GIT_CONFIG_*` off and resolve with it on. VM left running (Rick).
- **Commits**: `4d0fa1281` `src/docs/vm-new-host-checklist.md` + README line · `32e5fde8a` API docs regenerated after `64905b079` (2 reds reported by Cheech, now 9 passed). Not pushed.
- **Rulings**: preflight stays check-only (Rick); ratio check C9 stays a warning (my call).
- **Open on `72781b05`**: `lupin-vm.sh vm-start` cannot wake a suspended VM; the script needs `LUPIN_GCP_PROJECT_ID` exported; no roster line for weil-parallel-search on the VM.
- **Waiting on Rick**: the TypeSafe plugin install (the permission classifier refused it; two commands for him to run). Board unstaffed: `3a2f726b` P0, `a3c59f2d`, `80513825`, `c4a81acc`, `8a99f2ee`.
- **Files**: history.md, src/docs/vm-new-host-checklist.md, src/docs/README.md, src/docs/fastapi/api.json, src/docs/fastapi/api.md

#### Checkpoint | 2026.10.01 15:10 | Test-VM follow-up closed out; history written (`900e73b82`)

- **Session end ~15:45 EDT, spun down on Rick's word** (fleet focus is docs + wiki; none of my rows is). No push, no backup. Memento: root slot, session `cf6ff92a`.
- **Checks**: orphan-row check read 68 open rows, 2 findings, neither mine (`d8543167` → María, `768e852f` → Tiffany, past its chase). Delivery-collision scan exit 1 (informational). Orphaned-work sweep not installed in lupin. Memento sweep and both archives deferred (TODO Decisions Log 10-01).

### 2026.09.30 (evening) - Session 9d720da8 (Mr. Radio 🦉, manager; crew Maya 🌻, Chloé 🗼, Krishna 🦚, Sam 🎙️) | 17 rows closed on merges; doc viewer race closed; resume-job ownership; every job builder refuses bad input

- **Merged after 17:00, each on a clean full unit tier** (or named artifact reds re-run green): `54a011650` (`d51ffc36`) · `ea80264e1` (`876d183e`) · `f905e7aa3` comparator kept (`4f5301ad`) · `4c5214b64` container init, zombies 48→0 (`3c86391e`) · `f7eedfc17` MCP validation-alert throttle (`d49d713c`, after the 20:00 63-ping flood) · `5e7f02c0c` diag strip (`8c3628a4`, closed on `ts-a4cc8586`) · `f1fee2067` DOM-absence assert lint + frame-buffer LRU (`f2d3df2b`, `15111f96`) · `8f2093a9b` tier stamp sees a bundle rebuild (`105ff244`) · `9470e93d5` upload size cap before spooling (`4d2eb22f`) · `8df8690d2` scope paths judged by where they land (5 rows) · `41b854a56` (`8a578dd0`) · `12f610fc0` terse rows carry `item_class` (`7e1d72d0`) · `418a05c0e` preflight-vm venue scrubs every override var (`5ad93b8c`) · `64905b079` resume-job only resumes the caller's own job (`a758bd0f`) · `c8bd4ebf9` every job builder refuses bad input, no receptionist degrade (`a4014235`) · `04146b299` doc viewer judges the opened fd, not the string (`39b3035b`).
- **Rulings / ops**: P0 `08691779` closed (`e569fd1e0`; test-host ratio 24h/2.0); `88c4eb2c` Rick ruled "keep mux design"; self-respin at 21:42 (50.9%), wake proof written.
- **Held for tomorrow (re-owned to me)**: `1f4b30ce` io door race (P3), `1af41dc9` purge-pycache flake, `5aedbad2`, `8796333b`, `2af2c387`, `0c695d2a`, `27300d00`.
- **Files**: history.md; code via reviewed merges only.

### 2026.09.30 - Session 9867024c (Cheech 🌿, manager; crew Rachel 🕊️, Rio ⚡, Tiberius 👑, Pocholo 📣) | v0.2.2 code wiki + reuse review: W-B symindex, W-C reuse tools, Phase 1 linters merged; not pushed

- **Merged, all with Tiberius PASS (row `9babe43d`)**: `e0309132f` W-B symindex + W-C four reuse tools vs fake Jev · `57655ad7c` Phase 1 doc linters, Dart extractor, docstring fixtures · `e476d814f` Phase 0 docstring census + W-C STDIO integration tests · `cafbcf496` + `06b65ebe7` Dart unparsed-file reporting, field-section fix · `d2d24b994` plan diagrams inlined (E1) · `bf7d1ae39` a member of a private Dart owner is not public (277 records flip) · `f07a87f23` the Dart extractor is now part of the index freshness key. Working-branch head `f07a87f23`, **not pushed**.
- **Gates at `06b65ebe7`**: typecheck 3/3, stylelint 41/41, unit 27,670 passed, cosa 8,988 passed, 0 failed (run without coverage). No full tier yet on `f07a87f23`.
- **Rick's rulings**: Dart exit gate via an independent tree-sitter count (`9d449081`); E1 = delete the prototypes, inline the diagrams. That count found the private-owner index bug.
- **Owed (row `ca204c66`)**: coverage gate (blocked by a contention-guard false positive on live seats, bug `488403da`), a full tier at `f07a87f23`, the :8000 pyramid, the push, the post-game. The blind Dart gate `7a963ebf` is blocked until lupin-mobile has 30+ new Dart files.
- **Files**: history.md; code via reviewed merges; 4 untracked prototypes + 3 .mmd deleted from `src/rnd/v0.2.2/`.

### 2026.09.30 - Session 9d720da8 (Mr. Radio 🦉, manager; skeleton crew until 17:00) | Test-server port: 4 missing-config defects found and fixed on lupin-host-test

- **Dev**: Stop poke muted for skeleton crew (`poke_output_enabled=false`, 10:54 EDT); a one-shot systemd timer restores it at 17:00.
- **lupin-host-test (bug `08691779`, P0)**, each read back after applying:
  - `~/.claude/settings.json` had no `heartbeat` block, so the Stop poke was silently off. Added it (muted until 17:00) along with `task_store`.
  - There was no `~/.claude/fleet-roster.env`, so no seat was a manager and every manager-gated store write 403'd. Created it with `WEIL_NDA_DRAFTING_SUITE="Cheech"`; Cheech's new seat `92d6e14e` came up with `manager_figure_implicit=True`.
  - The flow-ratio override was missing, so the gate ran 24h / 1.0. Now 120h / 1.1, matching dev; enforcement paused for Cheech's batch, with an auto re-enable at 12:46 EDT.
  - The container's git refused the bind-mounted repos ("dubious ownership", a uid mismatch), which the receipt validator misreported as "commit not found". Added `safe.directory` for all 5 mounts.
- **Follow-up**: `31344c5f` (P0) folds all four fixes into the VM push script's preflight checks.
- **Files**: history.md, TODO.md (branch handoff). No code changes; the test-host changes were config only.

### 2026.09.29 - Session 0174263f (Mr. Radio 🦉, manager; crew Sam 🎙️, Krishna 🦚, John 🏄🏽, Pocholo 📣, Rio ⚡) | Door 18 retired; approval settings moved into the DB; arbiter DMs delivered for the first time; two same-evening reverts

- **Evening merges (after the 20:11 push)**: `2e732e4cc` + `43d8990cc` approval settings in a DB table, and an unverified legacy file imports nothing (`80513825`, test-DB check blocked on the :8000 refresh) · `170c8520c` door 18 retired to 410; a refused v2 submit answers failed / submit_refused (`a3c59f2d`, blocked the same way) · `98c4a1a6c` + `99845008f` stale-MCP check runs in the arbiter; arbiter DMs had been 422'd and dropped for lack of `sender_project` (all of them, manager_stale_poke included); now dispatched once per pid, verified live over 2 ticks (`97c5bd94`, the INI key is still owed) · `acb480a21` a null `prediction_hint` no longer blanks the Action Required card (`759250e4` closed on `ts-9729a7ab` 3/3).
- **Reverts, the same evening**: `cb06df64f` undid the threshold-0 comparator (`4f5301ad`, one new 9-px red in phase6a; repeat run planned for 09-30 10:00–13:00) · `f56990abb` undid the first arbiter re-land (the dedup key drifted each tick), re-landed fixed as `99845008f`.
- **Blocked on Rick**: the :8000 refresh (auto-mode classifier refused it; 3 asks timed out; chase 09-30 10:30), image-read permission on `io/test-suite/visual-failures` for workers, admits for `a758bd0f` (resume-job has no ownership check; suggest P2), `a4014235`, `1af41dc9`.
- **Files**: history.md; the rest via reviewed merges and two reverts.

### 2026.09.28 - Session e14bd712 (Mr. Radio 🦉, manager; skeleton crew until 17:00, then Rio ⚡, Krishna 🦚, Tiberius 👑) | Transcript stream phases 0–2 closed; FCM wake P0 fixed; workers on Sonnet 5.5; 6 merges, not pushed

- **Transcript stream (27760534) DONE**: console tee, multiplexer store/renderer/roster, sender-card button, `/app/console` pop-out page, legacy button, ring cap, empty-thinking label. TypeScript tier `ts-43804547` 5,562/0; e2e_a `ts-180d8fdb` and e2e_b `ts-742c706c` triaged, every red pre-existing except one (row `0a678842`).
- **Evening merges** (tip `b45460bb6`): `875bc7584` FCM wake notify deferred not dropped (P0 `ed76b897`) · `d0bd6377b` parity walker sums a section's own bodies (`08b0e669`) · `0d6762be6` retired-door API-reference guard (`a3c59f2d`) · `c4f413ddc` spawned workers → `claude-sonnet-5-5` (Rick's ruling) · `941fc2793` one `/ws/queue` socket per (user, device), close 4004 (`dc446601` part 1) · `b45460bb6` region overrides re-harvested for CC 2.1.284 (`922b261a`).
- **Rulings**: Tiffany — supersede code 4004 (4001–4003 taken), no supersede without a `device_id`. Rick — doors 6/7 build a v2 resume then retire (`67a2a093`), door 14 retire as-is (`432511fd`), door 18 pending (brief `io/2026.09.28-queue-doors-decision-brief.md`).
- **Incident**: a worker's `pkill -f "pytest src/tests/unit"` (20:56, ~21:34, 22:05) could kill other seats' unit tiers; fleet warned on commons `incident`.
- **Files**: `src/conf/lupin-app.ini`, `src/tests/unit/test_spawn_sessions.py` (mine); the rest via reviewed merges.

### 2026.09.26 - Session 9c9d8e76 (Mr. Radio 🦉, manager, Skeleton Shift; crew Krishna 🦚, Chloé 🗼, Rachel 🕊️, Sam 🎙️) | 14 rows merged and pushed; dev, test and VM at parity on `7532068e9`

1. **Merged and pushed** (every one reviewed + gated on the same tree): 8105670f `56b53cd6d` · 8033756c `e06f6ffb7`+`9027c1046` · 730b33f2 `947620a36` (io/tmp/ 7-day sweep, crontab installed) · 77422be2 `02fb86345` · fbd1b273 `228cea1a8` (VM flow-ratio dir, P0) · 93ca4268 `e15ffbe84` · 44d8e89c `bb1e71698` · e1e2c545 `0be847011`+`a65716b85` · 1ca233ae `24805da91` · 27398998 `2b1c76f6f` · b84bbf1c `7532068e9` (external doc-viewer mounts writable on dev/test/VM, 403 names its step and errno). Origin = local = VM = `7532068e9`.
2. **Open**: b84bbf1c awaits Rick's upload retry into weil-nda. P0 47759aa3 (doc links open in-app in both layouts) is WIP `29fcfcf03` on `wip-47759aa3-doclink-inapp-open`, owner Chloé. e923b34d (preflight counts a `${VAR}` in a comment) blocks every VM deploy until admitted. 991d6a3a: the weekly Sunday cron has no @reboot catch-up; next run Sun 09-27 19:00.
3. **Last Call** bc8e6090 (María filed): I reaped the crew at 21:56, 34 min early; Rick corrected it. Hold the crew until the bell and re-spin only the seat that is over context. Mementos: `io/mementos/{krishna,chloe,rachel,sam}.md`.
4. **Lessons**: read shas from git and verdicts from rows; condensed DMs dropped them ~10 times. Prove a mount with `docker inspect`, not with "the script recreates". Ask for the response body first; one field solved the upload 403. The auto-mode classifier denied deploys, compose edits and LUPIN_SKIP_PREFLIGHT; Rick running one exact line was the working fix.
5. **Holding area**: 7 rows re-owned from reaped workers to Mr. Radio at shift end (row 57486c03).

### 2026.09.25 - Session 09edaa9c (Mr. Radio 🦉, manager; crew Rachel 🕊️, María 🌸) | Rewriter live on the test VM; three security/robustness fixes and a stack-dump hook landed

1. **DM rewriter on the GCP test VM (row 65073e81, done)**: the VM inherited `dm_tutor/phi_4` (a LAN vLLM it can't reach), so every 5+-claim DM stalled about 155 s and then went out raw. Rick ruled Phi-4 on Model Garden cost-prohibitive, so the VM uses Flash-Lite. The fix was a `git apply` of the INI hunk plus an in-place `docker restart` after John ACKed. Verified: long DM 30–45 s timeout → 3.6 s, and the tutor fired → `fabrication_blocked` in 2.8 s. Committed as `457009f5e`, with the fleet cap = 3 line (Rick: commit config like any file).
2. **Landed on the working branch (not pushed)**: `56fefe9ab` /api/init gate made visible in /docs and callers (977eaaf2) · `d6e8cbc76` TTS stall watchdog (26bfde78) · `49f4f2e97` proxy path-routes owner-gated, and `/api/prediction-engine/reset` is now POST, credentialed, drop_table=False (2d6f2221) · `9de117a33` layout-parity Phase 1 ruled from geometry (645a7da5) · `6a294fcc2` `kill -USR1` dumps all stacks (abe4188d). Also 34a0175 in planning-is-prompting (the last_call cron interpreter).
3. **Open**: the name-lookup hang on the VM (abe4188d, parked; VM down; resolver ruled out, needs a live stack). Five proxy routes are still open (44d8e89c, admit pending). Stale Rick-blocks cleared: 1c7da903 was already done (`c0ea45e14`).
4. **Lessons**: DMs don't wake an idle seat, so type into its tmux pane. Condensed DMs lose detail, so read the pane or the row amendments. A greyed Claude Code suggestion is not user input. Say "blocked on Rick" only while an explicit ask is in flight.

### 2026.09.24 - Session 5c850e1b (Mr. Radio 🦉, manager, skeleton crew; Rick AFK most of the evening) | Merge train landed; watchdog and proxy-auth fixed after adversarial review; :8000 gate half-read

1. **Doc viewer Folder / Roots / Upload (row 416d4b00)**: done and merged (`36ff55a8`); :8000 `ts-85abc648` 45/45. Follow-ups filed: `02f3bc8f` (drop `:ro` on external-repo mounts, needs Rick) and `4d2eb22f` (pre-parse upload size limit).
2. **Merge train landed (row 977eaaf2)**: working branch fast-forwarded `36ff55a8 → 848ba37b`. Before landing, the train fixed its own additions to two guard tests: 9 parity tests moved to `PARITY-CLAIM:` with live citations, 6 citations shifted +4 past the /api/init insertion, and 4 DOM-node asserts changed to counts. The adversarial review then caught two of those citations pointing at the wrong code (`848ba37b`). Unit: 7 red, every one also red on main or a worktree artifact (main's reds filed as `542b2fc2`). Cosa 8,968. Coverage 97.38%.
3. **:8000 `ts-026c689f`**: typescript ✅. **e2e_a is invalid**: the multiplexer dist bundle was rebuilt at 19:50 by something outside the run, so half A served stale JS. e2e_b has new reds: an AR card that never appears, and 6 section visuals. Integration hung in `test_v2_eval_live` (200 live calls at about 2 min each, suite timeout still the TEMP 30000s), the same place as last night. Rick was told at 21:00.
4. **Row 26bfde78 TTS watchdog**: the review found that a release freed the slot but left the audio playing, so a late end could end the next item. Fixed (`178d5477`): the release halts the audio, and an item that arrives during a pause starts suspended. 368/368 tests; each of the 3 mutation arms reddened its own test.
5. **Row 2d6f2221 proxy auth**: the review found the owner guards protected nothing, because ProxyDecision has no owner column. Pending, ratify and delete are admin-only now (`768778d7`). Both fixes sit on `radio/followups-landing-20260924` (`92048a93`): unit 7 known reds / 26,005 passed, cosa 8,968. Coverage and :8000 wait for a free box.
6. **Lesson**: build the bundle, or run `check_bundle_freshness.py`, before scheduling E2E. Nothing rebuilds `dist/` on its own.

### 2026.09.23 - Session 75c92041 (Mr. Radio 🦉, manager; crew Rio ⚡, Krishna 🦚, Maya 🌻, Chloé 🗼) | Parity features, not tooling: 74 local commits, most of the owed B-rows merged

1. **Rick's ruling (~19:12): features first.** Staff the owed multiplexer-vs-legacy parity rows; tests only for the behaviour built. Merged on María's GO by sha: B-1/B-1b Q&A + TTFA/RTT, B-2 Submit Jobs, B-4 Time Saved, B-5/B-5L System Status, M1 ack tally, A-2 #6/#7, Recent Activity persist, broadcast-ack persistence (`4f320c27`).
2. **Earlier in the day**: Rick's 400-file R&D cut landed (`b113a3a7`); the 375-file second cut is **parked to 09-30** ("do not delete anything"). Test host `lupin-host-test` deployed d04152cf → d3dbbc89; its socket 403s were underscore session ids from stale legacy code.
3. **Not landed**: merge train `mrradio/merge-train` @ `a86e59b6` (B-3, A-2 #4/#11, B-6, B-7, TS RSS fix `fb7be6ca`, /api/init admin gate `816d882a`, stats 500 fix) is a clean fast-forward, held because `:8000` run `ts-f580148a` hung in `test_v2_eval_live.py` from 22:25 and killing it needs Rick's word (asked 23:10, no answer).
4. **ts-f580148a on old main**: typescript exit 137 (RSS), e2e_a 4 red, e2e_b 7 red + 3 errors, integration task_store reds, then the hang. The full pyramid on the train tip is owed tomorrow.
5. **Open for Rick**: `af01bd4b` (two speaking clients), `e772da4f` (badges as buttons), `8c3628a4` visual rebaselines. Memento: `.claude-memento-mr-radio-75c92041.md`.

### 2026.09.23 - Memento sweep (María 🌸, row `5b29a807`) | 814 mementos moved to the trash (5 kept for Mr. Radio, Sam, Cheech); per Rick's ruling, only the last two days summarized

- **09-22**: `src/rnd/README.md` is not authorization — 75 of 106 September docs were cited only by it. The §6.2 broadcast-ack reconciliation path is absent (a code trace, not a live measurement). A durable status field goes stale and cannot notice.

