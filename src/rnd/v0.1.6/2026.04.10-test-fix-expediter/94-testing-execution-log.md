# 94 — Testing Execution Log

**Tracks**: Implementation steps 15, 16, 18, 19 of the plan — proxy Q&A script, live pipeline test, E2E dry-run, live monopolize run.

**Design doc**: [`11-testing-strategy.md`](11-testing-strategy.md)

**Precondition**: Watchdog integration complete. See [`93-watchdog-integration-execution-log.md`](93-watchdog-integration-execution-log.md).

---

## Step 15: Proxy Q&A script

**Status**: BLOCKED on Phase 2 propose (step 9)

| Sub-step | Status | Commit | Notes |
|----------|--------|--------|-------|
| Create `src/conf/notification-proxy-scripts/test_fix_expediter.json` | TODO | — | Required for CI auto-proxy runs |
| Map Phase 1 aggregate diagnose gate question pattern → "yes" | TODO | — | `"Diagnosis complete. .* clusters analyzed. Proceed to proposal phase\\?"` → `"yes"` |
| Map Phase 2 aggregate proposal gate → select all proposals | TODO | — | `"Select fixes to apply .*"` → `all_options` selector |
| Map per-cluster diagnose gates (if voice_gate_mode=per_cluster) | TODO | — | |
| Document in `src/docs/automated-interactive-testing.md` | TODO | — | Add TFE row to the agent table |

---

## Step 16: Live pipeline test

**Status**: BLOCKED on all TFE phases complete (steps 7-12)

### `src/tests/smoke/test_tfe_live_pipeline.py`

| Scenario | Status | Commit | Notes |
|----------|--------|--------|-------|
| `basic_1cluster` | TODO | — | 1-cluster snapshot fixture, phases 0-6 complete |
| `kcluster_aggregate_gate` | TODO | — | 3-cluster snapshot, auto-proxy selects all, 3 commits |
| `partial_success` | TODO | — | 3-cluster, mock fix failure in C2, Phase 5 commits 2 clusters only |
| `dry_run` | TODO | — | dry_run=True, no edits, breadcrumbs visible |
| `error_startup` | TODO | — | Missing API key, graceful failure + urgent notif |
| `recursion_guard` | TODO | — | metadata.triggered_by_tfe set, watchdog refuses re-trigger |

### Execution runs

| Run | Mode | Status | Cost | Notes |
|-----|------|--------|------|-------|
| Mock client pass | `--auto-proxy --no-confirm` + mock | TODO | $0 | All 6 scenarios must pass |
| Live API pass | `--auto-proxy --no-confirm` + live | TODO | TBD | Cost cap $1 per scenario |

---

## Step 18: E2E TFE dry-run

**Status**: BLOCKED on all code steps

| Sub-step | Status | Commit | Notes |
|----------|--------|--------|-------|
| Create `src/tests/e2e/run-tfe-live-e2e.sh` | TODO | — | Shell script, disposable branch |
| Wire `bug_injector.py` invocation | TODO | — | Known-fixable bug |
| TestSuiteJob submission via `/schedule-tests` or direct API | TODO | — | |
| Watch-for-TFE helper script | TODO | — | Poll queue for auto-dispatched TFE job |
| Phase verification helper script | TODO | — | Assert each phase completed |
| Branch cleanup at end | TODO | — | |

### First dry-run execution

| Stage | Status | Observations |
|-------|--------|--------------|
| Bug injection | TODO | |
| TestSuiteJob submission | TODO | |
| TestSuiteJob completion (with failures) | TODO | |
| Watchdog dispatch (TFE job queued) | TODO | |
| TFE Phase 0 (cluster) | TODO | |
| TFE Phase 1 (diagnose, aggregate gate) | TODO | |
| TFE Phase 2 (propose, aggregate gate) | TODO | |
| TFE Phase 3 (dry_run — no edits) | TODO | |
| TFE Phase 5 (dry_run — no commits) | TODO | |
| TFE Phase 6 (dry_run — no dispatch) | TODO | |
| Branch cleanup | TODO | |

---

## Step 19: E2E TFE live monopolize

**Status**: BLOCKED on dry-run success + user confirmation

**Scheduled via `/schedule-tests` skill (mandatory per memory rule).**

| Sub-step | Status | Commit | Notes |
|----------|--------|--------|-------|
| Schedule via `/schedule-tests --test-types tfe_live --scheduled-at "01:00" --monopolize` | TODO | — | |
| Job ID captured | TODO | — | |
| User-present during run OR background monitor script | TODO | — | |

### Live run results (after execution)

| Stage | Status | Observations | Cost |
|-------|--------|--------------|------|
| Bug injection | TODO | | — |
| TestSuiteJob execution (real) | TODO | | — |
| Watchdog auto-dispatch | TODO | | — |
| TFE full walk-through | TODO | | TBD |
| Real fix applied | TODO | | — |
| Real branch + commit + PR | TODO | | — |
| Validation TestSuiteJob dispatched | TODO | | — |
| Validation run green | TODO | | — |
| Branch cleanup | TODO | | — |
| **Total cost** | | | TBD |

---

## Pre-merge checklist execution

Per [`11-testing-strategy.md`](11-testing-strategy.md) pre-merge checklist:

| # | Check | Status | Result |
|---|-------|--------|--------|
| 1 | Unit tests (~1,077 passing) | TODO | |
| 2 | Smoke tests | TODO | |
| 3 | WebSocket smoke (50/50) | TODO | |
| 4 | Integration tests `--bg` (44/44) | TODO | |
| 5 | E2E UI `--bg` (285+12) | TODO | |
| 6 | Live pipeline mock | TODO | |
| 7 | Live pipeline live | TODO | |
| 8 | E2E TFE dry-run | TODO | |
| 9 | E2E TFE live monopolize | TODO | |
| 10 | PEFT training (user-run, see 95) | TODO | |

---

## Deviations from testing strategy

_(add entries here as they occur)_

---

## Open follow-ups

_(add entries here as discovered)_
