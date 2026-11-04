---
capability: orphaned-dm-buffers-report
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.report-orphaned-dm-buffers.read_buffer@4295ad540c
  - scripts.report-orphaned-dm-buffers.is_session_live@597b8d8807
  - scripts.report-orphaned-dm-buffers.collect_orphans@fbf3c18dcb
  - scripts.report-orphaned-dm-buffers.format_report@fe8bd957a5
  - scripts.report-orphaned-dm-buffers.main@2574e846ff
---
# Orphaned DM buffers report

Reports peer DMs that were accepted, buffered and never delivered. When a session is busy, the listener appends inbound messages to a per-session buffer, and a hook drains it on the next turn. If the session ends first, the messages stay on disk and nobody is told, although the sender already saw `dispatched: true`.

## Reading
- `read_buffer` reads one buffer file into message dicts. A malformed line is skipped, so one bad line never hides the readable messages beside it. An unreadable file gives an empty list.
- `is_session_live` decides whether the session that owns a buffer is still running. It is true when a spawn bridge or a listener log for that session was modified within the threshold, ten minutes by default.
- Liveness is freshness, not presence. The empty spawn-lock file carries no process id and survives its session, so testing for it always says live. Both files are checked, because neither alone covers every seat.

## Reporting
- `collect_orphans` returns one record per orphaned buffer: the session, path, message count, age in hours and the distinct senders stranded there. It excludes buffers of live sessions and empty files, and returns an empty list when the directory does not exist.
- `format_report` renders the list for a terminal. It names the total message count rather than the file count, which understates the loss. An empty list renders as an explicit all-clear.
- `main` returns 0 when nothing is orphaned and 1 otherwise. `--json` emits the records, and `--min-age-hours` ignores recent buffers.
- The script reports and never deletes. The file on disk is the only surviving copy of what the sender said, and deciding its fate is a person's job.
