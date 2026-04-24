# Approach C — Phase 3 Execution Log

**Status**: NOT STARTED (skeleton only — populate as implementation proceeds)
**Paired design doc**: `04-phase-3-ghost-watchdog-and-e2e.md`
**Depends on**: Phases 1 and 2 complete (all checkboxes `[x]` in `90-phase-1-execution-log.md` and `91-phase-2-execution-log.md`)
**Branch**: `wip-v0.1.7-2026.04.22-spit-and-polish-for-cjflow-tfe-and-bfe`

---

## Progress ledger

> **Implementation steps below (Steps 3.1 – 3.6) are EXECUTOR: AI throughout** — these are code-writing checkboxes. Verification steps in the "Full regression" and "Phase 3 Live API probe" sections later in this file carry their own per-line `EXECUTOR:` tags.

### Step 3.1 — Ghost-job watchdog

- [ ] Add `cj flow ghost job sweep interval seconds = 30` to `src/conf/lupin-app.ini` under `[Lupin: Baseline]` (splainer note: bounded to [5s, 300s] — below 5s is noise, above 300s is too slow)
- [ ] Add matching splainer entry
- [ ] Add `_ghost_job_sweeper_stop_event = threading.Event()` and `_ghost_job_sweeper_thread = threading.Thread(target=self._ghost_job_sweep_loop, daemon=True, name="GhostJobSweeper")` to `RunningFifoQueue.__init__` per the ordered sequence in `04-phase-3-*.md` Step 3.1 §"Thread lifecycle" — AFTER the Phase-2 pool init, start the thread via `self._ghost_job_sweeper_thread.start()`
- [ ] Implement `_ghost_job_sweep()` method — snapshot `_agentic_futures` under lock, iterate without lock, per-future check `self.get_by_id_hash(id_hash)` (second safeguard — None means callback already transitioned, skip), dead-letter via `_transition_to_dead(job, cause)` when `Future.done() is True` and job still in running_queue
- [ ] Implement `_ghost_job_sweep_loop()` method — `while not stop_event.is_set(): try: self._ghost_job_sweep() except Exception: log; stop_event.wait(timeout=interval_seconds)`. Inner try/except prevents a single failed sweep from killing the thread.
- [ ] Prepend `shutdown_pool()` with sweeper-stop: `self._ghost_job_sweeper_stop_event.set(); self._ghost_job_sweeper_thread.join(timeout=5.0)` — FIRST lines of `shutdown_pool`, before the pool drain
- [ ] EXECUTOR: AI — `python -c "import py_compile; py_compile.compile('src/cosa/rest/running_fifo_queue.py', doraise=True)"` — AI asserts exit code 0

### Step 3.2 — `ApiResourceManager` caller migration (Deep Research)

- [ ] Flesh out `ApiResourceManager.acquire(provider)` for `anthropic_web_search`: lazy-import `WebSearchRateLimiter`, instantiate once per ARM, delegate to `wait_if_needed()` (no tokens arg — reactive limiter)
- [ ] Flesh out `ApiResourceManager.record_call()` for `anthropic_web_search` — delegate to `WebSearchRateLimiter.record_usage(tokens)`
- [ ] Migrate `src/cosa/agents/deep_research/api_client.py::_call_with_retry()` to call `get_arm()` (module-level accessor, NOT `ApiResourceManager.get_instance()` — class-method pattern was rejected in fitness review). Pattern: `arm = get_arm(); await arm.acquire("anthropic_web_search"); response = ...; arm.record_call("anthropic_web_search", tokens=..., latency_ms=...)`
- [ ] Migrate `src/cosa/agents/deep_research/cli.py` direct `rate_limiter.estimate_total_time(...)` call to go through `get_arm()` (hidden third caller surfaced in fitness review — see `01-design-review.md` §3a). If cli.py is purely a dev utility, leaving on direct import is acceptable — document the decision in this log's "Surprises / notable deviations" table.
- [ ] Remove now-dead per-agent `_rate_limiter` field from `api_client.py` (after both callers migrated). Grep `deep_research/` for any remaining `_rate_limiter` references; each must be resolved.
- [ ] EXECUTOR: AI — Submit Deep Research dry-run via `POST /api/push`; AI polls `/api/get-queue/done` until the row appears, asserts `status == "done"` within the documented DR-dry-run window, asserts no matching `dead_queue` entry; reports elapsed time + final status via cosa-voice `notify`. (Requires the Phase-2 prep step to have confirmed DR dry-run is AI-runnable without real API spend — see `91-phase-2-execution-log.md` Step 2.0.)
- [ ] EXECUTOR: AI — `python -c "import py_compile; [py_compile.compile(p, doraise=True) for p in ['src/cosa/agents/deep_research/api_client.py', 'src/cosa/utils/api_resource_manager.py']]"` — AI asserts exit code 0

### Step 3.3 — `/api/queue/pool-status` enrichment

- [ ] Endpoint response includes `api_resource_manager` key from `ApiResourceManager.get_instance().get_status()`
- [ ] `anthropic_web_search` section shows real sliding-window state
- [ ] Other providers show `{"provider_wait_state": "passthrough"}`
- [ ] EXECUTOR: AI — `python -c "import requests; r = requests.get('http://localhost:7999/api/queue/pool-status'); assert r.status_code == 200; body = r.json(); assert 'api_resource_manager' in body; arm = body['api_resource_manager']; assert set(arm.keys()) >= {'anthropic_web_search', 'anthropic', 'openai', 'gemini'}; print(body)"` — AI asserts 200 + `api_resource_manager` key + all 4 provider sub-keys present.

### Step 3.4 — Watchdog tests (in `test_agentic_pool.py`)

- [ ] `test_ghost_job_detected_and_dead_lettered`
- [ ] `test_ghost_job_sweep_idempotent`
- [ ] `test_ghost_job_sweep_ignores_live_futures`
- [ ] `test_ghost_job_sweep_get_by_id_hash_none_skips` — second-safeguard test: callback races with sweep; sweep snapshot shows the future is done but `get_by_id_hash(id_hash)` returns None (already transitioned out of running_queue); assert sweeper skips (does not double-transition)
- [ ] `test_ghost_job_sweeper_loop_survives_exception` — force `_ghost_job_sweep()` to raise once; assert loop catches exception, logs banner, and proceeds to next tick (does not kill the thread)
- [ ] `test_ghost_job_sweeper_stops_on_shutdown`
- [ ] `test_on_agentic_complete_pops_before_transition` — invariant regression test (see `03-phase-2-*.md` Step 2.1 invariant callout)

### Step 3.5 — Singleton migration tests (in `test_api_resource_manager.py`)

- [ ] `test_deep_research_calls_acquire_through_singleton`
- [ ] `test_deep_research_records_call_after_success`
- [ ] `test_deep_research_records_call_even_on_error`

### Step 3.6 — Documentation updates

- [ ] `src/docs/notification-api.md` — concurrent `running` cards note
- [ ] `src/docs/websocket-architecture.md` — interleaved event note
- [ ] `src/docs/rest-api-reference.md` — `/api/queue/pool-status` row + `api_resource_manager` enrichment
- [ ] `src/rnd/v0.1.5/2026.02.19-approach-c-hybrid-queue-architecture.md` — completion banner pointing at v0.1.7 docs; all 11 sub-steps `[x]`
- [ ] `src/rnd/v0.1.7/2026.04.21-cj-flow-async-multi-lane-design-review.md` — add implementation pointer

### Full regression (all four automated layers)

Run in order. Each step must pass before next starts.

> **Executor contract**: every checkbox below is `EXECUTOR: AI`. AI captures output and reports pass/fail via cosa-voice before marking `[x]`. See `00-working-contract.md` and §TESTING VENUES for routing.

#### A. `:7999` AI-discretionary

- [ ] EXECUTOR: AI — **1. py_compile**: compile each modified `.py` file via `python -c "import py_compile; py_compile.compile('<path>', doraise=True)"` — all exit code 0
- [ ] EXECUTOR: AI — **2. Unit**: `pytest src/tests/unit/ -v` — 915 baseline + Phase 1/2/3 new tests all green
- [ ] EXECUTOR: AI — **3. Non-destructive smoke**: `/smoke-test-remediation SELECTIVE` (excludes `:8000`-routed destructive suites) — no regressions
- [ ] EXECUTOR: AI — **4. WebSocket smoke**: `./src/scripts/run-websocket-smoke-tests.sh` — 50/50

#### B. `:8000` scheduled monopolize-mode (AI submits via `/api/test-suite/submit` after user slot-check)

- [ ] EXECUTOR: AI — **5. Destructive smoke** (if touched): `POST /api/test-suite/submit {"test_types": "smoke", "scheduled_at": "<user-confirmed>"}` — 100% pass
- [ ] EXECUTOR: AI — **6. E2E UI**: `POST /api/test-suite/submit {"test_types": "e2e_ui", "scheduled_at": "<user-confirmed>"}` (local fallback: `./src/scripts/run-e2e-ui-tests.sh --bg -v`) — 285/285
- [ ] EXECUTOR: AI — **7. Integration (final gate)**: `POST /api/test-suite/submit {"test_types": "integration", "scheduled_at": "<user-confirmed>"}` (local fallback: `./src/tests/run-integration-tests.sh --bg -v`) — 43/43

### Phase 3 Live API probe — mandatory concurrent-happy-path (AI-executed)

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
| — | — | — |

---

## Surprises / notable deviations from design doc

| Date | What diverged | Why |
|---|---|---|
| — | — | — |

---

## Commits

| Date | Commit hash | Summary | Files |
|---|---|---|---|
| — | — | — | — |

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

### Live API probe evidence (AI-captured)

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
