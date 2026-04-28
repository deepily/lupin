# 06 — Testing Strategy

**Phases**: 1, 2, 3
**Files**: `src/cosa/tests/unit/rest/`, `src/tests/integration/`, `src/tests/e2e_ui/`

---

## 1. Pyramid layout

| Tier | Venue | When | Who runs |
|---|---|---|---|
| Unit (CoSA) | :7999 / process-local | After every CoSA-side edit | AI |
| Unit (Lupin) | :7999 / process-local | After every Lupin-side edit | AI |
| Smoke (inline `quick_smoke_test()`) | :7999 / process-local | After module-level edits | AI |
| WebSocket smoke | :7999 | End of Phase 2 | AI |
| Integration | :8000 scheduled | End of Phase 1 + final pyramid in Phase 3 | AI runs (user confirms slot) |
| E2E UI parity | :8000 scheduled | End of Phase 2 + Phase 3 | AI runs (user confirms slot) |
| Visual regression | :8000 scheduled | End of Phase 3 | AI runs (user confirms slot) |

Per CLAUDE.md TESTING VENUES rubric: `:7999` is AI-discretionary for non-destructive, fast (<2 min), no-monopoly tests; `:8000` is monopolize-mode and submitted via `POST /api/test-suite/submit` with a user-confirmed `scheduled_at` slot.

---

## 2. Phase 1 tests (Backend A1 + C)

### 2.1 Unit (CoSA) — `src/cosa/tests/unit/rest/test_job_persistence.py`

Existing file gets new test class `TestQueryJobHistoryShapeNormalization`:

| Test | Assertion |
|---|---|
| `test_query_job_history_unpacks_metadata_to_top_level` | Row with full `metadata_json` → response has `report_path`, `abstract`, `cost_summary`, `scheduled_at`, `monopolize`, `response_text` at top level |
| `test_query_job_history_handles_missing_metadata_json` | `metadata_json = None` → all metadata-derived fields default to `None` / `False`, no `KeyError` |
| `test_query_job_history_handles_partial_metadata_json` | `metadata_json` with only some keys → others default; present keys preserved |
| `test_query_job_history_aligns_report_path_naming` | Row with `metadata_json.report_link` (legacy) → `report_path` at top level (not `report_link`) |
| `test_query_job_history_paused_is_false_for_terminal` | All history rows return `paused: False` regardless of historical state |
| `test_query_job_history_retains_metadata_json` | Top-level fields unpacked AND `metadata_json` still in response (backwards compat) |
| `test_query_job_history_includes_has_interactions` | Each row has `has_interactions: bool` from the bulk count |

### 2.2 Unit (CoSA) — `src/cosa/tests/unit/rest/test_notification_repository.py`

Existing file gets new test class `TestCountByJobIds`:

| Test | Assertion |
|---|---|
| `test_count_by_job_ids_returns_correct_counts` | 3 job_ids with 0/2/5 notifications → exact counts in result dict |
| `test_count_by_job_ids_empty_input` | `[]` input → `{}` output, **zero DB queries** (use sqlalchemy event listener to verify) |
| `test_count_by_job_ids_no_matches` | All-unknown job_ids → all-zero counts populated |
| `test_count_by_job_ids_excludes_hidden` | `is_hidden = True` rows not counted |
| `test_count_by_job_ids_idempotent` | Calling twice with same input returns same result |

### 2.3 Integration — `src/tests/integration/test_job_history_shape_parity.py` (NEW)

Submitted on :8000. Validates the cross-endpoint contract:

| Test | Assertion |
|---|---|
| `test_done_and_history_share_field_set_for_same_job` | Submit dry-run agentic, await done → `/api/get-queue/done` and `/api/job-history` for same `job_id` return matching `set(keys)` for these 16 fields: `job_id`, `question_text`, `response_text`, `agent_type`, `has_interactions`, `is_cache_hit`, `report_path`, `abstract`, `cost_summary`, `scheduled_at`, `monopolize`, `paused`, `started_at`, `completed_at`, `duration_seconds`, `status` |
| `test_has_interactions_accuracy_done` | Job with N>0 notifications → `has_interactions: true` on done endpoint |
| `test_has_interactions_accuracy_history` | Same job after history rotation → `has_interactions: true` on history endpoint |
| `test_has_interactions_false_for_zero_notifications` | Job with no notifications → `has_interactions: false` on both endpoints |
| `test_history_metadata_json_retained` | `/api/job-history` response still includes `metadata_json` (backwards compat) |

### 2.4 Inline smoke

Run `python -c "from cosa.rest.db.repositories.notification_repository import NotificationRepository; print('OK')"` after the new method lands — verifies the import chain.

### 2.5 Pre-existing test repair

Per Phase 1 risk register entry: 8 cosmetic `test_notifications_router` failures (config key drift `app_timezone` ↔ `app timezone`). Fix in same phase to avoid leaving 8 known-red tests. Pure test-file edits, no production code change.

### 2.6 Verification commands (Phase 1)

```bash
# AI-discretionary (:7999):
pytest src/cosa/tests/unit/rest/test_job_persistence.py -v
pytest src/cosa/tests/unit/rest/test_notification_repository.py -v
pytest src/cosa/tests/unit/rest/test_notifications_router.py -v   # 8 repaired tests

# Scheduled on :8000 (user confirms slot via /api/test-suite/submit):
src/tests/integration/test_job_history_shape_parity.py
```

---

## 3. Phase 2 tests (Frontend B)

### 3.1 New E2E parity — `src/tests/e2e_ui/test_history_card_parity.py` (NEW)

Playwright Chromium against :8000. Validates the user-visible behavior:

| Test | Assertion |
|---|---|
| `test_history_card_shows_interaction_indicator_when_notifications_exist` | After job with notifications lands in history → 💬 indicator present in card |
| `test_history_card_clicking_interactions_loads_transcript` | Click 💬 → `/api/get-job-interactions/{job_id}` fires, transcript renders |
| `test_history_card_delete_uses_history_endpoint` | Click 🗑 on history card → `DELETE /api/job-history/{id}` fires (NOT `/api/queue/...`) |
| `test_done_card_delete_uses_queue_endpoint` | Click 🗑 on done card → `DELETE /api/queue/done/{id}` fires (parity) |
| `test_dom_id_namespacing_no_collision` | Job appears in both done (live) and history (after refresh) → both DOM ids exist (`done-${jobId}` and `history-${jobId}`) without collision |
| `test_history_card_renders_all_badges` | Scheduled badge 🕐, monopolize 🔒, completion ✓, cache hit (when applicable) all present |
| `test_history_card_renders_abstract_and_report_link` | `abstract` field renders as quoted block; `report_path` renders as clickable link |

### 3.2 Visual regression — extend `src/tests/e2e_ui/__snapshots__/`

| Test | Assertion |
|---|---|
| `test_history_card_visual_matches_done_card` | Side-by-side snapshot: same terminal job rendered in done bucket vs history bucket → near-identical pixels (allow ≤2% difference for timestamps and bucket-specific button) |

### 3.3 WebSocket smoke

Run `./src/scripts/run-websocket-smoke-tests.sh` on :7999. Should remain 100% green — Phase 2 doesn't touch WebSocket pathways but the queue-event handlers DO call `renderJobCard()`, so this is regression coverage.

### 3.4 Manual grep audit (post-edit, before declaring Phase 2 complete)

```bash
# Zero matches expected:
grep -n '_isHistory'                      src/fastapi_app/static/js/notifications.js
grep -nE 'has_interactions\\s*:\\s*false' src/fastapi_app/static/js/notifications.js

# Should return ONE match (the new dispatcher):
grep -n '_dispatchDelete'                 src/fastapi_app/static/js/notifications.js

# DOM-id selectors that need namespace migration (manual review of each):
grep -nE "getElementById\\(\\s*['\"]?\\\$?\\{?jobId" src/fastapi_app/static/js/notifications.js
```

### 3.5 Verification commands (Phase 2)

```bash
# AI-discretionary (:7999):
src/scripts/run-websocket-smoke-tests.sh

# Scheduled on :8000 (user confirms slot):
src/tests/e2e_ui/test_history_card_parity.py
src/tests/e2e_ui/test_history_card_visual.py     # visual regression
```

---

## 4. Phase 3 tests (Adapter collapse + final pyramid)

### 4.1 Final grep audit (gates)

All three MUST return zero matches:
```bash
grep -n '_isHistory'                              src/fastapi_app/static/js/notifications.js
grep -n 'renderHistoryCard'                       src/fastapi_app/static/js/notifications.js
grep -nE 'has_interactions\\s*:\\s*false'         src/fastapi_app/static/js/notifications.js
```

### 4.2 Full pyramid sweep

Per CLAUDE.md PR MERGE REQUIREMENTS:

| Tier | Venue | Command | Required |
|---|---|---|---|
| Unit (Lupin + CoSA) | :7999 | `pytest src/tests/unit/ src/cosa/tests/unit/ -v` | 100% pass |
| WebSocket smoke | :7999 | `./src/scripts/run-websocket-smoke-tests.sh` | 100% pass |
| E2E UI | :8000 scheduled | `./src/scripts/run-e2e-ui-tests.sh --bg -v` | 100% pass |
| Visual regression | :8000 scheduled | `./src/scripts/run-e2e-ui-tests.sh --bg -v -k visual` | 100% pass |
| Integration (FINAL GATE) | :8000 scheduled | `./src/tests/run-integration-tests.sh --bg -v` | 100% pass |

### 4.3 Manual end-to-end verification (per `dazzling-napping-frost.md` §Verification)

The 8-step checklist:
1. Submit dry-run agentic on :7999, wait for done.
2. Verify done card renders all sections + 💬 if notifications.
3. Verify same job in history pane renders identically.
4. Click 💬 on history → transcript loads.
5. Click delete on history → `DELETE /api/job-history/{id}` fires.
6. Verify `/api/job-history` response has flat shape (DevTools Network tab).
7. `grep -rn '_isHistory' src/fastapi_app/static/` → zero matches.
8. Full pyramid green.

---

## 5. Test ownership protocol

Per CLAUDE.md TEST OWNERSHIP MANDATE — the user is NEVER a tester. The AI:
- Writes every test in this strategy doc
- Runs every :7999-eligible test
- Writes (but does NOT submit) :8000 tests; submission requires user-confirmed slot
- Reports results in tabular pass/fail form
- Auto-queues any discovered bugs to `bug-fix-queue.md`
