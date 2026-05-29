# Phase 7 Slicing Manifest — 7a / 7b / 7c / 7d

**Date**: 2026-05-20
**Author**: Mr. Radio 🦉 (Lupin session `32a6e563`)
**Status**: ✅ **Ratified 2026-05-20** — Tiberius 🌑 greenlit; Rick ratified all 4 decisions (sequencing order, pre-cascade recon, operational-phase decoupling × 2). Awaiting Phase 6c close before first-slice pre-cascade recon kicks off.
**Sister docs**:
- Parent roadmap: [`00-synthesis-and-roadmap.md`](00-synthesis-and-roadmap.md) §3 Phase 7 row — defines Phase 7 = hardening
- Prior slicing manifest (template): [`07-phase6-slicing-manifest.md`](07-phase6-slicing-manifest.md) — shape + density pattern this doc mirrors
- Prior execution plan: [`12-phase6c-execution-plan.md`](12-phase6c-execution-plan.md) — DAG-first handoff pattern Phase 7 slices will inherit post-cascade

---

## How to read this document

This is the **slicing decision artifact** for Phase 7 (Hardening). It does NOT replace per-slice design docs — those are the next deliverables, drafted via the cascaded plan-authoring workflow once Rick ratifies the slicing + sequencing decisions captured here.

The manifest exists so each per-slice design doc can focus on slice-internal concerns rather than re-litigating "which Phase 7 sub-feature lands here vs there."

**Cadence per slice**: identical to Phase 4 + 5 + 6 — design doc → plan-review pipeline (REUSE + Pass 1 Fitness + Pass 2 Ownership-Language Audit, **sequential never parallel** per `feedback_pip_plan_review_is_sequential`) → user ratifies Q-decisions + D-tier → Resolution Loop → user go-ahead → code-execution plan (separate plan-mode session) → implementation + AC matrix → commit gate → AC-scheduled `:8000` visual baseline.

---

## Slice status (live)

| Slice | Status | Started | Closed | Closure doc |
|---|---|---|---|---|
| 7a — Telemetry (User Timing + Long Tasks + OTel browser SDK) | ⏸ Not started | — | — | — |
| 7b — CSP (Content Security Policy: report-only → enforce) | ⏸ Not started | — | — | — |
| 7c — Trusted Types (browser-level dynamic-HTML lockdown) | ⏸ Not started | — | — | — |
| 7d — Accessibility (WCAG 2.1 AA audit + ARIA + keyboard nav + screen-reader pass) | ⏸ Not started | — | — | — |

**Upstream phase status (context)**: Phase 6a CLOSED 2026-05-06; 6b CLOSED 2026-05-12; **6c in flight** (Tiffany 💍 implementing per `12-phase6c-execution-plan.md`; DAG nodes D + B + A shipped local-green; Node C partial — C1 + C2 done). Phase 7 begins after 6c closes.

---

## Why slice (recap)

Phase 7 was framed in `00-synthesis-and-roadmap.md` §3 as a single "hardening" cycle covering 4 distinct technical sub-areas plus 1 inert workstream:

1. **Telemetry**: User Timing API + Long Tasks API + ReportingObserver + OTel browser SDK
2. **Content Security Policy**: report-only header → tighten → enforce
3. **Trusted Types**: browser-level enforcement of dynamic-HTML construction discipline
4. **Accessibility**: WCAG 2.1 AA audit + ARIA + keyboard nav + screen reader pass

Plus inert: **BroadcastChannel cross-tab coordination** — Q12 single-tab policy ratified 2026-05-04 PM. The `broadcast.ts` wrapper stays inert in Phase 7 (no consumer wiring). Mentioned here only because it appears in roadmap §3 Phase 7 row and could be misread as in-scope.

Compared to Phase 6's parity scope (port existing features into the multiplexer), Phase 7 is **add new cross-cutting concerns to the already-ported feature set**. The 4 sub-areas have **near-zero functional overlap** with each other (telemetry instruments; CSP gates network/script loading; Trusted Types gates DOM sinks; accessibility augments semantic markup) — each can be designed, reviewed, and implemented as its own self-contained PR without blocking the others on shared mutable state.

Slicing into 7a/7b/7c/7d serves three goals:

1. **Reviewer attention focus** — each sub-area has its own canonical references (W3C CSP spec, Trusted Types spec, WCAG 2.1, OTel browser SDK docs). Bundling them into one design doc would force one reviewer to context-switch across 4 distinct specs in one pass.
2. **Commit blast radius** — each slice's diff is reviewable independently. A reviewer evaluating CSP policy doesn't need to mentally parallel-track keyboard-nav ARIA changes.
3. **Mid-phase pivot affordance** — if any slice surfaces a contract change (e.g., OTel browser SDK requires a transport bump, or CSP enforcement breaks a legitimate site behavior we hadn't anticipated), the project can redirect that one slice without unwinding the others.

Rick already ratified Option A (slice into 4 sub-areas, one per technical sub-area) on 2026-05-20 prior to this manifest being authored — Tiberius 🌑 confirmed in the brief that prompted this draft.

---

## Slice boundaries

### 7a — Telemetry

**Scope**: instrumentation only — measure, do not change behavior.

| Element | Source |
|---|---|
| User Timing API marks at canonical lifecycle points: boot start, boot complete, first queue render, TTS playback start, WS reconnect, auth refresh | `00-synthesis-and-roadmap.md` §3 Phase 7 row ("explicit User Timing marks at queue render, TTS start, reconnect, refresh") + §2.4 resolution row |
| Long Tasks API observer wired via `PerformanceObserver({ type: 'longtask' })` — emits to telemetry sink | §2.3 OpenAI exclusive findings: "No User Timing, no Long Tasks, no OTel browser SDK" |
| ReportingObserver registration for `deprecation` + `intervention` + `crash` reports | §2.3 OpenAI exclusive findings (Phase D in OpenAI's framing) |
| OTel browser SDK initialization + minimal instrumentation: page-load span, first-input-delay span, key user-action spans | §3 Phase 7 row |
| `multiplexer/observability/timing.ts` + `multiplexer/observability/otel.ts` modules (already enumerated as Phase 7 stubs in `00-synthesis-and-roadmap.md` §4.2 directory layout) | §4.2 directory layout |
| Perf budget gates (smoke-tier): boot < N ms (TBD-at-design), first-queue-render < N ms, longtask count < K per minute under typical load | Inherits Phase 6a/b/c AC machinery; budget literals TBD at slice design time |
| Telemetry sink config (env-driven endpoint; OTLP/HTTP collector) | New |

**Dependencies**: Phase 1-6 stores + renderers + transports exist (all merged); OTel browser SDK version pin TBD (Recon-7a-1); `multiplexer/observability/*` stubs from §4.2 directory layout become real modules (currently absent).

**Independence**: 7a doesn't modify any existing UI surface or transport contract — it adds instrumentation hooks at known call sites. Could land before, after, or interleaved with 7b/c/d without conflict on functional behavior. **Caveat**: if 7b CSP is already enforced when 7a lands, the OTel browser SDK CDN/script-src origin must be allow-listed in CSP — coordination concern surfaced in §Recommended order.

### 7b — Content Security Policy (CSP)

**Scope**: response-header policy, not source-code change. Two-phase rollout: report-only → enforce.

| Element | Source |
|---|---|
| `Content-Security-Policy-Report-Only` header emitted by FastAPI route serving `multiplexer.html` (initial policy: tight allow-list of `script-src`, `style-src`, `connect-src`, `font-src`, `img-src`, `frame-ancestors 'none'`) | `00-synthesis-and-roadmap.md` §3 Phase 7 row ("CSP report-only, Trusted Types"); §2.3 OpenAI exclusive findings (CSP/Trusted Types) |
| Reporting endpoint at new FastAPI route `/api/csp-report` (accepts violation reports; logs at structured-log level) | New |
| Iterative tightening: collect violations over N-day report-only window; close legitimate gaps; flip `Content-Security-Policy-Report-Only` → `Content-Security-Policy` (enforce) when violation count is zero across full UI exercise | New |
| `Reporting-Endpoints` HTTP header + `report-to` CSP directive for modern Reporting API (parallel to legacy `report-uri`) | New |
| Server-side router/middleware for header emission scoped to `/app/multiplexer` route only — does NOT touch `/app/notifications` legacy route | Phase 6 manifest carryover (`notifications.html` frozen) |

**Dependencies**: Greenfield commitment to **no inline handlers** (already enforced via Phase 1 design + Phase 2/3/4/5/6 patterns — every renderer uses `addEventListener` and `<template>` cloning); reporting endpoint must exist before report-only header makes sense; Trusted Types directive (`require-trusted-types-for 'script'`) is held back to slice 7c.

**Independence**: 7b changes server response headers + adds one new endpoint. Zero JS/TS source changes in the multiplexer module tree. Independent from 7a/c/d functionally; **coupled to 7c** via the `require-trusted-types-for` CSP directive (7c REQUIRES the CSP header mechanism 7b puts in place — see §Recommended order).

### 7c — Trusted Types

**Scope**: introduce Trusted Types policy + enable browser-level enforcement via CSP directive.

| Element | Source |
|---|---|
| `multiplexer/shared/trustedTypes.ts` — single named policy (`lupin-multiplexer-policy`) implementing `createHTML` / `createScript` / `createScriptURL` factories | New |
| Audit every dynamic-HTML construction site in multiplexer codebase (`<template>` cloning is already safe; tagged-template `html` helper is the canonical sink); refactor any unsafe-sink usages discovered | §2.3 OpenAI exclusive findings (Trusted Types directive); inherits Phase 5/6 `feedback_sanitize_at_boundary_not_format_strip` doctrine |
| Add `require-trusted-types-for 'script'` directive to the CSP header set up in 7b; `trusted-types lupin-multiplexer-policy 'allow-duplicates'` policy directive | New (extends 7b's policy) |
| Same two-phase rollout pattern: report-only → enforce, with violation-report watching for sink violations during the report-only window | Mirrors 7b's rollout pattern |
| Test surface: extend per-renderer unit tests to assert TrustedHTML is the type flowing through `replaceChildren` / `insertAdjacentHTML` sinks (none of which should exist by line 1 of Phase 6, but a defense-in-depth assertion) | Phase 6 AC2e grep guard pattern extension |

**Dependencies**: **Hard dependency on 7b** — Trusted Types is enabled via CSP directive (`require-trusted-types-for 'script'`), which requires the CSP header mechanism 7b provides. The roadmap §2.3 framing — "Greenfield bans inline handlers from line one" — means most enforcement is already there culturally; 7c FORMALIZES it browser-side.

**Independence from 7a + 7d**: zero overlap. 7c does not touch telemetry instrumentation or a11y semantic markup.

### 7d — Accessibility

**Scope**: WCAG 2.1 AA conformance for the multiplexer UI — ARIA, keyboard, screen reader, focus management, reduced-motion.

| Element | Source |
|---|---|
| WCAG 2.1 AA audit using axe-core (or equivalent) — produces a finding list per pane | `00-synthesis-and-roadmap.md` §3 Phase 7 row ("accessibility audit") |
| ARIA landmarks (`role="navigation"`, `role="main"`, `role="complementary"` for focus tray); ARIA labels on icon-only buttons (focus mode toggle, record, send); `aria-live` regions for notification + job status updates | New |
| Keyboard navigation paths: Tab order across panes; Escape-to-close-popover (Phase 6c persona modal already uses native Popover API close-on-Escape — verify); focus traps inside open popovers | Phase 6c F-Arnold-5 confirmed Popover API close mechanics — 7d formalizes the navigation model |
| Screen-reader pass: NVDA (Windows) + VoiceOver (macOS) live-region announcement verification for `aria-live="polite"` notification text | New |
| Focus management: focus return on popover close; focus restoration on focus-mode toggle (Phase 6c Section B's `data-focus-hidden` introduces a focus-visibility concern — keyboard users navigating into a now-hidden card) | Coordinates with Phase 6c Section B mechanics |
| `prefers-reduced-motion` media query support for Phase 6c animations (`@keyframes focus-flash`, persona-modal accent strip transitions, mic-monopoly pulse) | Phase 6c B-CSS owns `@keyframes focus-flash`; 7d adds the reduced-motion variant |
| Color contrast: per-persona-color readability check against background per WCAG 1.4.3 (1.4.6 for AAA, AA only here) | Persona color pool already constrained per `feedback_no_green_in_persona_pool`; 7d verifies AA contrast pass for all live pool entries |

**Dependencies**: Phase 1-6 multiplexer UI complete and merged (especially Phase 6c — adds focus-tray + persona modal which are the densest a11y surfaces); axe-core or equivalent a11y test tool (npm dev dep); screen reader access (NVDA / VoiceOver) for verification — these are HUMAN-execute verifications, NOT pytest-automatable per `feedback_long_running_tests` + the "user is never a tester" mandate caveat for genuinely-subjective UX checks.

**Independence**: 7d is the most UI-coupled but is mostly additive (ARIA attrs, semantic landmarks, focus-management) — minimal source-level conflict with 7a/b/c. **Caveat**: 7d's `prefers-reduced-motion` work touches the same CSS files Phase 6c authored (`conversation-mode-pin.css`, `focus-tray.css`, `persona-modal.css`). Coordination is design-time only; no merge conflict expected since 7d adds new `@media (prefers-reduced-motion: reduce) { ... }` blocks at end-of-file.

---

## Recommended order

**7a → 7b → 7c → 7d** is the recommended sequencing. **This is a Rick-ratification decision** — pros/cons + flip-conditions below per `feedback_always_include_pros_cons_recommendation`.

### Per-slice ordering rationale

1. **7a first (Telemetry)** — observability before lockdown. The roadmap §3 ordering principle ("observability before launch beats observability after regressions") is the load-bearing intent of Phase 7. Telemetry is the diagnostic infrastructure for every subsequent slice: 7b CSP rollout needs violation visibility (telemetry catches the violation-rate trend); 7c Trusted Types audit needs perf telemetry to confirm policy enforcement doesn't slow renders; 7d a11y audit needs Long Tasks telemetry to verify screen-reader-driven re-renders don't blow the perf budget. Landing telemetry first makes every later slice measurable.

2. **7b second (CSP report-only)** — cheap signal-gathering before tightening. Report-only mode is **zero behavioral risk** — the browser logs violations but does not block. Landing CSP report-only second lets the report-only window run in parallel with 7c authoring (collecting CSP violations is passive once headers are emitted). This compresses the timeline. **Risk-profile bonus**: 7a → 7b sequencing means the report-only collection window is exactly when CSP catches if 7a's OTel browser SDK CDN / `script-src` origin needs allow-listing — the discovery is passive and pre-enforce, vs Option B where 7b enforces before 7a even lands and any telemetry-CDN gap manifests as a hard block.

3. **7c third (Trusted Types)** — hard dependency on 7b's CSP header mechanism. Trusted Types is enabled via the `require-trusted-types-for` CSP directive, which requires the CSP infrastructure 7b provides. 7c also benefits from a report-only window for Trusted Types itself before enforce — landing third gives the CSP report-only collection time to produce violation data that informs the Trusted Types audit.

4. **7d fourth (Accessibility)** — most stable when the UI is no longer churning. WCAG audit produces a finding list against a fixed UI surface; running the audit while 7a/b/c are landing means the findings are against a moving target. Land a11y after the security/observability work has settled so the audit captures the final shape.

### Decision space for Rick (4 ordering options)

| Option | Order | Pro | Con | Flip-condition |
|---|---|---|---|---|
| **A (recommended)** | 7a → 7b → 7c → 7d | Telemetry-first matches roadmap §3 "observability before launch" intent; 7b's report-only window can run in parallel with 7c authoring; a11y audit hits a stable surface | Pushes a11y to end; if a11y stakeholders are blockers, this is too late | Flip to Option D if a11y stakeholder is in critical path |
| B | 7b → 7c → 7a → 7d | Security-first; CSP + Trusted Types land before any new telemetry source is enabled (no risk of telemetry CDN being blocked by enforced CSP) | Defers observability — Phase 7's defining feature — to the back half; CSP rollout has no telemetry to measure violation trend during report-only window | Flip to A if telemetry value is judged higher than security-first sequencing |
| C | 7c → 7b → 7a → 7d | Trusted-Types-first to lock down dynamic-HTML sinks before any new code lands (defense-in-depth) | 7c has a hard dependency on 7b — can't land Trusted Types without CSP infrastructure. Would require collapsing 7b into 7c or reordering | **Invalid** under current slice boundaries — would need slice-boundary redraw |
| D | 7d → 7a → 7b → 7c | Accessibility-first because a11y stakeholders are the blocker for shipping | a11y audit against a churning UI means re-audit after 7a/b/c land; doubles audit cost | Flip to A if a11y is not on the critical path |

### My recommendation: Option A (7a → 7b → 7c → 7d)

**Why**: telemetry is the diagnostic infrastructure for everything else in Phase 7. CSP report-only is cheap and can collect data in parallel with 7c authoring. Trusted Types needs 7b. A11y is most efficient when the UI is stable.

**Flip-condition**: if Rick has a11y stakeholder pressure (W3C audit deadline, partner requirement, regulatory date), flip to Option D and treat 7d as critical path.

---

## Permanently out of scope (across all 4 slices)

Inherits from `00-synthesis-and-roadmap.md` §3 "What is NOT in this roadmap" + Phase 6 manifest carryover:

- **Token storage migration** — server-side change, out of scope per §3. The OWASP localStorage-for-session-tokens finding is a server-side follow-up flagged in §2.3.
- **HttpOnly cookies + CSRF** — server-side follow-up, out of scope per §2.3 OpenAI exclusive findings.
- **Service Worker / offline outbox** — deferred per §3 "What is NOT in this roadmap"; Phase 7+ candidate but not committed.
- **Switch to React/Vue/Svelte** — vanilla TS + tagged templates is the chosen path per §3.
- **Multi-tab BroadcastChannel features** — Q12 single-tab application policy ratified 2026-05-04 PM; the `broadcast.ts` wrapper stays inert in Phase 7. Mentioned in §3 Phase 7 row only because the inert wrapper exists in the Phase 2 foundation; no consumer wiring in 7a-7d.
- **Modifying `notifications.html`** — frozen until cutover per Q9 unbounded coexistence; Phase 6 manifest carryover.
- **`claude_code_event` consumer** — D1 A-extended ratification (2026-05-04 PM); Phase 6 manifest carryover. CC infrastructure being torn down (bug-fix-queue retirement of `/api/claude-code/dispatch` per commit `73bee1b`).
- **Forced cutover from `/app/notifications`** — Q9 unbounded coexistence; legacy page survives Phase 7 unchanged. Phase 9 cutover is a separate phase.
- **AAA-tier accessibility** — 7d targets WCAG 2.1 AA; AAA features (1.4.6 enhanced contrast, sign-language interpretation, low-or-no-background-audio) are out of scope. 1.4.3 AA contrast is in.
- **i18n / l10n** — not in scope per pre-existing roadmap silence; flagged here only because a11y audits sometimes surface i18n adjacencies.
- **Perf budget dashboards (consumer-side)** — 7a captures telemetry; consuming it in a dashboard is a separate Lupin-wide initiative (out of scope for the JS-only refactor).
- **CSP for non-multiplexer routes** — 7b's CSP headers scope to `/app/multiplexer` only; `/app/notifications`, `/app/docs`, admin routes etc. retain their current header set.

---

## Per-slice file naming

Following the existing R&D directory convention. Renumbered 2026-05-20 to make room for per-slice pre-cascade recon docs (ratified ON per §Ratification outcomes #2). Each slice gets 4 docs: recon → design → cascade synthesis → execution plan.

| Slice | Pre-cascade recon | Design doc | Cascade artifacts (gitignored) | Review findings | Cascade synthesis | Execution plan |
|---|---|---|---|---|---|---|
| 7a | `14-phase7a-telemetry-pre-cascade-recon.md` | `15-phase7a-telemetry-design.md` | `io/commons/cascaded-prototype-phase-7a-section-*` | `94-phase7a-review-findings.md` | `16-phase7a-cascade-synthesis.md` | `17-phase7a-execution-plan.md` |
| 7b | `18-phase7b-csp-pre-cascade-recon.md` | `19-phase7b-csp-design.md` | `io/commons/cascaded-prototype-phase-7b-section-*` | `95-phase7b-review-findings.md` | `20-phase7b-cascade-synthesis.md` | `21-phase7b-execution-plan.md` |
| 7c | `22-phase7c-trusted-types-pre-cascade-recon.md` | `23-phase7c-trusted-types-design.md` | `io/commons/cascaded-prototype-phase-7c-section-*` | `96-phase7c-review-findings.md` | `24-phase7c-cascade-synthesis.md` | `25-phase7c-execution-plan.md` |
| 7d | `26-phase7d-accessibility-pre-cascade-recon.md` | `27-phase7d-accessibility-design.md` | `io/commons/cascaded-prototype-phase-7d-section-*` | `97-phase7d-review-findings.md` | `28-phase7d-cascade-synthesis.md` | `29-phase7d-execution-plan.md` |

Numbering reserves the prior space (00-12 already taken; 13 is this manifest; Phase 6c synthesis + execution plan at 11-12 set the precedent for triple-doc-per-slice — Phase 7 extends to quadruple-doc-per-slice with the pre-cascade recon prepended).

Each slice's design doc has the same shape as the Phase 6c design doc (`10-phase6c-persona-focus-recorder-design.md`): per-feature scope tables, ACs, Recon items (resolved upstream in the recon doc), OSQs, dependencies, browser-API surface, test pyramid plan.

---

## Acceptance per slice

Each slice inherits Phase 6's AC machinery patterns (per `07-phase6-slicing-manifest.md` § Acceptance):

| AC | Inheriting from Phase 6 | Adaptation per Phase 7 slice |
|---|---|---|
| AC1 | `tsc --noEmit` exit 0 | Same |
| AC2 | `eslint` exit 0 | Same |
| AC2e | Safe-write grep guard (no `.innerHTML =` / `rawHTML(` / `.outerHTML =`) | 7c EXTENDS — Trusted Types policy assertion in tests |
| AC3-AC5 | Per-file unit-test floors with vitest | Per-slice: 7a observability modules; 7b reporting endpoint; 7c policy + sink audit; 7d ARIA/focus tests |
| AC6 | **100% c8 coverage Lupin-wide** (line + branch + function via `c8 --100` per `feedback_100pct_coverage_multiplexer` — scope expanded 2026-05-16 from multiplexer-only) | Directory-wide glob enforces — no per-slice file-list drift |
| AC7 | Stylelint exit 0 + per-CSS LOC ceiling | Only 7d touches CSS (reduced-motion blocks); 7a/b/c are TS + server only |
| AC8a | Functional smoke on `:7999` | Per-slice smoke: 7a marks emission; 7b header presence; 7c policy installed; 7d ARIA tree |
| AC8b | Perf gate | 7a defines the perf budget; 7b/c/d MUST NOT regress past 7a's baseline |
| AC9 | `boot_complete` handshake | 7a adds `timingInstrumentation:initialized` (or similar); others unchanged |
| AC10 | Phase regression suites green | Phase 1/3/4/5/6 regression suites remain green after each slice |
| AC10b | gz boot.js delta ≤ +N KB vs prior phase baseline | 7a adds OTel SDK weight — may need ceiling bump per Q-I-style decision; 7b is zero JS-bundle delta; 7c adds tiny policy module; 7d adds zero JS (CSS + ARIA attrs only) |
| AC11a + AC11b | Scheduled `:8000` visual regression baseline via `POST /api/test-suite/submit` with `pytest_args="-k <slice>"`, `auto_fix_on_failure: False` per `feedback_baseline_capture_disable_tfe` | Per-slice; 7d generates the most new visual baselines (reduced-motion variants) |

**Slice-specific AC additions**:

- **7a**: AC-7a-TEL: User Timing marks appear at canonical lifecycle points (smoke assertion against `performance.getEntriesByType('mark')`); AC-7a-LT: Long Tasks observer wired (PerformanceObserver mock test); AC-7a-OTEL: OTel browser SDK page-load span emitted (mock collector assertion).
- **7b**: AC-7b-HDR: CSP report-only header present on `/app/multiplexer` (integration test asserting response header); AC-7b-REP: violation report endpoint accepts well-formed report payloads (Pydantic-validated per `feedback_pydantic_native_validation`); AC-7b-FLIP: post-collection-window flip to enforce is a manual decision gate (HUMAN slot-coordination), not pytest-automated.
- **7c**: AC-7c-POL: `trustedTypes.createPolicy('lupin-multiplexer-policy', ...)` succeeds at boot; AC-7c-SINK: every dynamic-HTML sink in multiplexer module tree passes TrustedHTML (grep for `.innerHTML = ` / `insertAdjacentHTML(` / `document.write(` — expect zero hits per AC2e); AC-7c-CSP: `require-trusted-types-for 'script'` directive emitted in CSP header (extends AC-7b-HDR).
- **7d**: AC-7d-AXE: axe-core scan returns zero serious/critical violations against `/app/multiplexer` (smoke-tier); AC-7d-KBD: keyboard-only nav path reaches every interactive control without trap (E2E UI test); AC-7d-SR: screen-reader live-region announcement verified for notification + job state changes (HUMAN-execute verification per "user is never a tester" caveat — genuinely-subjective UX); AC-7d-MOT: reduced-motion media query suppresses all Phase 6c animations (CSS computed-style assertion).

`boot.js` gz ceiling per slice will be re-baselined from the prior slice's actual gz size, not the Phase 6c frozen literal. 7a's OTel SDK weight is the biggest single contributor — design doc captures the literal at the time it lands.

---

## Cascade-readiness check per slice

Each slice is evaluated for fit with the 4-stage cascaded plan-authoring workflow (Author Stage 0 + 3 reviewer Stages 1/2/3). Cascade fit ≠ implementation effort; it's about whether the slice has enough design surface to warrant 3 review passes.

| Slice | Cascade fit | Notes |
|---|---|---|
| **7a Telemetry** | ✅ Strong | Design-driven: instrumentation point choice, OTel SDK version pin, perf budget literals, sampling strategy. 4-stage cascade with REUSE / Pass 1 Fitness / Pass 2 Ownership-Language Audit (per `feedback_pass2_is_ownership_audit_not_security`) reviewer panel applies well. |
| **7b CSP** | ⚠️ Mixed | Initial header design is cascade-shaped (policy directive choice, report endpoint shape, browser support matrix). Iterative tightening loop (report-only window → close gaps → flip) is operational, not design-shaped — may want a single design cascade + multiple follow-on tightening commits gated by violation-rate metrics, NOT a second cascade. |
| **7c Trusted Types** | ✅ Strong | Design-driven: policy contract (createHTML / createScript / createScriptURL signatures), sink audit methodology, integration with 7b CSP header. Coupled to 7b but the coupling is at policy-installation boundary, not at design-doc boundary. |
| **7d Accessibility** | ⚠️ Mixed | WCAG audit is **checklist-driven** more than design-driven — running axe-core against the multiplexer produces a finding list that drives the work, but the finding list itself isn't authored in a design doc. ARIA labeling decisions, focus-management mechanics, and reduced-motion media-query design are design-shaped. Recommend: 7d design doc captures the **mechanisms** (ARIA contract, focus-restoration pattern, reduced-motion strategy), then a follow-on **audit-driven implementation cycle** runs axe-core, classifies findings, and lands fixes commit-by-commit. |

**Flag for Rick**: 7b's iterative tightening loop and 7d's audit-driven implementation cycle are both **non-cascade-shaped operational phases** that follow the cascade-shaped design phase. Suggest treating each slice as **one cascade (design) + one operational close-out phase (tightening / audit-finding implementation)** to keep the doctrine clean.

---

## Pre-cascade recon (per slice)

Phase 6c had Recon-D1..D4 surfaced AT cascade time. Phase 7 has more new-Browser-API surface than 6c — a **pre-cascade recon pass per slice** may be cheaper than inline-cascade recon. Decision to surface to Rick:

| Slice | Recon item | Inline-cascade cost | Pre-cascade cost |
|---|---|---|---|
| 7a | OTel browser SDK version pin (e.g., `@opentelemetry/sdk-trace-web` vs `@opentelemetry/auto-instrumentations-web`) | Reviewer must research at Stage 1 | Author resolves before cascade fires |
| 7a | Long Tasks API browser support floor (Chrome / Firefox / Safari minimums per Phase 1 modern-browsers commitment) | Same | Same |
| 7b | Reporting API (`Reporting-Endpoints` header) browser support floor vs legacy `report-uri` directive | Same | Same |
| 7b | CSP directive choice: nonce vs hash vs strict-dynamic (each has tradeoffs for the multiplexer's static-bundle shape) | High — reviewers may diverge on best choice | Low — author resolves with current best practice |
| 7c | Trusted Types browser support floor (Chrome 83+ / FF 116+ flag / Safari recent — Phase 1 modern-browsers floor includes which?) | Same | Same |
| 7c | Sink audit methodology: TypeScript-compiler-driven (search for `as TrustedHTML` opportunities) vs grep-driven vs ESLint-rule-driven | Reviewer must propose | Author resolves |
| 7d | axe-core version pin + integration approach (npm dev dep vs CDN vs Playwright integration) | Same | Same |
| 7d | Screen reader testing process (NVDA on Windows VM, VoiceOver on macOS — which is canonical; both required) | Reviewer must clarify | Author resolves with Rick |

**My recommendation**: a 1-2 hour pre-cascade recon doc per slice (`<slice>-pre-cascade-recon.md`) BEFORE the design-doc cascade fires. Cost: 4-8 hours total recon. Benefit: each cascade pass focuses on design decisions rather than browser-API archaeology.

**Decision-space for Rick**: ratify pre-cascade recon ON / OFF. Default ON per recommendation.

---

## Where this manifest lives in the cadence

This doc IS the slicing decision artifact. It does NOT replace per-slice design docs — those are the next deliverables, one per slice, drafted via the cascaded plan-authoring workflow.

**Next steps** (in order):

1. **Tiberius 🌑 greenlight** of this draft (manifest shape + slice boundaries + sequencing recommendation).
2. **Rick ratification** of: (a) recommended sequencing order (Option A vs B vs C vs D); (b) pre-cascade recon ON / OFF; (c) 7b's iterative-tightening operational phase decoupling from cascade shape; (d) 7d's audit-driven implementation cycle decoupling from cascade shape.
3. **First slice's design doc cascade fires** — likely Run 4 of the cascaded workflow (per Tiberius's brief; the first live test of Step 9 doctrine post-Phase-6c). Author rotation TBD by Rick; likely Rachel 🕊️ continues as canonical author, with Mr. Radio 🦉 (this manifest's author) returning to Persona 3 (Usability/Reuse Reviewer) for the cascade itself.

**No code is written until per-slice design docs are ratified and per-slice execution plans drafted.** Phase 7 implementation begins only after Phase 6c closes (Tiffany 💍's current node).

---

## Pre-exit self-audit (against feedback memory)

Per `feedback_plan_self_audit_against_memory` + `feedback_audit_plans_at_execute_time`:

| Memory | Compliance check |
|---|---|
| `feedback_phase0_serialization_prominence` | n/a — this is a Phase 7 slicing manifest, not a Phase 0 decision doc |
| `feedback_plans_include_tracking_docs` | ✅ §Per-slice file naming enumerates design + cascade synthesis + execution plan + review findings per slice |
| `feedback_comprehensive_automated_testing` | ✅ §Acceptance per slice enumerates unit + smoke + integration + E2E layers per slice |
| `feedback_documentation_step_stops_at_doc` | ✅ This manifest IS the doc — no auto-progression to code or ExitPlanMode |
| `feedback_test_server_monopolize_mode` | ✅ §Acceptance AC11a/b routes all `:8000` work via `POST /api/test-suite/submit` with non-overlapping `scheduled_at` |
| `feedback_baseline_capture_disable_tfe` | ✅ §Acceptance AC11a explicitly cites `auto_fix_on_failure: False` per memory |
| `feedback_pip_plan_review_is_sequential` | ✅ §Cadence per slice cites "REUSE → Pass 1 → Pass 2, sequential never parallel" |
| `feedback_100pct_coverage_multiplexer` (Lupin-wide post-2026-05-16) | ✅ §Acceptance AC6 cites 100% c8 line + branch + function via directory-wide glob |
| `feedback_pydantic_native_validation` | ✅ §Acceptance AC-7b-REP cites Pydantic-validated reporting endpoint |
| `feedback_pass2_is_ownership_audit_not_security` | ✅ §Cascade-readiness check uses correct terminology ("Pass 2 Ownership-Language Audit") |
| `feedback_lupin_only_never_cosa` | ✅ All paths under `src/fastapi_app/`; no CoSA submodule references |
| `feedback_never_auto_commit_push` | ✅ Manifest commits no code; explicit "no code is written" gate before per-slice ratification |
| `feedback_audit_plans_at_execute_time` | ✅ This self-audit IS the execute-time re-check |
| `feedback_always_include_pros_cons_recommendation` | ✅ §Recommended order presents 4 options with pros + cons + recommendation + flip-conditions |
| `feedback_tests_must_cover_cross_target_invocations` | ⚠️ 7a's OTel SDK has CDN vs npm dep choice — recon item flagged; cross-target invocation surface (e.g., bundle-from-CDN tests) TBD at slice design time |
| `feedback_recraft_speech_dont_pipe_terminal` + `feedback_tts_body_headline_and_takeaway_only` | n/a at draft time — applies to author's mid-flow `notify()` calls |
| `feedback_doc_links_always_in_abstract` | n/a — applies to runtime `notify()` calls, not this serialized doc |
| `feedback_no_green_in_persona_pool` | n/a (a11y color-contrast verification in 7d cites the rule; not violated) |
| `feedback_tests_parameterize_base_url` | ✅ All test references rely on `LUPIN_API_URL` indirection per memory |
| `feedback_skip_rnd_doc_for_trivial_fixes` | n/a — non-trivial slicing decision, full doc applies |

No violations detected at draft time. Tiberius's review will catch what self-audit misses.

---

## Ratification outcomes (2026-05-20)

| # | Decision | Outcome | Ratified by |
|---|---|---|---|
| 1 | Sequencing order | **Option A** — 7a Telemetry → 7b CSP → 7c Trusted Types → 7d Accessibility | Rick |
| 2 | Pre-cascade recon ON / OFF | **ON** — each slice gets a 1-2h author-side recon doc before its design-doc cascade fires (4-8h total) | Rick |
| 3 | 7b CSP iterative-tightening operational-phase decoupling | **Decoupled** — 7b lands as one design cascade + one operational tightening loop (not a second cascade) | Rick |
| 4 | 7d Accessibility audit-driven implementation operational-phase decoupling | **Decoupled** — 7d lands as one design cascade + one operational audit-finding cycle (not a second cascade) | Rick |

**First-slice author assignment**: TBD — Rachel 🕊️ is the canonical cascade Author for Runs 1-3; rotation pending Rick's call. Mr. Radio 🦉 (this manifest's author) likely returns to Persona 3 (Usability/Reuse Reviewer) for the cascade itself.

**Cross-doctrine note**: this manifest's §Pre-cascade recon section is empirical validation for the Step 0 doctrine that Tiberius 🌑 + María 🌸 are codifying on the PIP side. When the Step 0 doctrine commits, a one-line back-ref lands in the doc footer per Tiberius's observation #2.

---

## Open follow-ups (cross-cutting)

| Filed | Source | Note |
|---|---|---|
| 2026-05-20 | Tiberius observation #2 | Once Step 0 cascade-prep doctrine commits to planning-is-prompting (likely with María 🌸's codification), add one-line back-ref to that doc here so this manifest's §Pre-cascade recon becomes a v1 empirical anchor. |
| 2026-05-20 | Phase 6c interlock | Phase 7 implementation begins ONLY after Phase 6c closes. Tiffany 💍 has Node C in flight (C1 + C2 done; C3-C7 pending) — likely tonight or tomorrow per Tiberius's brief. First-slice pre-cascade recon kicks off on 6c close. |

---

— Mr. Radio 🦉 (Author, Lupin session `32a6e563`) — Phase 7 slicing manifest, draft for Tiberius 🌑 greenlight + Rick ratification.

---

## Doctrine cross-refs

| Doctrine | Anchor | Codified in | Relationship to this manifest |
|---|---|---|---|
| **Step 0 cascade-preparation doctrine** | PIP commit `bbb3e47` (Tiberius 🌑 + María 🌸, 2026-05-20) | `planning-is-prompting/workflow/plan-authoring-cascaded-common.md` §Step 0 + `planning-is-prompting/src/rnd/2026.05.20-step-0-cascade-preparation-doctrine.md` | This manifest's §Pre-cascade recon section is **empirical anchor #1** for Step 0 — a fresh-cast author independently arrived at the recon-before-cascade framework Step 0 codifies. Per-slice recon docs (`14-`, `18-`, `22-`, `26-`) are empirical anchor #2+. Cascade Run 4 will be the first live test of BOTH Step 0 and Step 9 doctrine. |
| **Step 9 synthesis-and-handoff doctrine** | RATIFICATION-CLOSED 2026-05-19 (Tiberius 🌑 + María 🌸); validation-pending-Run-4 | `planning-is-prompting/workflow/plan-authoring-cascaded-common.md` §Step 9 (validation-pending) | Phase 6c Run 3 surfaced the synthesis-and-handoff gap; doctrine drafted same day. Phase 7's first cascade (likely 7a Telemetry) will validate the codification. |
