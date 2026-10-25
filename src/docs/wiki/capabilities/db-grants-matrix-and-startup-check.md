---
capability: db-grants-matrix-and-startup-check
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.utils.db_grants.build_check_sql@495eaa9be8
  - cosa.utils.db_grants.build_template_sql@56ec26e101
  - cosa.utils.db_grants.check_current_database@b06d35ca56
  - cosa.utils.db_grants.check_with_psql@c65d2eb27b
  - cosa.utils.db_grants.databases@a3ec9add3b
  - cosa.utils.db_grants.emit_startup_grants_alarm@80b33955da
  - cosa.utils.db_grants.evaluate@8347b73ae4
  - cosa.utils.db_grants.format_report@1502085191
  - cosa.utils.db_grants.parse_rows@14941ec17b
  - cosa.utils.db_grants.query_runner@b4bde6dd61
  - cosa.utils.db_grants.remedy_for@120593fb80
  - cosa.utils.db_grants.report_lines@5a24b84324
  - cosa.utils.db_grants.roles_of@fd08ee9168
  - cosa.utils.db_grants.template_problems@9598666a82
---
# Database grants matrix and startup check

The matrix in `db_grants` says which role may do what in `lupin_db_dev` and `lupin_db_test`. A command and the boot path both check it.

## What it does
- `databases` returns the two database names. `roles_of( database )` returns the roles the matrix names for one.
- `build_check_sql( database )` returns a read-only catalog query. Each output row is `database|kind|role|object|privilege`.
- `build_template_sql` returns one row about the clone template `lupin_template_vector`. `template_problems( rows )` returns `None` when no template row exists, else a list of sentences.
- `parse_rows` splits output into 5-field tuples and raises `ValueError` on any other shape.
- `evaluate( database, rows )` returns a report dict. A database with no public tables is a problem of kind `empty`. A missing table count raises `ValueError`.
- `format_report( reports, remedy, limit=None )` returns printable lines. `remedy_for` names the one repair command.
- `check_with_psql( psql_command, run_fn, which=None )` returns `( exit_code, lines )`: 0 clean, 1 a gap, 2 psql failed or its output was unreadable. A template problem alone also gives 1.
- `query_runner( connection )` wraps a SQLAlchemy connection. `check_current_database( run_query )` returns the report, or `None` when the matrix does not name the database. `report_lines` cuts the lines to 30 per database.
- `emit_startup_grants_alarm( debug=False, engine_factory=None )` is the boot check. Called from `src/lupin_app/main.py`. The test-suite job calls `check_current_database` too.

## Don't
- Don't read a `None` from `emit_startup_grants_alarm` as clean. It is also `None` on a cloud-backed deployment, an unnamed database or an internal failure.
- Don't treat a database with no public tables as a pass. It is a problem of kind `empty`.

## Invariants
- The boot check never raises. It fails open with a warning on stderr, and a gap prints a block headed critical.
