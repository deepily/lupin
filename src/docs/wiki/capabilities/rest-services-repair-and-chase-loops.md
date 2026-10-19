---
capability: rest-services-repair-and-chase-loops
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.repair_attempt_tracker.RepairAttempt@2e9e777bc8
  - cosa.rest.repair_attempt_tracker.RepairChain@7bf9706fc6
  - cosa.rest.repair_attempt_tracker.RepairAttemptTracker@4a6d976858
  - cosa.rest.repair_attempt_tracker.cosine_similarity@29cc6e2133
  - cosa.rest.repair_attempt_tracker.is_semantically_duplicate@ff10da3823
  - cosa.rest.repair_attempt_tracker.init_tracker@40f6fd9c54
  - cosa.rest.repair_attempt_tracker.get_tracker@550e1ef42f
  - cosa.rest.test_suite_completion_watchdog.TestSuiteCompletionWatchdog@f094aadf57
  - cosa.rest.test_suite_completion_watchdog.init_watchdog@b40e47abb0
  - cosa.rest.test_suite_completion_watchdog.get_watchdog@1f4e3d610e
  - cosa.rest.test_suite_completion_watchdog.reset_watchdog@498534d70c
  - cosa.rest.watchdogs.init_watchdogs@0b559c36aa
  - cosa.rest.task_chase_consumer.TaskChaseConsumer@cd8512f7dc
---
# Repair limits, watchdogs and the chase daemon

The circuit breakers and background watchers that keep automatic repair and blocked rows from running away. The expediters they dispatch are in [[fix-expediter-tfe]] and [[fix-expediter-bfe]].

## What it does
- `RepairAttempt.to_dict` leaves out the gist embedding. `RepairChain` exposes `attempt_count`, `cumulative_cost` and `elapsed_seconds` as properties. `can_attempt` refuses when attempts, cumulative cost or wall-clock time reach the chain's limit, and returns `( allowed, reason )`.
- `RepairAttemptTracker` keeps chains in memory. Chain lookup and creation run under a lock. Changes to a chain, such as recording an attempt, do not. `get_or_create_chain`, `can_attempt`, `record_attempt`, `update_attempt`, `check_semantic_dedup` and `get_chain_summary` all take the original job id.
- `cosine_similarity` returns 0.0 for an empty or all-zero vector. `is_semantically_duplicate` compares a new fix gist embedding to prior attempts that have one and returns `( is_duplicate, max_similarity, matching_attempt )`.
- `init_tracker( config_mgr )` builds the process singleton; `get_tracker` returns it, or `None` before init.
- `TestSuiteCompletionWatchdog.evaluate( completed_job )` dispatches a TestFixExpediter job for a finished `test_suite` job whose remediation snapshot lists failures, and returns its job id, or `None`. It runs when `test fix expediter auto fix enabled` is true, unless the job sets `auto_fix_on_failure` to false. A job that sets it to true runs regardless. It also needs a todo queue, an ask flow and a remediation snapshot path. It skips a rerun the expediter itself triggered and a count over the failure cap. Its repair-tracker check applies only when a tracker is passed, and `init_watchdogs` passes none. It never raises.
- `init_watchdog`, `get_watchdog` and `reset_watchdog` manage that singleton; `reset_watchdog` is for tests.
- `init_watchdogs` builds the dead-queue and test-suite watchdogs together, one failing without stopping the other, and returns `( bfe_watchdog, tfe_watchdog )`.
- `TaskChaseConsumer` is a daemon that chases overdue blocked task rows. It is inert unless `task store chase enabled` is true, and `start` must be called. The pass interval is `task store chase interval seconds`, 300 by default, and the re-arm backoff is `task store chase backoff seconds`, 1800 by default. `sweep_once` signals and re-arms each one in one transaction. `stall_report` lists them read-only.

## Don't
- Don't expect a chase to move a row: it never changes status.
- Don't rely on `RepairChain.to_dict` for the wall-clock limit; it leaves it out.

## Invariants
- On a disabled chase consumer, `sweep_once` does no database access and `start` returns `False`. `stall_report` is never gated and still queries.
