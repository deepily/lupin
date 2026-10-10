> Part 7 of 16 of the [Lupin Notification API Reference](../notification-api.md): SSE event models, helper functions, the PostgreSQL notification model and the in-memory queue item (sections 5.4 to 5.7).

### 5.4 SSE Event Models

All SSE event models extend `SSEEventBase( BaseModel )` which provides a `status: str` field.
These are emitted as `data:` lines in the Server-Sent Events stream from `POST /api/notify`.

#### RespondedEvent

```python
class RespondedEvent( SSEEventBase ):
    status       : Literal["responded"] = "responded"
    response     : str
    default_used : bool = False
```

Emitted when the user responds to a notification. `default_used` is always `False`.

#### ExpiredEvent

```python
class ExpiredEvent( SSEEventBase ):
    status       : Literal["expired"] = "expired"
    response     : Optional[str]
    default_used : bool
    timeout      : bool = True
```

Emitted when `timeout_seconds` elapses. If `response_default` was provided,
`response` contains that value and `default_used` is `True`. Otherwise `response`
is `None` and `default_used` is `False`.

#### OfflineEvent

```python
class OfflineEvent( SSEEventBase ):
    status       : Literal["offline"] = "offline"
    response     : str
    default_used : bool = True
```

Emitted immediately when the user has no active WebSocket connections and a
`response_default` was provided. `default_used` is always `True`.

#### ErrorEvent

```python
class ErrorEvent( SSEEventBase ):
    status   : Literal["error"] = "error"
    message  : str
    response : Optional[str] = None
```

Emitted on unexpected server errors during SSE stream processing.

**Union type**:

```python
SSEEvent = Union[ RespondedEvent, ExpiredEvent, OfflineEvent, ErrorEvent ]
```

---

### 5.5 Helper Functions & Patterns

#### `extract_sender_from_message( message, agent_type="claude.code" )`

Extracts a sender ID from a `[PREFIX]` at the start of the message text.

```python
extract_sender_from_message( "[LUPIN] Build complete" )
# -> "claude.code@lupin.deepily.ai"

extract_sender_from_message( "[COSA] Tests passed" )
# -> "claude.code@cosa.deepily.ai"

extract_sender_from_message( "[LUPIN] Research done", "deep.research" )
# -> "deep.research@lupin.deepily.ai"

extract_sender_from_message( "No prefix message" )
# -> None
```

Uses regex: `r'^\[([A-Z]+)\]'`

#### `parse_sender_id( sender_id )`

Parses a sender ID string into its component parts. Backward compatible with both
old format (no session) and new format (with session ID).

```python
parse_sender_id( "claude.code@lupin.deepily.ai" )
# -> {
#     "agent_type"     : "claude.code",
#     "project"        : "lupin",
#     "session_id"     : None,
#     "full_sender_id" : "claude.code@lupin.deepily.ai",
#     "base_sender_id" : "claude.code@lupin.deepily.ai"
# }

parse_sender_id( "claude.code@lupin.deepily.ai#a1b2c3d4" )
# -> {
#     "agent_type"     : "claude.code",
#     "project"        : "lupin",
#     "session_id"     : "a1b2c3d4",
#     "full_sender_id" : "claude.code@lupin.deepily.ai#a1b2c3d4",
#     "base_sender_id" : "claude.code@lupin.deepily.ai"
# }
```

#### Sender ID Pattern (Pydantic `pattern` validator)

```
^[a-z]+(\.[a-z]+)+@[a-z]+\.deepily\.ai(#([a-f0-9]{8}|[a-z]+(-[a-z]+)*|[a-z]+-[a-f0-9]{8}))?$
```

Breakdown:

| Segment | Matches |
|------------------------------------|------------------------------------------------|
| `[a-z]+(\.[a-z]+)+`               | Agent type: 2+ dot-separated lowercase words (e.g., `claude.code`, `claude.code.job`) |
| `@[a-z]+\.deepily\.ai`            | Domain: `@{project}.deepily.ai`                |
| `#[a-f0-9]{8}`                    | Hex session suffix (8 hex characters) |
| `#[a-z]+(-[a-z]+)*`               | Hyphenated topic suffix (e.g., `#cats-vs-dogs`) |
| `#[a-z]+-[a-f0-9]{8}`             | Job ID suffix (e.g., `#dr-a0ebba60`) |

#### Job ID Pattern (Pydantic `pattern` validator)

```
^([a-z]+-[a-f0-9]{8}|[a-f0-9]{64}(::[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})?)$
```

| Format | Example |
|------------------|--------------------------------------------------------------------------------------|
| Short | `dr-a1b2c3d4` (lowercase prefix + hyphen + 8 hex chars) |
| SHA256 | `61d021320bed364e82d50af9128ddf8e1a63d8680d76ec06b1b03e27d8dee435` (64 hex chars) |
| Compound | `{sha256}::{uuid}` (64 hex chars + `::` + UUID with hyphens) |

---

### 5.6 PostgreSQL Notification Model

Source: `src/cosa/rest/postgres_models.py` (class `Notification`), table name: `notifications`.

```python
class Notification( Base ):
    __tablename__ = "notifications"
```

**Columns**:

| Column | SQLAlchemy Type | Nullable | Default / Server Default | Description |
|---------------------|-------------------------------|----------|-------------------------------|--------------------------------------|
| `id`                | `UUID( as_uuid=True )`        | No (PK) | `uuid.uuid4` / `gen_random_uuid()` | Primary key |
| `sender_id`         | `String( 255 )`               | No | -- | Sender identifier (indexed) |
| `recipient_id`      | `UUID( as_uuid=True )`        | No | -- | FK -> `users.id` cascade (indexed) |
| `job_id`            | `String( 256 )`               | Yes | -- | Agentic job ID for routing (indexed) |
| `title`             | `String( 255 )`               | Yes | -- | Notification title |
| `message`           | `Text`                        | No | -- | Notification message body |
| `abstract`          | `Text`                        | Yes | -- | Supplementary context (markdown, URLs) |
| `type`              | `String( 50 )`                | No | -- | Notification type (indexed) |
| `priority`          | `String( 50 )`                | No | -- | Priority level |
| `created_at`        | `DateTime( timezone=True )`   | No | `func.now()` / `NOW()`       | Creation timestamp |
| `delivered_at`      | `DateTime( timezone=True )`   | Yes | -- | WebSocket delivery timestamp |
| `responded_at`      | `DateTime( timezone=True )`   | Yes | -- | User response timestamp |
| `expires_at`        | `DateTime( timezone=True )`   | Yes | -- | Expiration deadline |
| `response_requested`| `Boolean`                     | No | `False` / `'false'`          | Whether response is required |
| `response_type`     | `String( 50 )`                | Yes | -- | Response type (yes_no, open_ended, etc.) |
| `response_value`    | `JSONB`                       | Yes | -- | User's response data |
| `response_default`  | `String( 255 )`               | Yes | -- | Default response for timeout/offline |
| `response_options`  | `JSONB`                       | Yes | -- | Multiple-choice option definitions |
| `timeout_seconds`   | `BigInteger`                  | Yes | -- | Response timeout in seconds |
| `state`             | `String( 50 )`                | No | `"created"` / `'created'`   | State machine value (indexed) |
| `is_hidden`         | `Boolean`                     | No | `False` / `'false'`         | Soft-delete flag (indexed) |
| `payload`           | `JSONB`                       | Yes | -- | Structured side-channel — the same dict the in-memory push sends as `payload=`. Its first consumer is the broadcast ack, whose whole identity (which broadcast, which seat) lives here and nowhere else. NULL on every row written before `9184990becdf`. |

**Indexes**:

| Index Name | Column(s) | Type |
|-----------------------------------------|---------------------------------|------------|
| `idx_notifications_sender_id`           | `sender_id`                     | B-tree |
| `idx_notifications_recipient_id`        | `recipient_id`                  | B-tree |
| `idx_notifications_state`               | `state`                         | B-tree |
| `idx_notifications_created_at`          | `created_at`                    | B-tree |
| `idx_notifications_sender_recipient`    | `sender_id`, `recipient_id`     | Composite |
| `ix_notifications_type`                 | `type`                          | B-tree |
| `ix_notifications_is_hidden`            | `is_hidden`                     | B-tree |
| `ix_notifications_job_id`              | `job_id`                        | B-tree |
| `idx_notifications_ack_broadcast`       | `recipient_id`, `(payload->>'broadcast_id')` | Partial, `WHERE type = 'commons_broadcast_ack'` |

**Relationship**: `recipient: Mapped["User"]` via `back_populates="notifications"`.

**Migrations**:
- `275fb8d9c75c` - Original table creation (2025-12-30)
- `62ec6f256d27` - Added `job_id` column (2026-01-23)
- `9184990becdf` - Added `payload` column + the partial broadcast-ack index

---

### 5.7 NotificationItem (In-Memory Queue)

Source: `src/cosa/rest/notification_fifo_queue.py` (class `NotificationItem`).

This is a plain Python class (not a dataclass) that represents a notification in the
in-memory FIFO queue. It bridges the gap between API request parameters and WebSocket
delivery to the frontend.

```python
class NotificationItem:
```

**Constructor Parameters & Instance Attributes**:

| Attribute | Type | Default | Description |
|----------------------|-----------------|--------------------------------------|------------------------------------------------|
| `id`                 | `str`           | `str( uuid.uuid4() )`               | Database ID (or auto-generated for backward compat) |
| `id_hash`            | `str`           | same as `id`                         | Backward compatibility alias |
| `message`            | `str`           | *required* | Notification message text |
| `title`              | `Optional[str]` | `None`                               | Notification title |
| `type`               | `str`           | `"task"`                             | Notification type |
| `priority`           | `str`           | `"medium"`                           | Priority level |
| `source`             | `str`           | `"claude_code"`                      | Source system identifier |
| `user_id`            | `Optional[str]` | `None`                               | Target user system UUID |
| `timestamp`          | `str`           | Timezone-aware ISO 8601 | Creation timestamp from configured timezone |
| `played`             | `bool`          | `False`                              | Whether notification has been played (TTS) |
| `play_count`         | `int`           | `0`                                  | Number of times played |
| `last_played`        | `Optional[str]` | `None`                               | Timestamp of last playback |
| `response_requested` | `bool`          | `False`                              | Whether user response is required |
| `response_type`      | `Optional[str]` | `None`                               | Response type (yes_no, open_ended, etc.) |
| `response_default`   | `Optional[str]` | `None`                               | Default response value |
| `response_options`   | `Optional[dict]`| `None`                               | Multiple-choice option definitions |
| `timeout_seconds`    | `Optional[int]` | `None`                               | Response timeout in seconds |
| `sender_id`          | `str`           | `"claude.code@unknown.deepily.ai"`   | Sender identifier (fallback if not provided) |
| `abstract`           | `Optional[str]` | `None`                               | Supplementary context (markdown, URLs) |
| `suppress_ding`      | `bool`          | `False`                              | Skip notification sound for conversational TTS |
| `job_id`             | `Optional[str]` | `None`                               | Agentic job ID for routing to job cards |
| `queue_name`         | `Optional[str]` | `None`                               | Queue where job is running (run/todo/done/dead) |
| `progress_group_id`  | `Optional[str]` | `None`                               | Progress group ID for in-place DOM updates |

**Methods**:

| Method | Returns | Description |
|-------------------------|-----------------|---------------------------------------------------------|
| `_get_local_timestamp()`| `str`           | Timezone-aware ISO 8601 timestamp from `ConfigurationManager` |
| `_get_time_display()`   | `str`           | Formatted time with TZ abbreviation (e.g., `"14:30 EST"`) |
| `to_dict()`             | `Dict[str, Any]`| Full dictionary serialization for JSON / WebSocket emit |

---
