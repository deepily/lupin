---
capability: dump-solution-cache-dump
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.dump_solution_cache.databases_for@1fd508e2c3
  - scripts.dump_solution_cache.tables_for@ffb8e824ba
  - scripts.dump_solution_cache.psql_argv@8c26e2a324
  - scripts.dump_solution_cache.pg_dump_argv@8d4eb65af7
  - scripts.dump_solution_cache.count_sql@1748deb012
  - scripts.dump_solution_cache.delete_sql@3f12a489f2
  - scripts.dump_solution_cache.run_argv@6f2e15ceb5
  - scripts.dump_solution_cache.parse_count_row@1b501b7cce
  - scripts.dump_solution_cache.count_rows@0abfef82ed
  - scripts.dump_solution_cache.backup@71ed74d939
  - scripts.dump_solution_cache.dump@0a1610da7a
  - scripts.dump_solution_cache.verify_empty@675078915c
---
# Solution cache dump: scope, backup and delete
`src/scripts/dump_solution_cache.py` empties the solution cache with a backup and receipts. It does nothing destructive unless `--apply` is passed. The check that the emptied cache still learns is on [[dump-solution-cache-learn-back]].
- `databases_for` turns `--db` into database names, dev first for `both`. It raises `ValueError` for any other value.
- `tables_for` lists the in-scope tables: `solution_snapshots` first, then the synonyms table and the adjacent caches when their flags are on.
- `psql_argv` and `pg_dump_argv` build the docker-exec commands, with no shell. The dump command has one `-t` per table.
- `count_sql` builds one `SELECT` returning one pipe-separated row of counts. `parse_count_row` turns such a row into a dict by table.
- `count_rows` counts every in-scope table of one database.
- `delete_sql` is one transaction that deletes each table with `DELETE`, never `TRUNCATE`, and prints counts before and after.
- `run_argv` runs a command and returns its output. It raises `RuntimeError` naming the command and stderr on a non-zero exit.
- `backup` writes a timestamped `pg_dump` file, and raises if the dump fails.
- `dump` runs the delete and returns the before and after counts. `verify_empty` lists any table that is not empty on an independent read.
