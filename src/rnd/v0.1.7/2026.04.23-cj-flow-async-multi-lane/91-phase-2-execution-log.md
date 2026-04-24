# Approach C — Phase 2 Execution Log

**Status**: NOT STARTED (skeleton only — populate as implementation proceeds)
**Paired design doc**: `03-phase-2-dispatcher-pool-and-pool-status.md`
**Depends on**: Phase 1 complete (all checkboxes `[x]` in `90-phase-1-execution-log.md`)
**Branch**: `wip-v0.1.7-2026.04.22-spit-and-polish-for-cjflow-tfe-and-bfe`

---

## Progress ledger

> **Implementation steps below (Steps 2.0 – 2.5) are EXECUTOR: AI throughout** — these are code-writing checkboxes. Verification steps in the "Phase 2 verification" and "Phase 2 Protocol E2E" sections later in this file carry their own per-line `EXECUTOR:` tags.

### Step 2.0 — Pre-flight: confirm DeepResearch dry-run is AI-runnable (no real API spend)

Phase 2 (and Phase 3) Protocol E2E fires `POST /api/push` for "DeepResearch dry-run" twice per run. If no dry-run mode exists, each run burns real Anthropic spend (~$0.50–$5 per DR).

- [ ] EXECUTOR: AI — AI greps `src/cosa/agents/deep_research/` and the `/api/push` handler for a `dry_run` / `dry-run` / `dry_run_mode` parameter or construction flag. AI reports the finding (present or absent) in "Verification results" with file:line references.
- [ ] EXECUTOR: AI — If absent, AI surfaces the gap via cosa-voice `ask_multiple_choice`: (a) add `dry_run=true` support to `DeepResearchJob` (real fixture-backed replacement of LLM calls) — ~30min work; (b) replace Protocol E2E with a mock `AgenticJobBase` subclass that sleeps 30s (proves pool mechanics without spend) — ~15min work. Await user choice before Protocol E2E runs.
- [ ] EXECUTOR: AI — Once the mechanism is confirmed, AI documents the exact `/api/push` payload (including `user_id`, `question`, any `dry_run` flag) and captures it as a reusable helper in `src/tests/smoke/utilities.py` (or nearest equivalent location — grep `src/tests/smoke/` for existing helper-module conventions). Phase 2 and Phase 3 Protocol E2Es reuse this helper; do not duplicate the payload inline.

### Step 2.1 — Dispatcher refactor in `RunningFifoQueue`

- [ ] Add `from concurrent.futures import ThreadPoolExecutor` + `import threading, time` imports
- [ ] Add `from cosa.agents.agentic_job_base import AgenticJobBase` (may already exist)
- [ ] Add `_pool_max_workers`, `_agentic_pool`, `_agentic_futures`, `_agentic_futures_lock` to `__init__` per the ordered sequence in `03-phase-2-*.md` Step 2.1 §"New `__init__` fields"
- [ ] Refactor `_process_job()` to dispatch by `isinstance( job, AgenticJobBase )` → `_submit_agentic_job`; `isinstance( job, (AgentBase, SolutionSnapshot) )` → `_process_fast_lane`; ELSE raise `TypeError` (no silent fallthrough)
- [ ] Implement `_submit_agentic_job( job )` with the 3-step ordering: (1) `self.push(job)` into running_queue; (2) `emit_job_state_transition(job, from_state="todo", to_state="running")`; (3) ACQUIRE `_agentic_futures_lock` → `submit()` → assign `_agentic_futures[id_hash]` → `add_done_callback` — all inside the lock to close the fast-future race
- [ ] Implement `_execute_agentic_in_pool( job )` — single call to `job.do_all()`, no post-processing in this layer
- [ ] Implement `_on_agentic_complete( job, future )` with **outer `except BaseException`** (belt for KeyboardInterrupt/SystemExit survivors → log + leave for Phase-3 sweeper); **inner `except Exception`** (suspenders for dead-letter attempt); pop from `_agentic_futures` BEFORE transitioning (load-bearing invariant per 03 Step 2.1 callout)
- [ ] Implement `_transition_to_done( job, formatted_output )` — extract from `running_fifo_queue.py` lines 411–480 (agentic success) + 725–751 (agent success) + 1044 (cache-hit). Reads derived values from `job.*` attributes (do_all() side effects); formatted_output used for I/O logging only.
- [ ] Implement `_transition_to_dead( job, cause )` — extract from `running_fifo_queue.py` lines 482–532 (status-check fail) + 534–592 (exception) + 252 (outer crash) + 278 (error case). `cause` may be `Exception | str`; body normalises both.
- [ ] Implement `_process_fast_lane( job )` — internally dispatches by isinstance to `_handle_base_agent` (with cache-check + CRUD sub-branch) or `_handle_solution_snapshot`. Preserves today's exact fast-lane behaviour; only pop() calls change.
- [ ] Replace `self.pop()` with `self.delete_by_id_hash( running_job.id_hash )` at **ALL 9 CALL SITES** in `running_fifo_queue.py` per the table in `03-phase-2-*.md` Step 2.1: lines 252, 278, 394, 455, 528, 588, 747, 829, 1044. Not just agentic paths — fast-lane too (fast-lane runs concurrently with pool callbacks under Phase 2).
- [ ] EXECUTOR: AI — `grep -n "self\.pop(" src/cosa/rest/running_fifo_queue.py` — AI asserts NO MATCHES (zero output). Regression-test `test_no_pop_calls_remain_in_running_fifo_queue` in the unit suite enforces this at every subsequent test run.
- [ ] Implement `get_pool_status()` returning `{inflight_agentic_jobs, max_agentic_workers, pending_in_pool}` (note renamed field — `inflight` replaces the previous `active` to disambiguate running vs submitted)
- [ ] Implement `shutdown_pool( wait, timeout )` with deadline-based drain + dead-letter on overshoot
- [ ] EXECUTOR: AI — `python -c "import py_compile; py_compile.compile('src/cosa/rest/running_fifo_queue.py', doraise=True)"` — AI asserts exit code 0, reports stdout verbatim in "Verification results"

### Step 2.2 — Shutdown hook

- [ ] EXECUTOR: AI — AI greps `src/fastapi_app/main.py` for existing shutdown-pattern (`@app.on_event("shutdown")` vs `@asynccontextmanager def lifespan(app)` + `FastAPI(lifespan=...)`). AI reports which pattern is in use; new hook follows the same style.
- [ ] Add `running_queue.shutdown_pool( wait=True, timeout=30.0 )` call to the existing shutdown/lifespan-teardown block in `src/fastapi_app/main.py` — placed BEFORE the consumer-stop code AND BEFORE any HTTP socket close, so in-flight pool workers can still emit WS events as they finish
- [ ] EXECUTOR: AI — `shutdown_pool` and the consumer-stop path both emit distinguishable banner lines (`shutdown_pool returning`, `consumer thread stopped`). AI submits a long-running mock agentic job, triggers server shutdown, greps captured stderr/log, asserts the `shutdown_pool returning` timestamp precedes `consumer thread stopped` timestamp; reports both timestamps verbatim.
- [ ] EXECUTOR: AI — `python -c "import py_compile; py_compile.compile('src/fastapi_app/main.py', doraise=True)"` — AI asserts exit code 0

### Step 2.3 — `/api/queue/pool-status` endpoint

- [ ] Router file is `src/cosa/rest/routers/queues.py` (plural — confirmed in fitness review). Add `GET /api/queue/pool-status` endpoint there.
- [ ] Endpoint requires auth via `current_user: dict = Depends(get_current_user)` — matches sibling convention (every other `/api/queue/*` endpoint uses this). Import `from cosa.rest.auth import get_current_user` is already present in the file at line 23.
- [ ] Endpoint returns `running_queue.get_pool_status()` payload — keys `{inflight_agentic_jobs, max_agentic_workers, pending_in_pool}`
- [ ] EXECUTOR: AI — `python -c "import requests; r = requests.get('http://localhost:7999/api/queue/pool-status'); assert r.status_code == 401, f'expected 401 without auth, got {r.status_code}'"` — AI asserts unauthenticated request is rejected with 401 (regression for the auth requirement).
- [ ] EXECUTOR: AI — using a valid JWT (see `src/tests/AUTH-TESTING-GUIDE.md` pattern), `python -c "import requests; h = {'Authorization': f'Bearer {TOKEN}'}; r = requests.get('http://localhost:7999/api/queue/pool-status', headers=h); assert r.status_code == 200; body = r.json(); assert set(body.keys()) >= {'inflight_agentic_jobs', 'max_agentic_workers', 'pending_in_pool'}; print(body)"` — AI asserts 200 + all three keys present; reports body verbatim.

### Step 2.4 — Unit tests (`test_agentic_pool.py`)

- [ ] Create `src/tests/unit/test_agentic_pool.py`
- [ ] `test_agentic_job_submitted_to_pool`
- [ ] `test_sync_agent_processed_inline`
- [ ] `test_solution_snapshot_processed_inline`
- [ ] `test_dispatcher_raises_on_unknown_job_type`
- [ ] `test_submit_pushes_to_running_queue` — ghost-sweeper precondition
- [ ] `test_submit_emits_running_transition` — UX regression
- [ ] `test_submit_lock_ordering_atomic` — fast-future race regression
- [ ] `test_concurrent_agentic_execution` (3 mock jobs, max_workers=3, total <1s)
- [ ] `test_fast_lane_not_blocked_by_agentic`
- [ ] `test_completion_moves_to_done`
- [ ] `test_failure_moves_to_dead`
- [ ] `test_no_pop_calls_remain_in_running_fifo_queue` — grep regression
- [ ] `test_defensive_callback_swallows_exception_on_transition`
- [ ] `test_defensive_callback_both_transitions_fail_no_raise` — last-resort path
- [ ] `test_defensive_callback_handles_base_exception` — KeyboardInterrupt/SystemExit survivors
- [ ] `test_get_pool_status_accurate` — 3-state payload (running / pending / done)
- [ ] `test_shutdown_pool_waits_for_inflight`
- [ ] `test_shutdown_pool_dead_letters_timeouts`
- [ ] `test_pool_saturation_queues_work`
- [ ] `test_completion_order_not_fifo`
- [ ] `test_concurrent_transition_to_done_sqlite_thread_safe` — SQLite WAL under concurrent callbacks
- [ ] `test_concurrent_notify_from_callbacks` — TTS + WS emit under concurrent callbacks
- [ ] `test_concurrent_tfe_watchdog_evaluate` — TFE watchdog under concurrent callbacks

### Step 2.5 — Documentation touches

- [ ] `src/docs/notification-api.md` — note concurrent `running` cards
- [ ] `src/docs/websocket-architecture.md` — note interleaved `job_state_transition` events
- [ ] `src/docs/rest-api-reference.md` — add `/api/queue/pool-status` row

### Phase 2 verification

> **Executor contract**: every checkbox below is `EXECUTOR: AI`. AI captures output and reports pass/fail via cosa-voice before marking `[x]`. See `00-working-contract.md` and §TESTING VENUES for routing.

#### A. `:7999` AI-discretionary

- [ ] EXECUTOR: AI — Full unit regression passes: `pytest src/tests/unit/ -v` (915 baseline + Phase 1 + Phase 2 new tests)
- [ ] EXECUTOR: AI — `/smoke-test-remediation SELECTIVE` (non-destructive only) — no regressions
- [ ] EXECUTOR: AI — `./src/scripts/run-websocket-smoke-tests.sh` — 50/50

#### B. `:8000` scheduled monopolize-mode (AI submits via `/api/test-suite/submit` after user slot-check)

- [ ] EXECUTOR: AI — E2E UI via `POST /api/test-suite/submit {"test_types": "e2e_ui", "scheduled_at": "<user-confirmed>"}` (local fallback: `./src/scripts/run-e2e-ui-tests.sh --bg -v`) — 285/285
- [ ] EXECUTOR: AI — Integration (final gate) via `POST /api/test-suite/submit {"test_types": "integration", "scheduled_at": "<user-confirmed>"}` (local fallback: `./src/tests/run-integration-tests.sh --bg -v`) — 43/43

### Phase 2 Protocol E2E — mandatory (AI-executed)

"Protocol E2E" = "not yet in pytest." Every checkbox below is `EXECUTOR: AI`, executed via the API against `:7999`:

- [ ] EXECUTOR: AI — `LUPIN_ENV=dev` is set for this server process so the `[Lupin: Dev Overrides]` block loads. Set or confirm `cj flow max concurrent agentic jobs = 3` in the dev-overrides block (not the baseline).
- [ ] EXECUTOR: AI — Touch a Python file in the FastAPI reload-watch set (e.g. `touch src/cosa/rest/running_fifo_queue.py`) to force a reload; wait for reload log line. **INI edits alone do not trigger reload** — `_pool_max_workers` is captured at `__init__`, so the pool needs a fresh `__init__` to pick up the new value.
- [ ] EXECUTOR: AI — Verify the resize happened: GET `/api/queue/pool-status` with valid auth; assert `max_agentic_workers == 3`. If still `1`, the reload didn't fire — ask user for a manual restart before proceeding.
- [ ] EXECUTOR: AI — **Warmup**: POST /api/push (MathAgent, trivial query); poll `/api/get-queue/done` until returned; discard result. Warms fast-lane Phi-4-GPTQ path so the measured MathAgent below isn't confounded by cold-GPU load (3–8s).
- [ ] EXECUTOR: AI — POST /api/push × 2 (DeepResearch dry-run — uses the mechanism confirmed in Step 2.0, via the shared helper in `src/tests/smoke/utilities.py`) back-to-back; capture both `job_id`s
- [ ] EXECUTOR: AI — POST /api/push (MathAgent query) during agentic runs; capture `job_id`
- [ ] EXECUTOR: AI — Poll `/api/get-queue/done` until MathAgent completes; assert elapsed < 5s
- [ ] EXECUTOR: AI — GET `/api/queue/running` during research runs; assert both DR `job_id`s present simultaneously
- [ ] EXECUTOR: AI — GET `/api/queue/pool-status` mid-run with valid auth; assert payload `{inflight_agentic_jobs: 2, max_agentic_workers: 3, pending_in_pool: 0}` (note renamed field `inflight_agentic_jobs` replacing legacy `active_agentic_jobs`)
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

# pool-status endpoint smoke (with auth — endpoint requires Depends(get_current_user))
# AI asserts status==200 AND all 3 keys present under the renamed field set.
$ python -c "import requests, os; h={'Authorization': f'Bearer {os.environ[\"LUPIN_JWT\"]}'}; r=requests.get('http://localhost:7999/api/queue/pool-status', headers=h); assert r.status_code == 200; body=r.json(); assert set(body.keys()) >= {'inflight_agentic_jobs', 'max_agentic_workers', 'pending_in_pool'}; print(body)"
(TBD — expect a dict with keys {inflight_agentic_jobs, max_agentic_workers, pending_in_pool})

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
# Pool status during mixed workload — captured via requests.get (see shape-check stanza above, line ~137)
# curl is prohibited in committed docs per project CLAUDE.md testing anti-patterns.

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
