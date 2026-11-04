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
# nothing else: the one-line python in the container prints that number, never a token, and no Claude Code
# CLI call is made, because a call would refresh the login and hide the cause.
#
# The helper is found by this file's own directory, so it resolves from any working directory and from a
# caller that sets -e: every command whose failure is a verdict is guarded with || here.

CLAUDE_LOGIN_PROBE_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" && pwd )"

# probe_claude_login
#
# Requires:  $1 = container name; run_cmd, say_ok, say_fail and remedy defined by the caller
# Ensures:   calls say_ok for a valid login, say_fail plus remedy for an expired or unreadable one; returns 0
#            always, so a caller that exits on error is never ended by an expired login
probe_claude_login() {
    local container="$1" expires_ms verdict status detail
    expires_ms="$( run_cmd docker exec "${container}" python3 -c "import json; print( json.load( open( '/home/rruiz/.claude/.credentials.json' ) )[ 'claudeAiOauth' ][ 'expiresAt' ] )" 2>/dev/null )" || expires_ms=""
    verdict="$( python3 "${CLAUDE_LOGIN_PROBE_DIR}/claude_login_expiry.py" "${expires_ms}" )" || true
    status="${verdict%% *}"
    detail="${verdict#* }"
    case "$status" in
        valid)
            say_ok "claude login in ${container} expires ${detail}"
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
