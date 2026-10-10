---
capability: heartbeat-arbiter
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - lupin_arbiter_app.fleet_arbiter_loop.FleetArbiterLoop@f658361fd6
  - cosa.agents.heartbeat_arbiter.arbiter_job.ArbiterConsumerJob@783d1f7cc3
  - cosa.agents.heartbeat_arbiter.arbiter_routing.tier_for@810e74e825
  - cosa.rest.arbiter_bootstrap.submit_arbiter_if_enabled@23da8f20f5
  - cosa.rest.routers.arbiter.get_fleet_state@08546cb60d
  - cosa.rest.routers.arbiter.get_context_pressure@76c4b0c5de
  - cosa.rest.routers.arbiter.put_fleet_size_cap@328e788dfb
  - lupin_arbiter_app.fleet_arbiter_loop.make_follow_through_watcher_factory@f8105d8a1d
  - cosa.rest.routers.heartbeat.put_poke_mute@3a91d11f2d
---
# Heartbeat arbiter

The arbiter polls the fleet's heartbeat events and tells Rick or the managers when a session is stuck, silent or waiting. It runs as the standalone `lupin_arbiter_app` on port 8001. The REST side reads that app's `/state`. [[cc-hooks-heartbeat]] covers the hook side.

## How it runs
- `FleetArbiterLoop` builds an `ArbiterConsumerJob`, runs it, and builds a fresh one when the job reaches its time cap or crashes.
- Among the switches that ship `false` are in-process bootstrap, follow-through escalation, hwm and bookmark deletion and the orphan-bridge sweep. `submit_arbiter_if_enabled` reads the first and, when it is `false`, logs and returns.
- `/health` always says `ok`. Its `loops` map marks each loop alive, `DEAD` or not started, and `degraded` is true when any loop is `DEAD`.

## One poll
- A poll runs every 60 seconds. It reads new heartbeat events, who is on the commons and the bridges. From the task store it reads owed work, known owners and operator gates. Sent-DM activity is read when `arbiter count dm as liveness` is true.
- It checks, in order: deadlock cycles, blocker pings, manager taps and their acknowledgement, decisions needed, a whole-fleet stall and auto-pokes. Then it publishes the snapshot. The staleness, fleet-dark, gate and outreach checks and the follow-through sweep come after.
- Shipped limits in seconds: alive 600, tap acknowledgement 600, fleet stall 1800. Stale-manager pokes run from 2700 up to 7200.
- A stall needs an unchanged fleet signature, live owed work and no recent bridge, DM or hold write by any live session.
- `tier_for` sends each of the twenty numbered cases to one of six routes, mostly Rick alone or Rick with the active managers. One case is dropped. Blocker pings back off per edge; other cases have their own throttles.
- Mostly it notifies and sends DMs. Its auto-poke can inject into tmux panes, the worktree janitor removes worktrees, and the hold-file sweep deletes prunable hold files.

## Separate loops
- The context-pressure writer, the turn-age watchdog, the self-respin observer thread and the container health watcher run beside the poll, each behind its own enable key. The observer's own flag ships `false`, but its thread still runs for the stale-MCP check.
- `get_context_pressure` reports `over_budget` when the last prompt exceeds the budget line: half of a 1,000,000 token window or any unlisted size, three quarters of 200,000.

## REST routes
- The `/api/arbiter` reads accept an API key or a JWT. The two writes, `put_fleet_size_cap` and `put_skeleton_crew`, need an admin login and refuse an API key alone with 403. `get_fleet_state` and `get_context_pressure` pull the app's `/state` and answer `unreachable` when that fails.
- Nothing calls the `fleet-snapshot` pair. Its GET answers `awaiting`, and the app keeps its snapshot locally.
- `put_fleet_size_cap` needs an admin login, refuses a cap above the maximum with 422 and writes the INI file. It ships at 14 with a maximum of 18, and the spawner reads it.
- `put_poke_mute`, under `/api/heartbeat`, needs an admin login and refuses API keys. It mutes the Stop-hook poke, not the arbiter. Its answer, and the GET beside it, carry `source`: `file`, `skeleton_crew`, `both` or `none`, because skeleton crew mutes the poke too.
