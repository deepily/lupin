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
- `create_item` adds a row and its `->{status}` creation event. `apply_transition` updates the status and appends the `from->to` event. Both only write: they never validate.
- `apply_patch`, `apply_amendment`, `apply_correlation`, `apply_chase`, `apply_request_filing` and `apply_request_verdict` each change one family of fields and append one event for it.
- `get_by_id_for_update` loads a row with `SELECT ... FOR UPDATE` and refreshes it. `find_by_id_prefix` resolves a hyphen-free id prefix, and `statuses_for_ids` resolves many blocker ids in one query.
- `query_tasks` returns rows newest first, and terminal rows only when asked. `count_tasks` and the three `count_tasks_by_*` methods count over the same filters with no row loading.
- `query_chase_due` lists blocked rows whose chase time has passed, longest overdue first. `get_events` and `query_events` read the trail.
- `count_admissions_since` counts events that began `not_approved->` for one actor, which is how a batch of promotions is told from a single one.
- `ApprovalSettingRepository` has `get_all`, `has_key` and `upsert_many`. `upsert_many` replaces named keys and leaves the rest alone, stamping `updated_by`.

## Don't
- Don't call `query_tasks` with no narrowing filter. Past the unscoped threshold it raises `UnscopedQueryError` for every repository caller, unless `unscoped_audit` is set.
- Don't re-read a row you have edited and not flushed through `get_by_id_for_update`. It repopulates the row from the database and drops your edit.
- Don't expect `apply_transition` to refuse an illegal move. The caller must have validated it first.

## Invariants
- Every write flushes and none commits. The commit is the caller's `get_db()` block, and a change notice goes out only on commit.
- A `parked` row carries one timestamp in both `park_reason_captured_at` and its event; any non-blocked, non-parked status empties `blocked_by`.
- A request never moves a row's status. It sets `request_state` to `pending`.
