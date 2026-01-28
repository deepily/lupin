# Job State Transition WebSocket Event

**Created**: 2026-01-28 (Session 107)
**Status**: In Progress (Phase 4 of 10) - Server complete, client pending
**Branch**: `wip-v0.1.2-2026.01.28-job-state-change-refactoring`

## Problem Statement

Job cards get stuck in the run queue after completion because the client can't distinguish "API slow" from "job completed." The current `queue_*_update` events only signal count changes, not which specific job moved.

## Solution

Add fine-grained `job_state_transition` WebSocket event for deltas. Remove all race condition workarounds (provisional cards, registration tracking, protective logic).

## Documentation Index

| Document | Purpose |
|----------|---------|
| [01-implementation-current.md](01-implementation-current.md) | Active implementation phases (4-10) |
| [02-architecture.md](02-architecture.md) | WebSocket event design and payload specification |
| [03-decisions.md](03-decisions.md) | Design decisions: progressive enhancement, DOM reparenting |
| [04-testing-validation.md](04-testing-validation.md) | Test plan, verification steps, results |
| [archive/](archive/) | Completed phase documentation (1-3) |

## Quick Status

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Configuration files | ✅ Complete |
| 2 | `_emit_job_state_transition()` method | ✅ Complete |
| 3 | Server emissions at transition points | ✅ Complete (7/7) |
| 4 | Client subscription | 🔄 Next |
| 5 | Client handler | ⏳ Pending |
| 6 | Badge-only handlers | ⏳ Pending |
| 7 | Placeholder DOM nodes | ⏳ Pending |
| 8 | Remove cruft - data structures | ⏳ Pending |
| 9 | Remove cruft - methods | ⏳ Pending |
| 10 | Remove cruft - logic | ⏳ Pending |

## Critical Files

**Server (CoSA)**:
- `src/cosa/rest/fifo_queue.py` - Base emit method
- `src/cosa/rest/running_fifo_queue.py` - 6 transition emissions
- `src/cosa/rest/queue_consumer.py` - 1 transition emission

**Client (Lupin)**:
- `src/fastapi_app/static/js/notifications.js` - Handler and cruft removal
- `src/conf/lupin-app.ini` - Event configuration

## Related Documents

- Original plan: `src/rnd/2026.01.28-job-state-transition-implementation-plan.md`
