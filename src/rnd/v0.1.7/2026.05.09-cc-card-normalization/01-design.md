# 2026.05.09 — Claude Code Notifications-UI Card Normalization — Design

**Status**: ⏳ Phase 0 docs serialized 2026-05-10; awaiting `/plan-review` REUSE → Pass 1 → Pass 2 (sequential).
**Pattern**: Pattern 5 (Refactor) in scope, Pattern 3 in shape (single design doc + execution log).
**Branch**: `wip-v0.1.7-2026.04.22-spit-and-polish-for-cjflow-tfe-and-bfe`
**SHORT_PROJECT_PREFIX**: [LUPIN]
**Scope marker**: Parent Lupin repo + one CoSA-side router edit (Track B). NO multiplexer TS changes.
**Origin plan file**: `~/.claude/plans/ok-so-far-so-swirling-pearl.md` (approved 2026-05-10 via ExitPlanMode).

---

## Context

The Claude Code submit card in the notifications UI (`src/fastapi_app/static/html/notifications.html:117-218`, id `claude-code-submit-card`) carries five dead UI blocks left over from the 2026-05-05 retirement of the `/api/claude-code/dispatch` endpoint cluster (commit `73bee1b`, session `1a8900ee`). The submit half of the card already works: it POSTs to `/api/claude-code/queue/submit`, which routes through `agentic_job_factory.create_agentic_job()` — the same factory all six sibling agentic jobs (Deep Research, Podcast, Presentation, SWE Team, BFE, Test Suite) use. Submitted jobs surface in the multiplexer Jobs pane through agent-agnostic `job_state_transition` events (`JobStore.ts:215`), with zero per-agent renderer logic.

What's broken is purely cosmetic: a yellow `.cc-retired-banner` wrapping disabled inject/interrupt/end-session buttons, a `<pre>` response panel showing a retirement notice, a hidden session-info row, and a disabled execution-mode select. Sibling cards have none of these — they're a form + submit button + small status div, and that's it. The card needs to be brought down to that shape.

A secondary URL inconsistency is in scope: the CC submit endpoint is `/api/claude-code/queue/submit` while every sibling uses `/api/<agent>/submit` (no `/queue/` infix). The `/queue/` infix was originally a contrast marker against `/api/claude-code/dispatch`; with dispatch retired, it's a dangling fossil.

The architectural picture is correct as-is — `/api/<agent>/submit` (per-agent typed Pydantic) is the canonical **human UI** path; `/api/push-agentic` (generic opaque args) is the canonical **agent-to-agent** path. They serve different consumers by design. This plan does NOT migrate the human UI to `/api/push-agentic` — that would put humans on the agent endpoint, losing typed Pydantic 422s and friendly per-field error messages.

**Intended outcome**: After this lands, the CC submit card looks structurally identical to its five sibling cards. Submit → CJ Flow → multiplexer Jobs pane behaves indistinguishably from Deep Research / Podcast / Presentation / SWE / BFE / Test Suite. The URL outlier is gone (with an alias for one release cycle to let mobile migrate on its own schedule).

---

## Locked design decisions

| Q | Question | ✅ Decision | Rationale |
|---|----------|-----------|-----------|
| **Q1 FROZEN 2026-05-09** | URL rename scope | **Track A + B with alias.** Add `POST /api/claude-code/submit` as the new canonical path. Keep `POST /api/claude-code/queue/submit` as an alias route for one release cycle so mobile + integration tests can migrate on their own schedule. Aliased route logs a deprecation warning. | User-ratified via AskUserQuestion 2026-05-09. Mobile + 2 smoke test constants update in this work; mobile follow-up entry already exists in TODO.md (the dispatch cluster cleanup). |
| **Q2 FROZEN 2026-05-09** | `#cc-task-type` select handling | **Keep the select; promote the commented-out INTERACTIVE option to a `disabled` `<option>` with a tooltip explaining it returns when `ClaudeCodeJob.inject/interrupt/end_session` ship.** | User explicitly: "we are eventually going to return to the unbounded version… disable the interactive choice". Visually documents "INTERACTIVE returns later" without enabling it. |
| **Q3 FROZEN 2026-05-09** | Card `<h4>` header text | **`🤖 Submit Claude Code Task`** | User-ratified. Matches sibling verb-first pattern: "Submit Research Job" / "Submit SWE Team Task" / "Submit Presentation Job". |
| **Q4 FROZEN 2026-05-09** | Status feedback shape | **Inline pattern matching siblings: `<div id="cc-submit-status" style="margin-top: 8px; font-size: 12px; color: #666;">`. JS sets `textContent` + `style.color` on submit/success/failure.** No shared helper extracted. | Sibling pattern is repeated inline in 6 handlers (`research-submit-status`, `podcast-submit-status`, `presentation-submit-status`, etc.) without a shared helper. Extracting one is a separate cleanup, out of scope here. |
| **Q5 FROZEN 2026-05-09** | E2E test handling for deleted IDs | **Full delete of the 2 obsolete test functions in `test_job_dispatch.py`.** | Audit confirms both are assertion-only ("does the disabled stub exist?") with retirement breadcrumbs in their docstrings; no behavioral coverage is lost. |
| **Q6 FROZEN 2026-05-09** | Phase 0 documentation gate | **Serialize to `src/rnd/v0.1.7/2026.05.09-cc-card-normalization/{00-index.md, 01-design.md, 02-handoff-summary.md, 90-execution-log.md}` BEFORE any code edits.** Per documentation-first protocol. | Mandatory per `feedback_phase0_serialization_prominence.md`. Reader sees the doc gate first, not buried as "pre-flight". |
| **Q7 FROZEN 2026-05-09** | `/plan-review` cycle | **Run sequential REUSE → Pass 1 Fitness → Pass 2 Adversarial after Phase 0, before Phase 1 implementation.** Implementation BLOCKED until Pass 2 Adversarial closes. | Per `feedback_pip_plan_review_is_sequential.md`. Phase 4+5 multiplexer parallelism was the wrong shortcut. |
| **Q8 FROZEN 2026-05-10** | Decorator-stack failure fallback (Phase 4.2 risk mitigation) | **If FastAPI rejects the stacked-`@router.post(...)` alias pattern, COMMENT OUT (do NOT delete) the deviant `/api/claude-code/queue/submit` decorator.** Preserve as a code-level breadcrumb showing what the alias would have looked like; mobile + smoke tests must migrate to `/api/claude-code/submit` immediately (no working alias). The commented block stays for one release cycle as documentation, then deletes. | User-ratified 2026-05-10. Comment-out preserves traceability + future re-enable option without leaving a broken endpoint live. |
| **Q9 FROZEN 2026-05-10** | Cross-sub-project handoff requirement | **Produce ONE concise handoff doc co-located in this folder (`02-handoff-summary.md`, ~150-200 lines, ≤5-min read) AND seed TODO entries pointing to it in (a) `src/lupin-mobile/TODO.md` and (b) parent Lupin `TODO.md` under a "Multiplexer follow-ups" section AND in the multiplexer R&D folder's `00-synthesis-and-roadmap.md` Open follow-ups section.** Per the new `feedback_cross_project_handoff_doc.md` memory. | User-ratified 2026-05-10. Active push of the change to mobile + multiplexer teams; prevents discovery-by-accident. |

---

## Phases

### Phase 0 — Documentation (DONE 2026-05-10)

**EXECUTOR: AI**

Serialized to canonical R&D path:
- ✅ `00-index.md` (master nav, Q-decisions, REUSE table, open follow-ups)
- ✅ `01-design.md` (this file)
- ✅ `02-handoff-summary.md` (cross-sub-project handoff — Lupin mobile + multiplexer R&D consumers)
- ✅ `90-execution-log.md` (phase status table + Phase 1-6 evidence scaffolds)

**Hand-off trigger**: invoke `/plan-review --doc-set=src/rnd/v0.1.7/2026.05.09-cc-card-normalization/` to begin sequential REUSE → Pass 1 → Pass 2.

### Phase 1 — Track A: HTML normalization

**EXECUTOR: AI**
**File**: `src/fastapi_app/static/html/notifications.html`

| Sub-step | Lines | Action |
|----------|-------|--------|
| 1.1 | 119 | Rename header from `🤖 Claude Code Dispatcher` → `🤖 Submit Claude Code Task` |
| 1.2 | 142-148 | Keep `#cc-task-type` select wrapper. Inside it, change line 146 from a comment-only block to an actual disabled option: `<option value="INTERACTIVE" disabled title="Returns when ClaudeCodeJob.inject/interrupt/end_session ship — see TODO.md 'CC DISPATCH RETIREMENT — Follow-ups'">Interactive (coming back later)</option>` |
| 1.3 | 149-154 | DELETE the entire `#cc-execution-mode` div (single-option disabled select; only "CJ Flow (only path)") |
| 1.4 | 182-191 | DELETE the entire `<div class="form-group">` containing `#cc-response` `<pre>` (yellow retirement notice; per-turn streaming retired) |
| 1.5 | 193-209 | DELETE the entire `#cc-option-b-controls` `<div class="cc-retired-banner">` block (gravestone + 4 disabled inject/interrupt/end-session inputs) |
| 1.6 | 211-216 | DELETE the entire `#cc-session-info` div (hidden by default; redundant with multiplexer Jobs pane) |
| 1.7 | After line 164 (after the submit button div) | INSERT sibling-pattern status div: `<div id="cc-submit-status" data-testid="notifications-cc-submit-status" style="margin-top: 8px; font-size: 12px; color: #666;"></div>` |
| 1.8 | `src/fastapi_app/static/css/notifications.css` | DELETE the `.cc-retired-banner` CSS class definition (2 lines). **REUSE pre-pass 2026-05-10 confirmed zero other consumers across `.css`, `.ts`, `.tsx`, `.js` files**; orphan-safe to delete inline with the HTML block cleanup at Phase 1.5. |

### Phase 2 — Track A: JS handler normalization

**EXECUTOR: AI**
**File**: `src/fastapi_app/static/js/notifications.js`

| Sub-step | Lines | Action |
|----------|-------|--------|
| 2.1 | 1583, 1598-1603 | Audit + remove the `cc-inject` / `cc-interrupt` / `cc-end` / `cc-execution-mode` event-binding lookups (their DOM elements are gone; `getElementById` would return null and silently skip, but the dead lookups should be removed for clarity) |
| 2.2 | 3734-~3770 | Rewrite `submitClaudeCodeToQueue()` to mirror the research handler at lines 2870-2949. Drop `responseEl = document.getElementById('cc-response')` + every `responseEl.textContent = ...` write. Add `statusDiv = document.getElementById('cc-submit-status')` + sibling-pattern updates: neutral-`#666` on submit, green-`#28a745` on success with `Job ID + Position`, red-`#dc3545` on error with error message |
| 2.3 | 3765 | Update fetch URL from `/api/claude-code/queue/submit` → `/api/claude-code/submit` (Track B; the alias on the server keeps the old URL working) |
| 2.4 | 41-42, 3818-3823 | Refresh the comment block above the function to describe the post-normalization shape ("UI submits to the canonical `/api/claude-code/submit` typed-Pydantic endpoint, mirrors sibling card pattern, retired-dispatch comment can be condensed") |

### Phase 3 — Track A: E2E test cleanup

**EXECUTOR: AI**
**File**: `src/tests/e2e_ui/test_job_dispatch.py`

| Sub-step | Action |
|----------|--------|
| 3.1 | DELETE `test_cc_card_has_execution_mode_select()` (asserts `#cc-execution-mode` presence; element gone) |
| 3.2 | DELETE `test_cc_card_has_session_controls()` (asserts `#cc-option-b-controls` + 4 disabled inject/interrupt/end-session presence; block gone) |
| 3.3 | DELETE `test_cc_card_has_task_type_select()` IF it asserts the deprecated comment-style INTERACTIVE; KEEP IT and update assertion if it now needs to verify the disabled `<option value="INTERACTIVE">` element exists with the expected tooltip text |
| 3.4 | Add ONE replacement test: `test_cc_card_renders_in_sibling_shape()` — asserts the card has the standard sibling DOM shape (header text, prompt textarea, submit button, `#cc-submit-status` div); zero refs to deleted IDs |

### Phase 4 — Track B: URL rename with backward-compat alias

**EXECUTOR: AI** (CoSA edits OK from parent context per `feedback_cosa_edit_vs_manage_git`; commits handled in CoSA-context separately per `feedback_lupin_only_never_cosa`)
**File**: `src/cosa/rest/routers/claude_code_queue.py`

| Sub-step | Action |
|----------|--------|
| 4.1 | Rename existing `@router.post("/api/claude-code/queue/submit", ...)` decorator to `@router.post("/api/claude-code/submit", ...)`. **Function name `submit_claude_code_to_queue` stays unchanged in this work** — it's internal-only (Python identifier, not part of the public API); the `_to_queue` suffix is now a fossil from the dispatch-retirement era, and a future cosmetic rename to `submit_claude_code_job` completes Q1 intent once the alias retires. Already noted under Out-of-scope. |
| 4.2 | Add a SECOND decorator stack on the same function: `@router.post("/api/claude-code/queue/submit", deprecated=True, summary="DEPRECATED: use /api/claude-code/submit", description="Alias for /api/claude-code/submit. Removed after one release cycle. See src/rnd/v0.1.7/2026.05.09-cc-card-normalization/01-design.md Q1.")`. **The alias DOES appear in the OpenAPI schema (no `include_in_schema=False`) marked `deprecated: true` — this is the PRIMARY discovery channel for mobile + integration tests** (container-log deprecation line at Phase 4.3 is the secondary channel). **The Q8 verdict (PRIMARY vs FALLBACK path) is determined at Phase 5.3 quick_smoke_test() route-registration check — see Phase 5.3 for the explicit gate.** If Phase 5.3 reveals stacked decorators didn't register both routes, retroactively COMMENT OUT (do NOT delete) the secondary decorator at this sub-step with a `# DEPRECATED 2026-05-10 — alias attempted but FastAPI rejected stacked decorators; mobile + smoke tests migrate to /api/claude-code/submit immediately. Re-evaluate after one release cycle.` breadcrumb. |
| 4.3 | Inside the function body, add a top-of-handler check `if request.url.path == "/api/claude-code/queue/submit": print(f"[DEPRECATED] /api/claude-code/queue/submit hit by {user_email} — migrate to /api/claude-code/submit")`. Requires `request: Request` injection (currently absent — add to signature). **If Phase 5.3 surfaces Q8 FALLBACK (no alias), this check + Request injection are not needed — skip 4.3 and document the skip in `90-execution-log.md` Phase 4 evidence.** |
| 4.4 | Update file docstring (lines 4-18) to describe both URLs + the deprecation timeline (or, if Q8 fallback, document why only the canonical URL exists). |
| 4.5 | Update `quick_smoke_test()` at line 206+ to assert BOTH routes registered (or, if Q8 fallback, assert ONLY the canonical route registered + a structural test that the commented-out decorator block is present in the source). |

**Smoke tests** (parent Lupin):
| Sub-step | File:Line | Action |
|----------|-----------|--------|
| 4.6 | `src/tests/smoke/test_claude_code_dry_run_smoke.py:116` | Update `SUBMIT_ENDPOINT = "/api/claude-code/queue/submit"` → `SUBMIT_ENDPOINT = "/api/claude-code/submit"` |
| 4.7 | `src/tests/smoke/test_claude_code_max_subscription.py:45` | Update `SUBMIT_ENDPOINT = f"{TEST_SERVER_BASE}/api/claude-code/queue/submit"` → `SUBMIT_ENDPOINT = f"{TEST_SERVER_BASE}/api/claude-code/submit"` |

**Mobile follow-up** (mobile code edits NOT in scope here — handoff doc + parent TODO entry seed mobile migration):
| Sub-step | Action |
|----------|--------|
| 4.8 | UPDATE parent Lupin `TODO.md` mobile entry under "🪦 CC DISPATCH RETIREMENT — Follow-ups" to note: alias deprecation timeline = "removed after one release cycle"; mobile `queueSubmit()` migrate to `/api/claude-code/submit` during the same migration that fixes the dispatch-cluster brokenness — see handoff doc at Phase 4.9 |

### Phase 4.5 — Cross-sub-project handoff doc (per Q9, per `feedback_cross_project_handoff_doc.md`)

**EXECUTOR: AI**
**File**: `02-handoff-summary.md` (this folder; created at Phase 0, finalized at Phase 6 once final commit hash + alias-vs-fallback verdict known)

Concise document (~150-200 lines, ≤5-min read) consumable by both the Lupin mobile team AND the multiplexer R&D team. See [02-handoff-summary.md](02-handoff-summary.md) for the actual content.

### Phase 5 — Verification

| Sub-step | Tier | Venue | Owner | Command |
|----------|------|-------|-------|---------|
| 5.1 | py_compile | local | **AI** | `python -c "import py_compile; py_compile.compile('src/cosa/rest/routers/claude_code_queue.py', doraise=True)"` |
| 5.2 | Import chain | local | **AI** | `PYTHONPATH=src:$PYTHONPATH python -c "from cosa.rest.routers.claude_code_queue import router; print('OK')"` |
| 5.3 | Router-level smoke | local | **AI** | `python -m cosa.rest.routers.claude_code_queue` (runs `quick_smoke_test()`; asserts route registration) |
| 5.4 | Live `:7999` HTTP | :7999 | **AI** | `curl -s -X POST http://localhost:7999/api/claude-code/submit -H "Authorization: Bearer …" -d '{"prompt":"smoke","dry_run":true}'` returns 200 with `cc-{uuid8}` job_id |
| 5.5 | Live `:7999` alias | :7999 | **AI** | If primary alias path: same payload to `/api/claude-code/queue/submit` returns 200 + deprecation log line in container logs. **If Q8 fallback path: same payload returns 404; this confirms the comment-out was correctly applied; document in `90-execution-log.md` Phase 4 evidence.** |
| 5.6 | CC dry-run smoke | :7999 | **AI** | `python src/tests/smoke/test_claude_code_dry_run_smoke.py` — all 6 scenarios PASS against the renamed URL |
| 5.7 | UI manual probe (programmatic via headless) | browser | **AI (NOT human)** | Open `/app/notifications` (against `:7999`) headlessly, expand the Submit Claude Code Task card, verify: card has form + submit button + status div ONLY (no response panel, no inject controls, no session-info row); INTERACTIVE option visible-but-disabled in task-type select; submit dry-run → status div turns green with `cc-{uuid8}` ID; job appears in multiplexer Jobs pane within 5s. *AI executes via headless browser, NOT human-driven.* |
| 5.8 | E2E UI suite (FUNCTIONAL) | :8000 SCHEDULED | **AI submits, HUMAN confirms slot** | Schedule via `/schedule-tests` skill: `POST /api/test-suite/submit` with `test_types="e2e"` + `pytest_args="-k test_job_dispatch"`. After completion: 0 failures from CC card tests; deleted tests are gone; new sibling-shape test passes |
| 5.9 | E2E UI suite (VISUAL) | :8000 SCHEDULED | **AI submits, HUMAN confirms slot** | Schedule via `/schedule-tests` skill: `POST /api/test-suite/submit` with `test_types="e2e"` + `pytest_args="-k visual"`. CC card visual baseline regenerated (yellow banner gone changes the snapshot); commit baseline if visual diff is intentional |
| 5.10 | Subscription smoke (BLOCKING gate) | :8000 SCHEDULED | **AI submits, HUMAN confirms slot** | Schedule via `/schedule-tests` skill: `POST /api/test-suite/submit` with `test_types="smoke"` + `pytest_args="-k test_claude_code_max_subscription"`. Asserts `cost_usd == 0.0` against the renamed URL |
| 5.11 | Cross-agent regression | :7999 | **AI** | `pytest src/tests/smoke/test_tfe_error_capture_smoke.py src/tests/smoke/test_bfe_phase6_repair_loop_smoke.py -v --tb=no` — TFE/BFE flows that may invoke ClaudeCode internally remain GREEN |

**Two-phase E2E gate** (per `feedback_e2e_two_phase_gate.md`): Code writes (Phases 1-4) complete + py_compile + smoke green BEFORE scheduling 5.8/5.9/5.10 on `:8000`. **EXECUTOR: HUMAN** (rationale: `:8000` is a shared monopolize-mode resource; AI cannot reliably query the current scheduled-test queue from outside the slot-coordinator, per `feedback_test_server_monopolize_mode.md`). HUMAN confirms no overlapping `:8000` slot BEFORE AI fires `POST /api/test-suite/submit`.

### Phase 6 — Wrap

**EXECUTOR: AI**

| Sub-step | File | Action |
|----------|------|--------|
| 6.1 | parent Lupin `TODO.md` | Mark "Live UI probe (manual gate)" item under "🪦 CC DISPATCH RETIREMENT — Follow-ups" as resolved (Phase 5.7 automated headless probe now covers this — note: the word "manual" in the original TODO item's name is metadata dating to the prior manual-testing era; it does NOT signal a current Manual-E2E ownership claim. Phase 5.7 is AI-executed headless per the test-ownership mandate). Update mobile follow-up to reflect new URL + alias timeline + handoff doc link. |
| 6.2 | parent Lupin `TODO.md` | ADD a new "Multiplexer follow-ups" section (or append to existing if present) with one entry pointing to the handoff doc |
| 6.3 | `src/lupin-mobile/TODO.md` | ADD an entry under the **Pending** section (or equivalent), status `[ ]`, tagged `[LUPIN-CC-SUBMIT-RENAME]`, with literal text matching the breadcrumb shape published in `02-handoff-summary.md`: `- [ ] [LUPIN-CC-SUBMIT-RENAME] Update Claude Code submit endpoint from /api/claude-code/queue/submit to /api/claude-code/submit. Alias active for one release cycle from <commit-date>. See parent Lupin src/rnd/v0.1.7/2026.05.09-cc-card-normalization/02-handoff-summary.md for full context. [Q8 verdict: PRIMARY\|FALLBACK]`. Fill `<commit-date>` + Q8 verdict at Phase 6.8 commit time. |
| 6.4 | `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/00-synthesis-and-roadmap.md` | APPEND to "Open follow-ups" pointing to the handoff doc |
| 6.5 | `bug-fix-queue.md` | If a CC-card-normalization tracking entry exists, mark CLOSED |
| 6.6 | parent Lupin `history.md` | New session entry summarizing the work, files modified, test results, commit hashes, handoff doc link |
| 6.7 | `90-execution-log.md` | Per-phase evidence filled (py_compile output, smoke test summaries, :8000 result tables, baseline regeneration evidence, Q8 fallback decision if invoked) |
| 6.8 | Parent Lupin commit | **EXECUTOR: AI** — selectively stage ONLY the following files (per `.claude-session.md` v2.0 selective-staging mandate; never `git add -A` or `git add .`): `src/fastapi_app/static/html/notifications.html`, `src/fastapi_app/static/js/notifications.js`, `src/fastapi_app/static/css/notifications.css`, `src/tests/e2e_ui/test_job_dispatch.py`, `src/tests/smoke/test_claude_code_dry_run_smoke.py`, `src/tests/smoke/test_claude_code_max_subscription.py`, `TODO.md`, `history.md`, `src/lupin-mobile/TODO.md`, `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/00-synthesis-and-roadmap.md`, all 4 docs under `src/rnd/v0.1.7/2026.05.09-cc-card-normalization/`. Commit message captures: Track A (UI prune) + Track B (URL rename + alias-or-fallback Q8 verdict) + handoff doc link + sub-project TODO seeds. CoSA submodule pin NOT bumped here — that happens at Phase 6.9 after the HUMAN-applied CoSA commit lands. |
| 6.9 | CoSA commit (separate context) | **EXECUTOR: HUMAN** (rationale: CoSA is a managed submodule with its own release cadence and git boundary per `feedback_lupin_only_never_cosa.md`; AI must NEVER run git in `src/cosa/` from parent context). AI's Phase 4.1-4.5 code edits inside `src/cosa/rest/routers/claude_code_queue.py` land on disk; AI documents the change intent in parent Lupin `history.md` so the CoSA-context session has a clear handoff. HUMAN then opens a separate CoSA-context session and executes `git add` + `git commit` + `git push` on the CoSA changes. AFTER the CoSA commit lands, HUMAN (or a follow-up parent-Lupin session) bumps the CoSA submodule pin in parent Lupin via a separate commit (NOT this Phase 6.8 commit). |

---

## Critical files to modify

| File | Phase | Repo | Edit type |
|------|-------|------|-----------|
| `src/fastapi_app/static/html/notifications.html` | 1 | parent Lupin | DELETE 5 blocks (~60 lines), MODIFY 1 line (header), MODIFY 1 line (INTERACTIVE option), INSERT 1 line (status div) |
| `src/fastapi_app/static/js/notifications.js` | 2 | parent Lupin | REWRITE `submitClaudeCodeToQueue()`, AUDIT cc-inject/interrupt/end/execution-mode lookups, REPLACE fetch URL |
| `src/tests/e2e_ui/test_job_dispatch.py` | 3 | parent Lupin | DELETE 2-3 obsolete test functions, ADD 1 replacement test |
| `src/cosa/rest/routers/claude_code_queue.py` | 4 | **CoSA submodule** (edit OK from parent context, COMMIT IN COSA SEPARATELY) | RENAME primary route, ADD alias route + deprecation log (or COMMENT OUT old decorator per Q8 fallback), UPDATE docstring + smoke test |
| `src/tests/smoke/test_claude_code_dry_run_smoke.py` | 4 | parent Lupin | UPDATE `SUBMIT_ENDPOINT` constant (1 line) |
| `src/tests/smoke/test_claude_code_max_subscription.py` | 4 | parent Lupin | UPDATE `SUBMIT_ENDPOINT` constant (1 line) |
| `src/rnd/v0.1.7/2026.05.09-cc-card-normalization/02-handoff-summary.md` | 0 + 6 | parent Lupin | CREATE (Phase 0), FINALIZE with commit hash (Phase 6) |
| parent Lupin `TODO.md` | 6 | parent Lupin | UPDATE mobile entry + close manual UI probe item + ADD Multiplexer follow-ups entry pointing to handoff doc |
| `src/lupin-mobile/TODO.md` | 6 | **lupin-mobile sub-repo** (edit OK from parent context — file edit only, mobile team commits in their own context) | ADD entry pointing to handoff doc |
| `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/00-synthesis-and-roadmap.md` | 6 | parent Lupin | APPEND to Open follow-ups pointing to handoff doc |
| `history.md` | 6 | parent Lupin | NEW session entry |
| `src/rnd/v0.1.7/2026.05.09-cc-card-normalization/{00-index, 01-design, 90-execution-log}.md` | 0 + 6 | parent Lupin | CREATE (Phase 0), POPULATE evidence (Phase 6) |

---

## Acceptance Criteria

| AC | Description | Verification |
|----|-------------|--------------|
| AC1 | All 5 dead UI blocks deleted from `notifications.html` (cc-execution-mode, cc-response, cc-option-b-controls, cc-session-info, cc-retired-banner usage in HTML) | `grep -nE "cc-execution-mode\|cc-response\|cc-option-b-controls\|cc-session-info\|cc-retired-banner" notifications.html` returns 0 hits |
| AC1.5 | `.cc-retired-banner` CSS class definition removed from `src/fastapi_app/static/css/notifications.css` (REUSE pre-pass confirmed orphan-safe) | `grep -n "cc-retired-banner" src/fastapi_app/static/css/notifications.css` returns 0 hits |
| AC2 | `#cc-task-type` select retains both BOUNDED + INTERACTIVE options; INTERACTIVE has `disabled` attribute + tooltip explaining return condition | DOM inspection at `:7999/app/notifications` |
| AC3 | Card header reads exactly `🤖 Submit Claude Code Task` | grep notifications.html line 119 |
| AC4 | New `<div id="cc-submit-status" data-testid="notifications-cc-submit-status">` exists, located after submit button | grep notifications.html |
| AC5 | `submitClaudeCodeToQueue()` mirrors research handler shape: button-disable, spinner, status div updates (neutral/green/red), no `cc-response` writes | AI asserts via (a) `grep -nE "statusDiv\.style\.color = ('#666'\|'#28a745'\|'#dc3545')" notifications.js` returns all three literals in the CC handler; (b) programmatic `:7999` dry-run POST + headless DOM observation confirms all three colors fire in sequence (neutral on submit → green on success). No human ratification of submit visuals. |
| AC6 | JS fetches from `/api/claude-code/submit` (NOT `/queue/submit`) | grep notifications.js |
| AC7 | Server registers BOTH `/api/claude-code/submit` (canonical) AND `/api/claude-code/queue/submit` (alias). Both return identical responses; alias logs deprecation warning. **OR (Q8 fallback): only the canonical route registered + commented-out alias decorator with breadcrumb is present in source.** | `quick_smoke_test()` + curl probes 5.4 + 5.5 |
| AC8 | `test_job_dispatch.py` no longer references any of the 9 deleted data-testids; new `test_cc_card_renders_in_sibling_shape()` passes | grep test_job_dispatch.py + pytest run |
| AC9 | `test_claude_code_dry_run_smoke.py` 6 scenarios all PASS against renamed URL | Phase 5.6 |
| AC10 | `test_claude_code_max_subscription.py` PASSES against renamed URL with `cost_usd == 0.0` | Phase 5.10 (`:8000` SCHEDULED) |
| AC11 | AI asserts via Phase 5.8 + 5.9 evidence in `90-execution-log.md`: (a) pytest output shows `0 failures, N passed` where N ≥ 3 (2 deleted obsolete tests + 1 new sibling-shape test + any pre-existing CC tests); (b) Phase 5.9 git-diff of visual baselines contains ONLY the `.cc-retired-banner` removal + expected layout changes (card height reduction, INTERACTIVE-disabled option visible, removed-element shifts). Diffs outside this allow-list = regression → AC11 FAILS. | Phase 5.8 + 5.9 (`:8000` SCHEDULED) |
| AC12 | TFE + BFE smoke tests stay GREEN (no cross-agent regression) | Phase 5.11 |
| AC13 | TODO.md mobile entry updated; "Live UI probe (manual gate)" item closed (the "manual" in the original item name is legacy metadata — Phase 5.7 automated probe now satisfies the gate per AI-headless ownership) | grep TODO.md |
| AC14 | history.md session entry committed | git log |
| AC15 | `90-execution-log.md` populated with per-phase evidence | file inspection |
| AC16 | `02-handoff-summary.md` exists at canonical R&D path; ~150-200 lines; covers TL;DR / what / why / per-sub-project action / migration timeline / where to ask | file inspection + line count |
| AC17 | `src/lupin-mobile/TODO.md` has ONE new entry pointing to the handoff doc | grep |
| AC18 | parent Lupin `TODO.md` has ONE new "Multiplexer follow-ups" entry pointing to the handoff doc | grep |
| AC19 | `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/00-synthesis-and-roadmap.md` Open follow-ups section gains ONE entry pointing to the handoff doc | grep |

---

## Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| FastAPI stacked-decorator alias does not register both routes (some versions/configs reject this) | Low-Medium | Phase 4.5 `quick_smoke_test()` asserts both routes registered. **Per Q8 ratification: if stacked decorators fail, COMMENT OUT (do NOT delete) the deviant `/queue/submit` decorator with a `# DEPRECATED 2026-05-10 — alias attempted but FastAPI rejected` breadcrumb. Mobile + smoke tests migrate to `/api/claude-code/submit` immediately (no working alias). Two-separate-functions-sharing-helper is a follow-up option, not a same-session pivot.** |
| Visual snapshot test fails because the card shape changed substantially | High (expected) | Phase 5.9 regenerates baseline — this is intentional, not a regression. Commit new baseline. |
| Mobile app silently breaks if alias deprecation log goes unnoticed | Medium | Phase 4.8 TODO.md update + alias `deprecated=True` flag in OpenAPI schema. Mobile migration is a separate epic; alias buys one release cycle. Q8 fallback path tightens this to "mobile breaks immediately on deploy" — handoff doc + TODO seeding makes the migration urgency explicit. |
| `cc-inject` / `cc-interrupt` / `cc-end` event-handler audit at Phase 2.1 misses a binding that throws on null DOM | Low | py_compile + AI-executed `:7999` curl + headless DOM probe will surface any runtime errors |
| User schedules :8000 tests during plan-review walk and they collide with existing `:8000` work | Low | Phase 5 :8000 sub-steps are sequential AFTER all code edits, AND require user slot-confirmation per `feedback_test_server_monopolize_mode` |
| Coverage mandate scope on JS + backend Python edits | NIL (JS) / Low (Python) | JS edits at `src/fastapi_app/static/js/notifications.js` are out of scope per `feedback_100pct_coverage_multiplexer.md` (mandate applies to multiplexer TS only). For the Python edit at `src/cosa/rest/routers/claude_code_queue.py` (Phase 4): verify at execute time whether CoSA enforces backend coverage on route decorators. If yes, add a coverage report to Phase 5a evidence. If no (typical — backend coverage usually targets business logic, not route decorators), no action. |
| `deprecated=True` route param is novel to this codebase (REUSE 2026-05-10 confirmed zero prior uses) | Low | Standard FastAPI kwarg — no behavioral risk. Documentation hygiene: code reviewer may not recognize the keyword. Phase 4.4 docstring update should explicitly mention `deprecated=True` so the alias intent is clear at the file level. |

---

## Out of scope

- Migrating ANY agent's submit endpoint to `/api/push-agentic` — that endpoint is for agent-to-agent, not human UI (consumer split confirmed with user 2026-05-09)
- Migrating sibling agents (DR / Podcast / Presentation / SWE / BFE / Test Suite) to a unified URL or shared submit handler — separate scope, would need its own R&D doc
- Restoring INTERACTIVE controls — happens when `ClaudeCodeJob.inject/interrupt/end_session` ship; co-designed with the new endpoints, NOT a revival of the retired stubs
- Mobile `claude_code_repository.dart` migration off the retired dispatch cluster — already in `TODO.md` under "🪦 CC DISPATCH RETIREMENT — Follow-ups" as a `[LUPIN-MOBILE]` item; this plan only updates the URL target for that future migration (via handoff doc)
- Any changes to `agentic_job_factory.py`, `todo_fifo_queue.py`, or the in-flight Bounded ClaudeCodeJob canonical-shape redesign at `src/rnd/v0.1.7/2026.05.07-claude-code-bounded-redesign/`
- Multiplexer TS work — `JobsPaneRenderer` already renders CC jobs correctly; 100% coverage mandate scope unchanged
- Function rename `submit_claude_code_to_queue` → `submit_claude_code_job` — cosmetic, defer to a separate cleanup pass
- Extracting a shared `setSubmitStatus(divId, text, color)` helper across all 6 sibling submit handlers — separate refactor, would touch every submit handler

---

## Verification (end-to-end summary)

**Local (`:7999`, AI-discretionary)**:
1. py_compile claude_code_queue.py
2. import-chain check
3. python -m cosa.rest.routers.claude_code_queue (smoke + route registration)
4. curl POST `/api/claude-code/submit` (200 + cc-{uuid8})
5. curl POST `/api/claude-code/queue/submit` (200 + deprecation log, OR 404 if Q8 fallback)
6. python src/tests/smoke/test_claude_code_dry_run_smoke.py (6/6 PASS)
7. Headless probe of `/app/notifications`: submit dry-run, observe status div + Jobs pane
8. pytest src/tests/smoke/test_tfe_*.py test_bfe_*.py -v --tb=no

**Scheduled (`:8000`, user-confirmed slot)**:
1. `/schedule-tests` POST `/api/test-suite/submit` `test_types="e2e"` `pytest_args="-k test_job_dispatch"`
2. `/schedule-tests` POST `/api/test-suite/submit` `test_types="e2e"` `pytest_args="-k visual"`
3. `/schedule-tests` POST `/api/test-suite/submit` `test_types="smoke"` `pytest_args="-k test_claude_code_max_subscription"`

**Plan-review handoff** (Phase 0 closure):
```
/plan-review --doc-set=src/rnd/v0.1.7/2026.05.09-cc-card-normalization/
```
Sequential gates: REUSE pre-pass → user → Pass 1 Fitness → user → Pass 2 Adversarial → user → unblock Phase 1.
