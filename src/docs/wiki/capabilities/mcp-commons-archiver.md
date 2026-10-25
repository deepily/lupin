---
capability: mcp-commons-archiver
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.commons_archival.CommonsArchiver@76efbf61f1
---
# Commons archiver

The rotation of old commons entries into daily archive files. The store it rotates is in [[mcp-commons-and-dm]].

## What it does
- `CommonsArchiver` takes a root, an interval in seconds (default 3600) and a retention in hours (default 24).
- `rotate_once` reads every topic file under `io/commons` and moves entries older than the retention to `archive/<day>/<topic>.md`.
- It returns a map from topic to the kept and archived counts. A missing commons folder gives an empty map.
- `start` spawns a daemon thread that calls `rotate_once` each interval. `stop` signals it and joins.

## Don't
- Don't rely on a rotation error to show up. The loop swallows every error from `rotate_once`.

## Invariants
- The archive append runs before the active file is rewritten, so a failed rotation loses nothing.
- The rewrite is atomic and runs under an exclusive lock on the active file.
- Reserved topics keep their `reserved: true` front matter.
- `start` on a live archiver does nothing, and `stop` on one never started is safe.
