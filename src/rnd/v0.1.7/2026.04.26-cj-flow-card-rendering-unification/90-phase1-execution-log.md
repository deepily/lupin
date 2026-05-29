# 90 — Phase 1 Execution Log (Backend A1 + C)

**Status**: complete (code + unit tests + live :7999 probe; integration test pending — needs scheduled :8000 slot)
**Started**: 2026-04-26 11:38 EDT
**Completed**: 2026-04-26 11:54 EDT (code + unit tests)

---

## Overview

Live execution log for Phase 1 work — flatten `/api/job-history` response shape and wire accurate `has_interactions` via bulk count query. Per BFE pattern, this file is appended-to during implementation, not pre-filled.

Reference design docs:
- `01-design-overview.md` — overall architecture
- `02-api-shape-normalization.md` — A1 field-by-field unpack
- `03-has-interactions-accuracy.md` — C count-query design

---

## Files modified

**Lupin** (this repo):
- `src/tests/unit/test_job_persistence.py` — added 3 new test classes (`TestUnpackMetadataJson`, `TestBuildHistoryRow`, `TestCountNotificationsForJobs`) — 20 new tests, all green
- `src/tests/unit/test_notification_repository_count.py` — NEW file, 5 tests for `count_by_job_ids()`

**CoSA** (user commits separately from CoSA context):
- `src/cosa/rest/db/repositories/notification_repository.py` — added `count_by_job_ids(job_ids: list[str]) -> dict[str, int]` bulk-count helper (~37 lines)
- `src/cosa/rest/job_persistence.py` — added `_count_notifications_for_jobs()`, `_unpack_metadata_json()`, `_build_history_row()` helpers (~110 lines); rewrote `query_job_history()` row builder to call them (~13 lines changed)
- `src/cosa/rest/routers/queues.py` — added `_count_interactions_for_jobs()` helper (~31 lines); replaced `bool(job.session_id)` proxy with bulk-count lookup at done-bucket handler line 477 and dead-bucket handler line 540
- `src/cosa/tests/unit/rest/test_notifications_router.py` — fixed 1 test (`test_get_local_timestamp_success`): `app_timezone` → `app timezone` config-key string

---

## Tests added

| File | New tests | Coverage |
|---|---|---|
| `src/tests/unit/test_job_persistence.py` | 9 in `TestUnpackMetadataJson` | metadata_json flatten + report_link↔report_path naming + response_text fallback + monopolize bool coercion |
| `src/tests/unit/test_job_persistence.py` | 7 in `TestBuildHistoryRow` | top-level shape parity, has_interactions passthrough, paused-always-false, metadata_json retention, timestamp fallback |
| `src/tests/unit/test_job_persistence.py` | 4 in `TestCountNotificationsForJobs` | empty input no-query, zero defaults, actual count rendering, DB error fallback |
| `src/tests/unit/test_notification_repository_count.py` (NEW) | 5 in `TestCountByJobIds` | repo-level: empty input, unknown ids, real counts, int normalization, idempotency |

**Total new tests**: 25.

---

## Test results

| Tier | Venue | Command | Result |
|---|---|---|---|
| Unit (Lupin) — job persistence | :7999 process-local | `pytest src/tests/unit/test_job_persistence.py -v` | **43 passed** (23 baseline + 20 new) |
| Unit (Lupin) — notif repo | :7999 process-local | `pytest src/tests/unit/test_notification_repository_count.py -v` | **5 passed** (5/5 new) |
| Unit (CoSA) — timezone fix | :7999 process-local | `pytest src/cosa/tests/unit/rest/test_notifications_router.py::TestNotificationsRouter::test_get_local_timestamp_success` | **1 passed** (was failing before this phase) |
| Live shape probe — `/api/job-history` | :7999 server | Python urllib request | **31 top-level keys, 10/10 rows have all 19 expected shared fields** |
| Live `has_interactions` accuracy | :7999 server | Python urllib request | **8/10 rows True, 2/10 False — real count from notifications table** (proxy used to mark all True) |
| Integration `test_job_history_shape_parity` (NEW) | :8000 scheduled | TBD — needs user slot confirmation | NOT YET RUN |

The live probe confirms the new flat shape AND the accurate `has_interactions` count. Two rows showing `False` validates that the previous proxy (`bool(session_id)`) gave false positives — those rows had session_ids but zero notifications.

---

## Diff verification

```bash
# Confirms the helpers exist and import cleanly:
$ python -c "from cosa.rest.job_persistence import _count_notifications_for_jobs, _unpack_metadata_json, _build_history_row, query_job_history; print('OK')"
OK
$ python -c "from cosa.rest.routers.queues import _count_interactions_for_jobs; print('OK')"
OK

# Confirms `bool( job.session_id )` proxy is gone from queues.py done- and dead-handlers:
$ grep -n 'bool( job.session_id )' src/cosa/rest/routers/queues.py
(no matches)
```

---

## Issues discovered

### 2026-04-26 — Pre-existing pytest module-state pollution (note for future reference)

When running `src/tests/unit/` and `src/cosa/tests/unit/rest/test_notifications_router.py::TestNotificationsRouter::test_get_local_timestamp_success` together in one pytest invocation, the timezone test fails — even though it passes in isolation and even when paired with just `test_job_persistence.py`. Some other test file under `src/tests/unit/` is polluting `cosa.rest.routers.notifications` module state in a way that breaks the timezone test's mocks. This is **pre-existing test-ordering pollution**, not introduced by my fix. The fix itself is correct (verified by isolated run + pair-with-job-persistence run, both 100% green).

When the user runs the integration / E2E sweep on :8000, this won't surface because those suites don't load the polluting module. The pollution only matters if you run cross-package pytest invocations like `pytest src/tests/ src/cosa/tests/`.

### 2026-04-26 — Pre-existing test failures in `test_notifications_router.py` deeper than bug-fix-queue.md item #4 stated

bug-fix-queue.md item #4 described 8 failing tests as cosmetic config-key drift (`app_timezone` ↔ `app timezone`). Actual baseline run (PYTHONPATH=src pytest src/cosa/tests/unit/rest/test_notifications_router.py -v) shows:

- **1 failure** is the simple config-key drift (`test_get_local_timestamp_success` expects `"app_timezone"`; production at `notifications.py:112,147,176,1444,1644,1769,1850` uses `"app timezone"`). FIXED in this phase — see Files Modified.
- **7 failures** are NOT config-key drift. They're deeper test-drift after a refactor: tests patch `cosa.rest.routers.notifications.email_to_system_id` (returning a UUID), but production code now imports `get_user_by_email` from `cosa.rest.user_service` and reads `user_data["id"]` for the system ID. Different mock target, different return shape. Updating these tests is genuinely a separate refactor and out of scope for A1+C.

**Action**: Fix the 1 simple test in this phase. Update bug-fix-queue.md item #4 at end of Phase 1 to reflect the accurate diagnosis and split the 7-test refactor into its own queued item.

---

## Diff verification

(populate during execution; explicit `grep` results showing the change landed and didn't leave stale references)
