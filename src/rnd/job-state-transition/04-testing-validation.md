# Testing & Validation Plan

## Test Checkpoints

### After Phase 3 (Server Complete)

**Unit Tests**:
```bash
pytest src/tests/unit/
```

**Integration Tests**:
```bash
pytest src/tests/integration/
```

**Expected**: All existing tests pass, no server-side regressions.

### After Phase 10 (Client Complete)

**WebSocket Smoke Tests**:
```bash
src/scripts/run-websocket-smoke-tests.sh
```

**Manual Verification**:
1. Start server: `src/scripts/run-fastapi-lupin.sh`
2. Open browser, navigate to Lupin UI
3. Open dev tools console
4. Submit job (e.g., "What is 2+2?")
5. Observe console for `[JOB-TRANSITION]` logs
6. Verify card moves from run → done
7. Refresh page, verify jobs load via API

---

## Manual Test Scenarios

### Scenario 1: Fresh Job Completion

**Steps**:
1. Submit math question: "What is 15 + 7?"
2. Watch job card in todo queue
3. Observe transition to run queue
4. Observe transition to done queue with answer

**Expected**:
- Console: `[JOB-TRANSITION] dr-xxx: todo -> run`
- Console: `[JOB-TRANSITION] dr-xxx: run -> done`
- Card moves smoothly between containers
- Answer appears in card metadata section

### Scenario 2: Job Failure (Dead Queue)

**Steps**:
1. Submit job designed to fail (or use MockAgenticJob with `failure_probability: 1`)
2. Watch transitions

**Expected**:
- Console: `[JOB-TRANSITION] dr-xxx: run -> dead`
- Card moves to dead queue
- Error message displayed in card

### Scenario 3: Cache Hit

**Steps**:
1. Submit same question twice
2. Second submission should hit cache

**Expected**:
- Both jobs show in done queue
- Second job completes faster (cache hit)
- TTS plays for both

### Scenario 4: Page Refresh

**Steps**:
1. Submit job, let it complete
2. Refresh page
3. Check all queues

**Expected**:
- Jobs load correctly via API
- No duplicate cards
- Correct queue placement

### Scenario 5: Multiple Concurrent Jobs

**Steps**:
1. Submit 3 jobs in quick succession
2. Watch all transitions

**Expected**:
- Each job gets unique transition events
- No card confusion or misrouting
- All complete correctly

---

## Verification Checklist

### Server-Side
- [ ] `job_state_transition` in config events list
- [ ] `_emit_job_state_transition()` method exists in FifoQueue
- [ ] 7 emission points implemented
- [ ] User targeting works (emit_to_user_sync)
- [ ] Metadata included for completion transitions

### Client-Side
- [ ] Event subscribed in `authenticateQueueWebSocket()`
- [ ] Handler in switch statement
- [ ] `handleJobStateTransition()` method works
- [ ] `insertJobMetadata()` method works
- [ ] Placeholder nodes in `renderJobCard()`
- [ ] `queue_*_update` handlers are badge-only
- [ ] Duration timer starts/stops correctly

### Cruft Removal
- [ ] `registeredJobs` Map removed
- [ ] `completedJobs` Set removed
- [ ] `pendingJobNotifications` Map removed
- [ ] 7 obsolete methods removed
- [ ] Protective logic removed from `loadQueueJobCards()`
- [ ] Provisional registration removed from `handleNotificationUpdate()`
- [ ] `data-provisional` attribute removed

---

## Test Results Log

| Date | Phase | Tests Run | Result | Notes |
|------|-------|-----------|--------|-------|
| 2026-01-28 | 1-2 | Config + Method | ✅ Pass | Initial implementation |
| | | | | |
