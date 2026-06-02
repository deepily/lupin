#!/bin/bash
#################################################################
# cloud-run-setup-secrets.sh
#
# Purpose: Create GCP secrets for Cloud Run deployment
# Usage: ./src/scripts/cloud-run-setup-secrets.sh
#
# Creates lupin-notification-api-key secret in GCP Secret Manager
# and grants Cloud Run service account access to read it.
#################################################################

set -e  # Exit on any error

# Configuration — PROJECT_ID / REGION from the shared resolver (fail-loud).
source "$( dirname "$0" )/cloud-run-config.sh"
SECRET_NAME="lupin-notification-api-key"
KEY_FILE="src/conf/keys/notification-api-claude-code-dev"

echo "================================================================"
echo "  Lupin Cloud Run - Secret Setup"
echo "================================================================"
echo ""
echo "Project ID: $PROJECT_ID"
echo "Secret Name: $SECRET_NAME"
echo "Key File: $KEY_FILE"
echo ""

# Check if key file exists
if [ ! -f "$KEY_FILE" ]; then
    echo "❌ ERROR: API key file not found at $KEY_FILE"
    exit 1
fi

echo "✓ API key file found"
echo ""

# Get project number (needed for service account)
echo "[1/4] Getting project number..."
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')
echo "✓ Project number: $PROJECT_NUMBER"
echo ""

# Create secret
echo "[2/4] Creating secret in Secret Manager..."
if gcloud secrets describe $SECRET_NAME --project=$PROJECT_ID > /dev/null 2>&1; then
    echo "⚠️  Secret '$SECRET_NAME' already exists"
    read -p "Do you want to create a new version? (y/n) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        gcloud secrets versions add $SECRET_NAME \
            --project=$PROJECT_ID \
            --data-file=$KEY_FILE
        echo "✓ New secret version created"
    else
        echo "Skipping secret creation"
    fi
else
    gcloud secrets create $SECRET_NAME \
        --project=$PROJECT_ID \
        --data-file=$KEY_FILE \
        --replication-policy="automatic"
    echo "✓ Secret created"
fi
echo ""

# Grant Cloud Run service account access
echo "[3/4] Granting Cloud Run service account access..."
SERVICE_ACCOUNT="$PROJECT_NUMBER-compute@developer.gserviceaccount.com"
echo "Service account: $SERVICE_ACCOUNT"

gcloud secrets add-iam-policy-binding $SECRET_NAME \
    --project=$PROJECT_ID \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/secretmanager.secretAccessor"

echo "✓ Access granted"
echo ""

# Verify secret
echo "[4/4] Verifying secret creation..."
gcloud secrets describe $SECRET_NAME --project=$PROJECT_ID
echo ""
echo "✓ Secret verification complete"
echo ""

echo "================================================================"
echo "  ✅ Secret setup complete!"
echo "================================================================"
echo ""
echo "Secret details:"
echo "  Name: $SECRET_NAME"
echo "  Project: $PROJECT_ID"
echo "  Mount path for Cloud Run: /secrets/notification-api-key"
echo ""
echo "Next step: Run ./src/scripts/cloud-run-build.sh"
echo ""
