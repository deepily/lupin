# Lupin Project History

### 2026.04.21 - Session f9838819 | CJ Flow Async + Multi-Lane Design Review (v0.1.7 planning)

**Context**: User restarted the design conversation begun in Session 237 (2026-02-19) about migrating CJ Flow from strictly serial job execution to a concurrent dispatcher model. Two-part question: (1) what does the prior design (Approach C: Hybrid Fast Lane + Bounded Agentic Pool) actually look like, and (2) what changes — beyond raw throughput — when you go from serial to async?

**Accomplishments**:
- Mapped the existing serial baseline against the Approach C design and recapped the seven core moves (dispatcher refactor, fast lane inline, `ThreadPoolExecutor` for agentics, `Future.add_done_callback` completion, `threading.RLock()` on `FifoQueue`, `delete_by_id_hash()` over `pop()` in agentic paths, single INI knob `cj flow max concurrent agentic jobs`).
- Enumerated nine implications beyond throughput: concurrency safety + RLock discipline, ordering/determinism shift (start-FIFO preserved, completion-order is not), failure-mode geometry (N in-flight → N lost on crash, ghost-job risk if `_on_agentic_complete` raises), resource contention moving from CPU to API rate-limits + multiplicative spend, observability debt (pool-status promoted to Phase 2), testing complexity (concurrency tests, new mandatory unit files, concurrent-happy-path E2E), shutdown semantics + BFE/TFE checkpoint-resume alignment, UI + cosa-voice TTS debounce/batching needs, and ClaudeCodeJob INTERACTIVE worker-slot starvation as the case for a third "interactive" lane.
- Flagged seven open design questions before any code touches: interactive-lane scope, ship-default `= 1` vs `= 3`, cost-guardrail at the dispatcher, ghost-job watchdog, pool-status endpoint phase placement, per-job-type pools, and Approach D coupling for inbound user messages.
- **User decision**: defer all implementation to the v0.1.7 wip branch — current focus stays on landing v0.1.6 (TFE work). Default concurrency confirmed at `= 3` for first deploy.
- Created `src/rnd/v0.1.7/` subdirectory and serialized first version of the design review there for v0.1.7 future work.

**Files Modified**: 1 new (`src/rnd/v0.1.7/2026.04.21-cj-flow-async-multi-lane-design-review.md`, 18 332 bytes). No code changes — discussion + planning only.

---

### 2026.04.21 - Session b802e633 | Bug Fix Mode: DELETE /queue/all 404 + CJ-flow job-id chip truncation

**Context**: Retroactive Bug Fix Mode session (user invoked `/plan-bug-fix-mode-start` after fixes were already committed). Two user-reported bugs plus an in-flight refinement:

1. Test server logged `DELETE /api/queue/done/all → 404 Not Found` with the `[API]` line preceding the 404, pointing to a shadowed handler rather than a missing route. Investigation confirmed the parameterized `/queue/{queue_name}/{job_id}` route was declared before the literal `/queue/{queue_name}/all` in `src/cosa/rest/routers/queues.py`, so FastAPI bound `job_id="all"` and raised 404. Same defect existed on the `/job-history/all` vs `/job-history/{job_id}` pair (latent, not yet user-reported).
2. CJ Flow accordion cards rendered full 64-char sha + `::` + UUID id_hash strings, blowing out the header chip.
3. Follow-up tweak: the initial `length>8` truncation rule over-collapsed short non-compound ids like `foo-a1b2c9b2` and reasonable BFE prefixes like `bfe-a1b2c3d4::<uuid>`.

#### Fix 1: DELETE /api/queue/{name}/all and /job-history/all route shadowing

- **Source**: ad-hoc (user-reported from test-server logs)
- **Root cause**: route declaration order in `src/cosa/rest/routers/queues.py`
- **Fix**: moved literal `/all` routes above their `/{id}` siblings (both queue and job-history pairs); added docstring route-order note to both bulk handlers. CoSA submodule edit — user commits separately from CoSA context.
- **Lupin-side files** (in commit 82243e4):
  - `src/rnd/v0.1.6/2026.04.16-cj-flow-delete-all-buttons.md` — appended Fix History section
  - `src/tests/integration/test_queue_delete_all.py` — new, 6 lock-in tests (4 parametrized `/queue/{name}/all`, 400-on-bogus, 404-on-unknown-id for both pairs)
- **Verification**:
  - `py_compile` on `queues.py` + the new test file → OK
  - Route-table introspection: `/api/queue/{queue_name}/all` now precedes `/api/queue/{queue_name}/{job_id}`, same for job-history
  - Standalone HTTP probe against `:7999` dev (test server was occupied): 8/8 assertions pass (4 queues × `/all→200`, bogus→400, unknown-id→404 for queue and history)
- **Commit**: 82243e4

#### Fix 2: CJ Flow accordion — truncate enormously long job_ids in header chip

- **Source**: ad-hoc (follow-on user ask after Fix 1 verified)
- **Root cause**: `jobIdDisplay = jobId.split("::")[0]` still exposed 64-char sha prefixes
- **Fix**: initial rule `length>8 → jobId.substring(0,8) + "..."` in `renderJobCard()` (`notifications.js:6832`). Full `jobId` preserved in `data-job-id`, `title` tooltip, clipboard on-click, and the expanded `<code>` block — every API call and DOM lookup unaffected.
- **Files** (in commit 82243e4):
  - `src/fastapi_app/static/js/notifications.js` — truncation logic + updated comment
  - `src/fastapi_app/static/html/notifications.html` — cache-bust `v=20260420a → v=20260421a`
- **Test**: Not run (UI-only, user will verify in browser)
- **Commit**: 82243e4

#### Fix 3: Refine job-id chip truncation — preserve compound prefixes

- **Source**: ad-hoc follow-up after user observed Fix 2 was too aggressive on short ids (`foo-a1b2c9b2` and `bfe-a1b2c3d4::<uuid>` both got collapsed)
- **Root cause**: Fix 2's `length>8` rule didn't know about `::` (the canonical compound split point), so reasonable prefixes like `bfe-a1b2c3d4` (12 chars) got truncated even though they fit in the chip
- **New rule**: show the part before `::`; if that prefix is still >16 chars (64-char sha-style), fall back to `8 + "..."`. Effectively restores session `8ed95029`'s original `::`-split behavior (commit `5b3e305`) while adding a safety fallback for pathologically long prefixes.
- **Truth table**:
  - `cda8e7ed643cbc...::62d97559...` (prefix 64 chars) → `cda8e7ed...`
  - `bfe-a1b2c3d4::abc-def-uuid` (prefix 12 chars) → `bfe-a1b2c3d4`
  - `foo-a1b2c9b2` (no `::`, 12 chars) → `foo-a1b2c9b2`
  - `a::b` (prefix 1 char) → `a`
- **Files**:
  - `src/fastapi_app/static/js/notifications.js:6835` — compound-aware truncation (`idPrefix = jobId.split("::")[0]`; truncate only if `idPrefix.length > 16`)
  - `src/fastapi_app/static/html/notifications.html` — cache-bust `v=20260421a → v=20260421c` (two intermediate steps across the compound-awareness iterations)
- **Test**: Not run (UI-only; user will verify in browser); no automated coverage added for this chip's display text since no `data-testid` hook exists and no prior tests assert on it
- **Commit**: 0f67635

**Queue state at close**:
- 3 bugs fixed this session (all ad-hoc, all committed)
- 0 bugs still in progress (refinement wrapped in `0f67635`)
- 0 bugs carried over from this session's work

**Memory updates**:
- Strengthened [Ad-hoc dev work always targets :7999](memory/feedback_small_ad_hoc_runs_go_to_7999.md) — user: "Working against the dev server always. The test server is isolated so it's not your concern."

### Session Summary
- **Total Fixes**: 3 (route-ordering 404, job-id chip truncation, compound-prefix refinement)
- **Lupin-side files changed**: `src/fastapi_app/static/js/notifications.js`, `src/fastapi_app/static/html/notifications.html`, `src/tests/integration/test_queue_delete_all.py` (new), `src/rnd/v0.1.6/2026.04.16-cj-flow-delete-all-buttons.md`, `bug-fix-queue.md`, `history.md`, `.claude-session.md`
- **CoSA submodule (deferred to CoSA session)**: `src/cosa/rest/routers/queues.py` (route reorder)
- **GitHub Issues Closed**: none (all bugs were ad-hoc user reports)
- **Commits**: `82243e4` (Fix 1 + Fix 2 + integration test), `0f67635` (Fix 3 refinement + bug-fix-mode infra), `85629e6` (doc hash-reference correction), `<close commit>` (session summary)

**Status**: Session closed 2026.04.21

---

### 2026.04.21 - Session 9934d315 | TFE telemetry demotion + stop.py rebaseline + BFE stderr parity

**Context**: Overnight `tfe-10b2963e` ran 17 fixes, all failed verification, and triggered 3 blocking operator-intervention prompts ("Fix Verification Failed after 2 attempt(s)") because `shared/fix_executor.py` escalated via `present_choices()` after `max_fix_attempts`. The user wanted those demoted to fire-and-forget telemetry, wanted their intentional stop.py tweaks locked into unit-test baseline so TFE can't revert them, and wanted stderr tails surfaced in end-of-run reports without a worktree dig. Second-phase ask: mirror the parity change in BFE.

#### Checkpoint | 2026.04.21 13:15 | Part 1 + Part 2 code changes (parent Lupin only)

**Part 1 — TFE/shared telemetry + stop.py rebaseline** (4 parent-Lupin files; 3 CoSA submodule files deferred to user's CoSA session):

- `src/lupin_cli/claude_code/hooks/stop.py` — priority MEDIUM, timeout 60s, title "Stop hook: Anything else?" (mirrors user's 4b531fd); `_ask_anything_else` caller now passes `cwd=payload.get("cwd")`.
- `src/tests/unit/test_stop_hook.py` — `TestNotifyUserSync::test_notify_called_with_correct_params` asserts all three rebaselined fields; `NotificationPriority` imported from `lupin_cli.notifications.notification_models`.
- `src/tests/unit/test_deep_research_to_presentation.py:386` — stale `== 9` → `== 10` (TFE C3 straggler).
- `src/tests/unit/test_presentation_visual_renderer.py:78-80` — PlaceholderRenderer SUPPORTED_TYPES asserts only `["screenshot"]` (TFE C5 straggler).

**Part 1 — CoSA submodule changes, deferred to user's CoSA session**:

- `src/cosa/agents/shared/fix_executor.py` — replaced blocking `present_choices()` after `max_fix_attempts` with fire-and-forget `notify(priority="low")` + auto-reject `FixResult`. New `_tail_lines()` helper for stderr distillation.
- `src/cosa/agents/bug_fix_expediter/state.py` — `FixResult` grows `attempts: int = 0` and `last_stderr: Optional[str] = None`.
- `src/cosa/agents/test_fix_expediter/job.py` — end-of-run abstract appends "Failed fix diagnostics" section with top-5 stderr tails.

**Part 2 — BFE stderr parity** (2 parent-Lupin test files; 1 CoSA submodule file deferred):

- `src/cosa/agents/bug_fix_expediter/job.py` — mirrors TFE's Failed-fix-diagnostics block (no top-N cap, single-fix work unit). **Deferred to CoSA session.**
- `src/tests/unit/test_bfe_fix.py` — 2 new `TestFixResult` tests locking `attempts`/`last_stderr` defaults + auto-reject shape.
- `src/tests/unit/test_bfe_completion_report.py` — 3 `MagicMock` fixtures extended with `attempts=0, last_stderr=None` to fix `MagicMock > 0` TypeError (fix-at-source per memory).

**Design artifacts**:

- `src/rnd/v0.1.6/2026.03.27-bug-fix-expediter/2026.04.21-bfe-parity-with-tfe.md` — verification matrix showing BFE already had `worktree_scope` + safety guard + Phase 3+5 wrapping (Session Bug 9, 2026-04-16). Only remaining gap was the stderr section Part 2 closed.

**Verification**:

- **Unit suite**: 3544 passed, 1 xfailed (`test_ini_key_naming.py:121` pre-existing splainer gap), 0 failed. Runtime ~2m14s.
- **Integration suite**: started then killed — 44 auth 401 failures unrelated to my changes (stale test-container JWT/key drift). Resolved by test-container bounce in Phase 3 below.

**Phase 3 operational sequence** (user go-ahead 12:05 EDT, Claude executed end-to-end per `feedback_approved_sequences_execute_end_to_end`):

1. `src/scripts/preflight-test-container.sh` — all probes green (git mount, worktree add/remove, credentials, gh CLI).
2. `docker rm -f lupin-rest-test` + `docker compose up -d lupin-rest-test` — healthy, HTTP 200 on :8000.
3. `/schedule-tests all :8000` T+2min — job **`ts-f55d172d::50c73ba7-36dd-4eaf-a7e2-63256252c84f`**, queue position 1, started 12:08:52 EDT.

**Memory added**: `feedback_approved_sequences_execute_end_to_end.md` — one go-ahead covers the declared sequence; don't re-ask at each sub-step.

**Files**: stop.py, test_stop_hook.py, test_bfe_fix.py, test_bfe_completion_report.py, test_deep_research_to_presentation.py, test_presentation_visual_renderer.py, 2026.04.21-bfe-parity-with-tfe.md (+ manifest + history)
**Commit**: 3902f81

---

### 2026.04.20 - Session d8831785 | TFE-to-CC Opus 4.7 + thinking-effort parameterization (Phases A–G + Playwright verify)

**Status**: Matrix runner shipped; user-driven A/B/C/D sweep pending CoSA commit + test-container bounce.

**Context**: Phase 3 Run D (2026-04-19) landed 4/11 fixes in 8 min on Sonnet + no-effort vs. 0/11 × 3 SDK runs (63/120/180 min, $6.50–$15 paper cost each). Open question: how much of the win was engine (CC + Task subagents) vs. model choice? User asked for Opus 4.7 + runtime-configurable thinking effort + UI dropdowns + automated matrix sweep. Seven phases + Playwright verification delivered tonight.

**Earlier commits this session** (pre-checkpoint):

- `4b531fd` — stop.py re-enable `_ask_anything_else` + tune MEDIUM/60s notification; supersedes worktree C8 `dea2c76`.
- `ad55c29` — TFE-to-CC Phase 3 harness + live-test artifacts (11 files, 3277+): design doc 19-*, Phase 1+3 execution logs 20-*/21-*, harness scripts, 5 unit tests.
- `16299a5` — cherry-pick C6 `908ecf5` (agent-count 9→10) with conflict resolved in favor of C6 (registry verified 10 entries).
- 4 research worktrees reclaimed (194 MB); commits preserved in object DB.

**This checkpoint covers Phases A–G + Playwright verify**:

- **Phase A** — `src/scripts/tfe_to_cc_phase3_live.py`: argparse `--model` / `--effort` / `--max-budget-usd`. `DEFAULT_MODEL=claude-opus-4-7`, `DEFAULT_EFFORT=high`. Production default flipped from Sonnet to Opus per harness comment that already flagged Sonnet as a testing-mode override.
- **Phase B** — Changes-summary emitter in same harness: `_parse_worktree_commits`, `_derive_cluster_rows` (introduces `already_clean` verdict for fixed+null-SHA clusters — closes the validator contract gap from 21-*.md), `_compute_overall`, `_detect_submodule_leaks`, `_build_changes_artifact`, `_render_changes_md`, `_write_changes_artifacts`. Writes `/tmp/tfe-to-cc-changes-{ts}.{json,md}` per run.
- **Phase C** (CoSA — user commits) — `TestFixExpediterJob` + `BugFixExpediterJob` gain `thinking_effort` constructor param; propagates to `config.thinking_effort`; all 8 `ClaudeAgentOptions(...)` builders in both orchestrators pass `effort=self.config.thinking_effort` (None → SDK default, verified via live inspection of `ClaudeAgentOptions` dataclass).
- **Phase D** (CoSA — user commits) — `queues.py`: new `ResumeFromCheckpointRequest` body model for generic `/api/jobs/{id}/resume-from-checkpoint` endpoint (backward-compatible via `Body(default_factory=...)`); `TFEResumeFromRequest` extended with 3 optional override fields. `resume_job()` in `agentic_job_factory.py` accepts `args_overrides` dict + merges into `original_args` before factory reconstruction. `Literal["low","medium","high","xhigh","max"]` constrains `thinking_effort` at the API boundary.
- **Phase E** (Lupin JS) — `src/fastapi_app/static/js/notifications.js`: inline Model + Effort `<select>` dropdowns on stalled TFE/BFE job cards only (gated on `isResumableWithOverrides(job)`). `localStorage` persists last choice (`notifications_resume_model` / `notifications_resume_effort`). `resumeStalledJob()` reads DOM selections → POST body carries `lead_model_override` / `worker_model_override` / `thinking_effort`. Non-TFE/BFE cards unaffected.
- **Phase F** — Tests. Lupin new `test_tfe_to_cc_changes_artifact.py` (24): emitter pipeline, verdict remap, aggregation, submodule leak detection, argparse surface, production-default contract. Lupin extended `test_tfe_model_override.py` + `test_bfe_model_override.py`: 4 new thinking-effort tests per file (constructor storage, factory wiring via `args_dict`, config field presence). **44 tests green locally in 0.5s.**
- **Phase G** — New `src/rnd/v0.1.6/2026.04.10-test-fix-expediter/22-model-effort-matrix-plan.md`: A/B/C/D matrix design (Sonnet+high vs. Opus+{low,high,xhigh}), measurement method, read-out protocol (fixes-landed, fixes/min, tail-chasing proxy via stream-json); `00-index.md` row added for 22-*.
- **Phase E-verify** — Automated Playwright test `src/tests/e2e_ui/test_resume_overrides.py` (18 tests across 4 classes): agent-type detection, dropdown rendering + option counts + defaults, localStorage pre-selection, onchange persistence, POST body interception via `page.route()` proves override fields land in the correct shape. Uses sandbox injection (no live stalled-job seeding needed) so the suite runs in ~20s vs. typical minutes.
- **Matrix runner bonus** — `src/scripts/tfe_to_cc_matrix.sh`: one-shot A/B/C/D sequential runner with Docker preflight, `--arms` / `--dry-run` / `--strict` flags, per-arm logs, summary table emission. User can `nohup` it and walk away; harness per-arm notifications via cosa-voice keep them in the loop.

**Design decisions captured**:

- UI placement: inline dropdowns (not popup) — discoverable + low-friction for repeat use; button label stays simple.
- Thinking ROI is untested for this workload; matrix designed precisely to measure it. Prior: higher effort helps reasoning + planning, flat-to-negative on "apply known fix" work; tail-chasing risk grows at `xhigh` / `max`. Max subscription → $0 incremental so experiment is free.
- CoSA boundary clarification: the existing `feedback_lupin_only_never_cosa.md` says git ops in CoSA are off-limits but code edits are fine. Over-applied the rule earlier in the plan; user course-corrected ("you do all the work, I manage the cosa repo separately"). Acting on the correct interpretation from here — no new memory needed.

**Files modified this checkpoint (Lupin)**: `src/scripts/tfe_to_cc_phase3_live.py`, `src/fastapi_app/static/js/notifications.js`, `src/rnd/v0.1.6/2026.04.10-test-fix-expediter/00-index.md`, `src/tests/unit/test_tfe_model_override.py`, `src/tests/unit/test_bfe_model_override.py`, `.claude-session.md` (appended d8831785 section).

**New files this checkpoint (Lupin)**: `src/rnd/v0.1.6/2026.04.10-test-fix-expediter/22-model-effort-matrix-plan.md`, `src/scripts/tfe_to_cc_matrix.sh`, `src/tests/e2e_ui/test_resume_overrides.py`, `src/tests/unit/test_tfe_to_cc_changes_artifact.py`.

**CoSA-side uncommitted** (user commits from `src/cosa/` context, NOT in this checkpoint): `agents/test_fix_expediter/{config,job,orchestrator}.py`, `agents/bug_fix_expediter/{config,job,orchestrator}.py`, `rest/agentic_job_factory.py`, `rest/routers/queues.py`.

**Preliminary matrix results** (user kicked off `src/scripts/tfe_to_cc_matrix.sh` in parallel while I built Phase F/G + Playwright — arms A/B/C complete, D still running at checkpoint time):

| Arm | Model | Effort | Fixed | Already-clean | Unclear | Failed | Duration |
|---|---|---|---|---|---|---|---|
| **A** | Sonnet 4.6 | high | **3** | 2 | 6 | 0 | 17 m |
| **B** | Opus 4.7 | low | 0 | 0 | **11** | 0 | 4 m |
| **C** | Opus 4.7 | high | 1 | 0 | **9** | 1 | 6 m |
| D | Opus 4.7 | xhigh | _running_ | | | | |

Effective "actionable" count (fixed + already_clean) — A: **5/11**. B: **0/11**. C: **1/11**. **Sonnet baseline dominates Opus by a factor of 5×**, regardless of effort at low/high. Opus at low effort just returns `unclear` for everything (shorter duration — it gives up). Opus at high effort still craters. Hypothesis: Opus is more conservative on this workload — marks "unclear" where Sonnet would attempt; or extended thinking is actively causing over-analysis / tail-chasing. Arm D pending.

This **inverts the matrix-plan hypothesis** (Model > Effort, Opus > Sonnet). Follow-up doc `23-*` will propose default stays Sonnet + high until further investigation explains the Opus regression.

**Remaining steps for user**:

1. Commit CoSA-side edits from inside `src/cosa/` context (thinking_effort plumbing).
2. `./src/scripts/refresh-test-server.sh --quiet` to bounce test container for the Python changes (only needed if running UI/E2E tests — the matrix harness doesn't hit the server).
3. `PYTHONPATH=src pytest src/tests/e2e_ui/test_resume_overrides.py -v` — verify Phase E live (~20 s).
4. Wait on Arm D (xhigh) to complete the matrix; write `23-model-effort-matrix-results.md` with the finding + recommendation.

#### Checkpoint | 2026.04.20 21:30 | Phases A–G + Playwright verify

**Files**: 5 Lupin modified + 4 new Lupin (+ .claude-session.md).
**Commit**: `b9eeeef`

#### Session wrap | 2026.04.20 22:30 | 5-arm matrix complete + snake_case UI fix

**Post-checkpoint landings**:
- Fixed `isResumableWithOverrides` to match snake_case `job.agent_type` (was CamelCase-only → never matched real jobs). Added regression-guard Playwright test so this can't repeat. Bumped `notifications.html` cache-bust v=20260417c → v=20260420a so browser picks up the new JS.
- Created `23-model-effort-matrix-results.md` with full 5-arm analysis + recommendations; 22-*.md marked Closed.
- TODO.md updated with 8 new follow-ups (default flips, Opus investigation, cross-workload validation, confidence prompt tightening, validator fix, cache-bust discipline).

**Final matrix results** (all 5 arms complete — full analysis in `23-*.md`):

| Arm | Model | Effort | Effective | Duration | Fixes/min |
|---|---|---|---|---|---|
| A | Sonnet 4.6 | high | **5/11** | 17.1 m | 0.29 |
| B | Opus 4.7 | low | 0/11 | 4.3 m | 0.00 |
| C | Opus 4.7 | high | 1/11 | 5.9 m | 0.17 |
| D | Opus 4.7 | xhigh | 1/11 | 7.7 m | 0.13 |
| E | Sonnet 4.6 | xhigh | **4/11** | 7.4 m | **0.54** |

Headline: **Sonnet beats Opus by ~5× on this workload, regardless of effort.** Opus defaults to `unclear` at every effort level (B/C/D all land 0–1). Sonnet+xhigh is 2.3× faster than Sonnet+high with only slightly fewer fixes — best throughput arm. Matrix-plan hypotheses (Model>Effort, diminishing returns past `high`) were correct in shape but **direction inverted on Opus vs Sonnet**.

**Recommendations landing in follow-up commits**:
1. Flip harness `DEFAULT_MODEL` back to Sonnet
2. Flip UI localStorage fallback to Sonnet
3. Investigate Opus's `unclear` default (most interesting open question)

**Session commits** (four on wip branch):
- `4b531fd` — stop.py re-enable `_ask_anything_else`
- `ad55c29` — Phase 3 harness + artifacts (11 files, 3277+)
- `16299a5` — cherry-pick C6 (9→10)
- `3d95284` — checkpoint: Phases A–G + Playwright verify
- (this commit) — session-end wrap: matrix results + snake_case fix + cache-bust bump

**Next-session boot sequence**:
1. Read history.md + TODO.md (follow-ups from tonight listed first)
2. User commits CoSA Phases C/D edits from inside `src/cosa/` (config.py, job.py, orchestrator.py × 2; agentic_job_factory.py; rest/routers/queues.py)
3. `./src/scripts/refresh-test-server.sh --quiet`
4. If tackling follow-ups: apply the two default-flip TODOs first (harness + UI), commit, bounce, verify
5. If investigating Opus: `jq '.' /tmp/tfe-to-cc-changes-20260421T014055Z.json` (arm B) or pull the stream-json `/tmp/tfe-to-cc-phase3-stream-20260421T014055Z.jsonl` and grep for `verdict.*unclear` lines in the tool-use events

---

### 2026.04.18 - Session be57a252 | TFE Option A tier budgets + container preflight + gh CLI + worktree preservation + enriched completion report

**Status**: TFE resume underway at session-end per user request — polling for terminal state on new tfe-* job spawned from `tfe-72adc928`. Post-game analysis will compare Phase 3 outcomes vs. prior 0/11 baseline once the job lands done or dead.

**Accomplishments** (afternoon → evening):

- **Container preflight smoke tier** (new) — `src/scripts/preflight-test-container.sh` + `src/tests/smoke/test_container_preflight.py`. 5 blocking probes + 2 WARN (gh auth, worktree bind-mount end-to-end). Catches `docker-compose.yml` mount drift (the class of bug that silently recurred Bug 9a today).
- **GitHub CLI in container image** — Dockerfile edit via official apt repo (bottom of file to preserve the expensive Python/CUDA/torch/flash-attn/Chromium/MARP layers). `GH_TOKEN` env pass-through in `docker-compose.yml` for both services. Validated in-container: `gh auth status` → logged in as `deepily` with scopes `repo, workflow` (sufficient for personal-repo PR creation; `read:org` warning cosmetic). `gh pr list deepily/{lupin,cosa}` green.
- **Host worktree bind-mount** — `./.claude/worktrees:/var/lupin/.claude/worktrees` so preserved sandboxes survive `docker rm`.
- **`.dockerignore` additions** — nested `.venv/.git/.idea/.pytest_cache` globs (reclaims ~8.6 GB of build context transfer). Filed 37 GB `lupin.lancedb` as future runtime-bind-mount candidate.
- **TFE Option A — auto-tiered Coder turn budget** — new INI keys `test fix expediter coder budget {small,medium,large} turns = 30/50/80`. Replaces flat `max_fix_attempts * 10 = 20` that caused 11/11 `error_max_turns` in `tfe-8b2eaeda`. Orchestrator derives tier from proposal metadata (`fix_type` + affected-file count).
- **`cosa worktree auto cleanup = false`** — preserves worktree directory + commits for operator inspection after Phase 5 exit.
- **Completion abstract — Worktree Artifacts section** (TFE + BFE parity) — per-cluster outcome ✓/✗ + files, branch/commits/PR, inspection commands. Refactored into pure `render_worktree_artifacts_abstract()` helpers for unit-testability.
- **Coder tool-use breadcrumbs** — `Coder: Bash` → `Coder: Bash: pytest src/tests/unit/test_x.py`, etc. New `_summarize_tool_use` helper in TFE + BFE orchestrators.
- **Test coverage added** (45 new tests): `test_tfe_budget_tier` (7), `test_coder_tool_summary` (9), `test_container_preflight` (7), `test_config_integration_tfe_option_a` (6), `test_worktree_artifacts_abstract` (16).
- **Regression guard** — full unit suite sweep caught 6 genuine regressions (4 BFE completion from my refactor, 2 pre-existing SWE verification Bug 15 test-gap) and fixed all. 3394/3410 unit tests pass; remaining 16 failures are the exact TFE proposal targets (C2-C6, C8).

**Files modified this session (parent repo)**: `.claude-session.md`, `.claude/skills/testing-patterns/SKILL.md`, `.dockerignore`, `CLAUDE.md`, `TODO.md`, `docker-compose.yml`, `docker/lupin/Dockerfile`, `src/conf/lupin-app.ini`, `src/conf/lupin-app-splainer.ini`, `src/tests/unit/test_swe_team_verification.py`, `history.md` (this entry).

**New files**: `src/rnd/v0.1.6/2026.04.18-container-preflight-smoke{,-execution}.md`, `src/rnd/v0.1.6/2026.04.18-tfe-coder-turn-budget-option-a.md`, `src/scripts/preflight-test-container.sh`, `src/tests/smoke/test_config_integration_tfe_option_a.py`, `src/tests/smoke/test_container_preflight.py`, `src/tests/unit/test_coder_tool_summary.py`, `src/tests/unit/test_tfe_budget_tier.py`, `src/tests/unit/test_worktree_artifacts_abstract.py`.

**CoSA-side uncommitted** (user commits from inside `src/cosa/`): `agents/test_fix_expediter/{config,orchestrator,job}.py`, `agents/bug_fix_expediter/{orchestrator,job}.py`.

**Commits**: `6c9fe77` (checkpoint — Option A + infra + tests), session-end history commit (this entry).

---

### 2026.04.18 - Session 8ed95029 | Bug Fix: Truncate BFE job ID badge at `::` boundary

**Accomplishments**:

- **UI Bug — BFE badge overflow in CJ flow panels** — The `.job-id-chip` in each job card rendered the full scoped ID for BFE jobs (`bfe-XXXXXXXX::<uuid>` ~60 chars), distorting row layout. TFE and other prefixless IDs (`tfe-XXXXXXXX`) fit fine. Truncated the visible badge text at the `::` boundary while preserving the full compound ID for the tooltip, clipboard copy, `data-job-id`, and all DOM lookups. Mirrors the backend `AgenticJobBase.base_id` pattern (CoSA `agentic_job_base.py:153`).
- **Files (Lupin)**: `src/fastapi_app/static/js/notifications.js` — added `const jobIdDisplay = jobId.split( "::" )[ 0 ];` after line 6825; badge span on line 6980 now renders `${jobIdDisplay}` with `title="${jobId} — click to copy"`. Three-line change in one file.
- **Verification**: Hard-reload → user confirmed live: BFE badge shows only `bfe-XXXXXXXX`; tooltip reveals full scoped ID on hover; click-copy still yields full compound form. Node syntax-check clean. E2E visual regression run deferred (user-gated; trivial change).
- **Plan**: `~/.claude/plans/let-s-start-a-new-crispy-iverson.md` (approved via ExitPlanMode). Trivial one-file fix — R&D companion doc under `src/rnd/v0.1.6/` not warranted; captured feedback memory `feedback_skip_rnd_doc_for_trivial_fixes.md` so I apply this threshold in future sessions.
- **Session admin**: Session 8ed95029 retro-registered in Active Sessions table (was never formally initialized via `/plan-bug-fix-mode-start` — user opened with natural language).

**Commit**: 5b3e305

---

### 2026.04.17 - Session 44581b8c | Morning briefing → Resume path validated: Bugs 14 / 9a / 15 landed, Phase 3 blocker surfaced + fixed, Phase 3 observation deferred to tomorrow

**Status**: TO BE CONTINUED TOMORROW MORNING. All fix code + unit tests green; container bounce + Resume retry on `tfe-72adc928` + Phase 3/5/6 observation are the entry points for next session.

**Accomplishments** (from morning briefing → through Resume-path Phase 3 blocker):

- **UI Bug X1** — Resume button onclick sent empty jobId for history cards (`job.id_hash` stripped by normalization). Fixed at `notifications.js:7021-7022` (bare `jobId`). Confirmed working live.
- **UI Bug X2** (briefing's Bug 2) — history-card interactions toggle ID collision. Fixed by routing `idKey` (history-prefixed) to DOM lookups while keeping bare `jobId` for API/cache in `toggleJobInteractions` + `loadJobInteractions`. Live user confirmed 268 interactions loaded.
- **Bug 14** — Auto-dispatched TFE unresumable (empty `routing_command`, no `original_args`). Root cause: `_dispatch_tfe` bypassed `create_agentic_job()`. Fix: factory-routed dispatch (CoSA `test_suite_completion_watchdog.py`). Data-patched `tfe-3436c5b8` via SQL with pre-patch row snapshot for rollback. Unit test extended (36/36 green). Postmortem at `src/rnd/v0.1.6/2026.04.17-bug-14-*.md`.
- **showToast + 500-char response cap** — `notifications.js` showToast-undefined bug fixed (swap to `this.log`). Removed 500-char cap on `response_value` in `src/cosa/rest/routers/notifications.py` (was blocking 11-proposal voice-gate reply). Doc + cache-bust updated.
- **Bug 9a** — Test container missing `.git` bind-mount → `git worktree add` failed. Fixed in `docker-compose.yml` (both dev + test services). Container recreated (`docker rm -f` + `compose up -d` required; `--force-recreate` hit name conflict). Postmortem at `src/rnd/v0.1.6/2026.04.17-bug-9a-*.md`. Validated: `git rev-parse --is-inside-work-tree` → true inside container.
- **UI — job-ID chip** — Cards with identical labels from shared source-job were visually indistinguishable. Added click-to-copy `tfe-*` chip to card header + details line. CSS rules + cache-bust `v=20260417c`.
- **Bug 15** — `claude-agent-sdk v0.1.56` rejects string prompt when `can_use_tool` is set. Root-caused via SDK source. Community confirmed unresolved (upstream [issue #18735](https://github.com/anthropics/claude-code/issues/18735)). Helper `wrap_prompt_for_streaming()` added to `swe_team/hooks.py`; 7 call sites swapped in TFE/BFE/SWE orchestrators with inline WORKAROUND comment + URL at each site. New unit test (6 asserts). **42/42 passed** (6 new + 36 Bug 14 regression). Postmortem at `src/rnd/v0.1.6/2026.04.17-bug-15-*.md`.
- **Session manifest lapse** — Created `.claude-session.md` section for 44581b8c mid-session after user flagged missing status (protocol lapse: should have happened at session-start).

**Files modified this session (parent repo)**: `.claude-session.md`, `TODO.md`, `docker-compose.yml`, `src/docs/notification-api.md`, `src/fastapi_app/static/css/notifications.css`, `src/fastapi_app/static/html/notifications.html`, `src/fastapi_app/static/js/notifications.js`, `src/tests/unit/test_test_suite_completion_watchdog.py`.

**New files**: `src/rnd/v0.1.6/2026.04.17-bug-14-*.md`, `src/rnd/v0.1.6/2026.04.17-bug-9a-*.md`, `src/rnd/v0.1.6/2026.04.17-bug-15-*.md`, `src/tests/unit/test_wrap_prompt_for_streaming.py`.

**CoSA-side uncommitted** (user commits from inside `src/cosa/`): `agents/swe_team/hooks.py` (helper), `agents/swe_team/__init__.py` (export), `agents/swe_team/orchestrator.py` (3 call sites), `agents/bug_fix_expediter/orchestrator.py` (2 call sites + 1 import), `agents/test_fix_expediter/orchestrator.py` (2 call sites + 1 import), `rest/test_suite_completion_watchdog.py` (Bug 14 forward fix), `rest/routers/notifications.py` (500-char cap removal).

**DB state**: `lupin_db_test.job_history` row `tfe-3436c5b8` patched in-place (routing_command + metadata_json.original_args); pre-patch snapshot at `/tmp/tfe-3436c5b8-pre-patch.json` for rollback. Both `tfe-3436c5b8` and `tfe-72adc928` remain stalled and ready for tomorrow's Resume retry.

---

### 2026.04.17 - Session e55f7ac8 | Bug 2 intercession — resume plan queued for morning

#### Checkpoint | 2026.04.17 16:35 | Evening pause, pickup plan queued

- Resumed Bug 2 (Done-card toggle silently no-ops — DOM ID collision). Read plan doc `src/rnd/v0.1.6/2026.04.15-done-card-toggle-id-collision.md` + current `notifications.js` state. Zero repo edits this session.
- Verified JS fix landed in commit `1a25b9c` (Session f01fdc2f): `idKey` namespacing at `notifications.js:6831` — `const idKey = job._isHistory ? \`history-${jobId}\` : jobId;` + propagated through `renderJobCard`/`toggleJobCard`/`expandedJobCards`.
- Verified 3 Playwright regression tests (`TestJobCardToggleIDCollision` in `src/tests/e2e_ui/test_job_history_ui.py`) landed in commit `15f24d5` (Session aff39d3f) but have **never been executed** against the dev server (no `/tmp/e2e-ui-*.log`).
- Morning pickup queued: run targeted E2E (`./src/scripts/run-e2e-ui-tests.sh --bg -v -k TestJobCardToggleIDCollision`) → audit 12 bare-`jobId` DOM lookups for latent history-card misses → manual browser verification → flip `TODO.md:138` → session-end.
- Pickup plan (full detail): `~/.claude/plans/let-s-start-a-new-adaptive-engelbart.md`
- Parallel session detected editing `notifications.{js,css,html}` + `.claude-session.md` during this session — intercession intentionally isolated to `history.md` only.

**Files**: history.md (only)
**Commit**: e33d169

---

### 2026.04.16 - Session eb50bd56 | CJ Flow Delete All buttons (5 panes) + history archive

- 🗑️ Delete All button added to each of the 5 CJ flow pane headers (todo/run/done/dead/history). Non-admins delete own jobs only; admins clear entire queue. History pane respects the active time-window filter.
- **Backend** (CoSA — user commits from inside `src/cosa/`): `DELETE /api/queue/{name}/all` + `DELETE /api/job-history/all?days=N` + `delete_job_history_bulk()` in `job_persistence.py` + `queues.py`.
- **Frontend** (Lupin): `notifications.html` (5 buttons w/ data-testid), `notifications.js` (`deleteAllQueueJobs()` method), `notifications.css` (`.queue-delete-all-btn` ghost style, red tint).
- PQW HTTP 500 env-var bug filed in `bug-fix-queue.md` (Queued).
- **Plan**: serialized to `src/rnd/v0.1.6/2026.04.16-cj-flow-delete-all-buttons.md`
- **Commit**: 29a6fd4
- **History archive**: `history.md` was at 38,821 tokens (155% of 25k limit). Archived 23 sessions (2026-04-08 to 2026-04-14) to `history/2026-04-08-to-14-history.md`. Retained 4 recent sessions (10,008 tokens). **Commit**: 2879cbf
- **PQW HTTP 500 fix**: `LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL/_PASSWORD` were missing from the running `lupin-rest-dev` container (container predated the env var additions to docker-compose.yml). Fix: `docker rm -f lupin-rest-dev && docker compose up -d lupin-rest-dev`. Env vars confirmed injected; watcher confirmed running. No code changes — deployment-only fix.
- **Skill routing disambiguation**: Added explicit natural-language trigger lists + DISAMBIGUATION blocks to both `.claude/commands/plan-bug-fix-mode-wrap.md` and `plan-session-end.md` so "wrap up this bug" reliably routes to bug-fix-mode-wrap. **Commit**: 5f2713a
- **Seed account protection** (3-layer): `is_protected BOOLEAN` column added to `User` model (`postgres_models.py`); `seed_test_companions.py` sets `is_protected=TRUE` on every companion upsert; E2E `clean_test_db` now calls `seed_if_missing()` after DROP+RECREATE (Layer 1); both E2E + integration `clean_test_db` switched from DROP+RECREATE to row-level `DELETE FROM users WHERE NOT is_protected` + TRUNCATE of non-user tables (Layer 2); `admin_delete_user()` in `admin_service.py` guards against API deletion of protected accounts (Layer 3); 4 unit tests in `test_admin_protected_accounts.py`. DEV DB migrated immediately; TEST DB migrated + server bounced in Phase 2.
- **CoSA files** (user commits from inside `src/cosa/`): `postgres_models.py` (`is_protected` column), `admin_service.py` (Layer 3 guard).

**Session Summary**
- **Total Fixes**: 5 (CJ Flow Delete All, history archive, PQW HTTP 500, skill routing, seed account protection)
- **Commits (Lupin)**: 29a6fd4, 5f2713a, 2879cbf, 4e3c510, 91c3856, + this session's commit
- **CoSA-side changes (user commits separately)**: `queues.py` (2 new endpoints), `job_persistence.py` (`delete_job_history_bulk`), `postgres_models.py` (`is_protected`), `admin_service.py` (Layer 3 guard)
- **Status**: Session closed 2026.04.16

---

### 2026.04.15 - Session f01fdc2f | SDK creds mount + 11 TFE/BFE observability + lifecycle fixes

**Context**: Started with operator locked out of test server (401s, companions wiped from `lupin_db_test` by E2E UI suite teardown). Morning fix cascaded into a full audit of why last night's scheduled `ts-d2d890ed` TFE auto-dispatch produced "8 clusters, 0 proposed, 0 fixed" — SDK credentials weren't mounted in test container, voice gate fired at wrong priority, stalled rows mis-persisted as failed, resume re-ran Phase 0/1 unnecessarily. Ten bugs fixed + a tonight-run scheduled.

**Root cause #1 — SDK auth**: `~/.claude/.credentials.json` mount missing from `lupin-rest-test` compose service; `claude-agent-sdk` CLI returned `"Not logged in · Please run /login"` for every Phase 1 delegation → 0 diagnoses → Phase 2 skip at `orchestrator.py:628` → 0 proposals. Fix: add compose volume mount; re-probe shows live SDK response. Validated end-to-end by replaying `io/test-suite/2026.04.15-at-00:56-EDT-all-remediation.json`: 19 proposals generated (tfe-225d4df2 / tfe-e115ec67 / tfe-152111fe).

**Root cause #2 — voice gate silence**: dispatcher hardcoded `priority="medium"`; `TFE_FEEDBACK_TIMEOUT_SECONDS_OVERRIDE=3` left as test-container env; operator email (ricardo) wasn't the job target (interactive.job.tester was). Three separate fixes.

**Bugs landed** (Lupin parent):
- **Bug 1** (`src/cosa/rest/routers/io_files.py`): strip relative `io/` prefix so report links resolve.
- **Bug 2** (`src/fastapi_app/static/js/notifications.js`): Done/History job-card duplication — `refreshAllQueueLists` now awaits live-queue fetches before history so `exclude_ids` is populated.
- **Bug 4** (`docker-compose.yml`): remove `TFE_FEEDBACK_TIMEOUT_SECONDS_OVERRIDE:"3"` from `lupin-rest-test` env. Also add `~/.claude/.credentials.json` mount.
- **Bug 8** UI labels (`notifications.js`): badge differentiation via `stall_reason` — `⏸ Stalled` vs `⏸ Paused` vs `✕ Stopped`.
- **Bug 10** INI + splainer (`src/conf/lupin-app*.ini`): `voice gate operator email` + `voice gate service accounts` — dispatcher swaps target_user for service accounts so TTS reaches a real human.
- **Test-harness hardening** (`src/tests/e2e_ui/conftest.py`, `src/scripts/seed_test_companions.py`): post-suite companion reseed fixture; seed script fails loud when primary admin missing from `lupin_db_dev`.

**Bugs landed** (CoSA submodule — uncommitted, user to land from inside CoSA):
- Bug 3: dispatcher `priority="high"` default + `priority` param on ask_confirmation/get_feedback/present_choices.
- Bug 5: rewrite stale TFE orchestrator phase-status docstring (Phases 2/3/5/6 are REAL, not stubs).
- Bug 6: resume phase-skip guards at phase 0/1/2 entries — `_resume_from_ordinal` honored.
- Bug 7: dispatcher normalizes empty answers to `VoiceGateTimeoutError` (not silent empty selection).
- Bug 10 dispatcher: `_resolve_routing()` helper + `_prepend_operator_routing()` abstract prefix + `response_default` param on 3 blocking methods + BFE `cosa_interface` wrapper pass-through.
- Bug 11: `JobState.STALLED` → `persist_job_stalled_from_metadata` via `queue_util` route; `running_fifo_queue` recognizes STALLED as a first-class terminal (pushes to Done, not Dead, skips auto-fix watchdog).
- Resume factory fix: `resume_job()` dropped invalid `config_mgr` kwarg that was crashing `create_agentic_job`.

**Plan artifacts** (`src/rnd/v0.1.6/`):
- `2026.04.10-test-fix-expediter/18-post-tfe-validation-cleanup.md` (10-step plan doc; 18 in the TFE numbered series) + index updated.
- `2026.04.15-tfe-empty-clusters-and-bfe-dead-job-race.md` (earlier draft superseded by 18-).

**Validated end-to-end**:
- tfe-225d4df2 (dry_run=true, 1st resume): Phase 0+1 skipped ✓, voice gate auto-bypassed by dry_run ✓, status=completed with 2/2/2 dry synthetic successes.
- tfe-e115ec67 (dry_run=false, pre-op-routing): voice gate fired but MCP 503 (interactive.job.tester offline) → exposed Bug 10 + Bug 11.
- tfe-152111fe (post-op-routing): request correctly targets `ricardo.felipe.ruiz@gmail.com` → MCP 200 + `[NOTIFY-QUEUE] Notification queued` → TTS spoken → 5-min timeout → `status=stalled`, checkpoint intact, no error, re-resumable.

**Tonight** (scheduled before session-end at 19:27 EDT): `ts-79829a75` @ 19:30 EDT, `test_types=all`, `auto_fix_on_failure=true`, cheap-tier TFE via temporary `[Lupin: Testing]` INI override (`test fix expediter lead model = claude-sonnet-4-6`). TFE will auto-dispatch on failures; voice gate routes to ricardo via Bug 10; if unanswered, stalls cleanly per Bug 11 for morning resume per Bug 6.

**Deferred** (picked up next session):
- Bug 8b (wire Pause/Stop buttons end-to-end).
- Bug 9 (TFE/BFE Phase 3/5 in git worktree for isolation).
- `feedback_timeout_action` knob (stall/skip/auto_select_high_confidence).
- D1 BFE dead-job race (eager snapshot + packager fallback).
- D2 full TFE live attended (Phase 3/5/6 real commits + PR).
- D3 pre-merge E2E gate.

**Files touched this session** (Lupin parent, 8 modified + 3 new):
- `docker-compose.yml`, `src/conf/lupin-app.ini`, `src/conf/lupin-app-splainer.ini`, `src/fastapi_app/static/js/notifications.js`, `src/scripts/seed_test_companions.py`, `src/tests/e2e_ui/conftest.py`, `src/rnd/v0.1.6/2026.04.10-test-fix-expediter/00-index.md`, `src/rnd/v0.1.6/2026.04.10-test-fix-expediter/18-post-tfe-validation-cleanup.md` (new), `src/rnd/v0.1.6/2026.04.15-tfe-empty-clusters-and-bfe-dead-job-race.md` (new).
- **Not mine**: `src/tests/e2e_ui/test_job_history_ui.py`, `src/rnd/v0.1.6/2026.04.15-done-card-toggle-id-collision.md` (parallel session artifact).

**⚠️ Follow-up for next session**:
1. Archive history.md — this entry pushed us past 25k token limit (was 95.3% before write).
2. Morning: check tonight's `ts-79829a75` outcome; resume `tfe-*` stalled row via UI Resume button; answer voice gate → validate Phase 3/5/6.
3. Revert `[Lupin: Testing]` cheap-tier INI override once overnight run completes (or keep if desired).
4. Land the 9 CoSA-side changes from inside the CoSA repo.

---

### 2026.04.14 - Session 6ae2513c | TFE Resume E2E live path + env-vars API + test-suite scheduling

**Context**: Two scheduled TFE Resume E2E runs (21:00 + 21:39 EDT) had silently failed with `ConnectionError`. Root cause: scheduled pytest subprocesses executed inside `lupin-rest-test` where the server lives on internal port 7999, but `conftest.py` (via caller-set env var with `:8000` default) was hitting the host-side mapping. Secondary: `test_live_stall_and_resume` was a `pytest.skip()` placeholder with no body; needed real stall/resume plumbing; and no way to pass env vars through the test-suite scheduling API.

**Phase 1 — Unblock scheduled runs**:
- `src/cosa/agents/test_suite/job.py`: subprocess env now sets `LUPIN_TEST_BASE_URL=http://localhost:$PORT` (defaults 7999) so container-side pytest reaches the server. Caller-set value wins.
- `src/tests/integration/test_tfe_resume_e2e.py`: added `test_resume_from_checkpoint_happy_path_if_available` — queries `/api/job-history?status=stalled`, exercises resume endpoint if a stalled TFE job exists, skips cleanly otherwise.
- Host-side verified: `9 passed, 2 skipped` in 0.38s (was `9 errors`).

**Phase 2 — Real live stall-and-resume body**:
- `src/cosa/agents/test_fix_expediter/config.py`: `from_config()` now honors `TFE_FEEDBACK_TIMEOUT_SECONDS_OVERRIDE` env var, overriding the INI value for `feedback_timeout_seconds`. Round-trip verified (300 → 3).
- `src/tests/integration/test_tfe_resume_e2e.py`: replaced `pytest.skip()` placeholder with real body — `_poll_job_state` helper, submits TFE job via `/api/agentic-jobs/submit`, polls for STALLED, calls `/api/jobs/{id}/resume-from-checkpoint`, asserts response shape. Gated by `TFE_RESUME_E2E_LIVE=1` + `TFE_REMEDIATION_SNAPSHOT_FIXTURE=<path>`.
- `src/tests/e2e/run-tfe-resume-e2e.sh`: `--live` mode exports the timeout override + warns if fixture missing.

**env_vars plumbing end-to-end (Lupin + CoSA)**:
- `src/cosa/rest/routers/test_suite.py`: `TestSuiteSubmitRequest` gains optional `env_vars: Dict[str, str]` field with prefix-allowlist description.
- `src/cosa/rest/agentic_job_factory.py`: threads `env_vars` into `TestSuiteJob` constructor.
- `src/cosa/agents/test_suite/job.py`: new constructor arg + `_filter_env_vars` classmethod (prefix allowlist: `TFE_`, `BFE_`, `LUPIN_TEST_`). Accepted vars merge into subprocess env, overriding defaults. Disallowed keys dropped with warning.

**Other**:
- `docker-compose.yml`: commented out crash-looping `lupin-pgadmin` service (`PGADMIN_DEFAULT_EMAIL=dev@lupin.local` rejected by deliverability validator); added `TFE_FEEDBACK_TIMEOUT_SECONDS_OVERRIDE=3` to `lupin-rest-test` env block. Container bounced clean at 23:11 EDT.
- TODO.md item #2 stale "NOT COMMITTED" note replaced with commit hash `309f98c`. Triage doc `2026.04.13-session-triage-and-option-c-docker-non-root.md` marked ✅ completed.
- Deleted stale `src/conf/long-term-memory/lupin.lancedb.backup-2026-01-22/` directory (user-run sudo).

**Planning docs (new)**:
- `src/rnd/v0.1.6/2026.04.14-tfe-resume-e2e-live-implementation.md` (design)
- `src/rnd/v0.1.6/2026.04.14-tfe-resume-e2e-live-execution-log.md` (paired execution log)
- `io/test-suite/fixtures/tfe/sample-remediation-snapshot.json` (synthetic 1-failure fixture for live path)

**Scheduled at session-end (23:12 EDT)**:
- `ts-1139f28d` @ 23:15 — TFE dry run (expect `9 passed, 2 skipped`)
- `ts-996dafbc` @ 23:20 — TFE live run (env_vars with `TFE_RESUME_E2E_LIVE=1` + fixture path)
- `ts-d2d890ed` @ 23:25 — full `all` suite (60-min pyramid)

**Verified end-to-end**: py_compile on all touched files, shell syntax, YAML parse, Pydantic round-trip (`env_vars` payload), snapshot_loader.load_from_path round-trip, allowlist filter drops non-prefix keys.

---

### 2026.04.14 - Session 5a620729 | Test server force-refresh + peer queue watch + bug-fix mode bug #1 closed

#### Checkpoint 5 | 2026.04.14 23:00 EDT | Session-end — Bug #1 live-validated; NEW /api/push-agentic endpoint unblocks harness

**Context**: After CP4 shipped the BFE/TFE interactions + reports code fix, live validation via the E2E scripts revealed two pre-existing harness gaps (missing `websocket_id` on TFE, missing BFE fixture) and — deeper — the `/api/push` endpoint now routes unregistered commands through the runtime-argument-expeditor which asks for missing args via interactive notification and cancels on timeout. Unattended harness scripts can't respond, so submissions were silently cancelled before reaching the queue. Rather than retrofit `/api/push`, user proposed the cleaner architecture: a new dedicated endpoint for unattended agentic submission. Built it, scripts work end-to-end, live pipeline validated.

**New endpoint** (CoSA submodule, not committed from Lupin):
- `POST /api/push-agentic` in `src/cosa/rest/routers/queues.py` — accepts explicit `routing_command` + `args` dict + `websocket_id`. Validates required fields; passes args dict unchanged to the agent factory. No voice-path LORA parsing, no interactive Q&A. Auth identical to `/api/push`. On success returns `{ status, routing_command, websocket_id, user_id, job_id, result }`. On unknown command or construction failure returns 400 with the factory's error message.
- `push_job_agentic()` method on `TodoFifoQueue` (`src/cosa/rest/todo_fifo_queue.py`) — mirrors the non-expeditor parts of `_handle_agentic_command`: emits speculative `pending→todo` WebSocket transition with expediting=False, injects `no_confirm=true` into args, calls `create_agentic_job()` factory, overrides the job's id_hash with the speculative ID so the UI card matches, applies `scheduled_at` / `monopolize`, pushes to queue, emits "gentle-gong" for new-job UX parity.

**Lupin-side harness patches**:
- `src/tests/e2e/run-tfe-live-e2e.sh`: SUBMIT_PAYLOAD now uses `routing_command` + `websocket_id` + `question` keys, POSTs to `/api/push-agentic`.
- `src/tests/e2e/run-bfe-live-e2e.sh`: POSTs to `/api/push-agentic` (fixture file holds the full payload).
- `src/tests/fixtures/bfe/snapshot_known_bad.json` (NEW) — deep_research dry-run with `force_failure_mode=code_bug`, matching `/api/push-agentic` shape. Triggers deterministic `KeyError('source_path')` → dead queue → DeadQueueWatchdog classifies as CODE_BUG → dispatches BFE.
- `src/tests/unit/test_report_writer.py`: +2 tests for slug-sanitizer underscore-to-hyphen normalization (surfaced from user's feedback on `deadjobnotfounddryrun` run-on in CP4's first BFE report filename).

**Cosmetic slug fix** (CoSA): `src/cosa/agents/shared/report_writer.py` `_sanitize_slug()` now normalizes underscores to hyphens before applying the `[^a-z0-9\s-]` whitelist. Status tokens like `dead_job_not_found_dry_run` render as `dead-job-not-found-dry-run` in filenames.

**User corrections captured during the session**:
1. mock_token_email_* is legacy, not canonical (CP2) — saved to auto-memory.
2. Bounce reseeding fix — 401s during CP4 weren't a transient race; mistaken env-var assumption in reseed. User patched.
3. TFE failure-path report gap — CP4 initially wrote reports on happy + stall only; missed generic exception handler in `do_all()`. Fixed in same CP4 commit.
4. voice_io decoupling education — explained that voice is one WebSocket subscriber downstream of dispatch, not an upstream gate; persistence + UI render always happen; TTS decision belongs at the voice-bridge subscriber.
5. Endpoint scope refactor — when naive INI-key rename proved insufficient (args dict discarded before reaching push_job), user proposed cleaner architecture: leave `/api/push` alone, build `/api/push-agentic` as separate unattended path. Implemented.

**Live validation** (curl-driven):
```
dr-eb1b680e (deep_research, dry-run, force_failure_mode=code_bug)
  → run queue → KeyError raised → dead queue ✓
  → DeadQueueWatchdog classified CODE_BUG → dispatched BFE ✓
  → bfe-f91fd115 now in run queue → notify breadcrumbs flowing ✓
```
15 notification rows in `lupin_db_test.notifications` with correct compound `job_id` + matching `sender_id`. **RC-1 voice_io fix validated in the wild.**

**Bug-fix mode closed**: `bug-fix-queue.md` — bug #1 moved to Completed with full summary; session `5a620729` marked `closed` in Active Sessions table.

**Files changed this checkpoint (7 Lupin-side; 3 CoSA-side uncommitted)**:
- `.claude-session.md` — CP5 section
- `bug-fix-queue.md` — bug #1 → Completed; session closed
- `TODO.md` — added 5 completed items for this session, bumped "Last updated"
- `history.md` — this entry
- `src/tests/e2e/run-bfe-live-e2e.sh` (patched endpoint)
- `src/tests/e2e/run-tfe-live-e2e.sh` (patched endpoint + websocket_id)
- `src/tests/fixtures/bfe/snapshot_known_bad.json` (new, /api/push-agentic shape)
- `src/tests/unit/test_report_writer.py` (+2 slug tests, 14 tests total now pass)
- **Uncommitted, CoSA submodule**: `src/cosa/rest/routers/queues.py` (~100 lines new endpoint), `src/cosa/rest/todo_fifo_queue.py` (~95 lines push_job_agentic), `src/cosa/agents/shared/report_writer.py` (4 lines slug normalization)

**Deferred (carried to next session)**:
- **Archive history.md** — 22.4k tokens / 89.5% at session-end (critical). Most of it is this session's 5 checkpoints. First action next session.
- Unit test for `/api/push-agentic` endpoint — covered by happy-path live validation; formal pytest deferred.
- Clean full-script run of both E2E scripts end-to-end — live chain validated via direct curl; script-level polling/validation logic not yet exercised. Expected to work based on submit success.

---

#### Bug Fix Mode | 2026.04.14 14:35 EDT | Session entered bug-fix mode

User invoked `/plan-bug-fix-mode-start`. Active work: Bug #1 — BFE/TFE job cards show "No interactions recorded" and have no results-document link. Plan serialized to `src/rnd/v0.1.6/2026.04.14-bfe-tfe-interactions-and-reports.md`. Investigation phase first (Postgres query against test DB `notifications` table to pinpoint RC-1 break point) before writing any fix code. RC-2 (missing final-report generator for BFE and TFE) is orthogonal and independent of the investigation outcome.

#### Checkpoint 4 | 2026.04.14 19:30 EDT | Bug #1 code complete — RC-1 voice_io decoupling + RC-2 ReportWriter

**Investigation findings** (SQL against `lupin_db_test.notifications`):
- Test DB `notifications` table: **0 rows ever**. Entire pipeline silently dropping on test server.
- Dev DB healthy: 20+ BFE rows from Apr 10 with correct compound `job_id` (`bfe-XXX::userid`) and `sender_id` — proving code works when env is clean.
- Direct `curl POST /api/notify` with `X-API-Key` to `:8000` → persists correctly. Endpoint healthy.
- User's failing BFE job `bfe-79df11f2::...`: ran 1.04s, hit "dead job not found" dry-run branch, should have emitted ≥1 notification. Zero persisted.
- Card `has_interactions: true` is misleading — derived from `bool(session_id)`, not actual DB rows.

**RC-1 root cause** (`src/cosa/agents/utils/voice_io.py:296`): the notify() gate conflated *voice availability* with *persistence dispatch*:
```python
if _force_cli_mode or _cosa_interface is None or not await is_voice_available():
    print( f"  {message}" ); return   # skips dispatcher → skips DB → skips WebSocket → skips UI
```
`is_voice_available()` itself calls `_cosa_interface.notify_progress()` as a probe and caches the result. One probe failure for any reason locks `_voice_available = False` for the process lifetime — every subsequent notify becomes a bare `print()`. That was the full explanation for the empty test DB.

**RC-1 fix**: removed the `is_voice_available()` clause from `notify()`'s gate. Two legitimate CLI modes preserved: `_cosa_interface is None` (standalone/tests/pre-configure race) and `_force_cli_mode` (explicit `set_cli_mode(True)` opt-out). Rationale documented: TTS is one subscriber downstream of the WebSocket fanout; gating *dispatch* on *voice availability* was a layering error. The TTS decision belongs at the voice-bridge subscriber.

**RC-2 fix**: no final report existed for BFE or TFE — only intermediate plans via PlanWriter. Surface infrastructure (`renderReportLinkSection()` in notifications.js, `artifacts["report_path"]` extraction in `queues.py:348-352`) was already in place but unused.
- NEW `src/cosa/agents/shared/report_writer.py` — agent-agnostic markdown writer. Path: `{project_root}/io/swe-team/reports/{email}/YYYY.MM.DD-at-HH:MM-EST-{slug}-{agent}-report.md`. America/New_York zoneinfo handles EST/EDT automatically; `EST` in the filename is a fixed token per the project filename convention.
- `src/cosa/agents/bug_fix_expediter/job.py` — added `_write_final_report()` with full artifact serialization (dead_job_context, diagnosis, proposed_fixes, selected_fix, fix_result, resubmitted_job_id, stall checkpoint, failure traceback). Wired into **five** terminal exits: dry-run dead-job-not-found, live dead-job-not-found, happy path, stall, and `do_all()` generic exception handler.
- `src/cosa/agents/test_fix_expediter/job.py` — same pattern, TFE-specific artifacts (source_test_suite_job_id, cluster_count, fix_count, validation_run_job_id, orchestrator.clusters + proposed_fixes). Wired into **three** exits: happy, stall, generic exception.
- Both helpers populate `self.artifacts["report_path"]` → UI `renderReportLinkSection()` fires → "📋 View Full Report" link opens at `/app/docs?path=...`.

**User correction #1**: early Explore agent asserted `mock_token_email_*` was canonical. Wrong. `src/cosa/rest/auth.py:80-125` dispatches on `auth mode=jwt` (from `lupin-app.ini:497` in `[Lupin: Baseline]`, inherited by every configured env). Mock tokens are legacy dev-mode only. Canonical paths are JWT from `/auth/login` or global `X-API-Key`. Saved as `feedback_mock_tokens_are_legacy.md`.

**User correction #2**: TFE/BFE did not write a final report on generic failure — only happy path and stall. Fixed in this checkpoint by adding a `status="failed"` report-write in both `do_all()` exception handlers. Reports stash `failure_message` + `failure_traceback` (first 4000 chars) in artifacts and render a `## Failure` section. Failure is the case where the report matters *most*; gap closed.

**Tests (new, all passing)**:
- `src/tests/unit/test_report_writer.py` (12 tests): slug sanitization boundary cases, path shape (regex match on full filename), content assertions (title + agent + body), empty-body placeholder, email partitioning, agent suffix.
- `src/tests/unit/test_voice_io_notify_decoupling.py` (6 regression tests): dispatches when configured, prints when cosa_interface None, respects `_force_cli_mode`, falls back on dispatcher raise, **does not invoke `is_voice_available()` probe** (explicit — pins the bad gate stays removed), dispatches even when `_voice_available = False` is cached.
- **Totals**: 30 of 30 passing across `test_report_writer.py` (12) + `test_voice_io_notify_decoupling.py` (6) + `test_peer_proxy.py` (12 unchanged from CP2/CP3).

**Files changed this checkpoint (6 Lupin-side; 4 CoSA-side uncommitted)**:
- `.claude-session.md` — CP4 manifest section
- `bug-fix-queue.md` — session registered + bug #1 claimed
- `history.md` — this entry
- `src/rnd/v0.1.6/2026.04.14-bfe-tfe-interactions-and-reports.md` (new — serialized plan)
- `src/tests/unit/test_report_writer.py` (new — 12 tests)
- `src/tests/unit/test_voice_io_notify_decoupling.py` (new — 6 regression tests)
- **Uncommitted, CoSA submodule** (user commits separately per nested-repo rules): `src/cosa/agents/utils/voice_io.py`, `src/cosa/agents/shared/report_writer.py` (new, ~160 lines), `src/cosa/agents/bug_fix_expediter/job.py` (+130 lines), `src/cosa/agents/test_fix_expediter/job.py` (+105 lines)

**Next**: User restarts test server, dispatches a fresh BFE run (likely another dead-job-not-found dry run to match original scenario), and checks the card:
1. Notification Conversation should show the notify breadcrumbs from the run (RC-1 validated).
2. "📋 View Full Report" link renders on the done card → opens populated markdown report (RC-2 validated).

If both surface: bug #1 passes live verification, ready for /plan-bug-fix-mode-wrap.

---

#### Checkpoint 3 | 2026.04.14 14:05 EDT | Peer Queue Watch live — three bug fixes + root-cause discovery

**Context**: User tested the freshly-shipped Peer Queue Watch UI and hit three issues in sequence, each peeling back a layer. Fix-as-you-go session resulting in a working end-to-end drain-notification pipeline AND a bonus fix for the user's pre-existing test-UI admin lockout.

**Bug 1 — empty host combo box**:
- **Symptom**: "Peer host field isn't editable and isn't populated with any pre-slug addresses."
- **Root cause**: `peer-queue-watch.js` guarded `DOMContentLoaded` init with `if ( !( await requireAdmin() ) ) return;` — but `auth.js:517-525`'s `requireAdmin()` has no explicit `return` (returns `undefined`), so `!undefined === true` short-circuited every init and `populateHostSelector()` never ran.
- **Fix**: populate UI and wire buttons FIRST, then `await requireAdmin()` inside a try/catch (auth.js handles redirect on failure). Hard-reload picks up new JS immediately.

**Bug 2 — upstream connection refused**:
- **Symptom**: `ClientConnectorError: Cannot connect to host localhost:8000 ssl:default [Connect call failed ('127.0.0.1', 8000)]`.
- **Root cause**: proxy runs INSIDE the `lupin-rest-dev` container where `localhost:8000` is the container itself, not the host's mapped port. Peer containers on the docker-compose network are reachable by service name + the in-container port `7999`.
- **Verified**: `docker exec lupin-rest-dev curl -fsS http://lupin-rest-test:7999/health` → 200.
- **Fix**: whitelist in `lupin-app.ini` changed from `localhost:8000,localhost:7999` → `lupin-rest-test:7999,lupin-rest-dev:7999`. JS `ALLOWED_HOSTS` restructured as `[{value, label}]` so the dropdown shows friendly labels ("lupin-rest-test:7999 (test server, host :8000)") while the `<option>` value is the canonical container hostname. Splainer updated. Added container-network clarification to `peer.py` module docstring (side effect: forces uvicorn --reload since INI files alone aren't watched).

**Bug 3 — 401 "User not found"**:
- **Symptom**: `HTTP 502: upstream http://lupin-rest-test:7999/api/get-queue/run returned 401: {"detail":"User not found"}`.
- **Investigation**: `verify_jwt_token` (`src/cosa/rest/auth.py:128-204`) decodes+validates the JWT signature (shared secret works → "`lupin-rest-test` accepted the token as genuine"), then calls `get_user_by_id(payload["sub"])`. Dev and test use SEPARATE PostgreSQL databases (`lupin_db_dev` vs `lupin_db_test`) — so the dev user's UUID doesn't exist in the test DB → 401. **JWT pass-through (plan's Option A) was fundamentally broken** — shared signing secret is necessary but not sufficient; shared user store is also required.
- **Pivot to Option B (service-account login)**: dev backend POSTs to test-server `/auth/login` with `LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL`/`_PASSWORD` env vars (already set in dev container, confirmed via `docker exec lupin-rest-dev env`). Cache JWT per-host with 25min expiry (Lupin tokens are 30min). On upstream 401, invalidate cache and retry once.
- **Implementation** in `src/cosa/rest/routers/peer.py` (CoSA submodule — uncommitted):
  - NEW `_peer_jwt_cache: Dict[host, {token, expires_at}]`.
  - NEW helpers `_login_to_peer(session, host)`, `_get_peer_jwt(session, host)`, `_invalidate_peer_jwt(host)`.
  - `_fetch_queue` no longer accepts an `authorization` param — acquires its own token via `_get_peer_jwt`. On 401 retries once after cache invalidation.
  - Removed `Header` import; removed `authorization` parameter from `get_peer_queue`, `start_watcher`, and `_watcher_loop` signatures.
  - Module docstring updated to document the Option A → Option B pivot and why.

**Service-account login itself initially failed with 401 "Invalid email or password"**, revealing the real root cause:
- **Test DB was missing every seeded user**. Query: `SELECT email FROM users WHERE email = 'interactive.job.tester@lupin.deepily.ai'` → empty in `lupin_db_test`, present in `lupin_db_dev`. `src/scripts/seed_test_companions.py` is SUPPOSED to copy the companion rows at test-container startup, but clearly hadn't run successfully against the current test DB (either recent DB wipe without a container restart, or a silent failure on last startup).
- **Manually ran** `docker exec lupin-rest-test python3 /var/lupin/src/scripts/seed_test_companions.py` → 5 users seeded: `ricardo.felipe.ruiz@gmail.com` (admin+user), `admin@lupin.deepily.ai` (admin+user), `claude.code@deepily.ai` (service_account), `interactive.job.tester@lupin.deepily.ai` (user), `mock.job.tester@lupin.deepily.ai` (user). Plus 1 API key row.
- **Bonus win — test-UI admin lockout ALSO resolved** (the item flagged as out-of-scope back at session start). User was never actually "locked out" in the sense of role/permission — their user row simply didn't exist in the test DB. With the row now present, normal admin credentials log in on :8000.

**End-to-end verification from dev container**:
```
docker exec lupin-rest-dev bash -c 'TOKEN=$(curl -sS -X POST http://lupin-rest-test:7999/auth/login
  -H "Content-Type: application/json"
  -d "{\"email\":\"$LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL\",\"password\":\"$LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD\"}"
  | python3 -c "import sys,json;print(json.load(sys.stdin)[\"tokens\"][\"access_token\"])");
  curl -sS -H "Authorization: Bearer $TOKEN" http://lupin-rest-test:7999/api/get-queue/run'
→ {"run_jobs_metadata":[],"filtered_by":"50c73ba7-...","is_admin_view":false,"total_jobs":0}
```
(test run queue was already drained — user's big job collection had completed during debugging.)

**User confirmed "Pier Q watch works" from the admin UI widget.**

**Files changed this checkpoint (4 Lupin-side; 1 CoSA-side uncommitted)**:
- `src/conf/lupin-app.ini` — whitelist changed to container names
- `src/conf/lupin-app-splainer.ini` — splainer entry updated with container-network rationale
- `src/fastapi_app/static/html/admin/js/peer-queue-watch.js` — requireAdmin guard order; ALLOWED_HOSTS shape `[{value, label}]`; stale-host guard in `restoreSettings`
- `history.md` + `.claude-session.md`
- **Uncommitted, CoSA submodule**: `src/cosa/rest/routers/peer.py` (Option B implementation, ~60 net lines added for service-account login + cache; `_fetch_queue` signature change; module docstring rewritten)

**Ops action (not a code change)**: ran `seed_test_companions.py` manually on `lupin-rest-test`. Users/API-keys now present in test DB. If the test DB is reset again, re-run the script or restart the container (seed hook fires on startup).

**Unit tests**: 12/12 `test_peer_proxy.py` still pass after signature change.

**Next / followups**:
- Why did the test-DB seed fail silently on last container startup? Worth investigating so this doesn't recur. Not done this session.
- CoSA-side commit of `peer.py` (Option B overhaul) + earlier `pages.py` (peer-queue-watch route) + `admin.py` (refresh-source from CP1) — yours to stage in the CoSA context.

---

#### Checkpoint 2 | 2026.04.14 12:10 EDT | Peer Queue Watch (dev UI → test server)

**Context**: User locked out of test server (:8000) admin UI; needed visibility into its running queue while a large overnight job collection was executing. Decision via `ask_multiple_choice`: architect as dev-server-side proxy + server-side watcher + admin UI widget on `:7999` (where auth works). Backend fires the high-priority voice notification so the drain alert survives the user closing the browser tab. Plan file: `~/.claude/plans/rosy-watching-quilt.md` (rewritten from Checkpoint 1's refresh-server plan).

**Key corrections during planning** (captured in memory for future work):
- **mock_token_email_* is NOT canonical**. `src/cosa/rest/auth.py:80-125` dispatches on config key `auth mode`, which is `jwt` in `[Lupin: Baseline]` (`lupin-app.ini:497`) — inherited by every configured environment. `verify_mock_token` is labeled "legacy development mode" and is not reached. CLAUDE.md + AUTH-TESTING-GUIDE.md references to mock tokens are stale; `LUPIN_TEST_INTERACTIVE_MOCK_JOBS_*` env vars are **login credentials for `POST /auth/login`**, not mock-token inputs. Saved as `feedback_mock_tokens_are_legacy.md` in auto-memory.
- **Cosa-voice CAN fire from the backend**. Initial Explore agent wrongly concluded cosa-voice was MCP-only. `src/cosa/agents/utils/sync_notify.py:20-87` posts to `/api/notify` with an `X-API-Key` header — the WebSocket fanout routes it to cosa-voice for TTS. Any backend code path can trigger the voice alert via this helper.
- **JWT pass-through viable**. `jwt_service.py:25-32` reads `JWT_SECRET_KEY` with a fallback dev string; `docker-compose.yml` sets the env var on NEITHER dev nor test container, so both fall back to the same string → a JWT minted by dev verifies on test. Zero credential-juggling needed for the proxy.

**Backend (CoSA submodule — NOT committed from Lupin context)**:
- `src/cosa/rest/routers/peer.py` (new, 289 lines): four endpoints. `GET /api/admin/peer-queue/{queue_name}` proxies to `http://{host}/api/get-queue/{name}` with whitelist validation + JWT pass-through. `POST /api/admin/peer-queue-watch/{start,stop}` + `GET .../status` manage one `asyncio.Task` per admin that polls the peer and fires `sync_notify.notify(priority="high")` via `asyncio.to_thread` when `consecutive_zero >= stable_for`. Host whitelist read from config `peer queue allowed hosts`. Per-admin state dict keyed by `uid`/`email`. Pure helpers (`_is_host_allowed`, `_validate_host_and_queue`) exposed for unit testing.
- `src/cosa/rest/routers/pages.py`: added `/app/admin/peer-queue-watch` route + `_ROUTE_TABLE` entry.

**Lupin-side**:
- `src/fastapi_app/main.py`: imported `peer` router, registered via `app.include_router(peer.router)`, added shutdown handler `await peer.cancel_all_watchers_on_shutdown()` in lifespan cleanup block.
- `src/fastapi_app/static/html/admin/peer-queue-watch.html` (new): widget page with host selector, signal toggle (`run` vs `run+todo`), interval/stable-for inputs, live status panel (run/todo counts, consecutive zeros, last poll, last error), event log. Breadcrumb: Home > Admin > Dev Tools > Peer Queue Watch.
- `src/fastapi_app/static/html/admin/js/peer-queue-watch.js` (new, 218 lines): thin controller. `setInterval(10s)` polls `/status`; start/stop buttons call respective endpoints. `requireAdmin()` guard. `localStorage` persistence (key `lupin:pqw:settings`). Drain transition detected via `drained_at` timestamp change → logged in UI (voice alert already dispatched by backend). Uses existing `apiCall()` from `auth/js/auth.js:137-200`.
- `src/fastapi_app/static/html/dev-tools.html`: added "Peer Queue Monitoring" section with card linking to the new page.
- `src/conf/lupin-app.ini`: `peer queue allowed hosts = localhost:8000,localhost:7999` in `[Lupin: Baseline]`.
- `src/conf/lupin-app-splainer.ini`: matching splainer entry.

**Tests**:
- `src/tests/unit/test_peer_proxy.py` (new): 12 tests across `_is_host_allowed` (exact-match semantics, port-sensitivity, empty whitelist, substring-rejection), `_validate_host_and_queue` (HTTPException raising with correct status codes and detail text, all four queue names accepted), and `_watcher_state` isolation. All 12 pass.
- Live reachability (curl, no auth): proxy → 401, `watch/status` → 401, `/app/admin/peer-queue-watch` page → 200. Dev server auto-reloaded cleanly.
- Integration test with mocked aiohttp — deferred; the critical pure logic is covered by the unit tier, and auth/network paths are thin enough to validate in-browser.

**Auto-memory updates**:
- NEW `feedback_mock_tokens_are_legacy.md` — canonical auth paths are JWT (from `/auth/login`) or `X-API-Key`; mock tokens are rejected in every configured environment.
- MEMORY.md index updated.

**Files changed (7 Lupin-side in this checkpoint; 2 CoSA-side uncommitted)**:
- `src/conf/lupin-app.ini` (+3 lines)
- `src/conf/lupin-app-splainer.ini` (+1 line)
- `src/fastapi_app/main.py` (+9 lines: import, router register, shutdown hook)
- `src/fastapi_app/static/html/dev-tools.html` (+8 lines: monitoring section)
- `src/fastapi_app/static/html/admin/peer-queue-watch.html` (new)
- `src/fastapi_app/static/html/admin/js/peer-queue-watch.js` (new)
- `src/tests/unit/test_peer_proxy.py` (new)
- `history.md` + `.claude-session.md`
- **Uncommitted, CoSA submodule**: `src/cosa/rest/routers/peer.py` (new, +289 lines), `src/cosa/rest/routers/pages.py` (+5 lines: new page route)

**Next**: User opens `http://localhost:7999/app/admin/peer-queue-watch`, clicks Start against `localhost:8000` with the current live job collection. Voice drain notification fires when the test server's run+todo queues both hit 0 for two consecutive polls. Separately, test-server admin auth lockout still to be investigated (deferred out-of-scope; likely role-seeding regression in test DB fixture).

---

**Context**: The dev server (:7999) auto-reloads source via `uvicorn --reload`, but the test server (:8000) runs with `reload=False` (main.py:813) so bind-mounted source edits are ignored until the Python process restarts. No friction-free refresh mechanism existed; manual `docker restart lupin-rest-test` + visual health poll was the only path. User requested design exploration of options (including the SIGHUP avenue — a dead end since the container runs plain uvicorn with no gunicorn master). Plan file: `~/.claude/plans/rosy-watching-quilt.md`.

#### Checkpoint 1 | 2026.04.14 11:15 EDT | Layer A + B implemented, live verification deferred

**Design choices confirmed (via ask_multiple_choice)**:
- **Scope**: Layer A (shell script + slash command) + Layer B (admin endpoint). Hook-based auto-refresh rejected — defeats snapshot semantics the user wants to preserve.
- **State**: Cold restart only. In-memory state (queues, WS sessions, consumer thread) discarded by design. `importlib.reload()` graph-walk rejected as fragile (stale closures, class identity, thread-held refs).

**Layer A — host side (committed in this checkpoint)**:
- `src/scripts/refresh-test-server.sh` (new, +62 lines) — wraps `docker restart lupin-rest-test` + polls `http://localhost:8000/health` at 500ms intervals up to 30s; on failure prints `docker logs --tail 50`; supports `--quiet` for automation.
- `.claude/commands/refresh-test.md` (new) — `/refresh-test` slash command, picked up by the harness this turn.

**Layer B — admin endpoint (CoSA submodule edit, NOT committed from this context)**:
- `src/cosa/rest/routers/admin.py` (+79 lines) — new `POST /admin/refresh-source` endpoint. Double gate: `LUPIN_ENV ∈ {test, testing}` AND config key `admin refresh source enabled = true`. Uses `BackgroundTasks` to schedule an `os.execv()` re-exec after a 0.2s sleep so the 202 response flushes before the process image is replaced. `os.execv` chosen over `sys.exit` to keep container lifecycle stable and avoid brief network teardown. Reuses existing `require_admin` dep from `cosa.rest.auth_middleware`. Added `BackgroundTasks` to the top-level fastapi import.

**Lupin-side config**:
- `src/conf/lupin-app.ini` — `admin refresh source enabled = false` in `[Lupin: Baseline]`; overridden to `true` in `[Lupin: Testing]` and `[Lupin: Testing-GCS]`.
- `src/conf/lupin-app-splainer.ini` — splainer entry matching the new key.

**Verification status**:
- Static: `py_compile.compile('.../admin.py')` → OK. `bash -n refresh-test-server.sh` → OK. Both pre-flight.
- Live: deferred — test server is currently running a large job collection per user; no container restart attempted.
- Pending: unit test for `_refresh_source_allowed()` guard function (pure, trivial to add when live verification runs).

**Files changed (5 Lupin-side in this checkpoint; 1 CoSA-side uncommitted)**:
- `src/scripts/refresh-test-server.sh` (new)
- `.claude/commands/refresh-test.md` (new)
- `src/conf/lupin-app.ini` (+3 config lines across 3 blocks)
- `src/conf/lupin-app-splainer.ini` (+1 splainer line)
- `.claude-session.md` (session 5a620729 section)
- **Uncommitted, CoSA submodule**: `src/cosa/rest/routers/admin.py` (+79 lines — user to commit in cosa context per nested-repo rules)

**Next**: When test server is idle — run `./src/scripts/refresh-test-server.sh` to verify Layer A end-to-end, add unit test for Layer B guard, then `curl -X POST /admin/refresh-source` with admin JWT to verify the full re-exec path.

---


## Archives

- [2026-04-08 to 04-14](history/2026-04-08-to-14-history.md) — 23 sessions (TFE E2E, BFE Phase 6, checkpoint-resume, bug fixes)
- [2026-03-26 to 04-07](history/2026-03-26-to-04-07-history.md) — Sessions 379-a47f938e (BFE Phase 6, CJ Flow persistence, Sonnet pivot, UPE LanceDB isolation)
- [Full archive index](history/README.md)
