// Multiplexer Phase 3 — ClaudeCodeTransport (STUB).
//
// **Phase 3 status: STUB** — TS interface and factory entry land in Phase 3
// per the design's file map (`04-phase3-transport-design.md` § "Files created
// / edited"); the running body lands in Phase 4.
//
// Why the stub: the legacy claude-code WS endpoint is fundamentally divergent
// from queue/audio (per execution-log Phase 3 § "Discovered design gap"):
//
//   - Per-TASK, not per-session — URL is `/api/claude-code/ws/{task_id}`,
//     constructed lazily after `POST /api/claude-code/dispatch` returns a
//     task_id. There is no taskId at page-load time.
//   - No `auth_request` handshake — server sends `{type: "connected", task_id}`
//     on accept; client never sends a credentialed envelope.
//   - Different message types (`connected`, `status`, `text`, `tool_use`,
//     `tool_result`, `complete`, `keepalive`) than queue's `auth_success` /
//     `notification` / etc.
//
// boot.ts MUST NOT auto-start this transport. Phase 4's claude-code store is
// responsible for calling `start(taskId)` after a CC task is dispatched.
//
// User decision (2026-05-04 PM): Option C — stub the file + interface in
// Phase 3; full body in Phase 4. Recorded in `90-execution-log.md` Phase 3.

import type { AuthManager } from "../auth/AuthManager";
import type { EventBus } from "../shared/EventBus";
import type { ConnectionState } from "../shared/types";

export interface ClaudeCodeTransport {
  /**
   * Open the per-task WebSocket. Phase 3 stub throws `not implemented`;
   * Phase 4 wires the body.
   *
   * @param taskId  The CC task identifier returned by POST /api/claude-code/dispatch
   */
  start(taskId: string): void;
  stop(): void;
  send(envelope: unknown): void;
  readonly state: ConnectionState;
}

export interface ClaudeCodeTransportOptions {
  authManager   : AuthManager;
  bus           : EventBus;
  baseUrl       : string;
  WebSocketCtor?: typeof WebSocket;
}

class ClaudeCodeTransportStub implements ClaudeCodeTransport {
  private _state: ConnectionState = "connecting";
  // Suppress "unused" lint findings; held for Phase 4 wiring.
  private readonly _opts: ClaudeCodeTransportOptions;

  constructor(opts: ClaudeCodeTransportOptions) {
    this._opts = opts;
    void this._opts;
  }

  get state(): ConnectionState {
    return this._state;
  }

  start(_taskId: string): void {
    void _taskId;
    throw new Error(
      "ClaudeCodeTransport: not implemented in Phase 3 — body lands in Phase 4 stores. " +
      "boot.ts must not auto-start this transport.",
    );
  }

  stop(): void {
    // Phase 3 stub: no resources to release. Transition to `failed` so any
    // observer of `state` sees a definite-terminal value rather than the
    // initial `connecting` placeholder.
    this._state = "failed";
  }

  send(_envelope: unknown): void {
    void _envelope;
    throw new Error(
      "ClaudeCodeTransport: not implemented in Phase 3 — body lands in Phase 4 stores.",
    );
  }
}

export function createClaudeCodeTransport(
  opts: ClaudeCodeTransportOptions,
): ClaudeCodeTransport {
  return new ClaudeCodeTransportStub(opts);
}
