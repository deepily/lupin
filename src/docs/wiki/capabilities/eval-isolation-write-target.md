---
capability: eval-isolation-write-target
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.eval_isolation_guard.IsolationNotConfigured@035d8f427e
  - scripts.eval_isolation_guard.PairedTargetsNotIsolated@5b5f3b1271
  - scripts.eval_isolation_guard.ConfigTableMismatch@0daa8e0b44
  - scripts.eval_isolation_guard.NotAMeasurementDatabase@d48a919579
  - scripts.eval_isolation_guard.PairedCorpusExercisesLeak@e19accc9da
  - scripts.eval_isolation_guard.resolve_write_target@626c6804ac
  - scripts.eval_isolation_guard.resolve_write_database@12c04d08f2
  - scripts.eval_isolation_guard.fully_qualified@fd216062e4
  - scripts.eval_isolation_guard.require_config_table_matches_write_target@b18efcbb73
  - scripts.eval_isolation_guard.assert_measurement_db@61897d8eff
---
# Eval isolation guard: write target and safety

Guards the paired v1-versus-v2 eval, where the v2 flow can write snapshots back to a store. A paired run must never write to a live store. It must also never let one arm warm the other's cold pass. This page covers the first property and the errors. The pairing check is on [[eval-isolation-pairing]].

## Errors
- `IsolationNotConfigured` means the write destination is not provably non-live.
- `PairedTargetsNotIsolated` means the two arms' destinations are not distinct and clean.
- `ConfigTableMismatch` means the declared snapshot table names a table the ORM never writes.
- `NotAMeasurementDatabase` means a destructive clean step was aimed at a database that is not a measurement database.
- `PairedCorpusExercisesLeak` means an argument-extracting corpus was paired with a v1 pin that still has the leak.

## Write target
- `resolve_write_target` reads the table the write-back ORM actually writes through, live, so a table rename moves the guard with it.
- `resolve_write_database` reads the database from the app's own database URL, live, so it tracks dev, testing or cloud.
- `fully_qualified` joins them as `database.table`. That pair is the unit the safety allowlist is keyed on, because the same table name in two databases is two stores.
- `require_config_table_matches_write_target` returns the ORM table when the declared `v2 snapshot table` equals it. An absent, blank or different value raises `ConfigTableMismatch`.
- The clean step calls it first, so the `TRUNCATE` identifier is always the ORM table and never a raw config string.

## Measurement database
- `assert_measurement_db` refuses a destructive clean step unless the connection's database is `lupin_db_test` or `lupin_db_v1baseline`.
- The name must match exactly, so `lupin_db_test_shadow` is refused. A missing or non-string target is refused too.
