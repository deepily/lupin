> Part 1 of 5 of the [WebSocket Architecture Overview](../websocket-architecture.md): overview and architecture.

# WebSocket Architecture Overview

**Date**:
**Source of truth**: `src/cosa/rest/websocket_manager.py`, `src/cosa/rest/routers/websocket.py`
**Status**: Active

## Executive Summary

The Lupin WebSocket architecture provides real-time bidirectional communication between the FastAPI server and client applications. The system employs a dual-session design with user-centric routing, event subscription filtering, and robust connection management.

### Key Architectural Principles

- **User-Centric Routing**: Events route by user ID, not ephemeral WebSocket connection ID
- **Event Subscription Filtering**: Clients only receive events they explicitly subscribe to
- **Dual-Session Architecture**: Separate channels for queue management and audio streaming
- **Thread-Safe Emission**: Background threads emit via `asyncio.run_coroutine_threadsafe`
- **Session Persistence**: localStorage-based session management across page reloads
- **Concurrent `job_state_transition` events** (v0.1.7+): with the agentic pool active (`cj flow max concurrent agentic jobs > 1`), several agentic jobs may emit transitions at once.
  The transitions are `RUNNING → COMPLETED/FAILED`, and they come from different pool worker threads.
  Cross-job event order is non-deterministic.
  Clients must key cards by `job_id`, as they already do. Within a single
  `job_id`, sequence is preserved by the pop-before-transition invariant in
  `RunningFifoQueue._on_agentic_complete`.

---

## System Architecture

### High-Level Data Flow

```
┌─────────────────┐    WebSocket     ┌──────────────────┐    Events     ┌─────────────────┐
│   Client Apps   │ ←─────────────→  │  WebSocket       │ ←──────────   │   Background    │
│                 │                  │  Manager         │               │   Processes     │
│ • queue.js      │                  │                  │               │                 │
│ • hybrid-tts.js │                  │ • User routing   │               │ • Job queue     │
│ • queue-fresh   │                  │ • Event filtering│               │ • TTS streaming │
└─────────────────┘                  │ • Session mgmt   │               │ • Notifications │
                                     └──────────────────┘               └─────────────────┘
```

### Dual-Session Design

Every client opens **two** WebSocket connections. Whether they share one `session_id`
**depends on the client** — measured, and the docs previously claimed all three
shared, which is false:

| Client | Queue id | Audio id |
|---|---|---|
| Mobile app (`enhanced_websocket_service.dart:740-741`) | `_sessionId` | the **same** `_sessionId` |
| Web multiplexer (`multiplexer/boot.ts:623-624`) | `sessionId` | the **same** `sessionId` |
| Web app (`static/js/notifications.js:2441-2442`) | `notifications_queue_session_id` | **a different id** — its own `/api/get-session-id` fetch under `notifications_audio_session_id` |

The split in `notifications.js` is deliberate, not drift: TTS requests from that client
carry `audioSessionId` explicitly (`notifications.js:4308`, `4316`, `4368`, `4376`). So its
audio channel is addressed by its own id. Expect to see a user holding two ids — e.g.
`foolish goat` on the queue socket and `slow zebra` on the audio socket. `emit_to_user`
fans out to both, and the audio socket then correctly declines queue events. Those
"not subscribed" lines are the design working, not a subscription bug (cost three seats six hours reading 749 of them as breakage).


| Channel | Endpoint | Purpose | Auth |
|---------|----------|---------|------|
| Queue | `/ws/queue/{session_id}` | Job state, notifications, system events | JWT required (in-band handshake) |
| Audio | `/ws/audio/{session_id}` | TTS streaming, audio events | No mandatory auth; pre-registration supported |

**Session ID formats**:
- Browser sessions: `"adjective noun"` (e.g., `wise penguin`, `happy cat`)
- Programmatic sessions: `"prefix-identifier"` (e.g., `cc-listener-72116632`, `proxy-ratify`)

The `cc-listener-` prefix identifies programmatic listener sessions (e.g., Claude Code agents) vs. browser clients.

---
