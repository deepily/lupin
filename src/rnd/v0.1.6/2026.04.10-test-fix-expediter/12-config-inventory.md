# 12 — Config Inventory (INI + Splainer)

## Location

- INI: `src/conf/lupin-app.ini` under `[Lupin: Baseline]`
- Splainer: `src/conf/lupin-app-splainer.ini` (matching entries MANDATORY per CLAUDE.md memory)
- Agent router JSON: `src/conf/agent-router-agentic-commands.json`
- Notification proxy script: `src/conf/notification-proxy-scripts/test_fix_expediter.json`
- PEFT templates: `src/conf/training-templates/test_fix_expediter-templates.txt`

## TFE INI keys (12 total)

All keys go under `[Lupin: Baseline]` near the existing `bug fix expediter *` keys.

```ini
# --- TestFixExpediter ---

test fix expediter auto fix enabled              = false
test fix expediter max clusters                  = 8
test fix expediter max cluster seed failures     = 50
test fix expediter max diagnosis iterations      = 4
test fix expediter min diagnosis confidence      = 0.65
test fix expediter max fix attempts              = 2
test fix expediter cost cap usd                  = 15.00
test fix expediter wall clock timeout secs       = 2400
test fix expediter trust mode                    = inherit
test fix expediter rerun scope                   = affected
test fix expediter continue on cluster failure   = true
test fix expediter voice gate mode               = aggregate
```

## Key-by-key reference

### `test fix expediter auto fix enabled` (bool, default `false`)
**Purpose**: Master kill switch for the TestSuiteCompletionWatchdog. When `false`, the watchdog evaluates but never dispatches. When `true`, test suite failures automatically trigger TFE.
**When to flip**: After TFE is fully tested and the live E2E monopolize run passes. Until then, `false` prevents runaway fix loops in dev.

### `test fix expediter max clusters` (int, default `8`)
**Purpose**: Upper bound on K, the number of root-cause clusters Phase 0 produces. Caps LLM output shape and downstream voice gate complexity.
**Why 8**: Realworld test failures cluster at K=3-8. Beyond 8 is usually "the test pyramid is on fire" and deserves human attention rather than automated repair.

### `test fix expediter max cluster seed failures` (int, default `50`)
**Purpose**: Upper bound on N, the number of failures the watchdog accepts as input. If a TestSuiteJob reports >50 failures, the watchdog defers to human (notification fired, no TFE dispatched).
**Why 50**: Beyond 50 failures, the cluster heuristic gets noisy and LLM prompt cost climbs non-linearly.

### `test fix expediter max diagnosis iterations` (int, default `4`)
**Purpose**: Per-cluster diagnose iteration cap. The lead agent can refine its diagnosis up to this many times before accepting the best-effort result.
**Tuning**: Lower (2) for cost-sensitive dev; higher (6) for complex codebases. 4 matches BFE's default.

### `test fix expediter min diagnosis confidence` (float 0-1, default `0.65`)
**Purpose**: Early-exit threshold for diagnose iterations. If a diagnosis reaches this confidence, stop iterating and accept.
**Tuning**: Lower (0.5) = faster but more risk of low-quality diagnoses. Higher (0.8) = slower but more trustworthy. 0.65 is a middle ground.

### `test fix expediter max fix attempts` (int, default `2`)
**Purpose**: Per-cluster fix attempt cap. If the tester reports failure, the coder can redelegate up to this many times before giving up on that cluster.
**Why 2**: Third-attempt fixes are rarely successful and often reflect diagnosis error rather than fixable code.

### `test fix expediter cost cap usd` (float, default `15.00`)
**Purpose**: Per-TFE-run cost ceiling. Cost tracker raises `BudgetExceededError` when exceeded; TFE completes with partial state.
**Why $15**: Allows Phase 0 cluster (~$0.50) + K=5 diagnoses (~$5) + K=5 proposals (~$3) + K=5 fixes (~$5) + validation rerun dispatch (~$0) with headroom.

### `test fix expediter wall clock timeout secs` (int, default `2400` = 40 min)
**Purpose**: Per-TFE-run wall-clock ceiling. Covers all phases. If exceeded, TFE cancels in-flight work and marks as `timed_out`.
**Why 40 min**: Realworld TFE run ≈ 15-25 min. 40 is generous for K=8 complex clusters without being absurd.

### `test fix expediter trust mode` (string, default `inherit`)
**Purpose**: Trust proxy mode for Phase 5 git strategy.
**Values**:
- `inherit` — read from global SWE trust proxy config (default — normal behavior)
- `fixed_l1` — force L1 (commit_only) regardless of global trust level (testing)
- `fixed_l3` — force L3 (branch_and_pr) regardless of global trust level (testing)
- `shadow` — passive mode: compute strategy but don't execute (observability only)

### `test fix expediter rerun scope` (string, default `affected`)
**Purpose**: Phase 6 validation rerun scope.
**Values**:
- `affected` — rerun only the original test_types that failed (default — fast validation)
- `full` — rerun the full test pyramid (all suites — exhaustive validation, 35-60 min penalty)

### `test fix expediter continue on cluster failure` (bool, default `true`)
**Purpose**: Phase 3 fix-loop failure handling.
**Values**:
- `true` — fix failure in cluster N does NOT abort clusters N+1..K (default — maximum useful progress)
- `false` — first cluster failure aborts remaining clusters (atomic "all or nothing" mode)

### `test fix expediter voice gate mode` (string, default `aggregate`)
**Purpose**: Voice gate UX for Phases 1 and 2.
**Values**:
- `aggregate` — 2 gates total (one after diagnose, one after propose with multi-select) — default
- `per_cluster` — K+1 gates (one per cluster diagnosis plus one final confirmation) — high-touch mode

## Matching splainer entries (MANDATORY)

Per CLAUDE.md memory: every INI key MUST have a matching splainer entry. Splainer file `src/conf/lupin-app-splainer.ini` mirrors the structure. Example:

```ini
# src/conf/lupin-app-splainer.ini

test fix expediter auto fix enabled = |
    Master kill switch for the TestSuiteCompletionWatchdog.
    When false, TestSuiteJobs that complete with failures land in the done queue
    without triggering TestFixExpediter. Flip to true only after TFE has been
    fully validated in live E2E monopolize runs. Default: false.

test fix expediter max clusters = |
    Upper bound on the number of root-cause clusters that Phase 0 clustering
    will produce. The LLM refinement step consolidates down to this cap if the
    heuristic seed produces more. Realworld failure batches cluster at K=3-8.
    Default: 8.

# ... and so on for all 12 keys ...
```

## agent-router-agentic-commands.json entry

Add to the existing JSON array:

```json
{
  "command": "agent router go to test fix expediter",
  "short_description": "Automated test failure diagnosis and repair via clustered root-cause analysis",
  "job_class_path": "cosa.agents.test_fix_expediter.job.TestFixExpediterJob",
  "required_user_args": ["remediation_snapshot_path", "source_test_suite_job_id"],
  "system_provided_args": ["user_id", "user_email", "session_id"],
  "fallback_questions": {
    "remediation_snapshot_path": "Which remediation snapshot should I use? (path relative to io/)",
    "source_test_suite_job_id": "Which source TestSuite job is this remediation for?"
  }
}
```

## Config loading — `TestFixExpediterConfig`

```python
# src/cosa/agents/test_fix_expediter/config.py

from dataclasses import dataclass

@dataclass
class TestFixExpediterConfig:
    auto_fix_enabled              : bool    = False
    max_clusters                  : int     = 8
    max_cluster_seed_failures     : int     = 50
    max_diagnosis_iterations      : int     = 4
    min_diagnosis_confidence      : float   = 0.65
    max_fix_attempts              : int     = 2
    cost_cap_usd                  : float   = 15.00
    wall_clock_timeout_secs       : int     = 2400
    trust_mode                    : str     = "inherit"
    rerun_scope                   : str     = "affected"
    continue_on_cluster_failure   : bool    = True
    voice_gate_mode               : str     = "aggregate"

    dry_run                       : bool    = False   # not from INI, per-run flag

    @classmethod
    def from_config(cls, config_mgr) -> "TestFixExpediterConfig":
        return cls(
            auto_fix_enabled=config_mgr.get(
                "test fix expediter auto fix enabled", default=False,
                return_type="boolean"),
            max_clusters=config_mgr.get(
                "test fix expediter max clusters", default=8,
                return_type="int"),
            max_cluster_seed_failures=config_mgr.get(
                "test fix expediter max cluster seed failures", default=50,
                return_type="int"),
            max_diagnosis_iterations=config_mgr.get(
                "test fix expediter max diagnosis iterations", default=4,
                return_type="int"),
            min_diagnosis_confidence=config_mgr.get(
                "test fix expediter min diagnosis confidence", default=0.65,
                return_type="float"),
            max_fix_attempts=config_mgr.get(
                "test fix expediter max fix attempts", default=2,
                return_type="int"),
            cost_cap_usd=config_mgr.get(
                "test fix expediter cost cap usd", default=15.00,
                return_type="float"),
            wall_clock_timeout_secs=config_mgr.get(
                "test fix expediter wall clock timeout secs", default=2400,
                return_type="int"),
            trust_mode=config_mgr.get(
                "test fix expediter trust mode", default="inherit"),
            rerun_scope=config_mgr.get(
                "test fix expediter rerun scope", default="affected"),
            continue_on_cluster_failure=config_mgr.get(
                "test fix expediter continue on cluster failure", default=True,
                return_type="boolean"),
            voice_gate_mode=config_mgr.get(
                "test fix expediter voice gate mode", default="aggregate"),
        )
```

## Unit test for config (`test_tfe_config.py`)

| Test | Assertion |
|------|-----------|
| `test_defaults` | All 12 fields match documented defaults |
| `test_from_config_all_default` | Empty config_mgr returns defaults |
| `test_from_config_override_bool` | Override auto_fix_enabled=true in mock |
| `test_from_config_override_int` | Override max_clusters=5 in mock |
| `test_from_config_override_float` | Override cost_cap_usd=20.0 in mock |
| `test_from_config_override_string` | Override trust_mode=fixed_l3 |
