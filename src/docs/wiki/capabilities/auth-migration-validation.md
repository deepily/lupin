---
capability: auth-migration-validation
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.validate-postgres-migration.print_banner@ab1d07319c
  - scripts.validate-postgres-migration.validate_record_counts@65306d1cf2
  - scripts.validate-postgres-migration.validate_uuids@e63b35354b
  - scripts.validate-postgres-migration.validate_foreign_keys@9ab9dd2be2
  - scripts.validate-postgres-migration.validate_password_hashes@9889aabd9d
  - scripts.validate-postgres-migration.validate_active_api_key@328b81f2d6
  - scripts.validate-postgres-migration.validate_user_roles@9f5d62c8e2
  - scripts.validate-postgres-migration.validate_timestamps@fc6b60f1bc
  - scripts.validate-postgres-migration.run_validation@dcaeccb708
---
# Auth migration validation

Checks that the SQLite data arrived in PostgreSQL intact. Each check asserts, and the first failure stops the run with exit 1. The migration it checks is on [[auth-sqlite-to-postgres-migration]].

## Checks
- `validate_record_counts` counts users, refresh tokens, API keys and audit logs. It asserts only that users and API keys are not empty, and returns the counts.
- `validate_uuids` asserts that no user id, refresh token id or user reference, or API key user reference, is null. The UUID format itself is enforced by the PostgreSQL type.
- `validate_foreign_keys` asserts that every refresh token and API key references a user that exists.
- `validate_password_hashes` asserts every user has a hash in bcrypt format, starting with `$2a$` or `$2b$`.
- `validate_active_api_key` asserts at least one active API key exists, and prints each.
- `validate_user_roles` asserts every user has a roles list, and counts the admin and regular users.
- `validate_timestamps` asserts that each user's created and last-login times carry timezone information.

## Running
- `run_validation` runs the checks in that order, then prints a summary of the migrated counts. An assertion failure or any other error prints the reason and exits 1.
- `print_banner` prints the formatted section banner.
