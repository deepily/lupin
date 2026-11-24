#!/usr/bin/env bash
#
# claude-login-tick.sh — a timed, read-only check of the dev container's Claude Code login.
#
# Row 807ffebc: the login's REFRESH token reached its own expiry (14:45 EST, 23 Nov 2026). The next job to
# renew (19:06) blanked the file, and every bounded job failed from then on, found two hours later by a user.
# This reads two numbers from the credentials file in the container, the access expiry and the refresh expiry,
# and never a token. It makes no model call, so it costs nothing and cannot blank anything.
#
# Silent (no output, exit 0) while the refresh token has more than CLAUDE_LOGIN_WARN_DAYS (default 7) left.
# Otherwise prints one line naming the problem and the remedy.
#
# Exit codes: 0 fine · 1 could not look (docker down, container stopped) · 2 login blank or refresh token lapsed
#             3 refresh token lapses within the warning window
#
# Usage:  claude-login-tick.sh [container]      (default lupin-rest-dev)
#         claude-login-tick.sh --print-install  (prints the crontab line; a person installs it)
set -uo pipefail
export PATH="${CLAUDE_LOGIN_PATH:-/usr/local/bin:/usr/bin:/bin:${PATH:-}}"   # CLAUDE_LOGIN_PATH replaces PATH outright (tests)
HERE="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" && pwd )"

if [ "${1:-}" = "--print-install" ]; then
    echo "7,37 * * * * ${HERE}/claude-login-tick.sh lupin-rest-dev >> \$HOME/.lupin/logs/claude-login-tick.log 2>&1 # claude-login-tick"
    exit 0
fi

CONTAINER="${1:-lupin-rest-dev}"
fields="$( docker exec "$CONTAINER" python3 -c "import json; v = json.load( open( '/home/rruiz/.claude/.credentials.json' ) )[ 'claudeAiOauth' ]; print( len( v.get( 'refreshToken' ) or '' ), v.get( 'refreshTokenExpiresAt' ) or 0 )" 2>/dev/null )" || { echo "claude-login-tick: cannot read the login in ${CONTAINER}" >&2; exit 1; }
python3 "${HERE}/lib/claude_login_expiry.py" --refresh "${CONTAINER}" ${fields}
