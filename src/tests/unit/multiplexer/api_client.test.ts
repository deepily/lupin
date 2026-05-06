// Phase 2 unit tests — ApiClient.
// Run via `npx tsx --test src/tests/unit/multiplexer/api_client.test.ts`.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  createApiClient,
  ApiError,
} from "../../../fastapi_app/static/js/multiplexer/api/ApiClient";
import type { AuthManager } from "../../../fastapi_app/static/js/multiplexer/auth/AuthManager";
import type { Token } from "../../../fastapi_app/static/js/multiplexer/shared/types";

interface FakeAuthState {
  token        : Token;
  invalidated  : number;
  getTokenCalls: number;
}

function fakeAuthManager(initial?: Partial<Token>): {
  authManager: AuthManager;
  state: FakeAuthState;
} {
  const state: FakeAuthState = {
    token : {
      accessToken  : "test-access",
      refreshToken : "test-refresh",
      expiresAt    : Date.now() + 3_600_000,
      ...initial,
    },
    invalidated  : 0,
    getTokenCalls: 0,
  };
  const authManager: AuthManager = {
    async getToken() {
      state.getTokenCalls++;
      return state.token;
    },
    invalidate() {
      state.invalidated++;
    },
    state : "ready",
  };
  return { authManager, state };
}

interface RecordedRequest {
  url     : string;
  method  : string;
  headers : Record<string, string>;
  body    : unknown;
  signal  : AbortSignal | null;
}

function recordingFetcher(handler: (req: RecordedRequest) => Promise<Response>) {
  const calls: RecordedRequest[] = [];
  const fetcher: typeof fetch = (input, init) => {
    const url = typeof input === "string" ? input : (input as URL).toString();
    const headersObj: Record<string, string> = {};
    if (init?.headers) {
      for (const [k, v] of Object.entries(init.headers as Record<string, string>)) {
        headersObj[k] = v;
      }
    }
    const req: RecordedRequest = {
      url,
      method  : init?.method ?? "GET",
      headers : headersObj,
      body    : init?.body ? JSON.parse(init.body as string) : undefined,
      signal  : (init?.signal as AbortSignal | null) ?? null,
    };
    calls.push(req);
    return handler(req);
  };
  return { fetcher, calls };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

test("get() injects Bearer auth header from AuthManager", async () => {
  const { authManager, state } = fakeAuthManager({ accessToken: "abc123" });
  const { fetcher, calls } = recordingFetcher(async () => jsonResponse({ ok: 1 }));
  const api = createApiClient({
    baseUrl          : "http://localhost:7999",
    defaultTimeoutMs : 5000,
    authManager,
    fetcher,
  });

  const result = await api.get<{ ok: number }>("/api/test");
  assert.deepEqual(result, { ok: 1 });
  assert.equal(calls.length, 1);
  assert.equal(calls[0]?.url, "http://localhost:7999/api/test");
  assert.equal(calls[0]?.headers["Authorization"], "Bearer abc123");
  assert.equal(state.getTokenCalls, 1);
});

test("noAuth=true skips the auth header and AuthManager.getToken", async () => {
  const { authManager, state } = fakeAuthManager();
  const { fetcher, calls } = recordingFetcher(async () => jsonResponse({ ok: 1 }));
  const api = createApiClient({
    baseUrl          : "http://localhost:7999",
    defaultTimeoutMs : 5000,
    authManager,
    fetcher,
  });

  await api.post<{ ok: number }>("/auth/login", { email: "a", password: "b" }, { noAuth: true });
  assert.equal(calls[0]?.headers["Authorization"], undefined);
  assert.equal(state.getTokenCalls, 0);
});

test("post() sends a JSON body and Content-Type: application/json", async () => {
  const { authManager } = fakeAuthManager();
  const { fetcher, calls } = recordingFetcher(async () => jsonResponse({ created: true }));
  const api = createApiClient({
    baseUrl          : "http://localhost:7999",
    defaultTimeoutMs : 5000,
    authManager,
    fetcher,
  });

  await api.post<{ created: boolean }>("/api/things", { name: "abc" });
  assert.equal(calls[0]?.method, "POST");
  assert.equal(calls[0]?.headers["Content-Type"], "application/json");
  assert.deepEqual(calls[0]?.body, { name: "abc" });
});

test("401 response invalidates the auth manager and raises ApiError(401)", async () => {
  const { authManager, state } = fakeAuthManager();
  const { fetcher } = recordingFetcher(async () =>
    new Response("nope", { status: 401 }),
  );
  const api = createApiClient({
    baseUrl          : "http://localhost:7999",
    defaultTimeoutMs : 5000,
    authManager,
    fetcher,
  });

  await assert.rejects(
    api.get<unknown>("/api/secure"),
    (e: unknown) => e instanceof ApiError && e.status === 401,
  );
  assert.equal(state.invalidated, 1);
});

test("non-OK response (e.g. 500) raises ApiError with the status code", async () => {
  const { authManager } = fakeAuthManager();
  const { fetcher } = recordingFetcher(async () =>
    new Response("server boom", { status: 500 }),
  );
  const api = createApiClient({
    baseUrl          : "http://localhost:7999",
    defaultTimeoutMs : 5000,
    authManager,
    fetcher,
  });

  await assert.rejects(
    api.get<unknown>("/api/test"),
    (e: unknown) => e instanceof ApiError && e.status === 500,
  );
});

test("204 No Content returns null without parsing body", async () => {
  const { authManager } = fakeAuthManager();
  const { fetcher } = recordingFetcher(async () => new Response(null, { status: 204 }));
  const api = createApiClient({
    baseUrl          : "http://localhost:7999",
    defaultTimeoutMs : 5000,
    authManager,
    fetcher,
  });

  const result = await api.delete<null>("/api/things/1");
  assert.equal(result, null);
});

test("user-supplied signal aborts in-flight request via AbortSignal.any", async () => {
  const { authManager } = fakeAuthManager();
  const ctrl = new AbortController();
  const { fetcher } = recordingFetcher((req) => {
    return new Promise<Response>((_resolve, reject) => {
      req.signal?.addEventListener("abort", () => {
        const err = new Error("aborted by user");
        err.name = "AbortError";
        reject(err);
      });
    });
  });
  const api = createApiClient({
    baseUrl          : "http://localhost:7999",
    defaultTimeoutMs : 60_000,
    authManager,
    fetcher,
  });

  const promise = api.get<unknown>("/api/test", { signal: ctrl.signal });
  // Abort before the fetcher resolves.
  setTimeout(() => ctrl.abort(), 5);
  await assert.rejects(promise, /aborted by user/);
});

test("timeout signal aborts the request when defaultTimeoutMs elapses", async () => {
  const { authManager } = fakeAuthManager();
  const { fetcher } = recordingFetcher((req) => {
    return new Promise<Response>((_resolve, reject) => {
      req.signal?.addEventListener("abort", () => {
        const err = new Error("aborted");
        err.name = "AbortError";
        reject(err);
      });
    });
  });
  const api = createApiClient({
    baseUrl          : "http://localhost:7999",
    defaultTimeoutMs : 20, // very short
    authManager,
    fetcher,
  });

  await assert.rejects(api.get<unknown>("/api/slow"), /aborted/);
});

test("baseUrl with trailing slash is handled correctly (no double-slash)", async () => {
  const { authManager } = fakeAuthManager();
  const { fetcher, calls } = recordingFetcher(async () => jsonResponse({ ok: 1 }));
  const api = createApiClient({
    baseUrl          : "http://localhost:7999/",
    defaultTimeoutMs : 5000,
    authManager,
    fetcher,
  });

  await api.get<{ ok: number }>("/api/test");
  assert.equal(calls[0]?.url, "http://localhost:7999/api/test");
});

test("baseUrl from LUPIN_API_URL fallback works (test parameterization)", async () => {
  // Mirrors `feedback_tests_parameterize_base_url` — tests must read env var.
  const baseUrl = process.env["LUPIN_API_URL"] ?? "http://localhost:7999";
  const { authManager } = fakeAuthManager();
  const { fetcher, calls } = recordingFetcher(async () => jsonResponse({ ok: 1 }));
  const api = createApiClient({
    baseUrl,
    defaultTimeoutMs : 5000,
    authManager,
    fetcher,
  });

  await api.get<{ ok: number }>("/api/test");
  assert.ok(calls[0]?.url.startsWith(baseUrl));
});

test("absolute URL in path is used verbatim (no baseUrl prefix)", async () => {
  const { authManager } = fakeAuthManager();
  const { fetcher, calls } = recordingFetcher(async () => jsonResponse({ ok: 1 }));
  const api = createApiClient({
    baseUrl          : "http://localhost:7999",
    defaultTimeoutMs : 5000,
    authManager,
    fetcher,
  });

  await api.get<{ ok: number }>("https://elsewhere.test/api/test");
  assert.equal(calls[0]?.url, "https://elsewhere.test/api/test");
});

test("response with NO content-type header returns text (fallback via `?? \"\"`)", async () => {
  // Exercises the `response.headers.get("content-type") ?? ""` fallback when
  // get() returns null. happy-dom's Response auto-sets a default Content-Type,
  // so we hand-build a fetcher that returns a Response-like object with a
  // headers.get() that returns null for "content-type" (and a text() body).
  const { authManager } = fakeAuthManager();
  const fakeResponse = {
    status     : 200,
    ok         : true,
    statusText : "OK",
    headers    : {
      get: ( name: string ): string | null => {
        if ( name.toLowerCase() === "content-type" ) return null; // <-- triggers `?? ""`
        return null;
      },
    },
    text: async (): Promise<string> => "fallback-text-body",
    json: async (): Promise<unknown> => ({ should: "not be called" }),
  };
  const fetcher = ( async () => fakeResponse ) as unknown as typeof fetch;
  const api = createApiClient({
    baseUrl          : "http://localhost:7999",
    defaultTimeoutMs : 5000,
    authManager,
    fetcher,
  });
  const result = await api.get<string>( "/api/notype" );
  assert.equal( result, "fallback-text-body", "no-content-type response routed through text path" );
});

test("response with non-JSON content-type returns text", async () => {
  const { authManager } = fakeAuthManager();
  const { fetcher } = recordingFetcher(async () =>
    new Response("plain text body", {
      status: 200,
      headers: { "Content-Type": "text/plain" },
    }),
  );
  const api = createApiClient({
    baseUrl          : "http://localhost:7999",
    defaultTimeoutMs : 5000,
    authManager,
    fetcher,
  });

  const result = await api.get<string>("/api/text");
  assert.equal(result, "plain text body");
});

test("put() sends a JSON body with PUT method + Content-Type header", async () => {
  const { authManager } = fakeAuthManager();
  const { fetcher, calls } = recordingFetcher(async () => jsonResponse({ updated: true }));
  const api = createApiClient({
    baseUrl          : "http://localhost:7999",
    defaultTimeoutMs : 5000,
    authManager,
    fetcher,
  });

  const result = await api.put<{ updated: boolean }>("/api/things/42", { name: "renamed" });
  assert.deepEqual(result, { updated: true });
  assert.equal(calls[0]?.method, "PUT");
  assert.equal(calls[0]?.headers["Content-Type"], "application/json");
  assert.deepEqual(calls[0]?.body, { name: "renamed" });
});

test("patch() sends a JSON body with PATCH method + Content-Type header", async () => {
  const { authManager } = fakeAuthManager();
  const { fetcher, calls } = recordingFetcher(async () => jsonResponse({ patched: true }));
  const api = createApiClient({
    baseUrl          : "http://localhost:7999",
    defaultTimeoutMs : 5000,
    authManager,
    fetcher,
  });

  const result = await api.patch<{ patched: boolean }>("/api/things/42", { active: false });
  assert.deepEqual(result, { patched: true });
  assert.equal(calls[0]?.method, "PATCH");
  assert.equal(calls[0]?.headers["Content-Type"], "application/json");
  assert.deepEqual(calls[0]?.body, { active: false });
});

test("relative path without leading slash is concatenated with baseUrl + '/' separator", async () => {
  const { authManager } = fakeAuthManager();
  const { fetcher, calls } = recordingFetcher(async () => jsonResponse({ ok: 1 }));
  const api = createApiClient({
    baseUrl          : "http://localhost:7999",
    defaultTimeoutMs : 5000,
    authManager,
    fetcher,
  });

  await api.get<{ ok: number }>("api/relative");
  assert.equal(calls[0]?.url, "http://localhost:7999/api/relative");
});

test("error response whose .text() throws falls back to statusText in ApiError message", async () => {
  const { authManager } = fakeAuthManager();
  // Build a Response whose .text() rejects to exercise the catch branch.
  const errResponse = {
    ok         : false,
    status     : 500,
    statusText : "Internal Server Error",
    headers    : new Headers(),
    text       : async () => {
      throw new Error("body stream broke");
    },
  } as unknown as Response;
  const { fetcher } = recordingFetcher(async () => errResponse);
  const api = createApiClient({
    baseUrl          : "http://localhost:7999",
    defaultTimeoutMs : 5000,
    authManager,
    fetcher,
  });

  await assert.rejects(
    api.get<unknown>("/api/test"),
    (e: unknown) =>
      e instanceof ApiError && e.status === 500 && /Internal Server Error/.test(e.message),
  );
});
