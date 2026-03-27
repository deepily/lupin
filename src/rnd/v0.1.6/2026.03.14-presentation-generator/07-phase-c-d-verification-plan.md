# Presentation Generator — CJ Flow Dry-Run Verification (Phases C-D)

**Date**: 2026-03-25
**Session**: 372
**Plan source**: `~/.claude/plans/cozy-hopping-falcon.md`

## Context

Phases 1-5 of the Presentation Generator are complete (37/56 tasks, 211 unit tests). Phase B verification (enhanced CLI dry-run) passed — 2412 words, 10 slides, 4.5KB YAML. However, the agent has **never been exercised through the actual CJ Flow queue or notifications UI**. Before building Phase 6 (Marp Rendering), we need to verify the full queue pipeline works end-to-end.

**Gaps found**:
1. `AGENTIC_MODE_MAP` + `MODE_METADATA` in `todo_fifo_queue.py` — missing "presentation" entry (no Q&A dropdown option)
2. `notifications.html` — no "Presentation" option in Q&A mode dropdown (hardcoded HTML)
3. `notifications.html` — no dedicated "Submit Presentation Job" card in agentic jobs section
4. `notifications.js` — no `submitPresentationJob()` handler

---

## Step 1: Backend — Add to Mode Maps

**File**: `src/cosa/rest/todo_fifo_queue.py`

Add to `MODE_METADATA` (after `swe_team` at line ~77):
```python
"presentation"       : { "display_name": "Presentation",       "description": "Generate slides from a document" },
```

Add to `AGENTIC_MODE_MAP` (after `swe_team` at line ~89):
```python
"presentation"       : "agent router go to presentation generator",
```

**2-line change.** Mode router reads dynamically — no other backend wiring needed.

---

## Step 2: Frontend HTML — Q&A Dropdown + Agentic Card

**File**: `src/fastapi_app/static/html/notifications.html`

### 2A: Add to Q&A mode dropdown (line ~55, after SWE Team option)
```html
<option value="presentation">Presentation Generator</option>
```

### 2B: Add Presentation submission card (after SWE Team card, before closing `</div>` at line ~293)

New card following the Podcast Generator card pattern:
- Source path input with STT voice button and smart-input hint
- Audience selector dropdown (general/beginner/expert/academic)
- Target duration input (minutes, default 15)
- Dry-run checkbox (checked by default)
- Submit button (teal/green color: `#20c997`)
- Status div for feedback
- `data-testid` attributes for E2E testing

**Fields**:
| ID | Type | Purpose |
|---|---|---|
| `presentation-source` | text input | Source document path |
| `presentation-stt-button` | button | Voice input for source |
| `presentation-audience` | select | general/beginner/expert/academic |
| `presentation-duration` | number | Target minutes (default 15) |
| `presentation-dry-run` | checkbox | Dry-run mode (default checked) |
| `submit-presentation-job` | button | Submit trigger |
| `presentation-loading` | span | Spinner |
| `presentation-submit-status` | div | Status feedback |

---

## Step 3: Frontend JS — Wire Up Handler

**File**: `src/fastapi_app/static/js/notifications.js`

### 3A: Add event listener init (in the section after SWE Team listener, ~line 1784)

Wire click handler for `submit-presentation-job` → `this.submitPresentationJob()`, plus STT button and Enter-key handler for `presentation-source` input.

### 3B: Add `submitPresentationJob()` method (after `submitSweTeamJob()`, ~line 2720)

Follow `submitPodcastJob()` pattern exactly:
1. Get DOM elements
2. Validate source not empty
3. Show loading state
4. `ensureValidToken()`
5. POST to `/api/presentation-generator/submit` with:
   ```json
   {
       "source_path": "...",
       "audience": "general",
       "target_duration_minutes": 15,
       "dry_run": true
   }
   ```
6. Handle `queued` response → show job_id + queue_position
7. Error handling → show message
8. Reset loading state

---

## Step 4: Create Dry-Run Smoke Test

**New file**: `src/tests/smoke/test_presentation_dry_run_smoke.py`

**Pattern**: Clone `test_claude_code_dry_run_smoke.py` structure exactly.

**6 scenarios**:

| # | ID | Description | Validation |
|---|---|---|---|
| 0 | PR_DRY_RUN_BASIC | Submit dry-run with real source file | keywords in response |
| 1 | PR_AGENT_TYPE | Verify `agent_type` in done queue metadata | check: agent_type |
| 2 | PR_COST_SUMMARY | Verify `cost_summary.total_cost_usd == 0.0` | check: cost_summary |
| 3 | PR_TIMESTAMPS | Verify `started_at` / `completed_at` set | check: timestamps |
| 4 | PR_JOB_ID_PREFIX | Verify `job_id` starts with `pr-` | check: job_id_prefix |
| 5 | PR_MISSING_SOURCE | Submit empty `source_path` → expect HTTP 400 | check: http_error |

**Key settings**:
- `SUBMIT_ENDPOINT = "/api/presentation-generator/submit"`
- `DEFAULT_TIMEOUT = 180`
- `get_mode_for_scenario()` returns `None` (dedicated REST endpoint)
- Source file: `/src/rnd/2026.03.14-presentation-generator/01-strategy-and-design.md`

**Entry points**: `quick_smoke_test()`, `test_presentation_dry_run_endpoint()` (pytest), `__main__` with `sys.argv`.

---

## Step 5: Run Smoke Test and Verify Queue Flow

1. Ensure server running on port 7999
2. Run: `python src/tests/smoke/test_presentation_dry_run_smoke.py --debug`
3. Watch server console for:
   - `Running AgenticJob [presentation]` banner
   - Phase breadcrumb notifications
   - Job moving todo → running → done
4. Verify all 6 scenarios pass

---

## Step 6: Manual UI Verification

1. Open Lupin UI in browser
2. **Q&A Interface**: Verify "Presentation Generator" in mode dropdown, submit via text input
3. **Agentic Jobs card**: Verify presentation card renders, submit with source path + dry-run
4. Watch job card in queue panel with `pr-` prefix
5. Watch status transitions: queued → running → done
6. Verify breadcrumb notifications in conversation panel

---

## Step 7 (Optional): Phase D — Live E2E Test

**Defer to follow-up session** unless Phase C completes quickly. Needs:
- Real Claude API calls ($0.10-0.30)
- Voice gates fire (notification proxy auto-answer or manual)
- Separate test file: `test_presentation_live_smoke.py`
- Timeout: 300-600s

---

## Critical Files

| File | Action |
|---|---|
| `src/cosa/rest/todo_fifo_queue.py` (lines 63-89) | Add 2 entries to MODE_METADATA + AGENTIC_MODE_MAP |
| `src/fastapi_app/static/html/notifications.html` (lines 55, 292) | Add dropdown option + new submission card |
| `src/fastapi_app/static/js/notifications.js` (~lines 1784, 2720) | Add event listener + `submitPresentationJob()` |
| `src/tests/smoke/test_presentation_dry_run_smoke.py` | **Create** — 6-scenario dry-run smoke test |
| `src/tests/smoke/test_claude_code_dry_run_smoke.py` | **Reference** — pattern to follow |
| `src/tests/smoke/utilities/live_pipeline_base.py` | **Reuse** — base class for submit-and-poll |
| `src/cosa/rest/routers/presentation_generator.py` | **Read-only** — endpoint being tested |

---

## Verification

1. **Unit tests**: `pytest src/tests/unit/ -v` — no regressions from mode map change
2. **Smoke test**: `python src/tests/smoke/test_presentation_dry_run_smoke.py` — all 6 pass
3. **UI — Q&A path**: "Presentation Generator" in dropdown, can submit via Q&A input
4. **UI — Agentic card**: Presentation card renders, can submit with source path
5. **Server logs**: Phase breadcrumbs printed, no errors in queue pipeline
6. **E2E tests**: `./src/scripts/run-e2e-ui-tests.sh -v` — no regressions (new card doesn't break existing)
