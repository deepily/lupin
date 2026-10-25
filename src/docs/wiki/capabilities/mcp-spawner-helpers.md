---
capability: mcp-spawner-helpers
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.session_spawner.artifact_alarm@328d1ddec3
  - lupin_mcp.session_spawner.build_spawn_argv@f76212cac7
  - lupin_mcp.session_spawner.default_runner@600edc9884
  - lupin_mcp.session_spawner.persona_chain_csv@978da6d8bc
  - lupin_mcp.session_spawner.placement_alarm@1b5b0b965a
  - lupin_mcp.session_spawner.reap_stale_spawned@0b676f3ac8
  - lupin_mcp.session_spawner.render_task_prompt@bed762299e
  - lupin_mcp.session_spawner.resolve_manager_identity@88ced050a2
  - lupin_mcp.session_spawner.resolve_spawn_config@46bcd96fec
  - lupin_mcp.session_spawner.venv_alarm@4a09793409
---
# Session spawner helpers
The small functions behind `spawn_sessions` and `dismiss_sessions` ([[mcp-session-spawn-and-reap]]). They live in `session_spawner.py`.
- `resolve_manager_identity` takes the manager's session id and persona from bridge metadata. It prefers the stable session id, so lineage survives a `/clear`.
- `resolve_spawn_config` reads the spawn INI keys with defaults: cap 8, ack timeout 120 seconds, memento on, and a model per role.
- `render_task_prompt` fills `{token}` placeholders in a task template and can prepend a seed memento.
- `persona_chain_csv` turns a persona preference into the comma list carried in the `COSA_VOICE_PERSONA_CHAIN` variable of the child.
- `build_spawn_argv` builds the headless `start-cc-with-tmux.sh` command. `default_runner` runs it with a 30 second timeout and never raises on a non-zero exit.
- `venv_alarm`, `artifact_alarm` and `placement_alarm` each give one top-level line when a seat got no interpreter, no borrowed artifacts, or the shared main checkout.
- The three alarms are separate fields because each answers a different question. A caller reads the top of a result, not a nested dict.
- `reap_stale_spawned` is the idle backstop. It reaps spawned sessions that a supplied staleness test flags, so a forgotten manager strands no seats.
