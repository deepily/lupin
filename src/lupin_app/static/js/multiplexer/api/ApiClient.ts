/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Phase 2 — ApiClient.
// Authenticated fetch wrapper with `AbortSignal.any` for combined timeout +
// manual abort, base-URL parametrization, and 401 → AuthManager.invalidate()
// trampoline. Refresh round-trips are owned by AuthManager itself (avoiding
// circular dep); ApiClient is for "application code that needs an auth header".

import type { AuthManager } from "../auth/AuthManager";

export interface ApiClientOptions {
  baseUrl          : string;     // e.g. process.env.LUPIN_API_URL or window.location.origin
  defaultTimeoutMs : number;     // e.g. 10_000
  authManager      : AuthManager;
  // Test injection.
  fetcher?         : typeof fetch;
}

export interface ApiCallOptions {
  signal?    : AbortSignal;      // user-supplied abort
  timeoutMs? : number;           // override defaultTimeoutMs for this call
  // Skip the Authorization header (used for endpoints like /auth/login).
  noAuth?    : boolean;
}

// ---------------------------------------------------------------------------
// Broadcast-to-all-CC-sessions (Lane C, v0.1.9 focus-bar parity, 2026-06-24).
// Typed shapes for POST /api/commons/broadcast-to-cc-sessions
// (`commons.py:execute_broadcast` → 200 body). `require_ack` /
// `include_originator` default true server-side; the client sends them
// explicitly for legacy parity.
// ---------------------------------------------------------------------------

export interface BroadcastRequest {
  message             : string;
  require_ack?        : boolean;       // default true
  include_originator? : boolean;       // default true
  broadcast_id?       : string;        // omit → server mints a UUIDv4
}

// One `filtered_out` fanout-receipt entry (F3). `reason` ∈ {bridge_unreadable,
// owner_mismatch, stale_bridge_mtime, bridge_vanished, originator_excluded};
// the mtime gate adds age_seconds/threshold_seconds (kept open via index sig).
export interface BroadcastFilteredOut {
  session_id  : string;
  reason      : string;
  [k: string] : unknown;
}

export interface BroadcastResult {
  broadcast_id      : string;
  recipients        : number;                              // count of successful fanouts
  failed_recipients : ReadonlyArray<unknown>;
  filtered_out      : ReadonlyArray<BroadcastFilteredOut>;
  status            : string;
}

export interface ApiClient {
  get<T>(path: string, opts?: ApiCallOptions): Promise<T>;
  post<T>(path: string, body: unknown, opts?: ApiCallOptions): Promise<T>;
  put<T>(path: string, body: unknown, opts?: ApiCallOptions): Promise<T>;
  patch<T>(path: string, body: unknown, opts?: ApiCallOptions): Promise<T>;
  delete<T>(path: string, opts?: ApiCallOptions): Promise<T>;
  /** Fan out a broadcast to the caller's active CC sessions (Lane C). */
  broadcastToCcSessions(req: BroadcastRequest, opts?: ApiCallOptions): Promise<BroadcastResult>;
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly url: string,
    message: string,
  ) {
    super(`HTTP ${status} ${url}: ${message}`);
    this.name = "ApiError";
  }
}

class ApiClientImpl implements ApiClient {
  private readonly baseUrl          : string;
  private readonly defaultTimeoutMs : number;
  private readonly authManager      : AuthManager;
  private readonly fetcher          : typeof fetch;

  constructor(opts: ApiClientOptions) {
    // Strip a trailing slash so callers can write `path` with a leading slash
    // and we never end up with a double `//`.
    this.baseUrl          = opts.baseUrl.replace(/\/+$/, "");
    this.defaultTimeoutMs = opts.defaultTimeoutMs;
    this.authManager      = opts.authManager;
    /* c8 ignore next */ // production-default fallback: globalThis.fetch is the runtime browser fetch; tests always inject a recordingFetcher via opts.fetcher.
    this.fetcher          = opts.fetcher ?? globalThis.fetch.bind(globalThis);
  }

  get<T>(path: string, opts?: ApiCallOptions): Promise<T> {
    return this.request<T>("GET", path, undefined, opts);
  }

  post<T>(path: string, body: unknown, opts?: ApiCallOptions): Promise<T> {
    return this.request<T>("POST", path, body, opts);
  }

  put<T>(path: string, body: unknown, opts?: ApiCallOptions): Promise<T> {
    return this.request<T>("PUT", path, body, opts);
  }

  patch<T>(path: string, body: unknown, opts?: ApiCallOptions): Promise<T> {
    return this.request<T>("PATCH", path, body, opts);
  }

  delete<T>(path: string, opts?: ApiCallOptions): Promise<T> {
    return this.request<T>("DELETE", path, undefined, opts);
  }

  broadcastToCcSessions(req: BroadcastRequest, opts?: ApiCallOptions): Promise<BroadcastResult> {
    const body: Record<string, unknown> = {
      message            : req.message,
      require_ack        : req.require_ack ?? true,
      include_originator : req.include_originator ?? true,
    };
    if (req.broadcast_id !== undefined) body["broadcast_id"] = req.broadcast_id;
    return this.post<BroadcastResult>("/api/commons/broadcast-to-cc-sessions", body, opts);
  }

  private async request<T>(
    method: string,
    path: string,
    body: unknown,
    opts?: ApiCallOptions,
  ): Promise<T> {
    const url = this.buildUrl(path);
    const timeoutMs = opts?.timeoutMs ?? this.defaultTimeoutMs;

    const headers: Record<string, string> = {};
    if (body !== undefined) headers["Content-Type"] = "application/json";

    if (!opts?.noAuth) {
      const token = await this.authManager.getToken();
      headers["Authorization"] = `Bearer ${token.accessToken}`;
    }

    // Manual timeout so we can clear it when the request settles —
    // `AbortSignal.timeout()` keeps the underlying timer alive even after
    // success, which leaks through to long-lived processes and to node:test's
    // lingering-work detection.
    const timeoutCtrl  = new AbortController();
    const timeoutTimer = setTimeout(() => {
      const err = new Error(`request to ${url} timed out after ${timeoutMs}ms`);
      err.name = "AbortError";
      timeoutCtrl.abort(err);
    }, timeoutMs);

    const signal = opts?.signal
      ? AbortSignal.any([opts.signal, timeoutCtrl.signal])
      : timeoutCtrl.signal;

    const init: RequestInit = {
      method,
      headers,
      signal,
    };
    if (body !== undefined) init.body = JSON.stringify(body);

    let response: Response;
    try {
      response = await this.fetcher(url, init);
    } finally {
      clearTimeout(timeoutTimer);
    }

    if (response.status === 401) {
      // Server says token is bad. Mark expired so the next call refreshes.
      this.authManager.invalidate();
      throw new ApiError(401, url, "unauthorized");
    }

    if (!response.ok) {
      let message = response.statusText;
      try {
        message = await response.text();
      } catch {
        /* ignore — keep statusText */
      }
      throw new ApiError(response.status, url, message);
    }

    // Empty body (204 No Content, or zero-length): return null cast.
    if (response.status === 204) return null as T;

    const contentType = response.headers.get("content-type") ?? "";
    if (contentType.includes("application/json")) {
      return (await response.json()) as T;
    }
    return (await response.text()) as T;
  }

  private buildUrl(path: string): string {
    if (path.startsWith("http://") || path.startsWith("https://")) return path;
    return path.startsWith("/")
      ? this.baseUrl + path
      : this.baseUrl + "/" + path;
  }
}

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createApiClient(opts: ApiClientOptions): ApiClient {
  return new ApiClientImpl(opts);
}
