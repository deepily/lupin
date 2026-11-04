> Part 3 of 17 of the [Lupin Notification API Reference](../notification-api.md): quick-start examples.

## 2. Quick-Start Examples

Six copy-paste recipes covering the most common notification patterns.

---

### Recipe 1: Fire-and-Forget Notification

Send a notification that does not require a response.

**curl**:

```bash
curl -X POST "http://localhost:7999/api/notify" \
  -H "X-API-Key: YOUR_API_KEY" \
  -d "message=Build+completed+successfully" \
  -d "type=task" \
  -d "priority=medium" \
  -d "target_user=user@example.com"
```

**Python (CLI)**:

```python
from lupin_cli.notifications.notification_models import (
    AsyncNotificationRequest,
    NotificationType,
    NotificationPriority
)
from lupin_cli.notifications.notify_user_async import notify_user_async

request = AsyncNotificationRequest(
    message           = "Build completed successfully",
    notification_type = NotificationType.TASK,
    priority          = NotificationPriority.MEDIUM,
    target_user       = "user@example.com"
)
response = notify_user_async( request )
print( f"Status: {response.status}, Connections: {response.connection_count}" )
```

**MCP (cosa-voice)**:

```python
notify( "Build completed successfully", notification_type="task", priority="medium" )
```

---

### Recipe 2: Yes/No Question with Response

Ask the user a binary question and wait for their answer.

**curl** (opens SSE stream):

```bash
curl -N -X POST "http://localhost:7999/api/notify" \
  -H "X-API-Key: YOUR_API_KEY" \
  -d "message=Deploy+to+production?" \
  -d "response_requested=true" \
  -d "response_type=yes_no" \
  -d "response_default=no" \
  -d "timeout_seconds=120" \
  -d "target_user=user@example.com"
```

The `-N` flag disables curl's output buffering, which is necessary for SSE streams.
The response will appear as an SSE event:

```
data: {"status": "responded", "response": "yes", "default_used": false}
```

Or on timeout:

```
data: {"status": "expired", "response": "no", "default_used": true}
```

**Python (CLI)**:

```python
from lupin_cli.notifications.notification_models import NotificationRequest, ResponseType
from lupin_cli.notifications.notify_user_sync import notify_user_sync

request = NotificationRequest(
    message          = "Deploy to production?",
    response_type    = ResponseType.YES_NO,
    response_default = "no",
    timeout_seconds  = 120,
    target_user      = "user@example.com"
)
response = notify_user_sync( request )

if response.exit_code == 0:
    print( f"User said: {response.response_value}" )
elif response.exit_code == 2:
    print( f"Timeout - default used: {response.response_value}" )
else:
    print( f"Error: {response.error_message}" )
```

**MCP (cosa-voice)**:

```python
response = ask_yes_no( "Deploy to production?", default="no", priority="high" )
# Returns: "yes", "no", "yes [comment: ...]", or "no [comment: ...]"

if response.startswith( "yes" ):
    print( "User approved deployment" )
```

---

### Recipe 3: Multiple-Choice Question

Present the user with a set of options and wait for their selection.

**curl**:

```bash
curl -N -X POST "http://localhost:7999/api/notify" \
  -H "X-API-Key: YOUR_API_KEY" \
  -d "message=How+should+we+handle+the+migration?" \
  -d "response_requested=true" \
  -d "response_type=multiple_choice" \
  -d "response_default=Cancel" \
  -d "timeout_seconds=300" \
  -d "target_user=user@example.com" \
  --data-urlencode 'response_options={"questions":[{"question":"How should we handle the migration?","header":"Migration","multiSelect":false,"options":[{"label":"Incremental","description":"Migrate tables one at a time"},{"label":"Big bang","description":"Migrate everything at once"},{"label":"Cancel","description":"Skip migration for now"}]}]}'
```

**Python (CLI)**:

```python
from lupin_cli.notifications.notification_models import NotificationRequest, ResponseType

request = NotificationRequest(
    message          = "How should we handle the migration?",
    response_type    = ResponseType.MULTIPLE_CHOICE,
    response_default = "Cancel",
    timeout_seconds  = 300,
    target_user      = "user@example.com",
    response_options = {
        "questions" : [ {
            "question"    : "How should we handle the migration?",
            "header"      : "Migration",
            "multi_select": False,
            "options"     : [
                { "label": "Incremental", "description": "Migrate tables one at a time" },
                { "label": "Big bang",    "description": "Migrate everything at once" },
                { "label": "Cancel",      "description": "Skip migration for now" }
            ]
        } ]
    }
)
response = notify_user_sync( request )
print( f"User chose: {response.response_value}" )
```

**MCP (cosa-voice)**:

```python
response = ask_multiple_choice(
    questions=[ {
        "question"    : "How should we handle the migration?",
        "header"      : "Migration",
        "multiSelect" : False,
        "options"     : [
            { "label": "Incremental", "description": "Migrate tables one at a time" },
            { "label": "Big bang",    "description": "Migrate everything at once" },
            { "label": "Cancel",      "description": "Skip migration for now" }
        ]
    } ],
    title    = "Migration Decision",
    priority = "high"
)
# Returns: { "answers": { "Migration": "Incremental" } }
```

---

### Recipe 4: Batch Open-Ended Questions

Ask multiple free-form questions on a single screen.

**MCP (cosa-voice)**:

```python
response = ask_open_ended_batch(
    questions=[
        { "question": "What is the main goal of this session?", "header": "Goal" },
        { "question": "Any constraints or blockers?",           "header": "Constraints" },
        { "question": "Target branch for changes?",             "header": "Branch", "default_value": "main" }
    ],
    title    = "Session Planning",
    priority = "high"
)
# Returns: {
#     "answers": {
#         "Goal"        : "Implement OAuth2 login flow",
#         "Constraints" : "Must use existing user table",
#         "Branch"      : "main"
#     }
# }
```

The `default_value` key pre-fills the text input so the user can accept defaults
by pressing **Submit All** without typing.

> **Note**: Batch open-ended questions are currently only available via the MCP
> interface. For the REST API, use sequential `POST /api/notify` calls with
> `response_type=open_ended`.

---

### Recipe 5: Query Notification History for a Sender

Retrieve the full conversation between a sender and a user.

```bash
curl "http://localhost:7999/api/notifications/conversation/claude.code@lupin.deepily.ai/user@example.com" \
  -H "X-API-Key: YOUR_API_KEY"
```

With optional time window (last 48 hours):

```bash
curl "http://localhost:7999/api/notifications/conversation/claude.code@lupin.deepily.ai/user@example.com?hours=48" \
  -H "X-API-Key: YOUR_API_KEY"
```

The response is a JSON array of notification objects sorted chronologically
(oldest first), suitable for chat-style display.

---

### Recipe 6: Clear All Notifications for a User

Delete all notifications within a time window.

**Delete all notifications from the last 7 days**:

```bash
curl -X DELETE "http://localhost:7999/api/notifications/bulk/user@example.com?hours=168" \
  -H "X-API-Key: YOUR_API_KEY"
```

**Delete all notifications (no time filter)**:

```bash
curl -X DELETE "http://localhost:7999/api/notifications/bulk/user@example.com" \
  -H "X-API-Key: YOUR_API_KEY"
```

Response:

```json
{
    "status"        : "success",
    "user_email"    : "user@example.com",
    "hours_filter"  : 168,
    "deleted_count" : 47
}
```

---
