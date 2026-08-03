#!/bin/bash
#################################################################
# cloud-run-setup-secrets.sh
#
# Purpose: Seed a GCP Secret Manager secret from a local key file
#          and grant the Cloud Run service account read access.
#
# Usage: ./src/scripts/cloud-run-setup-secrets.sh
#          [--secret-name <id>] [--key-file <path>]
#
# Defaults preserve the original behaviour (lupin-notification-api-key
# from the notifications key file).
#
# ⚠️ WHY THESE ARE PARAMETERS NOW (rows 574fd1dc / 6cc52525, 2026-07-28)
#   They used to be hardcoded, and THAT HARDCODING WAS THE COUPLING.
#   This script published `notification-api-claude-code-dev` — a key whose
#   authority is a PER-DEPLOYMENT `api_keys` table — as a GLOBAL secret that
#   Cloud Run mounts and bcrypt-hashes at boot. One file, two authorities:
#     - Lupin's own API  -> validated against THAT SERVER'S database
#     - model server     -> validated against ONE mounted secret version
#   The correct value differs per host for the first and is identical
#   everywhere for the second. On the dev box they coincide by accident, so
#   the flaw was invisible there; on the VM they cannot, and
#   /embeddings/generate returned 100% 401 for ~38h.
#   Full analysis: src/rnd/v0.1.9/2026.07.28-model-server-api-key-decoupling.md
#
# ⚠️ ORDER MATTERS WHEN ROTATING. The model server hashes its key at BOOT:
#     1. this script (add the new secret version)
#     2. terraform apply with the new api_key_secret_version  <- re-hash
#     3. ONLY THEN distribute the key file to caller hosts
#   Reversing 2 and 3 401s every caller until instances recycle.
#################################################################

set -e  # Exit on any error

# Configuration — PROJECT_ID / REGION from the shared resolver (fail-loud).
source "$( dirname "$0" )/cloud-run-config.sh"
SECRET_NAME="lupin-notification-api-key"
KEY_FILE="src/conf/keys/notification-api-claude-code-dev"

while [ $# -gt 0 ]; do
    case "$1" in
        --secret-name) SECRET_NAME="$2"; shift 2 ;;
        --key-file)    KEY_FILE="$2";    shift 2 ;;
        -h|--help)
            sed -n '3,32p' "$0"
            exit 0 ;;
        *)
            echo "❌ ERROR: unknown argument '$1'" >&2
            echo "Usage: $0 [--secret-name <id>] [--key-file <path>]" >&2
            exit 2 ;;
    esac
done

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

# FINGERPRINT PARITY — the check that would have diagnosed 574fd1dc in one step.
#
# ⚠️ THE PREDICATE IS STATED BECAUSE IT IS LOAD-BEARING: sha256 of the STRIPPED
# value. The model server fingerprints `f.read().strip()` (main.py:157) and the
# client reads via du.get_api_key() which also strips (util.py:754). Measured
# 2026-07-28: hashing the notifications key RAW gives 26f45dbc7276 while the
# same key STRIPPED gives 26e3c096d4df — the file carries a trailing newline.
# Comparing a raw fingerprint to a stripped one manufactures a discrepancy that
# does not exist, and nearly did during the 574fd1dc investigation.
#
# This is deliberately IN THE SCRIPT rather than left to an operator one-liner:
# the one-liner is where the predicate gets chosen wrong.
_fp_local="$(  python3 -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1]).read().strip().encode()).hexdigest()[:12])" "$KEY_FILE" )"
_fp_remote="$( gcloud secrets versions access latest --secret="$SECRET_NAME" --project="$PROJECT_ID" 2>/dev/null \
               | python3 -c "import hashlib,sys; print(hashlib.sha256(sys.stdin.read().strip().encode()).hexdigest()[:12])" )"

echo "Fingerprint parity (sha256 of the STRIPPED value, first 12):"
echo "  local  $KEY_FILE : $_fp_local"
echo "  secret $SECRET_NAME (latest)     : $_fp_remote"
if [ "$_fp_local" = "$_fp_remote" ]; then
    echo "  ✓ MATCH — the mounted secret and the local key are the same credential"
else
    echo "  ❌ MISMATCH — the secret does NOT hold this key file's value"
    echo "     Do NOT deploy against this. A mounted key that differs from the"
    echo "     caller's is exactly bug 574fd1dc: every request 401s for the"
    echo "     instance's entire life while the boot log still reads healthy."
    exit 1
fi
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
echo "  Key file: $KEY_FILE"
echo ""
# ⚠️ These two lines used to be HARDCODED and became wrong the moment the script
# was parameterized: they named /secrets/notification-api-key as "the" mount path
# and cloud-run-build.sh as "the" next step, for any secret. The mount path is
# owned by Terraform (modules/cloud-run-model-server: {keys_dir}/{api_key_name}),
# not by this script — printing a literal here would be a second authority.
echo "The MOUNT PATH is Terraform's, not this script's:"
echo "  modules/cloud-run-model-server mounts it at {keys_dir}/{api_key_name}."
echo ""
echo "⚠️ NEXT STEP — ORDER MATTERS (the model server hashes its key at BOOT):"
echo "  1. (done) this script added the secret version"
echo "  2. terraform apply with the new api_key_secret_version  <- instances re-hash"
echo "  3. ONLY THEN distribute $KEY_FILE to caller hosts"
echo ""
echo "  Doing 3 before 2 401s every caller until instances recycle — bug 574fd1dc."
echo ""
