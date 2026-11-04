---
capability: cc-hold-verb-and-acked-ledger
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_cli.claude_code.hooks.lib.heartbeat_hold_io.cmd_write@eba6941075
  - lupin_cli.claude_code.hooks.lib.heartbeat_hold_io.cmd_read@5229311156
  - lupin_cli.claude_code.hooks.lib.heartbeat_hold_io.cmd_clear@ef5b2606d7
  - lupin_cli.claude_code.hooks.lib.heartbeat_hold_io.build_parser@1773a99e65
  - lupin_cli.claude_code.hooks.lib.heartbeat_hold_io.main@6e880f74cf
  - lupin_cli.claude_code.hooks.lib.heartbeat_acked_ledger.acked_ledger_path@7508287d89
  - lupin_cli.claude_code.hooks.lib.heartbeat_acked_ledger.read_acked_qids@09cae79cd8
  - lupin_cli.claude_code.hooks.lib.heartbeat_acked_ledger.mark_acked@8a11b57ec1
---
# Hold command line and acked ledger
The shell front-end for writing, reading and clearing a hold, and the per-session ledger of question ids a manager has looked at.
## What it does
- `heartbeat_hold_io` is run as `python3 -m lupin_cli.claude_code.hooks.lib.heartbeat_hold_io`. `build_parser` defines `write`, `read` and `clear`; `main` runs one and returns its exit code.
- `cmd_write` calls `write_hold`, then reads the hold back through the Stop hook's own search. If the hook would not honor it, the previous file is restored.
- `cmd_write` also accepts the three debounce stamps, each `now` or an ISO-8601 time, and names the ones it stored.
- `cmd_read` prints the hold as JSON with the honored verdict. It exits with a distinct code when there is no hold.
- `cmd_clear` removes only the exact path for this session id. It reports a distinct code when no hold exists.
- `acked_ledger_path` builds `.heartbeat-acked-<session_id>.json` beside the hold. `read_acked_qids` returns its question ids as a set.
- `mark_acked` merges new ids into the ledger as a union and writes atomically. It returns the sorted ids.
## Don't
- Don't hand-write a hold file; the verb checks that the hook will honor it.
## Invariants
- `read_acked_qids` never raises. Any error gives an empty set.
- Concurrent `mark_acked` writers use separate temp files, so one cannot rename another's partial file.
