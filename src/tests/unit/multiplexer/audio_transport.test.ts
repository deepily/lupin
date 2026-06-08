// Phase 3 unit tests — AudioTransport.
// Verifies the binary-callback contract per Pass 1 finding #14:
//   - start(sessionId, binaryHandler?) signature accepts optional handler
//   - default handler is the debug-logger
//   - binary frames invoke the handler exactly once
//   - errors thrown by the handler are caught at the call site (transport
//     keeps running)
//   - text envelopes flow through the same payload-mapping rule as Queue.

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createAudioTransport,
} from "../../../lupin_app/static/js/multiplexer/transport/AudioTransport";
import type { AuthManager } from "../../../lupin_app/static/js/multiplexer/auth/AuthManager";
import type { LupinEvent, TransportReadyPayload } from "../../../lupin_app/static/js/multiplexer/shared/types";

// ---------------------------------------------------------------------------
// Test infrastructure (mirrors queue_transport.test.ts shim).
// ---------------------------------------------------------------------------

function makeCloseEvent(code: number, reason: string): CloseEvent {
  if (typeof CloseEvent !== "undefined") return new CloseEvent("close", { code, reason });
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
  receive(data: string | Blob | ArrayBuffer): void {
    if (this.onmessage) this.onmessage(new MessageEvent("message", { data }));
  }
}

function freshMockCtor(): typeof WebSocket {
  MockWebSocket.instances = [];
  return MockWebSocket as unknown as typeof WebSocket;
}

function makeMockAuth(): AuthManager {
  return {
    state    : "ready",
    invalidate: () => { /* no-op */ },
    getToken : async () => ({
      accessToken  : "audio-token",
      refreshToken : "refresh",
      expiresAt    : Date.now() + 3_600_000,
    }),
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test("URL points at /ws/audio/{sessionId}", () => {
  const Ctor = freshMockCtor();
  const t = createAudioTransport({
    authManager   : makeMockAuth(),
    bus           : createEventBusForTesting(),
    baseUrl       : "ws://localhost:7999",
    WebSocketCtor : Ctor,
  });
  t.start("wise_penguin");
  assert.equal(MockWebSocket.instances[0]!.url, "ws://localhost:7999/ws/audio/wise_penguin");
});

test("auth_request envelope carries audio-specific subscribed_events list", async () => {
  const Ctor = freshMockCtor();
  const t = createAudioTransport({
    authManager   : makeMockAuth(),
    bus           : createEventBusForTesting(),
    baseUrl       : "",
    WebSocketCtor : Ctor,
  });
  t.start("wise_penguin");
  MockWebSocket.instances[0]!.fireOpen();
  await new Promise((r) => setTimeout(r, 10));

  const env = JSON.parse(MockWebSocket.instances[0]!.sent[0]!);
  assert.equal(env.type, "auth_request");
  assert.ok(Array.isArray(env.subscribed_events));
  // Audio-specific entries.
  assert.ok(env.subscribed_events.includes("audio_streaming_chunk"));
  assert.ok(env.subscribed_events.includes("audio_streaming_status"));
  assert.ok(env.subscribed_events.includes("audio_streaming_complete"));
  // Should NOT include queue-only entries.
  assert.ok(!env.subscribed_events.includes("job_state_transition"));
});

test("Pass 1 finding #14: binary handler receives Blob frames", async () => {
  const Ctor = freshMockCtor();
  const handled: Array<Blob | ArrayBuffer> = [];
  const t = createAudioTransport({
    authManager   : makeMockAuth(),
    bus           : createEventBusForTesting(),
    baseUrl       : "",
    WebSocketCtor : Ctor,
  });
  t.start("wise_penguin", (data) => handled.push(data));
  MockWebSocket.instances[0]!.fireOpen();
  await new Promise((r) => setTimeout(r, 10));

  const blob = new Blob([new Uint8Array([1, 2, 3, 4])]);
  MockWebSocket.instances[0]!.receive(blob);

  assert.equal(handled.length, 1);
  assert.ok(handled[0] instanceof Blob);
});

test("Pass 1 finding #14: binary handler receives ArrayBuffer frames", async () => {
  const Ctor = freshMockCtor();
  const handled: Array<Blob | ArrayBuffer> = [];
  const t = createAudioTransport({
    authManager   : makeMockAuth(),
    bus           : createEventBusForTesting(),
    baseUrl       : "",
    WebSocketCtor : Ctor,
  });
  t.start("wise_penguin", (data) => handled.push(data));
  MockWebSocket.instances[0]!.fireOpen();
  await new Promise((r) => setTimeout(r, 10));

  const buf = new ArrayBuffer(16);
  MockWebSocket.instances[0]!.receive(buf);

  assert.equal(handled.length, 1);
  assert.ok(handled[0] instanceof ArrayBuffer);
});

test("Pass 1 finding #14: errors thrown in handler are caught; transport survives", async () => {
  const Ctor = freshMockCtor();
  let invocations = 0;
  const t = createAudioTransport({
    authManager   : makeMockAuth(),
    bus           : createEventBusForTesting(),
    baseUrl       : "",
    WebSocketCtor : Ctor,
  });
  t.start("wise_penguin", () => {
    invocations += 1;
    throw new Error("decode failed");
  });
  MockWebSocket.instances[0]!.fireOpen();
  await new Promise((r) => setTimeout(r, 10));

  // Send 3 binary frames — handler throws each time but transport keeps going.
  for (let i = 0; i < 3; i++) {
    MockWebSocket.instances[0]!.receive(new Blob([new Uint8Array([i])]));
  }

  assert.equal(invocations, 3, "all 3 frames invoked the handler");
  assert.equal(t.state, "connected");
});

test("default binary handler is invoked when none is passed", async () => {
  const Ctor = freshMockCtor();
  // Spy on console.debug to verify the default handler runs without
  // installing a custom one.
  const originalDebug = console.debug;
  const calls: unknown[][] = [];
  console.debug = (...args: unknown[]) => { calls.push(args); };

  try {
    const t = createAudioTransport({
      authManager   : makeMockAuth(),
      bus           : createEventBusForTesting(),
      baseUrl       : "",
      WebSocketCtor : Ctor,
    });
    t.start("wise_penguin");  // NO binaryHandler — uses default.
    MockWebSocket.instances[0]!.fireOpen();
    await new Promise((r) => setTimeout(r, 10));

    MockWebSocket.instances[0]!.receive(new Blob([new Uint8Array([0xAB])]));
    assert.ok(calls.some((c) => typeof c[0] === "string" && c[0].includes("Audio chunk")),
      `expected default handler debug log; saw: ${JSON.stringify(calls)}`);
  } finally {
    console.debug = originalDebug;
  }
});

test("text envelopes flow through to EventBus (Pass 1 finding #15 mapping)", async () => {
  const Ctor = freshMockCtor();
  const bus  = createEventBusForTesting();
  const ready: LupinEvent<TransportReadyPayload>[] = [];
  bus.on<TransportReadyPayload>("transport_ready", (e) => ready.push(e));

  const t = createAudioTransport({
    authManager   : makeMockAuth(),
    bus,
    baseUrl       : "",
    WebSocketCtor : Ctor,
  });
  t.start("wise_penguin");
  MockWebSocket.instances[0]!.fireOpen();
  await new Promise((r) => setTimeout(r, 10));

  MockWebSocket.instances[0]!.receive(JSON.stringify({ type: "auth_success", data: {} }));

  assert.equal(ready.length, 1);
  assert.equal(ready[0]?.payload.transport, "AudioTransport");
});
