# 2026.05.05 — Claude Code Dispatch Endpoint Retirement

**Status**: ✅ Plan ratified 2026-05-05 (session 1a8900ee). Implementation in progress.
**Bug-fix-queue source**: 🔥 IMMEDIATE entry "eliminate the `/api/claude-code/ws/{task_id}` WebSocket endpoint cluster of bugs" (filed 2026-05-04 by session ec746144, promoted to top-of-queue by user directive 2026-05-04 PM).
**Predecessor doc**: `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/04-phase3-transport-design.md` §"Claude Code transport — intentionally absent" (where Multiplexer Phase 3 quarantined this endpoint pending today's retirement).
**Multiplexer Phase 4 dependency**: D1 ratification was halted on `ClaudeCodeTransport`-against-this-endpoint. **Unblocked** by this retirement.
**Companion file**: `90-execution-log.md` (phase-by-phase progress, appended at each phase boundary).

---

## Context

**Why this change is being made.** `src/cosa/rest/routers/claude_code.py` is an architectural fossil — the first cut at Claude Code dispatch (filed 2026-01-08), built before CJ Flow's cj-integrated path, before auth-mode-jwt, and before `WebSocketManager` became the canonical WS routing layer. It has four catalogued structural defects (URL contract mismatch, no auth, module-level state, parallel pre-cj-flow path) and was promoted to top-of-queue by user directive 2026-05-04 PM after the Multiplexer Phase 4 review halted on a `ClaudeCodeTransport` aimed at this endpoint.

**What replaces it.** The cj-flow-integrated sibling `POST /api/claude-code/queue/submit` at `src/cosa/rest/routers/claude_code_queue.py` — JWT-authenticated, creates a `ClaudeCodeJob`, rides the standard CJ Flow queue + `WebSocketManager` + per-user-or-listener dispatch plane.

**Known parity gap (informs the disable strategy).** The cj-flow `ClaudeCodeJob` lacks bidirectional control (`inject` / `interrupt` / `end_session`) and emits only coarse-grained per-job notifications (start / complete / fail), not per-turn streaming. So **Option B / INTERACTIVE controls and the live-streaming output panel cannot be migrated today**; they must be visibly disabled with retirement banners so any hidden dependency surfaces loudly. Per user direction: "definitively going away today" with anything that can't be cleanly migrated "temporarily and obviously disabled."

**Mobile scope (user decision, conversation 2026-05-05).** `src/lupin-mobile/lib/features/claude_code/data/claude_code_repository.dart:18` is a live caller. Per nested-repo-management rules, mobile work happens in a mobile session. Today: **breadcrumb-only** — retirement-pointer footnotes added to mobile rnd docs, no Dart edits. Mobile feature 404s until addressed separately. Loudness is intentional.

**Intended outcome by end of session.** Server file deleted; `main.py` wiring removed; frontend submits exclusively through the queue path; orphaned UI controls show prominent "Retired 2026-05-05" banners; orphaned E2E tests skipped with breadcrumb; docs reflect the change; verification passes.

---

## The bug, viewed structurally

The endpoint is anomalous because it predates and bypasses **every** convention in the WS / queue / auth stack:

- **URL contract is broken.** Server returns `websocket_url = "/ws/claude-code/{task_id}"` (`claude_code.py:134`) but the WS is mounted at `/api/claude-code/ws/{task_id}` (prefix `claude_code.py:25` + route `claude_code.py:506`). The lone consumer (`notifications.js:3915`) hardcodes the served URL, ignoring the field — proof nobody has ever integrated against the documented contract.
- **Auth-free in a JWT-enforced server.** `await websocket.accept()` is unconditional at `claude_code.py:521`. No `auth_request` envelope, no JWT verification. Compare `routers/websocket.py:351-491`.
- **Module-level state.** `active_sessions` (line 28) + `websocket_connections` (line 31) — not durable, not multi-worker safe, invisible to CJ Flow / `WebSocketManager`.
- **Parallel pre-CJ-Flow path.** `claude_code_queue.py:5-6` already explicitly contrasts itself with this dispatcher in its docstring. Two paths exist; the newer one is convention-compliant; the older one was never retired.

Most Lupin bugs are bugs *inside* systems that comply with conventions. This is a **compliance failure across every convention simultaneously** — that's why "obviously disable, don't silently mask" is the correct strategy: hidden dependencies surface as 404s and visible banners, not as silent NoOps.

---

## Phases

### Phase 0 — Serialize plan into repo (this document) ✅

- Created `src/rnd/v0.1.7/2026.05.05-claude-code-dispatch-retirement/01-plan.md` (this file).
- Created paired `90-execution-log.md` (phase-by-phase scaffold).
- Skipped `src/rnd/README.md` per-file link — the index is version-level only and recent v0.1.7 entries don't follow the per-file-link convention either; that's a separate doc-health issue.

### Phase 1 — Server retirement (CoSA + Lupin)

Server-first ordering is intentional. A 404 between Phase 1 and Phase 2 is a *visible* signal that surfaces stale callers (curl, mobile, leftover tabs) — that's the user's "obviously disabled" mandate operating at the network layer.

1. Delete `src/cosa/rest/routers/claude_code.py` (CoSA submodule edit; user commits separately in CoSA session).
2. `src/fastapi_app/main.py`:
   - Remove `claude_code` from the line-66 router import; leave `claude_code_queue`.
   - Remove `app.include_router(claude_code.router)` (line 779); leave the line-780 `claude_code_queue` registration.
3. **Do not touch** `src/cosa/orchestration/` — it's shared with `src/cosa/agents/claude_code/job.py` (cj-flow path) and stays live.
4. Verify import chain end-to-end:
   ```
   python -c "from fastapi_app.main import app; print( len( app.routes ) )"
   python -c "from cosa.agents.claude_code.job import ClaudeCodeJob; print( 'ok' )"
   ```
5. Confirm uvicorn auto-reload picks it up on `:7999` (no manual bounce per `feedback_fastapi_auto_reload`).

### Phase 2 — Frontend: kill dead callers, plant retirement banners

Single atomic Lupin commit covering JS + HTML + CSS + cache-bust.

**`src/fastapi_app/static/js/notifications.js`** — remove (full method bodies + state):

| Symbol | Lines | Notes |
|---|---|---|
| `submitClaudeCodeDirect` | 3867-3911 | calls dead `/api/claude-code/dispatch` |
| `connectClaudeCodeWebSocket` | 3913-3946 | hardcodes dead WS URL |
| `handleClaudeCodeMessage` | 3948-4003 | renders dead WS payloads |
| `injectClaudeCode` | 4005-4042 | POSTs dead `/{task_id}/inject` |
| `interruptClaudeCode` | 4044-4070 | POSTs dead `/{task_id}/interrupt` |
| `endClaudeCodeSession` | 4072-4101 | POSTs dead `/{task_id}/end` |
| `this.claudeCodeWs` | 40 | state, no longer needed |
| `this.currentClaudeCodeTaskId` | 43 | state, no longer needed |

**`src/fastapi_app/static/js/notifications.js`** — keep but rewire:

- `submitClaudeCode` (3774): strip the `#cc-execution-mode` branch; always route to `submitClaudeCodeToQueue`.
- `submitClaudeCodeToQueue` (3803-3865): unchanged. This is the survivor.
- Remove the four orphaned event-handler blocks: lines 1600 (`#cc-inject-btn`), 1608 (`#cc-interrupt-btn`), 1616 (`#cc-end-btn`), 1635 (`#cc-inject-input` Enter). Keep 1584 (`#cc-submit`), 1624 (`#cc-task-type` change), 1646 (`#cc-prompt` Ctrl+Enter).

**`src/fastapi_app/templates/notifications.html`** — slim the dispatcher card (lines 116-209):

- Remove the `#cc-execution-mode` toggle row (single-path now).
- Remove `INTERACTIVE` `<option>` from `#cc-task-type` dropdown (no working flow without inject parity).
- Replace the `#cc-option-b-controls` block with a `<div class="cc-retired-banner">` reading: **"INTERACTIVE control panel retired 2026-05-05. The legacy `/api/claude-code/dispatch` endpoint has been eliminated. Inject / interrupt / end-session controls will return when `ClaudeCodeJob` gains bidirectional control. See bug-fix-queue.md retirement entry."**
- Replace the `#cc-response` `<pre>` element's *initial inner content* with a banner reading: **"Live per-turn streaming retired 2026-05-05. Submitted jobs now appear in the CJ Flow accordion below as `cc-*` job cards. This panel is preserved as a DOM contract; it no longer streams."** Keep the `<pre id="cc-response">` element itself — `submitClaudeCodeToQueue` references it at line 3853.
- Keep all of: `#cc-prompt`, `#cc-project`, `#cc-task-type` (BOUNDED-only now), `#cc-dry-run`, `#cc-stt-button`, `#cc-cost`, `#cc-loading`, `#cc-submit`. These all work with the queue path.
- **Do not touch** the session-strip block (`#cc-session-strip`, `#cc-strip-icons`, `#cc-strip-toggle`, `#cc-hide-inactive-toggle`) — separate feature, lives on.

**`src/fastapi_app/static/css/notifications.css`**:

- Add a prominent `.cc-retired-banner` rule (yellow background, 1px border, padding, italic copy) — designed to be impossible to miss in dev tools.
- Pre-edit grep for orphan rules: `grep -n -E "cc-inject|cc-interrupt|cc-end|cc-option-b|cc-response|cc-session-info|cc-task-id|cc-status" src/fastapi_app/static/css/notifications.css`.
- Keep all session-strip rules.

**Cache-bust**: bump `notifications.html` query string to `v=20260505a` so browsers force-fetch.

### Phase 3 — Tests: skip-with-breadcrumb, do not delete

E2E tests live for archeological reasons; deleting them erases the restoration paper trail.

- `src/tests/e2e_ui/test_job_dispatch.py` — for any test referencing the orphaned selectors `notifications-cc-inject-input`, `notifications-cc-inject-btn`, `notifications-cc-interrupt-btn`, `notifications-cc-end-btn`: add per-test `@pytest.mark.skip(reason="Targets retired /api/claude-code/dispatch INTERACTIVE controls. Restore when ClaudeCodeJob gains inject/interrupt/end_session — see bug-fix-queue.md 2026-05-05 retirement entry.")`. Tests targeting `#cc-prompt` / `#cc-submit` / `#cc-task-type` (queue path) remain active.
- `src/tests/e2e_ui/test_notifications_sections.py:135` — reference to `notifications-cc-card`: leave alone; the card still exists post-retirement.
- `src/tests/e2e_ui/test_cc_session_strip_and_focus.py` — separate feature, do not touch.
- Smoke tests `src/tests/smoke/test_claude_code_dry_run_smoke.py` and `src/tests/smoke/test_claude_code_max_subscription.py` — already exercise the survivor path. **Leverage these as the parity baseline** in Phase 5.

### Phase 4 — Docs

- `src/docs/rest-api-reference.md`: remove dead-endpoint rows around lines 27-33 (and any duplicates near 168/173); add a "Retired endpoints" footnote pointing at `/api/claude-code/queue/submit` + the bug-fix-queue retirement entry.
- `src/docs/fastapi/api.md`: regenerate via `src/scripts/generate-api-docs.sh` after Phase 1 lands.
- `src/rnd/v0.1.1/2026.01.08-cold-call-path-1-ui-card-plan.md`: append retirement-pointer footnote at the top, do not rewrite.
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/04-phase3-transport-design.md:18` — already documents retirement; leave alone.
- `src/fastapi_app/static/js/multiplexer/transport/index.ts:9-16` — already documents retirement; leave alone.
- **Mobile breadcrumbs (no Dart edits)**:
  - Append retirement-pointer footnote to `src/lupin-mobile/src/rnd/v0.1.6-migration/2026.04.15-tier-3-queue-and-claude-code-plan.md`.
  - Append retirement-pointer footnote to `src/lupin-mobile/src/rnd/v0.1.6-migration/2026.04.15-resync-mobile-with-lupin-api-v0.1.6.md`.
  - Both name `claude_code_repository.dart:18` + `claude_code_models.dart` as live callers and link back to this plan + the bug-fix-queue entry.

### Phase 5 — Verification

| Check | Command | Expected |
|---|---|---|
| Server starts clean | `python -c "from fastapi_app.main import app; print(len(app.routes))"` | route count drops by 6, no ImportError |
| ClaudeCodeJob import survives | `python -c "from cosa.agents.claude_code.job import ClaudeCodeJob; print('ok')"` | "ok" |
| Server-side residue grep | `grep -rn -E "/api/claude-code/dispatch\|/api/claude-code/ws/\|/ws/claude-code/\|claude_code\.router" src/cosa/ src/fastapi_app/` | zero hits |
| Frontend residue grep | `grep -rn -E "claudeCodeWs\|currentClaudeCodeTaskId\|connectClaudeCodeWebSocket\|handleClaudeCodeMessage\|submitClaudeCodeDirect\|injectClaudeCode\|interruptClaudeCode\|endClaudeCodeSession" src/fastapi_app/static/js/` | zero hits |
| Lupin unit suite | `pytest src/tests/unit/` | green |
| WebSocket smoke | `bash src/scripts/run-websocket-smoke-tests.sh` | green |
| Queue path smoke (:7999) | `python src/tests/smoke/test_claude_code_dry_run_smoke.py` | 6 scenarios pass |
| Live UI probe (:7999) | open notifications page, dev tools Network; submit BOUNDED dry-run | request only to `/api/claude-code/queue/submit`; zero hits to dead endpoints; banners visible; job lands in CJ Flow accordion |
| Dead-endpoint 404 sanity | `curl -X POST http://localhost:7999/api/claude-code/dispatch` | 404 |

E2E full sweep on `:8000` — schedule via `/api/test-suite/submit` only after user-confirms a clean slot.

### Phase 6 — Wrap

- Update `bug-fix-queue.md`: move the "🔥 IMMEDIATE" entry to "Completed" with commit hash + summary.
- Append session entry to `history.md`.
- TODO.md follow-up: "Restore Claude Code INTERACTIVE controls when `ClaudeCodeJob` gains `inject` / `interrupt` / `end_session`" with mobile-port subtask.
- Note Multiplexer Phase 4 D1 ratification unblocked in the execution log.

---

## Critical files

**Delete**:
- `src/cosa/rest/routers/claude_code.py` (CoSA, ~620 lines)

**Edit (server)**:
- `src/fastapi_app/main.py` (lines 66, 779)

**Edit (frontend)**:
- `src/fastapi_app/static/js/notifications.js` (8 method/handler removals, 1 method rewire)
- `src/fastapi_app/templates/notifications.html` (dispatcher card lines 116-209: slim + plant banners)
- `src/fastapi_app/static/css/notifications.css` (add `.cc-retired-banner`, prune orphans)

**Edit (tests)**:
- `src/tests/e2e_ui/test_job_dispatch.py` (skip marks for INTERACTIVE-control tests)

**Edit (docs)**:
- `src/docs/rest-api-reference.md`
- `src/docs/fastapi/api.md` (regenerate via script)
- `src/rnd/v0.1.1/2026.01.08-cold-call-path-1-ui-card-plan.md`
- `src/lupin-mobile/src/rnd/v0.1.6-migration/2026.04.15-tier-3-queue-and-claude-code-plan.md`
- `src/lupin-mobile/src/rnd/v0.1.6-migration/2026.04.15-resync-mobile-with-lupin-api-v0.1.6.md`

**Reused (do not touch)**:
- `src/cosa/orchestration/` (shared with `ClaudeCodeJob`)
- `src/cosa/rest/routers/claude_code_queue.py` (the survivor)
- `src/cosa/agents/claude_code/job.py` (`ClaudeCodeJob`)
- `src/cosa/rest/agentic_job_factory.py:199-212` (`"agent router go to claude code"` dispatch)
- `src/cosa/rest/websocket_manager.py` (canonical dispatch helper used by the queue path)

---

## Cross-repo commit shape (FYI; user owns commits)

- **CoSA submodule**: 1 file deletion (`claude_code.py`). Committed by user in CoSA session.
- **Lupin**: 1 commit covering main.py + JS + HTML + CSS + tests + docs + mobile breadcrumbs + this R&D plan + execution log.
- I will not run any git commands across this work — per `feedback_never_auto_commit_push` and `feedback_lupin_only_never_cosa`.

## Risk surface

- **Browser cache stickiness**: cache-bust the HTML query string aggressively in Phase 2.
- **CoSA/Lupin commit ordering**: not planned here; user handles per session-end ritual.
- **Mobile field 404s** until mobile session ports it. Intentional.
- **No live `:8000` work today**. All verification on `:7999` plus mocked unit/smoke. Full E2E sweep deferred to user-scheduled slot.
