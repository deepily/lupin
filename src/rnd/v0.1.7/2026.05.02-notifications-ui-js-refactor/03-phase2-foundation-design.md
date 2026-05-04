# Phase 2 Design — Multiplexer Foundation Services

**Date**: 2026-05-04
**Status**: DRAFT — spine-bundle member; pending bundled plan-review pass + user approval (per Q10 amendment in `01-phase0-decisions.md`)
**Phase**: 2 of 9 (per `01-execution-plan.md` §"Phase plan")
**Predecessors**: `00-synthesis-and-roadmap.md`, `01-execution-plan.md`, `01-phase0-decisions.md`, `02-phase1-scaffolding-design.md`
**Bundle siblings**: `02-phase1-scaffolding-design.md` (toolchain) + `04-phase3-transport-design.md` (transport — input consumer of this phase's contracts)
**Companion**: `90-execution-log.md` Phase 2 section (opens after spine-bundle approval)

---

## Approval coupling — spine bundle (Phases 1-3)

This design doc is a member of the **spine bundle** per Q10 amendment 2026-05-04. It does NOT land alone — it ships alongside `02-phase1-scaffolding-design.md` (Phase 1 toolchain) and `04-phase3-transport-design.md` (Phase 3 transport) as a single plan-review pass + single user approval gate.

Why bundled: this phase's service contracts (AuthManager refresh callback, EventBus event shape, ApiClient base-URL config) are direct inputs to Phase 3 transport-wrapper interfaces. Reviewing them as a unit catches cross-phase contract gaps that serial single-phase reviews would miss. Phase 1 toolchain decisions (TS strictness + ESLint rules) constrain how these services are written.

Within the bundle, **implementation cadence stays per-phase**: Phase 1 implementation completes (multiplexer route serves "hello", build artifact produced) before Phase 2 code starts. Phase 2 finishes (all services unit-tested in isolation) before Phase 3 code starts.

## Plan-review pointer — canonical PIP machinery

Per Q11 amendment 2026-05-04: review machinery is the canonical `planning-is-prompting/workflow/plan-review.md`. The slot table for the spine bundle is in `02-phase1-scaffolding-design.md` (single bundle = single slot fill = single review pass with `{{PLAN_DOC_PATHS}}` listing all three design docs). No separate slot fill for this phase alone.

---

## Context

Phase 2 builds the **foundation services layer** — five modules that every later phase consumes. Each is small (50-200 lines TS), independently unit-testable, and frozen in its public API at the end of Phase 2 so that Phase 3+ can rely on stable contracts.

The five services:

| Module | Purpose | XState? |
|---|---|---|
| `AuthManager` | Token storage, refresh-token flow with `navigator.locks` dedup, expiry tracking | Yes (per Q6 — high-churn) |
| `ApiClient` | Authenticated HTTP wrapper with `AbortSignal.any` for timeout + manual abort | No |
| `StorageService` | Typed JSON wrapper around `localStorage` with key prefixes + schema versioning | No |
| `EventBus` | `EventTarget` instance for cross-module pub/sub; typed listener helper | No |
| `BroadcastChannel("lupin")` wrapper | Cross-tab event replication for selected EventBus events | No |

This phase ships **no UI**, **no transport**, **no domain stores**. The output is a tested foundation that Phase 3 (transport) and Phase 4 (stores) build on.

## Strategic posture (recap)

Per `00-synthesis-and-roadmap.md` §1: parallel greenfield rebuild. Foundation services are written in TypeScript strict mode (per Q4) under `src/fastapi_app/static/js/multiplexer/` per the directory layout (Q2). All services follow a "no-globals" rule (per Phase 1 ESLint config); inter-module communication is exclusively via EventBus + BroadcastChannel.

## Out of scope for Phase 2

- Any UI rendering (Phase 5 + 6)
- Any WebSocket transport — `AuthManager` does NOT subscribe to WS events; that's Phase 3 transport responsibility
- Any domain stores (Phase 4)
- Token-storage migration off `localStorage` to HttpOnly cookies — out of scope for the entire multiplexer rebuild per Q7
- Service Worker / offline outbox per Q8
- Observability (Phase 7)
- Any CSP / Trusted Types enforcement (Phase 7)

## Files created / edited

| Path | Change | Owner | Rationale |
|---|---|---|---|
| `src/fastapi_app/static/js/multiplexer/auth/AuthManager.ts` | NEW | Lupin | Refresh-token deduplication via `navigator.locks.request("lupin-token-refresh", …)`; XState actor (idle → refreshing → ready → expired); fail-soft on refresh error with explicit event emission |
| `src/fastapi_app/static/js/multiplexer/api/ApiClient.ts` | NEW | Lupin | Authenticated `fetch` wrapper; `AbortSignal.any([timeoutSignal, manualAbortSignal])` on every call; auth-header injection via `AuthManager`; `LUPIN_API_URL`-aware base URL |
| `src/fastapi_app/static/js/multiplexer/shared/StorageService.ts` | NEW | Lupin | Typed JSON helpers (`getJSON<T>`, `setJSON<T>`); key prefix `lupin:`; schema-version field on every payload; corrupt-payload recovery (return `null` + emit event, don't throw) |
| `src/fastapi_app/static/js/multiplexer/shared/EventBus.ts` | NEW | Lupin | Single `EventTarget` instance; typed `on(event, listener)` / `off` / `emit(event, payload)`; event-shape contract: `{type, payload, source, ts}` |
| `src/fastapi_app/static/js/multiplexer/shared/broadcast.ts` | NEW | Lupin | `BroadcastChannel("lupin")` wrapper; subscribes to a configurable EventBus event whitelist and re-emits across tabs; receives cross-tab events and emits them on the local EventBus with a `source: "broadcast"` marker to prevent loops |
| `src/fastapi_app/static/js/multiplexer/shared/types.ts` | NEW | Lupin | Shared TypeScript interfaces — `LupinEvent`, `AuthState`, `Token`, `StorageEnvelope<T>`, etc. |
| `src/tests/unit/multiplexer/auth_manager.test.ts` | NEW | Lupin | Unit tests covering navigator.locks dedup, refresh state machine transitions, expiry detection, fail-soft on refresh error |
| `src/tests/unit/multiplexer/api_client.test.ts` | NEW | Lupin | Unit tests covering auth-header injection, `AbortSignal.any` timeout + manual abort, base-URL parametrization (`LUPIN_API_URL`) |
| `src/tests/unit/multiplexer/storage_service.test.ts` | NEW | Lupin | Unit tests covering schema-version round-trip, corrupt-payload recovery, key-prefix isolation |
| `src/tests/unit/multiplexer/event_bus.test.ts` | NEW | Lupin | Unit tests covering subscribe/emit/unsubscribe, event-shape contract, listener error isolation (one listener throwing doesn't break others) |
| `src/tests/unit/multiplexer/broadcast.test.ts` | NEW | Lupin | Unit tests covering whitelist filtering, loop prevention via `source: "broadcast"` marker, receive-side re-emission |

**No CoSA edits**: All files under `src/fastapi_app/static/js/multiplexer/` and `src/tests/unit/multiplexer/`. Per `feedback_lupin_only_never_cosa`.

## Service contracts (the inputs to Phase 3)

These public APIs are what Phase 3 transport wrappers consume. They MUST stay stable across the spine bundle review and Phase 2 implementation; if review surfaces a contract change, it ripples into Phase 3 design.

### AuthManager (DC1 resolution: sync block + EventBus observability — 2026-05-04)

```ts
export interface Token {
  accessToken: string;
  refreshToken: string;
  expiresAt: number;  // ms epoch
}

export interface AuthManager {
  getToken(): Promise<Token>;        // BLOCKS until any in-flight refresh completes; returns valid token or throws
  invalidate(): void;                // mark token as expired (e.g., on 401); next getToken() will refresh
  on(event: AuthEventType, listener: (e: LupinEvent) => void): () => void;
}

export type AuthEventType =
  | "ready"               // valid token available
  | "expired"             // refresh failed; user must re-authenticate
  | "refresh_started"     // refresh round-trip began
  | "refresh_completed"   // refresh succeeded; new token cached
  | "refresh_failed";     // refresh round-trip failed (network, 401 from refresh endpoint, etc.)
```

**Blocking semantics (DC1 resolution)**:
- `getToken()` returns `Promise<Token>` that **blocks until any in-flight refresh completes**. Two paths:
  - **Cached token still valid** → returns immediately with cached token (the 99%+ hot path)
  - **Cached token expired or near-expiry** → acquires `navigator.locks.request("lupin-token-refresh", { mode: "exclusive" }, async () => { … })`, performs the refresh round-trip, releases the lock, returns the freshly-refreshed token
- **Concurrent callers during refresh**: queue at the lock automatically. Lock primitive serializes; only ONE network round-trip ever fires per refresh; all queued callers receive the same fresh token. No thundering herd, no caller-side dedup needed.
- **Refresh failure**: `getToken()` throws (caller decides retry / sign-out policy); the promise rejection is the failure signal for the *caller*. UI / telemetry observes the parallel `refresh_failed` event.

**Why blocking, not optimistic-return** (resolved DC1 from REUSE pre-pass; full pros/cons in `~/.claude/plans/vectorized-bubbling-plum.md`):
- `navigator.locks` is the right primitive for sync block — concurrent callers queue for free.
- Statistically, refresh fires only on the rare expired-token path; latency cost is one round trip, paid once per token lifetime. Optimistic-return-then-retry-on-401 costs *two* round trips on the same path.
- WebSocket auth handshake is the killer use case: optimistic-stale-token → server rejects → socket close → reconnect → refresh → re-handshake (3 round trips + connection churn) vs sync block (refresh → handshake, 2 round trips). Sync block wins decisively.
- UX observability is solvable orthogonally via the EventBus emissions below — internal callers block, external observers (UI, telemetry) subscribe.

**EventBus emissions (the orthogonal observability path)**:
- On refresh start: `{type: "refresh_started", payload: { reason: "expired" | "invalidated" }, source: "AuthManager", ts: Date.now()}`
- On refresh success: `{type: "refresh_completed", payload: { expiresAt: number }, source: "AuthManager", ts: Date.now()}`
- On refresh failure: `{type: "refresh_failed", payload: { error: string, willRetry: boolean }, source: "AuthManager", ts: Date.now()}`
- On state transitions: `{type: "auth_state_change", payload: <newState>, source: "AuthManager", ts: Date.now()}`

UI components (Phase 5+) and telemetry (Phase 7) subscribe to these events independently of any caller's `getToken()` call. AuthManager's internals are not coupled to any specific consumer.

**XState actor states**: `idle` (no token) → `ready` (valid token) → `refreshing` (refresh in flight) → `ready` (refreshed) | `expired` (refresh failed). Transitions emit the events above.

**Refresh timeout** (Pass 1 finding #6 resolution): AuthManager performs the refresh round-trip via `ApiClient` internally with the same `defaultTimeoutMs`. If the refresh exceeds timeout, the resulting `AbortError` is caught inside the lock callback, `getToken()` rejects with the AbortError payload, and the EventBus emits `{type: "refresh_failed", payload: { error: "timeout", willRetry: false }, source: "AuthManager", ts: Date.now()}`. The lock releases regardless of outcome — no zombie locks.

### ApiClient

```ts
export interface ApiClientOptions {
  baseUrl: string;          // from LUPIN_API_URL env at build time, fallback to window.location.origin
  defaultTimeoutMs: number; // 10_000 default
  authManager: AuthManager;
}

export interface ApiClient {
  get<T>(path: string, opts?: { signal?: AbortSignal; timeoutMs?: number }): Promise<T>;
  post<T>(path: string, body: unknown, opts?: { signal?: AbortSignal; timeoutMs?: number }): Promise<T>;
  // …same shape for put / patch / delete
}
```

- Every call wraps the user's signal (if any) and a timeout-derived signal via `AbortSignal.any([userSignal, timeoutSignal])`. Either one firing aborts the fetch.
- Auth header injected from `authManager.getToken()`; on 401 from server, calls `authManager.invalidate()` and rethrows so the caller can decide whether to retry.

### StorageService (DC2 resolution: session ID accessor — 2026-05-04)

```ts
export interface StorageEnvelope<T> {
  schemaVersion: number;
  payload: T;
  ts: number;  // ms epoch
}

export interface SessionIdEnvelope {
  sessionId: string;       // "wise penguin" format per existing convention
  generatedAt: number;     // ms epoch
}

export interface StorageService {
  // Generic typed accessors
  getJSON<T>(key: string, expectedSchemaVersion: number): T | null;
  setJSON<T>(key: string, value: T, schemaVersion: number): void;
  remove(key: string): void;
  keys(prefix?: string): string[];

  // Session ID — first-class accessor (DC2 resolution)
  getSessionId(): string | null;     // returns current session ID or null on miss
  setSessionId(sessionId: string): void;  // stamp generatedAt internally
}
```

- All keys auto-prefixed with `lupin:`; exposed `keys()` returns un-prefixed keys.
- `getJSON` returns `null` on parse error / schema mismatch and emits `{type: "storage_corrupt", payload: {key, error}, source: "StorageService", ts: Date.now()}` on the EventBus (the corruption is observable but doesn't throw).
- **Emission timing** (Pass 1 finding #7 resolution): the `storage_corrupt` event is emitted **synchronously, in the same microtask as the `null` return**, before `getJSON` returns to its caller. EventBus listeners receive the event in the same microtask as the caller observing `null`. This means observers that subscribe before calling `getJSON` will see the corruption event paired with the null return without an interleaving race window.
- **Session ID accessor (DC2)**: `getSessionId()` reads the session ID envelope (storage key `lupin:session_id`); returns `null` on miss. `setSessionId(id)` writes the envelope with internal `generatedAt`. **Phase 3 transports MUST use these methods**, not raw `localStorage` — the "StorageService owns all storage" invariant is non-negotiable. boot.ts is responsible for: read `getSessionId()` at startup; if `null`, generate a new ID via the existing "adjective noun" format (mirrors `notifications.js` legacy logic at line 478) and call `setSessionId()`.

### EventBus

```ts
export interface LupinEvent<T = unknown> {
  type: string;
  payload: T;
  source: string;  // module name emitting the event
  ts: number;
}

export interface EventBus {
  on<T>(type: string, listener: (e: LupinEvent<T>) => void): () => void;  // returns unsubscribe fn
  off(type: string, listener: Function): void;
  emit<T>(event: LupinEvent<T>): void;
}
```

- Single global instance exported from `multiplexer/shared/EventBus.ts`; ALL modules import from there. ESLint rule (Phase 1) prevents creating ad-hoc EventTargets elsewhere.
- One listener throwing must NOT break other listeners — the bus catches per-listener errors and emits `{type: "listener_error", payload: {originalEvent, error}, …}`.

#### Phase 2 reserved event types (Pass 1 finding #5 resolution)

Phase 2 services emit these event types; consumers can rely on them. Phase 3+ adds `transport_*` and `connection_*` types (defined in `04-phase3-transport-design.md`).

| Source | Event types |
|---|---|
| AuthManager | `auth_state_change`, `refresh_started`, `refresh_completed`, `refresh_failed` (idle/ready/expired states surface via `auth_state_change.payload.state`) |
| StorageService | `storage_corrupt` (synchronous emission per finding #7 below) |
| EventBus itself | `listener_error` (per-listener error isolation) |

**Type-safety policy** (Open Q3 RESOLVED — hybrid 2026-05-04): `LupinEventType` is declared as a string-literal union in `multiplexer/shared/types.ts` covering all enumerated types above plus Phase 3+ types. For test flexibility, runtime-only types may be cast: `bus.emit({type: "fake_test_event" as LupinEventType, …})`. New event types added by later phases append to the union; tests and runtime use go through `LupinEventType` declarations. Phase 7 hardening reviews whether to formalize as a registry if 50+ types accumulate.

### BroadcastChannel wrapper (DC4 resolution: static whitelist constant — 2026-05-04)

```ts
// Static — exported from multiplexer/shared/broadcast.ts
export const BROADCAST_WHITELIST: ReadonlySet<string> = new Set([
  "auth_state_change",
  "notification_received",
  "voice_persona_assigned",
  "voice_persona_released",
  "conversation_mode_change",
]);

export interface BroadcastWrapper {
  start(): void;        // begin replication; idempotent
  stop(): void;
}
```

- Subscribes to whitelisted EventBus events whose `source !== "broadcast"`; re-emits via `BroadcastChannel("lupin")`.
- Receives messages from the channel and emits them on the EventBus with `source: "broadcast"` to break replication loops.
- **Whitelist is a static constant (DC4 resolution)** — not a runtime config. Cross-tab replication is a design decision about which events make sense to replicate, not an operational tuning knob. Phase 3 (which instantiates the wrapper) does not pass a whitelist; the wrapper imports `BROADCAST_WHITELIST` directly. Changes to the whitelist ratify via code review, never via runtime config.
- High-rate events explicitly EXCLUDED from the whitelist: `audio_chunk`, `streaming_progress`, any per-token TTS event. These would saturate the BroadcastChannel.
- **Non-whitelisted event behavior** (Pass 1 finding #8 resolution): events whose `type` is not in `BROADCAST_WHITELIST` are **silently not replicated** — no warning, no error, no log. This is intentional — the wrapper observes the EventBus passively and only relays the whitelisted set.
- **Procedure for adding a new event type to the whitelist** (Pass 1 finding #8 resolution):
  1. Confirm the event type is low-frequency — under approximately 1 event/second across all tabs in steady state. High-rate events go on the EXCLUDED list, not the whitelist.
  2. Confirm cross-tab synchronization is semantically correct for that event — i.e., that other tabs of the same user benefit from observing it. (E.g., `auth_state_change` benefits all tabs; `notification_received` benefits all tabs that show notifications. A new `local_ui_animation_started` event would NOT benefit other tabs.)
  3. Add the event type to `BROADCAST_WHITELIST` in `multiplexer/shared/broadcast.ts` with a code comment explaining why cross-tab replication is desired.
  4. Update `src/tests/unit/multiplexer/broadcast.test.ts` with a loop-prevention test for the new event type (mirrors the existing whitelist-loop-prevention assertion).

## Acceptance criteria (definition of done for Phase 2)

1. All five service modules exist at the expected paths.
2. `tsc --noEmit -p tsconfig.json` passes with zero errors.
3. ESLint passes with zero errors (Phase 1's `.eslintrc.json` rules apply).
4. Unit tests for all five modules pass at 100%; **line coverage 100% per module** instrumented via `tsx --test` + `c8` (per DC3 + Pass 1 OQ resolution; both pulled via Phase 1 `package.json`). Two narrowly-scoped exceptions, each annotated inline with `/* c8 ignore */` directives and rationale comments:
    - `auth/AuthManager.ts` `NavigatorLockManager.request` body — wraps `navigator.locks` which is a Web API unavailable in Node; tests use `ChainMutexLockManager` instead. Browser-only by design.
    - `auth/AuthManager.ts` `ChainMutexLockManager` `release: () => {}` placeholder — satisfies TypeScript's "definitely assigned" check; never executed because the Promise constructor synchronously overwrites `release` before any caller can reach the placeholder. TS plumbing dead code.

  All other lines must be exercised by tests. **Coverage AC upgraded from `≥ 90%` to `100%` (with documented exceptions) in session ec746144 (2026-05-04 PM)** after the user pointed out that `≥ 90%` was being treated as a ceiling rather than a floor; the upgrade is documented in `90-execution-log.md` Phase 2 Notes "Coverage AC upgrade".
5. AuthManager dedup: a deliberate test-harness scenario where 5 concurrent `getToken()` calls fire while the token is expired produces exactly ONE network request to `/auth/refresh` (verified via mocked fetch).
6. ApiClient timeout: a deliberate test where the mock fetch hangs longer than `defaultTimeoutMs` causes the call to reject with an `AbortError` and emits no listener-error events.
7. EventBus listener error isolation: a deliberate test where one listener throws and another succeeds confirms the second listener still receives the event.
8. BroadcastChannel loop prevention: a deliberate two-instance test (simulate two tabs via two `BroadcastChannel` instances on the same origin) confirms an event emitted in tab A reaches tab B exactly once and does NOT echo back to tab A.

## Verification (Claude-executed per `01-working-contract.md`)

The user is never the tester. Claude executes every verification step and reports results in tabular form.

### :7999 (AI-discretionary, immediately after each module lands)

| Step | Command / Action | Pass criterion |
|---|---|---|
| Build smoke | `bash src/scripts/build-multiplexer.sh` | Exit 0; bundle includes the new modules |
| TypeScript check | `npx tsc --noEmit -p tsconfig.json` | Zero errors |
| ESLint check | `npx eslint src/fastapi_app/static/js/multiplexer/` | Zero errors |
| Unit tests — auth_manager | `npx tsx --test src/tests/unit/multiplexer/auth_manager.test.ts` (Pass 1 finding #9 + DC3: Node `node:test` runner via `tsx`; coverage via `c8`) | All pass; 100% line coverage on `AuthManager.ts` (with two `c8 ignore` exceptions: `NavigatorLockManager.request` body, `ChainMutexLockManager` `release` placeholder) |
| Unit tests — api_client | `npx tsx --test src/tests/unit/multiplexer/api_client.test.ts` | All pass; 100% line coverage |
| Unit tests — storage_service | `npx tsx --test src/tests/unit/multiplexer/storage_service.test.ts` | All pass; 100% line coverage |
| Unit tests — event_bus | `npx tsx --test src/tests/unit/multiplexer/event_bus.test.ts` | All pass; 100% line coverage |
| Unit tests — broadcast | `npx tsx --test src/tests/unit/multiplexer/broadcast.test.ts` | All pass; 100% line coverage |
| Page-load smoke | Playwright headless: navigate to `/app/multiplexer`, assert no console errors related to module imports | All five services importable from `boot.ts` without runtime errors |

All `LUPIN_API_URL`-aware tests use the env var per `feedback_tests_parameterize_base_url`; default `http://localhost:7999`.

### :8000 (scheduled — N/A for Phase 2)

Phase 2 introduces no destructive state, no LLM spend, no monopoly requirement. All verification fits the :7999 envelope. :8000 work begins at Phase 6 (E2E parity) per `01-execution-plan.md` §4.5.

## Rollback procedure

If Phase 2 needs to be reverted:
1. Remove new files: `multiplexer/auth/`, `multiplexer/api/`, `multiplexer/shared/EventBus.ts`, `multiplexer/shared/StorageService.ts`, `multiplexer/shared/broadcast.ts`, `multiplexer/shared/types.ts`.
2. Remove unit tests under `src/tests/unit/multiplexer/`.
3. **EXECUTOR: AI**: `curl -I http://localhost:7999/app/multiplexer` returns 200 OK; re-run Phase 1 unit suite + the Phase 1 page-load Playwright assertion (Phase 1 AC#4) — confirms Phase 1 surface unaffected by the Phase 2 revert.

No DB migrations, no shared state mutations, no config keys added.

## Open questions — RESOLVED 2026-05-04 (REUSE pre-pass + DC3)

1. **Test runner choice** — **RESOLVED: option (b)** — Phase 2 ships tests as `.test.ts` files runnable via `tsx --test` using Node's built-in `node:test` runner. Coverage via `c8`. Both pulled via the Phase 1 `package.json` (`tsx` + `c8` listed as `devDependencies` per Phase 1 Open Questions resolution). Zero additional node_modules sprawl beyond Phase 1's commitment. If Phase 7 hardening review wants Vitest, that's a separate Phase 7 conversation.

2. **`navigator.locks` browser support** — **RESOLVED 2026-05-04 (Pass 1 OQ ratification): option (a)** — Require modern browsers (Chrome 96+, Firefox 96+, Safari 15.4+ for `navigator.locks`; same era as the other modern APIs the multiplexer relies on). No polyfill, no fallback. Documented in multiplexer README + a comment in `tsconfig.json`. Lupin's user base already runs on modern Web APIs (BroadcastChannel, BigInt); the additional requirement is consistent.

3. **EventBus event-type registry** — **RESOLVED 2026-05-04 (Pass 1 OQ ratification): hybrid** — `LupinEventType` is a string-literal union in `multiplexer/shared/types.ts` covering enumerated types (Phase 2 + Phase 3+ unions; canonical list in §"Phase 2 reserved event types" above and in `04-phase3-transport-design.md`). Test-time cast permitted for runtime-only test events: `bus.emit({type: "fake_test_event" as LupinEventType, …})`. New event types append to the union as later phases land. Phase 7 hardening reviews whether to formalize as a runtime registry if 50+ types accumulate.

4. **`AbortSignal.any` polyfill** — **RESOLVED 2026-05-04 (Pass 1 OQ ratification): option (a)** — Require modern browsers (Chrome 116+, Firefox 124+, Safari 17.4+ for `AbortSignal.any`). Consistent with Q2. No polyfill. Documented in multiplexer README.

## Prior art referenced (from REUSE pre-pass 2026-05-04)

Per PIP §4: extend-existing + genuinely-new-with-prior-art findings, captured for traceability.

| Phase 2 component | Prior art (file:line) | Verdict |
|---|---|---|
| AuthManager + `navigator.locks` dedup | `src/fastapi_app/static/js/notifications.js:951-1120` (`ensureValidToken()` + `refreshAccessToken()`; raw `localStorage` token storage; **no `navigator.locks` dedup**) | genuinely-new (greenfield isolation per Q5; legacy lacks lock dedup; sync-block contract per DC1 resolution above) |
| ApiClient + `AbortSignal.any` | `src/fastapi_app/static/js/notifications.js:1002-1030` (`authedFetch()` method; **no `AbortSignal.any` or timeout handling**) | genuinely-new (greenfield isolation per Q5; legacy lacks timeout abort) |
| StorageService typed JSON helpers | `src/fastapi_app/static/js/notifications.js:172-204` (raw `localStorage.getItem/setItem/removeItem` with manual JSON.parse/stringify; **no schema versioning or error recovery**) | genuinely-new (greenfield isolation per Q5; legacy has no typed-storage wrapper). Session ID accessor (DC2) preserves the legacy "adjective noun" format from `notifications.js:478` |
| EventBus (EventTarget singleton) | none — legacy uses direct method calls + `window.X` globals, not event-driven bus | genuinely-new |
| BroadcastChannel wrapper | none — legacy has no cross-tab synchronization | genuinely-new (whitelist as static constant per DC4 resolution above) |
| JS unit-test infrastructure (`tsx --test` + `c8`) | `src/tests/` is pytest-only; no JS runner | genuinely-new (first JS-side unit-test infra per DC3 resolution; runner pulled via Phase 1 `package.json`) |

## Self-audit (against feedback memory, draft time)

| Memory | Compliance |
|---|---|
| `feedback_phase0_serialization_prominence` | ✅ Phase 0 already shipped; this doc is Phase 2 |
| `feedback_documentation_first_protocol` | ✅ This design doc lands BEFORE any Phase 2 code |
| `feedback_audit_plans_at_execute_time` | ✅ Open Questions section flags re-audit on test-runner + browser-support choices |
| `feedback_lupin_only_never_cosa` | ✅ All paths under `src/fastapi_app/static/js/multiplexer/` and `src/tests/unit/multiplexer/`; no CoSA edits |
| `feedback_never_auto_commit_push` | ✅ No commit-on-completion language; user owns commit cadence |
| `feedback_comprehensive_automated_testing` | ✅ Verification section covers build smoke, TS check, ESLint check, unit tests per module, page-load smoke |
| `feedback_tests_parameterize_base_url` | ✅ All :7999 verification reads `LUPIN_API_URL` |
| `feedback_test_server_monopolize_mode` | ✅ Phase 2 needs no :8000 work |
| `feedback_skip_rnd_doc_for_trivial_fixes` | n/a — Phase 2 introduces 5 new service modules |
| `feedback_no_green_in_persona_pool` | n/a — no persona-color decisions |
| `feedback_audit_plans_at_execute_time` (re-audit obligation) | ✅ Will re-audit this section against memory at execute time |
| `feedback_no_defensive_programming` | ✅ StorageService corruption recovery returns `null` + emits event (explicit boundary), not silent fallback |
| `feedback_fix_at_source_not_consumer` | ✅ Service contracts normalize at the boundary; no defensive `or ""` at consumers |

## Approval gate

Phase 2 implementation begins ONLY after the bundled spine plan-review passes and the user approves the spine bundle (covering this doc + `02-phase1-scaffolding-design.md` + `04-phase3-transport-design.md`). Per Q10 amendment + `feedback_never_auto_commit_push`. Within the bundle, Phase 1 implementation completes BEFORE Phase 2 implementation starts.
