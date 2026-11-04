---
capability: repo-tools-symindex-librarian-tick-run
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.symindex.librarian_tick.run_tick@8aff424b3a
  - cosa.repo.symindex.librarian_tick.run_mobile@59bfbe1b4b
  - cosa.repo.symindex.librarian_tick.due@da2c1edfb5
  - cosa.repo.symindex.librarian_tick.read_state@dcc7be473b
  - cosa.repo.symindex.librarian_tick.write_state@4ba0748bb6
  - cosa.repo.symindex.librarian_tick.make_logger@2bd00293f7
  - cosa.repo.symindex.librarian_tick.LiveStore@e974357b6b
  - cosa.repo.symindex.librarian_tick.notify_owner@56aee637b7
  - cosa.repo.symindex.librarian_tick.data_dir@1dc90370b7
  - cosa.repo.symindex.librarian_tick.main@0351f4d1dd
---
# Wiki librarian tick: one run

The daily job that lints the wiki, queues the findings and exports the reuse misses. Rows are made by [[repo-tools-symindex-librarian-queue]]; the switches and cron lines are in [[repo-tools-symindex-librarian-tick-config]].

## Running it
- `python -m cosa.repo.symindex.librarian_tick [--force] [--root R] [--misses-out P]`. The tick is off until the configuration key `wiki librarian tick enabled` is true, and an off tick exits 3 before building anything. `main` prints the run summary as JSON.
- Exit 0: nothing due, or the run finished and nothing is held. Exit 1: the run could not finish. Exit 2: it finished and some rows, lupin or lupin-mobile, sit in a pending file. Exit 3: switched off.

## What `run_tick` does
- It is due when the local hour is 10 or later and the last finished run was on another day (`due`). `--force` skips that check.
- It refuses with exit 1 when the wiki has no capability page or the index holds no symbols. An empty lint read would clear every open rollup.
- Otherwise it ensures the index, lints, calls `librarian.sync` with the index header's `symbols_sha`, reads every row including done and dropped, and writes the misses file. The state file gets today's date only after the sync and the miss export both finished.
- A `mobile` callable, if given, runs after the lupin export. If it fails, the tick exits 1 and leaves the state as it was, so the next tick runs both corpora again.
- A vector status check, if given, puts its stale flag and reasons in the summary. An `OSError` or `ValueError` from it is logged and does not fail the tick.

## Files and helpers
- `run_mobile` lints the lupin-mobile wiki against its Dart index and syncs its rollups under their own key. It refuses a wiki with no capability page or an index with no symbols. Nothing is written inside the mobile repo.
- `data_dir` is `<fleet data root>/reuse-review/librarian`. It holds `tick-state.json`, `pending.jsonl`, `librarian.log` and `misses.jsonl`.
- `read_state` returns an empty dict for an absent or unreadable file. `write_state` writes by temporary name and rename. `make_logger` appends stamped lines and drops one it cannot write.
- `LiveStore` is the adapter over the task-store client. Its reads follow pages of 500 and fail on a truncated read; `query` also reads held rows, `query_all` adds done and dropped ones. Creates are stamped with the actor `wiki-librarian tick`.
- `notify_owner( persona, text, environ )` sends one direct message and returns True only on a 201. It never raises.
