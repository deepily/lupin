---
capability: dump-solution-cache-learn-back
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.dump_solution_cache.latest_snapshot_row@a0102e1bd7
  - scripts.dump_solution_cache.queue_jobs@d6ac9b7465
  - scripts.dump_solution_cache.probe_job_terminal@c1b930bc28
  - scripts.dump_solution_cache.snapshot_ids@adbee4b869
  - scripts.dump_solution_cache.poll_until@40ba3c0807
  - scripts.dump_solution_cache.login@2155ace636
  - scripts.dump_solution_cache.ask_v2@35f68ab1ff
  - scripts.dump_solution_cache.settle_first_ask@7e724bbf30
  - scripts.dump_solution_cache.verify_learn_back@9de381e199
  - scripts.dump_solution_cache.build_parser@0d9e7e7398
  - scripts.dump_solution_cache.main@bfc1ca1c74
---
# Solution cache dump: the learn-back check
After the delete, the tool asks the server one question and checks that the emptied cache learns. The scope, backup and delete are on [[dump-solution-cache-dump]].
- `login` logs in and returns the bearer token, and raises `RuntimeError` on a non-200. `ask_v2` posts one question to `/api/v2/ask`.
- `snapshot_ids` lists every `id_hash` now in the snapshot table, so a new row can be proven fresh.
- `queue_jobs` reads one queue's job metadata list. `probe_job_terminal` looks once for a job in the done or dead queue.
- `poll_until` calls a probe until it answers truthy or the time runs out. It calls it at least once, and sleep and clock can be replaced in tests.
- `settle_first_ask` waits for the first ask to finish and names the snapshot row it wrote.
- `latest_snapshot_row` fetches the id, user, routing command and correctness columns of one snapshot row.
- `verify_learn_back` returns receipts that show the emptied cache still learns.
- `build_parser` makes every scope question a flag. `main` is a dry run unless `--apply` is given, prints receipts as JSON, and returns 2 when a verification failed.
