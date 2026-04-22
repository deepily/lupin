# 06 — TFE Phase 3: Fix Delegation (via shared FixExecutor)

## Goal

For each `ProposedFix` in `selected_fixes` (from Phase 2's gate), invoke the shared `FixExecutor.execute_fix()` with a TFE-flavored `FixContext`. Collect `FixResult` + `files_changed` per cluster. Aggregate final outcome.

This phase delegates the actual code-change work to the shared module — TFE's orchestrator does NOT directly invoke the coder/tester agents. All SDK client lifecycle, cancellation plumbing, SafetyGuard wiring, and retry loops live in `shared/fix_executor.py`.

## Input / output

```python
# Input
selected_fixes : list[ProposedFix]
diagnoses      : dict[str, TestDiagnosisResult]   # keyed by cluster_id
clusters       : dict[str, FailureCluster]
plan_path      : str
ctx            : TestRemediationContext           # for user_email

# Output
fix_results        : list[FixResult]              # one per selected fix
files_changed_all  : list[str]                    # deduped union across clusters
files_changed_by_cluster : dict[str, list[str]]   # keyed by cluster_id
final_status       : str                          # "fixed" | "partial" | "failed"
```

## TestRemediationContext model (defined here since this is where it's consumed)

```python
class TestRemediationContext(BaseModel):
    source_test_suite_job_id : str
    snapshot_path            : str    # relative to io/
    snapshot                 : dict   # parsed JSON
    suites_run               : list[str]
    summary                  : dict
    failures                 : list[dict]
    original_test_types      : list[str]
    original_pytest_args     : list[str]
    user_id                  : str
    user_email               : str
    session_id               : str
```

Built by `snapshot_loader.py::load_from_artifacts()` which:
1. Reads the snapshot JSON from the source TestSuiteJob's artifacts
2. Validates `schema_version == "1.0"`
3. Validates summary + failures are non-empty
4. Strips any PII from `traceback` fields (redact absolute paths outside project)
5. Returns the populated pydantic model

## FailureCluster model (defined in state.py)

```python
class FailureCluster(BaseModel):
    cluster_id              : str
    failure_indices         : list[int]
    shared_error_signature  : str
    hypothesis              : str
    affected_files_guess    : list[str]
    confidence              : float
```

## TFE `prompts/fix.py` — the test-flavored prompt builders

At the bottom of `test_fix_expediter/prompts/fix.py`, register into the shared registry:

```python
from cosa.agents.shared.fix_executor import register_fix_prompts

def build_fix_prompt(proposed_fix, fix_context, iteration):
    """
    Build the coder system + user prompt for a test-failure fix.
    fix_context.origin_details contains:
      failure_indices, shared_error_signature, hypothesis, test_symptoms
    """
    ...

def build_verification_prompt(proposed_fix, fix_context):
    """
    Build the tester system + user prompt to verify the fix.
    For test failures: run the affected tests via `pytest -k <name>`
    and assert zero regressions.
    """
    ...

def build_redelegation_prompt(proposed_fix, fix_context, prior_attempt, tester_output):
    """
    Build the redelegation prompt when the tester reported failure.
    """
    ...

register_fix_prompts(
    "tfe",
    build_fix_prompt=build_fix_prompt,
    build_verify_prompt=build_verification_prompt,
    build_redelegate_prompt=build_redelegation_prompt,
)
```

### Critical differences from BFE's fix prompt

BFE's fix prompt says "apply this fix to resolve the crash described in the stack trace." TFE's says "apply this fix to make the following N failing tests pass." The tester verification is different too:

- **BFE tester**: re-runs the original agentic job with the fix in place
- **TFE tester**: runs `pytest -k "{test_names}"` selecting just the tests in the cluster, asserts zero failures

TFE's verification prompt must teach the tester:
- How to construct a `pytest -k` filter from the failing test names in the cluster
- That "pass" means the specific tests in this cluster pass; other tests are out of scope for verification
- That a fixture bug fix may require running more tests than the cluster (anything sharing the fixture)

## Orchestrator wiring

```python
class TFEOrchestrator:
    async def run_phase3_fix(self, selected_fixes, diagnoses, clusters, plan_path, ctx):
        fix_results = []
        files_changed_by_cluster = {}

        for fix in selected_fixes:
            cluster = clusters[fix.cluster_id]
            diagnosis = diagnoses[fix.cluster_id]

            self._voice_io.set_session_topic(
                f"TFE Phase 3: Fix cluster {fix.cluster_id} "
                f"({selected_fixes.index(fix)+1}/{len(selected_fixes)})"
            )
            self._notify(
                f"Applying fix for cluster {fix.cluster_id}: {fix.title}",
                priority="low",
            )

            fix_context = FixContext.from_test_cluster(
                cluster=cluster,
                diagnosis=diagnosis,
                user_email=ctx.user_email,
            )

            try:
                result, files_changed = await self._fix_executor.execute_fix(
                    proposed_fix=fix,
                    fix_context=fix_context,
                    plan_path=plan_path,
                )
            except Exception as e:
                # Never reach here — FixExecutor never raises
                result = FixResult(applied=False, success=False,
                                   details=f"Unexpected exception: {e}",
                                   retry_eligible=False)
                files_changed = []

            fix_results.append(result)
            files_changed_by_cluster[fix.cluster_id] = files_changed

            if not result.success and not self.config.continue_on_cluster_failure:
                self._notify(
                    f"Cluster {fix.cluster_id} failed. Aborting remaining clusters "
                    f"(continue_on_cluster_failure=False).",
                    priority="high",
                )
                break

        files_changed_all = sorted(set(
            f for files in files_changed_by_cluster.values() for f in files
        ))

        return fix_results, files_changed_by_cluster, files_changed_all
```

## Final status aggregation

```python
successful = [r for r in fix_results if r.success]

if len(successful) == len(selected_fixes):
    final_status = "fixed"       # all selected clusters succeeded
elif len(successful) > 0:
    final_status = "partial"     # some succeeded
else:
    final_status = "failed"      # none succeeded
```

Phase 5 (git) and Phase 6 (rerun) are gated on `len(successful) > 0`. If zero clusters succeeded, there's nothing to commit and nothing to validate.

## continue_on_cluster_failure — the default

`test fix expediter continue on cluster failure = true` (default).

**Rationale**: clusters are independent by construction (Phase 0 ensures each cluster has its own root cause). A fix failure in cluster C2 doesn't invalidate a successful fix in cluster C1. The user wants the maximum useful progress — a `partial` outcome is still valuable.

Override to `false` when the user wants atomic "all or nothing" fix application — e.g., when clusters are actually dependent (a Phase 0 clustering bug) or when the user prefers to review before any commit.

## Voice / notification

- **Session topic per cluster fix**: `"TFE Phase 3: Fix cluster C2 (2/3)"`
- **Breadcrumb per fix start**: `notify(f"Applying fix for cluster {cluster_id}: {title}", priority="low")`
- **Breadcrumb per fix outcome**: `notify(f"Cluster {cluster_id} fix: {'success' if result.success else 'failed'}", priority="low")`
- **Urgent notification on partial failure**: `notify(f"TFE Phase 3 complete: {len(successful)}/{K} succeeded", priority="high")` with abstract detailing which clusters failed
- **No voice gate at Phase 3** — fixes were selected in Phase 2

## Dry-run mode

When `self.dry_run == True`, `FixExecutor` must NOT make real edits. The fix executor is responsible for honoring dry-run (the config is passed in) and emitting breadcrumbs:

```python
# inside FixExecutor
if self.config.dry_run:
    self._on_notify(
        f"[DRY RUN] Would apply fix: {proposed_fix.title} "
        f"({len(proposed_fix.changes)} file changes)",
        priority="low",
    )
    return FixResult(applied=False, success=True,
                     details="dry_run: skipped actual edits",
                     retry_eligible=False), []
```

In dry-run mode, Phase 3 reports success for every fix (the "would have worked" path), Phase 5 git is skipped entirely, Phase 6 rerun is skipped entirely.

## Unit test coverage

Target: `src/tests/unit/test_tfe_fix_delegation.py` (separate from the shared fix executor tests)

| Test | Mock | Assertion |
|------|------|-----------|
| `test_fix_delegation_success_all_clusters` | FixExecutor mock returns success for all | `final_status == "fixed"`, Phase 5 runs |
| `test_fix_delegation_partial_success` | FixExecutor mock returns success for 2/3 | `final_status == "partial"`, Phase 5 runs (with 2 clusters) |
| `test_fix_delegation_all_failed` | FixExecutor mock returns failure for all | `final_status == "failed"`, Phase 5 skipped, Phase 6 skipped |
| `test_fix_delegation_abort_on_failure` | continue_on_cluster_failure=False, failure in cluster 2 | Cluster 3 never attempted |
| `test_fix_context_populated_correctly` | any | Assert `FixContext.prompt_builder_key == "tfe"`, `origin_label == "test_cluster:C1"` |
| `test_files_changed_deduped` | Mock returns overlapping file lists | `files_changed_all` is sorted + deduped |
| `test_dry_run_no_real_edits` | dry_run=True | FixExecutor receives dry_run config, no file writes |
| `test_tfe_prompts_registered_on_import` | import test_fix_expediter.prompts.fix | `FIX_PROMPT_BUILDERS["tfe"]` is populated |
