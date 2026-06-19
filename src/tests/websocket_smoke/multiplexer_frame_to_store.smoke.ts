// Live :7999 WS smoke — proves a REAL server frame reaches a store-layer
// subscriber through the REAL multiplexer client path (WP0 flat-frame fix).
//
// Tiberius/Arnold finding: QueueTransport.onMessage formerly read `env.data`, a
// key the live server NEVER sends (frames are flat `{type, timestamp, ...data}`),
// so every store received `undefined` and the green unit tests were
// synthetic-shaped. This smoke closes that gap end-to-end: it logs in against
// the live dev server, drives the actual QueueTransport + EventBus, and asserts
// the auth_success frame's TOP-LEVEL keys (e.g. undelivered_count) arrive in the
// EventBus payload — exactly what a store reads.
//
// Venue: :7999 (AI-discretionary). Non-destructive (read-only WS subscription).
// NOT a `*.test.ts` (kept out of the unit auto-discovery glob — it needs a live
// server). Run explicitly:
//   npx tsx src/tests/websocket_smoke/multiplexer_frame_to_store.smoke.ts
// Requires: dev server on :7999 + LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL/_PASSWORD.

import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createStorageServiceForTesting } from "../../lupin_app/static/js/multiplexer/shared/StorageService";
import { createAuthManager, ChainMutexLockManager } from "../../lupin_app/static/js/multiplexer/auth/AuthManager";
import { createQueueTransport } from "../../lupin_app/static/js/multiplexer/transport/QueueTransport";
import type { LupinEvent } from "../../lupin_app/static/js/multiplexer/shared/types";

const HTTP_BASE = process.env.LUPIN_API_URL ?? "http://localhost:7999";
const WS_BASE   = HTTP_BASE.replace(/^http/, "ws");

async function login(): Promise<string> {
  const email    = process.env.LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL;
  const password = process.env.LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD;
  if (!email || !password) {
    console.log("SKIP: LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL/_PASSWORD not set");
    process.exit(0);
  }
  const resp = await fetch(`${HTTP_BASE}/auth/login`, {
    method  : "POST",
    headers : { "Content-Type": "application/json" },
    body    : JSON.stringify({ email, password }),
  });
  assert.equal(resp.status, 200, `login failed: HTTP ${resp.status}`);
  const body = (await resp.json()) as { tokens: { access_token: string; refresh_token: string } };
  return body.tokens.access_token;
}

async function main(): Promise<void> {
  const accessToken = await login();

  const bus     = createEventBusForTesting();
  const storage = createStorageServiceForTesting(bus);
  // Seed the canonical keys so AuthManager hydrates to "ready" (the real JWT's
  // exp claim is in the future) and getToken() returns it without a refresh.
  storage.setTokens(accessToken, accessToken);

  const authManager = createAuthManager({
    refreshUrl       : `${HTTP_BASE}/auth/refresh`,
    defaultTimeoutMs : 10_000,
    storage,
    bus,
    locks            : new ChainMutexLockManager(),
  });
  assert.equal(authManager.state, "ready", "AuthManager should hydrate from the live token");

  // A store is just an EventBus subscriber — capture what one would receive.
  const authFrames: LupinEvent<unknown>[] = [];
  bus.on("auth_success", (e) => authFrames.push(e));
  let transportReady = false;
  bus.on("transport_ready", () => { transportReady = true; });

  const transport = createQueueTransport({
    authManager,
    bus,
    baseUrl : WS_BASE,
  });

  const sessionId = `mux-frame-smoke-${process.pid}`;
  transport.start(sessionId);

  // Wait up to 8s for the real auth_success frame to round-trip.
  const deadline = Date.now() + 8_000;
  while (authFrames.length === 0 && Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 100));
  }
  transport.stop();

  assert.ok(transportReady, "transport_ready never emitted (auth handshake failed)");
  assert.equal(authFrames.length >= 1, true, "no auth_success frame reached the EventBus");

  const payload = authFrames[0]?.payload as Record<string, unknown> | undefined;
  // THE PROOF: payload is a populated object (NOT undefined), and the server's
  // TOP-LEVEL flat keys are present — i.e. the flat-frame mapping works against
  // the real server, not just synthetic fixtures.
  assert.ok(payload !== undefined && payload !== null, "payload is undefined — flat-frame mapping is broken");
  assert.equal(typeof payload, "object");
  assert.ok("undelivered_count" in payload, "undelivered_count missing from flat payload");
  assert.equal(typeof payload.undelivered_count, "number", "undelivered_count should be a number");
  assert.ok("session_id" in payload, "session_id missing from flat payload");
  assert.equal("type" in payload, false, "envelope `type` leaked into payload");

  console.log(`PASS: real auth_success frame reached store-layer subscriber. payload=${JSON.stringify(payload)}`);
  process.exit(0);
}

main().catch((err) => {
  console.error(`FAIL: ${err instanceof Error ? err.message : String(err)}`);
  process.exit(1);
});
