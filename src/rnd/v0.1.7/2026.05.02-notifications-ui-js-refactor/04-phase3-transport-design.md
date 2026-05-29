# Phase 3 Design — Multiplexer Transport Layer

**Date**: 2026-05-04
**Status**: IMPLEMENTED + POST-IMPLEMENTATION AMENDED — see banner below
**Phase**: 3 of 9 (per `01-execution-plan.md` §"Phase plan")
**Predecessors**: `00-synthesis-and-roadmap.md`, `01-execution-plan.md`, `01-phase0-decisions.md`, `02-phase1-scaffolding-design.md`, `03-phase2-foundation-design.md`
**Bundle siblings**: `02-phase1-scaffolding-design.md` (toolchain) + `03-phase2-foundation-design.md` (services — provides AuthManager + ApiClient + EventBus contracts that this phase consumes)
**Companion**: `90-execution-log.md` Phase 3 section (opens after spine-bundle approval)

---

## ⚠️ Post-implementation amendment — D1 ratification 2026-05-04 PM

**Scope change**: `ClaudeCodeTransport` is REMOVED from Phase 3 + all subsequent multiplexer phases.

**User directive (2026-05-04 PM)**: "I prefer to proceed as though this endpoint never existed. When the corresponding functionality turns up as missing from the UI using the new multiplexer code we'll finish building out, functionality with proper URL and proper authentication."

**Why**: Pre-implementation grep (per Open Q4) surfaced that the legacy `/api/claude-code/ws/{task_id}` endpoint is structurally defective (advertised URL doesn't match served route; no WS authentication; module-level in-memory state; parallel pre-cj-flow path that bypasses `claude_code_queue.py`). The endpoint has been queued for elimination — see `bug-fix-queue.md` "🔥 Top of Queue — IMMEDIATE" entry filed by session ec746144.

**What was removed** (one revert-style action over commit `703ab5a` Phase 3 ship):
- `src/fastapi_app/static/js/multiplexer/transport/ClaudeCodeTransport.ts` (DELETED)
- `src/tests/unit/multiplexer/claude_code_transport.test.ts` (DELETED)
- `claudeCode` field removed from `TransportSet` in `transport/index.ts`; `createTransports()` returns `{queue, audio}` only
- `ClaudeCodeTransport` mention removed from `TransportReadyPayload` JSDoc in `shared/types.ts`
- CC mentions removed from comments in `boot.ts`, `QueueTransport.ts`, `AudioTransport.ts`, `ConnectionStateMachine.ts`, and `test_multiplexer_phase3_smoke.py`

**Test count delta**: 128 unit tests → 122 unit tests (the 6 stub-locking CC tests go away). All other Phase 1-3 verification (tsc, ESLint, build, Phase 1+3 smoke, WS smoke) remains green.

**What was kept as historical record**: the rest of this design doc retains its original 3-transport scope as a record of how we got here. The `ClaudeCodeTransport` rows in the file map, acceptance criteria, etc. below are SUPERSEDED by this amendment. Read this banner first; sections below describe the AS-DESIGNED scope, not the AS-SHIPPED scope.

**Phase 4 implication**: the planned Phase 4 stores phase no longer needs to wire a CC transport body. A future Claude Code transport will be authored only when UI surfaces a missing-functionality gap, against the cleaned-up endpoint produced by tomorrow's bug-fix-queue work.

---

## Approval coupling — spine bundle (Phases 1-3)

This design doc is a member of the **spine bundle** per Q10 amendment 2026-05-04. It does NOT land alone — it ships alongside `02-phase1-scaffolding-design.md` (toolchain) and `03-phase2-foundation-design.md` (foundation services) as a single plan-review pass + single user approval gate.

Phase 3 is the **payoff** of the spine: by the end of this phase, the multiplexer page connects to `:7999` via three transports (queue, audio, claude-code), authenticates, receives real events, and reconnects on disconnect. This is the first concrete proof-of-spine.

Within the bundle, **implementation cadence stays per-phase**: Phase 1 implementation completes (route serves "hello") → Phase 2 implementation completes (services unit-tested in isolation) → THEN Phase 3 implementation starts. Phase 3 cannot start without Phase 2's `AuthManager`, `ApiClient`, and `EventBus` shipped and tested.

## Plan-review pointer — canonical PIP machinery

Per Q11 amendment 2026-05-04: review machinery is the canonical `planning-is-prompting/workflow/plan-review.md`. The slot table for the spine bundle is in `02-phase1-scaffolding-design.md`. This phase's TBDs (§"Open Questions" below) feed into `{{TBD_QUESTIONS}}` for the bundled review.

---

## Context

Phase 3 ports the existing `src/fastapi_app/static/js/ws-channel.js` to TypeScript at `multiplexer/transport/ws-channel.ts`, applying the three Claude analysis findings as it copies:

| Finding | What it fixes |
|---|---|
| **§1.1** — binary-frame routing | Add Blob/ArrayBuffer branch in `socket.onmessage` that routes binary frames to a separate `onBinaryMessage` callback, so audio chunks aren't dropped via `JSON.parse(<Blob>)` throws |
| **§2.2** — lifecycle removal | Remove `_attachPageLifecycle` from the channel; orchestrator (`boot.ts`) owns visibilitychange / online / offline. Channel is transport-only |
| **§2.5** — JSON round-trip removal | Channel emits parsed envelope to `onMessage`; no parse → stringify → parse chain in the dispatch path |

Then this phase builds three thin wrappers that subscribe to the relevant message types and emit on the EventBus:

| Wrapper | Subscribes to | Emits |
|---|---|---|
| `QueueTransport` | `/ws/queue/{session_id}` text frames: `auth_success`, `notification`, `claude_code_event`, `voice_persona_*`, `conversation_mode_*`, etc. | EventBus events with `source: "QueueTransport"` |
| `AudioTransport` | `/ws/audio/{session_id}` text envelopes (`audio_streaming_status`, `audio_streaming_complete`) + binary chunks | EventBus events for status; binary chunks routed to a callback for Phase 4's `AudioStore` |
| `ClaudeCodeTransport` | `/ws/claude-code/...` (currently raw `claudeCodeWs` in `notifications.js`) | EventBus events with `source: "ClaudeCodeTransport"` |

A shared XState **connection state machine** (per Q6 — connection is high-churn) tracks `connecting → connected → reconnecting → backoff → connected | failed`. All three transport wrappers share it via composition; the state machine is the single source of truth for "are we online?".

This phase ships **no UI**, **no domain stores**. The output is observable via EventBus; Phase 4 (stores) and Phase 5 (renderer) consume.

## Strategic posture (recap)

Per Q5: copy `ws-channel.js` to `multiplexer/transport/ws-channel.ts` and apply the three fixes. The original file at `src/fastapi_app/static/js/ws-channel.js` continues to serve current `notifications.html` until cutover. Divergence is permanent.

The transport layer **does not own lifecycle**. `boot.ts` (orchestrator) attaches visibilitychange / online / offline / pagehide listeners and routes them to the connection state machine via EventBus events. This makes lifecycle wiring testable in isolation (transport tests don't need to mock `document.visibilityState`).

## Out of scope for Phase 3

- Domain stores (Phase 4) — transport emits events; Phase 4 stores subscribe and reduce
- Audio playback (binary chunks routed to Phase 4 `AudioStore`; PCM decoding + playback queue is Phase 4)
- TTS playback queue (Phase 4)
- Action-required countdown (Phase 4)
- Any UI rendering (Phase 5+)
- WebSocket server-side changes — server contract (`auth_request` / `auth_success` / event format) unchanged
- Lifecycle implementation in `boot.ts` — the boot.ts skeleton from Phase 1 gets the lifecycle wiring in Phase 3, but the `boot.ts` body is also a Phase 3 deliverable (it's where the transport wrappers come online)

## Files created / edited

| Path | Change | Owner | Rationale |
|---|---|---|---|
| `src/fastapi_app/static/js/multiplexer/transport/ws-channel.ts` | NEW | Lupin | Port of `ws-channel.js` with Claude §1.1 + §2.2 + §2.5 applied; transport-only (no lifecycle) |
| `src/fastapi_app/static/js/multiplexer/transport/ConnectionStateMachine.ts` | NEW | Lupin | Shared XState actor: `connecting → connected → reconnecting → backoff → failed`; consumed by all three wrappers |
| `src/fastapi_app/static/js/multiplexer/transport/QueueTransport.ts` | NEW | Lupin | Subscribes to queue WS text frames; auth via `AuthManager.getToken()`; emits parsed events on EventBus |
| `src/fastapi_app/static/js/multiplexer/transport/AudioTransport.ts` | NEW | Lupin | Subscribes to audio WS; routes binary frames to a callback for `AudioStore` (Phase 4); emits text envelopes on EventBus |
| `src/fastapi_app/static/js/multiplexer/transport/ClaudeCodeTransport.ts` | NEW | Lupin | Subscribes to claude-code WS; replaces raw `claudeCodeWs` from legacy notifications.js |
| `src/fastapi_app/static/js/multiplexer/transport/index.ts` | NEW | Lupin | Exports + factory: `createTransports(authManager, eventBus, baseUrl) → {queue, audio, claudeCode}` |
| `src/fastapi_app/static/js/multiplexer/boot.ts` | EDIT | Lupin | Replace "hello multiplexer" stub: import + start the three transports; attach page-lifecycle listeners and route them to ConnectionStateMachine via EventBus |
| `src/tests/unit/multiplexer/ws_channel.test.ts` | NEW | Lupin | Unit tests for the ts-port: binary-frame routing (§1.1 regression), no-lifecycle (§2.2), parsed-envelope dispatch (§2.5) |
| `src/tests/unit/multiplexer/connection_state_machine.test.ts` | NEW | Lupin | Unit tests for state transitions, backoff jitter, reconnect counter reset on success |
| `src/tests/unit/multiplexer/queue_transport.test.ts` | NEW | Lupin | Unit tests covering auth handshake, event emission, reconnect on socket close |
| `src/tests/unit/multiplexer/audio_transport.test.ts` | NEW | Lupin | Unit tests covering binary-frame routing to callback, text-envelope emission |
| `src/tests/unit/multiplexer/claude_code_transport.test.ts` | NEW | Lupin | Unit tests; equivalent shape to QueueTransport |
| `src/tests/websocket_smoke/test_multiplexer_transport.py` | NEW | Lupin | Live :7999 smoke: connect against dev server, verify `auth_success` arrives on EventBus, kill connection, verify reconnect with backoff. Reads `LUPIN_API_URL` per `feedback_tests_parameterize_base_url` |

**No CoSA edits**: All files under `src/fastapi_app/static/js/multiplexer/` and `src/tests/unit/multiplexer/` + one Python smoke test under `src/tests/websocket_smoke/`. Per `feedback_lupin_only_never_cosa`.

## Transport contracts

### ws-channel.ts (the lowest-level WebSocket wrapper)

Port of `ws-channel.js` with these changes from line one:

```ts
export interface WSChannelOptions {
  url: string;
  protocols?: string | string[];
  onOpen?: (e: Event) => void;
  onMessage?: (envelope: unknown) => void;       // parsed JSON envelope
  onBinaryMessage?: (data: Blob | ArrayBuffer) => void;  // §1.1 fix — binary frames
  onClose?: (e: CloseEvent) => void;
  onError?: (e: Event) => void;
  generationToken: number;  // monotonic; rejects messages from stale generations
}

export interface WSChannel {
  start(): void;
  stop(): void;
  send(envelope: unknown): void;
  state: "connecting" | "open" | "closing" | "closed";
}
```

- §1.1 fix: top of `socket.onmessage`, branch on `event.data` type. Blob/ArrayBuffer → `onBinaryMessage`; string → `JSON.parse` → `onMessage`. No JSON.parse on binary frames. (This regression was already fixed at the Lupin parent in Session 656c8ba2 per history.md; the multiplexer port carries the fix from line one, not as a patch.)
- §2.2 fix: NO `_attachPageLifecycle` method. The channel doesn't know about `document.visibilitychange`, `online`, `offline`, `pagehide`. Orchestrator-side responsibility.
- §2.5 fix: `onMessage` receives the already-parsed envelope. No `JSON.stringify` in the ws-channel.ts body; downstream handlers operate on objects.
- Generation tokens: every reconnect bumps a monotonic counter. Late callbacks from prior connections check the token and no-op if stale. This is preserved from the original — nothing fancy added.
- Full-jitter backoff: preserved from the original, exposed via `ConnectionStateMachine`'s timing config.

### ConnectionStateMachine (XState actor)

States:
- `connecting` — initial; on success → `connected`; on failure → `backoff`
- `connected` — receiving messages; on close → `reconnecting` (if open <100ms — likely fluke) | `backoff` (if open ≥100ms — real disconnect) | `failed` (if max-retries exhausted)
- `reconnecting` — opening a new socket; on success → `connected`; on failure → `backoff`
- `backoff` — waiting (full-jitter per Open Q2); on timer expire → `reconnecting`
- `offline` — network reported unavailable; reconnects cancelled; on `network_online` → `reconnecting`
- `failed` — terminal; user-visible "lost connection" UI; explicit `restart` event re-enters `connecting`

**Grace period** (Pass 1 finding #10 resolution): the "this might be a fluke" threshold is **100ms**. On `socket_close` while in `connected`, check time since last `socket_open`: if <100ms, transition to `reconnecting` (immediate retry, the close was likely transient); if ≥100ms, transition to `backoff` (genuine disconnect, full-jitter wait).

Events:
- `socket_open` — from ws-channel.ts
- `socket_close` — from ws-channel.ts
- `page_hidden`, `page_visible` — from `boot.ts` lifecycle listeners (event types per finding #12 resolution below)
- `network_online`, `network_offline` — from `boot.ts` lifecycle listeners
- `restart` — user-initiated reconnect from a `failed` state

**Full state × event transition matrix** (Pass 1 finding #13 resolution):

| Current state ↓ \ Event → | `socket_open` | `socket_close` | `page_hidden` | `page_visible` | `network_online` | `network_offline` |
|---|---|---|---|---|---|---|
| `connecting` | → `connected` | → `backoff` | cancel timers, stay `connecting` | stay `connecting` | stay `connecting` | → `offline`, cancel timers |
| `connected` | n/a (already open) | → `reconnecting` (if <100ms) or `backoff` (if ≥100ms) | cancel scheduled reconnects, stay `connected` | stay `connected` | stay `connected` | → `offline`, cancel timers |
| `reconnecting` | → `connected` | → `backoff` | cancel any open attempt, stay `reconnecting` (will retry on `page_visible`) | continue attempt | stay `reconnecting` | → `offline`, cancel attempt |
| `backoff` | n/a (no socket yet) | n/a | cancel backoff timer, stay `backoff` (timer resumes on `page_visible`) | fast-forward to `reconnecting` | fast-forward to `reconnecting` | → `offline`, cancel timer |
| `offline` | n/a | n/a | stay `offline` | stay `offline` | → `reconnecting` | stay `offline` |
| `failed` | n/a | n/a | stay `failed` | stay `failed` | stay `failed` (user must `restart`) | stay `failed` |

`offline` is a distinct state from `failed`: `offline` auto-recovers on `network_online`; `failed` requires explicit user intervention. Emits a `connection_offline` event on EventBus on entry, `connection_online` on exit.

### QueueTransport / AudioTransport / ClaudeCodeTransport

Each transport wrapper owns:
1. A `WSChannel` instance for its endpoint (URL constructed from `baseUrl + sessionId`)
2. A subscription to its own `ConnectionStateMachine` actor (each wrapper has its own — disconnect on one socket doesn't reset the others' backoff)
3. An auth handshake: on `socket_open`, call `authManager.getToken()` → send `auth_request` → wait for `auth_success` → emit `transport_ready` event
4. Message parsing + EventBus emission

Public API:
```ts
export interface Transport {
  start(sessionId: string): void;
  stop(): void;
  state: ConnectionState;  // observable via EventBus too
  send(envelope: unknown): void;
}

// AudioTransport's start() takes an additional binary handler (Pass 1 finding #14 resolution)
export interface AudioTransport extends Transport {
  start(sessionId: string, binaryHandler?: (data: Blob | ArrayBuffer) => void): void;
}
```

**QueueTransport / ClaudeCodeTransport envelope mapping** (Pass 1 finding #15 resolution): Each WS text frame from the server arrives as `{type: string, data: unknown, …}` (the legacy envelope format from `/ws/queue/{session_id}` and `/ws/claude-code/...`). On parse, the wrapper emits to EventBus with the LupinEvent shape: `{type: envelope.type, payload: envelope.data, source: "QueueTransport" | "ClaudeCodeTransport", ts: Date.now()}`. Any extra envelope fields are placed on `payload` alongside `data`. The `type` string flows through unchanged (e.g., `auth_success`, `notification`, `claude_code_event`) so EventBus consumers subscribe to the same string the server sends.

**AudioTransport binary callback** (Pass 1 finding #14 resolution; supersedes Open Q3 deferral): `binaryHandler` is the callback provided by boot.ts. Phase 3 default is a debug-logger: `(data) => console.debug("Audio chunk received", data instanceof Blob ? data.size : data.byteLength)`. Phase 4's `AudioStore` replaces this with the real PCM-decoding handler. The callback is invoked once per binary frame received; no return value; errors thrown in the callback are caught by the transport at the call site (do not crash the transport). The text-envelope path on the audio WS (status events) flows through the same `payload`-mapping rule as Queue/ClaudeCode.

**Factory signature** (Pass 1 finding #11 resolution):

```ts
// transport/index.ts
export interface TransportSet {
  queue: Transport;
  audio: Transport;
  claudeCode: Transport;
}

export function createTransports(
  authManager: AuthManager,
  eventBus: EventBus,
  baseUrl: string,
): TransportSet;
```

The factory wires each transport to the shared `AuthManager` + `EventBus`. Each transport gets its own `ConnectionStateMachine` instance (a disconnect on one socket does not reset the others' backoff). Return-key naming is fixed: `{queue, audio, claudeCode}` — never `{queueTransport, ...}`.

### boot.ts Lifecycle Event Emission Contract (Pass 1 finding #12 resolution)

`boot.ts` owns DOM lifecycle. Each ConnectionStateMachine subscribes to the EventBus events below; boot.ts only emits, never re-subscribes.

| DOM event source | Boot emits to EventBus |
|---|---|
| `document.visibilitychange` → hidden | `{type: "page_hidden", payload: { ts: Date.now() }, source: "boot", ts: Date.now()}` |
| `document.visibilitychange` → visible | `{type: "page_visible", payload: { ts: Date.now() }, source: "boot", ts: Date.now()}` |
| `window.online` event | `{type: "network_online", payload: { ts: Date.now() }, source: "boot", ts: Date.now()}` |
| `window.offline` event | `{type: "network_offline", payload: { ts: Date.now() }, source: "boot", ts: Date.now()}` |
| `window.pagehide` (with `event.persisted=true`, bfcache restore) | `{type: "page_visible", payload: { ts: Date.now(), bfcache: true }, source: "boot", ts: Date.now()}` |

**Subscription model**: `boot.ts` emits these events exactly once per DOM event (no multiplication, no debounce — that's the state machine's job). Each transport's `ConnectionStateMachine` subscribes to all four event types via `eventBus.on(type, …)`. boot.ts NEVER subscribes to its own emissions.

`page_hidden`/`page_visible` payloads carry `{ ts }` for downstream telemetry (e.g., measuring how long a tab was hidden); `network_online`/`network_offline` payloads similarly carry `{ ts }`. Future telemetry consumers can subscribe to these events without changing the contract.

## Acceptance criteria (definition of done for Phase 3)

1. All transport modules exist at the expected paths.
2. `tsc --noEmit -p tsconfig.json` passes with zero errors.
3. ESLint passes with zero errors.
4. Unit tests for ws-channel.ts: binary-frame routing (a Blob frame fixture invokes `onBinaryMessage`, never `onMessage`); no `_attachPageLifecycle` exists on the public API; parsed envelope reaches `onMessage` (no JSON.stringify in the dispatch path).
5. Unit tests for ConnectionStateMachine: state transitions match spec; backoff timer fires; generation tokens reject stale-connection callbacks.
6. Unit tests for each Transport: auth handshake completes; event emission has correct `source` marker; reconnect attempt fires on socket close.
7. **EXECUTOR: AI** — Live :7999 smoke (`src/tests/websocket_smoke/test_multiplexer_transport.py`) — **observability spec** (Pass 1 finding #17 + Pass 2 finding #5 resolution):
   - AI test connects against dev server; AI asserts `auth_success` text frame arrives within 5s of socket open (programmatic assertion via WS client subscription)
   - AI test force-closes the socket (server-side disconnect via WS protocol close, or client-side `transport.stop()` + `start()` cycle)
   - AI test asserts `ConnectionStateMachine` transitions to `backoff` within 100ms of close (programmatic assertion via EventBus subscription to `connection_state_change` event with `payload.state === "backoff"`)
   - AI test asserts a new socket open attempt and fresh `auth_success` frame arrive within `(2^n × 1000ms × full-jitter)` of the close, max 35s timeout (per Open Q2 backoff config)
   - AI test asserts `connection_reconnecting` event was emitted on EventBus (with `source: "ConnectionStateMachine"`) BEFORE the new socket opened — ordering assertion captures the correct state machine transition
   - AI test uses `asyncio.wait_for` with explicit timeouts on EventBus subscription queues; NO `time.sleep`; pass/fail produced programmatically
8. Page-load smoke: load `/app/multiplexer` in Playwright headless; verify all three transports reach `transport_ready` state within 10s; no console errors.

## Verification (Claude-executed per `01-working-contract.md`)

The user is never the tester. Claude executes every verification step and reports results in tabular form.

### :7999 (AI-discretionary, immediately after each module lands)

| Step | Command / Action | Pass criterion |
|---|---|---|
| Build smoke | `bash src/scripts/build-multiplexer.sh` | Exit 0; bundle includes transport modules |
| TypeScript check | `npx tsc --noEmit -p tsconfig.json` | Zero errors |
| ESLint check | `npx eslint src/fastapi_app/static/js/multiplexer/` | Zero errors |
| Unit tests — ws_channel | `npx tsx --test src/tests/unit/multiplexer/ws_channel.test.ts` (or test runner per Phase 2 Q1 resolution) | All pass; binary-frame regression test included |
| Unit tests — connection_state_machine | (same shape) | All pass; state transitions cover full spec |
| Unit tests — queue_transport | (same shape) | All pass; auth handshake + emission verified |
| Unit tests — audio_transport | (same shape) | All pass; binary-callback routing verified |
| Unit tests — claude_code_transport | (same shape) | All pass |
| WS smoke — multiplexer transports | `pytest src/tests/websocket_smoke/test_multiplexer_transport.py -v` | All pass against `:7999`; reconnect observed within 10s of socket close |
| Page-load smoke | Playwright headless: load `/app/multiplexer`; observe console + DOM state for `transport_ready` markers on all three transports | All three transports ready within 10s; zero console errors |

All `LUPIN_API_URL`-aware tests use the env var per `feedback_tests_parameterize_base_url`; default `http://localhost:7999`.

### :8000 (scheduled — N/A for Phase 3)

Phase 3 is non-destructive (read-only WS subscription against the dev server, no state mutations) and fast (< 30s total). Fits :7999 envelope. :8000 work begins at Phase 6 per `01-execution-plan.md` §4.5.

## Rollback procedure

If Phase 3 needs to be reverted:
1. Remove `multiplexer/transport/` directory and tests under `src/tests/unit/multiplexer/{ws_channel,connection_state_machine,*_transport}.test.ts` + `src/tests/websocket_smoke/test_multiplexer_transport.py`.
2. Revert `boot.ts` to the Phase 1 "hello multiplexer" stub.
3. **EXECUTOR: AI**: `curl -I http://localhost:7999/app/multiplexer` returns 200 OK; re-run Phase 1 page-load Playwright assertion + Phase 2 full unit suite (`npx tsx --test src/tests/unit/multiplexer/`) — both must produce pass output to confirm Phase 1 and Phase 2 surfaces unaffected by the Phase 3 revert.

The original `src/fastapi_app/static/js/ws-channel.js` is NOT modified by Phase 3 — current `notifications.html` continues to serve.

## Open questions — ALL RESOLVED 2026-05-04 (REUSE DC2 + Pass 1 OQ ratifications)

1. **Session ID source** — **RESOLVED 2026-05-04 (DC2)**: Phase 2 StorageService owns the session ID via first-class `getSessionId()` / `setSessionId()` methods (see `03-phase2-foundation-design.md` § StorageService). Phase 3 transports MUST call `storage.getSessionId()` — never raw localStorage. boot.ts is responsible for: read `getSessionId()` at startup; if `null`, generate a new ID via the existing "adjective noun" format (mirrors `notifications.js:478` legacy logic) and call `setSessionId()`. The "StorageService owns all storage" invariant is non-negotiable.

2. **Backoff timing config** — **RESOLVED 2026-05-04 (Pass 1 OQ ratification)**: Hard-coded `min(1000 * 2^n, 30000)` with full jitter. INI plumbing for browser-side backoff is overkill; if a future incident demands tuning, surface as a config flag then. Document the formula in `ConnectionStateMachine.ts` comments at the timing-config site.

3. **AudioTransport binary callback contract** — **RESOLVED 2026-05-04 (Pass 1 finding #14 + OQ ratification)**: Phase 3 stub signature is pinned: `start(sessionId: string, binaryHandler?: (data: Blob | ArrayBuffer) => void): void`. Default Phase 3 handler is a debug-logger; Phase 4's AudioStore replaces it with the real PCM handler. Callback contract: invoked once per binary frame; no return value; errors thrown caught at call site without crashing the transport. Full contract in §"AudioTransport binary callback" above.

4. **ClaudeCodeTransport WebSocket URL pattern** — **RESOLVED 2026-05-04 (Pass 1 finding #16 + OQ ratification)** with explicit unblock procedure for execute-time:

   **Pre-implementation step** (run BEFORE writing Phase 3 transport code):
   ```bash
   grep -n 'claudeCodeWs\|claude-code' src/fastapi_app/static/js/notifications.js | head -3
   ```
   Identify the URL pattern the legacy file uses. Then verify the same pattern is registered in `src/cosa/rest/routers/websocket.py` route table (open the file and confirm an `@router.websocket("/ws/claude-code/{...}")` line exists with the matching path). If the legacy URL exists in the server router, use that pattern in `ClaudeCodeTransport`. If the server route is missing or differs from the legacy URL, **escalate to user before writing transport code** — there's a server/client mismatch that needs design clarification, not a transport-side fix.

   This unblocks Phase 3 implementation without coupling the design doc to a specific URL string (the server router is the source of truth, and inlining the URL here would create a doc-vs-code drift risk).

## Prior art referenced (from REUSE pre-pass 2026-05-04)

Per PIP §4: extend-existing + genuinely-new-with-prior-art findings, captured for traceability.

| Phase 3 component | Prior art (file:line) | Verdict |
|---|---|---|
| ws-channel.ts port + Claude §1.1 binary-frame fix | `src/fastapi_app/static/js/ws-channel.js:267-278` (Blob/ArrayBuffer branch + `onBinaryMessage` callback at line 95-96, 127, 271-273) — fix already landed in Session 656c8ba2 | genuinely-new (copy + carry-forward per Q5; the parent file is already patched, so the multiplexer port carries the fix from line one rather than re-applying it; §2.2 lifecycle removal + §2.5 JSON round-trip removal still apply during the port) |
| ConnectionStateMachine (XState actor) | `src/fastapi_app/static/js/ws-channel.js:95-450` + `src/fastapi_app/static/js/notifications.js:911-921` (state tracking via string constants `"CONNECTING"`, `"CONNECTED"`, `"OPEN_CIRCUIT"`; **no XState; state mgmt is boolean + timer soup**) | genuinely-new (greenfield isolation per Q5; legacy has no formal state machine) |
| QueueTransport wrapper | `src/fastapi_app/static/js/notifications.js:2150-2216` (creates WSChannel instances; handles `auth_success` / `notification` events directly on `NotificationsUI`; **no wrapper abstraction or EventBus emission**) | genuinely-new (REUSE agent originally verdict-tagged this `extend-existing` but the explanation contradicted that — re-classified to genuinely-new per user direction; the wrapper IS a new boundary layer between the channel and the domain stores, even though the WS endpoint is the same) |
| AudioTransport wrapper | `src/fastapi_app/static/js/notifications.js:2256-2260` (audio handling mixed into main UI; **no transport abstraction**) | genuinely-new (greenfield isolation per Q5) |
| ClaudeCodeTransport wrapper | `src/fastapi_app/static/js/notifications.js:3919-3943` (raw `claudeCodeWs` WebSocket; **no transport wrapper**) | genuinely-new (greenfield isolation per Q5; legacy uses raw socket, not wrapped transport) |
| WS smoke test for multiplexer transports | `src/tests/websocket_smoke/` directory exists with Python fixtures | extend-existing (add `test_multiplexer_transport.py` to existing smoke-test structure) |

## Self-audit (against feedback memory, draft time)

| Memory | Compliance |
|---|---|
| `feedback_phase0_serialization_prominence` | ✅ Phase 0 already shipped; this doc is Phase 3 |
| `feedback_documentation_first_protocol` | ✅ Design doc lands BEFORE Phase 3 code |
| `feedback_audit_plans_at_execute_time` | ✅ Open Questions section flags re-audit on session-ID source + binary-callback contract + claude-code URL |
| `feedback_lupin_only_never_cosa` | ✅ All paths under `src/fastapi_app/static/js/multiplexer/` + `src/tests/`; no CoSA edits |
| `feedback_never_auto_commit_push` | ✅ No commit-on-completion language |
| `feedback_comprehensive_automated_testing` | ✅ Verification covers build smoke, TS/ESLint, unit per module, WS smoke, page-load smoke |
| `feedback_tests_parameterize_base_url` | ✅ All tests read `LUPIN_API_URL` |
| `feedback_test_server_monopolize_mode` | ✅ Phase 3 needs no :8000 work |
| `feedback_skip_rnd_doc_for_trivial_fixes` | n/a — Phase 3 ports a 600+ line file + adds 5 new transport modules |
| `feedback_sweep_for_pattern_offenders` | ✅ The §1.1 binary-frame regression is the canonical example of a sweep finding (already swept across `notifications.js`); the multiplexer port carries the fix from line one |
| `feedback_no_defensive_programming` | ✅ ws-channel.ts emits parsed envelope; no defensive `try/catch` around the parse — bad data fails loudly |
| `feedback_fix_at_source_not_consumer` | ✅ Binary-frame routing decided at the channel boundary, not at every consumer |

## Approval gate

Phase 3 implementation begins ONLY after the bundled spine plan-review passes and the user approves the spine bundle (covering this doc + `02-phase1-scaffolding-design.md` + `03-phase2-foundation-design.md`). Per Q10 amendment + `feedback_never_auto_commit_push`. Within the bundle, Phase 1 + Phase 2 implementations complete BEFORE Phase 3 implementation starts.
