# Decision Proxy — Notification Integration Design

## Principle: Reuse Existing Pipeline

The proxy does NOT need custom WebSocket code. The existing notification API
handles the full delivery path:

```
POST /api/notify (target_user email)
  → NotificationFifoQueue.push_notification()
  → WebSocketManager.emit_to_user( user_id, "notification_queue_update", data )
  → Browser JS handleNotificationUpdate()
```

**Key insight**: The orchestrator already has user context (email/session), and the
notification pipeline delivers to any entity addressable by email.

## Notification Types

### proxy_decision

Emitted after each proxy classification in `_gated_confirmation()`.

**Payload**:

| Field | Type | Description |
|-------|------|-------------|
| `category` | string | deployment, testing, deps, architecture, destructive, general |
| `action` | string | shadow, suggest, act |
| `trust_level` | int | 1-5 |
| `confidence` | float | 0.0-1.0 |
| `question_snippet` | string | First 80 chars of question |
| `agreement` | bool/null | null if user hasn't answered yet |

### proxy_circuit_breaker

Emitted when CircuitBreaker trips or recovers.

**Payload**:

| Field | Type | Description |
|-------|------|-------------|
| `category` | string | Which category CB triggered for |
| `state` | string | tripped, recovered, cooldown |
| `reason` | string | Human-readable explanation |
| `error_rate` | float | Current error rate |

## Implementation (Phase 7)

**File**: `src/cosa/agents/swe_team/orchestrator.py`

After trust feedback recording in `_gated_confirmation()`, call notification API:

```python
# After proxy evaluation
notification_payload = {
    "notification_type" : "proxy_decision",
    "category"          : category,
    "action"            : action,
    "trust_level"       : trust_level,
    "confidence"        : confidence,
    "question_snippet"  : question[ :80 ],
}
# Use team_io notification methods or direct HTTP call to /api/notify
```

## No Changes Needed

| Component | Why No Changes |
|-----------|----------------|
| `notifications.js` | Existing handler renders all notification types |
| `websocket_manager.py` | Already routes to user by email |
| WS event types | No new event types needed |
| Subscriptions | No custom handlers or subscription changes |
