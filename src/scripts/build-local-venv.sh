#!/usr/bin/env bash
# ============================================================================
# build-local-venv.sh — (re)build the host-side developer virtual environment
#
# WHAT THIS PRODUCES
#   A root-level `.venv` (Python 3.13, gitignored) that mirrors the package set
#   baked into the `lupin:1.0.0` Docker dev/test image — built from the SAME
#   root `pyproject.toml` + `uv.lock` — MINUS three native packages the host
#   cannot build and that no host-side code path imports:
#       - pyaudio    (needs the PortAudio system lib; runtime audio only)
#       - flash-attn (needs cuda-toolkit-12-4 / nvcc 12.4; GPU training only)
#       - autoawq    (CUDA quantization kernels; GPU inference only)
#   plus the en_core_web_sm spaCy model (pure-data, installs cleanly on host).
#
# WHY A SUBSET (not a byte-identical mirror)
#   The container gets the three native packages because its Dockerfile
#   apt-installs PortAudio + cuda-toolkit-12-4. The host has neither (driver
#   535 / CUDA 12.2, no nvcc-12.4), and none of the three are imported by the
#   unit tests or the dev scripts (verified) — they only execute at runtime
#   INSIDE the container. Installing a multi-GB CUDA toolkit on the host just
#   to satisfy a `--locked` build of unimported code is wasted, so we omit them
#   here. The production container build recipe (docker/lupin/Dockerfile) is
#   deliberately left UNTOUCHED — it still installs the full set.
#
#   torch stays IN this venv (the cu124 wheel installs without nvcc and runs on
#   driver 535 via CUDA Minor Version Compatibility — `cuda_available == True`).
#
# CONSUMERS OF THIS VENV
#   IDE interpreter, `pytest src/tests/unit/`, the WebSocket smoke runner, and
#   the host dev scripts (notify-claude-*, generate-api-docs.sh, etc.), all of
#   which point at `$LUPIN_ROOT/.venv`.
#
# Requires:
#   - LUPIN_ROOT is set (or this script is run from the repo root)
#   - uv is on PATH (>= 0.8)
#   - network access to PyPI + the pytorch cu124 index
# Ensures:
#   - A fresh $LUPIN_ROOT/.venv built from uv.lock minus the 3 native packages
#   - Never touches the old src/cosa/.venv (kept as a fallback) or the Dockerfile
# ============================================================================
set -euo pipefail

LUPIN_ROOT="${LUPIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
cd "$LUPIN_ROOT"

CU124_INDEX="https://download.pytorch.org/whl/cu124"
REQS="/tmp/lupin-reqs-lean.txt"
OMIT=( pyaudio flash-attn autoawq )

echo "[build-local-venv] LUPIN_ROOT=$LUPIN_ROOT"
echo "[build-local-venv] ensuring uv-managed Python 3.13..."
uv python install 3.13

echo "[build-local-venv] creating fresh .venv (Python 3.13, seeded)..."
rm -rf .venv
uv venv --python 3.13 --seed .venv

echo "[build-local-venv] exporting locked deps minus native packages: ${OMIT[*]}"
EXPORT_ARGS=( --frozen --no-emit-project --no-hashes )
for pkg in "${OMIT[@]}"; do EXPORT_ARGS+=( --no-emit-package "$pkg" ); done
uv export "${EXPORT_ARGS[@]}" -o "$REQS"

echo "[build-local-venv] installing into .venv (cu124 index for torch)..."
UV_PROJECT_ENVIRONMENT=.venv uv pip install --python .venv \
  --extra-index-url "$CU124_INDEX" \
  --index-strategy unsafe-best-match \
  -r "$REQS"

echo "[build-local-venv] installing the en_core_web_sm spaCy model..."
.venv/bin/python -m spacy download en_core_web_sm

echo "[build-local-venv] sanity check..."
.venv/bin/python -c "import torch, fastapi, pydantic, pgvector, transformers, pytest, spacy; \
spacy.load('en_core_web_sm'); \
print('OK | torch', torch.__version__, '| cuda', torch.cuda.is_available())"

echo "[build-local-venv] done. .venv is ready (old src/cosa/.venv left intact as fallback)."
