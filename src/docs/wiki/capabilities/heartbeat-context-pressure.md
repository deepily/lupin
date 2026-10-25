---
capability: heartbeat-context-pressure
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.heartbeat_arbiter.context_pressure.ContextPressure@c8381af519
  - cosa.agents.heartbeat_arbiter.context_pressure.Liveness@ab2f83de76
  - cosa.agents.heartbeat_arbiter.context_pressure.PressureState@289771df24
  - cosa.agents.heartbeat_arbiter.context_pressure.Usage@c9525ad70e
  - cosa.agents.heartbeat_arbiter.context_pressure.WorkerContextPressure@821486af27
  - cosa.agents.heartbeat_arbiter.context_pressure.assess_context_pressure@da24a0f2cd
  - cosa.agents.heartbeat_arbiter.context_pressure.assess_fleet_context_pressure@95fd244a4f
  - cosa.agents.heartbeat_arbiter.context_pressure.assess_liveness@812d32ea92
  - cosa.agents.heartbeat_arbiter.context_pressure.estimate_pending_input@3f3b6f099a
  - cosa.agents.heartbeat_arbiter.context_pressure.read_last_usage@13c6d17322
  - cosa.agents.heartbeat_arbiter.context_pressure.recommend@b2525cb3a6
  - cosa.agents.heartbeat_arbiter.context_pressure.render_fleet_table@e2036d7c21
---
# Heartbeat context pressure

Reads a worker's transcript and estimates how full its context window is, so a manager can act before the worker compacts mid-task. It is a leaf of [[heartbeat-arbiter]] and uses only the standard library on its main path.

## What it does
- `read_last_usage` tail-reads the transcript and returns the newest assistant turn's `Usage`, its parse-failure count and its timestamp. A cold worker gives no usage.
- `Usage.last_prompt_size` is input plus cache creation plus cache read. Output is not in it.
- `estimate_pending_input` guesses tokens that arrived after the last assistant turn, as one quarter of each message's character count, rounded up.
- `assess_context_pressure` sets next prompt to last prompt plus last output plus pending. It returns a `ContextPressure` with a percentage of the window and a `PressureState`.
- The state is `OK`, `WARN` at 70 percent, `CRITICAL` at 85 percent, or `UNKNOWN` when no assistant turn exists. The reserve and response carve-outs default to zero.
- `assess_liveness` returns a `Liveness` of `DEAD` when neither the listener pid nor the Claude pid answers. Otherwise it is `ACTIVE` when the bridge file is fresh and `IDLE` when stale.
- `recommend` maps liveness and state to a one-line manager hint: sweep, skip, harvest and respawn, compact soon, or nothing.
- `assess_fleet_context_pressure` walks live sessions through the bridge files and returns a `WorkerContextPressure` for each. It reads the window size from the bridge and assesses only `ACTIVE` seats.
- A seat with no persona is still listed. One bad bridge is skipped.
- `render_fleet_table` prints one row per worker: persona, liveness, percent, state, pending and recommendation.

## Don't
- Do not read the percentage for an `IDLE` or `DEAD` worker. Its pressure is left empty.
