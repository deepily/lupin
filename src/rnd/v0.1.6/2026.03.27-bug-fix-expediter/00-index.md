# Bug Fix Expediter — Plan Index

**Created**: 2026-03-27 (Session 381)
**Status**: Planning
**Pattern**: Pattern 1 (Multi-Phase Implementation) with Phase 0 prerequisite
**Prefix**: [LUPIN]

---

## Documents

| Doc | Purpose | Status |
|-----|---------|--------|
| [00-index.md](00-index.md) | This file — navigation hub | Active |
| [01-implementation-plan.md](01-implementation-plan.md) | Full implementation plan with phases and tasks | Active |
| [02-agentic-job-consistency-audit.md](02-agentic-job-consistency-audit.md) | Phase 0 audit findings and remediation spec | Complete |
| [03-phase2-diagnose-orchestrator-plan.md](03-phase2-diagnose-orchestrator-plan.md) | Phase 2 detailed implementation plan — orchestrator, prompts, SDK delegation, voice gate, cancellation, unit tests | Complete |
| [04-phase3-propose-plan-artifacts.md](04-phase3-propose-plan-artifacts.md) | Phase 3 detailed implementation plan — proposal prompts, plan writer, fix selection, voice gate | Complete |
| [05-phase4-fix-coder-tester-plan.md](05-phase4-fix-coder-tester-plan.md) | Phase 4 detailed implementation plan — coder/tester delegation, retry loop, safety hooks, plan update | Complete |
| [06-phase5-trust-proxy-git-strategy-plan.md](06-phase5-trust-proxy-git-strategy-plan.md) | Phase 5 detailed implementation plan — trust proxy init, git operations, commit/branch/PR strategy | Active |

## Context

**Problem**: CJ Flow jobs that die end up in the dead bucket with rich failure context (stack traces, metadata, abstract objects) but no automated path to diagnosis and repair.

**Solution**: A new `BugFixExpediterJob` that takes a dead job's context, runs a three-phase forensic pipeline (diagnose → propose → fix), and optionally retries the original job to validate the fix — all runnable overnight via scheduled queuing.

**Prerequisite**: Existing agentic job implementations have significant consistency gaps (voice I/O API divergence, missing `set_job_id()`, config loading patterns, etc.) that must be remediated before building another job type.

## Architecture Summary

```mermaid
flowchart TD
    Dead["Dead Job<br>(stack trace, metadata, abstracts)"]
    UI["'Fix This' Button<br>+ Voice Triage Popup"]
    Queue["CJ Flow Queue<br>(now or scheduled)"]
    BFE["BugFixExpediterJob"]

    Dead --> UI --> Queue --> BFE

    subgraph "Three-Phase Pipeline"
        D["Phase 1: Diagnose<br>(Lead agent analyzes failure)"]
        P["Phase 2: Propose<br>(Plan doc + trust proxy gate)"]
        F["Phase 3: Fix<br>(Coder + Tester agents)"]
        D --> P --> F
    end

    BFE --> D

    F --> Branch{Trust Level?}
    Branch -->|"L1-L2"| Commit["Commit on branch"]
    Branch -->|"L3+"| PR["Fix branch + PR"]

    F --> Retry["Retry Original Job"]
    Retry --> Result{Outcome?}
    Result -->|Pass| Fixed["Status: fixed"]
    Result -->|Fail| Review["Status: review_needed"]
```

## Related Work

- SWE Team: `src/cosa/agents/swe_team/` (coder/tester agent definitions reused)
- Agentic Voice Workflow Skill: `~/.claude/skills/agentic-voice-workflow/SKILL.md`
- CJ Flow Persistence: `src/rnd/v0.1.6/2026.03.13-cj-flow-persistence-plan.md`
- Scheduled Queuing: `src/rnd/v0.1.6/2026.03.30-cj-flow/2026.03.27-cj-flow-timed-execution-monopolize-pause.md`
- CJ Flow Hub: `src/rnd/v0.1.6/2026.03.30-cj-flow/00-index.md`
