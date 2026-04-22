# Plan: Post-TFE-Validation Cleanup

## Context

TFE job `aj-225d4df2` completed. Headline numbers vs. last night:

| Metric | Last night | This run |
|---|---|---|
| Clusters | 8 | 8 |
| **Proposed** | **0** | **19** |
| Selected | 0 | 0 |
| Fixed | 0 | 0 |

The SDK credentials mount fix is validated end-to-end: Phase 1 (Diagnose) produced real diagnoses for all 8 clusters and Phase 2 (Propose) produced 19 ranked fix proposals across them. 0 selected + 0 fixed is the *correct* behavior for an unattended run — voice gate is a human gate and nobody answered it.

**Major secondary finding**: by reading the actual Phase 3/5/6 methods we discovered that the orchestrator docstring at `src/cosa/agents/test_fix_expediter/orchestrator.py:4-10` is **fully stale** — Phases 3 (Fix), 5 (Git), and 6 (Rerun) are all **REAL**, not stubs. They delegate to the shared `FixExecutor`, `GitStrategist.commit_and_pr_multi()`, and `create_agentic_job()` for a validation rerun respectively. So TFE is end-to-end capable right now, given a human-selected subset of proposals. No "hand-off to BFE" is needed or expected — BFE fixes failed *jobs* (dead queue), TFE fixes failed *tests*; they're parallel pipelines, not chained.

## Bugs to fix in this plan

### Bug 1 — `/api/io/file` 404 on relative `io/...` paths

**Repro**: TFE report at `io/swe-team/reports/…-test_fix_expediter-report.md` line 129 links to `io/test-suite/2026.04.15-at-00:56-EDT-all-remediation.json`. Browser fetch returns 404.

**Root cause**: `src/cosa/rest/routers/io_files.py:88-93` strips an absolute `/var/lupin/io/` prefix and a leading `/`, but does not strip a relative `io/` prefix. The join becomes `/var/lupin/io/` + `io/test-suite/…` = `/var/lupin/io/io/test-suite/…` which doesn't exist.

**Fix** (1 line): after line 93, add:
```python
elif decoded_path.startswith( "io/" ):
    decoded_path = decoded_path[ 3: ]
```
So the condition order is: absolute `io_base` prefix → leading `/` → leading `io/`.

**Verification**: `curl -sf "http://localhost:8000/api/io/file?path=io/test-suite/2026.04.15-at-00:56-EDT-all-remediation.json" | head -c 200` returns the JSON; report link in browser renders the file.

### Bug 2 — Same completed job appears in both Done and History panels

**What the user observed**: one TFE job card visible in both `/api/get-queue/done` (in-memory FifoQueue) and `/api/job-history` (Postgres).

**Design intent** (from `src/fastapi_app/static/js/notifications.js:5973-5984`): the history panel is supposed to pass `exclude_ids` to `/api/job-history` containing all live-queue job ids so it never re-renders a job already shown in Done/Dead. A single job should appear in **exactly one** panel at a time.

**Likely failure modes** (one of these is true — need to determine which):
a. Frontend isn't passing `exclude_ids` for this code path.
b. Frontend passes `exclude_ids` but the `/api/job-history` router ignores or mis-parses the parameter.
c. The `id_hash` on the Done side (e.g. `aj-225d4df2::50c73ba7-…`) doesn't byte-match the `id_hash` stored in `job_history` (e.g. due to scoped-id suffix differences), so the exclude filter never matches.

**Investigation step** before fixing: capture the `/api/job-history` request headers + query string from the browser devtools when the duplication is visible, then compare the Done-queue `id_hash` format to the history-row `id_hash` format. The replay we just did makes (c) the strongest hypothesis — `aj-225d4df2::50c73ba7-…` is the scoped form; if either side stores the bare `aj-225d4df2`, the compare fails.

**Fix locus**: whichever of the three above turns out to be true. If (c), the canonical fix is to normalize id_hash comparisons to the base id on both sides (strip the `::user_id` suffix).

**Verification**: reload the queue panel with the TFE job present and confirm it appears in exactly one of Done / History.

### Bug 3 — Voice gate fires at priority="medium", so no TTS alert

**What the user experienced**: the TFE run produced 19 proposals and "asked" for selection, but the user heard nothing. Per CLAUDE.md, all blocking voice requests MUST use `priority="high"` for TTS to reach the user.

**Root cause** (verified by reading the chain):
1. `orchestrator.py:1002` calls `cosa_interface.present_choices(questions, timeout, title, abstract, job_id)` — no `priority` arg.
2. `bug_fix_expediter/cosa_interface.py:151` (which TFE delegates to via `test_fix_expediter/cosa_interface.py:58`) also has no `priority` parameter.
3. `agent_notification_dispatcher.py:288-326` `present_choices` signature accepts no `priority`; line 318 hardcodes `priority=NotificationPriority(self.default_priority)`.
4. The SWE dispatcher is constructed at `bug_fix_expediter/cosa_interface.py:42` as `AgentNotificationDispatcher(agent_type=AGENT_TYPE)` with **no `default_priority`**, so the constructor default `"medium"` (line 63) wins.

**Fix** (two changes, both in CoSA — user commits from inside the submodule):
- `agent_notification_dispatcher.py:288`: add `priority: str = None` parameter; line 318 becomes `priority = NotificationPriority(priority or "high")` for the `present_choices`, `ask_confirmation`, and `get_feedback` paths (they're all blocking and should all default to high).
- `bug_fix_expediter/cosa_interface.py:42`: change to `AgentNotificationDispatcher(agent_type=AGENT_TYPE, default_priority="high")`. Belt-and-suspenders for any call path that doesn't pass an explicit priority.

**Verification**: trigger a voice gate on the test server, confirm the TTS alert fires audibly and the UI notification header carries the high-priority badge.

### Bug 4 — TFE feedback timeout is 3 seconds in the test container

**Locus**: `docker-compose.yml:108` sets `TFE_FEEDBACK_TIMEOUT_SECONDS_OVERRIDE: "3"` on `lupin-rest-test`. That env var is consumed by `src/cosa/agents/test_fix_expediter/config.py:147-154` and overrides `feedback_timeout_seconds` unconditionally.

**Why it exists**: likely a fast-feedback setting for automated/dry-run tests where the proxy auto-answers.

**Why it's biting us now**: today's run was a *live* TFE (dry_run=false), but the env var applies regardless. 3 seconds is way too short for a human to receive TTS + open the UI + click options.

**Recommended fix**:
- Remove `TFE_FEEDBACK_TIMEOUT_SECONDS_OVERRIDE: "3"` from the test container's compose block.
- Keep the override mechanism itself — it's useful for the proxy-auto-answer path — but invert the default: env var unset = real value from `lupin-app.ini` (currently 180s or whatever the config block sets). Tests that want the fast path set the env var explicitly in their runner script, not in the always-on container env.

**Alternative**: set the override to 600s (10 min) instead of 3s for the test container. Still short enough that automated proxy runs can time out, long enough for a human in the loop. Less correct architecturally but smaller diff.

### Bug 5 — Stale orchestrator docstring (observability)

`src/cosa/agents/test_fix_expediter/orchestrator.py:4-10` incorrectly claims Phases 2/3/5/6 are STUBs. They're all implemented. The stale docstring is what caused us to mis-diagnose last night's "0 proposed" as a stub rather than as an SDK auth failure.

**Fix**: rewrite those lines to reflect reality — all 7 phases (0-6, skipping 4) are REAL as of session 1cfcdf73+. Small diff, pure comment, but important because future debugging *will* read this first.

## TFE Resume Entry Point (exists) + Latent Phase-Skip Bug

**User can resume any stalled TFE today** (functionally):
- Command: `agent router go to test fix expediter resume` with `args.resume_from="<tfe-job-id>"`.
- Endpoint: `POST /api/test-fix-expediter/resume-from` (`src/cosa/rest/routers/queues.py:1610-1685`).
- Checkpoint is persisted automatically on stall at `job_history.metadata_json.artifacts["checkpoint"]`, including the full `state_snapshot` (clusters + diagnoses + proposed_fixes).
- Resolver accepts either a TFE job id (`tfe-7c25082a` or scoped form) or a plan path. No checkpoint path arg needed.

## Bug 7 — Stalled runs finish with `status="completed"` instead of `status="stalled"`

Today's `aj-225d4df2` has status `"completed"` in `job_history` despite 0 selected + voice-gate timeout. Root cause (likely): the 3s timeout returned MCP `exit_code=0` with empty `answers`, not `exit_code=2`. At `agent_notification_dispatcher.py:330-338`, `exit_code=0` with empty response falls through → `result.get("answers", {})` → `selected_labels = []` → no exception, orchestrator finalizes cleanly. `VoiceGateTimeoutError` → `StalledException` → `status="stalled"` never fires.

Net effect: the UI's pre-wired stalled badge (`notifications.js:6837` `isStalled = job.status === 'stalled'`) and resume button (`notifications.js:6940` `resume-stalled-btn`) are **correctly plumbed but never activate** because the job's status isn't `stalled`.

**Fix**: in the dispatcher `present_choices` response handling (`agent_notification_dispatcher.py:330-338`), treat empty `answers` payload on a multi-select gate as a timeout (raise `VoiceGateTimeoutError`), not as an explicit empty selection. Users don't "submit with nothing selected"; an empty response always means no-answer → checkpoint-stall. After Bug 4 lands, real timeouts will return `exit_code=2` anyway, but Bug 7's fix is still correct defensive normalization.

## Stalled UI last-mile (already plumbed)

Infrastructure is in place in `notifications.js`:
- Line 6837-6839: `isStalled` gate + `⏸` pause badge with tooltip.
- Line 6933: `.job-stalled-actions` DOM wrapper.
- Line 6940: `.resume-stalled-btn` button already rendered.
- Line 7159+: full resume handler.

No new UI components required — once Bug 7 lands (so `status="stalled"` actually reaches `job_history`), the badge and resume button will appear automatically on stalled cards in both Done and History panels.

**What to verify**:
1. Resume button click pulls the job's `id_hash` from the card and submits `POST /api/test-fix-expediter/resume-from` with `resume_from=<id>` — single click, no extra args from user. Read the click handler at `notifications.js:7159+` to confirm this is already wired.
2. Badge/button render identically in Done and History panels (both panels call the same `renderJobCard()`).
3. Label text clearly says "Stalled" (or "Paused" after Bug 8 below) so it's unambiguous to the user.

## Bug 8 — Pause/Stop/Stalled semantics

User wants three user-facing lifecycle states for a job awaiting voice input:
| State | How it happens | Resumable? | Current support |
|---|---|---|---|
| Stalled | Voice gate timed out — no human answer | Yes | `stall_reason="voice_gate_timeout"` exists |
| Paused | User explicitly said "pause" | Yes | **Missing** — needs new `stall_reason="user_pause"` |
| Stopped/Killed | User explicitly rejected | No (terminal) | `stall_reason="user_cancel"` exists |

All three share the checkpoint mechanism; they only differ in trigger + resumability.

**Fix approach**:
1. Add `"user_pause"` as a fourth legal value of `stall_reason` (state.py:240 docstring + any enum-ish validation).
2. Add a dedicated voice-gate button alongside the multi-select: "Pause (resume later)" → dispatcher raises a new `PauseRequested` exception → orchestrator catches it, saves checkpoint with `stall_reason="user_pause"`, job transitions to `status="paused"`.
3. Add similar "Stop" button → `stall_reason="user_cancel"`, `status="stopped"` (or keep `status="dead"` if that's the queue convention).
4. UI renders:
   - `status="stalled"` → `⏸` yellow badge + "Stalled" label + resume button
   - `status="paused"` → `⏸` blue badge + "Paused" label + resume button
   - `status="stopped"` → `✕` gray badge + "Stopped" label + *no* resume button
5. Resume endpoint accepts either `stalled` or `paused` jobs; rejects `stopped` with a 409.

**Latent bug — Bug 6**: the resume plumbing exists but the phase methods don't honor it. `load_checkpoint()` + `set_resume_phase(2)` populate state and mark the resume ordinal, but `run_phase0_cluster()` and `run_phase1_diagnose()` at `orchestrator.py:274` and `:304` don't check `self._resume_from_ordinal` before running. Net effect: resuming today's `aj-225d4df2` re-clusters and re-diagnoses (Opus cost again) before reaching Phase 2, instead of short-circuiting to the voice gate with the persisted 19 proposals.

**Fix**: at the top of `run_phase0_cluster`, `run_phase1_diagnose`, and `run_phase2_propose`, add a guard:
```python
if self._resume_from_ordinal is not None and self._resume_from_ordinal > <this_phase_ordinal>:
    return self.<stored_field>  # already rehydrated by load_checkpoint
```
Wire this pattern through all three phase methods so a resume at phase_ordinal=2 skips 0 and 1 cleanly.

**Tests**: `src/tests/integration/test_tfe_resume_e2e.py` covers the endpoint/dispatch layer; `src/tests/e2e/run-tfe-resume-e2e.sh` with `TFE_RESUME_E2E_LIVE=1` drives a full stall→resume round-trip. After Bug 6 fix, add a unit test that asserts resume skips phase methods via mock counters.

**Dependency on Bugs 3 + 4**: resume re-opens the voice gate with the same `priority="medium"` + `timeout=3s` problem. Until Bugs 3 and 4 land, the resume will stall again silently and you'll loop. Resume validation must come after Bugs 3 + 4.

## Open Design Question — default-on-timeout behavior

Current behavior when `feedback_timeout_seconds` elapses:
- `VoiceGateTimeoutError` raised → caught in `orchestrator.py:656` → wrapped in `StalledException` with a checkpoint → job persists checkpoint, exits with `stalled` status, waits for `agent router go to test fix expediter resume`.

User asks: should the default be flipped to "proceed with no selection" (i.e., skip Phase 3 entirely and finalize the run) instead of stall?

**Recommendation**: keep stall as the default, but make it configurable. Rationale: TFE executes Phase 3 (real code edits) + Phase 5 (real git branch/commit/PR) when fixes are selected. Auto-proceeding past a missed voice gate is safe *because* 0 selected → 0 applied → 0 committed; the job just completes with `n_fixed=0`. Stalling keeps queue state pinned but preserves the option to resume later. Neither is strictly wrong.

**Proposed knob** (in `lupin-app.ini` + splainer):
```
test fix expediter feedback timeout action = stall
# options: stall | skip (complete with 0 selected) | auto_select_high_confidence
```
Default `stall` preserves current behavior. Test container can override to `skip` in its config block so unattended scheduled runs don't pile up stalled jobs. Never auto-apply fixes without explicit human selection.

## Deferred — Return to these AFTER this plan's Execution Order (steps 1-10) is complete

These items are explicitly preserved for a follow-up session. Do not discard.

### D1. BFE dead-job race (eager snapshot + packager fallback)
- **Status**: unchanged from the earlier plan draft; untouched by today's work.
- **What**: `dead_queue_watchdog._submit_bfe` captures only `dead_job_id` as a string; BFE's later DB lookup fails if the row was evicted (done/dead rotation, TTL, or E2E `clean_test_db` drop-all). Fix is to snapshot the dead-job context at watchdog dispatch time and have `package_dead_job()` accept a snapshot fallback, skipping the DB when the snapshot is present.
- **Files**: `src/cosa/rest/dead_queue_watchdog.py:393-470`, `src/cosa/agents/bug_fix_expediter/dead_job_packager.py:38-42`, `src/cosa/agents/bug_fix_expediter/job.py:~227`.
- **Why deferred**: independent of today's TFE work; no acute user impact now that the 2026-04-15 test DB is stable.

### D2. TFE end-to-end live attended run (proves Phases 3/5/6)
- **What**: schedule a live TFE where a human answers the voice gate, selects proposals, and walks through Phase 3 (Fix) → Phase 5 (Git branch + commit + PR) → Phase 6 (Rerun validation).
- **Why deferred until after this plan**: today's run was unattended. Once bugs 1-7 land (working report links, single-panel job cards, audible voice gate, real timeout, correct `status="stalled"`, working resume button), the human-in-the-loop session is dramatically easier to drive. Doing it now would hit the same silent/truncated-gate failure mode and waste cycles.
- **Prereq**: this plan's steps 1-7 landed.

### D3. Pre-merge E2E gate
- **What**: the parallel session's proposed `POST /api/test-suite/submit` with `test_types="e2e"` + `monopolize=true`.
- **Why deferred**: fine to run but does not exercise the Claude Agent SDK path, so it won't catch SDK-auth regressions like yesterday's. Run it only after bugs 1-3 land so the operator's report links resolve when reviewing any failures.
- **Prereq**: this plan's bugs 1, 2, 3 landed.

## Critical Files

| Path | Change |
|---|---|
| `src/cosa/rest/routers/io_files.py:88-93` | Add `elif decoded_path.startswith( "io/" ):` strip |
| `src/fastapi_app/static/js/notifications.js:~5973-5984` | Verify `exclude_ids` wiring; possibly normalize id_hash |
| `src/cosa/rest/routers/job_history.py` (or wherever `/api/job-history` lives) | Confirm `exclude_ids` query-param honored; possibly normalize id_hash |
| `src/cosa/agents/utils/agent_notification_dispatcher.py:288-326` | Add `priority` param to `present_choices` + `ask_confirmation` + `get_feedback`; default `"high"` for blocking calls |
| `src/cosa/agents/bug_fix_expediter/cosa_interface.py:42` | `AgentNotificationDispatcher(agent_type=AGENT_TYPE, default_priority="high")` |
| `docker-compose.yml:108` | Remove `TFE_FEEDBACK_TIMEOUT_SECONDS_OVERRIDE: "3"` from `lupin-rest-test` env |
| `src/cosa/agents/test_fix_expediter/config.py` + `lupin-app.ini` + `lupin-app-splainer.ini` | Add `feedback_timeout_action` knob (stall/skip/auto_select_high_confidence), default `stall` |
| `src/cosa/agents/test_fix_expediter/orchestrator.py:4-10` | Rewrite stale phase-status docstring |
| `src/cosa/agents/test_fix_expediter/orchestrator.py:274, 304, 581` | Add resume-ordinal short-circuit at each phase entry |

## Execution Order

1. **Bug 4** (3-second timeout): remove env var from compose. Bounce test container. Highest-impact single change — unblocks every future attended TFE run.
2. **Bug 3** (priority="medium"): dispatcher signature change + default_priority on the SWE dispatcher. Lives in CoSA submodule; user commits from inside that repo.
3. **Bug 1** (io/file 404): one-line fix to `io_files.py`. Verify with curl.
4. **Bug 5** (stale docstring): comment-only. Land with #3 — same Lupin-parent commit.
5. **Bug 2** (Done/History dup): investigate (browser devtools + id_hash compare), then fix whichever of (a/b/c). Separate commit.
6. **Bug 7** (status="completed" instead of "stalled" on empty gate response): dispatcher defensive normalization. Small but critical — without this, the already-wired UI badge + resume button never activate.
7. **Bug 6** (resume phase-skip): add resume-ordinal guards at phase 0/1/2 entries. Unit test for skip. Validates today's `aj-225d4df2` can be resumed without redoing Opus work.
8. **Attended TFE resume smoke** against `aj-225d4df2`: submit resume, confirm badge + button appear, click button, answer voice gate (high priority, real timeout, checkpoint-skipped), walk through Phase 3 fix → Phase 5 git → Phase 6 rerun. End-to-end loop validation.
9. **Bug 8** (Pause/Stop semantics): add `user_pause` stall_reason + "Pause" / "Stop" voice-gate buttons + UI labels. Enables "pause for the night, resume tomorrow" workflow. Low priority — after 1-8 stable.
10. **Design knob** (`feedback_timeout_action`): land after 1-9. Default `stall` per user's decision.

## Verification

1. `curl -sf "http://localhost:8000/api/io/file?path=io/test-suite/2026.04.15-at-00:56-EDT-all-remediation.json" | wc -c` — returns >0 bytes after fix.
2. Browser: open the TFE report URL from the message, click the "Remediation snapshot" link, confirm it opens instead of 404.
3. Reload queue UI: confirm `aj-225d4df2::...` appears in exactly one panel (Done or History, not both).
4. `grep -A 6 '"""' src/cosa/agents/test_fix_expediter/orchestrator.py | head -12` — shows the updated phase-status block with no "STUB" labels.
5. Smoke: resubmit a small TFE run (same pattern as today), confirm the report's Appendix links resolve and the job card is single-panel.

## Out of Scope

- CoSA submodule commits (changes under `src/cosa/` are yours to commit from inside the CoSA repo).
- TFE Phase 2 implementation (already implemented — confirmed today).
- TFE attended end-to-end live validation (deferred to a later session).
- BFE dead-job race fix (separate plan, still valid).
