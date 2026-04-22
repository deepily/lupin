# 01 — TFE Design Overview

## The problem

`TestSuiteJob` has been producing a machine-readable remediation snapshot JSON since Session f28d32d1 (2026-04-09):

```json
{
  "schema_version": "1.0",
  "timestamp": "2026.04.10-at-14:53",
  "suites_run": ["e2e"],
  "summary": {"total_passed": 335, "total_failed": 4, "total_skipped": 2,
              "total_errors": 0, "all_passed": false},
  "failures": [
    {"classname": "...", "name": "test_x[param]", "type": "FAILED|ERROR",
     "message": "...", "traceback": "...", "suite": "e2e"},
    ...
  ]
}
```

Nothing consumes it. BFE (Bug Fix Expediter) is the obvious fit — it's Lupin's agentic repair pipeline, and Phase 6 automated repair loop is code-complete (58 tests passing). But BFE's input contract is `DeadJobContext` from the dead queue. It assumes **one crashed job → one root cause → one fix → retry that job**. Test failures violate that model on every axis:

- **Cardinality**: N test failures, typically clustering into K=3-8 root causes. BFE is single-bug only.
- **Shape**: flat list of tracebacks with `classname::name[param]` test IDs, not a single stack trace from a crashed job.
- **Validation semantics**: rerun affected tests, not retry the original job.
- **Prompts**: BFE's `prompts/{diagnosis,proposal,fix}.py` hard-code `ctx.error`, `ctx.stack_trace`, `ctx.question_text`, `ctx.metadata_json` — dead-job fields. The prompts can't be lifted wholesale.
- **Trigger**: BFE fires when a job lands in the dead queue. TestSuiteJobs complete *successfully* even when tests fail — they return a result object, not a crash. Different queue, different hook.

## The chosen direction: Option B

Three options were analyzed in session 1cfcdf73:

- **A. Modify BFE** — extend `DeadJobContext` with a discriminator, branch every prompt, fabricate synthetic dead-job contexts per cluster. Contaminates the proven dead-job path.
- **B. New `TestFixExpediterJob` (TFE)** sharing BFE primitives via extracted modules. Clean separation, matches cardinality reality.
- **C. Intermediate clusterer + delegated BFE** — a small agent that fires K sequential BFE jobs. K voice gates, K minutes each, semantically dishonest synthetic contexts.

**Option B chosen** because:
1. BFE stays untouched on its proven dead-job path. Zero regression risk.
2. The shared `FixExecutor` + `GitStrategist` + `PlanWriter` extraction is a positive refactor that benefits both job types.
3. Clustering and test-aware semantics live where they belong — in TFE's own Phase 0 and prompts — not grafted onto BFE's single-bug model.
4. Matches the real-world pattern ("22 failures = 3 root causes") as a first-class design principle.

## Architecture

```
TestSuiteJob completes (success, but tests failed)
    → DoneQueue
        → RunningFifoQueue calls TestSuiteCompletionWatchdog
            → eligibility gates pass? → construct TestFixExpediterJob
                → push to jobs_todo_queue
                    ↓
        TestFixExpediterJob (tfe-xyz) runs:
            Phase 0:  Cluster N failures → K clusters
                      (heuristic seed + LLM refine, Opus, read-only SDK)
            Phase 1:  Diagnose per cluster (Opus, read-only Grep/Read/Bash)
                      → aggregate ask_yes_no gate: proceed?
            Phase 2:  Propose fixes (Opus, read-only)
                      → aggregate ask_multiple_choice(multiSelect): select subset
                      → shared PlanWriter writes multi-section plan doc
            Phase 3:  For each selected fix → shared FixExecutor.execute_fix()
                      (Sonnet coder+tester via polymorphic prompt registry)
            Phase 5:  shared GitStrategist.commit_and_pr_multi()
                      (one branch, N commits, one PR)
            Phase 6:  async create_agentic_job("agent router go to test suite",
                      args={"test_types": ctx.original_test_types, ...},
                      metadata={"triggered_by_tfe": self.id_hash})
                      → push to jobs_todo_queue (recursion-guarded)
            Complete: artifacts["validation_run_job_id"] set for UI lineage
```

## Shared-module boundary

New package: `src/cosa/agents/shared/`

| Module | Extracted from | Owns |
|---|---|---|
| `plan_writer.py` | BFE `plan_writer.py` (moved) | Multi-section plan doc writer |
| `git_strategist.py` | BFE `orchestrator.run_git_strategy()` et al. | Trust-level → git strategy mapping, `commit_and_pr_single`, `commit_and_pr_multi` |
| `fix_executor.py` | BFE `orchestrator.run_fix()` body | Coder+tester loop, polymorphic `FIX_PROMPT_BUILDERS` registry, `FixContext` model |
| `meta_repair_guard.py` | New | Shared recursion-guard helpers (is_meta_repair_job, key generation) |

BFE retains its own `orchestrator.py`, `state.py`, `config.py`, `dead_job_packager.py`, `prompts/{diagnosis,proposal,fix}.py`. BFE's `run_fix` and `run_git_strategy` become thin shims delegating to the shared modules. BFE's `prompts/fix.py` registers into the shared registry under key `"bfe"` at import time.

TFE gets its own parallel tree at `src/cosa/agents/test_fix_expediter/` with all the modules mandated by the `agentic-voice-workflow` skill (see [02](02-fix-executor-extraction-plan.md) and the compliance table in the approved plan).

## What this plan is NOT

- **Not a BFE replacement.** BFE continues to handle dead-queue failures from other agentic jobs (presentation_generator, deep_research, podcast_generator, etc.) exactly as before.
- **Not a test flake detector.** Phase 6 rerun is a validation step, not a flake-repeat-to-filter loop. Flake detection is a future extension.
- **Not a prompt refactor of BFE.** BFE's prompts stay verbatim. Only the code paths below the prompt layer are extracted.
- **Not a CoSA repo operation.** All file edits inside `src/cosa/` are working-tree only from the Lupin parent context. User manages CoSA commits in a separate session.

## Risk register

| Risk | Severity | Mitigation |
|---|---|---|
| FixExecutor extraction breaks BFE behaviorally | High | Regression gate: `pytest src/tests/unit/ -v` totals must not degrade on each extraction commit. Expect 2-3 iterations on step 3. |
| Extraction lands before BFE Phase 6 live E2E baseline | Medium | Step 1 waits for the parallel BFE Phase 6 dry-run console to establish a known-good baseline. |
| Clustering produces too many or too few clusters | Medium | Heuristic pre-pass caps N→K by classname+frame; LLM refinement bounded by `max_clusters` (default 8). |
| Prompt mismatch for test-aware diagnosis | Medium | Prompts tested against 6 fixture snapshots covering 1cluster, K-cluster, parametrized, fixture error, collection error, startup crash. |
| Recursion: TFE-triggered rerun fails, re-triggering TFE | High | `metadata["triggered_by_tfe"]` flag on the validation TestSuiteJob. Watchdog honors the flag and refuses to re-trigger. Unit test for the guard. |
| Voice gate fatigue with K=5+ clusters | Medium | Default is aggregate mode (2 gates total via multi-select). Per-cluster mode is opt-in. |
| PEFT training data generation forgotten | Low | Explicit step 17 in the approved plan. Training run is USER-RUN only per memory rule. |
