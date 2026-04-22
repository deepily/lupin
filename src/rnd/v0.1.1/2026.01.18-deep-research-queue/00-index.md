# Deep Research Queue Integration

> **Navigation Hub** | Session 69+ | Created: 2026-01-18

## Quick Links

| Document | Purpose | Status |
|----------|---------|--------|
| [01-implementation-current.md](./01-implementation-current.md) | Active phase tracking | Active |
| [02-architecture.md](./02-architecture.md) | System design & data flow | Reference |
| [03-decisions.md](./03-decisions.md) | Design decisions with rationale | Reference |
| [04-testing-validation.md](./04-testing-validation.md) | Test strategy & verification | Reference |
| [archive/](./archive/) | Completed phase documentation | Archive |

## Feature Summary

Add FastAPI endpoint to submit Deep Research jobs that run asynchronously within the existing todo/running/done/dead queue infrastructure, with progress notifications via WebSocket and a UI trigger from the notifications panel.

## Implementation Status

| Phase | Description | Status | Session |
|-------|-------------|--------|---------|
| 1 | AgenticJobBase Foundation | Pending | 69 |
| 2 | DeepResearchJob Implementation | Pending | 69 |
| 3 | FastAPI Endpoint | Pending | 69 |
| 4 | RunningFifoQueue Integration | Pending | 69 |
| 5 | cosa-voice MCP Enhancement | Pending | 70 |
| 6 | Notification Router (Frontend) | Pending | 71 |
| 7 | Unified Queue View (Frontend) | Pending | 71 |
| 8 | COSA Router Integration | Pending | 72 |

## Session Log

| Session | Date | Phases | Outcome |
|---------|------|--------|---------|
| 69 | 2026-01-18 | 1-4 | (In Progress) |

## Key Files

### New Files (To Be Created)
- `src/cosa/agents/agentic_job_base.py` - Base class for agentic jobs
- `src/cosa/agents/deep_research/job.py` - DeepResearchJob implementation

### Modified Files
- `src/cosa/rest/routers/deep_research.py` - New submit endpoint
- `src/cosa/rest/running_fifo_queue.py` - Agentic job handling

## References

- Plan file: `/home/rruiz/.claude/plans/[session-69-plan].md`
- Deep Research CLI: `src/cosa/agents/deep_research/cli.py`
- Queue system: `src/cosa/rest/todo_fifo_queue.py`
