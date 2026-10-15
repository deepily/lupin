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

Which task rows count as owed, and which waits can never end. Each rule has a Python form for plain dicts and a SQLAlchemy twin for queries; see [[task-store]] for the statuses.

## What it does
- A parked row is park-active while its `next_chase_ts` is in the future. Expiry is computed at read time and never written back. `park_is_active_clause( model, now )` is the SQL twin and treats a NULL chase as not active.
- `holding_is_active` and `holding_is_active_clause` do the same for a `not_approved` row. On expiry such a row becomes visible but is not poked, since nobody approved it.
- `owed_clause( model, now )` is true for every row that is not park-active. `owed_status_row( status, next_chase_ts, now )` is the dict-level form of the owed-only set: queued, in_progress, and parked rows whose park has expired.
- `is_owed` is the general rule (non-terminal and not park-active). No reader uses it as its owed definition yet, because it would also count blocked, claimed and review rows.
- `park_reason_is_stale` and its clause are true when the body changed after the park reason was captured. They compare `body_changed_ts`, not `updated_ts`, and a NULL on either side reads as not stale.
- `item_blocker_ids( blocked_by )` returns the `{kind: item}` ids, skipping malformed entries. Persona and user refs are left out because nothing can say they are gone.
- `is_canonical_uuid` is true only for a 36-character dashed UUID.
- `blocker_is_terminal( status, blocked_by, status_by_id )` flags a row waiting on a blocker that can never move again. It is advisory and changes no status.

## Don't
- Don't pass a default clock. Every predicate takes `now` from the caller.
- Don't treat a missing id as a deleted blocker unless it is a full UUID; a short prefix may simply not resolve.

## Invariants
- The Python and SQL forms of a rule must agree. A NULL chase lands on the owed side in both.
