#!/usr/bin/env bash
# Installer for the Claude Code runaway-memory watcher (store row df5c3696).
#
# WHY THIS EXISTS. The service does NOT run src/cosa/utils/cc_memory_watch.py. It
# runs a copy under ~/.local/lib/lupin-cc-memory-watch, reached via the unit's
# PYTHONPATH. Until now that copy was made BY HAND and nothing reconciled it, so
# editing the tracked module changed nothing about what was sampling memory.
# Measured 2026-08-25: the two agreed only because somebody had copied the file
# across ninety minutes earlier while chasing why a fix had not taken effect.
#
# Deploys the module, renders the unit from lupin-cc-memory-watch.service,
# enables + starts it, and turns on lingering so it survives a reboot.
#
# Idempotent: re-running re-deploys, re-renders and restarts.
#
# ⚠️ RESTARTING INTERRUPTS AN IN-FLIGHT COLLECTION for a few seconds. No samples
# are lost — the unit appends rather than truncates — but if a measurement window
# is being relied on right now, finish it first.
#
# USAGE:
#   LUPIN_ROOT=/path/to/lupin ./src/scripts/install-cc-memory-watch.sh
#   LUPIN_ROOT=... ./src/scripts/install-cc-memory-watch.sh --dry-run
#
# Overridable for testing without touching the live service:
#   DEPLOY_DIR  where the module copy goes   (default ~/.local/lib/lupin-cc-memory-watch)
#   UNIT_DIR    where the unit is installed  (default ~/.config/systemd/user)
#   LOG_DIR     where the streams are kept   (default ~/.claude/sessions)

set -euo pipefail

DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

if [ -z "${LUPIN_ROOT:-}" ]; then
    echo "ERROR: LUPIN_ROOT is not set — export LUPIN_ROOT=/path/to/project" >&2
    exit 1
fi

TEMPLATE="${LUPIN_ROOT}/src/scripts/lupin-cc-memory-watch.service"
MODULE="${LUPIN_ROOT}/src/cosa/utils/cc_memory_watch.py"
UNIT_NAME="lupin-cc-memory-watch.service"

DEPLOY_DIR="${DEPLOY_DIR:-$HOME/.local/lib/lupin-cc-memory-watch}"
UNIT_DIR="${UNIT_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user}"
LOG_DIR="${LOG_DIR:-$HOME/.claude/sessions}"
UNIT="${UNIT_DIR}/${UNIT_NAME}"

[ -f "${TEMPLATE}" ] || { echo "ERROR: template not found: ${TEMPLATE}" >&2; exit 1; }
[ -f "${MODULE}" ]   || { echo "ERROR: module not found: ${MODULE}" >&2; exit 1; }

if [ "${DRY_RUN}" = "1" ]; then
    echo "DRY RUN — nothing will be written."
    echo "  module   ${MODULE}"
    echo "        -> ${DEPLOY_DIR}/cc_memory_watch.py"
    echo "  unit     ${TEMPLATE}"
    echo "        -> ${UNIT}"
    echo "  logs     ${LOG_DIR}/cc-memory-{samples,alerts}.log"
    exit 0
fi

mkdir -p "${DEPLOY_DIR}" "${UNIT_DIR}" "${LOG_DIR}"

# The copy is the whole point of this script; everything below is plumbing.
cp "${MODULE}" "${DEPLOY_DIR}/cc_memory_watch.py"

# A stale .pyc next to a replaced source is its own quiet drift — Python usually
# invalidates on mtime+size, but "usually" is not a guarantee worth carrying on a
# daemon nobody watches.
rm -rf "${DEPLOY_DIR}/__pycache__"

sed -e "s#__LUPIN_ROOT__#${LUPIN_ROOT}#g" \
    -e "s#__DEPLOY_DIR__#${DEPLOY_DIR}#g" \
    -e "s#__LOG_DIR__#${LOG_DIR}#g" \
    "${TEMPLATE}" > "${UNIT}"

# A surviving placeholder gives systemd a unit it cannot run, and the failure
# would surface as a dead watcher rather than an install error. Fail here instead.
if grep -q "__LUPIN_ROOT__\|__DEPLOY_DIR__\|__LOG_DIR__" "${UNIT}"; then
    echo "ERROR: placeholder substitution failed — ${UNIT} still contains a __PLACEHOLDER__" >&2
    exit 1
fi

systemctl --user daemon-reload
systemctl --user enable --now "${UNIT_NAME}"
systemctl --user restart "${UNIT_NAME}"

# Lingering makes the user service start at BOOT rather than at login. Without it
# the watcher does not come back until somebody logs in — and on this box the
# median morning boot is 09:24, so that gap swallows the start of the working day.
if command -v loginctl >/dev/null 2>&1; then
    loginctl enable-linger "${USER}" || \
        echo "WARNING: could not enable lingering — run 'sudo loginctl enable-linger ${USER}' so the watcher starts at boot." >&2
fi

echo "Installed + started: ${UNIT_NAME}"
echo "  deployed: ${DEPLOY_DIR}/cc_memory_watch.py"
echo "  samples:  ${LOG_DIR}/cc-memory-samples.log"
# Point at the SANCTIONED runner, never a bare python3 -m pytest. A bare python3
# is whatever is on PATH; under-provisioned it under-collects and reports the
# reduced count as the whole suite (rows c98bce3f, fc74c1d4). A printed command
# is one somebody will paste, so it has to be the right one.
echo "  verify:   ./src/tests/run-unit-tests.sh -k cc_memory_watch_deploy_parity"
