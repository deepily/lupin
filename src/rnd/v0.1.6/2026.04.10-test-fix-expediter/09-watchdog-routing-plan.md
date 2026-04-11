# 09 — TestSuiteCompletionWatchdog

## Why a new watchdog is needed

TestSuiteJobs complete **successfully** from a queue perspective even when tests fail. The job's `do_all()` ran, returned a result object, set status to "completed", populated `artifacts` with the remediation snapshot, and was pushed to the **done queue**. It did not crash — it reported failures as output, not as an exception.

The existing `DeadQueueWatchdog` only fires on jobs that land in the dead queue (FAILED / INTERRUPTED status). TestSuiteJobs never go there on test failures. The dead watchdog is the wrong hook.

## Architecture

A parallel watchdog, `TestSuiteCompletionWatchdog`, runs alongside `DeadQueueWatchdog`:

```
RunningFifoQueue.push_to_done(completed_job)
    │
    ├─→ if completed_job.status == "completed":
    │       → TestSuiteCompletionWatchdog.evaluate(completed_job)  (new)
    │
    └─→ if completed_job.status in ("failed", "interrupted"):
            → DeadQueueWatchdog.evaluate(dead_job)  (existing)
```

## File: `src/cosa/rest/test_suite_completion_watchdog.py`

```python
class TestSuiteCompletionWatchdog:
    def __init__(self, config_mgr, todo_queue, repair_tracker, debug=False, verbose=False):
        self.enabled = config_mgr.get(
            "test fix expediter auto fix enabled", default=False, return_type="boolean"
        )
        self.max_failures = config_mgr.get(
            "test fix expediter max cluster seed failures", default=50, return_type="int"
        )
        self._todo_queue     = todo_queue
        self._repair_tracker = repair_tracker
        self.debug           = debug
        self.verbose         = verbose

    def evaluate(self, completed_job) -> Optional[str]:
        """
        Requires:
            - completed_job is a completed job from the done queue
        Ensures:
            - returns TFE job id if dispatched, None otherwise
            - never raises (watchdog must not crash the queue consumer)
        """
        try:
            return self._evaluate_inner(completed_job)
        except Exception as e:
            if self.debug: print(f"[TFE-WATCHDOG] error evaluating job: {e}")
            return None

    def _evaluate_inner(self, completed_job) -> Optional[str]:
        # Gate 1: enabled?
        if not self.enabled:
            return None

        # Gate 2: is it a TestSuiteJob?
        if getattr(completed_job, "JOB_TYPE", None) != "test_suite":
            return None

        # Gate 3: does it have a valid remediation snapshot?
        snapshot = completed_job.artifacts.get("remediation_snapshot")
        if not isinstance(snapshot, dict):
            return None
        if snapshot.get("schema_version") != "1.0":
            return None
        summary = snapshot.get("summary", {})
        if summary.get("all_passed", True):
            return None
        failures = snapshot.get("failures", [])
        if not failures:
            return None

        # Gate 4: recursion guard (is this a TFE-dispatched rerun?)
        metadata = getattr(completed_job, "metadata", None) or {}
        if metadata.get("triggered_by_tfe"):
            if self.debug: print(
                f"[TFE-WATCHDOG] skipping — job was TFE-triggered "
                f"(tfe={metadata['triggered_by_tfe']})"
            )
            return None

        # Gate 5: failure count cap
        if len(failures) > self.max_failures:
            self._notify_failure_cap_exceeded(completed_job, len(failures))
            return None

        # Gate 6: repair tracker (cost/iteration/wall-clock)
        repair_key = self._compute_repair_key(completed_job, snapshot)
        if not self._repair_tracker.allow(repair_key):
            if self.debug: print(f"[TFE-WATCHDOG] blocked by repair tracker for {repair_key}")
            return None

        # All gates passed — dispatch TFE
        return self._dispatch_tfe(completed_job, snapshot)

    def _compute_repair_key(self, completed_job, snapshot) -> tuple:
        suites = tuple(sorted(snapshot.get("suites_run", [])))
        return (completed_job.id_hash, suites)

    def _dispatch_tfe(self, completed_job, snapshot) -> str:
        from cosa.agents.test_fix_expediter.job import TestFixExpediterJob

        tfe_job = TestFixExpediterJob(
            remediation_snapshot_path=completed_job.artifacts.get("remediation_snapshot_path"),
            source_test_suite_job_id=completed_job.id_hash,
            user_id=completed_job.user_id,
            user_email=completed_job.user_email,
            session_id=completed_job.session_id,
            dry_run=False,
        )

        self._todo_queue.push(tfe_job)
        self._repair_tracker.record_attempt(
            self._compute_repair_key(completed_job, snapshot)
        )

        return tfe_job.id_hash

    def _notify_failure_cap_exceeded(self, completed_job, failure_count):
        # TODO: integrate with cosa-voice notify if available
        pass
```

## Hook point in `running_fifo_queue.py`

In the existing success-path post-pop block (~line 540, parallel to `_evaluate_for_auto_fix`):

```python
# Existing dead-queue watchdog block (unchanged):
if completed_job.status in ("failed", "interrupted"):
    self._dead_watchdog.evaluate(completed_job)

# NEW: TestSuite completion watchdog block
elif completed_job.status == "completed":
    tfe_job_id = self._test_suite_completion_watchdog.evaluate(completed_job)
    if tfe_job_id:
        if self.debug: print(f"[QUEUE] auto-dispatched TFE {tfe_job_id} from {completed_job.id_hash}")
```

The exact line is determined during step 13; the pattern is: immediately after the success-path `done_queue.push()` call, before the WebSocket state-transition emit.

## Initialization in `main.py`

```python
from cosa.rest.test_suite_completion_watchdog import TestSuiteCompletionWatchdog

@app.on_event("startup")
async def startup_event():
    # ... existing startup ...

    # Dead queue watchdog (existing)
    app.state.dead_queue_watchdog = DeadQueueWatchdog(...)

    # TestSuite completion watchdog (new)
    app.state.test_suite_completion_watchdog = TestSuiteCompletionWatchdog(
        config_mgr=config_mgr,
        todo_queue=app.state.jobs_todo_queue,
        repair_tracker=app.state.repair_attempt_tracker,
        debug=debug, verbose=verbose,
    )

    # Wire into running_fifo_queue
    app.state.jobs_run_queue.set_test_suite_completion_watchdog(
        app.state.test_suite_completion_watchdog
    )
```

A new setter `RunningFifoQueue.set_test_suite_completion_watchdog(watchdog)` exposes the wire-up point.

## Eligibility gate reference table

| Gate | Check | Config key | Rationale |
|------|-------|------------|-----------|
| 1 | `self.enabled` | `test fix expediter auto fix enabled` | Global on/off switch; default false for safety |
| 2 | `job_type == "test_suite"` | — | Only test_suite jobs produce remediation snapshots |
| 3 | Snapshot valid + failures>0 | — | Schema version, `all_passed=false`, non-empty failures list |
| 4 | Recursion guard | — | `metadata["triggered_by_tfe"]` prevents infinite rerun loops |
| 5 | Failure count ≤ max | `test fix expediter max cluster seed failures` | Defer mega-batches to humans |
| 6 | Repair tracker allow | cost / iteration / wall-clock | Reuses BFE's `RepairAttemptTracker` |

## Observability

- **Log line**: `[TFE-WATCHDOG] dispatched TFE {tfe_job_id} from TestSuiteJob {ts_job_id} (failures={N})` when a dispatch fires
- **Log line**: `[TFE-WATCHDOG] skipping {reason}` when a gate rejects
- **WebSocket lineage event**: emit when a TFE is dispatched, payload:
  ```json
  {
    "type": "tfe_auto_dispatched",
    "test_suite_job_id": "ts-abc",
    "tfe_job_id": "tfe-xyz",
    "failure_count": 3,
    "suites": ["e2e"]
  }
  ```
  The UI subscribes and renders a "lineage" badge on the TestSuiteJob card showing the dispatched TFE. Emission goes through `emit_job_state_transition()` — never a manual WS send.

## Unit test coverage

Target: `src/tests/unit/test_test_suite_completion_watchdog.py` (new file)

| Test | Mock | Assertion |
|------|------|-----------|
| `test_watchdog_disabled` | enabled=False | Always returns None |
| `test_watchdog_wrong_job_type` | JOB_TYPE=presentation_generator | Returns None |
| `test_watchdog_no_snapshot` | completed job with no remediation_snapshot | Returns None |
| `test_watchdog_snapshot_all_passed` | snapshot.summary.all_passed=True | Returns None (nothing to fix) |
| `test_watchdog_snapshot_empty_failures` | failures=[] | Returns None |
| `test_watchdog_recursion_guard_honored` | metadata.triggered_by_tfe set | Returns None, no dispatch |
| `test_watchdog_failure_count_exceeded` | failures=100, max=50 | Returns None, notify fired |
| `test_watchdog_repair_tracker_blocks` | repair_tracker.allow=False | Returns None |
| `test_watchdog_dispatches_tfe_valid_snapshot` | all gates pass | TFE job created, pushed to todo, id_hash returned |
| `test_watchdog_repair_key_stable` | same snapshot twice | Same repair_key computed |
| `test_watchdog_never_raises_on_exception` | completed_job with malformed data | Returns None silently, doesn't crash queue |
| `test_watchdog_wires_via_running_queue_hook` | integration test with RunningFifoQueue | push_to_done triggers watchdog when status=completed |
