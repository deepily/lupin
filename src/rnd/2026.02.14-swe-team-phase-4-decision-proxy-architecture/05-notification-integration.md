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

## Implementation (Phase 7) — DONE

Phase 7 expanded significantly from the original 3-task plan to 10 tasks.

### What Was Actually Built

1. **Batch lifecycle** — In-place progress group rendering with `pr-{hex}-{N}` batch IDs.
   - Relaxed `progress_group_id` regex in `notification_models.py` and widened DB column in `postgres_models.py`
   - Monotonic batch counter in `decision_proxy.py` router with `acknowledge`/`batch-id` endpoints

2. **Proxy summary notification** — `orchestrator.py` → `_emit_proxy_summary_notification()` emits
   a summary notification after each `_gated_confirmation()` cycle with category, action, trust level,
   confidence, and a link to the ratification page.

3. **Batch acknowledge/retire cycle** — Frontend `notifications.js` renders a "View Decisions" link
   that opens the ratify page. Batch retirement visual in notification panel on acknowledge.

4. **Belt-and-suspenders on ratify page** — `proxy-ratify.js` adds focus refresh + WebSocket subscription
   for `notification_queue_update` events, ensuring the ratify page shows latest decisions even if
   the user navigates away and returns.

5. **Per-job trust_mode override** — Trust mode dropdown on SWE Team job card in `notifications.html`.
   End-to-end plumbing: HTML → `swe_team.py` router → `agentic_job_factory.py` → `job.py` → orchestrator config.

6. **Circuit breaker alert** — `orchestrator.py` → `_on_circuit_breaker_trip()` callback emits
   urgent notification when any category's circuit breaker trips.

### Key Design Decisions

- **In-place rendering** via `progress_group_id` rather than separate per-decision notifications.
  This prevents notification panel flood during multi-decision jobs.
- **Batch ID format**: `pr-{8hex}-{N}` where hex is stable per server lifetime and N is monotonic.
  The `acknowledge` endpoint retires the current batch and starts a new one.
- **No new WebSocket event types needed** — reused existing `notification_queue_update` pipeline.

### Files Changed

| File | Repo | What |
|------|------|------|
| `notification_models.py` | CoSA | Relaxed progress_group_id regex |
| `postgres_models.py` | CoSA | Widened DB column |
| `decision_proxy.py` router | CoSA | Batch counter + acknowledge/batch-id endpoints |
| `orchestrator.py` | CoSA | `_emit_proxy_summary_notification`, `_on_circuit_breaker_trip` |
| `agentic_job_factory.py` | CoSA | trust_mode parameter passthrough |
| `job.py` | CoSA | `_trust_mode_override` attribute |
| `swe_team.py` router | CoSA | trust_mode in submit request |
| `notifications.html` | Lupin | Trust mode dropdown on SWE Team card |
| `notifications.js` | Lupin | Proxy ratify link + batch retirement |
| `notifications.css` | Lupin | Proxy notification styles |
| `proxy-ratify.js` | Lupin | Focus refresh + WS subscription |
| `test_swe_team_orchestrator.py` | Lupin | 6 proxy notification tests |
| `test_notification_models.py` | Lupin | 1 batch regex test |
| `test_proxy_notifications.py` | Lupin | 1 E2E smoke test (NEW) |
