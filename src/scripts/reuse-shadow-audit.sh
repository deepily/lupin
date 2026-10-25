#!/usr/bin/env bash
#
# reuse-shadow-audit.sh — the shadow audit's daily drain, as a command cron can run.
#
# It runs the queued audits through the full search, under the token ceiling in the INI key
# `reuse shadow audit max tokens per drain`. The job is off until the INI key `reuse shadow audit enabled`
# is true, and it refuses to run while the ceiling key is blank.
#
# Usage:  reuse-shadow-audit.sh [--install | --uninstall | --status | --print-install]
#   --print-install  print the two cron lines and change nothing
#   --install        write the lines through the shared crontab lock; refused without that lock
#   --uninstall      remove only the lines this tool wrote
#   --status         say whether the lines are present
#
# A Claude seat never installs. A person installs from the main checkout, so the cron lines name that
# checkout and not a worktree. Set LUPIN_REUSE_JEV_PACK_SIZE to the live server's value before installing.
#
# Exit codes: 0 drained or nothing queued; 1 could not finish or install refused; 2 a named error
#   (a blank ceiling, no pack size); 3 switched off.
set -uo pipefail

export PATH="${REUSE_SHADOW_AUDIT_PATH:-/usr/local/bin:/usr/bin:/bin:${PATH:-}}"

SELF="$( readlink -f "${BASH_SOURCE[0]}" )"
SELF_ROOT="$( cd "$( dirname "$SELF" )/../.." && pwd )"
ROOT="${LUPIN_ROOT:-$SELF_ROOT}"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

PYTHON=""
for CANDIDATE in "${REUSE_SHADOW_AUDIT_PYTHON:-}" "$ROOT/.venv/bin/python" "${HOME:-}/.venv-lupin-mcp/bin/python" "$( command -v python3 || true )"; do
    [ -n "$CANDIDATE" ] && [ -x "$CANDIDATE" ] || continue
    if "$CANDIDATE" -c "import lupin_mcp.reuse_shadow" >/dev/null 2>&1; then PYTHON="$CANDIDATE"; break; fi
    echo "reuse-shadow-audit: $CANDIDATE cannot import lupin_mcp.reuse_shadow; trying the next Python" >&2
done
if [ -z "$PYTHON" ]; then
    echo "reuse-shadow-audit: no Python can import lupin_mcp.reuse_shadow. Set REUSE_SHADOW_AUDIT_PYTHON." >&2
    exit 1
fi

export LUPIN_ROOT="$ROOT"
export LUPIN_CONFIG_MGR_CLI_ARGS="${LUPIN_CONFIG_MGR_CLI_ARGS:-config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Development}"
exec "$PYTHON" -m lupin_mcp.reuse_shadow --root "$ROOT" --python "$PYTHON" "$@"
