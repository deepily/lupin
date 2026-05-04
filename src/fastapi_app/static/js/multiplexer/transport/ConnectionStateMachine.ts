// Multiplexer Phase 3 — ConnectionStateMachine.
// XState v5 tracker (Phase 2 pattern) modeling the per-transport WebSocket
// lifecycle: `connecting` → `connected` → (`reconnecting` | `backoff`) →
// `connected` | `offline` | `failed`. Each transport (QueueTransport /
// AudioTransport / ClaudeCodeTransport) holds its own instance — a disconnect
// on one socket does NOT reset the others' backoff.
//
// Pattern decision (per Phase 2 AuthManager): the XState machine TRACKS state
// (driven by external code that owns timers + WSChannel start/stop); it is
// NOT an autonomous actor invoking services. This keeps the orchestration
// (timer scheduling, EventBus emission) in one readable place — the wrapping
// transport — instead of split across actor invocations.
//
// Grace period (Pass 1 finding #10): on `socket_close` while in `connected`,
// check time-since-last-`socket_open`. < 100ms → transient fluke, immediate
// retry via `reconnecting`. ≥ 100ms → genuine disconnect, full-jitter wait
// via `backoff`.
//
// `offline` is distinct from `failed`: the former auto-recovers on
// `network_online`; the latter requires explicit `restart` from the user
// (or the wrapper escalating after retry-budget exhaustion).
//
// Backoff timing: hard-coded `min(1000 * 2^n, 30000)` ms with full jitter.
// No INI plumbing per Open Q2 ratification (2026-05-04). Exposed via
// `backoffDelayMs(attempt)` so the wrapping transport can schedule its own
// timer; the machine does NOT own setTimeout — only state.

import { createActor, setup, assign } from "xstate";

import type { EventBus } from "../shared/EventBus";
import type {
  ConnectionLifecyclePayload,
  ConnectionReconnectingPayload,
  ConnectionState,
  ConnectionStateChangePayload,
  LupinEvent,
} from "../shared/types";

// ---------------------------------------------------------------------------
// Constants. Documented at the timing-config site per Open Q2 ratification.
// ---------------------------------------------------------------------------

// Grace threshold: a `socket_close` arriving within this many ms of the last
// `socket_open` is treated as a transient fluke — retry via `reconnecting`
// instead of waiting in `backoff`.
const DEFAULT_GRACE_MS = 100;

// Backoff base + cap per design Open Q2 ratification 2026-05-04. Full jitter
// per AWS Architecture Blog "Exponential Backoff And Jitter".
const BACKOFF_BASE_MS = 1000;
const BACKOFF_CAP_MS  = 30_000;

/**
 * Full-jitter backoff delay in milliseconds.
 *
 * Requires:
 *   - attempt is a non-negative integer
 *
 * Ensures:
 *   - returns an integer in [0, min(BACKOFF_BASE_MS * 2^attempt, BACKOFF_CAP_MS)]
 *   - documented formula matches design Open Q2 (`min(1000 * 2^n, 30000)`)
 */
export function backoffDelayMs(attempt: number): number {
  const exp = Math.min(BACKOFF_BASE_MS * Math.pow(2, attempt), BACKOFF_CAP_MS);
  return Math.floor(Math.random() * exp);
}

// ---------------------------------------------------------------------------
// XState v5 machine.
// ---------------------------------------------------------------------------

interface ConnectionContext {
  attempts       : number;
  connectedAtMs  : number;
  graceMs        : number;
}

interface ConnectionInput {
  graceMs? : number;
}

export type ConnectionEvent =
  | { type: "socket_open" }
  | { type: "socket_close" }
  | { type: "page_hidden" }
  | { type: "page_visible" }
  | { type: "network_online" }
  | { type: "network_offline" }
  | { type: "backoff_expire" }       // wrapper fires after backoff timer
  | { type: "max_attempts_reached" } // wrapper escalates → failed
  | { type: "restart" };             // user-initiated restart from failed

const connectionMachine = setup({
  types : {
    context : {} as ConnectionContext,
    events  : {} as ConnectionEvent,
    input   : {} as ConnectionInput | undefined,
  },
  guards : {
    // < graceMs since last socket_open → transient fluke.
    isFluke : ({ context }) =>
      Date.now() - context.connectedAtMs < context.graceMs,
  },
  actions : {
    recordConnectedAt : assign({
      connectedAtMs : () => Date.now(),
    }),
    incrementAttempts : assign({
      attempts : ({ context }) => context.attempts + 1,
    }),
    resetAttempts : assign({
      attempts : () => 0,
    }),
  },
}).createMachine({
  id      : "connection",
  initial : "connecting",
  context : ({ input }) => ({
    attempts      : 0,
    connectedAtMs : 0,
    graceMs       : input?.graceMs ?? DEFAULT_GRACE_MS,
  }),
  states : {
    connecting : {
      // page_hidden / page_visible / network_online stay (matrix); only
      // network_offline and socket events transition.
      on : {
        socket_open     : { target: "connected",  actions: "recordConnectedAt" },
        socket_close    : { target: "backoff",    actions: "incrementAttempts" },
        network_offline : { target: "offline" },
      },
    },
    connected : {
      // Reset attempts on every entry to connected — successful connection.
      entry : "resetAttempts",
      on : {
        socket_close : [
          { guard: "isFluke", target: "reconnecting" },
          { target: "backoff", actions: "incrementAttempts" },
        ],
        network_offline : { target: "offline" },
      },
    },
    reconnecting : {
      on : {
        socket_open     : { target: "connected",  actions: "recordConnectedAt" },
        socket_close    : { target: "backoff",    actions: "incrementAttempts" },
        network_offline : { target: "offline" },
      },
    },
    backoff : {
      on : {
        backoff_expire       : { target: "reconnecting" },
        // Fast-forward: visibility / network restore should retry NOW
        // instead of waiting out the timer.
        page_visible         : { target: "reconnecting" },
        network_online       : { target: "reconnecting" },
        network_offline      : { target: "offline" },
        max_attempts_reached : { target: "failed" },
      },
    },
    offline : {
      on : {
        network_online : { target: "reconnecting" },
      },
    },
    failed : {
      on : {
        restart : { target: "connecting" },
      },
    },
  },
});

// ---------------------------------------------------------------------------
// ConnectionStateMachine class.
// ---------------------------------------------------------------------------

export interface ConnectionStateMachine {
  send(event: ConnectionEvent): void;
  readonly state    : ConnectionState;
  readonly attempts : number;
  // Subscribe to state transitions. Return value is unsubscribe.
  subscribe(listener: (state: ConnectionState, prev: ConnectionState) => void): () => void;
  // Tear down — stops the underlying actor + drops subscribers.
  stop(): void;
}

export interface ConnectionStateMachineOptions {
  bus           : EventBus;
  // Per-transport identifier ("QueueTransport" / "AudioTransport" etc.).
  // The CSM emits all events with `source: "ConnectionStateMachine"` per
  // AC#7; the per-transport name lands in `payload.transport` so consumers
  // can filter when multiple CSMs share the bus.
  transportName : string;
  // Override grace threshold (test-only).
  graceMs?      : number;
}

const CSM_EVENT_SOURCE = "ConnectionStateMachine";

export class ConnectionStateMachineImpl implements ConnectionStateMachine {
  private readonly bus           : EventBus;
  private readonly transportName : string;
  private readonly actor;
  private readonly listeners     : Set<(state: ConnectionState, prev: ConnectionState) => void> = new Set();
  private prevState              : ConnectionState = "connecting";

  constructor(opts: ConnectionStateMachineOptions) {
    this.bus           = opts.bus;
    this.transportName = opts.transportName;

    this.actor = createActor(connectionMachine, {
      input : opts.graceMs !== undefined ? { graceMs: opts.graceMs } : undefined,
    });

    // Subscribe to actor transitions; emit EventBus events.
    this.actor.subscribe((snapshot) => {
      const next = snapshot.value as ConnectionState;
      const prev = this.prevState;
      if (next === prev) return;
      this.prevState = next;
      const attempts = snapshot.context.attempts;

      // Emit connection_state_change for every transition.
      this.bus.emit<ConnectionStateChangePayload>({
        type    : "connection_state_change",
        payload : { state: next, prev, attempts, transport: this.transportName },
        source  : CSM_EVENT_SOURCE,
        ts      : Date.now(),
      });

      // Emit connection_reconnecting BEFORE the wrapper opens a new socket
      // (per AC#7 ordering assertion). The wrapper observes the state
      // transition and starts WSChannel immediately after; the EventBus
      // emit ordering is established here at the source.
      if (next === "reconnecting") {
        this.bus.emit<ConnectionReconnectingPayload>({
          type    : "connection_reconnecting",
          payload : { attempts, transport: this.transportName },
          source  : CSM_EVENT_SOURCE,
          ts      : Date.now(),
        });
      }

      // Emit connection_offline on entry to offline; connection_online on
      // exit from offline.
      if (next === "offline") {
        this.bus.emit<ConnectionLifecyclePayload>({
          type    : "connection_offline",
          payload : { ts: Date.now(), transport: this.transportName },
          source  : CSM_EVENT_SOURCE,
          ts      : Date.now(),
        });
      } else if (prev === "offline") {
        this.bus.emit<ConnectionLifecyclePayload>({
          type    : "connection_online",
          payload : { ts: Date.now(), transport: this.transportName },
          source  : CSM_EVENT_SOURCE,
          ts      : Date.now(),
        });
      }

      // Notify direct subscribers (used by transport wrappers to drive
      // WSChannel start/stop + timer scheduling).
      for (const listener of this.listeners) {
        try { listener(next, prev); } catch { /* swallow consumer errors */ }
      }
    });
    this.actor.start();
  }

  send(event: ConnectionEvent): void {
    this.actor.send(event);
  }

  get state(): ConnectionState {
    return this.actor.getSnapshot().value as ConnectionState;
  }

  get attempts(): number {
    return this.actor.getSnapshot().context.attempts;
  }

  subscribe(
    listener: (state: ConnectionState, prev: ConnectionState) => void,
  ): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  stop(): void {
    this.listeners.clear();
    this.actor.stop();
  }
}

export function createConnectionStateMachine(
  opts: ConnectionStateMachineOptions,
): ConnectionStateMachine {
  return new ConnectionStateMachineImpl(opts);
}

export type ConnectionEventOnBus =
  | LupinEvent<ConnectionStateChangePayload>
  | LupinEvent<ConnectionReconnectingPayload>
  | LupinEvent<ConnectionLifecyclePayload>;
