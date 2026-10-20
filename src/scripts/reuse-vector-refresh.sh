#!/usr/bin/env bash
#
# reuse-vector-refresh.sh — the daily vector-freshness job, as a command cron can run.
#
# It ensures the symbol index, writes the purpose lines that are missing and rebuilds the stored vector
# set when the index, the engines or the lines changed. One run per local day, from 10:00 on. The job is
# off until the INI key `reuse vector refresh enabled` is true.
#
# Usage:  reuse-vector-refresh.sh [--force] [--install | --uninstall | --status | --print-install]
#   --print-install  print the two cron lines and change nothing
#   --install        write the lines through the shared crontab lock; refused without that lock
#   --uninstall      remove only the lines this tool wrote
#   --status         say whether the lines are present
#
# The purpose-line jobs are submitted with the test credentials, so the environment needs
# LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL and _PASSWORD. Cron's environment is bare: put them in a file
# that only the owner can read and name it in REUSE_VECTOR_REFRESH_ENV; this script sources it.
# Write that file with: lupin-vm.sh push-test-mock-login [local|vm]. It reads the two Secret Manager secrets
# and writes ~/.lupin/reuse-vector-refresh.env, mode 600. --install names that file in both cron lines.
#
# A Claude seat never installs. A person installs from the main checkout, so the cron lines name that
# checkout and not a worktree.
#
# Exit codes: 0 nothing due, fresh, or rebuilt; 1 could not finish or install refused; 2 a named
#   candidate-stage error; 3 switched off; 4 another build holds the build lock.
set -uo pipefail

export PATH="${REUSE_VECTOR_REFRESH_PATH:-/usr/local/bin:/usr/bin:/bin:${PATH:-}}"

SELF="$( readlink -f "${BASH_SOURCE[0]}" )"
SELF_ROOT="$( cd "$( dirname "$SELF" )/../.." && pwd )"
ROOT="${LUPIN_ROOT:-$SELF_ROOT}"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

# Pick the first Python that can import the job. A venv can exist and still lack a package the job needs
# (the test VM's .venv has no `requests`), so "executable" is not enough: try the import.
PYTHON=""
for CANDIDATE in "${REUSE_VECTOR_REFRESH_PYTHON:-}" "$ROOT/.venv/bin/python" "${HOME:-}/.venv-lupin-mcp/bin/python" "$( command -v python3 || true )"; do
    [ -n "$CANDIDATE" ] && [ -x "$CANDIDATE" ] || continue
    if "$CANDIDATE" -c "import cosa.repo.symindex.vector_refresh" >/dev/null 2>&1; then PYTHON="$CANDIDATE"; break; fi
    echo "reuse-vector-refresh: $CANDIDATE cannot import cosa.repo.symindex.vector_refresh; trying the next Python" >&2
done
if [ -z "$PYTHON" ]; then
    echo "reuse-vector-refresh: no Python can import cosa.repo.symindex.vector_refresh. Tried REUSE_VECTOR_REFRESH_PYTHON, $ROOT/.venv, ${HOME:-}/.venv-lupin-mcp and python3. Set REUSE_VECTOR_REFRESH_PYTHON to one that can." >&2
    exit 1
fi

if [ -n "${REUSE_VECTOR_REFRESH_ENV:-}" ] && [ -r "$REUSE_VECTOR_REFRESH_ENV" ]; then
    set -a
    # shellcheck disable=SC1090
    . "$REUSE_VECTOR_REFRESH_ENV"
    set +a
fi

export LUPIN_ROOT="$ROOT"
# Cron's environment is bare. Default the ConfigurationManager arguments the way run-lupin-arbiter-app.sh does.
export LUPIN_CONFIG_MGR_CLI_ARGS="${LUPIN_CONFIG_MGR_CLI_ARGS:-config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Development}"
exec "$PYTHON" -m cosa.repo.symindex.vector_refresh --root "$ROOT" --python "$PYTHON" "$@"
