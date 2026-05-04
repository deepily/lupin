// Phase 3 unit tests — ClaudeCodeTransport (STUB).
// Per Option C user decision (recorded in 90-execution-log.md Phase 3):
// the file ships with the TS interface and factory entry, but `start(taskId)`
// throws `not implemented` until Phase 4 stores wire the body. These tests
// LOCK that contract so Phase 4's reimplementation will surface as expected
// failures here, prompting the test rewrite alongside the new body.

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../fastapi_app/static/js/multiplexer/shared/EventBus";
import {
  createClaudeCodeTransport,
} from "../../../fastapi_app/static/js/multiplexer/transport/ClaudeCodeTransport";
import type { AuthManager } from "../../../fastapi_app/static/js/multiplexer/auth/AuthManager";

function makeMockAuth(): AuthManager {
  return {
    state    : "ready",
    invalidate: () => { /* no-op */ },
    getToken : async () => ({
      accessToken  : "stub-access-token",
      refreshToken : "stub-refresh-token",
      expiresAt    : Date.now() + 3_600_000,
    }),
  };
}

function makeStub() {
  return createClaudeCodeTransport({
    authManager : makeMockAuth(),
    bus         : createEventBusForTesting(),
    baseUrl     : "ws://localhost:7999",
  });
}

test("factory returns a ClaudeCodeTransport-shaped object", () => {
  const t = makeStub();
  assert.equal(typeof t.start, "function");
  assert.equal(typeof t.stop, "function");
  assert.equal(typeof t.send, "function");
  assert.equal(typeof t.state, "string");
});

test("initial state is `connecting` (placeholder until Phase 4 wires the body)", () => {
  const t = makeStub();
  assert.equal(t.state, "connecting");
});

test("start(taskId) throws `not implemented` per Option C", () => {
  const t = makeStub();
  assert.throws(
    () => t.start("task-abc-123"),
    /not implemented in Phase 3/,
  );
});

test("send() throws `not implemented` per Option C", () => {
  const t = makeStub();
  assert.throws(
    () => t.send({ type: "ping" }),
    /not implemented in Phase 3/,
  );
});

test("stop() is a no-op-but-safe; transitions state to `failed`", () => {
  const t = makeStub();
  t.stop();
  assert.equal(t.state, "failed");
  // Calling stop() again is also safe.
  t.stop();
  assert.equal(t.state, "failed");
});

test("Phase 3 boot.ts MUST NOT auto-start ClaudeCodeTransport — the throw is the gate", () => {
  // Documents the Phase 3 contract: any code path that auto-starts the stub
  // crashes loudly. Phase 4 will replace this body, at which point the test
  // file is rewritten to verify real connection behavior.
  const t = makeStub();
  // Simulate the (incorrect) auto-start scenario.
  assert.throws(
    () => t.start("any-task-id"),
    /boot\.ts must not auto-start/,
  );
});
