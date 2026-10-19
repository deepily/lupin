---
capability: db-provisioning-secret-files-and-dotenv-login
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.utils.db_roles.build_psql_stdin@48b675941f
  - cosa.utils.db_roles.main@b322babf6f
  - cosa.utils.db_roles.read_secret@8b1fa51ba2
  - cosa.utils.db_secret_files.check_files@dfc04511e0
  - cosa.utils.db_secret_files.unsearchable@7f6c9e22a7
  - cosa.utils.db_secret_files.wanted@72a10444bd
  - cosa.utils.db_secret_files.write_files@69372ca0f7
  - cosa.utils.dotenv_password.clone_login@9edf483aac
  - cosa.utils.dotenv_password.reselect_seeded_login@cca87176b5
  - cosa.utils.dotenv_password.seed_db_password_from_dotenv@44d6260c4f
  - cosa.utils.dotenv_password.seed_db_password_from_file@213d4b9b36
---
# Database provisioning, secret files and dotenv login

How the Postgres roles are provisioned with their passwords, how the compose secret files are made, and how a host process finds its login.

## What it does
- `db_roles.main` is the `python -m cosa.utils.db_roles` command. It is a dry run unless `--apply` is given.
- `read_secret( path )` reads one password file and raises `ValueError` for a missing, empty or unsafe value. `build_psql_stdin` builds the psql input and redacts passwords when `redact=True`.
- `db_secret_files` makes and checks `db_app_password` and `db_test_password` in `/etc/lupin/secrets`, mode 0440, owner root, group 1002. `wanted` pairs name and password.
- `write_files` writes them and needs root. `check_files` returns `( gaps, notes )`. `unsearchable` is true for an existing directory this login cannot search.
- `seed_db_password_from_dotenv( root=None )` fills a blank `DB_PASSWORD` from `.env`. `seed_db_password_from_file()` does it from the file named by `DB_PASSWORD_FILE`.
- `reselect_seeded_login` re-chooses the role after `LUPIN_ENV` changes. `clone_login` returns `( user, password )` for the test role, or `None`.

## Don't
- Don't read a clean `--check` as complete when it exits 5. The secret directory could not be searched, so the files were not looked at.
- Don't combine `--secrets-dir` with `--rollback`, `--grants-only`, `--drop-template` or `--reassign`. The parser refuses it.
- Don't put a quote, backslash or newline in a password file. `read_secret` rejects it.
- Don't expect `.env` lines that start with `export` to be read. Only lines that begin with the key and `=` match.

## Invariants
- Passwords go to psql on stdin, never in the argument list. A dry run prints `<redacted>`.
- `check_files` and `write_files` never print or return a password. A link in place of a secret file is a gap and is replaced on write.
- `write_files` raises `PermissionError` when not root. A file is written beside itself at mode 0440 and renamed into place.
- The `.env` login follows `LUPIN_ENV`: `LUPIN_TEST_DB_*` when it is `testing`, otherwise `LUPIN_HOST_DB_*`. `POSTGRES_PASSWORD` is the fallback. An exported `DB_PASSWORD` is never overwritten.
- `check_files` notes a secret file that has no entry in `values` and does not compare it; it does not raise.
