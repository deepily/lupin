/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// Multiplexer Phase 2 — AuthManager.
// Token storage + refresh-token flow with `navigator.locks` deduplication.
// XState-backed state machine (idle → ready → refreshing → ready | expired)
// per Q6 (XState for high-churn modules). Sync-block contract per DC1:
// getToken() blocks until any in-flight refresh completes; concurrent callers
// queue at the lock; one network round-trip per refresh.

import { createActor, setup, assign } from "xstate";

import { jwtExpiryMs, jwtEmail } from "./jwt";
import type { EventBus } from "../shared/EventBus";
import type { StorageService } from "../shared/StorageService";
import type {
  AuthState,
  AuthStateChangePayload,
  LupinEvent,
  RefreshCompletedPayload,
  RefreshFailedPayload,
  RefreshStartedPayload,
  Token,
} from "../shared/types";

// ---------------------------------------------------------------------------
// LockManager — abstraction over `navigator.locks` so AuthManager can be
// tested in Node where `navigator.locks` is unavailable.
// ---------------------------------------------------------------------------

export interface LockManager {
  request<T>(name: string, callback: () => Promise<T>): Promise<T>;
}

class NavigatorLockManager implements LockManager {
  /* c8 ignore start */
  // Browser-only by design — wraps `navigator.locks` which is a Web API
  // unavailable in Node. Tests use ChainMutexLockManager instead.
  async request<T>(name: string, callback: () => Promise<T>): Promise<T> {
    return navigator.locks.request(name, { mode: "exclusive" }, callback) as Promise<T>;
  }
  /* c8 ignore stop */
}

// Simple promise-chain mutex; works in Node and browser. Exported for tests
// (and as a fallback if `navigator.locks` is somehow unavailable).
export class ChainMutexLockManager implements LockManager {
  private readonly tails = new Map<string, Promise<unknown>>();

  async request<T>(name: string, callback: () => Promise<T>): Promise<T> {
    const prev = this.tails.get(name) ?? Promise.resolve();
    /* c8 ignore next 3 */
    // TS "definitely assigned" placeholder — the Promise constructor below
    // synchronously overwrites `release` before any caller can reach this body.
    let release: () => void = () => { /* unreachable */ };
    const next = new Promise<void>((res) => {
      release = res;
    });
    const chained = prev.then(() => next);
    this.tails.set(name, chained);
    try {
      await prev;
      return await callback();
    } finally {
      release();
      // Drop the entry if no further work is queued behind us. Otherwise the
      // next caller's promise stays in the map.
      if (this.tails.get(name) === chained) this.tails.delete(name);
    }
  }
}

// ---------------------------------------------------------------------------
// XState machine. Pattern: machine TRACKS state (driven by external code that
// owns the lock + fetch); it is not an autonomous actor. This keeps the
// lock-and-double-check sequence in one readable function instead of split
// across actor invocations.
// ---------------------------------------------------------------------------

interface AuthContext {
  token : Token | null;
  error : string | null;
}

type AuthMachineEvent =
  | { type: "REFRESH_START" }
  | { type: "REFRESH_SUCCESS"; token: Token }
  | { type: "REFRESH_FAIL"; error: string }
  | { type: "INVALIDATE" }
  | { type: "READY"; token: Token };

const authMachine = setup({
  types : {
    context : {} as AuthContext,
    events  : {} as AuthMachineEvent,
  },
  actions : {
    setToken : assign({
      /* c8 ignore next 2 */ // defensive: setToken is wired only on READY + REFRESH_SUCCESS transitions in the machine config below; the `: null` arm is unreachable by machine design.
      token : ({ event }) =>
        event.type === "READY" || event.type === "REFRESH_SUCCESS" ? event.token : null,
      error : () => null,
    }),
    setError : assign({
      /* c8 ignore next */ // defensive: setError is wired only on REFRESH_FAIL transition in the machine config below; the `: null` arm is unreachable by machine design.
      error : ({ event }) => (event.type === "REFRESH_FAIL" ? event.error : null),
    }),
    clearToken : assign({
      token : () => null,
    }),
  },
}).createMachine({
  id      : "auth",
  initial : "idle",
  context : { token: null, error: null },
  states  : {
    idle : {
      on : {
        READY         : { target: "ready", actions: "setToken" },
        REFRESH_START : { target: "refreshing" },
      },
    },
    ready : {
      on : {
        INVALIDATE    : { target: "expired", actions: "clearToken" },
        REFRESH_START : { target: "refreshing" },
      },
    },
    refreshing : {
      on : {
        REFRESH_SUCCESS : { target: "ready", actions: "setToken" },
        REFRESH_FAIL    : { target: "expired", actions: ["clearToken", "setError"] },
      },
    },
    expired : {
      on : {
        REFRESH_START : { target: "refreshing" },
        READY         : { target: "ready", actions: "setToken" },
      },
    },
  },
});

// ---------------------------------------------------------------------------
// AuthManager
// ---------------------------------------------------------------------------

export interface AuthManager {
  getToken(): Promise<Token>;
  invalidate(): void;
  // Current-user email from the access-token `email` claim (WP1). Reads the
  // stored token even before hydration; null when no/malformed token present.
  getCurrentUserEmail(): string | null;
  // Test-only state introspection.
  readonly state: AuthState;
}

export interface AuthManagerOptions {
  refreshUrl       : string;             // e.g. "/auth/refresh"
  defaultTimeoutMs : number;             // 10_000 default in production
  storage          : StorageService;
  bus              : EventBus;
  // Test injection. Production code constructs defaults.
  locks?           : LockManager;
  fetcher?         : typeof fetch;
  // Buffer applied to expiresAt when judging "still valid" — refresh slightly
  // before actual expiry to avoid in-flight expiry races. Default 30s.
  expiryBufferMs?  : number;
}

const LOCK_NAME = "lupin-token-refresh";

export class AuthManagerImpl implements AuthManager {
  private readonly refreshUrl       : string;
  private readonly defaultTimeoutMs : number;
  private readonly storage          : StorageService;
  private readonly bus              : EventBus;
  private readonly locks            : LockManager;
  private readonly fetcher          : typeof fetch;
  private readonly expiryBufferMs   : number;
  private readonly actor;

  constructor(opts: AuthManagerOptions) {
    this.refreshUrl       = opts.refreshUrl;
    this.defaultTimeoutMs = opts.defaultTimeoutMs;
    this.storage          = opts.storage;
    this.bus              = opts.bus;
    /* c8 ignore next */ // production-default fallback: NavigatorLockManager wraps the browser-only `navigator.locks` Web API, which is unavailable in Node. Tests always inject ChainMutexLockManager explicitly via opts.locks; this `??` arm fires only in production browsers.
    this.locks            = opts.locks ?? new NavigatorLockManager();
    /* c8 ignore next */ // production-default fallback: globalThis.fetch is the runtime browser fetch; tests always inject a mockFetch via opts.fetcher; this `??` arm fires only in production browsers.
    this.fetcher          = opts.fetcher ?? globalThis.fetch.bind(globalThis);
    this.expiryBufferMs   = opts.expiryBufferMs ?? 30_000;

    this.actor = createActor(authMachine);
    this.actor.subscribe((snapshot) => {
      this.bus.emit<AuthStateChangePayload>({
        type    : "auth_state_change",
        payload : { state: snapshot.value as AuthState },
        source  : "AuthManager",
        ts      : Date.now(),
      });
    });
    this.actor.start();

    // Hydrate from the canonical cross-client token keys on boot. If a valid
    // token sits on disk, jump to "ready" without firing a refresh.
    const stored = this.readStoredToken();
    if (stored && this.isStillValid(stored)) {
      this.actor.send({ type: "READY", token: stored });
    }
  }

  get state(): AuthState {
    return this.actor.getSnapshot().value as AuthState;
  }

  invalidate(): void {
    this.actor.send({ type: "INVALIDATE" });
  }

  getCurrentUserEmail(): string | null {
    // Prefer the in-memory token; fall back to the stored access token. The
    // email claim is stable across refresh, so an expired-but-present token
    // still yields the correct address — usable before hydration completes.
    const accessToken =
      this.actor.getSnapshot().context.token?.accessToken ?? this.storage.getAccessToken();
    if (accessToken === null) return null;
    return jwtEmail(accessToken);
  }

  // Reconstruct a Token from the canonical raw token strings, deriving expiry
  // from the access-token JWT `exp` claim. Returns null unless BOTH tokens are
  // present AND the access token carries a decodable expiry.
  private readStoredToken(): Token | null {
    const accessToken  = this.storage.getAccessToken();
    const refreshToken = this.storage.getRefreshToken();
    if (accessToken === null || refreshToken === null) return null;
    const expiresAt = jwtExpiryMs(accessToken);
    if (expiresAt === null) return null;
    return { accessToken, refreshToken, expiresAt };
  }

  async getToken(): Promise<Token> {
    // Hot path: snapshot the in-memory token; if still valid, return without
    // any lock or fetch.
    const ctx = this.actor.getSnapshot().context;
    if (ctx.token && this.isStillValid(ctx.token)) {
      return ctx.token;
    }

    // Cold path: acquire the refresh lock. Concurrent callers queue here.
    return this.locks.request(LOCK_NAME, async () => {
      // Double-check: a previous lock holder may have just refreshed.
      const after = this.actor.getSnapshot().context;
      if (after.token && this.isStillValid(after.token)) {
        return after.token;
      }
      return this.refreshUnderLock();
    });
  }

  private async refreshUnderLock(): Promise<Token> {
    const reason: RefreshStartedPayload["reason"] =
      this.actor.getSnapshot().value === "expired" ? "invalidated" : "expired";

    this.actor.send({ type: "REFRESH_START" });
    this.bus.emit<RefreshStartedPayload>({
      type    : "refresh_started",
      payload : { reason },
      source  : "AuthManager",
      ts      : Date.now(),
    });

    let token: Token;
    try {
      token = await this.callRefreshEndpoint();
    } catch (err) {
      const errMsg =
        err instanceof Error ? (err.name === "AbortError" ? "timeout" : err.message) : String(err);
      this.actor.send({ type: "REFRESH_FAIL", error: errMsg });
      this.bus.emit<RefreshFailedPayload>({
        type    : "refresh_failed",
        payload : { error: errMsg, willRetry: false },
        source  : "AuthManager",
        ts      : Date.now(),
      });
      throw err;
    }

    this.actor.send({ type: "REFRESH_SUCCESS", token });
    this.storage.setTokens(token.accessToken, token.refreshToken);
    this.bus.emit<RefreshCompletedPayload>({
      type    : "refresh_completed",
      payload : { expiresAt: token.expiresAt },
      source  : "AuthManager",
      ts      : Date.now(),
    });
    return token;
  }

  private async callRefreshEndpoint(): Promise<Token> {
    // Refresh endpoint does NOT take an Authorization header — the body
    // contains the refresh token. AuthManager intentionally does NOT route
    // through ApiClient: ApiClient consumes AuthManager.getToken() and would
    // create a circular dep. Implementation deviation from design §AuthManager
    // captured in execution log Phase 2 Notes.
    const refreshToken =
      this.storage.getRefreshToken() ?? this.actor.getSnapshot().context.token?.refreshToken;
    if (!refreshToken) {
      throw new Error("no refresh token available");
    }

    const timeoutSignal = AbortSignal.timeout(this.defaultTimeoutMs);
    const response = await this.fetcher(this.refreshUrl, {
      method  : "POST",
      headers : { "Content-Type": "application/json" },
      body    : JSON.stringify({ refresh_token: refreshToken }),
      signal  : timeoutSignal,
    });

    if (!response.ok) {
      throw new Error(`refresh failed: HTTP ${response.status}`);
    }

    // Server response shape: { tokens: { access_token, refresh_token, expires_in } }
    const body = (await response.json()) as {
      tokens: { access_token: string; refresh_token: string; expires_in: number };
    };
    // Prefer the access-token JWT `exp` claim (single source of truth, matching
    // hydration); fall back to the `expires_in` field if the token isn't a
    // decodable JWT (e.g. test fixtures / opaque tokens).
    const expiresAt = jwtExpiryMs(body.tokens.access_token) ?? Date.now() + body.tokens.expires_in * 1000;
    return {
      accessToken  : body.tokens.access_token,
      refreshToken : body.tokens.refresh_token,
      expiresAt,
    };
  }

  private isStillValid(token: Token): boolean {
    return token.expiresAt - this.expiryBufferMs > Date.now();
  }
}

// Production singleton is constructed by boot.ts (Phase 3+) since it needs
// both the production storage + bus singletons. No top-level export — boot
// owns the lifecycle.

/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function createAuthManager(opts: AuthManagerOptions): AuthManager {
  return new AuthManagerImpl(opts);
}

// Re-export types consumed by tests / boot.
export type { Token };
export type AuthEvent =
  | LupinEvent<AuthStateChangePayload>
  | LupinEvent<RefreshStartedPayload>
  | LupinEvent<RefreshCompletedPayload>
  | LupinEvent<RefreshFailedPayload>;
