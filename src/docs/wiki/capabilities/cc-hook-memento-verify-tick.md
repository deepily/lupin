---
capability: cc-hook-memento-verify-tick
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - lupin_cli.claude_code.hooks.lib.memento_verify_tick.fleet_repo_roots@dfc5e1bc5b
  - lupin_cli.claude_code.hooks.lib.memento_verify_tick.verify_tick_line@8c80060c89
---
# Hook memento verify tick

`memento_io.py verify` checks that each memento record matches its out-of-repo mirror. Nothing called it, so findings went unseen. The Stop hook now runs it daily.

## What it does
- `verify_tick_line` runs the verify at most once a day, behind a time-to-live ledger. It returns one line, or an empty string when the ledger is fresh or every repo came back clean.
- With no explicit repo it checks every repo that live session bridges report, plus `LUPIN_ROOT`.
- `force=True` skips the ledger, for the command line and tests.
- `fleet_repo_roots` returns those repos from the live bridges' `cwd`, keeping only repos that contain `io/mementos`.
- It skips unreadable or partial bridge files, and returns an empty list when the sessions folder is missing.
- The script lives in planning-is-prompting and is reached through `PLANNING_IS_PROMPTING_ROOT`.

## Don't
- Don't make the tick restore, delete or migrate a record. An orphan mirror can mean deleted by choice as easily as lost.
- Don't read an empty result as a full audit. A repo with no live seat drops off the list.

## Invariants
- The tick reports a finding and changes nothing.
- Its cadence is one constant, `MEMENTO_VERIFY_TTL_SECONDS`.
