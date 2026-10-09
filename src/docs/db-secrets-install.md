# Installing the database secret files on a new host

One command, run once per host from an operator account:

```bash
sudo src/scripts/install_db_secrets.py            # install
sudo src/scripts/install_db_secrets.py --check    # report only, changes nothing
```

Run it from an ordinary host terminal. Typed into a Claude pane with `!`, sudo cannot ask for the password.

## What it does

| Step | Result | Why |
|---|---|---|
| 1 | copies `src/scripts/lupin_install_db_secrets.py` to `/usr/local/sbin/lupin-install-db-secrets` (root, mode 0755) | sudo must never run a file the repository can change |
| 2 | writes `/etc/sudoers.d/lupin-install-db-secrets` (root, mode 0440): `<you> ALL=(root) NOPASSWD: <that copy> ""`. The trailing `""` forbids arguments. | lets the copy be rerun without a password, for one file only |
| 3 | runs the installed copy, which writes `/etc/lupin/secrets/db_test_password` (root:1002, 0440) from `~/.lupin/db_test_pw` and repairs the owner and mode of `db_app_password` | the test container mounts these files |

Nothing is carried between steps in a shell variable. Everything that can be checked is checked **before** the copy. The checks are: root; a sudo operator whose name agrees with `SUDO_UID`; the payload is a plain file; `visudo` exists; `~/.lupin/db_test_pw` passes the payload's own checks; `db_app_password` exists and is not empty.

The sudoers line goes live only after `visudo -cf` accepts it. Once it is in, `visudo -c` checks the whole set, and a failure there takes the new line out again.

A refusal prints the reason and a line such as `done: copy of the payload; did not: sudoers line, run of the installed copy`. A rerun on a finished host prints `unchanged` for each step.

## Exit codes

| code | meaning |
|---|---|
| 0 | done (install), or everything in place (`--check`) |
| 2 | an argument it does not know |
| 15, 16, 17 | the payload's own refusals: operator account, `~/.lupin/db_test_pw`, `db_app_password` |
| 20 | not root |
| 21 | not run through sudo from an operator account |
| 22 | the payload in the repository is missing or a link |
| 23 | `visudo` not found |
| 26 | `visudo` refused the new line; nothing was installed |
| 27 | `visudo` refused the whole set; the new line was taken out again |

`--check` answers 0 (all in place), 1 (something missing or different) or 2 (could not look: not root, or not run through sudo). Run it as `sudo ... --check` to see all three pieces.

## What stays manual

- Creating `/etc/lupin/secrets/db_app_password` (the runbook's app-password step) and `~/.lupin/db_test_pw`, which must hold the password `lupin_test` was given.
- Creating the `lupin_test` role and the template database: `src/scripts/provision-db-roles.sh` (it also writes the secret files, but only on a host where it runs as root with the database reachable).
- Cloud SQL (the `lupin_test` user and the template database) and applying terraform. The VM gets the password as `LUPIN_TEST_DB_PASSWORD` in `cloud-gpu.env`. Push it with `lupin-vm.sh push-test-login`.
- Recreating the test container afterwards: `docker compose up -d --force-recreate lupin-rest-test`, only when `PYTHONPATH=src python3 -m cosa.rest.venue_idle --port 8000` exits 0.

## Undo

```bash
sudo rm /etc/sudoers.d/lupin-install-db-secrets && sudo visudo -c
sudo rm /usr/local/sbin/lupin-install-db-secrets
```

The secret files stay, because the containers read them.

## Tests

`src/tests/unit/deploy/test_install_db_secrets.py` (every branch, injected host) and `src/tests/smoke/test_install_db_secrets_real_sudo.py` (real sudo and visudo in a throwaway container; it never touches this host).
