#!/usr/bin/env bash
#
# wiki-librarian-tick.sh — the daily wiki-librarian tick, as a command cron can run.
#
# It lints the code wiki against the symbol index, keeps the store's wiki-librarian rows in step with
# the findings, and exports the miss records. One run per local day, from 10:00 on.
#
# Usage:  wiki-librarian-tick.sh [--force] [--install | --uninstall | --status | --print-install]
#   --print-install  print the two cron lines and change nothing
#   --install        write the lines through the shared crontab lock; refused without that lock
#   --uninstall      remove only the lines this tool wrote
#   --status         say whether the lines are present
#
# A Claude seat never installs. --print-install is the form a seat may run. A person installs from the
# main checkout, so the cron lines name that checkout and not a worktree.
#
# Exit codes: 0 nothing due or finished clean, 1 could not finish or install refused, 2 finished with rows held,
#   3 switched off (the INI key `wiki librarian tick enabled` is not true).
set -uo pipefail

# Cron's environment is bare. Nothing below relies on the profile.
export PATH="${WIKI_LIBRARIAN_PATH:-/usr/local/bin:/usr/bin:/bin:${PATH:-}}"

SELF="$( readlink -f "${BASH_SOURCE[0]}" )"
SELF_ROOT="$( cd "$( dirname "$SELF" )/../.." && pwd )"
ROOT="${LUPIN_ROOT:-$SELF_ROOT}"
PYTHON="${WIKI_LIBRARIAN_PYTHON:-$ROOT/.venv/bin/python}"
[ -x "$PYTHON" ] || PYTHON="$( command -v python3 )"

export LUPIN_ROOT="$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$PYTHON" -m cosa.repo.symindex.librarian_tick --root "$ROOT" --python "$PYTHON" "$@"
