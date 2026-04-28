# syntax=docker/dockerfile:1.7
# ============================================================================
# Lupin runtime image — Tier 0 + Tier 1 hygiene pass + chown elimination
#
#   Tier 0 (delivered 2026-04-26): Python 3.11.5 → 3.13.x (closes CPython #97382 + ~2 yrs CVEs)
#   Tier 1 (delivered 2026-04-26): uv python install (~20 s vs 15 min source build),
#           uv sync --locked (single resolver run vs 20+ pip layers),
#           BuildKit cache mounts, MAX_JOBS as ARG, fail-loud Python patcher
#   Compat fix (delivered 2026-04-27): apt purge cuda-compat-12-4 to fix Error 804 on consumer GPUs
#   Chown elimination (this revision, 2026-04-27):
#       - Single USER rruiz switch after all root work
#       - --chown=rruiz:rruiz on every COPY into rruiz-owned paths
#       - Drops the final `chown -R rruiz:rruiz /home /var/lupin /opt/python /opt/venv` layer
#         (was 31.5 GB of duplicated metadata-rewritten files in lupin:1.0.0)
#       - Playwright system apt deps hardcoded so we drop --with-deps in user-space step
#       - BuildKit cache mount for uv retargeted to /home/rruiz/.cache/uv,uid=1001,gid=1001
#
# Plans:
#   src/rnd/v0.1.7/2026.04.26-dockerfile-cpython-3.11.9-upgrade-to-3.13.13.md
#   src/rnd/v0.1.7/2026.04.27-cuda-driver-vs-image-torch-cu124-mismatch-omit-cuda-compat-12-4.md
#   src/rnd/v0.1.7/2026.04.27-drop-recursive-chown-image-bloat-audit.md
#
# Build (production):
#   docker compose build --no-cache lupin-rest-test
# Build (this iteration, parking tag, no auto-promotion):
#   tar -cf - --exclude=... | DOCKER_BUILDKIT=1 docker build -t lupin:1.0.0-nochown -
#
# Tier 2 (multi-stage builder/runtime, secret mounts, checksum-pinned d2/MARP/Claude Code)
# and Tier 3 (digest-pinned base image, GCS-FUSE for HF models) intentionally
# remain on the existing single-stage / curl|bash / baked-models layout below.
# ============================================================================
FROM nvidia/cuda:12.4.1-base-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

ARG LUPIN_UID=1001
ARG LUPIN_GID=1001
ENV HOME=/home/rruiz
ENV HF_HOME=/home/rruiz/.cache/huggingface

# ============================================================================
# ROOT BLOCK — all root-required setup happens here, in one stretch.
# After this block we `USER rruiz` and never come back.
# ============================================================================

# ----------------------------------------------------------------------------
# Purge cuda-compat-12-4 (CRITICAL for non-Tesla GPUs)
#
# The base image installs cuda-compat-12-4, which drops an R550-class libcuda
# under /usr/local/cuda-12.4/compat/. nvidia-container-toolkit detects this
# directory at container start and bind-mounts those R550 libs over
# /usr/lib/x86_64-linux-gnu/libcuda.so.* — engaging "Forward Compatibility",
# which is restricted to NVIDIA Tesla / data-center GPUs ONLY.
# On consumer GeForce (RTX 4090) or workstation Quadro this throws
# CUDA Error 804: "forward compatibility was attempted on non supported HW".
#
# Removing the compat dir lets the cu124 wheel run on driver >= 525 via
# Minor Version Compatibility (unrestricted by GPU class). Validated on
# RTX 4090 + driver 535.104.05, 2026-04-27.
#
# cuda-compat-12-4 has zero reverse-deps in this image's apt graph; nothing
# pulls it back in transitively, so a single purge step is stable.
# ----------------------------------------------------------------------------
RUN apt-get update && \
    apt-get purge -y cuda-compat-12-4 && \
    rm -rf /usr/local/cuda-12.4/compat /usr/local/cuda/compat && \
    ldconfig && \
    rm -rf /var/lib/apt/lists/*

# ----------------------------------------------------------------------------
# Non-root user
# ----------------------------------------------------------------------------
RUN groupadd -g ${LUPIN_GID} rruiz && \
    useradd -m -u ${LUPIN_UID} -g ${LUPIN_GID} -s /bin/bash rruiz

# ----------------------------------------------------------------------------
# BuildKit cache hygiene: keep apt cache across builds
# (the base image's docker-clean hook would otherwise wipe it)
# ----------------------------------------------------------------------------
RUN rm -f /etc/apt/apt.conf.d/docker-clean && \
    echo 'Binary::apt::APT::Keep-Downloaded-Packages "true";' \
        > /etc/apt/apt.conf.d/keep-cache

# ----------------------------------------------------------------------------
# System dependencies — single layer with BuildKit cache mount.
#
# Required for:
#   - flash-attn / autoawq native compile: build-essential, ninja-build, cuda-toolkit-12-4
#   - pyaudio runtime: portaudio + alsa libs
#   - audio processing runtime: libsndfile1, ffmpeg
#   - TLS/repo plumbing: ca-certificates, curl, wget, gnupg
#   - patch primitive (still kept though .patch was replaced by the python script)
#   - spell check: python3-enchant
#   - Playwright Chromium runtime libs: libnss3..libasound2 (lets us drop
#     `--with-deps` from the user-space `playwright install chromium` step,
#     which would otherwise need root). Hardcoded list derived from
#     `playwright install-deps chromium --dry-run` — refresh when playwright
#     bumps a major version.
#   - Playwright fonts (WG-1, 2026-04-28): the original 3950d0a hardcoded list
#     omitted the fonts that `--with-deps` previously installed. Without them
#     Chromium falls back to system defaults → emoji tofu + metric drift in
#     visual-baseline tests (12 ERRORs in the 2026-04-27 run). Authoritative
#     list re-extracted via `playwright install-deps chromium --dry-run`
#     against the existing image. Refresh when playwright bumps a major.
# ----------------------------------------------------------------------------
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates curl wget git nano rsync gnupg patch \
        build-essential ninja-build \
        cuda-toolkit-12-4 \
        python3-enchant \
        libportaudio2 libportaudiocpp0 portaudio19-dev \
        libasound-dev libsndfile1-dev ffmpeg \
        libnss3 libnspr4 libdbus-1-3 \
        libatk1.0-0 libatk-bridge2.0-0 libatspi2.0-0 libcups2 libdrm2 \
        libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
        libgbm1 libpango-1.0-0 libcairo2 libasound2 \
        libx11-6 libxcb1 libxext6 libwayland-client0 \
        libfontconfig1 libfreetype6 xvfb \
        fonts-noto-color-emoji fonts-unifont xfonts-cyrillic xfonts-scalable \
        fonts-liberation fonts-ipafont-gothic fonts-wqy-zenhei \
        fonts-tlwg-loma-otf fonts-freefont-ttf

# ----------------------------------------------------------------------------
# GitHub CLI via signed apt repo (root, system /usr/bin)
# Moved up into the root block so we don't have to switch USER back later.
# ----------------------------------------------------------------------------
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    mkdir -p -m 755 /etc/apt/keyrings && \
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      -o /etc/apt/keyrings/githubcli-archive-keyring.gpg && \
    chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
      > /etc/apt/sources.list.d/github-cli.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends gh

# ----------------------------------------------------------------------------
# MARP CLI to /usr/local/bin (root, system path)
# Moved up into the root block.
# ----------------------------------------------------------------------------
RUN MARP_VERSION="4.3.1" && \
    wget -q "https://github.com/marp-team/marp-cli/releases/download/v${MARP_VERSION}/marp-cli-v${MARP_VERSION}-linux.tar.gz" \
      -O /tmp/marp-cli.tar.gz && \
    tar -xzf /tmp/marp-cli.tar.gz -C /usr/local/bin/ && \
    chmod +x /usr/local/bin/marp && \
    rm /tmp/marp-cli.tar.gz

# ----------------------------------------------------------------------------
# uv binary into system PATH (everyone can execute)
# ----------------------------------------------------------------------------
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /uvx /usr/local/bin/

# ----------------------------------------------------------------------------
# Pre-create rruiz-owned directories so subsequent USER rruiz steps can write.
# All-empty dirs — sub-kB layer cost — replaces the 31.5 GB recursive chown.
# ----------------------------------------------------------------------------
RUN mkdir -p /opt/python /opt/venv /var/lupin/io /home/rruiz/.claude /home/rruiz/.cache /home/rruiz/.local/bin && \
    chown -R rruiz:rruiz /opt/python /opt/venv /var/lupin /home/rruiz

# ============================================================================
# USER SWITCH — everything below runs as rruiz, files created here are owned
# by rruiz at write time. NO recursive chown at the end.
# ============================================================================
USER rruiz

ENV UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_PYTHON_PREFERENCE=only-managed \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:/opt/python/bin:/home/rruiz/.local/bin:$PATH

# ----------------------------------------------------------------------------
# Python 3.13 from python-build-standalone (pgo+lto, ~20 s)
# Writes to UV_PYTHON_INSTALL_DIR=/opt/python (rruiz-owned)
# ----------------------------------------------------------------------------
RUN uv python install 3.13

# ----------------------------------------------------------------------------
# Application dependencies via uv sync (replaces 20+ separate pip install layers)
#
# Cache mount target retargeted from /root/.cache/uv to /home/rruiz/.cache/uv
# with uid=1001/gid=1001 so the cache is rruiz-owned and uv sync running as
# rruiz can read/write it without permission errors.
# ----------------------------------------------------------------------------
ARG MAX_JOBS=12

WORKDIR /app
COPY --chown=rruiz:rruiz pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/home/rruiz/.cache/uv,uid=1001,gid=1001 \
    uv venv --seed /opt/venv && \
    MAX_JOBS=${MAX_JOBS} FLASH_ATTENTION_FORCE_BUILD=TRUE \
    uv sync --locked --no-install-project

# ----------------------------------------------------------------------------
# spaCy English model + pre-downloaded HF models (Tier 3 will move these
# to GCS-FUSE; Tier 1 keeps them baked).
# Files written to HF_HOME=/home/rruiz/.cache/huggingface (rruiz-owned).
# ----------------------------------------------------------------------------
RUN python -m spacy download en_core_web_sm

RUN python -c "from huggingface_hub import snapshot_download; snapshot_download( repo_id='distil-whisper/distil-large-v3' )"
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer( 'nomic-ai/CodeRankEmbed', trust_remote_code=True )"
RUN python -c "from transformers import AutoModel, AutoTokenizer; AutoModel.from_pretrained( 'nomic-ai/nomic-embed-text-v1.5', trust_remote_code=True ); AutoTokenizer.from_pretrained( 'bert-base-uncased' )"

# ----------------------------------------------------------------------------
# Playwright Chromium browser binary
# No --with-deps — the apt block above already installed the system runtime libs.
# Browser binary lands at /home/rruiz/.cache/ms-playwright (rruiz-owned).
# ----------------------------------------------------------------------------
RUN python -m playwright install chromium

# ----------------------------------------------------------------------------
# pytest-playwright-visual-snapshot import patch — fail-loud, idempotent.
# Replaces a silent `sed -i` that succeeded on context drift.
# Patcher modifies /opt/venv/lib/python3.13/site-packages/pytest_playwright_visual_snapshot/__init__.py
# (rruiz-owned because uv sync ran as rruiz).
# ----------------------------------------------------------------------------
COPY --chown=rruiz:rruiz docker/lupin/scripts/patch-pytest-playwright-visual-snapshot.py /tmp/
RUN python /tmp/patch-pytest-playwright-visual-snapshot.py

# ----------------------------------------------------------------------------
# D2 diagramming CLI (Tier 2 will checksum-pin)
# Installs to /home/rruiz/.local/bin/d2 (rruiz-owned, on PATH).
# ----------------------------------------------------------------------------
RUN curl -fsSL https://d2lang.com/install.sh | sh

# ----------------------------------------------------------------------------
# Claude Code CLI (Tier 2 will switch to signed apt repo)
# Installer respects $HOME — writes to /home/rruiz/.local/bin (rruiz-owned).
# ----------------------------------------------------------------------------
RUN curl -fsSL https://claude.ai/install.sh | bash

# ----------------------------------------------------------------------------
# Runtime configuration
# ----------------------------------------------------------------------------
ENV LUPIN_ROOT=/var/lupin
ENV LUPIN_CONFIG_MGR_CLI_ARGS="config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Development"

# ----------------------------------------------------------------------------
# Application source code (most-volatile layers last for cache reuse).
# All COPYs use --chown=rruiz:rruiz so files land with the correct ownership
# at write time — no later chown layer needed.
# ----------------------------------------------------------------------------
COPY --chown=rruiz:rruiz src/cosa         /var/lupin/src/cosa
COPY --chown=rruiz:rruiz src/fastapi_app  /var/lupin/src/fastapi_app
COPY --chown=rruiz:rruiz src/lib          /var/lupin/src/lib
COPY --chown=rruiz:rruiz src/lupin_cli    /var/lupin/src/lupin_cli
COPY --chown=rruiz:rruiz src/lupin_mcp    /var/lupin/src/lupin_mcp
COPY --chown=rruiz:rruiz src/scripts      /var/lupin/src/scripts
COPY --chown=rruiz:rruiz src/migrations   /var/lupin/src/migrations
COPY --chown=rruiz:rruiz src/docs         /var/lupin/src/docs
COPY --chown=rruiz:rruiz src/resources    /var/lupin/src/resources
COPY --chown=rruiz:rruiz src/templates    /var/lupin/src/templates

COPY --chown=rruiz:rruiz src/conf/*.ini   /var/lupin/src/conf/
COPY --chown=rruiz:rruiz src/conf/*.map   /var/lupin/src/conf/
COPY --chown=rruiz:rruiz src/conf/*.json  /var/lupin/src/conf/
COPY --chown=rruiz:rruiz src/conf/*.js    /var/lupin/src/conf/
COPY --chown=rruiz:rruiz src/conf/auth    /var/lupin/src/conf/auth
COPY --chown=rruiz:rruiz src/conf/keys    /var/lupin/src/conf/keys
COPY --chown=rruiz:rruiz src/conf/mcp     /var/lupin/src/conf/mcp
COPY --chown=rruiz:rruiz src/conf/prompts /var/lupin/src/conf/prompts
COPY --chown=rruiz:rruiz src/conf/tools   /var/lupin/src/conf/tools

COPY --chown=rruiz:rruiz src/conf/long-term-memory/*.csv   /var/lupin/src/conf/long-term-memory/
COPY --chown=rruiz:rruiz src/conf/long-term-memory/*.jsonl /var/lupin/src/conf/long-term-memory/
COPY --chown=rruiz:rruiz src/conf/long-term-memory/*.db    /var/lupin/src/conf/long-term-memory/
# Lance DB intentionally NOT copied — sourced at runtime via host bind-mount
# (./src in docker-compose.yml) or GCS-FUSE in production (Tier 3).
# Was 41 GB of dead weight in lupin:0.9.0 (overlaid by the same bind-mount anyway).

COPY --chown=rruiz:rruiz docker/lupin/claude-config/settings.json /home/rruiz/.claude/settings.json
COPY --chown=rruiz:rruiz docker/lupin/claude-config/mcp.json      /home/rruiz/.claude/.mcp.json

WORKDIR /var/lupin/src

CMD [ "/bin/bash", "/var/lupin/src/scripts/run-fastapi-lupin.sh" ]
