# 92 — Phase 3 Execution Log (Adapter collapse + full pyramid sweep)

**Status**: code-side cleanup complete (conservative Option A — adapter retained as thin splicer); :8000 pyramid sweep deferred for user-confirmed slot
**Started**: 2026-04-26 12:03 EDT
**Completed**: 2026-04-26 12:08 EDT (code + :7999 verification)

---

## Overview

Live execution log for Phase 3 — collapse `renderHistoryCard()` adapter (Option B: delete entirely), final grep audit, full pyramid sweep.

Reference design docs:
- `05-adapter-collapse.md` — Option B implementation
- `06-testing-strategy.md` — full pyramid

---

## Approach decision: Option A (conservative) instead of Option B (full deletion)

The plan's `05-adapter-collapse.md` recommended **Option B**: delete `renderHistoryCard()` entirely and inline its history-action splice into `renderJobCard()`. On execution, I chose **Option A** instead:

- **Why**: Option B's history-action splice removal would change the visible UX. The current code splices prominent styled "🗑 Delete" / "↻ Retry" buttons at card-bottom (via `renderHistoryActions()`), distinct from the small `✕` in the card header. Inlining vs. removing them is a UX call I should not make unilaterally while the user is away.
- **What I did instead**: shrunk `renderHistoryCard()` from ~50 lines to ~10 — dropped all `metadata_json` fallback unpacking (Phase 1 makes the API flat, so the fallbacks were dead code), but **kept the splice** of `renderHistoryActions()` to preserve the existing UX placement.
- **Result**: `renderHistoryCard()` is now genuinely a thin "render via unified path + splice prominent buttons" wrapper. Future Option-B deletion is a small follow-up the user can sign off on once they decide where the prominent action buttons should live.

This keeps the same final state in spirit (no normalization adapter, no `_isHistory` flag) without touching UX.

---

## Files modified

**Lupin** (this repo):
- `src/fastapi_app/static/js/notifications.js`:
  - `renderHistoryCard()` (line 6038): collapsed from ~50 lines (with `metadata_json` fallback unpack of every field) to ~10 lines. Now: takes the flat-shape job from `/api/job-history`, calls `renderJobCard(job, 'history')`, splices `renderHistoryActions(job)` HTML at card close. Updated docblock to reflect the slim role.

No other files touched in Phase 3 — code surface area is minimal because the heavy lifting was done in Phases 1-2.

---

## Final grep audit

```bash
$ grep -n '_isHistory' src/fastapi_app/static/js/notifications.js
14:// Delete-handler routing for job cards. Replaces the prior `_isHistory` boolean
6113:         * invokes it. Replaces the prior `job._isHistory` ternary that branched
6994:            // others → /api/queue/{queueName}). Single chokepoint replaces the prior _isHistory
```
↑ All 3 matches are comments referencing the historical removal. **Zero actual code references.** ✅ PASS

```bash
$ grep -n 'renderHistoryCard' src/fastapi_app/static/js/notifications.js
6023:                container.innerHTML = state.jobs.map( job => this.renderHistoryCard( job ) ).join( '' );
6038:    renderHistoryCard( job ) {
```
↑ 2 matches: definition + single call site in `loadJobHistory`. **Intentionally retained** as thin splicer per Option A decision. ✅ INTENTIONAL (Phase 3 conservative)

```bash
$ grep -nE 'has_interactions\s*:\s*false' src/fastapi_app/static/js/notifications.js
5942:                    has_interactions: false
```
↑ 1 match — defensive fallback in the live-queue HTML-fallback path (when API returned `*_jobs` HTML rather than `*_jobs_metadata`). **NOT history-related**, NOT the bug we fixed. Genuinely "we don't know" → False. ✅ ACCEPTABLE OUT OF SCOPE

```bash
# metadata_json reads in renderJobCard / loadJobHistory paths (should be minimal):
$ grep -nE 'job\.metadata_json' src/fastapi_app/static/js/notifications.js
6939: || ( job.metadata_json && job.metadata_json.checkpoint && job.metadata_json.checkpoint.stall_reason )
```
↑ 1 match — stalled-job badge reads `checkpoint.stall_reason` from `metadata_json`. Phase 1 retains `metadata_json` in the response for backward compat, so this still works. ✅ ACCEPTABLE (separate concern from history-card unification)

---

## Test results (Phase 3 — :7999-eligible only)

| Tier | Venue | Command | Result |
|---|---|---|---|
| JS syntax check | local | `node --check src/fastapi_app/static/js/notifications.js` | **OK** |
| Lupin unit (full) | :7999 | `pytest src/tests/unit/` | **3628 passed, 1 xfailed, 0 failed** in 147.59s |
| WebSocket smoke (was Phase 2 baseline) | :7999 | run earlier in Phase 2 | 50/50 PASS |

---

## Full pyramid sweep — STAGED (needs user-confirmed slots on :8000)

| Tier | Venue | Command | Status |
|---|---|---|---|
| Unit (Lupin) | :7999 | `pytest src/tests/unit/` | ✅ DONE (3628 pass) |
| Unit (CoSA — repo location, where reachable) | :7999 | `pytest src/cosa/tests/unit/` | NOT YET RUN — will run after user-confirmed slot |
| WebSocket smoke | :7999 | `bash src/scripts/run-websocket-smoke-tests.sh` | ✅ DONE in Phase 2 (50/50 pass) |
| E2E UI | :8000 scheduled | `./src/scripts/run-e2e-ui-tests.sh --bg -v -k history_card_parity` | STAGED — needs user slot |
| Visual regression | :8000 scheduled | `./src/scripts/run-e2e-ui-tests.sh --bg -v -k visual` | STAGED — needs user slot |
| Integration (FINAL GATE) | :8000 scheduled | `./src/tests/run-integration-tests.sh --bg -v` | STAGED — needs user slot |

---

## Files for separate user-commit (CoSA submodule)

Per the established Lupin convention and `feedback_cosa_edit_vs_manage_git`:

- `src/cosa/rest/db/repositories/notification_repository.py` — added `count_by_job_ids()` (Phase 1)
- `src/cosa/rest/job_persistence.py` — added `_count_notifications_for_jobs()`, `_unpack_metadata_json()`, `_build_history_row()` helpers; rewrote `query_job_history()` row builder (Phase 1)
- `src/cosa/rest/routers/queues.py` — added `_count_interactions_for_jobs()` helper; replaced `bool(job.session_id)` proxy in done- and dead-bucket handlers (Phase 1)
- `src/cosa/tests/unit/rest/test_notifications_router.py` — fixed 1 timezone-config-key test (Phase 1)

---

## Issues discovered

None during Phase 3 itself. The 7 pre-existing `email_to_system_id` failures in `test_notifications_router.py` are documented in `90-phase1-execution-log.md` as separate-refactor scope and not addressed here.

---

## Open follow-ups for the user

1. **Schedule the :8000 sweep** — E2E UI parity test (`test_history_card_parity.py`, 7 cases), visual regression, integration final gate. All three need user-confirmed `scheduled_at` slots via `/api/test-suite/submit`.
2. **Decide on Option B (full `renderHistoryCard` deletion)** — current Option A retains the function as a 10-line splicer. Option B inlines history actions into `renderJobCard` and deletes the wrapper. UX-touching call.
3. **Filing follow-ups** — update `bug-fix-queue.md` item #4 to split out the 7 `email_to_system_id` test refactors as a separate queued item (per `90-phase1-execution-log.md` Issues Discovered).
4. **CoSA-side commits** — list above.
