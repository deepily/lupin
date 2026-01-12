# FOR lupin:0.8.0
#FROM python:3.10.12
FROM nvidia/cuda:12.2.2-base-ubuntu22.04

# Install build dependencies and Python 3.11.5 from source
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        wget \
        zlib1g-dev \
        libncurses5-dev \
        libgdbm-dev \
        libnss3-dev \
        libssl-dev \
        libreadline-dev \
        libffi-dev \
        libsqlite3-dev \
        libbz2-dev \
        liblzma-dev \
        tk-dev && \
    wget https://www.python.org/ftp/python/3.11.5/Python-3.11.5.tgz && \
    tar -xzf Python-3.11.5.tgz && \
    cd Python-3.11.5 && \
    ./configure --enable-optimizations && \
    make -j"$(nproc)" && \
    make altinstall && \
    cd .. && \
    rm -rf Python-3.11.5 Python-3.11.5.tgz && \
    apt-get purge -y build-essential wget && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# Ensure 'python3' and 'pip3' point to the new 3.11.5 install
RUN ln -sf /usr/local/bin/python3.11 /usr/bin/python3 && \
    ln -sf /usr/local/bin/pip3.11 /usr/bin/pip3

# Install everything else
RUN apt-get update && apt-get install -y \
    && apt-get install cuda-toolkit-12-2 -y \
    && apt-get install git wget nano rsync python3-enchant pip -y \
    && apt-get install libportaudio2 libportaudiocpp0 portaudio19-dev libasound-dev libsndfile1-dev ffmpeg -y \
    && pip install pyaudio

RUN pip install -U pip

#######################################
# Specific versions needed to support web socket Io
#######################################
#RUN pip install Flask==2.1.3
#RUN pip install Flask-SocketIO==5.0.1
#RUN pip install eventlet==0.30.2
#RUN pip install Werkzeug==2.0.3
#RUN pip install requests==2.31.0

RUN pip install pandas

RUN pip install pydub

RUN pip install pyperclip

# RUN pip install flask_cors

# RUN #pip install duckduckgo-search

# RUN pip install jupyterlab
#
# RUN pip install ipywidgets

RUN pip install tabulate

RUN pip install tiktoken

RUN pip install --upgrade --no-cache-dir openai

# RUN pip install --upgrade --no-cache-dir langchain[llms]

# RUN pip install --upgrade --no-cache-dir wandb

RUN pip install --upgrade --no-cache-dir transformers

RUN pip install --upgrade --no-cache-dir accelerate

RUN pip install --upgrade --no-cache-dir torch

RUN pip install pyaudio

RUN pip install huggingface_hub

RUN pip install --no-cache-dir wheel packaging ninja
ENV MAX_JOBS=12
RUN pip install flash-attn --no-build-isolation

RUN python3 -c "from huggingface_hub import snapshot_download; snapshot_download( repo_id='distil-whisper/distil-large-v3' )"

RUN pip install xmlschema

RUN pip install scikit-learn

RUN pip install autoawq

RUN pip install --no-cache-dir groq google-generativeai

RUN pip install --no-cache-dir lancedb kagiapi tantivy

RUN pip install --no-cache-dir fastapi

RUN pip install --no-cache-dir spacy[lookups]

RUN python3 -m spacy download en_core_web_sm

RUN apt-get update && apt-get install -y curl

RUN pip install --no-cache-dir pydantic[email] pydantic-ai[slim]==0.6.2

RUN pip install --no-cache-dir xmltodict==0.14.2

RUN pip install --no-cache-dir pylance==0.36.0

RUN pip install --no-cache-dir PyJWT==2.10.1 passlib==1.7.4 bcrypt==3.2.2 cffi==2.0.0 pycparser==2.23

RUN pip install --no-cache-dir sqlalchemy==2.0.40 psycopg2-binary==2.9.11


# ============================================================================
# RUNTIME CONFIGURATION (Can be overridden via docker run -e or Cloud Run)
# ============================================================================
# This Docker image is multi-environment capable. The ENV values below are
# DEFAULTS for local development. Override at runtime for test/prod deployments.
#
# EXAMPLES:
#
# Local Development (uses defaults):
#   docker run -p 7999:7999 lupin:latest
#
# Testing Deployment (override at runtime):
#   docker run -p 7999:7999 \
#     -e LUPIN_CONFIG_MGR_CLI_ARGS="config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Testing-GCS" \
#     lupin:latest
#
# Cloud Run Testing Deployment:
#   gcloud run deploy lupin-test \
#     --image gcr.io/PROJECT/lupin:latest \
#     --set-env-vars="LUPIN_ROOT=/app,LUPIN_CONFIG_MGR_CLI_ARGS=config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Testing-GCS"
#
# Cloud Run Production Deployment:
#   gcloud run deploy lupin-prod \
#     --image gcr.io/PROJECT/lupin:latest \
#     --set-env-vars="LUPIN_ROOT=/app,LUPIN_CONFIG_MGR_CLI_ARGS=config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Production"
#
# Available config blocks: Lupin:+Development, Lupin:+Testing, Lupin:+Testing-GCS, Lupin:+Production
# Note: '+' is URL encoding for space - becomes "Lupin: Development" internally
# ============================================================================

env LUPIN_ROOT=/var/lupin
env LUPIN_CONFIG_MGR_CLI_ARGS="config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Development"

# Copy application code selectively (excluding postgresql-dev-data, test artifacts, and separate repos)

# Core application directories
COPY src/cosa /var/lupin/src/cosa
COPY src/fastapi_app /var/lupin/src/fastapi_app
COPY src/lib /var/lupin/src/lib
COPY src/scripts /var/lupin/src/scripts
COPY src/migrations /var/lupin/src/migrations
COPY src/docs /var/lupin/src/docs
COPY src/resources /var/lupin/src/resources
COPY src/templates /var/lupin/src/templates

# Configuration files and directories
COPY src/conf/*.ini /var/lupin/src/conf/
COPY src/conf/*.map /var/lupin/src/conf/
COPY src/conf/*.json /var/lupin/src/conf/
COPY src/conf/*.js /var/lupin/src/conf/
COPY src/conf/auth /var/lupin/src/conf/auth
COPY src/conf/keys /var/lupin/src/conf/keys
COPY src/conf/prompts /var/lupin/src/conf/prompts
COPY src/conf/tools /var/lupin/src/conf/tools

# Long-term-memory files (explicitly excluding postgresql-dev-data directory)
COPY src/conf/long-term-memory/*.csv /var/lupin/src/conf/long-term-memory/
COPY src/conf/long-term-memory/*.jsonl /var/lupin/src/conf/long-term-memory/
COPY src/conf/long-term-memory/*.db /var/lupin/src/conf/long-term-memory/
COPY src/conf/long-term-memory/lupin.lancedb /var/lupin/src/conf/long-term-memory/lupin.lancedb

WORKDIR /var/lupin/src
RUN mkdir -p /var/lupin/io

# ============================================================================
# CLAUDE CODE CLI INSTALLATION (Level 2: Functional MCP Support)
# ============================================================================
# Enables dispatching Claude Code tasks from the Lupin UI with voice tools.
# API key is provided at RUNTIME via: docker run -e ANTHROPIC_API_KEY="..."
# NO secrets are baked into this image.
#
# Usage with prompt-style key input (local dev):
#   read -s -p "Anthropic API Key: " KEY && \
#   docker run -e ANTHROPIC_API_KEY="$KEY" -p 7999:7999 lupin:latest
#
# Usage with GCP Secret Manager (production):
#   gcloud run deploy lupin --set-secrets="ANTHROPIC_API_KEY=anthropic-api-key:latest"
# ============================================================================

# Install Node.js 20.x LTS (required for Claude Code CLI)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI globally (gets latest version at build time)
# To update: rebuild this image. Auto-update disabled for container immutability.
RUN npm install -g @anthropic-ai/claude-code

# Create Claude config directory and copy pre-configured settings
RUN mkdir -p /root/.claude

# Copy MCP configuration (cosa-voice with container paths) and settings
COPY docker/lupin/claude-config/settings.json /root/.claude/settings.json
COPY docker/lupin/claude-config/mcp.json /root/.claude/.mcp.json

# ============================================================================
# END CLAUDE CODE CLI INSTALLATION
# ============================================================================

# CMD ["/bin/bash", "-c", "echo '-- OR -- Run `python3 -m fastapi_app.main` to spin up FastAPI server' && exec /bin/bash"]
# Run the script: /var/lupin/src/scripts/run-fastapi-lupin.sh
CMD [ "/bin/bash", "/var/lupin/src/scripts/run-fastapi-lupin.sh" ]
