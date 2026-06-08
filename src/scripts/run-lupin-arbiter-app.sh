#!/usr/bin/env bash
#
# run-lupin-arbiter-app.sh — launch the standalone, OUT-OF-BAND fleet watcher on :8001.
#
# Host-side process, runs OUTSIDE all Docker containers (deploy doc §3, D1).
# Binds 127.0.0.1 explicit (R3 — never 0.0.0.0; the :7999 reverse-proxy is the
# only external view path). reload=False (a watcher must not hot-reload itself).
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

# Explicit project-venv interpreter (NOT bare `python` — systemd --user PATH is minimal).
PYBIN="${LUPIN_ROOT}/.venv/bin/python"
if [[ ! -x "${PYBIN}" ]]; then
  echo "venv python not found/executable at ${PYBIN} — create .venv and install requirements" >&2
  exit 1
fi

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
  --host 127.0.0.1 \
  --port 8001 \
  --no-access-log
