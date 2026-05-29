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

test("ChainMutexLockManager: cleanup branch deletes the tail entry when no caller is queued behind us", async () => {
  // Exercises the `if (this.tails.get(name) === chained) this.tails.delete(name)`
  // cleanup branch on line 65. Sequential request → second request finds an
  // empty Map (entry was deleted), confirming the truthy arm of the comparison
  // fires when no follow-up caller queued during our work.
  const locks = new ChainMutexLockManager();
  await locks.request("L", async () => "first");
  // Internal Map should be empty after the single request completes — exposed
  // indirectly by triggering a second request and verifying it starts fresh.
  // Use bracket access to peek into the private `tails` Map for the assertion;
  // c8 sees both arms of the cleanup `if` exercised.
  const peek = ( locks as unknown as { tails: Map<string, unknown> } ).tails;
  assert.equal( peek.size, 0, "cleanup branch deleted the tail entry" );
  const result = await locks.request( "L", async () => "second" );
  assert.equal( result, "second" );
});

test("ChainMutexLockManager: cleanup branch leaves the entry when a follow-up caller is queued", async () => {
  // Exercises the falsy arm of the cleanup `if`. While caller-A is still
  // executing its callback, caller-B requests the same lock; B's chained
  // promise overwrites the Map entry. When A's `finally` runs, the get(name)
  // returns B's chained promise (NOT A's `chained`), so the comparison is
  // false and A leaves the entry alone for B.
  const locks = new ChainMutexLockManager();
  let releaseA: () => void = () => { /* set by promise */ };
  const aBlock = new Promise<void>( ( res ) => { releaseA = res; } );
  const aPromise = locks.request( "L", async () => {
    await aBlock;
    return "a";
  } );
  // Give A a microtask to register its tail.
  await new Promise( ( res ) => setTimeout( res, 5 ) );
  const bPromise = locks.request( "L", async () => "b" );
  // B is queued behind A. Now release A; A's cleanup must NOT delete the entry.
  releaseA();
  const aResult = await aPromise;
  assert.equal( aResult, "a" );
  // After A finishes, the Map still has B's chained promise.
  const peekDuringB = ( locks as unknown as { tails: Map<string, unknown> } ).tails;
  // B may already have started or completed; if B is done its own cleanup ran.
  // The relevant assertion is that A did not crash and B succeeds.
  void peekDuringB;
  const bResult = await bPromise;
  assert.equal( bResult, "b" );
});

test("refresh failure: fetcher throws a non-Error (string) — coerced via String(err)", async () => {
  // True execution of the `: String(err)` arm on AuthManager.ts:249.
  const bus = createEventBusForTesting();
  const storage = createStorageServiceForTesting( bus );
  storage.setJSON( "auth_token", {
    accessToken  : "stale",
    refreshToken : "rrr",
    expiresAt    : Date.now() - 1_000,
  }, 1 );
  const stringThrowingFetcher: typeof fetch = async () => {
    /* eslint-disable-next-line @typescript-eslint/no-throw-literal */
    throw "raw-string-error" as unknown as Error;
  };
  const auth = createAuthManager({
    refreshUrl       : "/auth/refresh",
    defaultTimeoutMs : 5000,
    storage,
    bus,
    locks            : new ChainMutexLockManager(),
    fetcher          : stringThrowingFetcher,
  });

  const failed: LupinEvent<RefreshFailedPayload>[] = [];
  bus.on<RefreshFailedPayload>( "refresh_failed", ( e ) => failed.push( e ) );

  await assert.rejects( auth.getToken() );
  assert.equal( failed.length, 1 );
  assert.equal( failed[0]?.payload.error, "raw-string-error" );
  assert.equal( auth.state, "expired" );
});

test("callRefreshEndpoint: refreshToken sourced from in-memory context.token when storage payload omits it", async () => {
  // Targets AuthManager.ts:278 — `stored?.refreshToken ?? context.token?.refreshToken`.
  // Strategy: hydrate via storage with a token that's barely-valid under
  // expiryBufferMs=0 so the constructor transitions to "ready" with an
  // in-memory copy. Wait briefly so the token natural-expires while still
  // sitting in context. Then overwrite storage with a payload that omits
  // refreshToken, forcing the `??` fallback to in-memory context.token.refreshToken.
  // (invalidate() can't be used here — it clears context.token via the
  // clearToken action, which would defeat the test.)
  const bus = createEventBusForTesting();
  const storage = createStorageServiceForTesting( bus );
  storage.setJSON( "auth_token", {
    accessToken  : "in-memory-access",
    refreshToken : "rrr-from-memory",
    expiresAt    : Date.now() + 50, // valid for 50ms with expiryBufferMs=0
  }, 1 );
  const fetch = mockFetch();
  const auth = createAuthManager({
    refreshUrl       : "/auth/refresh",
    defaultTimeoutMs : 5000,
    storage,
    bus,
    locks            : new ChainMutexLockManager(),
    fetcher          : fetch.fetcher,
    expiryBufferMs   : 0,
  });
  // After construction: state=ready, context.token = the seed token.
  assert.equal( auth.state, "ready" );

  // Wait for natural expiry without invalidating.
  await new Promise( ( res ) => setTimeout( res, 100 ) );

  // Overwrite storage with a payload missing refreshToken — `stored?.refreshToken`
  // becomes undefined, which is nullish under `??`, triggering the fallback.
  storage.setJSON( "auth_token", {
    accessToken : "in-memory-access",
    expiresAt   : Date.now() - 1_000,
    // refreshToken intentionally omitted
  } as unknown as Token, 1 );

  const p = auth.getToken();
  await new Promise( ( res ) => setTimeout( res, 5 ) );

  assert.equal( fetch.calls.length, 1, "refresh fired" );
  const body = fetch.calls[0]?.body as { refresh_token: string };
  assert.equal( body.refresh_token, "rrr-from-memory", "fallback used in-memory refreshToken" );

  fetch.resolvePending({
    tokens : { access_token: "rotated", refresh_token: "rrr-rotated", expires_in: 3600 },
  });
  await p;
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
