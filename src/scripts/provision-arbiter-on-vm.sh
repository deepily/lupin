#!/usr/bin/env bash
#
# provision-arbiter-on-vm.sh — one-script host bring-up of the standalone arbiter
# (:8001) on the GCP test VM (Option B: host `systemd --user`, ratified 2026-06-10).
#
# WHAT THIS DOES (idempotent, re-runnable):
#   1. Validates host prerequisites (LUPIN_ROOT, python3, venv module, docker CLI,
#      and that the running user can read the docker socket — the arbiter shells
#      out to `docker inspect`).
#   2. Creates/refreshes a LIGHT host venv at $LUPIN_ROOT/.venv-arbiter from
#      src/scripts/requirements-arbiter.txt (no torch — see that file's header).
#   3. Stamps the systemd --user unit from src/lupin_arbiter_app/systemd/ with this
#      host's LUPIN_ROOT + config_block_id=Lupin:+Testing-GCS, and installs it to
#      ~/.config/systemd/user/lupin-arbiter-app.service.
#
# WHAT THIS DOES NOT DO (HELD — operator/Rick gate; never actuate a login session
# unprompted, per the systemd README + engagement rules):
#   - `loginctl enable-linger`   (makes the user manager survive logout)
#   - `systemctl --user enable --now lupin-arbiter-app.service`
#   The script PRINTS these as the final manual step.
#
# PREREQUISITES (Phase E, before this runs):
#   - The Lupin repo is cloned/pulled onto the VM data disk and LUPIN_ROOT points
#     at it (e.g. export LUPIN_ROOT=/mnt/lupin-data/lupin).
#   - The running user is in the `docker` group (so `docker inspect` works without
#     sudo). Verify: `id -nG | tr ' ' '\n' | grep -qx docker`.
#   - The cloud-test compose stack is (or will be) up; the arbiter watches the
#     containers named in [Lupin: Testing-GCS] `arbiter health watch containers`.
#
# Design of record:
#   src/rnd/v0.1.8/2026.05.30-gcp-deployment/2026.06.10-m2-arbiter-ride-along-and-vm-cutover.md §2.4
#
set -euo pipefail

CONFIG_BLOCK_ID="${ARBITER_CONFIG_BLOCK_ID:-Lupin:+Testing-GCS}"
VENV_DIR_NAME=".venv-arbiter"

log() { printf '[provision-arbiter] %s\n' "$*"; }
die() { printf '[provision-arbiter] ERROR: %s\n' "$*" >&2; exit 1; }

# --- 1. Prerequisites -------------------------------------------------------
[[ -n "${LUPIN_ROOT:-}" ]] || die "LUPIN_ROOT not set — export LUPIN_ROOT=/path/to/vm/checkout"
[[ -d "${LUPIN_ROOT}/src/lupin_arbiter_app" ]] || die "LUPIN_ROOT=${LUPIN_ROOT} does not look like a Lupin checkout (no src/lupin_arbiter_app)"

command -v python3 >/dev/null 2>&1 || die "python3 not found on PATH"
python3 -c "import venv" 2>/dev/null || die "python3 venv module missing — install python3-venv"
command -v docker  >/dev/null 2>&1 || die "docker CLI not found — the arbiter shells out to 'docker inspect'"

if ! docker info >/dev/null 2>&1; then
  die "cannot reach the docker daemon as $(id -un) — add this user to the 'docker' group (id -nG should list 'docker') and re-login"
fi

UNIT_SRC="${LUPIN_ROOT}/src/lupin_arbiter_app/systemd/lupin-arbiter-app.service"
RUN_SCRIPT="${LUPIN_ROOT}/src/scripts/run-lupin-arbiter-app.sh"
REQS="${LUPIN_ROOT}/src/scripts/requirements-arbiter.txt"
[[ -f "${UNIT_SRC}"   ]] || die "missing systemd unit template: ${UNIT_SRC}"
[[ -f "${RUN_SCRIPT}" ]] || die "missing run script: ${RUN_SCRIPT}"
[[ -f "${REQS}"       ]] || die "missing requirements file: ${REQS}"

# --- 2. Light host venv -----------------------------------------------------
VENV_DIR="${LUPIN_ROOT}/${VENV_DIR_NAME}"
if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  log "creating arbiter venv at ${VENV_DIR}"
  python3 -m venv "${VENV_DIR}"
else
  log "arbiter venv already present at ${VENV_DIR} (reusing)"
fi
log "installing/updating arbiter requirements (light — no torch)"
"${VENV_DIR}/bin/python" -m pip install --quiet --upgrade pip
"${VENV_DIR}/bin/python" -m pip install --quiet -r "${REQS}"

# --- 2b. IMPORT GATE — fail the DEPLOY, not a runtime thread (2026-08-10) -----
# Until today the only verification here was `/health`, which returns 200 even when
# a worker thread is dead. That is exactly how a missing `sqlalchemy` killed the
# fleet-arbiter loop on 2026-08-08 and went unnoticed for two days (third instance
# of the requirements-file-drifts-behind-the-import-graph class; `pyyaml` was the
# second, on this same VM, 2026-07-22).
#
# NOTE the pipe discipline: `cmd | tee` reports TEE's status, not cmd's. This runs
# the checker unpiped and tests $? directly — the same trap silently reported a
# FAILED pip install as exit 0 while this fix was being built.
# Record: src/rnd/v0.2.0/2026.08.10-arbiter-fleet-loop-silent-death.md
CHECKER="${LUPIN_ROOT}/src/scripts/check-arbiter-venv.py"
if [[ -f "${CHECKER}" ]]; then
  log "verifying the venv can import everything the arbiter runs"
  set +e
  LUPIN_ROOT="${LUPIN_ROOT}" \
  PYTHONPATH="${LUPIN_ROOT}/src" \
  LUPIN_CONFIG_MGR_CLI_ARGS="${CONFIG_ARGS_FOR_CHECK:-config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=${CONFIG_BLOCK_ID}}" \
    "${VENV_DIR}/bin/python" "${CHECKER}"
  CHECK_RC=$?
  set -e
  [[ ${CHECK_RC} -eq 0 ]] || die "arbiter venv import check FAILED (exit ${CHECK_RC}) — see the remedy above. Refusing to provision a venv that cannot run the service."
else
  log "WARNING: ${CHECKER} not found — skipping the import gate (older checkout?)"
fi

# The run script hard-codes ${LUPIN_ROOT}/.venv/bin/python. On the VM the arbiter
# venv is .venv-arbiter (the app stack uses the baked image, so there is no full
# .venv on the host). Symlink .venv -> .venv-arbiter ONLY if no .venv exists, so a
# host that genuinely has a full .venv is never clobbered.
if [[ ! -e "${LUPIN_ROOT}/.venv" ]]; then
  log "symlinking ${LUPIN_ROOT}/.venv -> ${VENV_DIR_NAME} (run script expects .venv)"
  ln -s "${VENV_DIR_NAME}" "${LUPIN_ROOT}/.venv"
else
  log "NOTE: ${LUPIN_ROOT}/.venv already exists — leaving it; ensure it can import uvicorn + fastapi"
fi

# --- 3. Stamp + install the systemd --user unit -----------------------------
UNIT_DEST_DIR="${HOME}/.config/systemd/user"
mkdir -p "${UNIT_DEST_DIR}"
UNIT_DEST="${UNIT_DEST_DIR}/lupin-arbiter-app.service"

CONFIG_ARGS="config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=${CONFIG_BLOCK_ID}"

log "stamping unit → ${UNIT_DEST} (LUPIN_ROOT=${LUPIN_ROOT}, config_block_id=${CONFIG_BLOCK_ID})"
# Rewrite the Environment=LUPIN_ROOT line to this host's path, and ensure a
# LUPIN_CONFIG_MGR_CLI_ARGS Environment line exists (override the run script's
# Development default → Testing-GCS). Both edits are idempotent.
awk -v root="${LUPIN_ROOT}" -v cfg="${CONFIG_ARGS}" '
  /^Environment=LUPIN_ROOT=/      { print "Environment=LUPIN_ROOT=" root; next }
  /^Environment=LUPIN_CONFIG_MGR_CLI_ARGS=/ { next }   # drop any stale one; re-add below
  /^ExecStart=/ {
      # QUOTE the value: it contains spaces (config_path=… splainer_path=… config_block_id=…),
      # and systemd splits an UNQUOTED Environment= on whitespace → the var is truncated to the
      # first token → ConfigurationManager gets an incomplete cli_args dict → KeyError at boot,
      # Restart=always crash-loops forever. (Caught live on lupin-host-test 2026-07-22.)
      print "Environment=\"LUPIN_CONFIG_MGR_CLI_ARGS=" cfg "\""
      # rewrite ExecStart absolute path to this host
      print "ExecStart=" root "/src/scripts/run-lupin-arbiter-app.sh"
      next
  }
  { print }
' "${UNIT_SRC}" > "${UNIT_DEST}"

systemctl --user daemon-reload 2>/dev/null || log "NOTE: 'systemctl --user daemon-reload' unavailable in this shell — run it after login"

log "DONE — venv + unit installed. Verify the unit:"
log "  grep -E 'Environment=|ExecStart=' ${UNIT_DEST}"

cat <<EOF

================================================================================
HELD — operator/Rick steps (NOT run by this script; actuates the login session):

  # survive logout so the watcher runs ~24/7 (may need sudo on first grant)
  loginctl enable-linger "\$USER"

  # enable + start the arbiter on :8001
  systemctl --user enable --now lupin-arbiter-app.service

  # verify liveness (ops check, not a test surface)
  systemctl --user status lupin-arbiter-app.service
  python3 -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=3).read())"

Bounce-survival check (the out-of-band guarantee): restarting an app container
must NOT affect :8001 —
  docker restart lupin-rest-cloud-test && \\
  python3 -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=3).read())"
================================================================================
EOF
