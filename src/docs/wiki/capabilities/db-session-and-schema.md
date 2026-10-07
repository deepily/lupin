---
capability: db-session-and-schema
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.rest.db.database.get_db@63596843e9
  - cosa.rest.db.database.get_database_url@4036f19257
  - cosa.rest.db.auto_migrate.run_migrations_to_head@f45791ac43
  - cosa.rest.db.schema_drift.find_missing_columns@e7952a8c24
  - cosa.rest.db.schema_drift.emit_startup_drift_alarm@5a9d566cd7
  - cosa.rest.db.repositories.base.BaseRepository@6839b17f66
  - cosa.rest.postgres_models.Base@5515a96e30
  - cosa.rest.sqlite_database.get_auth_db_path@fbe9ae52dc
---
# Database sessions, startup migration and schema-drift alarm

The Postgres engine, the session context manager, the ORM base, the boot-time Alembic upgrade and the boot-time drift check. Query code per table lives in [[db-repositories]]; the task tables are described in [[task-store]].

## Getting a session
- `with get_db() as session:` commits when the block ends normally, rolls back and re-raises on any exception, and always closes the session.
- `BaseRepository` never commits. `create` and `update` only flush; the commit comes from `get_db`.

## Which database
- Postgres through SQLAlchemy is the main store. `LUPIN_CLOUD_BACKED` set to 1, true, yes or on (any case) selects Cloud SQL over a Unix socket. It needs `CLOUD_SQL_CONNECTION_NAME` and `DB_PASSWORD`, or `get_database_url` raises `ValueError`.
- Otherwise `LUPIN_ENV=testing` selects the test database on a local host; any other value, or none, selects the development database.

## Startup migration
- `run_migrations_to_head` is called once from the `lupin_app.main` lifespan, before anything else uses the database. Any error aborts boot.
- Database with an `alembic_version` table: runs `upgrade head`, a no-op at head.
- Database with no `alembic_version` table and no `users` table: enables the `vector` extension, runs `create_all` from `Base.metadata`, then stamps head.
- Database with a `users` table but no `alembic_version` table: raises `RuntimeError` and does not touch the schema. The operator must stamp a baseline once by hand.

## Drift alarm
- `emit_startup_drift_alarm` runs after the migration. It compares every table and column in `Base.metadata` with the live database by name only. It flags a missing table or a missing column.
- It also reads the stamped revision and the migration head. If both are readable and differ it adds a revision-behind finding. If either is unreadable it adds nothing.
- On a finding it prints the alarm to stderr and returns the report. The header says CRITICAL when a table or column is missing and WARNING when only the revision differs. The server keeps booting.
- It never raises. An internal failure prints a warning and returns `None`.

## When not to use
- A hand-run `ALTER` for a new column is not the way. Add the Alembic migration; the alarm text says the same.
- For accounts and tokens as a feature, see [[auth-and-accounts]].
