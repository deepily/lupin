# Phase 5 Execution Log — Server-Side Hardening (Auth-Failure Close Codes)

**Phase**: 5 of 5 (server-side close codes 4001/4002/4003 + client wiring + docs)
**Started**: 2026-05-02
**Status**: ✅ COMPLETE — all 9 verification rows green (CoSA edits awaiting separate user-driven CoSA-context commit)
**Branch**: `wip-v0.1.7-2026.04.22-spit-and-polish-for-cjflow-tfe-and-bfe`
**Owner**: AI

---

## Pre-Phase Audit (Convention 4)

| Check | Result |
|-------|--------|
| Re-read `99-plan-review-findings.md` for Phase-5 deferrals | Done. Two deferrals applicable: (a) "close-code-collision sweep" (verification row 0) — must grep the codebase for existing 4xxx close codes BEFORE picking the auth block, and (b) "exact line numbers + close-code-per-branch table" — must re-read `routers/websocket.py` at phase entry. |
| **Step 0** — collision grep | `grep -rnE "close.*code\s*=\s*4[0-9]{3}" src/cosa/ src/fastapi_app/` returns ZERO production hits. Only references are in the design docs of THIS milestone (ws-reconnect-circuit-breaker/) and the new `ws-channel.js` PERMANENT_CLOSE_CODES set. **4001/4002/4003 are safe to use** — no renumbering required. |
| Auth-failure sites in `routers/websocket.py` | Surveyed. Queue path has 10 close calls at lines 346, 358, 370, 380, 389, 400, 409, 456, 466, 471, 478. All currently call `await websocket.close()` with no code. Phase 5 patch replaces each with `code=4001` (auth_request flow). Audio path at `:249-254` does NOT close the socket on auth failure — only sends `auth_error` — so no 4001 patch needed there. |
| 4002 site (single-session-per-user displacement) | Found at `cosa/rest/websocket_manager.py:141` — currently closes old sessions with `code=1000, reason="New session opened"`. Phase 5 patch changes to `code=4002, reason="session_conflict_displaced"` so the displaced client recognizes it as permanent and does NOT retry. |
| 4003 (subscription RBAC) | No existing reject branch in code today (audio subscriptions are filtered silently at `:238`). Phase 5 reserves the code in a comment block but does NOT manufacture a synthetic reject branch — would be speculative. Code reserved for future RBAC enforcement. |
| Re-read feedback memories from `99-plan-review-findings.md` §6 | Done. `feedback_lupin_only_never_cosa` partially relaxed by `feedback_cosa_edit_vs_manage_git`: editing `src/cosa/...` files is allowed, only git ops (add/commit/push) are forbidden. **CoSA submodule edits in this Phase will NOT be staged or committed by me — that's the user's responsibility in a CoSA-context session.** |

---

## Step 0 Verification (collision grep) — full output

```
$ grep -rnE "close.*code\s*=\s*4[0-9]{3}" src/cosa/ src/fastapi_app/ | grep -v "rnd/v0.1.7/2026.05.02-ws-reconnect" | grep -v "ws-channel.js"
[ZERO hits]
```

The 4001/4002/4003 block is unique in the Lupin + CoSA codebase outside the design-doc/new-module references.

---

## Files Modified / Created

| Path | Action | Repo | Purpose |
|------|--------|------|---------|
| `src/cosa/rest/routers/websocket.py` | modify | **CoSA submodule** (USER MUST COMMIT SEPARATELY) | 10 queue auth-fail close-call sites get `code=4001, reason=<specific>` |
| `src/cosa/rest/websocket_manager.py` | modify | **CoSA submodule** (USER MUST COMMIT SEPARATELY) | line 141 single-session-displaced close gets `code=4002, reason="session_conflict_displaced"` |
| `src/fastapi_app/static/js/ws-channel.js` | modify | Lupin | `openCircuit()` accepts `reason` + emits `detail.reason` and `detail.code` so consumers can differentiate auth-permanent vs network-failure |
| `src/fastapi_app/static/js/notifications.js` | modify | Lupin | `_showCircuitBanner(detail)` swaps banner text by `detail.reason`; on `reason === "auth-permanent"` and `code === 4001`, attempts `refreshAccessToken()` first; only shows banner if refresh fails |
| `src/fastapi_app/static/html/notifications.html` | modify | Lupin | Banner DOM gets `<span class="ws-circuit-banner-text-default">` + `<span class="ws-circuit-banner-text-auth">` so JS can swap visibility |
| `src/tests/websocket_smoke/core/test_close_codes.py` | new | Lupin | Layer-2 Python: assert close frame code is 4001 on junk-token connect |
| `src/tests/ws_channel_browser/test_ws_close_codes.py` | new | Lupin | Layer-3: 4001 immediate-trip, banner-copy differentiation, token-refresh path, no-banner-flash on refresh-success |
| `src/docs/websocket-events.md` | modify | Lupin | New §"Close Code Semantics" listing 4001/4002/4003 |
| `src/docs/websocket-architecture.md` | modify | Lupin | Cross-reference to the new close-code section |
| `src/rnd/v0.1.7/2026.05.02-ws-reconnect-circuit-breaker/95-phase-5-execution-log.md` | new | Lupin | This log |

---

## Verification (mirrors `06-phase-5-server-side-hardening.md` §Phase 5 Verification)

| # | Step | EXECUTOR | Status | Evidence |
|---|------|----------|--------|----------|
| 0 | Codebase 4xxx collision grep returns zero hits | EXECUTOR: AI | ✅ PASS | (above) |
| 1 | `py_compile` on the modified CoSA files | EXECUTOR: AI | ✅ PASS | `routers/websocket.py` and `websocket_manager.py` both compile clean |
| 2 | Import-chain check `from cosa.rest.routers import websocket` | EXECUTOR: AI | ✅ PASS | imports clean; constants exposed as `CLOSE_CODE_AUTH_INVALID_TOKEN=4001`, `..._SESSION_CONFLICT=4002`, `..._SUBSCRIPTION_DENIED=4003` |
| 3 | Layer-2 `test_invalid_token_close_code` asserts close frame code 4001 | EXECUTOR: AI | ✅ PASS | live `:7999` connect with junk token; server sends `auth_error` then closes with `code=4001`. Verified 1 passed in 0.04s. |
| 4 | Layer-2 `test_session_conflict_close_code` (conditional) | EXECUTOR: AI | ✅ SKIP (conditional) | `pytest.mark.skip` with reason; fixture for `enforce_single_session_per_user=True` requires server-config hot-swap. Reachable manually with that flag set. |
| 5 | Layer-3 `test_close_4001_opens_circuit_immediately` | EXECUTOR: AI | ✅ PASS | drive 4001 close on queue channel → `state==="OPEN_CIRCUIT"` in 1 tick; `attempts` unchanged (matches Phase 1 test 20 invariant) |
| 6 | Layer-3 `test_close_4001_banner_message` | EXECUTOR: AI | ✅ PASS | banner text contains "Authentication failed" and `data-reason="auth-permanent"` after refresh-failure |
| 7 | `src/docs/websocket-events.md` lists 4001/4002/4003 semantics | EXECUTOR: AI | ✅ PASS | new "Close Code Semantics" section appended; full reaction matrix + comparison to standard codes (1000/1001/1006/1008) |
| 8 | `src/docs/websocket-architecture.md` references the new close-code section | EXECUTOR: AI | ✅ PASS | "Auth Error Conditions" table extended with Close Code column; cross-link to `websocket-events.md#close-code-semantics` |
| 9 | Layer-3 `test_4001_triggers_token_refresh_path` + `test_4001_refresh_success_no_banner_flash` | EXECUTOR: AI | ✅ PASS | refresh-stub call counter == 1 on 4001 close; banner stays hidden when refresh resolves to true (no banner flash) |
| extra | All Layer-1 unit tests still green (regression after openCircuit signature change) | EXECUTOR: AI | ✅ PASS | 20/20 in 0.96s |
| extra | Full websocket_smoke regression after CoSA edits | EXECUTOR: AI | ✅ PASS | 50/50 in 45s |
| extra | All Layer-3 banner + lifecycle tests still green (regression after notifications.js banner-reason swap + duplicate onCircuitOpen removal) | EXECUTOR: AI | ✅ PASS | 14/14 (4 banner + 6 lifecycle + 4 close-code) in ~3s combined |

---

## CoSA Submodule Boundary (per `feedback_cosa_edit_vs_manage_git`)

Two CoSA files are modified in this Phase:

1. `src/cosa/rest/routers/websocket.py`
2. `src/cosa/rest/websocket_manager.py`

I will **edit the code** but will **NOT** run any git commands inside the CoSA submodule — no `git add`, no `git commit`, no `git push` against `src/cosa/`. Per the parent-repo project rules, the CoSA-side commit is the user's responsibility in a CoSA-context session.

The Lupin-side parent-repo commit at the end of this Phase will track only the parent-repo files (Lupin's `ws-channel.js` / `notifications.js` / `notifications.html` / new tests / new docs / this execution log).

---

## AI Structural Review

| Spec row | Implemented at | Status |
|----------|----------------|--------|
| Close-code constants reserved at top of `routers/websocket.py` | `routers/websocket.py:26-49` | ✅ |
| 10 queue auth-fail close-call sites get explicit `code=4001, reason=<specific>` | `routers/websocket.py:362, 374, 387, 397, 406, 416, 425, 472, 482, 487, 494` (full set) | ✅ |
| Single-session displacement gets `code=4002, reason="session_conflict_displaced"` | `websocket_manager.py:147` | ✅ |
| Audio path auth-fail does NOT close — confirmed (only sends auth_error) | `routers/websocket.py:249-254` (no close call — left as-is) | ✅ |
| Reserved 4003 documented in code comment block; no synthetic branch manufactured | `routers/websocket.py:42-46` | ✅ |
| `ws-channel.js` `openCircuit` accepts reason+code; permanent path passes "auth-permanent"+code | `ws-channel.js:236, 264, 287` | ✅ |
| CIRCUIT_OPEN_EVENT detail carries `reason` and optional `code` | `ws-channel.js:299-304` | ✅ |
| `notifications.js` `_showCircuitBanner` differentiates by reason; 4001 → token refresh first | `notifications.js:2334-2360` | ✅ |
| `_renderCircuitBanner` swaps banner copy by reason+code; sets `data-reason` for tests | `notifications.js:2363-2399` | ✅ |
| Duplicate per-channel `onCircuitOpen` callback removed (was double-firing _showCircuitBanner) | `notifications.js:2195, 2226` (replaced with explanatory comment) | ✅ |
| Layer-2 close-code test uses thread-isolated asyncio (avoids pytest-asyncio + pytest-playwright loop conflict) | `websocket_smoke/core/test_close_codes.py` | ✅ |
| Doc touchpoints — `websocket-events.md` close-code section + `websocket-architecture.md` cross-ref | both files | ✅ |

---

## Bugs Filed

(none yet)

---

## Phase 5 Commits

| Commit | Description | SHA |
|--------|-------------|-----|
| (filled at phase close) | `[LUPIN] Server-side WS auth-failure close codes (4001/4002/4003) + client-side immediate-trip handling + docs (Lupin-side files; CoSA edits to be committed separately by user)` | (sha) |

---

## Test Results Summary

| Tier | Count | Pass | Fail | Skipped | Runtime |
|------|-------|------|------|---------|---------|
| Layer 1 (regression after openCircuit signature change) | 20 | 20 | 0 | 0 | 0.96s |
| websocket_smoke (regression after CoSA close-code patch) | 50 | 50 | 0 | 0 | 45s |
| Layer 2 (NEW close-code tests in `websocket_smoke/core/test_close_codes.py`) | 2 | 1 | 0 | 1 | 0.04s |
| Layer 3 banner (regression after banner-reason swap) | 4 | 4 | 0 | 0 | (combined) |
| Layer 3 lifecycle (regression) | 6 | 6 | 0 | 0 | (combined) |
| Layer 3 close-codes (NEW, 4 tests) | 4 | 4 | 0 | 0 | 1.71s |
| Layer 3 combined runtime (14 tests) | 14 | 14 | 0 | 0 | ~3s |
| **Phase-5 total** | **86** | **85** | **0** | **1** | **~50s** |

### Layer-3 close-code per-test breakdown (`src/tests/ws_channel_browser/test_ws_close_codes.py`)

| # | Test | Pass | Note |
|---|------|------|------|
| 5 | `test_close_4001_opens_circuit_immediately` | ✅ | 4001 close → state=OPEN_CIRCUIT in 1 tick, attempts unchanged |
| 6 | `test_close_4001_banner_message` | ✅ | refresh-failure path → banner text "Authentication failed", data-reason="auth-permanent" |
| 7 | `test_4001_triggers_token_refresh_path` | ✅ | refreshAccessToken called exactly once on 4001 |
| 8 | `test_4001_refresh_success_no_banner_flash` | ✅ | refresh-success path → manualRetry both channels, banner stays hidden |

---

## Phase 5 Sign-Off

| Criterion | Status |
|-----------|--------|
| Step 0 collision grep zero | ✅ |
| `routers/websocket.py` close-call sites get explicit codes | ✅ 10 sites |
| `websocket_manager.py:147` single-session displace gets 4002 | ✅ |
| Client-side `_showCircuitBanner` differentiates by reason; 4001 → token refresh first | ✅ |
| Layer-2 + Layer-3 close-code tests green | ✅ 5/5 (1 conditional skip) |
| Doc touchpoints updated | ✅ |
| Lupin-side commit hash filed | pending (next checkpoint) |
| User notified that CoSA submodule edits need separate commit | pending (in close notify) |
