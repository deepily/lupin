> Part 2 of 4 of the [Test Fix Expediter (TFE) Guide](../test-fix-expediter-guide.md): section 4, the six-phase pipeline.

## 4. Six-Phase Pipeline

### Phase 0: Cluster

**Goal**: group the N failures in the remediation snapshot into K ≤ `max_clusters`
clusters, each representing one root cause.

**Implementation**: `src/cosa/agents/test_fix_expediter/cluster.py::heuristic_seed()`
does a pure-Python first pass. For each failure, it computes a key of
`(normalized_classname, first_non_pytest_traceback_frame)`. Failures sharing a key
get grouped together. Parametrized tests (`test_foo[param1]`, `test_foo[param2]`)
collapse to one cluster because they share the classname and the first non-pytest
frame in the traceback.

```python
# Simplified example
failures = [
    {"classname": "TestVisual", "name": "test_page[login]",    "traceback": "...visual.py:88..."},
    {"classname": "TestVisual", "name": "test_page[register]", "traceback": "...visual.py:88..."},
    {"classname": "TestAuth",   "name": "test_refresh",        "traceback": "...auth.py:42..."},
]
# heuristic_seed() produces:
# C1 = failures[0, 1]  (TestVisual @ visual.py:88)
# C2 = failures[2]     (TestAuth @ auth.py:42)
```

**LLM refinement (`llm_refine()`)**: an optional second pass that accepts an async
callback `refine_fn`. When provided, the function runs a Lead agent pass to
merge/split/relabel the heuristic clusters with agent-level understanding. When not
provided (MVP default), `llm_refine()` enforces `max_clusters` via a pure-Python
`_cap_enforce()` helper that consolidates the smallest clusters into a tail "Mixed"
cluster.

**INI tuning**:
- `test fix expediter max clusters` — default 8
- `test fix expediter max cluster seed failures` — default 50 (watchdog cap, not cluster cap)

**No voice gate at Phase 0** — clusters are shown to the user in the Phase 2
proposal gate.

**Output**: `list[FailureCluster]` where each cluster has `cluster_id`, `failure_indices`
(pointers into the flat failure list), `shared_error_signature`, `hypothesis`,
`affected_files_guess`, and `confidence`.

### Phase 1: Diagnose

**Goal**: for each cluster, produce a structured `TestDiagnosisResult` explaining
the shared root cause.

**Agent**: Opus lead with read-only SDK tools (`Read`, `Glob`, `Grep`, `Bash`).
System prompt lives in
`src/cosa/agents/test_fix_expediter/prompts/diagnosis.py`.

**Critical difference from BFE's diagnosis**: TFE's prompt teaches the agent to
parse `classname::name[param]` test IDs into source file paths. It also teaches
it to recognize four failure mode categories:

- **`code_bug`** — production code under test is wrong. Fix in `src/cosa/` or `src/lupin_app/`.
- **`test_bug`** — test itself is wrong (stale assertion, bad mock). Fix in `src/tests/`.
- **`fixture_bug`** — shared fixture is broken, affecting many tests. Fix in `conftest.py`.
- **`env_bug`** — environment/config issue. Fix in `src/conf/` or infra.

**Iteration**: per cluster, up to `max_diagnosis_iterations` (default 4) rounds.
Stop early when confidence ≥ `min_diagnosis_confidence` (default 0.65). Each
iteration re-prompts with the prior attempt's confidence; the prompt explicitly
tells the agent to discard bad hypotheses rather than incrementally patch them.

**Processing order**: serial in MVP. Future optimization would parallelize via
`asyncio.gather()` with a semaphore. It is deferred because per-cluster diagnoses are
cheap enough (~30s each) that serial execution is fine for K ≤ 8.

**Voice gate**: aggregated — one `ask_yes_no()` gate after all clusters have been
diagnosed. Summary markdown lists each cluster ID + error_category + confidence.
User approves to proceed to Phase 2, or rejects to cancel the whole run.

**INI tuning**:
- `test fix expediter max diagnosis iterations` — default 4
- `test fix expediter min diagnosis confidence` — default 0.65
- `test fix expediter voice gate mode` — `aggregate` (default) or `per_cluster`

### Phase 2: Propose

**Goal**: for each cluster, generate 1-3 fix alternatives; consolidate into a
multi-select voice gate.

**Agent**: Opus lead (read-only SDK, same model as Phase 1).

**Per-cluster behavior**: for each cluster's `TestDiagnosisResult`, the agent
produces a list of `TFEProposedFix` objects. Each proposal ranks a specific
approach: `code_patch`, `test_patch`, `config_change`, `retry`, or `manual`. The
proposal prompt caps each fix at 5 file changes — larger scopes get rejected as
"diagnosis too broad."

**Plan document**: `PlanWriter.write_plan()` (from the shared package) writes one
multi-section Markdown document listing every cluster + its proposals. Each
cluster becomes a `## Cluster C1: ...` section. The number in the heading is the cluster's position, starting at 1. The document lives at
`io/swe-team/plans/{user_email}/YYYY.MM.DD-{slug}-plan.md`.

**Aggregated voice gate**: `ask_multiple_choice()` with `multiSelect=True`. The
user sees a checklist of every proposed fix across every cluster, each row
labeled `{cluster_id}: {title}`. Selecting a subset lets the user cherry-pick
which cluster fixes to apply. Selecting nothing cancels Phase 3.

```
✅ C1: Re-baseline visual snapshots           [test_patch, 95% confidence, low risk]
⬜ C2: Add mutex to token refresh              [code_patch, 85% confidence, medium risk]
✅ C3: Fix queue size counter                  [code_patch, 90% confidence, low risk]
```

**Alternative mode**: `test fix expediter voice gate mode = per_cluster` switches
to K+1 sequential gates (one per proposal + one final confirm). This is high-touch
but preserves finer-grained control for high-risk fix batches.

**INI tuning**:
- `test fix expediter voice gate mode` — `aggregate` (default) or `per_cluster`

### Phase 3: Fix

**Goal**: apply each selected fix through the shared `FixExecutor`.

This is where TFE plugs into the shared Coder+Tester engine. See
[Shared Primitives Reference §5](../shared-fix-primitives-reference/01-planwriter-gitstrategist-fixexecutor.md#5-fixexecutor--polymorphic-codertester-loop).
TFE's `run_phase3_fix()` iterates the selected fixes and, for each one, constructs
a `FixExecutor(prompt_builder_key="tfe", ...)` and calls `execute_fix()`.

**TFE-specific prompts**: registered into `FIX_PROMPT_BUILDERS["tfe"]` at import
time from `src/cosa/agents/test_fix_expediter/prompts/fix.py`. The Tester's system
prompt instructs it to use `pytest -k` filtered by the cluster's failing test
names — not to run the whole suite. Verification success means only "these
specific tests pass now."

**`continue_on_cluster_failure`**: when a cluster fix fails verification and
exhausts `max_fix_attempts`, TFE decides whether to abort the rest of the batch or
continue with remaining clusters. Default: `true` (continue). Rationale: cluster
fixes are independent (Phase 0 clustering ensures distinct root
causes), so a failed second cluster shouldn't block the first or third.

**Dry-run mode**: when `dry_run=True` on the TFE job, Phase 3 synthesizes success
results from the proposals without invoking the Coder/Tester agents. Files are
extracted from the `proposal.changes` list so Phase 5 can still walk the happy
path (synthetic commits) without real code changes.

**INI tuning**:
- `test fix expediter max fix attempts` — default 2 (per cluster)
- `test fix expediter continue on cluster failure` — default `true`
- `test fix expediter cost cap usd` — default 15.00 (whole-run budget, aliased as `budget_usd` for the shared `FixExecutor`)

### Phase 5: Git

**Goal**: commit the fixes as one branch with N commits and one PR.

Delegates to `shared.GitStrategist.commit_and_pr_multi()` — see
[Shared Primitives Reference §4](../shared-fix-primitives-reference/01-planwriter-gitstrategist-fixexecutor.md#4-gitstrategist--trust-aware-git-operations).
TFE's `run_phase5_git()` builds the `(cluster_id, title, files, commit_message)`
tuples and hands them to the strategist.

**Commit message format**: `fix(tfe): {cluster_id} {title}` with a body containing
the fix type, confidence, risk, and description. Example:

```
fix(tfe): C1 Re-baseline visual snapshots

Root cause category: test_patch
Confidence: 95%
Risk: low

Update the 4 stale PNGs for pages affected by the Session 383 layout width change.
```

**Branch naming**: `fix/YYYY-MM-DD-tfe-{suite_abbrev}-{K}-clusters`. For single-suite
runs, `suite_abbrev` is the suite name (`unit`, `e2e`, etc.); for multi-suite, it's
`mixed`. Example: `fix/2026-04-10-tfe-e2e-3-clusters`.

**Trust level**: read via `_resolve_tfe_trust_level()`. The `test fix expediter trust mode`
INI key supports four modes:

- `inherit` (default) — read from the global SWE trust proxy, same as BFE
- `fixed_l1` — force trust level 1 (commit_only) regardless of earned trust
- `fixed_l3` — force trust level 3 (branch_and_pr) for testing
- `shadow` — passive, compute but don't escalate

**Partial-progress semantics**: if the Coder broke the build mid-batch, the
strategist's `commit_and_pr_multi()` leaves the successful commits in place.
It surfaces the failure in the returned `error` field. TFE reports the partial state
in its final status notification.

### Phase 6: Rerun Validation

**Goal**: schedule a new `TestSuiteJob` targeting the affected suites to verify
the fixes end-to-end.

**Async, not waiting**: TFE does not block on the validation rerun. It queues a
new `TestSuiteJob` via `create_agentic_job("agent router go to test suite", ...)`.
It sets `metadata["triggered_by_tfe"] = self.job_id` on the new job, pushes to
`jobs_todo_queue`, and then completes itself. The user watches the rerun's
progress in the Activity Log separately.

**Recursion guard — critical**: the `metadata["triggered_by_tfe"]` flag is
checked by `TestSuiteCompletionWatchdog._evaluate_inner()` on every done-queue
push. If the flag is set, the watchdog refuses to dispatch another TFE job, no
matter what. This prevents an infinite loop where TFE's rerun produces new
failures which trigger TFE which produces a new rerun...

**Rerun scope**: `test fix expediter rerun scope` controls whether the validation
run targets:

- `affected` (default) — only the suites the original TestSuiteJob ran. Fast,
  narrow, catches regressions in the same scope.
- `full` — the full test pyramid via `test_types = ["all"]`. Exhaustive,
  but adds 35-60 minutes to each TFE run.

**Dry-run**: when `dry_run=True`, Phase 6 sets
`self.validation_run_job_id = "dry-run-skipped"` and emits a breadcrumb. No
actual TestSuiteJob is queued.

**INI tuning**:
- `test fix expediter rerun scope` — `affected` (default) or `full`

---

