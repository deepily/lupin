---
capability: rest-services-task-feed-and-priority-firewall
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.task_store_change_notifier.set_sink@8a5e68c3b0
  - cosa.rest.task_store_change_notifier.get_sink@471f115381
  - cosa.rest.task_store_change_notifier.install_websocket_sink@4f27f1c576
  - cosa.rest.task_store_change_notifier.to_status_of@3bbd1028fb
  - cosa.rest.task_store_change_notifier.build_payload@e55b292c8f
  - cosa.rest.task_priority_firewall.normalize_priority@1ca6207c9a
  - cosa.rest.task_priority_firewall.caller_is_operator@9ea6d81004
  - cosa.rest.task_priority_firewall.caller_is_manager@ee61b68990
  - cosa.rest.task_priority_firewall.caller_is_manager_by_bridge@28a178a2e9
  - cosa.rest.task_priority_firewall.session_id_from_actor@669dd8ec84
  - cosa.rest.task_priority_firewall.petition_is_available@0c4a2104d7
---
# Task change feed and priority firewall

The push that tells web panes a task changed, and the rules on who may set a priority. See [[task-store]] and [[web-client-task-board-panes]].

## What it does
- A commit that appended `TaskEvent` rows emits one `task_store_changed` event for the whole commit; a rollback emits nothing. The event carries no delta and the client re-reads.
- `build_payload( appended )` gives the last event's identity and how many there were. `to_status_of( "from->to" )` returns the text after the last `->`, or `None`.
- `set_sink( sink )` installs the delivery function, or clears it with `None`; `get_sink` returns it. `install_websocket_sink( websocket_manager )` points it at `emit( "task_store_changed", payload )`. A process that never installs one emits nothing.
- `normalize_priority( value )` returns the upper-case priority or `None`. Rejecting an unknown value belongs to `task_store_rules`.
- `caller_is_operator( account_email )` is true only for a validated account that maps to an unconditional approver. It never reads a declared name.
- `caller_is_manager( bridge_role, account_email )` is true for a bridge role of `manager` or for the operator. `caller_is_manager_by_bridge` resolves the role from the session id inside `actor`, and is false if the bridge cannot be read.
- `session_id_from_actor( actor )` returns the last token when it looks like a session id (8 or more hex-like characters), else `None`.
- `petition_is_available` is true only for a manager, not the operator, asking for P0 with `authority` exactly `user_direct`. A worker escalates through a manager.

## Don't
- Don't use a savepoint in code that writes task events. A savepoint rollback drops parked events and a release can push early.
- Don't treat the bridge role as proof. It is self-declared.

## Invariants
- Only the operator's validated account can set P0.
