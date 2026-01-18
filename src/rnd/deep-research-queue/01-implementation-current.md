# Implementation Status - Deep Research Queue

> **Active Phase Tracking** | Last Updated: 2026-01-18

## Current Phase: 1-4 (Backend API)

### Session 69 Goals
1. Create AgenticJobBase foundation class
2. Create DeepResearchJob implementation
3. Add FastAPI endpoint `POST /api/deep-research/submit`
4. Integrate with RunningFifoQueue

---

## Phase 1: AgenticJobBase Foundation

**Status**: Pending

**File**: `src/cosa/agents/agentic_job_base.py`

**Purpose**: Abstract base class for long-running Claude Code agentic jobs (Deep Research, Podcast Generation, etc.)

**Key Features**:
- Job ID generation with type prefix
- Queue system required attributes (`id_hash`, `last_question_asked`, `user_id`)
- Execution state tracking (started_at, completed_at, status, error)
- `is_cacheable` property (False for agentic jobs)
- Abstract `do_all()` and `_execute()` methods

**Verification**:
- [ ] Class imports without error
- [ ] Can instantiate subclass
- [ ] `id_hash` generated with correct prefix

---

## Phase 2: DeepResearchJob Implementation

**Status**: Pending

**File**: `src/cosa/agents/deep_research/job.py`

**Purpose**: Concrete implementation for Deep Research background jobs

**Key Features**:
- Inherits from AgenticJobBase
- Wraps existing CLI research logic
- `JOB_TYPE = "deep_research"`, `JOB_PREFIX = "dr"`
- Async execution via `asyncio.run()`
- Stores report_path, abstract, cost_summary after completion

**Verification**:
- [ ] Job instantiates with query, user_email, budget
- [ ] `last_question_asked` returns formatted string
- [ ] `do_all()` calls `_execute()` via asyncio.run()

---

## Phase 3: FastAPI Endpoint

**Status**: Pending

**File**: `src/cosa/rest/routers/deep_research.py` (modify existing)

**Endpoint**: `POST /api/deep-research/submit`

**Request Body**:
```json
{
    "query": "Research topic",
    "user_email": "user@example.com",
    "budget": 1.00,
    "websocket_id": "wise-penguin"
}
```

**Response**:
```json
{
    "status": "queued",
    "job_id": "dr-abc123",
    "queue_position": 3,
    "message": "Deep research job queued"
}
```

**Verification**:
- [ ] Endpoint accessible at `/api/deep-research/submit`
- [ ] Returns 401 without auth token
- [ ] Returns 422 for invalid request body
- [ ] Creates DeepResearchJob and pushes to todo_queue
- [ ] Returns job_id in response

---

## Phase 4: RunningFifoQueue Integration

**Status**: Pending

**File**: `src/cosa/rest/running_fifo_queue.py` (modify existing)

**Changes Required**:
- Add `isinstance(job, AgenticJobBase)` check in `_process_job()`
- Skip snapshot caching for agentic jobs
- Ensure WebSocket events fire correctly

**Verification**:
- [ ] DeepResearchJob picked up by consumer thread
- [ ] Job moves through todo → running → done
- [ ] No snapshot storage attempted
- [ ] WebSocket events broadcast

---

## Blockers & Issues

_None currently identified_

---

## Next Session (70)

- Phase 5: cosa-voice MCP Enhancement
  - Add `job_id` parameter to notification tools
  - Enable job-specific notification routing
