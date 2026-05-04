// Phase 2 unit tests — AuthManager.
// Run via `npx tsx --test src/tests/unit/multiplexer/auth_manager.test.ts`.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  createAuthManager,
  ChainMutexLockManager,
} from "../../../fastapi_app/static/js/multiplexer/auth/AuthManager";
import {
  createEventBusForTesting,
} from "../../../fastapi_app/static/js/multiplexer/shared/EventBus";
import {
  createStorageServiceForTesting,
} from "../../../fastapi_app/static/js/multiplexer/shared/StorageService";
import type {
  AuthStateChangePayload,
  LupinEvent,
  RefreshFailedPayload,
  RefreshStartedPayload,
  Token,
} from "../../../fastapi_app/static/js/multiplexer/shared/types";

interface FetchCall {
  url      : string;
  body     : unknown;
  resolved : boolean;
}

interface MockFetch {
  fetcher   : typeof fetch;
  calls     : FetchCall[];
  // Pending resolvers — controls when the in-flight refresh request resolves.
  resolvePending : (response: ResponseInit & { tokens: TokensBody }) => void;
  rejectPending  : (err: Error) => void;
  pendingCount   : () => number;
}

interface TokensBody {
  access_token  : string;
  refresh_token : string;
  expires_in    : number;
}

function mockFetch(): MockFetch {
  const calls: FetchCall[] = [];
  const queue: Array<{
    resolve: (r: Response) => void;
    reject: (e: Error) => void;
  }> = [];

  const fetcher: typeof fetch = (input, init) => {
    const url = typeof input === "string" ? input : (input as URL).toString();
    const body = init?.body ? JSON.parse(init.body as string) : undefined;
    const call: FetchCall = { url, body, resolved: false };
    calls.push(call);
    return new Promise<Response>((resolve, reject) => {
      queue.push({
        resolve : (r) => {
          call.resolved = true;
          resolve(r);
        },
        reject,
      });
    });
  };

  return {
    fetcher,
    calls,
    resolvePending : (response) => {
      const next = queue.shift();
      if (!next) throw new Error("no pending fetch to resolve");
      next.resolve(
        new Response(JSON.stringify({ tokens: response.tokens }), {
          status  : response.status ?? 200,
          headers : { "Content-Type": "application/json" },
        }),
      );
    },
    rejectPending : (err) => {
      const next = queue.shift();
      if (!next) throw new Error("no pending fetch to reject");
      next.reject(err);
    },
    pendingCount : () => queue.length,
  };
}

function freshAuthToken(overrides: Partial<TokensBody> = {}): TokensBody {
  return {
    access_token  : "access_" + Math.random().toString(36).slice(2),
    refresh_token : "refresh_" + Math.random().toString(36).slice(2),
    expires_in    : 3600,
    ...overrides,
  };
}

function makeHarness(opts?: { initialToken?: Token }) {
  const bus = createEventBusForTesting();
  const storage = createStorageServiceForTesting(bus);
  if (opts?.initialToken) storage.setJSON("auth_token", opts.initialToken, 1);
  const fetch = mockFetch();
  const auth = createAuthManager({
    refreshUrl       : "/auth/refresh",
    defaultTimeoutMs : 5000,
    storage,
    bus,
    locks            : new ChainMutexLockManager(),
    fetcher          : fetch.fetcher,
  });
  return { bus, storage, fetch, auth };
}

test("getToken returns the cached token immediately if still valid (no fetch)", async () => {
  const validToken: Token = {
    accessToken  : "valid",
    refreshToken : "rrr",
    expiresAt    : Date.now() + 3_600_000,
  };
  const h = makeHarness({ initialToken: validToken });
  const got = await h.auth.getToken();
  assert.equal(got.accessToken, "valid");
  assert.equal(h.fetch.calls.length, 0, "no refresh round-trip on the hot path");
  assert.equal(h.auth.state, "ready");
});

test("getToken triggers a refresh when no token is cached", async () => {
  const h = makeHarness();
  // Without an initial token, getToken should still kick off a refresh — but
  // the AuthManager has no refresh token to send. Expect failure.
  await assert.rejects(h.auth.getToken(), /no refresh token/);
  assert.equal(h.auth.state, "expired");
});

test("getToken refreshes when the cached token is past expiry buffer", async () => {
  const h = makeHarness({
    initialToken : {
      accessToken  : "stale",
      refreshToken : "rrr",
      expiresAt    : Date.now() - 1_000, // already expired
    },
  });

  const tokenPromise = h.auth.getToken();
  // Wait for fetch to be invoked.
  await new Promise((res) => setTimeout(res, 5));
  assert.equal(h.fetch.calls.length, 1);
  const fresh = freshAuthToken({ access_token: "fresh-token" });
  h.fetch.resolvePending({ tokens: fresh });

  const got = await tokenPromise;
  assert.equal(got.accessToken, "fresh-token");
  assert.equal(h.auth.state, "ready");
});

test("AC#5: 5 concurrent getToken calls produce exactly ONE fetch", async () => {
  const h = makeHarness({
    initialToken : {
      accessToken  : "stale",
      refreshToken : "rrr",
      expiresAt    : Date.now() - 1_000,
    },
  });

  const promises = [
    h.auth.getToken(),
    h.auth.getToken(),
    h.auth.getToken(),
    h.auth.getToken(),
    h.auth.getToken(),
  ];

  // Let the lock + fetch fire.
  await new Promise((res) => setTimeout(res, 10));
  assert.equal(h.fetch.calls.length, 1, "only one network round-trip");

  const fresh = freshAuthToken({ access_token: "shared-fresh" });
  h.fetch.resolvePending({ tokens: fresh });

  const tokens = await Promise.all(promises);
  for (const t of tokens) assert.equal(t.accessToken, "shared-fresh");
  assert.equal(h.fetch.calls.length, 1, "still one round-trip after all promises resolved");
});

test("invalidate() transitions state to expired and forces refresh on next getToken", async () => {
  const h = makeHarness({
    initialToken : {
      accessToken  : "valid",
      refreshToken : "rrr",
      expiresAt    : Date.now() + 3_600_000,
    },
  });

  const stateChanges: LupinEvent<AuthStateChangePayload>[] = [];
  h.bus.on<AuthStateChangePayload>("auth_state_change", (e) => stateChanges.push(e));

  // Hot-path access; no fetch.
  await h.auth.getToken();
  assert.equal(h.fetch.calls.length, 0);

  h.auth.invalidate();
  assert.equal(h.auth.state, "expired");

  const promise = h.auth.getToken();
  await new Promise((res) => setTimeout(res, 5));
  assert.equal(h.fetch.calls.length, 1);
  h.fetch.resolvePending({ tokens: freshAuthToken({ access_token: "rotated" }) });
  const fresh = await promise;
  assert.equal(fresh.accessToken, "rotated");

  // Sanity: state machine traversed expired → refreshing → ready.
  const states = stateChanges.map((e) => e.payload.state);
  assert.ok(states.includes("expired"), "transitioned to expired");
  assert.ok(states.includes("refreshing"), "transitioned to refreshing");
  assert.ok(states.includes("ready"), "transitioned back to ready");
});

test("refresh failure: getToken rejects and emits refresh_failed with willRetry=false", async () => {
  const h = makeHarness({
    initialToken : {
      accessToken  : "stale",
      refreshToken : "rrr",
      expiresAt    : Date.now() - 1_000,
    },
  });

  const failed: LupinEvent<RefreshFailedPayload>[] = [];
  h.bus.on<RefreshFailedPayload>("refresh_failed", (e) => failed.push(e));

  const promise = h.auth.getToken();
  await new Promise((res) => setTimeout(res, 5));
  h.fetch.rejectPending(new Error("network is down"));

  await assert.rejects(promise, /network is down/);
  assert.equal(failed.length, 1);
  assert.match(failed[0]?.payload.error ?? "", /network is down/);
  assert.equal(failed[0]?.payload.willRetry, false);
  assert.equal(h.auth.state, "expired");
});

test("refresh timeout surfaces as AbortError (mapped to error: 'timeout')", async () => {
  const h = makeHarness({
    initialToken : {
      accessToken  : "stale",
      refreshToken : "rrr",
      expiresAt    : Date.now() - 1_000,
    },
  });

  const failed: LupinEvent<RefreshFailedPayload>[] = [];
  h.bus.on<RefreshFailedPayload>("refresh_failed", (e) => failed.push(e));

  // Simulate AbortSignal.timeout firing.
  const promise = h.auth.getToken();
  await new Promise((res) => setTimeout(res, 5));
  const abortErr = new Error("aborted");
  abortErr.name = "AbortError";
  h.fetch.rejectPending(abortErr);

  await assert.rejects(promise);
  assert.equal(failed.length, 1);
  assert.equal(failed[0]?.payload.error, "timeout");
});

test("refresh_started emission carries reason='expired' on stale-token path", async () => {
  const h = makeHarness({
    initialToken : {
      accessToken  : "stale",
      refreshToken : "rrr",
      expiresAt    : Date.now() - 1_000,
    },
  });

  const started: LupinEvent<RefreshStartedPayload>[] = [];
  h.bus.on<RefreshStartedPayload>("refresh_started", (e) => started.push(e));

  const promise = h.auth.getToken();
  await new Promise((res) => setTimeout(res, 5));
  h.fetch.resolvePending({ tokens: freshAuthToken() });
  await promise;

  assert.equal(started.length, 1);
  assert.equal(started[0]?.payload.reason, "expired");
});

test("refresh_started emission carries reason='invalidated' after explicit invalidate()", async () => {
  const h = makeHarness({
    initialToken : {
      accessToken  : "valid",
      refreshToken : "rrr",
      expiresAt    : Date.now() + 3_600_000,
    },
  });

  // Warm up the hot path — sets state to ready.
  await h.auth.getToken();
  h.auth.invalidate();

  const started: LupinEvent<RefreshStartedPayload>[] = [];
  h.bus.on<RefreshStartedPayload>("refresh_started", (e) => started.push(e));

  const promise = h.auth.getToken();
  await new Promise((res) => setTimeout(res, 5));
  h.fetch.resolvePending({ tokens: freshAuthToken() });
  await promise;

  assert.equal(started.length, 1);
  assert.equal(started[0]?.payload.reason, "invalidated");
});

test("subsequent concurrent caller arriving AFTER fetch starts does not trigger another fetch", async () => {
  const h = makeHarness({
    initialToken : {
      accessToken  : "stale",
      refreshToken : "rrr",
      expiresAt    : Date.now() - 1_000,
    },
  });

  const first = h.auth.getToken();
  await new Promise((res) => setTimeout(res, 5));
  assert.equal(h.fetch.calls.length, 1);

  // Second caller arrives mid-flight.
  const second = h.auth.getToken();
  await new Promise((res) => setTimeout(res, 5));
  assert.equal(h.fetch.calls.length, 1, "still one round-trip");

  h.fetch.resolvePending({ tokens: freshAuthToken({ access_token: "rotated" }) });
  const [a, b] = await Promise.all([first, second]);
  assert.equal(a.accessToken, "rotated");
  assert.equal(b.accessToken, "rotated");
});

test("refresh endpoint returning 5xx raises a refresh failure (HTTP-status path)", async () => {
  const h = makeHarness({
    initialToken : {
      accessToken  : "stale",
      refreshToken : "rrr",
      expiresAt    : Date.now() - 1_000,
    },
  });

  const failed: LupinEvent<RefreshFailedPayload>[] = [];
  h.bus.on<RefreshFailedPayload>("refresh_failed", (e) => failed.push(e));

  const promise = h.auth.getToken();
  await new Promise((res) => setTimeout(res, 5));
  // Resolve the pending fetch with a 500 instead of a successful token body.
  h.fetch.resolvePending({
    tokens : { access_token: "x", refresh_token: "y", expires_in: 0 },
    status : 500,
  });

  await assert.rejects(promise, /HTTP 500|refresh failed/);
  assert.equal(failed.length, 1);
  assert.match(failed[0]?.payload.error ?? "", /HTTP 500|refresh failed/);
  assert.equal(h.auth.state, "expired");
});

test("fresh token from refresh is persisted to storage", async () => {
  const h = makeHarness({
    initialToken : {
      accessToken  : "stale",
      refreshToken : "rrr",
      expiresAt    : Date.now() - 1_000,
    },
  });

  const promise = h.auth.getToken();
  await new Promise((res) => setTimeout(res, 5));
  h.fetch.resolvePending({
    tokens : { access_token: "persisted", refresh_token: "new-r", expires_in: 1800 },
  });
  await promise;

  const stored = h.storage.getJSON<Token>("auth_token", 1);
  assert.equal(stored?.accessToken, "persisted");
  assert.equal(stored?.refreshToken, "new-r");
});
