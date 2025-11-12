#!/bin/bash
#################################################################
# cloud-run-build.sh
#
# Purpose: Build and push Docker image to Google Container Registry
# Usage: ./src/scripts/cloud-run-build.sh [version]
#
# Arguments:
#   version - Image version tag (default: latest)
#
# Example:
#   ./src/scripts/cloud-run-build.sh latest
#   ./src/scripts/cloud-run-build.sh v1.0.0
#################################################################

set -e  # Exit on any error

# Configuration
PROJECT_ID="hello-world-foo-423219"
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

# Build Docker image
echo "[1/3] Building Docker image..."
echo "Image tag: gcr.io/$PROJECT_ID/$IMAGE_NAME:$VERSION"
echo ""

docker build \
    -f $DOCKERFILE \
    -t gcr.io/$PROJECT_ID/$IMAGE_NAME:$VERSION \
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
        -e LUPIN_ROOT=/app \
        gcr.io/$PROJECT_ID/$IMAGE_NAME:$VERSION

    echo ""
else
    echo "Skipping local test"
    echo ""
fi

# Push to GCR
echo "[3/3] Pushing image to Google Container Registry..."
echo ""

docker push gcr.io/$PROJECT_ID/$IMAGE_NAME:$VERSION

echo ""
echo "✓ Image pushed successfully"
echo ""

# Tag as latest if this is a version build
if [ "$VERSION" != "latest" ]; then
    read -p "Also tag as 'latest'? (y/n) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Tagging as latest..."
        docker tag gcr.io/$PROJECT_ID/$IMAGE_NAME:$VERSION gcr.io/$PROJECT_ID/$IMAGE_NAME:latest
        docker push gcr.io/$PROJECT_ID/$IMAGE_NAME:latest
        echo "✓ Tagged and pushed as latest"
    fi
fi

echo ""
echo "================================================================"
echo "  ✅ Build and push complete!"
echo "================================================================"
echo ""
echo "Image details:"
echo "  Registry: gcr.io"
echo "  Project: $PROJECT_ID"
echo "  Image: $IMAGE_NAME"
echo "  Tag: $VERSION"
echo "  Full path: gcr.io/$PROJECT_ID/$IMAGE_NAME:$VERSION"
echo ""
echo "Next step: Run ./src/scripts/cloud-run-deploy.sh $VERSION"
echo ""
