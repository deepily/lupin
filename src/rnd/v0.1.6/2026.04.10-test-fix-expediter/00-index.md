# TestFixExpediter (TFE) — Plan Index

**Created**: 2026-04-10 (Session 1cfcdf73)
**Status**: Planning (documentation-first phase)
**Pattern**: Pattern 1 (Multi-Phase Implementation) with Phase 0 prerequisite (extraction)
**Prefix**: [LUPIN]
**Direction chosen**: Option B — new TFE job type, shared FixExecutor, BFE stays clean

---

## Canonical references

- **Approved Claude plan**: [`../../../2026.04.10-test-fix-expediter-plan.md`](../../2026.04.10-test-fix-expediter-plan.md)
- **Agentic-voice-workflow skill**: [`../../../workflow/agentic-voice-workflow.md`](../../../workflow/agentic-voice-workflow.md)
- **Parent BFE planning dir**: [`../2026.03.27-bug-fix-expediter/00-index.md`](../2026.03.27-bug-fix-expediter/00-index.md)

---

## Documents

### Design docs (frozen on approval — the plan)

| Doc | Purpose | Status |
|-----|---------|--------|
| [00-index.md](00-index.md) | This file — navigation hub + phase status | Active |
| [01-design-overview.md](01-design-overview.md) | Option B rationale, architecture diagram, shared-module boundary | Active |
| [02-fix-executor-extraction-plan.md](02-fix-executor-extraction-plan.md) | BFE → shared refactor: PlanWriter, GitStrategist, FixExecutor | Active |
| [03-phase0-clustering-plan.md](03-phase0-clustering-plan.md) | Phase 0 heuristic + LLM clustering | Active |
| [04-phase1-diagnose-plan.md](04-phase1-diagnose-plan.md) | Test-aware diagnose phase, pytest semantics | Active |
| [05-phase2-propose-plan.md](05-phase2-propose-plan.md) | Aggregated multi-select proposal gate | Active |
| [06-phase3-fix-delegation-plan.md](06-phase3-fix-delegation-plan.md) | FixExecutor integration, FixContext adapter | Active |
| [07-phase5-multi-cluster-git-plan.md](07-phase5-multi-cluster-git-plan.md) | Single-branch, N-commits, one-PR strategy | Active |
| [08-phase6-rerun-validation-plan.md](08-phase6-rerun-validation-plan.md) | Async TestSuiteJob resubmit + recursion guard | Active |
| [09-watchdog-routing-plan.md](09-watchdog-routing-plan.md) | TestSuiteCompletionWatchdog + queue hook | Active |
| [10-prompt-design.md](10-prompt-design.md) | All TFE prompts collected for review | Active |
| [11-testing-strategy.md](11-testing-strategy.md) | Unit + smoke + live pipeline + E2E layers | Active |
| [12-config-inventory.md](12-config-inventory.md) | 12 INI keys + matching splainer entries | Active |
| [13-peft-training-data-plan.md](13-peft-training-data-plan.md) | Voice routing training templates + xml_coordinator | Active |
| [14-checkpoint-resume-and-completion-report.md](14-checkpoint-resume-and-completion-report.md) | Checkpoint-resume for stalled voice gates + TFE completion voice report | Active |

### Execution log docs (placeholders — updated during work)

| Doc | Tracks | Status |
|-----|--------|--------|
| [90-extraction-execution-log.md](90-extraction-execution-log.md) | Extraction steps 1-3 (PlanWriter, GitStrategist, FixExecutor) | Placeholder |
| [91-tfe-scaffolding-execution-log.md](91-tfe-scaffolding-execution-log.md) | TFE package build-out (step 6) | Placeholder |
| [92-tfe-phases-execution-log.md](92-tfe-phases-execution-log.md) | TFE phases 0-6 implementation (steps 7-12) | Placeholder |
| [93-watchdog-integration-execution-log.md](93-watchdog-integration-execution-log.md) | Watchdog + queue hook (step 13) | Placeholder |
| [94-testing-execution-log.md](94-testing-execution-log.md) | Unit/smoke/live pipeline + E2E runs (steps 16-19) | Placeholder |
| [95-peft-data-execution-log.md](95-peft-data-execution-log.md) | PEFT template authoring + xml_coordinator runs (step 17) | Placeholder |

---

## Phase status dashboard

| Phase | Description | Status | Execution log |
|-------|-------------|--------|---------------|
| **Phase 0 (doc)** | 20 docs written, gate fired | In progress | — |
| **Phase 1 — Extract** | PlanWriter → shared | Pending | [90](90-extraction-execution-log.md) |
| **Phase 1 — Extract** | GitStrategist → shared | Pending | [90](90-extraction-execution-log.md) |
| **Phase 1 — Extract** | FixExecutor → shared (riskiest) | Pending | [90](90-extraction-execution-log.md) |
| **Phase 2 — Scaffold** | TFE package + all agentic-voice-workflow modules | Pending | [91](91-tfe-scaffolding-execution-log.md) |
| **Phase 2 — P0 Cluster** | Heuristic + LLM clustering | Pending | [92](92-tfe-phases-execution-log.md) |
| **Phase 2 — P1 Diagnose** | Test-aware diagnose | Pending | [92](92-tfe-phases-execution-log.md) |
| **Phase 2 — P2 Propose** | Multi-select aggregate gate | Pending | [92](92-tfe-phases-execution-log.md) |
| **Phase 2 — P3 Fix** | FixExecutor delegation | Pending | [92](92-tfe-phases-execution-log.md) |
| **Phase 2 — P5 Git** | Multi-cluster commit/PR | Pending | [92](92-tfe-phases-execution-log.md) |
| **Phase 2 — P6 Rerun** | Async resubmit + recursion guard | Pending | [92](92-tfe-phases-execution-log.md) |
| **Phase 2 — Watchdog** | TestSuiteCompletionWatchdog | Pending | [93](93-watchdog-integration-execution-log.md) |
| **Phase 2 — Config** | INI keys + splainer + command JSON | Pending | [91](91-tfe-scaffolding-execution-log.md) |
| **Phase 2 — Proxy** | Q&A script + live pipeline test | Pending | [94](94-testing-execution-log.md) |
| **Phase 2 — PEFT data** | Template authoring + xml_coordinator | Pending | [95](95-peft-data-execution-log.md) |
| **Phase 3 — E2E dry** | Live dry-run via bug_injector | Pending | [94](94-testing-execution-log.md) |
| **Phase 3 — E2E live** | Monopolize run via /schedule-tests | Pending | [94](94-testing-execution-log.md) |

---

## Key design decisions (all resolved)

| Decision | Choice | Where explained |
|----------|--------|-----------------|
| BFE vs new agent | New TFE (shared FixExecutor) | [01](01-design-overview.md) |
| Clustering approach | Heuristic seed + LLM refine | [03](03-phase0-clustering-plan.md) |
| Voice gate default | Aggregate (2 gates per run) | [05](05-phase2-propose-plan.md) |
| Rerun scope default | Affected suites only | [08](08-phase6-rerun-validation-plan.md) |
| Branch strategy | One branch, N commits, one PR | [07](07-phase5-multi-cluster-git-plan.md) |
| Watchdog trigger | New TestSuiteCompletionWatchdog (done queue, not dead queue) | [09](09-watchdog-routing-plan.md) |
| Prompt registry | Polymorphic via key (`bfe` / `tfe`) | [02](02-fix-executor-extraction-plan.md), [10](10-prompt-design.md) |
| Recursion guard | `metadata["triggered_by_tfe"]` flag | [08](08-phase6-rerun-validation-plan.md) |

---

## Constraints

- **CoSA submodule rule**: Most edits land inside `src/cosa/`, which is a separate git repository. From the Lupin parent context: edit files, but NEVER run git there, never investigate submodule state, never propose cross-submodule commit ordering, never offer to commit CoSA. CoSA commit coordination is explicitly out of scope.
- **GPU workloads**: User-run only. PEFT trainer runs are handed back to the user — plan generates training data only.
- **Documentation-first**: All 20 docs must exist BEFORE any code is written. Gate via `ask_yes_no` after docs complete.
- **BFE Phase 6 live E2E** is running in a separate console. Step 1 (PlanWriter extraction) waits for that baseline.
