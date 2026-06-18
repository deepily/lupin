// Phase 3 unit tests — QueueTransport.
// Verifies the auth handshake (auth_request envelope shape, auth_success →
// transport_ready emission), envelope-mapping pass-through (Pass 1 finding
// #15), reconnect orchestration via the embedded ConnectionStateMachine,
// and stop() teardown.

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createQueueTransport,
} from "../../../lupin_app/static/js/multiplexer/transport/QueueTransport";
import type {
  AuthStateChangePayload,
  ConnectionStateChangePayload,
  LupinEvent,
  TransportReadyPayload,
} from "../../../lupin_app/static/js/multiplexer/shared/types";
import type { AuthManager } from "../../../lupin_app/static/js/multiplexer/auth/AuthManager";

// ---------------------------------------------------------------------------
// Test infrastructure
// ---------------------------------------------------------------------------

function makeCloseEvent(code: number, reason: string): CloseEvent {
  if (typeof CloseEvent !== "undefined") {
    return new CloseEvent("close", { code, reason });
  }
  return { type: "close", code, reason } as unknown as CloseEvent;
}

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

  static instances: MockWebSocket[] = [];

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  send(data: string): void { this.sent.push(data); }
  close(code: number = 1000, reason: string = ""): void {
    if (this.closed) return;
    this.closed = true;
    this.readyState = MockWebSocket.CLOSED;
    if (this.onclose) this.onclose(makeCloseEvent(code, reason));
  }

  fireOpen(): void {
    this.readyState = MockWebSocket.OPEN;
    if (this.onopen) this.onopen(new Event("open"));
  }
  fireClose(code: number = 1006, reason: string = ""): void {
    this.readyState = MockWebSocket.CLOSED;
    if (this.onclose) this.onclose(makeCloseEvent(code, reason));
  }
  receive(data: string): void {
    if (this.onmessage) this.onmessage(new MessageEvent("message", { data }));
  }
}

function freshMockCtor(): typeof WebSocket {
  MockWebSocket.instances = [];
  return MockWebSocket as unknown as typeof WebSocket;
}

function makeMockAuth(accessToken: string = "test-access-token", shouldThrow: boolean = false): AuthManager {
  return {
    state    : "ready",
    invalidate: () => { /* no-op */ },
    getToken : async () => {
      if (shouldThrow) throw new Error("auth fetch failed");
      return {
        accessToken,
        refreshToken : "test-refresh-token",
        expiresAt    : Date.now() + 3_600_000,
      };
    },
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test("start() opens WS to /ws/queue/{sessionId}; URL has encoded sessionId", () => {
  const Ctor = freshMockCtor();
  const bus  = createEventBusForTesting();
  const t    = createQueueTransport({
    authManager   : makeMockAuth(),
    bus,
    baseUrl       : "ws://localhost:7999",
    WebSocketCtor : Ctor,
  });

  t.start("wise penguin");  // includes a space — should be URL-encoded.
  assert.equal(MockWebSocket.instances.length, 1);
  assert.equal(MockWebSocket.instances[0]!.url, "ws://localhost:7999/ws/queue/wise%20penguin");
});

test("on socket open: sends correctly-shaped auth_request envelope", async () => {
  const Ctor = freshMockCtor();
  const bus  = createEventBusForTesting();
  const t    = createQueueTransport({
    authManager   : makeMockAuth("test-token-abc"),
    bus,
    baseUrl       : "",
    WebSocketCtor : Ctor,
  });

  t.start("wise_penguin");
  const ws = MockWebSocket.instances[0]!;
  ws.fireOpen();
  // Wait for the async getToken() + send chain.
  await new Promise((r) => setTimeout(r, 10));

  assert.equal(ws.sent.length, 1);
  const env = JSON.parse(ws.sent[0]!);
  assert.equal(env.type, "auth_request");
  assert.equal(env.token, "test-token-abc");
  assert.equal(env.session_id, "wise_penguin");
  assert.ok(Array.isArray(env.subscribed_events));
  assert.ok(env.subscribed_events.includes("auth_success"));
});

test("on auth_success: emits transport_ready with payload.transport=QueueTransport", async () => {
  const Ctor = freshMockCtor();
  const bus  = createEventBusForTesting();
  const ready: LupinEvent<TransportReadyPayload>[] = [];
  bus.on<TransportReadyPayload>("transport_ready", (e) => ready.push(e));

  const t = createQueueTransport({
    authManager   : makeMockAuth(),
    bus,
    baseUrl       : "",
    WebSocketCtor : Ctor,
  });
  t.start("wise_penguin");
  const ws = MockWebSocket.instances[0]!;
  ws.fireOpen();
  await new Promise((r) => setTimeout(r, 10));

  ws.receive(JSON.stringify({ type: "auth_success", data: {} }));

  assert.equal(ready.length, 1);
  assert.equal(ready[0]?.payload.transport, "QueueTransport");
  assert.equal(ready[0]?.source, "QueueTransport");
});

test("envelope mapping (finding #15 REVISED): FLAT server frame → EventBus payload = frame minus type+timestamp", async () => {
  const Ctor = freshMockCtor();
  const bus  = createEventBusForTesting();
  const seen: LupinEvent<unknown>[] = [];
  bus.on("notification_received", (e) => seen.push(e));

  const t = createQueueTransport({
    authManager   : makeMockAuth(),
    bus,
    baseUrl       : "",
    WebSocketCtor : Ctor,
  });
  t.start("wise_penguin");
  const ws = MockWebSocket.instances[0]!;
  ws.fireOpen();
  await new Promise((r) => setTimeout(r, 10));

  // EXACTLY the shape websocket_manager.py emits: { type, timestamp, ...data }.
  // The data keys (id, title) are spread at the TOP level — NOT under `data`.
  ws.receive(JSON.stringify({
    type      : "notification_received",
    timestamp : "2026-06-10T12:00:00Z",
    id        : "notif-1",
    title     : "hello",
  }));

  assert.equal(seen.length, 1);
  assert.equal(seen[0]?.source, "QueueTransport");
  const payload = seen[0]?.payload as { id: string; title: string; type?: unknown; timestamp?: unknown };
  assert.equal(payload.id, "notif-1");
  assert.equal(payload.title, "hello");
  // Envelope keys are stripped — payload is the server `data` dict, nothing more.
  assert.equal(payload.type, undefined, "type must not leak into payload");
  assert.equal(payload.timestamp, undefined, "timestamp must not leak into payload");
});

test("flat-frame mapping: auth_success top-level keys (undelivered_count) reach the payload", async () => {
  // Server sends auth_success FLAT (websocket.py): no `data` wrapper, no
  // `timestamp`. WP15 reads payload.undelivered_count — prove it arrives. This
  // is the contract that lets Lane E drop its server-side `data`-mirror.
  const Ctor = freshMockCtor();
  const bus  = createEventBusForTesting();
  const seen: LupinEvent<unknown>[] = [];
  bus.on("auth_success", (e) => seen.push(e));

  const t = createQueueTransport({
    authManager   : makeMockAuth(),
    bus,
    baseUrl       : "",
    WebSocketCtor : Ctor,
  });
  t.start("wise_penguin");
  const ws = MockWebSocket.instances[0]!;
  ws.fireOpen();
  await new Promise((r) => setTimeout(r, 10));

  ws.receive(JSON.stringify({
    type              : "auth_success",
    user_id           : "u-123",
    session_id        : "wise_penguin",
    undelivered_count : 7,
  }));

  assert.equal(seen.length, 1);
  const payload = seen[0]?.payload as { user_id: string; undelivered_count: number };
  assert.equal(payload.undelivered_count, 7);
  assert.equal(payload.user_id, "u-123");
});

test("transport_ready emits ONCE even on multiple auth_success frames", async () => {
  const Ctor = freshMockCtor();
  const bus  = createEventBusForTesting();
  const ready: LupinEvent<TransportReadyPayload>[] = [];
  bus.on<TransportReadyPayload>("transport_ready", (e) => ready.push(e));

  const t = createQueueTransport({
    authManager   : makeMockAuth(),
    bus,
    baseUrl       : "",
    WebSocketCtor : Ctor,
  });
  t.start("wise_penguin");
  const ws = MockWebSocket.instances[0]!;
  ws.fireOpen();
  await new Promise((r) => setTimeout(r, 10));

  ws.receive(JSON.stringify({ type: "auth_success", data: {} }));
  ws.receive(JSON.stringify({ type: "auth_success", data: {} }));

  assert.equal(ready.length, 1, "transport_ready emitted at most once per session");
});

test("socket_close after auth_success → reconnect via CSM", async () => {
  const Ctor = freshMockCtor();
  const bus  = createEventBusForTesting();
  const transitions: LupinEvent<ConnectionStateChangePayload>[] = [];
  bus.on<ConnectionStateChangePayload>("connection_state_change", (e) => transitions.push(e));

  const t = createQueueTransport({
    authManager   : makeMockAuth(),
    bus,
    baseUrl       : "",
    WebSocketCtor : Ctor,
    graceMs       : 5_000,  // big grace so close < 5s registers as fluke
    maxAttempts   : 5,
  });
  t.start("wise_penguin");
  MockWebSocket.instances[0]!.fireOpen();
  await new Promise((r) => setTimeout(r, 10));
  // auth_success arrives — socket is now CONNECTED on the wire.
  MockWebSocket.instances[0]!.receive(JSON.stringify({ type: "auth_success", data: {} }));
  // Force-close — within grace window → reconnecting.
  MockWebSocket.instances[0]!.fireClose(1006);

  // CSM should have transitioned: connecting → connected → reconnecting → ...
  // a new socket should have opened (driven by the reconnecting state).
  await new Promise((r) => setTimeout(r, 20));
  assert.ok(MockWebSocket.instances.length >= 2, `expected ≥2 sockets, got ${MockWebSocket.instances.length}`);
  // EventBus saw the reconnecting transition.
  const sawReconnecting = transitions.some((e) => e.payload.state === "reconnecting");
  assert.ok(sawReconnecting, "saw reconnecting transition");
});

test("auth getToken() failure → socket stops; CSM enters backoff (attempts incremented)", async () => {
  const Ctor = freshMockCtor();
  const bus  = createEventBusForTesting();
  const transitions: LupinEvent<ConnectionStateChangePayload>[] = [];
  bus.on<ConnectionStateChangePayload>("connection_state_change", (e) => transitions.push(e));

  const t = createQueueTransport({
    authManager   : makeMockAuth("ignored", /* shouldThrow */ true),
    bus,
    baseUrl       : "",
    WebSocketCtor : Ctor,
  });
  t.start("wise_penguin");
  MockWebSocket.instances[0]!.fireOpen();
  await new Promise((r) => setTimeout(r, 10));

  // RECONNECT-PARITY FIX (4450995d): onSocketOpen no longer sends socket_open
  // on TCP open, so the CSM is in `connecting` when the auth getToken() failure
  // path stops the channel → socket_close fires from `connecting` → `backoff`
  // with an attempt increment (NO grace-fluke fast-path, which only applies
  // from `connected`). Auth failures therefore accumulate budget, exactly the
  // behavior the fix restores.
  const sawBackoff = transitions.some((e) => e.payload.state === "backoff");
  assert.ok(sawBackoff, `expected backoff after auth failure; saw ${transitions.map((e) => e.payload.state).join(",")}`);
  assert.equal(t.state, "backoff");
});

test("stop() releases everything; subsequent start() throws", () => {
  const Ctor = freshMockCtor();
  const bus  = createEventBusForTesting();
  const t = createQueueTransport({
    authManager   : makeMockAuth(),
    bus,
    baseUrl       : "",
    WebSocketCtor : Ctor,
  });
  t.start("wise_penguin");
  t.stop();
  // Mock socket should be closed.
  assert.equal(MockWebSocket.instances[0]!.closed, true);
  // Subsequent start throws.
  assert.throws(() => t.start("wise_penguin"), /cannot start a stopped transport/);
});

test("idempotent start: same sessionId is a no-op; different sessionId throws", () => {
  const Ctor = freshMockCtor();
  const bus  = createEventBusForTesting();
  const t = createQueueTransport({
    authManager   : makeMockAuth(),
    bus,
    baseUrl       : "",
    WebSocketCtor : Ctor,
  });
  t.start("wise_penguin");
  t.start("wise_penguin");  // same — no-op
  assert.equal(MockWebSocket.instances.length, 1);

  assert.throws(() => t.start("clever_dolphin"), /already started with a different session/);
});

test("send() before start() throws; after start() forwards to WSChannel", () => {
  const Ctor = freshMockCtor();
  const bus  = createEventBusForTesting();
  const t = createQueueTransport({
    authManager   : makeMockAuth(),
    bus,
    baseUrl       : "",
    WebSocketCtor : Ctor,
  });
  assert.throws(() => t.send({ x: 1 }), /channel is not started/);

  t.start("wise_penguin");
  MockWebSocket.instances[0]!.fireOpen();

  t.send({ ping: 1 });
  // Sent twice: once auth_request (async), once ping (sync). Last entry is the ping.
  // Sequence is async, so let's just check it shows up eventually.
  assert.ok(MockWebSocket.instances[0]!.sent.some((s) => s.includes("ping")));
});

test("baseUrl trailing slashes are stripped", () => {
  const Ctor = freshMockCtor();
  const bus  = createEventBusForTesting();
  const t = createQueueTransport({
    authManager   : makeMockAuth(),
    bus,
    baseUrl       : "ws://localhost:7999///",
    WebSocketCtor : Ctor,
  });
  t.start("wise_penguin");
  assert.equal(MockWebSocket.instances[0]!.url, "ws://localhost:7999/ws/queue/wise_penguin");
});

test("non-string event types from server are ignored (defensive)", async () => {
  const Ctor = freshMockCtor();
  const bus  = createEventBusForTesting();
  const t = createQueueTransport({
    authManager   : makeMockAuth(),
    bus,
    baseUrl       : "",
    WebSocketCtor : Ctor,
  });
  t.start("wise_penguin");
  MockWebSocket.instances[0]!.fireOpen();
  await new Promise((r) => setTimeout(r, 10));
  // auth_success drives the CSM to `connected` (post-fix: connected == authed).
  MockWebSocket.instances[0]!.receive(JSON.stringify({ type: "auth_success", data: {} }));

  // No crash on missing/numeric type.
  MockWebSocket.instances[0]!.receive(JSON.stringify({ data: "no type" }));
  MockWebSocket.instances[0]!.receive(JSON.stringify({ type: 42, data: "numeric type" }));

  assert.equal(t.state, "connected");
});

test("network_offline → CSM enters offline; wsChannel is stopped + cleared", async () => {
  const Ctor = freshMockCtor();
  const bus  = createEventBusForTesting();
  const t = createQueueTransport({
    authManager   : makeMockAuth(),
    bus,
    baseUrl       : "",
    WebSocketCtor : Ctor,
  });
  t.start("wise penguin");
  MockWebSocket.instances[0]!.fireOpen();
  await new Promise((r) => setTimeout(r, 10));

  // Send network_offline via EventBus → wrapper forwards to CSM → CSM
  // transitions to offline → wrapper's onStateChange should stop the
  // wsChannel.
  bus.emit({
    type    : "network_offline",
    payload : { ts: Date.now() },
    source  : "boot",
    ts      : Date.now(),
  });

  assert.equal(t.state, "offline");
  assert.equal(MockWebSocket.instances[0]!.closed, true);
});

test("transport.state before start() returns the pre-CSM default 'connecting'", () => {
  const Ctor = freshMockCtor();
  const bus  = createEventBusForTesting();
  const t = createQueueTransport({
    authManager   : makeMockAuth(),
    bus,
    baseUrl       : "ws://localhost:7999",
    WebSocketCtor : Ctor,
  });
  // Before start(), `this.csm` is null — `state` getter falls back to
  // `?? "connecting"` (covers QueueTransport.ts line ~103).
  assert.equal(t.state, "connecting");
});

test("onMessage drops non-object/null envelopes silently (defensive)", async () => {
  const Ctor = freshMockCtor();
  const bus  = createEventBusForTesting();
  const events: { type: string }[] = [];
  bus.on<unknown>("connect", ( e ) => events.push({ type: e.type }));
  const t = createQueueTransport({
    authManager   : makeMockAuth(),
    bus,
    baseUrl       : "",
    WebSocketCtor : Ctor,
  });
  t.start("wise_penguin");
  MockWebSocket.instances[0]!.fireOpen();
  await new Promise((r) => setTimeout(r, 10));
  // auth_success drives the CSM to `connected` (post-fix: connected == authed).
  MockWebSocket.instances[0]!.receive(JSON.stringify({ type: "auth_success", data: {} }));

  // Wire-level: WSChannel only forwards parsed objects to onMessage, but the
  // BaseTransportImpl onMessage is itself defensive against null / non-object
  // envelopes. We exercise the guard by sending JSON literals that parse to
  // primitives — null, a number, a string. These reach onMessage as their
  // parsed form (null / number / string) and must NOT throw or emit.
  const before = events.length;
  MockWebSocket.instances[0]!.receive("null");          // parses to null
  MockWebSocket.instances[0]!.receive("42");            // parses to number
  MockWebSocket.instances[0]!.receive("\"hello\"");     // parses to string
  // None of those should produce any new emissions.
  assert.equal(events.length, before, "primitive envelopes were dropped without emission");
  assert.equal(t.state, "connected", "transport stayed alive");
});

test("backoff timer eventually fires reconnecting (mock.timers)", async () => {
  const { mock } = await import("node:test");
  mock.timers.enable({ apis: [ "setTimeout" ] });

  try {
    const Ctor = freshMockCtor();
    const bus  = createEventBusForTesting();
    const t = createQueueTransport({
      authManager   : makeMockAuth(),
      bus,
      baseUrl       : "",
      WebSocketCtor : Ctor,
      // Tight grace + plenty of attempts so socket_close after wait → backoff,
      // not reconnecting.
      graceMs       : 1,
      maxAttempts   : 10,
    });
    t.start("wise penguin");
    MockWebSocket.instances[0]!.fireOpen();

    // Allow async getToken to resolve — but mock.timers doesn't intercept
    // microtasks, so the await still works.
    // Drive past the grace window:
    mock.timers.tick(50);

    // Force socket_close → CSM connecting/connected → backoff (since beyond grace)
    MockWebSocket.instances[0]!.fireClose(1006, "test");

    // Backoff timer is scheduled. Advance well past the worst-case 30s cap.
    mock.timers.tick(35_000);

    // The timer should have fired backoff_expire → reconnecting → openSocket
    // creating instance #2.
    assert.ok(
      MockWebSocket.instances.length >= 2,
      `expected ≥2 sockets after backoff timer fires; got ${MockWebSocket.instances.length}`,
    );
  } finally {
    mock.timers.reset();
  }
});

// --- reconnect-parity fix (audit 4450995d) ----------------------------------

test("reconnect-parity: stays `connecting` on TCP open; `connected` only after auth_success", async () => {
  const Ctor = freshMockCtor();
  const bus  = createEventBusForTesting();
  const t = createQueueTransport({
    authManager : makeMockAuth(), bus, baseUrl : "", WebSocketCtor : Ctor,
  });
  t.start("wise_penguin");
  MockWebSocket.instances[0]!.fireOpen();
  await new Promise((r) => setTimeout(r, 10));
  // THE FIX: raw TCP open must NOT reach `connected` (that would reset the
  // reconnect budget before auth — the unbounded-loop bug).
  assert.equal(t.state, "connecting");
  MockWebSocket.instances[0]!.receive(JSON.stringify({ type: "auth_success", data: {} }));
  assert.equal(t.state, "connected");
});

test("reconnect-parity: permanent-auth close (4001) after auth → failed carrying reason/code", async () => {
  const Ctor = freshMockCtor();
  const bus  = createEventBusForTesting();
  const transitions: LupinEvent<ConnectionStateChangePayload>[] = [];
  bus.on<ConnectionStateChangePayload>("connection_state_change", (e) => transitions.push(e));
  const t = createQueueTransport({
    authManager : makeMockAuth(), bus, baseUrl : "", WebSocketCtor : Ctor,
  });
  t.start("wise_penguin");
  MockWebSocket.instances[0]!.fireOpen();
  await new Promise((r) => setTimeout(r, 10));
  MockWebSocket.instances[0]!.receive(JSON.stringify({ type: "auth_success", data: {} }));  // → connected
  MockWebSocket.instances[0]!.fireClose(4001, "token expired");

  assert.equal(t.state, "failed");
  const failed = transitions.find((e) => e.payload.state === "failed");
  assert.equal(failed?.payload.reason, "auth-permanent");
  assert.equal(failed?.payload.code, 4001);
  // Terminal — NO reconnect socket opened.
  assert.equal(MockWebSocket.instances.length, 1);
});

test("reconnect-parity: permanent-auth close during auth phase (4002) → failed", async () => {
  const Ctor = freshMockCtor();
  const bus  = createEventBusForTesting();
  const t = createQueueTransport({
    authManager : makeMockAuth(), bus, baseUrl : "", WebSocketCtor : Ctor,
  });
  t.start("wise_penguin");
  MockWebSocket.instances[0]!.fireOpen();
  await new Promise((r) => setTimeout(r, 10));
  // Still `connecting` (no auth_success yet). A permanent close goes straight
  // to `failed` without spending reconnect budget.
  MockWebSocket.instances[0]!.fireClose(4002, "session displaced");
  assert.equal(t.state, "failed");
});

// Defuse a noisy unused-import warning during type-cast; harmless to runtime.
void ({} as AuthStateChangePayload);
