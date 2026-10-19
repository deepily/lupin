---
capability: cc-task-store-map-mirror-drain
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - lupin_cli.claude_code.hooks.lib.task_store_map.map_path@67710a2871
  - lupin_cli.claude_code.hooks.lib.task_store_map.map_key@440c3ed013
  - lupin_cli.claude_code.hooks.lib.task_store_map.read_map@10de95052e
  - lupin_cli.claude_code.hooks.lib.task_store_map.write_map@618941af64
  - lupin_cli.claude_code.hooks.lib.task_store_map.current_generation@e2e18a25e4
  - lupin_cli.claude_code.hooks.lib.task_store_map.bump_generation@13cbdb479c
  - lupin_cli.claude_code.hooks.lib.task_store_map.record_task@864ffcccb8
  - lupin_cli.claude_code.hooks.lib.task_store_map.lookup_task@bf5a4542fb
  - lupin_cli.claude_code.hooks.lib.task_store_map.set_flagged@700afb27d5
  - lupin_cli.claude_code.hooks.lib.task_store_mirror.build_correlation_key@f788152e6a
  - lupin_cli.claude_code.hooks.lib.task_store_mirror.mirror_task_tool_event@89243d7902
  - lupin_cli.claude_code.hooks.lib.task_store_drain.discover_active_sessions@4aec7f8abf
  - lupin_cli.claude_code.hooks.lib.task_store_drain.drain_owed_items_for_session@5e98f1fbb8
  - lupin_cli.claude_code.hooks.lib.task_store_drain.check_session_parity@1063ef168c
  - lupin_cli.claude_code.hooks.lib.task_store_drain.run_drain@68277b7391
  - lupin_cli.claude_code.hooks.lib.task_store_drain.format_report@f73b82c864
  - lupin_cli.claude_code.hooks.lib.task_store_drain.main@3a08931ec1
  - lupin_cli.claude_code.hooks.lib.transcript_reader.read_transcript@8d3529378c
  - lupin_cli.claude_code.hooks.lib.transcript_reader.iter_tool_uses@59894e03a2
---
# Task-store map, mirror and drain
Hook-side memory of which store row matches each native Task item, the retired mirror, and a one-shot back-fill from transcripts.
## What it does
- The map file `.task-store-map-<session>.json` holds `tasks`, `flagged_at` and `generation`. Keys look like `<generation>:<harness_id>`, built by `map_key()`.
- `read_map()` always returns a normal shape and never raises. `write_map()` is atomic; `record_task()`, `bump_generation()` and `set_flagged()` read, change and write.
- The generation rises when a create arrives for a harness id already live. Harness counters restart after a clear, so the key keeps the old and new rows apart.
- `build_correlation_key()` returns `cc-task:<stable id>:g<generation>:<harness id>`.
- `mirror_task_tool_event()` is a deprecated no-op that logs one line while `MIRROR_WRITES_DEPRECATED` is true. Sessions write owed work through `task_create`.
- `read_transcript()` yields each parseable JSON object of a transcript; `iter_tool_uses()` yields `( name, input, tool_use_id )` for assistant tool calls. Neither raises.
- `discover_active_sessions()` lists live persona sessions that have a transcript. `drain_owed_items_for_session()` probes each owed correlation key and creates only missing rows.
- `check_session_parity()` compares the store's owed count with the transcript's. `run_drain()` runs discover, drain and parity, and `format_report()` prints the table.
- `main()` is a dry run unless `--apply` is given. It exits 0 only when every session reaches parity.
## Don't
- Do not use `query_owed` to check one session. It aggregates across every session of the same persona.
## Invariants
- Drain is idempotent. A failure in one session does not stop the others.
