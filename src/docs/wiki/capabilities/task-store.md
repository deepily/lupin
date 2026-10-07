---
capability: task-store
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.rest.task_store_rules.validate_transition@5e11c08174
  - cosa.rest.task_store_rules.validate_create_status@06e2c5966d
  - cosa.rest.task_store_rules.is_unscoped@b9acf708e0
  - cosa.rest.task_store_owed.owed_status_clause@e10dfec0cc
  - cosa.rest.task_store_owed.park_is_active@9f096d7729
  - cosa.rest.task_store_rejoin.classify_blocked_row@adcf2351f2
  - cosa.rest.task_chase_consumer.TaskChaseConsumer.sweep_once@80a7268a04
  - cosa.rest.task_store_change_notifier.record_appended_event@7b9f6b43b5
---
# Task store

The store of owed work: one row per task, decision, review request, bug or gate, with an append-only event trail. The Stop hook, managers and the web board read the same rows through `/api/tasks`. The arbiter queries `TaskRepository` directly. [[task-promotion-gate]] covers how a row leaves the holding area; [[mcp-task-store-tools]] is the MCP door.

## What it does
- `routers.tasks` serves `/api/tasks`, a sync `def` surface over `get_db()`. `task_store_rules` holds the structural checks as pure functions that return error strings; the router turns those errors into HTTP 422 through `_reject_if_errors`, so the repository (`TaskRepository`, see [[db-repositories]]) never sees invalid input. A create refused for its priority answers 403. The exception is a refusal that can go to the operator as a petition: that row is held at a holding priority instead. A blocked mint by a non-manager, a live-mint refusal and an approval refusal also answer 403.
- A create may mint only the statuses in `CREATE_ALLOWED_STATUSES`: `queued`, `blocked` or `not_approved`. Every other status is reached by a transition.
- `validate_transition` follows an explicit legal-edge graph. `done`, `dropped` and `wont_fix` have no way out. A `->done` needs a receipt key: a `commit` or `test_run`, an operator attestation or a manager attestation. The server resolves an attestation itself: an API-key caller cannot mint the operator one, and a worker seat cannot mint the manager one. A `->blocked` needs at least one typed `blocked_by` ref. It needs a chase time only when a persona is among the blockers; a user-only or item-only block needs none. A `->dropped` or `->wont_fix` needs a reason, and so does a demotion into `->not_approved`. A `->parked` is legal only from `queued` or `in_progress`, and needs a chase time and a park reason (`validate_park`).
- `task_store_change_notifier` turns each commit that appended events into one `task_store_changed` push with no delta, so the web pane re-reads. The `:7999` server installs the push; any other process, such as the arbiter or a script, emits nothing and its rows appear on the next poll.

## Invariants
- "Owed" has one home, `task_store_owed`, so the board and the Stop-hook oracle cannot disagree. The arbiter does not use the owed set. It reads every non-terminal row with `hide_parked=True`, because it needs the blocked rows. Holding-area rows (`not_approved`) stay hidden until their triage chase comes due. That hides a row while its park is active and shows it once the park has expired. The `owed_only` query applies `owed_status_clause` in `TaskRepository`, and the Stop hook asks the server for `owed_only=true`, so it never evaluates the set itself. The row twin `owed_status_row` has one production caller, the one-shot cutover parity drain `task_store_drain`. The set is `queued`, `in_progress`, and `parked` rows whose chase has come due. `is_owed` is a wider rule that no production reader uses; only tests call it.
- A parked row is silent only while `next_chase_ts` is later than now. Expiry is computed at read time and never written, so a stopped daemon cannot leave a row parked forever.
- `park_is_active` and `park_is_active_clause` express one rule in Python and in SQL. They share no code, on purpose.
- A bare query that would return more than 50 non-terminal rows raises `UnscopedQueryError` unless the caller passes `unscoped_audit=True`. `urgency` alone does not count as a narrowing filter.
- `TaskChaseConsumer` nudges overdue blocked rows and re-arms their chase. It never changes a status, and it does nothing unless `task store chase enabled` is true; `lupin-app.ini` sets it `False`.

## Rejoin and drift checks
- `task_store_rejoin` rejoins a blocked row only when every blocker is an item row that is `done`. It holds a row that is not blocked or has no blockers. It also holds one with a persona, user or malformed blocker, an unknown id or a live blocker. A `dropped` or `wont_fix` blocker is flagged and left, because closing it that way was a decision. The module builds the dormancy stamp; `src/scripts/rejoin-done-blocked-rows.py` writes it with `--apply`, as an amend and then the transition, and is dry-run by default.
- `task_store_epic_keys` and `task_store_prose_refs` only report drift. The first reports rows with a blank key, a foreign key, or an `epic:<slug>` that names no known epic; `cc-task:` mirror rows are never findings. The second reports rows that name a finished task in prose with no `blocked_by` edge. Both print what they could not check.

## How to extend
- Put a new rule in `task_store_rules` as a pure function and call it from the router. Add a status to `VALID_STATUSES` and the legal-edge graph follows, because it is derived from that tuple. Then decide whether it is terminal (`TERMINAL_STATUSES`), whether it may be minted (`CREATE_ALLOWED_STATUSES`), whether the board hides it (`BOARD_INVISIBLE_STATUSES`) and whether it is owed (`task_store_owed`).
- Do not read the owed set by summing per-status counts; an expired parked row would be counted twice.
