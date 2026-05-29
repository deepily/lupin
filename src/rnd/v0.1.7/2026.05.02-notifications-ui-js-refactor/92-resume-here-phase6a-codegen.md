# 92 — Resume Here: Multiplexer Phase 6a Code-Writing Cycle (post-/clear pointer)

**Purpose**: Single-file pointer document for the new session that picks up after `/clear` to begin **Phase 6a code-writing**. Read this first; everything else is linked from here.

**Phase 6a status going in**:
- ✅ REUSE-CLOSED 2026-05-05
- ✅ PASS-1-CLOSED 2026-05-06 AM (17 findings ratified; F15 ratification produced the 100% c8 coverage mandate for multiplexer TS)
- ✅ PASS-2-CLOSED 2026-05-06 PM (15 findings + C-6 Layer 3 ratified; design doc fully updated; convergence re-grep clean; "user is never a tester" mandate audit clean — all 15 ACs `EXECUTOR: AI` with AC11a's HUMAN slot-coordination explicitly mandate-blessed)
- ✅ Phase 4 + Phase 5 c8 100% coverage backfill closed (400 tests passing)

**Documentation cycle CLOSED. Implementation cycle now opens.**

---

## Recommended kick-off prompt (paste after `/clear`)

> Begin the Phase 6a code-writing cycle. The Phase 6a documentation cycle is closed and the design doc is implementation-ready. Read these in order:
>
> 1. `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/92-resume-here-phase6a-codegen.md` (this pointer doc — start here)
> 2. `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/08-phase6a-jobs-surface-design.md` (Pass-2-resolved design doc; AC table is the implementation contract)
> 3. `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/94-phase6a-review-findings.md` § "Pass 2 Adversarial — closed" (disposition trail for the 15 findings + C-6; cross-reference if a design decision feels surprising)
>
> Then enter plan mode to sequence the implementation. Constraints baked into the design doc:
>
> - **`feedback_documentation_step_stops_at_doc`** — do NOT auto-progress through ExitPlanMode. Land the implementation plan in the chat first; wait for explicit user approval before writing code.
> - **`feedback_phase0_serialization_prominence`** — if the implementation plan adds new tracking docs, serialize them as Phase 0 BEFORE any code edits.
> - **100% c8 coverage mandate for multiplexer TS** — every new file under `src/fastapi_app/static/js/multiplexer/` must hit `c8 --100` (lines + branches + functions + statements). `c8 ignore` allowed but requires same-line comment with explicit reason. See `feedback_100pct_coverage_multiplexer.md` auto-memory.
> - **"User is never a tester"** — every AC is `EXECUTOR: AI`. AC11a's HUMAN column is slot-coordination only (calendar coordination, NOT tester duty, NOT budget approval). Tests run under your control; you triage failures.
> - **`feedback_audit_plans_at_execute_time`** — re-audit the plan against feedback memories before ExitPlanMode.
> - **`feedback_acknowledge_receipt_before_tool_work`** — if conversation mode is active, ack receipt via `notify()` before tool calls.
>
> Confirm the read-and-understood state and propose the implementation sequence.

---

## TL;DR for the resuming session

### What "Phase 6a" delivers

A new "Jobs Pane" surface in the multiplexer UI: 5-bucket layout (todo / running / done / dead / history) rendering `Job` records from Phase 4 `JobStore`. Card template + bucket template + renderer + CSS port + tests. Hydrate-on-mount via `JobStore.hydrateHistory(api)` (Phase 4 method previously banned — Phase 6a explicitly invokes it).

### What needs to be built (Critical files in design doc)

**New files (9)**:
- `src/fastapi_app/static/js/multiplexer/render/JobsPaneRenderer.ts`
- `src/fastapi_app/static/js/multiplexer/render/templates/jobCard.ts`
- `src/fastapi_app/static/js/multiplexer/render/templates/jobBucket.ts`
- `src/fastapi_app/static/css/multiplexer/jobs-pane.css`
- `src/tests/unit/multiplexer/render/templates_job_card.test.ts`
- `src/tests/unit/multiplexer/render/templates_job_bucket.test.ts`
- `src/tests/unit/multiplexer/render/jobs_pane_renderer.test.ts`
- `src/tests/smoke/test_multiplexer_phase6a_smoke.py`
- `src/tests/e2e_ui/test_multiplexer_phase6a_visual.py`

**Edited files (5)**:
- `src/fastapi_app/static/html/multiplexer.html` (lift `data-phase6-pending` + `hidden` from `#jobs-pane`; populate section structure with `#jobs-buckets-container` + "Load history" button; add CSS `<link>` for `jobs-pane.css`)
- `src/fastapi_app/static/js/multiplexer/boot.ts` (jobs renderer instantiation post-Phase-5-renderer-mount; emits `BootCompletePayload.handlers.jobsRenderer = "mounted"`; emits the SECOND stable AC9 line `console.log("[multiplexer] jobsRenderer:mounted")`; invokes `configureMetaDisplayCap(serverConfig)` after fetching the client-config endpoint)
- `src/fastapi_app/static/html/dev-tools.html:145` (description text)
- `src/fastapi_app/static/js/multiplexer/render/index.ts` (export `createJobsPaneRenderer` from barrel)
- `src/fastapi_app/static/js/multiplexer/shared/types.ts` (extend `BootCompletePayload.handlers` with optional `jobsRenderer?: string`)

**Side-effect tasks paired with Pass 2 close** (NOT optional — these are part of the implementation cycle):

1. **INI key for F20 cap** (per Pass 2 F20 user refinement):
   - Add to `src/conf/lupin-app.ini` under `[Lupin: Baseline]`: `multiplexer max meta display bytes = 256000`
   - Matching explanation in `src/conf/lupin-app-splainer.ini`
   - Verify FastAPI client-config endpoint exposes this key (the existing endpoint pattern that already serves other tunable client values to `boot.ts`)
2. **`render/time.ts` extension** (per Pass 2 F24): add `formatDuration(startTs: number, endTs?: number): string` returning humanized "5m 12s" / "1h 47m" / "running for 23s"; add 4 unit-test cases in `render/time.test.ts` (sub-minute, sub-hour, multi-hour, running-with-undefined-end). Coverage rolls into Phase 5's existing 100% mandate.
3. **stylelint config** (per Pass 2 F28): add `.stylelintrc.json` `overrides` block for `jobs-pane.css` with `selector-disallowed-list: ["*", "html", "body", ":root"]`.

### AC table is the implementation contract

15 acceptance criteria, all `EXECUTOR: AI`. Floors:

| AC | Floor / requirement |
|---|---|
| AC1 | `npx tsc --noEmit` exit 0 |
| AC2 | `npx eslint src/fastapi_app/static/js/multiplexer/` exit 0 |
| AC2a | `grep -rn "hydrateHistory" src/.../render/` returns ≥1 match (Phase 5 ban INVERTS to a require) |
| AC3 | jobCard template tests ≥6 PASS |
| AC4 | jobBucket template tests ≥6 PASS (includes F30 keyboard activation sub-test + aria-expanded) |
| AC5 | JobsPaneRenderer tests **≥18** PASS (Test 15+16 deferred-promise race tests, Test 17 mount idempotency throw, Test 18 disabled-delete-button no-op) |
| AC6 | `c8 --100` on the new render files (lines / branches / functions / statements all 100%) |
| AC7 | `boot.js` gz delta ≤ +30 KB vs Phase 5 baseline 29662 → ceiling **60382** bytes |
| AC8a | Functional smoke: 5 buckets present; 3-job fixture (statuses `running`/`done`/`done` — third lands in history via separate `job_removed` event); `data-phase6-pending` count = 1+N |
| AC8b | Perf gate: 50-job pre-seed paints within 150ms of `boot_complete` |
| AC9 | Boot emits stable line `[multiplexer] jobsRenderer:mounted` (separate from JSON `boot_complete` line, per F22) |
| AC10 | Cross-phase verification (1)-(10) all green; sub-steps 10a-10e for visual baseline drift detection (three-layer scope-leak: grep + stylelint + canary; default-to-rollback decision tree) |
| AC10b | CSS port residual ≤ 800 LOC + stylelint clean |
| AC11a | E2E submission via `POST /api/test-suite/submit` (HUMAN slot-coordination column; AI executes the curl) |
| AC11b | E2E post-run: visual baseline directory non-empty + container log shows "1 passed, 0 errors" on Run #2 |

### Plan-mode constraints (read these before drafting the implementation plan)

- **`feedback_documentation_step_stops_at_doc`**: do not auto-ExitPlanMode. Plan first, ratify with user, then implement.
- **`feedback_phase0_serialization_prominence`**: if new tracking docs are needed (most likely a `90-execution-log.md` Phase 6a section seed), serialize them as Phase 0 before code edits.
- **`feedback_audit_plans_at_execute_time`**: re-audit against memory before exit.
- **`feedback_plans_include_tracking_docs`**: design doc + paired execution log per phase.
- **`feedback_lupin_only_never_cosa`**: parent-Lupin work only; never touch git in `src/cosa/`.
- **`feedback_no_defensive_programming`**: no `x ?? defaultX()` chains where the value is required from upstream.
- **`feedback_never_auto_commit_push`**: every commit needs explicit user approval.
- **100% c8 mandate**: every new TS file under `multiplexer/` hits `c8 --100`.
- **"User is never a tester"**: AI runs all tests across the pyramid (unit / smoke / integration / E2E); user is the architect/designer + end user, never the tester.

### Implementation sequencing — suggested order (open for plan mode to revise)

1. **Phase 0 — Author tracking docs** (per `feedback_phase0_serialization_prominence`):
   - Seed `90-execution-log.md` Phase 6a section
   - Phase 0 serialization completes BEFORE any code edits
2. **Phase 1 — Genuinely-new dependencies** that other 6a code consumes:
   - INI key + splainer entry (per F20)
   - FastAPI client-config endpoint exposes the key (verify existing pattern)
   - `formatDuration` in `render/time.ts` + 4 unit tests (per F24)
3. **Phase 2 — Templates** (no JobStore dependency yet, pure rendering):
   - `templates/jobCard.ts` + tests ≥6
   - `templates/jobBucket.ts` + tests ≥6 (includes F30 keyboard + aria-expanded)
4. **Phase 3 — JobsPaneRenderer** (consumes templates + JobStore):
   - `JobsPaneRenderer.ts` + tests ≥18 (mount idempotency, deferred-promise races, disabled-delete-button no-op)
5. **Phase 4 — CSS port + page shell**:
   - `jobs-pane.css` (≤800 LOC, stylelint clean)
   - `multiplexer.html` updates
   - `boot.ts` updates (renderer instantiation + AC9 stable line + `configureMetaDisplayCap`)
6. **Phase 5 — Smoke + E2E**:
   - `test_multiplexer_phase6a_smoke.py` (functional + perf + AC9 handshake)
   - `test_multiplexer_phase6a_visual.py` (E2E visual regression)
7. **Phase 6 — Cross-phase verification + scheduled E2E**:
   - AC10 cross-phase suite
   - AC10b stylelint config + CSS-canary test
   - AC11a/AC11b — schedule the `:8000` E2E run via `/api/test-suite/submit` (user confirms slot)

### Auto-memory hits expected

These memories will fire repeatedly during code-writing — read at session start:

- `feedback_100pct_coverage_multiplexer` — mandatory floor
- `feedback_documentation_step_stops_at_doc` — pre-exit gate
- `feedback_phase0_serialization_prominence` — Phase 0 ordering
- `feedback_audit_plans_at_execute_time` — re-audit before exit
- `feedback_acknowledge_receipt_before_tool_work` — conversation-mode receipt acks
- `feedback_recraft_speech_dont_pipe_terminal` — voice channel re-shaping
- `feedback_e2e_two_phase_gate` — E2E baseline + regression gate
- `feedback_test_server_monopolize_mode` — `:8000` scheduled-only via `/api/test-suite/submit`
- `feedback_lupin_only_never_cosa` — parent-Lupin git only
- `feedback_never_auto_commit_push` — explicit per-commit approval

### Conversation mode contract (if active)

If `get_session_info().conversation_mode_active === true`:
- Receipt-ack BEFORE every tool batch (one short sentence, e.g., "Drafting the implementation plan now.")
- Closing turn `notify()` with **headline-only voice + rich `abstract`** for written record
- Spoken `message` capped ~120 words; strip code blocks, file paths, line numbers, JSON
- `abstract` STAYS richly formatted with full markdown / code / tables

### Where to look (state pointers)

- **Design doc**: `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/08-phase6a-jobs-surface-design.md` — AC table (lines 379-396), Critical files (lines 423-444), Risks table (lines 312-328), Pre-exit self-audit (lines 462-486)
- **Findings doc**: `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/94-phase6a-review-findings.md` § "Pass 2 Adversarial — closed 2026-05-06 PM" (full disposition trail)
- **Slicing manifest**: `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/07-phase6-slicing-manifest.md` (Phase 6 → 6a/6b/6c slice rationale; 6b is delete UX, 6c is persona modal + audio recorder)
- **Phase 0 decisions**: `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/01-phase0-decisions.md` Q11 amendment (sequential PIP mandate)

### Session metadata

- **Author session**: `5ced4868` (Mr. Radio persona) — same session that:
  - Closed Phase 4 + Phase 5 100% coverage backfill (10 PM-half files)
  - Walked Pass 2 Adversarial ratification (15 findings + C-6)
  - Authored this resume-here pointer
- **Authored**: 2026-05-06 PM (post-Pass-2-close)
- **Voice persona used**: Mr. Radio 🦉 (#FFA000)
- **Conversation mode**: active throughout Pass 2 ratification + this authoring step

---

**End of resume-here doc. Welcome to the implementation cycle.**
