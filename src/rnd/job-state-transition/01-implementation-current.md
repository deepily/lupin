# Current Implementation Status

**Last Updated**: 2026-01-28 (Session 107) - End of session

## Active Work: Phase 4 (Client Subscription)

**Phase 3 COMPLETE** - All 7 server emissions implemented and smoke tested.

### Completed Emissions (7/7)

| # | Location | Transition | Status |
|---|----------|------------|--------|
| 1 | running_fifo_queue.py:274 | run → done (agentic success) | ✅ |
| 2 | running_fifo_queue.py:307 | run → dead (agentic failure) | ✅ |
| 3 | running_fifo_queue.py:335 | run → dead (agentic crash) | ✅ |
| 4 | running_fifo_queue.py:436 | run → done (base agent) | ✅ |

| 5 | running_fifo_queue.py:~490 | run → done (solution snapshot) | ✅ |
| 6 | running_fifo_queue.py:~600 | run → done (cache hit) | ✅ |
| 7 | queue_consumer.py:~64 | todo → run | ✅ |

---

## Upcoming Phases

### Phase 4: Client Subscription (Low Risk)

**File**: `src/fastapi_app/static/js/notifications.js`

**Change**: Add `"job_state_transition"` to `subscribed_events` array in `authenticateQueueWebSocket()` (~line 1752)

---

### Phase 5: Client Handler (Medium Risk)

**File**: `src/fastapi_app/static/js/notifications.js`

**Add**:
1. Switch case for `job_state_transition`
2. `handleJobStateTransition()` method
3. `insertJobMetadata()` method

**Key Logic**:
```javascript
handleJobStateTransition( event ) {
    const { job_id, from_queue, to_queue, metadata } = event;

    // Find card in source container
    const card = document.querySelector( `.job-card[data-job-id="${job_id}"]` );

    // Update status class
    card.classList.remove( `status-${from_queue}` );
    card.classList.add( `status-${to_queue}` );

    // DOM reparenting
    const toContainer = document.getElementById( `${to_queue}-jobs-container` );
    toContainer.insertAdjacentElement( 'afterbegin', card );

    // Insert metadata if provided
    if ( metadata ) this.insertJobMetadata( job_id, card, metadata );
}
```

---

### Phase 6: Badge-Only Handlers (Medium Risk)

**File**: `src/fastapi_app/static/js/notifications.js`

**Change**: Modify `queue_*_update` handlers to only call `updateQueueCountBadge()`:

```javascript
case "queue_running_update":
    this.log( `Queue RUNNING update: ${envelope.value}` );
    this.updateQueueCountBadge( "run", envelope.value );  // Badge only
    break;
```

---

### Phase 7: Placeholder DOM Nodes (Medium Risk)

**File**: `src/fastapi_app/static/js/notifications.js`

**Change**: Add placeholder elements to `renderJobCard()`:

```html
<div class="job-response" style="display: none"></div>
<div class="job-abstract" style="display: none"></div>
<div class="job-report-link" style="display: none"></div>
<div class="job-cost-summary" style="display: none"></div>
<div class="job-error" style="display: none"></div>
```

---

### Phases 8-10: Cruft Removal (High Risk)

**Phase 8 - Data Structures**:
- Remove `this.registeredJobs = new Map()`
- Remove `this.completedJobs = new Set()`
- Remove `this.pendingJobNotifications`

**Phase 9 - Methods**:
- Remove `isJobRegistered()`
- Remove `getRegisteredJobInfo()`
- Remove `cacheJobNotification()`
- Remove `createProvisionalJobRegistration()`
- Remove `ensureJobCardExists()`
- Remove `scheduleQueueRefreshForJob()`
- Remove `updateJobRegistration()`

**Phase 10 - Logic**:
- Remove protective logic from `loadQueueJobCards()`
- Remove provisional registration from `handleNotificationUpdate()`
- Remove `data-provisional` from `renderJobCard()`
- Simplify `handleNotificationUpdate()` to direct routing

---

## File Change Summary

| File | Phases | Risk |
|------|--------|------|
| lupin-app.ini | 1 | Low |
| lupin-app-splainer.ini | 1 | Low |
| fifo_queue.py | 2 | Low |
| running_fifo_queue.py | 3 | Medium |
| queue_consumer.py | 3 | Low |
| notifications.js | 4-10 | Medium-High |
