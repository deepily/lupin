#!/usr/bin/env bash
#
# claude-login-probe.sh — the Claude Code login expiry probe, as a function shared by three doors.
#
# Source it, then call probe_claude_login <container>. The caller supplies run_cmd, say_ok, say_fail and
# remedy, as preflight-test-secret-probe.sh asks of its caller. The three doors are the test preflight, the
# standalone check-claude-login.sh and the dev bounce.
#
# A container keeps its own Claude Code login in its own volume. Once it expires every Claude Code job in
# that container fails, and the SDK's own text for it is the word "success". This reads the expiry field and
# nothing else: the one-line python in the container prints that number, never a token.
#
# That field is the short-lived access token, about 8 hours. A lapsed one is not a lost login: the CLI renews it
# from the refresh token on its next call. So a lapsed expiry gets one cheap `claude -p` call and a second read,
# and the verdict is "expired" only when that renewal did not move the expiry. Measured 9 Nov 2026 in
# lupin-rest-test with no browser login: expiry 8 Nov 08:02Z, one call, expiry 9 Nov 23:53Z, refresh token kept.
#
# The helper is found by this file's own directory, so it resolves from any working directory and from a
# caller that sets -e: every command whose failure is a verdict is guarded with || here.

CLAUDE_LOGIN_PROBE_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" && pwd )"

# _claude_login_verdict
#
# Requires:  $1 = container name; run_cmd defined by the caller
# Ensures:   prints the helper's one-line verdict ( valid | expired | unreadable, then a detail ) for the expiry now on disk
_claude_login_verdict() {
    local expires_ms
    expires_ms="$( run_cmd docker exec "$1" python3 -c "import json; print( json.load( open( '/home/rruiz/.claude/.credentials.json' ) )[ 'claudeAiOauth' ][ 'expiresAt' ] )" 2>/dev/null )" || expires_ms=""
    python3 "${CLAUDE_LOGIN_PROBE_DIR}/claude_login_expiry.py" "${expires_ms}" || true
}

# probe_claude_login
#
# Requires:  $1 = container name; run_cmd, say_ok, say_fail and remedy defined by the caller
# Ensures:   calls say_ok for a valid login, or for one that a single renewing call made valid; say_fail plus
#            remedy for an expired one that stays expired and for an unreadable one; returns 0
#            always, so a caller that exits on error is never ended by an expired login
#            an unreadable expiry is never renewed: only a lapsed one is
probe_claude_login() {
    local container="$1" verdict status detail renewed=""
    verdict="$( _claude_login_verdict "${container}" )"
    status="${verdict%% *}"
    detail="${verdict#* }"
    if [ "$status" = "expired" ]; then
        run_cmd docker exec "${container}" claude -p "Reply with the single word ok" --max-turns 1 >/dev/null 2>&1 || true
        verdict="$( _claude_login_verdict "${container}" )"
        status="${verdict%% *}"
        detail="${verdict#* }"
        [ "$status" = "valid" ] && renewed=" (renewed from the refresh token)"
    fi
    case "$status" in
        valid)
            say_ok "claude login in ${container} expires ${detail}${renewed}"
            ;;
        expired)
            say_fail "claude login in ${container} expired ${detail}; every Claude Code job there fails until it is renewed"
            remedy "docker exec -it ${container} claude /login   (needs a browser login by the account owner)"
            ;;
        *)
            say_fail "claude login expiry in ${container} could not be read (${detail})"
            remedy "docker exec -it ${container} claude /login   (needs a browser login by the account owner), then run this again"
            ;;
    esac
    return 0
}
