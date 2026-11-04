---
capability: db-secrets-payload
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.lupin_install_db_secrets.Refusal@113e9cff1b
  - scripts.lupin_install_db_secrets.check_copy@11b830d54d
  - scripts.lupin_install_db_secrets.read_source@b7d8469f04
  - scripts.lupin_install_db_secrets.install@a2cbf285f5
  - scripts.lupin_install_db_secrets.main@05142acaea
---
# Database secrets payload

The file the installer copies to a root-owned place and runs through one sudoers line. It makes the compose secret files of the test login. Anyone who can write to the repository can edit the repository copy, so sudo must never run that one. The installer is on [[db-secrets-installer-steps]].

## Checks before writing
- `Refusal` is a reason to stop, with the exit code it maps to.
- `check_copy` refuses to run from a copy that anyone but root could have changed. It refuses a link, or a path that resolves elsewhere, with 14. A file not owned by root gets 10, and a mode other than 0755 gets 11.
- It also refuses with 13 when the directory is not root's alone, or is writable by group or others.
- `read_source` reads the test password from the operator's `~/.lupin/db_test_pw` without trusting the path. It refuses with 15 when sudo gave no non-root user id that names an account.
- It refuses with 16 when the file is a link or not a regular file. The same code covers a file not owned by that account, one writable by group or others, and an empty one.

## Writing
- `install` makes the secret directory mode 0750 and the files mode 0440, owned by root and group 1002.
- `db_test_password` holds the password, written beside itself and renamed. `db_app_password` must already exist and keeps its content, or `install` refuses with 17.
- It returns one status per file, `unchanged`, `repaired` or `written`, and never a password.
- `main` checks the copy, then root, then the source, then writes. It prints one line per file and never a password.
