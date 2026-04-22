# Agentic Jobs & Recovery — Documentation

> **Audience**: Lupin operators enabling automated repair + test scheduling, and developers maintaining or extending the agentic job ecosystem
>
> **Last Updated**: 2026-04-10

This subsystem covers the three agentic job patterns that deal with **automated
recovery and test scheduling**: Bug Fix Expediter (BFE), Test Fix Expediter (TFE),
and the `TestSuiteJob` / `/schedule-tests` scheduler. These three patterns share
a common foundation in `src/cosa/agents/shared/` and are documented here as a
cohesive subsystem.

For documentation of OTHER agents (deep_research, podcast_generator,
presentation_generator, etc.) see the top-level project README and their
respective R&D directories under `src/rnd/`.

---

## Documents in this subsystem

| Doc | Purpose | Audience |
|-----|---------|----------|
| [**Bug Fix Expediter Guide**](bug-fix-expediter-guide.md) | Dead-job recovery agent — diagnose → propose → fix → git → retry. Phases 1-6, INI keys, trust-to-git mapping, troubleshooting. | Operators enabling auto-recovery, devs maintaining BFE |
| [**Test Fix Expediter Guide**](test-fix-expediter-guide.md) | Test-failure recovery agent — cluster → diagnose → propose → fix → git → rerun. Phase 0 clustering, `TestSuiteCompletionWatchdog`, 16 INI keys. | Operators running test suites, devs maintaining TFE |
| [**Test-Suite Scheduling Guide**](test-suite-scheduling-guide.md) | `TestSuiteJob` + `/schedule-tests` skill. Suite types, monopolize mode, remediation snapshot schema v1.0, REST API. | Operators scheduling test runs, devs integrating with `/api/test-suite/submit` |
| [**Shared Fix Primitives Reference**](shared-fix-primitives-reference.md) | `src/cosa/agents/shared/` package — `PlanWriter`, `GitStrategist`, `FixExecutor`, `FIX_PROMPT_BUILDERS` registry. How to add a new expediter agent. | Developers extending the expediter pattern |

---

## When to read which

| Your situation | Start here |
|---------------|------------|
| "One of my deep research jobs died — can I auto-fix it?" | [Bug Fix Expediter Guide](bug-fix-expediter-guide.md) |
| "I want to enable automated BFE on failed agentic jobs" | [Bug Fix Expediter Guide §6 How to Enable Auto-Fix](bug-fix-expediter-guide.md#6-how-to-enable-auto-fix) |
| "My test run has 22 failures — can TFE cluster and fix them?" | [Test Fix Expediter Guide](test-fix-expediter-guide.md) |
| "How does TFE decide which tests to rerun?" | [Test Fix Expediter Guide §4 Phase 6](test-fix-expediter-guide.md#4-six-phase-pipeline) |
| "I want to run the full test pyramid every night at 1am" | [Test-Suite Scheduling Guide §4 The `/schedule-tests` Skill](test-suite-scheduling-guide.md#4-the-schedule-tests-skill) |
| "What's in the remediation snapshot JSON?" | [Test-Suite Scheduling Guide §6 Remediation Snapshot Schema](test-suite-scheduling-guide.md#6-remediation-snapshot-schema-v10) |
| "How is the BFE/TFE shared `FixExecutor` structured?" | [Shared Fix Primitives Reference](shared-fix-primitives-reference.md) |
| "How do I add a new expediter agent of my own?" | [Shared Fix Primitives Reference §7 How to Add a New Expediter Agent](shared-fix-primitives-reference.md#7-how-to-add-a-new-expediter-agent) |
| "What's the difference between BFE and TFE?" | [TFE Guide §2 How TFE Differs from BFE](test-fix-expediter-guide.md#2-how-tfe-differs-from-bfe) |
| "BFE/TFE isn't firing — what's wrong?" | Troubleshooting sections of the respective guides |

---

## Canonical code locations

| Component | Path | Purpose |
|-----------|------|---------|
| Bug Fix Expediter | `src/cosa/agents/bug_fix_expediter/` | BFE agent package |
| Test Fix Expediter | `src/cosa/agents/test_fix_expediter/` | TFE agent package |
| Shared primitives | `src/cosa/agents/shared/` | `PlanWriter`, `GitStrategist`, `FixExecutor`, `FIX_PROMPT_BUILDERS` |
| Test-Suite Job | `src/cosa/agents/test_suite/` | `TestSuiteJob` + pytest subprocess wrapper |
| Dead-queue watchdog (BFE) | `src/cosa/rest/dead_queue_watchdog.py` | Dispatches BFE from dead queue |
| Done-queue watchdog (TFE) | `src/cosa/rest/test_suite_completion_watchdog.py` | Dispatches TFE from done queue |
| Queue consumer hooks | `src/cosa/rest/running_fifo_queue.py` | Where both watchdogs are invoked |
| Config keys | `src/conf/lupin-app.ini` + `lupin-app-splainer.ini` | 14 BFE keys + 16 TFE keys under `[Lupin: Baseline]` |
| Voice proxy scripts | `src/conf/notification-proxy-scripts/tfe.json` | Auto-answer scripts for TFE CI runs |
| Fixture snapshots | `src/tests/fixtures/tfe/*.json` | 6 sample remediation snapshots for unit tests |
| Live E2E driver | `src/tests/e2e/run-tfe-live-e2e.sh` | End-to-end `--dry-run`/`--live` script |
| `/schedule-tests` skill | `~/.claude/skills/schedule-tests/SKILL.md` | Voice-driven test scheduling workflow |

---

## R&D planning archive

Historical design + execution logs live under `src/rnd/v0.1.6/`:

- **BFE**: [`src/rnd/v0.1.6/2026.03.27-bug-fix-expediter/`](../../rnd/v0.1.6/2026.03.27-bug-fix-expediter/00-index.md) — 10 files, Phases 1-6 design + execution logs
- **TFE**: [`src/rnd/v0.1.6/2026.04.10-test-fix-expediter/`](../../rnd/v0.1.6/2026.04.10-test-fix-expediter/00-index.md) — 14 design docs + 6 execution logs
- **TestSuiteJob**: [`src/rnd/v0.1.6/2026.03.31-test-suite-agentic-job-plan.md`](../../rnd/v0.1.6/2026.03.31-test-suite-agentic-job-plan.md) — original design
- **CJ Flow packaging**: [`src/rnd/v0.1.4/2026.02.12-cj-flow-bounded-job-packaging-guide.md`](../../rnd/v0.1.4/2026.02.12-cj-flow-bounded-job-packaging-guide.md) — agentic job packaging conventions

These are **frozen planning artifacts** — they explain WHY the agents are
designed the way they are. The guides in this directory explain HOW to use and
maintain them in production.

---

## Test coverage

As of 2026-04-10:

| Suite | Tests | Location |
|-------|-------|----------|
| BFE unit tests | 58 (Phase 6 complete) | `src/tests/unit/test_bfe_*.py` |
| TFE unit tests | 197 | `src/tests/unit/test_tfe_*.py`, `test_test_suite_completion_watchdog.py`, `src/tests/smoke/test_tfe_live_pipeline.py` |
| Shared module tests | included in BFE + TFE suites | extraction regression gates |
| **Total BFE + TFE** | **255** |  |
| Full Lupin unit regression | **3119 passed, 1 xfailed** | `pytest src/tests/unit/` |

Run the full TFE suite:

```bash
pytest src/tests/unit/test_tfe_*.py src/tests/unit/test_test_suite_completion_watchdog.py -v
```

Run BFE + TFE together:

```bash
pytest src/tests/unit/test_bfe_*.py src/tests/unit/test_tfe_*.py src/tests/unit/test_test_suite_completion_watchdog.py -v
```

---

## Related documentation

- **[REST API Reference](../rest-api-reference.md)** — REST endpoints for BFE, TFE, and TestSuiteJob (quick-reference table; full schemas at `/docs` Swagger UI)
- **[Decision Proxy Admin Guide](../proxy-admin-guide.md)** — SWE Team Trust Proxy that both BFE and TFE read for Phase 5 git strategy
- **[Notification API Reference](../notification-api.md)** — how voice notifications flow from agentic jobs through cosa-voice MCP to the user
- **[WebSocket Architecture](../websocket-architecture.md)** — how Activity Log cards update in real time as BFE/TFE jobs progress
- **[Agentic Voice Workflow Skill](../../workflow/agentic-voice-workflow.md)** — canonical conventions for building ANY new agentic job (not just expediters)
- **[Docs Index](../README.md)** — main `src/docs/` table of contents
