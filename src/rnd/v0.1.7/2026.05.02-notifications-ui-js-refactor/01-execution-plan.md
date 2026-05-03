# Notifications UI Rebuild — Execution Plan

**Date**: 2026-05-03
**Status**: DRAFT — pending user decisions on §"Strategic recommendations"
**Companion to**: `00-synthesis-and-roadmap.md` (long-form synthesis + phase rationale)
**Type**: Documentation only — no code lands until user approves Phase 0 decisions and Phase 1 design doc.

---

## Context

The current notifications surface (`src/fastapi_app/static/html/notifications.html` + `src/fastapi_app/static/js/notifications.js`, 16,797 lines, ~115 instance fields, ~279 methods on `NotificationsUI`) has accumulated to the point where two independent senior reviews (Claude Opus 4.7 + OpenAI deep-research, both at `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/`) flag the monolith as the dominant architectural risk.

The user has chosen **parallel greenfield rebuild** rather than in-place refactor: a new UI built from scratch at a new URL, with all the lessons from both reviews baked in from line one. The current `notifications.html` enters maintenance freeze (only the parked voice-persona /clear preservation Fix 4 lands as a patch) and is deprecated at cutover.

`00-synthesis-and-roadmap.md` (sibling file) is the long-form rationale. This document is the executable companion — file paths, recommendations, verification, risk register.

**Outcome**: a working second notifications-class UI at a new URL with full feature parity, modular module tree, type-checked, observability-instrumented, CSP-strict-ready, 100% covered by automated tests, validated by adversarial review before cutover.

## Out of scope

- Token storage migration off `localStorage` (requires server HttpOnly-cookie + CSRF redesign — flag as follow-up only).
- Service Worker / Background Sync offline outbox (deferred to post-cutover).
- Modifying current `notifications.html` / `notifications.js` (frozen until cutover; only voice-persona Fix 4 lands).
- Switching the app to React/Vue/Svelte (vanilla TS + tagged templates is the chosen path).
- CoSA-submodule git operations — user owns those (this plan edits `src/cosa/rest/routers/pages.py` for the route registration; user commits in CoSA context).

## Strategic recommendations (user confirmation pending)

| Decision | Recommendation | Rationale |
|---|---|---|
| Name + URL | **`inbox` at `/app/inbox`** | Semantic accuracy (it IS an inbox); short; URL slot is unoccupied per route table check |
| Language | **TypeScript with `tsc --strict`** | First TS in the project; required for sustainability of a 5-10k-line app with state machines; greenfield removes migration cost |
| Build chain | **`esbuild`** via `src/scripts/build-inbox.sh` (first JS build tooling in the project) | Single binary, no node_modules sprawl, content-hashed output kills the manual `?v=` ritual |
| State machines | **XState** for high-churn modules (auth, TTS playback, action-required, connection); plain reducers everywhere else | Proven, designed for actor model; both reviews flagged the need |
| Renderer primitive | **Tagged-template `html` helper** + keyed render units, no framework | Vanilla, CSP-friendly, works without component runtime |
| `ws-channel.js` | **Copy + apply Claude §1.1 (binary-frame fix) + §2.2 (lifecycle out) + §2.5 (no JSON round-trip)**, port to TS | Greenfield isolation; original keeps serving current `notifications.html` until cutover |
| Per-phase user gate | **Yes** — design doc lands, user approves, then code begins for that phase | Lower risk; matches established Lupin BFE/TFE pattern |
| Adversarial review | **Both** — separate Claude agent (clean context) + new OpenAI deep-research pass | Two independent lenses already proved valuable in Phase 0 |

## Critical files

### Existing (read-only references, except where noted)

| Path | Role |
|---|---|
| `src/cosa/rest/routers/pages.py:24-40,69-71` | Route table + `/app/notifications` handler — pattern to mirror for `/app/inbox`. **Will edit** to add new route. CoSA file — user commits. |
| `src/fastapi_app/main.py:795,802` | Router include + `/static` mount — no changes needed |
| `src/fastapi_app/static/html/notifications.html` | Reference for feature parity (CSS classes, data-testid, layout) |
| `src/fastapi_app/static/js/notifications.js` | Reference for feature semantics, NOT for code reuse |
| `src/fastapi_app/static/js/ws-channel.js` | Source for the TS port (copy + fixes; do NOT modify in place) |
| `src/fastapi_app/static/js/tts-audio-cache.js` | Reference for cache contract |
| `src/fastapi_app/static/js/job-completion-cache.js` | Reference for cache contract |
| `src/fastapi_app/static/js/audio-recorder.js` | Reference for recorder semantics + Claude §4.5 fix |
| `src/fastapi_app/static/html/dev-tools.html` | Card pattern — register new "Inbox (next-gen)" card here |
| `src/cosa/rest/routers/websocket.py:314,437-448` | WS auth contract — unchanged |
| `2026.05.02-notifications-ui-js-refactor-analysis-claude.md` | Tactical findings input |
| `2026.05.02-notifications-ui-js-refactor-analysis-openai.md` | Architectural findings input |
| `00-synthesis-and-roadmap.md` | Full synthesis (drafted pre-plan-mode) |

### New files (created across phases)

| Path | Phase | Purpose |
|---|---|---|
| `src/fastapi_app/static/html/inbox.html` | 1 | Shell entry, served at `/app/inbox` |
| `src/fastapi_app/static/css/inbox/*.css` | 5+ | Modular CSS port |
| `src/fastapi_app/static/js/inbox/boot.ts` + module tree | 1-7 | New TS module tree (full layout in synthesis doc §4.2) |
| `src/fastapi_app/static/js/inbox/transport/ws-channel.ts` | 3 | Port of `ws-channel.js` with §1.1+§2.2+§2.5 fixes applied |
| `src/scripts/build-inbox.sh` | 1 | esbuild driver |
| `tsconfig.json` (project root) | 1 | TS strict config — **first in project** |
| `src/fastapi_app/static/js/inbox/.eslintrc.json` | 1 | Bans `window.notificationsUI` / `window.inboxUI` global access |
| `01-phase0-decisions.md` (this dir) | 0 | Decisions captured after this plan is approved (separate file from this one) |
| `02-phase1-scaffolding-design.md` (this dir) | 0→1 | Drafted at end of Phase 0; approved before Phase 1 code |
| `03-phase2-foundation-design.md` … `10-phase9-cutover-design.md` (this dir) | per phase | One design doc per phase, drafted + approved before that phase's code |
| `90-execution-log.md` (this dir) | spans all | Single log, sectioned by phase, appended-to as each phase lands |
| `src/tests/unit/inbox/*.test.ts` | per phase | Unit tests per module |
| `src/tests/smoke/test_inbox_*.py` | per phase | Smoke tests per phase milestone |
| `src/tests/e2e_ui/test_inbox_parity.py` | 6 | Parity E2E vs current `/app/notifications` |

## Phase plan

| Phase | Focus | Code? | Test venue |
|---|---|---|---|
| **0** | Decisions captured (this plan + answered questions). No code. | No | — |
| **1** | Scaffolding: `inbox.html` + FastAPI route + `tsconfig.json` + `build-inbox.sh` + empty `boot.ts` that logs "hello, inbox". Dev-tools card. | Tiny | :7999 smoke (page loads) |
| **2** | Foundation services: `AuthManager` (`navigator.locks` from day one), `ApiClient` (`AbortSignal.any` baseline), `StorageService`, `EventBus`, `BroadcastChannel("lupin")`. Unit-tested in isolation. | Yes | :7999 unit |
| **3** | Transport: ws-channel.ts (port + Claude §1.1 + §2.2 + §2.5 fixes); `QueueTransport` / `AudioTransport` / `ClaudeCodeTransport` thin wrappers; orchestrator owns lifecycle. | Yes | :7999 unit + WS smoke |
| **4** | Domain stores: `NotificationStore`, `JobStore`, `AudioStore`, `ActionRequiredStore`, `SenderStore` — XState actors for high-churn, plain reducers elsewhere. Mocked transports for tests. | Yes | :7999 unit |
| **5** | Renderer: tagged-template `html` helper + first pane (notifications list) + CSS port. Mock data drives initial render. | Yes | :7999 unit + smoke |
| **6** | Feature parity: jobs queue (todo/run/done/dead/history), TTS playback + queue, action-required countdown, focus-tray (incl. hide-inactive toggle from Session 4ede5bad), voice-persona display, conversation-mode UI, sender cards, audio recorder, focus-mode. **Each feature its own PR.** | Yes | :7999 unit + smoke; :8000 (scheduled) E2E parity |
| **7** | Hardening: User Timing + Long Tasks + OTel browser SDK, CSP report-only, Trusted Types, BroadcastChannel cross-tab coordination, accessibility audit. | Yes | :7999 unit; :8000 (scheduled) integration |
| **8** | **Adversarial review + viability gate**: full automated pyramid + parallel adversarial reviews (separate Claude agent + new OpenAI deep-research pass) of every tracking doc and the implementation. Cutover blocked until pass. | Tests + reviews only | :7999 fast tiers + :8000 (scheduled) full pyramid |
| **9** | Cutover: feature-flag rollout, redirect (or banner on) `/app/notifications`, deprecate after 1 release. | Minimal | :7999 smoke + :8000 (scheduled) E2E |

## Verification

### Per-phase end-to-end checks (executed by Claude, not the user, per `feedback_user_is_never_a_tester`)

| Phase | What to verify | How |
|---|---|---|
| 1 | Route serves HTML; build artifact exists; dev-tools card renders | `curl -I http://localhost:7999/app/inbox` (200), build script succeeds (`bash src/scripts/build-inbox.sh`), Playwright smoke loads dev-tools.html and clicks the inbox card |
| 2 | All four services unit-tested with mocked dependencies | `pytest src/tests/unit/inbox/` — auth lock dedup, api timeout/retry, storage typed JSON, eventbus pub/sub |
| 3 | Three transports auth + receive events + reconnect | WS smoke — connect against :7999 dev server, verify `auth_success`, kill connection, verify reconnect with backoff. **Phase 3 explicitly tests Claude §1.1 binary-frame regression** with a binary frame fixture. |
| 4 | Stores transition correctly under simulated event streams | Unit tests with replay-able event fixtures; XState model tests for invariants |
| 5 | Notification list pane renders mock data; XSS injection in `message`/`title` fields safely escaped | Unit + Playwright smoke with adversarial fixtures (HTML/JS in fields) |
| 6 | Per-feature parity vs `/app/notifications` | Side-by-side E2E via Playwright fixtures; visual regression baselines |
| 7 | User Timing marks emit; CSP violations zero in report-only; cross-tab BroadcastChannel works | Perf budget script + CSP violation collector + 2-tab Playwright integration |
| 8 | Full pyramid pass + adversarial reviews issue NO P0/P1 findings | Automated suite via `/api/test-suite/submit` on :8000; reviews via parallel Agent spawns |
| 9 | New URL is default; old URL still serves with deprecation banner; rollback path verified | Smoke + manual switch back via feature flag |

### Adversarial review protocol (Phase 8)

Three independent passes, run in parallel:
1. **Claude clean-context agent** spawned via Agent tool with no session history; reads only the synthesis doc + design docs + final implementation; produces severity-ranked findings.
2. **OpenAI deep-research** new pass on the implementation (uploaded artifacts); compares against its own May 2026 review.
3. **Tracking-doc audit**: same Claude clean-context agent reads only the design docs + execution logs; flags any divergence between what was planned and what shipped.

Cutover (Phase 9) blocked until all three return zero P0 / P1 findings.

## Risks + mitigations

| Risk | Mitigation |
|---|---|
| Greenfield never finishes (parity drag) | Phase 6 has explicit feature checklist matching current notifications.html; cutover (Phase 8) gate requires 100% E2E parity |
| CSS divergence during long Phase 6 | Periodic CSS re-port + visual regression tests |
| Server contract drift | Per-phase server-contract audit at the start of each phase |
| Voice-persona Fix 4 collision | Fix 4 lands on current `notifications.js` only; new UI gets correct behavior from line one |
| TypeScript blocks contributors | Strict mode but pragmatic types; `any` allowed at boundaries |
| `window.X` global access creeps in | ESLint rule from Phase 1 bans it; events flow via EventBus only |
| CoSA route-edit becomes a git rabbit hole | This plan touches one CoSA file (`pages.py`); user commits separately in CoSA context per Lupin git policy |

## Self-audit against feedback memory

| Memory | Compliance |
|---|---|
| `feedback_phase0_serialization_prominence` | ✅ Phase 0 is row 1 of the phase plan, not buried |
| `feedback_plans_include_tracking_docs` | ✅ Per-phase design docs (02-NN) + spanning execution log (90) enumerated |
| `feedback_documentation_first_protocol` | ✅ Each phase design doc lands BEFORE its code |
| `feedback_comprehensive_automated_testing` | ✅ Verification section routes every phase through unit + smoke + integration + E2E layer |
| `feedback_e2e_two_phase_gate` | ✅ Phase 8 separates code (1-7) from test execution |
| `feedback_test_server_monopolize_mode` | ✅ All :8000 work scheduled via `/api/test-suite/submit` |
| `feedback_lupin_only_never_cosa` | ⚠️ One CoSA file edit (`pages.py`) — code edit allowed; git commit by user |
| `feedback_cosa_edit_vs_manage_git` | ✅ Editing `pages.py` is fine; git ops handed off to user |
| `feedback_never_auto_commit_push` | ✅ No commits authored in this plan |
| `feedback_audit_plans_at_execute_time` | ✅ Per-phase design doc re-audits at execute time |
| `feedback_tests_parameterize_base_url` | ✅ All E2E tests will read `LUPIN_API_URL` |
| `feedback_no_auto_promote_tags` | n/a (no Docker images) |

No violations detected.

## Open questions (deferred — answered later via separate user reply)

These were drafted as Phase 0 questions but the user has indicated this is a documentation-only checkpoint. They remain open and will be answered in the user's next substantive message:

1. **Name + URL**: `inbox` (recommended) / `notifications-next` / `console` / `signal` / other
2. **Language**: TypeScript strict (recommended) / vanilla JS / hybrid (JS + JSDoc + tsc checkJs)
3. **Build chain**: esbuild (recommended) / vanilla ES modules no build / defer
4. **Approval cadence**: per-phase (recommended) / approve once now

No code work begins until these are answered and Phase 1 design doc (`02-phase1-scaffolding-design.md`) is drafted and approved.
