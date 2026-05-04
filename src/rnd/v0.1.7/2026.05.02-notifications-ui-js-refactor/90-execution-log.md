# Multiplexer Notifications UI Rebuild — Execution Log

**Spans**: All 9 phases (Phase 0 through Phase 9)
**Format**: One section per phase, appended in chronological order as each phase progresses
**Anchor docs**: `00-synthesis-and-roadmap.md`, `01-execution-plan.md`, `01-phase0-decisions.md`, `0N-phaseM-design.md` (per phase)

---

## Phase 0 — Decisions Captured

**Status**: ✅ Complete
**Started**: 2026-05-03
**Completed**: 2026-05-03

### Deliverables

| Deliverable | Location | Status |
|---|---|---|
| Strategic synthesis | `00-synthesis-and-roadmap.md` | ✅ Drafted |
| Tactical execution plan | `01-execution-plan.md` | ✅ Drafted |
| Working contract | `01-working-contract.md` | ✅ Drafted |
| 11 Phase 0 decisions resolved | `01-phase0-decisions.md` | ✅ Captured 2026-05-03 |
| Phase 1 design doc | `02-phase1-scaffolding-design.md` | ✅ Drafted, awaiting approval |

### Commits

| Repo | Hash | Message |
|---|---|---|
| Lupin | `f3f4564` | `[LUPIN] Notifications UI refactor — synthesis + execution plan + review-pass scaffolding` |
| Lupin | (pending) | Phase 0 decisions + Phase 1 design doc (next session-end) |

### Verification results

Phase 0 is documentation-only. No live verification required. Document existence + cross-reference integrity is the only check, performed at write time.

### Notes

- Q9 cutover release count overrode the recommended 1-release window in favor of unbounded fallback retention.
- All other decisions tracked the recommended path.
- Plan-review machinery uses canonical `planning-is-prompting/workflow/plan-review.md` (REUSE pre-pass → Pass 1 Fitness → Pass 2 Adversarial; parametrized via `{{slots}}` filled per milestone). The two files at `src/rnd/v0.1.7/2026.05.03-testing-and-fitness-prompts/02-testing-review-prompt.md` and `03-fitness-review-prompt.md` are stale clones lifted from cj-flow and are NOT canonical — ignore them. The directory's `01-working-contract.md` is a Layer-2 anchor instance per PIP §1 and stays.
- Phase 1 design no longer lands alone — it bundles with Phase 2 + Phase 3 design as the **spine bundle** (per Q10 amendment 2026-05-04). Single plan-review pass + single user approval gate covers all three. Implementation cadence within the bundle stays per-phase.

---

## Spine Bundle Plan-Review (Phases 1-3)

**Status**: 🔄 In progress — REUSE pre-pass complete; Pass 1 (Fitness) pending; Pass 2 (Adversarial) pending
**Started**: 2026-05-04
**Last activity**: 2026-05-04
**Last reviewed at**: 2026-05-04 (REUSE pre-pass only; Pass 1 + Pass 2 pending)

### REUSE pre-pass — completed 2026-05-04

**Agent**: Clean-context Explore agent invoked with the canonical PIP `plan-review.md` §4 prompt. `{{slots}}` filled per `02-phase1-scaffolding-design.md` §"Plan-review pointer".

**Findings**: 17 rows total. 4 extend-existing, 13 genuinely-new, 0 reuse-as-is. Plus 4 design concerns surfaced for user decision (DC1–DC4).

**User decisions** (per PIP §6 gate, all approved 2026-05-04):
- All 4 extend-existing rows applied: `pages.py` route registration (#4), dev-tools.html card (#5), QueueTransport wrapper (#13 — re-classified to genuinely-new on user direction since the agent's verdict-cell-vs-explanation was contradictory), WS smoke test for multiplexer (#17)
- Prior-art notes applied for 7 genuinely-new-with-prior-art rows: AuthManager (#6), ApiClient (#7), StorageService (#8), ws-channel.ts port (#11), ConnectionStateMachine (#12), AudioTransport (#14), ClaudeCodeTransport (#15)
- Genuinely-new rows with no prior art (#1, #2, #3, #9, #10, #16) — no doc changes required; verdicts captured here for traceability

**Design concerns resolved**:

| DC | Topic | Resolution |
|---|---|---|
| DC1 | AuthManager dedup contract — sync block vs async optimistic | **Sync block.** `getToken()` blocks until any in-flight refresh completes. `navigator.locks` serializes concurrent refreshes; one network round-trip per refresh. Plus EventBus emissions (`refresh_started` / `refresh_completed` / `refresh_failed` / `auth_state_change`) for orthogonal UI / telemetry observability. Decisive argument: WS auth handshake. Optimistic-stale-token costs 3 round-trips (handshake fail → reconnect → refresh → re-handshake) vs sync block 2 round-trips (refresh → handshake). Full pros/cons captured in `~/.claude/plans/vectorized-bubbling-plum.md` §"DC1". Applied to `03-phase2-foundation-design.md` § AuthManager. |
| DC2 | Session ID source — Phase 2 StorageService or raw localStorage? | **Phase 2 StorageService owns it.** Add first-class `getSessionId() / setSessionId()` methods. Phase 3 transports call `storage.getSessionId()`. The "StorageService owns all storage" invariant is non-negotiable. boot.ts generates "adjective noun" ID on miss (mirrors `notifications.js:478`). Applied to `03-phase2-foundation-design.md` § StorageService + `04-phase3-transport-design.md` Open Q1. |
| DC3 | Test runner commitment — Phase 1 Open Q1 + Phase 2 Open Q1 | **Phase 1 commits to `package.json` + npm with `esbuild` + `typescript` + `tsx` + `eslint` + `c8` + ESLint TS plugins as `devDependencies`.** Phase 2 commits to `tsx --test` using Node's built-in `node:test` runner; coverage via `c8`. Zero additional sprawl beyond Phase 1's commitment. Phase 2's ≥ 90% coverage acceptance criterion now verifiable. Applied to `02-phase1-scaffolding-design.md` § Open questions + `03-phase2-foundation-design.md` § Open questions. |
| DC4 | BroadcastChannel whitelist — static or runtime config? | **Static constant** exported from `multiplexer/shared/broadcast.ts`: `BROADCAST_WHITELIST = new Set([auth_state_change, notification_received, voice_persona_assigned, voice_persona_released, conversation_mode_change])`. Cross-tab replication is a design decision, not runtime config. Applied to `03-phase2-foundation-design.md` § BroadcastChannel wrapper. |

### Pass 1 (Fitness) — completed 2026-05-04

**Agent**: Clean-context Explore agent invoked with the canonical PIP `plan-review.md` §5 prompt. Same `{{slots}}` table as REUSE pre-pass (per `02-phase1-scaffolding-design.md` § "Plan-review pointer").

**Findings**: 17 rows total. Severity tally (corrected — agent's summary line said "15" but the table is the source of truth): 7 AMBIGUITY, 7 COMPLETENESS, 2 TESTABILITY, 1 RISK_SURFACE, 0 ORDERING / DECISION TRACEABILITY / SCOPE / EXTERNAL DEPENDENCIES.

**Per-doc breakdown**: 4 findings on Phase 1 (#1-4), 5 on Phase 2 (#5-9), 8 on Phase 3 (#10-17).

**User decision** (per PIP §6 gate, 2026-05-04): "Apply all" — all 17 findings applied + all 6 enumerated Open-Question answers ratified.

**Open-Question ratifications applied**:

| OQ | Phase | Resolution |
|---|---|---|
| Q2 | Phase 2 | RESOLVED option (a) — require modern browsers for `navigator.locks` (Chrome 96+, Firefox 96+, Safari 15.4+). No polyfill. |
| Q3 | Phase 2 | RESOLVED hybrid — `LupinEventType` string-literal union for compile-time safety + cast for test flexibility. Phase 7 reviews registry formalization if 50+ types accumulate. |
| Q4 | Phase 2 | RESOLVED option (a) — require modern browsers for `AbortSignal.any` (Chrome 116+, Firefox 124+, Safari 17.4+). No polyfill. |
| Q2 | Phase 3 | RESOLVED — hard-coded `min(1000 * 2^n, 30000)` full-jitter backoff. No INI plumbing. Document formula in `ConnectionStateMachine.ts` comments. |
| Q3 | Phase 3 | RESOLVED via finding #14 — `start(sessionId, binaryHandler?: (data: Blob \| ArrayBuffer) => void)` Phase 3 stub signature pinned; debug-logger default. |
| Q4 | Phase 3 | RESOLVED via finding #16 — explicit pre-implementation grep + server-router-verification procedure; escalate on mismatch rather than inline URL. |

**Findings-to-fix mapping** (all 17 applied):

| # | Doc | Section | Fix |
|---|---|---|---|
| 1 | Phase 1 | Verification table | Prepended bootstrap row: `[ -d node_modules ] \|\| npm install` (idempotent) before TS check |
| 2 | Phase 1 | Files-created table — tsconfig.json | Pinned exact paths: `rootDir: "src/fastapi_app/static/js/multiplexer"`, `outDir: "src/fastapi_app/static/dist/multiplexer"`, `include` glob |
| 3 | Phase 1 | Files-created table — .eslintrc.json | Inlined the canonical rule snippet (`no-restricted-properties` + `no-restricted-globals` config + error messages) |
| 4 | Phase 1 | Files-created table — dev-tools.html | Specified 3-step section-resolution order (Notifications & UI → Audio & TTS → new section) |
| 5 | Phase 2 | EventBus contract | Added "Phase 2 reserved event types" subsection enumerating `auth_*` + `refresh_*` + `storage_corrupt` + `listener_error`; tied to OQ3 hybrid |
| 6 | Phase 2 | AuthManager contract | Added "Refresh timeout" paragraph: refresh uses ApiClient with `defaultTimeoutMs`; AbortError → `getToken()` rejects + emits `refresh_failed` with `error: "timeout"`; lock releases regardless |
| 7 | Phase 2 | StorageService contract | Specified synchronous emission of `storage_corrupt` in same microtask as `null` return |
| 8 | Phase 2 | BroadcastChannel contract | Added non-whitelisted-event behavior (silent no-op) + 4-step procedure for adding new whitelist entries |
| 9 | Phase 2 | Verification table | Replaced `npx vitest run` with `npx tsx --test` across all 5 test rows; removed "or whatever Phase 1's chosen runner is" parenthetical |
| 10 | Phase 3 | ConnectionStateMachine contract | Specified 100ms grace period for socket-close-as-fluke detection |
| 11 | Phase 3 | Transport factory | Pinned `createTransports(authManager, eventBus, baseUrl): {queue, audio, claudeCode}` signature |
| 12 | Phase 3 | (new section) | Added "boot.ts Lifecycle Event Emission Contract" with explicit 5-event map + payload shapes + boot-emits-only rule |
| 13 | Phase 3 | ConnectionStateMachine contract | Added full state × event transition matrix; introduced `offline` state distinct from `failed` |
| 14 | Phase 3 | AudioTransport contract | Pinned `start(sessionId, binaryHandler?)` signature with `Blob \| ArrayBuffer` callback type and debug-logger default |
| 15 | Phase 3 | Queue/ClaudeCode contract | Specified envelope mapping: server `{type, data}` → EventBus `{type: env.type, payload: env.data, source: ..., ts}` |
| 16 | Phase 3 | Open Q4 | Replaced "resolves at execute time" deferral with explicit pre-implementation grep + server-router verification + escalation procedure |
| 17 | Phase 3 | Acceptance criterion 7 | Added 6-bullet observability spec for the WS smoke reconnect verification (EventBus assertions, no time.sleep) |

**Convergence re-grep status**: ✅ clean 2026-05-04. Post-fix grep results: TBD/decide/confirm/tbd grep returns 2 meta-references to PIP machinery vocabulary only (`{{TBD_QUESTIONS}}` slot description in Phase 1 doc + a meta-mention in Phase 3 doc); zero actual unresolved TBDs. `Open sub-question` grep returns zero hits. All 6 enumerated OQs (Phase 2 Q2/Q3/Q4 + Phase 3 Q2/Q3/Q4) now marked RESOLVED with explicit answers. Section headers updated. Stale "see Open Questions" parentheticals cleaned. Pass 1 Resolution Loop closed.

### Pass 2 (Adversarial) — completed 2026-05-04

**Agent**: Clean-context Explore agent invoked with the canonical PIP `plan-review.md` §8 prompt. Same `{{slots}}` table; ownership-language scope per PIP §3 (Pass 1 covered structural completeness; Pass 2 covers TEST OWNERSHIP MANDATE conformance).

**Findings**: 6 ownership-language findings. All Acceptance criteria + Rollback procedures lacking explicit `EXECUTOR: AI` tags. Per-doc breakdown: 3 on Phase 1 (A1-A3), 1 on Phase 2 (A4), 2 on Phase 3 (A5-A6).

**Greps clean**:
- `Manual/manual` — 4 hits in Phase 2 doc, all annotated as legitimate non-Manual-E2E uses (ApiClient `manual abort` feature naming, `manualAbortSignal` parameter, prior-art "manual JSON.parse/stringify" describing legacy code). No Manual-E2E flags.
- `EXECUTOR: HUMAN` — zero hits. The docs do not punt human-required steps without justification.
- Bare unchecked checkboxes — zero hits. Verification tables use header-level "Claude-executed per `01-working-contract.md`" semantics.

**Design concerns**: zero — Q1-Q11 + Q10/Q11 amendments hold. Pass 2 surfaces no challenges to the spine-bundle architecture.

**User decision** (per PIP §9 gate, 2026-05-04): "Apply all" — all 6 findings applied.

**Findings-to-fix mapping**:

| # | Doc | Section | Fix |
|---|---|---|---|
| A1 | Phase 1 | AC#4 | Reframed as `EXECUTOR: AI` (Playwright headless) with explicit `document.title` + body + console assertions; programmatic pass/fail |
| A2 | Phase 1 | AC#7 | Reframed as `EXECUTOR: AI` (Playwright headless) navigating to dev-tools, asserting card existence, asserting URL after click |
| A3 | Phase 1 | Rollback #4 | Reframed as `EXECUTOR: AI`: `curl -I /app/notifications`; assert 200 OK |
| A4 | Phase 2 | Rollback #3 | Reframed as `EXECUTOR: AI`: `curl -I /app/multiplexer` + Phase 1 unit suite + Phase 1 page-load Playwright assertion |
| A5 | Phase 3 | AC#7 (6 bullets) | All 5 "observe" verbs reframed as "AI test asserts" with explicit programmatic-assertion language; `time.sleep` ban preserved; ordering assertion on `connection_reconnecting` |
| A6 | Phase 3 | Rollback #3 | Reframed as `EXECUTOR: AI`: `curl -I /app/multiplexer` + Phase 1 page-load + Phase 2 full unit suite via `tsx --test` |

**EXECUTOR: AI tag count after fixes**: Phase 1 = 5; Phase 2 = 1; Phase 3 = 2; total 8 across the spine bundle.

**Convergence re-grep status**: ✅ clean 2026-05-04. Manual/manual hits unchanged from baseline (all legitimate). Zero EXECUTOR: HUMAN. Zero bare checkboxes. Pass 2 Resolution Loop closed.

### Spine Bundle — APPROVED 2026-05-04 (final user OK pending)

| Gate | Status | Date |
|---|---|---|
| REUSE pre-pass | ✅ Complete; fixes applied; convergence clean | 2026-05-04 |
| Pass 1 (Fitness) | ✅ Complete; 17 fixes + 6 OQ ratifications applied; convergence clean | 2026-05-04 |
| Pass 2 (Adversarial) | ✅ Complete; 6 fixes applied; convergence clean | 2026-05-04 |
| **Spine bundle implementation** | ⏸ Awaiting final user OK to begin Phase 1 | — |

**Idempotency marker** (per PIP §12): `last-reviewed-at: 2026-05-04 (commit-hash: TBD — set in checkpoint commit)`.

**Phase 1 implementation prerequisites** (entry artifacts a fresh-context Claude must read):
1. `~/.claude/CLAUDE.md` — Layer 1 anchor (TEST OWNERSHIP MANDATE + DOCUMENTATION-FIRST PROTOCOL)
2. `CLAUDE.md` (Lupin project root) — Layer 1 project anchors
3. `src/rnd/v0.1.7/2026.05.03-testing-and-fitness-prompts/01-working-contract.md` — Layer 2 multiplexer working contract
4. `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/01-phase0-decisions.md` — Layer 3 design anchor (Q1-Q11 + Q10/Q11 amendments)
5. `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/00-synthesis-and-roadmap.md` — strategic context
6. `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/02-phase1-scaffolding-design.md` — **THIS PHASE** — Phase 1 implementation reads from here exclusively
7. `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/03-phase2-foundation-design.md` — Phase 2 (consumed by Phase 1 only via the spine-bundle approval; do NOT implement Phase 2 code in the Phase 1 session)
8. `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/04-phase3-transport-design.md` — Phase 3 (same)
9. This file (`90-execution-log.md`) — review history + Phase status

### Pass 2 (Adversarial) — pending

Fires after Pass 1 closes per PIP §3 ordering rationale.

---

## Phase 1 — Scaffolding

**Status**: ⏸ Awaiting spine-bundle plan-review pass + user approval (Phases 1+2+3 bundled per Q10 amendment 2026-05-04). Design doc updated 2026-05-04 with Approval coupling note + Plan-review pointer (canonical PIP slots filled).
**Started**: —
**Completed**: —

### Deliverables (per `02-phase1-scaffolding-design.md`)

| File | Status |
|---|---|
| `src/fastapi_app/static/html/multiplexer.html` | ⏸ Not yet created |
| `src/cosa/rest/routers/pages.py` (route registration) | ⏸ Not yet edited |
| `tsconfig.json` (project root) | ⏸ Not yet created |
| `src/scripts/build-multiplexer.sh` | ⏸ Not yet created |
| `src/fastapi_app/static/js/multiplexer/boot.ts` | ⏸ Not yet created |
| `src/fastapi_app/static/js/multiplexer/.eslintrc.json` | ⏸ Not yet created |
| `src/fastapi_app/static/html/dev-tools.html` (card add) | ⏸ Not yet edited |
| `package.json` + `package-lock.json` (project's first) | ⏸ Per Phase 1 design Open Questions §1+§2 |

### Commits

(empty — phase not started)

### Verification results

(empty — phase not started)

### Notes

(empty — phase not started)

---

## Phase 2 — Foundation services (AuthManager, ApiClient, StorageService, EventBus, BroadcastChannel)

**Status**: ⏸ Spine bundle member. Design doc `03-phase2-foundation-design.md` drafted 2026-05-04 alongside Phase 1 + Phase 3 designs; awaiting bundled plan-review + user approval. Implementation starts after Phase 1 implementation completes (within-bundle per-phase cadence per Q10 amendment).
**Started**: —
**Completed**: —

### Deliverables, Commits, Verification, Notes

(populated when Phase 2 begins)

---

## Phase 3 — Transport (ws-channel.ts port + Claude §1.1 + §2.2 + §2.5 fixes; QueueTransport / AudioTransport / ClaudeCodeTransport)

**Status**: ⏸ Spine bundle member. Design doc `04-phase3-transport-design.md` drafted 2026-05-04 alongside Phase 1 + Phase 2 designs; awaiting bundled plan-review + user approval. Implementation starts after Phase 2 implementation completes (within-bundle per-phase cadence). Phase 3 ships the first concrete proof-of-spine — `auth_success` handshake against :7999.
**Started**: —
**Completed**: —

### Deliverables, Commits, Verification, Notes

(populated when Phase 3 begins)

---

## Phase 4 — Domain stores (NotificationStore, JobStore, AudioStore, ActionRequiredStore, SenderStore — XState for high-churn, plain reducers elsewhere)

**Status**: ⏸ Not started
**Started**: —
**Completed**: —

### Deliverables, Commits, Verification, Notes

(populated when Phase 4 begins)

---

## Phase 5 — Renderer (tagged-template `html` helper + first pane: notifications list + CSS port)

**Status**: ⏸ Not started
**Started**: —
**Completed**: —

### Deliverables, Commits, Verification, Notes

(populated when Phase 5 begins)

---

## Phase 6 — Feature parity (jobs queue, TTS, action-required, focus tray, voice-persona, conversation-mode UI, sender cards, audio recorder, focus-mode)

**Status**: ⏸ Not started
**Started**: —
**Completed**: —

### Deliverables, Commits, Verification, Notes

(populated when Phase 6 begins)

---

## Phase 7 — Hardening (User Timing + Long Tasks + OTel browser SDK, CSP report-only, Trusted Types, BroadcastChannel cross-tab, accessibility audit)

**Status**: ⏸ Not started
**Started**: —
**Completed**: —

### Deliverables, Commits, Verification, Notes

(populated when Phase 7 begins)

---

## Phase 8 — Adversarial review + viability gate (full automated pyramid + parallel adversarial reviews — Claude clean-context + OpenAI deep-research + tracking-doc audit)

**Status**: ⏸ Not started
**Started**: —
**Completed**: —

### Deliverables, Commits, Verification, Notes

(populated when Phase 8 begins)

---

## Phase 9 — Cutover (feature-flag rollout, multiplexer becomes default; notifications.html stays alive indefinitely per Q9)

**Status**: ⏸ Not started
**Started**: —
**Completed**: —

### Deliverables, Commits, Verification, Notes

(populated when Phase 9 begins)
