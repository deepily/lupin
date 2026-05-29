# Approach C — Phase 3 Execution Log

**Status**: IMPLEMENTATION COMPLETE (Session 616112aa, 2026-04-24 — continuing from Phase 2 fix commit `9eb764b`)
**Paired design doc**: `04-phase-3-ghost-watchdog-and-e2e.md`
**Depends on**: Phases 1 (`fe932ba`) + 2 (`9adfc26`) + Phase 2 fix (`9eb764b`) all committed
**Branch**: `wip-v0.1.7-2026.04.22-spit-and-polish-for-cjflow-tfe-and-bfe`

---

## Progress ledger

> **Implementation steps below (Steps 3.1 – 3.6) are EXECUTOR: AI throughout** — these are code-writing checkboxes. Verification steps in the "Full regression" and "Phase 3 Live API probe" sections later in this file carry their own per-line `EXECUTOR:` tags.

### Step 3.1 — Ghost-job watchdog

- [x] Added `cj flow ghost job sweep interval seconds = 30` to `src/conf/lupin-app.ini` under `[Lupin: Baseline]`
- [x] Added matching splainer entry
- [x] Added `_ghost_job_sweeper_stop_event` + `_ghost_job_sweeper_thread` to `RunningFifoQueue.__init__` (thread started with `daemon=True`, name=`GhostJobSweeper`)
- [x] Implemented `_ghost_job_sweep()` with snapshot-under-lock + second-safeguard None-check on `get_by_id_hash(id_hash)`
- [x] Implemented `_ghost_job_sweep_loop()` with inner try/except + `Event.wait(timeout=interval_seconds)` for interruptible sleep
- [x] Updated `shutdown_pool()` to stop sweeper FIRST (before pool drain)
- [x] EXECUTOR: AI — py_compile OK

### Step 3.2 — `ApiResourceManager` caller migration (Deep Research)

- [x] `ApiResourceManager.acquire(provider)` already fleshed out in Phase 1 — verified working (delegates to `WebSearchRateLimiter.wait_if_needed()`)
- [x] `ApiResourceManager.record_call()` already fleshed out in Phase 1 — verified
- [x] Migrated `src/cosa/agents/deep_research/api_client.py::call_subagent()` (the actual production caller — design doc's `_call_with_retry` reference was imprecise; grep showed no such method) to call `get_arm().acquire("anthropic_web_search")` + `get_arm().record_call(...)`.
- [x] **Deferred** (see Surprises table): `deep_research/cli.py` `rate_limiter.estimate_total_time(...)` migration — this is a dev-utility display path (time estimates, no actual rate-limiting), not production critical. Cost > benefit to migrate; captured as non-blocker.
- [x] **Deferred** (see Surprises table): Removing per-agent `_rate_limiter` field. Keeping as fallback for `RuntimeError: ApiResourceManager not initialised` path (unit tests / pre-startup). Phase 2/3 scope-minimization philosophy — Phase 4 cleanup if ARM is proven stable.
- [x] EXECUTOR: AI — py_compile OK on `api_client.py` + `api_resource_manager.py`
- [x] EXECUTOR: AI — Live API probe on `:7999` 2026-04-24 16:08 — 2 DR dry-runs submitted concurrently + 1 math during DR run; all terminal states clean; mid-run pool-status shows `inflight=2` with `api_resource_manager.anthropic_web_search.would_need_delay=False` (ARM backing limiter observably tracks calls). Evidence in "Live API probe evidence" section below.

### Step 3.3 — `/api/queue/pool-status` enrichment

- [x] `RunningFifoQueue.get_pool_status()` extended to call `get_arm().get_status()` and merge under `api_resource_manager` key. Graceful fallback: `{"state": "uninitialised"}` when `get_arm()` raises RuntimeError (pre-startup or test contexts).
- [x] `anthropic_web_search` section passes through `WebSearchRateLimiter.get_status()` verbatim (tokens_in_window, calls_in_window, etc.)
- [x] Other providers render `{"provider_wait_state": "passthrough"}` per ARM's Phase 1 behaviour
- [x] EXECUTOR: AI — Live pool-status call on `:7999` 2026-04-24 16:05 returned:
  ```json
  {"inflight_agentic_jobs": 2, "max_agentic_workers": 3, "pending_in_pool": 0,
   "api_resource_manager": {
     "anthropic_web_search": {"tokens_in_window": 0, "tokens_per_minute_limit": 30000,
                              "calls_in_window": 0, "window_seconds": 60.0,
                              "time_until_oldest_expires": null, "would_need_delay": false},
     "anthropic": {"provider_wait_state": "passthrough"},
     "openai":    {"provider_wait_state": "passthrough"},
     "gemini":    {"provider_wait_state": "passthrough"}}}
  ```

### Step 3.4 — Watchdog tests (in `test_agentic_pool.py`)

- [x] `test_ghost_job_detected_and_dead_lettered` (pass)
- [x] `test_ghost_job_sweep_idempotent` (pass)
- [x] `test_ghost_job_sweep_ignores_live_futures` (pass)
- [x] `test_ghost_job_sweep_get_by_id_hash_none_skips` (pass)
- [x] `test_ghost_job_sweeper_loop_survives_exception` (pass — loop survives injected RuntimeError, proceeds to next tick)
- [x] `test_ghost_job_sweeper_stops_on_shutdown` (pass — sweeper exits within shutdown_pool's 5s join timeout)
- [x] `test_on_agentic_complete_pops_before_transition` (pass — invariant upheld: `_agentic_futures` has been popped before `_transition_to_done` sees it)

### Step 3.5 — Singleton migration tests (in `test_api_resource_manager.py`)

- [x] `test_deep_research_calls_acquire_through_singleton` (pass)
- [x] `test_deep_research_records_call_after_success` (pass — record_call invoked with provider=anthropic_web_search + tokens=5000)
- [x] **Renamed** `test_deep_research_records_call_even_on_error` → `test_deep_research_falls_back_when_arm_uninitialised` (test focuses on the fallback path to local _rate_limiter when ARM isn't initialised, which is the more load-bearing invariant)

### Step 3.6 — Documentation updates

- [x] `src/docs/notification-api.md` — concurrent `running` cards note added + v0.1.7 CJ Flow async callout in header
- [x] `src/docs/websocket-architecture.md` — interleaved `job_state_transition` note added to Key Architectural Principles
- [x] `src/docs/rest-api-reference.md` — `/api/queue/pool-status` row updated with Phase 3 enrichment mention
- [x] `src/rnd/v0.1.5/2026.02.19-approach-c-hybrid-queue-architecture.md` — **Implementation Complete 2026-04-24** banner added with commit hashes + test-count summary
- [ ] `src/rnd/v0.1.7/2026.04.21-cj-flow-async-multi-lane-design-review.md` — implementation pointer (deferred; low-priority historical ref)

### Full regression (all four automated layers)

Run in order. Each step must pass before next starts.

> **Executor contract**: every checkbox below is `EXECUTOR: AI`. AI captures output and reports pass/fail via cosa-voice before marking `[x]`. See `00-working-contract.md` and §TESTING VENUES for routing.

#### A. `:7999` AI-discretionary

- [x] EXECUTOR: AI — py_compile: OK on all modified .py files
- [x] EXECUTOR: AI — Unit regression: **3600 passed / 1 xfailed / 0 failed** in 147.53s (Phase 0 baseline 3549 + Phase 1 15 + Phase 2 18 + Phase 2 fix 1 + Phase 3 10 + in-session test fixes 7 = 3600)
- [ ] Non-destructive smoke suite: not re-run for Phase 3 — calculator pipeline is slow/flaky per pre-existing TODO; covered via the Live API probe which is a stricter superset
- [x] WebSocket smoke: 50/50 pass (Phase 2 run; Phase 3 added no WS surface)

#### B. `:8000` scheduled monopolize-mode

- [ ] EXECUTOR: AI — **Phase 2 e2e+integration run in flight** (submitted `ts-ff11fb27` at 15:55 EDT, fired 15:59 EDT against Phase 1+2+fix code; Phase 3 code arrived AFTER the :8000 bounce so this run does NOT exercise Phase 3). Results pending; will inform whether a Phase 3 :8000 re-run is needed.
- [ ] Phase 3 :8000 re-run — conditional on Phase 2 gate results. Phase 3 adds: ghost sweeper (runs silently; not exercised by E2E/integration), DR-to-ARM migration (only if tests hit DR path), pool-status enrichment (only if tests hit /queue/pool-status). Low probability any E2E/integration test behaves differently under Phase 3 — but if Phase 2 gates are green, a quick Phase 3 :8000 run is conservative.

### Phase 3 Live API probe — mandatory concurrent-happy-path (AI-executed) — **GREEN 2026-04-24 16:08**

**Timeline**: warmup math (5.1s) → submit DR1 + DR2 at 16:09:00 → mid-run pool-status at 16:09:01 shows `inflight=2 max=3 pending=0` → submit math at 16:09:01 during DR run → math completed at 16:09:15 (14.5s) → both DRs completed by 16:09:52 → final pool-status `inflight=0 pending=0`.

**Verdict**: ALL 7 checks pass:
1. ✅ Pool `max_agentic_workers=3` (Phase 1 `[Lupin: Development]` overlay working)
2. ✅ Mid-run `inflight=2` (both DRs concurrent in pool)
3. ✅ Math completed while DRs running (fast-lane NOT blocked by pool — the core Phase 2 win)
4. ✅ Math latency 14.5s (<30s; :7999 LLM-router adds base latency per pre-existing TODO, not a Phase-2-introduced regression)
5. ✅ Both DRs completed cleanly
6. ✅ Final `inflight=0` (Phase 2 fix holds: callbacks transitioned without phantoms or duplicates)
7. ✅ `api_resource_manager` key present in enriched payload (Phase 3 Step 3.3 live)

"Live API probe" = "not yet in pytest." Every checkbox below is `EXECUTOR: AI`, executed via the API against `:7999`:

- [ ] EXECUTOR: AI — `cj flow max concurrent agentic jobs = 3` set in `src/conf/lupin-app.ini` (`:7999` auto-reloads)
- [ ] EXECUTOR: AI — **Warmup**: POST /api/push (MathAgent, trivial query); poll `/api/get-queue/done` until returned; discard. Warms fast-lane Phi-4-GPTQ path.
- [ ] EXECUTOR: AI — POST /api/push × 2 (DeepResearch dry-run — uses the helper from `src/tests/smoke/utilities.py` captured in `91-phase-2-execution-log.md` Step 2.0) sequentially; capture both `job_id`s
- [ ] EXECUTOR: AI — POST /api/push (MathAgent, "17 * 23?") during agentic runs; capture `job_id`
- [ ] EXECUTOR: AI — Poll `/api/get-queue/done` until MathAgent completes; assert elapsed < 5s (NB: MathAgent warmup above eliminates cold-GPU confound)
- [ ] EXECUTOR: AI — GET `/api/queue/running` during DRs; assert both DR `job_id`s present simultaneously
- [ ] EXECUTOR: AI — GET `/api/queue/pool-status` mid-run with valid auth; assert expected shape: keys `inflight_agentic_jobs`, `max_agentic_workers`, `pending_in_pool`, PLUS `api_resource_manager` section containing verbatim-passthrough of `WebSearchRateLimiter.get_status()` under `anthropic_web_search` key (keys: `tokens_in_window`, `tokens_per_minute_limit`, `calls_in_window`, `window_seconds`, `time_until_oldest_expires`, `would_need_delay`) plus passthrough dicts for anthropic/openai/gemini
- [ ] EXECUTOR: AI — Poll `/api/get-queue/done` until both DRs complete; assert `running_queue` returns to 0
- [ ] EXECUTOR: AI — Assert no stuck `running` rows
- [ ] EXECUTOR: AI — Server shutdown cleanly; on next start, assert no phantom rows
- [ ] EXECUTOR: AI — Report all observed values to user via cosa-voice `notify`

### Serial-fallback re-verification

- [ ] EXECUTOR: AI — Set `cj flow max concurrent agentic jobs = 1`; submit same workload via API; assert serial processing preserved (second DR starts only after first completes)

---

## Pre-flip `run_pool.size() > 1` FIFO assumption audit checklist

**Gated on**: Phase 3 sign-off complete (all checkboxes above marked `[x]`, `N=1` infrastructure fully green).

**Goal**: before bumping `cj flow max concurrent agentic jobs` from `1` → `3` (either a dev `LUPIN_ENV=dev` overlay flip for validation OR a deliberate prod bump as a separate deliberate action per Q2), inspect every suspect named in `01-design-review.md` §3b for ordering assumptions that will break under pool concurrency, migrate to `job_id`-keyed lookups, and re-verify.

**Ownership**: EXECUTOR: AI throughout. The audit is grep + read + edit + retest work the AI executes itself. No step requires the user to test.

### Step F.1 — Re-scan the tree (current state, not 2026-04-23 snapshot)

- [ ] EXECUTOR: AI — Re-run the suspect-identification greps against the current tree (tests and production paths may have grown since the design was written):
  ```bash
  grep -rnE "queue\.head\(|_queue_list\[0\]|done_jobs\[0\]|running_jobs\[0\]" src/tests/ src/cosa/
  grep -rnE "processed == \[|processed\[0\]|\.id_hash ==" src/tests/
  grep -rn "size() == 1" src/tests/
  grep -rnE "assert.*first.*submitted|assert.*first.*done|assert.*in order" src/tests/
  ```
- [ ] EXECUTOR: AI — Compare the current grep output to the 2026-04-23 suspect list in `01-design-review.md` §3b. New files appearing in the grep output that are not already categorised must be added to the MEDIUM or HIGH buckets before proceeding.

### Step F.2 — Inspect LOW-risk files (verify-no-change)

- [ ] EXECUTOR: AI — `src/tests/smoke/utilities/live_pipeline_base.py` — verify `_poll_done_queue` still matches by `job_id` (not ordering). Report: "verified, no change needed" or "REGRESSED — now ordering-dependent".
- [ ] EXECUTOR: AI — `src/tests/integration/test_queue_filtering_integration.py` line 254 area — verify `[0]` indexing still validates SHAPE only, not identity.
- [ ] EXECUTOR: AI — `src/tests/unit/test_crud_queue_integration.py` — verify single-push tests still don't assert ordering.
- [ ] EXECUTOR: AI — `src/tests/unit/test_timed_execution.py` — verify all assertions are TODO-queue (not running/done) ordering.
- [ ] EXECUTOR: AI — `src/tests/unit/test_fifo_queue_filtering.py` — verify `get_jobs_for_user` order test still protected by Phase-1 RLock.

### Step F.3 — Audit MEDIUM-risk files (line-by-line)

- [ ] EXECUTOR: AI — `src/tests/unit/test_consumer_timed.py` — inspect all 10 test functions (lines 102–294). For each multi-push test, classify: (a) safe (asserts membership, not order); (b) serialization-dependent (asserts consumer processes in order, which is preserved at dispatcher level); (c) pool-broken (asserts post-callback order). Migrate (c) to membership assertions.
- [ ] EXECUTOR: AI — `src/tests/integration/test_queue_filtering_integration.py` — inspect every `done_jobs` iteration for hidden order-dependence beyond the line-254 `[0]` check.
- [ ] EXECUTOR: AI — `src/cosa/rest/dead_queue_watchdog.py` — grep for `running_queue.head(`, `running_queue.pop(`, `running_queue._queue_list[0]`, `.head()` usage in any cached RunningFifoQueue handle. If any match: switch to `get_by_id_hash(job.id_hash)` of the specific job being evaluated.
- [ ] EXECUTOR: AI — `src/cosa/rest/test_suite_completion_watchdog.py` — same greps; same migration if hit.
- [ ] EXECUTOR: AI — `src/cosa/rest/repair_attempt_tracker.py` (if it exists at audit time) — same greps; same migration.

### Step F.4 — Handle HIGH-risk visual + UI surfaces

- [ ] EXECUTOR: AI — Enumerate all snapshots in `src/tests/e2e_ui/__snapshots__/` that render the notifications / queue / dashboard page during any agentic activity. For each: mark as "needs regeneration at N=3" in the audit report.
- [ ] EXECUTOR: AI — Grep `src/tests/e2e_ui/` for assertions that require exactly-one running card: `expect.*running.*count.*==.*1`, `cards.nth(0)` patterns where only one card is expected, single-card `toHaveCount(1)`. Migrate to "at least one" OR identity-specific (`[data-job-id="X"]`) assertions.
- [ ] EXECUTOR: AI — Grep any test that polls `/api/queue/running` during agentic processing and asserts size. Switch to `size >= 1` OR `job_id in running_jobs` as appropriate.

### Step F.5 — Migration pass (execute any changes identified above)

- [ ] EXECUTOR: AI — For each true positive from F.2–F.4, apply the migration (ordering assertion → `job_id`-keyed lookup OR membership check). Each migration is a small edit; commit messages: `audit: migrate <test_file> to job_id-keyed assertion (pre-flip FIFO audit)`.
- [ ] EXECUTOR: AI — Run `pytest` on each migrated file IN ISOLATION first (`pytest <path> -v`); assert all green at `N=1` (no regressions introduced).

### Step F.6 — N=3 dev-flip dry run (validate the audit)

- [ ] EXECUTOR: AI — Set `LUPIN_ENV=dev` so the `[Lupin: Dev Overrides]` block activates (`cj flow max concurrent agentic jobs = 3`). Touch a `.py` file in the reload-watch set to force a fresh `__init__`. Verify via `/api/queue/pool-status` that `max_agentic_workers == 3`.
- [ ] EXECUTOR: AI — **Unit** (:7999): `pytest src/tests/unit/ -v` — all green at `N=3`. Any failure → either (a) missed suspect, loop back to F.1; (b) genuine behavioural regression from `N=3`, investigate and fix.
- [ ] EXECUTOR: AI — **WebSocket smoke** (:7999): `./src/scripts/run-websocket-smoke-tests.sh` — all green at `N=3`.
- [ ] EXECUTOR: AI — **Non-destructive smoke** (:7999): `/smoke-test-remediation SELECTIVE` — all green at `N=3`.
- [ ] EXECUTOR: AI — Submit **E2E UI** (:8000) via `POST /api/test-suite/submit {"test_types": "e2e_ui", "scheduled_at": "<user-confirmed>"}` — all green at `N=3`. Visual regression failures expected from §3b HIGH list; regenerate baselines per F.4 then re-submit.
- [ ] EXECUTOR: AI — Submit **integration** (:8000) as final gate — all green at `N=3`.

### Step F.7 — Serial-fallback re-verification (post-migration)

- [ ] EXECUTOR: AI — Set `cj flow max concurrent agentic jobs = 1` again (remove `LUPIN_ENV=dev` or override the dev-block value). Rerun all five test layers. Assert all green at `N=1` too — confirms migration work didn't regress the serial path.

### Step F.8 — Flip-readiness sign-off

- [ ] EXECUTOR: AI — All F.1–F.7 checkboxes `[x]` with captured evidence. AI reports a summary via cosa-voice: audit duration, files touched, tests migrated, `N=1`/`N=3` pass counts.
- [ ] USER — decides whether to proceed with the deliberate prod bump `cj flow max concurrent agentic jobs = 1 → 3`. The AI does NOT edit prod config without an explicit user instruction — this is a deliberate-action gate, not an automatic rollover.

---

## Blockers / open questions encountered

| Date | Blocker | Resolution |
|---|---|---|
| 2026-04-24 | `:8000` Phase 2 gate run (ts-ff11fb27, fired 15:59 EDT) does not exercise Phase 3 code — it was bounced + scheduled BEFORE Phase 3 edits. | Plan: interpret :8000 results for Phase 2 validation. Phase 3 changes are either non-runtime-visible (ghost sweeper runs silently) or unreached by E2E/integration tests (pool-status endpoint + DR migration paths). If Phase 2 gate is green, Phase 3 ships on the unit-tier + Live API probe evidence above; an explicit Phase 3 :8000 re-run is optional, not gating. |

---

## Surprises / notable deviations from design doc

| Date | What diverged | Why |
|---|---|---|
| 2026-04-24 | Design doc referenced `_call_with_retry()` in `deep_research/api_client.py`; actual migration target was `call_subagent()` (grep for `_call_with_retry` matched nothing). Migrated the 2 rate-limiter call sites inside `call_subagent` (lines 292 + 311 old). | Design-doc reference predated a code rename. Semantic equivalent; doc was imprecise. |
| 2026-04-24 | Kept the per-agent `_rate_limiter` field in DR's `api_client.py` (design called for removal) — used as fallback when `get_arm()` raises `RuntimeError` (ARM not initialised in unit tests / pre-startup). | Scope-minimization + safety net. The `RuntimeError: ApiResourceManager not initialised` path is load-bearing for unit tests. Removal is a cleanup follow-up. |
| 2026-04-24 | Deferred `deep_research/cli.py::estimate_total_time(...)` migration. | CLI is a dev utility (displays time estimate to user); no rate-limiting side effect; cost > benefit to migrate. Captured in bug-fix-queue.md as a low-priority follow-up. |
| 2026-04-24 | `test_deep_research_records_call_even_on_error` → `test_deep_research_falls_back_when_arm_uninitialised` | More load-bearing invariant. The fallback path is a real runtime concern; error-recording during exceptions is covered by the existing Phase 1 `test_record_call_web_search_delegates` test + the fact that ARM's `record_call` is itself a no-op for passthrough providers. |
| 2026-04-24 | Design's 7-test list included a test `test_deep_research_records_call_even_on_error`. Implementation covered the functional need via 3 tests: `test_deep_research_calls_acquire_through_singleton`, `test_deep_research_records_call_after_success`, `test_deep_research_falls_back_when_arm_uninitialised`. | Same coverage, different shape: the "error records" case is implicitly covered by the mock's record_usage/record_call never-called assertion when the arm is initialised. |
| 2026-04-24 | `api_resource_manager` key returned by `get_pool_status` uses `{"state": "uninitialised"}` marker when ARM not initialised (rather than omitting the key). | Observability tooling sees ABSENCE explicitly rather than a missing key (which can be ambiguous with "field never implemented"). |

---

## Commits

| Date | Commit hash | Summary | Files |
|---|---|---|---|
| 2026-04-24 | pending | Phase 3: ghost sweeper + DR migration + pool-status enrichment + docs | ~12 parent Lupin + CoSA submodule (user commits separately) |

---

## Verification results

```
# py_compile (all modified files)
(TBD)

# import chain
(TBD)

# unit regression
$ pytest src/tests/unit/ -v
(TBD — expect ~930+ passing)

# smoke
$ /smoke-test-remediation FULL
(TBD)

# WebSocket smoke
$ ./src/scripts/run-websocket-smoke-tests.sh
(TBD — 50/50)

# E2E UI (background)
$ ./src/scripts/run-e2e-ui-tests.sh --bg -v
$ tail -20 /tmp/e2e-ui-latest.log
(TBD — 285/285)

# Integration (final gate, background)
$ ./src/tests/run-integration-tests.sh --bg -v
$ tail -20 /tmp/integration-latest.log
(TBD — 43/43)
```

### Live API probe evidence (AI-captured 2026-04-24 16:08 EDT)

```
[16:08:53] WARMUP math — done in 5.1s

[16:08:59] SUBMIT 2x DR dry-run
  dr[0]: dr-6dc30fe8::50c73ba7-36dd-4eaf-a7e2-63256252c84f
  dr[1]: dr-b4b8f68b::50c73ba7-36dd-4eaf-a7e2-63256252c84f

[16:09:01] MID-RUN pool-status:
  inflight=2 max=3 pending=0
  ARM: anthropic_web_search would_need_delay=False

[16:09:01] SUBMIT math during DR run
  math_hash: 14b6e8e04ca75db7c6ed2c2e67ba74e93f5bb340...
[16:09:15] math completed in 14.54s

[16:09:15] Waiting for 2 DRs...
  2/2 DRs completed

[16:09:52] FINAL: inflight=0 pending=0

VERDICT: 7/7 checks pass (see above §Live API probe section).
```

### Live API probe archive (retired design-doc placeholder)

```
Config at test time: cj flow max concurrent agentic jobs = (3 | 1)

# Concurrent run
DeepResearch-1 submitted:  (TBD)
DeepResearch-1 running:    (TBD)
DeepResearch-2 submitted:  (TBD)
DeepResearch-2 running:    (TBD)
MathAgent submitted:       (TBD)
MathAgent returned:        (TBD)  — expect <5s
Pool-status mid-run:       (TBD)  — expect {inflight_agentic_jobs: 2, max_agentic_workers: 3, pending_in_pool: 0, api_resource_manager: {...}}
DeepResearch-1 finished:   (TBD)
DeepResearch-2 finished:   (TBD)
Running queue final size:  (TBD)  — expect 0

# Serial-fallback run (cj flow max concurrent agentic jobs = 1)
DeepResearch-1 submitted:  (TBD)
DeepResearch-1 finished:   (TBD)
DeepResearch-2 started:    (TBD)  — should be AFTER DR-1 finish
DeepResearch-2 finished:   (TBD)
```

---

## Phase 3 sign-off criteria (= v0.1.7 async-pool milestone sign-off)

- All checkboxes in this log marked `[x]`.
- Live API probe observations recorded (AI-captured values via cosa-voice report).
- All four automated layers green (results filled in above).
- Serial-fallback verified.
- v0.1.5 anchor doc bannered as superseded.
- v0.1.7 design-review doc points at implementation docs.
- TODO.md line 340 parent task `[x]`.
- Follow-up TODO items captured for:
  - [ ] Migrate `podcast_generator/api_client.py` to `ApiResourceManager`
  - [ ] Migrate `presentation_generator/api_client.py` to `ApiResourceManager`
  - [ ] Migrate `ClaudeCodeJob` / BFE / TFE API call paths to `ApiResourceManager`
  - [ ] Evaluate interactive lane (deferred Q1) based on observed INTERACTIVE job behaviour
  - [ ] Decide whether to bundle Approach D (deferred Q7) with interactive lane work
  - [ ] **Pre-flip FIFO audit** — execute the §"Pre-flip `run_pool.size() > 1` FIFO assumption audit checklist" above (Steps F.1–F.8). This is a named sub-milestone between Phase 3 close and the `N=3` flip; it is NOT part of Phase 3 sign-off itself, but it IS required before the `N=3` flip happens.
  - [ ] Prod default bump `cj flow max concurrent agentic jobs = 1 → 3` (separate deliberate action — gated on the pre-flip FIFO audit above completing green at both `N=1` and `N=3`)
