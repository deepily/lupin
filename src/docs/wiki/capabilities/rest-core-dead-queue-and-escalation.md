---
capability: rest-core-dead-queue-and-escalation
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.dead_queue_watchdog.FailureCategory@d62b2d8f59
  - cosa.rest.dead_queue_watchdog.classify_failure@92ae9ac038
  - cosa.rest.dead_queue_watchdog.is_eligible_for_auto_fix@f0097393c3
  - cosa.rest.dead_queue_watchdog.init_watchdog@39ab8bffe4
  - cosa.rest.dead_queue_watchdog.get_watchdog@15daed4a28
  - cosa.rest.follow_through_escalation_watcher.FollowThroughEscalationWatcher@45177fd7e8
  - cosa.rest.follow_through_escalation_watcher.is_awaiting_manager@9cb7bb7bba
---
# Failed-job triage and aged escalation

Two watchers act on stalled work. The dead-queue watchdog decides which failed jobs go to the Bug Fix Expediter, and does nothing unless `auto fix enabled` is true. The escalation watcher chases items blocked on a manager. The dead queue itself is on [[cj-flow-queue]].

## Dead-queue watchdog
- `classify_failure( error, stack_trace )` returns a `FailureCategory` string. It checks user-input patterns first, then timeout, out-of-memory, rate-limit and environment patterns, then code-bug patterns. No match, or empty text, is `unknown`.
- `is_eligible_for_auto_fix( job, eligible_types, max_attempts, attempt_count )` returns `(eligible, reason)`. It refuses a job with no type, a `bug_fix_expediter` or `swe_team` job, and a type outside the list. It also refuses an exhausted attempt count and a job whose `state` is set and not `FAILED`.
- It then refuses `infra_oom`, `infra_environment` and `user_input`. Timeouts, rate limits, code bugs and `unknown` pass this check. The watchdog retries timeouts and rate limits directly.
- `init_watchdog( config_mgr, todo_queue, debug, ask_flow )` builds the process singleton at startup. `get_watchdog` returns it, or `None` before that.

## Escalation watcher
- `is_awaiting_manager( item )` is true for a `blocked` item with an accountable manager, whose `blocked_by` holds a persona ref to that same manager.
- `FollowThroughEscalationWatcher.sweep_once` does nothing, and touches no database, unless `follow through escalation enabled` is true.
- Enabled, it fires one escalation for each such item older than the live arbiter tick times the multiplier. It skips a worker with a valid hold, and reads at most 500 blocked items. The fired marker is in memory, so a restart can fire again. It clears when the item leaves the candidate set. The default sink prints a banner.

## Don't
- Don't read the attempt counts as durable. They are held in memory and reset on a restart.
