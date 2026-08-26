#!/usr/bin/env bash
#
# run-lupin-arbiter-app.sh — launch the standalone, OUT-OF-BAND fleet watcher on :8001.
#
# Host-side process, runs OUTSIDE all Docker containers (deploy doc §3, D1).
# Binds 0.0.0.0 (Option 2, 2026-06-08): the :7999/:8000 reverse-proxies run INSIDE
# Docker containers and reach this host process via host.docker.internal (host-gateway).
# A 127.0.0.1 host-loopback bind (the original R3 default) is unreachable from a
# container's separate network namespace. The broader bind is host-firewall-restricted,
# not publicly exposed. reload=False (a watcher must not hot-reload itself).
#
# Supervised by the systemd --user unit in src/lupin_arbiter_app/systemd/ (this
# script is its ExecStart). systemd runs with a MINIMAL, NON-INHERITED env, so we
# set BOTH the interpreter (the project .venv — a bare `python` would resolve to
# system python with no uvicorn) AND LUPIN_CONFIG_MGR_CLI_ARGS (ConfigurationManager
# requires it; without it create_production_app() raises and Restart=always would
# crash-loop forever). Both gaps were caught by Tiffany's clean-env L2 review.
#
set -euo pipefail

if [[ -z "${LUPIN_ROOT:-}" ]]; then
  echo "LUPIN_ROOT not set — export LUPIN_ROOT=/path/to/project" >&2
  exit 1
fi

# Explicit venv interpreter (NOT bare `python` — systemd --user PATH is minimal).
#
# RESOLUTION ORDER (2026-08-10) — first match wins:
#   1. $LUPIN_ARBITER_VENV        explicit override (deploys, tests, odd hosts)
#   2. $HOME/.venvs/lupin-arbiter the standalone host venv's HOME
#   3. $LUPIN_ROOT/.venv          legacy / dev box, where a full project venv lives
#
# WHY 2 EXISTS AND WHY IT COMES BEFORE 3: the arbiter's host venv used to live at
# $LUPIN_ROOT/.venv-arbiter, INSIDE the deploy tree. Every code push runs
# `sudo chown -R 1001:1001` over that tree (lupin-vm.sh; deploy-cloud-test.sh did the
# same until it was retired 2026-08-26, row 0d175dac),
# and uid 1001 does not exist on lupin-host-test — so the venv ended up owned by a
# nonexistent user, unwritable by the service account that runs it. Provisioning it
# in place failed with `PermissionError: RECORD`, and a hand-chown was silently
# reverted by the next deploy. A runtime dependency has no business living in a tree
# that git and the deploy chown out from under it.
# Record: src/rnd/v0.2.0/2026.08.10-arbiter-fleet-loop-silent-death.md
if [[ -n "${LUPIN_ARBITER_VENV:-}" ]]; then
  PYBIN="${LUPIN_ARBITER_VENV}/bin/python"
elif [[ -x "${HOME}/.venvs/lupin-arbiter/bin/python" ]]; then
  PYBIN="${HOME}/.venvs/lupin-arbiter/bin/python"
else
  PYBIN="${LUPIN_ROOT}/.venv/bin/python"
fi
if [[ ! -x "${PYBIN}" ]]; then
  echo "venv python not found/executable at ${PYBIN}" >&2
  echo "  provision it:  src/scripts/provision-arbiter-on-vm.sh" >&2
  echo "  or point at one explicitly:  export LUPIN_ARBITER_VENV=/path/to/venv" >&2
  exit 1
fi
echo "run-lupin-arbiter-app: interpreter ${PYBIN}" >&2

export PYTHONPATH="${LUPIN_ROOT}/src:${PYTHONPATH:-}"

# ConfigurationManager env (systemd's clean env won't inherit it). An explicitly
# pre-set value still wins via `:-` (e.g. a test harness pointing at another block).
# config_path/splainer_path are project-root-relative (the manager prepends root);
# config_block_id uses `+` for the space (the manager's CLI-args format).
export LUPIN_CONFIG_MGR_CLI_ARGS="${LUPIN_CONFIG_MGR_CLI_ARGS:-config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Development}"

cd "${LUPIN_ROOT}/src"

# --factory: create_production_app() builds the real Loop A (health watch) wired
# to the shared :8001-local store. The lifespan start()s the loop on boot.
exec "${PYBIN}" -m uvicorn lupin_arbiter_app.app:create_production_app --factory \
  --host 0.0.0.0 \
  --port 8001 \
  --no-access-log
