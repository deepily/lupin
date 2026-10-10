> Part 1 of 16 of the [Lupin Notification API Reference](../notification-api.md): the table of contents, the executive summary, the three delivery layers with the FCM wake push side channel, and the key concepts.

# Lupin Notification API Reference

**One-stop reference** for the Lupin notification system — from architecture to testing.

**Source of Truth**: This document supersedes all R&D planning docs in `src/rnd/2025.10.15-sse-notifications/`.

**v0.1.7 CJ Flow async note**: when `cj flow max concurrent agentic jobs > 1`, several agentic jobs may emit notifications at once.
They emit from different pool worker threads. `notification_id` + `job_id` routing remains the canonical way
to correlate responses. No ordering guarantee exists across different jobs.
Within a single job, the pop-before-transition invariant in
`RunningFifoQueue._on_agentic_complete` preserves TTS → emit → queue transition.

---

## Table of Contents

1. [Overview & Architecture](#1-overview--architecture)
    - 1.5 [Historical Evolution](02-architecture-request-flows-and-history.md#15-historical-evolution)
2. [Quick-Start Examples](03-quick-start-examples.md#2-quick-start-examples)
3. [Authentication](04-authentication.md#3-authentication)
4. [REST API Endpoints](05-rest-api-endpoints.md#4-rest-api-endpoints)
5. [Pydantic Models & Enums](#5-pydantic-models--enums) *(second half)*
6. [In-Memory Queue (NotificationFifoQueue)](#6-in-memory-queue--notificationfifoqueue-) *(second half)*
7. [PostgreSQL Persistence](#7-postgresql-persistence) *(second half)*
8. [SSE Blocking Flow](#8-sse-blocking-flow) *(second half)*
9. [WebSocket Events](#9-websocket-events) *(second half)*
10. [CLI Clients](#10-cli-clients) *(second half)*
11. [cosa-voice MCP Integration](#11-cosa-voice-mcp-integration) *(second half)*
12. [Notification Proxy (Auto-Responder)](#12-notification-proxy--auto-responder-) *(second half)*
13. [Testing & Debugging](#13-testing--debugging) *(second half)*

---

## 1. Overview & Architecture

### Executive Summary

Lupin's notification system enables bidirectional communication between automated
agents (Claude Code sessions, deep research jobs, podcast generators) and human
users. It supports two fundamental modes:

1. **Fire-and-forget** — The agent sends a message; no response expected. Used for
   progress updates, task completions, and alerts.
2. **Response-required** — The agent sends a question and blocks until the user
   responds or a timeout occurs. Used for confirmations, decisions, and open-ended
   input.

The system is designed for a **voice-first UX**: notifications are spoken aloud via
TTS. And user responses can be captured through voice-to-text or traditional text
input.

---

### Three Delivery Layers

Every notification flows through up to three layers, each serving a distinct purpose:

#### Layer 1: FIFO Queue + WebSocket (real-time)

An in-memory `NotificationFifoQueue` accepts incoming notifications and immediately
pushes them to connected browser clients via WebSocket events
(`notification_queue_update`). Priority handling inserts `urgent` and `high` items at the front of the queue.
`medium` and `low` items are appended to the back.

**Source**: `src/cosa/rest/notification_fifo_queue.py`

#### Layer 2: PostgreSQL (persistent history)

All notifications are persisted via the `Notification` SQLAlchemy ORM model and the
`NotificationRepository` class. This layer enables:

- Conversation grouping by sender
- Date-based accordion display
- Sender analytics (last activity, notification counts)
- Soft-delete / archive via `is_hidden` flag

**Source**: `src/cosa/rest/postgres_models.py` (lines 482-628),
`src/cosa/rest/db/repositories/notification_repository.py`

**`persist=false` — delivery-only re-attempts skip this layer only** . The fire-and-forget branch persists a forensic row by default
(`persist=true`). A caller that is re-attempting delivery of an *already-persisted*
notification passes `persist=false` to skip the DB insert.
Layer 1 (FIFO + WebSocket) delivery stays fully intact. So a repeated retry never mints a
duplicate forensic row. The sole production user is the fleet arbiter's
re-announce-on-return loop (see § `persist` param below).

#### Layer 3: SSE (synchronous blocking)

For response-required notifications, the `POST /api/notify` endpoint returns a
`StreamingResponse` with Server-Sent Events. The SSE stream stays open until one
of three things happens:

1. The user responds (via the browser UI or voice input)
2. The timeout expires (`timeout_seconds` parameter)
3. The user is detected as offline (immediate default return)

**Source**: Router endpoint `POST /api/notify` with `response_requested=true`

#### Side Channel: FCM Wake Push (mobile silent relay)

A user-targeted notification is enqueued at Layer 1, and the user has no live WebSocket session marked `client_type: "mobile"`.
A live web or desktop session does not suppress the wake.
In that case the queue's enqueue chokepoint asks `FcmWakeService` to send a content-free, data-only, high-priority FCM push.
The payload is `{ "type": "ws_wake", "reason": "undelivered" | "reconnect-hint", "ts": <iso8601> }`.
It goes to the user's registered devices (`POST /api/fcm/register-token`). The push carries
no message content — the woken mobile handler fetches the notification over the
authenticated API. Debounced to at most one wake per user per
`fcm wake debounce seconds` (default 60). Boots disabled with a clear log line
until Firebase credentials are provisioned — never blocks the notification path.

**A notification enqueued inside a live debounce window is deferred, never dropped**
(). It used to be dropped: the debounce arm returned `debounced` and
ended there. And because its log line was gated on `debug` and `verbose` it produced
no output either. Measured live: a notify 37 s after a completed wake, with the device socket down, logged nothing at all.
It sat unplayed until something else woke the device. Now the first notify inside a window arms one trailing wake for the moment
the window closes. Every later notify in that window collapses onto it. The trailing
wake re-runs the whole policy at fire time. So a device that reconnected during the
window is not woken — a deferral is a request, not a promise. `/api/notify/next`
serves the oldest unplayed item. So the backlog drains in order.

**The trailing wake has no override — it honours the window like any other caller**.
A timer thread is not a clock. Descheduled it fires late, and by then an ordinary
notify may have taken the expired slot and opened a new window. A forced send would
put two wakes inside it, defeating the one rate limit the service exists for. Woken
Early it would send before the window it was waiting on had closed. Both cases disappear because the trailing wake simply re-enters `maybe_send_wake`.
Late or early, it finds the window open and re-defers for what is left.
Each re-defer's delay strictly decreases. So it converges rather than loops. **At most one
wake per user per window holds even against a late timer**.

`maybe_send_wake()` returns the arm it took:

| status | meaning |
|---|---|
| `disabled` | master switch off, or Firebase credentials never resolved |
| `mobile_ws_live` | the user has a live mobile queue-WS — no wake needed |
| `deferred` | inside a window; **this call** armed the trailing wake (logged UNGATED) |
| `debounced` | inside a window; a trailing wake was **already** pending, so this collapsed onto it |
| `no_tokens` | no registered FCM tokens for the user |
| `submitted` | handed to the send executor |

The `deferred` line and the trailing wake's outcome line are both printed **ungated**. The original silence went unread for a day because the debug flag was off.

**Source**: `src/cosa/rest/fcm_wake_service.py` (policy + sender),
`src/cosa/rest/notification_fifo_queue.py` (`_maybe_send_fcm_wake` hook),
`src/cosa/rest/routers/fcm.py` (token registration),
spec `src/lupin-mobile/src/rnd/2026.06.11-focus-mode-voice-chat/15-section-s6-fcm-backend-interface.md`

---

### Key Concepts

#### Sender Identity

Every notification carries a `sender_id` in the format:

```
{agent_type}@{project}.deepily.ai
```

Or, for session-aware senders:

```
{agent_type}@{project}.deepily.ai#{session_id}
```

**Known agent types**:

| Agent Type | Description |
|------------------------|--------------------------------------------|
| `claude.code`          | Claude Code CLI sessions (via cosa-voice) |
| `deep.research`        | Deep Research agentic jobs |
| `podcast.generator`    | Podcast Generator agentic jobs |
| `claude.code.job`      | Claude Agent SDK bounded/interactive jobs |
| `notification.proxy`   | Auto-responder proxy |
| `arg.expeditor`        | Runtime argument expeditor agent |

**Examples**:

```
claude.code@lupin.deepily.ai
claude.code@lupin.deepily.ai#a1b2c3d4
deep.research@lupin.deepily.ai#dr-5e6f7a8b
podcast.generator@lupin.deepily.ai
```

#### Recipient Routing

Notifications target a user by **email address** (the `target_user` parameter).
The server resolves the email to an internal UUID via `get_user_by_email()`, then
uses that UUID for database storage and WebSocket delivery.

#### Conversation Grouping

The frontend groups notifications by `sender_id`, creating a chat-style interface
where each sender has its own card. Within each card, notifications are organized
into date-based accordion sections for easy navigation.

#### Job Card Routing

The optional `job_id` field routes notifications to specific agentic job cards in
the UI. This allows long-running background jobs (deep research, podcast generation)
to have their own notification streams displayed within the job's progress panel.

**Job ID formats**:

- Short: `dr-a1b2c3d4`, `mock-12345678`
- SHA256: 64 hex characters
- Compound: `{sha256}::{uuid}`

---
