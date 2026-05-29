/* c8 ignore next */ // tsx phantom-branch artifact on file-header line (TypeScript module-init transpile produces a fake branch on line 1 in c8's source-map view; no actual code on this line — it's a comment).
// Multiplexer Phase 3 — WSChannel.
// Thin per-endpoint WebSocket wrapper. Transport-only: NO page-lifecycle
// attachment (`document.visibilitychange` / `online` / `offline` / `pagehide`
// are owned by boot.ts → ConnectionStateMachine per Claude analysis §2.2).
// NO reconnect orchestration (ConnectionStateMachine owns that). NO JSON
// round-trip in the dispatch path (Claude analysis §2.5 — `onMessage` receives
// the already-parsed envelope; nothing in this module re-stringifies it).
//
// Binary frames (audio chunks) bypass JSON parse and route to `onBinaryMessage`
// (Claude analysis §1.1). Without this branch, `JSON.parse(Blob)` throws and
// the frame is silently dropped — the regression that broke audio TTS playback
// after the original WSChannel facade was introduced (Session 656c8ba2 fix in
// the parent file; carried forward into this port from line one).
//
// Generation tokens: every `start()` bumps a monotonic counter; callbacks
// captured before the bump are dropped silently. This preserves the late-
// callback discipline from the original — straggler `onmessage`/`onclose`
// invocations from a prior socket cannot mutate state that belongs to the
// current connection.

export type WSChannelState = "connecting" | "open" | "closing" | "closed";

export interface WSChannelOptions {
  url             : string;
  protocols?      : string | string[];
  onOpen?         : (e: Event) => void;
  onMessage?      : (envelope: unknown) => void;       // parsed JSON envelope
  onBinaryMessage?: (data: Blob | ArrayBuffer) => void;
  onClose?        : (e: CloseEvent) => void;
  onError?        : (e: Event) => void;
  // Initial generation token. Each `start()` bumps it; tests pass a starting
  // value so they can assert late-callback drops by snapshotting the value
  // before reconnect. Production callers can pass 0.
  generationToken : number;
  // Test injection. Production uses the global WebSocket constructor.
  WebSocketCtor?  : typeof WebSocket;
}

export interface WSChannel {
  start(): void;
  stop(): void;
  send(envelope: unknown): void;
  readonly state: WSChannelState;
  readonly generation: number;   // observable for tests + telemetry
}

class WSChannelImpl implements WSChannel {
  private readonly url             : string;
  private readonly protocols?      : string | string[];
  private readonly onOpen?         : (e: Event) => void;
  private readonly onMessage?      : (envelope: unknown) => void;
  private readonly onBinaryMessage?: (data: Blob | ArrayBuffer) => void;
  private readonly onClose?        : (e: CloseEvent) => void;
  private readonly onError?        : (e: Event) => void;
  private readonly WSCtor          : typeof WebSocket;

  private socket   : WebSocket | null = null;
  private gen      : number;
  private _state   : WSChannelState = "closed";

  constructor(opts: WSChannelOptions) {
    if (typeof opts.url !== "string" || opts.url.length === 0) {
      throw new Error("ws-channel: opts.url is required (non-empty string)");
    }
    this.url             = opts.url;
    this.protocols       = opts.protocols;
    this.onOpen          = opts.onOpen;
    this.onMessage       = opts.onMessage;
    this.onBinaryMessage = opts.onBinaryMessage;
    this.onClose         = opts.onClose;
    this.onError         = opts.onError;
    this.gen             = opts.generationToken;
    this.WSCtor          = opts.WebSocketCtor ?? globalThis.WebSocket;

    if (typeof this.WSCtor !== "function") {
      throw new Error(
        "ws-channel: WebSocket constructor not found (pass opts.WebSocketCtor in non-browser environments)",
      );
    }
  }

  get state(): WSChannelState {
    return this._state;
  }

  get generation(): number {
    return this.gen;
  }

  start(): void {
    // Idempotency: if a socket is already CONNECTING or OPEN, do not create
    // another. The caller (ConnectionStateMachine) is responsible for calling
    // stop() before start() on a reconnect.
    if (this._state === "connecting" || this._state === "open") return;

    // Drop any straggler reference. cleanupSocket nulls handlers + close()s.
    if (this.socket) {
      this.cleanupSocket(this.socket);
      this.socket = null;
    }

    // Bump generation BEFORE handler binding so newly-bound closures capture
    // the post-bump value and prior in-flight callbacks see a stale token.
    this.gen += 1;
    const myGen = this.gen;

    let ws: WebSocket;
    try {
      ws = this.protocols !== undefined
        ? new this.WSCtor(this.url, this.protocols)
        : new this.WSCtor(this.url);
    } catch (err) {
      // Construction itself failed (rare — invalid URL, CSP, etc.). Surface
      // as a synthetic close event to the caller so the state machine can
      // book the failure.
      this._state = "closed";
      if (this.onError) {
        try { this.onError(new Event("error")); } catch { /* swallow consumer */ }
      }
      const reason = err instanceof Error ? err.message : "construction failed";
      const synthetic = makeCloseEvent(1006, reason);
      if (this.onClose) {
        try { this.onClose(synthetic); } catch { /* swallow */ }
      }
      return;
    }

    this.socket = ws;
    this._state = "connecting";

    ws.onopen = (e) => {
      if (myGen !== this.gen) return;
      this._state = "open";
      if (this.onOpen) {
        try { this.onOpen(e); } catch { /* swallow consumer errors */ }
      }
    };

    ws.onmessage = (ev) => {
      if (myGen !== this.gen) return;
      // §1.1 fix: route binary frames before any JSON parse attempt.
      if (ev.data instanceof Blob || ev.data instanceof ArrayBuffer) {
        if (this.onBinaryMessage) {
          try { this.onBinaryMessage(ev.data); } catch { /* swallow */ }
        }
        return;
      }
      if (typeof ev.data !== "string") return;  // ignore exotic frame types
      // §2.5 fix: parse once, hand the parsed envelope to the consumer.
      // Nothing in this module re-stringifies; downstream handlers operate
      // on the object.
      let envelope: unknown;
      try {
        envelope = JSON.parse(ev.data);
      } catch {
        return;  // malformed JSON — drop the frame, channel keeps running
      }
      if (this.onMessage) {
        try { this.onMessage(envelope); } catch { /* swallow */ }
      }
    };

    ws.onerror = (e) => {
      if (myGen !== this.gen) return;
      // RFC 6455 §7.1.4: error MUST precede close. Channel does NOT trigger
      // reconnect from onerror — onclose is the single owner. Caller may
      // observe via onError for telemetry only.
      if (this.onError) {
        try { this.onError(e); } catch { /* swallow */ }
      }
    };

    ws.onclose = (e) => {
      if (myGen !== this.gen) return;
      this._state = "closed";
      if (this.onClose) {
        try { this.onClose(e); } catch { /* swallow */ }
      }
    };
  }

  stop(): void {
    // Bump generation FIRST so any in-flight callback bound to the current
    // socket is dropped before its handler can run.
    this.gen += 1;

    if (this.socket) {
      this._state = "closing";
      this.cleanupSocket(this.socket);
      this.socket = null;
    }
    this._state = "closed";
  }

  send(envelope: unknown): void {
    if (!this.socket || this._state !== "open") {
      throw new Error(`ws-channel: cannot send — channel state is '${this._state}'`);
    }
    const data = typeof envelope === "string" ? envelope : JSON.stringify(envelope);
    this.socket.send(data);
  }

  // Null all four handlers and close(1000) the socket. Releases the renderer's
  // pending-handshake slot per Chromium 255-slot fix discipline.
  private cleanupSocket(oldWs: WebSocket): void {
    oldWs.onopen    = null;
    oldWs.onmessage = null;
    oldWs.onerror   = null;
    oldWs.onclose   = null;
    try {
      oldWs.close(1000, "cleanup");
    } catch { /* already closed/closing */ }
  }
}

export function createWSChannel(opts: WSChannelOptions): WSChannel {
  return new WSChannelImpl(opts);
}

// CloseEvent global is browser-native but absent in Node (without
// `--experimental-websocket`). Provide a duck-typed fallback so tests run
// under tsx --test without polyfilling. Both branches are now covered by
// unit tests: the false branch via the default Node test environment, the
// true branch via the "makeCloseEvent uses native CloseEvent" test which
// polyfills globalThis.CloseEvent before invoking the constructor-failure
// path. Production browsers always hit the true branch.
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line (TypeScript return-type erasure produces a fake branch in c8's source-map view; both real branches inside the body ARE covered — verified via lcov).
function makeCloseEvent(code: number, reason: string): CloseEvent {
  if (typeof CloseEvent !== "undefined") {
    return new CloseEvent("close", { code, reason });
  }
  return { type: "close", code, reason } as unknown as CloseEvent;
}
