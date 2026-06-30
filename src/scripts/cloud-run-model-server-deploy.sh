#!/bin/bash
#################################################################
# cloud-run-model-server-deploy.sh
#
# Purpose: Build the lupin-model-server GPU image, push it to Artifact
#          Registry, and deploy it to Cloud Run as an L4-GPU,
#          scale-to-zero inference service (Whisper + 2 text encoders).
#
# This is the GPU-service sibling of cloud-run-deploy.sh (which deploys
# the CPU-only app). It mirrors that script's structure and reuses the
# shared cloud-run-config.sh resolver, adding the Cloud Run GPU flags:
#   --gpu=1 --accelerator=nvidia-l4 --no-cpu-throttling
#   --min-instances=${MIN:-0} --ingress=internal
#
# DRY-BY-DEFAULT / RICK-GATED:
#   With no flags this script is a DRY RUN — it prints the build, push,
#   and `gcloud run deploy` commands it WOULD execute and exits 0 without
#   touching GCP. The real build+push+deploy is gated behind an explicit
#   --apply (or APPLY=1) AND valid GCP credentials. This lets the script
#   be authored, shellcheck'd, and dry-validated with no creds, while the
#   irreversible deploy stays Rick-gated.
#
# Usage:
#   ./src/scripts/cloud-run-model-server-deploy.sh [version] [--apply]
#
# Arguments:
#   version   - Image version tag (default: latest)
#   --apply   - Actually build, push, and deploy (default: dry run)
#
# Environment overrides (see cloud-run-model-server.env.example):
#   MIN                 - min-instances (default: 0 → scale-to-zero)
#   MS_SECRET_NAME      - Secret Manager secret holding the ck_live_* key
#                         (default: lupin-notification-api-key)
#   MS_MEMORY / MS_CPU  - container limits (default: 32Gi / 8)
#   MS_PORT             - container port (default: 7998)
#   MS_INGRESS          - ingress mode (default: internal)
#
# Design of record:
#   src/rnd/2026.06.30-gpu-model-server-cloud-run-split/01-design.md
#   src/rnd/v0.1.7/2026.05.16-model-server-carveout/01-design.md
#
# Examples:
#   # Dry run (no creds needed) — prints what it would do:
#   ./src/scripts/cloud-run-model-server-deploy.sh
#
#   # Real deploy (needs GCP creds + LUPIN_GCP_PROJECT_ID):
#   ./src/scripts/cloud-run-model-server-deploy.sh 0.1.0 --apply
#
#   # Keep one warm instance instead of scaling to zero:
#   MIN=1 ./src/scripts/cloud-run-model-server-deploy.sh 0.1.0 --apply
#################################################################

set -euo pipefail

# --- Parse args ------------------------------------------------------------
IMAGE_VERSION="latest"
APPLY="${APPLY:-0}"
for arg in "$@"; do
    case "$arg" in
        --apply) APPLY="1" ;;
        --dry-run) APPLY="0" ;;
        -*) echo "❌ ERROR: unknown flag '$arg'"; exit 1 ;;
        *)  IMAGE_VERSION="$arg" ;;
    esac
done

# --- Shared GCP config -----------------------------------------------------
# Resolves PROJECT_ID / REGION / REGISTRY / AR_REPO and FAILS LOUD if
# LUPIN_GCP_PROJECT_ID is unset (no sandbox default can leak into a deploy).
_SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]:-$0}" )" && pwd )"
# shellcheck source=src/scripts/cloud-run-config.sh disable=SC1091
source "$_SCRIPT_DIR/cloud-run-config.sh"

# Optional model-server-specific overrides, sourced AFTER the shared config
# so they can layer on top. Git-ignored; copy from the .env.example sibling.
_MS_ENV_FILE="$_SCRIPT_DIR/cloud-run-model-server.env"
# shellcheck source=/dev/null
[ -f "$_MS_ENV_FILE" ] && source "$_MS_ENV_FILE"

# --- Model-server deployment parameters ------------------------------------
SERVICE_NAME="lupin-model-server"
DOCKERFILE="docker/lupin-model-server/Dockerfile"
IMAGE_PATH="$REGISTRY/$PROJECT_ID/$AR_REPO/lupin-model-server:$IMAGE_VERSION"

MIN="${MIN:-0}"                                   # min-instances → 0 = scale-to-zero
MS_MEMORY="${MS_MEMORY:-32Gi}"
MS_CPU="${MS_CPU:-8}"
MS_PORT="${MS_PORT:-7998}"
MS_TIMEOUT="${MS_TIMEOUT:-300}"
MS_INGRESS="${MS_INGRESS:-internal}"
MS_SECRET_NAME="${MS_SECRET_NAME:-lupin-notification-api-key}"

# Model identifiers baked into the image; passed as env so a redeploy can
# repoint without a rebuild. Defaults match docker-compose.cloud-test.yml.
MS_DEVICE="${LUPIN_MODEL_SERVER_DEVICE:-cuda:0}"
MS_WHISPER_ID="${LUPIN_MODEL_SERVER_WHISPER_ID:-distil-whisper/distil-large-v3}"
MS_CODE_EMBED="${LUPIN_MODEL_SERVER_CODE_EMBED:-nomic-ai/CodeRankEmbed}"
MS_PROSE_EMBED="${LUPIN_MODEL_SERVER_PROSE_EMBED:-nomic-ai/nomic-embed-text-v1.5}"
MS_API_KEY_NAME="${LUPIN_MODEL_SERVER_API_KEY_NAME:-notification-api-claude-code-dev}"

# Comma-joined env-var string for `gcloud run deploy --set-env-vars`.
MS_ENV_VARS="LUPIN_MODEL_SERVER_DEVICE=$MS_DEVICE"
MS_ENV_VARS="$MS_ENV_VARS,LUPIN_MODEL_SERVER_PORT=$MS_PORT"
MS_ENV_VARS="$MS_ENV_VARS,LUPIN_MODEL_SERVER_WHISPER_ID=$MS_WHISPER_ID"
MS_ENV_VARS="$MS_ENV_VARS,LUPIN_MODEL_SERVER_CODE_EMBED=$MS_CODE_EMBED"
MS_ENV_VARS="$MS_ENV_VARS,LUPIN_MODEL_SERVER_PROSE_EMBED=$MS_PROSE_EMBED"
MS_ENV_VARS="$MS_ENV_VARS,LUPIN_MODEL_SERVER_API_KEY_NAME=$MS_API_KEY_NAME"

echo "================================================================"
echo "  Lupin Model Server — Cloud Run GPU Deployment"
echo "================================================================"
echo ""
echo "Mode:          $( [ "$APPLY" = "1" ] && echo 'APPLY (live build+push+deploy)' || echo 'DRY RUN (no GCP calls)' )"
echo "Project ID:    $PROJECT_ID"
echo "Region:        $REGION"
echo "Service Name:  $SERVICE_NAME"
echo "Image:         $IMAGE_PATH"
echo "Dockerfile:    $DOCKERFILE"
echo "Port:          $MS_PORT"
echo "Memory / CPU:  $MS_MEMORY / $MS_CPU"
echo "GPU:           1 × nvidia-l4"
echo "min-instances: $MIN   (0 = scale-to-zero)"
echo "max-instances: 1"
echo "Ingress:       $MS_INGRESS"
echo "Secret:        $MS_SECRET_NAME"
echo ""

# --- Build the gcloud run deploy argument vector ---------------------------
# Built as an array so the dry-run print and the live call are identical and
# each argument is correctly word-split-safe.
DEPLOY_ARGS=(
    run deploy "$SERVICE_NAME"
    --project="$PROJECT_ID"
    --region="$REGION"
    --image="$IMAGE_PATH"
    --platform=managed
    --port="$MS_PORT"
    --memory="$MS_MEMORY"
    --cpu="$MS_CPU"
    --gpu=1
    --accelerator=nvidia-l4
    --no-cpu-throttling
    --min-instances="$MIN"
    --max-instances=1
    --ingress="$MS_INGRESS"
    --no-gpu-zonal-redundancy
    --timeout="$MS_TIMEOUT"
    --set-secrets="/secrets/$MS_API_KEY_NAME=$MS_SECRET_NAME:latest"
    --set-env-vars="$MS_ENV_VARS"
)

if [ "$APPLY" != "1" ]; then
    echo "[DRY RUN] Would secret-scan the build context, then run:"
    echo ""
    echo "  ./src/scripts/secret-scan-gate.sh ."
    echo ""
    echo "  docker build -f $DOCKERFILE -t $IMAGE_PATH ."
    echo ""
    echo "  docker push $IMAGE_PATH"
    echo ""
    echo "  gcloud ${DEPLOY_ARGS[*]}"
    echo ""
    echo "Re-run with --apply (and valid GCP creds) to execute."
    echo "NOTE: --accelerator=nvidia-l4 is per the design spec; confirm the exact"
    echo "      gcloud flag name (some releases use --gpu-type=nvidia-l4) at deploy."
    exit 0
fi

# --- APPLY path (Rick-gated; requires GCP creds) ---------------------------
if [ ! -f "$DOCKERFILE" ]; then
    echo "❌ ERROR: Dockerfile not found at $DOCKERFILE"
    exit 1
fi

echo "[0/4] Secret-scan gate (abort if any plaintext key in build context)..."
"$_SCRIPT_DIR/secret-scan-gate.sh" .
echo ""

echo "[1/4] Building model-server image..."
docker build -f "$DOCKERFILE" -t "$IMAGE_PATH" .
echo "✓ Image built"
echo ""

echo "[2/4] Pushing image to Artifact Registry..."
docker push "$IMAGE_PATH"
echo "✓ Image pushed"
echo ""

echo "[3/4] Verifying Secret Manager secret exists..."
if ! gcloud secrets describe "$MS_SECRET_NAME" --project="$PROJECT_ID" > /dev/null 2>&1; then
    echo "❌ ERROR: Secret '$MS_SECRET_NAME' not found in project $PROJECT_ID"
    echo "Run ./src/scripts/cloud-run-setup-secrets.sh first"
    exit 1
fi
echo "✓ Secret found"
echo ""

echo "[4/4] Deploying to Cloud Run (GPU)..."
gcloud "${DEPLOY_ARGS[@]}"
echo ""
echo "✓ Deployment complete"
echo ""

# --- Emit the service URL for LUPIN_MODEL_SERVER_URL -----------------------
SERVICE_URL="$( gcloud run services describe "$SERVICE_NAME" \
    --region="$REGION" --project="$PROJECT_ID" \
    --format='value(status.url)' )"

echo "================================================================"
echo "  ✅ Model server deployed"
echo "================================================================"
echo ""
echo "Service URL: $SERVICE_URL"
echo ""
echo "Point the app at it via the env override (no INI edit needed):"
echo "  export LUPIN_MODEL_SERVER_URL=$SERVICE_URL"
echo ""
echo "Or in docker-compose.cloud-gpu.yml set:"
echo "  LUPIN_MODEL_SERVER_URL: $SERVICE_URL"
echo ""
echo "Health check (with creds; never in committed tests):"
echo "  gcloud run services proxy $SERVICE_NAME --region=$REGION  # then GET /health"
echo ""
