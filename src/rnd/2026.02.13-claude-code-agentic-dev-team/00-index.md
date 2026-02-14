# Autonomous Multi-Agent Engineering Team — Navigation Hub

## Quick Links

| Document | Purpose | Status |
|----------|---------|--------|
| [Architecture Design](agent-team-architecture-design.md) | Phase 0 research — 6-role team, trust proxy, safety limits | DONE |
| [Implementation Plan](01-implementation-current.md) | Active phase tracking (Phases 1-5) | ACTIVE |
| [Architecture Decisions](02-architecture-decisions.md) | Design decisions traced to research | PENDING |
| [Testing & Validation](03-testing-validation.md) | Test results, coverage, regression tracking | PENDING |

## Phase Overview

```
Phase 0: Research + Architecture Design .............. DONE
Phase 1: Single Agent + Notification Integration ..... PENDING
Phase 2: Lead + Coder Delegation Loop ................ PENDING
Phase 3: Add Tester to Loop .......................... PENDING
Phase 4: Trust-Aware Proxy Expansion ................. PENDING
Phase 5: Full Team + CJ Flow Integration ............. PENDING
```

## Dependency Graph

```
Phase 1 (Foundation + Notifications)
    |
    +---> Phase 2 (Lead + Coder)
    |         |
    |         +---> Phase 3 (Add Tester)
    |                    |
    +---> Phase 4 (Trust Proxy) [INDEPENDENT — parallel after Phase 1]
    |                    |
    +--------------------+---> Phase 5 (Full Team + CJ Flow)
```

## Key References

- **Agentic Voice Workflow**: `src/workflow/agentic-voice-workflow.md`
- **Deep Research (Pattern Source)**: `src/cosa/agents/deep_research/`
- **Podcast Generator (Pattern Source)**: `src/cosa/agents/podcast_generator/`
- **Queue Protocol**: `src/cosa/rest/queue_protocol.py`
- **Job Base Class**: `src/cosa/agents/agentic_job_base.py`
- **Job Factory**: `src/cosa/rest/agentic_job_factory.py`

## Archive

Completed phase details will be moved to `archive/` to keep `01-implementation-current.md` under 25K tokens.

| Archive | Phase | Date |
|---------|-------|------|
| (none yet) | — | — |
