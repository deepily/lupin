# 11 — Testing Strategy

Per `feedback_comprehensive_automated_testing` memory: plans for new agents must include ALL testing layers. This doc enumerates each layer TFE will have.

## Layer 1: Unit tests (`pytest src/tests/unit/`)

### New test files

| File | Covers | Approx tests |
|------|--------|--------------|
| `test_fix_executor_shared.py` | Polymorphic FIX_PROMPT_BUILDERS registry, FixExecutor extracted body, FixContext.from_dead_job / from_test_cluster | 10 |
| `test_git_strategist_shared.py` | `commit_and_pr_single` (BFE path), `commit_and_pr_multi` (TFE path), trust-to-git mapping, gh CLI degradation | 12 |
| `test_tfe_config.py` | INI key loading, default values, `from_config(config_mgr)` factory | 6 |
| `test_tfe_state.py` | Pydantic model validation (TestRemediationContext, FailureCluster, TestDiagnosisResult, TFEState), phase enum | 8 |
| `test_tfe_snapshot_loader.py` | Schema version gate, malformed JSON, empty failures, PII redaction | 8 |
| `test_tfe_cluster.py` | Heuristic seeding, LLM refinement (mocked), fallback on LLM failure, 6 fixture snapshots | 12 |
| `test_tfe_orchestrator.py` | Per-phase orchestration with mocked SDK, voice gates yes/no, final status aggregation | 14 |
| `test_tfe_cost_tracker.py` | Cost accumulation, BudgetExceededError, format_summary | 5 |
| `test_tfe_rate_limiter.py` | Rolling window accounting, wait_if_needed, status dict | 5 |
| `test_tfe_api_client.py` | Three-tier key loading, mock mode, retry policy (mocked) | 6 |
| `test_tfe_job.py` | Instantiation, JOB_TYPE/JOB_PREFIX, id_hash format, `last_question_asked` property, state transitions | 6 |
| `test_test_suite_completion_watchdog.py` | All 6 eligibility gates, recursion guard, repair tracker blocking, never-raises, integration with running queue | 12 |
| **Total new unit tests** | | **~104** |

### Touched BFE unit tests (extraction-era)

| File | Change |
|------|--------|
| `test_bfe_fix.py` | Import path update; FixContext adapter; all 8-10 BFE fix tests stay green |
| `test_bfe_orchestrator.py` | Shim delegation assertions added (verify run_fix → execute_fix) |
| `test_bfe_phase5.py` | Only if GitStrategist surface shifts — target: zero change |
| `test_bfe_plan_writer.py` | Import path update to `shared/plan_writer.py` |

### Regression gate protocol

After every extraction commit (steps 1-3) AND every TFE feature commit (steps 6-13):

```bash
pytest src/tests/unit/ -v --tb=no -q | tail -5
```

The pre-step total must be captured in `90-extraction-execution-log.md` (for extraction) or `91/92-execution-log.md` (for TFE features). Post-step total must not regress.

### Baseline numbers

- Current baseline: 915 unit tests passing (per MEMORY.md)
- Post-BFE Phase 6: 58 new BFE unit tests → ~973 (not yet counted into MEMORY.md)
- Post-TFE full land: 973 + 104 new TFE tests = ~1,077 target

---

## Layer 2: Smoke tests (inline `quick_smoke_test()`)

Every new TFE module gets a `quick_smoke_test()` runnable as:

```bash
cd /mnt/DATA01/include/www.deepily.ai/projects/lupin/src
python -m cosa.agents.test_fix_expediter.state
python -m cosa.agents.test_fix_expediter.config
python -m cosa.agents.test_fix_expediter.snapshot_loader
python -m cosa.agents.test_fix_expediter.cluster
python -m cosa.agents.test_fix_expediter.api_client       # expected key error in CI is OK
python -m cosa.agents.test_fix_expediter.cost_tracker
python -m cosa.agents.test_fix_expediter.rate_limiter
python -m cosa.agents.test_fix_expediter.orchestrator     # instantiation only
python -m cosa.agents.test_fix_expediter.job              # JOB_TYPE/PREFIX constant check
```

Plus the shared modules:

```bash
python -m cosa.agents.shared.plan_writer
python -m cosa.agents.shared.git_strategist
python -m cosa.agents.shared.fix_executor
python -m cosa.agents.shared.meta_repair_guard
```

Each smoke test prints a `cu.print_banner()` header, runs the minimal sanity check, prints ✓ / ✗ per sub-check, exits 0 on all pass.

---

## Layer 3: WebSocket smoke tests (`./src/scripts/run-websocket-smoke-tests.sh`)

No new TFE-specific WebSocket events. TFE relies on `RunningFifoQueue.emit_job_state_transition()` for all state updates (per the skill). The only new WS event is from the watchdog's "auto-dispatched TFE" lineage log, which goes through the same emission path.

Action: run the existing WebSocket smoke suite after step 13 (watchdog integration) to verify zero regressions. 50 existing tests must stay green.

---

## Layer 4: Integration tests (`./src/tests/run-integration-tests.sh --bg -v`)

New integration test: `src/tests/integration/test_tfe_watchdog_dispatch.py`

- Seeds the queue with a TestSuiteJob having a mock remediation snapshot
- Pushes it to the done queue
- Asserts the watchdog dispatches a TFE job within 2 seconds
- Asserts the new TFE job has correct user identity and constructor args
- Asserts recursion guard: a TFE-triggered TestSuiteJob does NOT re-trigger TFE

Existing 43 integration tests must stay green. Run with `--bg` per memory rule.

---

## Layer 5: E2E UI tests (`./src/scripts/run-e2e-ui-tests.sh --bg -v`)

No new E2E UI tests required for TFE MVP — TFE's UI surface is the existing queue UI rendering TFE job cards, which is covered by existing tests. The "lineage" badge (TFE-dispatched relationship) is a nice-to-have and can be added in a follow-up.

Existing 285 E2E UI tests + 12 visual regression must stay green after step 13 (watchdog) and step 14 (config) — run with `--bg` per memory rule.

---

## Layer 6: Live pipeline tests (`src/tests/smoke/test_tfe_live_pipeline.py`)

New file, inherits `LivePipelineTestBase` per skill.

Scenarios (each is a @pytest.mark.parametrize case):

| Scenario | Inputs | Expected |
|----------|--------|----------|
| `basic_1cluster` | 1-cluster fixture snapshot | Phases 0-6 complete, validation run queued |
| `kcluster_aggregate_gate` | 3-cluster fixture snapshot, auto-proxy selects all | All 3 clusters fixed, 1 commit per cluster |
| `partial_success` | 3-cluster snapshot, fix injection breaks cluster 2 | 2 fixed 1 failed, still Phase 5 commits 2 clusters |
| `dry_run` | dry_run=True | No edits, no commits, breadcrumbs visible |
| `error_startup` | Mock API key missing | Graceful failure, urgent notification, no partial state |
| `recursion_guard` | Resubmit with metadata.triggered_by_tfe set | Watchdog refuses; no second TFE dispatched |

Run with `--auto-proxy --no-confirm` using the Q&A script at `src/conf/notification-proxy-scripts/test_fix_expediter.json`:

```bash
python src/tests/smoke/test_tfe_live_pipeline.py --group all --auto-proxy --no-confirm
```

First pass uses mock API client; second pass uses live API client with low cost cap (≤ $1).

---

## Layer 7: End-to-end TFE dry-run (`src/tests/e2e/run-tfe-live-e2e.sh`)

New shell script. Seeds a broken state via `bug_injector.py` and runs the full loop through the real queue consumer.

```bash
#!/bin/bash
set -e

# 1. Checkout disposable branch
git checkout -b tfe-live-e2e-$(date +%Y%m%d-%H%M%S)

# 2. Inject a known-fixable bug
python -m src.scripts.bug_injector --type code_bug --target \
    src/cosa/agents/math_agent/math_agent.py --mutation divide-by-zero

# 3. Submit a TestSuiteJob via /schedule-tests skill
# (this will fail on the injected bug)
./src/scripts/schedule-test-suite.sh --test-types unit --dry-run

# 4. Wait for the TestSuiteJob to complete and watchdog to dispatch TFE
./src/scripts/wait-for-tfe.sh --source-ts-job <ts_job_id> --timeout 300

# 5. Verify TFE dry-run walked all phases
./src/scripts/verify-tfe-phases.sh --tfe-job <tfe_job_id>

# 6. Restore branch
git checkout - && git branch -D tfe-live-e2e-*
```

Dry-run mode means: no real edits, no real commits, no real PR, no real rerun — just the orchestration + breadcrumbs. Used during development.

---

## Layer 8: Live TFE E2E monopolize (scheduled after hours)

After dry-run passes, schedule a live run via `/schedule-tests` skill (per memory rule — **always** use the skill, never hand-roll auth + API).

```bash
/schedule-tests --test-types tfe_live --scheduled-at "01:00" --monopolize
```

This creates a scheduled TestSuiteJob that runs `run-tfe-live-e2e.sh` without `--dry-run`:
- Real bug injection
- Real TestSuite failure
- Real TFE dispatch
- Real fix application (to disposable branch)
- Real commit + PR (to disposable branch)
- Real validation rerun on affected suites
- Branch cleanup at end

Expected runtime: ~20-45 minutes depending on cluster count and fix complexity. Cost cap: $15.

---

## Layer 9: PEFT training validation (after user runs trainer)

Per `feedback_voice_routing_training_data` memory: validate >95% accuracy on the test set with no regression on other agents. User runs the trainer; this plan produces the data.

Tracked in [`95-peft-data-execution-log.md`](95-peft-data-execution-log.md).

---

## Pre-merge checklist

Before merging TFE to main, ALL of these must be clean:

| # | Check | Target |
|---|-------|--------|
| 1 | Unit tests | ~1,077 passing, zero failures |
| 2 | Smoke tests | All new modules' quick_smoke_test() exit 0 |
| 3 | WebSocket smoke | 50/50 passing |
| 4 | Integration tests (`--bg`) | 44/44 passing (43 existing + 1 new watchdog) |
| 5 | E2E UI (`--bg`) | 285+12 passing |
| 6 | Live pipeline test (mock client) | 6/6 scenarios passing |
| 7 | Live pipeline test (live API, low cost cap) | 6/6 scenarios passing, cost ≤ $6 total |
| 8 | E2E TFE dry-run | One full pipeline walk-through, all phases green |
| 9 | E2E TFE live monopolize | One scheduled overnight run, validation rerun green |
| 10 | PEFT training (user-run) | >95% accuracy, no regression on other agents |

Any failure at any layer blocks the merge. No "fix in a follow-up" exceptions per `feedback_fix_all_failing_tests` memory.
