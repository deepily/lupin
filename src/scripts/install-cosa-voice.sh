#!/bin/bash
#
# install-cosa-voice.sh — Idempotent cosa-voice MCP onboarding bootstrapper
#
# Registers the cosa-voice MCP server at user scope (global) so it's
# available in every Claude Code session regardless of project directory.
# Auto-detection handles project identification — no MCP_PROJECT needed.
#
# Usage:
#   install-cosa-voice.sh               # Validate + install/update + verify
#   install-cosa-voice.sh --check-only  # Validate and report (no writes)
#   install-cosa-voice.sh --uninstall   # Remove cosa-voice from global config
#   install-cosa-voice.sh --verbose     # Extra diagnostic output
#

set -e

# ── Colors ───────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# ── Parse arguments ──────────────────────────────────────────────────────
MODE="install"
VERBOSE=false

for arg in "$@"; do
    case "$arg" in
        --check-only) MODE="check" ;;
        --uninstall)  MODE="uninstall" ;;
        --verbose)    VERBOSE=true ;;
        --help|-h)
            echo "Usage: install-cosa-voice.sh [--check-only] [--uninstall] [--verbose]"
            echo ""
            echo "Modes:"
            echo "  (default)     Validate + install/update global MCP registration + verify"
            echo "  --check-only  Validate prerequisites and report without writing"
            echo "  --uninstall   Remove cosa-voice from global MCP config"
            echo ""
            echo "Options:"
            echo "  --verbose     Extra diagnostic output"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown argument: $arg${NC}"
            echo "Run with --help for usage"
            exit 1
            ;;
    esac
done

# ── Header ───────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}=========================================="
echo "  cosa-voice MCP Onboarding Bootstrapper"
echo -e "==========================================${NC}"
echo ""

# ── Track results for summary ────────────────────────────────────────────
PASS_COUNT=0
FAIL_COUNT=0
WARN_COUNT=0

pass_check() {
    echo -e "  ${GREEN}✓${NC} $1"
    PASS_COUNT=$((PASS_COUNT + 1))
}

fail_check() {
    echo -e "  ${RED}✗${NC} $1"
    FAIL_COUNT=$((FAIL_COUNT + 1))
}

warn_check() {
    echo -e "  ${YELLOW}⚠${NC} $1"
    WARN_COUNT=$((WARN_COUNT + 1))
}

# ══════════════════════════════════════════════════════════════════════════
# PREREQUISITE CHECKS (all modes)
# ══════════════════════════════════════════════════════════════════════════

echo -e "${CYAN}Prerequisite Checks${NC}"
echo ""

# 1. LUPIN_ROOT
if [ -z "$LUPIN_ROOT" ]; then
    fail_check "LUPIN_ROOT not set"
    echo ""
    echo "    Add to ~/.bashrc or ~/.zshrc:"
    echo "      export LUPIN_ROOT=\"/path/to/lupin\""
    echo ""
    exit 1
elif [ ! -d "$LUPIN_ROOT" ]; then
    fail_check "LUPIN_ROOT directory does not exist: $LUPIN_ROOT"
    exit 1
else
    pass_check "LUPIN_ROOT = $LUPIN_ROOT"
fi

# 2. CC-integration venv (LUPIN_CC_VENV)
# The MCP server + the 7 python hooks run as the OPERATOR in their Claude Code
# session — NOT as the app or the arbiter. They need a venv the operator OWNS,
# holding just the host closure (fastmcp/requests/pydantic). On the dev box that
# is $LUPIN_ROOT/.venv (operator-owned). On the GCP test VM, $LUPIN_ROOT/.venv is
# a symlink -> .venv-arbiter (uid-1001, the arbiter's venv) — registering against
# it mis-points the whole CC integration (missing deps + unwritable). So the venv
# is resolved from LUPIN_CC_VENV (default $LUPIN_ROOT/.venv, per-machine override),
# PROVISIONED here (create + install the closure), and guarded against a foreign
# service venv. See task 81a24c93.
CC_VENV_REQS="fastmcp==2.14.2 requests pydantic regex pytz"   # host closure — cosa_voice_mcp.py + the 8 hooks + their TRANSITIVE in-repo chain (cosa.utils.util pulls regex; config/tz pulls pytz). Confirmed complete 2026-07-24 by MCP connecting (30 tools) on the VM. Everything else is stdlib or in-repo via PYTHONPATH.
LUPIN_CC_VENV="${LUPIN_CC_VENV:-$LUPIN_ROOT/.venv}"

# Preflight: refuse a CC venv that is a symlink into a foreign-uid service venv
# (catches the arbiter-symlink collision loudly instead of a cryptic permission /
# ModuleNotFound failure at first hook fire).
if [ -L "$LUPIN_CC_VENV" ]; then
    link_target="$( readlink -f "$LUPIN_CC_VENV" )"
    venv_uid="$( stat -c '%u' "$link_target" 2>/dev/null )"
    if [ -n "$venv_uid" ] && [ "$venv_uid" != "$( id -u )" ]; then
        fail_check "LUPIN_CC_VENV ($LUPIN_CC_VENV) is a symlink -> $link_target owned by uid $venv_uid (you are uid $( id -u ))"
        echo ""
        echo "    That is another service's venv (e.g. the arbiter's .venv-arbiter) — do NOT register against it."
        echo "    Point LUPIN_CC_VENV at a venv you own and re-run:"
        echo "      LUPIN_CC_VENV=\$HOME/.venv-lupin-mcp bash $0"
        echo ""
        exit 1
    fi
fi

VENV_PYTHON="$LUPIN_CC_VENV/bin/python"
if [ ! -f "$VENV_PYTHON" ]; then
    echo "  Provisioning CC venv at $LUPIN_CC_VENV (Python 3.13)..."
    if command -v uv &> /dev/null; then
        uv venv "$LUPIN_CC_VENV" --python 3.13          || { fail_check "uv venv failed for $LUPIN_CC_VENV"; exit 1; }
        uv pip install --python "$VENV_PYTHON" $CC_VENV_REQS || { fail_check "CC venv dependency install failed"; exit 1; }
    else
        python3 -m venv "$LUPIN_CC_VENV"                 || { fail_check "python3 -m venv failed for $LUPIN_CC_VENV"; exit 1; }
        "$VENV_PYTHON" -m pip install --quiet --upgrade pip
        "$VENV_PYTHON" -m pip install $CC_VENV_REQS      || { fail_check "CC venv dependency install failed"; exit 1; }
    fi
    pass_check "CC venv provisioned: $LUPIN_CC_VENV"
else
    # Pre-existing venv — ensure the closure is present (idempotent, cheap no-op if satisfied).
    if command -v uv &> /dev/null; then
        uv pip install --python "$VENV_PYTHON" $CC_VENV_REQS > /dev/null 2>&1 || true
    fi
    pass_check "CC venv found: $LUPIN_CC_VENV"
fi

# Persist LUPIN_CC_VENV so hook subprocesses + fresh shells resolve the SAME
# interpreter (the hooks fall back to $LUPIN_ROOT/.venv when it is unset). Only
# when non-default, to keep the dev-box ~/.bashrc clean.
if [ "$LUPIN_CC_VENV" != "$LUPIN_ROOT/.venv" ]; then
    CC_VENV_EXPORT="export LUPIN_CC_VENV=$LUPIN_CC_VENV"
    grep -qxF "$CC_VENV_EXPORT" "$HOME/.bashrc" 2>/dev/null || echo "$CC_VENV_EXPORT" >> "$HOME/.bashrc"
fi

# 3. MCP server file
MCP_SERVER="$LUPIN_ROOT/src/lupin_mcp/cosa_voice_mcp.py"
if [ ! -f "$MCP_SERVER" ]; then
    fail_check "MCP server not found: $MCP_SERVER"
    exit 1
else
    pass_check "MCP server file found"
fi

# 4. Claude CLI
if ! command -v claude &> /dev/null; then
    fail_check "claude CLI not found on PATH"
    echo ""
    echo "    Install Claude Code: https://docs.anthropic.com/en/docs/claude-code"
    echo ""
    exit 1
else
    pass_check "claude CLI available"
fi

# 5. ~/.lupin/config
LUPIN_CONFIG="$HOME/.lupin/config"
if [ ! -f "$LUPIN_CONFIG" ]; then
    fail_check "~/.lupin/config not found"
    echo ""
    echo "    Create it with at minimum:"
    echo "      [environments]"
    echo "      default = local"
    echo ""
    echo "      [local]"
    echo "      api_url = http://localhost:7999"
    echo "      global_notification_recipient = your@email.com"
    echo ""
    exit 1
else
    # Check for [local] section
    if grep -q "^\[local\]" "$LUPIN_CONFIG" 2>/dev/null; then
        pass_check "~/.lupin/config found with [local] section"
    else
        fail_check "~/.lupin/config exists but missing [local] section"
        exit 1
    fi
fi

# 6. Server reachable (soft check)
SERVER_URL="${LUPIN_APP_SERVER_URL:-http://localhost:7999}"
if curl -s --head --max-time 2 "$SERVER_URL/docs" > /dev/null 2>&1; then
    pass_check "Lupin server reachable at $SERVER_URL"
else
    warn_check "Lupin server not reachable at $SERVER_URL (start with run-fastapi-lupin.sh)"
fi

echo ""

# ══════════════════════════════════════════════════════════════════════════
# CHECK EXISTING REGISTRATION
# ══════════════════════════════════════════════════════════════════════════

echo -e "${CYAN}MCP Registration Status${NC}"
echo ""

# Check registration by inspecting config files directly
# NOTE: user-scope MCP servers live in ~/.claude.json top-level "mcpServers",
# NOT in ~/.claude/settings.json. The settings.json file holds hooks/permissions only.
SETTINGS_FILE="$HOME/.claude/settings.json"
USER_CONFIG_FILE="$HOME/.claude.json"
HAS_LOCAL=false
HAS_USER=false

# Check local scope (.mcp.json in cwd)
if [ -f ".mcp.json" ]; then
    if python3 -c "
import json
with open( '.mcp.json' ) as f:
    cfg = json.load( f )
exit( 0 if 'cosa-voice' in cfg.get( 'mcpServers', {} ) else 1 )
" 2>/dev/null; then
        HAS_LOCAL=true
        warn_check "cosa-voice registered at local scope (.mcp.json — will migrate to global)"
    fi
fi

# Check user scope (~/.claude.json top-level mcpServers)
if [ -f "$USER_CONFIG_FILE" ]; then
    if python3 -c "
import json
with open( '$USER_CONFIG_FILE' ) as f:
    cfg = json.load( f )
exit( 0 if 'cosa-voice' in cfg.get( 'mcpServers', {} ) else 1 )
" 2>/dev/null; then
        HAS_USER=true
        pass_check "cosa-voice registered at user scope (global)"
    fi
fi

if [ "$HAS_LOCAL" = false ] && [ "$HAS_USER" = false ]; then
    warn_check "cosa-voice not registered"
fi

# Hook count
HOOK_COUNT=0
if [ -f "$SETTINGS_FILE" ]; then
    # Count hook types that have entries
    HOOK_COUNT=$(python3 -c "
import json
with open( '$SETTINGS_FILE' ) as f:
    s = json.load( f )
hooks = s.get( 'hooks', {} )
count = sum( 1 for v in hooks.values() if isinstance( v, list ) and len( v ) > 0 )
print( count )
" 2>/dev/null || echo "0")
fi

if [ "$HOOK_COUNT" -ge 8 ]; then
    pass_check "Hooks: $HOOK_COUNT/8 registered"
elif [ "$HOOK_COUNT" -gt 0 ]; then
    warn_check "Hooks: $HOOK_COUNT/8 registered (some missing)"
else
    warn_check "Hooks: 0/8 registered"
fi

echo ""

# ══════════════════════════════════════════════════════════════════════════
# MODE-SPECIFIC ACTIONS
# ══════════════════════════════════════════════════════════════════════════

if [ "$MODE" = "check" ]; then
    # ── Check-only mode ──────────────────────────────────────────────
    echo -e "${CYAN}Summary (check-only mode — no changes made)${NC}"
    echo ""
    echo -e "  ${GREEN}✓ Passed${NC}: $PASS_COUNT"
    [ "$WARN_COUNT" -gt 0 ] && echo -e "  ${YELLOW}⚠ Warnings${NC}: $WARN_COUNT"
    [ "$FAIL_COUNT" -gt 0 ] && echo -e "  ${RED}✗ Failed${NC}: $FAIL_COUNT"
    echo ""
    exit 0

elif [ "$MODE" = "uninstall" ]; then
    # ── Uninstall mode ───────────────────────────────────────────────
    echo -e "${CYAN}Uninstalling cosa-voice MCP...${NC}"
    echo ""

    if claude mcp remove cosa-voice 2>/dev/null; then
        pass_check "cosa-voice removed from MCP config"
    else
        warn_check "cosa-voice was not registered (nothing to remove)"
    fi
    echo ""
    echo -e "${GREEN}Done.${NC} Hooks are NOT removed (manage separately in ~/.claude/settings.json)"
    echo ""
    exit 0

else
    # ── Install mode (default) ───────────────────────────────────────
    echo -e "${CYAN}Installing cosa-voice MCP (user scope)...${NC}"
    echo ""

    # Remove stale local-scope registration if present
    if [ "$HAS_LOCAL" = true ]; then
        echo "  Removing local-scope registration..."
        claude mcp remove cosa-voice -s local 2>/dev/null || true
        pass_check "Removed local-scope registration"
    fi

    # Remove existing user-scope registration for idempotent re-add
    if [ "$HAS_USER" = true ]; then
        echo "  Removing existing user-scope registration (will re-add)..."
        claude mcp remove cosa-voice -s user 2>/dev/null || true
    fi

    # Register at user scope (global)
    echo "  Registering at user scope..."
    # NOTE: server name MUST come before -e flags. The claude CLI's -e is variadic
    # and will greedily consume the server name as another env var value otherwise.
    if claude mcp add \
        --scope user \
        --transport stdio \
        cosa-voice \
        -e "PYTHONPATH=$LUPIN_ROOT/src" \
        -e "LUPIN_ROOT=$LUPIN_ROOT" \
        -- "$VENV_PYTHON" "$MCP_SERVER" 2>/dev/null; then
        pass_check "cosa-voice registered at user scope (global)"
    else
        fail_check "Failed to register cosa-voice"
        echo ""
        echo "    Try manually:"
        echo "      claude mcp add --scope user --transport stdio cosa-voice \\"
        echo "        -e \"PYTHONPATH=$LUPIN_ROOT/src\" \\"
        echo "        -e \"LUPIN_ROOT=$LUPIN_ROOT\" \\"
        echo "        -- \"$VENV_PYTHON\" \"$MCP_SERVER\""
        echo ""
        exit 1
    fi

    # ── Install the 8 CC hooks from the canonical in-repo template ────
    # Merges src/conf/claude-code-hooks.json into ~/.claude/settings.json,
    # overwriting ONLY the "hooks" key and preserving every other setting.
    # Commands are $LUPIN_ROOT / $PLANNING_IS_PROMPTING_ROOT relative, so the
    # SAME template ports to any host where those env vars are exported.
    HOOKS_TEMPLATE="$LUPIN_ROOT/src/conf/claude-code-hooks.json"
    echo "  Installing CC hooks (SessionStart, Stop, PreToolUse, ... 8 total)..."
    if [ ! -f "$HOOKS_TEMPLATE" ]; then
        warn_check "Hooks template missing: $HOOKS_TEMPLATE (skipping hook install)"
    else
        mkdir -p "$HOME/.claude"
        [ -f "$SETTINGS_FILE" ] && cp "$SETTINGS_FILE" "$SETTINGS_FILE.bak-$(date +%s)"
        if python3 -c "
import json, os, sys
tmpl = json.load( open( '$HOOKS_TEMPLATE' ) )[ 'hooks' ]
cfg  = '$SETTINGS_FILE'
existing = {}
if os.path.exists( cfg ):
    try:    existing = json.load( open( cfg ) )
    except Exception: existing = {}
existing[ 'hooks' ] = tmpl
json.dump( existing, open( cfg, 'w' ), indent=2 )
print( '  ✓ installed', len( tmpl ), 'hook event-types ->', cfg )
"; then
            pass_check "CC hooks installed (8/8)"
        else
            warn_check "CC hook install failed — merge $HOOKS_TEMPLATE into $SETTINGS_FILE manually"
        fi
    fi

    # ── End-to-end test notification ─────────────────────────────────
    if curl -s --head --max-time 2 "$SERVER_URL/docs" > /dev/null 2>&1; then
        echo ""
        echo "  Sending test notification..."
        TEST_RESULT=$("$VENV_PYTHON" -c "
import sys, os
sys.path.insert( 0, '$LUPIN_ROOT/src' )
os.environ[ 'LUPIN_ROOT' ] = '$LUPIN_ROOT'
from lupin_cli.notifications.notify_user_async import notify_user_async
from lupin_cli.notifications.notification_models import AsyncNotificationRequest, NotificationType, NotificationPriority
try:
    req = AsyncNotificationRequest(
        message='cosa-voice bootstrapper: test notification',
        notification_type=NotificationType.PROGRESS,
        priority=NotificationPriority.LOW,
        sender_id='claude.code@installer.deepily.ai',
        server_url='$SERVER_URL'
    )
    resp = notify_user_async( req )
    print( 'ok' if resp and resp.success else 'fail' )
except Exception as e:
    print( f'fail: {e}' )
" 2>/dev/null || echo "fail")

        if echo "$TEST_RESULT" | grep -q "^ok"; then
            pass_check "Test notification delivered"
        else
            warn_check "Test notification failed ($TEST_RESULT)"
        fi
    fi

    # ── Summary ──────────────────────────────────────────────────────
    echo ""
    echo -e "${BOLD}=========================================="
    echo "  Installation Complete"
    echo -e "==========================================${NC}"
    echo ""
    echo -e "  ${GREEN}✓ Passed${NC}: $PASS_COUNT"
    [ "$WARN_COUNT" -gt 0 ] && echo -e "  ${YELLOW}⚠ Warnings${NC}: $WARN_COUNT"
    [ "$FAIL_COUNT" -gt 0 ] && echo -e "  ${RED}✗ Failed${NC}: $FAIL_COUNT"
    echo ""
    echo "  cosa-voice is now available in ALL Claude Code sessions."
    echo "  Project auto-detection handles identification — no per-project config needed."
    echo ""
    echo "  To verify, start Claude Code and run:"
    echo "    get_session_info()"
    echo ""
    exit 0
fi
