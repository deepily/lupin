# Approach C — Phase 2 Execution Log

**Status**: NOT STARTED (skeleton only — populate as implementation proceeds)
**Paired design doc**: `02-phase-2-dispatcher-pool-and-pool-status.md`
**Depends on**: Phase 1 complete (all checkboxes `[x]` in `90-phase-1-execution-log.md`)
**Branch**: `wip-v0.1.7-2026.04.22-spit-and-polish-for-cjflow-tfe-and-bfe`

---

## Progress ledger

### Step 2.1 — Dispatcher refactor in `RunningFifoQueue`

- [ ] Add `from concurrent.futures import ThreadPoolExecutor` + `import threading, time` imports
- [ ] Add `from cosa.agents.agentic_job_base import AgenticJobBase` (may already exist)
- [ ] Add `_pool_max_workers`, `_agentic_pool`, `_agentic_futures`, `_agentic_futures_lock` to `__init__`
- [ ] Refactor `_process_job()` to dispatch by `isinstance( job, AgenticJobBase )`
- [ ] Implement `_submit_agentic_job( job )`
- [ ] Implement `_execute_agentic_in_pool( job )`
- [ ] Implement `_on_agentic_complete( job, future )` **with defensive try/except outer wrap**
- [ ] Implement `_transition_to_done( job, formatted_output )` (extract from existing inline logic)
- [ ] Implement `_transition_to_dead( job, exception )` (extract from existing inline logic)
- [ ] Implement `_process_fast_lane( job )` (extract from existing inline logic)
- [ ] Replace `self.pop()` with `self.delete_by_id_hash( job.id_hash )` in ALL agentic paths
- [ ] Implement `get_pool_status()`
- [ ] Implement `shutdown_pool( wait, timeout )` with deadline-based drain + dead-letter on overshoot
- [ ] `py_compile` verification passes for `running_fifo_queue.py`

### Step 2.2 — Shutdown hook

- [ ] Add `running_queue.shutdown_pool( wait=True, timeout=30.0 )` call to `src/fastapi_app/main.py` shutdown event
- [ ] Verify ordering: pool drains BEFORE consumer thread stops
- [ ] `py_compile` verification passes for `main.py`

### Step 2.3 — `/api/queue/pool-status` endpoint

- [ ] Identify correct router file (likely `src/cosa/rest/routers/queue.py` — confirm during impl)
- [ ] Add `GET /api/queue/pool-status` endpoint
- [ ] Endpoint returns `running_queue.get_pool_status()` payload
- [ ] No auth required (read-only; matches other `/api/queue/*` read endpoints — verify during impl)
- [ ] Smoke: curl-equivalent via Python (`requests.get("http://localhost:7999/api/queue/pool-status")`) returns correct shape

### Step 2.4 — Unit tests (`test_agentic_pool.py`)

- [ ] Create `src/tests/unit/test_agentic_pool.py`
- [ ] `test_agentic_job_submitted_to_pool`
- [ ] `test_sync_agent_processed_inline`
- [ ] `test_concurrent_agentic_execution` (3 mock jobs, max_workers=3, total <1s)
- [ ] `test_fast_lane_not_blocked_by_agentic`
- [ ] `test_completion_moves_to_done`
- [ ] `test_failure_moves_to_dead`
- [ ] `test_delete_by_id_hash_not_pop`
- [ ] `test_defensive_callback_swallows_exception_on_transition`
- [ ] `test_get_pool_status_accurate`
- [ ] `test_shutdown_pool_waits_for_inflight`
- [ ] `test_shutdown_pool_dead_letters_timeouts`
- [ ] `test_pool_saturation_queues_work`
- [ ] `test_completion_order_not_fifo`

### Step 2.5 — Documentation touches

- [ ] `src/docs/notification-api.md` — note concurrent `running` cards
- [ ] `src/docs/websocket-architecture.md` — note interleaved `job_state_transition` events
- [ ] `src/docs/rest-api-reference.md` — add `/api/queue/pool-status` row

### Phase 2 verification

> **Executor contract**: every checkbox below is `EXECUTOR: AI`. The AI runs against `:7999`, captures output, and reports pass/fail via cosa-voice before marking `[x]`. See `00-working-contract.md`.

- [ ] Full unit regression passes (`pytest src/tests/unit/ -v`)
- [ ] `/smoke-test-remediation FULL` — no regressions
- [ ] `./src/scripts/run-websocket-smoke-tests.sh` — 50/50
- [ ] `./src/scripts/run-e2e-ui-tests.sh --bg -v` — 285/285 (`--bg` MANDATORY)
- [ ] `./src/tests/run-integration-tests.sh --bg -v` — 43/43 (`--bg` MANDATORY, final gate)

### Phase 2 Protocol E2E — mandatory (AI-executed)

"Protocol E2E" = "not yet in pytest." Every checkbox below is `EXECUTOR: AI`, executed via the API against `:7999`:

- [ ] EXECUTOR: AI — `cj flow max concurrent agentic jobs = 3` set in `src/conf/lupin-app.ini` (`:7999` auto-reloads)
- [ ] EXECUTOR: AI — POST /api/push × 2 (DeepResearch dry-run) back-to-back; capture both `job_id`s
- [ ] EXECUTOR: AI — POST /api/push (MathAgent query) during agentic runs; capture `job_id`
- [ ] EXECUTOR: AI — Poll `/api/get-queue/done` until MathAgent completes; assert elapsed < 5s
- [ ] EXECUTOR: AI — GET `/api/queue/running` during research runs; assert both DR `job_id`s present simultaneously
- [ ] EXECUTOR: AI — GET `/api/queue/pool-status` mid-run; assert payload `{active_agentic_jobs: 2, max_agentic_workers: 3, pending_in_pool: 0}`
- [ ] EXECUTOR: AI — Poll `/api/get-queue/done` until both DRs complete; assert `running_queue` size returns to 0
- [ ] EXECUTOR: AI — Server shutdown cleanly; on next start, assert no phantom `running` rows
- [ ] EXECUTOR: AI — Report all observed values to user via cosa-voice `notify`

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
$ python -c "import py_compile; py_compile.compile( 'src/cosa/rest/running_fifo_queue.py', doraise=True )"
$ python -c "import py_compile; py_compile.compile( 'src/fastapi_app/main.py', doraise=True )"
(TBD)

# import chain
$ PYTHONPATH=src python -c "from cosa.rest.running_fifo_queue import RunningFifoQueue; print('OK')"
(TBD)

# new unit tests
$ pytest src/tests/unit/test_agentic_pool.py -v
(TBD — expect ~13 tests passing)

# full unit regression
$ pytest src/tests/unit/ -v
(TBD — expect 915 baseline + Phase 1 + Phase 2 new tests passing)

# pool-status endpoint smoke
$ python -c "import requests; print(requests.get('http://localhost:7999/api/queue/pool-status').json())"
(TBD — expect {'active_agentic_jobs': ..., 'max_agentic_workers': ..., 'pending_in_pool': ...})

# WebSocket smoke
$ ./src/scripts/run-websocket-smoke-tests.sh
(TBD — expect 50/50)

# E2E UI (background)
$ ./src/scripts/run-e2e-ui-tests.sh --bg -v
$ tail -20 /tmp/e2e-ui-latest.log
(TBD — expect 285/285)

# Integration (final gate, background)
$ ./src/tests/run-integration-tests.sh --bg -v
$ tail -20 /tmp/integration-latest.log
(TBD — expect 43/43)
```

### Protocol E2E evidence (AI-captured)

```
# Pool status during mixed workload
$ curl http://localhost:7999/api/queue/pool-status  # acceptable for manual debug only; not test harness
(TBD)

# Timing observations
DeepResearch-1 started:  (TBD)
DeepResearch-2 started:  (TBD)
MathAgent submitted:     (TBD)
MathAgent returned:      (TBD)  — expect <5s delta from submission
DeepResearch-1 finished: (TBD)
DeepResearch-2 finished: (TBD)
```

---

## Phase 2 sign-off criteria

- All checkboxes above marked `[x]`.
- Protocol E2E observations recorded (AI-captured values via cosa-voice report).
- Verification results filled in with actual command output.
- Commit hash(es) recorded.
- No blockers outstanding.
- Ready to hand off to Phase 3.
