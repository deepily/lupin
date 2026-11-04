#!/usr/bin/env bash
# Provision the three database roles of the approval-settings guard rail (row 80513825).
#
# Thin wrapper over `python -m cosa.utils.db_roles`. DRY RUN unless --apply is passed; the
# passwords come from files (never argv) and travel to psql on stdin. See that module and
# src/scripts/sql/init-db-roles.sql for what each role may do.
#
#   src/scripts/provision-db-roles.sh \
#       --app-pw-file /etc/lupin/secrets/db_app_password \
#       --host-pw-file <file> --test-pw-file <file> \
#       --psql "docker exec -i lupin-postgres psql -U lupin_dev -d lupin_db_dev" [--reassign] [--apply]
#
#   The way back from --reassign (no password files needed, no role or grant touched):
#   src/scripts/provision-db-roles.sh --psql "<same as above>" --rollback [--apply]
#
#   The repair after a migration or a test made a table the roles cannot reach (no password files, no root):
#   src/scripts/provision-db-roles.sh --psql "<same as above>" --grants-only [--apply]
#
#   The compose secret files, written after the psql step (needs root; the dry run lists them):
#   sudo src/scripts/provision-db-roles.sh <the full-run options above> --secrets-dir /etc/lupin/secrets [--secrets-group-id 1002] [--apply]
#
#   The read-only check, exit 1 on a gap (it prints each gap and the repair command above):
#   src/scripts/provision-db-roles.sh --psql "<same as above>" --check
#
# The test login's secret file on a new host: sudo src/scripts/install_db_secrets.py (src/docs/db-login-files-install.md).
#
# ⚠️ NOT RUN AGAINST THE LIVE DATABASE YET. The app's password file is root-owned (a sudo step),
# and --reassign is a cutover step that needs the app containers recreated first. See
# io/findings-80513825.md §11 for the order.
set -euo pipefail

ROOT="${LUPIN_ROOT:?LUPIN_ROOT is not set — export LUPIN_ROOT=/path/to/lupin}"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"

PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}" exec "$PYTHON" -m cosa.utils.db_roles "$@"
