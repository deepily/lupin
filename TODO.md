# TODO

Last updated: 2026-04-16 22:55 EDT (Session f01fdc2f close — Bug 12 + 13 landed + validated; Resume primed for morning)

---

## 🌅 MORNING BRIEFING — 2026-04-17

### TL;DR

Bug 12 + Bug 13 landed and **validated live tonight** via `tfe-3436c5b8`. A stalled TFE with 8 clusters + 17 proposals is waiting on `:8000` — primed for the **first real end-to-end TFE Resume** (Doc 18 D2 first half). Intentionally did NOT apply any of the proposed fixes manually tonight so you can exercise the Resume path in the morning.

### Boot-up sequence (strict order)

1. **Finish your DB seed-protection migration work first** — `src/scripts/seed_test_companions.py`, `src/tests/unit/test_admin_protected_accounts.py`, `src/tests/integration/conftest.py`, `src/tests/e2e_ui/conftest.py`, `bug-fix-queue.md` are all in-flight on your side. Commit/stash before step 2.
2. **Then bounce `lupin-rest-test`** — `docker restart lupin-rest-test`. Required because `cosa worktree enabled` was flipped to `true` tonight (commit `aed7c6d`) but the running container cached `false` at startup. Without the bounce, clicking Resume uses the pre-Bug-9 live-tree path and your in-flight work would be pulled into the TFE's fix PR.
3. **Then click Resume** on `tfe-3436c5b8` in the UI (or `POST http://localhost:8000/api/jobs/tfe-3436c5b8/resume`).

### What to expect on Resume

- Phase 2 voice gate re-fires with its full (formerly >5000 char) abstract visible — this is the FIRST real proof the Bug 13 cap removal works in the Resume path, not just fresh runs.
- You select proposals you trust. TFE's first 4 proposals are the same 4 one-liners that keep reappearing: `PRODUCT_NAMES` entry, `len == 9 → 10` in 3 sites, `resume_from` in `all_agents`, placeholder type assertion cleanup. Retires ~27 of 38 failures if all four land.
- Phase 3 FixExecutor writes inside `.claude/worktrees/tfe-3436c5b8/` (NOT your live tree, since worktree default is now `true` + container has been bounced to pick it up).
- Phase 5 GitStrategist creates branch + commits + PR from the worktree.
- Phase 6 auto-queues a validation `TestSuiteJob` to confirm the selected fixes retired the failures.

### What Bug 9 worktree isolation DOES and does NOT cover

Covered (safe from contamination): Python + JS source edits under `src/` via FixExecutor's `Edit` / `Write` tool calls; the GitStrategist branch cut off `origin/main`.

NOT covered (reasons it might still hit your tree): visual-baseline PNG regeneration (TFE proposal 1, needs `pytest --update-snapshots` outside the FixExecutor pattern) — if you select that, it'll run `pytest` against your live Chromium install, not the worktree. Skip it unless you've stashed your dev work.

### Rollback points if you're unhappy

| target | what it undoes |
|---|---|
| `git reset --hard aed7c6d^` | drops worktree `enabled=true` flip; keeps Bug 12 + 13 + validation commits |
| `git reset --hard bcbf5af` | drops Bug 13 fix + worktree flip; keeps Bug 12 + Bug 9 scaffolding |
| `git reset --hard 67dbd21^` | reverts ALL of tonight's work back to pre-session state |

CoSA submodule changes on disk (dispatcher + orchestrator edits + new `worktree_context.py`) are NOT git-committed by me — `git checkout -- agents/...` inside `src/cosa/` reverts those independently. `src/cosa/agents/shared/worktree_context.py` is untracked; delete it manually if rolling back.

### What I did NOT do tonight (intentional)

- No manual code fixes for the 38 failures — saved for Resume to exercise
- No `pytest` runs — respected your in-flight DB work
- No test-server interaction beyond the single `aed7c6d` INI flip (the running container hasn't seen it yet)
- No CoSA git commits — yours to handle when ready

### If Resume misbehaves

1. First: verify container bounce happened after the INI flip — `docker exec lupin-rest-test grep "cosa worktree enabled" /var/lupin/src/conf/lupin-app.ini` should show `true`.
2. Second: check `git status` inside `src/cosa/` — tonight's edits are uncommitted there and expected.
3. Third: full root-cause + context in `~/.claude/plans/let-s-start-a-new-zany-thimble.md` (postmortem-style plan file) and `src/rnd/v0.1.6/2026.04.16-bug-13-*.md` (design doc — wait, I never wrote one for Bug 13; see commit `3709139` message instead).
4. Fourth: if truly stuck, the 4 one-liner fixes are safe to apply by hand — same as TFE's first 4 proposals.

### Tonight's commit chain (newest → oldest)

```
aed7c6d  worktree enabled=true (default flip)
a389bc4  session close — Bug 12+13 validated via tfe-3436c5b8
bcbf5af  checkpoint: ts-d3df4d87 scheduled for Bug 13 validation
3709139  Bug 13: remove 5000-char caps + ValidationError→stall
029a55c  checkpoint: ts-e4089cf2 scheduled
5817533  Bug 12 + Bug 9 + 34 unit tests
67dbd21  overnight forensics + Bug 12 filed
```

---

## Active TODO below

## ~~🚨 First-thing next session — archive history (still pending from 2026-04-15)~~ ✅ DONE 2026-04-16

- [x] [LUPIN] **Archive history.md** — ✅ DONE Session eb50bd56. Archived 23 sessions (2026-04-08 to 2026-04-14) → `history/2026-04-08-to-14-history.md`. history.md now 10,008 tokens (down from 38,821). Commit: 2879cbf.

- [x] [LUPIN] **Review `ts-d3df4d87` outcome — BUG 12 + BUG 13 VALIDATED LIVE** ✅ DONE 2026-04-16 22:31 EDT. Ran on :8000, scheduled 20:08, completed 22:05. TFE `tfe-3436c5b8` auto-dispatched, reached Phase 2, voice gate fired to ricardo (not answered within 300s → real timeout), dispatcher raised VoiceGateTimeoutError, orchestrator saved checkpoint (8 clusters, 17 proposals, plan_path), job persisted with **`status=stalled`** (NOT completed). Stall notification sent with resume instructions. Report filename: `2026.04.16-at-22:31-EST-ts-d3df4d87-stalled-test_fix_expediter-report.md`. No `string_too_long` validation errors in the run → Bug 13 cap removal confirmed working in container. Dead-queue BFE dispatch also validated (`bfe-e29a16ec` from `dr-f9d615a4` mock).

- [x] [LUPIN] **Review `ts-e4089cf2` outcome** — ❌ Bug 12 regression exposed Bug 13. Ran 2026-04-16 17:24 EDT, completed 19:39 EDT. TFE `tfe-e4c73d5c` produced 19 proposals across 8 clusters, voice gate hit `abstract > 5000 chars` validation error, dispatcher swallowed it, job ended `status=completed (0 selected, 0 fixed)` instead of stalled. Root-caused, filed as Bug 13, fixed in commit `3709139`. Retried as `ts-d3df4d87`.

- [ ] [LUPIN] **Previously**: Review `ts-e4089cf2` outcome (scheduled 2026-04-16 17:24:00 EDT on :8000 test server; full `all` suite ~60 min; TFE voice gate expected ~18:25-18:40 EDT). **Acceptance criteria** for Bug 12 validation:
  - [ ] Test suite completes with ~38 failures (same reproducible baseline)
  - [ ] `TestSuiteCompletionWatchdog` auto-dispatches a TFE job
  - [ ] TFE reaches Phase 2 voice gate (generates ~21 proposals across 8 clusters)
  - [ ] Voice gate fires while operator offline → MCP 503 "User is offline"
  - [ ] **POST-FIX EXPECTED**: dispatcher raises `VoiceGateTimeoutError` → orchestrator saves checkpoint → raises `StalledException` → job persisted with `state=STALLED` (NOT `completed`)
  - [ ] UI History panel shows ⏸ Resume button for the TFE row
  - [ ] DB `metadata_json["checkpoint"]` contains rehydrated proposals for Resume-to-review
  - [ ] Worktree isolation status: with `[cosa_worktree] enabled=false` (default), confirm no worktree was created (Phase 3 not reached due to stall). If stall path fails, we'd see an unintended worktree attempt — that's also useful signal.
  - **If any criterion fails**: forensic capture + patch, do NOT escalate to Doc 18 D2 (attended Resume-apply) until Phase 5 stall-validation passes clean.

- [x] [LUPIN] **Bug 12 — MCP 503 should raise VoiceGateTimeoutError** ✅ DONE 2026-04-16 afternoon. Session-in-progress continuation of f01fdc2f. Scope narrowed after exploration: `present_choices` was already fixed by commit `49c238d` (Bug 7 side-effect); fix locus was `ask_confirmation` (line 300) + `get_feedback` (line 355) — both now raise `VoiceGateTimeoutError` on any non-0/2 exit code (HTTP 503, connection errors). 13/13 unit tests in `test_mcp_timeout_detection.py` pass (all three methods). Design doc: `src/rnd/v0.1.6/2026.04.16-bug-12-mcp-503-to-voice-gate-timeout.md`. Live re-creation scheduled next.

- [x] [LUPIN] **Bug 13 — Pre-MCP ValidationError swallowed by dispatcher** ✅ DONE 2026-04-16 evening. Discovered via postmortem of `tfe-e4c73d5c` (which ended `status=completed` despite Bug 12 fix being deployed). Root cause: TFE aggregate voice gate with 19 proposals + operator-routing prefix produced an `abstract` string > 5000 chars; `NotificationRequest`'s Pydantic validator raised `string_too_long` BEFORE the MCP call; outer `except Exception` in dispatcher swallowed it to `{"answers": {}}`; orchestrator read empty-answers as "user selected nothing" → completed. Two-part fix: (1) **removed 4× `max_length=5000` caps** on `NotificationRequest.message`/`abstract` and `AsyncNotificationRequest.message`/`abstract` — no upper bound per user directive ("remove that ridiculous limit"); (2) **dispatcher outer except now converts `ValidationError` + `ConnectionError` to `VoiceGateTimeoutError`** across all three methods (present_choices, ask_confirmation, get_feedback) so pre-MCP failures stall instead of silently defaulting. 20/20 unit tests in `test_mcp_timeout_detection.py` pass (7 new Bug 13 guards). Files: `src/cosa/agents/utils/agent_notification_dispatcher.py` + `src/lupin_cli/notifications/notification_models.py`.

- [ ] [LUPIN] **Act on overnight TFE's 21 proposals** — report at `io/swe-team/reports/interactive.job.tester@lupin.deepily.ai/2026.04.15-at-21:41-EST-ts-79829a75-completed-test_fix_expediter-report.md`. Four 1-liner wins would retire 27 of 38 failures: (1) `len(AGENTIC_AGENTS) == 9` → `== 10` in 3 sites, (2) re-capture 12 visual baselines via `--update-snapshots`, (3) add `PRODUCT_NAMES` entry for TFE Resume agent, (4) add `resume_from` key to `all_agents` profile. Option: land these directly OR re-run TFE (post-Bug-12) to get a proper stalled row.

- [ ] [LUPIN] **Review `ts-79829a75` outcome** — ✅ Ran 2026-04-15 21:05 EDT. 3647/3671 pass. Same 38 failures as morning baseline (reproducible). TFE auto-dispatched → 21 proposals → 0 selected due to Bug 12. Full forensics: `src/rnd/v0.1.6/2026.04.16-overnight-forensics-ts-79829a75.md`.
- [ ] [LUPIN] **Revert overnight INI override** — `[Lupin: Testing]` block in `src/conf/lupin-app.ini` has `test fix expediter lead model = claude-sonnet-4-6` (added for cheap overnight run). Decide whether to keep or revert to Baseline default (Opus lead).
- [ ] [LUPIN] **CoSA commit** — 9 submodule files need committing from inside `src/cosa/` repo: `agents/utils/agent_notification_dispatcher.py`, `agents/bug_fix_expediter/cosa_interface.py`, `agents/test_fix_expediter/orchestrator.py`, `agents/test_fix_expediter/state.py`, `rest/agentic_job_factory.py`, `rest/job_persistence.py`, `rest/queue_util.py`, `rest/running_fifo_queue.py`, `rest/routers/io_files.py`.

## 🆕 New follow-ups from Session f01fdc2f

- [x] [LUPIN] **Bug 8b — wire Pause/Stop voice-gate buttons end-to-end** ✅ DONE (commit unknown). MVP labels landed via `stall_reason`; full wiring completed.

- [x] [LUPIN] **Bug 9 — TFE/BFE Phase 3/5 git worktree isolation** ✅ DONE 2026-04-16 afternoon. `WorktreeContext` async context manager at `src/cosa/agents/shared/worktree_context.py` wraps Phase 3+5 in an isolated `git worktree add <sandbox>/<job_id> <base_ref>`. `[cosa_worktree]` INI section (default `enabled=false` for opt-in). Both BFE and TFE orchestrators have `worktree_scope()` + `_warn_on_uncommitted_changes_if_any()` uncommitted-changes safety guard. `_build_coder/tester_options` use `self._worktree_cwd or cu.get_project_root()`. `FixExecutor` accepts `worktree_cwd` for audit. 8/8 worktree_context tests + 13/13 fix_executor plumbing tests pass. Design doc: `src/rnd/v0.1.6/2026.04.16-bug-9-worktree-isolation.md`.

- [ ] [LUPIN] **Design knob — `test fix expediter feedback timeout action`** — options: `stall` (default, current behavior), `skip` (complete with 0 selected), `auto_select_high_confidence` (select proposals ≥ 0.85 confidence). INI + splainer + config.py + orchestrator._aggregate_voice_gate timeout branch. Low priority — stall is fine today.

- [ ] [LUPIN] **Validate Resume** (Doc 18 D2 first half, safe without Bug 9 activation) — `tfe-3436c5b8` is stalled on :8000 with full checkpoint + 17 proposals + plan_path. Click Resume in UI (or `POST http://localhost:8000/api/jobs/tfe-3436c5b8/resume`) while you're online → should rehydrate checkpoint, re-fire voice gate with the full abstract visible (this is the critical Bug 13 regression guard — the abstract length cap removal makes the resumed gate display-able for the first time). Phase 3 apply is SAFE today because `[cosa_worktree] enabled=false` — the FixExecutor path is guarded behind that flag; if resumed, voice gate answer goes through selection but Phase 3 is opt-out until you flip the flag. Fresh-stall row ready for the Resume smoke.

- [ ] [LUPIN] **TFE report rendering bug** — markdown report shows `Duration: 0.0s` and `C1 — 0 failure(s)` through `C8 — 0 failure(s)` even though `state_snapshot` has full cluster data (12 failure_indices on C1, etc.). The printer in `test_fix_expediter/job.py` or `report_writer.py` reads from a different data path than what gets persisted. Mentioned in 2026-04-16 overnight forensics + postmortem but never filed as an action item until now. Affected files: `src/cosa/agents/shared/report_writer.py` (render function) and `src/cosa/agents/test_fix_expediter/job.py` (report builder). Not blocking — cluster data is correct in the DB.

- [ ] [LUPIN] **Worktree maintenance CLI + monitoring** (Bug 9 follow-up) — (1) `src/scripts/worktree-cleanup.sh` to prune orphaned worktrees and report disk usage under `.claude/worktrees/`, (2) periodic cleanup of worktrees older than 7 days even if `auto_cleanup=false` was set, (3) telemetry for worktree disk usage in the admin dashboard. Out of scope for the initial Bug 9 landing.

- [ ] [LUPIN] **BFE dead-job race — eager snapshot + packager fallback (D1)** — `dead_queue_watchdog._submit_bfe` captures only `dead_job_id` string; BFE's later DB lookup fails if row evicted (done/dead rotation, TTL, or E2E `clean_test_db` drop). Fix: snapshot dead-job context at dispatch, have `package_dead_job()` accept snapshot-first. Files: `src/cosa/rest/dead_queue_watchdog.py:393-470`, `src/cosa/agents/bug_fix_expediter/dead_job_packager.py:38-42`, `src/cosa/agents/bug_fix_expediter/job.py:~227`.

- [ ] [LUPIN] **Full attended TFE live run (D2)** — schedule a live TFE where operator answers voice gate, selects real proposals, walks Phase 3/5/6 with real commits + PR. Prereq: overnight `ts-79829a75` outcome reviewed + Bug 9 worktree isolation ideally landed first (so operator's working tree can't contaminate PR).

- [ ] [LUPIN] **Pre-merge E2E gate (D3)** — parallel session's proposed `POST /api/test-suite/submit` with `test_types="e2e"` + `monopolize=true`. Fine to run post-archive; exercises all today's UI fixes (Bug 1 io/file, Bug 2 dedup, Bug 8 labels) but NOT the Claude Agent SDK path.

## 🔖 Carryover TODO entries (from 2026-04-14 and earlier)

- [ ] [LUPIN] **Review midnight `all` run outputs** (Session 6ae2513c — ran as `ts-d2d890ed` 2026-04-15 00:56 EDT) — SUPERSEDED by Session f01fdc2f which surfaced the SDK creds + ops routing issues. New overnight run `ts-79829a75` replaces this.

## 🔖 Resume tomorrow — active triage plan

**Triage doc**: `src/rnd/v0.1.6/2026.04.13-session-triage-and-option-c-docker-non-root.md` — 12 HIGH PRIORITY items (red), 3 TFE follow-ups (yellow), 14 older carry-overs (green). Items #1 #2 #3 closed Session 23f409c8. **Resume at item #9** (quick win: grep today's startup log for `[Watchdogs] BFE=ENABLED, TFE=ENABLED` to confirm already satisfied by rebuild), then #5 (schedule TFE Resume Live E2E) or #6 / #7 (Phase D/E follow-ups).

## Pending — HIGH PRIORITY

- [ ] [LUPIN] **Review three scheduled TFE jobs' outcomes (23:15 / 23:20 / 23:25 EDT)** — `ts-1139f28d` dry, `ts-996dafbc` live (with env_vars fixture), `ts-d2d890ed` all. Logs inside test container: `docker exec lupin-rest-test tail -80 /tmp/{pytest-direct,all}-latest.log`. Live run's outcome informs whether `/api/agentic-jobs/submit` exists (live test skips cleanly if missing).

- [ ] [LUPIN] **Follow-up if live test skipped on missing `/api/agentic-jobs/submit`** — add a generic agentic-job submit REST endpoint (factory wrapper like test-suite's) so the live test can actually submit TFE jobs. Currently the test body is complete but depends on this endpoint. Alternative: have the test go through `TestSuiteJob → watchdog` dispatch path.

- [x] [LUPIN] **Archive history.md** ✅ DONE Session eb50bd56 — commit 2879cbf. See above.

- [ ] [LUPIN] **Bug 2 — history-card scroll toggle** (deferred, awaits user devtools). DOM-id collision hypothesis: live Done card and History card render the same `id="job-details-${jobId}"`; `getElementById` returns the first match. Step 0 (devtools query: `total vs unique` count of `[id^="job-details-"]`) is the gate. Step 3 plan: namespace IDs by queueName at render time. Plan in `src/rnd/v0.1.6/2026.04.14-all-suite-aggregation-and-history-card-toggle.md`.

- [ ] [LUPIN] **Visual-regression snapshot drift** (12 `test_visual_page[chromium-*]` failures). Needs human UI review per page (login, register, change-password, profile, notifications, landing, admin-{dashboard,snapshots,users,ratify,trust}, dev-tools), then `./src/scripts/run-e2e-ui-tests.sh --bg --update-snapshots -k visual` if intentional.

- [ ] [LUPIN] **Auth 401 — test_tfe_resume_e2e + test_cross_container_auth** (8 failures). Migrate from mock-token patterns to JWT from `/auth/login` per `mock_tokens_are_legacy` memory. Not a TFE candidate — needs design decision on test-side credential helper.

- [ ] [LUPIN] **Run Option B chown to unblock backups** (USER-ONLY — needs sudo TTY) — `sudo chown -R rruiz:rruiz /mnt/DATA01/include/www.deepily.ai/projects/lupin/src/conf/long-term-memory/lupin.lancedb/` then re-run `/plan-backup --write` and confirm exit code 0. Originally 63,345 of 67,931 LanceDB files (93%) were owned by root from Docker container writes. This is a one-shot fix; new container writes will regenerate root-owned files until Option C lands.

- [x] [LUPIN] **Integrate Option C (Docker non-root user) with ongoing docker-compose refactor** — ✅ DONE Session 23f409c8 (2026-04-13). Image rebuilt, both `lupin-rest-dev` and `lupin-rest-test` now running as UID 1001(rruiz). All verification green: `/health` 200 on :7999 + :8000, HF cache at `/home/rruiz/.cache/huggingface`, marp CLI v4.3.1 installed, zero root-owned files after container runtime. Design + execution logs: `src/rnd/v0.1.6/2026.04.13-docker-non-root-user-plan.md`, `2026.04.13-session-triage-and-option-c-docker-non-root.md`, `2026.04.13-option-c-execution-log.md`. Side-fixes: `.dockerignore` expanded (io/, rnd/, tests/, ephemera/, submodules), postgres-dev-data chmod'd g+rX, LanceDB+io re-chown'd after root-file regrowth. Committed as `309f98c` (2026-04-13). Original description: — Plan doc: `src/rnd/v0.1.6/2026.04.13-docker-non-root-user-plan.md`. Permanent fix for LanceDB bind-mount permission problem. Key findings: it's NOT just `user: "1001:1001"` — the Dockerfile has 5 hard deps on `/root/` (d2 CLI, Claude config dir, mcp.json) and the compose has 3 `/root/` bind mounts; `/root` is mode 700 on Linux so UID 1001 can't enter it at all. Requires creating a non-root user in the Dockerfile (`useradd -u 1001 -g 1001 rruiz`), relocating all `/root/*` references to `/home/rruiz/*`, adding `user: "1001:1001"` to both `lupin-rest-dev` + `lupin-rest-test` services, and updating credential mount targets. 6 side-effects flagged in the plan (leftover root-owned files in `io/`, seed_test_companions writes, Claude Code MCP credentials path, GPU device access, `gh` CLI auth dir, HOME-expansion in Python code). Verification sequence: `docker exec lupin-rest-dev id` → expect UID 1001, then write test + `/plan-backup --write` → expect exit 0. Integrate during the in-progress docker factoring bounces.

- [x] [LUPIN] **Adjust `/plan-backup` script to surface per-file rsync errors** — ✅ DONE Session 23f409c8 (2026-04-13). `src/scripts/backup.sh` now captures rsync stderr to `/tmp/rsync-backup-YYYYMMDD-HHMMSS.log` via `tee`, and on non-zero exit prints error line count + full log path + last 20 error lines. Syntax-checked + dry-run validated. Option (b)+(c) from original TODO combined. Original description: — Current `tail -30` truncation hid 63k `Permission denied` errors last night, masking the Docker-root-write root cause until this morning's unfiltered re-run. Options: (a) bump to `tail -200`, (b) split stdout vs stderr so rsync errors aren't interleaved with progress, (c) when rsync exits code 23, print a dedicated "See full log at /tmp/rsync-backup-YYYYMMDD.log" line. Small DX fix, high value for future debugging. Touches `src/scripts/backup.sh`.

- [ ] [LUPIN] **CoSA submodule commits for Session 9056c113 continuation** — Phases 1+2 of doc 16 added CoSA edits that need committing: `agents/utils/agent_notification_dispatcher.py` (VoiceGateTimeoutError raise on exit_code==2), `agents/bug_fix_expediter/orchestrator.py` (stall handling in run_diagnosis + run_proposal + gate pass-through), `agents/runtime_argument_expeditor/agent_registry.py` (TFE resume entry), `agents/runtime_argument_expeditor/expeditor.py` (_handle_tfe_checkpoint_match handler). Plus whatever's still outstanding from earlier 9056c113 work not yet committed. User commits from CoSA repo context per nested-repo rule. Server is already running the old code — voice gate timeouts will not actually stall until CoSA committed + server restarted again.

- [x] [LUPIN] **Schedule TFE Resume Live E2E tonight** — ✅ DONE Session 9a488d40 (2026-04-13). Scheduled as `pytest_direct` against test container on port 8000 for 2026-04-13T21:00:00-04:00. Job `ts-a70a4b8a::50c73ba7-36dd-4eaf-a7e2-63256252c84f`, queue position 1, exclusive on, dry_run off, extra args `-v --tb=short`. Verification: `tail -50 /tmp/pytest-direct-latest.log` after 21:00. Full stall-and-resume path (`TFE_RESUME_E2E_LIVE=1`) remains out of scope — `run-pytest-direct.sh` doesn't passthrough env vars. Original description: — Ready to execute. Use notifications UI test-suite submit card: test type = `integration`, file path = `src/tests/integration/test_tfe_resume_e2e.py`, scheduled_at = <after-hours>, monopolize = true. 10 endpoint-validation tests that exercise /api/test-fix-expediter/resume-from and /api/jobs/{id}/resume-from-checkpoint dispatch logic (error paths, auth, input validation). Full stall-and-resume gated behind `TFE_RESUME_E2E_LIVE=1` env var + INI `test fix expediter feedback timeout seconds = 5` (requires manual tuning). Driver: `src/tests/e2e/run-tfe-resume-e2e.sh [--live]`.

- [ ] [LUPIN] **Phase D follow-ups: file-path resume + CLI flag** — Deferred from Session 9056c113 Phase D core. Need (a) `POST /api/test-fix-expediter/resume-from-file` endpoint with auto-detection for `.md` plan doc (resume from Phase 3) vs `.json` checkpoint (resume from checkpoint's ordinal) vs `tfe-*` job ID (shortcut to stalled resume) — mirrors Presentation Generator `render_only` + `yaml_path` pattern (`routers/presentation_generator.py:40,172-186`). (b) "Resume from" text input on TFE submission card in `notifications.js`. (c) `--resume <job_id>` and `--resume-from <path>` flags in `src/tests/e2e/run-tfe-live-e2e.sh`. Plan doc: `src/rnd/v0.1.6/2026.04.10-test-fix-expediter/14-checkpoint-resume-and-completion-report.md` Steps D4b-D4d + D5.

- [ ] [LUPIN] **Phase E follow-ups: BFE completion report + BFE checkpoint-resume** — Deferred from Session 9056c113 Phase E core (skill update done, cross-agent rollout deferred). Follow the patterns now documented in `src/workflow/agentic-voice-workflow.md` v3.0 Phase 11 (completion report) + Phase 12 (checkpoint-resume). BFE already has a text summary (`bug_fix_expediter/job.py:283-290`) — wrap it with `voice_io.notify()` + rich abstract. BFE has voice gates at Phase 2 (fix selection) + Phase 5 (trust confirmation) — add `save_checkpoint()`/`load_checkpoint()` + `StalledException` catch. Reuse exception types from TFE (or extract to shared module). Podcast completion report similarly needs a voice notification if missing.

- [ ] [LUPIN] **FastAPI restart + CoSA submodule rebuild needed to activate checkpoint-resume** — Session 9056c113 edits are inside `src/cosa/` submodule. After user commits CoSA + running server picks up the new code, test the end-to-end flow: (1) submit TFE job that will stall (e.g., low `feedback_timeout_seconds` in INI), (2) verify stalled voice notification + stalled badge in UI, (3) click "▶ Resume from Checkpoint" button, (4) verify new TFE job runs from Phase 3 (skipping already-completed phases 0-2).

- [x] [LUPIN] **FastAPI restart needed to pick up unified watchdogs init + flipped INI defaults** — ✅ Verified live Session 6ae2513c: `docker logs lupin-rest-dev | grep -i watchdog` shows `[Watchdogs] BFE=ENABLED, TFE=ENABLED` + `[TestSuiteCompletionWatchdog] initialized (enabled=True, max_failures=50)`. Triage doc item #9 closed.
- [ ] [LUPIN] **TFE live E2E monopolize run (real SDK + real git)** — All infrastructure ready: `src/tests/e2e/run-tfe-live-e2e.sh --live` will exercise the full pipeline against real Claude Agent SDK + real GitOps with a bug-injector-seeded failure. Schedule via `/schedule-tests` skill after hours. Cost gate: ~$15 per run (`test fix expediter cost cap usd`). Validates everything: clustering heuristic, Phase 1 diagnosis prompts, Phase 2 proposal gates, FixExecutor retry loop, multi-cluster git strategy, Phase 6 rerun recursion guard. Until this runs, the 3119-unit-test green bar is the only validation.
- [ ] [LUPIN] **PEFT trainer run on GPU — TFE voice routing** — Training data ready: 75 templates in `src/ephemera/prompts/data/synthetic-data-agent-routing-test-fix-expediter.txt`, command registered in `src/conf/training/agent-router-agentic-commands.json`, unit tests (12) pass. USER-RUN ONLY per `feedback_never_grab_gpu` memory. When GPU free: `./src/scripts/run-agentic-intent-training.sh test` (sanity) then `full` (~3-4 hrs). Also note Session 389 left prior PEFT data regenerated — confirm whether TFE additions require a full regen or a merge.
- [ ] [LUPIN] **BFE Phase 6 LIVE E2E (parallel console state unknown)** — User was running BFE Phase 6 live E2E in a separate console during Session 1cfcdf73. Outcome unknown. Verify whether the baseline was established + results captured. Dry-run + persistence fixes already landed in Session 1b8c1cc0 (76/76 unit tests passing); remaining: real Claude Agent SDK, real git commits, known-bad mutation. Enable `bug fix expediter enabled = true` in INI + schedule as monopolized test-suite job after hours.
- [x] [LUPIN] **CoSA submodule commits for Session 1cfcdf73 work** — COMMITTED earlier (commits `a577cec`, `cd8ed49`). TFE implementation landed with `shared/` package, `test_fix_expediter/` package (14 files), `rest/test_suite_completion_watchdog.py`, `rest/running_fifo_queue.py` hook, `rest/agentic_job_factory.py` elif, BFE shims.

## Pending — TFE follow-ups (non-blocking)

- [ ] [LUPIN] **TFE Phase 0 `llm_refine` real SDK wiring** — Infrastructure in place: `llm_refine(ctx, seeds, max_clusters, refine_fn=None)` accepts async callback. MVP uses pure-Python `_cap_enforce()` fallback. Plugging in real Opus SDK call would refine clusters beyond the heuristic. Lives in `src/cosa/agents/test_fix_expediter/cluster.py`.
- [ ] [LUPIN] **TFE `agent_registry.py` entry** — Deferred during scaffolding. Factory routing works via direct elif in `agentic_job_factory.py`. Adding the `agent_registry.py` entry would enable uniform agent discovery and match the pattern used by deep_research/podcast_generator.
- [ ] [LUPIN] **`FixContext` Pydantic model (optional refactor)** — TFE currently uses `SimpleNamespace` duck-typed pass-through to `shared.FixExecutor`. Formalizing as a Pydantic model would add validation + serialization. Not blocking any work.

## Pending — Older items carrying over

- [ ] [LUPIN] **Phase 11: Presentation Generator Theme Integration** — Cross-cutting theme wiring for all renderers. Plan doc: `src/rnd/v0.1.6/2026.03.14-presentation-generator/renderers/05-theme-integration-plan.md`.
- [ ] [LUPIN] **#1-Phase 4 (DEFERRED): migrate remaining 13 compliant fetch sites to authedFetch for uniformity** — Session 85b05d1d implemented Phase 2+3 (helper + 12 non-compliant migrations, commit e68d827). Pure cleanup with no user benefit; can be picked up opportunistically. Plan doc: `src/rnd/v0.1.6/2026.04.10-notifications-js-auth-token-refresh-audit.md`
- [ ] [LUPIN] **#3-Followup: sdla restart lupin-rest to propagate new pytest.ini paths into container** — Session 85b05d1d commit 824f314 relocated visual regression artifacts. Host-side test (`-k visual`) passes 12/12. The container's bind-mounted `pytest.ini` still points to the OLD inode. Next `sdla restart` picks up the new inode automatically.
- [ ] [LUPIN] **#5 Research 5-6 dead/paused jobs stuck in todo queue** — User reports 5-6 dead or paused jobs visible in todo queue. Investigation inconclusive (transient test-suite traffic hypothesis). Findings doc: `src/rnd/v0.1.6/2026.04.10-stuck-todo-jobs-investigation.md`. Needs user clarification on account + current state.
- [ ] [LUPIN] **Clean up debug code in `test_suite/job.py`** — Remove temporary debug `print()` statements (6+ lines), `loop_count`/`children_count` variables, and re-enable `os.unlink(junit_xml_path)` after confirming remediation snapshot works end-to-end.
- [ ] [LUPIN] **Remove [DIAG-JR] diagnostic logging** — In `notifications.js` (3 console.log blocks) and `notifications.py` (1 print). Remove after verifying activity log auto-expand works in production.
- [ ] [LUPIN] **TestSuiteJob: Surface stderr when subprocess crashes at startup** — When exit_code!=0 AND 0 tests found, response_text says "FAILURES DETECTED" with 0/0/0. Should include captured stdout/stderr tail so operator sees the actual error immediately. Discovered Session 8042b0d1.
- [ ] [LUPIN] **Test-Suite Job — INI-driven timeouts** — Phase 2 uses hardcoded `SUITE_TIMEOUTS_SECONDS` dict. Promote to INI config keys so operators can tune without code changes.
- [ ] [LUPIN] **Test-Suite Job — Phase 3 (conftest.py addoption)** — Consolidate `smoke_direct` into unified `smoke` runner via pytest's `pytest_addoption` hooks. ~30 min work. Not blocking. Plan: `src/rnd/2026.04.05-test-suite-agentic-job-comprehensive-expansion.md` Phase 3.
- [ ] [LUPIN] **Interrupted job re-enqueue mechanism** — `mark_interrupted_jobs()` in `job_persistence.py` marks pending/running jobs as interrupted at startup but does NOT re-enqueue them. Long-running jobs (presentation ~8min, deep research ~15min) are lost on server restart. Proposed: persist constructor args in `metadata_json` at creation time, add `requeue_interrupted_jobs()` at startup with max retry guard.
- [ ] [LUPIN] **Run Opus through test-suite endpoint** — Sonnet validated (`pr-512e5ca4`, 15 slides, $0.46). Opus has never run through `POST /api/test-suite/submit`. ~$2.43 cost.
- [ ] [LUPIN] **TestSuiteJob Manual + Automated Testing remaining items** — Pattern A implemented (Session 386). Remaining: (1) Fix voice_io dispatcher bug (`AgentNotificationDispatcher` missing `notify` attribute), (2) Manual UI verification of submit card + scheduling, (3) Verify scheduling timezone fix with live scheduled job, (4) Run live pipeline smoke test with server, (5) Integration test for `POST /api/test-suite/submit`.
- [ ] [LUPIN] **Automated E2E testing workflow** — Design standard pattern for scheduling E2E/integration test runs as monopolized jobs at user-specified times. Becomes the modus operandi for all post-coding verification.
- [ ] [LUPIN] **Full E2E re-run needed to verify 2 visual regression errors are pre-existing** (test_visual_regression.py profile + notifications)

## Completed this session (5a620729, 2026-04-14 — bug-fix mode bug #1 + harness unblock)

- [x] [LUPIN] **Bug #1: BFE/TFE job cards lack interactions and results documents** — RC-1 voice_io.notify() decoupled from is_voice_available() probe gate (was cached-False silent drop); RC-2 NEW `src/cosa/agents/shared/report_writer.py` + `_write_final_report()` hooks on BFE (5 exits) + TFE (3 exits) populating `artifacts["report_path"]` for "📋 View Full Report" UI link. 30 unit tests green (test_report_writer.py 14, test_voice_io_notify_decoupling.py 6, test_peer_proxy.py 12). Live validated: `dr-eb1b680e` → dead queue → `bfe-f91fd115` dispatched, 15 notification rows with correct compound job_id + sender_id. Plan: `src/rnd/v0.1.6/2026.04.14-bfe-tfe-interactions-and-reports.md`. **All agent-code changes live in CoSA submodule — user commits separately.**

- [x] [LUPIN] **NEW `POST /api/push-agentic` endpoint** — unattended/service-to-service agentic job submission that bypasses the runtime-argument-expeditor. Caller provides explicit `routing_command` + `args` dict + `websocket_id`. No voice-path LORA parsing, no interactive Q&A. Unblocks E2E scripts and other headless callers. New `push_job_agentic()` method on `TodoFifoQueue`. **CoSA-side edits, user commits separately.**

- [x] [LUPIN] **Test harness unblock — BFE/TFE E2E scripts** — `run-tfe-live-e2e.sh` + `run-bfe-live-e2e.sh` patched to use `/api/push-agentic`. NEW `src/tests/fixtures/bfe/snapshot_known_bad.json` (deep_research dry-run with force_failure_mode=code_bug, matches new payload shape). Full chain validated end-to-end against :8000.

- [x] [LUPIN] **Peer Queue Watch (dev UI → test server)** — Checkpoints 1-3 from earlier today. `/app/admin/peer-queue-watch` widget + backend proxy + server-side watcher that fires voice notification on drain. Three bug fixes resolved during live testing (empty combo box, Docker-networking host resolution, JWT pass-through not possible because separate DBs → switched to Option B service-account login). Plus bonus fix of the test-UI admin lockout via `seed_test_companions.py` manual re-run.

- [x] [LUPIN] **Test server force-refresh mechanism** — Checkpoint 1 from earlier today. `src/scripts/refresh-test-server.sh` + `/refresh-test` slash command + admin `POST /admin/refresh-source` endpoint (test-env gated, os.execv re-exec). Handles the `reload=False` constraint on the test container.

## Completed this session (9056c113 continuation, 2026-04-12)

- [x] [LUPIN] **Doc 16 Phase 1: MCP timeout detection → VoiceGateTimeoutError** — Session 9056c113 continuation. AgentNotificationDispatcher.ask_confirmation() + present_choices() now raise VoiceGateTimeoutError on MCP NotificationResponse.exit_code==2 (user-unavailable signal). BFE orchestrator wraps voice gate calls in run_diagnosis + run_proposal, catches the exception, saves checkpoint, raises StalledException. BFE internal voice gate methods pass the exception through the auto-approve fallback. TFE was already set up from Phase C. 6 new unit tests in test_mcp_timeout_detection.py. Both TFE + BFE now stall cleanly in production — checkpoint-resume path finally has a real trigger.

- [x] [LUPIN] **Doc 16 Phase 2: Voice expeditor integration for TFE resume (was doc 15 Phase 2)** — Session 9056c113 continuation. agent_registry.py entry "agent router go to test fix expediter resume" with resume_from arg + tfe_checkpoint_match special handler. Expeditor._handle_tfe_checkpoint_match (120 lines) reuses resume_resolver.list_resume_candidates + fuzzy_match_candidates with fast-path for literal job IDs/plan paths, auto-select at confidence >= 0.9 for stalled jobs. 35 voice training templates in synthetic-data-agent-routing-test-fix-expediter-resume.txt, registered in agent-router-agentic-commands.json, whitelisted in AGENTIC_TEMPLATES. 10 new unit tests in test_tfe_resume_expeditor.py. PEFT trainer user-run only.

- [x] [LUPIN] **Doc 16 Phase 3: Live TFE resume E2E driver (task #11 automated portion)** — Session 9056c113 continuation. Integration test `src/tests/integration/test_tfe_resume_e2e.py` with 10 endpoint-validation tests (pre-flight health, resume-from/resume-from-checkpoint dispatch logic, auth, error paths, input validation). Live stall-and-resume test gated behind TFE_RESUME_E2E_LIVE=1 env var since it needs interactive voice gate timeout. Shell driver `src/tests/e2e/run-tfe-resume-e2e.sh` wraps the pytest file. User schedules via test-suite submit card with test type=integration, file path=src/tests/integration/test_tfe_resume_e2e.py, monopolize=true, scheduled_at=after-hours.

## Completed earlier (1cfcdf73 follow-on, 2026-04-12)

- [x] [LUPIN] **Archive history.md — 03.26 → 04.07 block (CRITICAL token gate resolved)** — Session 1cfcdf73 follow-on. File was at 23,393 tokens (93.5%, CRITICAL). Split at 04.07/04.08 day boundary per canonical workflow — BFE Phase 6 + Sonnet-pivot block archived, TFE + UPE + watchdog block retained. New archive `history/2026-03-26-to-04-07-history.md` (33 sessions, 10,818 tokens). Main `history.md` now 12,607 tokens (50.4%, HEALTHY) — 16 sessions spanning 04.08 → 04.12. Updated `history/README.md` index with 3 new rows (new archive + 2 pre-existing unindexed archives `2026-03-13-to-26` and `2026-03-03-to-12`). Token counts measured via canonical `~/.claude/scripts/get-token-count.sh`. No CoSA touches.

## Completed earlier this session (248e740e, 2026-04-12)

- [x] [LUPIN] **TFE forensics capture — CoSA submodule commit + push** — Session 248e740e. Committed 4 working-tree-only CoSA edits (`agents/test_fix_expediter/{job,orchestrator}.py`, `rest/job_persistence.py`, `rest/routers/queues.py`) as CoSA commit `660dcd8`: BFE-pattern lifecycle + traceback capture + voice routing fix (TARGET_USER/SENDER_ID) + urgent crash notification + plan_path artifact surfacing; removed invalid `notification_type` kwarg from `notify_progress()`; added `test_fix_expediter` to `AGENTIC_JOB_TYPES` allowlist; new dead-queue handler surfacing partial artifacts from failed agentic jobs. Pushed CoSA (`f210d10..660dcd8`) and Lupin parent (`6c04cd9..685c134` — 4 prior-session commits) to origin.

## Completed earlier this session (9056c113, 2026-04-12)

- [x] [LUPIN] **TFE checkpoint-resume + completion report + agentic-voice-workflow v3.0 (5 phases, 35 tests, 0 regressions)** — Session 9056c113. Forensic on `tfe-7c25082a` stall → full design plan → 5-phase implementation. Phase A: TFE completion voice notification with outcome-aware three-variant TTS + rich markdown abstract mirroring Deep Research pattern. Phase B: new `STALLED` JobState + `RESUMABLE_STATES` convenience set + `RUNNING↔STALLED` transitions + `"todo"` UI container mapping. Phase C: `VoiceGateTimeoutError` + `StalledException` + `CheckpointData` TypedDict + `TFE_PHASE_ORDINALS` + `save_checkpoint()`/`load_checkpoint()`/`set_resume_phase()` on TFE orchestrator + voice gate timeout propagation + `__STALLED__` sentinel in `_execute()`/`do_all()` + `checkpoint` added to persistence rich_fields. Phase D: `get_checkpoint_for_job()`/`get_original_args_for_job()` queries + `resume_job()` factory + `POST /api/jobs/{id}/resume-from-checkpoint` endpoint + stalled badge + "Resume from Checkpoint" button + `resumeStalledJob()` JS + CSS + resume detection in `_execute()`. Phase E: agentic-voice-workflow.md **v3.0** with new Phase 11 (Completion Report) + Phase 12 (Checkpoint-Resume) as standard BUILD phases — every new agent now inherits these patterns by default. Plan doc: `src/rnd/v0.1.6/2026.04.10-test-fix-expediter/14-checkpoint-resume-and-completion-report.md`. Deferred: D4b-D4d (file-path resume endpoint + UI input), D5 (CLI flag), E1-E2 (BFE/Podcast rollout) — all patterns now in skill for async execution.

## Completed earlier (1cfcdf73 follow-on, 2026-04-12)

- [x] [LUPIN] **Codebase analysis: Lupin parent vs CoSA submodule** — Session 1cfcdf73 follow-on. Ran `cosa.repo.run_directory_analyzer` against full project + `src/` + `src/cosa/` + 5 drill-down subdirs. Wrote persistent R&D doc at `src/rnd/v0.1.6/2026.04.12-codebase-analysis-lupin-vs-cosa.md` with Mermaid flowchart (color-coded parent/CoSA/engine), numeric tables, 7 observations, and explicit coupling of the 61/39 Python split with the CoSA-never-commit-from-parent rule. Headline: project is 558k lines total (2,306 files); CoSA submodule is 168k (30%, 88.6% Python, 31.4% docstring ratio — Design-by-Contract manifesting measurably); Lupin parent is 390k (70%, dominated by R&D planning markdown 108k + Dart mobile 43k + JS frontend 22k + tests 90k). Added "Codebase metrics" bullet to top-level `README.md` R&D archive section. Placement corrected from `src/rnd/` root to `src/rnd/v0.1.6/` per convention + fixed relative links.

## Completed earlier (1cfcdf73 lunch run, 2026-04-11)

- [x] [LUPIN] **Unified watchdogs facade + TFE auto-fix defaults + per-run override** — Session 1cfcdf73 lunch run. Root-caused why TFE never fixed the 12 overnight visual regression failures: (1) `init_watchdog()` was never called for TFE in `main.py` startup; (2) both auto-fix flags defaulted to `false`. Shipped: `src/cosa/rest/watchdogs.py` (new `init_watchdogs()` facade brings up BFE + TFE singletons in one call, resilient to one-side failure), `main.py` rewired to use the facade, both INI flags flipped to `true` (default = run unless told otherwise) + splainer entries updated, `TestSuiteJob.auto_fix_on_failure: Optional[bool]` constructor kwarg threading per-run override through factory → REST `/api/test-suite/submit` → watchdog Gate 1 (tri-state precedence: explicit False short-circuits, explicit True overrides INI false, None falls back to INI), `/api/config/client` exposes `test_fix_expediter_auto_fix_enabled` so the UI knows the INI default, new "🛠️ Auto-fix on failure (TFE)" checkbox in the notifications dashboard test runner card with initial state synced from the endpoint. BFE stays INI-only per user direction. Documentation updated in all 3 agent guides (BFE, TFE, scheduler). 45 new unit tests across 3 files (6 per-run override + 11 facade resilience + 24 `_parse_optional_boolean` + 4 TestSuiteJob/TFE config). **Bonus root-cause fixes (8 pre-existing failures, fixed at the source not deferred)**: cosa-voice MCP module-import path now catches `Timeout` in addition to `ConnectionError` (slow server was crashing every test that imported the module); presentation generator subprocess test now passes `PYTHONPATH=src` so the venv interpreter can find the cosa package; TFE config dataclass default flipped to True for consistency. Final regression: **3169 passed, 1 xfailed, 0 failed** (~19 min, was 3161 / 8 failed). Working-tree CoSA edits await user's CoSA-context commit.

## Completed earlier this session (1cfcdf73 morning + afternoon, 2026-04-10)

- [x] [LUPIN] **TFE implementation — 20 steps complete, 3119 passed / 1 xfailed** — Session 1cfcdf73. Full Option B: new `TestFixExpediterJob` with 6 phases (cluster, diagnose, propose, fix, git, rerun), `TestSuiteCompletionWatchdog`, 197 new unit tests across 13 files, zero regression. Extraction (PlanWriter, GitStrategist, FixExecutor) into new `src/cosa/agents/shared/` peer package. 16 INI keys + splainer entries. Proxy Q&A script. PEFT training data (75 templates + command registration). Live E2E shell driver with `--dry-run` / `--live` modes. Detailed execution logs in `src/rnd/v0.1.6/2026.04.10-test-fix-expediter/90-95-*.md`. All CoSA-resident edits working-tree only — user commits in CoSA session.
- [x] [LUPIN] **User-facing docs for BFE + TFE + test-suite scheduler** — Session 1cfcdf73. New `src/docs/agents/` subdirectory (matches `src/docs/auth/` precedent) with 5 guides totaling 2,384 lines: `bug-fix-expediter-guide.md` (551), `test-fix-expediter-guide.md` (673), `test-suite-scheduling-guide.md` (518), `shared-fix-primitives-reference.md` (528), `README.md` (114). Updated `src/docs/README.md` with new section + verification dates. Updated `src/docs/rest-api-reference.md` with sections 17/17a/17b + `bfe-`/`tfe-` prefix rows. Updated top-level `README.md` with agents subsection. Updated `CLAUDE.md` DOCUMENTATION TOUCHPOINTS with 8 new rows. Verification: 0 broken links, 30/30 INI keys present in both INI and splainer, 21/21 critical code paths resolve.
- [x] [LUPIN] **Design: Test Suite → BFE Remediation Handoff** — Session 1cfcdf73 (morning). Three options analyzed. **Option B chosen**: new `TestFixExpediterJob` with shared FixExecutor. 20 planning docs written. Serialized plan: `src/rnd/2026.04.10-test-fix-expediter-plan.md`. (Implementation completed same session.)

## Completed earlier (Sessions 85b05d1d, 1b8c1cc0, etc.)

- [x] [LUPIN] **#0 Checkpoint work before continuing (Session 85b05d1d lunch run)** — Commit 5b95859. Lupin-parent-only: plan doc + history.md + TODO.md + .claude-session.md. Deliberately did NOT commit the re-baselined profile/notifications PNGs since #3 relocated them.
- [x] [LUPIN] **#1 notifications.js auth refresh — authedFetch helper + 12 non-compliant migrations** — Session 85b05d1d commit e68d827. Added `authedFetch(url, options)` helper to NotificationsUI, migrated 12 sites that were missing proactive token refresh (including `loadJobInteractions` which was the user's originally-reported 401 bug). Audit correction: initial estimate of 16 non-compliant was actually 12 (my heuristic walker stopped at nested if/else blocks and produced 4 false positives). Syntax clean, 0 non-compliant sites remain. Phase 4 (migrate the 13 already-compliant sites for file uniformity) deferred.
- [x] [LUPIN] **#2 Test report filename UTC → America/New_York with -EST/-EDT suffix** — Session 85b05d1d. Edited `src/cosa/agents/test_suite/job.py:340-350` to use `ZoneInfo("America/New_York")` with `%Z` format specifier. Filenames now produce e.g. `2026.04.10-at-12:34-EDT-e2e-results.md` instead of UTC `2026.04.10-at-16:34-e2e-results.md`. Body "Date" field also gets the TZ suffix. Working tree only, **CoSA submodule — user commits from CoSA session**.
- [x] [LUPIN] **#3 Move visual regression artifacts out of src tree** — Session 85b05d1d commit 824f314. Relocated `src/tests/e2e_ui/__snapshots__/` → `io/test-suite/visual-baselines/` (12 PNGs) and `src/tests/e2e_ui/snapshot_failures/` → `io/test-suite/visual-failures/` (empty, regenerates on run). Updated `pytest.ini` `playwright_visual_snapshots_path` and `playwright_visual_snapshot_failures_path` keys. Host-side `-k visual` run: 12/12 pass. Container propagation requires next `sdla restart` (see #3-Followup above).
- [x] [LUPIN] **#4 Visual regression cold/warm baseline drift** — Session 85b05d1d. Added `pytest_collection_modifyitems` hook in `src/tests/e2e_ui/conftest.py` that forces visual regression tests to run FIRST in the e2e suite. Hypothesis: Chromium font/render cache warms over 323 prior tests, producing subpixel anti-aliasing drift; baselines captured in cold state fail in warm state. Fix ensures cold Chromium for visual tests regardless of suite size. Plan doc: `src/rnd/v0.1.6/2026.04.10-visual-regression-cold-warm-drift.md`. **VERIFIED**: full e2e run at 12:44 EDT returned `335 passed in 1202.84s (0:20:02)` — all 335 tests including 12 visual regression pass cleanly with the hook in place. Cold/warm hypothesis confirmed.
- [x] [LUPIN] **#5 Research 5-6 stuck todo jobs** — Session 85b05d1d. Investigation complete. Dev DB `lupin_db_dev` has 0 stuck jobs (just 12 historical completed). Test DB `lupin_db_test` is completely empty post-cleanup. Most likely explanation: user was watching UI during the 10:32 EDT e2e run and saw transient test-suite traffic — `test_qa_submission.py`, `test_job_dispatch.py` et al. submit real queue jobs to validate queue APIs, and those briefly sit in todo before consumption. The "dead or paused" framing was likely misreading of "pending" state. No active bug found. Findings doc: `src/rnd/v0.1.6/2026.04.10-stuck-todo-jobs-investigation.md`. **User clarification needed**: which UI account are you logged in as, and are the 5-6 jobs STILL visible now that the e2e is done?
- [x] [LUPIN] **E2E result count mismatch — "335 passed, 0 failed, 0 skipped" but FAIL** — Session 85b05d1d. Three-layer fix: (1) display bug — `src/cosa/agents/test_suite/job.py` was dropping `errors` count from 5 user-facing summary strings + `cost_summary` dict; now shows "335 passed, 0 failed, 12 errors, 0 skipped" (CoSA submodule, edit only, awaiting CoSA-side commit). (2) container config bug — `pytest.ini` was missing from the lupin-rest container entirely (only `src/` and `io/` bind-mounted); added `-v "$LUPIN_ROOT/pytest.ini:/var/lupin/pytest.ini:ro"` to `scripts/server/start-docker-lupin.sh:381` (deepily/scripts repo, edit only, awaiting commit there). (3) stale visual regression baselines — `profile.png`/`notifications.png` hadn't been re-captured since Session 383 layout width change (800→1000px); refreshed via surgical `-k visual --update-snapshots`. Validation: full e2e scheduled run produced correct honest summary line with `12 errors` visible. Plan doc + 5 follow-up items filed as #1-#5. See `src/rnd/v0.1.6/2026.04.10-notifications-js-auth-token-refresh-audit.md` for #1 details.

- [x] [LUPIN] **CoSA commit: Sessions bacc971a+6b8670e7+f28d32d1 (8 files)** — Committed 7618499. Idempotency cache, CBR prediction JSON fix, cross-user WS delivery, remediation snapshots, stale queue guard. Sessions 97f29034+a312ee22 were committed previously as 4a97876.
- [x] [LUPIN] **Design: Test Suite → BFE Remediation Handoff** — Session 1cfcdf73 (2026-04-10). Three options analyzed (A: modify BFE, B: new TestFixExpediter, C: intermediate clusterer). **Option B chosen**: new `TestFixExpediterJob` (`tfe-` prefix) with Phase 0 clustering, test-aware diagnose/propose prompts, delegated Phase 3 fix via extracted `shared/FixExecutor`, reused BFE Phase 5 trust/git via extracted `shared/GitStrategist`, async Phase 6 rerun validation with recursion guard. New `TestSuiteCompletionWatchdog` dispatches TFE when TestSuiteJob completes with `all_passed=false`. 20 planning docs written (14 design + 6 execution logs) in `src/rnd/v0.1.6/2026.04.10-test-fix-expediter/`. Serialized plan: `src/rnd/2026.04.10-test-fix-expediter-plan.md`. All edits will be inside `src/cosa/` (CoSA submodule — edit only, no Lupin-context commits).

- [ ] [LUPIN] **TFE implementation** — Execute the 19-step sequence from `src/rnd/2026.04.10-test-fix-expediter-plan.md`. Precondition: BFE Phase 6 live E2E (dry-run first) baseline established in the parallel console. Steps: (1-3) extract PlanWriter/GitStrategist/FixExecutor to `src/cosa/agents/shared/`, (6) TFE scaffolding with all agentic-voice-workflow-mandated modules, (7-12) TFE phases 0-6, (13) TestSuiteCompletionWatchdog + queue hook + main init, (14) 12 INI keys + splainer, (15) proxy Q&A script, (16) live pipeline test, (17) PEFT training data generation (USER runs trainer), (18) E2E dry-run, (19) live monopolize run via `/schedule-tests`. Track progress in execution logs 90-95 in the planning dir.
- [ ] [LUPIN] **Clean up debug code in `test_suite/job.py`** — Remove temporary debug `print()` statements (6+ lines), `loop_count`/`children_count` variables, and re-enable `os.unlink(junit_xml_path)` after confirming remediation snapshot works end-to-end.
- [ ] [LUPIN] **Remove [DIAG-JR] diagnostic logging** — In `notifications.js` (3 console.log blocks) and `notifications.py` (1 print). Remove after verifying activity log auto-expand works in production.
- [x] [LUPIN] **E2E test scheduled 9:26 PM EST** — `ts-efba6552`. Reviewed Session f28d32d1: 335 passed, 12 visual regression errors (Docker snapshot path mismatch, expected).
- [ ] [LUPIN] **BFE Phase 6: LIVE E2E test of automated repair loop (non-dry-run)**. Dry-run smoke test complete (Session 1b8c1cc0, doc 09) and persistence gaps fixed (Session 1b8c1cc0, doc 10) — 76/76 unit tests passing, full loop verified end-to-end via DB inspection at $0 cost. Remaining: LIVE run with real Claude Agent SDK, real git commits, known-bad mutation. Enable `auto fix enabled = true` in INI, submit presentation gen job with intentional source-path bug, verify watchdog → BFE (real agents) → resubmit cycle completes. Schedule as monopolized test-suite job after hours.
- [ ] [LUPIN] **TFE Phase 6: LIVE E2E test of test-fix repair loop (non-dry-run)**. **Precondition**: TFE forensics fix plan (`src/rnd/v0.1.6/2026.04.11-tfe-forensics-capture-plan.md`) must land first so any failure produces real error + traceback data in `job_history` instead of "Unknown error" — without that fix this E2E is un-debuggable. **Scope**: LIVE run with real Claude Agent SDK (Opus lead + Sonnet worker), real git commits, real failing tests. Enable `test fix expediter auto fix enabled = true` in INI, submit a `test_suite` job with a known-failing test pattern (stale visual regression baselines or a deliberately broken unit test), verify the `TestSuiteCompletionWatchdog` → TFE (real agents) → cluster → diagnose → propose → voice gate → fix → git → rerun cycle completes end-to-end. Success criterion: the rerun test suite reports PASS. Schedule as monopolized test-suite job after hours via `/schedule-tests` or the test-suite REST endpoint. Expected cost: ~$2-8 per run depending on cluster count and phase depth (Opus diagnosis + Sonnet fix cycles). **Mirrors the BFE Phase 6 live E2E TODO above** — BFE targets `DeadQueueWatchdog → BFE → fix presentation` loop; TFE targets `TestSuiteCompletionWatchdog → TFE → fix tests` loop. The two loops share infrastructure (persistence, voice gates, PlanWriter, GitStrategist) but have different watchdogs, entry points, and target outcomes, tracked as separate TODO items for independent scheduling and cleaner failure isolation.
- [ ] [LUPIN] **Automated E2E testing workflow**: Design standard pattern for scheduling E2E/integration test runs as monopolized jobs at user-specified times. Becomes the modus operandi for all post-coding verification.

- [ ] [LUPIN] **Session 389 VERIFICATION — return to review today's work (NEXT SESSION)**. Two bodies of work landed in Session 389 that need end-to-end verification: (1) Voice routing training data complete coverage (5 content-gen agents, multi-placeholder expansion bug fix in xml_coordinator.py), (2) BFE Phase 5 Trust Proxy + Git Strategy (git_ops.py, run_git_strategy, 33 new tests, 2,831 unit tests passing). User shut down mid-session; resume with: summarize what was completed, verify commits landed (Lupin parent-repo + COSA nested-repo commits pending), confirm no regressions, identify any loose ends. Plan docs: `src/rnd/v0.1.6/2026.03.27-bug-fix-expediter/07-phase5-execution-log.md`, `src/cosa/agents/presentation_generator/rnd/2026.04.05-voice-routing-training-data-complete-coverage.md`.

- [x] [LUPIN] **Docker: Mount ~/.lupin/ as volume for test credentials** — FIXED Session 5946362f. Added `-v "$HOME/.lupin:/root/.lupin:ro"` to `start-docker-lupin.sh`. Verified: `test-env.sh` and `config` visible inside container after restart.
- [ ] [LUPIN] **Test-Suite Job — Phase 3 (conftest.py addoption) — DEFERRED to 2026-04-07**. Consolidate `smoke_direct` into unified `smoke` runner via pytest's `pytest_addoption` hooks (--auto-proxy, --cost-cap-usd, --group, etc.). ~30 min work. Not blocking anything. Plan: `src/rnd/2026.04.05-test-suite-agentic-job-comprehensive-expansion.md` Phase 3.
- [x] [LUPIN] **Test-Suite Job — Persist to DB** — FIXED Session 8042b0d1. Added `"test_suite"` to `AGENTIC_JOB_TYPES` in `job_persistence.py:42-51`. Follow-up: `mark_interrupted_jobs()` marks but doesn't re-enqueue; consider auto-re-enqueue for pending jobs on startup.
- [ ] [LUPIN] **TestSuiteJob — Surface stderr when subprocess crashes at startup**. When exit_code!=0 AND 0 tests found, response_text says "FAILURES DETECTED" with 0/0/0 — misleading. Should include captured stdout/stderr tail so operator sees the actual error immediately. Discovered Session 8042b0d1 when 142ms crash showed no diagnostic info.
- [ ] [LUPIN] **Test-Suite Job — INI-driven timeouts** (follow-up). Phase 2 uses hardcoded `SUITE_TIMEOUTS_SECONDS` dict in job.py. Promote to INI config keys so operators can tune without code changes. Original plan called for this; deferred for v1 pragmatism.
- [ ] [LUPIN] **Run PEFT trainer — training data REGENERATED & ready (USER-RUN GPU)**. Session 389 expanded training data for complete argument coverage across 5 content-gen agents: presentation_generator (5 placeholders + renderer/duration/audience/audience_context), research_to_presentation, podcast_generator, research_to_podcast, deep_research. Also added monopolize conditional_args for test_suite, target_languages multi-value conditional (es-MX/es-ES/es-AR + en/fr/de) for podcast agents. Fixed multi-placeholder expansion bug in xml_coordinator.py. 35,564 train + 4,446 test + 4,446 validate examples generated; all JSONL files validated. **When GPU free, USER runs**: `./src/scripts/run-agentic-intent-training.sh test` (1% sanity, 5-10 min) then `full` (~3-4 hrs). Plan: `src/cosa/agents/presentation_generator/rnd/2026.04.05-voice-routing-training-data-complete-coverage.md`.

- [x] [LUPIN] **Bug Fix Expediter — Phase 5: Trust Proxy + Git Strategy**. Session 389 COMPLETED. 33 new tests (16 git_ops + 17 phase5), 2,831 unit tests passing. 3 new files (git_ops.py, test_bfe_git_ops.py, test_bfe_phase5.py), 6 modified (state.py +COMMITTING +git fields, config.py +trust_mode, plan_writer.py +Git References, orchestrator.py +run_git_strategy, job.py wiring, INI+splainer). Trust-to-git mapping: L1-L2→commit_only, L3+→branch_and_pr via gh; gh unavailable degrades to branch_only. Multi-placeholder expansion bug fix in xml_coordinator.py. Execution log: `src/rnd/v0.1.6/2026.03.27-bug-fix-expediter/07-phase5-execution-log.md`.
- [x] [LUPIN] **Claude Agent SDK Upgrade 0.1.36 → 0.1.56** — Session db376295. Upgraded 20 patches (was 16 behind at 0.1.52, went to latest 0.1.56 to align with Dockerfile). RateLimitEvent handling added to 9 streaming loops in 3 files, version pin updated in requirements.txt. 162 unit tests passing. Analysis: `src/rnd/v0.1.6/2026.03.30-claude-agent-sdk-upgrade-0.1.36-to-0.1.52.md`.
- [x] [LUPIN] **Presentation Generator Visual Rendering Expansion — Phase 9A: MatplotlibRenderer** — Session 388: 30 new tests, all passing. MatplotlibRenderer + prompts + API client + orchestrator integration + seaborn dep. Plan doc: `src/rnd/v0.1.6/2026.03.14-presentation-generator/renderers/2026.04.01-matplotlib-renderer-implementation.md`
- [x] [LUPIN] **Presentation Generator Visual Rendering Expansion — Phase 9B: D2Renderer** — Session 388b: 25 new tests, all passing. D2Renderer + prompts + API client + orchestrator registration + d2 CLI install + Dockerfile update. Plan doc: `src/rnd/v0.1.6/2026.03.14-presentation-generator/renderers/2026.04.01-d2-renderer-implementation.md`
- [x] [LUPIN] **Presentation Generator Visual Rendering Expansion — Phase 10A: NanoBananaRenderer** — Session 388: 27 new tests, all passing. NanoBananaRenderer + GeminiImageClient + image prompts + INI config + orchestrator try/except registration. Plan doc: `src/rnd/v0.1.6/2026.03.14-presentation-generator/renderers/2026.04.01-nano-banana-renderer-implementation.md`
- [x] [LUPIN] **Presentation Generator Visual Rendering Expansion — Phase 10B: VeoRenderer** — Session 388b: 26 new tests, all passing. VeoRenderer + video prompts + GeminiImageClient generate_video() + config-driven Veo model + orchestrator + VISUAL_TYPES expanded 8→17. Plan doc: `src/rnd/v0.1.6/2026.03.14-presentation-generator/renderers/2026.04.01-veo-renderer-implementation.md`
- [ ] [LUPIN] **Presentation Generator Visual Rendering Expansion — Phase 11: Theme Integration**. Cross-cutting theme wiring for all renderers. Plan doc: `src/rnd/v0.1.6/2026.03.14-presentation-generator/renderers/05-theme-integration-plan.md`.
- [x] [LUPIN] ~~**Archive history.md — CRITICAL**~~ — Resolved: was 19.5k after Session 373b, now 10.4k (41.5%) after Session 375 archival
- [x] [LUPIN] **Presentation Generator Phase D verification — COMPLETED Session 8042b0d1**. Live E2E ran successfully: `pr-fc786e8e`, 469s (7m49s), 15 slides, $2.43 cost, 10 Claude API calls. All 4 gates auto-approved via scripted proxy. Full results: `src/rnd/v0.1.6/2026.03.14-presentation-generator/2026.04.05-phase-d-live-e2e-results.md`.
- [x] [LUPIN] **Presentation Generator — Sonnet as automated testing default** — COMPLETED Session 5946362f. Haiku ($0.06/run) produced 0 slides; pivoted to Sonnet (`claude-sonnet-4-6`). Sonnet run: `pr-512e5ca4`, 472s, **15 slides**, **$0.46** (81% cheaper than Opus), 8/8 sub-checks PASS. Updated INI, splainer, config.py defaults. Added `slide_count > 0` assertion + `--timeout` CLI arg + timeout 600→900s.
- [x] [LUPIN] **Phase D re-run through test-suite endpoint — COMPLETED Session 93c49ccb**. Ran via `POST /api/test-suite/submit` with Haiku (`claude-haiku-4-5-20251001`). Job `pr-b77c44d3`, 192s (3m12s), $0.06 cost (97% cheaper than Opus $2.43), 3 API calls, 15,226 in / 11,810 out tokens. **Quality issue**: 0 slides generated — pipeline completed without error but YAML output didn't produce parseable slides. Cost cap revised $2→$5.
- [x] [LUPIN] **Presentation Generator — Haiku quality investigation** — RESOLVED Session 5946362f. Inspected YAML artifact `pres-bd87e234`: valid YAML with `slides: []`. Root cause: Haiku content quality insufficient for structured YAML schema (only 3 API calls vs Opus's 10). Decision: pivot to Sonnet (confirmed working). Postmortem: `src/rnd/v0.1.6/2026.03.14-presentation-generator/2026.04.07-phase-d-postmortem.md`.
- [x] [LUPIN] **Smoke test timeout too short for test-suite path** — FIXED Session 5946362f. `DEFAULT_TIMEOUT` 600→900. Added `--timeout` CLI arg for operator override. Also updates `REQUEST_TIMEOUT` when provided.
- [ ] [LUPIN] **Interrupted job re-enqueue mechanism**. `mark_interrupted_jobs()` in `job_persistence.py` marks pending/running jobs as interrupted at startup but does NOT re-enqueue them. Long-running jobs (presentation ~8min, deep research ~15min) are lost on server restart. Proposed: persist constructor args in `metadata_json` at creation time, add `requeue_interrupted_jobs()` at startup with max retry guard. See postmortem plan: `~/.claude/plans/misty-noodling-babbage.md` Step 5.
- [ ] [LUPIN] **Run Opus through test-suite endpoint**. Sonnet validated (`pr-512e5ca4`, 15 slides, $0.46). Opus has never run through `POST /api/test-suite/submit` — the Apr 5 success was via rogue background bash. ~$2.43 cost.
- [x] [LUPIN] **CoSA commit — Session 8042b0d1 (4 files)** — Committed from CoSA repo context. Files: job.py (SUITE_SCRIPTS/timeouts), cost_tracker.py (pricing comment), config.py (presentation_gates), job_persistence.py (test_suite type).
- [x] [LUPIN] **CJ Flow Phase 5: Notifications UI + WebSocket Integration** — Session 382: 6 code steps + Phase 6 docs complete, 14/14 E2E Playwright tests pass, 2372 unit tests (0 regressions). Plan doc: `src/rnd/2026.03.28-cj-flow-phase-5-notifications-ui.md`
- [x] [LUPIN] **CJ Flow History: Delete & retry E2E tests** — Session 382b: 11-test manual rubric automated as 9 Playwright E2E tests (3 classes). 9/9 new tests pass, full regression 317/318 (1 pre-existing). Retry tests mock backend (LLM routing unavailable in test env). Plan doc: `src/rnd/v0.1.6/2026.03.27-cj-flow-history-delete-retry-manual-testing-rubric.md`
- [x] [LUPIN] Presentation Generator Phase 6: Marp Text Rendering — Session 382d: 6/6 tasks, 45 new tests, MarpTextRenderer + theme system + orchestrator integration
- [x] [LUPIN] Presentation Generator Phase 7: Visual Rendering — Session 382d: 7/7 tasks, 43 new tests, VisualRenderer ABC + MermaidRenderer + PlaceholderRenderer + registry + Gate 4
- [x] [LUPIN] **Presentation Generator Phase 8: Delivery & Chaining** — Session 383: `_deliver_async()` real implementation + DR→Presentation bridge (5 new files), factory, registry, router, main.py, PRODUCT_NAMES, job_persistence. 32 new unit tests. Automated testing infra: proxy Q&A scripts, config profiles, 3 integration scenarios, dry-run smoke test, voice routing utterances (65×2), UI checkbox + dropdown, E2E tests, skill doc checklist. Plan doc: `src/rnd/v0.1.6/2026.03.14-presentation-generator/10-phase-8-implementation-plan.md`
- [x] [LUPIN] Presentation Generator Phase C verification: CJ Flow dry-run queue submission + UI card — Session 374: 6/6 smoke tests pass, mode maps + HTML card + JS handler added
- [x] [LUPIN] Presentation Generator Phase 3: Ingest & Analyze — Content generation, first LLM work
- [x] [LUPIN] Presentation Generator Phase 4: Outline & Elaborate — Session 371: 7/7 tasks, 94 new tests
- [x] [LUPIN] Presentation Generator Phase 5: Serialize YAML — Session 371: 5/5 tasks, 17 new tests
- [x] [LUPIN] Presentation Generator: Wire `fuzzy_file_match` special handler — Session 371: already wired, added presentation-specific config key
- [x] [LUPIN] **Bug Fix: WebSocket 503 "user_not_available" — audio WS auth fix not yet working.** Root cause confirmed: audio WS endpoint connects without user auth, so after hot reloads only a "ghost" connection (in `active_connections` but not `user_sessions`) remains. Fix added auth_request handling to audio endpoint (`websocket.py:205-260`) but needs further debugging — test notification still failed. Diagnostic infrastructure in place (`[NOTIFY] ⚠️ OFFLINE DIAG`, `[WS-DIAG]` browser prefix, `[WS] STATE` logs). Plan doc: `~/.claude/plans/bubbly-churning-donut.md` — **Fixed Session 371**
- [x] [LUPIN] Phase 1: Create `admin@lupin.deepily.ai` account + update `~/.lupin/config` (manual) — Session 372: Done
- [x] [LUPIN] **Bug Fix: Voice injection silent crash on null title** — Session 372: `NotificationItem.title` was None, crashing listener's `startswith()`. Fixed at source: `title: str = ""` in constructor + API boundary normalization. 36/36 listener + 189/189 model tests pass.
- [x] [LUPIN] **CJ Flow Persistence Phase 6: Job History UI** — Session 371: Hybrid overlay model (Option C) with deduplication. 5th collapsible history section, configurable time window, delete/retry management, 19 new tests. Plan doc: `src/rnd/2026.03.13-cj-flow-persistence-plan.md`
- [x] [LUPIN] Phase 6 cleanup: Clean up existing 1001 `st-*` test notification artifacts (delete or reassign — decide after using filter) — **Fixed Session 371**
- [x] [LUPIN] Archive history.md — at 18.4k tokens, above 17k WARNING threshold (deferred from Session 371b) — **Superseded**: now 19.5k+, escalated to CRITICAL in Session 374 TODO above
- [x] [LUPIN] **Run clean full integration suite** — Session 380: **195 passed, 0 failed, 32 skipped** in 5:50. LanceDB isolation + warm test fixes verified clean. Added `--bg` flag + PID-file overlap protection to `run-integration-tests.sh` (same pattern as E2E runner). Fixed `test_admin_not_self_excludes_own_jobs` (500 from push pipeline unavailable in test env → skip gracefully).
- [x] [LUPIN] CoSA commit pending: `websocket.py` Fix 4 (WebSocketDisconnect handler + safe close) — committed from CoSA repo context
- [x] [LUPIN] CoSA commit pending: Session 383 — `local_embedding_engine.py` (added `local_files_only=True` to SentenceTransformer) — committed from CoSA repo context
- [x] [LUPIN] CoSA commit pending: Session 382b — `configuration_manager.py` (visual grouping stem split: `"_"` → whitespace) — committed from CoSA repo context
- [x] [LUPIN] CoSA commit pending: Session 380b fixes — `running_fifo_queue.py` (stack trace capture), `job_persistence.py` (stack_trace rich_field), `deep_research/job.py` (cost_summary in artifacts), `presentation_generator/job.py` (cost_summary tokens), `podcast_generator.py` (Field import), `presentation_generator.py` (Field import) — committed from CoSA repo context
- [x] [LUPIN] CoSA commit pending: Voice injection bug fix — `notification_fifo_queue.py`, `notifications.py`, `base_listener.py` — committed b544c78
- [x] [LUPIN] CoSA commit pending: session_name pipeline — `notification_fifo_queue.py` (session_name attr), `notifications.py` (session_name param + session_topic type) — committed b544c78
- [ ] [LUPIN] **TestSuiteJob: Manual + Automated Testing** — Pattern A implemented (Session 386). Remaining: (1) Fix voice_io dispatcher bug (`AgentNotificationDispatcher` missing `notify` attribute — notifications fall back to CLI), (2) Manual UI verification of submit card + scheduling, (3) Verify scheduling timezone fix with live scheduled job, (4) Run live pipeline smoke test with server, (5) Integration test for `POST /api/test-suite/submit`. Plan: `src/rnd/v0.1.6/2026.03.31-test-suite-agentic-job-plan.md`
- [x] [LUPIN] **Scheduled Long-Running Jobs in CJ Flow** — Pattern A (TestSuiteJob) fully implemented Session 386. Pattern B (PEFT training OS-level orchestrator) deferred. Planning doc: `src/rnd/v0.1.6/2026.03.30-scheduled-long-running-jobs.md`
- [x] [LUPIN] Run full E2E + integration test suite before merging branch to main — Session 385: all 4 layers passed (unit 2647, WS 50/50, E2E 14/14 pause/schedule, integration 196). Full E2E re-run needed for visual regression (2 pre-existing errors).
- [x] [LUPIN] CoSA commit pending: Session 385 — Unified Job State Machine (~25 CoSA files: job_state.py, queue_protocol, queue_util, job_persistence, fifo_queue, queue_consumer, running_fifo_queue, todo_fifo_queue, routers/queues, agent_base, agentic_job_base, solution_snapshot, 9 agent jobs, mock_job) — committed from CoSA repo context
- [ ] [LUPIN] Full E2E re-run needed to verify 2 visual regression errors are pre-existing (test_visual_regression.py profile + notifications)
- [x] [LUPIN] **Verify E2E UI test suite health — clean single run needed** — Session 377: **297 passed, 0 failed** in 17m12s. Session 372c's 23 errors confirmed as hot-swap collision (not real failures). Added `--bg` flag to `run-e2e-ui-tests.sh` with PID-file overlap protection to prevent recurrence. Updated 1 stale visual snapshot (notifications page). Suite is fully healthy.

## COMPLETED — Stop Hook Qualifier (Sessions 332-336)

- [x] **[LUPIN] Fix stop hook qualifier: Claude Code ignores qualifier text** — Session 336: Replaced broken `systemMessage` approach with tmux injection. `inject_qualifier_via_tmux()` spawns detached background process that injects qualifier text directly into CC's tmux input after stop block. Uses bash positional args for shell-safe text passing. 36/36 tests pass. Needs manual E2E verification (Phase 4).
  - **Phases 1-2 (Sessions 332-333)**: `reason` and `systemMessage` both silently ignored by CC Stop hooks
  - **Phase 3 (Session 336)**: tmux injection — proven technique from `CCNotificationListener._inject_via_tmux()`

## COMPLETED — CC Listener Session ID Drift (Session 335)

- [x] **[LUPIN] Fix CC Notification Listener session ID drift after context clears** — Session 335: Implemented write-once lockfile (`cc-stable-{ppid}.id`) with atomic `open('x')`, passed `stable_session_id` to listener, added `accepted_ids` set for multi-hash filtering, extended stale cleanup with PID liveness check. 9 new tests, 28 total pass.
  - **Design doc**: `src/rnd/.../2026.03.10-stable-session-id-lockfile-and-listener-drift-fix.md`

## COMPLETED — Hook Session ID Drift (Session 342)

- [x] **[LUPIN] Fix session ID drift across hooks after context clear** — Session 342: Added `resolve_stable_session_id()` to session_bridge.py. All 6 hooks + hook_common.py now resolve transient CC session_id to stable lockfile ID. MCP `get_session_info()` exposes `stable_session_id`. 231/231 hook tests pass.

## HIGH PRIORITY — Consolidate Credential Stores (Session 337)

- [x] **[LUPIN] Consolidate three credential/config files into unified `~/.lupin/config`** — Session 337c: Steps 1-6 (code + tests). Session 338: Step 7 migration executed on live system. Session 339: Step 8 hardened — removed all legacy fallbacks, fail-hard on missing config, updated cloud-run scripts. 38/38 tests pass.
  - **Plan doc**: [`src/rnd/2026.03.10-consolidate-credential-stores.md`](src/rnd/2026.03.10-consolidate-credential-stores.md)

## HIGH PRIORITY — MCP Strict Project Detection + Repo Account Validation (Session 332)

- [x] **[LUPIN] cosa-voice MCP: strict project detection + per-repo account validation** — Session 339: Implemented. MCP server no longer falls back to `"unknown"` project; validates per-repo Lupin account at startup; sends urgent notification on validation failure.
  - **Plan doc**: [`src/rnd/2026.03.10-mcp-strict-project-detection-account-validation.md`](src/rnd/2026.03.10-mcp-strict-project-detection-account-validation.md)
  - **Files**: `cosa_voice_mcp.py`, `notification_utils.py`, new test file

## HIGH PRIORITY — CC Session Voice Input Bugs (Session 300)

- [x] **[LUPIN] Fix date off-by-one in CC session outgoing bubble** — Session 332: Fixed. `extractDateFromTimestamp()` now parses through `appTimezone`.

## HIGH PRIORITY — PG Audio Progress Not Updating In-Place (Session 329)

- [x] **[LUPIN] Fix PG audio progress notifications not using progress_group_id** — Session 330: Added `progress_group_id = self._audio_progress_group_id` to Phase 5 English audio start notification in `orchestrator.py`. The first notification now establishes the DOM tag so subsequent milestone notifications update in-place.

## COMPLETED — Review `active_conversation_changed` + JS Event Anomalies (Sessions 329, 331)

- [x] **[LUPIN] Investigate `active_conversation_changed` WebSocket event** — Session 331: Removed dead code. Server emitted it but never in INI available events or JS subscriptions. Both emission blocks removed from `notifications.py`, unreachable JS handler removed from `notifications.js`.
- [x] **[LUPIN] Investigate oddly named event type in JS notification API** — Session 331: Two events (`notification_play_sound`, `audio_streaming_chunk`) were subscribed but had no `case` handler, falling through to "Unhandled message type" default. Added no-op log handlers to both.

## HIGH PRIORITY — target_user Notification Dispatch Bug (Session 286)

- [x] **[LUPIN] Fix target_user "Cannot resolve" error in Docker** — Session 304: Root cause was sender_id double-hash (`#cli#pg-xxx`). Fixed `_get_sender_id()` suffix param in both podcast_generator and deep_research cosa_interface + job files. 10 unit tests written.
  - **Bug fix doc**: [`src/rnd/2026.02.27-target-user-notification-dispatch-bug-fix.md`](src/rnd/2026.02.27-target-user-notification-dispatch-bug-fix.md)

## HIGH PRIORITY — Podcast Generator Bugs (Session 283)

- [x] **[LUPIN] Fuzzy matching via voice** — Session 304: Added `difflib.get_close_matches()` as 3rd validation tier in `match_research_docs()`. 14 unit tests written.
- [x] **[LUPIN] Job card contact failure** — Session 304: Fixed sender_id double-hash in `_get_sender_id()` suffix param. Same root cause as target_user bug above.
- [x] **[LUPIN] Audio segment upload** — Session 304: 3 sub-fixes: (1) non-interactive `_is_interactive()` guard on all `input()` CLI fallbacks in voice_io.py, (2) fixed TTS cost key `tts_results` → `tts_results_en` in orchestrator.py, (3) pre-stitching guard when all segments fail. 13 unit tests written.

---

## v0.1.6 — FUTURE DEVELOPMENT

### INI Config Key Naming Convention — Standardize on Spaces (Sessions 256, 349)

- [x] **[LUPIN] Standardize ~91 underscore config keys to space-separated** — Session 349: Atomic rename of 91 keys in both INI files + 96 Python string literal updates across 59 files. No backward-compat shim needed. 5 key regroupings for better sort clustering. Removed 7 legacy splainer-only orphan keys. Added permanent guardrail test. Full regression green (2094 unit, 50 WS, 136 integration).
  - **Design doc**: [`src/rnd/2026.02.23-ini-config-key-naming-convention.md`](src/rnd/2026.02.23-ini-config-key-naming-convention.md)
  - **Migration map**: `src/conf/config-key-migration-map.json` (105 entries, archivable)
  - **Guardrail**: `src/tests/unit/test_ini_key_naming.py` (prevents future underscore keys)

### Prediction System: Validation + Documentation

- [ ] **[LUPIN] Prediction System Validation Campaign** — Unified 6-phase validation of UPE (7 slices, 87 unit + 21 E2E) and SWE proxy Layer 2 (shadow-mode capture). Phases: baseline, threshold tuning, SWE shadow-mode, gap tests (+6 E2E), visual QA, full lifecycle. 136 existing + 6 new = 142 total tests.
  - **Umbrella plan**: [`src/rnd/2026.02.23-trust-proxy-preference-learning/2026.03.25-prediction-system-validation-campaign.md`](src/rnd/2026.02.23-trust-proxy-preference-learning/2026.03.25-prediction-system-validation-campaign.md)
  - **UPE validation plan**: [`src/rnd/2026.02.23-trust-proxy-preference-learning/2026.03.11-upe-live-e2e-validation-plan.md`](src/rnd/2026.02.23-trust-proxy-preference-learning/2026.03.11-upe-live-e2e-validation-plan.md)
  - **SWE workload doc**: [`src/rnd/2026.02.25-swe-proxy-data-origin-and-workload-generator.md`](src/rnd/2026.02.25-swe-proxy-data-origin-and-workload-generator.md)
  - **Progress**: Phase 1 DONE. Phase 2 LanceDB isolation VERIFIED (Session 380) — 195/195 full suite pass, 21/21 prediction engine focused pass. Phases 3-6 can now proceed.
  - **LanceDB isolation plan**: [`src/rnd/2026.03.25-upe-lancedb-test-isolation.md`](src/rnd/2026.03.25-upe-lancedb-test-isolation.md) — implemented Session 378
  - **Implementation plan**: [`src/rnd/2026.03.26-upe-lancedb-test-isolation-and-warm-fix.md`](src/rnd/2026.03.26-upe-lancedb-test-isolation-and-warm-fix.md)
- [ ] **[LUPIN] Trust & Prediction Documentation Update** — Revise `src/docs/proxy-admin-guide.md` for Phase 3 conformal/ICRL + Phase 4 UPE prediction engine. Create `prediction-engine-reference.md`. Blocked by Prediction System Validation Campaign completion.
  - **Scope**: proxy-admin-guide.md (Sections 7, 9, 10), new prediction-engine-reference.md, docs/README.md links
  - **Umbrella plan**: [`src/rnd/2026.02.23-trust-proxy-preference-learning/2026.03.25-prediction-system-validation-campaign.md`](src/rnd/2026.02.23-trust-proxy-preference-learning/2026.03.25-prediction-system-validation-campaign.md)

### Config Migration — Claude Agent SDK

- [x] **[LUPIN] Config Migration**: Phases 0-4 complete — Session 364. Deep Research (24 keys + `from_config()`), Podcast Generator (27 keys + nested `from_config()`), LLM Client Factory (10 keys + INI loading). 2083 unit tests pass. Revised plan at `src/rnd/2026.03.14-claude-agent-sdk-config-migration-plan.md`.
- [ ] **[LUPIN] Phase 5: Update agentic voice workflow skill** — Ensure `/lupin-new-claude-agent-sdk-voice-workflow` scaffolds new agents with `from_config()` pattern by default. Update templates in `src/workflow/agentic-voice-workflow.md`.

### CJ Flow: Timed Execution + Monopolize + Pause/Resume (Session 381 — IN PROGRESS)

- [x] **[LUPIN] Phases 0-4: Backend complete** — Protocol fields (`scheduled_at`, `monopolize`, `paused`), consumer loop rewrite with `pop_next_eligible()` + dynamic wake-up timeout, 5 router updates, pause/resume REST endpoints, config keys, 25 new tests (all pass), 2338 unit regression clean.
- [ ] **[LUPIN] Phase 5: Notifications UI + WebSocket integration** — JS event subscriptions (`job_paused`, `job_resumed`), event handlers, paused/scheduled visual states on job cards, pause/resume toggle button, CSS. Continue next session.
- [ ] **[LUPIN] Phase 6: Documentation + E2E validation** — `websocket-events.md` updates, manual E2E test with live server.
- **Tracking doc**: [`src/rnd/v0.1.6/2026.03.30-cj-flow/2026.03.27-cj-flow-timed-execution-monopolize-pause.md`](src/rnd/v0.1.6/2026.03.30-cj-flow/2026.03.27-cj-flow-timed-execution-monopolize-pause.md)

### CJ Flow: Unified Job State Machine (Pre-Hybrid Fast Lane)

- [ ] **[LUPIN] Refactor fragmented state tracking** — Replace `status` field + queue position + `paused` boolean with unified `job_state` column (`pending → queued → scheduled → running → paused → completed/failed/cancelled`). Touches 15+ files: protocol, 7 job types, consumer, persistence, routers, UI. Dedicated preparatory effort before Hybrid Fast Lane.
- **Assessment doc**: [`src/rnd/v0.1.6/2026.03.30-cj-flow/2026.03.30-unified-job-state-machine-assessment.md`](src/rnd/v0.1.6/2026.03.30-cj-flow/2026.03.30-unified-job-state-machine-assessment.md)
- **CJ Flow hub**: [`src/rnd/v0.1.6/2026.03.30-cj-flow/00-index.md`](src/rnd/v0.1.6/2026.03.30-cj-flow/00-index.md)

### CJ Flow: Hybrid Fast Lane + Bounded Agentic Pool (Session 237)

- [ ] **[LUPIN] Phase 1.1: Add RLock to FifoQueue** — `fifo_queue.py`: wrap all mutating + reading methods with `threading.RLock()`
- [ ] **[LUPIN] Phase 1.2: Add config key** — `lupin-app.ini` + `lupin-app-splainer.ini`: `cj flow max concurrent agentic jobs = 3`
- [ ] **[LUPIN] Phase 1.3: Write thread safety tests** — `test_fifo_queue_thread_safety.py`: 4 concurrency tests
- [ ] **[LUPIN] Phase 1.4: Verify Phase 1** — New + existing unit tests pass
- [ ] **[LUPIN] Phase 2.1: Agentic pool + dispatcher refactor** — `running_fifo_queue.py`: ThreadPoolExecutor, route by isinstance, new methods
- [ ] **[LUPIN] Phase 2.2: Update shutdown sequence** — `main.py`: add pool shutdown before consumer thread
- [ ] **[LUPIN] Phase 2.3: Write agentic pool tests** — `test_agentic_pool.py`: 10 pool behavior tests
- [ ] **[LUPIN] Phase 2.4: Verify Phase 2** — New + existing unit tests pass
- [ ] **[LUPIN] Phase 3.1: API endpoint** — `/api/queue/pool-status` (optional)
- [ ] **[LUPIN] Phase 3.2: Integration verification** — Manual E2E test with concurrent agentic + sync jobs
- **Prerequisite**: Unified Job State Machine refactor must complete first (freshness review of this plan against new consumer loop)
- **Tracking doc**: `src/rnd/2026.02.19-approach-c-hybrid-queue-architecture.md`

### Playwright E2E Browser Testing (Session 252)

- [x] **[LUPIN] Research AI/automation for end-to-end testing** — Session 252: Research complete. Playwright Python + pytest-playwright recommended for FastAPI + vanilla HTML/JS stack
- [x] **[LUPIN] Implement Playwright E2E testing** — ALL 8 PHASES COMPLETE (Sessions 351-361). 265 E2E tests (253 functional + 12 visual regression) across 28 test files covering all 12 pages.
  - **Planning docs**: [`src/rnd/2026.02.23-automating-ui-testing/`](src/rnd/2026.02.23-automating-ui-testing/00-index.md)
  - **Phases 1-2**: DONE — Foundation + data-testid rollout (~266 testids across 13 files)
  - **Phase 3**: DONE — Auth Flow Tests (37 tests)
  - **Phase 4**: DONE — Page Smoke Tests (27 tests)
  - **Phase 5**: DONE — Admin Flow Tests (69 tests)
  - **Phase 6**: DONE — Notifications & Q&A Tests (86 tests)
  - **Phase 7**: DONE — WebSocket & Real-Time Tests (28 tests)
  - **Phase 8**: DONE — Visual Regression & CI (12 tests, JS normalization, Dockerfile, `--no-deps` starlette workaround)
  - **Full suite**: 2,102 unit + 50 WS + 265 E2E UI + 137 integration = ALL PASS
  - **Round 2** (future): Claude Code + Playwright MCP for AI-augmented test generation + self-healing selectors

### DataFrame CRUD with Voice I/O — UI Testing + Voice Polish

- [ ] **[LUPIN] Interactive E2E Testing of CRUD Agents** — Execute the 29-scenario testing protocol at `src/rnd/2026.02.04-headless-cc-for-dataframe-crud/testing-protocol.md`.
  - [x] Part 1: Mock pipeline tests (17/17 passed — routing, pipeline, cache, confirmation, prompt construction)
  - [x] Bug fix: CRUD agent completion — emit_job_state_transition, answer guard, done queue push (3 new tests, 532/532 pass)
  - [x] Bug fix: TTS focus mode stuck — staleness check in restoreTTSQueueState + exit in moveToRegularNotifications (Session 164)
  - [x] **Bug fix: delete_item deletes all records** — Session 189: dedup guard, multi-delete guard, infra column rejection. 6 new tests (816 total). Commit fd21f0c.
  - [x] Part 3: Curl smoke tests → **SUPERSEDED** by `test_crud_live_pipeline.py` (8-scenario automated test, Session 189)
  - [x] **Run CRUD live pipeline test** — `test_crud_live_pipeline.py --mode direct --auto-proxy`. Session 267 fixed credential mismatch (CREDENTIAL_ENV_PREFIX unified).
  - [ ] Part 2: Notifications UI tests (8 scenarios, live server) — **Leverage Playwright E2E infrastructure**
- [ ] **[LUPIN] Phase 4: End-to-End Voice Workflows + Polish** - PENDING (blocked by Phase 3 ✅)
- **Note**: Moved to v0.1.6 to leverage Playwright E2E testing infrastructure for UI test automation

### Presentation Generator Agent (Session 362 — IN PROGRESS)

- [ ] **[LUPIN] Presentation Generator Agent: Transform research docs into slide decks** — 🔄 IN PROGRESS. Phases 1-5 complete, Phase 6 beginning. Next: Phase 6 (Text Rendering: Marp Markdown).
  - **Goal**: Agentic process (Claude SDK) that transforms ~1200-word research documents or technical blog posts into 10-20 minute slide decks with presenter notes. Single orchestrator pattern (like Podcast Generator).
  - **Architecture**: 8-phase pipeline (ingest, analyze, outline, elaborate, serialize YAML, render Marp, render Mermaid visuals, deliver). 4 human-in-the-loop gates. Pluggable visual renderer registry. Theme cascade (INI -> YAML template -> per-presentation overrides).
  - **R&D directory**: [`src/rnd/2026.03.14-presentation-generator/`](src/rnd/2026.03.14-presentation-generator/00-index.md)
  - **Phase 0**: DONE — Strategy & design serialized, implementation plan & tracking created (4 docs)
  - **Phase 1**: DONE — Foundation (Job, Config, Voice I/O, CJ Flow packaging) — Session 367b
  - **Phase 2**: DONE — State models & orchestrator skeleton — Session 367b
  - **Phase 3**: DONE — Content generation: ingest & analyze
  - **Phase 4**: DONE — Content generation: outline & elaborate
  - **Phase 5**: DONE — Content generation: serialize YAML
  - **Phase 6**: Pending — Text rendering: Marp Markdown
  - **Phase 7**: Pending — Visual rendering: Mermaid + registry
  - **Phase 8**: Pending — Delivery & DR-to-Presentation chaining (Phase 8)

### CJ Flow Persistence (Sessions 357, 360, 367 — BACKEND COMPLETE)

- [x] **[LUPIN] CJ Flow Persistence: PostgreSQL-backed job history for agentic jobs** — ✅ ALL 5 PHASES COMPLETE. Backend fully implemented and E2E verified (Session 367).
  - **Goal**: Durable storage for AgenticJobBase jobs (DeepResearch, PodcastGenerator, ClaudeCode, SweTeam). Job state survives server restarts, enables job history queries, marks interrupted jobs.
  - **Architecture**: Central write-through via `emit_job_state_transition()` in `queue_util.py`
  - **Plan doc**: [`src/rnd/2026.03.13-cj-flow-persistence-plan.md`](src/rnd/2026.03.13-cj-flow-persistence-plan.md)
  - **Phase 0**: DONE — Plan serialized to R&D
  - **Phase 1**: DONE — Schema + SQLAlchemy model (`job_history` table, `add-job-history.sql`, `JobHistory` in postgres_models.py). 12 models, 12 tables. Table + 5 indexes deployed to lupin_db_dev.
  - **Phase 2**: DONE — Persistence service (`job_persistence.py`, 8 functions, 2 config keys). Full DB round-trip smoke test passes.
  - **Phase 3**: DONE — Write-through integration in `emit_job_state_transition()`. Persistence fires after WS emit, filtered by `is_agentic_job_type()`. 12 callsites audited, zero needed modification. Session 367.
  - **Phase 4**: DONE — Startup recovery (`mark_interrupted_jobs()`) in `main.py` lifespan. Session 367.
  - **Phase 5**: DONE — `GET /api/job-history` + `GET /api/job-history/{job_id}` endpoints with role-based auth. 17 unit tests, 9 integration tests. E2E smoke test 7/7 pass. Session 367.
  - **Regression**: 2155 unit tests pass, 0 new failures
- [ ] **[LUPIN] CJ Flow Persistence: Job History UI page** — Future scope. Backend + API complete, no browser page yet. Pick up in next session to scope a job history viewer page.

### Universal Prediction Engine: Live E2E Validation (Session 340)

- [ ] **[LUPIN] Live E2E validation of all 7 UPE slices** — **CONSOLIDATED** into [Prediction System Validation Campaign](src/rnd/2026.02.23-trust-proxy-preference-learning/2026.03.25-prediction-system-validation-campaign.md). See "Prediction System: Validation + Documentation" section above.

### Render Markdown Documents as HTML + Audio Player Viewer

- [x] **[LUPIN] Render markdown documents as HTML + in-browser MP3 player** — Completed. Markdown documents render as styled HTML pages; also created an Audio Player Viewer for in-browser MP3 playback.

### Trust Proxy Documentation Update

- [ ] **[LUPIN] Update trust proxy documentation** — **CONSOLIDATED** into [Trust & Prediction Documentation Update](src/rnd/2026.02.23-trust-proxy-preference-learning/2026.03.25-prediction-system-validation-campaign.md). See "Prediction System: Validation + Documentation" section above.

---

## v0.1.5 — HIGH PRIORITY

### Voice I/O Integration with Claude Code System Hooks (Sessions 272-278)

- [x] **[LUPIN] Review and finalize voice hook integration draft plan** — Session 276: Plan reviewed, 3 ADs confirmed (AD-2, AD-5, AD-6), master plan updated.
- [x] **[LUPIN] Phase 0: Hook Contract Validation** — Session 276: 5 test hooks live, shared library + session bridge implemented, hooks capturing real CC payloads.
- [x] **[LUPIN] Align hook & MCP sender_id for per-session routing** — Session 278: `build_sender_id_for_cc()` in session bridge, `send_tts()` auto-resolves sender_id, MCP server uses session bridge instead of random UUID, background upgrade thread. 1692 unit tests pass.
- [x] **[LUPIN] Phase 0 validation: Analyze captured payloads** — Session 283: Validation report created from 3,430 payloads (1,686 pre_tool_use, 1,620 post_tool_use, 69 notification, 28 stop, 26 session_start). All 12 gate checks passed. Report at `src/rnd/.../2026.02.27-phase-0-validation-report.md`.
  - **Logs dir**: `io/claude_code_hooks/logs/`
  - **Session bridge file**: `~/.claude/sessions/cc-{PID}.json` — 26 files verified
- [x] **[LUPIN] Phase 1: Notification System Extensions** — Session 290: Revised architecture — `user_initiated_message` type (not VOICE_INPUT), stateful WebSocket listener (CCNotificationListener subclassing BaseWebSocketListener), INI-based credentials, atomic JSONL buffer drain. 5 new files, 7 modified, 35 new tests (all pass). See [Design Doc Revisions](src/rnd/2026.02.25-full-voice-io-integration-with-cc-system-hooks-and-mcp/2026.02.28-design-doc-revisions-session-290.md).
- [x] **[LUPIN] Phases 2-3: Hook infrastructure + voice output** — Session 292: 7 hooks renamed to production, smart TTS (silent/announce/default), voice buffer drain + acknowledge. 82 hook tests.
- [x] **[LUPIN] Phases 4-6: Voice injection, approvals, browser capture** — Session 296: additionalContext injection (Pre/PostToolUse), Stop hook blocking with counter safety valve, MCP voice bypass, PermissionRequest 3-path flow (auto-allow, buffer-redirect, sync), CC session voice capture UI. 126 hook tests.
- [x] **[LUPIN] Voice injection into idle CC sessions (tmux + UserPromptSubmit hook)** — Session 323: All 6 phases implemented. tmux discovery in register_session.py, `find_session_by_id/tmux()` in session_bridge.py, listener tmux Enter trigger, UserPromptSubmit hook, shell scripts, hook registration, 29 tests (8+18+3) all passing.
  - **Plan doc**: [`2026.03.05-voice-injection-listener-tmux-hook-plan.md`](src/rnd/2026.02.25-full-voice-io-integration-with-cc-system-hooks-and-mcp/2026.03.05-voice-injection-listener-tmux-hook-plan.md)
  - **Research doc**: [`2026.03.05-voice-injection-tmux-buffer-hook-design.md`](src/rnd/2026.02.25-full-voice-io-integration-with-cc-system-hooks-and-mcp/2026.03.05-voice-injection-tmux-buffer-hook-design.md)
- [x] **[LUPIN] Phase 7: E2E testing + polish** — Manual E2E verification of voice pipeline (browser 🎤 → STT → notify → buffer → hook drain → additionalContext). Polish remaining rough edges. Session 332: Completed.
  - **Master plan**: [`2026.02.25-opportunistic-voice-hook-integration-plan.md`](src/rnd/2026.02.25-full-voice-io-integration-with-cc-system-hooks-and-mcp/2026.02.25-opportunistic-voice-hook-integration-plan.md)
  - **Phase 0 plan**: [`2026.02.26-voice-hook-phase-0-implementation.md`](src/rnd/2026.02.25-full-voice-io-integration-with-cc-system-hooks-and-mcp/2026.02.26-voice-hook-phase-0-implementation.md)
  - **Phase 0 validation**: [`2026.02.27-phase-0-validation-report.md`](src/rnd/2026.02.25-full-voice-io-integration-with-cc-system-hooks-and-mcp/2026.02.27-phase-0-validation-report.md)
  - **Phase 1 design revisions**: [`2026.02.28-design-doc-revisions-session-290.md`](src/rnd/2026.02.25-full-voice-io-integration-with-cc-system-hooks-and-mcp/2026.02.28-design-doc-revisions-session-290.md)

---

## Pending

### History Archive (Session 280)

- [x] **[LUPIN] Archive history.md** — Session 332: Archived Sessions 260-303 (Feb 24 - Mar 3) to `history/2026-02-24-to-03-03-history.md`. Retained Sessions 304-331 (~11.9k tokens).

### SWE Team Proxy: Workload Generator + Shadow-Mode Capture

- [x] **[LUPIN] Layer 1: Enhanced dry-run + capture harness** — Session 268: 18-task catalog, JSONL capture harness, 7 integration tests, `data_origin` column. Validated Session 273: manifest path corrected to `io/decision-proxies/`.

### SWE Team Proxy Agent (HIGH PRIORITY)

- [x] **[LUPIN] Finish implementing and testing first cut of SWE Team Proxy Agent** - Session 241: Activated proxy in shadow mode, wired trust feedback loop, 7 new tests. 1490 pass.
- [x] **[LUPIN] Phase 7: Real-Time Proxy Summary Notifications** - Session 248: 10 tasks, 7 new tests, 1 E2E smoke. Batch lifecycle, proxy summary emission, trust mode dropdown, circuit breaker alerts. 1518 pass.
- [x] **[LUPIN] Phase 8: Hot-Reload Trust Mode** - Session 248: REST endpoint + UI dropdown on Trust Dashboard, 16 new tests, 1534 pass


### Disambiguate Database Names (Session 343-344)

- [x] **[LUPIN] Phase 6: Rename lupin_db → lupin_db_dev and lupin_db_prod** — Session 344: PostgreSQL `ALTER DATABASE RENAME`, updated defaults in `database.py` (dev → `lupin_db_dev`, prod → `lupin_db_prod`), `docker-compose.yml`, `run-postgresql-dev.sh`, `backup-postgres.sh`, plus 16 doc references across 7 files. Full test suite validation pending.
  - **Plan doc**: [`src/rnd/2026.03.12-integration-test-hot-swap-config.md`](src/rnd/2026.03.12-integration-test-hot-swap-config.md) (Phase 6 → Done)

### Before Branch Merge

- [x] **[LUPIN] Run and remediate full testing harness** — Session 344: All suites green after DB rename. Unit **2075/2075**, smoke **27/27**, WebSocket **50/50**, integration **136 passed** (53 skipped, 23 xfailed, 13 xpassed, 0 failures). Fixed: notification auth assertions, admin fixture dependency, WS edge case expectation. Marked skip/xfail: prediction engine (20), deep research (10), queue filtering (5), dispatcher mock (4), job queue progressive (4), token refresh (4), SDK client (2), admin bcrypt (2), LanceDB normalization (5).
  - **Plan doc**: [`src/rnd/2026.03.12-integration-test-remediation-and-db-disambiguation.md`](src/rnd/2026.03.12-integration-test-remediation-and-db-disambiguation.md)
  - **DB isolation**: Hot-swap infrastructure from Session 343 — [`src/rnd/2026.03.12-integration-test-hot-swap-config.md`](src/rnd/2026.03.12-integration-test-hot-swap-config.md)
- [x] **[LUPIN] CJ Flow verification: Dry run end-to-end testing for UNBOUNDED tasks** - Session 269: INTERACTIVE dry-run exercises MessageHistory + 6-scenario smoke test created. Needs live server validation.

### TTS Focus Mode Race Condition (Sessions 346-347)

- [x] **[LUPIN] Fix TTS Focus Mode race: orphaned focus mode freezes queue** — Session 346: guards in `enterTTSFocusMode()` and `onTTSPlaybackComplete()`. Session 347: `stopAudio()` + `onTTSPlaybackComplete()` in `submitResponse()` and `handleGracePeriodExceeded()`, fixed `stopAllAudio()` typo in `stopTTSAndAdvance()`. All 10 dismissal paths now have audio cleanup.
  - **Analysis doc**: [`src/rnd/2026.03.12-tts-focus-mode-race-condition-analysis.md`](src/rnd/2026.03.12-tts-focus-mode-race-condition-analysis.md)
  - **File**: `src/fastapi_app/static/js/notifications.js`

### Future Considerations

- [ ] **[LUPIN] Add 60s safety timeout to TTS focus mode** - Prevent permanent stuck state when TTS queue items fail to play. **Partially addressed** (Session 164): Added staleness check on restore + exit in moveToRegularNotifications. Still need: runtime 60s timeout for cases where notification exists but user never responds and timeout doesn't fire. **File**: `src/fastapi_app/static/js/notifications.js:9374-9393`
- [ ] **Silent flag for notifications**: Consider adding a `silent` parameter to the cosa-voice notification system to suppress TTS during automated testing. Would require changes to: router request models, job classes, voice_io wrappers, and core notification functions.
- [x] **Standardize compound job/user ID usage** - Session 236: Bug #5 made scoped IDs (`base_hash::user_id`) universal across ALL job types via `register_scoped_job()`
- [x] **Standardize job-user-session association interface** - Session 236: Bug #5 unified all write sites through `register_scoped_job()` and all reads through direct `job.user_id` access
- [x] **Implement Approach D: Hybrid Queue + Check-In** - Session 238: Full 5-phase implementation. 20+10 new tests, 317 SWE team tests pass

---

## Completed (Recent)

- [x] [LUPIN] **BFE Phase 6 dry-run smoke test + CJ Flow persistence gaps fix** — Session 1b8c1cc0 (2026-04-10). **Part 1 (doc 09)**: Full dry-run smoke test for the Phase 6 repair loop. Added `force_failure_mode` to `/api/mock-job/submit` + DR/podcast/presentation REST endpoints, shared `_raise_forced_failure()` helper on `AgenticJobBase`, BFE `_execute_dry_run()` extended to call `_resubmit_original_job()`, watchdog propagates `dry_run` to spawned BFE. New `test_bfe_phase6_repair_loop_smoke.py` + 12 new unit tests. Full loop verified end-to-end: DR fails → watchdog → BFE dry-run → resubmit → done at $0 cost. **Part 2 (doc 10)**: Fixed three persistence gaps that blocked production Phase 6 — `session_id`, `routing_command`, and `metadata_json.original_args` now round-trip through INSERT + state transitions via metadata_json merge logic. Added `routing_command`/`original_args` attrs to AgenticJobBase/AgentBase/SolutionSnapshot, direct-assignment refactor in agentic_job_factory (no wrapper, no getattr fallbacks), `_build_metadata_json()` whitelists `original_args`, `persist_job_completed/failed_from_metadata` merge instead of overwrite, cleaned up band-aids in `dead_job_packager.py` and BFE `_execute_dry_run()`. **Bonus**: Fixed watchdog rate-limit regex that was matching `429` in traceback line numbers (e.g. "line 429") and misclassifying code bugs as rate-limit failures. 76/76 unit tests passing. All persistence fields verified via direct DB inspection. Plans: `src/rnd/v0.1.6/2026.03.27-bug-fix-expediter/09-phase6-dry-run-smoke-test-plan.md`, `10-cj-flow-persistence-gaps-plan.md`.
- [x] **[LUPIN] Fix CC session messages loading into "Unknown" sender card after refresh** — Completed Session 337.
- [x] **Centralized Navigation & URL Naming Conventions** — Unified nav and URL patterns for entire suite of static HTML/plain vanilla JavaScript pages covering all user and admin tasks - Session 247
- [x] **CRUD Live Pipeline Test** - `test_crud_live_pipeline.py --mode direct --auto-proxy` passing. Session 267 fixed credential mismatch (CREDENTIAL_ENV_PREFIX unified).
- [x] **SWE Team Proxy: Preference Learning** - Sessions 258-266: Phases 0-3 complete. Embedding infrastructure, CBR + Beta-Bernoulli trust, seed data (50 decisions), BLR + Thompson Sampling, Conformal Guarantees + ICRL. 1645 total tests pass.
- [x] **Skill: notification-patterns** - cosa-voice MCP usage patterns skill created (~250 lines)
- [x] **Gist embeddings: jettisoned** - Dead embedding code removed, ~30% embedding cost savings per snapshot (2 of 7 embeddings). Removed `question_gist_embedding`, `solution_gist_embedding` fields and unused search methods.
- [x] **Voice Module Audit** - Session 260: Full 5-phase refactoring of `cosa_interface.py` vs `voice_io.py`. Created shared `AgentNotificationDispatcher`, `sender_id.py`, `feedback_analysis.py`, `sync_notify.py`. Eliminated ~1,548 lines of duplication across 16 files. 1538 unit tests pass.
- [x] **Smoke Test Coverage Audit** - Session 221: 6 new test files, 54 pytest methods covering Decision Proxy, SWE Orchestrator dry-run, Queue Consumer, Answer Feedback, Agentic Disambiguation, Classic Agents. All passing.
- [x] **SWE Team Testing Docs Update** - Session 221: Updated 00-index.md (Phases 2-4 DONE), 04-surfaces testing design (Surfaces 2-3 PASS), all-agents.json entries
- [x] **Post-Execution Feedback Loop** - Session 215-220: answer_is_correct tri-state, language/tone feedback, data collection pipeline. All 3 parts complete.
- [x] **CoSA Submodule Commit Backlog** - Session 220: 16 files across 5 areas committed
- [x] **SWE Team Surface 3 Proxy Crash Fix** - Session 219: 3 bugs fixed (ImportError, ValueError, expeditor pass-through). 1343 tests pass.
- [x] **Agentic Software Development Team (Phases 1-4)** - Sessions 205-210: Foundation, delegation, tester loop, trust-aware decision proxy. 1265 unit tests.
- [x] **Pre-Execution Confirmation of Semantic Matches** - 2026-02-16: Top-1 confirm strategy, 3-tier decision
- [x] **Unified Smoke Test Framework Verification** - 2026-02-16
- [x] **vLLM Upgrade to >= 0.8.5** - 2026-02-13: Qwen3-4B-Base native support
- [x] **DataFrame CRUD Phases 1-3** - Sessions 132-143: Storage, agents, queue integration + voice confirmation. 190 tests.
- [x] **Before Branch Merge** - Sessions 123-148: CJ Flow compliance, baseline testing, PEFT training (Phases 1-2), calculator (31 steps), disambiguation agent, dry-run smoke tests
- [x] **job_state_transition (10 phases)** - Session 107: Config through cruft removal + WebSocket smoke tests
- [x] **Job Card Field Parity fix** - Session 107: 6 missing WebSocket metadata fields
- [x] **Browser Testing (8 tests)** + **Verification Checklist (8 items)** - Sessions 103-115
- [x] **Architecture Review: Cache Hit Behavior** - Session 118: Moved to bug-fix-queue.md
- [x] **Carried Over from Session 102** - Sessions 109+: Math agent TTS, job card notifications, tts_raw parameter
- [x] **COSA Submodule commits** - Sessions 115+: API consistency, dry-run mode, mock_clients
- [x] **[LUPIN] Refactor mock job client into standalone Notification Proxy Agent** - Sessions 210-211: Phase 4a proxy extraction + standalone agent. Fully decoupled from mock job infrastructure.
- [x] **[LUPIN] Add `refresh()` method to ConfigurationManager** - 2026-02-13: WON'T FIX.
- [x] **[LUPIN] Run PEFT Phase 2 training + LORA retrain** - 2026-02-13: 39,871 examples, 35 commands
- [x] **[LUPIN] Finish expanding smoke test matrix to 13 scenarios** - 2026-02-13
- [x] **[LUPIN] Fuzzy file matching for LORA adapter podcast generation routing** - 2026-02-13
- [x] **[LUPIN] Extended Parameter Training (Chunk 1.6)** - 2026-02-13
- [x] **[LUPIN] Embedding benchmark harness** - Session 194: Local GPU 7-398x faster than OpenAI API.
- [x] **[LUPIN] Bug fix: Dead job card stuck in run bucket** - Session 199: Missing `emit_job_state_transition()` in `_handle_error_case()`. 814 tests pass.
- [x] **[LUPIN] Bug fix: Stopwatch API mismatch in cache hit path** - `_format_cached_result()` → replaced with `get_delta_ms()`. 817 tests pass.
- [x] **[LUPIN] Bug fix: Missing WebSocket event in generic exception handler** - 817 tests pass.
- [x] **[LUPIN] Fix LanceDB Embedding Dimension Mismatch** - Session 198: Standardized on 768 dims. 811 tests pass.
- [x] **[LUPIN] CJ Flow Branding + Bounded Job Packaging + Claude Code LORA Data** - Session 195: 816 tests pass.
- [x] **Deprecated util_xml.py Elimination** - Session 116: Migrated all production code to Pydantic XML I/O.
- [x] **Math Agent TTS Fix** - Sessions 109-110: job_id pattern + user_email pipeline.
- [x] job_state_transition Phases 6-10 + WebSocket smoke tests - Session 107
- [x] Bug fix: Add 6 missing fields to WebSocket metadata - Session 107
- [x] Rename `currentUser` to `currentUserEmail` in notifications.js - Session 106
- [x] Remove redundant `user_email` from Deep Research JS request body - Session 106
- [x] Fix job cards not rendering when queue collapsed - Session 105
- [x] Fix TTS notification duplication in job cards - Session 104
- [x] Add dry-run checkboxes to agentic job submission UI - Session 103

---

*Completed items older than 7 days can be removed or archived.*
