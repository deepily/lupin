---
capability: heartbeat-self-respin-loop
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.heartbeat_arbiter.self_respin_observer.SelfRespinObserverLoop@646f4b024b
  - cosa.agents.heartbeat_arbiter.self_respin_observer.sweep_returned_markers@1e86a59d16
  - cosa.agents.heartbeat_arbiter.self_respin_observer.build_respin_sample@ae2c8c0d35
  - cosa.agents.heartbeat_arbiter.self_respin_observer.collect_respin_samples@bd0c372ad5
  - cosa.agents.heartbeat_arbiter.self_respin_observer.append_respin_samples@9e9dcc59c0
  - cosa.agents.heartbeat_arbiter.self_respin_observer.run_stale_mcp_check@164b6f0393
  - cosa.agents.heartbeat_arbiter.self_respin_observer.render_observer_table@975400c2ec
---
# Heartbeat self-respin loop

The standing loop that acts on the markers in [[heartbeat-self-respin-markers]]. It alarms on seats that did not come back, sweeps done markers, records a sample row per marker and tells managers about stale MCP processes.

## What it does
- `SelfRespinObserverLoop` runs on a daemon thread, one pass per arbiter poll. `start` comes from `StoppableDaemonMixin` ([[utils-stoppable-daemon]]). Its `_should_start` hook does nothing unless the observer flag or the stale-MCP flag is on.
- `sweep_once` does nothing when the observer flag is off, except the stale-MCP half. When on, it sends one advisory per alarming marker and verdict, then sweeps.
- An alarm that clears drops its one-shot key, so a later alarm advises again. A failed pass returns a zero summary and the thread survives.
- `sweep_returned_markers` deletes markers confirmed `RETURNED` and older than the time to live. Pending and alarming markers stay.
- `tell_stale_mcp_once` runs the stale check and DMs each stale seat's manager once per process, keyed by pid and start ticks.
- A refused DM goes to the operator advisory once. A DM with no answer from the server is retried next tick. A seat with no manager goes to the operator advisory.
- `run_stale_mcp_check` runs the check script and returns the stale records. Exit code 2 or unparseable output raises `RuntimeError`.
- `record_once` appends one sample row per marker. It decides nothing and sends nothing.
- `build_respin_sample` holds the pre-clear and current percent, elapsed seconds, verdict, anchor and send delay. `collect_respin_samples` builds one per marker.
- `append_respin_samples` appends to one JSONL file under the fleet data root. It rotates once at a size cap, keeping one older file, and returns the line count.
- `render_observer_table` prints the assessments as a fixed-width table.

## Don't
- Do not read the sample file as a gate. It is an instrument that records and classifies nothing new.
