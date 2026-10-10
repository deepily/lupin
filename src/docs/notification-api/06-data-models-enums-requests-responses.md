> Part 6 of 16 of the [Lupin Notification API Reference](../notification-api.md): enums, request models, the persist query parameter and response models (sections 5.1 to 5.3).

## 5. Data Models & Enums

All Pydantic models and enums live in `src/cosa/cli/notification_models.py`. The PostgreSQL
ORM model lives in `src/cosa/rest/postgres_models.py`. The in-memory queue item lives in
`src/cosa/rest/notification_fifo_queue.py`.

### 5.1 Enums

Three `str, Enum` classes provide type-safe choices throughout the notification system.

#### NotificationType

```python
class NotificationType( str, Enum ):
    TASK     = "task"
    PROGRESS = "progress"
    ALERT    = "alert"
    CUSTOM   = "custom"
```

| Value | Description |
|------------|--------------------------------------------------|
| `task`     | Discrete work item completion or status change |
| `progress` | Ongoing process update (build, test, analysis) |
| `alert`    | Warning or error requiring attention |
| `custom`   | Freeform notification type |

#### NotificationPriority

```python
class NotificationPriority( str, Enum ):
    LOW    = "low"
    MEDIUM = "medium"
    HIGH   = "high"
    URGENT = "urgent"
```

| Value | Audio Behavior | Queue Insertion |
|----------|-----------------------------|-----------------|
| `low`    | Silent (no sound) | Back of queue |
| `medium` | Gentle ping | Back of queue |
| `high`   | Prominent ping + TTS | Front of queue |
| `urgent` | Alert tone + TTS | Front of queue |

#### ResponseType

```python
class ResponseType( str, Enum ):
    YES_NO           = "yes_no"
    OPEN_ENDED       = "open_ended"
    MULTIPLE_CHOICE  = "multiple_choice"
    OPEN_ENDED_BATCH = "open_ended_batch"
```

| Value | UI Rendering | Response Format |
|--------------------|-----------------------------------|-------------------------------------|
| `yes_no`           | Yes/No/Neither buttons + optional comment | `"yes"`, `"no"`, `"neither"`, or with `[comment: ...]` |
| `open_ended`       | Text input + mic button | Free-form string |
| `multiple_choice`  | Radio/checkbox options | Selected label(s) |
| `open_ended_batch` | Multiple text inputs on one screen | Dict keyed by header |

---

### 5.2 Request Models

#### NotificationRequest (Sync / Response-Required)

Used for blocking notifications that wait for user response via SSE stream.

```python
class NotificationRequest( BaseModel ):
```

**Fields**:

| Field | Type | Default | Constraints / Validators |
|---------------------|-------------------------------|--------------------------------------|---------------------------------------|
| `message`           | `str`                         | *required* | min_length=1, max_length=5000, `message_not_whitespace` validator |
| `response_type`     | `ResponseType`                | *required* | Enum validation |
| `notification_type` | `NotificationType`            | `NotificationType.CUSTOM`            | Enum validation |
| `priority`          | `NotificationPriority`        | `NotificationPriority.MEDIUM`        | Enum validation |
| `target_user`       | `Optional[str]`               | `None`                               | Resolved from config/env at dispatch time |
| `timeout_seconds`   | `int`                         | `120`                                | ge=1, le=600 |
| `response_default`  | `Optional[str]`               | `None`                               | `validate_yes_no_default` validator |
| `title`             | `Optional[str]`               | `None`                               | min_length=1, max_length=100 |
| `sender_id`         | `Optional[str]`               | `None`                               | Regex pattern (see Section 5.5) |
| `response_options`  | `Optional[dict]`              | `None`                               | `validate_multiple_choice_options` validator |
| `abstract`          | `Optional[str]`               | `None`                               | max_length=5000 |
| `session_name`      | `Optional[str]`               | `None`                               | max_length=50 |
| `job_id`            | `Optional[str]`               | `None`                               | Regex pattern (see Section 5.5) |
| `suppress_ding`     | `bool`                        | `False`                              | Boolean flag |

**Validators**:

| Validator | Target Field | Rule |
|------------------------------------|--------------------|---------------------------------------------------------------|
| `message_not_whitespace`           | `message`          | Strips whitespace; raises `ValueError` if empty after strip |
| `validate_yes_no_default`          | `response_default` | For `yes_no` type, must be `"yes"` or `"no"` (or `None`) |
| `validate_multiple_choice_options` | `response_options` | For `multiple_choice`: must have `questions` array, each with `question`, `options` (2-20 items), each option with `label`. For `open_ended_batch`: must have `questions` array, each with `question`. |

**Method**: `to_api_params() -> dict`

Converts the model to API query parameters for `POST /api/notify`. Converts enums to
string values, resolves `sender_id` (explicit > extracted from message prefix > None),
JSON-serializes `response_options`, and excludes `None` optional fields.

#### AsyncNotificationRequest (Fire-and-Forget)

Used for non-blocking notifications that do not wait for a response.

```python
class AsyncNotificationRequest( BaseModel ):
```

**Fields**:

| Field | Type | Default | Constraints |
|---------------------|-------------------------------|--------------------------------------|---------------------------------------|
| `message`           | `str`                         | *required* | min_length=1, max_length=5000, `message_not_whitespace` validator |
| `notification_type` | `NotificationType`            | `NotificationType.CUSTOM`            | Enum validation |
| `priority`          | `NotificationPriority`        | `NotificationPriority.MEDIUM`        | Enum validation |
| `target_user`       | `Optional[str]`               | `None`                               | Resolved from config/env at dispatch time |
| `timeout`           | `int`                         | `5`                                  | ge=1, le=30 (HTTP request timeout) |
| `sender_id`         | `Optional[str]`               | `None`                               | Regex pattern (see Section 5.5) |
| `abstract`          | `Optional[str]`               | `None`                               | max_length=5000 |
| `session_name`      | `Optional[str]`               | `None`                               | max_length=50 |
| `job_id`            | `Optional[str]`               | `None`                               | Regex pattern (see Section 5.5) |
| `suppress_ding`     | `bool`                        | `False`                              | Boolean flag |
| `queue_name`        | `Optional[str]`               | `None`                               | Pattern: `^(run|todo|done|dead)$`     |
| `progress_group_id` | `Optional[str]`               | `None`                               | Pattern: `^pg-[a-f0-9]{8}$`          |

**Method**: `to_api_params() -> dict`

Same conversion logic as `NotificationRequest.to_api_params()`, minus
`response_requested`, `response_type`, and `timeout_seconds` fields. Includes
`queue_name` for provisional job card registration, and `progress_group_id` for in-place DOM updates.

---

### 5.2a Server-Side Query Param: `persist` (fire-and-forget only)

`persist` is a **server-side query parameter on `POST /api/notify`** — it is not a
field on the client convenience models above. Because its only production user
(the fleet arbiter) builds the notify URL directly rather than through those models.

| Param | Type | Default | Applies to | Semantics |
|-----------|--------|---------|-------------------|-----------------------------------------------------------------------|
| `persist` | `bool` | `True`  | fire-and-forget | `True` → persist a forensic Layer-2 (PostgreSQL) row (prior behavior, byte-identical for all existing callers). `False` → skip only the DB insert. Layer-1 (FIFO + WebSocket) delivery + the `queued` / `user_not_available` outcome are unchanged. |

- **Not a config/INI knob** — `persist` is request-scoped (per-call query param). There
  is no `lupin-app.ini` key for it; each caller decides per request. Response-required
  mode ignores it and always persists.
- **Who sends `persist=false` and why** — the fleet arbiter's re-announce-on-return
  loop (`_check_pending_outreach`, `arbiter_job.py`). When Rick is offline, a pending
  Rick-bound advisory is re-pushed every `reannounce_interval_seconds` (300s) until a
  delivered outcome or the 24h TTL. Each retry is a *delivery* re-attempt of an
  advisory whose forensic row was already written by the first escalation
  (`persist=true`). Without `persist=false`, every 300s retry minted a fresh forensic
  row — the flood (3000+ duplicate rows on Rick's return). With
  `persist=false`, retries collapse to **exactly one forensic row per advisory**.
- **Wiring** — `arbiter_live_notify.build_notify_request` / `make_notify_transport`
  thread the flag. `app._build_arbiter_outreach_hops` builds two transports: the
  first-send `live_notify_fn` (persist=True → the one forensic row) and the
  re-announce `live_retry_fn` (persist=False → no new rows).

---

### 5.3 Response Models

#### NotificationResponse (Sync)

Returned by `notify_user_sync` after the SSE stream completes.

```python
class NotificationResponse( BaseModel ):
```

| Field | Type | Default | Description |
|------------------|-----------------|---------|-------------------------------------------------|
| `response_value` | `Optional[str]` | `None`  | User's response value or `None` on error |
| `exit_code`      | `int`           | *required* | `0` = success, `1` = error, `2` = timeout |
| `status`         | `Optional[str]` | `None`  | Event status: `responded`, `expired`, `offline`, `error` |
| `default_used`   | `bool`          | `False` | Whether the default value was used |
| `is_timeout`     | `bool`          | `False` | Whether the notification timed out |

**Properties**:

| Property | Returns | Logic |
|-------------|---------|----------------------|
| `success`   | `bool`  | `exit_code == 0`     |
| `is_error`  | `bool`  | `exit_code == 1`     |

#### AsyncNotificationResponse (Fire-and-Forget)

Returned by `notify_user_async` after the HTTP POST completes.

```python
class AsyncNotificationResponse( BaseModel ):
```

| Field | Type | Default | Description |
|--------------------|-----------------|---------|--------------------------------------------------|
| `success`          | `bool`          | *required* | Whether notification was sent successfully |
| `status`           | `str`           | *required* | `queued`, `user_not_available`, `error`, `connection_error`, `timeout` |
| `message`          | `Optional[str]` | `None`  | Status message or error description |
| `target_user`      | `str`           | *required* | Target user email address |
| `target_system_id` | `Optional[str]` | `None`  | System UUID if user found |
| `connection_count` | `int`           | `0`     | Number of active WebSocket connections (ge=0) |

**Properties**:

| Property | Returns | Logic |
|-------------|---------|--------------------------------------------------------|
| `is_queued` | `bool`  | `status == "queued"`                                   |
| `is_error`  | `bool`  | `status in ("error", "connection_error", "timeout")`   |

---
