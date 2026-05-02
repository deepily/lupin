# Test Strategy — WS Reconnect Circuit-Breaker

The user explicitly asked for a strategy that maximizes automation
inside the dev environment and minimizes "open the browser and click
around" reliance, with any unavoidable browser tests scoped to the
smallest useful subset of the existing E2E sweep.

This doc describes a five-layer pyramid. Layers 1, 2, 3 are
AI-discretionary on `:7999`. Layers 4 and 5 are scheduled on `:8000`
via `POST /api/test-suite/submit` per project CLAUDE.md §TESTING VENUES.
The user's only `:8000` action is slot-confirmation; the AI submits and
monitors the run.

---

## Test Routing Table (which layer runs where)

| Layer | Tier | Description | Venue | Submission |
|-------|------|-------------|-------|------------|
| 1 | JS unit | Pure state-machine assertions, no real WS | `:7999` Playwright `page.evaluate()` against MockWebSocket | AI-discretionary |
| 2 | Python protocol | Server-side WS lifecycle assertions via `websockets` lib | `:7999` (existing `websocket_smoke` harness) | AI-discretionary |
| 3 | Browser in-page | NotificationsUI + WSChannel integration with MockWebSocket injected into page | `:7999` Playwright | AI-discretionary |
| 4 | Browser real-server | `page.routeWebSocket()` selectively rejects handshakes; full client + server | `:8000` | Scheduled — slot-confirm |
| 5 | Live reproducer | `docker pause` server, observe circuit-open + Retry-now recovery | `:8000` | Scheduled — slot-confirm |

Bulk of validation lives in Layers 1 + 3. Layer 5 is the smallest
useful subset of the full E2E sweep — one test scenario, ~30 seconds.

---

## Layer 1 — JS Unit Tests (pure state machine)

**Where**: `src/tests/e2e_ui/test_ws_channel_unit.py` — a Pytest file
that uses Playwright's `page.evaluate()` to load `ws-channel.js` and
drive it with a `MockWebSocket` global, NEVER hitting the network.

**Why Pytest+Playwright instead of Jest**: Lupin has no JS unit-test
harness today (no Jest, no Vitest, no Karma — confirmed via
`find . -name "*.test.js" -not -path "*/node_modules/*"` returning only
the firefox-plugin sub-repo). Adding one is a real maintenance cost
(node_modules, CI integration, version drift). Pytest+Playwright is
already the de-facto JS test harness for the rest of this codebase.
A new tooling layer is hard to justify.

**MockWebSocket sketch** (lives inline in `page.evaluate()`):

```js
class MockWebSocket {
  static CONNECTING = 0; static OPEN = 1; static CLOSING = 2; static CLOSED = 3;
  static instances = [];
  constructor( url ) {
    this.url = url;
    this.readyState = MockWebSocket.CONNECTING;
    this.onopen = this.onclose = this.onerror = this.onmessage = null;
    MockWebSocket.instances.push( this );
  }
  send( data ) { this.lastSent = data; }
  close( code = 1000, reason = "" ) {
    this.readyState = MockWebSocket.CLOSED;
    queueMicrotask( () => this.onclose?.( { code, reason, wasClean: code === 1000 } ) );
  }
  // Test-driver helpers:
  _open() {
    this.readyState = MockWebSocket.OPEN;
    queueMicrotask( () => this.onopen?.( {} ) );
  }
  _msg( payload ) {
    queueMicrotask( () => this.onmessage?.( { data: JSON.stringify( payload ) } ) );
  }
  _close( code = 1006, reason = "" ) {
    this.readyState = MockWebSocket.CLOSED;
    queueMicrotask( () => this.onclose?.( { code, reason, wasClean: false } ) );
  }
}
```

**Test cases** (each is a separate Pytest function):

| # | Name | Asserts |
|---|------|---------|
| 1 | `test_close_schedules_one_reconnect` | One `close` event ⇒ one entry in MockWebSocket.instances after backoff timer fires; not two |
| 2 | `test_onerror_does_not_double_schedule` | `onerror` followed by `onclose` schedules exactly one reconnect |
| 3 | `test_per_channel_counter_isolation` | Failing the `audio` channel does not increment `queue.attempts` |
| 4 | `test_auth_success_resets_counter` | After 5 failures, an `auth_success` envelope drops attempts to 0 |
| 5 | `test_tcp_open_does_not_reset_counter` | `_open()` (TCP) does not clear attempts; only `_msg({type:"auth_success"})` does |
| 6 | `test_circuit_opens_at_max_attempts` | After exactly MAX_ATTEMPTS (20) failures, state == OPEN_CIRCUIT and `ws-circuit-open` event fired |
| 7 | `test_rapid_fail_opens_circuit_early` | 5 closes within 30s with `wasEverOpen=false` opens the circuit on the 5th, attempts < 20 |
| 8 | `test_full_jitter_bounds_statistical` | 1000 trials of `fullJitterDelay(attempt, 1000, 30000)` for attempts 0..15 — all in [1000, 30000] (lower bound is BASE_MS) |
| 9 | `test_generation_token_drops_late_callbacks` | After `connect()` increments generation, the previous WS's late `onclose` does not increment attempts |
| 10 | `test_readystate_guard_prevents_double_construction` | While ws.readyState === CONNECTING, calling `connect()` again does NOT push a new entry to MockWebSocket.instances |
| 11 | `test_manual_retry_resets_state` | From OPEN_CIRCUIT state, `manualRetry()` zeros attempts, clears rapid-fail window, transitions to CONNECTING |
| 12 | `test_handshake_timeout_closes_socket` | A WebSocket stuck in CONNECTING is `close()`d after HANDSHAKE_TIMEOUT_MS — releases the renderer slot |
| 13 | `test_cleanupSocket_nulls_handlers` | After internal cleanup, the prior MockWebSocket instance has all four `on*` properties === null |
| 14 | `test_visibility_hidden_defers_connect` | While `document.visibilityState === "hidden"`, `connect()` does not push a new MockWebSocket instance |
| 15 | `test_pageshow_persisted_full_reset` | Dispatching `pageshow` with `persisted=true` invokes `manualRetry` |
| 16 | `test_online_triggers_retry` | Dispatching `online` invokes `manualRetry` |
| 17 | `test_offline_closes_socket` | Dispatching `offline` transitions state to DISCONNECTED |
| 18 | `test_watchdog_only_fires_when_closed_and_no_pending` | Watchdog tick with state === BACKOFF (timer pending) is no-op; with state === CONNECTED is no-op (only liveness ping); with ws.readyState === CLOSED and no scheduled reconnect, watchdog calls scheduleReconnect |
| 19 | `test_watchdog_never_resets_counter` | Run watchdog 10 times after 5 failures; attempts stays at 5 |
| 20 | `test_close_4001_immediate_open_circuit` | A close with code 4001 transitions state to OPEN_CIRCUIT in one tick (does NOT decrement attempts to 19) |

20 tests. Runtime ≈ 5–10s total (each test runs `page.evaluate()` blocks
with `queueMicrotask` resolution, no real network).

**Run command**: `pytest src/tests/e2e_ui/test_ws_channel_unit.py -v`

---

## Layer 2 — Python Protocol Tests (server-side WS lifecycle)

**Where**: New file `src/tests/websocket_smoke/core/test_close_codes.py`
in the existing `websocket_smoke` harness. Run via the existing
`src/scripts/run-websocket-smoke-tests.sh` runner.

**Test cases**:

| # | Name | Asserts |
|---|------|---------|
| 1 | `test_invalid_token_close_code` | Connect to `/ws/queue/test_session` with junk token; assert close frame code == 4001 |
| 2 | `test_first_message_not_auth_request_close_code` | Connect, send `{"type":"random","payload":"foo"}`; assert close code == 4001 (per Phase 5 mapping decision) |
| 3 | `test_session_conflict_close_code` | Pre-condition: `enforce_single_session_per_user = True` in test config; connect twice as same user; assert second's close code == 4002. SKIP if config flag is False (with a `@pytest.skip` decorator carrying the reason) |
| 4 | `test_subscription_denied_close_code` | Connect with valid token but request an event the user lacks RBAC for; assert close code == 4003 |
| 5 | `test_sys_ping_emitted_at_configured_interval` | Connect, sit for 35s, assert at least one `sys_ping` envelope was received (config interval = 30s) |
| 6 | `test_clean_close_no_app_code` | Send a `{"type":"close"}` (or whatever the app's voluntary close path is, if any) and assert close code is in {1000, 1001} — NOT 4xxx |

**Auth contract**: Tests use POST `/auth/login` with the
`LUPIN_TEST_INTERACTIVE_MOCK_JOBS_*` env vars per `feedback_auth_contract_lookup`
memory; access token at `tokens.access_token`. NEVER use `mock_token_email_*`
(that's legacy per `feedback_mock_tokens_are_legacy`).

**Base URL**: read from `LUPIN_API_URL` env var, default `http://localhost:7999`,
per `feedback_tests_parameterize_base_url`.

**Run command**: `bash src/scripts/run-websocket-smoke-tests.sh`

---

## Layer 3 — Browser In-Page Integration (MockWebSocket injected)

**Where**: New file `src/tests/e2e_ui/test_ws_channel_browser_integration.py`.
Uses Playwright to navigate to `/notifications` (with auth bypass for the
test fixture), inject a MockWebSocket constructor onto `window` BEFORE
the notifications.js module loads, then drive the channel state machine
and assert NotificationsUI behavior.

**Test cases**:

| # | Name | Asserts |
|---|------|---------|
| 1 | `test_circuit_open_shows_banner` | Drive 20 closes; assert `#ws-circuit-banner` is visible |
| 2 | `test_retry_now_clears_breaker_and_reconnects` | After banner is shown, click `#ws-circuit-retry-btn`; assert banner hides on next `auth_success` |
| 3 | `test_retry_button_disables_during_reconnect` | After click, button has `disabled` attribute until next state change |
| 4 | `test_dev_hint_visible_only_in_dev` | With `envLabel === "DEVELOPMENT"`, `.ws-circuit-banner-dev-hint` is visible; in PROD it's hidden |
| 5 | `test_token_refresh_resets_channels` | Inject auth_error envelope; assert refresh path is triggered and channels' manualRetry is called |
| 6 | `test_4001_triggers_token_refresh_path` | Inject close with code=4001; assert refresh path fires before banner is shown |
| 7 | `test_4001_refresh_success_no_banner_flash` | Refresh succeeds inside the 4001 handler; assert banner is never made visible |
| 8 | `test_global_banner_one_channel_open` | Trip queue circuit only; assert banner shown |
| 9 | `test_global_banner_both_channels_open` | Trip both circuits; click Retry-now; assert both channels recover |
| 10 | `test_health_monitor_does_not_reset_counter` | Drive 5 failures, run 3 watchdog ticks (force via test hook), drive 16 more failures; assert circuit opens at the 21st total failure (NOT reset by ticks) |

**Run command**: `pytest src/tests/e2e_ui/test_ws_channel_browser_integration.py -v`

---

## Layer 4 — Browser Real-Server (`page.routeWebSocket()` injection)

**Where**: New file `src/tests/e2e_ui/test_ws_circuit_recovery.py`. Runs
against a real Lupin server (the `:8000` test server), with Playwright's
`page.route_web_socket()` selectively rejecting handshakes to simulate
network failures the server cannot itself manufacture.

**Test cases**:

| # | Name | Asserts |
|---|------|---------|
| 1 | `test_happy_path_smoke` | Open `/notifications`; assert both channels reach CONNECTED within 5s; no banner shown | 
| 2 | `test_handshake_rejection_opens_circuit` | route_web_socket rejects ALL `/ws/queue/*` handshakes; load page; assert banner appears within 30s (well under 6-min budget) |
| 3 | `test_intermittent_failure_recovers_within_budget` | route_web_socket rejects first 3 handshakes then accepts; assert banner does NOT appear and channel reaches CONNECTED |

3 tests. Runtime ≈ 60–90s.

**Run command**: scheduled on `:8000` via `POST /api/test-suite/submit`
with `{"test_types": "ws_circuit_recovery", "scheduled_at": "..."}`.
The `test_types` value here is a NEW key; Phase 5 / Phase 6 of
implementation must register it in the test-suite scheduler. If
registration is non-trivial, fall back to running under
`run-e2e-ui-tests.sh -k ws_circuit_recovery` per existing harness.

---

## Layer 5 — Live Reproducer (`docker pause` for true outage simulation)

**Where**: New file `src/tests/e2e_ui/test_ws_circuit_live_outage.py`.
Single test case that reproduces the actual incident pattern:
sustained network failure → circuit opens → user clicks retry → recovery.

**Test case**:

| # | Name | Asserts |
|---|------|---------|
| 1 | `test_docker_pause_outage_recovery` | Open `/notifications`; assert both channels CONNECTED. Run `docker pause lupin-rest-test`. Wait. Assert circuit banner appears within 6 minutes. Run `docker unpause lupin-rest-test`. Click Retry-now. Assert both channels back to CONNECTED within 30s. |

This is the smallest useful subset of the full E2E sweep and the only
test that exercises the actual real-network-plus-real-server pathology
the bug describes. Runtime ≈ 7–8 minutes.

**Run command**: scheduled on `:8000`; the test itself orchestrates
`docker pause` / `docker unpause` against the lupin-rest-test container
via `subprocess.run`. Permission scope: requires `docker` CLI access
inside the test runner; assumed available per the existing
`test_container_preflight.py` precedent.

**Why we cannot fully simulate the renderer-cap (255-pending) symptom
in any layer**: Chrome's `kMaxPendingWebSocketConnections = 255` is
enforced inside the network service. Driving a real renderer to 255
pending handshakes requires either (a) a physically slow upstream
that holds 255 handshakes open simultaneously — Playwright can do this
with `page.routeWebSocket(handler)` that never calls `connectToServer()`,
but the test runtime grows to minutes — or (b) running the test in a
real Chromium with the pool deliberately throttled. We accept that the
255-cap symptom itself is NOT directly tested; what IS tested is the
behavior change that prevents the cap from being hit (per-channel state,
readyState guard, generation token, explicit cleanup). The Layer-5 test
gives us the recovery-after-real-outage assertion that is the
user-observable bug fix.

---

## Test Coverage Summary by Pyramid Tier

| Tier | Count | Where | Cumulative runtime | Catches |
|------|-------|-------|--------------------|---------|
| Layer 1 (JS unit) | 20 | `:7999` | ~10s | State-machine bugs, backoff math, counter rules, generation token |
| Layer 2 (Py protocol) | 6 | `:7999` | ~30s | Server close-code regressions, sys_ping cadence |
| Layer 3 (Browser integration) | 10 | `:7999` | ~45s | NotificationsUI ↔ WSChannel wiring, banner UX |
| Layer 4 (Browser real-server) | 3 | `:8000` | ~90s | End-to-end with real auth + real WS, no cheating with mocks |
| Layer 5 (Live reproducer) | 1 | `:8000` | ~8min | The actual incident pattern |
| **Total NEW** | **40** | | ~10min | |

For comparison: the existing E2E UI suite is 285 tests / ~17 min. The
five layers above add ~10 minutes for ~40 tests, all targeted at this
fix surface. The pyramid keeps the per-PR validation cost bounded.

---

## What the User Does NOT Have to Do

Per `CLAUDE.local.md` THE USER IS NEVER A TESTER and the working
contract:

- The user does NOT open a browser to validate the banner shows.
- The user does NOT click Retry-now to validate the recovery path.
- The user does NOT manually run any `docker pause` reproducer.
- The user does NOT diff visual snapshots subjectively (the
  pytest-playwright-visual-snapshot harness produces
  diff-or-no-diff verdicts).

The user's gates are: (a) approve the design (this doc set);
(b) confirm the `:8000` slot is clear when the AI submits Layer 4 / 5
tests; (c) the rare visual-judgment call (banner color, copy tone) if
the AI surfaces it as a HUMAN-required step with reason.
