---
capability: db-secrets-installer-steps
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.install_db_secrets.preflight@88e10161e2
  - scripts.install_db_secrets.write_file@35789bdc1d
  - scripts.install_db_secrets.install_copy@300787a82c
  - scripts.install_db_secrets.install_sudoers@1fbaea7247
  - scripts.install_db_secrets.run_installed@eb67a8e177
  - scripts.install_db_secrets.install@081eac7420
  - scripts.install_db_secrets.check@1145fed786
  - scripts.install_db_secrets.main@1c052409d1
---
# Database secrets installer: steps

Everything that can be checked is checked before the first change. A refusal prints what stopped it and which of the three steps were not done. A rerun on a finished host reports unchanged for each. The helpers are on [[db-secrets-installer-helpers]].

## Preflight and writing
- `preflight` checks everything before the first change. It returns the user, payload bytes, payload module and `visudo` path, or raises `Refusal` for the first failure. The payload's own source checks run here, so a bad password file stops the copy from running.
- `write_file` puts data at a path as root with a given mode, written beside itself and renamed. It reports `unchanged`, `repaired` when the file existed, or `written`.
- The temporary file is created exclusively at the final mode, so the content is never in a looser file.

## The three steps
- `install_copy` is the first step: it copies the payload to the root-owned place under `/usr/local/sbin`.
- `install_sudoers` is the second step. It writes the sudoers line only after `visudo -cf` accepts it, which otherwise refuses with 26.
- If `visudo -c` then refuses the whole set, the line is taken out and the previous file restored, with refusal 27.
- `run_installed` is the third step: it runs the installed copy and returns the lines it printed. A copy that refuses passes its own exit code through.

## Running
- `install` runs the preflight and the three steps and says what each did. On a refusal it prints the reason and the steps not done, and returns the refusal's code.
- `check` reports the state of each piece and changes nothing. It returns 0 when all is in place, 1 when something is missing or different, and 2 when it could not look. A piece that needs root to see is reported as cannot look, never as missing.
- `main` is the entry point: install, or `--check`.
