#!/usr/bin/env bash
# One-time installer for the dev-server bounce watcher (row 1b4211ac R2).
#
# Renders the systemd USER unit from lupin-bounce-watcher.service (substituting the
# real LUPIN_ROOT), installs it under ~/.config/systemd/user, enables + starts it,
# and turns on lingering so it survives a reboot. After this, the "bounce dev server"
# button in the web clients works without anyone remembering to start a script — a
# courtesy that gets forgotten is exactly the failure row 1b4211ac exists to remove.
#
# Idempotent: re-running re-renders the unit and re-enables it.
#
# USAGE:
#   LUPIN_ROOT=/path/to/lupin ./src/scripts/install-bounce-watcher.sh

set -euo pipefail

if [ -z "${LUPIN_ROOT:-}" ]; then
    echo "ERROR: LUPIN_ROOT is not set — export LUPIN_ROOT=/path/to/project" >&2
    exit 1
fi

TEMPLATE="${LUPIN_ROOT}/src/scripts/lupin-bounce-watcher.service"
WATCHER="${LUPIN_ROOT}/src/scripts/bounce-watcher.sh"
UNIT_NAME="lupin-bounce-watcher.service"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT="${UNIT_DIR}/${UNIT_NAME}"

[ -f "${TEMPLATE}" ] || { echo "ERROR: template not found: ${TEMPLATE}" >&2; exit 1; }
[ -f "${WATCHER}" ]  || { echo "ERROR: watcher not found: ${WATCHER}" >&2; exit 1; }

mkdir -p "${UNIT_DIR}"

# Render the placeholder to the real path. A leftover __LUPIN_ROOT__ would give
# systemd a unit it cannot run, so fail loudly if any survives.
sed "s#__LUPIN_ROOT__#${LUPIN_ROOT}#g" "${TEMPLATE}" > "${UNIT}"
if grep -q "__LUPIN_ROOT__" "${UNIT}"; then
    echo "ERROR: placeholder substitution failed — ${UNIT} still contains __LUPIN_ROOT__" >&2
    exit 1
fi

systemctl --user daemon-reload
systemctl --user enable --now "${UNIT_NAME}"

# Lingering makes the user service start at BOOT, before a login session exists —
# without it the watcher (and the button) only work while ${USER} is logged in.
if command -v loginctl >/dev/null 2>&1; then
    loginctl enable-linger "${USER}" || \
        echo "WARNING: could not enable lingering — run 'sudo loginctl enable-linger ${USER}' so the watcher starts at boot." >&2
fi

echo "Installed + started: ${UNIT_NAME}"
echo "  status: systemctl --user status ${UNIT_NAME}"
echo "  logs:   journalctl --user -u ${UNIT_NAME} -f"
