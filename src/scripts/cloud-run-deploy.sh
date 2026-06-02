#!/bin/bash
#################################################################
# cloud-run-deploy.sh
#
# Purpose: Deploy Lupin to Google Cloud Run with runtime config selection
# Usage: ./src/scripts/cloud-run-deploy.sh [version] [port] [environment]
#
# Arguments:
#   version     - Image version tag (default: latest)
#   port        - Port to expose (default: 8080, Cloud Run standard)
#   environment - Configuration environment: testing|production (default: testing)
#
# Environment Configs:
#   testing    - Uses [Lupin: Testing-GCS] with gs://lupin-lancedb-test/
#   production - Uses [Lupin: Production] with gs://lupin-lancedb-prod/
#
# Prerequisites (for GCS backends):
#   1. GCS bucket must exist:
#      - Testing: gs://lupin-lancedb-test/
#      - Production: gs://lupin-lancedb-prod/
#   2. Cloud Run service account must have permissions:
#      - roles/storage.objectViewer (read)
#      - roles/storage.objectCreator (write)
#   3. Grant permissions (use gcloud storage, NOT gsutil to avoid Python env conflicts):
#      PROJECT_NUMBER=$(gcloud projects describe "$LUPIN_GCP_PROJECT_ID" --format='value(projectNumber)')
#      SERVICE_ACCOUNT="$PROJECT_NUMBER-compute@developer.gserviceaccount.com"
#      gcloud storage buckets add-iam-policy-binding gs://lupin-lancedb-test \
#        --member="serviceAccount:$SERVICE_ACCOUNT" \
#        --role="roles/storage.objectViewer"
#      gcloud storage buckets add-iam-policy-binding gs://lupin-lancedb-test \
#        --member="serviceAccount:$SERVICE_ACCOUNT" \
#        --role="roles/storage.objectCreator"
#
# Examples:
#   # Deploy to testing environment (default)
#   ./src/scripts/cloud-run-deploy.sh latest 8080 testing
#
#   # Deploy to production environment
#   ./src/scripts/cloud-run-deploy.sh v1.0.0 8080 production
#
#   # Deploy with defaults (latest, 8080, testing)
#   ./src/scripts/cloud-run-deploy.sh
#################################################################

set -e  # Exit on any error

# Configuration — PROJECT_ID / REGION / REGISTRY / AR_REPO resolved by the
# shared resolver, which fails loud if LUPIN_GCP_PROJECT_ID is unset.
source "$( dirname "$0" )/cloud-run-config.sh"
SERVICE_NAME="lupin"
IMAGE_VERSION="${1:-latest}"
PORT="${2:-8080}"
ENVIRONMENT="${3:-testing}"
MEMORY="2Gi"
CPU="1"
TIMEOUT="300"
SECRET_NAME="lupin-notification-api-key"

# Map environment to config block
case "$ENVIRONMENT" in
    testing)
        CONFIG_BLOCK="Lupin:+Testing-GCS"
        LUPIN_ENV="testing"
        ;;
    production)
        CONFIG_BLOCK="Lupin:+Production"
        LUPIN_ENV="production"
        ;;
    *)
        echo "❌ ERROR: Invalid environment '$ENVIRONMENT'"
        echo "Valid options: testing, production"
        exit 1
        ;;
esac

# Build ConfigurationManager CLI args
CONFIG_MGR_ARGS="config_path=/var/lupin/src/conf/lupin-app.ini splainer_path=/var/lupin/src/conf/lupin-app-splainer.ini config_block_id=$CONFIG_BLOCK"

echo "================================================================"
echo "  Lupin Cloud Run - Deployment"
echo "================================================================"
echo ""
echo "Project ID: $PROJECT_ID"
echo "Region: $REGION"
echo "Service Name: $SERVICE_NAME"
echo "Image Version: $IMAGE_VERSION"
echo "Environment: $ENVIRONMENT"
echo "Config Block: $CONFIG_BLOCK"
echo "Port: $PORT"
echo "Memory: $MEMORY"
echo "CPU: $CPU"
echo "Timeout: ${TIMEOUT}s"
echo ""

# Verify image exists
echo "[1/3] Verifying Docker image exists..."
if ! gcloud artifacts docker images describe $REGISTRY/$PROJECT_ID/$AR_REPO/lupin:$IMAGE_VERSION > /dev/null 2>&1; then
    echo "❌ ERROR: Image $REGISTRY/$PROJECT_ID/$AR_REPO/lupin:$IMAGE_VERSION not found"
    echo "Run ./src/scripts/cloud-run-build.sh first"
    exit 1
fi
echo "✓ Image found in Artifact Registry"
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
echo "  • Image: $REGISTRY/$PROJECT_ID/$AR_REPO/lupin:$IMAGE_VERSION"
echo "  • Port: $PORT"
echo "  • Memory: $MEMORY, CPU: $CPU"
echo "  • Secret mount: /secrets/notification-api-key"
echo "  • Environment: LUPIN_ROOT=/var/lupin, LUPIN_ENV=$LUPIN_ENV"
echo "  • Config Block: $CONFIG_BLOCK"
echo "  • ConfigManager Args: $CONFIG_MGR_ARGS"
echo ""

gcloud run deploy $SERVICE_NAME \
    --project=$PROJECT_ID \
    --region=$REGION \
    --image=$REGISTRY/$PROJECT_ID/$AR_REPO/lupin:$IMAGE_VERSION \
    --platform=managed \
    --allow-unauthenticated \
    --port=$PORT \
    --memory=$MEMORY \
    --cpu=$CPU \
    --timeout=$TIMEOUT \
    --min-instances=1 \
    --max-instances=1 \
    --set-secrets="/secrets/notification-api-key=$SECRET_NAME:latest" \
    --set-env-vars="LUPIN_ROOT=/var/lupin,LUPIN_ENV=$LUPIN_ENV,LUPIN_CONFIG_MGR_CLI_ARGS=$CONFIG_MGR_ARGS"

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
echo "1. Update ~/.lupin/config with $ENVIRONMENT URL:"
echo "   [$ENVIRONMENT]"
echo "   api_url = $SERVICE_URL"
echo ""
echo "2. Test the deployment:"
echo "   ./src/scripts/cloud-run-validate.sh $SERVICE_URL"
echo ""
echo "3. View logs:"
echo "   gcloud run services logs read $SERVICE_NAME --region=$REGION --project=$PROJECT_ID --limit=50"
echo ""
echo "4. Verify config block is loaded correctly:"
echo "   curl $SERVICE_URL/health"
echo "   # Check logs for: 'Config block: $CONFIG_BLOCK'"
echo ""
