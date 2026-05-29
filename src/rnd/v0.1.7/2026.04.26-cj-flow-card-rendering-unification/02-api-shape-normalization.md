# 02 — API Shape Normalization (A1, Backend)

**Phase**: 1
**Files**:
- `src/cosa/rest/job_persistence.py` (`query_job_history()` at lines 567-643)
- `src/cosa/rest/routers/queues.py` (`/api/job-history` route handler around lines 1282-1334)

---

## 1. Goal

Make `/api/job-history` return the same flat shape as `/api/get-queue/done`. After this phase, the frontend can consume both endpoints' responses with the same code paths — no adapter required.

---

## 2. Reference shape (`/api/get-queue/done`)

Source: `src/cosa/rest/routers/queues.py:458-515` (per forensic investigation 2026-04-26).

```python
{
  "done_jobs_metadata": [
    {
      "job_id"                    : str,   # job.id_hash
      "question_text"             : str,   # job.last_question_asked
      "response_text"             : str,   # job.answer_conversational or job.answer
      "timestamp"                 : str,   # ISO; job.run_date or job.created_date
      "user_id"                   : str,   # filtered authorization scope
      "user_email"                : str,
      "session_id"                : str,
      "agent_type"                : str,   # job.job_type
      "has_interactions"          : bool,  # CURRENTLY: bool(job.session_id) — proxy
      "has_audio_cache"           : bool,
      "is_cache_hit"              : bool,
      "report_path"               : str | None,
      "remediation_snapshot_path" : str | None,
      "yaml_path"                 : str | None,
      "pptx_path"                 : str | None,
      "abstract"                  : str | None,
      "cost_summary"              : dict | None,
      "started_at"                : str | None,   # ISO
      "completed_at"              : str | None,   # ISO
      "duration_seconds"          : float | None,
      "status"                    : str,   # job.state.value
      "error"                     : str | None,
      "scheduled_at"              : str | None,
      "monopolize"                : bool,
      "paused"                    : bool   # job.state == JobState.PAUSED
    },
    ...
  ],
  "filtered_by"  : str,
  "is_admin_view": bool,
  "total_jobs"   : int
}
```

---

## 3. Current shape (`/api/job-history`)

Source: `src/cosa/rest/job_persistence.py:618-637`.

```python
{
  "jobs": [
    {
      "id_hash"          : str,
      "job_type"         : str,
      "user_id"          : str,
      "user_email"       : str,
      "session_id"       : str,
      "routing_command"  : str,
      "status"           : str,
      "question_text"    : str,
      "error"            : str | None,
      "is_cache_hit"     : bool,
      "duration_seconds" : float | None,
      "created_at"       : str,   # ISO
      "started_at"       : str | None,
      "completed_at"     : str | None,
      "updated_at"       : str,
      "metadata_json"    : dict   # <-- everything rich lives here
    },
    ...
  ]
}
```

Rich fields nested in `metadata_json`:
- `response_text` (sometimes `answer_conversational`)
- `abstract`, `report_link` (note: `_link` not `_path`), `report_path` (newer rows), `cost_summary`, `artifacts`
- `yaml_path`, `pptx_path`, `remediation_snapshot_path`
- `scheduled_at`, `monopolize`, `checkpoint`, `original_args`, `stack_trace`

---

## 4. Field-by-field unpack table

| Top-level field (after change) | Done queue source | History source (after change) | Default if missing |
|---|---|---|---|
| `job_id` | `job.id_hash` | `row.id_hash` | required |
| `question_text` | `job.last_question_asked` | `row.question_text` | `""` |
| `response_text` | `job.answer_conversational or job.answer` | `metadata_json.get("response_text") or metadata_json.get("answer_conversational")` | `None` |
| `timestamp` | `job.run_date or job.created_date` | `row.completed_at or row.created_at` | required |
| `user_id` | filter scope | `row.user_id` | required |
| `user_email` | `job.user_email` | `row.user_email` | `None` |
| `session_id` | `job.session_id` | `row.session_id` | `None` |
| `agent_type` | `job.job_type` | `row.job_type` | `"unknown"` |
| `has_interactions` | (currently proxy) → see doc 03 | (NEW) bulk count query → see doc 03 | `False` |
| `has_audio_cache` | `False` (always today) | `False` (history is terminal) | `False` |
| `is_cache_hit` | `job.is_cache_hit` | `row.is_cache_hit` | `False` |
| `report_path` | `job.artifacts.get("report_path")` | `metadata_json.get("report_path") or metadata_json.get("report_link")` | `None` |
| `remediation_snapshot_path` | `job.artifacts.get(...)` | `metadata_json.get("remediation_snapshot_path")` | `None` |
| `yaml_path` | `job.artifacts.get(...)` | `metadata_json.get("yaml_path")` | `None` |
| `pptx_path` | `job.artifacts.get(...)` | `metadata_json.get("pptx_path")` | `None` |
| `abstract` | `job.artifacts.get("abstract")` | `metadata_json.get("abstract")` | `None` |
| `cost_summary` | `job.cost_summary` | `metadata_json.get("cost_summary")` | `None` |
| `started_at` | `job.started_at` | `row.started_at` (ISO) | `None` |
| `completed_at` | `job.completed_at` | `row.completed_at` (ISO) | `None` |
| `duration_seconds` | computed from started/completed | `row.duration_seconds` | `None` |
| `status` | `job.state.value` | `row.status` | required |
| `error` | `job.error` | `row.error` | `None` |
| `scheduled_at` | `getattr(job, "scheduled_at", None)` | `metadata_json.get("scheduled_at")` | `None` |
| `monopolize` | `getattr(job, "monopolize", False)` | `metadata_json.get("monopolize", False)` | `False` |
| `paused` | `job.state == JobState.PAUSED` | always `False` (history is terminal) | `False` |

---

## 5. Naming alignment: `report_link` → `report_path`

The `metadata_json.report_link` field on older history rows is the path to a report artifact. The done queue uses `report_path` as the canonical name. This plan surfaces the field as `report_path` at the top level for both endpoints.

**Read order in unpacker** (handles both old and new rows):
```python
report_path = metadata_json.get("report_path") or metadata_json.get("report_link")
```

`metadata_json.report_link` is **not removed** from the underlying JSONB column. It just isn't surfaced to the top level. Any external code that still reads `metadata_json["report_link"]` continues to work.

---

## 6. Fallback rules for older / partial rows

`metadata_json` is JSONB and can be `None`, `{}`, or partially populated. The unpacker MUST be defensive:

```python
def _unpack_metadata( row ):
    md = row.metadata_json or {}
    return {
        "response_text"             : md.get( "response_text" ) or md.get( "answer_conversational" ),
        "abstract"                  : md.get( "abstract" ),
        "report_path"               : md.get( "report_path" ) or md.get( "report_link" ),
        "remediation_snapshot_path" : md.get( "remediation_snapshot_path" ),
        "yaml_path"                 : md.get( "yaml_path" ),
        "pptx_path"                 : md.get( "pptx_path" ),
        "cost_summary"              : md.get( "cost_summary" ),
        "scheduled_at"              : md.get( "scheduled_at" ),
        "monopolize"                : bool( md.get( "monopolize", False ) )
    }
```

**Invariants**:
- All callers of `query_job_history()` get a flat dict with every key present (`None` / `False` defaults if missing). No `KeyError` at the rendering layer.
- `metadata_json` is **retained** in the response (preserves backward compat for anything that still reads from it).

---

## 7. Backward compatibility (additive change)

**The change is additive at the response level**:
- Adds top-level keys that didn't exist before
- Removes nothing
- `metadata_json` remains in the response unchanged

External consumers (if any beyond Lupin's frontend) see new fields they didn't know about and ignore them. Their existing reads from `metadata_json` continue to work.

This means **Phase 1 ships independently of Phase 2** — no rollback risk, no coordinated deploy.

---

## 8. Implementation pointers

### `query_job_history()` change (`src/cosa/rest/job_persistence.py:618-637`)

Currently:
```python
return [{
    "id_hash"         : row.id_hash,
    "job_type"        : row.job_type,
    ...
    "metadata_json"   : row.metadata_json,
    ...
} for row in rows]
```

Becomes:
```python
return [_build_history_row( row, has_interactions_map ) for row in rows]
```

Where `_build_history_row()` is a new helper that:
1. Maps `id_hash → job_id` (and other column-name renames for parity)
2. Calls `_unpack_metadata( row )` to flatten metadata_json fields to top level
3. Adds `has_interactions` from the bulk-count map (see `03-has-interactions-accuracy.md`)
4. Adds `paused: False` (history is terminal)
5. **Keeps** `metadata_json` in the response for backward compatibility

### `/api/job-history` route handler (`src/cosa/rest/routers/queues.py:1282-1334`)

Build `has_interactions_map` ONCE per request (single `count_by_job_ids` call) and pass it through to `query_job_history()` (or call sites can pass already-extracted job_ids and merge).

### `/api/get-queue/done` route handler (`src/cosa/rest/routers/queues.py:458-515`)

Replace `"has_interactions": bool( job.session_id )` with the bulk-count lookup. Same `count_by_job_ids` helper used here as on history side.

---

## 9. Test scope (Phase 1)

See `06-testing-strategy.md` §Phase 1 for full breakdown. Key cases this doc drives:

- `test_query_job_history_unpacks_metadata_to_top_level` — full row → all top-level fields populated
- `test_query_job_history_handles_missing_metadata_json` — `metadata_json = None` → top-level fields default to `None`/`False`
- `test_query_job_history_handles_partial_metadata_json` — only some keys present → others default
- `test_query_job_history_aligns_report_path_naming` — `report_link`-only row surfaces as `report_path`
- `test_query_job_history_paused_is_false_for_terminal` — always `paused: False`
- Integration: `test_job_history_shape_parity` — `/api/get-queue/done` and `/api/job-history` return matching keys for same job
