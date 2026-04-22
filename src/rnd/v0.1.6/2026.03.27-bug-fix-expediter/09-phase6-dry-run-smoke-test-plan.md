# BFE Phase 6 — Dry-Run Integration Smoke Test

**Created**: 2026-04-10
**Status**: READY FOR IMPLEMENTATION
**Prefix**: [LUPIN]
**Parent plan**: `src/rnd/v0.1.6/2026.03.27-bug-fix-expediter/08-phase6-automated-repair-loop-plan.md` — Step 8

---

## Context

BFE Phase 6 (automated repair loop) is substantially implemented — more than the parent plan doc
suggests. What remains before the live E2E (Step 9) is a **deterministic, $0-cost, CI-gateable
integration smoke test** that exercises the full loop: dead-queue watchdog → BFE submission →
diagnose/propose/fix (simulated) → resubmit original job. Without this, the only way to validate
the loop is a live run with a known-bad mutation, which is slow, costs money, and is hard to
regression-test after every watchdog or resubmit change.

**Goal**: A smoke test that follows Lupin's established dry-run convention (no monkey patching,
no new test flags, no production branches that exist only for tests), exercises the real watchdog
and real resubmit path end-to-end, and costs $0 per run.

---

## Current-State Findings

### Phase 6 code is further along than the parent plan states

| Component | Actual status (2026-04-10) |
|-----------|----------------------------|
| `src/cosa/rest/dead_queue_watchdog.py` | ✓ 639 lines — `evaluate()`, `_submit_bfe()`, `_direct_retry()`, cooldown, smoke test |
| `src/cosa/rest/repair_attempt_tracker.py` | ✓ 425 lines — `RepairChain`, semantic dedup, circuit breakers |
| `src/cosa/agents/bug_fix_expediter/job.py:_resubmit_original_job()` | ✓ Lines 302-421 — wired after fix at lines 268-275 |
| `BFEPhase.RESUBMITTING` / `FixResult.resubmitted_job_id` | ✓ Both present in `state.py` |
| `running_fifo_queue.py:_evaluate_for_auto_fix()` | ✓ Hook wired at lines 464, 524 |
| INI `[Lupin: Auto Fix]` section | ✓ 6 keys, `auto fix enabled = false` default |
| `test_bfe_phase6.py` unit tests | ✓ ~340 lines covering classification, eligibility, cooldown, state model, `evaluate()` branches |
| `test_repair_integration.py` | ✓ Covers tracker integration |
| **Integration dry-run smoke test** | ✗ **Missing — this plan delivers it** |

### The dry-run convention (from exploration of DR, podcast, presentation, expediter, BFE)

Every agentic job in Lupin follows the same three-part pattern:

1. `dry_run: bool = False` constructor parameter on the job class
2. Separate `async _execute_dry_run()` method that fires breadcrumb notifications and returns canned results
3. REST layer accepts `dry_run=true` and threads it through `agentic_job_factory.create_agentic_job()`

No part of the codebase uses monkey patching or test-only flags for this.

### Two gaps block the smoke test today

**Gap 1**: BFE's existing `_execute_dry_run()` (`job.py:423-459`) fires breadcrumbs and returns
**before** reaching `_resubmit_original_job()` at line 302. So `dry_run=True` on BFE covers phases
0-5 but never exercises Phase 6.

**Gap 2**: The expediter mock-job pipeline (`/api/mock-job/submit`) submits jobs that
**succeed** in dry-run. There is no failure-injection mechanism, so nothing lands in the dead
queue, so the Phase 6 watchdog never fires.

### Reusable pieces (no new infrastructure needed)

| Component | Path | Purpose |
|-----------|------|---------|
| `/api/mock-job/submit` endpoint | `src/cosa/rest/routers/mock_job.py:216-339` | Voice-command → expeditor → dry-run job pipeline |
| `test_expeditor_mock_job_smoke.py` | `src/tests/smoke/` | 13-scenario harness pattern (the reuse target) |
| `InteractiveSmokeTest` / `LivePipelineTestBase` | `src/tests/smoke/utilities/` | Base class with login, polling, cleanup |
| `create_agentic_job()` | `src/cosa/rest/agentic_job_factory.py:78-127` | Already threads `dry_run` through `args_dict` |
| `running_fifo_queue._evaluate_for_auto_fix()` | Lines 464, 524 | Calls `watchdog.evaluate()` on every dead-queue push — already wired |
| `package_dead_job()` | `src/cosa/agents/bug_fix_expediter/dead_job_packager.py:14` | Reads `job_history` by id_hash |
| `LUPIN_TEST_INTERACTIVE_MOCK_JOBS_*` env vars | `CLAUDE.md` | Auth pattern for smoke tests |

---

## Recommended Approach

Three small production changes + one new smoke test. Every change follows the existing dry-run
convention. No monkey patching. No test-only code paths in production.

### Change 1 — Failure injection on the mock-job endpoint

**File**: `src/cosa/rest/routers/mock_job.py` (around line 216 `_handle_expeditor_test` and the
`MockJobSubmitRequest` model near the top)

- Add optional `force_failure_mode: Literal["code_bug", "infra_timeout", "rate_limit"] | None = None`
  to the request model.
- When set, pass it through `args_dict["force_failure_mode"]`.
- In the agentic job classes used for mock testing (deep research / podcast / presentation
  dry-run methods), after the last breadcrumb, check `self.force_failure_mode` and raise the
  matching exception type with a realistic error message:
  - `"code_bug"` → `raise KeyError("'source_path' — simulated mock failure")`
  - `"infra_timeout"` → `raise asyncio.TimeoutError("simulated mock timeout")`
  - `"rate_limit"` → `raise Exception("RateLimitError: 429 Too Many Requests — simulated")`
- The exception propagates through `AgenticJobBase.do_all()` → `running_fifo_queue.push_to_dead_queue()`
  → `_evaluate_for_auto_fix()` → watchdog fires. All real code paths.

**Scope note**: Only the dry-run paths of DR/podcast/presentation need this hook — one
4-line conditional per `_execute_dry_run()`. Keep the hook gated on `self.dry_run` so production
live runs cannot see it.

### Change 2 — Extend BFE's `_execute_dry_run()` to cover resubmit

**File**: `src/cosa/agents/bug_fix_expediter/job.py:423-459`

At the end of `_execute_dry_run()`, after the last breadcrumb:

1. Package the real `DeadJobContext` via `package_dead_job(self.dead_job_id)` so `ctx` is
   populated (this call is cheap — just a DB read).
2. Build a mocked-successful `FixResult(applied=True, success=True, details="dry-run mock fix")`.
3. Call `await self._resubmit_original_job(voice_io)` exactly as the live path does at lines
   268-275.
4. Store the resubmitted job id in `self.artifacts["resubmitted_job_id"]`.
5. Return a summary that includes the resubmitted id (or a "resubmit skipped" marker if
   `auto fix enabled = false` — which matches the live path's own behavior at `job.py:334-337`).

**This completes a pattern BFE was already following** — the rest of `_resubmit_original_job()`
already handles the `auto fix enabled` config check, the `create_agentic_job()` call, and the
`todo_queue.push()`. None of those need to change.

### Change 3 — Watchdog propagates dry_run to spawned BFE

**File**: `src/cosa/rest/dead_queue_watchdog.py:390-450` (`_submit_bfe` method)

When the failed job has `getattr(failed_job, "dry_run", False) is True` (or the original
`args_dict` contained `dry_run=True`), propagate it:

```python
args_dict = {
    "dead_job_id"   : job_id,
    "extra_context" : extra_context,
}
if getattr( failed_job, "dry_run", False ):
    args_dict[ "dry_run" ] = True
bfe_job = create_agentic_job( command="agent router go to bug fix expediter", args_dict=args_dict, ... )
```

This keeps the production behavior unchanged (non-dry-run failures spawn non-dry-run BFE) while
making dry-run failures spawn dry-run BFE automatically. It is one if-statement.

### Change 4 (the test) — New smoke test file

**File**: `src/tests/smoke/test_bfe_phase6_repair_loop_smoke.py`

Extends `InteractiveSmokeTest` following the `test_expeditor_mock_job_smoke.py` pattern. Runs
against the live FastAPI server on `:7999`. Uses `LUPIN_TEST_INTERACTIVE_MOCK_JOBS_*` env vars
for auth.

**Scenarios** (~4, following the 13-scenario harness shape):

| # | ID | Voice command | force_failure_mode | Expected outcome |
|---|----|---------------|---------------------|------------------|
| 0 | PR_LOOP_HAPPY | "make a presentation about quantum computing" | `code_bug` | Presentation dry-run fails → watchdog fires → BFE dry-run spawned → BFE resubmits → resubmitted presentation appears in done queue |
| 1 | DR_LOOP_HAPPY | "do deep research on fusion reactors" | `code_bug` | Same loop with a different eligible job type |
| 2 | MAX_ATTEMPTS | Repeat PR_LOOP_HAPPY × 4 under one repair chain | `code_bug` | 4th attempt rejected by `RepairAttemptTracker.can_attempt()` — circuit breaker fires, user gets escalation notification |
| 3 | WATCHDOG_DISABLED | PR_LOOP_HAPPY with `auto fix enabled = false` | `code_bug` | Mock job fails → watchdog returns `None` → no BFE spawned → failed job stays in dead queue |

**Test flow per scenario**:
1. POST `/api/mock-job/submit` with `voice_command` + `force_failure_mode="code_bug"`
2. Poll `/api/get-queue/dead` until the mock job appears (proves the failure-injection worked)
3. Poll `/api/get-queue/done` until the BFE dry-run job appears (proves the watchdog fired)
4. Poll `/api/get-queue/done` until the resubmitted original job appears (proves Phase 6
   `_resubmit_original_job()` ran)
5. Assert `cost_summary.total_cost_usd == 0.0` for both BFE and resubmitted jobs
6. Assert `metadata_json` lineage: `repair_chain_id`, `parent_bfe_job_id`, `attempt_number`

**Config toggling**: The test toggles `auto fix enabled` via the config-manager REST hot-reload
endpoint if one exists; otherwise it sets an env var override that `ConfigurationManager`
respects (per Lupin's convention that env vars override INI). Confirm the env-var override path
exists during implementation; if not, add a test fixture that edits the INI and reverts.

**Pre-flight gates**: If `LUPIN_INTERACTIVE_TESTS != "true"`, skip the scenarios and run only
the login / health / endpoint-shape checks (matches the expediter smoke test's gating at
`test_expeditor_mock_job_smoke.py:509`).

---

## Implementation Sequence

| Step | Task | Scope | Test gate |
|------|------|-------|-----------|
| 1 | Add `force_failure_mode` to `MockJobSubmitRequest` + thread into `args_dict` | `mock_job.py` | Unit test on request-model validation |
| 2 | Honor `force_failure_mode` inside DR/podcast/presentation `_execute_dry_run()` methods | 3 files in `src/cosa/agents/*/job.py` | Smoke run of DR dry-run with `force_failure_mode=code_bug` lands in dead queue |
| 3 | Extend BFE `_execute_dry_run()` to call `_resubmit_original_job()` | `bug_fix_expediter/job.py:423-459` | Inline `quick_smoke_test()` addition + one new `test_bfe_phase6.py` assertion |
| 4 | Watchdog `_submit_bfe()` propagates `dry_run` when present | `dead_queue_watchdog.py:_submit_bfe()` | New assertion in `test_bfe_phase6.py::TestWatchdogEvaluate` |
| 5 | Create `test_bfe_phase6_repair_loop_smoke.py` | `src/tests/smoke/` | Runs against :7999 with all 4 scenarios |
| 6 | Verify full loop green under `LUPIN_INTERACTIVE_TESTS=true` | N/A | Manual + CI invocation |

**Order matters**: Step 2 depends on Step 1. Steps 3 and 4 are independent of each other but
both required before Step 5. Step 5 is the final gate.

---

## Critical Files

### Modified (production)
- `src/cosa/rest/routers/mock_job.py` — Add `force_failure_mode` to request model + plumbing (Step 1)
- `src/cosa/agents/deep_research/job.py` — Honor `force_failure_mode` in `_execute_dry_run()` (Step 2)
- `src/cosa/agents/podcast_generator/job.py` — Same (Step 2)
- `src/cosa/agents/presentation_generator/job.py` — Same (Step 2)
- `src/cosa/agents/bug_fix_expediter/job.py:423-459` — Extend `_execute_dry_run()` to cover resubmit (Step 3)
- `src/cosa/rest/dead_queue_watchdog.py:_submit_bfe()` — Propagate `dry_run` (Step 4)

### Modified (tests)
- `src/tests/unit/test_bfe_phase6.py` — Two new assertions (dry-run resubmit path + watchdog propagation)

### New
- `src/tests/smoke/test_bfe_phase6_repair_loop_smoke.py` — 4-scenario integration smoke test

### Reused (no changes)
- `src/cosa/rest/agentic_job_factory.py` — Already threads `dry_run` through `args_dict`
- `src/cosa/rest/running_fifo_queue.py:464,524` — Watchdog hook already wired
- `src/cosa/agents/bug_fix_expediter/dead_job_packager.py` — Already reads `job_history`
- `src/tests/smoke/utilities/` — `InteractiveSmokeTest`, `LivePipelineTestBase` base classes

---

## Verification Plan

### Per-step verification

1. **Steps 1-2** (failure injection): After implementing, submit a mock DR job with
   `force_failure_mode=code_bug`. Hit `/api/get-queue/dead` and confirm the job appears with
   error containing `KeyError`. No BFE should spawn yet unless `auto fix enabled = true`.
2. **Step 3** (BFE dry-run resubmit): Directly invoke BFE `dry_run=True` against a seeded dead
   job via `/api/mock-job/submit` with voice command `"fix last failed job"`. Confirm breadcrumbs
   fire AND the resubmitted job id is populated in `artifacts["resubmitted_job_id"]`. Confirm
   `_resubmit_original_job()` log line appears in debug output.
3. **Step 4** (watchdog propagation): Unit-test assertion in `test_bfe_phase6.py` — mock a
   failed job with `dry_run=True` attribute, stub `_submit_bfe` to capture its `args_dict`,
   assert `args_dict["dry_run"] is True`.
4. **Step 5** (full loop): Run the new smoke test with `LUPIN_INTERACTIVE_TESTS=true`. Expect
   all 4 scenarios to pass and end in a "done" state with `cost=$0.00`. Total runtime target
   under 2 minutes (each scenario polls for ~15s).

### End-to-end dry-run loop verification

```bash
# Prerequisite: FastAPI server on :7999, LUPIN_TEST_INTERACTIVE_MOCK_JOBS_* env vars set
# Toggle auto-fix on for the test run
export LUPIN_INTERACTIVE_TESTS=true
python src/tests/smoke/test_bfe_phase6_repair_loop_smoke.py
```

Expected console output (tabular, per scenario): `PR_LOOP_HAPPY ✓ dead queue hit ✓ BFE spawned
✓ resubmit queued ✓ done $0.00` etc.

### Regression verification

- `pytest src/tests/unit/test_bfe_phase6.py` — all existing + new assertions pass
- `pytest src/tests/unit/test_repair_integration.py` — unchanged, passes
- `python -m cosa.rest.dead_queue_watchdog` — inline smoke test still green
- `python -m cosa.rest.repair_attempt_tracker` — inline smoke test still green

### What this plan does NOT cover

- **Step 9** (live E2E with real presentation generator + Haiku + known-bad mutation) — deferred
  to a separate follow-up plan. That requires real money, real git commits, and the full
  trust-proxy flow. This plan is strictly the dry-run precursor.
- **Auto-fix checkbox in the job submission UI** — parent plan marks this as deferred future work.
- **RepairAttemptTracker persistence across server restarts** — currently in-memory only; fine
  for this smoke test since it runs in one process.

---

## Open Questions (resolved before finalization)

| Question | Answer | Source |
|----------|--------|--------|
| pytest integration vs smoke script? | Smoke script — matches convention of every other agent's dry-run test | User chose "reuse expediter pipeline" |
| How to stub orchestrator calls? | Don't stub — extend BFE's existing `_execute_dry_run()` | User ruled out monkey patching; convention aligns |
| How to inject mock failure? | Add `force_failure_mode` to mock-job endpoint | User chose "reuse expediter pipeline"; pipeline needs extension |
| How to toggle `auto fix enabled`? | Env var override (verify path during Step 1) or test fixture that edits INI | Deferred to implementation |
