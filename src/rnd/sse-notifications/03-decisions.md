# SSE Notification System - Decision Log

**Purpose**: Track significant technical and architectural decisions

**Format**: Each decision includes Context, Options, Choice, Rationale, and Consequences

---

## Decision D001: Use SSE Instead of WebSockets

**Date**: 2025.10.15
**Status**: ACCEPTED
**Category**: Architecture

### Context

Claude Code needs synchronous notifications that wait for responses. Must choose communication protocol for server-to-client streaming.

### Options Considered

**Option 1: Server-Sent Events (SSE)**
- Pros: Simpler protocol, unidirectional (server → client), HTTP/1.1 compatible, built-in reconnection
- Cons: Unidirectional only (no client → server except initial request), less full-featured than WebSockets

**Option 2: WebSockets**
- Pros: Bidirectional communication, full-duplex, more powerful
- Cons: More complex setup, overkill for unidirectional streaming, requires WebSocket library

**Option 3: Long Polling**
- Pros: Universal compatibility, simple concept
- Cons: Inefficient (repeated connections), poor for streaming, high latency

### Choice

We selected **Option 1: Server-Sent Events (SSE)**

### Rationale

1. **Unidirectional is sufficient**: We only need server → client streaming (heartbeats + result)
2. **Simpler implementation**: SSE is just HTTP with `Content-Type: text/event-stream`
3. **FastAPI native support**: `StreamingResponse` handles SSE cleanly
4. **Existing reference**: SSE implementation guide already created for project
5. **Timeout handling**: requests library provides robust timeout support
6. **No bidirectional needed**: Client sends one request, server streams response

**WebSockets would be overkill** for this use case - we're not building a chat application.

### Consequences

- Server uses FastAPI `StreamingResponse` with async generator
- Client uses `requests` library with `stream=True`
- Event format: `data: {json}\n\n`
- Connection kept alive with heartbeats
- Clean separation of concerns (HTTP POST → SSE stream)

### References

- [Architecture](02-architecture.md#three-layer-pattern)
- [SSE Implementation Guide](../2025.10.14-server-sent-events.md)

---

## Decision D002: Two-Phase Implementation Approach

**Date**: 2025.10.15
**Status**: ACCEPTED
**Category**: Implementation

### Context

Production FastAPI server is actively used on port 7999. Need to validate SSE pattern before integrating into production.

### Options Considered

**Option 1: Direct Production Implementation**
- Pros: Faster to market, no throwaway code
- Cons: High risk, difficult to debug, production downtime if issues

**Option 2: Two-Phase (PoC → Production)**
- Pros: De-risks Phase 2, validates pattern, reference implementation
- Cons: Extra work, temporary code on different port

**Option 3: Feature Branch with Production Integration**
- Pros: Production-like environment, easier transition
- Cons: Still risky, harder to isolate issues, conflicts with active development

### Choice

We selected **Option 2: Two-Phase Implementation (PoC → Production)**

### Rationale

1. **Risk mitigation**: Validate SSE pattern without touching production
2. **Faster debugging**: Standalone server easier to test and troubleshoot
3. **Reference implementation**: PoC becomes example for future work
4. **Team confidence**: Working PoC builds confidence before production integration
5. **Clean separation**: Port 8000 (PoC) vs port 7999 (production) avoids conflicts

**3-5 day PoC investment** saves potential days of production debugging.

### Consequences

- Phase 1: Standalone FastAPI on port 8000
- Phase 2: Integrate validated pattern into port 7999
- PoC code preserved in `src/rnd/sse-notifications/src/` for reference
- Documentation archives with PoC code for future reference

### References

- [Current Implementation](01-implementation-current.md#phase-1)
- [Current Implementation](01-implementation-current.md#phase-2)

---

## Decision D003: PoC Code Location in rnd/ Directory

**Date**: 2025.10.15
**Status**: ACCEPTED
**Category**: Implementation

### Context

Need to decide where to place Phase 1 PoC code. Options include temporary locations (src/tmp/) or documentation locations (src/rnd/).

### Options Considered

**Option 1: src/tmp/ (Temporary)**
- Pros: Standard location for throwaway code
- Cons: Gets deleted, lost reference, not preserved with documentation

**Option 2: src/rnd/sse-notifications/src/ (With Documentation)**
- Pros: Preserved with docs, archives together, permanent reference
- Cons: Slightly non-standard location for code

**Option 3: Separate poc/ Directory**
- Pros: Clear separation from production code
- Cons: Disconnected from documentation, requires separate archival

### Choice

We selected **Option 2: src/rnd/sse-notifications/src/ (With Documentation)**

### Rationale

1. **Permanent reference**: PoC serves as working example for future SSE work
2. **Documentation integration**: Code lives alongside architecture and decisions docs
3. **Archival together**: When project completes, docs + PoC archive as unit
4. **Visual storytelling**: Directory structure shows complete project (docs + code)
5. **Team learning**: New developers can see working PoC with full context

**Key insight**: PoC is not throwaway code - it's a **reference implementation**.

### Consequences

- PoC location: `src/rnd/sse-notifications/src/`
- Files: `server.py`, `client.py`, `send-notification-from-claude-sync`
- Archival path: `src/rnd/archive/2025.10.15-sse-notifications/` (entire directory)
- PoC becomes template for future SSE implementations

### References

- [Architecture](02-architecture.md#deployment-architecture)
- [Index](00-index.md) - Shows PoC code link in navigation

---

## Decision D004: Script Naming Convention

**Date**: 2025.10.15
**Status**: ACCEPTED
**Category**: Implementation

### Context

Need to differentiate between async (fire-and-forget) and sync (wait-for-response) notification scripts. Current script is `notify-claude` (async).

### Options Considered

**Option 1: Add Sync, Keep Async Name**
- Rename current: No change (`notify-claude` stays)
- Add new: `notify-claude-sync`
- Cons: Inconsistent naming (one has suffix, one doesn't)

**Option 2: Add Suffixes to Both**
- Rename current: `notify-claude` → `send-notification-from-claude-async`
- Add new: `send-notification-from-claude-sync`
- Cons: Longer names, but consistent

**Option 3: Use Flags**
- Keep: `notify-claude`
- Add flag: `notify-claude --sync`
- Cons: More complex script logic, harder to see behavior from command name

### Choice

We selected **Option 2: Add Suffixes to Both Scripts**

### Rationale

1. **Symmetry**: Both scripts have clear behavior in name
2. **Self-documenting**: Command name tells you exactly what it does
3. **No ambiguity**: `-async` vs `-sync` makes intent crystal clear
4. **Future-proof**: Easier to add variations (e.g., `-streaming`, `-polling`)
5. **Claude Code clarity**: AI can understand behavior from script name

**Longer names acceptable** for clarity and maintainability.

### Consequences

- Current script renamed: `notify-claude` → `send-notification-from-claude-async`
- New script: `send-notification-from-claude-sync`
- Update CLAUDE.md notification system documentation
- Team coordination needed for migration
- Backward compatibility period (symlink `notify-claude` → `...-async` temporarily)

### References

- [Implementation Phase 2](01-implementation-current.md#phase-2)
- [Architecture](02-architecture.md#async-vs-sync-coexistence-phase-2)

---

*Token count target: 2,000-5,000*
*Archive old decisions when approaching 7,000 tokens*
