# syntax=docker/dockerfile:1.7
# ============================================================================
# lupin-model-server runtime image — frozen-code GPU model host
#
# Hosts Whisper + 2 text encoders on :7998 so the compute containers
# (lupin-rest-dev :7999, lupin-rest-test :8000) can run uvicorn --reload
# safely without re-initializing CUDA on every reload.
#
# Mirrors the structural choices of docker/lupin/Dockerfile:
#   - nvidia/cuda:12.4.1-base-ubuntu22.04 (matching CUDA toolkit)
#   - cuda-compat-12-4 PURGED (CRITICAL — same RTX 4090 forward-compat fix
#     as the parent image; without this, cuInit() hits CUDA Error 804 on
#     consumer GPUs)
#   - Non-root user `rruiz` (uid 1001) matching the parent's UID convention
#     so bind-mounted HF caches have consistent ownership
#   - HF_HOME=/home/rruiz/.cache/huggingface
#
# Differs from the parent in being LEAN:
#   - No FastAPI middleware soup, no spaCy, no Playwright, no Lupin app code
#   - Only the lupin_model_server package + its direct Python deps
#   - Target image size < 15 GB (parent is 31.7 GB)
#
# Design doc:
#   src/rnd/v0.1.7/2026.05.16-model-server-carveout/01-design.md
# ============================================================================
FROM nvidia/cuda:12.4.1-base-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

ARG LUPIN_UID=1001
ARG LUPIN_GID=1001
ENV HOME=/home/rruiz
ENV HF_HOME=/home/rruiz/.cache/huggingface
ENV PYTHONPATH=/var/lupin/src

# ============================================================================
# ROOT BLOCK
# ============================================================================

# Purge cuda-compat-12-4 — CRITICAL for RTX 4090 / consumer GPUs.
# See docker/lupin/Dockerfile header for the full diagnosis. Without this,
# nvidia-container-toolkit bind-mounts an R550-class libcuda over the
# system one, engaging Forward-Compat (Tesla-only) and tripping
# CUDA Error 804 on this hardware.
RUN apt-get update && \
    apt-get purge -y cuda-compat-12-4 && \
    rm -rf /usr/local/cuda-12.4/compat /usr/local/cuda/compat && \
    ldconfig && \
    rm -rf /var/lib/apt/lists/*

# Non-root user — uid 1001 matches docker/lupin/Dockerfile so bind-mounted
# HF caches at /home/rruiz/.cache/huggingface have consistent ownership
# between this container and the compute containers.
RUN groupadd -g ${LUPIN_GID} rruiz && \
    useradd -m -u ${LUPIN_UID} -g ${LUPIN_GID} -s /bin/bash rruiz

# Minimal apt deps: Python 3 toolchain + curl for healthcheck + ffmpeg for
# Whisper audio decoding. No build-essentials, no apt-pinned CUDA toolkit
# (already in the base image), no spaCy/Playwright deps.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3.11 \
        python3.11-venv \
        python3-pip \
        curl \
        ffmpeg && \
    rm -rf /var/lib/apt/lists/* && \
    ln -sf /usr/bin/python3.11 /usr/local/bin/python && \
    ln -sf /usr/bin/python3.11 /usr/local/bin/python3

# Python venv at /opt/venv — owned by rruiz so we can pip-install as the
# non-root user without sudo.
RUN python -m venv /opt/venv && chown -R rruiz:rruiz /opt/venv
ENV PATH=/opt/venv/bin:${PATH}

# Lupin app code mount-point (read-only; bind-mounted by compose for
# Whisper warmup MP3 access). Created here so chown doesn't recurse into
# code at build time.
RUN mkdir -p /var/lupin/src && chown -R rruiz:rruiz /var/lupin

# ============================================================================
# USER BLOCK — everything below runs as rruiz
# ============================================================================
USER rruiz
WORKDIR /home/rruiz

# Python deps — pinned to match parent image's torch + cu124 wheel.
# (If parent's pyproject.toml ever bumps torch, this needs a matching bump;
# tracked in design doc R9 risk.)
RUN pip install --no-cache-dir \
        torch==2.6.0 \
        torchaudio==2.6.0 \
        --index-url https://download.pytorch.org/whl/cu124

RUN pip install --no-cache-dir \
        fastapi==0.115.0 \
        uvicorn[standard]==0.32.0 \
        python-multipart==0.0.12 \
        transformers==4.46.0 \
        sentence-transformers==5.2.2 \
        prometheus-client==0.21.0 \
        bcrypt==4.2.0 \
        einops

# Pre-download the 3 models at build time so the container's first
# `/health` reaches 200 in seconds (model files already on disk; only
# `.to(cuda:0)` happens at startup). Files land under HF_HOME and travel
# with the image. Phase 4 will drop these same lines from docker/lupin/Dockerfile.
RUN python -c "from huggingface_hub import snapshot_download; snapshot_download( repo_id='distil-whisper/distil-large-v3' )"
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer( 'nomic-ai/CodeRankEmbed', trust_remote_code=True )"
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer( 'nomic-ai/nomic-embed-text-v1.5', trust_remote_code=True )"

# Copy the model-server package into the image at /var/lupin/src/lupin_model_server.
# PYTHONPATH=/var/lupin/src (set above) makes `import lupin_model_server` work.
# Read-only — code does NOT evolve in this container (freeze property).
COPY --chown=rruiz:rruiz src/lupin_model_server /var/lupin/src/lupin_model_server

# ============================================================================
# Runtime
# ============================================================================
ENV LUPIN_MODEL_SERVER_PORT=7998
EXPOSE 7998

# Healthcheck via Python urllib (no curl baked into the venv layer).
# `start_period: 60s` in docker-compose accounts for the 25-30s model-load window.
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=60s \
    CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://localhost:7998/health', timeout=3).getcode() == 200 else 1)"

CMD ["uvicorn", "lupin_model_server.main:app", "--host", "0.0.0.0", "--port", "7998"]
