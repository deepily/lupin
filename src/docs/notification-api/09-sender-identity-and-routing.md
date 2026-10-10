> Part 9 of 17 of the [Lupin Notification API Reference](../notification-api.md): sender identity and routing.

## 7. Sender Identity & Multi-Project Routing

### 7.1 Sender ID Formats

The sender ID is the primary key for multi-project notification grouping. It follows
an email-like format:

**Basic format** (no session awareness):

```
{agent_type}@{project}.deepily.ai
```

Example: `claude.code@lupin.deepily.ai`

**Session-aware format** (parallel session support):

```
{agent_type}@{project}.deepily.ai#{session_id}
```

Example: `claude.code@lupin.deepily.ai#<hash8>`

**Job-aware format** (agentic job routing):

```
{agent_type}@{project}.deepily.ai#{job_id}
```

Example: `deep.research@lupin.deepily.ai#dr-a0ebba60`

### 7.2 Known Agent Types

| Agent Type | Description | Typical Usage |
|-----------------------|------------------------------------------------|--------------------------------------|
| `claude.code`         | Claude Code CLI sessions | Interactive development sessions |
| `claude.code.job`     | Claude Code bounded/interactive jobs | Fire-and-forget agentic tasks |
| `deep.research`       | Deep Research agent | Long-running research jobs |
| `podcast.generator`   | Podcast Generator agent | Audio content generation jobs |
| `notification.proxy`  | Notification proxy / relay | Internal routing and forwarding |
| `arg.expeditor`       | Runtime Argument Expeditor agent | Parameter resolution and routing |

### 7.3 Sender ID Validation

The sender ID is validated by a Pydantic `pattern` regex on both `NotificationRequest`
and `AsyncNotificationRequest`:

```
^[a-z]+(\.[a-z]+)+@[a-z]+\.deepily\.ai(#([a-f0-9]{8}|[a-z]+(-[a-z]+)*|[a-z]+-[a-f0-9]{8}))?$
```

**Validation rules**:

| Component | Rules |
|--------------|-----------------------------------------------------------------|
| Agent type | Lowercase alpha only, 2+ dot-separated segments (e.g., `claude.code`, `deep.research`) |
| `@` separator | Required literal character |
| Project | Lowercase alpha only, single word |
| Domain | Must be `.deepily.ai`                                           |
| `#` suffix | Optional; one of: 8-char hex, hyphenated lowercase words, or prefix-hex job ID |

**Examples of valid sender IDs**:

```
claude.code@lupin.deepily.ai                    # Basic (no session)
claude.code@lupin.deepily.ai#a1b2c3d4           # Hex session suffix
deep.research@lupin.deepily.ai#dr-a0ebba60      # Job ID suffix
podcast.gen@cosa.deepily.ai#cats-vs-dogs        # Topic suffix
claude.code.job@lupin.deepily.ai                # 3-word agent type
claude.code.job@lupin.deepily.ai#cc-a1b2c3d4    # 3-word agent + job ID
```

**Examples of invalid sender IDs**:

```
Claude.Code@lupin.deepily.ai        # Uppercase (rejected)
claude_code@lupin.deepily.ai        # Underscore in agent type (rejected)
claude@lupin.deepily.ai             # Single-segment agent type (rejected)
claude.code@lupin.google.com        # Wrong domain (rejected)
claude.code@lupin.deepily.ai#       # Empty suffix (rejected)
```

### 7.4 Project Auto-Detection

When a sender ID is not explicitly provided, the system can auto-detect the project
from message prefixes using `extract_sender_from_message()`:

```python
# Message with [PREFIX] -> auto-detected sender_id
extract_sender_from_message( "[LUPIN] Build complete" )
# -> "claude.code@lupin.deepily.ai"

extract_sender_from_message( "[COSA] Tests passed" )
# -> "claude.code@cosa.deepily.ai"
```

The cosa-voice MCP server also performs project auto-detection from the working
directory path:

| Directory Pattern | Detected Project |
|-----------------------------------|------------------|
| `*/planning-is-prompting/*`       | `plan`           |
| `*/genie-in-the-box/*` or `*/lupin/*` | `lupin`     |
| Other | Directory name |

This auto-detection ensures that notifications are correctly grouped even when the
caller does not explicitly set a sender ID.

### 7.5 Frontend Conversation Grouping

The notification UI groups notifications into conversations using the sender ID:

**Sender List** (`GET /api/notifications/senders/{email}`):
- Returns all unique `sender_id` values for a given user
- Each sender entry includes the most recent notification timestamp
- Ordered by last activity (most recent first)

**Conversation View** (`GET /api/notifications/conversation/{sender_id}/{user_email}`):
- Returns all notifications from a specific sender to a specific user
- Excludes soft-deleted (`is_hidden=True`) notifications
- Ordered by `created_at` ascending (chronological)

**Date Grouping** (`GET /api/notifications/conversation-by-date/{sender_id}/{user_email}`):
- Same as conversation view but grouped by date
- Returns a dict keyed by date strings (e.g., `"2026-02-13"`)
- Each date contains an array of notifications from that day

**Activity-Anchored Window Loading** (`GET /api/notifications/sender-dates/{sender_id}/{user_email}`):
- Returns the list of dates that have notifications for a sender/user pair
- Used by the frontend to implement efficient pagination
- Loads only the dates the user scrolls to

**Reaped-Sender Roster Eviction** (`GET /api/notifications/senders-visible/{email}` — the focus-bar roster;):
- The visible-senders roster **durably excludes** any `sender_id` that has a persisted
  `type="session_reaped"` marker row for the recipient. When a session is reaped —
  by a normal `dismiss_sessions` **or** by the heartbeat-arbiter orphan-bridge sweep —
  a `session_reaped` notification is persisted. And from then on that sender is absent
  from the roster, **including across a page refresh** (`get_visible_senders` →
  `NotificationRepository.get_sender_last_activities_visible`).
- This is **roster-only** and **history-preserving**: the Conversation View,
  Date Grouping. And Sender-Dates endpoints above are **unaffected** — a reaped
  sender's notifications remain fully readable in history/audit. The eviction is a roster-query exclusion, **not** an `is_hidden` soft-delete.
`is_hidden=True` would also hide the rows from every history view.
That is the user's clear-conversation action, and it is not used here (a choice, not an oversight).
- Roster is a *liveness* view (a reaped session is gone). History is the *durable
  record* (the reaped session's messages stay). Re-spawn-safe: a new session has a new
  `sender_id` (8-hex session suffix), so it is never masked by a prior session's marker.

### 7.6 Session Routing

Session IDs enable multiple Claude Code sessions working on the same project to maintain
separate notification streams:

**How it works**:

1. Each Claude Code session gets a unique session ID (8 hex characters)
2. The session ID is appended to the sender ID: `claude.code@lupin.deepily.ai#<hash8>`
3. Notifications from different sessions appear as separate conversations in the UI
4. The user can identify which session sent each notification

**Project Sessions endpoint** (`GET /api/notifications/project-sessions/{project}/{user_email}`):
- Returns all sessions for a given project, grouped by base sender ID
- Each session includes:
  - `sender_id` (full, with session suffix)
  - `session_id` (extracted suffix)
  - `notification_count`
  - `last_activity` timestamp
- Used by the frontend to show a per-session breakdown within a project

**Agentic Job Routing**:
- Long-running agentic jobs (Deep Research, Podcast Generator) use `job_id` for routing
- The `job_id` field (e.g., `dr-a1b2c3d4`) links notifications to specific job cards in the UI
- Job notifications can be viewed alongside the job's progress and output
- The `queue_name` field enables provisional job card registration when notifications
  arrive before the job metadata is fetched from the queue API

---
