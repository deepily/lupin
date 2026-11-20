---
capability: question-vector-backfill-run
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - scripts.backfill_missing_question_vectors.apply_plan@b258ed9909
  - scripts.backfill_missing_question_vectors.read_back@176c0635f6
  - scripts.backfill_missing_question_vectors.database_name@19084a4c08
  - scripts.backfill_missing_question_vectors.run@507f7feb8d
  - scripts.backfill_missing_question_vectors.main@51639b51b8
---
# Question vector backfill: the run
This is the run half of the backfill script. Its side file and plan are in [[question-vector-backfill-plan]].

## Three modes, one transaction
- The default is a dry run. It reads inside a read-only transaction and prints counts only.
- `--rehearse` runs every apply step and the read-back, then rolls back. `--apply` is the same run, committed.
- A rehearsal or an apply needs the three `--expect-*` counts, `--expect-insert-ids`, `--frozen-ids` and `--expect-database`.
- Without them `main` exits with a usage error before it touches the database. `main` returns the exit code of `run`.
- `run` prints the database name of the connection. `database_name` reads `current_database()` on Postgres, and the URL's database part elsewhere.
- A rehearsal or apply on a database other than `--expect-database` writes nothing and returns 2.

## Apply and read-back
- `apply_plan` first checks that the plan's insert ids equal the expected ids exactly, and that no insert id has a row.
- Then it inserts the missing rows, replaces the vectors of existing rows and stamps the encoder version.
- `read_back` counts case rows, rows with a vector, human-labelled inserts and stamped log rows. A count that differs from the plan raises `CountMismatch`, and the transaction rolls back.
- Exit codes: 0 is a clean dry run or apply. 2 is an unusable side file or plan. 3 is a count mismatch. 4 is a failed import.
