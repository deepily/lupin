---
capability: heartbeat-idle-roster-and-managers
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.heartbeat_arbiter.idle_roster.build_roster@f5c5f5d63a
  - cosa.agents.heartbeat_arbiter.idle_roster.classify_idle@8fc0fd18ad
  - cosa.agents.heartbeat_arbiter.manager_resolver.find_manager_session_id@9ae0412872
  - cosa.agents.heartbeat_arbiter.manager_resolver.list_manager_session_ids@a9dbcd4471
  - cosa.agents.heartbeat_arbiter.manager_resolver.resolve_active_managers@d53e5628eb
  - cosa.agents.heartbeat_arbiter.manager_resolver.resolve_manager@b1273e8bc1
---
# Heartbeat idle roster and managers

Two pure helpers of [[heartbeat-arbiter]]: which sessions are idle, and which manager owns a worker. Both read the view from [[heartbeat-fleet-view]] and never raise.

## What it does
- `classify_idle` says an idle beacon is declared idle and trusted. Otherwise an alive session quiet for the threshold is inferred idle. A working or dead one gives nothing.
- `build_roster` lists the idle sessions, newest activity first. It drops a session older than the alive threshold, so a dead session's old idle beacon does not inflate the free count.
- `find_manager_session_id` scans the spawn manifests for the manager of a tmux session. It returns nothing on no match, a lossy filename or more than one match.
- `list_manager_session_ids` returns every manager id that owns a valid spawn manifest. A missing directory gives an empty set.
- `resolve_active_managers` returns the managers on duty, sorted. A manager needs a role, from a manifest or the declared roster, and a live bridge.
- A declared manager counts before its first spawn. A manager seen only in old commons rows is a phantom and is left out.
- `resolve_manager` returns the manager session, persona and a source of `lineage`, `declared` or `unresolved`. The bridge's `spawned_by` is the main source.
- When the bridge carries `spawned_by_persona`, that frozen name is used, so a later persona change does not rewrite history. A lineage hit needs a usable persona.

## Don't
- Do not DM an `unresolved` result as if it named a manager. The caller escalates to the owner.
