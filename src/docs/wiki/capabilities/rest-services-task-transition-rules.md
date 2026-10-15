---
capability: rest-services-task-transition-rules
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.task_store_rules.validate_receipt_refs@7568938fc9
  - cosa.rest.task_store_rules.validate_blocked_by_refs@6de274810e
  - cosa.rest.task_store_rules.blocked_by_has_persona@6b52789152
  - cosa.rest.task_store_rules.validate_blocked_fields@63596174a9
  - cosa.rest.task_store_rules.normalize_status_fields@bc87fd6f8b
  - cosa.rest.task_store_rules.compose_drop_marker@c4c0f40d44
  - cosa.rest.task_store_rules.is_blocker_repoint@66cc2e2eb7
  - cosa.rest.task_store_rules.validate_park@0696e317a5
  - cosa.rest.task_store_rules.is_park_legal_from@c91aab45a7
  - cosa.rest.task_store_rules.is_park_refresh@cad0ba5f12
---
# Task transition rules: receipts, blockers and parking

The pure rules the task store applies to a status change. Each returns data and never raises on bad input. See [[task-store]] and [[mcp-task-store-tools]].

## What it does
- `validate_receipt_refs( receipt_refs, scope_roots, require_checkable )` checks keys against a whitelist and each value's shape. A `commit` is 7 to 40 hex, a `test_run` is `ts-` plus 8 hex, and a `qid` is a UUID. A `doc_path` or `log_line` names an existing file, and an attestation is 1 to 255 characters.
- With `require_checkable` (a done transition) the receipts need a `commit`, `test_run` or an attestation, and a commit must be reachable from a branch. A path alone never closes a row.
- `validate_blocked_by_refs` requires a non-empty list of typed refs (item, persona or user). `blocked_by_has_persona` is true when one is a persona.
- `validate_blocked_fields( blocked_by, next_chase_ts )` requires a chase time only when a persona ref is present.
- `normalize_status_fields( status, blocked_by, next_chase_ts )` returns `( resolved, dropped )`. `blocked_by` survives only for `blocked` and is named in `dropped` when emptied; `next_chase_ts` is kept as given on every status. `compose_drop_marker` folds that list into the event reason as `[dropped: ...]`.
- `is_blocker_repoint` is true for a `blocked` to `blocked` change that moves the blocker or the chase. It is false when the caller gives no current values.
- `validate_park( from_status, next_chase_ts, park_reason )` needs a legal source, a chase time and a non-blank reason. `is_park_legal_from` allows `queued`, `in_progress` and `parked`. `is_park_refresh` is true for a parked-to-parked write carrying both fields.

## Don't
- Don't read a passing receipt check as authorization. It checks shape; the router decides who may assert an attestation.
- Don't allow any other same-status transition; it would write a meaningless event.

## Invariants
- A row is parked only from queued or in_progress, and a re-park is parked to parked. So every parked row came from an owed status.
