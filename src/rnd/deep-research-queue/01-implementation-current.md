# Implementation Status - Deep Research Queue

> **Active Phase Tracking** | Last Updated: 2026-01-20 (Session 83)

## Current Phase: 7 (Unified Queue View - PENDING)

---

## Session 74b: Progressive Narrowing Test Harness ✅ COMPLETE

**Status**: ✅ Complete (Session 74b)

**Purpose**: Isolated test harness for the "progressive narrowing" phase - theme clustering, theme selection, topic refinement, and final filtering. Enables testing without full CLI or API calls.

**Files Created**:
- `src/cosa/agents/deep_research/narrowing_mocks.py` (~300 lines)
- `src/cosa/agents/deep_research/narrowing_harness.py` (~660 lines)

**Key Features**:
- Mock API client (`MockResearchAPIClient`) for testing without Anthropic API calls
- Sample subquery sets: 5 topics (React vs Vue) and 8 topics (Python vs Rust)
- Canned theme clustering responses (3/4/6/1/empty variants)
- CLI flags: `--mock`, `--cli-mode`, `--sample 5|8`, `--phase`, `--auto-approve`, `--verbose`, `--debug`
- Dual-modality support via existing `voice_io.py` (voice-first, CLI fallback)
- `NarrowingResult` dataclass for phase tracking

**CLI Usage**:
```bash
# Smoke test (no args)
PYTHONPATH="src:$PYTHONPATH" python -m cosa.agents.deep_research.narrowing_harness

# Mock mode with 8-topic sample
PYTHONPATH="src:$PYTHONPATH" python -m cosa.agents.deep_research.narrowing_harness --mock --sample 8 --verbose

# CLI mode (force text-only)
PYTHONPATH="src:$PYTHONPATH" python -m cosa.agents.deep_research.narrowing_harness --cli-mode --mock --verbose
```

**Verification**:
- [x] narrowing_mocks.py smoke test PASSED
- [x] narrowing_harness.py smoke test PASSED
- [x] Entry point correctly detects --verbose as CLI mode (not smoke test)
- [x] Mock mode works with sample subqueries
- [x] Voice-first modality delegates to voice_io.py

---

### Session 69b Completed ✅
1. ✅ Created AgenticJobBase foundation class
2. ✅ Created DeepResearchJob implementation
3. ✅ Added FastAPI endpoint `POST /api/deep-research/submit`
4. ✅ Integrated with RunningFifoQueue

### Session 83 Completed ✅
1. ✅ Created Auth Testing Quick-Reference Guide (`src/tests/AUTH-TESTING-GUIDE.md`)
2. ✅ Created Deep Research submit smoke test (`src/tests/smoke/test_deep_research_submit_smoke.py`)
3. ✅ Tested API endpoint with JWT auth - job `dr-c0ed19ef` queued successfully
4. ✅ Phase 5: cosa-voice MCP Enhancement - added `job_id` parameter to all notification tools
5. ✅ Phase 6: Notification Router (Frontend) - implemented job-based notification routing

### Session 84 Goals (Next)
1. Browser testing of Phase 6 notification routing
2. Submit Deep Research job and verify notifications appear in job card activity log
3. If Phase 6 verified, proceed to Phase 7 (Unified Queue View)

---

## Phase 1: AgenticJobBase Foundation ✅ COMPLETE

**Status**: ✅ Complete (Session 69b)

**File**: `src/cosa/agents/agentic_job_base.py` (~175 lines)

**Purpose**: Abstract base class for long-running Claude Code agentic jobs (Deep Research, Podcast Generation, etc.)

**Key Features**:
- Job ID generation with type prefix (e.g., `aj-a1b2c3d4`)
- Queue system required attributes (`id_hash`, `last_question_asked`, `user_id`, `session_id`)
- Execution state tracking (started_at, completed_at, status, error)
- `is_cacheable` property (False for agentic jobs)
- Abstract `do_all()` and `_execute()` methods
- `artifacts` dict for storing results
- `get_execution_duration_seconds()` helper

**Verification**:
- [x] Class imports without error
- [x] Can instantiate subclass
- [x] `id_hash` generated with correct prefix
- [x] Smoke test PASSED

---

## Phase 2: DeepResearchJob Implementation ✅ COMPLETE

**Status**: ✅ Complete (Session 69b)

**File**: `src/cosa/agents/deep_research/job.py` (~320 lines)

**Purpose**: Concrete implementation for Deep Research background jobs

**Key Features**:
- Inherits from AgenticJobBase
- Wraps existing CLI research logic (`run_research`, `generate_abstract_for_cli`, `save_report_with_frontmatter`)
- `JOB_TYPE = "deep_research"`, `JOB_PREFIX = "dr"`
- Async execution via `asyncio.run(self._execute())`
- Stores report_path, abstract, cost_summary after completion
- Voice notifications via cosa-voice MCP at start/completion
- Session name generation via Gister

**Verification**:
- [x] Job instantiates with query, user_email, budget
- [x] `last_question_asked` returns formatted string
- [x] `do_all()` calls `_execute()` via asyncio.run()
- [x] Smoke test PASSED

---

## Phase 3: FastAPI Endpoint ✅ COMPLETE

**Status**: ✅ Complete (Session 69b)

**File**: `src/cosa/rest/routers/deep_research.py` (+90 lines)

**Endpoint**: `POST /api/deep-research/submit`

**Pydantic Models Added**:
- `DeepResearchSubmitRequest`: query, user_email, budget, websocket_id, lead_model
- `DeepResearchSubmitResponse`: status, job_id, queue_position, message

**Request Body**:
```json
{
    "query": "Research topic",
    "user_email": "user@example.com",
    "budget": 1.00,
    "websocket_id": "wise-penguin",
    "lead_model": "claude-opus-4-20250514"
}
```

**Response**:
```json
{
    "status": "queued",
    "job_id": "dr-abc123",
    "queue_position": 3,
    "message": "Deep research job queued: [Deep Research] Research topic..."
}
```

**Verification**:
- [x] Endpoint accessible at `/api/deep-research/submit`
- [x] Python syntax valid
- [x] Returns 401 without auth token ✅ (Session 83)
- [x] Creates DeepResearchJob and pushes to todo_queue ✅ (Session 83)
- [x] Returns job_id in response ✅ (Session 83 - `dr-c0ed19ef`)

**Testing Note**: See `src/tests/AUTH-TESTING-GUIDE.md` for auth testing patterns and `src/tests/smoke/test_deep_research_submit_smoke.py` for automated testing.

---

## Phase 4: RunningFifoQueue Integration ✅ COMPLETE

**Status**: ✅ Complete (Session 69b)

**File**: `src/cosa/rest/running_fifo_queue.py` (+95 lines)

**Changes Made**:
- Added `from cosa.agents.agentic_job_base import AgenticJobBase` import
- Modified `_process_job()` to check AgenticJobBase BEFORE AgentBase
- Added `_handle_agentic_job()` method (~90 lines):
  - Calls `running_job.do_all()` without snapshot caching
  - Moves to done_queue if status == "completed"
  - Moves to dead_queue if status == "failed"
  - Broadcasts appropriate WebSocket events

**Verification**:
- [x] Python syntax valid
- [ ] DeepResearchJob picked up by consumer thread (NEEDS TESTING)
- [ ] Job moves through todo → running → done (NEEDS TESTING)
- [ ] No snapshot storage attempted (by design)
- [ ] WebSocket events broadcast (NEEDS TESTING)

---

## Phase 5: cosa-voice MCP Enhancement ✅ COMPLETE

**Status**: ✅ Complete (Session 83)

**Files Modified**:
- `src/cosa/cli/notification_models.py` (+20 lines)
- `src/lupin_mcp/cosa_voice_mcp.py` (+15 lines)

**Purpose**: Add `job_id` parameter to notification system for job-based routing

**Changes Made**:
- Added `job_id: Optional[str]` field to `NotificationRequest` and `AsyncNotificationRequest`
- Regex validation: `^[a-z]+-[a-f0-9]{8}$` (e.g., `dr-a1b2c3d4`)
- Added `job_id` parameter to all 4 MCP tools: `notify()`, `ask_yes_no()`, `converse()`, `ask_multiple_choice()`
- Updated `to_api_params()` methods to include job_id in API calls

**Backward Compatibility**: `job_id=None` (default) uses existing routing

**Verification**:
- [x] Module imports without error
- [x] Valid job_id patterns accepted
- [x] Invalid patterns rejected (validation works)
- [x] Backward compatibility maintained (job_id=None works)

---

## Phase 6: Notification Router (Frontend) ✅ COMPLETE

**Status**: ✅ Complete (Session 83) - Awaiting browser testing

**Files Modified**:
- `src/fastapi_app/static/js/notifications.js` (+150 lines)
- `src/fastapi_app/static/css/notifications.css` (+45 lines)

**Purpose**: Route notifications with `job_id` to job card activity logs instead of sender cards

**JavaScript Changes**:
- Added `registeredJobs` Map for tracking active jobs (todo/running queues)
- `updateJobRegistration(queueName, jobsMetadata)` - registers jobs when queue loads
- `isJobRegistered(jobId)` / `getRegisteredJobInfo(jobId)` - check job status
- Modified `handleNotificationUpdate()` to check for `job_id` and route accordingly
- `appendNotificationToJobCard(jobId, notification)` - adds notification to job card
- `createJobActivityLog(jobCard)` - creates activity section if missing
- `createActivityLogEntry(notification)` - formats notification with timestamp
- `cacheJobNotification(jobId, notification)` - caches if job card not rendered yet
- `expandJobCard(jobId)` - auto-expands job card when notification arrives

**CSS Changes**:
- `.job-activity-log` - container styling
- `.activity-log-header` - header styling
- `.activity-log-entry` - entry styling with priority-based border colors
- `.activity-timestamp` / `.activity-message` - individual element styling

**Routing Flow**:
```
Notification arrives
    ├── response_requested=true → Action Required card (unchanged)
    ├── job_id + registered → Job card activity log (NEW)
    └── else → Sender card (unchanged)
```

**Verification**:
- [x] JavaScript syntax valid
- [x] CSS syntax valid
- [ ] Job registration works in browser (NEEDS TESTING)
- [ ] Notifications route to job cards (NEEDS TESTING)
- [ ] Activity log displays correctly (NEEDS TESTING)

---

## Blockers & Issues

**JWT Authentication Required for Testing**:
- Docker container uses real Firebase JWT authentication
- Mock tokens don't work
- Must use proper login flow:
  ```bash
  # Step 1: Login to get token
  TOKEN=$(curl -s -X POST "http://localhost:7999/auth/login" \
    -H "Content-Type: application/json" \
    -d '{"email": "user@example.com", "password": "password"}' \
    | python3 -c "import sys, json; print(json.load(sys.stdin)['tokens']['access_token'])")

  # Step 2: Use token for API call
  curl -X POST http://localhost:7999/api/deep-research/submit \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"query": "test topic", "user_email": "user@example.com", "budget": 0.50}'
  ```

---

## Next Session (84)

1. **Browser Testing - Phase 6 Verification**:
   - Submit Deep Research job via API
   - Verify notifications route to job card activity log
   - Test job registration/unregistration on queue updates

2. **Phase 7: Unified Queue View** (if Phase 6 verified):
   - Enhance expandable job cards
   - Real-time progress updates
   - Completed job details display

---

## Implementation Timeline

| Phase | Description | Status | Session |
|-------|-------------|--------|---------|
| 1 | AgenticJobBase Foundation | ✅ Complete | 69b |
| 2 | DeepResearchJob Implementation | ✅ Complete | 69b |
| 3 | FastAPI Endpoint | ✅ Complete | 69b |
| 4 | RunningFifoQueue Integration | ✅ Complete | 69b |
| 5 | cosa-voice MCP Enhancement | ✅ Complete | 83 |
| 6 | Notification Router (Frontend) | ✅ Complete | 83 |
| 7 | Unified Queue View (Frontend) | ⏳ Pending | 84 |
| 8 | COSA Router Integration | 📋 Planned | TBD |
