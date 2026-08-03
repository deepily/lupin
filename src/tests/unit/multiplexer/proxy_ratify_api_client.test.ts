// Multiplexer B4 (01-D, v0.1.9 CC-session parity) — ApiClient.acknowledgeProxy tests.
// Run via `npx tsx --test src/tests/unit/multiplexer/proxy_ratify_api_client.test.ts`.
//
// Coverage target: the acknowledgeProxy method added to ApiClient.ts — the thin
// wrapper for the proxy-ratify-link's acknowledge call (F-Krishna-BD3 / OSQ-B4.1:
// legacy createProxyRatifyLink POSTs /api/proxy/acknowledge with NO body; the
// page-open is renderer-side, NOT in the apiClient).

import { test } from "node:test";
import assert from "node:assert/strict";

import { createApiClient } from "../../../lupin_app/static/js/multiplexer/api/ApiClient";
import type { ProxyAcknowledgeResult } from "../../../lupin_app/static/js/multiplexer/api/ApiClient";
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

interface Recorded { url: string; method: string; body: unknown; hasAuth: boolean; }

function recordingFetcher(responseBody: unknown): { fetcher: typeof fetch; calls: Recorded[] } {
  const calls: Recorded[] = [];
  const fetcher: typeof fetch = (input, init) => {
    const headers = (init?.headers ?? {}) as Record<string, string>;
    calls.push({
      url     : typeof input === "string" ? input : (input as URL).toString(),
      method  : init?.method ?? "GET",
      body    : init?.body ? JSON.parse(init.body as string) : undefined,
      hasAuth : typeof headers["Authorization"] === "string",
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

// Server shape: decision_proxy.py:72 acknowledge_proxy_batch → { status, retired_batch, new_batch }.
const RESULT: ProxyAcknowledgeResult = {
  status        : "success",
  retired_batch : "pr-1a2b3c4d-7",
  new_batch     : "pr-1a2b3c4d-8",
};

test("acknowledgeProxy POSTs /api/proxy/acknowledge with NO body + auth header + returns typed result", async () => {
  const { fetcher, calls } = recordingFetcher(RESULT);
  const client = createApiClient({
    baseUrl: "http://localhost:7999", defaultTimeoutMs: 5000, authManager: fakeAuthManager(), fetcher,
  });
  const result = await client.acknowledgeProxy();
  assert.equal(calls.length, 1);
  assert.equal(calls[0]?.url, "http://localhost:7999/api/proxy/acknowledge");
  assert.equal(calls[0]?.method, "POST");
  assert.equal(calls[0]?.body, undefined);   // acknowledge is body-less (legacy parity)
  assert.equal(calls[0]?.hasAuth, true);
  assert.deepEqual(result, RESULT);
});
