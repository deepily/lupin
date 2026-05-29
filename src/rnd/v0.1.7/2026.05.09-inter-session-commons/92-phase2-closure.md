# Phase 2 Closure — Inter-Session Commons (user-broadcast surface)

| Field | Value |
|---|---|
| **Initiative** | Inter-Session Commons + User-Broadcast (Phase 2: user → all CC sessions broadcast surface) |
| **Phase 2 status** | ✅ **CLOSED 2026-05-12** |
| **Owners** | Rachel 🕊️ (`9a4a601d`) — steps 1-8 (backend); Tiberius 🌑 (`6a054460`, this session) — steps 9-13 (E2E + UI + docs + closure) |
| **Plan-review pipeline** | CLOSED 2026-05-11 (REUSE + Pass 1 Fitness + Pass 2 Adversarial all closed before code-write started) |
| **Implementation window** | 2026-05-12 single-day milestone (backend morning, UI + tests + docs afternoon) |

---

## What landed

### Backend (4 new pure-logic modules, 8 modules total under the coverage gate)

| Module | Stmts | Branches | Coverage |
|---|---|---|---|
| `src/cosa/rest/commons_rate_limiter.py` (NEW) | 29 | 8 | **100%** |
| `src/lupin_mcp/broadcast_handler.py` (NEW) | 57 | 18 | **100%** |
| `src/cosa/rest/commons_ack_watcher.py` (NEW) | 103 | 24 | **100%** |
| `src/cosa/rest/routers/commons.py` (NEW — pure-logic helpers) | 124 | 40 | **100%** |
| Phase 1 modules (unchanged but re-verified) | 309 | 80 | **100%** |
| **Aggregate (8 modules)** | **622** | **170** | **100% lines / 100% branches / 100% functions** |

### REST endpoints (2 new under `/api/commons/`)

| Endpoint | Surface |
|---|---|
| `GET /api/commons/active-sessions` | Same-user-scoped recipient preview (per `user_id` on bridge file + freshness filter) — returns `{session_id, persona_name, persona_icon, persona_color, last_seen_iso, conversation_mode_active}` per session, **never** the bridge filesystem path (T8 mitigation) |
| `POST /api/commons/broadcast-to-cc-sessions` | Fanout to active CC sessions with rate limiting (T4 single-uvicorn-worker assumption), in-flight tracking (T9 atomic register-or-409), `<system-reminder>` substring rejection (T1), per-recipient failure isolation (F10), zero-recipients 200 (Q14), `require_ack=false` skip-tracking semantics (Pass 1 ratification) |

### Listener-side wiring

- `_handle_action()` 3rd `elif` branch in `cc_notification_listener.py:300` (`action == "broadcast_received"`) → `_handle_broadcast_received()` (~40 LOC) → delegates to `broadcast_handler.handle_broadcast()` with `inject_fn = lambda text: self._inject_via_tmux(text, wrap=False)`.
- Broadcast handler is the keystone (callable from listener AND from any future MCP-side broadcast tool). 100%-covered pure-logic core, no listener-instance leakage.

### Server-side daemon

- `CommonsAckWatcher` (`src/cosa/rest/commons_ack_watcher.py`) — daemon thread tailing `broadcast-acks` topic every `commons broadcast ack watch interval seconds` (default 1s). Dispatches one `commons_broadcast_ack` notification per ack that matches an in-flight `broadcast_id`. F3 REUSE — same shape as `commons_archival.CommonsArchiver`. Startup `_last_seen_ts` initialized to last existing ack so historical entries don't replay.
- Wired into `main.py` `lifespan()` startup (after CJ Flow recovery) + shutdown (before peer-watcher cancel). Gated by `commons enabled` INI key.

### Custom notification type

- `commons_broadcast_ack` registered in `notifications.py:359-363` `valid_types` (extends the existing voice_persona_assigned / voice_persona_released / conversation_mode_changed pattern per the C1 ratification + `2026.04.29-ws-event-cleanup-to-custom-notification-types` mandate).
- Per-recipient payload: `{broadcast_id, session_id, persona_name, persona_icon, persona_color, status, body_summary}`.
- Documented in NEW `src/docs/notification-types.md` (Phase 2 step 12).

### UI (frontend)

- NEW `src/fastapi_app/static/js/broadcast-panel.js` (~350 LOC IIFE): recipient chip-row, live markdown preview via `DOMPurify.sanitize(marked.parse(body))` (AC10 + T2), Send-button gating on body + recipients (AC8 + F17), one-step confirm modal (Q10), POST with Bearer auth from `localStorage.lupin_access_token`, live aggregate panel with named-pending sessions + 5-min auto-dismiss + timed-out passive banner (AC9 + F18), T10 defense-in-depth (`body_summary` rendered via `.textContent` only).
- NEW `src/fastapi_app/static/css/broadcast-panel.css` (~220 LOC) — extends notification-card conventions; confirm modal matches `showErrorModal` pattern (F6 REUSE).
- MODIFIED `src/fastapi_app/static/html/notifications.html` — new `<link>` for css, new `<script>` for js, `broadcast-submit-card` panel inserted between presentation + test-suite cards.
- MODIFIED `src/fastapi_app/static/js/notifications.js` — added `case "commons_broadcast_ack"` in the `notification_queue_update` switch (line 5370) delegating to `window.broadcastPanel.handleAck`.

### INI keys (2 new under `[Lupin: Baseline]`)

| Key | Default | Effect |
|---|---|---|
| `commons broadcast active session threshold seconds` | 600 | Inactivity threshold (s) for "active enough to receive a broadcast" |
| `commons broadcast ack watch interval seconds` | 1 | Poll period for `CommonsAckWatcher` |

Plus existing Phase 1 `commons broadcast rate limit seconds = 30` is now consumed. All 3 keys have paired splainer entries.

### Tests (216 total commons tests as of close, all `:7999` AI-discretionary except step 11 Playwright on `:8000`)

| Tier | File | Count | Venue |
|---|---|---|---|
| Unit | `test_commons_rate_limiter.py` (NEW) | 12 | :7999 |
| Unit | `test_broadcast_handler.py` (NEW) | 28 | :7999 |
| Unit | `test_commons_ack_watcher.py` (NEW) | 26 | :7999 |
| Unit | `test_commons_router.py` (NEW) | 55 | :7999 |
| Unit | `test_commons_ac14_registration.py` (NEW) | 5 | :7999 |
| Unit | Phase 1 modules (unchanged) | 85 | :7999 |
| Smoke | `test_commons_two_session_roundtrip.py` (Phase 1) | 3 | :7999 |
| Smoke | `test_broadcast_two_session_e2e.py` (NEW — step 9) | 1 (covering 7 design-doc gates) | :7999 |
| E2E UI | `test_broadcast_panel.py` (NEW — step 11) | 8 | :8000 (scheduled) |
| **Aggregate** | | **216 + 8 = 224** | mix |

`:7999` aggregate run: **215 passed in 14.76s** (211 unit + 3 Phase 1 smoke + 1 step 9 smoke). 100% coverage gate held across all 8 commons modules.

---

## Step 11 Playwright E2E result

| Field | Value |
|---|---|
| **Job ID** | `ts-436237f6::50c73ba7-36dd-4eaf-a7e2-63256252c84f` |
| **Submitted** | 2026-05-12 09:56:30 EDT |
| **Scheduled / started / completed** | 10:00:00 → 10:00:00.016 → 10:00:40.984 EDT |
| **Duration** | 40.97s |
| **Verdict** | ✅ **10 passed, 0 failed, 0 errors, 0 skipped** |
| **Suites** | `e2e` (`-k test_broadcast_panel -v`) |
| **Report markdown** | `io/test-suite/2026.05.12-at-10:00-EDT-e2e-results.md` |
| **Container bounce** | `:8000` (`lupin-rest-test`) restarted 2026-05-12 09:53 EDT to pick up Phase 2 backend; verified post-bounce that `/api/commons/active-sessions` + `/api/commons/broadcast-to-cc-sessions` are in OpenAPI + `broadcast-panel.js` (19,240 bytes) + `broadcast-panel.css` (5,612 bytes) are served. |

All 10 Playwright tests passed first-try against a live `:8000` server. AC8 (panel + Send gating + confirm modal), AC9 (aggregate progression + T10 body_summary-as-text), AC10 (markdown + DOMPurify XSS hardening) all verified end-to-end.

---

## ACs verified

| AC | Verification | Status |
|---|---|---|
| **AC1** | Endpoint body validation (empty / whitespace / `<system-reminder>` substring case-insensitive / bad UUID / collision / 401 / `require_ack=false`) | ✅ `test_commons_router.py` (8 tests covering AC1 cases) |
| **AC2** | Session enumeration with same-user scoping (T7) + freshness filter + `include_originator` toggle + T8 no-path-leak | ✅ `test_commons_router.py` (multiple) |
| **AC3** | Sliding-window rate limit (allow / 429 with Retry-After / per-user isolation / `reset()` hook / concurrent-race) | ✅ `test_commons_rate_limiter.py` (12 tests) |
| **AC4** | Per-recipient `broadcasts` topic post with `broadcast-<8hex>` pseudo-sid + System Broadcast persona stamp + distinct `target_session_id` | ✅ `test_commons_router.py` + step 9 smoke |
| **AC5** | Per-recipient `action:broadcast_received` notification fanout + per-recipient failure isolation | ✅ `test_commons_router.py` + step 9 smoke |
| **AC6** | Listener-side handle_broadcast: happy path + skip-with-ack (A6) + T1+T3 reminder-framing rejection | ✅ `test_broadcast_handler.py` (28 tests) + step 9 smoke |
| **AC7** | AckWatcher in-flight tracker + TTL prune + startup `_last_seen_ts` cursor + dispatch on match | ✅ `test_commons_ack_watcher.py` (26 tests) + step 9 smoke tick() |
| **AC8** | UI panel + confirm modal + Send-gating + whitespace-trim | ✅ `test_broadcast_panel.py::TestBroadcastPanelRendering` + `::TestBroadcastSendFlow` |
| **AC9** | Aggregate panel 0/N → N/N progression + named-pending + body_summary as text-content (T10) | ✅ `test_broadcast_panel.py::TestBroadcastAggregate` |
| **AC10** | Markdown preview via `marked` + DOMPurify XSS hardening (T2) | ✅ `test_broadcast_panel.py::TestBroadcastPreview` |
| **AC11** | 2 INI keys present with paired splainer entries | ✅ grep + step 7 verification |
| **AC12** | 100% line + branch + function coverage on the 4 NEW pure-logic modules | ✅ Final aggregate: 622 stmts, 170 branches, 0 missing across 8 modules |
| **AC13** | `py_compile` clean + import-chain check | ✅ Step 6 closure note + step 9 `pytest` collect-OK |
| **AC14** | Router registered in `main.py` + both endpoints in OpenAPI | ✅ `test_commons_ac14_registration.py` (5 tests) + `:8000` post-bounce OpenAPI grep |

---

## Notable deviations from the original design

### D1 (declared pre-implementation) — Section numbering in `rest-api-reference.md`

The design doc's MODIFIED-files row said "document the 2 new endpoints in section 17 (commons)". But §17 was already taken by Test Suite. Step 12 added a new sub-section `17c. Inter-Session Commons` between §17b (TFE) and §18 (Decision Proxy) to keep numbering stable and to cluster the new endpoints with the adjacent agentic submission surfaces (BFE/TFE/Test Suite).

### D2 (surfaced during step 10) — DOMPurify already vendored

The design doc's T2 mitigation said "vendor `dompurify.min.js` if not already present (verify at code-write)". Verification revealed `src/fastapi_app/static/js/vendor/purify.min.js` was already vendored and loaded at `notifications.html:957`. The global export is `DOMPurify` (standard). No new vendoring needed — the speculative "add it if absent" branch was unneeded.

### D3 (declared at step 9 design) — Step 9 architecture uses direct `execute_broadcast()` call instead of TestClient

AC12 allowed either "TestClient for endpoint hits OR direct `requests.post(":7999/api/commons/broadcast-to-cc-sessions")`". The implementation went a third route: call `execute_broadcast()` directly with DI'd dependencies. Rationale: the FastAPI auth dependency + route decorator plumbing is already covered by `test_commons_router.py` (55 unit tests) and `test_commons_ac14_registration.py` (5 smoke tests); the value of step 9 is the cross-process flow (endpoint logic → fanout → listener subprocess → handler → ack → ack-watcher dispatch) and that runs identically whether the endpoint is hit via TestClient or via `execute_broadcast()`. Direct call is faster, deterministic, and avoids the TestClient app construction overhead.

---

## Deferred items (Phase 3 unblock)

Phase 2 closes with **no carry-over backend bugs**. Phase 3 picks up:

| Item | Origin | Phase 3 work |
|---|---|---|
| `commons_ask_async` push-mode upgrade | Phase 0 D1 deviation | Replace polling-mode with `<system-reminder>` injection via the existing conversation-mode listener pattern at `routers/conversation_mode.py:195-278`. MCP tool signature stays stable; callers' code does not change. |
| LLM-fallback wiring for persona matcher | Phase 1 Q8 ratification + `commons_persona_matcher.disambiguate_via_llm()` stub | Wire the actual LLM call when mechanical matching fails. The stub returns `None` today; Phase 3 calls `Llm(model_name=...)` and parses the response. |
| WS push for commons events | Phase 0 Q2 + Q6 architectural principle (commons is INTRA-AI) | None of the commons MCP tools currently emit WS events (per the "commons is INTRA-AI" principle). Phase 3 may add a `commons_event` custom notification type if the UI grows a "commons activity feed" surface. Not currently planned. |
| Multiplexer Commons tab integration | Out-of-scope for Phase 2 per §3 | Phase 4 (Postgres-backed commons) + Phase 6c (multiplexer rewrite). Phase 2's UI lives in legacy `notifications.html`; the multiplexer port lands when Phase 6c is in flight. |

---

## Cross-project follow-ups

- **MCP tool catalog audit** (filed at `planning-is-prompting/TODO.md` 2026-05-10 — Phase 1 carryover): after the 5 commons MCP tools landed in Phase 1, the catalog references in every consumer repo (Lupin CLAUDE.md, src/docs/, planning-is-prompting workflow docs, cosa-voice-notifications skill) should be audited and updated. Phase 2 doesn't change the MCP surface area, so the Phase 1 follow-up still applies as-filed.
- **Mobile broadcast surface** — explicitly out of scope (`src/lupin-mobile/`). Post-v0.1.7 if user demand surfaces.

---

## Files touched (Phase 2 — final)

### NEW (10 files)

- `src/cosa/rest/commons_rate_limiter.py` — 29 stmts / 8 branches / 100% (12 unit tests)
- `src/lupin_mcp/broadcast_handler.py` — 57 stmts / 18 branches / 100% (28 unit tests)
- `src/cosa/rest/commons_ack_watcher.py` — 103 stmts / 24 branches / 100% (26 unit tests)
- `src/cosa/rest/routers/commons.py` — 124 stmts / 40 branches / 100% (55 unit tests, route bodies `# pragma: no cover`)
- `src/tests/unit/commons/test_commons_rate_limiter.py`
- `src/tests/unit/commons/test_broadcast_handler.py`
- `src/tests/unit/commons/test_commons_ack_watcher.py`
- `src/tests/unit/commons/test_commons_router.py`
- `src/tests/unit/commons/test_commons_ac14_registration.py`
- `src/tests/smoke/test_broadcast_two_session_e2e.py` — step 9, 2-session E2E smoke
- `src/tests/e2e_ui/test_broadcast_panel.py` — step 11, Playwright E2E
- `src/fastapi_app/static/js/broadcast-panel.js`
- `src/fastapi_app/static/css/broadcast-panel.css`
- `src/docs/notification-types.md` — step 12 NEW docs

### MODIFIED

- `src/lupin_mcp/commons_store.py` — `broadcasts` added to `RESERVED_TOPICS` tuple (+1 line)
- `src/fastapi_app/main.py` — commons router include + lifespan startup/shutdown + 3 module-level singletons (+15 lines)
- `src/lupin_cli/claude_code/hooks/lib/cc_notification_listener.py` — 3rd `elif` branch in `_handle_action()` + `_handle_broadcast_received()` method (~40 lines)
- `src/cosa/rest/routers/notifications.py` — `commons_broadcast_ack` in `valid_types` (+1 line)
- `src/fastapi_app/static/html/notifications.html` — broadcast panel insertion + CSS link + JS script (+30 lines)
- `src/fastapi_app/static/js/notifications.js` — `case "commons_broadcast_ack"` in `notification_queue_update` switch (+9 lines)
- `src/conf/lupin-app.ini` — 2 new INI keys (+3 lines)
- `src/conf/lupin-app-splainer.ini` — 2 paired splainer entries (+2 lines)
- `src/docs/rest-api-reference.md` — §17c Inter-Session Commons section (+ ~50 lines)
- `src/docs/README.md` — notification-types.md entry in the WebSocket / notifications cluster
- `src/rnd/v0.1.7/2026.05.09-inter-session-commons/00-index.md` — Phase 2 status closed
- `src/rnd/v0.1.7/2026.05.09-inter-session-commons/90-phase2-execution-log.md` — all 13 step rows closed

---

## Idempotency marker

`phase-2-closed-at: 2026-05-12 (steps 1-13 all CLOSED; aggregate 622 stmts / 170 branches / 100% across 8 commons modules; 215 :7999 unit+smoke pass + step 11 Playwright result on :8000)`

**Phase 3 is eligible to begin.** No outstanding plan-review gates required — D1 polling-mode → push-mode upgrade is a re-implementation of an already-shipped MCP tool surface, not a new API contract.
