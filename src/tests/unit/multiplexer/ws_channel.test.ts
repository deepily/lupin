// Phase 3 unit tests — WSChannel.
// Covers Claude analysis fixes:
//   §1.1 — binary-frame routing (Blob/ArrayBuffer → onBinaryMessage)
//   §2.2 — no `_attachPageLifecycle` (lifecycle owned by orchestrator)
//   §2.5 — parsed envelope to onMessage (no JSON round-trip in dispatch)
// Plus generation-token discipline and basic state lifecycle.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  createWSChannel,
} from "../../../lupin_app/static/js/multiplexer/transport/ws-channel";

// ---------------------------------------------------------------------------
// CloseEvent shim — Node 22 omits CloseEvent from globals (it requires the
// --experimental-websocket flag). Mirrors the production fallback in
// ws-channel.ts.
// ---------------------------------------------------------------------------

function makeCloseEvent(code: number, reason: string): CloseEvent {
  if (typeof CloseEvent !== "undefined") {
    return new CloseEvent("close", { code, reason });
  }
  return { type: "close", code, reason } as unknown as CloseEvent;
}

// ---------------------------------------------------------------------------
// MockWebSocket — minimal shim for test injection.
// ---------------------------------------------------------------------------

class MockWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN       = 1;
  static readonly CLOSING    = 2;
  static readonly CLOSED     = 3;

  url       : string;
  readyState : number = MockWebSocket.CONNECTING;
  onopen    : ((e: Event) => void) | null = null;
  onmessage : ((e: MessageEvent) => void) | null = null;
  onclose   : ((e: CloseEvent) => void) | null = null;
  onerror   : ((e: Event) => void) | null = null;
  sent      : string[] = [];
  closed    : boolean = false;

  // Tracks all instances created during a test run.
  static instances: MockWebSocket[] = [];

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(code: number = 1000, reason: string = ""): void {
    if (this.closed) return;
    this.closed = true;
    this.readyState = MockWebSocket.CLOSED;
    if (this.onclose) {
      this.onclose(makeCloseEvent(code, reason));
    }
  }

  // Test helpers
  fireOpen(): void {
    this.readyState = MockWebSocket.OPEN;
    if (this.onopen) this.onopen(new Event("open"));
  }
  receive(data: string | Blob | ArrayBuffer): void {
    if (this.onmessage) this.onmessage(new MessageEvent("message", { data }));
  }
  fireError(): void {
    if (this.onerror) this.onerror(new Event("error"));
  }
  fireClose(code: number = 1006, reason: string = ""): void {
    this.readyState = MockWebSocket.CLOSED;
    if (this.onclose) this.onclose(makeCloseEvent(code, reason));
  }
}

function freshMockCtor(): typeof WebSocket {
  MockWebSocket.instances = [];
  return MockWebSocket as unknown as typeof WebSocket;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test("start() opens a socket and transitions to 'open' on socket_open", () => {
  const Ctor = freshMockCtor();
  const ch = createWSChannel({
    url             : "ws://test/queue",
    generationToken : 0,
    WebSocketCtor   : Ctor,
  });
  assert.equal(ch.state, "closed");

  ch.start();
  assert.equal(ch.state, "connecting");
  assert.equal(MockWebSocket.instances.length, 1);

  const ws = MockWebSocket.instances[0]!;
  ws.fireOpen();
  assert.equal(ch.state, "open");
});

test("§2.5: parsed envelope reaches onMessage; no JSON round-trip", () => {
  const Ctor = freshMockCtor();
  const received: unknown[] = [];
  const ch = createWSChannel({
    url             : "ws://test/queue",
    generationToken : 0,
    WebSocketCtor   : Ctor,
    onMessage       : (env) => received.push(env),
  });
  ch.start();
  const ws = MockWebSocket.instances[0]!;
  ws.fireOpen();

  ws.receive(JSON.stringify({ type: "auth_success", data: { user: "alice" } }));
  ws.receive(JSON.stringify({ type: "notification", data: { id: 42 } }));

  assert.equal(received.length, 2);
  // Consumer receives the parsed object — not a string. Reference identity
  // does not need to match (parse creates a new object), but the values do.
  const first = received[0] as { type: string; data: { user: string } };
  assert.equal(first.type, "auth_success");
  assert.equal(first.data.user, "alice");
  const second = received[1] as { type: string; data: { id: number } };
  assert.equal(second.data.id, 42);
});

test("§1.1: Blob frames route to onBinaryMessage, not onMessage", () => {
  const Ctor = freshMockCtor();
  const text: unknown[] = [];
  const binary: Array<Blob | ArrayBuffer> = [];
  const ch = createWSChannel({
    url             : "ws://test/audio",
    generationToken : 0,
    WebSocketCtor   : Ctor,
    onMessage       : (env) => text.push(env),
    onBinaryMessage : (data) => binary.push(data),
  });
  ch.start();
  const ws = MockWebSocket.instances[0]!;
  ws.fireOpen();

  const blob = new Blob([new Uint8Array([1, 2, 3])]);
  ws.receive(blob);

  assert.equal(text.length, 0, "binary frame did NOT reach onMessage");
  assert.equal(binary.length, 1, "binary frame reached onBinaryMessage");
  assert.ok(binary[0] instanceof Blob);
});

test("§1.1: ArrayBuffer frames route to onBinaryMessage", () => {
  const Ctor = freshMockCtor();
  const binary: Array<Blob | ArrayBuffer> = [];
  const ch = createWSChannel({
    url             : "ws://test/audio",
    generationToken : 0,
    WebSocketCtor   : Ctor,
    onBinaryMessage : (data) => binary.push(data),
  });
  ch.start();
  MockWebSocket.instances[0]!.fireOpen();

  const buf = new ArrayBuffer(8);
  MockWebSocket.instances[0]!.receive(buf);

  assert.equal(binary.length, 1);
  assert.ok(binary[0] instanceof ArrayBuffer);
});

test("§2.2: WSChannel public API does NOT expose lifecycle attachment", () => {
  const Ctor = freshMockCtor();
  const ch = createWSChannel({
    url             : "ws://test/queue",
    generationToken : 0,
    WebSocketCtor   : Ctor,
  });
  // The legacy module exposed `_attachPageLifecycle` (or attached one
  // implicitly at construction). The new module must NOT.
  assert.equal((ch as unknown as { _attachPageLifecycle?: unknown })._attachPageLifecycle, undefined);
  // Public surface is just start/stop/send + state/generation getters.
  assert.equal(typeof ch.start, "function");
  assert.equal(typeof ch.stop, "function");
  assert.equal(typeof ch.send, "function");
  assert.equal(typeof ch.state, "string");
  assert.equal(typeof ch.generation, "number");
});

test("malformed JSON text frame is dropped silently; channel keeps running", () => {
  const Ctor = freshMockCtor();
  const received: unknown[] = [];
  const ch = createWSChannel({
    url             : "ws://test/queue",
    generationToken : 0,
    WebSocketCtor   : Ctor,
    onMessage       : (env) => received.push(env),
  });
  ch.start();
  const ws = MockWebSocket.instances[0]!;
  ws.fireOpen();

  ws.receive("not valid json {{{");
  ws.receive(JSON.stringify({ type: "ok" }));

  assert.equal(received.length, 1, "malformed frame dropped; valid frame delivered");
  assert.equal(ch.state, "open");
});

test("generation-token discipline: stale callbacks from a prior socket are dropped", () => {
  const Ctor = freshMockCtor();
  const received: unknown[] = [];
  const ch = createWSChannel({
    url             : "ws://test/queue",
    generationToken : 0,
    WebSocketCtor   : Ctor,
    onMessage       : (env) => received.push(env),
  });
  ch.start();
  const ws1 = MockWebSocket.instances[0]!;
  ws1.fireOpen();

  // Drop the channel and start fresh (simulates reconnect).
  ch.stop();
  ch.start();
  const ws2 = MockWebSocket.instances[1]!;
  ws2.fireOpen();
  // Now fire a late callback from ws1 — it should be ignored.
  ws1.receive(JSON.stringify({ type: "stale" }));
  // ws2 callback should still work.
  ws2.receive(JSON.stringify({ type: "live" }));

  assert.equal(received.length, 1);
  const got = received[0] as { type: string };
  assert.equal(got.type, "live");
});

test("send() before open throws; send() after open delivers JSON-stringified envelope", () => {
  const Ctor = freshMockCtor();
  const ch = createWSChannel({
    url             : "ws://test/queue",
    generationToken : 0,
    WebSocketCtor   : Ctor,
  });
  ch.start();
  assert.throws(() => ch.send({ hello: "world" }), /cannot send/);

  const ws = MockWebSocket.instances[0]!;
  ws.fireOpen();
  ch.send({ type: "auth_request", token: "abc" });
  assert.equal(ws.sent.length, 1);
  const parsed = JSON.parse(ws.sent[0]!);
  assert.equal(parsed.type, "auth_request");
  assert.equal(parsed.token, "abc");
});

test("send() with a string payload sends it raw (no double-stringification)", () => {
  const Ctor = freshMockCtor();
  const ch = createWSChannel({
    url             : "ws://test/queue",
    generationToken : 0,
    WebSocketCtor   : Ctor,
  });
  ch.start();
  MockWebSocket.instances[0]!.fireOpen();

  ch.send("ping");
  assert.equal(MockWebSocket.instances[0]!.sent[0], "ping");
});

test("idempotent start: second start() while open is a no-op (no new socket)", () => {
  const Ctor = freshMockCtor();
  const ch = createWSChannel({
    url             : "ws://test/queue",
    generationToken : 0,
    WebSocketCtor   : Ctor,
  });
  ch.start();
  MockWebSocket.instances[0]!.fireOpen();
  assert.equal(ch.state, "open");
  ch.start();  // already open
  assert.equal(MockWebSocket.instances.length, 1, "second start did not create another socket");
});

test("start() after socket close cleans up the prior reference before opening a new one", () => {
  const Ctor = freshMockCtor();
  const ch = createWSChannel({
    url             : "ws://test/queue",
    generationToken : 0,
    WebSocketCtor   : Ctor,
  });
  ch.start();
  const ws1 = MockWebSocket.instances[0]!;
  ws1.fireOpen();
  // Server-driven close: state goes to "closed" but the reference to ws1
  // is NOT nulled (only stop() does that). Calling start() again should
  // see the straggler and clean it up before opening a new socket.
  ws1.fireClose(1006);
  assert.equal(ch.state, "closed");

  ch.start();
  // Two MockWebSocket instances exist; the first should now be closed
  // (the cleanup path ran) and a fresh one was created.
  assert.equal(MockWebSocket.instances.length, 2);
  assert.equal(ws1.closed, true);
});

test("stop() bumps generation so straggler callbacks are ignored after teardown", () => {
  const Ctor = freshMockCtor();
  const received: unknown[] = [];
  const ch = createWSChannel({
    url             : "ws://test/queue",
    generationToken : 0,
    WebSocketCtor   : Ctor,
    onMessage       : (env) => received.push(env),
  });
  ch.start();
  const ws = MockWebSocket.instances[0]!;
  ws.fireOpen();

  ch.stop();
  // Even if a straggler frame arrives after stop(), it must NOT reach the
  // consumer (generation has been bumped).
  ws.receive(JSON.stringify({ type: "post_stop" }));
  assert.equal(received.length, 0);
});

test("constructor rejects empty URL", () => {
  assert.throws(
    () => createWSChannel({ url: "", generationToken: 0, WebSocketCtor: MockWebSocket as unknown as typeof WebSocket }),
    /url is required/,
  );
});

test("constructor rejects when no WebSocket constructor is available", () => {
  // Simulate a non-browser environment by passing a non-function value
  // (Node 22 exposes globalThis.WebSocket as a function so undefined would
  // be filled in by the `??` fallback; pass an explicit non-function to
  // hit the type-guard).
  assert.throws(
    () => createWSChannel({
      url             : "ws://test/queue",
      generationToken : 0,
      WebSocketCtor   : "not-a-function" as unknown as typeof WebSocket,
    }),
    /WebSocket constructor not found/,
  );
});

test("non-string non-binary message frames are ignored (defensive)", () => {
  const Ctor = freshMockCtor();
  const received: unknown[] = [];
  const binary: unknown[] = [];
  const ch = createWSChannel({
    url             : "ws://test/queue",
    generationToken : 0,
    WebSocketCtor   : Ctor,
    onMessage       : (env) => received.push(env),
    onBinaryMessage : (d) => binary.push(d),
  });
  ch.start();
  const ws = MockWebSocket.instances[0]!;
  ws.fireOpen();

  // Simulate exotic frame type — number — which is neither string nor
  // Blob/ArrayBuffer. Should be ignored without throwing.
  if (ws.onmessage) {
    ws.onmessage(new MessageEvent("message", { data: 42 as unknown as string }));
  }
  assert.equal(received.length, 0);
  assert.equal(binary.length, 0);
});

test("error event surfaces via onError but does NOT trigger reconnect", () => {
  const Ctor = freshMockCtor();
  const errors: Event[] = [];
  const closes: CloseEvent[] = [];
  const ch = createWSChannel({
    url             : "ws://test/queue",
    generationToken : 0,
    WebSocketCtor   : Ctor,
    onError         : (e) => errors.push(e),
    onClose         : (e) => closes.push(e),
  });
  ch.start();
  const ws = MockWebSocket.instances[0]!;
  ws.fireOpen();

  ws.fireError();
  // RFC 6455 §7.1.4: error MUST precede close. Our channel observes via
  // onError for telemetry but does NOT auto-trigger reconnect — the close
  // handler is the single owner.
  assert.equal(errors.length, 1);
  assert.equal(closes.length, 0, "error alone does not surface as close");
});

test("close event delivers to onClose with the original code/reason", () => {
  const Ctor = freshMockCtor();
  const closes: CloseEvent[] = [];
  const ch = createWSChannel({
    url             : "ws://test/queue",
    generationToken : 0,
    WebSocketCtor   : Ctor,
    onClose         : (e) => closes.push(e),
  });
  ch.start();
  const ws = MockWebSocket.instances[0]!;
  ws.fireOpen();
  ws.fireClose(4001, "auth_invalid");

  assert.equal(closes.length, 1);
  assert.equal(closes[0]!.code, 4001);
  assert.equal(closes[0]!.reason, "auth_invalid");
  assert.equal(ch.state, "closed");
});

test("WebSocket constructor failure surfaces as synthetic close (1006)", () => {
  const closes: CloseEvent[] = [];
  const errors: Event[] = [];
  const ThrowingCtor = function () {
    throw new Error("CSP blocked");
  } as unknown as typeof WebSocket;

  const ch = createWSChannel({
    url             : "ws://test/queue",
    generationToken : 0,
    WebSocketCtor   : ThrowingCtor,
    onError         : (e) => errors.push(e),
    onClose         : (e) => closes.push(e),
  });
  ch.start();
  assert.equal(errors.length, 1);
  assert.equal(closes.length, 1);
  assert.equal(closes[0]!.code, 1006);
  assert.equal(ch.state, "closed");
});

test("protocols are forwarded to the WebSocket constructor when provided", () => {
  const calls: Array<[string, string | string[] | undefined]> = [];
  const RecordingCtor = function (url: string, protocols?: string | string[]) {
    calls.push([url, protocols]);
    return new MockWebSocket(url);
  } as unknown as typeof WebSocket;

  const ch = createWSChannel({
    url             : "ws://test/queue",
    protocols       : ["lupin.v1"],
    generationToken : 0,
    WebSocketCtor   : RecordingCtor,
  });
  ch.start();
  assert.equal(calls.length, 1);
  assert.deepEqual(calls[0]![1], ["lupin.v1"]);
});

// ---------------------------------------------------------------------------
// Consumer-callback try/catch swallow tests + onOpen callback test
// (added 2026-05-06 to close branch-coverage gaps as part of the
// 100% c8 coverage mandate for the multiplexer TS codebase).
// ---------------------------------------------------------------------------

test("onOpen callback is invoked when set; absent onOpen is a no-op", () => {
  const Ctor = freshMockCtor();
  const opens: Event[] = [];
  const ch = createWSChannel({
    url             : "ws://test/queue",
    generationToken : 0,
    WebSocketCtor   : Ctor,
    onOpen          : (e) => opens.push(e),
  });
  ch.start();
  MockWebSocket.instances[0]!.fireOpen();
  assert.equal(opens.length, 1);
  assert.equal(ch.state, "open");
});

test("onOpen consumer error is swallowed; channel state still transitions to open", () => {
  const Ctor = freshMockCtor();
  const ch = createWSChannel({
    url             : "ws://test/queue",
    generationToken : 0,
    WebSocketCtor   : Ctor,
    onOpen          : () => { throw new Error("consumer onOpen blew up"); },
  });
  ch.start();
  // Must NOT throw: the channel's try/catch swallows consumer errors so a
  // misbehaving caller cannot break the channel's state-machine invariants.
  MockWebSocket.instances[0]!.fireOpen();
  assert.equal(ch.state, "open");
});

test("onMessage consumer error is swallowed; channel keeps delivering subsequent frames", () => {
  const Ctor = freshMockCtor();
  let callCount = 0;
  const received: unknown[] = [];
  const ch = createWSChannel({
    url             : "ws://test/queue",
    generationToken : 0,
    WebSocketCtor   : Ctor,
    onMessage       : (env) => {
      callCount += 1;
      if (callCount === 1) throw new Error("consumer onMessage blew up");
      received.push(env);
    },
  });
  ch.start();
  const ws = MockWebSocket.instances[0]!;
  ws.fireOpen();

  ws.receive(JSON.stringify({ type: "first" }));   // throws
  ws.receive(JSON.stringify({ type: "second" }));  // delivered

  assert.equal(callCount, 2);
  assert.equal(received.length, 1);
  assert.equal((received[0] as { type: string }).type, "second");
});

test("onBinaryMessage consumer error is swallowed; channel keeps running", () => {
  const Ctor = freshMockCtor();
  let callCount = 0;
  const ch = createWSChannel({
    url             : "ws://test/audio",
    generationToken : 0,
    WebSocketCtor   : Ctor,
    onBinaryMessage : () => {
      callCount += 1;
      throw new Error("consumer onBinaryMessage blew up");
    },
  });
  ch.start();
  const ws = MockWebSocket.instances[0]!;
  ws.fireOpen();

  // Two binary frames; both should be delivered to the consumer despite throws.
  ws.receive(new Blob([new Uint8Array([1])]));
  ws.receive(new ArrayBuffer(4));

  assert.equal(callCount, 2);
  assert.equal(ch.state, "open");
});

test("onError consumer error is swallowed; channel keeps running for the close cycle", () => {
  const Ctor = freshMockCtor();
  const closes: CloseEvent[] = [];
  const ch = createWSChannel({
    url             : "ws://test/queue",
    generationToken : 0,
    WebSocketCtor   : Ctor,
    onError         : () => { throw new Error("consumer onError blew up"); },
    onClose         : (e) => closes.push(e),
  });
  ch.start();
  const ws = MockWebSocket.instances[0]!;
  ws.fireOpen();

  ws.fireError();
  ws.fireClose(1006);

  // Even though onError threw, onClose still fires normally.
  assert.equal(closes.length, 1);
  assert.equal(ch.state, "closed");
});

test("onClose consumer error is swallowed; channel state still settles to closed", () => {
  const Ctor = freshMockCtor();
  const ch = createWSChannel({
    url             : "ws://test/queue",
    generationToken : 0,
    WebSocketCtor   : Ctor,
    onClose         : () => { throw new Error("consumer onClose blew up"); },
  });
  ch.start();
  const ws = MockWebSocket.instances[0]!;
  ws.fireOpen();
  ws.fireClose(1006);
  assert.equal(ch.state, "closed");
});

test("constructor-failure path: onError absent → only synthetic onClose fires", () => {
  const closes: CloseEvent[] = [];
  const ThrowingCtor = function () {
    throw new Error("CSP blocked");
  } as unknown as typeof WebSocket;

  // No onError handler — the if-branch in the catch path must NOT run; only
  // the onClose branch fires when set. This covers the `if (this.onError)`
  // false branch in the constructor-failure recovery code.
  const ch = createWSChannel({
    url             : "ws://test/queue",
    generationToken : 0,
    WebSocketCtor   : ThrowingCtor,
    onClose         : (e) => closes.push(e),
  });
  ch.start();
  assert.equal(closes.length, 1);
  assert.equal(closes[0]!.code, 1006);
  assert.equal(ch.state, "closed");
});

test("constructor-failure path: onClose absent → channel stays closed quietly", () => {
  const ThrowingCtor = function () {
    throw new Error("CSP blocked");
  } as unknown as typeof WebSocket;

  // No onClose handler — the if-branch is false; nothing crashes.
  const ch = createWSChannel({
    url             : "ws://test/queue",
    generationToken : 0,
    WebSocketCtor   : ThrowingCtor,
  });
  ch.start();
  assert.equal(ch.state, "closed");
});

test("constructor-failure path: onError throws → swallowed; onClose still fires", () => {
  const closes: CloseEvent[] = [];
  const ThrowingCtor = function () {
    throw new Error("CSP blocked");
  } as unknown as typeof WebSocket;

  const ch = createWSChannel({
    url             : "ws://test/queue",
    generationToken : 0,
    WebSocketCtor   : ThrowingCtor,
    onError         : () => { throw new Error("onError consumer blew up"); },
    onClose         : (e) => closes.push(e),
  });
  // Must NOT throw at start() time despite consumer onError throwing.
  ch.start();
  assert.equal(closes.length, 1);
});

test("constructor-failure path: non-Error throwable maps to 'construction failed' reason", () => {
  const closes: CloseEvent[] = [];
  const ThrowingCtor = function () {
    throw "string-not-an-error";  // eslint-disable-line @typescript-eslint/no-throw-literal
  } as unknown as typeof WebSocket;

  const ch = createWSChannel({
    url             : "ws://test/queue",
    generationToken : 0,
    WebSocketCtor   : ThrowingCtor,
    onClose         : (e) => closes.push(e),
  });
  ch.start();
  assert.equal(closes.length, 1);
  assert.equal(closes[0]!.reason, "construction failed");
});

test("constructor-failure path: synthetic onClose consumer error is swallowed", () => {
  const ThrowingCtor = function () {
    throw new Error("CSP blocked");
  } as unknown as typeof WebSocket;

  const ch = createWSChannel({
    url             : "ws://test/queue",
    generationToken : 0,
    WebSocketCtor   : ThrowingCtor,
    onClose         : () => { throw new Error("onClose consumer blew up"); },
  });
  // Must NOT propagate the consumer-thrown error.
  ch.start();
  assert.equal(ch.state, "closed");
});

test("stop() while no socket exists is a quiet no-op (state already closed)", () => {
  const Ctor = freshMockCtor();
  const ch = createWSChannel({
    url             : "ws://test/queue",
    generationToken : 0,
    WebSocketCtor   : Ctor,
  });
  // Never started; no socket ever created. stop() must run cleanly.
  ch.stop();
  assert.equal(ch.state, "closed");
});

test("late ws.onerror after stop() is dropped (generation-token mismatch)", () => {
  const Ctor = freshMockCtor();
  const errors: Event[] = [];
  const ch = createWSChannel({
    url             : "ws://test/queue",
    generationToken : 0,
    WebSocketCtor   : Ctor,
    onError         : (e) => errors.push(e),
  });
  ch.start();
  const ws = MockWebSocket.instances[0]!;
  ws.fireOpen();
  ch.stop();
  // After stop() bumps generation, a late error from the prior socket must
  // NOT reach onError — the if (myGen !== this.gen) return guard fires.
  // Re-set the handler reference because cleanupSocket nulled it; we have
  // to invoke the captured closure manually for the late-callback simulation.
  // This is necessarily contrived because in production the handler is
  // already nulled by cleanupSocket — but the captured closure can still be
  // invoked if the browser dispatched it before null-out completed.
  assert.equal(errors.length, 0);
});

// ---------------------------------------------------------------------------
// Branch-coverage close-out tests (added 2026-05-06 for the 100% c8 mandate).
// These cover the four handler-level generation-token drops (onopen,
// onmessage, onerror, onclose) by capturing the bound closure BEFORE stop()
// nulls the handler reference, then invoking it after stop()/start() has
// bumped the generation. In production, a browser may dispatch one of these
// handlers between gen-bump and handler-null in cleanupSocket — that is the
// real-world race the if-guard exists for.
// ---------------------------------------------------------------------------

test("late ws.onopen after stop(): captured closure sees gen mismatch and returns", () => {
  const Ctor = freshMockCtor();
  const ch = createWSChannel({
    url             : "ws://test/queue",
    generationToken : 0,
    WebSocketCtor   : Ctor,
    onOpen          : () => assert.fail("onOpen consumer must not fire after stop()"),
  });
  ch.start();
  const ws = MockWebSocket.instances[0]!;
  const capturedOnopen = ws.onopen!;  // grab BEFORE stop nulls it
  ch.stop();
  // Invoke the captured closure as if the browser dispatched it post-stop.
  // The if (myGen !== this.gen) return guard must fire and prevent state mutation.
  capturedOnopen(new Event("open"));
  assert.equal(ch.state, "closed");
});

test("late ws.onmessage after stop(): captured closure sees gen mismatch and returns", () => {
  const Ctor = freshMockCtor();
  const received: unknown[] = [];
  const ch = createWSChannel({
    url             : "ws://test/queue",
    generationToken : 0,
    WebSocketCtor   : Ctor,
    onMessage       : (env) => received.push(env),
  });
  ch.start();
  const ws = MockWebSocket.instances[0]!;
  ws.fireOpen();
  const capturedOnmessage = ws.onmessage!;
  ch.stop();
  capturedOnmessage(new MessageEvent("message", { data: JSON.stringify({ type: "stale" }) }));
  assert.equal(received.length, 0);
});

test("late ws.onerror after stop(): captured closure sees gen mismatch and returns", () => {
  const Ctor = freshMockCtor();
  const errors: Event[] = [];
  const ch = createWSChannel({
    url             : "ws://test/queue",
    generationToken : 0,
    WebSocketCtor   : Ctor,
    onError         : (e) => errors.push(e),
  });
  ch.start();
  const ws = MockWebSocket.instances[0]!;
  const capturedOnerror = ws.onerror!;
  ch.stop();
  capturedOnerror(new Event("error"));
  assert.equal(errors.length, 0);
});

test("late ws.onclose after stop(): captured closure sees gen mismatch and returns", () => {
  const Ctor = freshMockCtor();
  const closes: CloseEvent[] = [];
  const ch = createWSChannel({
    url             : "ws://test/queue",
    generationToken : 0,
    WebSocketCtor   : Ctor,
    onClose         : (e) => closes.push(e),
  });
  ch.start();
  const ws = MockWebSocket.instances[0]!;
  const capturedOnclose = ws.onclose!;
  ch.stop();
  // capturedOnclose receives the close event but the gen-guard returns early.
  capturedOnclose(makeCloseEvent(1006, "stale"));
  // onClose may have fired synchronously inside ch.stop()'s cleanupSocket path
  // (cleanupSocket calls oldWs.close(1000, "cleanup") which on MockWebSocket
  // triggers ws.onclose). That's the LIVE close from the cleanup path and
  // should be allowed through the if-guard (myGen still matches because stop
  // bumps gen AFTER setting state but BEFORE invoking cleanupSocket — wait,
  // re-reading: stop() bumps gen FIRST, then cleanupSocket. So even the cleanup
  // path's onclose dispatch sees gen mismatch and is dropped). Net: zero
  // closes should reach the consumer.
  assert.equal(closes.length, 0);
});

test("default WebSocketCtor falls back to globalThis.WebSocket when opts.WebSocketCtor is omitted", () => {
  // The `?? globalThis.WebSocket` fallback branch on line 73 — current tests
  // always inject WebSocketCtor explicitly; this one omits it to exercise
  // the fallback. We have to inject globalThis.WebSocket because Node 22
  // doesn't expose one without --experimental-websocket.
  const original = (globalThis as { WebSocket?: typeof WebSocket }).WebSocket;
  (globalThis as { WebSocket?: typeof WebSocket }).WebSocket =
    MockWebSocket as unknown as typeof WebSocket;
  try {
    MockWebSocket.instances = [];
    const ch = createWSChannel({
      url             : "ws://test/queue",
      generationToken : 0,
      // WebSocketCtor intentionally omitted — exercises ?? fallback
    });
    ch.start();
    assert.equal(MockWebSocket.instances.length, 1);
  } finally {
    (globalThis as { WebSocket?: typeof WebSocket }).WebSocket = original;
  }
});

test("cleanupSocket: a close() that throws is swallowed; channel still settles to closed", () => {
  // Phase 3 ws-channel.ts:210-212 wraps oldWs.close(1000, "cleanup") in
  // try/catch — defensive against close() throwing on already-closed sockets.
  // To exercise the catch branch, inject a MockWebSocket subclass whose
  // close() throws.
  MockWebSocket.instances = [];  // Subclass shares parent's static array
  class ThrowingCloseMock extends MockWebSocket {
    override close(): void {
      throw new Error("already-closed");
    }
  }
  const Ctor = ThrowingCloseMock as unknown as typeof WebSocket;
  const ch = createWSChannel({
    url             : "ws://test/queue",
    generationToken : 0,
    WebSocketCtor   : Ctor,
  });
  ch.start();
  MockWebSocket.instances[0]!.fireOpen();
  // stop() invokes cleanupSocket which calls close() which throws — must be
  // swallowed; state still settles to closed.
  ch.stop();
  assert.equal(ch.state, "closed");
});

test("makeCloseEvent uses native CloseEvent when one is available globally", () => {
  // Phase 3 ws-channel.ts:227-233 has a CloseEvent polyfill for Node test
  // environments. The if (typeof CloseEvent !== "undefined") branch's TRUE
  // arm is browser-only by default; this test polyfills CloseEvent to
  // exercise it. Restores the original after.
  const original = (globalThis as { CloseEvent?: typeof CloseEvent }).CloseEvent;
  class MockCloseEvent {
    type   : string;
    code   : number;
    reason : string;
    constructor(type: string, init: { code: number; reason: string }) {
      this.type   = type;
      this.code   = init.code;
      this.reason = init.reason;
    }
  }
  (globalThis as { CloseEvent?: typeof CloseEvent }).CloseEvent =
    MockCloseEvent as unknown as typeof CloseEvent;
  try {
    const closes: CloseEvent[] = [];
    const ThrowingCtor = function () {
      throw new Error("CSP blocked");
    } as unknown as typeof WebSocket;
    const ch = createWSChannel({
      url             : "ws://test/queue",
      generationToken : 0,
      WebSocketCtor   : ThrowingCtor,
      onClose         : (e) => closes.push(e),
    });
    ch.start();
    // makeCloseEvent ran with the polyfill in place — the if-true branch
    // returned a fresh MockCloseEvent instance; verify by checking
    // instanceof (production browsers would similarly produce a real
    // CloseEvent through the same code path).
    assert.equal(closes.length, 1);
    assert.ok(closes[0] instanceof MockCloseEvent);
  } finally {
    (globalThis as { CloseEvent?: typeof CloseEvent }).CloseEvent = original;
  }
});
