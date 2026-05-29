# Notifications UI Refactor — Synthesis & Roadmap

**Date**: 2026-05-03
**Status**: Phase 0 decisions captured (2026-05-03) → see `01-phase0-decisions.md`. Phase 1 design doc drafted (`02-phase1-scaffolding-design.md`) — awaiting user approval before code begins.
**Inputs**: `2026.05.02-notifications-ui-js-refactor-analysis-claude.md` (Claude Opus 4.7) + `2026.05.02-notifications-ui-js-refactor-analysis-openai.md` (OpenAI deep-research)
**Strategic posture**: **PARALLEL GREENFIELD REBUILD** — new module tree at a new URL (`/app/multiplexer`); current `notifications.html` stays running and unchanged until cutover, then remains as unbounded fallback per Q9.

---

## 1. Why parallel greenfield (not in-place refactor)

Both reviews recommend incremental in-place refactor (strangler pattern). The user has chosen a different path:

- **In-place** means every PR risks breaking the live notifications surface that the user actively depends on (CC sessions, voice-persona allocation, focus tray, conversation mode, action-required queue).
- **Parallel greenfield** means the live UI stays frozen at its current URL; the new UI is built from scratch at a new URL with all the lessons from both reviews baked in from day one. Cutover happens when parity + adversarial review pass.
- **Cost**: more code written net (no code reuse). **Benefit**: zero risk to running surface; clean module boundaries from line one; no compromise refactors.

**Implication for both reviews**: Claude's "Tier 1 hotfix sweep" against the *current* file is **deprioritized** — current file enters maintenance freeze; only voice-persona /clear preservation (Frontend Fix 4, currently parked) lands as patches. All other findings flow into the greenfield design specs.

**Current file's fate**: maintenance freeze → cutover → archive. The duplicate methods, dead branches, broken Firefox detection, etc. are accepted as legacy debt that ages out at cutover.

---

## 2. Synthesis: where the two reviews converge, diverge, and complement

### 2.1 Strong convergence (both flag, both recommend same shape)

| Theme | Headline |
|---|---|
| **Monolith is the dominant risk** | 16,797-line `NotificationsUI`, ~115 instance fields, ~279 methods. No human can hold the surface area. |
| **`ws-channel.js` is the cleanest module** | Preserve as-is conceptually; use as the template for every other transport. Generation tokens, full-jitter backoff, single transition point, frozen public API. |
| **Auth-refresh dedup is the highest-value fix** | Claude: `navigator.locks.request("lupin-token-refresh", …)`. OpenAI: single in-flight refresh promise. Same primitive, both right. |
| **No fetch timeouts/aborts anywhere** | 48 fetch sites, zero `AbortController`. A hung `/auth/refresh` blocks the UI indefinitely. |
| **Page-lifecycle wiring is duplicated** | Both `ws-channel.js` and `NotificationsUI._attachPageLifecycle()` attach the same events. Channel should be transport-only; orchestrator owns lifecycle. |
| **`claudeCodeWs` raw socket has no fallback** | Migrate to `createChannel`; inherits the entire reliability story for free. |
| **State-machine shape required for high-churn flows** | Auth refresh, TTS playback, action-required queue, STT recording, connection — currently boolean+timer soup. |
| **HTML-string rendering is the XSS + CSP blocker** | 62 raw `innerHTML` vs 34 `escapeHtml`. Inline `onclick`/`onchange` everywhere blocks Trusted Types. |

### 2.2 Claude's exclusive findings (concrete latent bugs)

| § | Finding | Severity | Greenfield action |
|---|---|---|---|
| 1.1 | Binary audio frames silently dropped — `JSON.parse(<Blob>)` swallowed in ws-channel.js:261-276 | **Critical** | New `onBinary` callback wired into `AudioTransport` from line one |
| 1.2 | Three duplicate methods (`playAudioBlob`, `escapeHtml`, `moveSenderCardToTop`) with broken dead first-defs | High | Won't recur — module boundaries prevent duplication |
| 2.5 | JSON round-trip in dispatch (parse → stringify → parse) | Medium | Channel passes parsed envelope; no stringify in handler chain |
| 3.3 | `TTSAudioCache.scheduleCleanup` `setInterval` never cleared | Low | `destroy()` on every owning module by convention |
| 3.6 | `InstallTrigger` Firefox detection dead since FF128 | Low | Feature-detect, never UA-sniff |
| 3.7 | `parseInt() \|\| 48` swallows zero | Low | Use `Number.isFinite` at every parse site |
| 4.5 | AudioRecorder sends base64 string with `Content-Type: audio/mpeg` | Medium | Send raw blob with `audioBlob.type` |
| 5.5 | Cache-bust drift HTML `?v=20260502b` vs JS `?v=20260502a` | Cosmetic | Content-hashed paths via build tool |

### 2.3 OpenAI's exclusive findings (architectural posture)

| Area | Finding | Greenfield action |
|---|---|---|
| Concrete bug | HTML logout button calls `window.freshQueueUI.logout()` but app initializes `window.notificationsUI` | Won't recur — no global `window.X.method()` calls |
| Constant drift | `FILE_DRIVEN_TEST_TYPES` duplicated in HTML inline `<script>` AND `notifications.js` | Single source in shared module |
| Redundant init | `JobCompletionCache` opens IDB in constructor + `NotificationsUI.init()` calls `initializeIndexedDB()` separately | Storage service owns IDB lifecycle exclusively |
| Encapsulation violation | STT manager reaches into `AudioRecorder._cancelling` directly | Public `cancel()` method only |
| Connectivity truth | `navigator.onLine` is hint-only per MDN | Active reachability probe + last-known-good timestamp |
| Renderer cost | Full-container `innerHTML` replacement for routine updates is the biggest perf smell | Keyed render units + virtualization for history pane |
| Observability | No User Timing, no Long Tasks, no OTel browser SDK | Phase-7 hardening item — not deferred |
| Token storage | OWASP: localStorage is wrong place for session tokens | Out of scope for JS-only refactor; flagged for server-side follow-up (HttpOnly cookies + CSRF) |
| CSP/Trusted Types | Inline handlers block enforcement | Greenfield bans inline handlers from line one |
| Offline outbox | Service Worker + Background Sync for replay-safe mutations only | Phase-7 hardening item |

### 2.4 Tensions — and how this roadmap resolves them

| Tension | Claude | OpenAI | Resolution |
|---|---|---|---|
| Module structure | Vanilla ES-module file tree | Domain stores/actors (XState) | **File tree from Claude; XState actors live inside the high-churn modules (auth, TTS, action-required, connection)** |
| Language | Vanilla JS | TypeScript | **TypeScript from line one** — greenfield removes the JS-migration cost. Strict mode. |
| Renderer | `<template>` cloning + tagged-template `html` helper | Components / keyed render functions | **Tagged-template `html` helper** as base primitive; keyed render units on top. No framework. |
| Token storage | Not addressed | Move off localStorage | **Out of scope this iteration**; document as server-side follow-up |
| Observability | Not addressed | Phase D before deeper perf | **Phase-7 hardening item** with explicit User Timing marks at queue render, TTS start, reconnect, refresh |

---

## 3. Phase plan (greenfield)

| Phase | Focus | Output | Code? |
|---|---|---|---|
| **0** | Decisions: name, URL, directory, build chain, TS config, ws-channel reuse policy | This doc + user sign-off | No |
| **1** | Scaffolding: FastAPI route, empty shell page, TS+esbuild build, dev-tools card, manifest | Page loads, says "hello", served at new URL | Tiny |
| **2** | Foundation services: `AuthManager` (`navigator.locks` from day one), `ApiClient` (`AbortSignal.any`), `StorageService` (typed JSON helpers), `EventBus` (`EventTarget` instance), `BroadcastChannel("lupin")` | Services exist; unit-tested in isolation; not yet wired to UI | Yes |
| **3** | Transport layer: copy `ws-channel.js` and apply Claude §1.1 binary-frame fix + §2.2 lifecycle removal + §2.5 JSON round-trip removal; build `QueueTransport` / `AudioTransport` / `ClaudeCodeTransport` thin wrappers | All three sockets connect, auth, route to handlers; lifecycle owned by orchestrator | Yes |
| **4** | Domain stores: `NotificationStore`, `JobStore`, `AudioStore`, `ActionRequiredStore`, `SenderStore` — XState actors where event-driven, simple reducers where not | Stores exist, fully unit-tested with mocked transports | Yes |
| **5** | Renderer: tagged-template `html` helper + first pane (notifications list); CSS port from current page | Notifications list renders correctly with mock data | Yes |
| **6** | Feature parity: jobs queue (todo/run/done/dead/history), TTS playback + queue, action-required countdown, focus-tray, voice-persona display, conversation-mode UI, sender cards, focus-mode toggle, hide-inactive toggle, audio recorder | All current features work at new URL | Yes |
| **7** | Hardening: User Timing + Long Tasks + OTel browser SDK, CSP report-only, Trusted Types, BroadcastChannel cross-tab coordination, accessibility audit | Production-grade telemetry; CSP-strict-ready | Yes |
| **8** | **Adversarial review + viability gate**: full automated test pyramid + adversarial review of every tracking doc and the implementation | Sign-off to cutover | Tests only |
| **9** | Cutover: feature-flag rollout, redirect old URL, deprecate `notifications.html` (kept for 1 release as fallback) | New URL is the default | Minimal |

**Phase ordering rationale**:
- Phases 1-3 (scaffolding + foundation + transport) build the spine. No user-visible features yet.
- Phase 4 stores can be built and tested independently of rendering — proves the data model before pixels.
- Phase 5 ships one pane (notifications list) as the renderer-pattern proof. If the pattern is wrong, we find out before building 6 more panes.
- Phase 6 is the long phase — every existing feature ported. Each feature is its own PR.
- Phase 7 is mandatory before cutover, not after — observability before launch beats observability after regressions.
- Phase 8 is the user's gate. Adversarial review is run by spawning a separate Claude agent that has not seen the implementation history; viability is the full automated pyramid.
- Phase 9 is the cutover. Old URL stays alive as fallback for one release.

### Phase bundling — the spine (Phases 1-3) lands as one approval unit

Per Q10 amendment in `01-phase0-decisions.md` (2026-05-04): **Phases 1, 2, and 3 design docs bundle as the spine** and land as a single plan-review pass + single user approval gate. Phases 4-9 revert to the per-phase cadence.

Why bundled: the toolchain decisions in Phase 1 (TS strictness, ESLint rule, esbuild output shape) constrain Phase 2 service contracts (AuthManager refresh callback, EventBus event shape), which constrain Phase 3 transport-wrapper interfaces. Designing them serially would pin earlier decisions before later constraints surface; designing them as a unit catches contract-interface gaps at design time. The clean-context Claude review (per Q11 amendment, canonical PIP `plan-review.md` machinery) sees the whole spine surface in one pass.

Within the bundle, **implementation cadence stays per-phase**: Phase 1 implements + verifies + commits before Phase 2 code starts; same Phase 2 → Phase 3. This preserves the working-contract verification discipline (each phase ships a runnable artifact: Phase 1 = `/app/multiplexer` returns "hello"; Phase 2 = unit-tested foundation services; Phase 3 = `auth_success` handshake against :7999).

After spine implementation completes, a natural go/no-go gate: if Phase 4-9 architectural assumptions held, per-phase from Phase 4. If something fundamental needs rework (e.g., transport contract turned out wrong), re-scope BEFORE committing to 6 more design docs.

**What is NOT in this roadmap**:
- ❌ Token storage migration (server-side change required; out of scope)
- ❌ Service Worker offline outbox (Phase 7+ if we want it; deferred)
- ❌ Switch to React/Vue/Svelte (vanilla TS + tagged templates is the chosen path)
- ❌ XState as a global pattern (only for the high-churn modules)
- ❌ Modifying `notifications.js` at the current URL (frozen until cutover; only voice-persona Fix 4 lands)
- ❌ Multi-tab support — **single-tab application policy** per Q12 (ratified 2026-05-04 PM). Phase 2 `BroadcastChannel("lupin")` wrapper is inert; users wanting two views open a second window of the same tab. See `01-phase0-decisions.md` Q12 + `TODO.md` Phase 2 broadcast cleanup follow-up.

---

## 4. Decisions required from user (Phase 0 gate)

### 4.1 Name + URL

The new UI needs a name distinct from "notifications" so URLs and module trees never collide with the existing surface. Candidates:

| Name | URL | Rationale | Tradeoff |
|---|---|---|---|
| `notifications-next` | `/notifications-next` | Boring, mirrors industry convention (`vue-next`, `react-next`) | Reads as a patch level, not a re-architecture |
| `inbox` | `/inbox` | Accurate semantic — it IS an inbox of notifications, jobs, voice cards | Drops the "notification" word the team is used to |
| `console` | `/console` | Captures the control-surface aspect (focus tray, hide-inactive, conversation mode toggle) | Ambiguous with `/dev-tools`-style admin pages |
| `signal` | `/signal` | Lupin-themed (signals from agents); short | Collides with the messaging app brand |
| `lupin-ui` | `/lupin-ui` | Project-themed | Generic |
| **(your suggestion)** | | | |

**Recommendation**: `inbox` — semantically accurate, short, clearly distinct from `notifications` for parallel-running purposes. Open to alternatives.

### 4.2 Directory structure

Proposed (assuming name = `inbox` for illustration; trivially renamed):

```
src/fastapi_app/static/
├── html/
│   ├── notifications.html           # FROZEN — current
│   └── inbox.html                   # NEW shell entry
├── css/
│   ├── notifications.css            # FROZEN
│   └── inbox/                       # NEW — modular CSS
│       ├── shell.css
│       ├── notifications.css
│       ├── jobs.css
│       └── audio.css
├── js/
│   ├── notifications.js             # FROZEN
│   ├── ws-channel.js                # FROZEN (current consumers depend on it)
│   └── inbox/                       # NEW module tree
│       ├── boot.ts
│       ├── auth/
│       │   └── AuthManager.ts
│       ├── transport/
│       │   ├── ws-channel.ts        # COPY of current with §1.1+§2.2+§2.5 fixes
│       │   ├── QueueTransport.ts
│       │   ├── AudioTransport.ts
│       │   └── ClaudeCodeTransport.ts
│       ├── api/
│       │   └── ApiClient.ts
│       ├── stores/
│       │   ├── NotificationStore.ts
│       │   ├── JobStore.ts
│       │   ├── AudioStore.ts
│       │   ├── ActionRequiredStore.ts
│       │   └── SenderStore.ts
│       ├── tts/
│       │   ├── TTSEngine.ts
│       │   └── TTSQueue.ts
│       ├── audio/
│       │   ├── AudioRecorder.ts
│       │   └── caches/
│       │       ├── TTSAudioCache.ts
│       │       └── JobCompletionCache.ts
│       ├── render/
│       │   ├── html.ts              # tagged-template helper
│       │   ├── NotificationList.ts
│       │   ├── JobQueue.ts
│       │   ├── SenderCard.ts
│       │   ├── FocusTray.ts
│       │   └── ActionRequired.ts
│       ├── shared/
│       │   ├── sha256.ts
│       │   ├── storage.ts
│       │   ├── events.ts            # EventBus + BroadcastChannel wrapper
│       │   └── time.ts
│       └── observability/
│           ├── timing.ts
│           └── otel.ts
└── dist/inbox/                      # esbuild output
```

**Build chain proposal**: `esbuild` (single binary, no node_modules sprawl) — input `src/fastapi_app/static/js/inbox/boot.ts` → output `src/fastapi_app/static/dist/inbox/boot.js` + sourcemap. Content-hashed filename eliminates the `?v=YYYYMMDD` ritual. Dev mode: `--watch` + auto-rebuild. Production: minified + sourcemap separate.

**Alternative**: TypeScript via a single-file transpile-on-import pattern (`<script type="module">` with a small dev server). Lower setup cost, but no tree-shaking and no minification — not viable for a 5-10k-line app.

### 4.3 ws-channel.js — copy or symlink?

Two options:
- **(a) Copy + fix**: copy current `ws-channel.js` to `inbox/transport/ws-channel.ts`, apply Claude's §1.1 + §2.2 + §2.5 fixes, divergence is permanent. Original stays serving current notifications.html.
- **(b) Fix in place**: apply fixes to `ws-channel.js` now, both URLs share. Risk: a regression in current notifications.html during refactor.

**Recommendation**: **(a) copy**. Greenfield isolation principle. Original ws-channel.js becomes legacy at cutover.

### 4.4 Tracking-doc layout

Following the v0.1.7 convention (`feedback_plans_include_tracking_docs`):

```
src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/
├── 2026.05.02-notifications-ui-js-refactor-analysis-claude.md    # input (existing)
├── 2026.05.02-notifications-ui-js-refactor-analysis-openai.md    # input (existing)
├── 2026.05.05-phase5-pre-design-exploration.md                   # Phase 5 pre-design Explore-agent findings (citation-depth backing for 06-)
├── 00-synthesis-and-roadmap.md                                   # this doc
├── 01-phase0-decisions.md                                        # decisions captured (filled in after user signs off)
├── 02-phase1-scaffolding-design.md
├── 03-phase2-foundation-design.md
├── 04-phase3-transport-design.md
├── 05-phase4-domain-stores-design.md
├── 06-phase5-renderer-design.md                                  # design landed 2026-05-05; Q-A through Q-L awaiting ratification
├── 07-phase6-parity-design.md                                    # large — likely sub-divided
├── 08-phase7-hardening-design.md
├── 09-phase8-adversarial-review-design.md
├── 10-phase9-cutover-design.md
└── 90-execution-log.md                                           # one log spanning all phases, sectioned
```

Each phase design doc ends with: testing strategy for that phase (unit + smoke + integration + E2E layer per `feedback_comprehensive_automated_testing`), open questions, and rollback procedure. The execution log gets a new section per phase as it lands.

**Plan-review timing** (per Q11 amendment 2026-05-04): the canonical PIP `plan-review.md` workflow fires **AFTER the per-phase design doc is drafted (= tracking-doc generation per `/p-is-p-02-documentation`) and BEFORE the user approves it / the 90-log section opens / code begins**. Sequence per phase: AI drafts design doc → AI fills `{{slots}}` → spawn REUSE pre-pass Agent → user-decision gate → spawn Pass 1 (Fitness) Agent → user-decision gate → spawn Pass 2 (Adversarial) Agent → user-decision gate → user approves → 90-log section opens → implementation. For the spine bundle (Phases 1-3), the slot fill lists all three design docs as `{{PLAN_DOC_PATHS}}` so a single review pass covers the whole spine. Phase 8 viability gate uses the same machinery + adds OpenAI deep-research per Q11. **The two prompt files at `src/rnd/v0.1.7/2026.05.03-testing-and-fitness-prompts/02-` and `/03-` are stale clones lifted from cj-flow and are NOT canonical** — ignore them; the canonical source is `planning-is-prompting/workflow/plan-review.md`. (The directory's `01-working-contract.md` is a Layer-2 anchor instance per PIP §1 and stays.)

### 4.5 Testing venue routing per phase

Per Lupin's :7999 / :8000 venue policy:

| Phase | Test types | Venue |
|---|---|---|
| 1 | Smoke: page loads, build artifact exists | :7999 |
| 2 | Unit: AuthManager + ApiClient + StorageService | :7999 |
| 3 | Unit: transport wrappers; smoke: WS connects against dev | :7999 |
| 4 | Unit: stores with mocked transports | :7999 |
| 5 | Unit: render helpers; smoke: pane renders with mock data | :7999 |
| 6 | Unit + smoke per feature; E2E UI parity tests | E2E → :8000 (scheduled) |
| 7 | Integration: cross-tab BroadcastChannel; perf: User Timing budgets | :8000 (scheduled) |
| 8 | **Full pyramid**: unit + smoke + WS smoke + E2E UI + integration | :7999 fast tiers + :8000 scheduled |
| 9 | Smoke: redirect works; E2E: cutover URL serves new UI | :7999 + :8000 (scheduled) |

---

## 5. Open questions for the user

> **Resolved 2026-05-03** — all 11 decisions captured in `01-phase0-decisions.md` (the durable record). Original questions and recommended defaults preserved below for traceability. Q9 (cutover release count) overrode the recommended `1 release` default in favor of `unbounded` per user direction.

| # | Question | Default if no answer |
|---|---|---|
| Q1 | **Name + URL** — `inbox` / `notifications-next` / `console` / `signal` / your pick? | (block — required) |
| Q2 | **Directory layout** — accept the proposal in §4.2 as-is? Any path you'd rename? | Accept proposal |
| Q3 | **Build chain** — `esbuild` ok? Alternative preferred? | esbuild |
| Q4 | **TypeScript strict mode** — yes? | yes, strict + `noUncheckedIndexedAccess` |
| Q5 | **ws-channel.js** — copy (recommended) or fix-in-place? | copy |
| Q6 | **XState** — accepted as the actor lib for high-churn modules (auth, TTS, action-required, connection)? Or roll our own minimal FSM? | XState |
| Q7 | **Token storage migration** — confirmed out of scope? | out of scope |
| Q8 | **Service Worker / offline outbox** — confirmed out of scope this iteration? | out of scope |
| Q9 | **Cutover policy** — keep old `notifications.html` alive for how many releases after cutover? | 1 release |
| Q10 | **Per-phase user gate** — do you want to approve each phase's design doc before code begins, or once at the start? | per-phase approval (safer). **Amended 2026-05-04**: Phases 1-3 bundle as the spine (single approval unit); Phases 4-9 individual gates. See `01-phase0-decisions.md` Q10 amendment. |
| Q11 | **Adversarial review owner** — separate Claude agent (clean context), or external (OpenAI/another model)? | separate Claude agent + OpenAI deep research, both, comparing. **Amended 2026-05-04**: timing per canonical PIP `plan-review.md` (REUSE → Fitness → Adversarial; review fires AFTER design-doc draft, BEFORE user approval). See `01-phase0-decisions.md` Q11 amendment. Stale clones at `2026.05.03-testing-and-fitness-prompts/02-` + `/03-` are NOT canonical. |

---

## 6. Risks + mitigations

| Risk | Mitigation |
|---|---|
| **Greenfield never finishes** — feature parity drags, both UIs stay alive forever | Phase 6 has explicit feature checklist; cutover gate (Phase 8) requires 100% parity demonstrable via E2E tests |
| **CSS divergence** — current `notifications.css` evolves during the rebuild; new UI looks subtly different | Periodic re-port of CSS during Phase 6; visual regression tests against parity baseline |
| **Server contract drift** — server adds new WS events / endpoints during the rebuild | Per-phase server-contract audit at the start of each phase; integration tests pinned to current contract |
| **Voice-persona Fix 4 collision** — frontend stale-badge propagation work parked on `notifications.js`; if it lands during the rebuild, divergent fixes | Voice-persona Fix 4 lands on current `notifications.js` only; new UI gets the correct behavior from the start (no patches needed) |
| **Adversarial review finds fundamental flaws at Phase 8** — late, expensive | Adversarial review of *tracking docs* at end of each phase, not just at Phase 8; cheap re-cast at design time |
| **TypeScript adoption blocks contributors** — anyone who only knows JS | Strict mode but pragmatic types; `any` allowed at boundaries; no compiler-enforced patterns |
| **`window.X` global access in templates carries over by habit** | Lint rule from Phase 1: ban `window.notifications*` and `window.inbox*` references in module code; events flow via EventBus |
| **Spine boundary holds but Phase 4+ surface is bigger than expected** — store/render/parity work expands faster than planned per-phase pace can absorb | After spine implementation completes (end of Phase 3), reassess Phase 4-9 scope before drafting more design docs; spine-bundle approval explicitly does NOT commit to the rest of the phase plan; pivot to a pure per-phase cadence is the default escape hatch |

---

## 7. What ships in Phase 0 (this gate)

This document + the 11 questions above answered. Once answered:
1. ✅ `00-synthesis-and-roadmap.md` updated with decisions captured (2026-05-03)
2. ✅ `01-phase0-decisions.md` written as the durable record (2026-05-03)
3. ✅ `02-phase1-scaffolding-design.md` drafted as the Phase 1 entry doc (2026-05-03)
4. ⏸ User approves Phase 1 design → code begins (PENDING)

No code is written until §5 is fully answered. **Status: §5 fully answered; awaiting Phase 1 design-doc approval.**

---

## 8. Pre-exit self-audit (against feedback memory)

Per `feedback_plan_self_audit_against_memory`:

| Memory | Compliance check |
|---|---|
| `feedback_phase0_serialization_prominence` | ✅ Phase 0 is §3 row 1, explicit, not buried |
| `feedback_plans_include_tracking_docs` | ✅ §4.4 enumerates 01-NN design + 90 execution log |
| `feedback_comprehensive_automated_testing` | ✅ §4.5 routes every phase through unit + smoke + integration + E2E |
| `feedback_documentation_first_protocol` | ✅ Each phase design doc lands BEFORE its code |
| `feedback_e2e_two_phase_gate` | ✅ Phase 8 separates code (Phases 1-7) from test execution |
| `feedback_skip_rnd_doc_for_trivial_fixes` | n/a — this is non-trivial, full docs apply |
| `feedback_test_server_monopolize_mode` | ✅ §4.5 explicitly schedules :8000 work via `/api/test-suite/submit` |
| `feedback_lupin_only_never_cosa` | ✅ All paths under `src/fastapi_app/`; no CoSA submodule changes |
| `feedback_never_auto_commit_push` | ✅ This roadmap commits no code; user explicitly approves each phase |
| `feedback_audit_plans_at_execute_time` | ✅ Per-phase design doc re-audits at execute time, not just author time |
| `feedback_no_green_in_persona_pool` | n/a — not a persona-color decision |
| `feedback_tests_parameterize_base_url` | ✅ Phase 6+ E2E tests will read `LUPIN_API_URL` (will document in phase doc) |

No violations detected at draft time.

---

## 9. Open follow-ups (cross-cutting)

| Filed | Source | Note |
|-------|--------|------|
| 2026-05-11 | Parent Lupin CC Card Normalization (session 658ea35d) | CC card on `/app/notifications` reshaped to sibling shape (form + submit + status div; no response panel, no inject controls, no session-info row). Submit URL renamed to canonical `/api/claude-code/submit`; old `/queue/submit` alias preserved for one release cycle (Q8 verdict PRIMARY). `JobsPaneRenderer.ts` unchanged — agent-agnostic via `metadata.agent_type`. **Phase 6b visual-baseline impact**: if Phase 6b touches CC card screenshots, expect to regen baselines. Full handoff: [`../2026.05.09-cc-card-normalization/02-handoff-summary.md`](../2026.05.09-cc-card-normalization/02-handoff-summary.md). |
