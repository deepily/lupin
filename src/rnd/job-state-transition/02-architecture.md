# Architecture: job_state_transition WebSocket Event

## Event Design

### Mechanism Overview

| Scenario | Mechanism |
|----------|-----------|
| Page load / refresh | API fetch → render all jobs |
| Job moves between queues | `job_state_transition` → move card (DOM reparenting) |
| Queue count changes | `queue_*_update` → update badge number only |
| Metadata updates | Insert into placeholder nodes (progressive enhancement) |

### Event Payload

**Basic transition** (todo → run):
```json
{
  "type": "job_state_transition",
  "job_id": "dr-7d92bfda",
  "from_queue": "todo",
  "to_queue": "run",
  "timestamp": "2026-01-28T10:30:00.123456"
}
```

**Completion transition** (run → done/dead, includes metadata):
```json
{
  "type": "job_state_transition",
  "job_id": "dr-7d92bfda",
  "from_queue": "run",
  "to_queue": "done",
  "timestamp": "2026-01-28T10:30:00.123456",
  "metadata": {
    "response_text": "The answer is 4.",
    "abstract": "Simple arithmetic calculation.",
    "report_link": "/reports/dr-7d92bfda.html",
    "cost_summary": "$0.002",
    "error": null
  }
}
```

**Error transition** (run → dead):
```json
{
  "type": "job_state_transition",
  "job_id": "dr-7d92bfda",
  "from_queue": "run",
  "to_queue": "dead",
  "timestamp": "2026-01-28T10:30:00.123456",
  "metadata": {
    "error": "API rate limit exceeded"
  }
}
```

## Transition Points

### Server Emissions (7 total)

| Location | File | Transition | Metadata |
|----------|------|------------|----------|
| queue_consumer.py:64 | todo → run | None |
| running_fifo_queue.py:274 | run → done | Full (agentic success) |
| running_fifo_queue.py:307 | run → dead | Error (agentic failure) |
| running_fifo_queue.py:335 | run → dead | Error (agentic crash) |
| running_fifo_queue.py:436 | run → done | Full (base agent) |
| running_fifo_queue.py:~480 | run → done | Full (solution snapshot) |
| running_fifo_queue.py:~575 | run → done | Full (cache hit) |

### Client Handling

1. **Subscribe**: Add `"job_state_transition"` to `subscribed_events` array
2. **Handle**: Switch case routes to `handleJobStateTransition()`
3. **DOM Reparenting**: Move card from source to target container
4. **Metadata Insertion**: Populate placeholder nodes on completion

## Progressive Enhancement Pattern

**Card Lifecycle**:
1. **Created once** when job enters todo queue (or on page load)
   - Includes placeholder DOM nodes for: response, abstract, report link, cost summary
   - Placeholders hidden or show "Processing..."
2. **Moved via DOM reparenting** when job transitions queues
   - `container.appendChild(card)` + update status class
   - No re-rendering
3. **Metadata inserted** as it becomes available
   - Activity log entries appended via `notification_queue_update`
   - Final metadata (response, abstract, etc.) inserted via `job_state_transition`

## Backward Compatibility

- Existing `queue_*_update` events preserved (now badge-only)
- Initial page load still fetches via API
- Graceful degradation if emit fails
