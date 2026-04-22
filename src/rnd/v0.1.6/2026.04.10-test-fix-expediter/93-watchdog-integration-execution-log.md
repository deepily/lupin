# 93 — Watchdog Integration Execution Log

**Tracks**: Implementation step 13 of the plan — `TestSuiteCompletionWatchdog` creation, `running_fifo_queue.py` hook, and `main.py` init.

**Design doc**: [`09-watchdog-routing-plan.md`](09-watchdog-routing-plan.md)

**Precondition**: All TFE phases 0-6 complete. See [`92-tfe-phases-execution-log.md`](92-tfe-phases-execution-log.md).

**Regression gate**: `pytest src/tests/unit/ -v --tb=no -q | tail -5` + WebSocket smoke + integration tests.

---

## Step 13: TestSuiteCompletionWatchdog + queue hook + main init

**Status**: BLOCKED on TFE Phase 6 (step 12)

### Core watchdog

| Sub-step | Status | Commit | Notes |
|----------|--------|--------|-------|
| Create `src/cosa/rest/test_suite_completion_watchdog.py` | TODO | — | Parallel to DeadQueueWatchdog |
| `TestSuiteCompletionWatchdog.__init__` reads INI config | TODO | — | `test fix expediter auto fix enabled` |
| `evaluate()` with try/except — never raises | TODO | — | Watchdog must not crash queue consumer |
| `_evaluate_inner()` with 6 eligibility gates | TODO | — | enabled / job_type / snapshot valid / recursion guard / failure cap / repair tracker |
| `_compute_repair_key()` — tuple of `(job_id, sorted(suites))` | TODO | — | |
| `_dispatch_tfe()` constructs TestFixExpediterJob and pushes | TODO | — | Inherits user identity |
| `_notify_failure_cap_exceeded()` | TODO | — | Notify when N > max_cluster_seed_failures |

### Queue hook

| Sub-step | Status | Commit | Notes |
|----------|--------|--------|-------|
| Locate `running_fifo_queue.py` done-queue push path | TODO | — | ~line 540, parallel to `_evaluate_for_auto_fix` |
| Add new setter `set_test_suite_completion_watchdog(watchdog)` | TODO | — | |
| Add branch: `elif completed_job.status == "completed": watchdog.evaluate(completed_job)` | TODO | — | After done_queue.push, before WS emit |
| Log line for auto-dispatch | TODO | — | `[QUEUE] auto-dispatched TFE {id} from {ts_id}` |

### Main init

| Sub-step | Status | Commit | Notes |
|----------|--------|--------|-------|
| Import TestSuiteCompletionWatchdog in `src/fastapi_app/main.py` | TODO | — | |
| Construct singleton in startup event | TODO | — | Alongside DeadQueueWatchdog init |
| Wire into running_fifo_queue via new setter | TODO | — | |

### Unit tests

| Test | Status | Commit | Notes |
|------|--------|--------|-------|
| `test_test_suite_completion_watchdog.py` — 12 tests | TODO | — | All 6 gates, recursion guard, never-raises |

### Integration tests

| Test | Status | Commit | Notes |
|------|--------|--------|-------|
| `src/tests/integration/test_tfe_watchdog_dispatch.py` | TODO | — | End-to-end queue-level test |

### Regression checks

| Check | Status | Notes |
|-------|--------|-------|
| Full unit regression | TODO | ~973 baseline + new TFE tests |
| `./src/scripts/run-websocket-smoke-tests.sh` | TODO | 50/50 must pass |
| `./src/tests/run-integration-tests.sh --bg -v` | TODO | 44/44 (43 existing + 1 new) |
| `./src/scripts/run-e2e-ui-tests.sh --bg -v` | TODO | 285+12 must pass (queue change could regress) |

---

## WebSocket lineage event

Per design doc: emit a `tfe_auto_dispatched` event when a TFE is dispatched by the watchdog. Routed through existing `emit_job_state_transition()` — never manual WS send.

| Sub-step | Status | Notes |
|----------|--------|-------|
| Add event type to INI `websocket available events` | TODO | |
| Update splainer for the event | TODO | |
| `websocket-events.md` documentation | TODO | Per DOCUMENTATION TOUCHPOINTS in CLAUDE.md |
| `emit_job_state_transition()` extension or new method | TODO | |

---

## Deviations from plan

_(add entries here as they occur)_

---

## Open follow-ups

_(add entries here as discovered)_
