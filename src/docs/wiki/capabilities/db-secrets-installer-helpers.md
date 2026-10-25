---
capability: db-secrets-installer-helpers
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.install_db_secrets.Refusal@113e9cff1b
  - scripts.install_db_secrets.Host@a6622caa5c
  - scripts.install_db_secrets.run_command@11ce0facfc
  - scripts.install_db_secrets.sudoers_line@8c406aef81
  - scripts.install_db_secrets.load_payload@ec2ff220a3
  - scripts.install_db_secrets.owner_and_mode@a24b0eddaa
  - scripts.install_db_secrets.sha256_of@95b9a6d1ee
  - scripts.install_db_secrets.operator_of@173637c6bb
---
# Database secrets installer: helpers

Installs the test login's database secret files on a new host in one command, run from an operator account through sudo. It uses the standard library only and finds its payload beside itself, because sudo drops the environment. The three steps are on [[db-secrets-installer-steps]]. The payload is on [[db-secrets-payload]].

## Refusals and host
- `Refusal` is a reason to stop, with the exit code it maps to. Exit codes 20 to 27 are the installer's own. Codes 15 to 17 are the payload's, and any other nonzero code is the installed copy's, passed through.
- `Host` gathers every outside thing the installer touches in one place, so tests can replace paths and calls one by one.
- `run_command` runs a command given as a list and returns the exit code with stdout and stderr together in one string.

## Small helpers
- `sudoers_line` renders the one line that lets a user run the installed copy with no arguments. The user must match a lower-case account pattern, and the trailing empty argument is kept, because without it sudo would allow any arguments.
- `load_payload` imports the payload file by its path and returns the module.
- `owner_and_mode` returns the user id, group id and permission bits of a path, following no link beyond the first stat.
- `sha256_of` returns the hex sha256 of bytes.
- `operator_of` names the account that ran sudo. It accepts a non-root account only when `SUDO_USER` agrees with `SUDO_UID`. Otherwise it refuses with 21, so a name from the environment is never trusted alone.
