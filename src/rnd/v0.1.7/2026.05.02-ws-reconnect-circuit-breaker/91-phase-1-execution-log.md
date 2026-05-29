# Phase 1 Execution Log — `WSChannel` State Machine Module

**Phase**: 1 of 5 (Extract WSChannel state machine into stand-alone module)
**Started**: 2026-05-02
**Status**: complete (awaiting commit)
**Branch**: `wip-v0.1.7-2026.04.22-spit-and-polish-for-cjflow-tfe-and-bfe`
**Owner**: AI

## Deviation from strategy doc (acknowledged)

The strategy doc (`07-test-strategy.md` §Layer 1) names the test path
`src/tests/e2e_ui/test_ws_channel_unit.py`. Tests were placed at
`src/tests/ws_channel_unit/test_ws_channel_unit.py` instead because the
`e2e_ui/` `conftest.py` declares an autouse `verify_test_environment`
fixture that mandates a `:8000` `lupin_db_test` server. Pure JS unit
tests have no server dependency and would have been blocked by that
gate. The strategy doc's intent (`:7999` AI-discretionary, fast,
server-free) is preserved; only the directory differs. Phase 2 may
revisit colocation if a shared harness emerges.

---

## Pre-Phase Audit (Convention 4)

Per `00-working-contract.md` §Pre-Phase Audit:

| Check | Result |
|-------|--------|
| Re-read `99-plan-review-findings.md` for Phase-1 deferrals | Done. Phase 1 has no deferrals (deferrals tagged for Phases 2/3/4/5 only — cache-bust pattern, banner insertion sentinel, init-order site, close-code grep). |
| Re-read feedback memories from `99-plan-review-findings.md` §6 | Done. No new violations to surface. |
| Newly-discovered violations? | None pre-code-write. |

---

## Live API Probe Group (AI-executed against :7999)

| # | Probe | Result | Run-at |
|---|-------|--------|--------|
| (none — Phase 1 is module-creation + Layer-1 unit tests; no live API surfaces touched) | | | |

---

## Verification (mirrors `02-phase-1-ws-channel-module.md` §Phase 1 Verification)

| # | Step | EXECUTOR | Status | Evidence |
|---|------|----------|--------|----------|
| 1 | `node --check src/fastapi_app/static/js/ws-channel.js` | EXECUTOR: AI | ✅ PASS | `node --check` returned exit 0; `PARSE OK` printed |
| 2 | All Layer-1 unit tests pass via Playwright `page.evaluate()` (against MockWebSocket + TestClock injected into `about:blank`) | EXECUTOR: AI | ✅ PASS | `pytest src/tests/ws_channel_unit/ -v` → **20 passed in 0.95s** |
| 3 | `notifications.js` UNCHANGED — `git diff src/fastapi_app/static/js/notifications.js` returns empty | EXECUTOR: AI | ✅ PASS | empty diff (exit 0) |
| 4 | `grep -rn "ws-channel" src/fastapi_app/` shows the new file present and unreferenced | EXECUTOR: AI | ✅ PASS | 6 hits — all self-mentions inside `ws-channel.js` (header comment + design refs + 2 error strings); no consumer references |
| 5 | Existing `src/tests/websocket_smoke/` Python tests still pass | EXECUTOR: AI | ✅ PASS | **50/50 pass** (Core 25/25, Integration 22/22, Performance 2/2, Load 1/1) in 43.75s |

---

## AI Structural Review Against `01-design-review.md` §2

| Invariant | Status | Notes / file:line |
|-----------|--------|-------------------|
| State set complete (DISCONNECTED, CONNECTING, AUTHENTICATING, CONNECTED, BACKOFF, OPEN_CIRCUIT) | ✅ PASS | `ws-channel.js:21-28` — all six states present in frozen `STATE` object |
| Single reconnect scheduler — only `onclose` schedules; `onerror` is a no-op (RFC 6455 §7.1.4 — error precedes close) | ✅ PASS | `ws-channel.js:225-227` (onerror logs only, never calls scheduleReconnect); `ws-channel.js:229-237` (onclose is sole scheduling path) |
| Counter resets only on `auth_success`; never on TCP-open, never on a timer | ✅ PASS (with note) | `ws-channel.js:213` resets on auth_success message; `ws-channel.js:200-214` does NOT reset on `_open()` (transitions to AUTHENTICATING only); watchdog does NOT touch attempts. Note: `manualRetry()` also resets attempts — design Q2 reads "never on online event," but design row §2 "Page lifecycle" + Risk Surface row 7 jointly establish online → manualRetry → reset as the canonical synthesis. Implementation matches the synthesized design. |
| Generation token increments per `connect()`; late callbacks dropped | ✅ PASS | `ws-channel.js:182-184` increments at top of connect; `:200, :206, :223, :229` check `myGen !== generation` and bail. `close()` and `manualRetry()` also bump generation (`:301`, `:289`) |
| `readyState` guard before `new WebSocket()` (CONNECTING/OPEN no-ops) | ✅ PASS | `ws-channel.js:172` — `if ( ws && ( ws.readyState === WS_CONNECTING || ws.readyState === WS_OPEN ) ) return;` |
| Cleanup nulls all four `on*` handlers + calls `close(1000, "cleanup")` | ✅ PASS | `ws-channel.js:138-145` — `cleanupSocket` nulls `onopen/onclose/onerror/onmessage` and calls `close(1000, "cleanup")` |
| Backoff is full jitter, lower bound = BASE_MS, upper bound ≤ CAP_MS | ✅ PASS | `ws-channel.js:79-83` — `floor(BASE + random() * max(0, exp - BASE))`; verified statistically by Layer-1 test 8 (16000 trials, all in [1000, 30000]) |
| Circuit trips at MAX_ATTEMPTS_PER_CHANNEL (20) OR rapid-fail (5 closes in 30s with wasEverOpen=false) | ✅ PASS | `ws-channel.js:248-255` — handleClose tracks `recentFailures` only when `!wasEverOpen`, trips at length ≥ 5; `:264-267` — scheduleReconnect trips at attempts ≥ 20 |
| Auth-failure close codes (4001/4002/4003) → immediate OPEN_CIRCUIT (no decrement) | ✅ PASS | `ws-channel.js:43-45` defines `PERMANENT_CLOSE_CODES`; `:232-235` short-circuits to `openCircuit()` without touching `attempts` |
| Watchdog re-arms `scheduleReconnect` only when truly idle; NEVER zeros attempts | ✅ PASS (with clarification) | `ws-channel.js:319-330` — early-returns on hidden, OPEN_CIRCUIT, BACKOFF, CONNECTING, AUTHENTICATING, CONNECTED, pending backoff timer, or live ws. Only when state==DISCONNECTED + no timer + no live ws does it call `scheduleReconnect` (which DOES bump attempts — Q3's "never touches the attempt counter" is interpreted as "never RESETS/zeros attempts," matching the OLD-bug fix scope) |
| `connect()` no-ops when `document.visibilityState === "hidden"` | ✅ PASS | `ws-channel.js:163` — visibility guard at top of connect |
| Page-lifecycle handlers attached at construction (online/offline/pageshow/pagehide/freeze/resume) | ✅ PASS | `ws-channel.js:341-355` — six handlers registered on `window` and `document` |
| Dispatches `ws-circuit-open` and `ws-state-change` events on `window` | ✅ PASS | `:131-134` STATE_CHANGE_EVENT on every transition; `:281-284` CIRCUIT_OPEN_EVENT in openCircuit |
| State machine transitions match §2.2 diagram | ✅ PASS | All 9 transitions implemented: DISCONNECTED↔CONNECTING via connect(), CONNECTING→AUTHENTICATING via onopen, AUTHENTICATING→CONNECTED via auth_success, CONNECTING/AUTHENTICATING/CONNECTED→BACKOFF via onclose, BACKOFF→CONNECTING via timer, BACKOFF→OPEN_CIRCUIT via budget/rapid-fail, OPEN_CIRCUIT→CONNECTING via manualRetry. (CONNECTED → BACKOFF via "heartbeat-stale" is Phase-2 watchdog responsibility on the consumer; not in Phase 1 scope.) |
| Two-state breaker (closed/open), no auto half-open probe (Q10) | ✅ PASS | OPEN_CIRCUIT is terminal until `manualRetry()` is called |

---

## Bugs Filed (auto-queued during testing)

(none yet)

---

## Phase 1 Commits

| Commit | Description | SHA |
|--------|-------------|-----|
| (filled at phase close) | `[LUPIN] Add ws-channel.js state machine module + Layer-1 unit tests` | (sha) |

---

## Test Results Summary

| Tier | Count | Pass | Fail | Skipped | Runtime |
|------|-------|------|------|---------|---------|
| Layer 1 (JS unit) — `src/tests/ws_channel_unit/` | 20 | 20 | 0 | 0 | 0.95s |
| websocket_smoke (regression) — `src/tests/websocket_smoke/` | 50 | 50 | 0 | 0 | 43.75s |
| **Total** | **70** | **70** | **0** | **0** | **~45s** |

### Layer 1 — Per-test breakdown

| # | Test | Pass | Note |
|---|------|------|------|
| 1 | `test_close_schedules_one_reconnect` | ✅ | one close → exactly one new WS instance after backoff fires |
| 2 | `test_onerror_does_not_double_schedule` | ✅ | onerror NEVER schedules; only handshake timer pending |
| 3 | `test_per_channel_counter_isolation` | ✅ | queue.attempts isolated from audio.attempts |
| 4 | `test_auth_success_resets_counter` | ✅ | counter zeroed on `auth_success` envelope |
| 5 | `test_tcp_open_does_not_reset_counter` | ✅ | TCP open transitions to AUTHENTICATING; attempts unchanged |
| 6 | `test_circuit_opens_at_max_attempts` | ✅ | OPEN_CIRCUIT at attempts ≥ 20; ws-circuit-open fires once |
| 7 | `test_rapid_fail_opens_circuit_early` | ✅ | 5 closes with wasEverOpen=false trips < 20 attempts |
| 8 | `test_full_jitter_bounds_statistical` | ✅ | 16000 trials, all in [1000, 30000] |
| 9 | `test_generation_token_drops_late_callbacks` | ✅ | stale-gen onclose handler is a no-op |
| 10 | `test_readystate_guard_prevents_double_construction` | ✅ | connect() no-ops while ws is CONNECTING or OPEN |
| 11 | `test_manual_retry_resets_state` | ✅ | manualRetry: OPEN_CIRCUIT → CONNECTING, attempts=0 |
| 12 | `test_handshake_timeout_closes_socket` | ✅ | 10s timer fires → ws.close() |
| 13 | `test_cleanupSocket_nulls_handlers` | ✅ | all 4 on* handlers null after cleanup |
| 14 | `test_visibility_hidden_defers_connect` | ✅ | connect() no-op when visibilityState=hidden |
| 15 | `test_pageshow_persisted_full_reset` | ✅ | pageshow.persisted=true → manualRetry path |
| 16 | `test_online_triggers_retry` | ✅ | online event → manualRetry → attempts=0 |
| 17 | `test_offline_closes_socket` | ✅ | offline event → close() → DISCONNECTED |
| 18 | `test_watchdog_only_fires_when_closed_and_no_pending` | ✅ | watchdog no-op in BACKOFF/CONNECTED; schedules only when idle DISCONNECTED |
| 19 | `test_watchdog_never_resets_counter` | ✅ | 10 watchdog ticks leave attempts unchanged |
| 20 | `test_close_4001_immediate_open_circuit` | ✅ | code 4001 → OPEN_CIRCUIT in 1 tick, attempts not decremented |

---

## Phase 1 Sign-Off

| Criterion | Status |
|-----------|--------|
| All five verification rows green | ✅ |
| AI structural review all-pass | ✅ (15/15 invariants pass; 2 carry interpretive notes that match the synthesized design) |
| Commit hash filed | pending (awaiting user authorization) |

## Files Changed (Phase 1)

| Path | Action | Purpose |
|------|--------|---------|
| `src/fastapi_app/static/js/ws-channel.js` | new | WSChannel state machine factory |
| `src/tests/ws_channel_unit/__init__.py` | new | Test package marker |
| `src/tests/ws_channel_unit/test_ws_channel_unit.py` | new | 20 Layer-1 unit tests |
| `src/rnd/v0.1.7/2026.05.02-ws-reconnect-circuit-breaker/91-phase-1-execution-log.md` | new | This log |
