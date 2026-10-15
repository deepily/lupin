#!/usr/bin/env bash
# The installer's end-to-end test notification step (rows 80535f46, review of 957ff4af6).
# Sourced by install-cosa-voice.sh; kept here so a test can run it with a stubbed probe.
#
# Needs: pass_check, warn_check, fail_check, SERVER_URL, LUPIN_ROOT, VENV_PYTHON.
# NOTIFY_PROBE overrides the probe path (tests). Sets INSTALL_RC=1 on a failure.
#
# run_test_notification reachable|unreachable
#   probe exit 0 -> delivered, 3 -> SKIPPED (no listener), anything else -> failed.
run_test_notification() {
    if [ "$1" != "reachable" ]; then
        warn_check "Test notification SKIPPED: no server to reach at $SERVER_URL"
        return 0
    fi
    local probe="${NOTIFY_PROBE:-$LUPIN_ROOT/src/scripts/lib/installer_notify_probe.py}"
    local probe_rc=0 result
    echo ""
    echo "  Sending test notification..."
    # `set -e` may be on: capture the code with `||`. 2>&1 keeps the probe's own diagnostics.
    result=$( LUPIN_ROOT="$LUPIN_ROOT" "$VENV_PYTHON" "$probe" "$SERVER_URL" 2>&1 ) || probe_rc=$?
    case "$probe_rc" in
        0) pass_check "Test notification delivered" ;;
        3) warn_check "Test notification SKIPPED: server reached, no listener connected ($result)" ;;
        *) fail_check "Test notification failed ($result)"; INSTALL_RC=1 ;;
    esac
}
