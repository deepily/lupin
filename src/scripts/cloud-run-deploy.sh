#!/bin/bash
#################################################################
# cloud-run-deploy.sh
#
# Purpose: Deploy Lupin to Google Cloud Run
# Usage: ./src/scripts/cloud-run-deploy.sh [version] [port]
#
# Arguments:
#   version - Image version tag (default: latest)
#   port - Port to expose (default: 8080, Cloud Run standard)
#
# Example:
#   ./src/scripts/cloud-run-deploy.sh latest 8080
#   ./src/scripts/cloud-run-deploy.sh v1.0.0 7999
#################################################################

set -e  # Exit on any error

# Configuration
PROJECT_ID="hello-world-foo-423219"
REGION="us-central1"
SERVICE_NAME="lupin"
IMAGE_VERSION="${1:-latest}"
PORT="${2:-8080}"
MEMORY="2Gi"
CPU="1"
TIMEOUT="300"
SECRET_NAME="lupin-notification-api-key"

echo "================================================================"
echo "  Lupin Cloud Run - Deployment"
echo "================================================================"
echo ""
echo "Project ID: $PROJECT_ID"
echo "Region: $REGION"
echo "Service Name: $SERVICE_NAME"
echo "Image Version: $IMAGE_VERSION"
echo "Port: $PORT"
echo "Memory: $MEMORY"
echo "CPU: $CPU"
echo "Timeout: ${TIMEOUT}s"
echo ""

# Verify image exists
echo "[1/3] Verifying Docker image exists..."
if ! gcloud container images describe gcr.io/$PROJECT_ID/lupin:$IMAGE_VERSION --project=$PROJECT_ID > /dev/null 2>&1; then
    echo "❌ ERROR: Image gcr.io/$PROJECT_ID/lupin:$IMAGE_VERSION not found"
    echo "Run ./src/scripts/cloud-run-build.sh first"
    exit 1
fi
echo "✓ Image found in GCR"
echo ""

# Verify secret exists
echo "[2/3] Verifying secret exists..."
if ! gcloud secrets describe $SECRET_NAME --project=$PROJECT_ID > /dev/null 2>&1; then
    echo "❌ ERROR: Secret '$SECRET_NAME' not found"
    echo "Run ./src/scripts/cloud-run-setup-secrets.sh first"
    exit 1
fi
echo "✓ Secret found"
echo ""

# Deploy to Cloud Run
echo "[3/3] Deploying to Cloud Run..."
echo ""
echo "Deploying with configuration:"
echo "  • Image: gcr.io/$PROJECT_ID/lupin:$IMAGE_VERSION"
echo "  • Port: $PORT"
echo "  • Memory: $MEMORY, CPU: $CPU"
echo "  • Secret mount: /secrets/notification-api-key"
echo "  • Environment: LUPIN_ROOT=/app, LUPIN_ENV=production"
echo ""

gcloud run deploy $SERVICE_NAME \
    --project=$PROJECT_ID \
    --region=$REGION \
    --image=gcr.io/$PROJECT_ID/lupin:$IMAGE_VERSION \
    --platform=managed \
    --allow-unauthenticated \
    --port=$PORT \
    --memory=$MEMORY \
    --cpu=$CPU \
    --timeout=$TIMEOUT \
    --set-secrets="/secrets/notification-api-key=$SECRET_NAME:latest" \
    --set-env-vars="LUPIN_ROOT=/app,LUPIN_ENV=production"

echo ""
echo "✓ Deployment complete"
echo ""

# Get service URL
echo "================================================================"
echo "  ✅ Deployment successful!"
echo "================================================================"
echo ""
SERVICE_URL=$(gcloud run services describe $SERVICE_NAME --region=$REGION --project=$PROJECT_ID --format='value(status.url)')
echo "Service URL: $SERVICE_URL"
echo ""
echo "Next steps:"
echo ""
echo "1. Update ~/.notifications/config with production URL:"
echo "   [production]"
echo "   api_url = $SERVICE_URL"
echo ""
echo "2. Test the deployment:"
echo "   ./src/scripts/cloud-run-validate.sh $SERVICE_URL"
echo ""
echo "3. View logs:"
echo "   gcloud run services logs read $SERVICE_NAME --region=$REGION --project=$PROJECT_ID --limit=50"
echo ""
