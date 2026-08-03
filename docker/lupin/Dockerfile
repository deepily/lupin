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

# ============================================================================
# CODE DELIVERY — BAKE_CODE build arg (added 2026-07-12, Rick's voice ruling)
#
# DOCTRINE: containers shipped to TESTING carry NO application code. The image
# is dependencies + runtime environment ONLY; the code a testing container runs
# is a bind-mounted static snapshot of a committed ref, materialized at deploy
# time and refreshable by re-materializing + restart — never by an image rebuild.
# "Not shadowed — ABSENT." Production is explicitly OUT OF SCOPE (postponed).
# Plan of record: src/rnd/2026.07.12-gcp-bind-mount-revert-plan.md §3b + §4b.
#
#   BAKE_CODE=off  (DEFAULT) → codeless image. /var/lupin/src is an EMPTY
#                              mountpoint. Deps venv, HF models, playwright,
#                              CLI tooling all present. Requires a ./src bind
#                              mount to run — see FAIL-LOUD below.
#   BAKE_CODE=on             → legacy baked tree (the pre-2026-07-12 layout),
#                              preserved for the postponed production decision.
#                              Build with: docker build --build-arg BAKE_CODE=on
#
# Docker has no conditional COPY, so the flag is implemented as a FROM-selector:
# two variant stages over a shared `runtime-base`, and `FROM code-${BAKE_CODE}`
# picks one. BuildKit prunes the unselected stage, so a codeless build also skips
# the multiplexer-builder stage entirely (nothing references it).
#
# FAIL-LOUD (intended contract, not a defect): with BAKE_CODE=off and no ./src
# bind mount, CMD runs a script that does not exist → bash exits 127 immediately
# ("No such file or directory"). A missing or mis-pointed mount is now a loud,
# instant failure instead of a silent run against stale baked code — the exact
# mount-shadow trap this ruling exists to close. The mount is MANDATORY.
#
# MOUNT SOURCES MUST CARRY THE MUX BUNDLE: with no baked code, the cross-stage
# COPY of the multiplexer dist/ (see the code-on stage) does not run, so the
# bind-mount SOURCE must already contain src/lupin_app/static/dist/multiplexer/.
# dist/ is BOTH .gitignore'd and .dockerignore'd, so a `git archive`-based deploy
# will NOT carry it — the deploy step must run src/scripts/build-multiplexer.sh
# against the mount source (or rsync a locally-built dist/ alongside the archive)
# or the multiplexer 404s on boot. Local dev/test are unaffected: they mount the
# live working tree, which holds a built dist/.
# ============================================================================
ARG BAKE_CODE=off

# ============================================================================
# STAGE 0 — multiplexer bundle builder (Node + esbuild → dist/)
#
# Produces src/lupin_app/static/dist/multiplexer/{boot.js, boot.<hash>.js,
# boot.js.map, manifest.json} from the checked-in TypeScript sources.
#
# WHY a dedicated stage: dist/ is .gitignore'd AND .dockerignore'd (line 77),
# so the build context NEVER carries a prebuilt bundle. Without this stage the
# final image ships no boot.js and the multiplexer 404s on boot in prod. This
# stage regenerates the bundle deterministically (same esbuild driver the dev
# loop uses, src/scripts/build-multiplexer.sh) and the runtime stage COPYs the
# fresh dist/ across the stage boundary.
#
# Build context needs (all present, none .dockerignore'd): package.json,
# package-lock.json, src/scripts/build-multiplexer.sh, and the TS sources under
# src/lupin_app/static/js/multiplexer/. npm ci installs both deps (xstate) and
# devDeps (esbuild) — NODE_ENV is left unset so devDeps are included.
# ============================================================================
FROM node:22-bookworm-slim AS multiplexer-builder
WORKDIR /build

# Manifest + lockfile first so the npm-ci layer caches across source-only edits.
COPY package.json package-lock.json ./
RUN npm ci

# TS sources + the esbuild driver (build-multiplexer.sh resolves PROJECT_ROOT
# from its own location: src/scripts/../.. == /build).
COPY src/scripts/build-multiplexer.sh ./src/scripts/build-multiplexer.sh
COPY src/lupin_app/static/js/multiplexer ./src/lupin_app/static/js/multiplexer
RUN npm run build

# ============================================================================
# RUNTIME BASE — dependencies + runtime environment ONLY. No application code
# is ever added in this stage; both BAKE_CODE variants build on top of it.
# ============================================================================
FROM nvidia/cuda:12.4.1-base-ubuntu22.04 AS runtime-base

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
#   - fonts-dejavu-core / -extra (bug a5559b49, 2026-06-30): the WG-1 dry-run
#     list ALSO omitted DejaVu, which `--with-deps` used to pull in. Lupin's CSS
#     stacks all terminate in the generic `sans-serif` (named fonts -apple-system
#     / Segoe UI / Roboto / Helvetica Neue do not exist on Linux), so fontconfig
#     falls through to the terminal generic. WITHOUT DejaVu, `sans-serif` resolves
#     to fonts-wqy-zenhei (WenQuanYi Zen Hei — a CJK face) IN THE CONTAINER, while
#     the HOST (which has fonts-dejavu-core) resolves to DejaVu Sans. Every page's
#     body text then renders in a different typeface container-vs-host → ALL 37
#     visual baselines mismatch (baselines are host-captured). Adding DejaVu makes
#     `fc-match sans-serif` → DejaVu Sans in the container, matching the host and
#     the host-captured baselines. Guarded by src/tests/e2e_ui/test_render_env_fingerprint.py.
#     Root-cause: src/rnd/v0.1.9/2026.06.30-visual-regression-env-drift-root-cause.md
#   - libfreetype6 CONTAINER-CANONICAL (task 47e0dfa9 / 6975970a residual, 2026-07-01):
#     libfreetype6 is intentionally left UNPINNED here — the container's freetype patch
#     level (currently 2.11.1+dfsg-1ubuntu0.3) is the AUTHORITATIVE baseline rasterizer.
#     Visual baselines are captured in-container (Option-1, 6975970a: 37/37 green) and the
#     :8000 merge gate renders in-container, so container-vs-baseline is always aligned.
#     The host dev box sits one security-patch behind (…0.2); that patch delta is a benign
#     AA glyph-edge axis (~0.1px), so HOST-side `-k visual` dev runs are NON-AUTHORITATIVE
#     (informational only — trust the :8000 gate). We deliberately do NOT pin both sides:
#     downgrading the container to …0.2 would REVERT a security update (and …0.2 is gone
#     from the apt security pocket), and upgrading the host is a non-reproducible box
#     mutation. The fingerprint guard asserts freetype MAJOR only for exactly this reason
#     (a full-version pin would false-fail the intentionally-unaligned host). Decision:
#     src/rnd/v0.1.9/2026.06.30-visual-regression-env-drift-root-cause.md §Resolution (Option-2).
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
        fonts-dejavu-core fonts-dejavu-extra \
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
# Claude Code CLI — symlinked from the claude-agent-sdk bundled binary
# (pinned via uv.lock). One hash-pinned binary serves both the SDK runtime
# and interactive `claude`; no drift, no extra fetch.
# ----------------------------------------------------------------------------
RUN ln -sf "$(python -c 'import claude_agent_sdk as m, pathlib as p; print(p.Path(m.__file__).parent / "_bundled" / "claude")')" /home/rruiz/.local/bin/claude

# ----------------------------------------------------------------------------
# TEST-TIER TOOLCHAIN — tmux, node, terraform  (rows 719962ed / b5b6d252)
#
# WHY THIS EXISTS. The scheduled :8000 unit tier runs INSIDE this image, and a
# growing set of tests under src/tests/unit/ depend on these three binaries.
# Without them the tier did not merely go red — it went SILENT:
#
#     6 assertions SKIPPED on "tmux is not installed"  (test_killtrace_probe x4,
#       test_tmux_socket_precedence x2) with NO watchdog naming the loss
#     1 assertion SKIPPED on terraform  (test_envs_test_passes_terraform_validate —
#       this one DOES have a watchdog, test_terraform_binary_is_installed)
#     the entire `typescript` tier reduced to 76 bytes: "exec: npx: not found"
#
# A skip is invisible in an 11,000-test run. That is precisely the modules.bats
# disease test_terraform_invariants.py was written to kill, reproduced inside the
# gate meant to catch it. Measured 2026-07-27 (Krishna) at HEAD ee3078c0:
#     without these  1 failed, 18 passed,  6 skipped
#     with these    25 passed,  0 skipped
#
# ⛔ gcloud AND bq ARE DELIBERATELY ABSENT — DO NOT ADD THEM TO "FIX" A RED.
# test_pilot_ac_instruments::test_every_ac_register_entry_matches_the_host
# attests that THE OPERATOR HOST carries them (its own header: "IT MEANS 'THE TOOL
# IS ON THIS HOST'", "Venue: :7999-eligible"). Installing them here turns that test
# green while the claim it encodes — about a metered-billing pilot's host — goes
# unverified. Its 5 reds in the container are honest and must stay until the tier
# enforces the venue each test declares. Ruled by Mr. Radio 🦉 2026-07-27.
#
# LATE LAYER ON PURPOSE: the main apt block sits above the HF model downloads, so
# amending it would re-run multi-GB fetches for three small binaries. Versions are
# pinned to the dev host (node v22.15.0 / terraform v1.12.2) per the host-vs-
# container drift lesson at the visual-regression block above.
#
# ⚠️ node ALONE IS NOT SUFFICIENT for the typescript tier. node_modules is in
# .dockerignore and is NOT baked; the tier resolves `npx c8` / `npx tsx` from a
# bind mount (docker-compose.yml, lupin-rest-test). Binary present != tier runnable.
# ----------------------------------------------------------------------------
USER root
ARG NODE_VERSION=22.15.0
ARG TERRAFORM_VERSION=1.12.2
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends tmux unzip && \
    curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" \
        | tar -xJ -C /opt && \
    ln -sf "/opt/node-v${NODE_VERSION}-linux-x64/bin/node" /usr/local/bin/node && \
    ln -sf "/opt/node-v${NODE_VERSION}-linux-x64/bin/npm"  /usr/local/bin/npm  && \
    ln -sf "/opt/node-v${NODE_VERSION}-linux-x64/bin/npx"  /usr/local/bin/npx  && \
    curl -fsSL -o /tmp/terraform.zip \
        "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip" && \
    unzip -qo /tmp/terraform.zip -d /usr/local/bin && \
    chmod +x /usr/local/bin/terraform && \
    rm -f /tmp/terraform.zip
USER rruiz

# ----------------------------------------------------------------------------
# Runtime configuration
# ----------------------------------------------------------------------------
ENV LUPIN_ROOT=/var/lupin
# config_path / splainer_path are PROJECT-ROOT-RELATIVE (start "/src/…") per the PATH
# MANAGEMENT mandate: ConfigurationManager combines them with the project root
# (LUPIN_ROOT=/var/lupin) at runtime. An ABSOLUTE "/var/lupin/src/conf/…" here
# double-prefixes to "/var/lupin/var/lupin/src/conf/…" → AssertionError at boot.
# Dev/test masked it via the docker-compose env-override; GCP (no override) hit it
# → app wouldn't boot. Baked default must be self-consistent (boots with no crutch).
ENV LUPIN_CONFIG_MGR_CLI_ARGS="config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Development"

# ============================================================================
# CODE VARIANT: code-off (DEFAULT) — the CODELESS image.
#
# Deliberately empty: NO application source is added. /var/lupin/src exists only
# as the empty mountpoint the final stage's WORKDIR creates, to be filled by the
# ./src bind mount at (re)spin time. Without that mount the container fails loud
# at CMD (exit 127) — the intended contract. See the BAKE_CODE header block.
# ============================================================================
FROM runtime-base AS code-off

# ============================================================================
# CODE VARIANT: code-on — the LEGACY BAKED tree (pre-2026-07-12 layout).
#
# Preserved verbatim behind the build arg for the postponed production decision
# (plan doc §6). Application source code, most-volatile layers last for cache
# reuse. All COPYs use --chown=rruiz:rruiz so files land with the correct
# ownership at write time — no later chown layer needed.
# ============================================================================
FROM runtime-base AS code-on

COPY --chown=rruiz:rruiz src/cosa         /var/lupin/src/cosa
COPY --chown=rruiz:rruiz src/lupin_app  /var/lupin/src/lupin_app
# Multiplexer production bundle — layered on top of src/lupin_app from the
# Stage-0 builder. dist/ is .dockerignore'd so the COPY src/lupin_app above
# carries NO dist; this cross-stage COPY supplies the freshly-built bundle.
COPY --chown=rruiz:rruiz --from=multiplexer-builder \
     /build/src/lupin_app/static/dist/multiplexer \
     /var/lupin/src/lupin_app/static/dist/multiplexer
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
# NOTE: src/conf/keys is intentionally NOT copied (Phase-1 secret hygiene, D8).
# Keys arrive at runtime via Secret Manager (see cloud-run-setup-secrets.sh).
# The directory is also excluded from the build context in .dockerignore.
COPY --chown=rruiz:rruiz src/conf/mcp     /var/lupin/src/conf/mcp
COPY --chown=rruiz:rruiz src/conf/prompts /var/lupin/src/conf/prompts
COPY --chown=rruiz:rruiz src/conf/tools   /var/lupin/src/conf/tools

COPY --chown=rruiz:rruiz src/conf/long-term-memory/*.csv   /var/lupin/src/conf/long-term-memory/
COPY --chown=rruiz:rruiz src/conf/long-term-memory/*.jsonl /var/lupin/src/conf/long-term-memory/
COPY --chown=rruiz:rruiz src/conf/long-term-memory/*.db    /var/lupin/src/conf/long-term-memory/
# Lance DB intentionally NOT copied — sourced at runtime via host bind-mount
# (./src in docker-compose.yml) or GCS-FUSE in production (Tier 3).
# Was 41 GB of dead weight in lupin:0.9.0 (overlaid by the same bind-mount anyway).

# ============================================================================
# FINAL — selects the code variant via the BAKE_CODE build arg (default: off).
# Everything below is code-INDEPENDENT: container tooling config, the agy CLI,
# the workdir/mountpoint, and the entrypoint. Both variants share it verbatim.
# ============================================================================
FROM code-${BAKE_CODE} AS final

# Container tooling config for the in-container Claude Code CLI. NOT application
# source — a sanctioned residual under the codeless doctrine (it configures the
# tool, it is not code the app runs).
COPY --chown=rruiz:rruiz docker/lupin/claude-config/settings.json /home/rruiz/.claude/settings.json
COPY --chown=rruiz:rruiz docker/lupin/claude-config/mcp.json      /home/rruiz/.claude/.mcp.json

# ----------------------------------------------------------------------------
# agy — Google Antigravity CLI (v1.1.1), baked as one of the LAST layers so it
# stays cache-cheap. Claude Code running inside this container shells out to
# `agy` as a subprocess to hand off grunt / token-burning work to Gemini.
# Installed at /usr/local/bin so it is callable from any WORKDIR. The 173MB
# binary is staged OUTSIDE git at docker/lupin/bin/agy (.gitignore'd; NOT
# .dockerignore'd, so it rides the build context). Writing to /usr/local/bin
# needs root — the tail runs as USER rruiz — so briefly switch to root for the
# COPY, then back to rruiz.
# ----------------------------------------------------------------------------
USER root
COPY --chmod=0755 docker/lupin/bin/agy /usr/local/bin/agy
USER rruiz

# Creates /var/lupin/src when BAKE_CODE=off — the EMPTY mountpoint the ./src
# bind mount lands on. (Deliberately not added to the root-block mkdir: that
# layer sits above ~31 GB of deps/model layers and touching it would invalidate
# all of them for zero functional gain.)
WORKDIR /var/lupin/src

# FAIL-LOUD: under BAKE_CODE=off with no ./src mount, this script does not exist
# → bash exits 127 immediately. That is the contract, not a bug: a missing or
# mis-pointed mount must fail instantly rather than silently run stale code.
CMD [ "/bin/bash", "/var/lupin/src/scripts/run-fastapi-lupin.sh" ]
