> Part 11 of 16 of the [Lupin Notification API Reference](../notification-api.md): sending through CLI clients and direct HTTP (sections 8.3 and 8.4).

### 8.3 Tier 3 -- CLI Clients

#### notify_user_sync.py (SSE Blocking)

**Module**: `src/cosa/cli/notify_user_sync.py`

Sends a response-required notification and blocks on an SSE stream until the user
responds, the timeout expires, or the user is detected as offline.

**Python API**:

```python
from lupin_cli.notifications.notify_user_sync import notify_user_sync
from lupin_cli.notifications.notification_models import (
    NotificationRequest, NotificationResponse,
    NotificationType, NotificationPriority, ResponseType
)

request = NotificationRequest(
    message           = "Approve deployment?",
    response_type     = ResponseType.YES_NO,
    notification_type = NotificationType.CUSTOM,
    priority          = NotificationPriority.HIGH,
    timeout_seconds   = 120,
    response_default  = "no",
    sender_id         = "my.agent@lupin.deepily.ai"
)

response: NotificationResponse = notify_user_sync(
    request            = request,
    debug              = False,
    retry_on_timeout   = False,
    max_attempts       = 1,
    backoff_multiplier = 2.0,
    bearer_token       = None
)

if response.exit_code == 0:
    print( f"User said: {response.response_value}" )
```

**Function signature**:

```python
def notify_user_sync(
    request            : NotificationRequest,
    server_url         : Optional[ str ]   = None,
    debug              : bool              = False,
    retry_on_timeout   : bool              = False,
    max_attempts       : int               = 1,
    backoff_multiplier : float             = 2.0,
    bearer_token       : Optional[ str ]   = None
) -> NotificationResponse
```

**Exit codes**:

| Code | Meaning |
|------|---------|
| `0` | Success -- response received, or user offline with default applied |
| `1` | Error -- validation failure, network error, user not found |
| `2` | Timeout -- no response within `timeout_seconds` |

**CLI usage**:

```bash
python3 -m lupin_cli.notifications.notify_user_sync "Approve deployment?" \
    --response-type yes_no \
    --response-default no \
    --timeout 120
```

**Retry with backoff**: When `retry_on_timeout=True`, the client retries on
timeout using exponential backoff with the `backoff_multiplier`. Each attempt
doubles the wait (capped by `max_attempts`).

#### notify_user_async.py (Fire-and-Forget)

**Module**: `src/cosa/cli/notify_user_async.py`

Sends a fire-and-forget notification and returns immediately after delivery
confirmation. Uses adaptive retry to handle the WebSocket authentication window.

**Python API**:

```python
from lupin_cli.notifications.notify_user_async import notify_user_async
from lupin_cli.notifications.notification_models import (
    AsyncNotificationRequest, AsyncNotificationResponse,
    NotificationType, NotificationPriority
)

request = AsyncNotificationRequest(
    message           = "Build completed",
    notification_type = NotificationType.TASK,
    priority          = NotificationPriority.MEDIUM,
    sender_id         = "my.agent@lupin.deepily.ai"
)

response: AsyncNotificationResponse = notify_user_async(
    request = request,
    debug   = False
)

if response.success:
    print( f"Delivered: {response.status}" )
```

**Function signature**:

```python
def notify_user_async(
    request    : AsyncNotificationRequest,
    server_url : Optional[ str ] = None,
    debug      : bool            = False
) -> AsyncNotificationResponse
```

**Exit codes**:

| Code | Meaning |
|------|---------|
| `0` | Success -- notification queued or delivered |
| `1` | Error -- validation failure, network error, user not found |

**Adaptive retry**: The `calculate_retry_intervals()` function produces different
retry patterns based on the timeout budget:

| Timeout | Pattern | Rationale |
|---------|---------|-----------|
| <= 10s | `[1, 1, 2, 2, 3]` (aggressive) | Catch 5-10s WebSocket auth window |
| > 10s | `[1, 2, 4, 5, 5, 5...]` (exponential with 5s cap) | Reduce server load |

**CLI usage**:

```bash
python3 -m lupin_cli.notifications.notify_user_async "Build completed" \
    --type task \
    --priority high
```

#### Bash Wrapper Scripts (Global CLI Commands)

The Python CLI tools above are wrapped by bash scripts installed at `~/.local/bin/`
for convenient command-line access from any directory. The canonical copies live in
`src/scripts/` for version control and easy reinstallation.

**Installation** (from project root):

```bash
cp src/scripts/notify-claude-async ~/.local/bin/
cp src/scripts/notify-claude-sync  ~/.local/bin/
chmod +x ~/.local/bin/notify-claude-async ~/.local/bin/notify-claude-sync
```

**How they work**:

1. Resolve `LUPIN_ROOT` (from env var, `DEEPILY_PROJECTS_DIR` fallback, or hardcoded path)
2. Validate the directory exists
3. Use the CoSA venv Python (`$LUPIN_ROOT/src/cosa/.venv/bin/python3`) which has `requests` + `pydantic`
4. Set `PYTHONPATH` to include `$LUPIN_ROOT/src`
5. `exec` the Python CLI module with all args passed through (`"$@"`)

**Fire-and-forget** (async):

```bash
notify-claude-async "Build completed" --type task --priority medium
notify-claude-async "Deploying..." --type progress --priority low --debug
```

**Response-required** (sync, SSE blocking):

```bash
notify-claude-sync "Approve deployment?" --response-type yes_no --response-default no
notify-claude-sync "Enter API key" --response-type open_ended --timeout 60
```

**Deprecated wrapper**: `~/.local/bin/notify-claude` prints a deprecation warning
and chains to `notify-claude-async` via `exec`. A per-project `src/scripts/notify.sh`
does the same.

| Command | Script | Delegates To |
|---------|--------|-------------|
| `notify-claude-async` | `~/.local/bin/notify-claude-async` | `lupin_cli.notifications.notify_user_async` |
| `notify-claude-sync` | `~/.local/bin/notify-claude-sync` | `lupin_cli.notifications.notify_user_sync` |
| `notify-claude` | `~/.local/bin/notify-claude` *(deprecated)* | chains → `notify-claude-async` |
| `src/scripts/notify.sh` | per-project *(deprecated)* | chains → `notify-claude-async` |

**Canonical copies**: `src/scripts/notify-claude-async`, `src/scripts/notify-claude-sync`

---

### 8.4 Tier 4 -- Direct HTTP

Use `curl` or any HTTP client to call the notification API directly.

**Fire-and-forget** (no response required):

```bash
curl -X POST "http://localhost:7999/api/notify" \
    -H "X-API-Key: YOUR_API_KEY" \
    -G \
    --data-urlencode "message=Build completed successfully" \
    --data-urlencode "type=task" \
    --data-urlencode "priority=medium" \
    --data-urlencode "target_user=user@example.com"
```

Response:

```json
{
    "status"  : "delivered",
    "message" : "Notification sent to user@example.com"
}
```

**Response-required** (SSE blocking):

```bash
curl -X POST "http://localhost:7999/api/notify" \
    -H "X-API-Key: YOUR_API_KEY" \
    -N \
    -G \
    --data-urlencode "message=Approve deployment?" \
    --data-urlencode "type=custom" \
    --data-urlencode "priority=high" \
    --data-urlencode "target_user=user@example.com" \
    --data-urlencode "response_requested=true" \
    --data-urlencode "response_type=yes_no" \
    --data-urlencode "response_default=no" \
    --data-urlencode "timeout_seconds=120"
```

The server returns a `text/event-stream` response. The stream emits exactly one
SSE event and then closes:

```
data: {"status": "responded", "response": "yes", "default_used": false}
```

Or on timeout:

```
data: {"status": "expired", "response": "no", "default_used": true, "timeout": true}
```

---
