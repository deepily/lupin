# 2026.05.09 — Claude Code Notifications-UI Card Normalization

**Status**: ⏳ Phase 0 docs serialized 2026-05-10; awaiting `/plan-review` REUSE → Pass 1 → Pass 2 (sequential).
**Pattern**: Pattern 5 (Refactor) in scope, Pattern 3 in shape (single-design-doc + execution-log; no Pattern A/B/C scaffolding).
**Branch**: `wip-v0.1.7-2026.04.22-spit-and-polish-for-cjflow-tfe-and-bfe`
**SHORT_PROJECT_PREFIX**: [LUPIN]
**Scope marker**: Parent Lupin repo + one CoSA-side router edit (Track B). NO multiplexer TS changes — 100% c8 mandate does NOT apply.
**Origin plan file**: `~/.claude/plans/ok-so-far-so-swirling-pearl.md` (approved 2026-05-10 via ExitPlanMode; this R&D folder is the canonical serialization)
**last-reviewed-at**: 2026-05-11 (commit `c1cec74` — pre-implementation HEAD on branch `wip-v0.1.7-2026.04.22-spit-and-polish-for-cjflow-tfe-and-bfe`; all 3 plan-review passes CLOSED: REUSE + Pass 1 Fitness + Pass 2 Adversarial)

---

## Quick Navigation

| Doc | Purpose |
|-----|---------|
| [00-index.md](00-index.md) | This file — master nav + idempotency marker home + Q-decisions + REUSE table + open follow-ups |
| [01-design.md](01-design.md) | Full design: context, locked decisions Q1-Q9 FROZEN, 7 phases, ACs, risks, out-of-scope |
| [02-handoff-summary.md](02-handoff-summary.md) | Cross-sub-project handoff (Lupin mobile + multiplexer R&D consumers) — concise ~150-200 line summary |
| [90-execution-log.md](90-execution-log.md) | Phase status table + per-phase evidence (populated as work progresses) |

---

## Project Overview

**Why**: The Claude Code submit card in the notifications UI (`src/fastapi_app/static/html/notifications.html:117-218`, id `claude-code-submit-card`) carries five dead UI blocks left over from the 2026-05-05 retirement of the `/api/claude-code/dispatch` endpoint cluster (commit `73bee1b`, session `1a8900ee`). The submit half of the card already works: it POSTs to `/api/claude-code/queue/submit`, which routes through `agentic_job_factory.create_agentic_job()` — the same factory all six sibling agentic jobs use. What's broken is purely cosmetic: a yellow `.cc-retired-banner` wrapping disabled inject/interrupt/end-session buttons, a `<pre>` response panel showing a retirement notice, a hidden session-info row, and a disabled execution-mode select. Sibling cards have none of these.

**What this normalization solves**: bring the CC submit card down to sibling shape (form + submit button + small status div, period). Rename URL `/api/claude-code/queue/submit` → `/api/claude-code/submit` to drop the `/queue/` infix outlier (it was originally a contrast marker against `/dispatch`; with dispatch retired, it's a dangling fossil). Keep the old URL as a deprecated alias for one release cycle so mobile + integration tests can migrate on their own schedule.

**Architectural picture (NOT changed)**:
- `/api/<agent>/submit` (per-agent typed Pydantic) is the canonical **human UI** path
- `/api/push-agentic` (generic opaque args) is the canonical **agent-to-agent** path
- They serve different consumers by design. This plan does NOT migrate the human UI to `/api/push-agentic`.

**Predecessor R&D**:
- [2026.05.05-claude-code-dispatch-retirement](../2026.05.05-claude-code-dispatch-retirement/01-plan.md) — retired the rogue endpoint cluster; created the gravestones this plan removes
- [2026.05.07-claude-code-bounded-redesign](../2026.05.07-claude-code-bounded-redesign/00-index.md) — in-flight canonical-shape ClaudeCodeJob redesign (NOT touched by this plan; runs in parallel)
- [2026.05.02-notifications-ui-js-refactor](../2026.05.02-notifications-ui-js-refactor/00-synthesis-and-roadmap.md) — multiplexer Phase 6b in flight (consumer of the handoff doc)

---

## Key Decisions (FROZEN 2026-05-09 / 2026-05-10)

See [01-design.md §"Locked design decisions"](01-design.md) for full rationale.

| Q | Question | ✅ Decision |
|---|----------|------------|
| Q1 | URL rename scope | Track A + B with alias. New canonical `/api/claude-code/submit`; keep `/api/claude-code/queue/submit` as deprecated alias for one release cycle |
| Q2 | `#cc-task-type` select handling | Keep the select; promote commented-out INTERACTIVE option to disabled `<option>` with tooltip explaining return condition |
| Q3 | Card `<h4>` header text | `🤖 Submit Claude Code Task` (matches sibling verb-first pattern) |
| Q4 | Status feedback shape | Inline pattern matching siblings (`<div id="cc-submit-status">`, JS sets `textContent` + `style.color`); no shared helper extracted |
| Q5 | E2E test handling for deleted IDs | Full delete of 2 obsolete test functions in `test_job_dispatch.py` |
| Q6 | Phase 0 documentation gate | Serialize BEFORE any code edits (per documentation-first protocol) |
| Q7 | `/plan-review` cycle | Sequential REUSE → Pass 1 Fitness → Pass 2 Adversarial; implementation BLOCKED until Pass 2 closes |
| Q8 | Decorator-stack failure fallback | If FastAPI rejects stacked-`@router.post(...)`, COMMENT OUT (not delete) the deviant `/queue/submit` decorator with a breadcrumb; mobile + smoke tests migrate immediately |
| Q9 | Cross-sub-project handoff requirement | One concise `02-handoff-summary.md` + seed TODO entries in mobile + parent Multiplexer-section + multiplexer R&D `00-synthesis-and-roadmap.md` |

---

## Phase Summary

| Phase | Status | Notes |
|-------|--------|-------|
| 0 — Documentation (R&D doc set) | ✅ DONE 2026-05-10 | This file + 01-design + 02-handoff-summary + 90-execution-log all serialized |
| **GATE — PIP plan review** | ✅ CLOSED 2026-05-11 | All 3 passes closed sequentially. REUSE: 3/8 fixes applied. Pass 1 Fitness: 8/11 findings applied. Pass 2 Adversarial: 7/7 findings applied + 1 swept pattern offender. Idempotency marker stamped (commit `c1cec74`). |
| 1 — Track A: HTML normalization | ✅ DONE 2026-05-11 (session 658ea35d, Mr. Radio) — 8 sub-steps; AC1, AC1.5, AC2, AC3, AC4 GREEN |
| 2 — Track A: JS handler normalization | ✅ DONE 2026-05-11 — submitClaudeCode/submitClaudeCodeToQueue rewritten to sibling shape; AC5, AC6 GREEN |
| 3 — Track A: E2E test cleanup | ✅ DONE 2026-05-11 — 2 obsolete tests deleted, 1 sibling-shape test added; py_compile clean; AC8 partial (full verification at 5.8) |
| 4 — Track B: URL rename + alias | ✅ DONE 2026-05-11 — **Q8 PRIMARY**: stacked decorators register BOTH routes; deprecation log live; 2 smoke-test constants updated |
| 4.5 — Cross-sub-project handoff doc finalize | ✅ DONE 2026-05-11 — Q8 verdict populated as PRIMARY in 02-handoff-summary.md |
| 5a — Local verification (`:7999`) | ✅ DONE 2026-05-11 — 5.1-5.6 + 5.11 all GREEN; AC7, AC9, AC12 GREEN. 5.7 folded into 5.8 |
| 5b — Scheduled verification (`:8000`) | ⏳ AWAITING USER SLOT — 5.8/5.9/5.10 pending |
| 6 — Wrap (TODO + history + commits) | ⏳ PARTIAL — docs/tracking landed; commits held for user authorization |

---

## Doc Conventions Status

Per `workflow/p-is-p-02-documenting-the-implementation.md` §"Doc Conventions for Plan-Review Compatibility":

| Convention | Where | Status |
|-----------|-------|--------|
| 1 — Working-contract anchor | (not separately created — small-plan exception; Q-N decisions in 01-design.md serve as the contract anchor) | ⚠️ Implicit; will validate during plan-review whether a separate `00-working-contract.md` is required for plans of this size |
| 2 — Decision-anchor format (Q-N FROZEN) | `01-design.md` §"Locked design decisions" | ✅ All 9 Q-N FROZEN entries with Question / ✅ Decision / Rationale |
| 3 — `EXECUTOR: AI / HUMAN` tagging | `01-design.md` Phase 1-6 + Verification | ✅ Each phase tagged at top; HUMAN owners called out where applicable (user slot-confirmation for `:8000` scheduled tests) |
| 4 — `TBD` / `Open sub-question` markers | `01-design.md` | ✅ N/A — all 9 decisions FROZEN, no design TBDs at serialization time |
| 5 — "Manual E2E" semantics | `01-design.md` | ✅ Phase 5.7 explicitly programmatic-via-headless ("AI executes via headless browser, NOT human-driven"); no "Manual E2E = human" claims |

---

## Open follow-ups

(Empty at serialization time. Will be populated as plan-review surfaces deferrals.)

### Skip-with-reason log

(Empty at serialization time.)

---

## Prior art referenced

REUSE pre-pass executed 2026-05-10 (single Explore agent against `src/fastapi_app/`, `src/cosa/rest/routers/`, `src/tests/`, `src/fastapi_app/static/css/`). Outcome: 4 reuse-as-is + 1 extend-existing (CSS orphan) + 3 genuinely-new (justified). Zero blocking; zero material drift in author's pre-REUSE table. Spot-check verifications recorded inline below.

### `reuse-as-is` (verified to copy verbatim or use directly)

| Pattern | Source (file:line) | REUSE 2026-05-10 verification |
|---------|---------------------|--------|
| Sibling submit-status JS pattern | `src/fastapi_app/static/js/notifications.js:2870-2949` (research handler) | ✅ Lines 2873 (`statusDiv = document.getElementById('research-submit-status')`), 2889 (button disable), 2890 (spinner show), 2892/2936/2944 (neutral-`#666` / green-`#28a745` / red-`#dc3545`) all confirmed. Mirror verbatim; no shared helper. |
| Sibling status-div HTML inline-style pattern | `notifications.html:272, 319, 381, 441` | ✅ All 4 lines verified: `<div id="<agent>-submit-status" style="margin-top: 8px; font-size: 12px; color: #666;">` consistent across siblings. |
| Sibling card header verb-first phrasing | `notifications.html:223, 326, 388, 448` | ✅ Lines 223 (`Submit Research Job`), 326 (`Submit SWE Team Task`), 388 (`Generate Presentation from Document`) verified. Minor: line 448 reads `🧪 Run Test Suite` (looser verb-first) — acceptable as verb-first family. |
| `agentic_job_factory.create_agentic_job()` | `src/cosa/rest/agentic_job_factory.py` | ✅ Confirmed used at `claude_code_queue.py:160`; no change needed. |
| Multiplexer Jobs pane (agent-agnostic) | `JobsPaneRenderer.ts`, `JobStore.ts:215` | ✅ `JobStore.ts:215` reads `job_type: (e.payload.metadata?.agent_type as string \| undefined) ?? "unknown"`; renderer uses `data-job-type` + `<span class="job-type">` with verbatim agent_type label. Zero per-agent branching. |

### `extend-existing` (rename / relocate / add fields — NOT net-new)

| Plan claim | Existing source | What changes |
|------------|----------------|--------------|
| URL `/api/claude-code/submit` (NEW) + alias `/api/claude-code/queue/submit` (DEPRECATED) | Single decorator at `src/cosa/rest/routers/claude_code_queue.py:84` | Rename primary route + add stacked-decorator alias (Q8 fallback: comment-out if stacked rejected) |
| `#cc-task-type` INTERACTIVE option | Currently HTML comment at `notifications.html:146` | Promote to actual `<option value="INTERACTIVE" disabled>` |
| Card `<h4>` header | `notifications.html:119` reads `🤖 Claude Code Dispatcher` | Rename to `🤖 Submit Claude Code Task` |
| `submitClaudeCodeToQueue()` JS handler | `notifications.js:3734-~3770` | Rewrite to mirror research handler shape; drop `responseEl` writes; add `cc-submit-status` updates |
| `.cc-retired-banner` CSS class | Defined at `src/fastapi_app/static/css/notifications.css` (2 lines); single consumer at `notifications.html:198` | DELETE class definition (orphan after Phase 1.5). REUSE 2026-05-10 confirmed zero other consumers across `.css`, `.ts`, `.tsx`, `.js` files. New Phase 1.8 sub-step + AC1.5. |

### Genuinely-new (no prior art; novelty justified)

| Item | Why novel | REUSE 2026-05-10 verification |
|------|-----------|--------|
| FastAPI stacked-decorator alias on a single endpoint function | No in-repo prior art — verify FastAPI permits this in current version. Q8 fallback (comment-out) is the safety net | ✅ Zero examples of stacked-route patterns in `src/cosa/rest/routers/*.py`. FastAPI 0.115.12 confirmed installed; supports the pattern natively. Q8 fallback risk-mitigation is appropriate. |
| `deprecated=True` route param | Standard FastAPI kwarg, but no repo precedent | ✅ `include_in_schema=False` is used at `src/cosa/rest/routers/pages.py:*` (8+ routes). `deprecated=True` is novel to this codebase. Filed as Risk row in 01-design.md (low risk, documentation hygiene). |
| `02-handoff-summary.md` as a co-located cross-sub-project handoff format | First plan to use the new `feedback_cross_project_handoff_doc.md` pattern (filed 2026-05-10); structure: TL;DR / what / why / per-sub-project action / migration timeline / where to ask | ✅ Zero prior `*-handoff-summary.md` files in `src/rnd/v0.1.*/`. Closest match (`2026.03.02-status-summary-and-testing-plan.md`) is internal status, not cross-project handoff. Format intentionally novel per workflow guidance. |

---

## Plan-review handoff

**Trigger**: After all 4 R&D docs land + AC for Phase 0 satisfied.
**Command**: `/plan-review --doc-set=src/rnd/v0.1.7/2026.05.09-cc-card-normalization/`
**Sequence (per Q7, per `feedback_pip_plan_review_is_sequential.md`)**:
1. REUSE pre-pass (single Explore agent) → user-gated apply → idempotency marker
2. Pass 1 Fitness (single Explore agent) → user-gated apply → idempotency marker
3. Pass 2 Adversarial (single Explore agent) → user-gated apply → `last-reviewed-at` populated in this file

Implementation Phase 1 unblocks ONLY after Pass 2 closure.
