> Part 3 of 4 of the [Test Fix Expediter (TFE) Guide](../test-fix-expediter-guide.md): sections 5 to 7, the watchdog, INI reference and enabling auto-fix.

## 5. TestSuiteCompletionWatchdog

Source: `src/cosa/rest/test_suite_completion_watchdog.py`.

The watchdog is a singleton instantiated at FastAPI startup via
`init_watchdog(config_mgr, todo_queue, repair_tracker, ...)`. Its
`evaluate(completed_job)` method is called from
`src/cosa/rest/running_fifo_queue.py` in the success-path `jobs_done_queue.push()`
block (around line 401), parallel to how `DeadQueueWatchdog` fires on the failure
path.

### Six eligibility gates

All must pass for dispatch:

| Gate | Check | Rejection reason |
|------|-------|------------------|
| **1. Enabled** | `self.enabled` from INI | Feature flag off |
| **2. Job type** | `completed_job.JOB_TYPE == "test_suite"` | Not a TestSuiteJob |
| **3. Snapshot valid** | `artifacts["remediation_snapshot"]` is dict, schema v1.0, `all_passed=false`, non-empty failures | No snapshot to consume |
| **4. Recursion guard** | `metadata.get("triggered_by_tfe")` is None | Prevents infinite rerun loops |
| **5. Failure cap** | `len(failures) <= max_cluster_seed_failures` (default 50) | Defer mega-failure runs to humans |
| **6. Repair tracker** | `RepairAttemptTracker.allow()` (or equivalent method) returns True | Cost/iteration/wall-clock budget for this job-suite combo |

**Dispatch**: when all gates pass, the watchdog constructs a `TestFixExpediterJob`
inheriting the user identity from the original TestSuiteJob and pushes it to
`jobs_todo_queue`.

**Never raises**: `evaluate()` wraps all its logic in try/except. Errors are
logged via `logger.error()` and the method returns `None`. This is critical —
the watchdog runs inside the queue consumer thread, and any exception would
crash the whole consumer.

### Repair attempt tracker

Reuses BFE's `RepairAttemptTracker` from `src/cosa/rest/dead_queue_watchdog.py`.
Keyed by `(source_test_suite_job_id, tuple(sorted(suites_run)))` so repeatedly
submitting the same broken suite doesn't burn through budget on every push.

The watchdog is defensive about method name detection — it tries `allow()`,
`is_allowed()`, `check()`, and `can_attempt()` on the tracker before giving up.
Same for recording attempts (`record_attempt()`, `record()`, `track()`). This lets
TFE work against future tracker implementations without modification.

---

## 6. INI Reference

All TFE keys live in `src/conf/lupin-app.ini` under `[Lupin: Baseline]`. Splainer
entries live in `src/conf/lupin-app-splainer.ini`.

| Key | Default | Purpose |
|-----|---------|---------|
| `test fix expediter lead model` | `claude-opus-4-6` | Opus model for Phase 0 refinement, Phase 1 diagnose, Phase 2 propose |
| `test fix expediter worker model` | `claude-sonnet-4-6` | Sonnet model for Phase 3 Coder and Tester agents |
| `test fix expediter auto fix enabled` | `true` | Master kill switch for `TestSuiteCompletionWatchdog`. Default behavior is now "run unless told otherwise" — flip to `false` to disable globally, or use the per-run override (UI checkbox / `auto_fix_on_failure` field on `/api/v2/submit`) to disable on a single submission only. |
| `test fix expediter max clusters` | `8` | Upper bound K — LLM refinement consolidates seed clusters down to this cap |
| `test fix expediter max cluster seed failures` | `50` | Watchdog failure count cap — beyond this, defer to humans |
| `test fix expediter max diagnosis iterations` | `4` | Per-cluster Phase 1 refinement rounds |
| `test fix expediter min diagnosis confidence` | `0.65` | Early-exit threshold for Phase 1 iteration |
| `test fix expediter max fix attempts` | `2` | Per-cluster Phase 3 Coder-Tester retry loop cap |
| `test fix expediter cost cap usd` | `15.00` | Per-run USD ceiling (aliased as `budget_usd` for the shared `FixExecutor`) |
| `test fix expediter wall clock timeout secs` | `2400` | Whole-pipeline timeout (40 min covers cluster → diagnose → propose → fix → git → rerun dispatch) |
| `test fix expediter trust mode` | `inherit` | Trust proxy mode: `inherit`, `fixed_l1`, `fixed_l3`, `shadow` |
| `test fix expediter push fix branch enabled` | `false` | Whether trust level 3 and above pushes the fix branch (only `fix/<name>`, never forced) and opens the PR. Off, the commits stay on a local branch and the run says nothing was pushed. |
| `test fix expediter rerun scope` | `affected` | Phase 6 rerun scope: `affected` (original suites) or `full` (all) |
| `test fix expediter continue on cluster failure` | `true` | Phase 3: continue remaining clusters after a failure (`true`) or abort whole batch (`false`) |
| `test fix expediter voice gate mode` | `aggregate` | Phase 1+2 gate UX: `aggregate` (2 total gates, multi-select for Phase 2) or `per_cluster` (K+1 gates) |
| `test fix expediter feedback timeout seconds` | `300` | Voice gate human response timeout |
| `test fix expediter narrate progress` | `true` | Voice breadcrumbs at every phase transition |

**Config loading**: `TestFixExpediterConfig.from_config(config_mgr)` reads all keys
with type coercion. Source: `src/cosa/agents/test_fix_expediter/config.py`. The
dataclass exposes `budget_usd` as a post-init alias over `cost_cap_usd` so the
shared `FixExecutor` (which reads `config.budget_usd`) works unchanged.

### Per-invocation model overrides

`lead model` and `worker model` can be overridden per job submission via
`args.lead_model_override` / `args.worker_model_override`. The job class
stores them as `self.lead_model_override` / `self.worker_model_override`
and applies them in `_execute()` after `from_config()` loads the INI defaults.

Unlike BFE (which gets spawned by a watchdog), TFE is typically submitted
directly via `/api/push` (or by `TestSuiteCompletionWatchdog` during auto-fix).
Either path can include the override keys in `args_dict`, and the factory
(`agentic_job_factory.py`) passes them straight to the constructor.

**Primary use case**: `./src/tests/e2e/run-tfe-live-e2e.sh --live --cheap`
runs TFE with Sonnet lead + Sonnet worker for ~60-75% cost reduction on
trivially-fixable E2E fixtures. Watchdog-dispatched TFE (real test-suite
failures) leaves overrides unset → use INI defaults.

---

## 7. How to Enable / Disable Auto-Fix

### Step 1: Master switch (INI default)

As of 2026-04-10, auto-fix is **enabled by default**:

```ini
# src/conf/lupin-app.ini
test fix expediter auto fix enabled = true
```

The `TestSuiteCompletionWatchdog` is initialized at server startup via the
unified facade `init_watchdogs()` in `src/cosa/rest/watchdogs.py`, called from
`src/lupin_app/main.py`.

To disable auto-fix globally, flip the key to `false` and restart the server.

### Per-run override (no INI round-trip)

For a single submission, override the INI default without changing it:

- **UI**: Check or uncheck the **🛠️ Auto-fix on failure (TFE)** checkbox in the
  test runner card on the notifications dashboard. The checkbox's initial state
  mirrors the INI default (read from `/api/config/client`); toggling it applies
  only to the next submission.
- **API**: Pass `auto_fix_on_failure` in the `/api/v2/submit` body:
  - `true` → force-enable for this run
  - `false` → force-disable for this run
  - omitted/`null` → use the INI default

The override is honored by Gate 1 of `_evaluate_inner` and never mutates the
INI file.

### Step 2: Start conservative

Leave these at their defaults for your first few TFE runs:

```ini
test fix expediter trust mode       = inherit   # uses global SWE proxy, defaults to L1
test fix expediter voice gate mode  = aggregate # 2 gates, you stay in control
test fix expediter rerun scope      = affected  # fast validation
```

This gives you BFE-equivalent trust semantics: commit on your current branch, no
auto-branching, no auto-PR. Watch a few runs in the Activity Log before escalating.

### Step 3: Monitor the first few runs

Submit a test suite that you know will fail (e.g., inject a broken test via
`bug_injector.py` — see `src/tests/e2e/run-tfe-live-e2e.sh` for the scripted
recipe). When the TestSuiteJob completes:

1. The done-queue watchdog fires
2. A `tfe-*` job appears in the todo → run → done pipeline
3. cosa-voice sends a breadcrumb "Clustering N failures into K groups..."
4. At Phase 1's aggregate gate, you see a summary of all K clusters + confidences
5. Approve to proceed to Phase 2
6. At Phase 2's multi-select gate, you see a checklist of every proposed fix
7. Pick a subset (or all) and proceed
8. Phase 3 applies the fixes through the Coder+Tester loop
9. Phase 5 commits them as N commits on one branch
10. Phase 6 queues a validation rerun

Check the plan document at
`io/swe-team/plans/{your_email}/YYYY.MM.DD-tfe-{slug}-plan.md` for the full audit
trail.

### Step 4: Graduate to active mode (optional)

Once you trust TFE's behavior in shadow (trust level 1) mode, graduate to `active` — real
branch creation + PR via `gh`:

```ini
test fix expediter trust mode = inherit  # leave at inherit; SWE proxy manages the level
```

The SWE Team Trust Proxy must be populated with level 3+ earned trust via the
ratification workflow. See the
[Decision Proxy Admin Guide](../../proxy-admin-guide.md) for how to earn trust levels.

Alternatively, for testing only: force level 3 via

```ini
test fix expediter trust mode = fixed_l3
```

This bypasses the proxy and unconditionally uses branch+PR. **Do not use
`fixed_l3` in production** — it skips the earned-trust safety check.

### Step 5: Disable the aggregate gate for overnight runs

Full autonomy requires removing the voice gates. Set:

```ini
test fix expediter voice gate mode       = aggregate   # still the default
test fix expediter feedback timeout seconds = 10       # fail fast on no response
```

Then the gates still fire but time out quickly to fallback behavior. (Full
autonomous operation — skipping gates entirely — is not currently supported;
this is by design. Gates are a safety feature.)

---

