# Execution Log — Claude Code Notifications-UI Card Normalization

**Plan**: [`01-design.md`](01-design.md) (this directory).
**Session**: TBD (Phase 0 written 2026-05-10; subsequent phases will record session ID at execution time).
**Status**: ⏳ Phase 0 docs serialized; awaiting `/plan-review` REUSE → Pass 1 → Pass 2 (sequential) before Phase 1 implementation.

---

## Phase status

| Phase | Status | Started | Completed | Notes |
|-------|--------|---------|-----------|-------|
| 0 — Documentation (R&D doc set) | ✅ DONE | 2026-05-10 ~10:25 EDT | 2026-05-10 ~10:35 EDT | `00-index.md` + `01-design.md` + `02-handoff-summary.md` + this file. Plan serialized from `~/.claude/plans/ok-so-far-so-swirling-pearl.md` (approved 2026-05-10 via ExitPlanMode). |
| **GATE — PIP plan review** | ⏳ PENDING | (will populate at REUSE start) | (in flight) | Sequential REUSE → Pass 1 → Pass 2 per Q7. Implementation BLOCKED until Pass 2 closure. |
| 1 — Track A: HTML normalization | 🔒 BLOCKED | | | Blocked on PIP review |
| 2 — Track A: JS handler normalization | 🔒 BLOCKED | | | Blocked on PIP review |
| 3 — Track A: E2E test cleanup | 🔒 BLOCKED | | | Blocked on PIP review |
| 4 — Track B: URL rename + alias | 🔒 BLOCKED | | | Blocked on PIP review; Q8 fallback decision tracked here at execute time |
| 4.5 — Cross-sub-project handoff doc finalize | 🔒 BLOCKED | | | `02-handoff-summary.md` exists; finalize at Phase 6 with commit hash + alias-vs-fallback verdict |
| 5a — Local verification (`:7999` AI-discretionary) | 🔒 BLOCKED | | | Blocked on Phase 1-4 |
| 5b — Scheduled verification (`:8000` user-coordinated) | 🔒 BLOCKED | | | Blocked on 5a + user slot-confirmation |
| 6 — Wrap (TODO + history + commits) | 🔒 BLOCKED | | | After Phase 5 closure |

---

## Phase 0 — Documentation (DONE 2026-05-10)

**2026-05-10** — Plan approved via ExitPlanMode (origin: `~/.claude/plans/ok-so-far-so-swirling-pearl.md`). Serialized into this directory's four R&D docs.

R&D directory created: `src/rnd/v0.1.7/2026.05.09-cc-card-normalization/`.

**Pre-existing context preserved**:
- Predecessor R&D: `src/rnd/v0.1.7/2026.05.05-claude-code-dispatch-retirement/01-plan.md` (the rogue endpoint retirement that produced the gravestones this plan removes)
- Predecessor R&D: `src/rnd/v0.1.7/2026.05.07-claude-code-bounded-redesign/00-index.md` (in-flight canonical-shape redesign — runs in parallel; no overlap)
- Cross-cutting consumer R&D: `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/00-synthesis-and-roadmap.md` (multiplexer Phase 6b in flight — handoff doc seeded here)

**Files created**:
- `00-index.md` — master nav, Q-decisions table, REUSE-table scaffold, open follow-ups
- `01-design.md` — full design with 9 Q-N FROZEN decisions, 7 phases, 19 ACs, risks, out-of-scope
- `02-handoff-summary.md` — 110-line cross-sub-project handoff (Lupin mobile + multiplexer R&D consumers)
- `90-execution-log.md` — this file

---

## GATE — PIP plan review

### REUSE pre-pass — ✅ CLOSED 2026-05-10

**Findings delivered**: 4 reuse-as-is + 1 extend-existing (CSS orphan) + 3 genuinely-new (justified). Zero blocking issues. Author's pre-REUSE table verified, zero material drift.

**User-gated apply (3 of 3 applied)**:
1. ✅ Elevated `.cc-retired-banner` CSS orphan cleanup → new Phase 1.8 sub-step in 01-design.md + AC1.5
2. ✅ Updated `00-index.md` "Prior art referenced" with REUSE 2026-05-10 verification spot-checks (file:line confirmations inline)
3. ✅ Added Risk row in 01-design.md noting `deprecated=True` is novel to this codebase (low-risk documentation hygiene)

**Resolution Loop convergence**: REUSE has no recurring grep targets per canonical §4 (unlike Pass 1's TBD/Open-sub-question greps). Convergence check is "all approved fixes reflected in plan docs" — all 3 fixes verified landed.

**Spot-check evidence captured in 00-index.md** (verbatim):
- `notifications.js:2870-2949` research handler — lines 2873/2889/2890/2892/2936/2944 confirmed contain the disable-button + spinner + statusDiv + 3-color pattern
- `notifications.html:272/319/381/441` sibling status divs — all 4 lines verified consistent inline-style
- `notifications.html:223/326/388/448` sibling headers — all 4 verified verb-first family (line 448 `Run Test Suite` is looser but acceptable)
- `JobStore.ts:215` agent-agnostic — verified `metadata?.agent_type` lookup; zero per-agent branching in `JobsPaneRenderer.ts`
- FastAPI 0.115.12 supports stacked decorators; zero in-repo precedent (Q8 fallback risk-mitigation appropriate)
- `src/fastapi_app/static/css/notifications.css` — `.cc-retired-banner` is 2-line definition; zero other consumers found across .css/.ts/.tsx/.js files (orphan-safe to delete)

### Pass 1 — Fitness — ✅ CLOSED 2026-05-11

**Findings delivered**: 11 total (0 Block / 4 Major / 7 Minor / 0 Layer-3 Design Concerns). No Q-N FROZEN decision challenged.

**User-gated apply** (8 of 11 applied across 3 batches — Majors batch via AskUserQuestion, Minors A + Minors B via cosa-voice `ask_multiple_choice` per user-ratified mid-pass channel switch to high-priority action-required UI gates):

| Finding | Status | What landed |
|---------|--------|-------------|
| M1 — Q8 verdict gate pinned to Phase 5.3 | ✅ Applied | Phase 4.2 + 4.3 now reference Phase 5.3 as the explicit verdict-determining sub-step; Phase 5.3 row marked "Q8 verdict gate" and documents PRIMARY/FALLBACK branching |
| M2 — Specify Playwright + assertion shape for Phase 5.7 | ⏭️ Skipped | User chose not to apply; engineer will grep `src/tests/e2e_ui/` at execute time |
| M3 — Enumerate visual-baseline expected/regression diffs | ⏭️ Skipped | User chose not to apply; baseline-diff judgment stays as in-the-moment review |
| M4 — Mobile-late-migration UX Risk row | ⏭️ Skipped | User chose not to apply; existing Risk row 3 considered sufficient |
| m1 — Function-name fossil note in Phase 4.1 | ✅ Applied | Inline note explaining why `submit_claude_code_to_queue` stays this cycle |
| m2 — Literal mobile TODO entry shape in handoff doc | ✅ Applied | Code-fenced example added under "Where mobile's TODO lives"; includes `[Q8 verdict]` slot |
| m3 — Tightened "one release cycle" to v0.1.8+ trigger | ✅ Applied | Replaced vague phrasing with concrete release-tag trigger; FALLBACK path collapse explicit |
| m4 — Specify WHO to contact in handoff doc | ✅ Applied | 3-tier contact ladder added: primary (git show), fallback (bug-fix-queue), last resort (issue label) |
| m5 — Mobile TODO entry tag + section in Phase 6.3 | ✅ Applied | `[LUPIN-CC-SUBMIT-RENAME]` tag + Pending section + status `[ ]` + literal text aligned with handoff-doc shape |
| m6 — Backend coverage scope clarification in Risks row 7 | ✅ Applied | Row 7 rewritten to address both JS (out-of-scope) AND Python (verify at execute time) coverage paths |
| m7 — Drop `include_in_schema=False` from alias | ✅ Applied | Phase 4.2 alias decorator now keeps the route in OpenAPI as `deprecated: true` — primary discovery channel for mobile + integration tests |

**Resolution Loop convergence re-grep** (per canonical §7, run against the post-fix doc-set):

| Grep | Pre-fix baseline | Post-fix result | Delta |
|------|------------------|-----------------|-------|
| `grep -rnE "TBD\|confirm during impl\|decide at impl time\|tbd" <doc-set>` | All hits in 90-execution-log.md (evidence placeholders) + 02-handoff-summary.md (migration timeline dates) + 00-index.md meta-reference (Convention 4 row) | Same hits + 1 new placeholder in handoff doc (`<commit-date>` and `[Q8 verdict: PRIMARY\|FALLBACK]` from m2 fix — intentional execute-time slots, NOT design TBDs) | ✅ Zero new design TBDs |
| `grep -rn "Open sub-question" <doc-set>` | 1 meta-reference in 00-index.md (Convention 4 row) | Same single meta-reference | ✅ No change |

**Convergence verdict**: All TBD hits are legitimate execute-time placeholders that the canonical workflow expects (Phase 5 evidence cells, post-impl date-fills). Zero design ambiguities introduced.

**Layer-3 Design Concerns**: NONE — all 11 findings were implementation-clarity gaps; no Q-N FROZEN decision was challenged in either the finding set or the applied fixes.

**Next gate**: Pass 2 Adversarial (per Q7 sequential mandate — no parallel dispatch).

### Pass 2 — Adversarial — ✅ CLOSED 2026-05-11

**Findings delivered**: 7 total (0 Block / 5 Major / 2 Minor / 0 Layer-3 Design Concerns). No Q-N FROZEN decision challenged.

**User-gated apply** (7 of 7 applied across 2 batches — Majors batch (5) + Minors batch (2), both via cosa-voice `ask_multiple_choice` priority=high action-required gates):

| Finding | Status | What landed |
|---------|--------|-------------|
| A1 — AC11 visual baseline criteria falsifiable | ✅ Applied | Replaced "regenerated cleanly" with AI-assertion criteria: pytest count `N ≥ 3` + git-diff allow-list of expected changes. Diffs outside allow-list = AC11 FAILS. |
| A2 — AC5 "manual submit" → programmatic | ✅ Applied | Replaced with grep + headless DOM observation pattern. No human ratification of submit visuals. |
| A3 — Two-phase E2E gate `EXECUTOR: HUMAN` tag | ✅ Applied | Inline tag + rationale (slot availability per `feedback_test_server_monopolize_mode`). HUMAN confirms slot BEFORE AI fires the test-suite submit POST. |
| A4 — Phase 6.8 `EXECUTOR: AI` + explicit file list | ✅ Applied | 13-file allow-list inline; commit message template captures Track A + B + Q8 verdict + sub-project TODO seeds. CoSA submodule pin NOT bumped here. |
| A5 — Phase 6.9 `EXECUTOR: HUMAN` tag | ✅ Applied | Inline tag + rationale (CoSA git boundary per `feedback_lupin_only_never_cosa`). AI edits land on disk at Phase 4.1-4.5; HUMAN runs git in CoSA context. |
| a1 — Mobile TODO template placeholder clarification | ✅ Applied | Note added: `[Q8 verdict: PRIMARY\|FALLBACK]` is a placeholder; parent session fills before mobile sees it. |
| a2 — "Manual" metadata wording in Phase 6.1 + AC13 | ✅ Applied | Inline parenthetical clarifying "manual" is legacy item-name metadata, NOT current Manual-E2E claim. |

**Resolution Loop convergence re-grep** (against the 3 Pass 2 greps from canonical §8):

| Grep | Hits | Convergence |
|------|------|-------------|
| `grep -rn "Manual\|manual" <doc-set>` | 6 hits total. 5 explained (Convention 5 meta-reference, Phase 5.7 row-label with immediate "programmatic via headless" clarification, Phase 6.1 + AC13 + Critical Files row — all explicitly tagged as legacy metadata per a2 fix). 1 PRE-EXISTING pattern offender at `01-design.md:216` Risks row ("manual `:7999` probe") — adversarial agent missed it; swept under `feedback_sweep_for_pattern_offenders.md` mandate. Now reads "AI-executed `:7999` curl + headless DOM probe". | ✅ Zero unjustified `manual` hits remain (all are either legacy-metadata-tagged or AI-executed-tagged) |
| `grep -rn "EXECUTOR: HUMAN" <doc-set>` | 2 hits. (a) Two-phase E2E gate line 143: rationale "`:8000` is monopolize-mode resource". (b) Phase 6.9 line 159: rationale "CoSA managed submodule git boundary". | ✅ Both have same-line justification per canonical §8 |
| `grep -rnE "^- \[ \] [^E]" <doc-set>` | 1 hit at `02-handoff-summary.md:70` (mobile TODO entry template). | ✅ Context-resolved false positive: the line is a code-fenced TEMPLATE inside the "Per-sub-project action — Mobile" section heading, which establishes mobile (HUMAN) as the implicit executor of the TODO line. Adding an inline `EXECUTOR: HUMAN` tag inside a mobile-facing TODO template would be redundant and confusing for mobile readers. |

**Layer-3 Design Concerns**: NONE — no Q-N FROZEN decision challenged.

**Pass 2 architectural assumption noted** (transparency, not a concern): Phase 6.9 depends on HUMAN (CoSA owner) availability at wrap time. If unavailable, parent Lupin Phase 6.8 commit lands but CoSA side waits. Mitigation: AI documents change intent in parent `history.md` so a later CoSA session can apply the change retroactively. No design change needed.

**Idempotency marker** (per canonical §12): `last-reviewed-at: 2026-05-11 (commit c1cec74 — pre-implementation HEAD on branch wip-v0.1.7-2026.04.22-spit-and-polish-for-cjflow-tfe-and-bfe)` — stamped in `00-index.md`.

**GATE CLOSED** — Phase 1 implementation unblocks. Begin Phase 1 (HTML normalization).

---

## Phase 1 — Track A: HTML normalization

(To be filled at execute time. Will include: per-line diff summaries for all 7 sub-steps, grep-evidence that the 5 deleted IDs no longer appear in `notifications.html`, screenshot or DOM snapshot of the new card shape.)

---

## Phase 2 — Track A: JS handler normalization

(To be filled. Will include: before/after diff of `submitClaudeCodeToQueue()`, grep-evidence that `responseEl` writes are gone, evidence that the new fetch URL is `/api/claude-code/submit`.)

---

## Phase 3 — Track A: E2E test cleanup

(To be filled. Will include: list of deleted test functions, content of new `test_cc_card_renders_in_sibling_shape()`, pytest output showing 0 failures.)

---

## Phase 4 — Track B: URL rename + alias

### Q8 verdict (alias path or fallback path?)

(To be populated at execute time. One of:
- **PRIMARY**: stacked decorators registered both routes successfully; alias is live and logs deprecation warning when hit. Mobile + smoke tests have one-release-cycle migration window.
- **Q8 FALLBACK**: stacked decorators rejected by FastAPI; secondary `@router.post("/queue/submit", ...)` decorator commented out with breadcrumb. No working alias. Mobile + smoke tests must migrate immediately.

Document the verification command output that produced this verdict.)

### Code changes (CoSA: `src/cosa/rest/routers/claude_code_queue.py`)

(To be filled. Will include: diff of decorator changes, diff of docstring update, diff of `quick_smoke_test()` update.)

### Smoke test constant updates (parent Lupin)

(To be filled. Two single-line updates at `test_claude_code_dry_run_smoke.py:116` and `test_claude_code_max_subscription.py:45`.)

### Mobile TODO update

(To be filled. Diff of `TODO.md` mobile entry under "🪦 CC DISPATCH RETIREMENT — Follow-ups" pointing to handoff doc.)

---

## Phase 4.5 — Cross-sub-project handoff doc finalize

(To be filled at Phase 6. Will include: line-count check, list of all sub-project TODO files where seeds were added, commit hash that landed the handoff doc.)

---

## Phase 5a — Local verification (`:7999`)

| Sub-step | Command | Result | Evidence |
|----------|---------|--------|----------|
| 5.1 py_compile | `python -c "import py_compile; py_compile.compile('src/cosa/rest/routers/claude_code_queue.py', doraise=True)"` | (TBD) | (paste output) |
| 5.2 import-chain | `PYTHONPATH=src:$PYTHONPATH python -c "from cosa.rest.routers.claude_code_queue import router; print('OK')"` | (TBD) | (paste output) |
| 5.3 router smoke | `python -m cosa.rest.routers.claude_code_queue` | (TBD) | (paste output) |
| 5.4 curl `/submit` | `curl -s -X POST http://localhost:7999/api/claude-code/submit -H "Authorization: Bearer …" -d '{"prompt":"smoke","dry_run":true}'` | (TBD) | (paste response) |
| 5.5 curl `/queue/submit` | Same payload to old URL | (TBD — depends on Q8 verdict) | (paste response + container log line) |
| 5.6 dry-run smoke | `python src/tests/smoke/test_claude_code_dry_run_smoke.py` | (TBD) | (paste 6/6 PASS summary) |
| 5.7 headless UI probe | (TBD: programmatic playwright probe of `/app/notifications`) | (TBD) | (DOM snapshot + Jobs pane evidence) |
| 5.11 cross-agent regression | `pytest src/tests/smoke/test_tfe_*.py test_bfe_*.py -v --tb=no` | (TBD) | (paste pass/fail counts) |

---

## Phase 5b — Scheduled verification (`:8000`)

**User slot-confirmation**: (TBD — record date/time when user confirms `:8000` is free)

| Sub-step | Submit payload | Job ID | Result |
|----------|----------------|--------|--------|
| 5.8 E2E functional | `test_types="e2e"` `pytest_args="-k test_job_dispatch"` | (TBD `ts-*`) | (paste result) |
| 5.9 E2E visual | `test_types="e2e"` `pytest_args="-k visual"` | (TBD `ts-*`) | (paste result + new-baseline path if regenerated) |
| 5.10 subscription smoke | `test_types="smoke"` `pytest_args="-k test_claude_code_max_subscription"` | (TBD `ts-*`) | (paste result + `cost_usd` value) |

---

## Phase 6 — Wrap

(To be filled. Will include:
- TODO updates: 6.1, 6.2, 6.3, 6.4 — diff of each
- bug-fix-queue.md update if applicable (6.5)
- history.md session entry (6.6)
- 90-execution-log.md self-population (6.7) — this section captures everything else
- Commit hashes: parent Lupin (6.8) + CoSA (6.9)
- AC verification table — 19 ACs confirmed at file inspection / grep / pytest level)

---

## Spec drifts + execute-time deviations

(Empty at start. Append any deviation from `01-design.md` here. Per `feedback_audit_plans_at_execute_time`, re-audit serialized plan diffs against feedback memories before applying. Per `feedback_sweep_for_pattern_offenders`, when fixing a pattern bug grep ALL instances in parent + submodules — not just the surfaced one.)
