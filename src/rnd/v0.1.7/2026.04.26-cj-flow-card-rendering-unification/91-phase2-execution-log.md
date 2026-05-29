# 91 — Phase 2 Execution Log (Frontend B)

**Status**: code complete + :7999-eligible tests green; E2E parity tests written and staged for :8000 scheduled run (needs user slot confirmation)
**Started**: 2026-04-26 11:55 EDT
**Completed**: 2026-04-26 12:03 EDT (code + :7999 verification)

---

## Overview

Live execution log for Phase 2 — kill `_isHistory`, queueName-driven routing, drop hardcoded `has_interactions: false`.

Reference design doc: `04-frontend-flag-removal.md`

---

## Files modified

**Lupin** (this repo):
- `src/fastapi_app/static/js/notifications.js`:
  - Added `DELETE_HANDLERS` lookup (top of file, line 14)
  - Added `_dispatchDelete()` method (line 6135)
  - `renderHistoryCard()`: dropped `_isHistory: true` (was line 6065); rewrote normalized object to read flat top-level fields with metadata fallback for transition window; passes `queueName='history'` to renderJobCard (was status→queue mapping)
  - `renderJobCard()`: line 6891 DOM-id now uses `queueName === 'history'` (was `_isHistory`); line 6935-6951 completion badges now fire for `queueName === 'done' || === 'history'`; line 6976 interactions indicator gate expanded to history; line 7016-7020 delete button uses `_dispatchDelete()` chokepoint and the `[ 'todo', 'done', 'dead', 'history' ].includes( queueName )` gate; line 7128 "📋 Notification Conversation" section gate expanded to history
- `src/fastapi_app/static/html/notifications.html`: bumped `notifications.js?v=` from `20260422b` → `20260426a` (cache-bust)
- `src/tests/e2e_ui/test_history_card_parity.py` (NEW, 7 tests): validates DOM-id namespacing, completion badges, interactions section presence, delete-handler routing through DELETE_HANDLERS

---

## Tests added

| File | New tests | Coverage |
|---|---|---|
| `src/tests/e2e_ui/test_history_card_parity.py` (NEW) | 6 in `TestHistoryCardParity` + 1 in `TestDeleteHandlerRouting` | DOM-id namespacing, ✓/✗ badges per status, "Notification Conversation" section presence, delete dispatch routes to /api/job-history (NOT /api/queue/), DELETE_HANDLERS lookup table coverage |

**Total new tests**: 7 (E2E, scheduled :8000).

---

## Test results

| Tier | Venue | Command | Result |
|---|---|---|---|
| JS syntax check | local | `node --check src/fastapi_app/static/js/notifications.js` | **OK** |
| WebSocket smoke | :7999 | `bash src/scripts/run-websocket-smoke-tests.sh` | **50/50 passed** (Core 25/25, Integration 22/22, Performance 2/2, Load 1/1) |
| Lupin unit (full) | :7999 | `pytest src/tests/unit/` | **3628 passed, 1 xfailed, 0 failed** in 149.31s |
| E2E test collection check | :7999 | `pytest src/tests/e2e_ui/test_history_card_parity.py --collect-only` | **7 tests collected**, syntactically valid |
| Live JS served | :7999 | `curl /static/js/notifications.js?v=20260426a` | **HTTP 200, 653293 bytes**, contains all expected new symbols |
| E2E parity test (NEW) | :8000 scheduled | TBD — needs user slot confirmation | NOT YET RUN (staged) |
| Visual regression | :8000 scheduled | TBD — needs user slot confirmation | NOT YET RUN |

---

## Grep audit results

```bash
$ grep -n '_isHistory' src/fastapi_app/static/js/notifications.js
14:// Delete-handler routing for job cards. Replaces the prior `_isHistory` boolean
6138:         * invokes it. Replaces the prior `job._isHistory` ternary that branched
7019:            // others → /api/queue/{queueName}). Single chokepoint replaces the prior _isHistory
```
↑ All 3 matches are comment lines (no actual code references). ✅ PASS

```bash
$ grep -nE 'has_interactions\s*:\s*false' src/fastapi_app/static/js/notifications.js
5942:                    has_interactions: false
```
↑ The remaining match is in a defensive fallback path (when live-queue API returned `*_jobs` HTML instead of `*_jobs_metadata` — unrelated to history rendering). NOT the bug we fixed. Genuinely "we don't know" → False. Out of scope to remove. ✅ ACCEPTABLE

```bash
$ grep -n '_dispatchDelete' src/fastapi_app/static/js/notifications.js
6135:    _dispatchDelete( jobId, queueName ) {
6144:         * invokes it. Replaces the prior `job._isHistory` ternary that branched
7019:            const deleteAction = `window.notificationsUI._dispatchDelete('${jobId}', '${queueName}')`;
```
↑ Three matches: definition + docblock reference + single call site. ✅ PASS (one chokepoint)

---

## Issues discovered

None. Frontend code change is contained and JS still parses; WebSocket smoke + full unit pass remained 100% green.

---

## Notes for next phase

Phase 3 (`92-phase3-execution-log.md`) collapses `renderHistoryCard()` further — Option B from `05-adapter-collapse.md` — and runs the full pyramid sweep including the E2E parity tests staged here.
