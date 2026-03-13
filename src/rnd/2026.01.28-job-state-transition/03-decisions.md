# Design Decisions

## Decision 1: Progressive Enhancement via DOM Reparenting

**Context**: Need to move job cards between queue containers when state changes.

**Options Considered**:
1. Re-fetch and re-render entire queue on each update
2. Delete card from source, create new card in target
3. DOM reparenting - move existing card element

**Decision**: DOM reparenting (`container.appendChild(card)`)

**Rationale**:
- Preserves activity log and accumulated state
- More efficient than re-rendering
- Maintains event listeners attached to card
- Simpler code than delete/recreate

**Trade-offs**:
- Must update CSS classes manually (`status-run` → `status-done`)
- Must handle timer start/stop for running queue

---

## Decision 2: Placeholder Nodes for Metadata

**Context**: Completion metadata (response, abstract, report link) arrives after card creation.

**Options Considered**:
1. Re-render card when metadata arrives
2. Create placeholder DOM nodes, insert content later
3. Use data attributes and CSS to show/hide

**Decision**: Placeholder DOM nodes with `display: none` until populated

**Rationale**:
- Clean separation between card structure and content
- No re-rendering needed
- Easy to show/hide with simple style changes
- Consistent pattern across all metadata fields

**Implementation**:
```html
<div class="job-response" style="display: none"></div>
<div class="job-abstract" style="display: none"></div>
<div class="job-report-link" style="display: none"></div>
<div class="job-cost-summary" style="display: none"></div>
<div class="job-error" style="display: none"></div>
```

---

## Decision 3: Badge-Only for queue_*_update

**Context**: Previously, `queue_*_update` triggered full API fetch and re-render.

**Options Considered**:
1. Keep existing behavior (fetch + render)
2. Badge-only updates (just update count number)
3. Remove `queue_*_update` entirely

**Decision**: Badge-only updates via `updateQueueCountBadge()`

**Rationale**:
- `job_state_transition` handles card movement
- Count badges still need updating for UI consistency
- Reduces API calls and eliminates race conditions
- Backward compatible with existing event infrastructure

---

## Decision 4: Remove Provisional Registration System

**Context**: Session 106 added provisional registration to handle race conditions where notifications arrive before job cards exist.

**Options Considered**:
1. Keep provisional system alongside new events
2. Remove provisional system entirely
3. Simplify provisional system

**Decision**: Remove entirely (Phases 8-10)

**Rationale**:
- `job_state_transition` eliminates the race condition at source
- Provisional system adds complexity and potential bugs
- Cleaner codebase without workarounds
- Less memory usage (no Maps/Sets tracking state)

**Cleanup Required**:
- `registeredJobs` Map
- `completedJobs` Set
- `pendingJobNotifications` Map
- 7 related methods
- Protective logic in `loadQueueJobCards()`

---

## Decision 5: Emit Before Queue Operations

**Context**: When should `job_state_transition` be emitted relative to `pop()`/`push()`?

**Options Considered**:
1. Emit after queue operations complete
2. Emit before queue operations
3. Emit in the middle (after pop, before push)

**Decision**: Emit before queue operations

**Rationale**:
- Client receives notification while job is still in source queue
- If emit fails, job still moves (graceful degradation)
- Client can prepare for transition before it happens
- Matches TTS notification pattern (already emits before queue ops)

**Code Pattern**:
```python
# 1. TTS notification
self._notify( answer, job=job )

# 2. State transition event
self._emit_job_state_transition( job_id, 'run', 'done', user_id, metadata )

# 3. Queue operations
self.pop()
self.jobs_done_queue.push( job )
```
