# WebSocket Architecture Reference

This is a reference pointer to the full architecture documentation.

**Full Documentation**: See `src/docs/websocket-architecture.md`

## Quick Navigation

The full architecture document covers:

1. **Dual-Session Design** - Queue vs Audio WebSocket separation
2. **User-Centric Routing** - How events route to correct users
3. **Session Management** - Session creation, persistence, cleanup
4. **Connection Lifecycle** - Connect, auth, subscribe, disconnect
5. **Event Flow Diagrams** - Visual representation of event routing

## Key Concepts

### Why Two WebSockets?

| Aspect | Queue WebSocket | Audio WebSocket |
|--------|-----------------|-----------------|
| Traffic | Low-frequency, small payloads | High-frequency, large audio chunks |
| Priority | Application-critical | Media streaming |
| Buffering | Minimal | Chunked/streaming |

### Session State Machine

```
DISCONNECTED → CONNECTING → AUTHENTICATING → CONNECTED → SUBSCRIBED
                    ↑                              ↓
                    └──────── RECONNECTING ←───────┘
```

For complete details, read the full document at `src/docs/websocket-architecture.md`.
