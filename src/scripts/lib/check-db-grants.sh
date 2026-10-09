#!/usr/bin/env bash
#
# check-db-grants.sh — check the database roles' grants, and optionally repair them once.
#
# Runs `python -m cosa.utils.db_roles --check` through the docker exec psql. With --repair, a red check is
# followed by one `--grants-only --apply` and a second check. The repair needs no password and no root, only
# the same superuser login a seat already reaches with docker exec. With --repair-when-enabled the repair
# runs only when LUPIN_DB_GRANTS_REPAIR=on, which stays off until the one-time apply has been run by hand.
#
# Usage:  check-db-grants.sh [--repair | --repair-when-enabled]
# Exit:   0 = clean (or repaired) · 1 = still red after a repair attempt · 2 = the check could not run,
#         which is not a pass · 3 = red, and no repair was attempted · 4 = the grants are clean but the secret
#         files were not checked (this login cannot search DB_GRANTS_SECRETS_DIR): not a pass either
#
# Environment:
#   LUPIN_DB_GRANTS_REPAIR  on enables --repair-when-enabled; anything else leaves it check-only
#   DB_GRANTS_PSQL    the psql command, default: docker exec -i lupin-postgres psql -U lupin_dev -d lupin_db_dev
#   DB_GRANTS_PYTHON  the interpreter, default: the tree's .venv, then python3
#   DB_GRANTS_SECRETS_DIR  the secret files' directory, checked too; default /etc/lupin/secrets (the one place
#                     that names it; the bounce and the preflight both call this helper); set empty to skip
#
# Standalone so a test can drive it with a stub psql and no database.

set -uo pipefail

REPAIR=0
for arg in "$@"; do
    case "$arg" in
        --repair) REPAIR=1 ;;
        --repair-when-enabled) [ "${LUPIN_DB_GRANTS_REPAIR:-off}" = "on" ] && REPAIR=1 ;;
        -h|--help) sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "check-db-grants.sh: unknown argument $arg" >&2; exit 2 ;;
    esac
done

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOT="$( cd "${SCRIPT_DIR}/../../.." && pwd )"
PSQL="${DB_GRANTS_PSQL:-docker exec -i lupin-postgres psql -U lupin_dev -d lupin_db_dev}"
PYTHON="${DB_GRANTS_PYTHON:-}"
if [ -z "$PYTHON" ]; then
    if [ -x "${ROOT}/.venv/bin/python" ]; then PYTHON="${ROOT}/.venv/bin/python"; else PYTHON="python3"; fi
fi

roles() { LUPIN_ROOT="$ROOT" PYTHONPATH="${ROOT}/src" "$PYTHON" -m cosa.utils.db_roles --psql "$PSQL" "$@"; }

SECRETS_DIR="${DB_GRANTS_SECRETS_DIR-/etc/lupin/secrets}"
SECRETS_ARGS=()
if [ -n "$SECRETS_DIR" ]; then SECRETS_ARGS=( --secrets-dir "$SECRETS_DIR" ); fi

not_checked() {
    echo "check-db-grants: ${1}, but the secret files in ${SECRETS_DIR} were NOT checked (this login cannot search the directory)" >&2
    exit 4
}

check_out="$( roles --check ${SECRETS_ARGS[@]+"${SECRETS_ARGS[@]}"} 2>&1 )"; rc=$?
echo "$check_out"
if [ "$rc" -eq 0 ]; then exit 0; fi
if [ "$rc" -eq 5 ]; then not_checked "the grants are clean"; fi
if [ "$rc" -ne 1 ]; then
    echo "check-db-grants: the check could not run (exit ${rc}); grants were not verified" >&2
    exit 2
fi
if [ "$REPAIR" -ne 1 ]; then exit 3; fi

echo "check-db-grants: repairing with --grants-only --apply"
if ! roles --grants-only --apply; then
    echo "check-db-grants: the repair itself failed" >&2
    exit 1
fi
recheck_out="$( roles --check ${SECRETS_ARGS[@]+"${SECRETS_ARGS[@]}"} 2>&1 )"; rc=$?
echo "$recheck_out"
if [ "$rc" -eq 0 ]; then echo "check-db-grants: repaired"; exit 0; fi
if [ "$rc" -eq 5 ]; then not_checked "the grants are repaired"; fi
echo "check-db-grants: STILL RED after the repair (exit ${rc}); the roles need the full provisioning" >&2
exit 1
