# Phase 1 — Extract `WSChannel` State Machine into a Stand-Alone Module

**Goal**: Build the `ws-channel.js` module to spec from `01-design-review.md` §2.
NO behavior change to `notifications.js` in this phase. Module is unused
until Phase 2 wires it in.

## Files Created

| Path | Purpose |
|------|---------|
| `src/fastapi_app/static/js/ws-channel.js` | The factory + state machine + jitter helper + cleanup helper |

## Files Modified

None in this phase. Module is loaded only by tests until Phase 2.

## Module API

```js
// ws-channel.js — public API

export const STATE = Object.freeze({
  DISCONNECTED   : "DISCONNECTED",
  CONNECTING     : "CONNECTING",
  AUTHENTICATING : "AUTHENTICATING",
  CONNECTED      : "CONNECTED",
  BACKOFF        : "BACKOFF",
  OPEN_CIRCUIT   : "OPEN_CIRCUIT",
});

export const CIRCUIT_OPEN_EVENT = "ws-circuit-open";
export const STATE_CHANGE_EVENT = "ws-state-change";

export function fullJitterDelay( attempt, base, cap ) {
  const exp = Math.min( cap, base * Math.pow( 2, attempt ) );
  return Math.floor( base + Math.random() * Math.max( 0, exp - base ) );
}

/**
 * Create a per-channel WebSocket state machine.
 *
 * Requires:
 *   - opts.url is a non-empty wss:// or ws:// URL string
 *   - opts.name is a non-empty channel name (e.g. "queue", "audio")
 *   - opts.onMessage is invoked on every successfully-parsed JSON envelope
 *   - opts.onAuthSuccess is invoked on the first envelope with type === "auth_success"
 *   - opts.WebSocketCtor (optional) overrides the global WebSocket — used by tests
 *
 * Ensures:
 *   - Returns { connect, manualRetry, close, state, attempts, name }
 *   - Exactly one reconnect path: onclose -> scheduleReconnect
 *   - Counter resets only on auth_success
 *   - readyState guard prevents new WebSocket() while CONNECTING/OPEN
 *   - Generation token drops late callbacks
 *   - Dispatches CIRCUIT_OPEN_EVENT on window when budget exhausted
 *   - Dispatches STATE_CHANGE_EVENT on window on every state transition
 */
export function createChannel( opts ) { /* ... */ }
```

## Class-Level Constants (in `ws-channel.js`)

```js
const MAX_ATTEMPTS_PER_CHANNEL = 20;
const BACKOFF_BASE_MS          = 1000;
const BACKOFF_CAP_MS           = 30_000;
const RAPID_FAIL_COUNT         = 5;
const RAPID_FAIL_WINDOW_MS     = 30_000;
const HANDSHAKE_TIMEOUT_MS     = 10_000;
const WATCHDOG_INTERVAL_MS     = 30_000;
```

These are NOT made into INI keys in v1. Tunable via code edit; deferred
to INI config in v2 if telemetry demands per-environment overrides.

## Phase 1 Verification

| # | Step | EXECUTOR |
|---|------|----------|
| 1 | `node -c src/fastapi_app/static/js/ws-channel.js` (syntax check via Node) — module must parse without errors | EXECUTOR: AI |
| 2 | All Layer-1 unit tests in `07-test-strategy.md` §Layer 1 pass via the Playwright `page.evaluate()` harness on `:7999` | EXECUTOR: AI |
| 3 | `notifications.js` UNCHANGED in this phase — `git diff src/fastapi_app/static/js/notifications.js` returns empty | EXECUTOR: AI |
| 4 | `grep -rn "ws-channel" src/fastapi_app/` shows the new file present and unreferenced (only its own self-mentions) | EXECUTOR: AI |
| 5 | Existing `src/tests/websocket_smoke/` Python tests still pass — `bash src/scripts/run-websocket-smoke-tests.sh` exits 0 | EXECUTOR: AI |

## Phase 1 Exit Criteria

The phase is complete when all five verification rows above are green
AND the new file passes an AI-driven structural review (EXECUTOR: AI)
against §2 of `01-design-review.md` (state set, single scheduler,
generation token, readyState guard). The AI reads its own code against
the design doc and reports concrete pass/fail per checked invariant —
there is no human-side checkbox here.

## Phase 1 Risks

- **Risk**: Node syntax check passes but the module references browser
  globals (`window`, `document`) that don't exist under Node, so the
  Playwright `page.evaluate()` harness is the actual executable check.
  **Mitigation**: Step 1 is "parse-only" (`node --check`); Step 2 runs
  in a real browser context where the globals exist.
- **Risk**: Mock WebSocket harness diverges from real browser behavior
  (especially around when callbacks fire vs. when the constructor returns).
  **Mitigation**: Layer 3 + Layer 4 tests use real WebSocket against
  Playwright's `routeWebSocket()` to validate the assumptions Layer 1
  makes about timing.

## Phase 1 Commits

| Commit | Description | SHA |
|--------|-------------|-----|
| (filled at phase close) | `[LUPIN] Add ws-channel.js state machine module + Layer-1 unit tests` | (sha) |
