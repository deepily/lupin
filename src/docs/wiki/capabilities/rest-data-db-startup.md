---
capability: rest-data-db-startup
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.db.auto_migrate.build_alembic_config@341eae8102
  - cosa.rest.db.auto_migrate.next_backoff@37ce220dd0
  - cosa.rest.db.auto_migrate.resolve_database_url@fe83ed0205
  - cosa.rest.db.auto_migrate.wait_for_database@fd695c3efb
  - cosa.rest.db.database.announce_empty_db_password_once@366b20cb2c
  - cosa.rest.db.database.get_pool_config@f9210c8dae
  - cosa.rest.db.database.is_cloud_backed@7a61b3aa8a
  - cosa.rest.db.database.swap_database@75064d487f
---
# Database startup helpers

The small functions the server uses to find its database, size its connection pool and wait for it at boot. The session, the models and the migration chain belong to [[db-session-and-schema]]; this page covers the helpers that sit underneath them.

## What it does
- `is_cloud_backed()` is true only when `LUPIN_CLOUD_BACKED` is `1`, `true`, `yes` or `on`, in any case. The environment name is never used to guess it.
- `get_pool_config()` returns the engine arguments. Cloud-backed: 5 connections plus 10 overflow. `LUPIN_ENV=testing`: `NullPool`, so no connection is kept. Anything else: 10 plus 20. Both pooled variants check a connection before use. All three force UTC.
- `announce_empty_db_password_once( venue )` prints one warning that `DB_PASSWORD` is empty and returns `True`. Every later call returns `False`. It never tests the password itself. Only the development and testing branches of `get_database_url` call it, and only when the password is empty.
- `swap_database( new_env )` sets `LUPIN_ENV` and re-picks any login that was filled in from `.env`. It then disposes the old engine and builds a new engine and sessions. It runs `SELECT 1` and returns the URL with the password replaced by `***`.
- `resolve_database_url( database_url )` takes the argument, then `DATABASE_URL`, then `get_database_url()`.
- `build_alembic_config( database_url )` builds the Alembic config in code, with `script_location` set to `src/migrations` under the project root. A given URL goes to `env.py` on `config.attributes["injected_db_url"]`.
- `wait_for_database( probe )` calls `probe` until it succeeds. It sleeps 1 second, doubling up to 8 seconds, for at most 60 seconds, then re-raises the last error unchanged. `next_backoff` is the capped doubling.

## Don't
- Don't set `LUPIN_ENV=testing` to get `NullPool` on a cloud-backed deployment. The cloud flag is checked first and wins.
- Don't call `swap_database` and expect open sessions to follow. It replaces the module's `engine`, `SessionLocal` and `ScopedSession`; a session already created stays bound to the old engine.
- Don't look for `alembic.ini`. The container does not have one; the config is built in code.

## Invariants
- An empty `DB_PASSWORD` in development or testing warns and never raises at import, so every importer keeps working. On the cloud path `get_database_url` raises `ValueError` when `DB_PASSWORD` or `CLOUD_SQL_CONNECTION_NAME` is missing, and the module builds its engine at import.
- A spent wait budget re-raises the driver's own error, so a real outage still stops the boot.
- A probe that succeeds first time costs no sleep.
