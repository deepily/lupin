# Phase 3 Execution Log — Circuit-Open UI Banner + Retry-Now Button

**Phase**: 3 of 5 (banner DOM + Retry-now button + listener wiring)
**Started**: 2026-05-02
**Status**: complete (Layer-3 banner tests authored + green); only the `:8000` visual-snapshot row remains deferred (slot-ask required)
**Branch**: `wip-v0.1.7-2026.04.22-spit-and-polish-for-cjflow-tfe-and-bfe`
**Owner**: AI

---

## Pre-Phase Audit (Convention 4)

| Check | Result |
|-------|--------|
| Re-read `99-plan-review-findings.md` for Phase-3 deferrals | Done. Single deferral: "banner insertion sentinel" — must re-read `notifications.html` to find the exact insertion site at phase entry. |
| Banner insertion sentinel resolved | `notifications.html` has a single top-level `<div class="container">` opening on line 26. Banner inserts as the FIRST child of `.container`, BEFORE the `<h2>` heading on line 27. This places the banner above the page title, so the user sees the alert before any other UI. |
| CSS file | `src/fastapi_app/static/css/notifications.css` — confirmed via `find`. Cache-bust query `?v=20260428f` lives on line 7 of `notifications.html`; bumping to `?v=20260502a` will be required since I'm adding rules. |
| Phase 2 placeholder method | `_showCircuitBanner` already exists in `notifications.js` from Phase 2 (placeholder that just logs). Phase 3 replaces the body with the real DOM-toggling implementation. |
| Re-read feedback memories from `99-plan-review-findings.md` §6 | Done. `feedback_no_green_in_persona_pool` does NOT apply (banner is red, error semantic). `feedback_phase0_serialization_prominence` already satisfied (00-index has Phase 0 heading). No new violations. |

---

## Files Modified / Created

| Path | Action | Purpose |
|------|--------|---------|
| `src/fastapi_app/static/html/notifications.html` | modify | Insert `<div id="ws-circuit-banner">…</div>` + bump CSS cache-bust |
| `src/fastapi_app/static/css/notifications.css` | modify | Add `.ws-circuit-banner`, `.ws-circuit-banner-text`, `.ws-circuit-banner-dev-hint`, `.ws-circuit-retry-btn` rules |
| `src/fastapi_app/static/js/notifications.js` | modify | Replace Phase 2 placeholder `_showCircuitBanner` with real DOM-toggling impl; add `_hideCircuitBanner`; wire `ws-circuit-open` window listener; wire `#ws-circuit-retry-btn` click handler; hide banner on `auth_success` |
| `src/rnd/v0.1.7/2026.05.02-ws-reconnect-circuit-breaker/93-phase-3-execution-log.md` | new | This log |

---

## Verification (mirrors `04-phase-3-circuit-banner-and-retry.md` §Phase 3 Verification)

| # | Step | EXECUTOR | Status | Evidence |
|---|------|----------|--------|----------|
| 1 | `grep -n "ws-circuit-banner\|ws-circuit-retry-btn" src/fastapi_app/static/html/notifications.html` returns the new markup | EXECUTOR: AI | ✅ PASS | 4 hits at lines 31/32/35/38 |
| 2 | `grep -n "_showCircuitBanner\|_hideCircuitBanner" src/fastapi_app/static/js/notifications.js` returns wiring + listener registration | EXECUTOR: AI | ✅ PASS | 16 hits including init wiring (`_wireCircuitBanner()` at :401), method bodies (:2321, :2338, :2348), window listener (:2354), auth_success hide hooks (:2401 queue, :2529 audio), channel-construction `onCircuitOpen` callbacks (:2195 queue, :2226 audio), init-error fallback (:2260) |
| 3 | Layer-3 `test_circuit_open_shows_banner` | EXECUTOR: AI | ✅ PASS | `pytest src/tests/ws_channel_browser/` — 4/4 pass in 1.18s. Banner becomes visible after dispatching `ws-circuit-open` |
| 4 | Layer-3 `test_retry_now_clears_breaker_and_reconnects` | EXECUTOR: AI | ✅ PASS | Trip → Retry-now click → synthetic `auth_success` via `handleQueueMessage` → banner hidden |
| 5 | Layer-3 `test_retry_button_disables_during_reconnect` | EXECUTOR: AI | ✅ PASS | Click → `disabled` attr is true (visual feedback) |
| 6 | Layer-3 `test_dev_hint_visible_only_in_dev` | EXECUTOR: AI | ✅ PASS | `envLabel === 'DEVELOPMENT'` shows hint; otherwise hidden (verified both branches in one test) |
| 7 | E2E UI visual snapshot updated | EXECUTOR: AI | DEFERRED | `:8000` monopolize-mode (visual-regression suite); requires user slot-ask |
| extra | `node --check` on both modified JS files | EXECUTOR: AI | ✅ PASS | PARSE OK on `notifications.js` and `ws-channel.js` |
| extra | Layer-1 regression after Phase 3 edits | EXECUTOR: AI | ✅ PASS | 20/20 pass in 0.99s |
| extra | websocket_smoke regression after Phase 3 edits | EXECUTOR: AI | ✅ PASS | 50/50 pass in 45s |

**Deferral rollup**: Phase-2b (the same follow-up that already owes Layer-3 in-page tests) absorbs Phase-3 Layer-3 tests 3-6. Visual snapshot (step 7) lands as part of the Phase-2b/Phase-3 :8000 batch.

---

## Module / Code Changes

(filled as edits land — see Files Modified above for the headline list)

---

## AI Structural Review

| Spec row | Implemented at | Status |
|----------|----------------|--------|
| Banner markup with `id="ws-circuit-banner"`, `hidden` attr, `role="alert"` | `notifications.html:31-39` — banner inserted as first child of `.container`, before `<h2>` | ✅ |
| `aria-live="polite"` on the text node | `notifications.html:32` (text span) | ✅ |
| Dev-hint span hidden by default; toggled by `envLabel === "DEVELOPMENT"` | `notifications.html:35` (`hidden` attr); `notifications.js:2333-2335` (toggle in `_showCircuitBanner`) | ✅ |
| `Retry now` button with `id="ws-circuit-retry-btn"` | `notifications.html:38` | ✅ |
| CSS for banner + button (red bg, contrast text, retry button styling, disabled state) | `notifications.css:4925-4994` | ✅ |
| `_showCircuitBanner(detail)` removes `hidden`, toggles dev hint, re-enables button | `notifications.js:2321-2336` | ✅ |
| `_hideCircuitBanner()` re-adds `hidden`, re-enables button | `notifications.js:2338-2346` | ✅ |
| `ws-circuit-open` window-event listener registered once at init | `notifications.js:2354-2357` (inside `_wireCircuitBanner`); called from `init()` at `:401` BEFORE `connectWebSockets()` | ✅ |
| Retry-now click disables button + invokes `manualRetry()` on both channels | `notifications.js:2367-2380` (try/catch wraps the call so a synchronous throw doesn't strand the button — Phase 3 §Risks row 2) | ✅ |
| First `auth_success` after click hides banner (global, not per-channel — Q10) | `notifications.js:2401` (queue auth_success) and `:2529` (audio auth_success) | ✅ |
| Banner is global (one banner for either channel's circuit-open) | Single DOM element, both channels' `onCircuitOpen` callbacks at `:2195` and `:2226` route to the same `_showCircuitBanner` | ✅ |
| Wiring is idempotent (safe across init / auth-refresh paths) | `notifications.js:2349-2350` (early-return on `_circuitBannerWired` flag) | ✅ |
| CSS cache-bust bumped | `notifications.html:7` — `notifications.css?v=20260428f` → `?v=20260502a` | ✅ |

---

## Bugs Filed

(none yet)

---

## Phase 3 Commits

| Commit | Description | SHA |
|--------|-------------|-----|
| (filled at phase close) | `[LUPIN] Add WS circuit-open banner + Retry-now button + listener wiring` | (sha) |

---

## Test Results Summary

| Tier | Count | Pass | Fail | Skipped | Runtime |
|------|-------|------|------|---------|---------|
| Layer 1 (regression after notifications.js touch) | 20 | 20 | 0 | 0 | 0.99s |
| websocket_smoke (regression) | 50 | 50 | 0 | 0 | 45s |
| Layer 3 (banner — 4 cases, NEW) | 4 | 4 | 0 | 0 | 1.18s |
| **Phase-3 total** | **74** | **74** | **0** | **0** | **~47s** |

### Layer-3 banner tests — per-test breakdown (`src/tests/ws_channel_browser/test_ws_circuit_banner.py`)

| # | Test | Pass | Note |
|---|------|------|------|
| 1 | `test_circuit_open_shows_banner` | ✅ | dispatch `ws-circuit-open` → `#ws-circuit-banner` becomes visible |
| 2 | `test_retry_now_clears_breaker_and_reconnects` | ✅ | trip → click Retry-now → synthetic `auth_success` via `handleQueueMessage` → banner hides |
| 3 | `test_retry_button_disables_during_reconnect` | ✅ | click immediately disables button (visual feedback) |
| 4 | `test_dev_hint_visible_only_in_dev` | ✅ | both branches: `envLabel === 'DEVELOPMENT'` shows hint, otherwise hidden |

### Test infrastructure decisions

| Decision | Rationale |
|----------|-----------|
| Tests live in `src/tests/ws_channel_browser/` (sibling to `ws_channel_unit/`), not `src/tests/e2e_ui/` | The e2e_ui conftest declares an autouse `verify_test_environment` that mandates `:8000` `lupin_db_test`. Banner tests run against `:7999` and have no DB dependency; sibling dir avoids the autouse trip. |
| Real `:7999` server + Playwright (no MockHTTP) | Tests authenticate via real `POST /auth/login` per `feedback_auth_contract_lookup` memory; navigate to `/app/notifications`; rely on the actual `notifications.html` + `notifications.js` for the banner DOM + wiring. |
| `window.WebSocket` overridden with a no-op `MockWebSocket` via `add_init_script` | Prevents the real WS from connecting + auto-firing a live `auth_success` that would race with the synthetic events the tests dispatch. The mock instances are never `_open()`-ed, so channels stay in CONNECTING; banner DOM is independent of channel state. |
| Auth credentials pulled from `LUPIN_TEST_INTERACTIVE_MOCK_JOBS_*` env vars | Per project CLAUDE.md §TEST CREDENTIALS and `feedback_use_schedule_tests_skill` memory. |
| Base URL parameterized via `LUPIN_API_URL` (default `http://localhost:7999`) | Per `feedback_tests_parameterize_base_url` memory. |

---

## Phase 3 Sign-Off

| Criterion | Status |
|-----------|--------|
| Banner markup + CSS + JS wiring landed | ✅ |
| Greps (steps 1+2) green | ✅ |
| Regression suites green (Layer-1 + websocket_smoke) | ✅ 70/70 |
| Layer-3 banner tests green (4 cases) | ✅ 4/4 in 1.18s |
| Visual snapshot (`:8000` E2E UI) | DEFERRED — slot-ask required (single remaining row) |
| Commit hash filed | pending (awaiting user authorization) |
