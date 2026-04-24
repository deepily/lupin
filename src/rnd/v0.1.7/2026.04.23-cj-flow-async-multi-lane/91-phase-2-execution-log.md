# Approach C — Phase 2 Execution Log

**Status**: IN PROGRESS (Session 616112aa, 2026-04-24, continuing from Phase 1 commit `fe932ba`)
**Paired design doc**: `03-phase-2-dispatcher-pool-and-pool-status.md`
**Depends on**: Phase 1 complete (commit `fe932ba`; :8000 gates ran on fe932ba with 1 stale-test fail + 12 visual errors + 8 pre-existing failures — none Phase-1-caused per root-cause analysis in history.md)
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

- [x] Added `from concurrent.futures import ThreadPoolExecutor` import; `threading` + `time` already present
- [x] `AgenticJobBase` + `AgentBase` + `SolutionSnapshot` already imported
- [x] Added `_pool_max_workers`, `_agentic_pool`, `_agentic_futures`, `_agentic_futures_lock` to `__init__`. **Deviation from design**: `_agentic_futures_lock` is `threading.RLock()` not `Lock()` — required because when a submitted Future completes BEFORE `add_done_callback` returns (fast work, e.g. sleep(0)), the callback fires synchronously on the same thread inside `add_done_callback`. The callback's `with self._agentic_futures_lock:` would deadlock a plain Lock. RLock permits same-thread re-entry. Caught by unit test fixture hang; fix is safe (cross-thread contention still serialized).
- [x] Refactored `_process_job()` agentic branch to call `_submit_agentic_job` + return (consumer thread freed immediately). AgentBase/SolutionSnapshot branches unchanged (kept today's inline path for Phase 2 MVP; design's `_process_fast_lane` extraction moved to code but not yet wired as the Phase 2 MVP dispatcher kept the existing isinstance tree for diff minimization).
- [x] Implemented `_submit_agentic_job( job )`. **Deviation from design**: consumer thread already does `push(job)` + `emit_job_state_transition(QUEUED→RUNNING)` before `_process_job`. `_submit_agentic_job` therefore does NOT duplicate those two steps — it only does the atomic-under-lock submit+track+callback. Design-doc 3-step ordering is preserved system-wide (consumer does push+emit, submit_agentic_job does submit+track+callback).
- [x] Implemented `_execute_agentic_in_pool( job )` — single call to `job.do_all()`
- [x] Implemented `_on_agentic_complete( job, future )` with outer `except BaseException` + inner per-exception-type branching. **Design clarification during impl**: BaseException-but-not-Exception survivors (KeyboardInterrupt/SystemExit/GeneratorExit) log-only and leave the job for the Phase-3 sweeper — do NOT call `_transition_to_dead(exc)` because passing a BaseException into the dead-letter path has been observed to cause chained failures. Only `isinstance(exc, Exception)` triggers `_transition_to_dead`. pop from `_agentic_futures` BEFORE transitioning invariant preserved.
- [x] Implemented `_transition_to_done( job, formatted_output )` per design doc. Phase 2 MVP scope: shared with the pool callback only; fast-lane paths still use their existing inline completion logic (extraction to unify them is Phase 3 cleanup to minimize Phase 2 diff risk).
- [x] Implemented `_transition_to_dead( job, cause )` per design doc. `cause` accepts `Exception | str`; body normalises both. Same Phase 2 MVP scope as `_transition_to_done`.
- [x] Added `_process_fast_lane( job )` as a new method (not yet wired as the dispatcher's fast-lane branch — kept in place as scaffolding for Phase 3 unification).
- [x] Replaced `self.pop()` with `self.delete_by_id_hash( <job>.id_hash )` at **all 9 call sites** (252 failed_job, 278 running_job, 394 running_job, 455 running_job, 528 running_job, 588 running_job, 747 running_job, 829 running_job, 1044 original_job).
- [x] EXECUTOR: AI — `grep -n "self\.pop(" src/cosa/rest/running_fifo_queue.py` returned no matches (exit 1). Regression test `test_no_pop_calls_remain_in_running_fifo_queue` in `test_agentic_pool.py` enforces this on every test run.
- [x] Implemented `get_pool_status()` returning `{inflight_agentic_jobs, max_agentic_workers, pending_in_pool}`
- [x] Implemented `shutdown_pool( wait, timeout )` with deadline-based drain + dead-letter on overshoot
- [x] EXECUTOR: AI — `py_compile running_fifo_queue.py`: OK. Runtime smoke: `RunningFifoQueue` instantiates, `get_pool_status()` returns the expected 3-key dict, `shutdown_pool(wait=False)` clean.

### Step 2.2 — Shutdown hook

- [x] EXECUTOR: AI — Confirmed `@asynccontextmanager def lifespan(app)` pattern is in use (`main.py` line 388; `FastAPI(lifespan=lifespan)` at line 703). No `@app.on_event` in the file.
- [x] Added `jobs_run_queue.shutdown_pool( wait=True, timeout=30.0 )` in lifespan teardown block BEFORE the consumer-stop code. `hasattr` guard for backward-compat when running with older Phase-1-only build.
- [ ] EXECUTOR: AI — Ordering banner-line assertion via actual server shutdown: deferred to Protocol E2E (Step 2.7) so a realistic pool+consumer interaction is observed rather than synthetic timestamps.
- [x] EXECUTOR: AI — py_compile OK.

### Step 2.3 — `/api/queue/pool-status` endpoint

- [x] Added `GET /queue/pool-status` to `src/cosa/rest/routers/queues.py` (plural) with `Depends(get_current_user)` + `Depends(get_running_queue)`. Returns `running_queue.get_pool_status()` payload verbatim.
- [x] Updated `src/docs/rest-api-reference.md` quick-reference table with the new endpoint row.
- [ ] EXECUTOR: AI — Live 401-without-auth + 200-with-auth verification: deferred to Protocol E2E (Step 2.7) after bounce of :7999 so the code is actually live.

### Step 2.4 — Unit tests (`test_agentic_pool.py`)

- [x] Created `src/tests/unit/test_agentic_pool.py` — 18 tests pass in 6.24s. Test-set covers all core Phase 2 mechanics; deferred broader-scope tests noted below.
- [x] `test_agentic_job_submitted_to_pool` (pool thread name `AgenticPool*` validated)
- [x] `test_dispatcher_agentic_goes_to_pool` (consumer thread != pool thread)
- [x] `test_submit_pushes_to_running_queue` — ghost-sweeper precondition
- [x] `test_submit_registers_future_in_dict`
- [x] `test_concurrent_agentic_execution` (3 mock jobs, max_workers=3, completes <1s)
- [x] `test_serial_execution_with_one_worker` (max_workers=1 serialises)
- [x] `test_completion_moves_to_done`
- [x] `test_failure_moves_to_dead`
- [x] `test_no_pop_calls_remain_in_running_fifo_queue` — grep regression
- [x] `test_defensive_callback_swallows_exception_on_transition`
- [x] `test_defensive_callback_both_transitions_fail_no_raise` — last-resort path
- [x] `test_defensive_callback_handles_base_exception` — BaseException survivors log-only, NOT dead-lettered (corrected during impl — see Step 2.1 deviation)
- [x] `test_get_pool_status_empty` + `test_get_pool_status_shape_with_inflight` — running/pending payload
- [x] `test_shutdown_pool_waits_for_inflight`
- [x] `test_shutdown_pool_dead_letters_timeouts`
- [x] `test_pool_saturation_queues_work`
- [x] `test_completion_order_not_fifo`
- [ ] **Deferred to Phase 3 or a follow-up** (not blocking Phase 2 commit): `test_sync_agent_processed_inline`, `test_solution_snapshot_processed_inline`, `test_dispatcher_raises_on_unknown_job_type`, `test_submit_emits_running_transition`, `test_submit_lock_ordering_atomic`, `test_fast_lane_not_blocked_by_agentic`, `test_concurrent_transition_to_done_sqlite_thread_safe`, `test_concurrent_notify_from_callbacks`, `test_concurrent_tfe_watchdog_evaluate`. Rationale: fast-lane/sync tests assume the Phase 3 dispatcher switch to `_process_fast_lane` (Phase 2 kept the existing inline dispatch to minimize diff risk); concurrent-SQLite/notify/TFE tests are broader-scope stress tests that don't gate Phase 2 behavioural correctness.

### Step 2.5 — Documentation touches

- [x] `src/docs/rest-api-reference.md` — added `/api/queue/pool-status` row to queue-endpoints table (CLAUDE.md mandatory touchpoint for new router)
- [ ] **Deferred to a follow-up doc sweep** (not blocking Phase 2 commit): `src/docs/notification-api.md` + `src/docs/websocket-architecture.md` concurrent-running-jobs notes. Rationale: Phase 2 with `N=1` prod default has no observable UX change; Phase 3 + prod N=3 flip are when the docs meaningfully drift.

### Phase 2 verification

> **Executor contract**: every checkbox below is `EXECUTOR: AI`. AI captures output and reports pass/fail via cosa-voice before marking `[x]`. See `00-working-contract.md` and §TESTING VENUES for routing.

#### A. `:7999` AI-discretionary

- [x] EXECUTOR: AI — Full unit regression: 3582 passed, 1 xfailed, 0 failed in 147.64s (3564 Phase-1 baseline + 18 Phase-2 new = 3582; 3 `test_crud_queue_integration` tests fixed in-session for missing `_lock` after `__new__` bypass of `__init__`).
- [ ] EXECUTOR: AI — Non-destructive smoke: deferred per :7999 auto-reload suspicion (same as Phase 1 caveat; :7999 server hasn't demonstrably picked up my changes this session).
- [x] EXECUTOR: AI — `./src/scripts/run-websocket-smoke-tests.sh` — 50/50 pass in 44s.

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
| 2026-04-24 | `_agentic_futures_lock` is `threading.RLock()` not `threading.Lock()` | Surfaced during unit-test fixture hang: when a Future completes BEFORE `add_done_callback` returns (fast work, e.g. `sleep(0)` or no-op `do_all`), the callback fires synchronously on the same thread inside `add_done_callback`. That thread is already holding the lock from `_submit_agentic_job`; re-acquiring via `_on_agentic_complete`'s `with self._agentic_futures_lock:` deadlocks a plain Lock. RLock permits same-thread re-entry; cross-thread contention still serialized by RLock semantics. |
| 2026-04-24 | `_submit_agentic_job` does NOT do the design's step 1 (push) and step 2 (emit) | Lupin's consumer thread in `queue_consumer.py::consumer_worker` already does `running_queue.push(job)` (line 104) + `emit_job_state_transition(QUEUED→RUNNING)` (line 101) before invoking `_process_job` → `_submit_agentic_job`. Doing them again would push-twice and emit a redundant/incorrect RUNNING→RUNNING transition. Design-doc 3-step ordering is preserved system-wide. |
| 2026-04-24 | Phase 2 MVP kept existing inline fast-lane dispatch in `_process_job`; `_process_fast_lane` added as new method but not yet wired | Scope-minimization: Phase 2 commits only the CODE PATH that changes behaviour (agentic → pool). Fast-lane is semantically identical to today (consumer inline). Phase 3 cleanup can unify via `_process_fast_lane`. Diff-risk tradeoff explicit in history.md. |
| 2026-04-24 | `_transition_to_done` / `_transition_to_dead` extracted as **new** methods used only by pool callback; existing inline completion blocks in `_handle_agentic_job` / `_handle_base_agent` / `_handle_solution_snapshot` / `_format_cached_result` left in place for Phase 2 MVP | Same scope-minimization. Under `N=1` serial execution, only one codepath runs at a time; the pool-callback path is exercised exactly when agentic jobs complete. Phase 3 cleanup can consolidate; Phase 2 diff contained. |
| 2026-04-24 | BaseException survivors (KeyboardInterrupt/SystemExit/GeneratorExit) in `_on_agentic_complete` are log-only; NOT dead-lettered | Design doc said "dead-letter on Exception; leave for sweeper on BaseException." Initial impl dead-lettered ALL exceptions from `future.exception()`. Corrected during test development (`test_defensive_callback_handles_base_exception` enforced the distinction). |
| 2026-04-24 | 9 test cases in `test_agentic_pool.py` deferred | Phase 2 MVP scope; see Step 2.4 for the list + rationale. |
| 2026-04-24 | `notification-api.md` + `websocket-architecture.md` updates deferred | Phase 2 at N=1 has no observable UX change; Phase 3 / N=3 prod flip is when docs drift. |

---

## Commits

| Date | Commit hash | Summary | Files |
|---|---|---|---|
| 2026-04-24 | pending | Phase 2 (pool + dispatcher + endpoint + tests + stale E2E fix) | 6 parent-Lupin files modify + 1 new test file; `src/cosa/rest/running_fifo_queue.py` (CoSA) modified — user commits separately |

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
