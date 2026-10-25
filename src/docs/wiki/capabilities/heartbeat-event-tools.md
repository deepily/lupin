---
capability: heartbeat-event-tools
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.purge-offline-heartbeat-events.fetch_offline_and_live@3262e2d564
  - scripts.purge-offline-heartbeat-events.main@3410779e54
  - scripts.watch-hook-events.C@5333116fbb
  - scripts.watch-hook-events.main@d93053eb2f
---
# Heartbeat event tools

Two command lines over the Claude Code heartbeat event files and the hook event stream.

## Purge offline events
- The standalone arbiter on `:8001` rebuilds its fleet table every poll from one JSONL file per session under the heartbeat-events folder. Nothing ages that folder, so every session that ever emitted an event lingers as offline for days.
- `fetch_offline_and_live` fetches the arbiter's state and partitions its sessions. A session is offline only when its liveness verdict is `offline`. Everything else is kept. A bad fetch raises.
- `main` is a dry run unless `--apply` is given. It moves the offline sessions' event files to a timestamped archive folder, never hard-deleting them, and leaves live and quiet sessions untouched.
- Moving files while the arbiter runs is safe, since the event tailer skips missing files. It takes `--state-url`, `--events-dir`, `--timeout` and `--archive-dir`.

## Watch hook events
- The watcher tails the hook event stream like `tail -f` and pretty-prints each entry. The per-Stop heartbeat oracle line gets special highlighting.
- `C` holds the ANSI colour codes the output uses.
- The four heartbeat outcomes are shown in colours: not owed in green, poked in yellow, honored in cyan and cap reached in red.
- `main` follows heartbeat lines by default. `--all` follows every hook entry, `--replay` prints history first, `--once` prints and exits, and `--no-color` gives plain text.
