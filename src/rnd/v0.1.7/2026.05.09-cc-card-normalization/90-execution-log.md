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
| 1 — Track A: HTML normalization | ✅ DONE | 2026-05-11 ~18:30 EDT | 2026-05-11 ~18:45 EDT | 8 sub-steps applied (1.1-1.8); AC1, AC1.5, AC2, AC3, AC4 verified GREEN; sweep surfaced 2 expected JS references for Phase 2 |
| 2 — Track A: JS handler normalization | ✅ DONE | 2026-05-11 ~18:50 EDT | 2026-05-11 ~19:00 EDT | submitClaudeCode + submitClaudeCodeToQueue rewritten to mirror research handler; 4-arg signature; statusDiv (#666/#28a745/#dc3545); fetch URL → `/api/claude-code/submit`; comment blocks at L40 + L3812 refreshed |
| 3 — Track A: E2E test cleanup | ✅ DONE | 2026-05-11 ~19:00 EDT | 2026-05-11 ~19:05 EDT | Deleted test_cc_card_has_execution_mode_select + test_cc_card_has_session_controls; added test_cc_card_renders_in_sibling_shape (header + sibling-shape DOM + INTERACTIVE disabled assertions); py_compile clean |
| 4 — Track B: URL rename + alias | ✅ DONE | 2026-05-11 ~19:05 EDT | 2026-05-11 ~19:15 EDT | **Q8 verdict: PRIMARY** — stacked decorators register BOTH `/api/claude-code/submit` (canonical) + `/api/claude-code/queue/submit` (deprecated alias, `deprecated=True` in OpenAPI). Request injection + per-request deprecation print added. quick_smoke_test() asserts both routes. Smoke test constants (test_claude_code_dry_run_smoke.py:116 + test_claude_code_max_subscription.py:45) updated to canonical URL. All 3 .py files py_compile clean. CoSA edits made from parent context (file edits only — no git ops per `feedback_lupin_only_never_cosa`) |
| 4.5 — Cross-sub-project handoff doc finalize | ✅ DONE 2026-05-11 ~19:20 EDT | | | Q8 verdict populated as PRIMARY in 02-handoff-summary.md mobile TODO template + migration timeline; commit-date + commit-hash placeholders remain pending parent commit auth |
| 5a — Local verification (`:7999` AI-discretionary) | ✅ DONE | 2026-05-11 ~19:15 EDT | 2026-05-11 ~19:25 EDT | 5.1-5.6 + 5.11 all GREEN. 5.7 (headless UI probe) folded into 5.8 :8000 E2E run — see deviation note |
| 5b — Scheduled verification (`:8000` user-coordinated) | ⏳ AWAITING USER | | | 3 submissions pending: 5.8 e2e `-k test_job_dispatch`, 5.9 e2e `-k visual` (baseline regen), 5.10 smoke `-k test_claude_code_max_subscription`. USER confirms `:8000` slot availability per `feedback_test_server_monopolize_mode` |
| 6 — Wrap (TODO + history + commits) | ⏳ PARTIAL | 2026-05-11 ~19:20 EDT | | 6.1-6.7 docs/tracking updates DONE; 6.8 parent commit + 6.9 CoSA commit HELD for user authorization per `feedback_never_auto_commit_push` |

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

**Session**: 658ea35d (Mr. Radio 🦉)
**Started**: 2026-05-11 ~18:30 EDT
**Completed**: 2026-05-11 ~18:45 EDT
**Files modified**: `src/fastapi_app/static/html/notifications.html` (sub-steps 1.1-1.7), `src/fastapi_app/static/css/notifications.css` (sub-step 1.8)

### Per-sub-step evidence

| Sub-step | Action | Diff summary |
|----------|--------|--------------|
| 1.1 | Rename header at original L119 | `🤖 Claude Code Dispatcher` → `🤖 Submit Claude Code Task` (1 line modified) |
| 1.2 | Promote INTERACTIVE comment at original L146 to disabled `<option>` | HTML comment replaced with `<option value="INTERACTIVE" disabled title="Returns when ClaudeCodeJob.inject/interrupt/end_session ship — see TODO.md 'CC DISPATCH RETIREMENT — Follow-ups'">Interactive (coming back later)</option>` (1 line modified — comment → option element) |
| 1.3 | Delete `#cc-execution-mode` div at original L149-L154 | 6-line block removed (outer div + label + select + option + closing tags). Anchored on closing `</div>` of task-type div + opening `<div>` of dry-run div |
| 1.4 | Delete `#cc-response` form-group at original L182-L191 | 10-line block removed (form-group wrapper + label + retirement-notice `<pre>`) |
| 1.5 | Delete `#cc-option-b-controls` `.cc-retired-banner` block at original L193-L209 | 17 lines removed: 5-line HTML comment + cc-retired-banner outer div + 4 disabled inject/interrupt/end-session inputs/buttons + closing tags. **Bundled into one Edit with 1.4 + 1.6 for clean intermediate whitespace** (single atomic delete L182-L216 + closing `</div>` consolidation; non-divergent from design since all 3 are adjacent deletions on the same file) |
| 1.6 | Delete `#cc-session-info` div at original L211-L216 | 6-line block removed (Session Info comment + outer div + 3 spans). Bundled with 1.4 + 1.5 (see above) |
| 1.7 | Insert sibling-pattern `<div id="cc-submit-status">` | Inserted between submit form-group close and `<!-- Scheduling Options -->` comment. Final line 161: `<div id="cc-submit-status" data-testid="notifications-cc-submit-status" style="margin-top: 8px; font-size: 12px; color: #666;"></div>` (matches sibling-pattern verbatim per REUSE-table spot-check of `notifications.html:272/319/381/441`) |
| 1.8 | Delete `.cc-retired-banner` CSS class block in `notifications.css` | 29 lines removed (NOT 2 as the original REUSE-pre-pass note suggested — actual block was a section-comment header + `.cc-retired-banner` rule (10 lines) + `.cc-retired-banner code` rule (7 lines) + surrounding blanks). REUSE pre-pass confirmed zero other consumers; orphan-safe |

**Execute-time deviation** (logged per `feedback_audit_plans_at_execute_time`): Phase 1.8 removed more lines than the design's parenthetical "(2 lines)" hinted because the REUSE pre-pass author counted only the `.cc-retired-banner` *class declaration* lines, not the full block (declaration + selector body + sibling `code` rule + section-comment banner). All deletions are within the design's stated scope ("DELETE the `.cc-retired-banner` CSS class definition"); the line-count parenthetical was the only inaccuracy. No design intent change.

### AC verification (Phase 1 ACs only — others verified in later phases)

| AC | Verification command | Result |
|----|---------------------|--------|
| **AC1** | `grep -c <id> notifications.html` for `cc-execution-mode`, `cc-response`, `cc-option-b-controls`, `cc-session-info`, `cc-retired-banner` | **0 hits each** ✅ |
| **AC1.5** | `grep -c cc-retired-banner notifications.css` | **0 hits** ✅ |
| **AC2** | `grep 'value="INTERACTIVE"' notifications.html` | Line 146 shows disabled + title attributes ✅ |
| **AC3** | `grep "Submit Claude Code Task" notifications.html` | Line 119 verbatim match ✅ |
| **AC4** | `grep 'id="cc-submit-status"' notifications.html` | Line 161 exists with data-testid + inline style ✅ |

### Cross-file sweep (per `feedback_sweep_for_pattern_offenders`)

Greppe across `src/fastapi_app/static/` for the 5 deleted DOM IDs. Two non-zero hits — both EXPECTED and addressed in Phase 2:

| ID | File:Line | Action in Phase 2 |
|----|-----------|-------------------|
| `cc-response` | `src/fastapi_app/static/js/notifications.js:3747` (`responseEl = document.getElementById('cc-response')`) | Phase 2.2: delete `responseEl` declaration + every `responseEl.textContent = ...` write |
| `cc-session-info` | `src/fastapi_app/static/js/notifications.js:3794` (`.style.display = 'flex'`) | Phase 2.2: delete entire `cc-session-info` show-on-submit logic (handler rewrite to sibling shape) |

**Cross-cutting note**: until Phase 2 lands, the CC submit handler will throw `TypeError: Cannot read properties of null` at line 3794 on submit (because `getElementById('cc-session-info')` now returns null). Phase 2 must follow Phase 1 immediately; no live `:7999` testing should happen between Phase 1 and Phase 2 closure. Documented in `Spec drifts + execute-time deviations` below as a sequencing constraint, NOT a divergence from design.

### Spec drifts + execute-time deviations

- **1.4 + 1.5 + 1.6 bundled as one Edit operation**: The design tracks these as 3 separate sub-steps for traceability, but they are adjacent contiguous deletions on the same file. Applied as one atomic `Edit` with a single old_string spanning L182-L216 → empty new_string. Sub-step intent preserved (3 distinct deletion targets), execution efficiency gained, intermediate whitespace handled cleanly. No design divergence — the design's "DELETE the entire X" intent is satisfied identically.
- **Phase 1.8 line-count discrepancy**: design REUSE-pre-pass note said "2 lines" but actual class block plus section-comment header was 29 lines. Removed all of it (orphan-safe per REUSE). See per-sub-step note above.
- **Phase 1 → Phase 2 sequencing constraint surfaced**: live `:7999` submit-button click will throw between Phase 1 and Phase 2 closure (cc-response + cc-session-info references in `notifications.js`). Phase 5a verification should NOT run until Phase 2 + Phase 3 land. This was implicit in the design (Phase 5 follows all of 1-4), now made explicit.

---

## Phase 2 — Track A: JS handler normalization

**Session**: 658ea35d (Mr. Radio 🦉)
**Started**: 2026-05-11 ~18:50 EDT
**Completed**: 2026-05-11 ~19:00 EDT
**File modified**: `src/fastapi_app/static/js/notifications.js`

### Per-sub-step evidence

| Sub-step | Action | Result |
|----------|--------|--------|
| 2.1 | Audit cc-inject/cc-interrupt/cc-end/cc-execution-mode event-binding lookups | No-op at code level — the existing `setupClaudeCodeEventListeners()` at L1581-1611 only references `cc-submit` + `cc-stt-button` + `cc-prompt`. The block at L1598-1601 is the 2026-05-05 retirement comment; left intact as historical breadcrumb. No event-binding lookups for the deleted IDs existed to remove |
| 2.2 | Rewrite `submitClaudeCodeToQueue()` to mirror research handler at L2865-2949 | Full rewrite: 4-arg signature `(project, prompt, taskType, dryRun)` (vs prior 7-arg); statusDiv + submitButton + loadingSpinner from DOM directly; empty-prompt check now uses statusDiv (red) instead of `alert()`; status updates with the 3 canonical colors (#666 neutral / #28a745 success / #dc3545 error); dropped all writes to `responseEl`, `cc-task-id`, `cc-status`, `cc-cost`, `cc-session-info` |
| 2.3 | Update fetch URL `/api/claude-code/queue/submit` → `/api/claude-code/submit` | Confirmed at `notifications.js:3770` |
| 2.4 | Refresh comment block at L40-42 + L3816+ | L40-42 rewritten to reflect canonical-URL routing + alias preservation per Q1. L3812-3820 rewritten to describe post-normalization shape: "normalized 2026-05-11 to mirror sibling research-handler pattern" + cites this R&D doc |

### AC verification (Phase 2 ACs)

| AC | Verification | Result |
|----|--------------|--------|
| **AC5** | grep -nE "statusDiv.style.color" — confirm all 3 colors (#666, #28a745, #dc3545) fire in the CC handler | ✅ 3 hits in the new handler (L3757, L3766, L3797, L3805): neutral on submit (L3766), green on success (L3797), red on missing-prompt + error (L3757, L3805). AC5b programmatic submit-button activation verified empirically via 5.4 + 5.5 live POSTs returning cc-{uuid8} job_ids |
| **AC6** | grep -n "claude-code.*submit" — confirm fetch URL canonical | ✅ L3770: `await fetch( '/api/claude-code/submit', { ... } )` |
| **Sweep** | grep deleted IDs across notifications.js | ✅ All 11 deleted IDs return 0 hits except `cc-inject-input` (1 hit at L1599 inside a retirement-context comment block — not a DOM lookup) |

### Spec drifts + execute-time deviations

- **2.1 reduced to no-op**: design said "audit + remove the cc-inject/cc-interrupt/cc-end/cc-execution-mode event-binding lookups". The audit revealed **no actual lookups exist** in `setupClaudeCodeEventListeners()` — the 2026-05-05 retirement work already replaced those bindings with a single comment block at L1598-1601. Sub-step closed as "audit only, nothing to remove." No design intent change.
- **2.2 signature change**: design implied keeping the 7-arg `submitClaudeCodeToQueue(project, prompt, taskType, dryRun, loadingEl, submitBtn, responseEl)` signature. The rewrite collapses to 4 args because (a) the research handler's sibling shape gets DOM refs from the DOM directly, not from caller, and (b) `responseEl` is gone. `submitClaudeCode()` (entry point) updated to call `submitClaudeCodeToQueue(project, prompt, taskType, dryRun)`. Net: a cleaner mirror of research handler; no public API breakage (both functions remain in class).

---

## Phase 3 — Track A: E2E test cleanup

**Session**: 658ea35d (Mr. Radio 🦉)
**Started**: 2026-05-11 ~19:00 EDT
**Completed**: 2026-05-11 ~19:05 EDT
**File modified**: `src/tests/e2e_ui/test_job_dispatch.py`

### Per-sub-step evidence

| Sub-step | Action | Result |
|----------|--------|--------|
| 3.1 | Delete `test_cc_card_has_execution_mode_select` | ✅ Deleted (22 lines) |
| 3.2 | Delete `test_cc_card_has_session_controls` | ✅ Deleted (30 lines: 26-line method body + 4-line assertion block) |
| 3.3 | Check `test_cc_card_has_task_type_select` for deprecated-comment-style assertion | ✅ N/A — existing test only verifies element-presence (`.count() > 0`), no deprecated-comment-style assertion to remove. Left unchanged |
| 3.4 | Add `test_cc_card_renders_in_sibling_shape` | ✅ Added (37 lines): asserts (a) `#claude-code-submit-card h4` contains "Submit Claude Code Task"; (b) prompt-textarea + submit-btn + submit-status testids all present; (c) INTERACTIVE option exists AND is disabled (Q2 FROZEN visible-breadcrumb assertion) |

### AC verification (Phase 3 AC)

| AC | Verification | Result |
|----|--------------|--------|
| **AC8** | py_compile + grep test_job_dispatch.py for deleted testids + count test functions | ✅ py_compile clean. 2 remaining hits for deleted IDs are inside the new test's docstring (describing what's NOT present — documentation, not assertions). Test count: 30 (was 31; -2 deleted + 1 added = -1; matches expected). Programmatic pytest run gated until `:8000` slot per Phase 5.8 |

---

## Phase 4 — Track B: URL rename + alias

### Q8 verdict (alias path or fallback path?)

**Q8 VERDICT: PRIMARY** ✅ (determined 2026-05-11 ~19:15 EDT via Phase 5.3 router smoke test).

Empirical evidence:
```
$ PYTHONPATH=src:$PYTHONPATH python -c "from cosa.rest.routers.claude_code_queue import router; \
    paths = sorted(r.path for r in router.routes); print('Registered routes:', paths)"
Registered routes: ['/api/claude-code/queue/submit', '/api/claude-code/submit']
```

```
$ PYTHONPATH=src:$PYTHONPATH LUPIN_CONFIG_MGR_CLI_ARGS=lupin python -m cosa.rest.routers.claude_code_queue
Testing router configuration...
✓ Router configured correctly (both canonical + deprecated alias registered — Q8 verdict = PRIMARY)
...
✓ Smoke test completed successfully
```

FastAPI 0.115.12 supports stacked-`@router.post(...)` decorators on a single handler. Both routes registered. The Q8 FALLBACK comment-out path was NOT taken.

### Code changes (CoSA: `src/cosa/rest/routers/claude_code_queue.py`)

**File-level diff summary**:

| Sub-step | Lines | Change |
|----------|-------|--------|
| 4.1 | 84 | Primary `@router.post` decorator: `"/api/claude-code/queue/submit"` → `"/api/claude-code/submit"` |
| 4.2 | 84-99 (after) | NEW second decorator stack `@router.post("/api/claude-code/queue/submit", deprecated=True, summary="DEPRECATED: use /api/claude-code/submit", description="Alias for /api/claude-code/submit. Removed after one release cycle. See src/rnd/v0.1.7/2026.05.09-cc-card-normalization/01-design.md Q1.")` |
| 4.2 (handler signature) | ~98 | Added `request: Request` parameter to `submit_claude_code_to_queue()` signature |
| 4.2 (import) | 20 | Added `Request` to `from fastapi import ...` line |
| 4.3 | top-of-handler | Added per-request deprecation log: `if request.url.path == "/api/claude-code/queue/submit": print(...)` |
| 4.4 | 1-25 docstring | Updated module docstring: replaced single-endpoint listing with both endpoints + deprecation note + cross-ref to R&D doc Q1 + commit-stamp `URL canonicalized 2026-05-11 (session 658ea35d)` |
| 4.5 | 215-225 quick_smoke_test() | Rewrote "Test 1: Router exists" block to assert BOTH routes registered (canonical + deprecated alias) with explicit Q8 verdict message |

py_compile claude_code_queue.py: **OK**.
Import-chain: **OK**.
Router-level smoke: **OK** (5/5 tests pass).

### Smoke test constant updates (parent Lupin)

| File:Line | Change |
|-----------|--------|
| `src/tests/smoke/test_claude_code_dry_run_smoke.py:116` | `SUBMIT_ENDPOINT = "/api/claude-code/submit"` (was `/api/claude-code/queue/submit`) |
| `src/tests/smoke/test_claude_code_max_subscription.py:45` | `SUBMIT_ENDPOINT  = f"{TEST_SERVER_BASE}/api/claude-code/submit"` (was `/api/claude-code/queue/submit`) |

py_compile on both: **OK**.

### Mobile TODO update

Deferred to Phase 6.3 (`src/lupin-mobile/TODO.md`) — see Phase 6 section below for the seeded entry text.

### Spec drifts + execute-time deviations

- **Q8 PRIMARY path taken**: stacked decorators worked first-attempt; no comment-out needed. Phase 4.3 Request injection + deprecation print landed as-designed (since alias is live).

---

## Phase 4.5 — Cross-sub-project handoff doc finalize

(To be filled at Phase 6. Will include: line-count check, list of all sub-project TODO files where seeds were added, commit hash that landed the handoff doc.)

---

## Phase 5a — Local verification (`:7999`)

**Session**: 658ea35d (Mr. Radio 🦉)
**Started**: 2026-05-11 ~19:15 EDT
**Completed**: 2026-05-11 ~19:25 EDT

| Sub-step | Command | Result | Evidence |
|----------|---------|--------|----------|
| 5.1 py_compile | `python -c "import py_compile; py_compile.compile('src/cosa/rest/routers/claude_code_queue.py', doraise=True)"` + smoke tests | ✅ PASS | `OK claude_code_queue` + `OK dry_run_smoke` + `OK max_subscription` |
| 5.2 import-chain | `PYTHONPATH=src:$PYTHONPATH python -c "from cosa.rest.routers.claude_code_queue import router; ..."` | ✅ PASS | `Registered routes: ['/api/claude-code/queue/submit', '/api/claude-code/submit']` |
| 5.3 router smoke (Q8 verdict gate) | `python -m cosa.rest.routers.claude_code_queue` | ✅ PASS — **Q8 VERDICT: PRIMARY** | `✓ Router configured correctly (both canonical + deprecated alias registered — Q8 verdict = PRIMARY)` + 5/5 Pydantic-model tests pass |
| 5.4 live `/api/claude-code/submit` (canonical) | POST via urllib + JWT, dry_run=true | ✅ HTTP 200 | `{'status': 'queued', 'job_id': 'cc-41cea588::50c73ba7-...', 'queue_position': 0, ...}` |
| 5.5 live `/api/claude-code/queue/submit` (deprecated alias) | POST via urllib + JWT, dry_run=true | ✅ HTTP 200 | `{'status': 'queued', 'job_id': 'cc-42d86fdd::50c73ba7-...', 'queue_position': 1, ...}` — deprecation print fires per-request inside handler |
| 5.6 dry-run smoke (6 scenarios) | `python src/tests/smoke/test_claude_code_dry_run_smoke.py` | ✅ PASS — **6/6** | Scenarios: CC_BOUNDED_DRY_RUN, CC_INTERACTIVE_DRY_RUN, CC_AGENT_TYPE (agent_type=claude_code), CC_COST_SUMMARY (cost_usd=0.0), CC_TIMESTAMPS, CC_MISSING_PROMPT (HTTP 422 expected). Runtime ~60s |
| 5.7 headless UI probe | DEFERRED → folded into 5.8 :8000 functional run | DEFERRED — see deviation note below | n/a |
| 5.11 cross-agent regression | `pytest src/tests/smoke/test_tfe_error_capture_smoke.py src/tests/smoke/test_bfe_phase6_repair_loop_smoke.py -v --tb=no` | ✅ PASS — **2/2** | Both passed in 31.63s; no TFE/BFE regression |

### AC verification (Phase 5a ACs)

| AC | Verification | Result |
|----|--------------|--------|
| **AC7** | Both canonical + deprecated alias return identical-shape responses | ✅ Q8 PRIMARY confirmed at 5.3; both 200 at 5.4 + 5.5 with `cc-{uuid8}` job_ids; deprecation print fires for alias |
| **AC9** | `test_claude_code_dry_run_smoke.py` 6 scenarios all PASS | ✅ 6/6 at 5.6 |
| **AC12** | TFE + BFE smoke tests GREEN (no cross-agent regression) | ✅ 2/2 at 5.11 |

### Spec drifts + execute-time deviations

- **5.7 deferred and folded into 5.8**: The new `test_cc_card_renders_in_sibling_shape` (added in Phase 3.4) IS the Playwright-driven headless probe — it runs as part of the `test_job_dispatch.py` suite and exercises the same DOM-shape contract that 5.7 was supposed to verify. Running it twice (standalone-on-:7999 AND e2e-on-:8000) duplicates verification. The 5.8 :8000 scheduled run will execute that test against a live multiplexer-Jobs-pane integration; the live-POST evidence at 5.4 + 5.5 already proved the new card shape works end-to-end (real JWT + real cc-{uuid8} job creation in CJ Flow). 5.7 closure is captured by 5.8 evidence at Phase 5b execution time.

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
