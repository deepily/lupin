# 08 — TFE Phase 6: Rerun Validation (async resubmit)

## Goal

After Phase 5 lands commits (one or more successful clusters), validate the fix by resubmitting a new `TestSuiteJob` targeting the **affected suites** (default) — not the full test pyramid. The validation run is a peer job in the queue, not a child process TFE waits on. TFE completes as soon as the rerun is dispatched; the rerun's own completion is observable via the queue UI and via `artifacts["validation_run_job_id"]`.

## Invariants

1. **Guard on any success**: only resubmit if `any(r.success for r in fix_results)`. If zero clusters succeeded, there's nothing to validate.
2. **Recursion guard**: the new TestSuiteJob must carry `metadata["triggered_by_tfe"] = self.id_hash` so the `TestSuiteCompletionWatchdog` refuses to re-trigger TFE on its completion. Without this guard, a flaky fix would create an infinite rerun loop.
3. **Don't wait**: TFE does NOT block on the validation run. It completes with its own state (fixed/partial/failed from Phase 3) and leaves the validation as a separate, observable job.
4. **Inherit user identity**: the validation TestSuiteJob runs as the same user that triggered the original TestSuiteJob, so it goes through the same access control and WS routing.

## Rerun scope — `affected` vs `full`

Configured via `test fix expediter rerun scope = affected | full` (default `affected`).

### `affected` (default)

The validation run targets only `ctx.original_test_types`:

```python
args_dict = {
    "test_types": ",".join(ctx.original_test_types),
    "pytest_args": " ".join(ctx.original_pytest_args) if ctx.original_pytest_args else "",
}
```

Rationale: if the original run was `[e2e]` and e2e failed, rerunning `[e2e]` validates the fix. Running the full pyramid is a 35-60 minute penalty per fix cycle. Affected-only rerun matches what the user actually cares about.

### `full`

The validation run targets the full pyramid (`all` suite). Use when:
- The user wants maximum confidence before merging
- Clusters span multiple suite types and affected-only would miss interactions
- Cost/time is not the primary concern (e.g., nightly scheduled runs)

Config override is per-instance — a user can flip to `full` for a specific TFE run by setting the INI value before submission.

## Implementation

```python
async def run_phase6_validation(self, fix_results, ctx):
    if not any(r.success for r in fix_results):
        self._notify(
            "TFE Phase 6 skipped: no successful fixes to validate",
            priority="low",
        )
        return None

    self._voice_io.set_session_topic("TFE Phase 6: Rerun validation")

    if self.config.rerun_scope == "full":
        test_types = ["all"]
    else:
        test_types = ctx.original_test_types

    args_dict = {
        "test_types": ",".join(test_types),
        "pytest_args": " ".join(ctx.original_pytest_args) if ctx.original_pytest_args else "",
    }

    validation_job = await self._cosa.create_agentic_job(
        command="agent router go to test suite",
        args_dict=args_dict,
        user_id=ctx.user_id,
        user_email=ctx.user_email,
        session_id=ctx.session_id,
        metadata={
            "triggered_by_tfe": self.id_hash,            # recursion guard
            "tfe_source_test_suite_job_id": ctx.source_test_suite_job_id,
            "tfe_fix_count": sum(1 for r in fix_results if r.success),
        },
    )

    await self._cosa.push_to_todo_queue(validation_job)

    self.artifacts["validation_run_job_id"] = validation_job.id_hash

    self._notify(
        f"TFE Phase 6: validation TestSuiteJob {validation_job.id_hash} queued "
        f"(test_types={test_types})",
        priority="medium",
        abstract=(
            f"**Validation run scheduled**\n\n"
            f"- Job ID: `{validation_job.id_hash}`\n"
            f"- Test types: {test_types}\n"
            f"- Source TFE: `{self.id_hash}`\n"
            f"- Source TestSuiteJob: `{ctx.source_test_suite_job_id}`\n\n"
            f"TFE does not wait on the rerun; it's queued as a peer job."
        ),
    )

    return validation_job.id_hash
```

## Recursion guard — the critical detail

The `TestSuiteCompletionWatchdog.evaluate(completed_job)` method must check:

```python
if completed_job.metadata and completed_job.metadata.get("triggered_by_tfe"):
    return  # refuse to re-trigger TFE on a TFE-dispatched rerun
```

This is tested in `test_test_suite_completion_watchdog.py::test_recursion_guard_honored`.

**Edge case**: what if the validation run itself fails? The user sees a failed test suite in the queue UI with `metadata["triggered_by_tfe"]` set. The watchdog refuses to auto-retrigger. The user can:
- Manually investigate and fix
- Manually trigger a new TFE run without the guard (clear flag and resubmit)
- Accept the `partial` / `failed` state of the original TFE run

There's no second automatic attempt — one TFE cycle per TestSuiteJob failure, deliberate.

## TFE state transition on Phase 6 completion

Phase 6 is the LAST phase of TFE. After dispatching the validation run, TFE transitions to its final state based on Phase 3 results:

```python
if final_phase3_status == "fixed":
    self.status = "completed"
    self.answer_conversational = (
        f"Successfully fixed {K}/{K} clusters. Validation rerun queued "
        f"as {validation_job_id}."
    )
elif final_phase3_status == "partial":
    self.status = "completed"  # still completed, not failed
    self.answer_conversational = (
        f"Partially fixed {N}/{K} clusters. "
        f"Validation rerun (affected suites only) queued as {validation_job_id}. "
        f"Manual review needed for failed clusters: {failed_cluster_ids}"
    )
else:  # "failed"
    self.status = "failed"
    self.answer_conversational = (
        f"All {K} cluster fix attempts failed. No validation rerun queued. "
        f"See plan doc for diagnosis and proposed fixes: {plan_path}"
    )
```

Note: `final_status = "completed"` even for `"partial"` Phase 3 outcomes, because TFE itself completed its work — the mixed fix outcome is reported in the conversational answer, not in the job status. This is consistent with how BFE handles partial successes.

## UI lineage

The queue UI should show TFE and its validation TestSuiteJob as a parent-child pair:

- `artifacts["validation_run_job_id"]` on the TFE job — pointer to the validation run
- `metadata["triggered_by_tfe"]` on the validation TestSuiteJob — pointer back to TFE

The UI can render these as linked cards: "Auto-triggered by TFE-abc → TFE-abc → Validation run TS-xyz". No code changes needed in the UI beyond rendering the link; the data is all in existing fields.

## Dry-run mode

In dry-run, Phase 6 does NOT actually dispatch a TestSuiteJob. It emits a breadcrumb:

```python
if self.dry_run:
    self._notify(
        f"[DRY RUN] Would queue validation TestSuiteJob with test_types={test_types}",
        priority="low",
    )
    self.artifacts["validation_run_job_id"] = "dry-run-skipped"
    return None
```

## Voice / notification

- **Session topic**: `"TFE Phase 6: Rerun validation"`
- **Breadcrumb on skip** (no successful fixes): `notify(priority="low")`
- **Breadcrumb on dispatch**: `notify(priority="medium")` with abstract showing validation job ID
- **No voice gate** — validation dispatch is automatic. The user can still observe and cancel the validation run from the queue UI.

## Unit test coverage

Target: `src/tests/unit/test_tfe_phase6_rerun.py` (or in orchestrator tests)

| Test | Mock | Assertion |
|------|------|-----------|
| `test_phase6_skipped_no_successful_fixes` | all fix_results.success=False | No create_agentic_job call, returns None |
| `test_phase6_dispatches_validation_run` | 1 successful fix | create_agentic_job called once, job queued |
| `test_phase6_recursion_guard_metadata_set` | any | New job has `metadata["triggered_by_tfe"]` = TFE id_hash |
| `test_phase6_affected_scope` | rerun_scope=affected, original=["e2e"] | test_types=["e2e"] |
| `test_phase6_full_scope` | rerun_scope=full | test_types=["all"] |
| `test_phase6_pytest_args_propagated` | original pytest_args non-empty | pytest_args forwarded verbatim |
| `test_phase6_dry_run_no_dispatch` | dry_run=True | No create_agentic_job call, validation_run_job_id="dry-run-skipped" |
| `test_phase6_partial_success_status` | Phase 3 partial, Phase 6 dispatches | status="completed", answer mentions failed clusters |
| `test_phase6_all_failed_status` | Phase 3 all failed | status="failed", no validation dispatched |

See also `test_test_suite_completion_watchdog.py::test_recursion_guard_honored` for the watchdog-side verification.
