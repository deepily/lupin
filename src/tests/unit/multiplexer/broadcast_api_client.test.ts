// Multiplexer Lane C (v0.1.9 focus-bar parity) — ApiClient.broadcastToCcSessions tests.
// Run via `npx tsx --test src/tests/unit/multiplexer/broadcast_api_client.test.ts`.
//
// Coverage target: the broadcastToCcSessions method added to ApiClient.ts
// (default flag fill + optional broadcast_id branch + typed result passthrough).

import { test } from "node:test";
import assert from "node:assert/strict";

import { createApiClient } from "../../../lupin_app/static/js/multiplexer/api/ApiClient";
import type { BroadcastResult } from "../../../lupin_app/static/js/multiplexer/api/ApiClient";
import type { AuthManager } from "../../../lupin_app/static/js/multiplexer/auth/AuthManager";

function fakeAuthManager(): AuthManager {
  return {
    async getToken() {
      return { accessToken: "tok", refreshToken: "r", expiresAt: Date.now() + 3_600_000 };
    },
    invalidate() { /* no-op */ },
    state : "ready",
  };
}

interface Recorded { url: string; method: string; body: unknown; }

function recordingFetcher(responseBody: unknown): { fetcher: typeof fetch; calls: Recorded[] } {
  const calls: Recorded[] = [];
  const fetcher: typeof fetch = (input, init) => {
    calls.push({
      url    : typeof input === "string" ? input : (input as URL).toString(),
      method : init?.method ?? "GET",
      body   : init?.body ? JSON.parse(init.body as string) : undefined,
    });
    return Promise.resolve(
      new Response(JSON.stringify(responseBody), {
        status  : 200,
        headers : { "content-type": "application/json" },
      }),
    );
  };
  return { fetcher, calls };
}

const RESULT: BroadcastResult = {
  broadcast_id      : "abcdef12-3456-4789-abcd-ef0123456789",
  recipients        : 3,
  failed_recipients : [],
  filtered_out      : [],
  status            : "ok",
};

test("broadcastToCcSessions fills require_ack/include_originator defaults + omits broadcast_id", async () => {
  const { fetcher, calls } = recordingFetcher(RESULT);
  const client = createApiClient({
    baseUrl: "http://localhost:7999", defaultTimeoutMs: 5000, authManager: fakeAuthManager(), fetcher,
  });
  const result = await client.broadcastToCcSessions({ message: "hello fleet" });
  assert.equal(calls.length, 1);
  assert.equal(calls[0]?.url, "http://localhost:7999/api/commons/broadcast-to-cc-sessions");
  assert.equal(calls[0]?.method, "POST");
  assert.deepEqual(calls[0]?.body, {
    message: "hello fleet", require_ack: true, include_originator: true,
  });
  assert.deepEqual(result, RESULT);
});

test("broadcastToCcSessions forwards explicit flags + broadcast_id", async () => {
  const { fetcher, calls } = recordingFetcher(RESULT);
  const client = createApiClient({
    baseUrl: "http://localhost:7999", defaultTimeoutMs: 5000, authManager: fakeAuthManager(), fetcher,
  });
  await client.broadcastToCcSessions({
    message: "scoped", require_ack: false, include_originator: false,
    broadcast_id: "11111111-2222-4333-8444-555566667777",
  });
  assert.deepEqual(calls[0]?.body, {
    message: "scoped", require_ack: false, include_originator: false,
    broadcast_id: "11111111-2222-4333-8444-555566667777",
  });
});
