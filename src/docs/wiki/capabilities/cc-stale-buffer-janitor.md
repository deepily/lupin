---
capability: cc-stale-buffer-janitor
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - lupin_cli.claude_code.hooks.lib.stale_buffer_janitor.parse_hash_from_buffer_name@9b48501e3b
  - lupin_cli.claude_code.hooks.lib.stale_buffer_janitor.parse_listener_hashes@47e39c7a53
  - lupin_cli.claude_code.hooks.lib.stale_buffer_janitor.count_buffer_lines@483d775d27
  - lupin_cli.claude_code.hooks.lib.stale_buffer_janitor.classify_buffer@0bb0d2c222
  - lupin_cli.claude_code.hooks.lib.stale_buffer_janitor.build_plan@1d15c78037
  - lupin_cli.claude_code.hooks.lib.stale_buffer_janitor.plan_move_dst@ef1b6dd21e
  - lupin_cli.claude_code.hooks.lib.stale_buffer_janitor.format_report@a79dafab92
  - lupin_cli.claude_code.hooks.lib.stale_buffer_janitor.is_pid_alive@05e1745b45
  - lupin_cli.claude_code.hooks.lib.stale_buffer_janitor.list_listener_hashes@bb2f755fa2
  - lupin_cli.claude_code.hooks.lib.stale_buffer_janitor.list_bridge_live_hashes@9713914732
  - lupin_cli.claude_code.hooks.lib.stale_buffer_janitor.collect_live_hashes@94f3eb302b
  - lupin_cli.claude_code.hooks.lib.stale_buffer_janitor.gather_buffer_meta@8d1e7920bf
  - lupin_cli.claude_code.hooks.lib.stale_buffer_janitor.run@28e540469a
  - lupin_cli.claude_code.hooks.lib.stale_buffer_janitor.main@851933411f
---
# Stale buffer janitor
Archives `cc-buffer-<hash>.jsonl` files that belong to dead sessions. It never deletes a file and never replays a message.
## What it does
- `run()` scans the sessions directory, classifies each buffer, and moves dead ones to a quarantine folder only when `apply=True`. It returns the plan, the report and the moved paths.
- `main()` is the command line. It is a dry run unless `--apply` is passed.
- `parse_hash_from_buffer_name()` takes the 8-character hash from a buffer name. `gather_buffer_meta()` reads a file into a meta dict; an unreadable file still yields one.
- `count_buffer_lines()` counts valid rows and ai-to-ai rows, skipping blank and malformed lines.
- `classify_buffer()` calls a buffer dead only if its hash is not live and its age passes the grace window. `build_plan()` splits archive from keep.
- `collect_live_hashes()` joins `list_listener_hashes()` and `list_bridge_live_hashes()`. A bridge is live when its mtime is fresh or its listener pid runs.
- `parse_listener_hashes()` reads `--session-id` from `ps` lines. `is_pid_alive()` uses signal 0.
- `plan_move_dst()` keeps the file's base name inside the quarantine folder. `format_report()` states dry run or apply in its header.
## Don't
- Do not sweep when the live scan fails. The error propagates and `run()` stops.
## Invariants
- When in doubt a buffer is kept, and every move can be reversed.
