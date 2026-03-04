#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# check-cc-listener-status.sh — Quick status check for CC Notification Listeners
#
# Usage:
#   src/scripts/check-cc-listener-status.sh          # both process + server check
#   src/scripts/check-cc-listener-status.sh --local   # process check only (no server call)
# ─────────────────────────────────────────────────────────────────────

set -euo pipefail

LOCAL_ONLY=false
if [[ "${1:-}" == "--local" ]]; then
    LOCAL_ONLY=true
fi

echo ""
echo "═══ CC Notification Listener Status ═══"
echo ""

# ── 1. Process check ────────────────────────────────────────────────
echo "── Local Processes ──"
PROCS=$( ps aux | grep cc_notification_listener | grep -v grep || true )

if [[ -z "$PROCS" ]]; then
    echo "  (none running)"
else
    echo "$PROCS" | while read -r line; do
        pid=$( echo "$line" | awk '{print $2}' )
        etime=$( ps -p "$pid" -o etime= 2>/dev/null | xargs )
        sid=$( echo "$line" | grep -oP '(?<=--session-id )\S+' || echo "?" )
        echo "  PID $pid  session=$sid  uptime=$etime"
    done
fi

# ── 2. Bridge files ─────────────────────────────────────────────────
echo ""
echo "── Session Bridge Files ──"
BRIDGE_DIR="$HOME/.claude/sessions"
BRIDGES=$( ls "$BRIDGE_DIR"/cc-*.json 2>/dev/null || true )

if [[ -z "$BRIDGES" ]]; then
    echo "  (none)"
else
    for f in $BRIDGES; do
        bpid=$( basename "$f" | sed 's/cc-//;s/.json//' )
        lpid=$( python3 -c "import json; d=json.load(open('$f')); print(d.get('listener_pid','?'))" 2>/dev/null || echo "?" )
        if kill -0 "$bpid" 2>/dev/null; then bstatus="alive"; else bstatus="DEAD"; fi
        if [[ "$lpid" != "?" ]] && kill -0 "$lpid" 2>/dev/null; then lstatus="alive"; else lstatus="DEAD"; fi
        echo "  $f"
        echo "    CC PID=$bpid ($bstatus)  Listener PID=$lpid ($lstatus)"
    done
fi

# ── 3. Server-side WebSocket sessions ───────────────────────────────
if [[ "$LOCAL_ONLY" == true ]]; then
    echo ""
    echo "(skipping server check — use without --local for full status)"
    echo ""
    exit 0
fi

echo ""
echo "── Server WebSocket Sessions (localhost:7999) ──"

python3 - "$HOME/.lupin/credentials.ini" << 'PYEOF'
import configparser, json, sys
try:
    import requests
except ImportError:
    print( "  (requests not installed — pip install requests)" )
    sys.exit( 0 )

cred_file = sys.argv[1]
config    = configparser.ConfigParser()
if not config.read( cred_file ):
    print( f"  No credentials file at {cred_file}" )
    sys.exit( 0 )

try:
    email    = config[ "lupin" ][ "email" ]
    password = config[ "lupin" ][ "password" ]
except KeyError:
    print( f"  Missing [lupin] section in {cred_file}" )
    sys.exit( 0 )

try:
    login = requests.post( "http://localhost:7999/auth/login",
        json={ "email": email, "password": password }, timeout=5 )
    token = login.json()[ "tokens" ][ "access_token" ]
except Exception:
    print( "  Could not authenticate — is the server running?" )
    sys.exit( 0 )

try:
    resp = requests.get( "http://localhost:7999/api/websocket-sessions",
        headers={ "Authorization": f"Bearer {token}" }, timeout=5 )
    data = resp.json()
    for s in data[ "sessions" ]:
        tag = " << LISTENER" if "cc-listener" in s[ "session_id" ] else ""
        print( f'  {s[ "session_id" ]:28s}  connected={s[ "connected" ]}{tag}' )
    print( f'\n  Total: {data[ "total_sessions" ]} sessions, {data[ "unique_users" ]} unique users' )
except Exception as e:
    print( f"  Could not fetch sessions: {e}" )
PYEOF

echo ""
