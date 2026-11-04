---
capability: db-setup-and-seed-scripts
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.auth_migration.migrate_mock_users.generate_secure_password@c2839aff40
  - scripts.auth_migration.migrate_mock_users.migrate_users@02f45540fc
  - scripts.auth_migration.migrate_mock_users.quick_smoke_test@7a022f3624
  - scripts.auth_migration.validate_migration.validate_migration@b6f3aed733
  - scripts.create_notifications_table.create_notifications_table@7ec64c9794
  - scripts.create_notifications_table.validate_schema@70dea9ab3f
  - scripts.create_notifications_table.main@a820090cac
  - scripts.embedding_regen_probe.build_statements@2c22e93720
  - scripts.embedding_regen_probe.drop_statements@daccbef92a
  - scripts.embedding_regen_probe.main@d6f4504439
  - scripts.migrate_solution_snapshots.SolutionSnapshotMigrator@63d93bb174
  - scripts.migrate_solution_snapshots.main@65bda25f5b
  - scripts.seed_proxy_decisions.generate_embedding_via_api@52b6010d1f
  - scripts.seed_proxy_decisions.seed_decisions@48bc9fe5d6
  - scripts.seed_proxy_decisions.ratify_suggested@a87ede1d93
  - scripts.seed_proxy_decisions.verify@4a5d2ff1a4
  - scripts.seed_proxy_decisions.clean_seed_data@fd23a3d4f5
  - scripts.seed_proxy_decisions.main@59cc47af4a
  - scripts.seed_test_companions.seed_if_missing@10bf247c34
---
# Database setup, migration and seed scripts
One-off setup scripts under `src/scripts/`. Most are idempotent or have a dry run.
- `SolutionSnapshotMigrator` adds the default user id to existing snapshot files. Its `main` takes `--dry-run` and `--backup`.
- `migrate_users` and `generate_secure_password` migrate the three mock users into the JWT database with random passwords. `validate_migration` checks that all exist and verify.
- `create_notifications_table` creates the SQLite notifications table with its indexes. `validate_schema` checks every field and index.
- `seed_if_missing` copies the companion users and API keys from the dev database to the test database.
- `seed_decisions` inserts 50 proxy decision scenarios into Postgres and the pgvector store. `ratify_suggested`, `verify` and `clean_seed_data` ratify, check and remove them.
- `generate_embedding_via_api` gets an embedding from the running server.
- `build_statements` builds a throwaway clone of the embedding tables in its own schema. `drop_statements` removes it in one statement.
- Each `main` is the command line entry of its script, and `quick_smoke_test` of the mock user migration checks password format.
