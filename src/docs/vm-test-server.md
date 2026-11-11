# The VM's destructive-test server (lupin-rest-test on :8000)

`lupin-host-test` runs `docker-compose.cloud-gpu.yml`, which has one app service on :7999. The overlay `docker-compose.vm-test-overlay.yml` adds a second app, `lupin-rest-test` on :8000, and its own database, `lupin-pgvector-test` (pgvector pg16, a local container). `lupin-vm.sh deploy` and `svc` name the base file only, so they never touch the overlay. Only `lupin-vm.sh test-server ...` names both.

## What differs from the dev host's test server
| | dev host | VM |
|---|---|---|
| compose file | `docker-compose.yml` | overlay on `docker-compose.cloud-gpu.yml` |
| model server | local GPU container | Cloud Run (`LUPIN_MODEL_SERVER_URL`); no GPU |
| database | `lupin-postgres` | `lupin-pgvector-test`; `LUPIN_CLOUD_BACKED` stays unset so the app uses `DB_HOST` |
| image | local candidate tag | `LUPIN_TEST_IMAGE`, else the `LUPIN_IMAGE` that `lupin-rest` runs |
| `group_add` | 1002 | `LUPIN_BRIDGE_GID`, the host user's gid |
| not mounted | | `node_modules` (no typescript tier), dm-corpus, reuse-review, lora, worktrees, five of seven external scopes |

## Secrets
Files under `/etc/lupin/secrets` (root, host gid, 0440), written by `lupin-vm.sh push-test-server-secrets`. The app and test role passwords and the tester login come from Secret Manager over ssh stdin. The pgvector admin and `lupin_host` passwords are generated on the VM once. No value is in git, a command line or a log.

## Reaching VM :8000
- `lupin-vm.sh test-server idle` runs `venue_idle --port 8000` on the VM; the exit code (0 idle, 1 busy, 2 unknown) comes back through ssh. No firewall rule needed.
- `lupin-vm.sh test-server refresh` (or `refresh-test-server.sh --vm`) restarts the container and polls `/health` on the VM. It waits up to 180 seconds, because the app takes about a minute to start.
- From this host (`submit-test-suite.py`, a browser): `lupin-vm.sh firewall open 8000` once, then `lupin-vm.sh tunnel 18000 8000`, then `submit-test-suite.py --base-url http://127.0.0.1:18000 ...`. Local 8000 belongs to this host's own test server, hence 18000.

## Server update (one command)
`lupin-vm.sh deploy` is the update. In order, it:

1. checks Secret Manager (a warning, never a stop);
2. runs the pre preflight and syncs the code;
3. restarts :7999, where the app migrates the database to head at startup, and the arbiter;
4. restarts `lupin-rest-test` and waits for `/health`, only when the overlay containers exist;
5. runs the post preflight.

`push-bundle --checkout` alone moves code and restarts nothing, so it leaves schema drift behind.

The post preflight also reports the `reuse-vector-refresh` cron line in the ssh user's crontab. When the overlay exists it adds four more checks: `/health` on :8000, schema at head, `db_roles --check`, and a tester login in `lupin_db_test`. An absent overlay prints a `[SKIP]` line and never fails.

## Checks that print a line instead of acting
A Claude seat is refused a crontab install and Secret Manager writes, so these only detect and print the line a person runs:

| check | where it runs | missing means | line a person runs |
|---|---|---|---|
| `lupin-vm.sh secrets-check` (also the first step of `deploy`) | dev box | a secret a verb reads has no enabled version | `gcloud secrets create <name> --project=<project> --data-file=-` (value on stdin) |
| refresh cron (post preflight) | VM | the vector index is never refreshed | `lupin-vm.sh install-refresh-cron vm` |
| overlay checks (post preflight) | VM | see the bring-up order below | the remedy printed under each line |

`secrets-check` derives the secret names from the script's own `gcloud secrets` calls. A verb that starts reading a new secret is covered without editing a list. It prints names, never values.

## Bring-up order (a person runs these; nothing here starts by itself)
1. `lupin-vm.sh deploy` (the overlay and init SQL must be on the VM checkout)
2. `lupin-vm.sh push-test-server-secrets`
3. `lupin-vm.sh test-server prep`
4. `lupin-vm.sh test-server up-db` (the pgvector container alone; `roles` needs it running)
5. `lupin-vm.sh test-server roles` (dry run), then `... roles --apply`
6. `lupin-vm.sh test-server up`, then `lupin-vm.sh test-server roles --grants-only` and `... roles --check` once the app has created its tables
7. `lupin-vm.sh test-server idle`, then `lupin-vm.sh firewall open 8000` and the tunnel above

Known gap: the companion seed in `run-fastapi-lupin-test.sh` copies admin users from `lupin_db_dev`, which is empty here, so it skips and :8000 starts with no login. A tester user must be created in `lupin_db_test` before `submit-test-suite.py` can log in.
