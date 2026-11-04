> Part 4 of 4 of the [Test Fix Expediter (TFE) Guide](../test-fix-expediter-guide.md): sections 8 and 9, troubleshooting, the code map and related documents.

## 8. Troubleshooting

### TFE never fires on my failed test suites

**Check 1**: `test fix expediter auto fix enabled = true` in
`src/conf/lupin-app.ini`? Server restarted after the edit?

**Check 2**: Does the TestSuiteJob actually have a remediation snapshot? The
snapshot is only produced when `summary.all_passed == false`. Inspect
`job.artifacts` after the run.

**Check 3**: Is the recursion guard tripped? If you're manually resubmitting the
same broken TestSuiteJob repeatedly, check the `metadata` field. A leftover
`triggered_by_tfe` from a prior run will make the watchdog skip dispatch.

**Check 4**: Failure count over the cap? If the TestSuiteJob reports more than
`test fix expediter max cluster seed failures` (default 50), the watchdog defers
to a human. Lower the cap or split the test run.

**Check 5**: Repair tracker exhausted budget for this `(job_id, suites)` key?
Check FastAPI logs for `[TestSuiteCompletionWatchdog] skip: repair tracker blocked`.
Restart the server to reset in-memory tracker state.

### Clustering produces too many or too few clusters

Phase 0's heuristic is based on `(classname, first_non_pytest_frame)`. It handles
~80% of realworld cases but can over-cluster when multiple root causes share a
classname, or under-cluster when parametrized tests' tracebacks differ subtly.

**Fix 1**: Lower `test fix expediter max clusters` to force consolidation.

**Fix 2**: Wire a real LLM refinement callback via `llm_refine(ctx, seeds, refine_fn=...)`.
The MVP uses pure-Python cap enforcement; real LLM refinement is the future
optimization.

**Fix 3**: Inspect the 6 fixture snapshots at `src/tests/fixtures/tfe/` for
comparison — each fixture targets a specific clustering pattern.

### Diagnosis exhausts iterations with low confidence

Per-cluster diagnosis may exhaust `max_diagnosis_iterations` without reaching
`min_diagnosis_confidence`. The fallback behavior is to accept the highest-confidence
attempt and proceed. The aggregate Phase 1 voice gate will show you the low
confidence — you can approve anyway or cancel.

**Fix 1**: Increase `max_diagnosis_iterations` if budget allows.

**Fix 2**: Lower `min_diagnosis_confidence` to accept more marginal diagnoses.

**Fix 3**: Provide more context via the prompt. The Phase 1 prompt builder in
`src/cosa/agents/test_fix_expediter/prompts/diagnosis.py` already teaches the agent
how to read test files and trace to production code. Obscure bugs may still need
manual investigation.

### Fix phase keeps failing verification

The Coder applies changes but the Tester's `pytest -k` filter still shows
failures. Possible causes:

1. **Diagnosis was wrong** — the Coder is fixing the wrong thing. Cancel TFE and
   investigate manually.
2. **Fix is correct but tests depend on side effects** — fixture state, cached
   objects, flaky timing. Consider if the test itself should be marked `@pytest.mark.flaky`.
3. **`pytest -k` filter too narrow** — the fix affects tests outside the cluster.
   Broaden the filter manually via a redelegation prompt, or accept the
   "Accept without tests" escalation.

### Phase 5 commits succeeded but no PR appeared

`commit_and_pr_multi()` degrades to `branch_only` when `gh` CLI is missing or
fails. The commits + branch exist; the PR just wasn't opened. At trust 3 and above it
also stops at `commit_only` while `test fix expediter push fix branch enabled` is `false`, its default.
The error reads "push disabled (test fix expediter push fix branch enabled is false): nothing was pushed and no
pull request was opened". The branch then exists only on this machine. Set the key to `true` for the next run, or push it
yourself first, then create the PR manually:

```bash
gh pr create --base main --head fix/2026-04-10-tfe-e2e-3-clusters \
  --title "TFE fix: 3 clusters from e2e test run"
```

Or install `gh` CLI:

```bash
sudo apt install gh
gh auth login
```

### Infinite rerun loop (should never happen)

If you see TFE dispatching on the completion of its own validation rerun, the
recursion guard is broken. Immediately disable the feature:

```ini
test fix expediter auto fix enabled = false
```

Then investigate:
- Is `metadata["triggered_by_tfe"]` being set on the resubmitted TestSuiteJob?
  Check `TFEOrchestrator.run_phase6_validation()` in
  `src/cosa/agents/test_fix_expediter/orchestrator.py`.
- Is `TestSuiteCompletionWatchdog._evaluate_inner()` actually checking the
  metadata? Unit test: `test_test_suite_completion_watchdog.py::TestGate4RecursionGuard`.
- Is the metadata surviving the `agentic_job_factory` round-trip? The factory
  preserves all keyword args on the reconstructed job.

### Voice gates never come back

Same as BFE — check cosa-voice MCP connectivity via `claude mcp get cosa-voice`
at the command line. The gate timeout is `test fix expediter feedback timeout seconds`
(default 300s). After timeout, the gate treats the absence of a response as
rejection (cancels Phase 3 / Phase 5 / Phase 6).

---

## 9. Code Map

| Concept | Source file | Key symbols |
|---------|-------------|-------------|
| Job class | `src/cosa/agents/test_fix_expediter/job.py` | `TestFixExpediterJob`, `do_all()`, `_execute()` |
| Orchestrator | `src/cosa/agents/test_fix_expediter/orchestrator.py` | `TFEOrchestrator`, `run_phase0_cluster`, `run_phase1_diagnose`, `run_phase2_propose`, `run_phase3_fix`, `run_phase5_git`, `run_phase6_validation` |
| Config | `src/cosa/agents/test_fix_expediter/config.py` | `TestFixExpediterConfig` dataclass, `from_config()`, `budget_usd` post-init alias |
| State | `src/cosa/agents/test_fix_expediter/state.py` | `TFEPhase` enum, `TestRemediationContext`, `FailureCluster`, `TestDiagnosisResult`, `TFEProposedFix`, `TFEState` |
| Snapshot loader | `src/cosa/agents/test_fix_expediter/snapshot_loader.py` | `load_from_path`, `load_from_artifacts`, `SnapshotLoadError`, PII redaction |
| Phase 0 clustering | `src/cosa/agents/test_fix_expediter/cluster.py` | `heuristic_seed`, `llm_refine`, `_cap_enforce`, `_validate_refined` |
| Diagnosis prompts | `src/cosa/agents/test_fix_expediter/prompts/diagnosis.py` | `DIAGNOSIS_SYSTEM_PROMPT`, `build_diagnosis_prompt` |
| Proposal prompts | `src/cosa/agents/test_fix_expediter/prompts/proposal.py` | `PROPOSAL_SYSTEM_PROMPT`, `build_proposal_prompt` |
| Fix prompts | `src/cosa/agents/test_fix_expediter/prompts/fix.py` | `CODER_SYSTEM_PROMPT`, `TESTER_SYSTEM_PROMPT`, prompt builders, `register_fix_prompts("tfe", ...)` |
| Watchdog | `src/cosa/rest/test_suite_completion_watchdog.py` | `TestSuiteCompletionWatchdog`, `init_watchdog`, `get_watchdog` |
| Queue hook | `src/cosa/rest/running_fifo_queue.py` | Done-queue push path invokes `get_watchdog().evaluate()` |
| Shared primitives | `src/cosa/agents/shared/` | `PlanWriter`, `GitStrategist.commit_and_pr_multi`, `FixExecutor`, `FIX_PROMPT_BUILDERS["tfe"]` |
| Fixture snapshots | `src/tests/fixtures/tfe/` | 6 remediation snapshots: 1cluster, kcluster, parametrized, fixture_error, collection_error, startup_crash |
| Live E2E driver | `src/tests/e2e/run-tfe-live-e2e.sh` | Bash script with `--dry-run` and `--live` modes |

### R&D archive

Historical planning documents live under
[`src/rnd/v0.1.6/2026.04.10-test-fix-expediter/`](../../../rnd/v0.1.6/2026.04.10-test-fix-expediter/00-index.md)
— 14 design docs + 6 execution logs. Useful when debugging why TFE is designed
the way it is.

### Test coverage

197 TFE test methods across 13 files:

| Test file | Tests | Focus |
|-----------|-------|-------|
| `test_tfe_config.py` | 6 | INI loading, `budget_usd` alias |
| `test_tfe_state.py` | 9 | Pydantic model validation |
| `test_tfe_snapshot_loader.py` | 14 | Schema gate, PII redaction, load paths |
| `test_tfe_cluster.py` | 29 | Heuristic seeding, cap enforcement, fixture snapshots |
| `test_tfe_diagnose.py` | 17 | Per-cluster iteration, parse errors, mock SDK |
| `test_tfe_propose.py` | 21 | Multi-cluster proposals, voice gate modes |
| `test_tfe_phase3_fix.py` | 13 | FixExecutor delegation, prompt registration |
| `test_tfe_phase5_git.py` | 18 | `commit_and_pr_multi` level 1 and level 3 paths |
| `test_tfe_phase6_rerun.py` | 14 | Async dispatch, recursion guard, scope modes |
| `test_test_suite_completion_watchdog.py` | 30 | All 6 gates, dispatch, exception safety |
| `test_tfe_job.py` | 9 | Instantiation, factory routing |
| `test_tfe_training_data.py` | 12 | PEFT template validation |
| `test_tfe_live_pipeline.py` (smoke) | 5 | Offline-safe full pipeline walk |

Run the full TFE suite:

```bash
pytest src/tests/unit/test_tfe_*.py src/tests/unit/test_test_suite_completion_watchdog.py -v
```

---

## Related Documentation

- **[Shared Fix Primitives Reference](../shared-fix-primitives-reference.md)** — `PlanWriter`, `GitStrategist.commit_and_pr_multi`, `FixExecutor`, `FIX_PROMPT_BUILDERS`
- **[Bug Fix Expediter Guide](../bug-fix-expediter-guide.md)** — sister agent for dead-job recovery
- **[Test-Suite Scheduling Guide](../test-suite-scheduling-guide.md)** — how TestSuiteJob produces the remediation snapshots TFE consumes
- **[Decision Proxy Admin Guide](../../proxy-admin-guide.md)** — SWE Team Trust Proxy that Phase 5 reads
- **[REST API Reference](../../rest-api-reference.md)** — `/api/push` with `"agent router go to test fix expediter"` command
