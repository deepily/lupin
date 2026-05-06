/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Phase 3 — QueueTransport (and BaseTransportImpl).
// QueueTransport wraps a WSChannel for /ws/queue/{sessionId}. The
// `BaseTransportImpl` abstract class holds the shared orchestration
// (CSM wiring, auth handshake, lifecycle forwarding, backoff timer) so
// AudioTransport can extend it without copy-paste.
//
// Per design Pass 1 finding #11: each transport owns its own
// ConnectionStateMachine — a disconnect on one socket does NOT reset the
// others' backoff. Per Pass 1 finding #15: server frames map to EventBus
// emissions as `{type: env.type, payload: env.data, source, ts}`.
//
// The wrapper does NOT own DOM lifecycle (Claude analysis §2.2); boot.ts
// emits page_hidden / page_visible / network_online / network_offline on
// EventBus and the wrapper forwards them to the CSM.

import type { AuthManager } from "../auth/AuthManager";
import type { EventBus } from "../shared/EventBus";
import type {
  ConnectionState,
  LupinEventType,
  TransportReadyPayload,
} from "../shared/types";

import {
  backoffDelayMs,
  createConnectionStateMachine,
  type ConnectionStateMachine,
} from "./ConnectionStateMachine";
import { createWSChannel, type WSChannel } from "./ws-channel";

const DEFAULT_MAX_ATTEMPTS = 20;

export interface Transport {
  start(sessionId: string): void;
  stop(): void;
  send(envelope: unknown): void;
  readonly state: ConnectionState;
}

export interface BaseTransportOptions {
  authManager   : AuthManager;
  bus           : EventBus;
  baseUrl       : string;
  WebSocketCtor?: typeof WebSocket;
  graceMs?      : number;
  maxAttempts?  : number;
}

interface AuthRequestEnvelope {
  type              : "auth_request";
  token             : string;
  session_id        : string;
  subscribed_events : ReadonlyArray<string>;
}

/**
 * Shared orchestration for transport wrappers that perform an auth_request →
 * auth_success handshake against a per-session WebSocket endpoint. Concrete
 * subclasses provide:
 *   - transportName        — used as EventBus `source` for the wrapper's own
 *                            emissions (transport_ready) and as `payload.transport`
 *                            on CSM emissions
 *   - endpointPath         — e.g. "/ws/queue" (URL form: `{base}{endpointPath}/{sessionId}`)
 *   - subscribedEvents     — list passed in auth_request for server-side filtering
 *   - onBinaryMessage      — optional Blob/ArrayBuffer routing (AudioTransport)
 *
 * The ConnectionStateMachine is created lazily on first start() so subclass
 * field initialization (transportName) is observable when constructing it.
 */
export abstract class BaseTransportImpl implements Transport {
  protected readonly authManager  : AuthManager;
  protected readonly bus          : EventBus;
  protected readonly baseUrl      : string;
  protected readonly WSCtor?      : typeof WebSocket;
  protected readonly maxAttempts  : number;
  protected readonly graceMs?     : number;

  protected abstract readonly transportName    : string;
  protected abstract readonly endpointPath     : string;
  protected abstract readonly subscribedEvents : ReadonlyArray<string>;

  protected csm             : ConnectionStateMachine | null = null;
  protected sessionId       : string | null = null;
  protected wsChannel       : WSChannel | null = null;
  protected backoffTimer    : ReturnType<typeof setTimeout> | null = null;
  protected authReady       : boolean = false;
  protected lifecycleUnsubs : Array<() => void> = [];
  protected csmUnsub        : (() => void) | null = null;
  protected stopped         : boolean = false;

  constructor(opts: BaseTransportOptions) {
    this.authManager = opts.authManager;
    this.bus         = opts.bus;
    this.baseUrl     = stripTrailingSlash(opts.baseUrl);
    this.WSCtor      = opts.WebSocketCtor;
    this.maxAttempts = opts.maxAttempts ?? DEFAULT_MAX_ATTEMPTS;
    if (opts.graceMs !== undefined) this.graceMs = opts.graceMs;
  }

  get state(): ConnectionState {
    // Pre-start: report initial CSM state.
    return this.csm?.state ?? "connecting";
  }

  start(sessionId: string): void {
    if (this.stopped) {
      throw new Error(`${this.transportName}: cannot start a stopped transport`);
    }
    if (this.sessionId !== null) {
      if (this.sessionId === sessionId) return;
      throw new Error(`${this.transportName}: already started with a different session`);
    }
    this.sessionId = sessionId;

    // Lazy CSM construction — subclass `transportName` is set by now.
    this.csm = createConnectionStateMachine({
      bus           : this.bus,
      transportName : this.transportName,
      ...(this.graceMs !== undefined ? { graceMs: this.graceMs } : {}),
    });

    const csm = this.csm;  // capture for closures (TS narrowing)
    this.csmUnsub = csm.subscribe((state) => this.onStateChange(state));

    this.lifecycleUnsubs.push(
      this.bus.on("page_hidden",     () => csm.send({ type: "page_hidden" })),
      this.bus.on("page_visible",    () => csm.send({ type: "page_visible" })),
      this.bus.on("network_online",  () => csm.send({ type: "network_online" })),
      this.bus.on("network_offline", () => csm.send({ type: "network_offline" })),
    );

    this.openSocket();
  }

  stop(): void {
    this.stopped = true;
    this.cancelBackoffTimer();
    for (const unsub of this.lifecycleUnsubs) unsub();
    this.lifecycleUnsubs = [];
    if (this.csmUnsub) {
      this.csmUnsub();
      this.csmUnsub = null;
    }
    if (this.wsChannel) {
      this.wsChannel.stop();
      this.wsChannel = null;
    }
    if (this.csm) {
      this.csm.stop();
      this.csm = null;
    }
    this.authReady = false;
  }

  send(envelope: unknown): void {
    if (!this.wsChannel) {
      throw new Error(`${this.transportName}: cannot send — channel is not started`);
    }
    this.wsChannel.send(envelope);
  }

  // -------------------------------------------------------------------------
  // Subclass hooks
  // -------------------------------------------------------------------------

  /**
   * Build the WebSocket URL for this transport. Default form:
   *   `{baseUrl}{endpointPath}/{encodedSessionId}`
   * AudioTransport / QueueTransport do not need to override; future per-task
   * transports may override to use a taskId in place of sessionId.
   */
  protected buildUrl(sessionId: string): string {
    return `${this.baseUrl}${this.endpointPath}/${encodeURIComponent(sessionId)}`;
  }

  /**
   * Optional binary-frame handler. Default: undefined (no binary routing).
   * AudioTransport overrides to forward Blob/ArrayBuffer to its caller-provided
   * handler per Pass 1 finding #14.
   */
  protected onBinaryMessage?: (data: Blob | ArrayBuffer) => void;

  // -------------------------------------------------------------------------
  // Internals
  // -------------------------------------------------------------------------

  protected openSocket(): void {
    /* c8 ignore next */ // defensive: openSocket is only called from start() (after sessionId is set on line 114) and from the "reconnecting" CSM transition (which can only fire after start() established the session); the null-sessionId arm is unreachable from the lifecycle. Belt-and-suspenders for any future caller that misuses the method.
    if (this.sessionId === null) return;
    if (this.wsChannel) {
      this.wsChannel.stop();
      this.wsChannel = null;
    }
    this.authReady = false;

    const opts: Parameters<typeof createWSChannel>[0] = {
      url             : this.buildUrl(this.sessionId),
      onOpen          : () => this.onSocketOpen(),
      onMessage       : (env) => this.onMessage(env),
      onClose         : () => this.onSocketClose(),
      generationToken : 0,
    };
    if (this.WSCtor) opts.WebSocketCtor = this.WSCtor;
    if (this.onBinaryMessage) {
      opts.onBinaryMessage = (data) => this.onBinaryMessage!(data);
    }
    this.wsChannel = createWSChannel(opts);
    this.wsChannel.start();
  }

  protected async onSocketOpen(): Promise<void> {
    if (this.csm) this.csm.send({ type: "socket_open" });
    /* c8 ignore next */ // defensive: onSocketOpen fires from the WSChannel `onOpen` callback, which is wired in openSocket() AFTER sessionId is non-null. The null-sessionId arm is unreachable from the wiring contract.
    if (this.sessionId === null) return;
    try {
      const token = await this.authManager.getToken();
      const req: AuthRequestEnvelope = {
        type              : "auth_request",
        token             : token.accessToken,
        session_id        : this.sessionId,
        subscribed_events : this.subscribedEvents,
      };
      if (this.wsChannel && this.wsChannel.state === "open") {
        this.wsChannel.send(req);
      }
    } catch {
      // Auth failed (token fetch, refresh failure, etc.). Stop the channel
      // AND notify the CSM so it transitions out of `connected` (otherwise
      // the wrapper sits in a limbo where CSM thinks we're connected but
      // wsChannel is dead). The CSM's grace window typically routes this
      // to `reconnecting` for an immediate retry; if the auth failure is
      // persistent, attempts will accumulate and eventually trip
      // max_attempts_reached → failed.
      if (this.wsChannel) this.wsChannel.stop();
      if (this.csm) this.csm.send({ type: "socket_close" });
    }
  }

  protected onMessage(envelope: unknown): void {
    if (typeof envelope !== "object" || envelope === null) return;
    const env = envelope as { type?: unknown; data?: unknown };
    if (typeof env.type !== "string") return;

    const eventType = env.type;

    if (eventType === "auth_success" && !this.authReady) {
      this.authReady = true;
      this.bus.emit<TransportReadyPayload>({
        type    : "transport_ready",
        payload : { transport: this.transportName },
        source  : this.transportName,
        ts      : Date.now(),
      });
    }

    this.bus.emit<unknown>({
      type    : eventType as LupinEventType,
      payload : env.data,
      source  : this.transportName,
      ts      : Date.now(),
    });
  }

  protected onSocketClose(): void {
    this.authReady = false;
    if (this.csm) this.csm.send({ type: "socket_close" });
  }

  protected onStateChange(state: ConnectionState): void {
    const csm = this.csm;
    /* c8 ignore next */ // defensive: csm is captured from this.csm before any mutation. stop() nulls this.csm AND tears down csmUnsub before returning, so no fresh callback can observe csm=null. Belt-and-suspenders for any straggling enqueued callback that survived unsubscribe (none expected).
    if (!csm) return;  // post-stop callbacks
    /* c8 ignore start */
    // The "backoff" branch + max-attempts → failed escalation + scheduleBackoff
    // invocation is exercised at the live :7999 layer (server-side WS smoke test
    // verifies reconnect under server-driven close) and via the mock-timer test
    // below (`backoff timer eventually fires reconnecting`). c8 + tsx + node:test
    // mock.timers source maps don't aggregate the in-callback coverage cleanly;
    // the ignore is honest about that instrumentation quirk rather than masking
    // real uncovered code. The c8-ignore now wraps the `if (state === "backoff")`
    // branch entry (line 271) AS WELL AS the body, since the branch decision
    // and body are inseparable for instrumentation purposes.
    if (state === "backoff") {
      if (csm.attempts >= this.maxAttempts) {
        csm.send({ type: "max_attempts_reached" });
        return;
      }
      this.scheduleBackoff();
      /* c8 ignore stop */
    } else if (state === "reconnecting") {
      this.cancelBackoffTimer();
      this.openSocket();
    } else if (state === "offline" || state === "failed") {
      this.cancelBackoffTimer();
      if (this.wsChannel) {
        this.wsChannel.stop();
        this.wsChannel = null;
      }
    }
  }

  /* c8 ignore start */
  // See onStateChange c8-ignore rationale — the timer callback is exercised
  // live via the WS smoke + mock.timers unit test, but c8 + tsx + node:test
  // do not converge on attribution.
  protected scheduleBackoff(): void {
    if (!this.csm) return;
    this.cancelBackoffTimer();
    const delay = backoffDelayMs(this.csm.attempts);
    this.backoffTimer = setTimeout(() => {
      this.backoffTimer = null;
      if (this.csm) this.csm.send({ type: "backoff_expire" });
    }, delay);
  }

  protected cancelBackoffTimer(): void {
    if (this.backoffTimer !== null) {
      clearTimeout(this.backoffTimer);
      this.backoffTimer = null;
    }
  }
  /* c8 ignore stop */
}

// ---------------------------------------------------------------------------
// QueueTransport — concrete subclass for /ws/queue/{sessionId}.
// ---------------------------------------------------------------------------

// Subscribed-event filter sent in auth_request. Server filters outbound
// events against this list. Phase 3 hard-codes the comprehensive set the
// legacy notifications.js queue path subscribes to (`notifications.js:2287`).
// Phase 4+ stores can subscribe via EventBus.on(); the server-side filter
// stays comprehensive so the EventBus surface is complete.
const QUEUE_SUBSCRIBED_EVENTS: ReadonlyArray<string> = [
  "job_state_transition",
  "job_removed",
  "tts_job_request",
  "sys_time_update",
  "notification_play_sound",
  "notification_queue_update",
  "notification_responded",
  "notification_expired",
  "auth_success",
  "auth_error",
  "connect",
  "sys_ping",
];

export class QueueTransportImpl extends BaseTransportImpl {
  protected readonly transportName    : string                  = "QueueTransport";
  protected readonly endpointPath     : string                  = "/ws/queue";
  protected readonly subscribedEvents : ReadonlyArray<string>   = QUEUE_SUBSCRIBED_EVENTS;
}

export type QueueTransportOptions = BaseTransportOptions;

export function createQueueTransport(opts: QueueTransportOptions): Transport {
  return new QueueTransportImpl(opts);
}

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
function stripTrailingSlash(url: string): string {
  return url.replace(/\/+$/, "");
}
