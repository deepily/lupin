# SSE Notification System - Architecture

**Last Updated**: 2025.10.15

## Related Documentation

- **[Index](00-index.md)**: Master navigation
- **[Current Implementation](01-implementation-current.md)**: Active phases
- **[Decisions](03-decisions.md)**: Decision log
- **[Testing](04-testing-validation.md)**: Test strategy

---

## System Context

### Business Requirements

**Problem**: Current notification system is fire-and-forget (async). Claude Code needs to send notifications and wait for responses to support long-running operations.

**Solution**: Add Server-Sent Events (SSE) capability for synchronous notifications with timeout handling.

### Technical Requirements

1. **Synchronous Communication**: Wait for response from notification endpoint
2. **Timeout Handling**: Maximum 2-minute wait with graceful timeout
3. **Heartbeat Keepalive**: 5-second heartbeats to maintain connection
4. **Event Streaming**: Multiple event types (ack, heartbeat, result)
5. **Backward Compatibility**: Existing async notifications must continue working

---

## Architecture Overview

### Three-Layer Pattern

```
┌─────────────────────────────────────────────────┐
│  Layer 1: Bash Wrapper                          │
│  send-notification-from-claude-sync              │
│  - Orchestrates execution                        │
│  - Captures result from stdout                   │
│  - Propagates exit codes                         │
└───────────────┬─────────────────────────────────┘
                ↓
┌─────────────────────────────────────────────────┐
│  Layer 2: Python SSE Client                      │
│  client.py                                       │
│  - Maintains HTTP connection                     │
│  - Parses SSE events                             │
│  - Handles timeouts                              │
│  - Stream multiplexing (stderr/stdout)           │
└───────────────┬─────────────────────────────────┘
                ↓ (HTTP POST with streaming)
┌─────────────────────────────────────────────────┐
│  Layer 3: FastAPI SSE Server                     │
│  server.py (Phase 1) / production router (Phase 2)│
│  - Accepts POST requests                         │
│  - Async event generator                         │
│  - Emits heartbeats every 5s                     │
│  - Returns final result                          │
└─────────────────────────────────────────────────┘
```

### Communication Flow

**Phase 1 (PoC - Port 8000)**:
```
send-notification-from-claude-sync
  → python client.py "message" 5 120
    → HTTP POST localhost:8000/process {"message": "...", "heartbeat_interval": 5}
      → StreamingResponse with event_generator()
        → data: {"type": "ack", "message": "Request received"}
        → data: {"type": "heartbeat", "elapsed": 5.01}
        → data: {"type": "heartbeat", "elapsed": 10.02}
        → data: {"type": "result", "data": "Processed result"}
      ← Client receives result
    ← Exit code 0, stdout: "Processed result"
  ← Bash captures result and exit code
```

**Phase 2 (Production - Port 7999)**:
```
Same flow, but:
- FastAPI endpoint at localhost:7999/api/notifications/sse
- Integrated with existing notification system
- Both async and sync endpoints coexist
```

---

## Component Design

### 1. FastAPI SSE Server

**Technology**: FastAPI, Python asyncio

**Key Components**:
- `async def event_generator()`: Yields SSE events incrementally
- `StreamingResponse`: FastAPI response type for SSE
- Headers: `Content-Type: text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no`

**Event Schema**:
```python
# Acknowledgment
{"type": "ack", "message": "Request received", "timestamp": "ISO8601"}

# Heartbeat
{"type": "heartbeat", "elapsed": 5.01}

# Result
{"type": "result", "data": "Final result string", "timestamp": "ISO8601"}
```

**Processing**:
- Simulates async work with random duration (2-120 seconds for PoC)
- Emits heartbeat every 5 seconds
- Returns final result after processing completes

### 2. Python SSE Client

**Technology**: requests library

**Key Responsibilities**:
- HTTP POST with streaming enabled
- Parse SSE format: `data: <json>\n\n`
- Route events by type (ack → stderr, heartbeat → stderr, result → stdout)
- Enforce timeout (2 minutes default)
- Clean error handling and exit codes

**Timeout Strategy**:
- requests timeout tuple: `(connect_timeout, read_timeout)`
- Explicit elapsed time checking in event loop
- Ensures robustness against network and application-level hanging

### 3. Bash Wrapper Script

**Technology**: Bash shell script

**Key Responsibilities**:
- Locate and validate Python client exists
- Execute client with proper arguments
- Capture result from stdout (clean separation from diagnostics)
- Propagate exit codes to caller
- Provide consistent interface matching `notify-claude` pattern

---

## Integration Patterns

### Stream Multiplexing

**Problem**: Need both diagnostics and final result

**Solution**: Separate streams
- **stderr**: Diagnostics (ack messages, heartbeats, errors)
- **stdout**: Final result only
- **Benefit**: Bash can cleanly capture result: `result=$(command)`

### Async vs Sync Coexistence (Phase 2)

**Current (async)**:
```
notify-claude "message" --type=task --priority=high
  → Fire-and-forget, no response expected
  → Returns immediately
```

**New (sync)**:
```
send-notification-from-claude-sync "message" --type=task --priority=high
  → Waits for response up to 2 minutes
  → Returns result or timeout error
```

**Implementation**:
- Different endpoints: `/api/notifications/async` vs `/api/notifications/sse`
- Different wrapper scripts: `send-notification-from-claude-async` vs `send-notification-from-claude-sync`
- Both coexist in production

---

## Technology Stack

| Component | Technology | Rationale |
|-----------|------------|-----------|
| Server | FastAPI | Async support, streaming responses, existing Lupin stack |
| Client | requests library | Simple, reliable, streaming support |
| Event Format | JSON | Structured, extensible, easy to parse |
| Transport | Server-Sent Events | Unidirectional push, simpler than WebSockets for this use case |
| Wrapper | Bash | Consistent with existing `notify-claude` pattern |

---

## Deployment Architecture

### Phase 1 (PoC)

```
src/rnd/2025.10.15-sse-notifications/src/
├── server.py                    # Standalone FastAPI (port 8000)
├── client.py                    # Python SSE client
└── send-notification-from-claude-sync  # Bash wrapper

Manual execution: python server.py (terminal 1)
                  ./send-notification-from-claude-sync "test" (terminal 2)
```

### Phase 2 (Production)

```
Production FastAPI (port 7999):
└── src/cosa/rest/routers/notifications_sse.py  # SSE endpoint

Global scripts:
├── /home/rruiz/.local/bin/send-notification-from-claude-async  # Renamed from notify-claude
└── /home/rruiz/.local/bin/send-notification-from-claude-sync   # New sync script

Integration: FastAPI router registered in main.py
             Scripts accessible globally via PATH
```

---

## Performance Considerations

### Memory Efficiency

- Async generators yield events incrementally
- No memory accumulation for long-running streams
- Client discards heartbeats after logging

### Concurrency

**Phase 1**: Single-threaded (PoC validation only)

**Phase 2**:
- Configure uvicorn workers for production
- Connection pooling if multiple sequential requests needed

### Scalability

**Not a concern for this use case**:
- Low volume (< 10 requests/minute expected)
- Claude Code notifications are infrequent
- No need for load balancing or horizontal scaling

---

*Token count target: 4,000-8,000*
*Update as architecture evolves*
