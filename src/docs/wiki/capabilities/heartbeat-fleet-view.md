---
capability: heartbeat-fleet-view
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.heartbeat_arbiter.fleet_data_model.build_fleet_view@9ec632a963
  - cosa.agents.heartbeat_arbiter.fleet_render.build_snapshot@4df067f959
  - cosa.agents.heartbeat_arbiter.fleet_render.carry_forward_lineage@4587d703b1
  - cosa.agents.heartbeat_arbiter.fleet_render.compute_liveness@edf8ce8862
  - cosa.agents.heartbeat_arbiter.fleet_render.frame_signature@454cbc6423
  - cosa.agents.heartbeat_arbiter.fleet_render.prune_offline_rows@2d7979e886
  - cosa.agents.heartbeat_arbiter.fleet_render.render_fleet_table@808b4fd2ed
  - cosa.agents.heartbeat_arbiter.fleet_render.render_tick@24f05f2f95
---
# Heartbeat fleet view

Turns the heartbeat events, the commons roster and file times into one row per session, and renders that as a table. It is pure and never raises. [[heartbeat-arbiter]] polls it, and [[heartbeat-wait-graph]] reads the same view.

## What it does
- `build_fleet_view` merges five sources into one view per session: live bridges, commons rows, idle-prompt records, stop events and sent-DM times. Short and full session ids are folded into one.
- A session absent from the bridges gets no commons time, so a reaped process's commons echo is not a sign of life.
- A `reaped` tombstone makes the row a member and lets the snapshot force it offline. Task-transition beacons are progress only and never count as liveness.
- `compute_liveness` takes the freshest of up to seven signal ages and labels the row live, quiet, stale or offline. The ages stay separate columns.
- The sent-DM age joins the union only when `count_dm` is true. Hold and transcript file times always join it.
- `build_snapshot` adds role and manager to each row, sorted by session id. Offline rows are dropped unless `include_offline` is set.
- A session named in `process_dead` is forced offline. A manager is shown only when it came from spawn lineage.
- `carry_forward_lineage` fills a missing manager from the last poll that resolved it and returns the next map, pruned to the current rows.
- `prune_offline_rows` gives the published live-only view and recounts it.
- `frame_signature` covers only the meaningful fields, so a steady fleet does not reprint. `render_fleet_table` prints the full table and `render_tick` prints the one-line "no changes" tick.

## Invariants
- State and liveness are separate keys. Liveness errs toward alive, so only a positive dead reading overrides it.
