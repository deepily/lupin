---
capability: mcp-cron-switch-read
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - lupin_mcp.cron_switch_read.switch_key@fb6e422e6c
  - lupin_mcp.cron_switch_read.parse_switch@8c49eee605
  - lupin_mcp.cron_switch_read.read_switch@f868c7b99e
  - lupin_mcp.cron_switch_read.TickSwitch@16317e732a
  - lupin_mcp.cron_switch_read.summary_path_in@48664fdc21
  - lupin_mcp.cron_switch_read.for_job@c2ad6f4ad0
  - lupin_mcp.cron_switch_read.main@56513e8162
---
# Scheduled-job switch reader

The one parse rule for a scheduled job's on/off switch. Every reader of the switch calls it, so they cannot disagree. The readers are the cron wrapper ([[job-run-wrapper]]), the accordion ([[rest-cron-job-switches]]) and the loops that run inside a service. The module imports only the standard library and one small INI reader, so the light `:8001` arbiter can import it.

## The rule
- `switch_key( job )` returns `cron job <job> enabled`. It is the one place that builds the key.
- `parse_switch( raw )` returns True for `true` and False for `false`, in any case and with spaces around. It returns None for anything else: a missing value, a blank, `yes`, `1` or a non-string. It never raises.
- `read_switch( ini_path, job )` reads the key fresh from the file on disk and applies `parse_switch`. It returns None when the key is absent, defined twice or unreadable.

## The check a loop makes
- `TickSwitch` is built once per loop. Its `allowed()` runs at the start of every tick, reads the key fresh and returns True only when the key reads `true`. A false or unknown value returns False, because the code has no default. A skipped tick still sleeps, so turning the switch back on takes effect on the next tick with no restart.
- `allowed()` logs one line each time the answer changes, so a loop that stays off for a day writes one line. An unknown value also writes the job's summary with outcome `failed` and the key name as evidence, when the job has a summary.
- `for_job( job )` builds the `TickSwitch` a production loop uses. It reads the main checkout's `src/conf/lupin-app.ini`, never a seat's worktree copy, and writes its failures under that checkout's `io/jobs/<job>/`.
- `summary_path_in( root, job )` gives `<root>/io/jobs/<job>/job-summary.json`. A census test pins every reader's registry entry to this shape.

## From the command line
- `main` prints one word for a job's switch: `on`, `off` or `unknown`. It takes `--job`, `--ini` and `--root`. The log lines go to stderr, so stdout stays one word, and it returns 0 for every answer. A service outside this tree's Python uses it.
