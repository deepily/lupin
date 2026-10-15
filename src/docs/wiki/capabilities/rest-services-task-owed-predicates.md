---
capability: rest-services-task-owed-predicates
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.task_store_owed.is_owed@319c7ddeea
  - cosa.rest.task_store_owed.owed_clause@87b78da66f
  - cosa.rest.task_store_owed.owed_status_row@611dcd037a
  - cosa.rest.task_store_owed.park_is_active_clause@ec588723c9
  - cosa.rest.task_store_owed.holding_is_active@b6901f5324
  - cosa.rest.task_store_owed.holding_is_active_clause@46d422abb3
  - cosa.rest.task_store_owed.park_reason_is_stale@70782a8dc6
  - cosa.rest.task_store_owed.park_reason_is_stale_clause@e45ac59bfe
  - cosa.rest.task_store_owed.item_blocker_ids@eaf86ee994
  - cosa.rest.task_store_owed.is_canonical_uuid@cb5468647d
  - cosa.rest.task_store_owed.blocker_is_terminal@2b3a1363e4
---
# Task store owed-work predicates

Which task rows count as owed, and which waits can never end. The park, holding and stale-reason rules and the owed-only set have a Python form for plain dicts and a SQLAlchemy twin for queries. The blocker helpers and `is_owed` are Python only. See [[task-store]] for the statuses.

## What it does
- A parked row is park-active while its `next_chase_ts` is in the future. Expiry is computed at read time and never written back. `park_is_active_clause( model, now )` is the SQL twin and treats a NULL chase as not active.
- `holding_is_active` and `holding_is_active_clause` do the same for a `not_approved` row. On expiry such a row becomes visible but is not poked, since nobody approved it.
- `owed_clause( model, now )` is true for every row that is not park-active. `owed_status_row( status, next_chase_ts, now )` is the dict-level form of the owed-only set: queued, in_progress, and parked rows. A parked row counts when its park has expired or its chase is missing or unreadable. Its SQL form is `owed_status_clause`, not `owed_clause`.
- `is_owed` is the general rule (non-terminal and not park-active). No reader uses it as its owed definition yet, because it would also count blocked, claimed and review rows.
- `park_reason_is_stale` and its clause are true only for a parked row whose body changed after the park reason was captured. They compare `body_changed_ts`, not `updated_ts`, and a NULL on either side reads as not stale.
- `item_blocker_ids( blocked_by )` returns the `{kind: item}` ids, skipping malformed entries. Persona and user refs are left out because nothing can say they are gone.
- `is_canonical_uuid` is true only for a 36-character dashed UUID.
- `blocker_is_terminal( status, blocked_by, status_by_id )` flags a `blocked` row waiting on a blocker that can never move again. It is advisory and changes no status.

## Don't
- Don't default the clock. Predicates that compare a chase time take `now` from the caller. The stale-reason predicates compare two row timestamps and take none.
- Don't expect an id missing from `status_by_id` to be flagged. An id is flagged only when it resolved to a terminal status, or was looked up, not found, and is a full UUID.

## Invariants
- Each predicate and its SQL twin must agree. For `park_is_active` and `owed_status_row` a NULL chase counts as owed. `holding_is_active` gives False on NULL, so the row shows but is not owed.
