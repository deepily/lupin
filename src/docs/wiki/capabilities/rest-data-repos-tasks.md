---
capability: rest-data-repos-tasks
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.db.repositories.task_repository.TaskRepository@b07947b8e5
  - cosa.rest.db.repositories.approval_setting_repository.ApprovalSettingRepository@8a1babb9aa
---
# Task store repositories

`TaskRepository` is the storage layer of the task store: rows, the append-only event trail and every query over them. `ApprovalSettingRepository` holds the key and value settings of the promotion gate. The rules about who may do what live in the router and in `task_store_rules`; see [[task-store]] and [[task-promotion-gate]].

## What it does
- `create_item` adds a row and its `->{status}` creation event. `apply_transition` sets the status and appends the `from->to` event, with a second `request_withdrawn` event when a pending request no longer fits.
- Neither checks that the move is legal. Both force `blocked_by` to empty for any status but `blocked`, and record what was dropped in the event reason.
- `apply_patch`, `apply_amendment`, `apply_correlation`, `apply_chase`, `apply_request_filing` and `apply_request_verdict` each change one family of fields and append one event. A patch that changes nothing still writes a no-op event.
- `get_by_id_for_update` loads a row with `SELECT ... FOR UPDATE` and refreshes it from the database.
- `find_by_id_prefix` returns up to 10 rows whose id starts with a hyphen-free prefix. `statuses_for_ids` maps each ref to a status or `None`: full UUIDs in one query, other refs by prefix when exactly one row matches.
- `query_tasks` returns rows newest first, 100 by default. Terminal rows come back only with `include_terminal` or an explicit terminal `status`.
- `count_tasks`, `count_tasks_by_status` and `count_tasks_by_priority` count over the same filters without loading rows. `count_tasks_by_project` takes no `project` filter, so its buckets show every project the other filters admit.
- `query_chase_due` lists blocked rows whose chase time has passed, oldest chase first. `get_events` returns one row's trail oldest first. `query_events` filters by actor, transition, project and time, newest first.
- `count_admissions_since` counts one actor's `not_approved->` events since a time, leaving out `not_approved->not_approved`.
- `ApprovalSettingRepository` has `get_all` (a key-to-value dict), `has_key` and `upsert_many`. `upsert_many` adds or replaces the named keys, leaves the rest alone and stamps `updated_by`.

## Don't
- Don't call `query_tasks` without a narrowing filter. Over 50 non-terminal rows it raises `UnscopedQueryError`, unless `unscoped_audit` is set. `urgency` alone does not count as narrowing.
- Don't re-read an edited, unflushed row through `get_by_id_for_update`. It repopulates the row from the database and drops your edit, and `get_db()` sessions do not autoflush.
- Don't expect `apply_transition` to refuse an illegal move. The caller must have validated it first.

## Invariants
- Every write flushes and none commits. The commit is the caller's `get_db()` block, and event summaries wait on the session until it commits.
- Entering `parked` writes one timestamp to both `park_reason_captured_at` and the event. Any other status clears both fields.
- A filing sets `request_state` to `pending`. A verdict sets it to the verdict. Neither moves the row's status.
