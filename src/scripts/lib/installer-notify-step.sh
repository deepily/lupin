#!/usr/bin/env bash
# The installer's end-to-end test notification step (rows 80535f46, review of 957ff4af6).
# Sourced by install-cosa-voice.sh; kept here so a test can run it with a stubbed probe.
#
# Needs: pass_check, warn_check, fail_check, SERVER_URL, LUPIN_ROOT, VENV_PYTHON.
# NOTIFY_PROBE overrides the probe path (tests). Sets INSTALL_RC=1 on a failure.
#
# run_test_notification
#   Decides reachability itself (curl --head on $SERVER_URL/docs).
#   Unreachable: SKIPPED when the URL is the default; a failure naming the URL when the
#   operator set it (SERVER_URL_EXPLICIT=1), since an explicit target that is down is a
#   deployment error. Reachable: probe exit 0 delivered, 3 SKIPPED (no listener), else failed.
run_test_notification() {
    if ! curl -s --head --max-time 2 "$SERVER_URL/docs" > /dev/null 2>&1; then
        if [ "${SERVER_URL_EXPLICIT:-0}" = "1" ]; then
            fail_check "Test notification failed: the server at $SERVER_URL (set explicitly) cannot be reached"
            INSTALL_RC=1
        else
            warn_check "Test notification SKIPPED: no server to reach at $SERVER_URL"
        fi
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
