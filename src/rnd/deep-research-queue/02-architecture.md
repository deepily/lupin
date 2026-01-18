# Architecture - Deep Research Queue Integration

> **System Design Document** | Created: 2026-01-18

## System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│  Notifications UI                                                    │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  [New Research]  →  Modal: Enter query, budget, email       │   │
│  └─────────────────────────────────────────────────────────────┘   │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ POST /api/deep-research/submit
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  FastAPI Endpoint                                                    │
│  - Validates request (query, user_email, budget)                    │
│  - Creates DeepResearchJob                                          │
│  - Pushes to todo_queue                                             │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ todo_queue.push(job)
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Queue System (Existing)                                             │
│  todo_queue → consumer_thread → running_queue → done/dead_queue    │
│                                      │                               │
│                         DeepResearchJob.do_all()                    │
│                                      │                               │
│                         • run_research() async                       │
│                         • save_report_with_frontmatter()            │
│                         • Send completion notification               │
└─────────────────────────────────────────────────────────────────────┘
                               │ WebSocket events
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Notifications UI                                                    │
│  - queue_todo_update, queue_running_update, queue_done_update       │
│  - Research completion notification with report link                │
└─────────────────────────────────────────────────────────────────────┘
```

## Class Hierarchy

```
AgenticJobBase (abstract)
├── DeepResearchJob (Phase 1-2)
├── PodcastGenerationJob (future)
└── [Other agentic jobs]

AgentBase (existing)
├── AgentMath
├── AgentCalendar
├── AgentWeather
└── [Other simple agents]
```

## Data Flow

### Job Submission

```
1. User clicks "New Research" button in UI
2. Modal collects: query, budget, email
3. Frontend POSTs to /api/deep-research/submit
4. Endpoint creates DeepResearchJob instance:
   - Generates job_id: "dr-{uuid8}"
   - Sets user_id, user_email, session_id
   - Stores query, budget, lead_model
5. Job pushed to todo_queue
6. WebSocket broadcasts queue_todo_update
7. Response returned with job_id
```

### Job Execution

```
1. Consumer thread pops from todo_queue
2. Job moved to running_queue
3. WebSocket broadcasts queue_running_update
4. job.do_all() called:
   a. asyncio.run(_execute())
   b. _execute():
      - Sends progress notifications via cosa-voice
      - Calls Deep Research CLI functions
      - Saves report with frontmatter
      - Sends completion notification
   c. Returns result string
5. Job moved to done_queue (or dead_queue on error)
6. WebSocket broadcasts queue_done_update
```

## Queue Integration Points

### TodoFifoQueue

**File**: `src/cosa/rest/todo_fifo_queue.py`

No changes needed - accepts any object with required attributes.

### RunningFifoQueue

**File**: `src/cosa/rest/running_fifo_queue.py`

**Changes Required**:
```python
def _process_job(self, job):
    # NEW: Check for agentic job type
    if isinstance(job, AgenticJobBase):
        result = job.do_all()
        self._move_to_done(job)
        return

    # Existing AgentBase/SolutionSnapshot handling...
```

### ConsumerThread

**File**: `src/cosa/rest/queue_consumer.py`

No changes needed - calls `job.do_all()` on any job.

## WebSocket Events

| Event | When | Data |
|-------|------|------|
| `queue_todo_update` | Job queued | `{count: N}` |
| `queue_running_update` | Job started | `{count: 1}` |
| `job_notification` | Progress update | `{job_id, message, timestamp}` |
| `queue_done_update` | Job completed | `{count: N}` |

## Notification Flow (Phase 5+)

```
DeepResearchJob.do_all()
       │
       │ notify_progress("Synthesizing findings...")
       ▼
cosa-voice MCP (with job_id parameter)
       │
       ▼
Lupin FastAPI Notification Service
       │
       │ Routes by job_id presence:
       │   job_id present → job card in Queue View
       │   job_id absent  → standard Notification Card
       ▼
WebSocket → UI
```

## File Locations

### New Files

| File | Purpose |
|------|---------|
| `src/cosa/agents/agentic_job_base.py` | Abstract base class |
| `src/cosa/agents/deep_research/job.py` | DeepResearchJob |

### Modified Files

| File | Changes |
|------|---------|
| `src/cosa/rest/routers/deep_research.py` | New submit endpoint |
| `src/cosa/rest/running_fifo_queue.py` | Agentic job handling |

### Reference Files (Read-Only)

| File | Purpose |
|------|---------|
| `src/cosa/agents/deep_research/cli.py` | Existing research logic |
| `src/cosa/rest/todo_fifo_queue.py` | Queue push interface |
| `src/cosa/rest/queue_consumer.py` | Job execution |
