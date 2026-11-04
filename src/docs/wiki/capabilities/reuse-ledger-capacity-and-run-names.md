---
capability: reuse-ledger-capacity-and-run-names
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_ledger.make_run_name@010c4514b5
  - lupin_mcp.reuse_ledger.ceiling_for@71b8f985fb
  - lupin_mcp.reuse_ledger.capacity@2726201b49
  - lupin_mcp.reuse_ledger.account_capacity@d3c4451ace
  - lupin_mcp.reuse_ledger.AccountLedger.snapshot@c080178f3b
  - lupin_mcp.reuse_ledger.AccountLedger.total@f850976d2e
  - lupin_mcp.reuse_ledger.AccountLedger.held_by_prefix@bb8b8556d1
  - lupin_mcp.reuse_ledger.AccountLedger.open_runs@6edb2b1158
  - lupin_mcp.reuse_ledger.AccountLedger.limit_tokens@089d7aa396
---
# Reuse ledger: run names, ceilings, capacity and reads
The rest of `lupin_mcp.reuse_ledger`. The file, its rows and `begin_run` are in [[reuse-token-ceiling-and-spend-ledger]].

## What it does
- `make_run_name( prefix, today, pid )` returns `<prefix>-<date>-<pid>-<count>-<random>`. The count rises by one for each name this process makes, under a lock.
- The random part is four bytes in hex. A restart that reuses a process id and restarts the count still makes a new name.
- `ceiling_for( worst_tokens, margin )` is the worst measured spend times the margin, rounded up. The margin is 1.5 by default.
- `capacity( headroom, audit_ceiling, weekly_cap, ... )` asks whether the expected seats can look up at once beside the shadow audits. It returns `lookups_at_once`, `open_tokens`, `audit_week_tokens`, `spare_tokens` and `fits`.
- `lookups_at_once` is the headroom divided by the lookup ceiling, rounded down. `open_tokens` is the seats at the lookup ceiling plus one audit run.
- `audit_week_tokens` is one week of audits at the audit ceiling. `spare_tokens` is the headroom less both. It is negative when they do not fit, and `fits` is true at zero or more.
- `account_capacity( ledger, audit_ceiling, weekly_cap, **settings )` runs `capacity` on the headroom of one ledger read. It adds `headroom`, which is the limit less the total.

## Reads on the ledger
- `snapshot()` returns the limit and the total from one read. `total()` and `limit_tokens()` each return one half of it.
- `held_by_prefix( prefix )` sums what the runs whose name starts with `prefix` hold against the account. A closed run counts at its spend and an open one at the larger of ceiling and spend.
- `open_runs()` lists `{ run, ceiling, spent, began }` for each run with no end row, in the order they began. `began` is None for a hand-typed row with no time stamp.
- Each read parses only the rows appended since this instance last read. It reads from the start when the file was replaced, shrank or no longer holds the bytes read last time.
- Each read raises `LedgerUnreadable` as `snapshot` does.

## Defaults
- The module pins the price at 0.042 dollars per million tokens and the account limit at 40 dollars.
- The lookup ceiling is 64,000 tokens and five seats are expected at once.
- The audit ceiling and the weekly audit cap have no default here. The caller passes them, and the drain reads them from its INI keys ([[reuse-shadow-audit-wiring]]).
