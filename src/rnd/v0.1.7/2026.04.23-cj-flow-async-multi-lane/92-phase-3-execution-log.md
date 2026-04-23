# Approach C — Phase 3 Execution Log

**Status**: NOT STARTED (skeleton only — populate as implementation proceeds)
**Paired design doc**: `03-phase-3-ghost-watchdog-and-e2e.md`
**Depends on**: Phases 1 and 2 complete (all checkboxes `[x]` in `90-phase-1-execution-log.md` and `91-phase-2-execution-log.md`)
**Branch**: `wip-v0.1.7-2026.04.22-spit-and-polish-for-cjflow-tfe-and-bfe`

---

## Progress ledger

### Step 3.1 — Ghost-job watchdog

- [ ] Add `cj flow ghost job sweep interval seconds = 30` to `src/conf/lupin-app.ini`
- [ ] Add matching splainer entry
- [ ] Add `_ghost_job_sweeper_thread` + `_ghost_job_sweeper_stop_event` to `RunningFifoQueue.__init__`
- [ ] Implement `_ghost_job_sweep()` method
- [ ] Implement sweeper thread main loop (read interval from INI, use stop_event.wait for early wakeup)
- [ ] Start sweeper in `__init__` after pool is up
- [ ] Stop sweeper as FIRST step of `shutdown_pool()`
- [ ] `py_compile` verification passes

### Step 3.2 — `ApiResourceManager` caller migration (Deep Research)

- [ ] Flesh out `ApiResourceManager.acquire()` for `anthropic_web_search`: lazy-import `WebSearchRateLimiter`, delegate
- [ ] Flesh out `ApiResourceManager.record_call()` for `anthropic_web_search`
- [ ] Migrate `src/cosa/agents/deep_research/api_client.py::_call_with_retry()` to call `ApiResourceManager.get_instance()`
- [ ] Remove now-dead per-agent `_rate_limiter` field (unless used elsewhere — confirm during impl)
- [ ] Manual smoke: trigger a Deep Research dry-run, confirm no regressions in behavior
- [ ] `py_compile` verification passes on `api_client.py` + `api_resource_manager.py`

### Step 3.3 — `/api/queue/pool-status` enrichment

- [ ] Endpoint response includes `api_resource_manager` key from `ApiResourceManager.get_instance().get_status()`
- [ ] `anthropic_web_search` section shows real sliding-window state
- [ ] Other providers show `{"provider_wait_state": "passthrough"}`
- [ ] Smoke: endpoint returns new shape

### Step 3.4 — Watchdog tests (in `test_agentic_pool.py`)

- [ ] `test_ghost_job_detected_and_dead_lettered`
- [ ] `test_ghost_job_sweep_idempotent`
- [ ] `test_ghost_job_sweep_ignores_live_futures`
- [ ] `test_ghost_job_sweeper_stops_on_shutdown`

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

- [ ] **1. py_compile**: compile all modified `.py` files individually
- [ ] **2. Unit**: `pytest src/tests/unit/ -v` — 915 baseline + Phase 1/2/3 new tests all green
- [ ] **3. Smoke**: `/smoke-test-remediation FULL` — no regressions
- [ ] **4. WebSocket smoke**: `./src/scripts/run-websocket-smoke-tests.sh` — 50/50
- [ ] **5. E2E UI** (`--bg` MANDATORY): `./src/scripts/run-e2e-ui-tests.sh --bg -v` — 285/285
- [ ] **6. Integration (final gate)** (`--bg` MANDATORY): `./src/tests/run-integration-tests.sh --bg -v` — 43/43

### Phase 3 manual concurrent-happy-path E2E (REQUIRED)

- [ ] Dev `:7999` restarted with `cj flow max concurrent agentic jobs = 3`
- [ ] Submit two DeepResearch dry-run jobs sequentially
- [ ] Submit MathAgent ("17 * 23?") during agentic runs
- [ ] Math returns in <5s
- [ ] Both research jobs show `running` simultaneously
- [ ] `/api/queue/pool-status` mid-run returns expected shape (including `api_resource_manager` section)
- [ ] Both research jobs complete; running_queue returns to 0
- [ ] No stuck `running` rows
- [ ] Server shutdown clean; next start has no phantom rows

### Serial-fallback re-verification

- [ ] Restart with `= 1`; submit same workload; observe serial processing preserved

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

### Manual E2E evidence

```
Config at test time: cj flow max concurrent agentic jobs = (3 | 1)

# Concurrent run
DeepResearch-1 submitted:  (TBD)
DeepResearch-1 running:    (TBD)
DeepResearch-2 submitted:  (TBD)
DeepResearch-2 running:    (TBD)
MathAgent submitted:       (TBD)
MathAgent returned:        (TBD)  — expect <5s
Pool-status mid-run:       (TBD)  — expect {active: 2, max: 3, pending: 0, api_resource_manager: {...}}
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
- Manual E2E observations recorded.
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
  - [ ] Prod default bump `cj flow max concurrent agentic jobs = 1 → 3` (separate deliberate action)
