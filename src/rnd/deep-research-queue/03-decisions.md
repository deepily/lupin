# Design Decisions - Deep Research Queue Integration

> **Decision Log with Rationale** | Created: 2026-01-18

## D1: New Dedicated Endpoint vs Overloading /api/push

**Decision**: Create new `POST /api/deep-research/submit` endpoint

**Rationale**:
- Deep Research has different parameters (budget, model selection, user_email)
- Cleaner separation of concerns from standard queue push
- Easier to document and maintain
- Can have distinct rate limiting and validation rules

**Alternatives Considered**:
- Overload `/api/push` with `command: "deep_research"` - rejected for parameter mismatch

---

## D2: AgenticJobBase vs Direct DeepResearchJob

**Decision**: Create intermediate `AgenticJobBase` abstract class

**Rationale**:
- Shared behaviors across agentic processes (Deep Research, Podcast, etc.)
- Common interface expected by RunningFifoQueue
- Centralized `is_cacheable = False` for all agentic jobs
- Notification helpers reusable across job types

**Alternatives Considered**:
- Direct DeepResearchJob without base class - rejected for code duplication
- Extend existing AgentBase - rejected due to different execution model

---

## D3: Async Execution Model

**Decision**: Use `asyncio.run()` within synchronous `do_all()` method

**Rationale**:
- Deep Research CLI already uses async internally
- Consumer thread expects synchronous `do_all()` call
- `asyncio.run()` bridges async/sync boundary cleanly
- No changes needed to consumer thread

**Alternatives Considered**:
- Full async consumer thread - rejected for scope/complexity
- Threading within job - rejected for unnecessary complexity

---

## D4: No Caching for Agentic Jobs

**Decision**: Skip snapshot storage for all `AgenticJobBase` subclasses

**Rationale**:
- Each Deep Research query is unique (web content changes)
- Research results depend on current state of the web
- No benefit to caching stale research
- Reduces storage requirements

**Implementation**:
```python
@property
def is_cacheable(self) -> bool:
    """Agentic jobs should not be cached."""
    return False
```

---

## D5: Job ID Format

**Decision**: Use `{prefix}-{uuid8}` format (e.g., `dr-a1b2c3d4`)

**Rationale**:
- Prefix identifies job type at a glance (`dr` = deep research)
- 8-character UUID provides uniqueness
- Short enough for UI display
- Consistent with existing session ID patterns

**Format Examples**:
- `dr-a1b2c3d4` - Deep Research
- `pod-e5f6g7h8` - Podcast (future)
- `aj-i9j0k1l2` - Generic Agentic Job

---

## D6: Notification Routing (Phase 5+)

**Decision**: Add `job_id` parameter to cosa-voice MCP tools for routing

**Rationale**:
- Notifications with `job_id` route to specific job card
- Notifications without `job_id` route to standard notification card
- Backward compatible (job_id defaults to None)
- Single routing mechanism for all notification types

**Implementation Path**:
1. cosa-voice MCP tools accept optional `job_id`
2. Lupin notification service routes based on presence
3. UI subscribes to `job_notification` events for job cards

---

## D7: Interactive Prompts Location (Phase 6+)

**Decision**: Centralized "Response Required" card for all interactive prompts

**Rationale**:
- Single, consistent place for all user prompts
- Simpler implementation (no conditional rendering in job cards)
- User knows where to look for required actions
- Can migrate to inline job card prompts later if needed

**User Flow**:
1. Job emits `ask_yes_no` with job_id
2. Prompt appears in centralized "Response Required" area
3. Source shown as "From: Deep Research (dr-abc123)"
4. User response routed back to job

---

## D8: Progress Notification Flow

**Decision**: ALL agentic job notifications flow through cosa-voice MCP

**Rationale**:
- Unified notification path (voice + visual)
- Existing cosa-voice infrastructure handles routing
- No duplicate WebSocket emit logic needed
- TTS support for progress updates

**Not Changed**:
- Simple agents continue using direct WebSocket emit
- CLI mode uses cosa-voice without job_id

---

## Future Decisions (Deferred)

### F1: Natural Language Trigger
- How should COSA router detect "deep research" intent?
- Should budget/constraints be extractable from natural language?
- Deferred to Phase 8

### F2: Job Priority
- Should some agentic jobs have priority over others?
- How to handle long-running job blocking queue?
- Deferred to future sessions

### F3: Job Cancellation
- How should user cancel in-progress research?
- What cleanup is needed on cancellation?
- Deferred to future sessions
