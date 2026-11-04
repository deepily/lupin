---
capability: schema-and-claims-check-scripts
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.check_schema_parity.get_model_columns@8f2398d34e
  - scripts.check_schema_parity.get_db_columns@86b2a89160
  - scripts.check_schema_parity.check_parity@8c854b33a8
  - scripts.check_schema_parity.format_report@ecad9f39d6
  - scripts.check_schema_parity.main@e670dad17d
  - scripts.check_schema_at_head.read_revisions@254d509766
  - scripts.check_schema_at_head.main@3f6e8d9174
  - scripts.check_dead_claims.extract_table_claims@c7b0947d0e
  - scripts.check_dead_claims.unenforced_table_claims@16ff35677a
  - scripts.check_dead_claims.find_exemptions@d2d6188fe0
  - scripts.check_dead_claims.main@ef0c54eaf0
---
# Schema parity, schema head and dead claim scripts
Three check scripts under `src/scripts/`.
- `check_schema_parity.py` compares every ORM model table with the live database columns and reports drift in both directions.
- `get_model_columns` returns the declared columns of every model table. `get_db_columns` reads the live columns of named tables from `information_schema`.
- `check_parity` runs the check against the resolved database. It is read-only and returns the drift and the report text.
- `format_report` renders the drift. `main` prints a parseable `VERDICT=` record. It returns 0 on parity, 1 on drift and 2 when the question could not be answered.
- `check_schema_at_head.py` asks whether the database schema is at the head revision of the checked-out tree. A code push that skips startup skips the migrations.
- `read_revisions` returns the tree's head revision and the database's current one, or a reason it could not. `main` prints a parseable record and exits with the outcome code.
- `check_dead_claims.py` greps a design document for killed claims that may still be asserted in it.
- `extract_table_claims` takes the canonical phrase from each row of the document's dead-claims table. `unenforced_table_claims` lists table phrases the checker does not grep for.
- `find_exemptions` lists every per-line exemption, so they can be audited. `main` prints one line per live dead claim and exits 1 when any is live.
