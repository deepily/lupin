---
capability: cc-memory-watch-switch
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.utils.cc_memory_watch.parse_switch@8c49eee605
  - cosa.utils.cc_memory_watch.read_switch@eba044d209
  - cosa.utils.cc_memory_watch.SwitchGate@2bf1e08d71
  - cosa.utils.cc_memory_watch.SwitchGate.allowed@e22f630a12
  - cosa.utils.cc_memory_watch.write_failed_summary@167c43bf0d
---
# Memory watch: the side-services switch

The key `cron job side-services enabled` gates every sampling pass of [[claude-process-memory-watch]]. The bounce watcher script reads the same key.

## How it reads
- The unit passes `--ini` with the main configuration file. A run with no `--ini` has no gate.
- `read_switch` reads the key fresh from that file on every pass. It answers True, False or None.
- None covers an unreadable file, a missing key, a key defined twice and any other word.
- `SwitchGate.allowed` is True only for `true`. Any other answer skips that pass.
- It logs one line when the answer changes. The loop stays alive, so `true` resumes sampling with no restart.
- An unreadable key also calls `write_failed_summary` on each pass. That runs `lupin_mcp.cron_switch_read` in a child process, which writes the job's failed summary so the jobs page turns red.

## Why a copy
- The deployed module cannot import `lupin_mcp`, so `parse_switch` copies `cron_switch_read.parse_switch`.
- `test_cc_memory_watch_switch.py` fails when the two sources or their answers differ.
