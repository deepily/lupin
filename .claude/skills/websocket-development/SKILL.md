---
name: websocket-development
description: WebSocket development patterns for Lupin. Use when working on WebSocket connections, real-time events, WS authentication, session management, audio streaming, debugging WebSocket issues, or fixing connection problems.
metadata:
  author: lupin-team
  version: "1.0"
  last-updated: "2026-01-28"
---

# WebSocket Development

Quick reference for WebSocket development in the Lupin project.

## Architecture Overview

Lupin uses a **dual-session WebSocket design**:

| Endpoint | Purpose | Events |
|----------|---------|--------|
| `/ws/queue/{session_id}` | Main application | Queue, notifications, system events |
| `/ws/audio/{session_id}` | Audio streaming | TTS streaming, audio events |

**Key Principle**: User-centric routing - events routed by user identity, not just session.

## Authentication

**All connections require auth_request with Bearer token:**

```javascript
// Token format
Bearer mock_token_email_{email}

// Example auth message
{
  "type": "auth_request",
  "token": "Bearer mock_token_email_user@example.com"
}
```

## Session ID Format

Session IDs use "adjective noun" format for human-readability:
- `wise penguin`
- `clever dolphin`
- `swift falcon`

Stored in localStorage for persistence across page reloads.

## Quick Debugging Checklist

| Issue | Check |
|-------|-------|
| Connection fails | Server running on port 7999? |
| No events received | Auth succeeded? Events subscribed? |
| Session conflicts | Clear localStorage, refresh page |
| Audio not streaming | Both queue AND audio WS connected? |

## Development Tips

1. **Enable debug mode**: Set `app_debug = true` in lupin-app.ini (5s vs 60s updates)
2. **Monitor traffic**: Browser DevTools → Network → WS tab
3. **Check auth**: Console shows success/failure messages
4. **Configuration**: All settings under `websocket_*` keys in lupin-app.ini

## Event Subscription

Clients subscribe to specific event types to filter unwanted events:

```javascript
// Subscribe to events
{
  "type": "subscribe",
  "events": ["queue_update", "notification", "time_update"]
}
```

## Detailed References

For comprehensive documentation:
- [Architecture](references/websocket-architecture.md) - Full dual-session design
- [Configuration](references/websocket-configuration.md) - All config options
- [Events](references/websocket-events.md) - Complete event catalog
- [Troubleshooting](references/websocket-troubleshooting.md) - Debug procedures

## Anti-Patterns

- **Don't** hardcode session IDs - use localStorage persistence
- **Don't** skip auth_request - connections will be rejected
- **Don't** forget both WebSockets for audio features
- **Don't** ignore subscription filtering - causes event spam
