> Part 4 of 5 of the [Test-Suite Scheduling Guide](../test-suite-scheduling-guide.md): monopolize, cost and TFE.

## 7. Monopolize Mode

**What it is**: `monopolize=True` declares that the job needs exclusive DB access
during its run. The `RunningFifoQueue` consumer enforces this — only one
monopolize job runs at a time. And other monopolize jobs wait in the todo queue
even if regular (non-monopolize) jobs could otherwise run in parallel.

**Why tests need it**: Lupin's test suites hot-swap the database configuration at
startup. The `run-integration-tests.sh` and `run-e2e-ui-tests.sh` scripts
temporarily reconfigure `lupin-app.ini` to point at the test DB, run pytest, then
restore the original config. If two test runs overlapped, they'd race on the
config file and produce non-deterministic results.

**When it's set**: `TestSuiteJob.__init__()` always passes `monopolize=True` to
the parent `AgenticJobBase`. You can't turn it off — it's a hard requirement for
test runs. Non-monopolize jobs (deep research, podcast generator, etc.) coexist
with a running TestSuiteJob, but no other monopolize job can start until the
TestSuiteJob finishes.

**Scheduling conflicts**: if you schedule two TestSuiteJobs for 23:00, they'll run
sequentially — the second one starts when the first finishes. The queue consumer
doesn't try to split them or warn you; it just serializes them.

**User-facing implications**:

- Schedule monopolize-heavy runs for off-hours (overnight, weekends)
- Cancel rather than submit a second monopolize job if you realize the first
  will be wrong
- Avoid scheduling an `e2e` run that will overlap with a known long-running
  integration test

---

## 8. Cost Model

Test suites are **pytest subprocess** workloads — they don't invoke Claude API
unless your tests themselves do. Direct Claude API cost of a TestSuiteJob is
effectively **zero**.

However, there are indirect costs:

1. **Compute time** on your machine — the subprocess runs locally; you pay CPU +
   disk I/O but no cloud bill.
2. **TFE auto-fix** (if enabled). When a test suite fails and TFE takes over,
   TFE's diagnose, propose and fix phases consume Claude API budget.
   The cap is `test fix expediter cost cap usd` (default $15 per TFE run). See the
   [TFE guide section 8 Cost Model](../test-fix-expediter-guide/03-watchdog-ini-and-enabling.md#6-ini-reference).
3. **Validation rerun** triggered by TFE's rerun-validation phase. It submits a *new*
   TestSuiteJob targeting the affected suites. That job has the same cost
   profile (nearly $0 direct, risk of triggering TFE again if clusters remain
   unfixed, though the recursion guard prevents cascading).

**Typical cost per scheduled run**: $0 if tests pass, up to $15 if TFE fires.
Auto-fix is **on by default** (`test fix expediter auto fix enabled = true`).
Set the per-run `auto_fix_on_failure: false` override on
`/api/v2/submit` `args` to suppress TFE for an individual run without changing
the INI. The test runner UI checkbox does the same.

**Budget discipline**: if you're running the full pyramid nightly, you're looking
at $0 per run on green days and up to $15 on red days. Over a month of 30
nightly runs averaging 2 red days: $30 per month. Tune
`test fix expediter cost cap usd` downward if that's too high for your budget.

---

## 9. Interaction with TFE

The default is `test fix expediter auto fix enabled = true`. Every TestSuiteJob that lands in the done queue is evaluated by
`TestSuiteCompletionWatchdog`. If the job's remediation snapshot shows failures,
the watchdog auto-dispatches a TFE job. The TFE job then walks its six-phase pipeline, from cluster to rerun validation, as
described in the [TFE guide](../test-fix-expediter-guide.md).

**Per-run override**: pass `auto_fix_on_failure: false` in the
`/api/v2/submit` `args` to skip TFE on a single submission without changing
the INI default. The test runner UI checkbox does the same. Pass
`auto_fix_on_failure: true` to force-enable TFE for one run when the INI default
is `false`. Omitting the field uses the INI default.

**The recursion guard** is critical: TFE's rerun-validation phase creates a new
TestSuiteJob with `metadata["triggered_by_tfe"] = <tfe_job_id>`. When the rerun
completes, the watchdog sees the metadata flag and refuses to dispatch another
TFE. This is the only thing preventing an infinite rerun loop.

**What if I want manual control?** Flip
`test fix expediter auto fix enabled = false` globally in the INI. Or use the
per-run `auto_fix_on_failure: false` override on individual submissions. To
trigger a TFE run manually after suppressing the watchdog, submit it directly
via the REST API:

```bash
curl -X POST http://localhost:7999/api/push \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "agent router go to test fix expediter",
    "args": {
      "remediation_snapshot_path": "io/test-suite/2026.04.10-at-14:53-EDT-e2e-remediation.json",
      "source_test_suite_job_id":  "ts-abc12345",
      "original_test_types":       "e2e",
      "dry_run":                   "false"
    }
  }'
```

Manual submission bypasses the watchdog entirely. Useful for:

- **Curated fixes**: review the snapshot first, decide whether to let TFE try
- **Retry after a failed TFE run**: if TFE failed in the fix phase once, you can re-submit
  manually after investigating
- **Testing TFE in isolation**: submit against a known-good snapshot fixture from
  `src/tests/fixtures/tfe/`

**What if a TestSuiteJob crashes rather than completes?** Then it lands in the
dead queue and **BFE** (not TFE) picks it up. The dead queue path is for agentic
jobs that crashed; the done queue path is for agentic jobs that completed with
failures. These are distinct code paths with distinct watchdogs.

### The third case: a run that returned normally but executed zero tests

Warning: **This behaviour changed.** There is a case that is neither of the
two above, and it used to be filed under the wrong one. If the suite subprocess
crashes at *startup* — before any test runs — `_execute()` still returns normally. So `do_all` used to set `JobState.COMPLETED`. The job landed in the **done**
queue reading `completed` while carrying `0 passed / 0 failed / 0 errors / 0 skipped`.

Measured on job: the capped JS-test lane refused to start (`exit=70`,
no container memory ceiling) and the run was reported as completed.

**Now**: a run that executed zero tests terminates as `JobState.FAILED` and routes
to the **dead** queue, with `job.error` naming the verdict. A run that never
executed has not passed.

**Three deliberate exclusions — do not "tidy" these into the condition:**

| Case | State | Why |
|---|---|---|
| **Genuine red** (tests ran, some failed) | `COMPLETED` → done → **TFE** | The job did its work and is reporting a red. TFE reads the done queue and gates on `all_passed`; routing reds to dead would hide them from the thing that remediates them. |
| **Partial run** (one tier ran, another did not) | `COMPLETED` → done | Also classifies as `NOT EXECUTED`. But its counts and `all_passed` already tell the truth. Routing partials to dead is a behaviour change outside this defect. |
| **Dry run** (all-zero counts, because that path sets every count to zero) | `COMPLETED` → done | The dry-run path builds `suite_results` with zero counts too. `overall_status` is published by the *real* run path only. And that is what separates "a real run executed nothing" from "no real run happened". |

**Consequence worth knowing**: because these now reach the dead queue, **BFE** may
engage on a startup crash where previously nothing did. That is the intended
direction — a suite that cannot start is a defect — but it is a new trigger.

**This was not a live false green**. Every machine consumer reads
`cost_summary["all_passed"]`, which was already correctly `False`
(`test_suite_completion_watchdog.py:150`, `test_fix_expediter/snapshot_loader.py:161`). No caller gates on the job status. The fix closes the gap before one does.

---
