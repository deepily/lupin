#!/bin/bash
#################################################################
# cloud-run-build.sh
#
# Purpose: Build and push multi-environment Docker image to GCR
# Usage: ./src/scripts/cloud-run-build.sh [version]
#
# Arguments:
#   version - Image version tag (default: latest)
#
# This build produces a MULTI-ENVIRONMENT CAPABLE image. The same
# image can be deployed to development, testing, or production by
# overriding the LUPIN_CONFIG_MGR_CLI_ARGS environment variable
# at runtime (set by the deployer; the monolith cloud-run-deploy.sh
# path was retired 2026-07-11 — deploy via terraform src/terraform/envs/test).
#
# No environment-specific configuration is baked into the image!
#
# Example:
#   ./src/scripts/cloud-run-build.sh latest
#   ./src/scripts/cloud-run-build.sh v1.0.0
#################################################################

set -e  # Exit on any error

# Configuration — PROJECT_ID / REGION / REGISTRY / AR_REPO from the shared
# resolver, which fails loud if LUPIN_GCP_PROJECT_ID is unset.
source "$( dirname "$0" )/cloud-run-config.sh"
IMAGE_NAME="lupin"
VERSION="${1:-latest}"
DOCKERFILE="docker/lupin/Dockerfile"

echo "================================================================"
echo "  Lupin Cloud Run - Docker Build & Push"
echo "================================================================"
echo ""
echo "Project ID: $PROJECT_ID"
echo "Image Name: $IMAGE_NAME"
echo "Version: $VERSION"
echo "Dockerfile: $DOCKERFILE"
echo ""

# Check if Dockerfile exists
if [ ! -f "$DOCKERFILE" ]; then
    echo "❌ ERROR: Dockerfile not found at $DOCKERFILE"
    exit 1
fi

echo "✓ Dockerfile found"
echo ""

# HARD GATE: abort the build if any secret is detected in the build context
# (Phase-1 secret hygiene, D8). Must run BEFORE docker build so no image
# carrying a plaintext key can ever be built or pushed.
echo "[0/3] Secret-scan gate..."
"$( dirname "$0" )/secret-scan-gate.sh" .
echo ""

# Build Docker image
echo "[1/3] Building Docker image..."
echo "Image tag: $REGISTRY/$PROJECT_ID/$AR_REPO/$IMAGE_NAME:$VERSION"
echo ""

docker build \
    -f $DOCKERFILE \
    -t $REGISTRY/$PROJECT_ID/$AR_REPO/$IMAGE_NAME:$VERSION \
    .

echo ""
echo "✓ Docker image built successfully"
echo ""

# Optional: Test image locally
read -p "Do you want to test the image locally before pushing? (y/n) " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo ""
    echo "[2/3] Testing Docker image locally..."
    echo "Starting container on port 8080 (press Ctrl+C to stop after testing)"
    echo ""
    echo "In another terminal, run: curl http://localhost:8080/health"
    echo ""

    docker run -p 8080:8080 \
        -e PORT=8080 \
        -e LUPIN_ROOT=/var/lupin \
        $REGISTRY/$PROJECT_ID/$AR_REPO/$IMAGE_NAME:$VERSION

    echo ""
else
    echo "Skipping local test"
    echo ""
fi

# Push to GCR
echo "[3/3] Pushing image to Google Container Registry..."
echo ""

docker push $REGISTRY/$PROJECT_ID/$AR_REPO/$IMAGE_NAME:$VERSION

echo ""
echo "✓ Image pushed successfully"
echo ""

# Tag as latest if this is a version build
if [ "$VERSION" != "latest" ]; then
    read -p "Also tag as 'latest'? (y/n) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Tagging as latest..."
        docker tag $REGISTRY/$PROJECT_ID/$AR_REPO/$IMAGE_NAME:$VERSION $REGISTRY/$PROJECT_ID/$AR_REPO/$IMAGE_NAME:latest
        docker push $REGISTRY/$PROJECT_ID/$AR_REPO/$IMAGE_NAME:latest
        echo "✓ Tagged and pushed as latest"
    fi
fi

echo ""
echo "================================================================"
echo "  ✅ Build and push complete!"
echo "================================================================"
echo ""
echo "Image details:"
echo "  Registry: $REGISTRY"
echo "  Project: $PROJECT_ID"
echo "  Image: $IMAGE_NAME"
echo "  Tag: $VERSION"
echo "  Full path: $REGISTRY/$PROJECT_ID/$AR_REPO/$IMAGE_NAME:$VERSION"
echo ""
echo "This image is MULTI-ENVIRONMENT CAPABLE (config selected at runtime via"
echo "LUPIN_CONFIG_MGR_CLI_ARGS). The monolith cloud-run-deploy.sh path is RETIRED"
echo "(2026-07-11) — deploy via terraform: src/terraform/envs/test."
echo ""
echo "Configuration is selected at runtime via environment variables."
echo ""
