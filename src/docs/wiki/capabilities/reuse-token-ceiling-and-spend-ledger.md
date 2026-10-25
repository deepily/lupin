---
capability: reuse-token-ceiling-and-spend-ledger
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_ceiling.input_reserve@62746caa53
  - lupin_mcp.reuse_ceiling.reserve_tokens@2bb32c8859
  - lupin_mcp.reuse_ceiling.TokenBudget@abe6cba483
  - lupin_mcp.reuse_ledger.LedgerUnreadable@f430780837
  - lupin_mcp.reuse_ledger.AccountLimitReached@16e94115cf
  - lupin_mcp.reuse_ledger.usd_to_tokens@003b0079f8
  - lupin_mcp.reuse_ledger.ledger_path@5741220769
  - lupin_mcp.reuse_ledger.AccountLedger@12006950f4
---
# Jev token ceiling and spend ledger
Two guards on live runs against Jev. A run's ceiling stops one run, and the account ledger stops all runs together. See [[reuse-packed-requests]].
- `input_reserve( body )` is 1.5 times the body's length over four, rounded up. `reserve_tokens( body, entries )` adds a fixed output allowance for each entry. Both price a request before it is sent.
- `TokenBudget` holds an attempt limit and a token ceiling. Before each attempt it reserves the tokens under one lock. It refuses with `JevBudgetSpent`, making no HTTP call, if spent plus reserved plus this attempt would pass the ceiling.
- An attempt that drew no answer is charged its input reserve. A settled request is charged its real usage and the rest is released. Closing the run records it in the ledger.
- `ledger_path( index_root )` is `jev-spend-ledger.jsonl` under the fleet data root, the same from every worktree. It reads no `LUPIN_ROOT` and creates nothing.
- `AccountLedger` is that file, appended under a file lock by every process. Each row is a `limit`, `begin`, `spend` or `end`. A missing file is never read as empty: `LedgerUnreadable` stops any run.
- An open run counts at the larger of its ceiling and its spend, a closed run at its spend. `begin_run` reads and appends under one lock, so two processes cannot both pass the limit.
- `begin_run` raises `AccountLimitReached` when the total plus the ceiling would pass the limit, and `ValueError` for a reused run name. `create` writes the first limit and never resets one.
- `set_limit` records a new limit with who and why. `close_run( run, by, why )` closes a dead process's run so it counts at its spend. `usd_to_tokens( usd )` converts dollars at the pinned price.
