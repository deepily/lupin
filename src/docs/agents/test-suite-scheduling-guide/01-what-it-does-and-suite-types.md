> Part 1 of 5 of the [Test-Suite Scheduling Guide](../test-suite-scheduling-guide.md): what it does and suite types.

# Test-Suite Scheduling Guide

**Audience**: Lupin operators scheduling test runs and developers integrating with `/api/v2/submit` (test-suite command)

**Scope**: `src/cosa/agents/test_suite/`, the `/schedule-tests` skill, `POST /api/v2/submit` (test-suite command), remediation snapshot schema v1.0

**See Also**:
- [Test Fix Expediter Guide](../test-fix-expediter-guide.md) — TFE consumes the remediation snapshots TestSuiteJob produces
- [Bug Fix Expediter Guide](../bug-fix-expediter-guide.md). If a TestSuiteJob crashes rather than completes, BFE picks it up from the dead queue
- [Shared Fix Primitives Reference](../shared-fix-primitives-reference.md). Shared machinery across both expediters
- Skill: `~/.claude/skills/schedule-tests/SKILL.md` — voice-driven scheduling workflow (user-global Claude Code skill, outside the project tree)

---

## Table of Contents

1. [What the TestSuiteJob Does](#1-what-the-testsuitejob-does)
2. [Supported Suite Types](#2-supported-suite-types)
3. [Architecture](02-architecture-and-schedule-tests-skill.md#3-architecture)
4. [The `/schedule-tests` Skill](02-architecture-and-schedule-tests-skill.md#4-the-schedule-tests-skill)
5. [REST API: `/api/v2/submit` (test-suite command)](03-rest-api-and-remediation-snapshot.md#5-rest-api-apiv2submit-command-agent-router-go-to-test-suite)
6. [Remediation Snapshot Schema (v1.0)](03-rest-api-and-remediation-snapshot.md#6-remediation-snapshot-schema-v10)
7. [Monopolize Mode](04-monopolize-cost-and-tfe.md#7-monopolize-mode)
8. [Cost Model](04-monopolize-cost-and-tfe.md#8-cost-model)
9. [Interaction with TFE](04-monopolize-cost-and-tfe.md#9-interaction-with-tfe)
10. [Troubleshooting](05-troubleshooting-and-related-docs.md#10-troubleshooting)

---

## 1. What the TestSuiteJob Does

The **`TestSuiteJob`** is an agentic job that wraps the existing shell-script-based
test runners (`run-unit-tests.sh`, `run-integration-tests.sh`, `run-e2e-ui-tests.sh`,
etc.) into the CJ Flow queue system. It handles:

- **Scheduling**: cron-like future execution via the `scheduled_at` field
- **Monopolize mode**: exclusive access to the database during hot-swapped test config
- **Cancellation**: graceful subprocess termination mid-run
- **Voice notifications**: cosa-voice breadcrumbs + completion announcements
- **JUnit XML parsing**: structured result aggregation from the pytest `--junit-xml` output
- **Remediation snapshot emission**: schema-v1.0 JSON artifact listing every failure for downstream consumption (primarily by TFE)
- **Markdown test report**: human-readable Markdown summary at `io/test-suite/YYYY.MM.DD-at-HH:MM-EST-{suites}-results.md`

**Source**: `src/cosa/agents/test_suite/job.py` defines `TestSuiteJob(AgenticJobBase)`
with `JOB_TYPE = "test_suite"`, `JOB_PREFIX = "ts"`.

**Why a dedicated job type?** Before the TestSuiteJob, running the test pyramid
required manual `pytest` invocations or ad-hoc cron entries. Now the test runner
is a first-class citizen in CJ Flow. It reports progress via WebSocket, can be
cancelled from the Activity Log, and produces structured result artifacts. Via
TFE it can trigger automated remediation on failure.

---

## 2. Supported Suite Types

| Type | Script path | Default timeout | Typical runtime | Test count |
|------|-------------|-----------------|-----------------|------------|
| `unit` | `src/tests/run-unit-tests.sh` | refused by the test container: it runs on the host | not offered here | `pytest src/tests/unit/` on the host. A request naming `unit` answers `status: failed` with the cause in `error` |
| `docker_smoke` | `src/tests/run-docker-smoke-gate.sh` | refused by the test container: it runs on the host | not offered here | `src/tests/run-docker-smoke-gate.sh` on the host. The three docker smoke files; a skip, an error or a missing file is a failure. A request naming `docker_smoke` answers `status: failed` with the cause in `error` |
| `smoke` | `src/tests/run-smoke-tests.sh` | 3600s (60 min) | ~40 min | ~340 tests (excludes destructive `test_proxy_integration.py` — own:8000 venue) |
| `smoke_direct` | `src/tests/run-smoke-direct.sh` | 1200s (20 min) | ~10-20 min | live pipeline |
| `websocket` | `src/scripts/run-websocket-smoke-tests.sh` | 300s (5 min) | ~3 min | ~50 tests |
| `integration` | `src/tests/run-integration-tests.sh` | 2000s (33 min) | ~17 min | ~358 tests (320 passed + 38 skipped) |
| `e2e` | `src/scripts/run-e2e-ui-tests.sh` | 5000s (83 min) | 2992.7s full run (ts-cf9f5f85) | 830 tests. The whole suite under one timeout; the merge pyramid runs the halves below instead |
| `e2e_a` | `src/scripts/run-e2e-ui-tests-half-a.sh` | 2500s (42 min) | 1467.0s (ts-2aa41f55) | files in `src/tests/e2e_ui/partition/half-a.txt` |
| `e2e_b` | `src/scripts/run-e2e-ui-tests-half-b.sh` | 2500s (42 min) | 1452.0s (ts-2aa41f55) | files in `src/tests/e2e_ui/partition/half-b.txt` |
| `all` | `src/tests/run-all-tests.sh` | 3600s (60 min) | ~1.5-2 h across legs | Full pyramid (expands into per-leg runs, each with its own budget) |
| `presentation` | `src/tests/run-presentation-regression.sh` | 1800s (30 min) | ~10-30 min | Presentation regression |

**Source**: `SUITE_SCRIPTS` and `SUITE_TIMEOUTS_SECONDS` dicts at the top of
`src/cosa/agents/test_suite/job.py`.

**The test-suite live smoke cannot run as, or inside, a suite job**: `src/tests/smoke/test_test_suite_live_pipeline.py`
submits a test-suite job, which always takes the monopolize slot. Inside any suite job (`smoke`, `smoke_direct`,
`pytest_direct`) the suite job holds that slot, so the submitted job waits until the suite ends. Every suite job exports
`LUPIN_TEST_MONOPOLIZE_PARENT_ID`, and the smoke skips when it is set. Run it by hand from a host shell with
`src/scripts/run-test-suite-live-smoke.sh`. The runner exits 64 unless `cosa.rest.venue_idle --port 8000` exits 0, then
runs the one file against `:8000` and exits with pytest's status.

**Multi-suite runs**: at `POST /api/v2/submit` (`args.test_types`), `test_types` is one comma-separated
string. Pass `"integration,e2e"` to run both sequentially — a JSON list is refused 422,
because the request model declares a `str` (measured). The job
object itself holds a list after the router splits the string. The job aggregates results
across all requested suites in a single Markdown report and a single remediation
snapshot.

**E2E halves**: `e2e_a` and `e2e_b` split the e2e suite into two halves
by file, balanced on measured per-file time. Submit `"e2e_a,e2e_b"` to run the whole suite with
a separate timeout, junit and log per half: a timeout then discards one half's results, not both.
They run back to back in one job and cannot run side by side. `:8000` runs one monopolize job at a
time, the runner's PID file refuses a second copy. And every test truncates the shared
`lupin_db_test`. `src/tests/unit/test_e2e_halves_partition.py` fails when a collectable e2e test
file is in neither half or in both. A new e2e test file therefore goes into one of the two partition
manifests, whichever half is lighter.

**The `all` suite**: expands to the curated pyramid in `ALL_SUITE_COMPONENTS`, each leg with its own
timeout. In a container it runs the pyramid without `unit` and `docker_smoke`. The result says so.
The notes `unit: not run here, host tier` and `docker_smoke: not run here, host tier` appear in the summary, the abstract, the report and `cost_summary["suites_not_run"]`.
A pyramid without them is not the full pyramid, so read that note before reading the verdict.
The job also tells the coverage gate (`LUPIN_TEST_TIERS_NOT_RUN`), which then answers exit 2, inconclusive,
because the data file holds no unit tier. Run unit on the host, and run the coverage gate there.

### Cancellation

`TestSuiteJob` supports cancellation mid-run. A cancel request comes in via
the queue (e.g., the user clicks "Cancel" on the Activity Log card or submits another
monopolize request that conflicts). The subprocess running pytest is then sent SIGTERM,
waited on with a 10-second grace period, then SIGKILLed if still alive.
Cancellation produces a partial result dict with `exit_code=-1` and
`error="Cancelled by user"`.

---
