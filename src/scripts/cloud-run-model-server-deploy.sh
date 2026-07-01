#!/bin/bash
#################################################################
# cloud-run-model-server-deploy.sh
#
# Purpose: Build the lupin-model-server GPU image and push it to
#          Artifact Registry. This is the IMAGE-DELIVERY half of the
#          GPU model-server → Cloud Run split; it does NOT create or
#          mutate the Cloud Run service.
#
# SINGLE DEPLOY AUTHORITY (finding #4, 2026-07-01):
#   Terraform OWNS the Cloud Run service. ALL service configuration —
#   GPU/accelerator, min/max instances, ingress, Direct VPC egress,
#   the Secret Manager file-mount + KEYS_DIR, and the scheduled
#   warm/cool jobs — lives in src/terraform/modules/cloud-run-model-server
#   (wired by src/terraform/envs/test). This script's ONLY job is to
#   build the image + push it to Artifact Registry so `terraform apply`
#   has an image to deploy.
#
#   Earlier this script ALSO ran `gcloud run deploy`, creating TWO
#   divergent authorities for one service (state drift, and a secret
#   mount path that diverged from the app's {KEYS_DIR}/{API_KEY_NAME}
#   → 503 on every authed request — finding #3). That deploy step is
#   removed; Terraform's config (which already mounts the secret at the
#   path the app reads) is the sole authority.
#
# DEPLOY FLOW (two distinct, separately-gated steps):
#   1. THIS script: build + push image → Artifact Registry.
#   2. Rick (real-money, GCP login): cd src/terraform/envs/test &&
#      terraform apply -var model_server_image_tag=<tag-or-digest>,
#      then read the service URL from `terraform output service_url`
#      and wire it into LUPIN_MODEL_SERVER_URL (docker-compose.cloud-gpu.yml).
#
# DRY-BY-DEFAULT / RICK-GATED:
#   With no flags this script is a DRY RUN — it prints the secret-scan,
#   build, and push commands it WOULD execute and exits 0 without
#   touching GCP. The real build+push is gated behind an explicit
#   --apply (or APPLY=1) AND valid GCP credentials. `terraform apply`
#   (the irreversible, real-money deploy) is a SEPARATE Rick-run step.
#
# Usage:
#   ./src/scripts/cloud-run-model-server-deploy.sh [version] [--apply]
#
# Arguments:
#   version   - Image version tag (default: latest). Prefer a real
#               version (e.g. 0.1.0) over `latest`; for a reproducible
#               deploy, pin by the pushed digest at `terraform apply`
#               (this script prints the digest after push). See the
#               design doc's apply runbook.
#   --apply   - Actually build + push (default: dry run).
#
# Environment overrides:
#   PROJECT_ID / REGION / REGISTRY / AR_REPO come from the shared
#   cloud-run.env via cloud-run-config.sh. Service configuration is
#   NO LONGER script env — it is Terraform's (see
#   src/terraform/modules/cloud-run-model-server/variables.tf).
#
# Design of record:
#   src/rnd/2026.06.30-gpu-model-server-cloud-run-split/01-design.md
#   src/rnd/v0.1.7/2026.05.16-model-server-carveout/01-design.md
#
# Examples:
#   # Dry run (no creds needed) — prints what it would do:
#   ./src/scripts/cloud-run-model-server-deploy.sh
#
#   # Real build + push (needs GCP creds + LUPIN_GCP_PROJECT_ID):
#   ./src/scripts/cloud-run-model-server-deploy.sh 0.1.0 --apply
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

# --- Image-build parameters ------------------------------------------------
SERVICE_NAME="lupin-model-server"
DOCKERFILE="docker/lupin-model-server/Dockerfile"
IMAGE_PATH="$REGISTRY/$PROJECT_ID/$AR_REPO/lupin-model-server:$IMAGE_VERSION"

echo "================================================================"
echo "  Lupin Model Server — image build + push (Artifact Registry)"
echo "================================================================"
echo ""
echo "Mode:          $( [ "$APPLY" = "1" ] && echo 'APPLY (live build+push)' || echo 'DRY RUN (no GCP calls)' )"
echo "Project ID:    $PROJECT_ID"
echo "Region:        $REGION"
echo "Service Name:  $SERVICE_NAME   (created + configured by Terraform, not this script)"
echo "Image:         $IMAGE_PATH"
echo "Dockerfile:    $DOCKERFILE"
echo ""
echo "Service config (GPU, ingress, secret mount + KEYS_DIR, scaling, schedule)"
echo "is owned by Terraform: src/terraform/modules/cloud-run-model-server (envs/test)."
echo ""

if [ "$APPLY" != "1" ]; then
    echo "[DRY RUN] Would secret-scan the build context, then build + push:"
    echo ""
    echo "  ./src/scripts/secret-scan-gate.sh ."
    echo ""
    echo "  docker build -f $DOCKERFILE -t $IMAGE_PATH ."
    echo ""
    echo "  docker push $IMAGE_PATH"
    echo ""
    echo "Then deploy via Terraform (SEPARATE Rick-gated, real-money step):"
    echo ""
    echo "  cd src/terraform/envs/test"
    echo "  terraform apply -var project_id=<PROJECT> -var model_server_image_tag=$IMAGE_VERSION"
    echo "  terraform output -raw service_url    # → LUPIN_MODEL_SERVER_URL"
    echo ""
    echo "Re-run with --apply (and valid GCP creds) to build + push."
    exit 0
fi

# --- APPLY path (Rick-gated; requires GCP creds for the AR push) -----------
if [ ! -f "$DOCKERFILE" ]; then
    echo "❌ ERROR: Dockerfile not found at $DOCKERFILE"
    exit 1
fi

echo "[0/3] Secret-scan gate (abort if any plaintext key in build context)..."
"$_SCRIPT_DIR/secret-scan-gate.sh" .
echo ""

echo "[1/3] Building model-server image..."
docker build -f "$DOCKERFILE" -t "$IMAGE_PATH" .
echo "✓ Image built"
echo ""

echo "[2/3] Pushing image to Artifact Registry..."
docker push "$IMAGE_PATH"
echo "✓ Image pushed"
echo ""

echo "[3/3] Resolving pushed image digest (for a reproducible, digest-pinned apply)..."
IMAGE_DIGEST="$( docker inspect --format='{{index .RepoDigests 0}}' "$IMAGE_PATH" 2>/dev/null || true )"
if [ -n "$IMAGE_DIGEST" ]; then
    echo "✓ Digest: $IMAGE_DIGEST"
else
    echo "⚠ Could not resolve a RepoDigest (push metadata unavailable) — pin manually."
fi
echo ""

echo "================================================================"
echo "  ✅ Image built + pushed — Terraform now owns the deploy"
echo "================================================================"
echo ""
echo "Next (SEPARATE, Rick-gated, real-money step — Terraform owns the service):"
echo ""
echo "  cd src/terraform/envs/test"
echo "  terraform apply -var project_id=<PROJECT> \\"
echo "      -var model_server_image_tag=$IMAGE_VERSION"
echo ""
echo "For a reproducible deploy, pin by digest instead of the mutable tag"
echo "(set the module 'image' input to the full ref below):"
if [ -n "$IMAGE_DIGEST" ]; then
    echo "      $IMAGE_DIGEST"
fi
echo ""
echo "After apply, read the service URL and wire it into the app:"
echo "  terraform output -raw service_url    # → LUPIN_MODEL_SERVER_URL"
echo "  # docker-compose.cloud-gpu.yml: LUPIN_MODEL_SERVER_URL=<that url>"
echo ""
echo "Health check (with creds; never in committed tests):"
echo "  gcloud run services proxy $SERVICE_NAME --region=$REGION  # then GET /health"
echo ""
