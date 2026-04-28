# 03 — `has_interactions` Accuracy (C, Backend)

**Phase**: 1
**Files**:
- `src/cosa/rest/db/repositories/notification_repository.py` (add `count_by_job_ids()`)
- `src/cosa/rest/routers/queues.py` (`/api/get-queue/done` call site, ~line 477)
- `src/cosa/rest/job_persistence.py` (`query_job_history()` call site)

---

## 1. The current proxy (and why it's wrong)

`/api/get-queue/done` at `src/cosa/rest/routers/queues.py:477` uses:

```python
"has_interactions": bool( job.session_id )
```

This says "this job has interactions if it has a session_id." Two failure modes:

1. **False positives**: Many jobs are launched with a session_id (any agentic job touched by the AI) but generate zero notifications. Their cards show 💬 but the lazy-load returns an empty array.
2. **False negatives** (history-side): `renderHistoryCard()` hardcodes `has_interactions: false` regardless of session_id, so even jobs with rich notification transcripts get no indicator. This is the user-visible bug.

The accurate signal is "does the `notifications` table have any rows for this `job_id`?" That's a count query.

---

## 2. The accurate signal

```sql
SELECT job_id, COUNT(*) AS n
FROM notifications
WHERE job_id IN (:job_ids)
  AND is_hidden = FALSE
GROUP BY job_id;
```

- `notifications.job_id` is **indexed** (verified from forensic investigation 2026-04-26 of the schema)
- `is_hidden = FALSE` excludes soft-deleted rows from the count (consistent with how the lazy-load endpoint behaves)
- Single batched query for the whole page — N=1 round-trip regardless of page size

---

## 3. Repository helper

Add to `src/cosa/rest/db/repositories/notification_repository.py`:

```python
def count_by_job_ids( self, job_ids: list[str] ) -> dict[str, int]:
    """
    Bulk count of non-hidden notifications grouped by job_id.

    Requires:
        - job_ids is a list of UUID-shaped strings (may be empty)

    Ensures:
        - returns dict mapping each input job_id to its non-hidden notification count
        - job_ids with zero notifications are present in the dict with value 0
        - empty input returns an empty dict (no DB call)

    Raises:
        - SQLAlchemyError on database failure (caller's responsibility to handle)
    """
    if not job_ids:
        return {}

    rows = (
        self.db
            .query( Notification.job_id, func.count( Notification.id ) )
            .filter( Notification.job_id.in_( job_ids ) )
            .filter( Notification.is_hidden.is_( False ) )
            .group_by( Notification.job_id )
            .all()
    )
    counts = { job_id: int( n ) for job_id, n in rows }
    # Ensure every input job_id is in the result, even with zero count
    return { job_id: counts.get( job_id, 0 ) for job_id in job_ids }
```

**Design notes**:
- Returns `dict[job_id → count]` not just a list of "has any" booleans — this lets us optionally surface `interaction_count` later without re-querying. (Surfacing the count is out of scope for THIS plan; structure supports it.)
- Empty-input shortcut avoids a no-op query and a possible `WHERE id IN ()` SQL error on some dialects.
- `int()` cast normalizes whatever the dialect returns (Postgres can return Decimal for COUNT depending on driver settings).

---

## 4. Call sites

### `/api/get-queue/done` (`queues.py` ~line 458-515)

Today (line 477):
```python
"has_interactions": bool( job.session_id )
```

After change:
```python
# Build map ONCE for all jobs in this response
job_ids       = [ j.id_hash for j in done_jobs ]
notif_counts  = notification_repository.count_by_job_ids( job_ids )

# Per-job in the comprehension:
"has_interactions": notif_counts.get( job.id_hash, 0 ) > 0
```

### `query_job_history()` (`job_persistence.py:567-643`)

Today: no `has_interactions` field in the response.

After change:
```python
# After fetching rows:
job_ids       = [ row.id_hash for row in rows ]
notif_counts  = notification_repository.count_by_job_ids( job_ids )

# In _build_history_row():
"has_interactions": notif_counts.get( row.id_hash, 0 ) > 0
```

The `notif_counts` dict is computed once per page and passed (or accessed via the same DB session) to the row-building loop.

---

## 5. Performance

| Page size | Existing per-row queries | New batched query | Improvement |
|---|---|---|---|
| 50 jobs | (proxy — no query, but inaccurate) | 1 indexed range scan | n/a (correctness gain, not perf) |
| 200 jobs | (proxy) | 1 indexed range scan | n/a |
| 1000 jobs | (proxy) | 1 indexed range scan | sub-100ms expected |

Expected p99 ≤50ms for typical history page (≤200 rows) given the indexed `job_id` column. This is a single round-trip, not a per-row N+1.

---

## 6. Edge cases

- **`job.id_hash` mismatch with `notifications.job_id` shape**: Investigation showed `Notification.job_id` is `String(256)` and stores the same identifier the agentic job emits. BFE/TFE use compound IDs like `bfe-abc::uuid`. The notifications table stores them verbatim. Counts work correctly because both sides use the same string.
- **Jobs older than the persistence layer** (pre-existing rows from before notifications-table existed): `count_by_job_ids` returns 0 for those, `has_interactions: false` correctly.
- **Soft-deleted notifications**: filtered out via `is_hidden = FALSE`, consistent with what `/api/get-job-interactions/{job_id}` does (or should — verify in Phase 1 code reading; if the lazy-load endpoint includes hidden rows, count must include them too for parity).
- **Empty job_ids list** (page returns zero jobs): early return `{}`, no query.

---

## 7. Frontend implication

Both endpoints now return `has_interactions: bool` at the top level. The frontend reads this field unconditionally — no fallback to `bool(session_id)`, no hardcoded `false` for history. See `04-frontend-flag-removal.md` for the consuming-side change.

---

## 8. Test scope (Phase 1)

- `test_count_by_job_ids_returns_correct_counts` — N job_ids → exact counts
- `test_count_by_job_ids_empty_input` — `[]` → `{}`, zero queries
- `test_count_by_job_ids_no_matches` — all-zero counts populated for non-matching ids
- `test_count_by_job_ids_excludes_hidden` — `is_hidden = TRUE` rows not counted
- Integration: `/api/get-queue/done` and `/api/job-history` both return `has_interactions: bool` matching ground truth (push job, observe notification activity, check the field)
